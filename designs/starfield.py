#!/usr/bin/env python3
"""Warp starfield  (idea 3.3) — stars streak from centre, speed = energy
(the effect cut from Cyberpunk for cost, done cheap: row-indexed, O(stars))"""
import os, sys, random, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, fg, DIM, BRIGHT, ACCENT, RST

DEPTH = [(fg(60, 70, 110), "."), (fg(120, 130, 180), "·"),
         (fg(190, 200, 240), "*"), (BRIGHT, "+"), (ACCENT, "✦")]
_stars = []            # [x, y, z]  in normalised centre coords, z in (0,1]
_N = 140


def _reseed(s):
    s[0] = random.uniform(-1, 1)
    s[1] = random.uniform(-1, 1)
    s[2] = 1.0


def draw(w, h, a, t):
    if not _stars:
        for _ in range(_N):
            s = [0.0, 0.0, 0.0]
            _reseed(s)
            s[2] = random.random()
            _stars.append(s)
    speed = 0.006 + a.level * 0.05 + a.beat * 0.03
    cx, cy = w / 2.0, h / 2.0
    grid = [[" "] * w for _ in range(h)]
    for s in _stars:
        s[2] -= speed
        if s[2] <= 0.02:
            _reseed(s)
        k = 0.5 / s[2]
        sx = cx + s[0] * k * cx
        sy = cy + s[1] * k * cy
        xi, yi = int(sx), int(sy)
        if 0 <= yi < h and 0 <= xi < w:
            tier = min(4, int((1.0 - s[2]) * 5))
            col, ch = DEPTH[tier]
            grid[yi][xi] = col + ch
            # short warp streak toward centre when fast
            if speed > 0.03 and tier >= 2:
                bx, by = int(sx - s[0] * (k * 0.85) * cx), int(sy - s[1] * (k * 0.85) * cy)
                if 0 <= by < h and 0 <= bx < w and grid[by][bx] == " ":
                    grid[by][bx] = DIM + "·"
    return ["".join(c + RST if c != " " else " " for c in row) for row in grid]


if __name__ == "__main__":
    run(draw, title="Warp starfield")
