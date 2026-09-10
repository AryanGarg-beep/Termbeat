# termbeat — Project Documentation

*A retro hi-fi internet-radio player that runs entirely in a terminal.*

Single file: [`radio.py`](../radio.py) · 3,155 lines · pure Python 3 standard library · zero pip
dependencies.

This document describes the codebase as it stands after the September 2026 fix pass. It is the
reference for how termbeat works today; how it got here — the v2 → v3 changelog and what came
before — is in [`history.md`](history.md).

---

## Table of contents

1. [What it is](#1-what-it-is)
2. [Requirements and running it](#2-requirements-and-running-it)
3. [Keybindings](#3-keybindings)
4. [Architecture: processes, threads, data flow](#4-architecture-processes-threads-data-flow)
5. [The audio engine — `StreamPlayer`](#5-the-audio-engine--streamplayer)
6. [The spectrum engine — `CavaStreamEngine`](#6-the-spectrum-engine--cavastreamengine)
7. [Now-playing metadata — `MetadataScraper` + `HttpSession`](#7-now-playing-metadata--metadatascraper--httpsession)
8. [Input — `RawInput` and `parse_key_bytes`](#8-input--rawinput-and-parse_key_bytes)
9. [The rendering pipeline](#9-the-rendering-pipeline)
10. [State and physics — `update_physics`](#10-state-and-physics--update_physics)
11. [Configuration, environment, files on disk](#11-configuration-environment-files-on-disk)
12. [Lifecycle and signal handling](#12-lifecycle-and-signal-handling)
13. [Performance benchmarks](#13-performance-benchmarks)
14. [Security considerations](#14-security-considerations)
15. [Known limitations and non-goals](#15-known-limitations-and-non-goals)
16. [Development: tests, benchmarks, extending](#16-development-tests-benchmarks-extending)
17. [Code map](#17-code-map)

Companion documents: [`history.md`](history.md) — how the code got here ·
[`RESULTS.md`](RESULTS.md) — the raw benchmark tables.

---

## 1. What it is

**termbeat** paints a 1980s stereo receiver in the terminal with raw ANSI escape codes and plays
curated, commercial-free internet-radio streams behind it. It has **no pip dependencies** — every
import is from the Python standard library — and it hands the two genuinely hard jobs to external
programs it drives as subprocesses:

| Job | Owner | How it is driven |
| :-- | :-- | :-- |
| HTTP streaming + MP3/AAC decode + audio output | **`mpv`** (`--idle --no-video`) | JSON IPC over a private UNIX socket |
| Real-time audio spectrum (FFT of the sound card) | **`cava`** | generated temp config, raw ASCII bar values over a pipe |
| Now-playing track titles | four public HTTP APIs | keep-alive JSON polling, tuned station only |
| Everything else (layout, physics, input, lifecycle) | `radio.py` main thread | one adaptive-rate ANSI repaint loop |

Both external programs are optional. Without `mpv` the UI runs silently and says `NO MPV`. Without
`cava` the spectrum falls back to a synthesised animation.

### Feature surface

- **16 preset stations** (`DEFAULT_PLAYLIST`, `radio.py:109`) — SomaFM channels, Nightwave Plaza,
  Radio Paradise, KEXP — overridable and extendable via `~/.config/termbeat/stations.json`, which is
  **hot-reloaded** when its mtime changes (`check_reload_stations`, `radio.py:1666`).
- **4 design aesthetics** cycled with `D`: *Retro Hi-Fi*, *Modern Neo*, *Minimal Zen*, *Cyberpunk*
  (`render_frame` dispatch, `radio.py:2478`).
- **5 colour themes** cycled with `T` (`THEMES`, `radio.py:355`): Classic Tuna, Cyberpunk, Amber CRT,
  Matrix, Synthwave.
- **2 visualizers** cycled with `V`: an 18-band spectrum analyser and an oscilloscope; Modern Neo and
  Cyberpunk substitute a sub-pixel Braille waveform (2×4 dots per cell).
- **Responsive layout** with three retro form factors — *Studio Tower* (tall), *Deck-78* (compact),
  and the fixed 102-column *standard deck* — plus per-width transport-button label sets.
- **Live stream health** in the header: `PLAYING` / `BUFFERING` / `PAUSED` / `STOPPED` /
  `STREAM ERROR` / `NO MPV`, derived from mpv's actual state, not from the app's intent.
- **Station directory drawer** (`L`), analog tuning static-glitch effect on station change, elapsed
  timer with a wall-clock-blinked colon, 24-slot volume slider, mute.
- **btop-style "terminal too small"** screen below 70×18.

### Who it is for

Terminal-resident users who want ad-free background radio without a browser tab or an Electron app,
and who value a single file with no install step. It measures **~6× lighter in RAM than a browser
tab** playing the same stream (see [§13](#13-performance-benchmarks)). A large fraction of the code
exists purely to make the terminal look like hi-fi equipment; it is as much a demoscene piece as a
utility.

---

## 2. Requirements and running it

| | |
| :-- | :-- |
| **Python** | 3.9+ (uses `tuple[...]` annotations, f-strings, `shutil.get_terminal_size`) |
| **Terminal** | ANSI + 24-bit truecolor, UTF-8, ≥ 70×18 cells |
| **`mpv`** | optional, for audio — any recent build with `--input-ipc-server` |
| **`cava`** | optional, for the real spectrum — needs a PulseAudio/PipeWire monitor source |
| **OS** | Linux/macOS (POSIX). `termios`/`tty` are imported defensively; without them input is disabled but the UI still renders. |

```sh
python3 radio.py
```

There is no build step, no `pip install`, no virtualenv. First run writes
`~/.config/termbeat/stations.json` with the defaults and
`~/.local/state/termbeat/termbeat.log` for diagnostics.

---

## 3. Keybindings

| Key | Action |
| :-- | :-- |
| `Space` | Play / Pause |
| `n` / `→` | Next station |
| `p` / `←` | Previous station |
| `s` | Stop (tears the stream down; `Space` re-tunes) |
| `↑` / `+` / `=` | Volume +5 |
| `↓` / `-` / `_` | Volume −5 |
| `m` | Mute / unmute |
| `r` | Toggle loop indicator |
| `1`–`9` | Jump to preset *n* |
| `v` | Cycle visualizer (Spectrum ↔ Oscilloscope/Braille) |
| `t` | Cycle colour theme |
| `d` | Cycle design aesthetic |
| `l` | Open / close the station directory drawer |
| `q` / `Ctrl-C` / `Esc` | Quit (`Esc` closes the drawer first if it is open) |

**In the drawer:** `↑`/`↓` move the selection, `PageUp`/`PageDown` jump seven, `Home`/`End` go to the
ends, `Enter` tunes the selected station, `l`/`Esc` closes.

All of this is dispatched by a single method, `handle_key(key) -> bool` (`radio.py:2329`); returning
`False` quits.

---

## 4. Architecture: processes, threads, data flow

```
                         ┌───────────────────────────────────────────┐
   terminal (PTY) ◀──────│ radio.py   —   main thread (render loop)   │
        stdin  ──────────▶│  parse_key_bytes → handle_key             │
                          │  update_physics → render_frame            │
                          │  emit_frame  (damage-tracked ANSI)        │
                          └───┬───────────┬───────────────┬───────────┘
             daemon threads   │           │               │
                 ┌────────────▼──┐  ┌─────▼───────┐  ┌────▼─────────────┐
                 │ MetadataScraper│  │ Cava reader │  │ StreamPlayer:    │
                 │  (HTTP poll)   │  │  (pipe→bands)│  │  _supervise     │
                 └──────┬─────────┘  └─────▲───────┘  │  _read_loop     │
                        │ keep-alive        │ ascii    └──┬──────────▲───┘
                        │ JSON              │ frames      │ JSON cmd │ JSON reply
              ┌─────────▼──────────┐   ┌────┴────┐   ┌─────▼──────────┴──┐
              │ api.somafm.com …   │   │  cava   │   │  mpv --idle       │
              │ api.plaza.one …    │   │ (FFT)   │   │  UNIX socket IPC  │
              │ …radioparadise…kexp│   └────▲────┘   └───┬───────────▲───┘
              └────────────────────┘        │ monitor    │ HTTP      │ PCM
                                            │ source     ▼           │
                                    ┌───────┴────────────────────────┴──┐
                                    │  PipeWire / PulseAudio  ·  network │
                                    └───────────────────────────────────┘
```

### Thread inventory (v3)

| Thread | Owner | Job |
| :-- | :-- | :-- |
| main | — | input, physics, render, emit, pacing |
| `_supervise` | `StreamPlayer` | start mpv, reconnect on failure, restart if it dies |
| `_read_loop` | `StreamPlayer` | **drain the IPC socket**, parse replies/events into `_props` |
| `_reader_loop` | `CavaStreamEngine` | read ASCII bar frames from the cava pipe into `raw_bands` |
| `MetadataScraper` | itself (`threading.Thread`) | poll the tuned provider's HTTP API |

All are `daemon=True`. Shared state is guarded by small locks: `StreamPlayer._send_lock` and
`_state_lock`, `CavaStreamEngine.lock`, `HttpSession._lock`. `PLAYLIST` is a module global; the
metadata thread mutates the station dicts in place (only string/int leaf values), the render thread
only reads them — benign under CPython's GIL for this access pattern.

### The main loop (`run`, `radio.py:2419`)

```python
with RawInput() as user_input:
    next_deadline = time.monotonic()
    while self.running:
        for key in user_input.get_keys():          # every key since last frame
            if not self.handle_key(key):
                self.running = False
        self.t_sec = time.monotonic() - self.t0     # wall clock for animation
        self.update_physics()                        # 1 step of ballistics + state
        cols, rows = shutil.get_terminal_size((104, 30))
        lines = self.render_frame(cols, rows, THEMES[self.theme_idx], frame)[:rows]
        self.emit_frame(lines)                        # write only changed rows
        active = self.is_playing and not self.is_stopped and self.tuning_glitch_frames == 0
        next_deadline += ACTIVE_FRAME_TIME if active else IDLE_FRAME_TIME
        user_input.wait_readable(next_deadline - now) # block on stdin, not sleep
```

Key properties:

- **Time is wall-clock, not frame-count.** `t_sec` drives every animation. The pre-fix code used
  `frame * 0.04` while the loop actually slept `0.045 s` + render time, so waveforms ran ~12% slow
  and drifted against the audio.
- **Pacing is adaptive.** `ACTIVE_FRAME_TIME = 0.045` (~22 FPS) while audio flows;
  `IDLE_FRAME_TIME = 0.20` (~5 FPS) when paused/stopped/erroring. The wait is
  `select()` on stdin, so a keypress is serviced immediately even at the idle rate.
- **Deadline accumulation** (`next_deadline += interval`) corrects for render jitter instead of
  letting it accrue; if the loop falls behind, the deadline resyncs to `now`.

---

## 5. The audio engine — `StreamPlayer`

`radio.py:760`. Owns the `mpv` subprocess and the IPC socket.

### Why a reader thread is mandatory

mpv answers **every** IPC command with a JSON line and also emits asynchronous events. If nothing
reads them they queue on the socket. Measured on this machine: about **300 commands** — roughly 70
seconds of ordinary volume tapping — fills the 212,992-byte kernel socket buffer, after which **mpv
spins at 100% of a CPU core** and silently ignores all further commands, while the old UI kept
showing `PLAYING`. The v3 `_read_loop` (`radio.py:891`) drains the socket continuously:

```python
def _read_loop(self):
    sock, buf = self.sock, b""
    while self._running and sock is not None and self.sock is sock:
        chunk = sock.recv(65536)
        if not chunk:
            break                       # mpv closed the socket
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line.strip():
                self._handle_message(line.strip())
        if len(buf) > (1 << 20):        # runaway partial line — resync
            buf = b""
    if self.sock is sock:
        self._drop_connection()
```

`_handle_message` (`radio.py:917`) routes by shape: `property-change` events update `self._props`
under `_state_lock`; `end-file` with `reason in ("error","unknown")` sets `_load_failed`;
`start-file`/`file-loaded` clear it. On connect, `_apply_desired_state` subscribes to the properties
in `OBSERVED`:

```python
OBSERVED = ("pause", "core-idle", "paused-for-cache", "media-title",
            "idle-active", "demuxer-cache-duration")
```

so `media-title` (the ICY now-playing string) arrives by push — `get_media_title()` is a dict lookup,
not a blocking round trip as before.

### Supervision

`_supervise` (`radio.py:813`) runs on its own thread so the **first frame is not blocked** on mpv
coming up. It spawns mpv (`_spawn_mpv`, `radio.py:854`), waits up to 5 s for the socket, connects,
starts `_read_loop`, and re-applies desired state (`_want_url`, `_want_volume`, `_want_pause`,
`_want_mute`). If mpv exits or the socket drops, it reconnects with exponential backoff
(0.4 s → 10 s) and replays that state, so a stream survives an mpv crash or a network blip.

mpv is launched with:

```
mpv --no-video --idle --input-ipc-server=<sock> --really-quiet --audio-display=no
    --cache=yes --demuxer-max-bytes=8MiB
```

and `preexec_fn=_die_with_parent`, which calls `prctl(PR_SET_PDEATHSIG, SIGTERM)` in the child so
the kernel kills mpv if `radio.py` dies without cleaning up — see [§12](#12-lifecycle-and-signal-handling).

### `health()` → the status badge

```python
def health(self):                       # -> (state_string, is_really_playing)
    if not self.has_mpv:                 return NO_MPV,   False
    if not self.is_connected:            return (ERROR if attempts > 3 else STARTING), False
    if self._load_failed:               return ERROR,    False
    if not self._want_url or idle_active: return IDLE,    False
    if paused_for_cache:                return BUFFERING, False
    if pause:                           return PAUSED,   False
    if core_idle:                       return BUFFERING, False
    return PLAYING, True
```

`update_physics` calls this every frame and stores `(stream_state, stream_live)`. The second value
gates the visualizer and the elapsed timer: when it is `False`, `effective_vol` is forced to `0`, the
bars fall to zero, and the clocks freeze. This is why a dead or buffering stream now *looks* dead
instead of showing fabricated music.

### Socket location

`_runtime_dir()` (`radio.py:95`) puts the socket at `$XDG_RUNTIME_DIR/termbeat/mpv-<pid>.sock`
(mode 0700, per-user) rather than the world-readable, guessable `/tmp/termbeat_mpv_<pid>.sock`.

---

## 6. The spectrum engine — `CavaStreamEngine`

`radio.py:1328`. Wraps a `cava` subprocess configured to emit raw ASCII bar values.

`_start_cava` (`radio.py:1347`) writes a temp config into the runtime dir:

```ini
[general]
bars = 18
framerate = 30
[input]
method = pulse
source = auto
[output]
method = raw
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = 100
bar_delimiter = 59        ; ';'
frame_delimiter = 10      ; '\n'
[smoothing]
monstercat = 1
noise_reduction = 77
```

`_reader_loop` (`radio.py:1394`) splits each line on `;`, normalises the 18 values to `0.0–1.0`, and
stores them with a timestamp under `self.lock`. `get_bands()` returns `(bands, is_active)` where
`is_active` is true only if the data is < 0.5 s old **and** at least one band exceeds 0.02 — so
silence reads as inactive and `update_physics` falls back to the simulation.

### Suspend on pause (v3)

A running `cava` costs ~2.1% of a CPU core computing an FFT of whatever the sound card is doing —
including silence — and the pre-fix code never stopped it. `set_suspended(bool)` (`radio.py:1410`)
sends `SIGSTOP`/`SIGCONT`:

```python
def set_suspended(self, suspended):
    if suspended == self.is_suspended or self.proc is None:
        return
    self.proc.send_signal(signal.SIGSTOP if suspended else signal.SIGCONT)
    self.is_suspended = suspended
```

`update_physics` calls `set_suspended(not wants_audio)` every frame. `cleanup()` sends `SIGCONT`
first if the process is stopped — a `SIGSTOP`ped process cannot act on `SIGTERM`.

---

## 7. Now-playing metadata — `MetadataScraper` + `HttpSession`

`radio.py:1047` and `radio.py:1122`.

### `HttpSession` — keep-alive JSON with ETag revalidation

Standard-library only (`http.client`). Pools one connection per `(scheme, host)`, retries once on a
stale pooled socket, sends `If-None-Match` when it has an ETag and returns the cached body on `304`.
Measured on the four metadata endpoints, **93–96% of the wire bytes for the small responses were TLS
handshake** on the pre-fix one-shot `urllib` requests (a 295-byte answer cost 6,764 bytes on the
wire). None of the four APIs actually send an `ETag` today, so that path is currently inert but
harmless; keep-alive is where the saving comes from.

### Polling strategy (v3)

The pre-fix scraper polled **all four** provider APIs **every 12 seconds regardless of which station
was tuned** — 1,200 HTTPS requests/hour, a measured 24.4 MB/hour, 43% of the bandwidth of the audio
stream itself. v3:

| | Interval | What it fetches |
| :-- | :-- | :-- |
| **Tuned provider** | 30 s | just the current station's now-playing |
| **Directory sweep** | 600 s | all providers, to refresh listener counts for stations you are *not* on |
| **On failure** | exponential backoff to 300 s | — |

`set_active_station(station)` (`radio.py:1161`) is called from `_tune`; it marks the tuned slot due
immediately. `_tuned_request()` (`radio.py:1179`) picks the URL and apply-function for the current
provider. For SomaFM specifically it uses the **per-channel** endpoint
`https://api.somafm.com/songs/<id>.json` — **911 bytes** against **52,751 bytes** for the full
`channels.json` directory, a 58× reduction on the endpoint that dominated this app's traffic.

Per-provider apply functions (`_apply_somafm`, `_apply_somafm_channel`, `_apply_plaza`,
`_apply_radioparadise`, `_apply_kexp`) write `track`, and where available `listeners`,
`track_duration`, `track_elapsed`, `signal` back onto the matching `PLAYLIST` dicts.

---

## 8. Input — `RawInput` and `parse_key_bytes`

`radio.py:604` and `radio.py:673`.

The pre-fix `get_key()` did `os.read(fd, 32)` and matched the **entire buffer** against single-key
byte patterns, so **any two keys arriving within one frame matched nothing and were silently
dropped** — holding a key down, or key-repeat scrolling the drawer, did nothing.

`parse_key_bytes(data) -> (keys, leftover)` is a proper incremental parser:

- **CSI** (`ESC [ … final`) and **SS3** (`ESC O final`) sequences → `UP`/`DOWN`/`LEFT`/`RIGHT`,
  `HOME`/`END`, `PAGEUP`/`PAGEDOWN`, `BACKTAB` (`_CSI_KEYS`, `radio.py:593`).
- Control bytes → `ENTER`, `SPACE`, `TAB`, `BACKSPACE`, `QUIT` (Ctrl-C).
- Everything else → decoded as UTF-8, 1–4 bytes at a time.
- A trailing **partial** escape sequence or partial multi-byte character is returned as `leftover`
  and prepended to the next read, so a sequence split across two `read()`s is preserved.

`RawInput.get_keys()` (`radio.py:717`) drains stdin non-blockingly into one buffer, runs the parser,
and caps the result at `MAX_KEYS_PER_FRAME = 32` so a paste cannot queue hundreds of station changes.
A lone `ESC` is held for `ESC_TIMEOUT = 0.05 s` to disambiguate it from the start of an arrow
sequence before being delivered.

`wait_readable(timeout)` is `select()` on the stdin fd — the loop blocks here instead of
`time.sleep`, which is what keeps keys responsive at the 5 FPS idle rate.

---

## 9. The rendering pipeline

A frame is a `list[str]`, one entry per terminal row, each already exactly `cols` cells wide.
`render_frame` (`radio.py:2478`) dispatches on `design_style` to one of four ~90–370-line renderers.

### 9.1 Width measurement

Everything downstream depends on measuring the *display width* of a string that contains ANSI escape
sequences and possibly wide or zero-width characters.

| Function | Line | Role |
| :-- | :-- | :-- |
| `char_width(c)` | 492 | width of one character: 0 (combining/zero-width/VS), 1, or 2 (East Asian Wide/Fullwidth). Memoised in `_CHAR_WIDTH_CACHE`. |
| `_measure(clean)` | 506 | width of an escape-free string; `@lru_cache(maxsize=128)` |
| `str_width(s)` | 521 | strips ANSI via `ANSI_ESCAPE_RE`, fast-paths pure ASCII, else `_measure` |
| `cell_slots(text)` | 532 | splits a string into one entry per *cell* (a wide glyph → itself + an empty continuation slot); combining marks fold into the preceding cell. `@lru_cache(maxsize=128)` |
| `truncate_ansi(s, w)` | 554 | cuts to `w` visible cells without ever splitting an escape sequence |
| `fit_row(s, w, bg, fill)` | 580 | the workhorse: truncate if long, pad with `fill` if short, so the result is **exactly** `w` cells |

`_measure` was, in the pre-fix profile, **55% of all render time** — its `isascii()` fast path never
fired because every row contains box-drawing glyphs, so every row ran a per-character Python loop
(4.8M `ord()` calls per 1,500 frames). v3 adds `_NONTRIVIAL_WIDTH_RE` (`radio.py:482`), a single
compiled character class covering every codepoint that is *not* exactly one cell wide — generated
offline by classifying all of `range(0x110000)` with `unicodedata`. If it does not match, the width
is just `len()`:

```python
@functools.lru_cache(maxsize=128)
def _measure(clean):
    if not AMBIGUOUS_IS_WIDE and not _NONTRIVIAL_WIDTH_RE.search(clean):
        return len(clean)
    return sum(char_width(c) for c in clean)
```

Result: the measure path is 1.19–1.58× faster and byte-identical to the original on non-combining
input; combining marks are now correctly width 0 (they were counted as 2). `maxsize=128` measured
better than 8192 — a larger cache just churns on the ever-changing visualizer rows.

`TERMBEAT_AMBIGUOUS_WIDTH=2` forces East-Asian *Ambiguous* glyphs (which the whole UI chassis is
built from) to width 2, for terminals in CJK locales configured that way.

### 9.2 The damage-tracked emitter — `emit_frame`

`radio.py:2389`. The pre-fix loop re-serialised and re-sent the **entire screen every frame** — a
measured 563 KB/s at 101×54 while playing, and *the same* 563 KB/s while paused, where only 0.2% of
rows differ.

```python
def emit_frame(self, lines):
    prev = self._prev_lines
    if prev is None or len(prev) != len(lines):
        # full repaint: home, every row + clear-to-EOL, clear-below
        payload = "\033[H" + "\n".join("\033[0m" + l + "\033[K" for l in lines) + "\033[J"
    else:
        # only the rows that changed, addressed absolutely
        parts = ["\033[%d;1H\033[0m%s\033[K" % (i + 1, line)
                 for i, line in enumerate(lines) if line != prev[i]]
        if not parts:
            self._prev_lines = lines
            return 0
        payload = "".join(parts)
    sys.stdout.write(payload); sys.stdout.flush()
    self._prev_lines = lines
```

Each emitted row is prefixed with `\033[0m` and positioned absolutely (`\033[<row>;1H`), so a row
never depends on colour state left by the row above — a requirement for partial repaint to be
correct. `_prev_lines` is reset to `None` (forcing a full repaint) on resize and after the
"terminal too small" screen. A regression test (`tests/test_termbeat.py`) drives a small ANSI
terminal model and asserts the incremental stream paints the identical screen to a full repaint,
across 25 frames.

Measured effect: ~9× fewer output bytes while playing, and near-silence while paused (§13). The
larger, unmeasured win is on the *other* side of the PTY — the terminal emulator no longer parses
and repaints an entire screen 22 times a second.

### 9.3 Layout

Each renderer chooses a form factor from the terminal size:

| Form factor | Condition (Retro Hi-Fi) | Notes |
| :-- | :-- | :-- |
| Studio Tower | `rows ≥ 32 and cols ≥ 70` | tall; large visualizer, full inline directory |
| Deck-78 compact | `cols < 102` and not tall | 78-col chassis, visualizer beside the LCD |
| Standard deck | otherwise | fixed 102-column chassis |
| Too-small | `cols < 70 or rows < 18` | `render_btop_size_warning` (`radio.py:1579`) |

`render_frame`'s output is clamped with `lines[:rows]` in `run()` so an off-by-one can never scroll
the frame. Shared sub-renderers: `render_transport_bar` (per-width button labels at 68/54/44 cols),
`render_status_bar` (`box`/`bracket`/`plain` modes), `render_button`, `render_drawer_rows`.

### 9.4 Visualizers

| Method | Line | Output |
| :-- | :-- | :-- |
| `get_equalizer_rows` | 1882 | 18-band spectrum, interpolated to the panel width, 9 block glyphs `▁▂▃…█` with a floating peak-hold cap `▔` |
| `get_oscilloscope_rows` | 1948 | three summed sine components (bass/mid/treble weighted), `∿`/`~` on the trace, `·` near it |
| `get_braille_wave_rows` | 2004 | same wave at 2×4 sub-cell resolution using Braille codepoints `U+2800 + dotmask` |
| `get_tuning_glitch_rows` | 2075 | 5-frame static-noise "tuning" effect on station change, from `STATIC_CHARS` |

The spectrum's ballistics live in `update_physics` (§10), not here; these methods only rasterise the
current `band_heights` / energies into rows.

### 9.5 Themes and colours

`THEMES` (`radio.py:355`) is five dicts of RGB triples. At import each is augmented with
pre-built escape strings (`_c_frame`, `_c_accent`, `_c_bright`, `_c_dim`, `_c_warn`,
`_c_title_fg`, `_c_lcd_border`, …). The renderers read those directly; the pre-fix renderers rebuilt
every escape with `fg(*t_cfg[...])` on every frame (~31 `fg()` calls/frame in Retro Hi-Fi alone).
Theme-independent colours are module constants (`C_ERROR`, `C_MUTED`, `C_VOL_LABEL`, the `CYBER_*`
neon palette).

### 9.6 The status badge

`status_badge(t_cfg, compact=False)` (`radio.py:1546`) is the single source of the play-state label
and colour, replacing four independent copies that each derived it from `is_playing`/`is_stopped`
alone. It reads `self.stream_state` (from `health()`), so `BUFFERING` and `STREAM ERROR` are
reachable states in the UI.

---

## 10. State and physics — `update_physics`

`radio.py:1756`. One call per frame. In order:

1. **Poll real stream state.** `self.stream_state, self.stream_live = self.stream_player.health()`.
   If `mpv` is absent, `stream_live` falls back to `is_playing and not is_stopped` so the deck still
   animates like a toy.
2. **Suspend/resume cava.** `self.cava_engine.set_suspended(not wants_audio)`.
3. **Advance clocks** — `elapsed_seconds` and the per-track `track_elapsed`/`track_duration` — **only
   when `wants_audio and stream_live`**. Otherwise `last_tick`/`last_track_tick` are pinned to `now`,
   so a pause or a buffering stall is not credited to the track when audio returns.
4. **Compute `effective_vol`** — `0.0` if muted, not wanting audio, or `not stream_live`; else
   `volume / 100`.
5. **Get spectrum targets** — live cava bands scaled by a perceptual volume curve, or, if cava is
   inactive, a pure-Python simulation: per-band sine/cosine of `t_sec` plus noise, passed through
   `apply_monstercat_filter`.
6. **Ballistics** per band (`band_heights`): fast-attack spring up (`+= (target − h) * 0.60`),
   quadratic-gravity fall (`cava_fall += 0.035`; `h = peak * (1 − fall² · 1.25)`), clamped to
   `[0, max_height]`. Separate floating peak indicators (`peak_heights`, `peak_hold_frames`).
7. **Band energies** — `bass_energy`, `mid_energy`, `treble_energy` from slices of `band_heights`;
   these feed the oscilloscope and Braille wave.
8. **Decay button flashes and the tuning-glitch counter.**
9. Every 10th tick, if playing, pull `media-title` from mpv for generic/SomaFM stations that lack
   fresh API metadata.

`apply_monstercat_filter` (`radio.py:1730`) is CAVA's spatial smoothing (`cava.c`): each bar bleeds
into its neighbours by `value / (factor ** distance)`. v3 tables `factor ** distance` per
`(monstercat, n)` in `_monstercat_table` instead of calling `**` in the inner loop.

### Station change — `_tune(idx)`

`radio.py:1623`. One method, replacing three near-identical copies (`next_track`, `prev_track`,
`select_preset`, and the resume branch of `toggle_play` all call it). It resets the per-track state,
triggers the tuning glitch, calls `stream_player.load_stream(url)` + `set_pause(False)`, and calls
`meta_worker.set_active_station(station)` so the scraper switches provider and polls immediately.

---

## 11. Configuration, environment, files on disk

### `stations.json`

`~/.config/termbeat/stations.json` (or `$XDG_CONFIG_HOME/termbeat/…`). A JSON array of objects.
Written with the defaults on first run. Reloaded live when the mtime changes.

Every entry is passed through `normalize_station` (`radio.py:304`):

- **must** have a `url` with an `http`/`https` scheme — anything else (including `file://`) is
  rejected and logged, so a config file cannot make mpv open an arbitrary local path;
- missing keys are filled from `STATION_DEFAULTS` (`radio.py:295`), so the renderers — which index
  `station["genre"]`, `station["track"]`, etc. directly — cannot raise `KeyError` on a hand-edited
  file;
- text fields are coerced to `str`.

`normalize_playlist` drops unusable entries; if nothing survives, the defaults are used.

Recognised keys: `id`, `station`, `freq`, `url`, `bitrate`, `genre`, `signal`, `track`, `provider`
(`somafm` | `plaza` | `radioparadise` | `kexp` | `generic`). `provider` may be omitted — it is
inferred from the URL host by `MetadataScraper.provider_of`.

### Environment variables

| Variable | Effect |
| :-- | :-- |
| `TERMBEAT_DEBUG=1` | log level `DEBUG` instead of `INFO` |
| `TERMBEAT_AMBIGUOUS_WIDTH=2` | treat East-Asian Ambiguous glyphs as 2 cells |
| `XDG_CONFIG_HOME` | base for `stations.json` |
| `XDG_STATE_HOME` | base for the log file |
| `XDG_RUNTIME_DIR` | base for the mpv socket and cava config (falls back to `<tmp>/termbeat-<uid>/`, mode 0700) |

### Files created

| Path | Purpose | Cleaned up |
| :-- | :-- | :-- |
| `~/.config/termbeat/stations.json` | station list | persistent |
| `~/.local/state/termbeat/termbeat.log` | rotating-free append log | persistent |
| `$XDG_RUNTIME_DIR/termbeat/mpv-<pid>.sock` | mpv IPC | on exit (all paths except `SIGKILL`) |
| `$XDG_RUNTIME_DIR/termbeat/cava-*.conf` | cava config | on exit (all paths except `SIGKILL`) |

The log is the diagnostic channel — stdout is the UI, so nothing is ever printed there. Failure to
open the log is non-fatal (`NullHandler`), so the app runs on a read-only home directory.

---

## 12. Lifecycle and signal handling

### Startup order (`TermbeatPlayer.__init__`, `radio.py:1460`)

1. Plain state fields, `t0 = time.monotonic()`.
2. `CavaStreamEngine(...)` — spawns cava + reader thread if `cava` is on `PATH`.
3. `StreamPlayer()` — **does not block**; the supervisor thread brings mpv up asynchronously.
4. `MetadataScraper(PLAYLIST).start()`.
5. If playing: `load_stream(url)` and `set_active_station(station)`.

`main()` (`radio.py:3130`) then installs signal handlers and calls `app.run()`.

### Shutdown

`stop_app` (set as the `SIGINT`/`SIGTERM`/`SIGHUP` handler) just sets `self.running = False`; the
loop falls out of `while self.running` and its `finally:` calls `cleanup()`. `cleanup()`
(`radio.py:3112`) is idempotent (`_cleaned_up` guard) and:

1. stops the cava engine, the metadata worker, and the stream player (each wrapped so one failure
   doesn't block the others);
2. restores the terminal: `\033[?25h` (cursor), `\033[0m` (colour), `\033[?1049l` (leave alt
   screen);
3. prints the sign-off line and logs `termbeat exited cleanly`.

Each subprocess wrapper (`StreamPlayer.cleanup`, `CavaStreamEngine.cleanup`) also `atexit`-registers
itself, so an unexpected interpreter exit still tears the children down.

### Orphan prevention

The pre-fix code handled `SIGINT`/`SIGTERM` but **not `SIGHUP`** — the signal a terminal sends when
its window is closed, which is how many people quit a TUI. Python's default `SIGHUP` action
terminated the process *without running `atexit`*, leaving the socket and cava config on disk and
**mpv orphaned — still streaming from the CDN and still playing audio** with no UI to stop it.

v3 fixes this two ways:

1. `SIGHUP` is now in the handler list, so the normal clean shutdown runs.
2. Every child is spawned with `preexec_fn=_die_with_parent`, which calls
   `prctl(PR_SET_PDEATHSIG, SIGTERM)` — the kernel sends the child `SIGTERM` the moment its parent
   dies, **even on `SIGKILL`** where no Python code can run.

Verified (start app, mute, then kill it the stated way):

| Exit path | v2: files left / mpv orphaned | v3 |
| :-- | :-- | :-- |
| `q` keypress | clean / no | clean / no |
| `SIGTERM` | clean / no | clean / no |
| `SIGINT` | clean / no | clean / no |
| **`SIGHUP`** | **2 files / yes** | **clean / no** |
| **`SIGKILL`** | **2 files / yes** | **2 files / no orphan** |

(`SIGKILL` cannot run cleanup, so the two runtime-dir files remain; the process is gone and mpv is
reaped by the kernel.)

---

## 13. Performance benchmarks

Machine: Intel Core Ultra 7 258V (8 cores) · Linux 7.2.2 · Python 3.14.7 · `mpv` + `cava` present ·
PipeWire. Harnesses in [`bench/`](../bench/). Whole-system numbers are with audio **muted** (so the
spectrum is static and the diff renderer is near its best case); the render-path table below is the
honest playing-with-motion figure. [`RESULTS.md`](RESULTS.md) has the full per-geometry tables and
the profile behind the v2 column.

The v2 columns are the state before the September 2026 fix pass, kept because they are the evidence
for why the code looks the way it does; the changes themselves are listed in
[`history.md`](history.md).

### 13.1 Whole system, 101×54, real mpv + cava

| Metric | v2 (pre-fix) | v3 (current) |
| :-- | --: | --: |
| `radio.py` RSS | 34.7 MB | 40.4 MB |
| `mpv` RSS | 85.2 MB | 85.2 MB |
| `cava` RSS | 12.9 MB | 13.1 MB |
| **Total RSS** | **~133 MB** | **~138.7 MB** |
| CPU, playing | 8.2 % | **6.1 %** |
| CPU, paused | 6.5 % | **0.8 %** |
| `cava` CPU, paused | 2.1 % | **0.0 %** |
| PTY output, playing | 563 KB/s | 1.5 KB/s *(muted)* |
| PTY output, paused | 563 KB/s | **0.1 KB/s** |
| Threads (`radio.py`) | 3 | 5 |

### 13.2 mpv IPC saturation — 583 volume keypresses over 70 s

| | v2 | v3 |
| :-- | --: | --: |
| Socket write queue after | 213,504 B *(kernel ceiling)* | **0 B** |
| `mpv` CPU after | **100.5 %** | **3.2 %** |
| `Space` (pause) after | ignored — mpv still 100.8 % | **works — mpv → 0.3 %** |

### 13.3 Metadata traffic (tuned to a SomaFM station)

| | v2 | v3 |
| :-- | --: | --: |
| Steady-state wire rate | 6.95 KB/s | **0.12 KB/s** |
| Per hour | 24.4 MB | **0.4 MB** |
| HTTPS requests / hour | 1,200 | **144** |
| SomaFM now-playing fetch | 52,751 B / 12 s | 911 B / 30 s |

### 13.4 Render path (isolated; simulated spectrum in motion)

Unchanged by design — the renderer was never the bottleneck.

| Geometry · style · viz | p50 render | CPU @ 22 FPS | max FPS |
| :-- | --: | --: | --: |
| 80×24 · Retro · Spectrum | 0.16 ms | 0.3 % | 6,400 |
| 101×54 · Retro · Spectrum | 0.44 ms | 1.0 % | 2,300 |
| 200×60 · Retro · Spectrum | 0.50 ms | 1.1 % | 2,000 |
| 101×54 · Modern Neo · Braille | 0.35 ms | 0.8 % | 2,900 |

Output bytes per frame at 101×54, Retro/Spectrum, in motion: full repaint **602 KB/s** → span-diff
**≈ 63 KB/s** (~9.5×). Paused: **586 KB/s → ~1 KB/s**.

`_measure` micro-benchmark (v2 → v3): 1.19× (80×24) to 1.58× (Modern Neo Braille 101×54) faster on
the measure path; whole-frame effect is small because measurement is no longer dominant.

### 13.5 Context

| App | Stack | RSS | Idle CPU |
| :-- | :-- | --: | --: |
| **termbeat** (v3) | Python + mpv + cava | **~139 MB** | 0.8–6 % |
| `cmus` / `mocp` | C + ncurses | 15–35 MB | 0.5–1 % |
| Browser tab (SomaFM) | Chromium | 500 MB – 1.2 GB | 4–12 % |
| Spotify desktop | Electron | 450–800 MB | 3–8 % |

`mpv` is ~61% of termbeat's memory and is not `radio.py`'s code. See
[`../rs/rust-rewrite-plan.md`](../rs/rust-rewrite-plan.md) for the argument that removing the two
subprocesses — not rewriting the renderer — is where a large footprint reduction lives.

### 13.6 Test suite

`python3 tests/test_termbeat.py` — **16 checks, all passing**: width parity vs the legacy algorithm,
multi-key parsing, split-escape survival, config validation, cell-exact marquee for CJK titles,
every layout fits its terminal (6 geometries × 4 styles × 2 visualizers × drawer), the diff renderer
paints the same screen as a full repaint, diff byte savings, cava suspend/resume, and honest
dead-stream behaviour (error badge, collapsed visualizer, frozen timer).

---

## 14. Security considerations

- **IPC socket** is in `$XDG_RUNTIME_DIR/termbeat/` (mode 0700, per-user), not world-readable `/tmp`
  with a PID-guessable name.
- **`stations.json`** is validated: only `http`/`https` URLs reach `mpv loadfile`; a `file://` or
  other scheme is rejected and logged. The file is still user-writable and trusted for *content*
  (station names, etc.) — it is the user's own config.
- **No shell** is invoked anywhere; `subprocess.Popen` is always called with an argument list.
- **Metadata APIs** are contacted over HTTPS with a fixed `User-Agent`; responses are parsed as JSON
  and only specific string/int fields are read. A hostile response can at worst put attacker-chosen
  text in the marquee.
- **Logs** go to `~/.local/state/termbeat/termbeat.log` and contain station names, mpv/cava PIDs,
  socket paths, and error strings — no credentials (there are none).
- `preexec_fn` runs `prctl` via a `libc` handle resolved **once before any fork**, so the pre-exec
  hook only dereferences an already-bound pointer (fork-safe).

---

## 15. Known limitations and non-goals

- **`ETag` revalidation is inert today** — none of the four metadata APIs send `ETag`. The code path
  is correct and free; it will start saving bytes if any of them adds one. Keep-alive is the actual
  current win.
- **Single file, single class.** `TermbeatPlayer` is ~1,700 lines and owns state, input, physics,
  four renderers, and lifecycle. The four renderers still share ~70% of their structure by
  convention, not by a common layout engine. This was left deliberately untouched by the fix pass to
  keep the diff reviewable; splitting into a package is a separate task — see
[`../rs/improvement-ideas.md`](../rs/improvement-ideas.md).
- **No Windows audio path.** `termios`/`tty` absence is handled (UI renders, input disabled), but
  `mpv` IPC over `AF_UNIX` and `SIGSTOP`/`prctl` are POSIX. A Windows port would need a named pipe
  and a different child-reaping strategy.
- **Not a general music player** — no local files, no playlists beyond the station list, no seek
  (streams are live).
- **RSS regression** (+5.7 MB against the pre-fix version) is accepted in exchange for logging,
  child reaping, and the IPC fix — see [`history.md` §3](history.md#3-what-the-fix-pass-cost).

---

## 16. Development: tests, benchmarks, extending

```sh
python3 tests/test_termbeat.py          # 16 checks, ~5 s, no network, no subprocesses
python3 bench/benchmark_render.py       # isolated render path, all styles × geometries
python3 bench/benchmark_render.py --paused
python3 bench/benchmark_render.py --cava-live
python3 bench/benchmark_system.py 101 54 25   # real app in a PTY: RSS/CPU/bytes, playing vs paused
```

The render benchmark stubs out `StreamPlayer`/`CavaStreamEngine`/`MetadataScraper` (see the stub
classes at the top of the file) so it measures only Python. `benchmark_system.py` spawns the real
app in a `pty`, mutes it immediately, and samples `/proc/<pid>/stat` + `statm` for `radio.py`, `mpv`,
and `cava`.

### Adding a station

Edit `~/.config/termbeat/stations.json` — the running app reloads it. Minimum entry:

```json
{ "station": "My Stream", "url": "https://example.com/stream.mp3", "freq": "95.5", "genre": "TEST" }
```

Set `"provider"` to one of `somafm|plaza|radioparadise|kexp` to get live now-playing, or leave it
off (or `"generic"`) to fall back to mpv's ICY `media-title`.

### Adding a theme

Append a dict to `THEMES` (`radio.py:355`) with the same keys as the others. The `_c_*` escape
strings are derived automatically by the loop right after the list.

### Adding a design style

Add a `render_<name>` method, extend `design_names`, and add a branch to `render_frame`
(`radio.py:2478`). It must return a `list[str]` of rows each exactly `cols` cells wide (use
`fit_row`); `run()` clamps to `rows` and `emit_frame` handles the rest.

### Prototyping before you wire anything in

[`designs/`](../designs/) and [`gui/`](../gui/) hold standalone sketches that run against synthetic
audio and a fake player, so a visualizer or an interface idea can be seen before it touches
`radio.py`:

```sh
python3 designs/gallery.py    # every visualizer sketch
python3 gui/gallery.py        # launcher menu for the interface mock-ups
```

The idea each one comes from is catalogued in [`designs/README.md`](../designs/README.md) and
[`gui/README.md`](../gui/README.md); the backlogs themselves are in [`../rs/`](../rs/).

---

## 17. Code map

| Lines | Symbol | Role |
| --: | :-- | :-- |
| 52–107 | `_init_logger`, `_die_with_parent`, `_runtime_dir` | infra: file log, `PR_SET_PDEATHSIG`, per-user runtime dir |
| 109–288 | `DEFAULT_PLAYLIST` | 16 preset stations |
| 289–353 | `normalize_station`, `normalize_playlist`, `load_stations_config` | config loading + validation |
| 355–422 | `THEMES` (+ derived `_c_*`) | 5 colour themes |
| 424–472 | `fg`, `bg`, `RST`, `C_*`, `CYBER_*`, pacing constants, `BLOCKS` | colour + timing primitives |
| 474–590 | `str_width`, `char_width`, `_measure`, `cell_slots`, `truncate_ansi`, `fit_row` | width measurement + row fitting |
| 593–758 | `_CSI_KEYS`, `parse_key_bytes`, `RawInput` | input |
| 760–1044 | `StreamPlayer` | mpv subprocess + IPC + supervision + `health()` |
| 1047–1120 | `HttpSession` | keep-alive JSON client |
| 1122–1326 | `MetadataScraper` | provider-scoped now-playing polling |
| 1328–1456 | `CavaStreamEngine` | cava subprocess + spectrum pipe + suspend |
| 1459–1543 | `TermbeatPlayer.__init__` | all mutable state |
| 1546–1728 | badges, `_tune`, track nav, `toggle_*`, `check_reload_stations` | commands |
| 1730–1880 | `apply_monstercat_filter`, `update_physics` | per-frame simulation |
| 1882–2164 | `get_*_rows` | visualizer rasterisers |
| 2166–2327 | `render_button`, `render_transport_bar`, `render_status_bar`, `render_drawer_rows` | shared sub-renderers |
| 2329–2417 | `handle_key`, `adjust_volume`, `emit_frame` | dispatch + damage-tracked output |
| 2419–2476 | `run` | the main loop |
| 2478–3110 | `render_frame` + `render_retro_hifi` / `_modern_neo` / `_minimal_zen` / `_cyberpunk` | the four full-frame renderers |
| 3112–3155 | `cleanup`, `main` | shutdown + signal wiring |

---

*Written as part of the September 2026 fix pass, and kept current with `radio.py`. Companions:
[`history.md`](history.md) · [`RESULTS.md`](RESULTS.md) ·
[`../rs/rust-rewrite-plan.md`](../rs/rust-rewrite-plan.md).*
