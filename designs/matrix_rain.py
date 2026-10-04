#!/usr/bin/env python3
"""Matrix rain (audio-reactive)  (idea 3.5) — 18 columns fed by 18 bands;
fall speed and trail length track each band"""
import os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, fg, DIM, BRIGHT, RST

GLYPHS = "ｱｲｳｴｵｶｷｸｹｺｻｼｽ0123456789ﾊﾋﾌﾍﾎ$+=*#%"
HEAD = fg(220, 255, 220)
BODY = fg(40, 220, 90)
TAIL = fg(20, 110, 45)
_cols = None            # per screen-column: [head_y(float), speed, trail, seed]


def _init(w):
    global _cols
    _cols = []
    for _ in range(w):
        _cols.append([random.uniform(-20, 0), random.uniform(0.2, 0.6),
                      random.randint(4, 12), random.random()])


def draw(w, h, a, t):
    if _cols is None or len(_cols) != w:
        _init(w)
    grid = [[" "] * w for _ in range(h)]
    for x in range(w):
        band = a.bands[int(x * 17 / max(1, w - 1))]
        c = _cols[x]
        c[1] = 0.15 + band * 1.3               # speed from this band
        c[2] = 4 + int(band * 14)              # trail length
        c[0] += c[1]
        if c[0] - c[2] > h:
            c[0] = random.uniform(-8, 0)
        hy = int(c[0])
        for k in range(c[2]):
            y = hy - k
            if 0 <= y < h:
                if k == 0:
                    ch = HEAD + random.choice(GLYPHS)
                elif k < c[2] * 0.4:
                    ch = BODY + random.choice(GLYPHS)
                else:
                    ch = TAIL + random.choice(GLYPHS)
                grid[y][x] = ch
    return ["".join(cell + RST if cell != " " else " " for cell in row) for row in grid]


if __name__ == "__main__":
    run(draw, title="Matrix rain (audio-reactive)")
