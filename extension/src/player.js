// The full-tab player: keyboard in, canvas out. Audio lives in the host, so
// closing this tab keeps the music playing; Q stops it and closes the tab.

import { CanvasTerm } from "./term.js";
import { Deck, ACTIVE_FRAME_MS, IDLE_FRAME_MS } from "./deck.js";
import { HostClient } from "./client.js";

const api = globalThis.browser ?? globalThis.chrome;

const KEY_NAMES = {
  " ": "SPACE", ArrowUp: "UP", ArrowDown: "DOWN", ArrowLeft: "LEFT", ArrowRight: "RIGHT",
  Enter: "ENTER", Escape: "ESC", Tab: "TAB", Backspace: "BACKSPACE",
  PageUp: "PAGEUP", PageDown: "PAGEDOWN", Home: "HOME", End: "END",
};

const canvas = document.getElementById("screen");
const term = new CanvasTerm(canvas, [7, 10, 16]);
const client = new HostClient({
  wantBands: true,
  autoplay: true,                 // opening the player is launching the app
  onState: (snap) => { deck.setSnapshot(snap); wake(); },
  onBands: (bands, live) => deck.setBands(bands, live),
});
const deck = new Deck(client);

let timer = null;
function frame() {
  timer = null;
  deck.updatePhysics();
  term.draw(deck.render(term.cols, term.rows));
  timer = setTimeout(frame, deck.active ? ACTIVE_FRAME_MS : IDLE_FRAME_MS);
}
function wake() {
  if (timer !== null) clearTimeout(timer);
  timer = setTimeout(frame, 0);
}

function fit() {
  term.resize(window.innerWidth, window.innerHeight);
  wake();
}
window.addEventListener("resize", fit);

let toastTimer = null;
function toast(text) {
  const el = document.getElementById("toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2200);
}

window.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;          // leave browser shortcuts alone
  const key = KEY_NAMES[e.key] ?? (e.key.length === 1 ? e.key : null);
  if (!key) return;
  e.preventDefault();
  if (key === "a" || key === "A") {
    api.runtime.openOptionsPage();
    return;
  }
  if ((key === "d" || key === "D")) {
    toast("More deck styles are coming to the browser version");
    return;
  }
  if (!deck.handleKey(key)) {
    client.cmd("stop");
    setTimeout(() => window.close(), 50);
    return;
  }
  wake();
});

// stations added in the options page show up without a reload
api.storage.onChanged.addListener((changes, area) => {
  if (area === "sync" && changes.customStations) client.reloadStations();
});

fit();
canvas.focus();
client.connect().catch((err) => toast(`could not reach the audio host: ${err}`));
