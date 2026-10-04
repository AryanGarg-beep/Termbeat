// The browser's stand-in for mpv + cava: an <audio> element for streaming and
// decoding, and a Web Audio AnalyserNode for the spectrum.
//
// Two elements are kept. A spectrum needs the element routed through Web
// Audio, which only works when the stream allows CORS (or the extension holds
// a host permission for it); otherwise Web Audio is handed silence. So a
// station first plays through the analysed element and, if that fails, falls
// back to a plain element and the UI synthesises the spectrum - the same
// fallback the terminal app uses when cava is missing.

export const STATE = {
  STARTING: "CONNECTING", IDLE: "IDLE", BUFFERING: "BUFFERING", PLAYING: "PLAYING",
  PAUSED: "PAUSED", ERROR: "STREAM ERROR",
};

export const NUM_BANDS = 18;
// cava's default cutoffs
const LOW_HZ = 50;
const HIGH_HZ = 10000;
// A live stream paused longer than this is reloaded on resume rather than
// played from a stale buffer.
const STALE_PAUSE_MS = 30000;

export class AudioEngine {
  constructor(onChange) {
    this.onChange = onChange || (() => {});
    this.url = null;
    this.paused = false;
    this.volume = 75;
    this.muted = false;
    this.waiting = false;
    this.failed = false;
    this.error = "";
    this.pausedAt = 0;
    this.analysed = this._makeElement(true);
    this.plain = this._makeElement(false);
    this.active = null;
    this.ctx = null;
    this.analyser = null;
    this.freq = null;
    this.sens = 1.0;
  }

  _makeElement(cors) {
    const el = new Audio();
    el.preload = "none";
    if (cors) el.crossOrigin = "anonymous";
    const mine = () => el === this.active;
    el.addEventListener("waiting", () => { if (mine()) { this.waiting = true; this.onChange(); } });
    el.addEventListener("stalled", () => { if (mine()) { this.waiting = true; this.onChange(); } });
    el.addEventListener("playing", () => {
      if (mine()) { this.waiting = false; this.failed = false; this.error = ""; this.onChange(); }
    });
    el.addEventListener("pause", () => { if (mine()) this.onChange(); });
    el.addEventListener("error", () => {
      if (!mine() || !this.url) return;
      if (cors) {
        // most likely CORS: replay without the analyser
        this._start(this.plain);
        return;
      }
      this.failed = true;
      this.waiting = false;
      this.error = describeMediaError(el.error);
      this.onChange();
    });
    return el;
  }

  _ensureGraph() {
    if (this.ctx) return;
    const Ctx = globalThis.AudioContext || globalThis.webkitAudioContext;
    if (!Ctx) return;
    this.ctx = new Ctx();
    const src = this.ctx.createMediaElementSource(this.analysed);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 4096;
    this.analyser.smoothingTimeConstant = 0.55;
    this.analyser.minDecibels = -90;
    this.analyser.maxDecibels = -20;
    this.gain = this.ctx.createGain();
    // The analyser taps the signal before the volume, as cava taps the sound
    // card: the UI applies its own volume curve to the bars.
    src.connect(this.analyser);
    src.connect(this.gain);
    this.gain.connect(this.ctx.destination);
    this.freq = new Uint8Array(this.analyser.frequencyBinCount);
    this.bandBins = makeBandBins(this.ctx.sampleRate, this.analyser.fftSize, NUM_BANDS);
  }

  _applyVolume() {
    const g = this.muted ? 0 : Math.pow(this.volume / 100, 2);
    this.plain.volume = g;
    if (this.gain) this.gain.gain.value = g;
    this.analysed.volume = 1;
  }

  async _start(el) {
    for (const other of [this.analysed, this.plain]) {
      if (other !== el) { other.pause(); other.removeAttribute("src"); other.load(); }
    }
    this.active = el;
    this.waiting = true;
    this.failed = false;
    this.error = "";
    if (el === this.analysed) {
      try {
        this._ensureGraph();
        if (this.ctx && this.ctx.state !== "running") await this.ctx.resume();
      } catch { /* handled below */ }
      if (!this.ctx || this.ctx.state !== "running") {
        // no running audio graph means the analysed element would be silent
        return this._start(this.plain);
      }
    }
    this._applyVolume();
    el.src = this.url;
    this.onChange();
    if (this.paused) return;
    try {
      await el.play();
    } catch (exc) {
      if (el !== this.active) return;
      if (exc && exc.name === "AbortError") return;      // superseded by a newer load
      if (el === this.analysed) return this._start(this.plain);
      this.failed = true;
      this.waiting = false;
      this.error = exc && exc.name === "NotAllowedError" ? "autoplay blocked" : String(exc && exc.message || exc);
      this.onChange();
    }
  }

  load(url) {
    this.url = url;
    this.paused = false;
    this._start(this.analysed);
  }

  setPause(paused) {
    this.paused = !!paused;
    const el = this.active;
    if (!el || !this.url) return;
    if (paused) {
      this.pausedAt = Date.now();
      el.pause();
    } else if (Date.now() - this.pausedAt > STALE_PAUSE_MS) {
      this._start(el);
    } else {
      el.play().catch(() => this._start(el));
    }
    this.onChange();
  }

  setVolume(v) { this.volume = Math.max(0, Math.min(100, v | 0)); this._applyVolume(); }
  setMute(m) { this.muted = !!m; this._applyVolume(); }

  stop() {
    this.url = null;
    for (const el of [this.analysed, this.plain]) { el.pause(); el.removeAttribute("src"); el.load(); }
    this.active = null;
    this.waiting = false;
    this.failed = false;
    this.onChange();
  }

  /** The same states the terminal app derives from mpv: what is really happening. */
  health() {
    if (this.failed) return STATE.ERROR;
    if (!this.url || !this.active) return STATE.IDLE;
    if (this.paused || this.active.paused) return this.paused ? STATE.PAUSED : STATE.BUFFERING;
    if (this.waiting || this.active.readyState < 3) return STATE.BUFFERING;
    return STATE.PLAYING;
  }

  /** True when bands() reflects the real audio, not silence. */
  spectrumLive() {
    return this.active === this.analysed && !!this.analyser && this.health() === STATE.PLAYING;
  }

  /** 18 values in 0..1, like cava's output with autosens. */
  bands() {
    const out = new Array(NUM_BANDS).fill(0);
    if (!this.spectrumLive()) return out;
    this.analyser.getByteFrequencyData(this.freq);
    let peak = 0;
    for (let b = 0; b < NUM_BANDS; b++) {
      const [lo, hi] = this.bandBins[b];
      let sum = 0;
      for (let i = lo; i < hi; i++) sum += this.freq[i];
      // treble bins are quieter; cava's per-band equaliser lifts them similarly
      const tilt = 1 + (b / NUM_BANDS) * 0.6;
      const v = (sum / (hi - lo) / 255) * tilt * this.sens;
      out[b] = v;
      if (v > peak) peak = v;
    }
    // autosens: back off quickly when clipping, creep back up when quiet
    if (peak > 0.98) this.sens *= 0.96;
    else if (peak > 0.05) this.sens = Math.min(3, this.sens * 1.004);
    for (let b = 0; b < NUM_BANDS; b++) out[b] = Math.min(1, out[b]);
    return out;
  }
}

/** [lo, hi) FFT bin ranges for n log-spaced bands between LOW_HZ and HIGH_HZ. */
export function makeBandBins(sampleRate, fftSize, n) {
  const binHz = sampleRate / fftSize;
  const bins = [];
  let prevHi = 1;
  for (let b = 0; b < n; b++) {
    const f0 = LOW_HZ * Math.pow(HIGH_HZ / LOW_HZ, b / n);
    const f1 = LOW_HZ * Math.pow(HIGH_HZ / LOW_HZ, (b + 1) / n);
    const lo = Math.max(prevHi, Math.floor(f0 / binHz));
    const hi = Math.max(lo + 1, Math.ceil(f1 / binHz));
    bins.push([lo, hi]);
    prevHi = hi;
  }
  return bins;
}

function describeMediaError(err) {
  if (!err) return "stream error";
  return ({ 1: "aborted", 2: "network error", 3: "decode error", 4: "unsupported stream" })[err.code]
    || err.message || "stream error";
}
