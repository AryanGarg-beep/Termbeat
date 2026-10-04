#!/usr/bin/env python3
"""Pulse rings  (idea 4.2) — concentric rings expand from centre on each kick, fading"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, Braille, fg, DIM, BRIGHT, ACCENT, WARN, RST

_rings = []          # [radius_px, life]
_prev_beat = {"v": 0.0}
FADE = [fg(25, 80, 60), fg(35, 130, 90), fg(60, 190, 130), BRIGHT, ACCENT]


def draw(w, h, a, t):
    if a.beat > 0.6 and _prev_beat["v"] <= 0.6:
        _rings.append([1.0, 1.0])
    _prev_beat["v"] = a.beat

    b = Braille(w, h)
    cx, cy = b.pw / 2.0, b.ph / 2.0
    maxr = math.hypot(cx, cy)
    grow = (b.pw * 0.012) + a.level * (b.pw * 0.02)

    alive = []
    for ring in _rings:
        ring[0] += grow * 2.0
        ring[1] -= 1.0 / 22
        if ring[1] <= 0 or ring[0] > maxr:
            continue
        alive.append(ring)
        r = ring[0]
        steps = max(24, int(r * 3))
        for k in range(steps):
            ang = k / steps * math.tau
            b.plot(cx + math.cos(ang) * r, cy + math.sin(ang) * r * (b.ph / b.pw) * 2.0)
    _rings[:] = alive

    # colour the whole canvas by the newest ring's remaining life
    life = max((r[1] for r in _rings), default=0.0)
    col = FADE[min(len(FADE) - 1, int(life * len(FADE)))] if life else DIM
    return b.rows(color=col)


if __name__ == "__main__":
    run(draw, title="Pulse rings")
