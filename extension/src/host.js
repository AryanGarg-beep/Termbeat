// The audio host: owns playback state, the audio engine and metadata polling,
// and serves them to the player tab and the popup over runtime ports. It lives
// in an offscreen document on Chrome/Edge and in the background page on
// Firefox - the pages that keep playing after every termbeat tab is closed.
//
// The state and clocks mirror TermbeatPlayer in termbeat/app.py.

import { AudioEngine, STATE } from "./audio-engine.js";
import { MetadataPoller } from "./metadata.js";
import { normalizePlaylist, DEFAULT_STATIONS } from "./common.js";

const api = globalThis.browser ?? globalThis.chrome;

class Host {
  constructor() {
    this.fresh = true;                 // no page has said hello yet
    this.stations = normalizePlaylist(DEFAULT_STATIONS);
    this.idx = 0;
    this.volume = 75;
    this.prevVolume = 75;
    this.muted = false;
    this.playing = false;
    this.stopped = true;
    this.repeat = true;
    this.trackElapsed = 0;
    this.trackDuration = null;
    this.songTitle = "";
    this.lastTrackTick = Date.now();
    this.tunedAt = 0;
    this.ports = new Set();
    this.engine = new AudioEngine(() => this.broadcastSoon());
    this.meta = new MetadataPoller(() => this.broadcastSoon());
    this.meta.setPlaylist(this.stations);
    this._pending = null;

    api.runtime.onConnect.addListener((port) => this.attach(port));
    // Firefox: the background page is the host, so it answers this itself.
    // Chrome: the service worker creates this document and answers first.
    api.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
      if (msg && msg.type === "ensure-audio") sendResponse(true);
    });
    setInterval(() => this.tick(), 250);
    setInterval(() => this.pushBands(), 33);
  }

  attach(port) {
    if (port.name !== "termbeat") return;
    port.wantBands = false;
    this.ports.add(port);
    port.onDisconnect.addListener(() => this.ports.delete(port));
    port.onMessage.addListener((msg) => this.onMessage(port, msg));
  }

  onMessage(port, msg) {
    if (msg.type === "hello") {
      port.wantBands = !!msg.wantBands;
      this.setStations(msg.stations);
      if (this.fresh) {
        this.fresh = false;
        const r = msg.restore || {};
        if (Number.isInteger(r.idx)) this.idx = Math.max(0, Math.min(this.stations.length - 1, r.idx));
        if (Number.isInteger(r.volume)) this.volume = r.volume;
        if (Number.isInteger(r.prevVolume)) this.prevVolume = r.prevVolume;
        this.muted = !!r.muted;
        if (typeof r.repeat === "boolean") this.repeat = r.repeat;
        this.engine.setVolume(this.volume);
        this.engine.setMute(this.muted);
        if (msg.autoplay) this.tune(this.idx);
      }
      this.send(port);
      return;
    }
    if (msg.type !== "cmd") return;
    const a = msg.arg;
    switch (msg.name) {
      case "toggle_play": this.togglePlay(); break;
      case "next": this.tune(this.idx + 1); break;
      case "prev": this.tune(this.idx - 1); break;
      case "tune": if (a >= 0 && a < this.stations.length) this.tune(a); break;
      case "stop": this.stop(); break;
      case "volume": this.adjustVolume(a); break;
      case "set_volume": this.setVolume(a); break;
      case "mute": this.toggleMute(); break;
      case "repeat": this.repeat = !this.repeat; break;
      case "stations": this.setStations(a); break;
    }
    this.broadcastSoon();
  }

  setStations(list) {
    const fresh = normalizePlaylist(list);
    if (!fresh.length) return;
    // keep live metadata for stations that survive the update
    const old = new Map(this.stations.map((s) => [s.url, s]));
    this.stations = fresh.map((s) => {
      const o = old.get(s.url);
      return o ? { ...s, track: o.track, listeners: o.listeners, signal: o.signal,
                   track_duration: o.track_duration, track_elapsed: o.track_elapsed } : s;
    });
    this.idx = Math.min(this.idx, this.stations.length - 1);
    this.meta.setPlaylist(this.stations);
  }

  // ---------------------------------------------------------------- actions

  tune(idx) {
    if (!this.stations.length) return;
    const n = this.stations.length;
    this.idx = ((idx % n) + n) % n;
    const station = this.stations[this.idx];
    this.songTitle = "";
    this.trackElapsed = 0;
    this.trackDuration = null;
    this.lastTrackTick = Date.now();
    this.stopped = false;
    this.playing = true;
    this.tunedAt = Date.now();
    this.engine.load(station.url);
    this.meta.setActiveStation(station);
  }

  togglePlay() {
    if (this.stopped) return this.tune(this.idx);
    this.playing = !this.playing;
    this.engine.setPause(!this.playing);
  }

  stop() {
    this.stopped = true;
    this.playing = false;
    this.trackElapsed = 0;
    this.songTitle = "";
    this.engine.stop();
  }

  adjustVolume(delta) {
    if (this.muted) { this.muted = false; this.engine.setMute(false); }
    this.setVolume(this.volume + (delta | 0));
  }

  setVolume(v) {
    this.volume = Math.max(0, Math.min(100, v | 0));
    this.engine.setVolume(this.volume);
  }

  toggleMute() {
    if (this.muted) {
      this.volume = this.prevVolume > 0 ? this.prevVolume : 50;
      this.muted = false;
      this.engine.setVolume(this.volume);
      this.engine.setMute(false);
    } else {
      this.prevVolume = this.volume;
      this.volume = 0;
      this.muted = true;
      this.engine.setMute(true);
    }
  }

  // ------------------------------------------------------------------ clocks

  tick() {
    const now = Date.now();
    const wantsAudio = this.playing && !this.stopped;
    const live = wantsAudio && this.engine.health() === STATE.PLAYING;
    this.meta.setEnabled(wantsAudio);
    if (live) {
      const cur = this.stations[this.idx] || {};
      const title = cur.track || "";
      if (title && title !== this.songTitle) {
        this.songTitle = title;
        this.trackElapsed = cur.track_elapsed > 0 ? cur.track_elapsed : 0;
        this.trackDuration = cur.track_duration || null;
        this.lastTrackTick = now;
      } else {
        if (!this.trackDuration && cur.track_duration) this.trackDuration = cur.track_duration;
        if (now - this.lastTrackTick >= 1000) {
          const d = Math.floor((now - this.lastTrackTick) / 1000);
          this.trackElapsed += d;
          this.lastTrackTick += d * 1000;
          this.broadcastSoon();
        }
      }
    } else {
      // hold the clock still so a pause or a stall is not credited to the track
      this.lastTrackTick = now;
    }
    const h = this.engine.health();
    if (h !== this._lastHealth) { this._lastHealth = h; this.broadcastSoon(); }
  }

  snapshot() {
    return {
      stations: this.stations, idx: this.idx, volume: this.volume, prevVolume: this.prevVolume,
      muted: this.muted, playing: this.playing, stopped: this.stopped, repeat: this.repeat,
      health: this.engine.health(), error: this.engine.error,
      trackElapsed: this.trackElapsed, trackDuration: this.trackDuration, tunedAt: this.tunedAt,
    };
  }

  send(port) {
    try { port.postMessage({ type: "state", snap: this.snapshot() }); } catch { /* port closed */ }
  }

  broadcastSoon() {
    if (this._pending) return;
    this._pending = setTimeout(() => {
      this._pending = null;
      for (const p of this.ports) this.send(p);
    }, 16);
  }

  pushBands() {
    let any = false;
    for (const p of this.ports) if (p.wantBands) { any = true; break; }
    if (!any) return;
    const msg = { type: "bands", bands: this.engine.bands(), live: this.engine.spectrumLive() };
    for (const p of this.ports) {
      if (!p.wantBands) continue;
      try { p.postMessage(msg); } catch { /* port closed */ }
    }
  }
}

globalThis.termbeatHost = new Host();
