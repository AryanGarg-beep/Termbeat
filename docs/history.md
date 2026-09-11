# termbeat — development history

How the code got to where it is. [`termbeat.md`](termbeat.md) describes the program as it stands
now; this file records what changed on the way there and why, so a decision that looks arbitrary in
the source has somewhere to be explained.

---

## Table of contents

1. [Timeline](#1-timeline)
2. [The September 2026 fix pass](#2-the-september-2026-fix-pass)
3. [What the fix pass cost](#3-what-the-fix-pass-cost)
4. [Documents that predate the repository](#4-documents-that-predate-the-repository)
5. [After the fix pass: TIDE](#5-after-the-fix-pass-tide)

---

## 1. Timeline

| When | What |
| :-- | :-- |
| — | **v1.** The original single-file TUI: 102-column fixed layout, stereo VU needles, starfield background, spectrum + oscilloscope. |
| — | **v2.** Responsive layout work (three form factors, per-width transport labels, the "terminal too small" screen), theme and design-style engines, station directory drawer, analog tuning glitch. The stereo VU meter was deleted here — though its physics kept running every frame until v3 removed them. The starfield came out over the same stretch, taking the Cyberpunk style from the most expensive renderer to one of the cheapest. |
| 2026-09-08 | **Benchmarks re-measured from scratch** — [`RESULTS.md`](RESULTS.md). An earlier internal footprint study turned out to be wrong by large factors (it put whole-system memory at ~83 MB against a real 133 MB, and blamed the renderer for costs it does not have). Everything downstream of it was re-derived from measurement. |
| 2026-09-08 → 09 | **The fix pass — v3.** §2 below. Driven by what the re-measurement actually found: the renderer was never the problem, the subprocesses and the IPC path were. |
| 2026-09-09 | **`git init`.** Until this point the only version control was hand-copied backup files in a scratch directory. Those backups are not in the repository — the changelog in §2 is what they were kept for. |
| 2026-09-09 | Repository assembled: `radio.py` plus `docs/`, `designs/`, `gui/`, `bench/`, `tests/`, and the forward-looking plans in `rs/`. |
| 2026-09-10 | **TIDE**, a fifth design style, plus four colour themes, a drawer sized to its panel, and cheaper tuning static. §5 below. |
| 2026-09-11 | **Add-station form** on `A`, and a hint bar that is never cut short. §5 below. |

## 2. The September 2026 fix pass

Every item below is a behavioural change to `radio.py`. The measured before/after is in
[`termbeat.md` §13](termbeat.md#13-performance-benchmarks).

### Correctness

- **IPC reader thread.** `StreamPlayer` now drains the mpv socket continuously and observes
  properties. Fixes the write-queue saturation that pegged mpv at 100% CPU and killed all controls
  after ~300 commands; also fixes lost/split `media-title` replies.
- **Real stream health.** `health()` + `status_badge()` + `stream_live` gating. `BUFFERING`,
  `STREAM ERROR`, `NO MPV` are now real UI states; the visualizer and elapsed timer go dead when
  audio is not actually flowing, instead of fabricating a spectrum and ticking over a dead stream.
- **`SIGHUP` handled** and **`PR_SET_PDEATHSIG`** on children — no more orphaned mpv when the
  terminal closes or the app is killed. Before this, closing the terminal window — the most common
  way people quit a TUI — left mpv still streaming from the CDN with no UI to stop it.
- **Multi-key input parser.** `parse_key_bytes` replaces the whole-buffer match; held keys and
  key-repeat work; `PAGEUP`/`PAGEDOWN`/`HOME`/`END` are reachable; split escape sequences survive.
- **`stations.json` validation** — non-`http(s)` URLs rejected, missing keys filled, no more
  `KeyError` from a hand-edited config.
- **Wall-clock animation** — `t_sec = time.monotonic() - t0` everywhere, replacing the ~12%-slow
  `frame * 0.04`.
- **Cell-accurate marquee** — `cell_slots`-based, so accented/CJK track titles no longer make the
  ticker jitter and shrink.
- **`lines[:rows]` clamp** in `run()`.
- **Combining marks are width 0** (were 2).

### Resources

- **Damage-tracked `emit_frame`** — only changed rows are written. The app had been emitting a full
  repaint 22×/second regardless: 563 KB/s while *paused*, when 0.2% of rows were changing.
- **Adaptive frame rate** — 22 FPS active, 5 FPS idle, blocking on `select(stdin)`. The old
  `time.sleep(0.045)` was unconditional.
- **Provider-scoped metadata** — tuned station every 30 s, full sweep every 10 min, backoff on
  failure; keep-alive `HttpSession`; SomaFM per-channel endpoint (911 B vs 52,751 B).
- **cava `SIGSTOP` while paused** — reclaims ~2% of a core. cava had been running FFT on silence
  forever, since nothing ever paused or stopped it.
- **Theme colour cache** used by the renderers (was rebuilt every frame).
- **`_measure` wide-char fast path** + small `lru_cache`. Width measurement was 55% of render time.
- **`apply_monstercat_filter`** pow lookup table.

### Removed (verified dead)

- Four single-row visualizer wrappers (`get_equalizer_row`, `get_oscilloscope_row`,
  `get_braille_wave_row`, `get_tuning_glitch_row`) — each generated a whole frame to return one row;
  zero call sites.
- `activate_focused_button` + `focused_btn` — button-focus navigation removed earlier; the state
  was initialised and never mutated.
- Stereo VU meter physics (`vu_left`/`vu_right`/`vu_peak`) — the meter that consumed it was deleted
  in v2; the physics still ran every frame.
- `_start_mpv` — renamed `_spawn_mpv` and rewritten.

### New infrastructure

- File logger at `~/.local/state/termbeat/termbeat.log` (`TERMBEAT_DEBUG` for verbosity).
- `_runtime_dir()` — per-user 0700 directory for the socket and cava config.
- [`tests/test_termbeat.py`](../tests/test_termbeat.py) — 16 checks. [`bench/`](../bench/) harnesses
  updated.

## 3. What the fix pass cost

`radio.py` process RSS rose **34.7 MB → ~40.4 MB** (+5.7). Of that, ~3.0 MB is the new stdlib
imports (`logging`, `ctypes`, `http.client`, `urllib.parse`), ~0.5 MB the compiled wide-character
regex, the rest two extra threads and the caches. Thread count 3 → 5.

This was accepted deliberately: the regression buys logging, child reaping, and the IPC fix, and it
is small next to what the same pass removed elsewhere — CPU while paused fell 6.5% → 0.8%, and PTY
output fell from 563 KB/s to ~0.1 KB/s.

One thing the pass deliberately did **not** touch: `TermbeatPlayer` is still one ~1,700-line class
owning state, input, physics, four renderers, and lifecycle, and the four renderers still share
~70% of their structure by convention rather than through a layout engine. Splitting it up would
have made the diff unreviewable. It remains open — see
[`../rs/improvement-ideas.md`](../rs/improvement-ideas.md).

## 4. Documents that predate the repository

Before `git init` the project was worked on in a scratch directory, and each change was written up
as its own standalone plan document. Those files were **not** carried into the repository; they are
listed here because their titles are the only remaining record of the order things happened in, and
because a few describe work that is still visible in the code:

| Document | Subject |
| :-- | :-- |
| `tui_design_study_and_responsive_layouts_plan` | the three responsive form factors |
| `responsive_ui_fixes_plan` | follow-up fixes to the above |
| `resource_footprint_and_optimization_study_plan` | the footprint study later superseded by [`RESULTS.md`](RESULTS.md) |
| `row_indexed_star_caching_plan` | an optimisation for the starfield, obsoleted by removing it |
| `remove_starfield_plan` | removing the starfield background |
| `comprehensive_optimization_plan` | the umbrella optimisation pass |
| `remove_tab_enter_plan` | removing button-focus navigation (`Tab`/`Enter`) |
| `tuning_glitch_plan` | the analog static effect on station change |
| `tui_and_visualizer_design_ideas_plan` | the idea backlogs now kept in [`../rs/`](../rs/) |
| `walkthrough` | an early narrated read-through of the code |

Anything worth keeping from them has been folded into
[`termbeat.md`](termbeat.md), [`RESULTS.md`](RESULTS.md), or this file. New work is written up in
`docs/` from here on rather than as loose plan files.

## 5. After the fix pass: TIDE

Changes to `radio.py` after the repository was assembled. How TIDE works is in
[`termbeat.md` §9.7](termbeat.md#97-the-tide-renderer).

### Added

- **TIDE**, a fifth design style (`D`). The station name is drawn as large 5×7 bitmap type on a
  half-pixel raster, each letter flooding with its slice of the spectrum over a gradient fixed in
  frame space. New module-level primitives: `FONT_5X7`, `Pix`, `draw_word`. It reuses
  `band_heights`/`peak_heights`, the transport bar, the status badge, the drawer and the tuning
  glitch. No physics, threads or dependencies were added, and `emit_frame` is unchanged.
- **Four colour themes**: Blue Hour, Ultraviolet, Ember, Deep Field. The original five are unchanged.
- **Add-station form** on `A`: name, stream URL, freq, genre, bitrate and provider, validated as you
  type. `Enter` appends the station to `stations.json` and tunes to it. The file is only ever
  appended to, and a file that doesn't parse is never overwritten. This is backlog idea 7.2, built
  from the `gui/station_editor.py` mock-up without its `Ctrl-S` save, which the terminal's XON/XOFF
  flow control would swallow.

### Changed

- **The drawer fills its panel.** `render_drawer_rows` takes a `max_rows` from each caller instead
  of always showing 7 stations. Tall panels were mostly empty, and in panels shorter than 8 rows
  (Minimal Zen at 70×18, the Deck-78 LCD) the selection could scroll out of view. `PageUp`/`PageDown`
  now step by the page actually shown.
- **Tuning static is 2.3× cheaper to generate.** `get_tuning_glitch_rows` calls `random.choices`
  once per row instead of `random.choice` once per cell. The noise looks the same.
- **The hint bar is never cut short.** `render_status_bar` picks the fullest of five wordings that
  fits, and every chassis style now shows `[A] Add`. It had been truncated at some sizes: Modern Neo
  at 70 columns, and the standard deck's own bar, which lost `[M] Mute` and `[Q] Quit`.
- **Pastes survive in the form.** The 32-keys-per-frame input cap is lifted while the form is open,
  so a pasted URL arrives whole.

### Decisions worth recording

- **TIDE binds bands by horizontal position, not reading order.** The design brief assumed the
  readable signal in real cava output would be a spectral tilt, and asked for low bands under the
  first letters. Seen next to the Retro visualizer on a live station, the real signal was a centre
  hump, and reading order folded it at a line break: the peaks landed at the end of one line and the
  start of the next. Position-based binding puts the middle of the spectrum in the middle of the
  screen on every line.
- **`TIDE_EXPAND` is 1.25, not 1.8.** The stretch that separates correlated bands clipped the quiet
  ends to dark and pegged the loud middle full at 1.8.
- **`Pix` and `draw_word` are module-level**, next to `fit_row`. The brief placed them in the
  `get_*_rows` block, but that block is inside `TermbeatPlayer`.
- **`draw_word` calls its colour function per pixel**, as the brief specified. That callback is
  most of TIDE's render time (up to 1.4 ms/frame at 200×60). Calling it once per font-pixel row
  instead would cut the calls 2–6× but break the contract, so it was left.

### Tests and benchmark

- **`tests/test_termbeat.py`: 16 → 29 checks.** The layout check loops over all five styles. New
  checks cover:
  - TIDE's exact frame size in every theme, size, station and state
  - TIDE's bands in horizontal order, all 18 on screen
  - the name staying drawn but unflooded in silence
  - near-silence while paused
  - the drawer keeping its selection on screen in every style
  - `[A] Add` in an uncut hint bar in every chassis style
  - the add-station form (7 checks), run against a temporary config directory

  Each new check was confirmed to fail against the bug it guards.
- **Fixed a flaky existing check.** "Paused steady state is nearly silent" waited a fixed 40 frames
  after pausing, but a peak-hold cap can take 55 to fall. Whenever the random spectrum paused on a
  tall peak, the cap was still moving during the measured window, and the check failed (1 run in 15
  here). It now waits until the bars and caps are down.
- **`bench/benchmark_render.py` includes TIDE**, one row per size because it ignores `V`. At
  200×60 it is the benchmark's worst config: 1.40 ms, 3.0% of one core.

### Still open

- Retro Hi-Fi's Studio Tower layout never draws the drawer, so `L` there opens an invisible one
  ([`termbeat.md` §15](termbeat.md#15-known-limitations-and-non-goals)).
- The add-station form only adds. Editing or removing a station still means editing
  `stations.json` by hand.
