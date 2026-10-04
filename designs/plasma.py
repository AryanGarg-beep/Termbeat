#!/usr/bin/env python3
"""Plasma field  (idea 4.1) — sinusoidal interference, phases driven by bass/mid/treble"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, fg, RST

# luma ramp
SHADE = " .:-=+*#%@"
# a cyan->green->amber palette sampled by hue index
PAL = [fg(10, 40, 70), fg(15, 80, 90), fg(20, 130, 110), fg(40, 180, 120),
       fg(120, 220, 120), fg(200, 235, 110), fg(255, 210, 80), fg(255, 240, 170)]
_lut = {}


def _sin_lut(n=1024):
    if n not in _lut:
        _lut[n] = [math.sin(i / n * math.tau) for i in range(n)]
    return _lut[n]


def draw(w, h, a, t):
    S = _sin_lut()
    N = len(S)

    def s(v):
        return S[int(v * N / math.tau) % N]

    p1 = t * (0.8 + a.bass * 1.5)
    p2 = t * (0.5 + a.mid * 1.2)
    p3 = t * (0.9 + a.treble * 1.6)
    amp = 0.4 + a.level * 0.9
    rows = []
    for y in range(h):
        ny = y / max(1, h - 1) * 6.0
        line = []
        for x in range(w):
            nx = x / max(1, w - 1) * 10.0
            v = (s(nx + p1) + s(ny * 1.3 + p2) + s((nx + ny) * 0.7 + p3)
                 + s(math.hypot(nx - 5, ny - 3) * 1.4 - p1)) * 0.25 * amp
            lv = max(0.0, min(0.999, (v + 1) / 2))
            line.append(PAL[int(lv * len(PAL))] + SHADE[int(lv * (len(SHADE) - 1))])
        rows.append("".join(line) + RST)
    return rows


if __name__ == "__main__":
    run(draw, title="Plasma field")
