// The player tab's and the popup's connection to the audio host. Reconnects if
// the host goes away - Chrome closes an offscreen document after about 30 s
// without audio - and hands a fresh host the last known state to resume from.

import { loadStations } from "./common.js";

const api = globalThis.browser ?? globalThis.chrome;

export class HostClient {
  constructor({ wantBands = false, autoplay = false, onState, onBands }) {
    this.wantBands = wantBands;
    this.autoplay = autoplay;
    this.onState = onState || (() => {});
    this.onBands = onBands || (() => {});
    this.snap = null;
    this.port = null;
  }

  async connect() {
    this.stations = await loadStations();
    let restore = {};
    try {
      restore = (await api.storage.local.get("playerState")).playerState || {};
    } catch { /* first run */ }
    await this._open(restore);
  }

  async _open(restore) {
    try {
      await api.runtime.sendMessage({ type: "ensure-audio" });
    } catch { /* the host may already be up */ }
    const port = api.runtime.connect({ name: "termbeat" });
    this.port = port;
    port.onMessage.addListener((msg) => {
      if (msg.type === "state") {
        this.snap = msg.snap;
        this._persist(msg.snap);
        this.onState(msg.snap);
      } else if (msg.type === "bands") {
        this.onBands(msg.bands, msg.live);
      }
    });
    port.onDisconnect.addListener(() => {
      if (this.port !== port) return;
      this.port = null;
      const s = this.snap || {};
      // a replacement host resumes the station and volume, but never starts
      // audio the user had paused or stopped
      setTimeout(() => this._open({ idx: s.idx, volume: s.volume, prevVolume: s.prevVolume,
                                    muted: s.muted, repeat: s.repeat }), 300);
    });
    port.postMessage({ type: "hello", wantBands: this.wantBands, autoplay: this.autoplay,
                       stations: this.stations, restore });
    this.autoplay = false;
  }

  cmd(name, arg) {
    if (!this.port) return;
    try { this.port.postMessage({ type: "cmd", name, arg }); } catch { /* reconnecting */ }
  }

  async reloadStations() {
    this.stations = await loadStations();
    this.cmd("stations", this.stations);
  }

  _persist(s) {
    const state = { idx: s.idx, volume: s.volume, prevVolume: s.prevVolume, muted: s.muted, repeat: s.repeat };
    const key = JSON.stringify(state);
    if (key === this._lastSaved) return;
    this._lastSaved = key;
    api.storage.local.set({ playerState: state }).catch(() => {});
  }
}
