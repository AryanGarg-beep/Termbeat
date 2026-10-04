# termbeat (Python) — Improvement Ideas

*Companion to [`../docs/termbeat.md`](../docs/termbeat.md) and
[`rust-rewrite-plan.md`](rust-rewrite-plan.md). This is a backlog of
options for the current Python version, not a commitment to any of them. Nothing here is
started.*

---

## Context

`radio.py` is in good shape after the September 2026 fix pass: the correctness and resource
bugs are closed, there is a test suite (`tests/test_termbeat.py`, 16 checks) and benchmarks
(`bench/`), and reference documentation under [`../docs/`](../docs/). This document is a *what next*
menu for the Python version specifically — the Rust option is covered separately in
[`rust-rewrite-plan.md`](rust-rewrite-plan.md).

Items are ordered cheap-and-certain first, speculative last. Each carries a rough
**value** / **effort** read.

---

## Tier 0 — hygiene (minutes, worth doing regardless)

| # | Idea | Why | Value / Effort |
| :-- | :-- | :-- | :-- |
| ~~0.1a~~ | ~~`git init`, first commit~~ | **done** — 2026-09-09 | — |
| ~~0.2~~ | ~~`README.md` at repo root~~ | **done** — see [`../README.md`](../README.md) | — |
| 0.1b | `.gitignore` (`__pycache__/`, `*.pyc`, `.~lock.*#`) | the repo has none, so every `designs/`/`gui/`/`tests/` run leaves `__pycache__` staged | high / trivial |
| 0.3 | `pyproject.toml` + `__main__.py` shim so `pipx install .` / `python -m termbeat` works, keeping the single file | installable without losing the "one file, no pip" property | med / low |
| 0.4 | CI (GitHub Actions or equivalent) running `tests/test_termbeat.py` + a headless render smoke on push | the suite exists but nothing runs it automatically | med / low |
| 0.5 | `LICENSE` | it has none | low / trivial |

---

## Tier 1 — quick wins in the code (each roughly < 40 lines)

| # | Idea | Detail | Value / Effort |
| :-- | :-- | :-- | :-- |
| 1.1 | **CLI flags** via `argparse` in `main()` (`radio.py:3130`) | `--station <name\|freq>`, `--style`, `--theme`, `--no-audio`, `--list`, `--log-level`. There is currently zero argv handling. | high / low |
| 1.2 | **Poll the config mtime from the main loop**, not only on drawer open | `check_reload_stations` is called only from `toggle_drawer` (`radio.py:1693`), so an edit to `stations.json` while the drawer is closed is invisible until you open it. Call it every ~2 s from `run()`, debounced. | med / low |
| 1.3 | **Cache the terminal size** | `shutil.get_terminal_size()` is an `ioctl` on every frame (`radio.py:2440`). Refresh only when the `SIGWINCH` flag (`needs_clear`) is set, plus a 1 Hz safety re-check. | low / low |
| 1.4 | **Truecolor detection + 256-color fallback** | `fg`/`bg` hardcode `38;2;` / `48;2;` (`radio.py:424`). Check `$COLORTERM in ("truecolor", "24bit")`; if absent, quantise each RGB triple to the xterm-256 cube. Without this, a non-truecolor terminal renders raw escape bytes / wrong colour. | med / med |
| 1.5 | **Lazy-import `ctypes` and `http.client`** | `ctypes.CDLL` runs at import (`radio.py:75`) even with no `mpv`; `http.client` is used only by the metadata thread. Deferring both reclaims roughly 2 MB of the +5.7 MB RSS regression. | low / low |
| 1.6 | **Guard the `PLAYLIST` mutation** | the metadata thread adds keys (`listeners`, `track_duration`, `track_elapsed`, `signal`) to station dicts (`radio.py:1268`+) while the drawer renderers iterate `PLAYLIST`. CPython makes leaf writes atomic, but adding a key during iteration can raise `RuntimeError`. Have `_apply_*` build a replacement dict and swap it in, or take a short lock. | med / low |
| 1.7 | **Deeper idle throttle** | `IDLE_FRAME_TIME` is a single value. Drop to ~2 FPS when `stream_state in (IDLE, ERROR)`, the drawer is closed, and no tuning glitch is animating — nothing moves in that state except the timer-colon blink. | low / low |
| 1.8 | **Coalesce mpv volume commands** | rapid `+`/`-` sends one `set_property` each. Since the reader thread landed this is only wasteful, not dangerous; still, debounce to one `set_volume` per frame from a pending value. | low / low |
| 1.9 | **Name the physics constants** | `0.60` (spring), `0.035` (gravity), `1.25`, `0.16` (peak fall) in `update_physics` (`radio.py:~1760–1800`) are bare literals. Promote to named module constants. | low / low |
| 1.10 | **`RotatingFileHandler`** for the log | `_init_logger` (`radio.py:52`) appends without bound. Cap at ~1 MB × 3. | low / trivial |

---

## Tier 2 — features with real user payoff

| # | Idea | Detail | Value / Effort |
| :-- | :-- | :-- | :-- |
| 2.1 | **Album art in graphics-capable terminals** | SomaFM, Nightwave Plaza and Radio Paradise already return an art URL in the metadata the scraper fetches. Detect the kitty / iTerm2 / WezTerm graphics protocol (or sixel), draw a small thumbnail in the LCD area, draw nothing where unsupported. The biggest visible upgrade available. | high / high |
| 2.2 | **Sleep timer** | `[` / `]` keys or a `--sleep 30m` flag; overlay a countdown, then call `stop_playback()`. Standard radio feature, ~30 lines. | high / low |
| 2.3 | **Favourites + jump list** | star a station (`f`), persist to config, `Tab`-cycle the favourites. | med / low |
| 2.4 | **Type-to-filter the drawer** | as the station list grows past the built-in 16, an incremental filter in the drawer key handler + `render_drawer_rows`. | med / med |
| 2.5 | **Now-playing history** | keep the last ~10 distinct `track` values per station; a togglable panel or scrollback in the drawer. | med / med |
| 2.6 | **Desktop notification on track change** | if `notify-send` is on `PATH`, fire one when `current_song_title` changes. Subprocess, no new dependency, opt-in via flag/config. | med / low |
| 2.7 | **Stream recording** | `mpv` supports `--stream-record=<file>`; a keybind toggles the property and shows a `● REC` badge. Document the licensing/ethical caveat; it is a standard mpv capability. | med / low |
| 2.8 | **Perceptual volume taper** | `mpv`'s `volume` is linear amplitude; map the 0–100 slider through `x²` or a dB curve so the low end is usable. | med / low |
| 2.9 | **MPRIS / media-key control** | expose `org.mpris.MediaPlayer2` on the session bus so hardware media keys and desktop widgets drive playback. Possible dependency-free over the D-Bus socket but fiddly; `mpv` can also advertise its own MPRIS via a script. | med / high |
| 2.10 | **Clock in the chassis** | a small `HH:MM` in the frame — it is a *radio*. | low / trivial |
| 2.11 | **Configurable keybindings** | a `[keys]` table in `stations.json` or a sibling config file; `handle_key` (`radio.py:2329`) already routes by a single string, so remapping is a lookup. | low / med |

---

## Tier 3 — architecture / maintainability

Behaviour-neutral; these make the *next* change cheaper. Also flagged in [`../docs/termbeat.md` §15](../docs/termbeat.md#15-known-limitations-and-non-goals).

| # | Idea | Detail | Value / Effort |
| :-- | :-- | :-- | :-- |
| 3.1 | **Split into a package** | `termbeat/{app,audio,spectrum,metadata,config,themes,render/,widgets}.py`; keep a thin `radio.py` / `__main__.py` that imports and calls `main()`. The single-file property is pleasant, but a 3,155-line module holding a ~1,700-line class is the real barrier to contribution. | high / high |
| 3.2 | **One layout engine for the four styles** | `render_retro_hifi` / `_modern_neo` / `_minimal_zen` / `_cyberpunk` share ~70% structure (header → viz pane → transport → volume → status). Express a style as a table of row-builders + a `Theme`; the differences become data. Removes ~600 lines and makes a fifth style a config entry. | high / high |
| 3.3 | **Group `__init__` state into sub-objects** | `TermbeatPlayer.__init__` (`radio.py:1459`) is ~80 lines of flat assignment. `self.transport`, `self.viz`, `self.layout`, `self.clock` dataclasses. | med / med |
| 3.4 | **Full type hints + `pyright` / `mypy` in CI** | annotations are partial today. | med / med |
| 3.5 | **A `Settings` dataclass** | pacing constants, minimum size, band count, poll intervals, non-themed colours — currently module-level scatter. | low / low |

---

## Tier 4 — testing gaps

`tests/test_termbeat.py` covers width parity, input parsing, layout fit, diff-render
correctness, cava suspend, and dead-stream honesty. Not covered:

| # | Idea | Value / Effort |
| :-- | :-- | :-- |
| 4.1 | `_apply_somafm` / `_apply_plaza` / `_apply_radioparadise` / `_apply_kexp` against recorded JSON fixtures (capture once from the live APIs, commit under `tests/fixtures/`) | med / low |
| 4.2 | `_tune` / `next_track` / `prev_track` / `select_preset` state transitions (index wrap, clock reset, provider notification) | med / low |
| 4.3 | Config **hot-reload** path: write a new `stations.json`, bump mtime, assert `PLAYLIST` swaps and the indices clamp | med / low |
| 4.4 | `RawInput.get_keys()` end-to-end through a real `pty` (only `parse_key_bytes` is unit-tested today) | med / low |
| 4.5 | A subprocess test for `SIGHUP` / `SIGKILL` cleanup + no orphaned `mpv` (verified manually this session; fold into CI as a slow/optional test) | med / med |

---

## Tier 5 — probably not worth it (recorded so they are not re-litigated)

| Idea | Why not |
| :-- | :-- |
| Rewrite the renderer for speed | 0.5 ms/frame, ~1% of a core, 2,000 FPS capable. Nothing to gain. |
| Replace `mpv` with a pure-Python decoder | multi-year effort; that is the entire point of the Rust plan instead. |
| `asyncio` rewrite of the threads | three daemon threads doing blocking I/O is the right model; `asyncio` adds a loop and ceremony without removing a real problem. |
| Higher-resolution sixel/ANSI spectrum | the Braille path already gives 2×4 sub-cell; diminishing returns, more CPU. |
| Caching whole rendered sub-regions between frames | render is already negligible and the v3 diff emitter handles the output cost. |
| In-app `stations.json` editor | a TUI form for a file the user can edit in `$EDITOR` in two seconds. |

---

## If forced to pick five

1. **`git init` + README + `pyproject.toml`** (Tier 0) — unblocks everything else.
2. **CLI flags** (1.1) — `--station`, `--no-audio`, `--style` are basic ergonomics.
3. **Truecolor detection / 256-color fallback** (1.4) — the one colour-correctness gap that
   affects real terminals today.
4. **One layout engine for the four styles** (3.2) — makes every future UI tweak cheap and
   deletes ~600 lines of duplication.
5. **Sleep timer** (2.2) — small, self-contained, genuinely useful for a radio.

Album art (2.1) is the highest-*wow* item if the appetite is there, but it is the most work
and only pays off in graphics-capable terminals.

---

## Verification (for whichever items are chosen)

- `python3 tests/test_termbeat.py` stays green; add cases per Tier 4 for any new logic.
- `python3 bench/benchmark_system.py 101 54 25` before/after — `radio.py` RSS must not
  regress past ~40 MB and paused CPU must stay below 1%.
- Manual: cycle all 4 styles × 2 visualizers × 5 themes at 80×24, 102×30, 101×54; open the
  drawer; change stations rapidly; pull the network mid-stream and confirm `BUFFERING` →
  reconnect; `SIGHUP` the process and confirm no orphaned `mpv` and nothing left in
  `$XDG_RUNTIME_DIR/termbeat/`.
- For colour work (1.4): run under `TERM=xterm-256color` with `COLORTERM` unset and confirm
  the palette degrades gracefully instead of emitting `38;2;` to a non-truecolor terminal.
