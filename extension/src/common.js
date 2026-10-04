// Station rules shared by every extension page. Ported from termbeat/app.py
// (normalize_station, MetadataScraper.provider_of) so a station that is valid
// in the terminal app is valid here and vice versa.

import { DEFAULT_STATIONS, THEMES } from "./defaults.js";

export { DEFAULT_STATIONS, THEMES };

export const STATION_DEFAULTS = {
  id: "", station: "Unknown Station", freq: "00.0", url: "",
  bitrate: "128kbps", genre: "RADIO", signal: "95%",
  track: "No track information", provider: "generic",
};

const TEXT_KEYS = ["id", "station", "freq", "bitrate", "genre", "signal", "track", "provider"];

export const PROVIDERS = ["auto", "somafm", "plaza", "radioparadise", "kexp", "generic"];

export function isHttpUrl(url) {
  try {
    const u = new URL(String(url).trim());
    return (u.protocol === "http:" || u.protocol === "https:") && !!u.host;
  } catch {
    return false;
  }
}

/** Validate and complete one station entry; null if unusable (http(s) only). */
export function normalizeStation(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const url = String(raw.url ?? "").trim();
  if (!isHttpUrl(url)) return null;
  const item = { ...STATION_DEFAULTS };
  for (const [k, v] of Object.entries(raw)) if (v !== null && v !== undefined) item[k] = v;
  item.url = url;
  for (const k of TEXT_KEYS) item[k] = String(item[k]);
  return item;
}

export function normalizePlaylist(list) {
  if (!Array.isArray(list)) return [];
  return list.map(normalizeStation).filter(Boolean);
}

export function providerOf(item) {
  const prov = String(item.provider || "").trim().toLowerCase();
  if (prov && prov !== "generic") return prov;
  const url = item.url || "";
  for (const [name, host] of [["somafm", "somafm.com"], ["plaza", "plaza.one"],
                              ["radioparadise", "radioparadise.com"], ["kexp", "kexp.org"]]) {
    if (url.includes(host)) return name;
  }
  return prov || "generic";
}

/** The stations.json entry an add-station form describes, with a fresh id. */
export function stationEntry(fields, provider, existing) {
  const entry = { station: fields.name.trim(), url: fields.url.trim() };
  for (const k of ["freq", "genre", "bitrate"]) if (fields[k]?.trim()) entry[k] = fields[k].trim();
  if (provider && provider !== "auto") entry.provider = provider;
  if (providerOf(entry) === "somafm") {
    // SomaFM's now-playing feed is keyed by channel id: /groovesalad-128-mp3 -> groovesalad
    const path = new URL(entry.url).pathname.replace(/^\/+|\/+$/g, "");
    entry.id = path.split("/").pop().split("-")[0].split(".")[0];
  } else {
    const slug = entry.station.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "station";
    const taken = new Set(existing.map((s) => s.id));
    let sid = slug;
    for (let n = 2; taken.has(sid); n++) sid = `${slug}-${n}`;
    entry.id = sid;
  }
  return entry;
}

/** Why an add-station form can't be saved yet, or null. */
export function stationProblem(fields, existing) {
  if (!fields.name.trim()) return "name is required";
  if (!isHttpUrl(fields.url)) return "url must start with http:// or https://";
  const url = fields.url.trim();
  const dup = existing.find((s) => s.url === url);
  return dup ? `already saved as ${dup.station}` : null;
}

/** Origin match pattern for a URL, for permissions.request. */
export function originPattern(url) {
  const u = new URL(url);
  return `${u.protocol}//${u.hostname}/*`;
}

// ------------------------------------------------------------------ storage

const api = globalThis.browser ?? globalThis.chrome;

/** Defaults plus the user's own stations (kept in storage.sync). */
export async function loadStations() {
  let custom = [];
  try {
    const got = await api.storage.sync.get("customStations");
    custom = normalizePlaylist(got.customStations || []);
  } catch {
    // storage unavailable (tests, private windows): defaults only
  }
  return [...normalizePlaylist(DEFAULT_STATIONS), ...custom];
}

export async function loadCustomStations() {
  const got = await api.storage.sync.get("customStations");
  return Array.isArray(got.customStations) ? got.customStations : [];
}

export async function saveCustomStations(list) {
  await api.storage.sync.set({ customStations: list });
}
