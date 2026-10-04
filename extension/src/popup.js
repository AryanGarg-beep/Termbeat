// Toolbar popup: a compact remote for the audio host, plus a mini spectrum.

import { HostClient } from "./client.js";

const api = globalThis.browser ?? globalThis.chrome;
const $ = (id) => document.getElementById(id);
const pad2 = (n) => String(n).padStart(2, "0");

let snap = null;
let bands = new Array(18).fill(0);
let bandsLive = false;
let shown = new Array(18).fill(0);
let draggingVolume = false;

const client = new HostClient({
  wantBands: true,
  onState: render,
  onBands: (b, live) => { bands = b; bandsLive = live; },
});

function render(s) {
  snap = s;
  const st = s.stations[s.idx] || {};
  $("station").textContent = st.station || "—";
  $("track").textContent = st.track || "";
  $("track").title = st.track || "";
  const el = s.trackElapsed || 0;
  const dur = s.trackDuration;
  $("time").textContent = s.stopped ? "" :
    `${pad2(Math.floor(el / 60))}:${pad2(el % 60)}${dur ? ` / ${pad2(Math.floor(dur / 60))}:${pad2(dur % 60)}` : "  [LIVE]"}`;

  const badge = $("badge");
  let text, cls = "";
  if (s.stopped) { text = "■ STOPPED"; cls = "err"; }
  else if (s.health === "STREAM ERROR") { text = "✖ STREAM ERROR"; cls = "err"; badge.title = s.error || ""; }
  else if (!s.playing) text = "❚❚ PAUSED";
  else if (s.health === "PLAYING") { text = "● PLAYING"; cls = "play"; }
  else text = "◌ BUFFERING";
  badge.textContent = text;
  badge.className = `badge ${cls}`;

  const on = s.playing && !s.stopped;
  $("play").textContent = on ? "❚❚" : "▶";
  $("play").classList.toggle("on", on);
  $("mute").classList.toggle("on", s.muted);
  if (!draggingVolume) $("volume").value = s.volume;
  $("volnum").textContent = s.muted ? "MUTE" : `${s.volume}%`;

  const sel = $("stations");
  const names = s.stations.map((x, i) => `${pad2(i + 1)}. ${x.station}`);
  if (sel.options.length !== names.length || [...sel.options].some((o, i) => o.text !== names[i])) {
    sel.replaceChildren(...names.map((n, i) => new Option(n, String(i))));
  }
  sel.value = String(s.idx);
}

// mini spectrum: the same bars the deck shows, smoothed, without the deck
function drawBars() {
  const c = $("bars");
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height;
  ctx.clearRect(0, 0, w, h);
  const playing = snap && snap.playing && !snap.stopped && snap.health === "PLAYING";
  const t = performance.now() / 1000;
  for (let i = 0; i < 18; i++) {
    let target = 0;
    if (playing) {
      target = bandsLive ? bands[i]
        : Math.max(0.08, 0.35 + Math.sin(t * (3 + i * 0.4) + i) * 0.2 + Math.cos(t * 2.1 + i * 0.7) * 0.12);
    }
    shown[i] += (target - shown[i]) * (target > shown[i] ? 0.6 : 0.15);
    const bw = w / 18;
    const bh = Math.round(shown[i] * h);
    const y = h - bh;
    ctx.fillStyle = "rgb(55,255,95)";
    ctx.fillRect(Math.round(i * bw) + 2, y, Math.ceil(bw) - 4, bh);
    if (bh > h * 0.75) { ctx.fillStyle = "rgb(255,210,40)"; ctx.fillRect(Math.round(i * bw) + 2, y, Math.ceil(bw) - 4, Math.min(bh, 4)); }
  }
  requestAnimationFrame(drawBars);
}

$("prev").onclick = () => client.cmd("prev");
$("next").onclick = () => client.cmd("next");
$("play").onclick = () => client.cmd("toggle_play");
$("stop").onclick = () => client.cmd("stop");
$("mute").onclick = () => client.cmd("mute");
$("volume").addEventListener("input", (e) => { draggingVolume = true; client.cmd("set_volume", Number(e.target.value)); });
$("volume").addEventListener("change", () => { draggingVolume = false; });
$("stations").onchange = (e) => client.cmd("tune", Number(e.target.value));
$("options").onclick = () => api.runtime.openOptionsPage();
$("open").onclick = async () => {
  const url = api.runtime.getURL("player.html");
  let tab = null;
  try {
    [tab] = await api.tabs.query({ url });
  } catch { /* can't see tab urls: open a new one */ }
  if (tab) {
    await api.tabs.update(tab.id, { active: true });
    await api.windows.update(tab.windowId, { focused: true });
  } else {
    await api.tabs.create({ url });
  }
  window.close();
};

document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT") return;
  const k = e.key.toLowerCase();
  const map = { " ": "toggle_play", n: "next", p: "prev", s: "stop", m: "mute" };
  if (map[k]) { e.preventDefault(); client.cmd(map[k]); }
  else if (k === "+" || k === "=" ) client.cmd("volume", 5);
  else if (k === "-") client.cmd("volume", -5);
});

client.connect();
requestAnimationFrame(drawBars);
