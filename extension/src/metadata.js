// Now-playing titles, ported from MetadataScraper in termbeat/app.py: the tuned
// provider is polled every 30 s, every provider is swept every 10 minutes for
// listener counts, and failures back off up to 5 minutes.

import { providerOf } from "./common.js";

const TUNED_INTERVAL = 30_000;
const SWEEP_INTERVAL = 600_000;
const MAX_BACKOFF = 300_000;

const ENDPOINTS = {
  somafm: "https://api.somafm.com/channels.json",
  plaza: "https://api.plaza.one/status",
  radioparadise: "https://api.radioparadise.com/api/now_playing",
  kexp: "https://api.kexp.org/v2/plays/?limit=1",
};
const SOMAFM_CHANNEL_URL = (id) => `https://api.somafm.com/songs/${encodeURIComponent(id)}.json`;

const joinTrack = (artist, title) => {
  artist = (artist || "").trim();
  title = (title || "").trim();
  return artist && title ? `${artist} - ${title}` : (title || null);
};

export class MetadataPoller {
  constructor(onUpdate) {
    this.onUpdate = onUpdate;
    this.playlist = [];
    this.active = null;            // {provider, id}
    this.nextDue = {};
    this.backoff = {};
    this.lastSweep = 0;
    this.timer = null;
    this.enabled = false;
  }

  setPlaylist(list) { this.playlist = list; }

  setActiveStation(station) {
    const provider = providerOf(station);
    const id = station.id || null;
    if (!this.active || this.active.provider !== provider || this.active.id !== id) {
      this.active = { provider, id };
      this.nextDue.tuned = 0;
      this._kick();
    }
  }

  /** Poll only while something is playing, as the terminal app does. */
  setEnabled(on) {
    if (on === this.enabled) return;
    this.enabled = on;
    if (on) this._kick();
    else { clearTimeout(this.timer); this.timer = null; }
  }

  _kick() {
    if (!this.enabled) return;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this._tick(), 0);
  }

  async _tick() {
    const now = Date.now();
    if (now >= (this.nextDue.tuned || 0)) {
      const req = this._tunedRequest();
      if (req) await this._poll("tuned", req[0], req[1], now);
    }
    if (now - this.lastSweep >= SWEEP_INTERVAL) {
      this.lastSweep = now;
      for (const provider of Object.keys(ENDPOINTS)) {
        if (this._items(provider).length) {
          await this._poll(provider, ENDPOINTS[provider], (d) => this[`_apply_${provider}`](d), now);
        }
      }
    }
    if (this.enabled) this.timer = setTimeout(() => this._tick(), 1000);
  }

  _tunedRequest() {
    const a = this.active;
    if (!a || !(a.provider in ENDPOINTS)) return null;
    if (a.provider === "somafm" && a.id) {
      return [SOMAFM_CHANNEL_URL(a.id), (d) => this._apply_somafm_channel(d)];
    }
    return [ENDPOINTS[a.provider], (d) => this[`_apply_${a.provider}`](d)];
  }

  async _poll(slot, url, apply, now) {
    try {
      const res = await fetch(url, { cache: "no-cache", signal: AbortSignal.timeout(6000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      this.backoff[slot] = 15_000;
      this.nextDue[slot] = now + TUNED_INTERVAL;
      apply(data);
      this.onUpdate();
    } catch {
      const wait = Math.min(MAX_BACKOFF, Math.max(TUNED_INTERVAL, (this.backoff[slot] || 15_000) * 2));
      this.backoff[slot] = wait;
      this.nextDue[slot] = now + wait;
    }
  }

  _items(provider) { return this.playlist.filter((i) => providerOf(i) === provider); }

  _apply_somafm_channel(data) {
    const song = (data.songs || [])[0];
    if (!song) return;
    const track = joinTrack(song.artist, song.title);
    if (!track) return;
    for (const item of this.playlist) if (item.id === this.active.id) item.track = track;
  }

  _apply_somafm(data) {
    const channels = new Map((data.channels || []).map((ch) => [ch.id, ch]));
    for (const item of this._items("somafm")) {
      const ch = channels.get(item.id);
      if (!ch) continue;
      if (ch.lastPlaying) item.track = ch.lastPlaying;
      const listeners = parseInt(ch.listeners, 10);
      if (Number.isNaN(listeners)) continue;
      item.listeners = listeners;
      item.signal = `${Math.min(99, Math.max(88, 80 + Math.floor(listeners / 20)))}%`;
    }
  }

  _apply_plaza(data) {
    const song = data.song || {};
    const nowPlaying = joinTrack(song.artist, song.title);
    const listeners = parseInt(data.listeners, 10) || 0;
    for (const item of this._items("plaza")) {
      if (nowPlaying) item.track = nowPlaying;
      if (song.length) item.track_duration = parseInt(song.length, 10);
      if (song.position !== undefined && song.position !== null) item.track_elapsed = parseInt(song.position, 10);
      if (listeners) {
        item.listeners = listeners;
        item.signal = `${Math.min(99, Math.max(88, 80 + Math.floor(listeners / 10)))}%`;
      }
    }
  }

  _apply_radioparadise(data) {
    const track = joinTrack(data.artist, data.title);
    if (!track) return;
    for (const item of this._items("radioparadise")) {
      item.track = track;
      const t = parseInt(data.time, 10);
      if (!Number.isNaN(t) && t) item.track_duration = t;
    }
  }

  _apply_kexp(data) {
    const play = (data.results || [])[0];
    if (!play) return;
    const track = joinTrack(play.artist, play.song);
    if (!track) return;
    for (const item of this._items("kexp")) item.track = track;
  }
}
