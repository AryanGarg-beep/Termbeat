# termbeat — Audio Visualizer Ideas

*Appendix to [`improvement-ideas.md`](improvement-ideas.md). Options for new `get_<name>_rows`
visualizers.*

> **Runnable previews:** 20 of these are sketched in [`../designs/`](../designs/). Run
> `python3 designs/gallery.py` to flip through them, or `python3 designs/<name>.py` for one.
> They render against a synthetic audio model (no mpv/cava/network). See
> `designs/README.md` for the file→idea map and how to add more. Nothing is wired into
> `radio.py`.

---

## What exists today

| Method | Look |
| :-- | :-- |
| `get_equalizer_rows` (`radio.py:1882`) | 18-band spectrum, 9 block glyphs `▁▂…█`, floating peak cap `▔` |
| `get_oscilloscope_rows` (`radio.py:1948`) | three summed sines, `∿`/`~` trace + `·` near it |
| `get_braille_wave_rows` (`radio.py:2004`) | same wave at 2×4 Braille sub-cell resolution |
| `get_tuning_glitch_rows` (`radio.py:2075`) | static-noise "tuning" effect on station change |

## Building blocks already in the file (reuse these)

- **Per-frame data** on `self`: `band_heights[18]` (ballistic, 0–8), `peak_heights[18]`,
  `bass_energy` / `mid_energy` / `treble_energy` (0–1), `max_height = 8.0`,
  `cava_engine.get_bands() -> ([18 floats 0–1], is_active)`.
- `apply_monstercat_filter(bars, monstercat)` — CAVA spatial smoothing, has a pow table.
- `BLOCKS` (9 vertical eighth-blocks), `STATIC_CHARS`, `fit_row(s, w, bg, fill)`.
- **Braille canvas pattern** from `get_braille_wave_rows`: `chr(0x2800 + mask)`, with
  `col0 = (0x01,0x02,0x04,0x40)`, `col1 = (0x08,0x10,0x20,0x80)` → a 2×4 sub-cell grid.
- `t_sec` (wall clock), theme escapes `_c_bright` / `_c_accent` / `_c_dim` / `_c_warn`.
- Panel sizes a viz must survive: **~22×5** (compact deck), **36×8** (standard), up to
  **~92×24** (studio tower). Every method returns `total_rows` strings each `target_w` wide.

> **Friction to fix first:** adding a visualizer today means editing all four `render_*`
> methods. A `VIZ = [get_equalizer_rows, ...]` registry indexed by `viz_mode`, plus one
> dispatch helper the renderers call, makes each new entry a one-liner. Pairs with idea
> 3.2 in `improvement-ideas.md`.

Difficulty: **S** ≤ ~30 lines · **M** ~30–80 · **L** > 80 or needs a new helper.
"Best at" = panel size where it reads well.

---

## 1. Spectrum family

| # | Name | Look & data | Impl sketch | Diff · Best at |
| :-- | :-- | :-- | :-- | :-- |
| 1.1 | **Mirrored bars** | bars grow up *and* down from a centre line; classic reflected analyzer | render `get_equalizer_rows` twice about `total_rows//2`, bottom half flipped and dimmed | S · any |
| 1.2 | **Waterfall / spectrogram** | scrolling history: each frame pushes one column of the 18 bands, colour = magnitude (theme dim→bright ramp), time scrolls down | `deque(maxlen=target_w)` of band snapshots; each row = one frequency bin, each column = one past frame | M · wide (studio tower) |
| 1.3 | **Horizontal bars** | one band per row, bar grows left→right with a peak dot | 18 rows (or bin to `total_rows`); `BLOCKS`-style eighths but horizontal (`▏▎▍▌▋▊▉█`) | S · tall narrow |
| 1.4 | **Filled skyline** | area under the spectrum curve filled solid — a city silhouette; optional "windows" (`·`) punched in | for each column, fill every cell below the interpolated height | S · medium/wide |
| 1.5 | **Peak-only / minimal** | just the floating `peak_heights` caps, no bars — a sparse constellation that hangs and falls | draw only where `peak_rem` in `[0,1)` | S · any (great for Zen) |
| 1.6 | **Dot-matrix LED panel** | each band a column of discrete dots that light `●`/`·`; retro hi-fi VFD look, dim grid always visible | quantise band height to N dots; unlit = `_c_dim ·` | S · medium |
| 1.7 | **Gradient bars** | colour varies *within* each bar by height (green→amber→red), not per-row | pick colour from `min(1, cell_height/max)` per cell instead of per row | S · any |
| 1.8 | **Fake-stereo split** | odd bins → top half, even bins → bottom half, mirrored — reads as L/R without real stereo data | reindex bands, reuse 1.1's layout | S · medium/wide |
| 1.9 | **Descending peak dots** | 90s hi-fi: solid bar + a single peak dot that falls one row at a time with a hold delay | `peak_hold_frames` already exists; render the cap as `▄`/`■` on its own row | S · any |
| 1.10 | **Radial spectrum** | 18 bands as spokes around a centre, length = level; Braille for smoothness | polar → Braille canvas; `r = base + level*k`, plot along each spoke angle | L · large square |
| 1.11 | **Log/linear + band-count toggle** | not a new viz — a `[` / `]` keybind on the existing analyzer to switch frequency scaling and 12/18/24/32 bins | resample `band_heights` before rasterising | S · any |

## 2. Waveform family

| # | Name | Look & data | Impl sketch | Diff · Best at |
| :-- | :-- | :-- | :-- | :-- |
| 2.1 | **Filled waveform** | solid fill between the trace and the centre line — an "oscilloscope with body" | for each column fill cells between `center` and `y(x)` | S · any |
| 2.2 | **Mirror / "eye"** | wave on top, its mirror on the bottom, meeting at the centre — a lens/eye shape | draw `y` and `2*center - y` | S · medium/wide |
| 2.3 | **Envelope band** | min/max of the wave per column over a short window, filled as a ribbon that swells with loudness | keep a small deque of recent traces; per column fill `[min,max]` | M · wide |
| 2.4 | **Phosphor / persistence scope** | the classic fading CRT trail — current trace bright, past traces dimming over ~8 frames | `deque(maxlen=8)` of `(x,y)` traces; composite with intensity `i/8`, map to `_c_dim`→`_c_bright` | M · medium/wide |
| 2.5 | **Lissajous / X-Y scope** | two signals plotted against each other → rotating loops, knots, figure-eights; iconic scope art | synthesize signal B from a second phase set (or bass vs treble); Braille canvas; `x = A(t)`, `y = B(t)` | M · large square |
| 2.6 | **Ribbon / multi-trace** | 3–5 waves at staggered phases in a translucent stack, colours interpolated | loop the wave fn with per-line phase offset; nearer lines brighter | M · wide |
| 2.7 | **Goniometer / phase scope** | 45°-rotated Lissajous with a correlation needle — "how mono is it" gauge (faked from bass/treble coherence) | 2.5 rotated; add a single radial needle | M · large square |

## 3. Particle / cellular

| # | Name | Look & data | Impl sketch | Diff · Best at |
| :-- | :-- | :-- | :-- | :-- |
| 3.1 | **Doom fire** | the cellular fire algorithm; flame height/heat driven by `bass_energy`; sits at the bottom of the panel and licks upward | int heat grid, each cell = avg of the row below minus a random cool; palette maps heat→`_c_dim`→`_c_warn`→`_c_bright`; ~one array pass, very cheap | M · any (fills the panel) |
| 3.2 | **Bass fountain / fireworks** | particles spawn on bass onsets, arc under gravity, fade; treble tints them | small particle list `[(x,y,vx,vy,life)]`; spawn N on beat; Braille or `·*+` | M · medium/wide |
| 3.3 | **Warp starfield** | stars streak outward from centre, speed ∝ overall energy — the effect that was cut from Cyberpunk for cost, done cheap | pre-index stars by row (the fix the old plan proposed); `z` decreases with energy; `.`/`*`/`+` by depth | M · large |
| 3.4 | **Rain** | falling glyphs, density ∝ `treble_energy`, speed ∝ `mid_energy`; splash on the bottom row | column-wise drop positions in a float array; `｜`/`·` | S · any |
| 3.5 | **Matrix rain (audio-reactive)** | green cascading katakana/hex, column fall speed and trail length modulated per band | per-column head position + trail; head bright, trail `_c_dim`; feed 18 columns from 18 bands | M · any |
| 3.6 | **Bouncing balls** | one ball per band, launched to a height = that band's level, gravity brings it down between hits | `y[i]`, `v[i]`; on new peak set `v[i]` upward; `●` | S · medium/wide |

## 4. Geometric / demoscene

| # | Name | Look & data | Impl sketch | Diff · Best at |
| :-- | :-- | :-- | :-- | :-- |
| 4.1 | **Plasma field** | flowing sinusoidal colour interference, phases driven by bass/mid/treble; hypnotic backdrop | `v = sin(x*a+t) + sin(y*b+t) + sin((x+y)*c+t)`; map `v` to a palette; `░▒▓█` for luma | M · any |
| 4.2 | **Pulse rings** | concentric rings expand from centre on each beat, fading as they grow | ring list `[(radius, life)]`; spawn on bass onset; distance-field test per cell (Braille) | M · large square |
| 4.3 | **Tunnel** | receding concentric shapes with scrolling texture — you fly down a pipe; speed ∝ energy | precompute per-pixel `(angle, depth)`; sample a texture with `depth + t*speed` | L · large |
| 4.4 | **Rotating polygon** | an n-gon spinning; vertex count = f(bands active), spin rate ∝ mid, radius pulses with bass | vertices on a circle, `rotate(t)`, draw edges into a Braille canvas with Bresenham | M · large square |
| 4.5 | **Kaleidoscope** | render any cheap effect in one quadrant, mirror into four | compute top-left only, reflect on write | S · large square (wrapper) |
| 4.6 | **Bar "city" with parallax** | 1.4's skyline plus a dimmer, slower-scrolling silhouette behind it for depth | two skylines, back one scrolls with `t_sec` and is `_c_dim` | M · wide |

## 5. Retro hi-fi (fits the theme best)

| # | Name | Look & data | Impl sketch | Diff · Best at |
| :-- | :-- | :-- | :-- | :-- |
| 5.1 | **Analog VU needles** | two swinging needle gauges (L/R) with a peak LED — brings back the look of the VU code that was removed in v2 | arc of `·`, a needle line to `angle = f(energy)`, drawn in Braille; `● PK` when clipping | M · medium/wide |
| 5.2 | **Spinning reels** | two reel-to-reel hubs `◜◝◟◞` / spoked circles rotating, speed ∝ energy; tape line between them; also revives a removed v2 feature | two small circles, spoke phase advances with `t_sec * (0.5 + energy)` | M · medium |
| 5.3 | **Cassette** | tape spooling between two hubs, hub radii changing as if playing; wow/flutter wobble on the hubs with bass | draw two filled circles whose radius drifts; connecting tape sags with a sine | M · medium/wide |
| 5.4 | **VFD segment display** | dim cyan dot-grid with bright segments — 1.6 styled as a vacuum-fluorescent display, faint unlit dots everywhere | always draw the dim grid; overlay lit segments; heavy `_c_dim` background | S · medium |
| 5.5 | **CRT bloom scope** | 2.4 phosphor scope plus an accent-colour "halo" one cell around every bright trace cell | after plotting, for each bright cell set neighbours to `_c_accent` if currently blank | M · medium/wide |
| 5.6 | **Signal-strength meter** | a horizontal bar + numeric % that reacts to `bass+mid+treble`, styled like an FM tuner's signal LED ladder | 1-3 rows; ladder of `▮`/`▯`; the `station["signal"]` value is already tracked | S · small/medium |

## 6. Beat / rhythm driven

| # | Name | Look & data | Impl sketch | Diff · Best at |
| :-- | :-- | :-- | :-- | :-- |
| 6.1 | **Beat flash** | the whole panel briefly inverts / brightens on a detected bass onset | onset = `bass_energy - prev > k` with a ~6-frame refractory; scale a global intensity that decays | S · any (modifier on any viz) |
| 6.2 | **Strobe grid** | a checkerboard of blocks that pulses on beat, phase per cell offset for a shimmer | `((x+y+beat_count) % 2)` picks bright/dim | S · any |
| 6.3 | **Metronome pendulum** | a swinging arm whose period tracks an estimated BPM; a tick mark flashes on the beat | keep inter-onset intervals in a deque, median → period; `angle = A*sin(2π t / period)` | M · medium |
| 6.4 | **Kick/snare lights** | two big indicators — low-band onset lights one, high-band onset the other | two energy-delta detectors on band slices; `◉`/`○` | S · small/medium |

## 7. Hybrid / informational

| # | Name | Look & data | Impl sketch | Diff · Best at |
| :-- | :-- | :-- | :-- | :-- |
| 7.1 | **Spectrum + wave overlay** | the analyzer bars with the live waveform drawn *over* them in the accent colour | render `get_equalizer_rows`, then overwrite cells the wave passes through | M · medium/wide |
| 7.2 | **Analyzer readout** | bars plus a side column: peak band (Hz-ish label), dB-style numbers, a tiny history sparkline | reuse bars; add a 10–14 col gutter of text | M · wide |
| 7.3 | **Frequency heatmap strip** | a single row: colour along it shows which part of the spectrum is hot right now | 1×`target_w`, colour ramp by band level; good as a *second* mini-viz in a spare row | S · any (1 row) |
| 7.4 | **Loudness history** | a scrolling line graph of overall RMS over the last ~`target_w` frames — "how loud has it been" | `deque` of energy; plot as a line (Braille) | S · wide |

---

## Build these first

1. **Viz registry** (`VIZ = [...]` + one dispatch helper) — removes the "edit four renderers"
   tax so everything below is cheap to add. **S.**
2. **Waterfall / spectrogram** (1.2) — the highest-impact genuinely-new look; a `deque` of
   band snapshots is all the new state. **M.**
3. **Doom fire** (3.1) — iconic, one array pass, fills any panel, reads great in Cyberpunk /
   Amber CRT. **M.**
4. **Mirrored bars** (1.1) + **filled waveform** (2.1) — near-free variants of what's already
   there; good default additions. **S each.**
5. **Analog VU needles** (5.1) — revives the deleted v2 feature and is the best thematic fit
   for Retro Hi-Fi. **M.**
6. **Beat flash** (6.1) as a global modifier — a simple onset detector that any current or
   future viz can react to. **S**, and it unlocks 3.2, 4.2, 6.x.

Phosphor scope (2.4), plasma (4.1) and the Lissajous scope (2.5) are the next tier — more
code, but all high-wow and all cheap at runtime with a lookup table or a small deque.

---

## Notes on cost and correctness

- Everything here is O(cells) or O(cells + particles) per frame; the render budget is ~0.5 ms
  and the diff emitter only ships changed rows, so even a full-panel plasma is fine.
- A visualizer that animates every cell every frame (plasma, fire, tunnel, matrix rain)
  **defeats the damage-tracked emitter** — expect output to rise toward the old ~500 KB/s at
  large panel sizes while that viz is on screen. Acceptable, but worth knowing; the adaptive
  idle throttle still helps when paused.
- Keep every row exactly `target_w` cells — go through `fit_row`, and for sub-cell canvases
  copy the width discipline from `get_braille_wave_rows`.
- `is_active` from `cava_engine.get_bands()` is false on silence; fall back to the simulated
  bands (as the current analyzer does) so a viz never freezes on a quiet passage.
