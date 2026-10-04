#!/usr/bin/env python3
"""Bass fountain / fireworks  (idea 3.2) — particles spawn on kicks, arc, fade"""
import os, sys, random, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, fg, DIM, BRIGHT, ACCENT, WARN, RST

GLYPH = ["·", "•", "*", "+", "✦"]
_p = []            # [x, y, vx, vy, life, max_life, tint]
_last_beat = {"v": 0.0}


def draw(w, h, a, t):
    # spawn a burst on a rising beat edge
    if a.beat > 0.6 and _last_beat["v"] <= 0.6:
        cx = w * (0.3 + 0.4 * random.random())
        cy = h - 1
        count = 14 + int(a.bass * 26)
        spd = 0.8 + a.bass * 1.6
        for _ in range(count):
            ang = -math.pi / 2 + random.uniform(-0.9, 0.9)
            v = spd * random.uniform(0.5, 1.3)
            life = random.uniform(0.7, 1.6)
            tint = random.choice([BRIGHT, ACCENT, WARN, fg(255, 150, 200)])
            _p.append([cx, cy, math.cos(ang) * v * 2.0, math.sin(ang) * v,
                       life, life, tint])
    _last_beat["v"] = a.beat

    grid = [[" "] * w for _ in range(h)]
    dt = 1.0 / 24
    alive = []
    for pt in _p:
        pt[0] += pt[2]
        pt[1] += pt[3]
        pt[3] += 3.2 * dt            # gravity
        pt[4] -= dt
        if pt[4] <= 0 or pt[1] >= h or pt[0] < 0 or pt[0] >= w:
            continue
        alive.append(pt)
        frac = pt[4] / pt[5]
        gi = int(frac * (len(GLYPH) - 1))
        col = pt[6] if frac > 0.4 else DIM
        xi, yi = int(pt[0]), int(pt[1])
        if 0 <= yi < h and 0 <= xi < w:
            grid[yi][xi] = col + GLYPH[gi]
    _p[:] = alive
    return ["".join(c + RST if c != " " else " " for c in row) for row in grid]


if __name__ == "__main__":
    run(draw, title="Bass fountain / fireworks")
