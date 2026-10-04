// Extension test suite. Run: node extension/tests/test_extension.js
// Covers the text helpers, station rules, and - the important one - that the
// JS deck renders the same text as termbeat/app.py for the same state.

import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { strWidth, fitRow, truncateAnsi, parseRow, cellSlots, center, fg, RST, stripAnsi } from "../src/term.js";
import { normalizeStation, normalizePlaylist, providerOf, stationEntry, stationProblem, originPattern } from "../src/common.js";
import { makeBandBins } from "../src/audio-engine.js";
import { Deck } from "../src/deck.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const failures = [];
function check(cond, label, detail = "") {
  console.log(`  ${cond ? "ok  " : "FAIL"}  ${label}${cond || !detail ? "" : `   ${detail}`}`);
  if (!cond) failures.push(label);
}

console.log("termbeat extension tests\n" + "=".repeat(70));

// ------------------------------------------------------------------ term.js
check(strWidth(`${fg(1, 2, 3)}ab${RST}c`) === 3, "strWidth ignores escapes");
check(strWidth("日本") === 4 && strWidth("é") === 1, "strWidth counts wide and combining characters");
check(strWidth(fitRow(`${fg(1, 2, 3)}hello`, 10)) === 10, "fitRow pads to the exact width");
check(strWidth(fitRow("日本語テキスト", 5)) <= 5, "fitRow never overflows on wide text");
check(truncateAnsi(`${fg(9, 9, 9)}abcdef`, 3)[0].startsWith(fg(9, 9, 9) + "abc"), "truncateAnsi keeps escapes whole");
check(JSON.stringify(cellSlots("a日b")) === JSON.stringify(["a", "日", "", "b"]), "cellSlots gives wide glyphs a continuation slot");
check(center("ab", 7) === "   ab  " && center("abc", 8) === "  abc   " && center("abc", 6) === " abc  ",
      "center matches Python str.center");
{
  const cells = parseRow(`${fg(255, 0, 0)}\x1b[1mA\x1b[22m${RST}B日`, 10);
  check(cells.length === 4 && cells[0].fg[0] === 255 && cells[0].bold && !cells[1].fg && cells[3].ch === "",
        "parseRow decodes truecolor, bold, reset and wide cells");
}

// ---------------------------------------------------------------- common.js
check(normalizeStation({ station: "x", url: "file:///etc/passwd" }) === null, "stations reject non-http urls");
check(normalizePlaylist([{ station: "A", url: "https://a/s" }, "junk", { station: "B" }]).length === 1,
      "playlist drops unusable entries");
check(providerOf({ url: "https://ice1.somafm.com/x" }) === "somafm" && providerOf({ provider: "KEXP", url: "" }) === "kexp",
      "providerOf infers from the url and honours an explicit provider");
check(stationEntry({ name: "Groove", url: "https://ice2.somafm.com/groovesalad-256-mp3" }, "auto", []).id === "groovesalad",
      "a SomaFM station gets its channel id");
check(stationEntry({ name: "My Jazz", url: "https://x/y" }, "auto", [{ id: "my-jazz" }]).id === "my-jazz-2",
      "a generic station gets a unique slug id");
check(stationProblem({ name: "", url: "https://x" }, []) === "name is required" &&
      stationProblem({ name: "a", url: "ftp://x" }, []).startsWith("url must") &&
      stationProblem({ name: "a", url: "https://x/s" }, [{ url: "https://x/s", station: "Dup" }]) === "already saved as Dup",
      "add-station validation matches the terminal form");
check(originPattern("https://radio.example.com:8443/live.mp3") === "https://radio.example.com/*", "origin pattern for permissions");

// ----------------------------------------------------------- audio-engine.js
{
  const bins = makeBandBins(48000, 4096, 18);
  const ok = bins.length === 18 && bins.every(([lo, hi], i) => hi > lo && (i === 0 || lo >= bins[i - 1][1]));
  check(ok, "spectrum bands are 18 contiguous, non-empty bin ranges", JSON.stringify(bins));
}

// ------------------------------------------------------------- deck parity
const STATE = {
  volume: 75, trackElapsed: 83, tSec: 0.3, energy: [0.4, 0.3, 0.2],
  bands: [7.5, 6, 5.2, 4, 3.3, 2.5, 4.1, 5, 6.2, 3, 2, 1.5, 1, 0.8, 2.2, 3.3, 1.1, 0.5],
  peaks: [8, 6.5, 5.5, 4.5, 3.6, 2.9, 4.4, 5.3, 6.5, 3.4, 2.2, 1.8, 1.4, 1.0, 2.6, 3.6, 1.5, 0.9],
};
const CASES = [
  { name: "standard 110x30 spectrum", cols: 110, rows: 30, viz: 0, drawer: false },
  { name: "standard 110x30 scope", cols: 110, rows: 30, viz: 1, drawer: false },
  { name: "standard 120x24 drawer", cols: 120, rows: 24, viz: 0, drawer: true, sel: 3 },
  { name: "deck-78 90x24 spectrum", cols: 90, rows: 24, viz: 0, drawer: false },
  { name: "deck-78 80x20 drawer", cols: 80, rows: 20, viz: 0, drawer: true, sel: 6 },
  { name: "tower 104x36 spectrum", cols: 104, rows: 36, viz: 0, drawer: false },
  { name: "tower 101x54 scope", cols: 101, rows: 54, viz: 1, drawer: false, theme: 4 },
];

let ref;
try {
  const out = execFileSync("python3", [path.join(HERE, "py_frames.py"), JSON.stringify(STATE), JSON.stringify(CASES)],
                           { encoding: "utf-8", maxBuffer: 1 << 24 });
  ref = JSON.parse(out);
} catch (err) {
  check(false, "python reference frames", String(err.message || err).split("\n")[0]);
}

if (ref) {
  const fakeClient = { cmd() {} };
  for (const c of CASES) {
    const deck = new Deck(fakeClient);
    deck.setSnapshot({
      stations: ref.stations, idx: 0, volume: STATE.volume, prevVolume: 75, muted: false, playing: true,
      stopped: false, repeat: true, health: "PLAYING", error: "", trackElapsed: STATE.trackElapsed,
      trackDuration: null, tunedAt: 1,
    });
    deck.tSec = STATE.tSec;
    deck.bandHeights = STATE.bands.slice();
    deck.peakHeights = STATE.peaks.slice();
    [deck.bassEnergy, deck.midEnergy, deck.trebleEnergy] = STATE.energy;
    deck.vizMode = c.viz;
    deck.themeIdx = c.theme || 0;
    if (c.drawer) { deck.showDrawer = true; deck.drawerSelected = c.sel || 0; deck.drawerScroll = 0; }
    const js = deck.render(c.cols, c.rows).map(stripAnsi);
    const py = ref.frames[c.name].slice(0, js.length);
    // the Python app pads to the terminal height; the canvas does not need it
    while (py.length && py[py.length - 1] === "" && py.length > js.length) py.pop();
    const diff = [];
    for (let i = 0; i < Math.max(js.length, py.length); i++) {
      if ((js[i] ?? "").trimEnd() !== (py[i] ?? "").trimEnd()) {
        diff.push(`row ${i}:\n      py |${py[i]}|\n      js |${js[i]}|`);
      }
    }
    check(diff.length === 0, `deck matches the terminal app: ${c.name}`, diff.length ? `\n    ${diff.slice(0, 3).join("\n    ")}` : "");
    const widths = js.filter((l) => l.length).map((l) => strWidth(l));
    const want = Math.max(...widths);
    check(widths.every((w) => w === want), `every row has the same width: ${c.name}`);
  }
}

console.log("=".repeat(70));
if (failures.length) {
  console.log(`${failures.length} FAILED`);
  process.exit(1);
}
console.log("all checks passed");
