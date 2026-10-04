# termbeat — Rust Rewrite Plan

*Companion to [`../docs/termbeat.md`](../docs/termbeat.md). Read that first for how the current
Python version works.*

---

## 0. TL;DR

- **Do not rewrite the renderer to make it faster.** It is already 0.5 ms/frame — ~1% of one core,
  2,000 FPS capable against a 22 FPS need. Rust would take that to ~20 µs and save ~1% of a core.
  That is not a reason to do anything.
- **The only rewrite worth the cost removes the two subprocesses.** `mpv` is 61% of termbeat's
  memory and `cava` another 9%; neither is `radio.py`'s code, so no amount of Python or Rust work on
  `radio.py` touches them. A native Rust build that decodes and plays audio itself, and runs its own
  FFT, plausibly lands at **10–20 MB total against a measured 139 MB — a 7–13× reduction** — and
  makes several classes of bug *structurally impossible* rather than patched.
- **The cost is real:** codec coverage risk (AAC/HLS), hand-rolled Icecast metadata, the loss of
  "zero dependencies", and a full rewrite of every renderer into `ratatui`'s widget model — this is
  a port of the *design*, not the code.
- **If the goal is just "ship one binary" without that risk, use `libmpv` (link, don't spawn) or
  write it in Go.** Both keep mpv's codec/network robustness. Neither gets the memory win.
- **Recommended path:** the phased plan in §7 — start with `libmpv` linked + `ratatui`, prove the UI
  and the IPC-free control path, then swap the audio backend to `symphonia`/`cpal`/`rustfft` behind
  a trait as phase 2 only if the memory number matters enough.

---

## 1. Why consider this at all

### 1.1 What the measurements say

From [`../docs/RESULTS.md`](../docs/RESULTS.md) (Intel Core Ultra 7 258V, Linux, Python 3.14):

| Component | RSS | % of total | Whose code |
| :-- | --: | --: | :-- |
| `mpv --idle` | 85.2 MB | **61%** | not ours |
| `radio.py` | 40.4 MB | 29% | ours |
| `cava` | 13.1 MB | 9% | not ours |
| **Total** | **138.7 MB** | | |

Render path: worst p50 **0.50 ms** at 200×60 (1.1% of a core). Steady-state CPU: 6.1% playing,
0.8% paused. Output after the v3 diff renderer: ~63 KB/s playing, ~1 KB/s paused.

**Reading:** the Python process is a third of the footprint and its hot loop is already ~50× faster
than it needs to be. Optimising `radio.py` — in any language — fights over a shrinking third.
The 70% that is `mpv` + `cava` only moves if you stop spawning them.

### 1.2 Bugs a native rewrite deletes instead of fixing

The v3 Python fixes each *contain* a problem that a native design does not have:

| v3 Python fix | Native Rust: why it can't happen |
| :-- | :-- |
| IPC reader thread to stop the mpv socket write queue saturating and pegging a core | no IPC socket — playback is a function call / channel send |
| `PR_SET_PDEATHSIG` + `SIGHUP` handler to stop orphaned `mpv` | no child process to orphan |
| `_runtime_dir()` 0700 dir for a predictable `/tmp` socket | no socket file |
| cava `SIGSTOP` on pause to reclaim 2% of a core | the FFT is our thread; pausing it is a flag |
| `stream_live` gating so a dead stream stops faking a spectrum | the spectrum is computed from the PCM we are actually playing — there is nothing to fake |
| `HttpSession` keep-alive + provider-scoped polling | still needed (metadata is still HTTP), but now in a typed client |

### 1.3 What Rust makes *worse*

- **Iteration speed.** This project is ~90% string/color/layout fiddling. `f"{c}{label}"` becomes
  `Span::styled(label, style)`; a recompile sits between every visual tweak. For a project whose
  *product is the look*, that is a real tax.
- **The inline-ANSI idiom does not port.** Every renderer builds rows as strings with `\033[…m`
  spliced in. `ratatui` wants `Line`/`Span`/`Style` trees. The four design styles are a from-scratch
  reimplementation, not a translation.
- **"Zero dependencies" is gone.** It becomes "zero *runtime* dependencies" — arguably the better
  property for a distributed binary, but it is a change in character.
- **Codec risk** — see §4.1.

---

## 2. Goals and non-goals

### Goals

1. Single self-contained binary. No `mpv`, no `cava`, no Python, no `pip`. `cargo build --release`
   → one file, `scp` it anywhere with the same libc/audio stack.
2. Total resident memory **< 25 MB** with a stream playing (target 10–18).
3. Feature parity with v3: 16 presets + `stations.json` hot-reload, 4 design styles, 5 themes,
   2 visualizers, the drawer, live stream-health states, live now-playing metadata.
4. Behavioural parity or better: no orphaned processes, no leaked files, honest `BUFFERING` /
   `STREAM ERROR`, instant controls, cell-accurate layout including CJK titles.
5. Spectrum computed from the actual decoded audio, not a monitor source or a fallback.

### Non-goals

- Beating the renderer's speed (already a non-problem).
- Windows support in v1 (audio backend is `cpal` — it *can*, but ship Linux/macOS first).
- Local file playback, seeking, playlists beyond the station list — same scope as today.
- A plugin system, config UI, or theming DSL.

---

## 3. Target architecture

```
                    ┌──────────────────────────────────────────────┐
   crossterm  ◀─────│  ui thread  (ratatui)                        │
   (stdin/out)      │   • event poll → Action                      │
                    │   • App::update(Action)                      │
                    │   • App::draw(Frame)   ── ratatui diffs ──▶   │
                    └──────┬───────────────────────┬───────────────┘
                           │ Action / State via    │ SpectrumFrame
                           │ crossbeam channels     │ (18 f32, ~30 Hz)
              ┌────────────▼─────────┐   ┌──────────▼───────────────┐
              │ metadata task        │   │ audio engine  (own thread)│
              │  (async or thread)   │   │  Stream → Decode → Analyse │
              │  reqwest/ureq + serde │   │        → Resample → cpal   │
              └────────┬─────────────┘   │  emits: PlaybackState,     │
                       │ HTTP/JSON        │         SpectrumFrame,     │
              ┌────────▼─────────────┐    │         NowPlaying (ICY)   │
              │ somafm/plaza/rp/kexp │    └──────────┬────────────────┘
              └──────────────────────┘               │ HTTP (icecast)
                                          ┌──────────▼────────────────┐
                                          │  stream CDN               │
                                          └───────────────────────────┘
```

### 3.1 Crate → workspace layout

```
termbeat/
  Cargo.toml                 # [workspace]
  crates/
    termbeat-audio/          # trait AudioEngine + native impl + (optional) libmpv impl
    termbeat-meta/           # provider clients, HttpSession-equivalent
    termbeat-ui/             # ratatui widgets, themes, the 4 styles, layout
    termbeat-core/           # config, station model, XDG paths, logging
  src/main.rs                # wiring: spawn engine + meta, run ui loop
```

Splitting into crates is cheap in Rust and keeps compile units small; it also makes the audio
backend genuinely swappable (§4.2).

### 3.2 Dependencies (and the honest cost)

| Need | Crate | Notes / risk |
| :-- | :-- | :-- |
| Terminal | `crossterm` | ratatui's default backend; raw mode, alt screen, resize events, `poll()` with timeout — replaces `RawInput` + `parse_key_bytes` + the SIGWINCH dance |
| TUI | `ratatui` | **double-buffered cell diffing is the default** — the v3 `emit_frame` work is free here |
| Unicode width | `unicode-width`, `unicode-segmentation` | replaces `char_width`/`_measure`/`cell_slots`; handles grapheme clusters, which the Python still doesn't |
| HTTP | `ureq` (blocking, `rustls`) **or** `reqwest` | `ureq` is ~15 crates and no async runtime; enough for 4 JSON polls + 1 audio stream. `reqwest` if you want async. |
| JSON / config | `serde`, `serde_json` | station model, metadata responses |
| Audio decode | `symphonia` (feature-gated: `mp3`, `aac`, `isomp4`) | **primary risk — see §4.1** |
| Resample | `rubato` | streams are 44.1 kHz; device may want 48 kHz |
| Audio out | `cpal` | ALSA/PulseAudio/PipeWire/CoreAudio/WASAPI |
| FFT | `rustfft` + hand-rolled Hann window | replaces `cava` entirely |
| XDG paths | `etcetera` or `dirs` | `~/.config`, `~/.local/state`, `$XDG_RUNTIME_DIR` |
| Logging | `tracing` + `tracing-subscriber` (file writer) | file only — stdout is the UI, same rule as Python |
| Errors | `anyhow` (bin), `thiserror` (libs) | |
| Channels | `crossbeam-channel` | ui ↔ engine ↔ meta |
| (optional) file watch | poll mtime, like the Python | avoid `notify` to keep the tree small |

Total: ~25 direct deps, ~150–250 transitive. Build from scratch ~1–3 min; binary 4–9 MB stripped.
This is the "zero deps → zero runtime deps" trade stated plainly.

---

## 4. The hard parts

### 4.1 Codec coverage — the single biggest risk

The 16 default streams: **14 MP3**, 1 AAC (`kexp160.aac`, ADTS), 1 ambiguous (`plaza.one/mp3`).

- **MP3:** `symphonia` MP3 decode is solid and widely used. Low risk.
- **AAC/ADTS:** `symphonia`'s AAC decoder is decode-only, LC profile, and historically less battle-
  tested than its MP3 path. KEXP's stream and any SomaFM `-aac` variants must be tested early. If it
  fails: transcode is not an option in a player; the fallbacks are (a) drop AAC stations from the
  native build, (b) bundle a tiny C AAC decoder via FFI (`fdk-aac-sys`) — which dents the "pure
  Rust" story, or (c) use the `libmpv` backend for those URLs.
- **HLS:** none of the current defaults use it, but Radio Paradise and others offer HLS variants.
  `symphonia` does not do HLS (segment playlists). If a user adds an HLS URL, the native backend
  must reject it cleanly (the `stations.json` validator should flag `.m3u8`).
- **Icecast quirks:** chunked transfer, no `Content-Length`, occasional mid-stream format changes,
  `ICY 200 OK` status line instead of `HTTP/1.1 200 OK` (some servers). The HTTP client must tolerate
  the non-standard status line — `ureq`/`reqwest` may need a raw-socket fallback for the worst
  offenders. mpv handles all of this today; that robustness is what you are re-implementing.

**Mitigation:** phase 1 uses `libmpv` (no codec risk at all), phase 2 swaps in the native decoder
behind the `AudioEngine` trait and is gated on a codec test matrix passing against all 16 default
streams plus a handful of user-suggested ones.

### 4.2 The `AudioEngine` trait — make the backend swappable

```rust
pub enum PlaybackState { Connecting, Buffering, Playing, Paused, Stopped, Error(String), NoBackend }

pub struct SpectrumFrame { pub bands: [f32; 18], pub active: bool }

pub trait AudioEngine: Send {
    fn load(&mut self, url: &str);
    fn set_paused(&mut self, paused: bool);
    fn set_volume(&mut self, vol: u8);        // 0..=100
    fn set_muted(&mut self, muted: bool);
    fn stop(&mut self);
    fn state(&self) -> PlaybackState;         // drives status_badge
    fn now_playing(&self) -> Option<String>;  // ICY title
    fn spectrum(&self) -> SpectrumFrame;      // consumed by the visualizers
}
```

Two impls:

- **`MpvEngine`** (`libmpv2` crate): links `libmpv.so`, sets `pause`/`volume`/`ao-volume`, observes
  `media-title` / `core-idle` / `paused-for-cache` via the C API's `observe_property` — the *same*
  properties the Python reads over the socket, minus the socket. The saturation bug is gone because
  there is no byte stream to saturate. Memory: still ~40–55 MB (libmpv's decoders, ffmpeg, its
  thread pool). No `cava`: get PCM from libmpv's `--ao=null` + audio filter, or its
  `audio-data`/`--af=export` hook, and run the FFT ourselves — or just keep the memory and use a
  scope filter.
- **`NativeEngine`**: the `Stream → symphonia → rubato → cpal` pipeline, with a tap after decode
  feeding a ring buffer that the FFT thread windows and transforms. Memory: ~5–10 MB. This is the
  one that gets the headline number.

`main.rs` picks the impl from a build feature or a runtime flag; the UI never knows which it has.

### 4.3 The spectrum — replacing cava

cava does: capture → FFT → logarithmic frequency binning → "monstercat" spatial smoothing →
gravity/decay ballistics. In the native engine we already have the PCM (it is what we are sending to
`cpal`), so:

1. After decode, copy interleaved f32 samples into a `HeapRb<f32>` (from `ringbuf`), downmix to mono.
2. FFT thread: every ~33 ms, take the last 2048 samples, apply a Hann window, `rustfft` forward,
   magnitude spectrum.
3. Bin into 18 logarithmically-spaced bands (20 Hz–20 kHz), normalise.
4. Port `apply_monstercat_filter` verbatim (it is ~15 lines and already has a pow lookup table in
   v3) and the quadratic-gravity ballistics from `update_physics`. These stay in the UI's physics
   step, exactly as now — the engine only supplies the raw 18 bins.

`SpectrumFrame::active` is trivially honest: it is `false` when `PlaybackState != Playing` or the
recent RMS is below a threshold. No more "is the monitor source alive" heuristic.

### 4.4 Icecast metadata (ICY) in the native engine

For `generic` stations with no provider API, the Python leans on mpv to parse the ICY
`StreamTitle='...'` blocks. Native path: send `Icy-MetaData: 1` on the GET, read `icy-metaint` from
the response headers, then every `metaint` bytes of audio there is a length-prefixed metadata block
to parse out. ~40 lines; the `icy-metadata` crate exists but is thin — vendoring the parser is fine
and keeps control. The four provider APIs (`termbeat-meta`) are unchanged in spirit — a typed
`HttpSession` with a pooled `ureq::Agent`, the 30 s tuned / 600 s sweep schedule, exponential
backoff, and the SomaFM per-channel endpoint.

### 4.5 The four design styles → ratatui

Each `render_*` becomes a function `fn draw_retro(f: &mut Frame, area: Rect, st: &UiState, th: &Theme)`
composing ratatui widgets. Mechanical but large:

- The fixed-width chassis art (`╭─…─╮`) → `Block` with `Borders` + custom `border_set`, or a
  `Paragraph` of pre-built `Line`s for the truly bespoke frames.
- The LCD panel, transport bar, volume slider, drawer → small custom `Widget` impls.
- Visualizer rows → a `Canvas` widget or a custom `Widget` writing `Cell`s directly (Braille via
  `ratatui::widgets::canvas` which already has a Braille `Marker`).
- Themes: a `Theme` struct of `ratatui::style::Color` values; the `_c_*` pre-built escape strings
  disappear because `Style` is resolved at draw time by ratatui's diff, not by us.
- Layout breakpoints (`is_portrait_tall`, `is_compact_80`, standard) → a `match` on
  `frame.size()` picking a `Layout` split. ratatui's `Layout` with `Constraint::{Length,Min,Ratio}`
  replaces the hand-computed `inner_w`/`pad`/`margin_left` arithmetic.
- `fit_row`/`truncate_ansi` are gone: ratatui truncates and pads to the `Rect` and measures width
  with `unicode-width`. The v3 cell-accurate marquee becomes a `unicode-segmentation` grapheme walk.

Estimate: ~1,500–2,000 lines of Rust for `termbeat-ui`, vs ~1,400 lines of Python renderers.

### 4.6 Input

`crossterm::event::poll(timeout)?` + `read()?` yields `KeyEvent`/`Resize` already parsed — the entire
`parse_key_bytes` CSI/SS3/UTF-8 state machine and the lone-`ESC` timeout are handled by the library.
The adaptive frame pacing (`ACTIVE_FRAME_TIME` / `IDLE_FRAME_TIME`) becomes the `poll()` timeout,
which is exactly the v3 `wait_readable` design, done properly.

### 4.7 Lifecycle

No child processes ⇒ no `SIGHUP`/`PR_SET_PDEATHSIG` machinery. A `Drop` impl on the app restores the
terminal (leave alt screen, show cursor, disable raw mode); a top-level `catch_unwind` /
`std::panic::set_hook` ensures the terminal is restored on panic before the backtrace prints.
`cpal`'s stream is stopped in `Drop`. `ctrlc` crate or a `crossterm` `Ctrl-C` key event handles
interactive quit.

---

## 5. Component mapping (Python → Rust)

| Python (`radio.py`) | Rust home | Notes |
| :-- | :-- | :-- |
| `RawInput`, `parse_key_bytes`, `_CSI_KEYS` | *(deleted)* — `crossterm::event` | |
| `str_width`, `char_width`, `_measure`, `cell_slots`, `truncate_ansi`, `fit_row` | *(deleted)* — `ratatui` + `unicode-width` | keep a thin `marquee()` grapheme helper |
| `emit_frame` diff renderer | *(deleted)* — ratatui diffs natively | |
| `StreamPlayer` (mpv IPC, supervisor, `_read_loop`, `health`) | `termbeat-audio::{MpvEngine, NativeEngine}` behind `AudioEngine` | `health()` → `state()` |
| `CavaStreamEngine` | folded into `NativeEngine`'s FFT thread | |
| `apply_monstercat_filter`, ballistics in `update_physics` | `termbeat-ui::physics` | ported ~1:1 |
| `HttpSession` | `termbeat-meta::HttpClient` (pooled `ureq::Agent`) | |
| `MetadataScraper` + `_apply_*` | `termbeat-meta::{Scraper, providers}` | same 30 s/600 s/backoff schedule, same SomaFM per-channel endpoint |
| `normalize_station` / `normalize_playlist` / `load_stations_config` | `termbeat-core::config` with `serde` + validation | reject non-`http(s)`, reject `.m3u8` for native backend |
| `THEMES` + `_c_*` | `termbeat-ui::theme::Theme` (`ratatui::Color`) | |
| `render_frame` + 4 `render_*` | `termbeat-ui::styles::{retro,neo,zen,cyber}` | the bulk of the work |
| `get_*_rows` visualizers | `termbeat-ui::viz` custom widgets / `Canvas` | |
| `TermbeatPlayer` god-class | `App` struct in `main.rs` + `UiState` | state stays central, I/O moves to tasks |
| `_init_logger` | `tracing_subscriber` file layer | |
| `_runtime_dir`, `_die_with_parent` | *(deleted)* | no socket, no child |

---

## 6. Projected numbers (estimates, not measurements)

| Metric | Python v3 (measured) | Rust + libmpv | Rust native |
| :-- | --: | --: | --: |
| Total RSS, stream playing | 138.7 MB | 45–60 MB | **10–20 MB** |
| Frame render p50 @ 101×54 | 0.44 ms | ~15–40 µs | ~15–40 µs |
| CPU, playing | 6.1% | 3–5% | **2–4%** |
| CPU, paused | 0.8% | ~0.3% | ~0.2% |
| Terminal output, playing | ~63 KB/s | ~5–20 KB/s (ratatui diff) | ~5–20 KB/s |
| Cold start to first frame | ~150–300 ms | ~10–30 ms | ~5–15 ms |
| Binary / install size | 133 KB script + interpreter | 5–9 MB static | 5–9 MB static |
| Direct dependencies | 0 | ~20 | ~25 |
| Codec coverage | everything ffmpeg does | everything ffmpeg does | MP3 solid, AAC/HLS at risk |

The render p50 figure is a projection from typical `ratatui` redraw costs at this cell count; treat
±2× as the honest error bar. The RSS figures for the native build assume `symphonia` + `cpal` +
`rustfft` with a 2–4 MB decode buffer and no ffmpeg.

---

## 7. Phased plan

### Phase 0 — spike (½–1 week)

- `cargo new` workspace, `ratatui` + `crossterm` hello-loop with the adaptive `poll()` timeout.
- Port `Theme` and *one* style (Minimal Zen — smallest) to prove the widget approach and the
  layout-breakpoint `match`.
- `MpvEngine` via `libmpv2`: load a stream, pause/volume/mute, observe `media-title` + `core-idle`.
- **Decision gate:** does the widget model feel workable, and does libmpv linking behave?

### Phase 1 — parity on the libmpv backend (3–5 weeks)

- All 4 styles, 5 themes, 2 visualizers (FFT fed from a libmpv audio tap, or a scope filter).
- `termbeat-core::config`: `stations.json` load/validate/hot-reload (mtime poll).
- `termbeat-meta`: all four providers, the 30 s/600 s schedule, backoff, SomaFM per-channel.
- The drawer, tuning glitch, status badge from `state()`.
- Lifecycle: panic hook + `Drop` terminal restore, `Ctrl-C`.
- Port `tests/test_termbeat.py` intent to Rust: width/layout invariants (every style × geometry fits
  its `Rect`), marquee grapheme-exactness, config rejection, diff-render correctness is now the
  library's problem.
- **Ship this.** It is already a single binary with no `mpv`/`cava` *process* and no orphan/leak/
  IPC-saturation failure modes. Memory is still ~45–60 MB.

### Phase 2 — native audio (3–6 weeks, optional, gated on need)

- `NativeEngine`: `ureq` streaming GET → `symphonia` decode → `rubato` → `cpal`, PCM tap → `rustfft`.
- ICY metadata parser for `generic` stations.
- **Codec test matrix**: all 16 default streams + a curated extra set must play for 10 min with no
  underrun; AAC (KEXP) is the make-or-break case.
- Icecast robustness: non-standard status line, chunked/no-length, mid-stream sample-rate change,
  reconnect with backoff (mirrors `_supervise`).
- Flip the default backend to native; keep `MpvEngine` behind `--features libmpv` as the escape
  hatch for exotic URLs.
- **This is the phase that delivers the 10–20 MB number.** If AAC/HLS/Icecast robustness proves too
  costly, stopping after Phase 1 is a legitimate, useful outcome.

### Phase 3 — polish

- macOS CI, `cargo dist` / release binaries, `homebrew`/`AUR` packaging.
- Windows: `cpal` WASAPI works; input/paths need review; named-pipe not needed (no IPC).

**Total to Phase 1: ~1–1.5 months of focused work. To Phase 2: ~2–3 months.**

---

## 8. Risks and how to retire them early

| Risk | Severity | Retire by |
| :-- | :-- | :-- |
| `symphonia` AAC can't play KEXP/SomaFM-aac | high | test in Phase 0, before committing to native |
| Icecast servers with `ICY 200 OK` status line break `ureq` | med | test the 3 SomaFM + Plaza + RP + KEXP endpoints raw in Phase 0 |
| ratatui can't express the bespoke chassis art cleanly | med | port Retro Hi-Fi (the most decorated) in Phase 1, not last |
| `cpal` device-format mismatch / crackle | med | `rubato` + a generously sized `cpal` buffer; test on PipeWire and PulseAudio |
| Rewrite stalls at 80% (classic) | high | Phase 1 is a shippable product on its own; Phase 2 is opt-in |
| `libmpv` not present on user systems | low | static-link, or `dlopen` with a clear error, or just require it for the `libmpv` feature |
| Effort exceeds value (the honest one) | — | if after Phase 0 the answer is "libmpv linked is enough", ship that and stop |

---

## 9. The alternatives, briefly

| Option | Gets you | Costs |
| :-- | :-- | :-- |
| **Stay in Python (v3)** | already done; 139 MB, 6% CPU, no orphans, honest UI | mpv/cava still there; not a single binary |
| **Rust + `libmpv` (Phase 1)** | single binary, no orphan/leak/IPC bugs, ~50 MB, native ratatui diffing, fast start | ~20 deps, links libmpv, rewrite of all renderers |
| **Rust native (Phase 2)** | all of the above **+ 10–20 MB total**, real spectrum, no ffmpeg | codec/Icecast robustness is now your problem |
| **Go + Bubbletea/Lipgloss** | single binary, diff rendering, goroutines, ~10–15 MB *of Go* — but keep `mpv` | still spawns mpv → keeps 61% of the memory; only wins on distribution |
| **C + notcurses** | fastest possible; notcurses is purpose-built for sub-cell viz | every memory-safety footgun, in a program doing heavy string surgery |
| **Zig** | Rust-class perf, C-like simplicity | thin TUI ecosystem — you'd write the ANSI layer yourself, which this project already does |

**If you want the memory win:** Rust native, accept the codec work.
**If you want a binary without the risk:** Rust + libmpv, or Go.
**If neither is worth a rewrite:** v3 Python is a supported, honest, ~139 MB player today.

---

## 10. Verification plan (for whichever phase ships)

- **Codec matrix** (Phase 2): every default stream + extras plays 10 min, no underrun, correct
  sample rate; `state()` transitions Connecting→Buffering→Playing are observed; kill the network
  mid-stream and confirm Buffering→reconnect→Playing.
- **Layout invariants** (port from `tests/test_termbeat.py`): for every style × {80×24, 102×30,
  101×54, 200×60, 70×18} the drawn area never exceeds its `Rect`; marquee is grapheme-exact for a
  CJK title; `stations.json` with a `file://` URL and a missing-key entry is rejected/normalised.
- **Lifecycle**: `SIGHUP`, `SIGKILL`, panic, and normal quit all restore the terminal and leave no
  processes (there are none) and no files outside `~/.config` / `~/.local/state`.
- **Control latency**: 600 rapid volume keypresses — volume tracks, no stall, no runaway thread
  (the Python IPC-saturation regression test, retargeted).
- **Memory**: `/proc/<pid>/status` VmRSS with a stream playing, compared against the §6 target.
- **Metadata**: 5-minute capture of wire bytes with `strace -e trace=network` or `/proc/<pid>/io`,
  compared against the Python v3 figure (0.12 KB/s).

---

*Written September 2026 against `radio.py` at 3,155 lines / commit-equivalent of the v3 fix pass.
Numbers under "measured" come from [`../docs/RESULTS.md`](../docs/RESULTS.md); numbers under "projected" are estimates and
are marked as such.*
