# termbeat

A retro hi-fi internet-radio player that runs entirely in a terminal.

`termbeat/app.py` paints a 1980s stereo receiver with raw ANSI escape codes and plays curated,
commercial-free internet-radio streams behind it. One file, ~3,800 lines, **pure Python 3
standard library — no pip install, no build step, no virtualenv.**

The two genuinely hard jobs are handed to external programs driven as subprocesses:

| Job | Owner | How it's driven |
| :-- | :-- | :-- |
| HTTP streaming + MP3/AAC decode + audio out | `mpv` | JSON IPC over a private UNIX socket |
| Real-time audio spectrum (FFT of the sound card) | `cava` | generated temp config, bar values over a pipe |
| Now-playing track titles | four public HTTP APIs | keep-alive JSON polling, tuned station only |
| Layout, physics, input, lifecycle | `termbeat/app.py` | one adaptive-rate ANSI repaint loop |

Both external programs are **optional**. Without `mpv` the UI runs silently and says `NO MPV`;
without `cava` the spectrum falls back to a synthesised animation.

---

## Features

- **16 preset stations** — SomaFM, Nightwave Plaza, Radio Paradise, KEXP — extendable via
  `~/.config/termbeat/stations.json`, which is picked up when you open the station list.
- **5 design aesthetics** (`d`): Retro Hi-Fi, Modern Neo, Minimal Zen, Cyberpunk, and TIDE, which
  sets the station name as large bitmap type and floods each letter with its slice of the spectrum.
- **9 colour themes** (`t`): Classic Tuna, Cyberpunk, Amber CRT, Matrix, Synthwave, Blue Hour,
  Ultraviolet, Ember, Deep Field.
- **2 visualizers** (`v`): 18-band spectrum analyser and an oscilloscope; Modern Neo and Cyberpunk
  substitute a sub-pixel Braille waveform (2×4 dots per cell). TIDE is its own visualizer.
- **Responsive layout** — three retro form factors (Studio Tower, Deck-78, the fixed 102-column
  standard deck) with per-width transport-button labels, plus a "terminal too small" screen
  below 70×18.
- **Live stream health** in the header (`PLAYING` / `BUFFERING` / `PAUSED` / `STOPPED` /
  `STREAM ERROR` / `NO MPV`), derived from mpv's actual state rather than the app's intent.
- **Add stations from inside the app** (`a`): a form that checks the URL, appends the station to
  `stations.json`, and tunes to it.
- Station directory drawer sized to the panel it opens in, analog tuning static-glitch on station
  change, elapsed timer with a wall-clock-blinked colon, 24-slot volume slider, mute.

## Requirements

| | |
| :-- | :-- |
| **Python** | 3.9+ |
| **Terminal** | ANSI + 24-bit truecolor, UTF-8, ≥ 70×18 cells |
| **`mpv`** | optional, for audio — any build with `--input-ipc-server` |
| **`cava`** | optional, for the real spectrum — needs a PulseAudio/PipeWire monitor source |
| **OS** | Linux, macOS, Windows 10+ |

## Installing

```sh
pipx install termbeat        # or: uv tool install termbeat
termbeat
```

For audio and the real spectrum, also install `mpv` and `cava` (both optional):

| OS | Command |
| :-- | :-- |
| Arch | `sudo pacman -S mpv cava` |
| Debian / Ubuntu | `sudo apt install mpv cava` |
| macOS | `brew install mpv cava` |
| Windows | `winget install mpv` (or `scoop install mpv`); cava has no Windows build, so the spectrum is synthesised. Use Windows Terminal. |

Prefer not to install anything? The deck also runs as a [browser extension](#browser-extension).

## Running from source

```sh
python3 radio.py             # or: python3 -m termbeat
```

First run writes `~/.config/termbeat/stations.json` with the defaults and
`~/.local/state/termbeat/termbeat.log` for diagnostics. stdout is the UI, so nothing is ever
printed there — the log is the only diagnostic channel.

## Keybindings

| Key | Action |
| :-- | :-- |
| `Space` | Play / Pause |
| `n` / `→` | Next station |
| `p` / `←` | Previous station |
| `s` | Stop (tears the stream down; `Space` re-tunes) |
| `↑` `+` `=` | Volume +5 |
| `↓` `-` `_` | Volume −5 |
| `m` | Mute / unmute |
| `r` | Toggle loop indicator |
| `1`–`9` | Jump to preset *n* |
| `v` | Cycle visualizer |
| `t` | Cycle colour theme |
| `d` | Cycle design aesthetic |
| `l` | Open / close the station directory drawer |
| `a` | Add a station (`Enter` saves and tunes, `Esc` cancels) |
| `q` / `Ctrl-C` / `Esc` | Quit (`Esc` closes the drawer or the add-station form first) |

## Configuration

Stations live in `~/.config/termbeat/stations.json` (or `$XDG_CONFIG_HOME/termbeat/`) as a JSON
array. Press `a` to add one from the app, or edit the file; the app picks it up the next time you
open the station list. Every entry needs an `http`/`https` `url`; missing keys are filled from defaults, and
unusable entries are dropped rather than crashing the UI. Recognised keys: `id`, `station`,
`freq`, `url`, `bitrate`, `genre`, `signal`, `track`, `provider`.

| Environment variable | Effect |
| :-- | :-- |
| `TERMBEAT_DEBUG=1` | log at `DEBUG` instead of `INFO` |
| `TERMBEAT_AMBIGUOUS_WIDTH=2` | treat East-Asian Ambiguous glyphs as 2 cells |
| `XDG_CONFIG_HOME` | base for `stations.json` (Windows default: `%APPDATA%`) |
| `XDG_STATE_HOME` | base for the log file (Windows default: `%LOCALAPPDATA%`) |
| `XDG_RUNTIME_DIR` | base for the mpv socket and cava config (Windows uses a named pipe instead) |

Full details — validation rules, every file created, and when each is cleaned up — are in
[`docs/termbeat.md` §11](docs/termbeat.md).

---

## Browser extension

The same deck runs in Chrome, Edge, Brave and Firefox with nothing else to install. The browser
streams and decodes the audio and does the FFT, so neither mpv nor cava is needed.

- **Full player tab.** The Retro Hi-Fi deck in all three form factors, all 9 themes, the
  spectrum and oscilloscope, the station drawer, and the same keys as the terminal app.
- **Toolbar popup.** Play/pause, previous/next, stop, volume, a station picker and a mini spectrum.
- **Keeps playing** after every termbeat tab is closed. On Chrome/Edge an offscreen document
  hosts the audio; on Firefox it's the background page. `Q` stops playback and closes the tab.
- **Your own stations** are added on the options page (`A` in the player opens it) and sync
  through your browser account.
- **Spectrum.** It's real wherever the stream allows it, which includes all 16 built-in stations.
  For other stations it's simulated, the same fallback the terminal app uses without cava.
- **Not yet ported:** the Modern Neo, Minimal Zen, Cyberpunk and TIDE styles (`D` says so).

Build and load it from source:

```sh
python3 tools/build_extension.py     # -> build/extension/{chrome,firefox}/ and dist/termbeat-*.zip
```

- **Chrome / Edge / Brave:** open `chrome://extensions`, turn on Developer mode, choose
  *Load unpacked*, and select `build/extension/chrome`.
- **Firefox:** open `about:debugging#/runtime/this-firefox`, choose *Load Temporary Add-on*, and
  select `build/extension/firefox/manifest.json`.

The two builds share every file in `extension/src/` and differ only in the manifest. Chrome gets
Manifest V3 with an offscreen audio document. Firefox gets Manifest V2 with a persistent
background page, because Firefox unloads an idle MV3 background, which would stop the music. Built-in
stations and themes come from `termbeat/app.py` through `tools/export_stations.py`, so the two
apps can't drift apart. `extension/tests/test_extension.js` renders the deck in JS and in Python
from the same state and checks that every row matches.

### Publishing

Pushing an `ext-v*` tag (for example `ext-v1.0.0`) builds both zips and attaches them to a GitHub
release. Store submission is manual:

| Store | Upload | Account |
| :-- | :-- | :-- |
| [Chrome Web Store](https://chrome.google.com/webstore/devconsole) | `termbeat-chrome-*.zip` | one-time $5 developer fee |
| [Edge Add-ons](https://partner.microsoft.com/dashboard/microsoftedge) | `termbeat-chrome-*.zip` | free |
| [Firefox Add-ons (AMO)](https://addons.mozilla.org/developers/) | `termbeat-firefox-*.zip` | free |

Each listing asks for a privacy statement. termbeat collects nothing: it only fetches the streams
and the stations' public now-playing APIs, and it stores your settings and stations in your own
browser. The Firefox manifest already declares no data collection.

---

## Repository layout

```
termbeat/app.py   the entire application
radio.py          launcher for running from a source checkout
pyproject.toml    PyPI packaging (`termbeat` command)
extension/    browser extension: src/ (shared by Chrome and Firefox), tests/
tools/        export_stations.py (app -> extension defaults), build_extension.py
docs/         ← all project documentation lives here
                termbeat.md   the reference — how it works today
                history.md    how it got here
                RESULTS.md    the benchmark run behind both
designs/      runnable visualizer sketches (synthetic audio, no mpv/cava/network)
gui/          runnable interface mock-ups (fake player state, no audio)
bench/        render and whole-system benchmark harnesses
tests/        standard-library test suite
rs/           planning docs for a possible Rust rewrite
```

**`docs/` is the canonical place for written work on this project.** Anything in-depth — design
notes, investigations, measurements, decisions, changelogs — is written up there and kept current;
this README stays a summary and points into it.

| Document | What's in it |
| :-- | :-- |
| [`docs/termbeat.md`](docs/termbeat.md) | The reference. Architecture, threads and data flow, the audio and spectrum engines, metadata scraping, input, the render pipeline, physics, config, lifecycle, benchmarks, security, code map. |
| [`docs/history.md`](docs/history.md) | How the code got here — the timeline, the September 2026 fix pass changelog, what it cost, and what predates the repository. |
| [`docs/RESULTS.md`](docs/RESULTS.md) | The raw benchmark run — frame times, byte rates, per-process RSS/CPU, profiles, process-lifecycle leaks. |

Ideas backlogs for future work sit in [`rs/`](rs/): [`improvement-ideas.md`](rs/improvement-ideas.md),
[`visualizer-ideas.md`](rs/visualizer-ideas.md), [`gui-ideas.md`](rs/gui-ideas.md), and
[`rust-rewrite-plan.md`](rs/rust-rewrite-plan.md).

---

## Development

```sh
python3 tests/test_termbeat.py     # test suite — row widths, TIDE, drawer, station form, key parsing, marquee, config, diff renderer, Windows portability
node extension/tests/test_extension.js   # extension: text helpers, station rules, deck parity with the Python renderer
python3 bench/benchmark_render.py  # render path in isolation (mpv/cava/metadata stubbed)
python3 bench/benchmark_system.py  # real app in a pty: RSS, CPU, pty byte rate, playing vs paused
```

Prototypes run standalone, against fake audio and fake player state, so an idea can be seen before
it is wired into `radio.py`:

```sh
python3 designs/gallery.py         # flip through every visualizer sketch
python3 gui/gallery.py             # launcher menu for the interface mock-ups
python3 designs/_selftest.py       # headless: drive every sketch, check nothing breaks
python3 gui/_selftest.py
```

See [`designs/README.md`](designs/README.md) and [`gui/README.md`](gui/README.md) for what each
sketch is and which keys it responds to.

### Performance, in short

The renderer is **not** a bottleneck: the four chassis styles take at most ~0.5 ms/frame (~1% of
one core), and TIDE, the most expensive, 1.4 ms at 200×60 (~3%), against a 22 FPS need. The footprint is dominated by the subprocesses — of ~133 MB
total, `mpv` is 86 MB and `cava` 13 MB, leaving `radio.py` at 35 MB. Numbers, methodology and the
known issues they surfaced are in [`docs/RESULTS.md`](docs/RESULTS.md).
