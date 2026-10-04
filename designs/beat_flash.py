#!/usr/bin/env python3
"""Beat flash  (idea 6.1) — a spectral-flux onset detector driving a global flash.

The reusable piece is `flash` (1.0 on a kick, decaying to 0): any visualizer can
scale its brightness or background by it. Here it tints the bars and drops a
BEAT banner on the strongest hits.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, BLOCKS, bg, fg, DIM, MID, BRIGHT, WARN, RST

_prev_bass = {"v": 0.0}
_flash = {"v": 0.0}
PANEL_BG = ["", bg(12, 30, 18), bg(20, 46, 28), bg(32, 70, 42)]
BANNER_BG = bg(255, 210, 40)
BANNER_FG = fg(10, 20, 15)


def draw(w, h, a, t):
    rise = max(0.0, a.bass - _prev_bass["v"])
    _prev_bass["v"] = a.bass
    if rise > 0.14:
        _flash["v"] = 1.0
    _flash["v"] = max(0.0, _flash["v"] - (1.0 / 24) * 3.2)
    fl = _flash["v"]
    pbg = PANEL_BG[min(3, int(fl * 4))]

    n = max(8, min(w // 2, 40))
    pad = " " * max(0, (w - n * 2) // 2)
    vals = [a.bands[int(i * 17 / max(1, n - 1))] * h for i in range(n)]
    bar_col = WARN if fl > 0.3 else BRIGHT
    tip_col = WARN if fl > 0.3 else MID

    rows = []
    for r in range(h):
        thr = h - 1 - r
        cells = [pbg, pad]
        for i in range(n):
            rem = vals[i] - thr
            if rem >= 1:
                cells.append(bar_col + "█ ")
            elif rem > 0:
                cells.append(tip_col + BLOCKS[max(1, min(8, int(rem * 8)))] + " ")
            else:
                cells.append(DIM + "  ")
        line = "".join(cells) + RST
        if fl > 0.55 and r == h // 2:
            tag = f" ● BEAT {int(fl * 100):3d} "
            line = BANNER_BG + BANNER_FG + tag + RST + line[len(pbg):]
        rows.append(line)
    return rows


if __name__ == "__main__":
    run(draw, title="Beat flash (onset-reactive)")
