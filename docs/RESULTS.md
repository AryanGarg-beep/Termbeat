# termbeat — measured resource benchmarks

**Machine:** Intel Core Ultra 7 258V (8 cores) · Linux 7.2.2 · Python 3.14.7 · mpv + cava present · PipeWire
**Date:** 2026-09-08 · **Harnesses:** `bench/benchmark_render.py`, `bench/benchmark_system.py`

Re-measured from scratch. The numbers in `resource_footprint_and_optimization_study_plan.md` are
superseded — several were wrong by large factors (noted inline).

---

## 1. Render path (isolated: mpv/cava/metadata stubbed out)

500 frames per config. `phys` = `update_physics`, `rend` = `render_frame`. CPU% is of one core at the
shipped 22.2 FPS. `full` is the byte rate `run()` actually emits; `rowdiff`/`segdiff` are what a
damage-tracking renderer would emit instead (row-granular and span-granular).

### Playing, cava absent (simulated bands — the common case, since cava needs a monitor source)

| Geometry | Style | Viz | p50 | p95 | p99 | max FPS | CPU% | full KB/s | rowdiff | segdiff | rows changed |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 80×24 | Retro Hi-Fi | Spectrum | 0.16 | 0.16 | 0.17 | 6395 | 0.3% | 100.5 | 16.1 | **2.7** | 7.8% |
| 80×24 | Retro Hi-Fi | Osc | 0.16 | 0.17 | 0.18 | 6289 | 0.4% | 94.9 | 27.9 | 8.1 | 13.8% |
| 80×24 | Modern Neo | Spectrum | 0.18 | 0.19 | 0.20 | 5638 | 0.4% | 149.1 | 44.4 | 16.3 | 12.0% |
| 80×24 | Minimal Zen | Spectrum | 0.11 | 0.12 | 0.12 | 9120 | 0.2% | 106.2 | 38.1 | 11.4 | 10.7% |
| 80×24 | Cyberpunk | Spectrum | 0.16 | 0.17 | 0.17 | 6227 | 0.4% | 145.5 | 52.5 | 11.3 | 13.7% |
| 102×30 | Retro Hi-Fi | Spectrum | 0.20 | 0.22 | 0.22 | 4907 | 0.5% | 165.1 | 43.7 | 7.2 | 12.5% |
| 102×30 | Modern Neo | Spectrum | 0.29 | 0.31 | 0.32 | 3387 | 0.7% | 307.7 | 113.4 | 42.1 | 18.7% |
| 101×54 | Retro Hi-Fi | Spectrum | 0.44 | 0.46 | 0.48 | 2256 | 1.0% | **602.7** | 192.8 | **63.5** | 16.5% |
| 101×54 | Modern Neo | Spectrum | 0.39 | 0.41 | 0.43 | 2564 | 0.9% | 433.5 | 155.5 | 53.0 | 14.1% |
| 101×54 | Cyberpunk | Spectrum | 0.35 | 0.36 | 0.37 | 2870 | 0.8% | 377.9 | 187.3 | 29.3 | 17.4% |
| 200×60 | Retro Hi-Fi | Spectrum | 0.48 | 0.52 | 0.52 | 2068 | 1.1% | **749.3** | 170.9 | **67.3** | 12.6% |

**The renderer is not a bottleneck.** Worst case is 0.48 ms/frame — **1.1% of one core**, and it could
sustain 2,000 FPS. The old study's 4.86 ms / 10.8% Cyberpunk figure is gone: the starfield removal
landed and Cyberpunk is now among the cheaper styles.

### Paused — the same work, for nothing

| Geometry | Style | p50 | CPU% | full KB/s | diff KB/s | rows changed |
|---|---|--:|--:|--:|--:|--:|
| 101×54 | Retro Hi-Fi | 0.33 | 0.7% | **586.6** | **1.2** | **0.2%** |
| 101×54 | Modern Neo | 0.27 | 0.6% | 419.5 | 0.8 | 0.2% |
| 200×60 | Retro Hi-Fi | 0.37 | 0.8% | 732.9 | 1.5 | 0.2% |
| 80×24 | Retro Hi-Fi | 0.11 | 0.2% | 99.4 | 0.2 | 0.2% |

While paused, **0.2% of rows change and the app still emits 586 KB/s** — a **489× waste**. The only
thing moving is the blinking timer colon. `time.sleep(0.045)` at `radio.py:1749` is unconditional;
the adaptive-FPS fix recommended by the previous study was never applied.

### Profile — where render time actually goes

`cProfile`, Retro Hi-Fi / Spectrum @ 101×54, 1500 frames:

| function | tottime | cumtime | calls |
|---|--:|--:|--:|
| **`str_width`** (`radio.py:344`) | 0.561 s | **1.149 s (55%)** | 114,000 |
| `get_equalizer_rows` | 0.417 s | 1.138 s | 1,500 |
| `re.Pattern.sub` | 0.292 s | 0.292 s | 105,000 |
| `builtins.ord` | 0.217 s | 0.217 s | **4,846,164** |
| `unicodedata.east_asian_width` | 0.068 s | 0.068 s | 1,303,918 |
| `fit_row` | 0.021 s | 1.116 s | 97,500 |

`str_width` is **55% of the entire render path**. Its `clean.isascii()` fast path never fires,
because every row contains box-drawing or block glyphs — so each row falls into a per-character
Python loop: **3,230 `ord()` calls per frame**.

**Fix measured, output verified byte-identical:** replace the per-character loop with one C-level
regex `search` for any wide codepoint (return `len()` when there is none), plus an `lru_cache` for
repeated rows.

| config | as shipped | + wide-regex | + lru cache | speedup |
|---|--:|--:|--:|--:|
| Retro/Spectrum 80×24 | 0.160 ms | 0.148 | 0.134 | 1.19× |
| Retro/Spectrum 101×54 | 0.486 ms | 0.405 | 0.391 | 1.24× |
| Retro/Spectrum 200×60 | 0.595 ms | 0.478 | 0.454 | **1.31×** |
| Neo/Braille 101×54 | 0.322 ms | 0.247 | 0.204 | **1.58×** |
| Cyberpunk/Spectrum 101×54 | 0.370 ms | 0.306 | 0.284 | 1.30× |

Cache hit rate is 5456/5520 (99%) against just **63 distinct codepoints** — the whole UI alphabet.
(A memoised per-codepoint width dict *alone* gives 1.00× — the cost is the Python loop, not the
width lookup. Worth recording as a fix that looks obvious and does nothing.)

---

## 2. Whole system (real app in a pty, mpv + cava live, 101×54)

| process | RSS | CPU (%core) | threads |
|---|--:|--:|--:|
| `radio.py` | 34.7 MB | 3.7% | 3 |
| `mpv` | **85.6 MB** | 2.6% | 17 |
| `cava` | 12.9 MB | 1.9% | 3 |
| **TOTAL** | **133.2 MB** | **8.2%** | 23 |

pty output: **563 KB/s — 1,980 MB/hour of ANSI escape codes.**

**The prior study's ~83 MB is wrong: actual is 133 MB.** mpv alone measured 85.6 MB, not 53.2 MB.
mpv is **64% of total memory** — the Python process is a third of the footprint.

### Paused (same run, after Space)

| process | RSS | CPU |
|---|--:|--:|
| `radio.py` | 34.7 MB | 4.0% |
| `mpv` | 86.4 MB | 0.4% |
| `cava` | 12.9 MB | **2.1%** |
| **TOTAL** | 133.9 MB | **6.5%** |

- Pausing saves **21% of CPU** (8.2% → 6.5%). Only mpv actually stops working.
- **pty output is unchanged: 563 KB/s.** The UI repaints a frozen screen 22×/second.
- **`cava` keeps burning 2.1% doing FFT on silence forever** — it is never paused or stopped.

At 80×24 the same pattern holds: 6.7% playing → 4.7% paused (71%), 98 KB/s either way.

**Not measured: the terminal emulator.** This harness drives a headless pty, so nothing parses the
563 KB/s. In real use a terminal emulator must parse, shape and repaint every one of those bytes
22×/second — plausibly the largest single consumer in the pipeline, and entirely avoidable.

---

## 3. Process lifecycle — cleanup leaks on terminal close

Each row: start the app, mute, then terminate it the stated way.

| exit path | rc | `/tmp` leftovers | orphaned children |
|---|--:|--:|---|
| `q` keypress | 0 | 0 | none |
| SIGTERM | 0 | 0 | none |
| SIGINT (Ctrl-C) | 0 | 0 | none |
| **SIGHUP (terminal window closed)** | -1 | **2** | **`mpv`** |
| **SIGKILL (crash / OOM)** | -9 | **2** | **`mpv`** |

The prior study's claim — *"Socket files and CAVA configuration files are automatically unlinked upon
application exit"* — holds only for the three handled signals. **Closing the terminal window, the most
common way people quit a TUI, leaks the socket and the cava config and leaves `mpv` orphaned —
still streaming from the CDN and still playing audio, with no UI to stop it.**

`SIGHUP` has no handler, so Python's default terminates the process without running `atexit`.
Fix: handle SIGHUP, and set `PR_SET_PDEATHSIG` on the mpv/cava children so the kernel reaps them
whatever happens to the parent.

---

## 4. Metadata polling — 70× more traffic than reported

Measured at syscall level (`/proc/self/io`, so TLS handshake bytes are included). This is one poll
cycle, which `MetadataScraper` runs **every 12 seconds, for all four providers, regardless of which
station is tuned**:

| endpoint | payload | wire in | wire out | latency |
|---|--:|--:|--:|--:|
| SomaFM `channels.json` | **52,751 B** | 61,936 B | 1,776 B | 1439 ms |
| Plaza `status` | 461 B | 5,034 B | 1,787 B | 657 ms |
| Radio Paradise `now_playing` | 295 B | 6,764 B | 1,792 B | 1107 ms |
| KEXP `plays?limit=1` | 358 B | 4,551 B | 1,776 B | 373 ms |
| **total per cycle** | 53,865 B | **85,416 B** | | |

| metric | measured | prior study |
|---|--:|--:|
| sustained rate | **6.95 KB/s** | 0.10 KB/s (**70× low**) |
| per hour | **24.4 MB/hour** | — |
| HTTPS requests/hour | **1,200** | — |
| as % of a 128 kbps audio stream (16 KB/s) | **43.4%** | 0.6% |

Two compounding problems:

1. **SomaFM is 98% of the payload.** `channels.json` is the entire ~40-channel directory, with
   descriptions and artwork URLs, downloaded every 12 seconds to read one `lastPlaying` string.
2. **No connection reuse.** Radio Paradise's 295-byte answer costs 6,764 bytes on the wire — a fresh
   TCP + TLS handshake every time. For the three small endpoints, **93–96% of the bytes are
   handshake overhead**.

Polling only the tuned provider at 30 s, with `ETag`/`If-None-Match` and a keep-alive opener, would
cut this by well over 95% (a 304 on SomaFM is ~300 bytes).

---

## 5. Input handling — keys are dropped

`RawInput.get_key` (`radio.py:416`) does `os.read(fd, 32)` and then matches the **entire buffer**
against single-key patterns. Any two keypresses landing inside one 45 ms frame produce a buffer that
matches nothing, decodes to a multi-character string, and falls through every branch in `run()`:

| input arriving in one read | resulting `key` | outcome |
|---|---|---|
| `b'+'` | `'+'` | handled |
| `b'++'` | `'++'` | **dropped** |
| `b'++++++++'` (key auto-repeat) | `'++++++++'` | **dropped** |
| `b'\x1b[A\x1b[A'` (two Up arrows) | `'\x1b[A\x1b[A'` | **dropped** |
| `b'  '` (two spaces) | `'  '` | **dropped** |

So **holding down volume-up, or key-repeat scrolling the station directory, does nothing at all** —
the faster you press, the less happens. Fix: parse the buffer as a stream of keys and return a list,
or read one key at a time and loop.

---

## 6. mpv IPC socket — saturates in ~70 s of normal use, then mpv pins a core and controls die

`StreamPlayer._send_cmd` (`radio.py:499`) writes commands to mpv but **never reads the replies**.
mpv answers every command; those replies queue on the unix socket forever.

**Growth depends entirely on user input:**

| scenario | duration | commands | socket write queue |
|---|--:|--:|--:|
| Idle playback, no input | 200 s | 0 | flat at 6,912 B — **no growth** |
| One volume key / 120 ms | 20 s | 155 | 123,648 B |
| One volume key / 120 ms | 40 s | 309 | **213,504 B — kernel ceiling** |
| One volume key / 120 ms | 200 s | 1,542 | 213,504 B (pinned) |

`net.core.wmem_default` is 212,992 B. **~300 volume keypresses saturate it.**

**What happens once saturated (measured by watching mpv's own CPU):**

| step | action | mpv CPU | verdict |
|---|---|--:|---|
| 1 | playing, before saturation | 2.83% | normal |
| 2 | send Space (pause) | **0.50%** | command worked |
| 3 | send Space (resume) | 3.17% | command worked |
| — | *583 volume keys over 70 s → wq = 213,504* | | |
| 4 | playing, after saturation | **100.49%** | **mpv is spinning a full core** |
| 5 | send Space (pause) | **100.83%** | **command ignored — controls dead** |
| 6 | send Space (resume) | 100.66% | still dead |

The complete failure chain, all measured:

1. The user adjusts volume ~580 times (or changes stations repeatedly) — entirely ordinary use.
2. mpv's IPC reply queue hits the 212,992-byte kernel limit because nothing ever reads it.
3. **mpv goes from 2.8% to 100% of a CPU core** and stays there — it is spinning on a socket it
   cannot write to.
4. **Every playback control stops working.** Pause, play, next, volume: silently ignored.
5. **The UI shows no sign of any of this.** It keeps rendering at 22 FPS, still displaying
   `● PLAYING` and a ticking elapsed timer, because `is_connected` only flips on a *send* failure and
   sends still succeed.

This is worse than a memory leak: a laptop on battery ends up with a pegged core, dead controls, and
a UI insisting everything is fine. Fix: drain the socket in a reader thread (dispatching replies by
`request_id`), which is ~30 lines and also fixes B2's lost/split messages.

## 7. Corrections to the previous study

| metric | prior study | measured now | error |
|---|--:|--:|---|
| Total RAM | ~83 MB | **133.2 MB** | 1.6× low (mpv is 85.6 MB, not 53.2 MB) |
| mpv RSS | 53.2 MB | **85.6 MB** | 1.6× low |
| cava RSS | ~6.0 MB | **12.9 MB** | 2.2× low |
| Metadata bandwidth | 0.10 KB/s | **6.95 KB/s** | **70× low** |
| Cyberpunk 101×54 frame | 4.86 ms / 10.8% | **0.35 ms / 0.8%** | superseded — starfield removed |
| Retro 101×54 frame | 1.17 ms | **0.44 ms** | 2.7× pessimistic |
| "Sockets auto-cleaned on exit" | claimed | **false on SIGHUP/SIGKILL** | — |
| Adaptive FPS "proposed" | — | **never applied** | `sleep(0.045)` still unconditional |

---

## 8. What the measurements say to fix, in order

| # | Change | Measured payoff | Effort |
|---|---|---|---|
| 1 | **Damage-tracking renderer** (emit changed spans only) | 563 → ~64 KB/s playing (**9×**); 586 → 1.2 KB/s paused (**489×**); removes the unmeasured but large terminal-emulator parse cost | ~80 lines |
| 2 | **Adaptive frame interval** (0.045 s playing / 0.18 s idle) | ~75% of idle CPU and I/O; paused currently costs 79% of playing CPU for a frozen screen | 2 lines |
| 3 | **Poll only the tuned provider**, 30 s, ETag, keep-alive | 24.4 → <1 MB/hour (**>95%**); 1,200 → 120 req/hour | ~30 lines |
| 4 | **Handle SIGHUP + `PR_SET_PDEATHSIG`** | stops orphaned `mpv` streaming forever after the terminal closes | ~10 lines |
| 5 | **Fix `get_key`** to parse a buffer into multiple keys | key-repeat and fast input stop being silently dropped | ~15 lines |
| 6 | **Pause/stop `cava`** when playback is paused | 2.1% of a core, currently spent on FFT of silence | ~5 lines |
| 7 | **`str_width` wide-char regex fast path + lru_cache** | 1.19–1.58× render speed, output byte-identical | ~10 lines |
| 8 | **Drain the mpv IPC socket** in a reader thread | stops the write queue pinning at the 213 KB kernel ceiling after ~40 s of use | ~30 lines |

Items 1, 2 and 3 are the whole game. Item 7 is worth doing but note the renderer was never the
problem: at 0.48 ms worst case it is ~2,000 FPS capable against a 22 FPS requirement.

---

## 9. What this implies for a rewrite (Rust/Go)

The measurements sharpen the argument considerably.

**Rewriting the renderer for speed is pointless.** It is 1.1% of one core at worst and could sustain
2,000 FPS. Rust would take 0.48 ms → ~20 µs, saving ~1% of one core.

**Rewriting to remove the subprocesses is the real case.** Measured composition of 133.2 MB:

```
mpv        85.6 MB (64%)   ← symphonia + cpal removes this entirely
radio.py   34.7 MB (26%)   ← ratatui: ~4 MB
cava       12.9 MB (10%)   ← rustfft on the decoded PCM removes this entirely
```

A native Rust build (`symphonia` decode + `cpal` output + `rustfft` + `ratatui`) plausibly lands
around **10–18 MB total against a measured 133 MB — a 7–13× reduction**, and it structurally
eliminates measured defects rather than patching them: no IPC socket to saturate (§6), no `/tmp`
files to leak (§3), no orphaned `mpv` (§3), no `cava` burning 2.1% on silence (§2), and a spectrum
computed from real PCM instead of the synthetic sine-and-`random.uniform` fallback.

**The diff renderer is the one thing you get for free.** `ratatui` double-buffers cells and emits
only changes by default — measured here as a 9× reduction while playing and 489× while paused. In
Python it is ~80 lines you must write yourself (item 1 above), which is a good deal either way.

**Go + Bubbletea** gets the diff renderer and a static binary at ~10–15 MB, but keeps `mpv` and
therefore keeps 64% of the memory. It is the right choice only if the goal is distribution, not
footprint.
