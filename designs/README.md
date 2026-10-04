# designs/ — visualizer preview sketches

Runnable previews of the ideas in [`../rs/visualizer-ideas.md`](../rs/visualizer-ideas.md).
Each sketch renders full-screen against a **synthetic** audio model — no `mpv`, no `cava`,
no network — so you can see what a visualizer would look like before wiring it into
`radio.py`. Pure Python standard library.

## Running

```sh
python3 designs/gallery.py          # flip through all of them (auto-advances every 9 s)
python3 designs/gallery.py fire     # …starting on one

python3 designs/waterfall.py        # just one, full screen
python3 designs/_selftest.py        # headless: import + drive every sketch, check it doesn't break
```

Gallery keys: `→`/`n` next · `←`/`p` prev · `space` hold/resume auto-advance · `r` reseed
the fake audio · `q` quit. Any sketch: `Ctrl-C` quits and restores the terminal.

## What's here

| File | Idea | Family |
| :-- | :-- | :-- |
| `bars_classic.py` | baseline — matches termbeat's current analyzer | spectrum |
| `bars_mirror.py` | 1.1 mirrored bars | spectrum |
| `waterfall.py` | 1.2 waterfall / spectrogram | spectrum |
| `bars_horizontal.py` | 1.3 horizontal bars, one band per row | spectrum |
| `skyline.py` | 1.4 filled skyline with windows | spectrum |
| `peaks_only.py` | 1.5 floating caps only (minimal) | spectrum |
| `led_matrix.py` | 1.6 LED dot-matrix / VFD panel | spectrum |
| `wave_filled.py` | 2.1 filled waveform | waveform |
| `wave_mirror.py` | 2.2 mirror "eye" | waveform |
| `scope_phosphor.py` | 2.4 fading CRT persistence scope | waveform |
| `lissajous.py` | 2.5 X-Y / Lissajous scope | waveform |
| `fire.py` | 3.1 Doom fire, bass-driven | particle |
| `fountain.py` | 3.2 bass fountain / fireworks | particle |
| `starfield.py` | 3.3 warp starfield | particle |
| `matrix_rain.py` | 3.5 audio-reactive matrix rain | particle |
| `plasma.py` | 4.1 plasma interference field | geometric |
| `pulse_rings.py` | 4.2 concentric rings on the beat | geometric |
| `vu_needles.py` | 5.1 analog VU needle gauges | retro |
| `reels.py` | 5.2 spinning reel-to-reel | retro |
| `beat_flash.py` | 6.1 onset detector + global flash | beat |
| `modular_hud.py` | — full-screen "modular design" HUD poster (turntable + sunburst dial + needle), sketched from a reference image; ticks/arc/needle/dots are audio-reactive | HUD |

Not yet sketched (from the ideas doc): radial spectrum (1.10), envelope ribbon (2.3),
ribbon multi-trace (2.6), goniometer (2.7), rain (3.4), bouncing balls (3.6), tunnel (4.3),
rotating polygon (4.4), kaleidoscope (4.5), parallax skyline (4.6), cassette (5.3),
VFD segments (5.4), CRT bloom (5.5), signal meter (5.6), strobe grid (6.2), BPM pendulum
(6.3), kick/snare lights (6.4), and the hybrid/informational set (7.x).

## Writing a sketch

Drop a file in this folder with a one-line docstring (used as the title) and one function:

```python
#!/usr/bin/env python3
"""My visualizer  (idea X.Y)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, BLOCKS, DIM, BRIGHT, ACCENT, RST

def draw(w, h, a, t):
    # a is a FakeAudio; return exactly h strings, each w visible cells
    return [BRIGHT + ("█" * int(a.bands[x * 18 // w] * w)) for x in range(h)]

if __name__ == "__main__":
    run(draw, title="My visualizer")
```

`gallery.py` and `_selftest.py` pick it up automatically. Files starting with `_` are
ignored.

### The `FakeAudio` model (`_harness.py`)

Mirrors what termbeat's `update_physics` produces:

| Attribute | Meaning |
| :-- | :-- |
| `a.bands[18]` | ballistic band levels, 0–1 (fast attack, gravity fall), with a treble roll-off |
| `a.peaks[18]` | floating peak-hold, 0–1 |
| `a.bass`, `a.mid`, `a.treble` | band-slice energies, 0–1 |
| `a.level` | overall level, 0–1 |
| `a.beat` | 1.0 on a kick, decays to 0 — for beat-reactive sketches |
| `a.sample(x)` | pseudo-waveform value in −1..1 for phase `x` (0–1 across the panel) |

### Helpers in `_harness.py`

- `run(draw, *, fps=24, title="")` — the full-screen loop + terminal setup/teardown.
- `fit(s, w)` — pad/trim a string to exactly `w` visible cells, SGR-aware (the loop
  applies this to every row, so a sketch can be a little sloppy about exact width).
- `Braille(w_cells, h_cells)` — a 2×4-dots-per-cell canvas with `.plot(x, y)`,
  `.line(x0, y0, x1, y1)`, `.rows(color, edge_color)`; same dot layout as termbeat's
  `get_braille_wave_rows`. Used by the scope / Lissajous / rings / VU / reels sketches.
- `fg(r, g, b)`, `bg(r, g, b)`, `RST`, and a small palette (`DIM`, `MID`, `BRIGHT`,
  `ACCENT`, `WARN`, `HOT`), `BLOCKS`, `HBLOCKS`.

## Notes

- These are **previews, not the real thing**: the audio is synthetic and the loop does a
  full repaint every frame (no damage tracking), so `gallery.py` pushes a lot of bytes at
  large sizes. That is fine for eyeballing; the real integration would go through termbeat's
  `emit_frame` diff renderer.
- Every sketch is O(cells) or O(cells + particles) per frame; `_selftest.py` prints the
  measured ms/frame. `plasma` (~1.8 ms at 200×55) and `fire` / `scope_phosphor` (~1 ms) are
  the heaviest — still well under a frame budget, but they are the full-cell-animation cases
  that would partly defeat the diff renderer in the real app.
- To port one into `radio.py`: turn `draw(w, h, a, t)` into a
  `get_<name>_rows(self, target_w, total_rows, t_cfg)` method, read `self.band_heights` /
  `self.bass_energy` etc. instead of `a.*`, use the theme's `_c_*` colours, and route every
  row through `fit_row`. See [`../rs/visualizer-ideas.md`](../rs/visualizer-ideas.md) for the per-idea mapping.
