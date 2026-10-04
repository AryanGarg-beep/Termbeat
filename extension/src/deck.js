// The Retro Hi-Fi deck, ported from TermbeatPlayer in termbeat/app.py. Row
// building, layout thresholds and physics constants match the Python so the
// browser deck looks and moves like the terminal one; where this file and
// app.py disagree, app.py is right.

import { THEMES } from "./common.js";
import { RST, BOLD, NORMAL, fg, bg, strWidth, fitRow, cellSlots, charWidth, center, pad2 } from "./term.js";

for (const t of THEMES) {
  t._c_frame = fg(...t.frame);
  t._c_accent = fg(...t.accent);
  t._c_bright = fg(...t.lcd_bright);
  t._c_dim = fg(...t.lcd_dim);
  t._c_warn = fg(...t.warn);
  t._c_title_fg = fg(...t.title_fg);
  t._c_title_bg = bg(...t.title_bg);
  t._c_lcd_border = fg(...t.lcd_border);
  t._c_lcd_bg = bg(...t.lcd_bg);
  t._c_deck_bg = bg(...t.deck_bg);
}

const C_DIM_CYAN = fg(35, 65, 80);
const C_HINT_TEXT = fg(175, 200, 235);
const C_VOL_LABEL = fg(180, 215, 250);
const C_BTN_IDLE = fg(160, 195, 240);
const C_ERROR = fg(255, 105, 105);
const C_MUTED = fg(255, 120, 120);

export const ACTIVE_FRAME_MS = 45;      // ~22 FPS while audio is flowing
export const IDLE_FRAME_MS = 200;       // ~5 FPS when paused, stopped or erroring
const MARQUEE_CHARS_PER_SEC = 5.5;
const TIMER_BLINK_PERIOD = 1.1;
const BLOCKS = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"];
const STATIC_CHARS = "░▒▓#%*~+-=<>[]/\\$";

const NUM_BANDS = 18;
const MAX_HEIGHT = 8.0;

const fmtInt = (n) => Number(n).toLocaleString("en-US");
const toInt = (v) => {
  const n = parseInt(v, 10);
  return Number.isNaN(n) ? 0 : n;
};

export class Deck {
  constructor(client) {
    this.client = client;
    this.snap = null;
    this.t0 = performance.now();
    this.tSec = 0;
    this.themeIdx = 0;
    this.vizMode = 0;
    this.vizNames = ["SPECTRUM", "OSCILLOSCOPE"];
    this.showDrawer = false;
    this.drawerSelected = 0;
    this.drawerScroll = 0;
    this.drawerPage = 7;
    this.tuningGlitchFrames = 0;
    this.buttonFlash = [0, 0, 0, 0];
    this.marqueeOffset = 0;
    this.lastTunedAt = null;

    this.bandHeights = new Array(NUM_BANDS).fill(4.0);
    this.cavaFall = new Array(NUM_BANDS).fill(0);
    this.cavaPeak = new Array(NUM_BANDS).fill(0);
    this.peakHeights = new Array(NUM_BANDS).fill(0);
    this.peakHold = new Array(NUM_BANDS).fill(0);
    this.bassEnergy = 0;
    this.midEnergy = 0;
    this.trebleEnergy = 0;
    this.simConst = Array.from({ length: NUM_BANDS }, (_, i) =>
      [1.0 + (i / NUM_BANDS) * 2.5, Math.max(0, (5 - i) * 0.5), i * 0.6, -i * 0.4]);
    this.liveBands = new Array(NUM_BANDS).fill(0);
    this.liveBandsAt = 0;
    this.liveBandsReal = false;
    this.monstercatTable = null;
  }

  // ------------------------------------------------------------- host state

  get stations() { return this.snap ? this.snap.stations : []; }
  get idx() { return this.snap ? this.snap.idx : 0; }
  get isPlaying() { return !!this.snap && this.snap.playing; }
  get isStopped() { return !this.snap || this.snap.stopped; }
  get volume() { return this.snap ? this.snap.volume : 75; }
  get isMuted() { return !!this.snap && this.snap.muted; }

  setSnapshot(snap) {
    if (this.lastTunedAt !== null && snap.tunedAt !== this.lastTunedAt) {
      this.tuningGlitchFrames = 5;
      this.marqueeOffset = 0;
    }
    this.lastTunedAt = snap.tunedAt;
    this.snap = snap;
    this.drawerSelected = Math.min(this.drawerSelected, Math.max(0, snap.stations.length - 1));
  }

  setBands(bands, live) {
    this.liveBands = bands;
    this.liveBandsReal = live;
    this.liveBandsAt = performance.now();
  }

  /** Whether the next frame should come at the active rate. */
  get active() {
    return this.isPlaying && !this.isStopped && this.tuningGlitchFrames === 0;
  }

  // ------------------------------------------------------------------- keys

  /** Act on one key name (as the terminal app names them). False means quit. */
  handleKey(key) {
    const c = this.client;
    const n = this.stations.length;
    if (key === "q" || key === "Q") return false;
    if (key === "ESC") {
      if (this.showDrawer) { this.showDrawer = false; return true; }
      return false;
    }
    if (key === "v" || key === "V") this.vizMode = (this.vizMode + 1) % this.vizNames.length;
    else if (key === "t" || key === "T") this.themeIdx = (this.themeIdx + 1) % THEMES.length;
    else if (key === "l" || key === "L") this.toggleDrawer();
    else if (this.showDrawer && n) {
      if (key === "UP") this.drawerSelected = (this.drawerSelected - 1 + n) % n;
      else if (key === "DOWN") this.drawerSelected = (this.drawerSelected + 1) % n;
      else if (key === "PAGEUP") this.drawerSelected = Math.max(0, this.drawerSelected - this.drawerPage);
      else if (key === "PAGEDOWN") this.drawerSelected = Math.min(n - 1, this.drawerSelected + this.drawerPage);
      else if (key === "HOME") this.drawerSelected = 0;
      else if (key === "END") this.drawerSelected = n - 1;
      else if (key === "ENTER") { c.cmd("tune", this.drawerSelected); this.showDrawer = false; }
    } else if (key === "SPACE") { this.flash(2); c.cmd("toggle_play"); }
    else if (key === "n" || key === "N" || key === "RIGHT") { this.flash(3); c.cmd("next"); }
    else if (key === "p" || key === "P" || key === "LEFT") { this.flash(1); c.cmd("prev"); }
    else if (key === "s" || key === "S") c.cmd("stop");
    else if (key === "r" || key === "R") { this.flash(0); c.cmd("repeat"); }
    else if (key === "m" || key === "M") c.cmd("mute");
    else if (key === "UP" || key === "+" || key === "=") c.cmd("volume", 5);
    else if (key === "DOWN" || key === "-" || key === "_") c.cmd("volume", -5);
    else if (/^[1-9]$/.test(key) && Number(key) <= n) c.cmd("tune", Number(key) - 1);
    return true;
  }

  flash(i) { this.buttonFlash[i] = 4; }

  toggleDrawer() {
    this.showDrawer = !this.showDrawer;
    if (this.showDrawer) {
      this.drawerSelected = this.idx;
      const page = this.drawerPage;
      this.drawerScroll = Math.max(0, Math.min(this.stations.length - page, this.drawerSelected - Math.floor(page / 2)));
    }
  }

  // ---------------------------------------------------------------- physics

  updatePhysics() {
    this.tSec = (performance.now() - this.t0) / 1000;
    const live = this.snap && this.snap.health === "PLAYING";
    const wantsAudio = this.isPlaying && !this.isStopped;
    const effVol = (this.isMuted || !wantsAudio || !live) ? 0 : this.volume / 100;

    const fresh = performance.now() - this.liveBandsAt < 500;
    const hasLive = fresh && this.liveBandsReal && this.liveBands.some((v) => v > 0.02);
    let target;
    if (hasLive && effVol > 0.01) {
      target = this.liveBands.map((b) => Math.min(MAX_HEIGHT, b * MAX_HEIGHT * Math.pow(effVol, 0.65) * 1.15));
    } else if (wantsAudio && effVol > 0.01) {
      const t = this.tSec;
      const raw = this.simConst.map(([ff, boost, p1, p2]) => {
        const wave = Math.sin(t * (3.2 * ff) + p1) * 1.8 + Math.cos(t * (2.1 * ff) + p2) * 1.2 + (Math.random() * 1.8 - 0.5);
        return Math.max(0.4, (2.6 + wave + boost) * effVol);
      });
      target = this.monstercat(raw).map((b) => Math.min(MAX_HEIGHT, Math.max(0.2, b)));
    } else {
      target = new Array(NUM_BANDS).fill(0);
    }

    for (let i = 0; i < NUM_BANDS; i++) {
      const tgt = target[i];
      if (tgt >= this.bandHeights[i]) {
        this.bandHeights[i] += (tgt - this.bandHeights[i]) * 0.6;
        this.cavaPeak[i] = this.bandHeights[i];
        this.cavaFall[i] = 0;
      } else {
        this.cavaFall[i] += 0.035;
        const decay = this.cavaPeak[i] * (1 - this.cavaFall[i] ** 2 * 1.25);
        this.bandHeights[i] = Math.max(0, Math.max(tgt, decay));
      }
      this.bandHeights[i] = Math.max(0, Math.min(MAX_HEIGHT, this.bandHeights[i]));
      if (this.bandHeights[i] >= this.peakHeights[i]) {
        this.peakHeights[i] = this.bandHeights[i];
        this.peakHold[i] = 5;
      } else if (this.peakHold[i] > 0) {
        this.peakHold[i] -= 1;
      } else {
        this.peakHeights[i] = Math.max(this.bandHeights[i], this.peakHeights[i] - 0.16);
      }
    }
    const sum = (a, b) => this.bandHeights.slice(a, b).reduce((x, y) => x + y, 0);
    this.bassEnergy = sum(0, 5) / (5 * MAX_HEIGHT);
    this.midEnergy = sum(5, 12) / (7 * MAX_HEIGHT);
    this.trebleEnergy = sum(12, 18) / (6 * MAX_HEIGHT);

    for (let i = 0; i < 4; i++) if (this.buttonFlash[i] > 0) this.buttonFlash[i] -= 1;
    if (this.tuningGlitchFrames > 0) this.tuningGlitchFrames -= 1;
  }

  /** cava's Monstercat spatial smoothing filter. */
  monstercat(bars) {
    const n = bars.length;
    const res = bars.slice();
    if (!this.monstercatTable) this.monstercatTable = Array.from({ length: n }, (_, d) => 1.5 ** d);
    const table = this.monstercatTable;
    for (let z = 0; z < n; z++) {
      const val = bars[z];
      if (val <= 0) continue;
      for (let m = z - 1; m >= 0; m--) res[m] = Math.max(res[m], val / table[z - m]);
      for (let m = z + 1; m < n; m++) res[m] = Math.max(res[m], val / table[m - z]);
    }
    return res;
  }

  // -------------------------------------------------------------- widgets

  statusBadge(t, compact = false) {
    if (this.isStopped) return [compact ? "■ STOP" : "■ STOPPED", C_ERROR];
    const state = this.snap.health;
    if (state === "STREAM ERROR") return [compact ? "✖ ERR" : "✖ STREAM ERROR", C_ERROR];
    if (!this.isPlaying) return [compact ? "❚❚ PAUS" : "❚❚ PAUSED", t._c_warn];
    if (state === "BUFFERING" || state === "CONNECTING") return [compact ? "◌ BUF" : "◌ BUFFERING", t._c_warn];
    if (state === "IDLE") return ["◌ IDLE", t._c_dim];
    return [compact ? "● PLAY" : "● PLAYING", t._c_bright];
  }

  timerColon() {
    if (!this.isPlaying) return ":";
    return (this.tSec % TIMER_BLINK_PERIOD) < TIMER_BLINK_PERIOD * 0.66 ? ":" : " ";
  }

  timeStr(sep = "  ") {
    const el = this.snap ? this.snap.trackElapsed : 0;
    const dur = this.snap ? this.snap.trackDuration : null;
    const head = `${pad2(Math.floor(el / 60))}${this.timerColon()}${pad2(el % 60)}`;
    if (dur && dur > 0) return `Elapsed:${sep}${head} / ${pad2(Math.floor(dur / 60))}:${pad2(dur % 60)}`;
    return `Elapsed:${sep}${head}${sep === "  " ? "  " : " "}[LIVE]`;
  }

  equalizerRows(targetW, totalRows, t) {
    const { _c_bright: cBright, _c_warn: cWarn, _c_accent: cAccent, _c_dim: cDim } = t;
    let rowColors;
    if (totalRows <= 5) {
      rowColors = [cWarn, cAccent, cAccent, cBright, cBright];
    } else {
      const w = Math.max(1, Math.floor(totalRows / 4));
      const a = Math.max(1, Math.floor(totalRows / 3));
      const b = Math.max(1, totalRows - w - a);
      rowColors = [...Array(w).fill(cWarn), ...Array(a).fill(cAccent), ...Array(b).fill(cBright)];
    }
    const peakColors = Array.from({ length: totalRows }, (_, r) => (r <= Math.max(1, Math.floor(totalRows / 4)) ? cWarn : cAccent));
    const numBars = Math.max(10, targetW >= 20 ? Math.floor(targetW / 2) : targetW);
    const useSpaces = targetW >= numBars * 2;
    const nRaw = this.bandHeights.length;
    const scale = totalRows / 8;
    const denom = Math.max(1, numBars - 1);
    const barVals = [], peakVals = [];
    for (let i = 0; i < numBars; i++) {
      const pos = (i * (nRaw - 1)) / denom;
      const ix = Math.floor(pos);
      const frac = pos - ix;
      const nx = Math.min(ix + 1, nRaw - 1);
      barVals.push(((1 - frac) * this.bandHeights[ix] + frac * this.bandHeights[nx]) * scale);
      peakVals.push(((1 - frac) * this.peakHeights[ix] + frac * this.peakHeights[nx]) * scale);
    }
    const barsW = useSpaces ? numBars * 2 : numBars;
    const padL = " ".repeat(Math.max(0, Math.floor((targetW - barsW) / 2)));
    const out = [];
    for (let r = 0; r < totalRows; r++) {
      const color = rowColors[Math.min(r, rowColors.length - 1)];
      const pCol = peakColors[r];
      const threshold = totalRows - 1 - r;
      let s = padL;
      for (let i = 0; i < numBars; i++) {
        const rem = barVals[i] - threshold;
        const pRem = peakVals[i] - threshold;
        if (rem >= 1) s += `${color}█`;
        else if (rem > 0) s += `${color}${BLOCKS[Math.max(1, Math.min(8, Math.floor(rem * 8)))]}`;
        else if (pRem >= 0 && pRem < 1 && peakVals[i] > 0.4) s += `${pCol}▔`;
        else s += `${cDim} `;
        if (useSpaces) s += " ";
      }
      out.push(fitRow(s, targetW));
    }
    return out;
  }

  oscilloscopeRows(targetW, totalRows, t) {
    const { _c_bright: cBright, _c_accent: cAccent, _c_dim: cDim } = t;
    const effVol = (this.isMuted || this.isStopped || !this.isPlaying) ? 0 : this.volume / 100;
    const centerY = (totalRows - 1) / 2;
    const amp = (totalRows / 8) * effVol;
    const midRow = Math.floor(centerY);
    if (effVol < 0.02) {
      const flat = fitRow(`${cDim}─`.repeat(targetW), targetW);
      const blank = " ".repeat(targetW);
      const mids = totalRows > 4 ? [midRow, midRow + 1] : [midRow];
      return Array.from({ length: totalRows }, (_, r) => (mids.includes(r) ? flat : blank));
    }
    const ts = this.tSec;
    const ph1 = ts * (2.6 + this.trebleEnergy * 1.4), ph2 = -ts * 1.8, ph3 = ts * 3.5;
    const s1 = 1.3 + this.bassEnergy * 0.8, s2 = 0.8 + this.midEnergy * 0.5, s3 = 0.3 + this.trebleEnergy * 0.4;
    const cols = [];
    for (let x = 0; x < targetW; x++) {
      const xn = x / targetW;
      const val = (Math.sin(xn * 8.6 + ph1) * s1 + Math.cos(xn * 18 + ph2) * s2 + Math.sin(xn * 38 + ph3) * s3) * amp;
      const yf = centerY - val * 1.25;
      cols.push([yf, Math.round(yf)]);
    }
    const out = [];
    for (let r = 0; r < totalRows; r++) {
      const edge = r === 0 || r === totalRows - 1;
      const wave = edge ? `${cAccent}${BOLD}~${NORMAL}` : `${cBright}${BOLD}∿${NORMAL}`;
      let s = "";
      for (const [yf, yi] of cols) {
        if (yi === r) s += wave;
        else if (Math.abs(yf - r) < 0.65) s += `${cDim}·`;
        else s += " ";
      }
      out.push(fitRow(s, targetW));
    }
    return out;
  }

  glitchRows(targetW, totalRows, t) {
    const name = (this.stations[this.idx]?.station || "RADIO").toUpperCase();
    const tape = targetW >= 36 ? `PRESET ··· [ ${name} ] ··· TUNING`
      : targetW >= 22 ? `TUNING: [ ${name} ]` : targetW >= 14 ? `TUNE ${name}` : "TUNING";
    const lock = targetW >= 50 ? `>> LOCKING DIGITAL AUDIO STREAM ... [${name}] <<`
      : targetW >= 30 ? `>> LOCKING STREAM: ${name} <<` : targetW >= 18 ? `>> LOCK: ${name} <<` : `>> ${name} <<`;
    const lockRow = totalRows > 3 ? Math.min(2, Math.floor(totalRows / 2)) : (totalRows > 1 ? 1 : -1);
    const rows = [];
    for (let r = 0; r < totalRows; r++) {
      if (r === 0) rows.push(fitRow(`${t._c_warn}${BOLD}${center(tape, targetW)}${NORMAL}${RST}`, targetW));
      else if (r === lockRow) rows.push(fitRow(`${t._c_accent}${BOLD}${center(lock, targetW)}${NORMAL}${RST}`, targetW));
      else {
        let noise = "";
        for (let k = 0; k < targetW; k++) noise += STATIC_CHARS[Math.floor(Math.random() * STATIC_CHARS.length)];
        rows.push(fitRow(`${t._c_dim}${noise}${RST}`, targetW));
      }
    }
    return rows;
  }

  vizRows(w, h, t) {
    if (this.tuningGlitchFrames > 0) return this.glitchRows(w, h, t);
    return this.vizMode === 0 ? this.equalizerRows(w, h, t) : this.oscilloscopeRows(w, h, t);
  }

  marquee(text, targetW) {
    if (targetW <= 0) return "";
    const slots = cellSlots(`~~~ ${text} ~~~     `);
    const n = slots.length;
    if (!n) return " ".repeat(targetW);
    if (this.isPlaying && !this.isStopped) this.marqueeOffset = Math.floor(this.tSec * MARQUEE_CHARS_PER_SEC) % n;
    const offset = this.marqueeOffset % n;
    let out = "", width = 0, k = 0;
    while (width < targetW) {
      const slot = slots[(offset + k) % n];
      k++;
      if (!slot) { out += " "; width++; continue; }
      const w = charWidth(slot);
      if (width + w > targetW) { out += " "; width++; continue; }
      out += slot;
      width += w;
      if (w === 2) k++;
    }
    return out;
  }

  button(i, label, t, active = false) {
    if (this.buttonFlash[i] > 0) return `\x1b[48;2;255;210;40m\x1b[38;2;10;20;30m${BOLD}[ ${label} ]${RST}`;
    return `${active ? t._c_accent : C_BTN_IDLE}[ ${label} ]${RST}`;
  }

  transportBar(innerW, t, bgCol = "") {
    const on = this.isPlaying && !this.isStopped;
    const rep = !!this.snap?.repeat;
    let labels, gap;
    if (innerW >= 68) { labels = [rep ? "⟳ LOOP ●" : "⟳ LOOP ○", "|◀ PREV", on ? "|| PAUSE" : "▶ PLAY  ", "NEXT ▶|"]; gap = "      "; }
    else if (innerW >= 54) { labels = ["⟳ LOOP", "◀ PREV", on ? "❚❚ Pause" : "▶ Play  ", "NEXT ▶"]; gap = "   "; }
    else { labels = ["⟳", "◀", on ? "❚❚" : "▶ ", "▶"]; gap = innerW >= 44 ? "  " : " "; }
    const btns = [
      this.button(0, labels[0], t, rep), this.button(1, labels[1], t),
      this.button(2, labels[2], t, on), this.button(3, labels[3], t),
    ].join(gap);
    const sp = Math.max(0, Math.floor((innerW - strWidth(btns)) / 2));
    return fitRow(`${" ".repeat(sp)}${btns}`, innerW, bgCol);
  }

  statusBar(innerW, t, styleLabel = "", bgCol = "") {
    const key = t._c_accent, txt = C_HINT_TEXT;
    const style = styleLabel ? ` Style (${styleLabel})` : " Style";
    const full = [["[D]", style], ["[V]", " Viz"], ["[T]", " Theme"], ["[L]", " Stations"], ["[A]", " Add"], ["[+/-]", " Vol"], ["[Q]", " Quit"]];
    const variants = [
      [full, "   "], [full, "  "],
      [[["[D]", " Style"], ["[V]", " Viz"], ["[T]", " Theme"], ["[L]", " List"], ["[A]", " Add"], ["[+/-]", " Vol"], ["[Q]", " Quit"]], "  "],
      [[["[D]", "Style"], ["[V]", "Viz"], ["[T]", "Theme"], ["[L]", "List"], ["[A]", "Add"], ["[+/-]", "Vol"], ["[Q]", "Quit"]], "  "],
      [[["[D]", "Style"], ["[V]", "Viz"], ["[T]", "Thm"], ["[L]", "Stn"], ["[A]", "Add"], ["[Q]", "Quit"]], "  "],
    ];
    let s = "";
    for (const [items, sep] of variants) {
      s = items.map(([k, v]) => `${key}${k}${txt}${v}`).join(sep);
      if (strWidth(s) <= innerW) break;
    }
    const sp = Math.max(0, Math.floor((innerW - strWidth(s)) / 2));
    return fitRow(`${" ".repeat(sp)}${s}`, innerW, bgCol);
  }

  drawerRows(lcdW, t, maxRows = 8) {
    const { _c_bright: cBright, _c_accent: cAccent, _c_dim: cDim, _c_warn: cWarn } = t;
    const list = this.stations;
    const total = list.length;
    const visible = Math.max(1, maxRows - 1);
    this.drawerPage = visible;
    if (this.drawerSelected < this.drawerScroll) this.drawerScroll = this.drawerSelected;
    else if (this.drawerSelected >= this.drawerScroll + visible) this.drawerScroll = this.drawerSelected - visible + 1;
    this.drawerScroll = Math.max(0, Math.min(Math.max(0, total - visible), this.drawerScroll));
    const start = this.drawerScroll + 1;
    const end = Math.min(total, this.drawerScroll + visible);
    const up = this.drawerScroll > 0 ? "▲" : " ";
    const down = this.drawerScroll + visible < total ? "▼" : " ";
    const rows = [fitRow(`  ${cAccent}${BOLD}STATION DIRECTORY${NORMAL} ${cBright}(${pad2(start)}-${pad2(end)} of ${pad2(total)}) ${cDim}${up} [▲/▼: Scroll, Enter: Tune, L/Esc: Close] ${down}`, lcdW)];
    for (let slot = 0; slot < visible; slot++) {
      const i = this.drawerScroll + slot;
      if (i >= total) { rows.push(fitRow(" ", lcdW)); continue; }
      const stn = list[i];
      const isSel = i === this.drawerSelected;
      const cursor = isSel ? "►" : (i === this.idx ? "●" : " ");
      const prov = `[${(stn.provider || "STREAM").toUpperCase().padEnd(8)}]`;
      const name = stn.station.slice(0, 20).padEnd(20);
      const genre = `[${(stn.genre || "RADIO").padEnd(6)}]`;
      const sigVal = toInt(String(stn.signal || "95%").replace("%", ""));
      const filled = Math.floor((sigVal / 100) * 12);
      const sigBar = "█".repeat(filled) + "░".repeat(Math.max(0, 12 - filled));
      const sig = String(stn.signal || "95%").padEnd(4);
      const br = stn.bitrate || "128kbps";
      const line = isSel
        ? ` ${cBright}${BOLD}${cursor} ${pad2(i + 1)}. ${name} ${cAccent}${prov} ${cWarn}${genre} ${cDim}SIG:[${sigBar}] ${sig} ${cBright}${br}${NORMAL}`
        : ` ${cDim}${cursor} ${pad2(i + 1)}. ${name} ${prov} ${genre} SIG:[${sigBar}] ${sig} ${br}`;
      rows.push(fitRow(line, lcdW));
    }
    return rows;
  }

  // --------------------------------------------------------------- layouts

  render(cols, rows) {
    const t = THEMES[this.themeIdx];
    if (!this.snap || !this.stations.length) {
      const msg = `${t._c_accent}♫ ${t._c_title_fg}termbeat${t._c_dim}  connecting to the audio host…`;
      const lines = Array(Math.floor(rows / 2)).fill("");
      lines.push(" ".repeat(Math.max(0, Math.floor((cols - strWidth(msg)) / 2))) + msg);
      return lines;
    }
    if (rows >= 32 && cols >= 70) return this.renderTower(cols, rows, t);
    if (cols < 102) return this.renderCompact(cols, rows, t);
    return this.renderStandard(cols, rows, t);
  }

  volumeRow(innerW, slots, gap, t) {
    const filled = Math.floor((this.volume / 100) * slots);
    const bar = `${t._c_accent}${"▰".repeat(filled)}${C_DIM_CYAN}${"▱".repeat(slots - filled)}${RST}`;
    const s = `${C_VOL_LABEL}VOLUME: [${bar}]${gap}${t._c_accent}${String(this.volume).padStart(3)}%${RST}`;
    return " ".repeat(Math.max(0, Math.floor((innerW - strWidth(s)) / 2))) + s;
  }

  renderTower(cols, rows, t) {
    const cur = this.stations[this.idx];
    const F = t._c_frame, CY = t._c_accent, B = t._c_lcd_border;
    const W = Math.min(100, cols - (cols % 2));
    const innerW = W - 2;
    const pad = " ".repeat(Math.max(0, Math.floor((cols - W) / 2)));
    let vizH, slotsN;
    if (rows >= 40) {
      slotsN = Math.min(this.stations.length, 16);
      vizH = Math.max(8, Math.min(24, rows - 34));
    } else {
      vizH = 8;
      slotsN = Math.min(this.stations.length, Math.max(6, rows - 16 - vizH));
    }
    const chassisH = 16 + vizH + slotsN;
    const lines = Array(Math.max(0, Math.floor((rows - chassisH) / 2))).fill("");
    const vizTag = this.vizNames[this.vizMode];
    const title = `${CY} ♫ ${t._c_title_fg}${BOLD}termbeat${NORMAL} ${C_DIM_CYAN}// STUDIO TOWER${RST}`;
    const right = `${CY}[ ${vizTag} ] [RETRO HI-FI] [ FM STEREO ]${RST}`;
    const sp = Math.max(0, innerW - strWidth(title) - strWidth(right));
    lines.push(`${pad}${F}╭${"─".repeat(innerW)}╮${RST}`);
    lines.push(`${pad}${F}│${fitRow(`${title}${" ".repeat(sp)}${right}`, innerW)}${F}│${RST}`);
    lines.push(`${pad}${F}├${"─".repeat(innerW)}┤${RST}`);

    const vizW = innerW - 4;
    const vTop = fitRow(`─── ${vizTag} (HIGH-RESOLUTION) ──`, vizW, "", "─");
    lines.push(`${pad}${F}│ ${B}╭${vTop}╮${RST} ${F}│${RST}`);
    const vRows = this.vizRows(vizW, vizH, t);
    for (let r = 0; r < vizH; r++) {
      lines.push(`${pad}${F}│ ${B}│${fitRow(vRows[r] ?? " ".repeat(vizW), vizW)}${B}│${RST} ${F}│${RST}`);
    }
    lines.push(`${pad}${F}│ ${B}╰${"─".repeat(vizW)}╯${RST} ${F}│${RST}`);
    lines.push(`${pad}${F}├${"─".repeat(innerW)}┤${RST}`);

    const listeners = toInt(cur.listeners);
    const bit = cur.bitrate || "128kbps";
    const stats = listeners > 0 ? `${fmtInt(listeners)} Online  ${bit}` : bit;
    const stnLine = `  STATION: ${CY}${BOLD}${cur.station.toUpperCase()}${NORMAL}${RST}`;
    const stnSp = Math.max(1, innerW - strWidth(stnLine) - strWidth(stats) - 2);
    const r0 = `${stnLine}${" ".repeat(stnSp)}${CY}${stats}  `;
    const trackW = Math.max(32, Math.min(56, Math.trunc((innerW - 14) * 0.58)));
    const r1 = `  TRACK:   ${t._c_bright}${BOLD}${this.marquee(cur.track, trackW)}${NORMAL}  `;
    const time = this.timeStr("  ");
    const [badge, badgeCol] = this.statusBadge(t);
    const r2 = `  ${t._c_dim}${time}${" ".repeat(Math.max(2, innerW - strWidth(time) - strWidth(badge) - 4))}${badgeCol}${BOLD}${badge}${NORMAL}  `;
    for (const r of [r0, r1, r2]) lines.push(`${pad}${F}│${fitRow(r, innerW)}${F}│${RST}`);
    lines.push(`${pad}${F}│${this.transportBar(innerW, t)}${F}│${RST}`);
    const slots = Math.max(8, Math.min(24, Math.floor((innerW - 28) / 2)));
    lines.push(`${pad}${F}│${fitRow(this.volumeRow(innerW, slots, "   ", t), innerW)}${F}│${RST}`);
    lines.push(`${pad}${F}├${"─".repeat(innerW)}┤${RST}`);

    if (this.showDrawer) {
      // the tower's directory becomes the selectable drawer
      const dRows = this.drawerRows(innerW, t, slotsN + 1);
      for (const r of dRows) lines.push(`${pad}${F}│${fitRow(r, innerW)}${F}│${RST}`);
    } else {
      const hdr = `  ${CY}${BOLD}STATION DIRECTORY${NORMAL} ${t._c_bright}(All ${this.stations.length} Channels Online)  ${t._c_dim}[N/P: Tune, Space: Pause]${RST}`;
      lines.push(`${pad}${F}│${fitRow(hdr, innerW)}${F}│${RST}`);
      // keep the tuned station in view when there are more stations than rows
      const first = Math.max(0, Math.min(this.stations.length - slotsN, this.idx - slotsN + 1));
      for (let k = 0; k < slotsN; k++) {
        const i = first + k;
        const stn = this.stations[i];
        const isCur = i === this.idx;
        const marker = isCur ? `${CY}${BOLD}●${NORMAL}` : " ";
        const pTag = `[${(stn.provider || "STREAM").toUpperCase().padEnd(7)}]`;
        const name = stn.station.slice(0, 22).padEnd(22);
        const gTag = `[${(stn.genre || "RADIO").padEnd(6)}]`;
        const bTag = stn.bitrate || "128k";
        const lCnt = `${fmtInt(toInt(stn.listeners))} onl`;
        const line = isCur
          ? `  ${marker} ${t._c_bright}${BOLD}${pad2(i + 1)}. ${name}${NORMAL} ${CY}${pTag} ${t._c_warn}${gTag}${RST} ${t._c_dim}${lCnt.padStart(10)}  ${bTag}${RST}`
          : `  ${marker} ${t._c_dim}${pad2(i + 1)}. ${name} ${pTag} ${gTag} ${lCnt.padStart(10)}  ${bTag}${RST}`;
        lines.push(`${pad}${F}│${fitRow(line, innerW)}${F}│${RST}`);
      }
    }
    lines.push(`${pad}${F}├${"─".repeat(innerW)}┤${RST}`);
    lines.push(`${pad}${F}│${this.statusBar(innerW, t, "Retro")}${F}│${RST}`);
    lines.push(`${pad}${F}╰${"─".repeat(innerW)}╯${RST}`);
    return lines;
  }

  renderCompact(cols, rows, t) {
    const cur = this.stations[this.idx];
    const F = t._c_frame, CY = t._c_accent, B = t._c_lcd_border;
    const W = Math.min(78, cols - (cols % 2));
    const innerW = W - 2;
    const pad = " ".repeat(Math.max(0, Math.floor((cols - W) / 2)));
    const lines = Array(Math.max(0, Math.floor((rows - 15) / 2))).fill("");
    const vizTag = this.vizNames[this.vizMode];
    const title = `${CY} ♫ ${t._c_title_fg}${BOLD}termbeat${NORMAL}`;
    const tag = `${CY}[ ${vizTag} ] [FM STEREO]${RST}`;
    const sp = Math.max(0, innerW - strWidth(title) - strWidth(tag));
    lines.push(`${pad}${F}╭${"─".repeat(innerW)}╮${RST}`);
    lines.push(`${pad}${F}│${fitRow(`${title}${" ".repeat(sp)}${tag}`, innerW)}${F}│${RST}`);
    lines.push(`${pad}${F}├${"─".repeat(innerW)}┤${RST}`);

    const lcdW = innerW - 4;
    const leftW = 22;
    const rightW = lcdW - leftW - 3;
    const name = cur.station.toUpperCase();
    const lCnt = `${fmtInt(toInt(cur.listeners))} onl`;
    const c0 = `${CY}${BOLD}${name}${NORMAL}${" ".repeat(Math.max(1, rightW - strWidth(name) - strWidth(lCnt)))}${t._c_dim}${lCnt}`;
    const c1 = `${t._c_bright}${BOLD}${this.marquee(cur.track, rightW)}${NORMAL}`;
    const [badge, badgeCol] = this.statusBadge(t, true);
    const genre = `${cur.genre} / STEREO`;
    const c2 = `${t._c_dim}${genre}${" ".repeat(Math.max(1, rightW - strWidth(genre) - strWidth(badge)))}${badgeCol}${BOLD}${badge}${NORMAL}`;
    const c3 = `${t._c_bright}${this.timeStr(" ").padEnd(rightW)}`;
    const rights = [c0, c1, c2, c3, " ".repeat(rightW)];

    lines.push(`${pad}${F}│ ${B}╭${"─".repeat(lcdW)}╮${RST} ${F}│${RST}`);
    if (this.showDrawer) {
      const d = this.drawerRows(lcdW, t, 5);
      for (let r = 0; r < 5; r++) lines.push(`${pad}${F}│ ${B}│${fitRow(d[r] ?? "", lcdW)}${B}│${RST} ${F}│${RST}`);
    } else {
      const v = this.vizRows(leftW, 5, t);
      for (let r = 0; r < 5; r++) {
        lines.push(`${pad}${F}│ ${B}│${fitRow(` ${v[r] ?? " ".repeat(leftW)}  ${rights[r]} `, lcdW)}${B}│${RST} ${F}│${RST}`);
      }
    }
    lines.push(`${pad}${F}│ ${B}╰${"─".repeat(lcdW)}╯${RST} ${F}│${RST}`);
    lines.push(`${pad}${F}│${this.transportBar(innerW, t)}${F}│${RST}`);
    const slots = Math.max(8, Math.min(16, Math.floor((innerW - 24) / 2)));
    lines.push(`${pad}${F}│${fitRow(this.volumeRow(innerW, slots, "  ", t), innerW)}${F}│${RST}`);
    lines.push(`${pad}${F}├${"─".repeat(innerW)}┤${RST}`);
    lines.push(`${pad}${F}│${this.statusBar(innerW, t, "Retro")}${F}│${RST}`);
    lines.push(`${pad}${F}╰${"─".repeat(innerW)}╯${RST}`);
    return lines;
  }

  renderStandard(cols, rows, t) {
    const cur = this.stations[this.idx];
    const F = t._c_frame, CY = t._c_accent, B = t._c_lcd_border;
    const innerW = 100;
    const pad = " ".repeat(Math.max(0, Math.floor((cols - 102) / 2)));
    const lines = Array(Math.max(0, Math.floor((rows - 18) / 2))).fill("");
    const vizTag = this.vizNames[this.vizMode];
    const title = `${CY} ♫ ${t._c_title_fg}${BOLD}termbeat${NORMAL}`;
    const loop = this.snap.repeat ? `${CY}${BOLD}[ ⟳ LOOP ON ]${NORMAL} ` : `${C_DIM_CYAN}[ ⟳ LOOP OFF ] `;
    const status = `${loop}${CY}[ ${vizTag} ] [ FM STEREO ] ${RST}`;
    const free = innerW - strWidth(title) - strWidth(status);
    lines.push(`${pad}${F}╭${"─".repeat(innerW)}╮${RST}`);
    lines.push(`${pad}${F}│${fitRow(`${title}${" ".repeat(Math.max(0, free))}${status}`, innerW)}${F}│${RST}`);
    lines.push(`${pad}${F}├${"─".repeat(innerW)}┤${RST}`);

    const lcdW = 92;
    let lcdRows;
    if (this.showDrawer) {
      lcdRows = this.drawerRows(lcdW, t);
    } else {
      const rp = 48;
      const listeners = toInt(cur.listeners);
      const bit = cur.bitrate || "128kbps";
      const data = listeners > 0 ? `${fmtInt(listeners)} Online  ${bit}` : bit;
      let name = cur.station.toUpperCase();
      const availW = Math.max(8, rp - 1 - strWidth(data));
      if (strWidth(name) > availW) name = `${name.slice(0, availW - 1)}…`;
      const r0 = `${CY}${BOLD}${name}${NORMAL}${" ".repeat(Math.max(1, rp - strWidth(name) - strWidth(data)))}${CY}${data}`;
      const r1 = `${t._c_bright}${BOLD}${this.marquee(cur.track, rp)}${NORMAL}`;
      const [badge, badgeCol] = this.statusBadge(t);
      const genre = `Genre:    ${cur.genre} / STEREO`;
      const rGenre = `${t._c_dim}${genre}${" ".repeat(Math.max(1, rp - strWidth(genre) - strWidth(badge)))}${badgeCol}${BOLD}${badge}${NORMAL}`;
      const rTime = `${t._c_bright}${this.timeStr("  ").padEnd(rp)}`;
      const blank = " ".repeat(rp);
      const rights = [r0, r1, blank, rGenre, blank, rTime, blank, blank];
      const v = this.vizRows(36, 8, t);
      lcdRows = rights.map((rr, i) => fitRow(`  ${v[i] ?? " ".repeat(36)}    ${rr}  `, lcdW));
    }
    const dPad = "   ";
    lines.push(`${pad}${F}│${dPad}${B}╭${"─".repeat(lcdW)}╮${RST}${dPad}${F}│${RST}`);
    for (const r of lcdRows) lines.push(`${pad}${F}│${dPad}${B}│${fitRow(r, lcdW)}${B}│${RST}${dPad}${F}│${RST}`);
    lines.push(`${pad}${F}│${dPad}${B}╰${"─".repeat(lcdW)}╯${RST}${dPad}${F}│${RST}`);

    const slots = 28;
    let vol;
    if (this.isMuted) {
      vol = `${C_MUTED}VOLUME: [${C_ERROR}${"▱".repeat(slots)}${RST}${C_MUTED}]   MUTED${RST}`;
      vol = " ".repeat(Math.max(0, Math.floor((innerW - strWidth(vol)) / 2))) + vol;
    } else {
      vol = this.volumeRow(innerW, slots, "   ", t);
    }
    lines.push(`${pad}${F}│${this.transportBar(innerW, t)}${F}│${RST}`);
    lines.push(`${pad}${F}│${fitRow(vol, innerW)}${F}│${RST}`);
    lines.push(`${pad}${F}├${"─".repeat(innerW)}┤${RST}`);

    const K = CY, X = C_HINT_TEXT;
    const bar = this.showDrawer
      ? ` ${K}[▲/▼]${X} Navigate Directory   ${K}[Enter]${X} Tune Channel   ${K}[L/Esc]${X} Close Drawer   ${K}[Q]${X} Quit Player`
      : ` ${K}[Space]${X} Play/Pause  ${K}[N/P]${X} Stn  ${K}[V]${X} Viz  ${K}[T]${X} Theme  ${K}[D]${X} Style  ${K}[L]${X} List  ${K}[A]${X} Add  ${K}[M]${X} Mute  ${K}[Q]${X} Quit`;
    lines.push(`${pad}${F}│${fitRow(bar, innerW)}${F}│${RST}`);
    lines.push(`${pad}${F}╰${"─".repeat(innerW)}╯${RST}`);
    return lines;
  }
}
