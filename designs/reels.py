#!/usr/bin/env python3
"""Spinning reels  (idea 5.2) — reel-to-reel hubs, spin speed = energy, tape between them"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, Braille, fg, DIM, BRIGHT, ACCENT, WARN, RST

_phase = {"v": 0.0}


def _reel(b, cx, cy, rad, phase, spokes=5):
    # rim
    steps = max(30, int(rad * 4))
    for k in range(steps):
        ang = k / steps * math.tau
        b.plot(cx + math.cos(ang) * rad, cy + math.sin(ang) * rad)
        b.plot(cx + math.cos(ang) * rad * 0.32, cy + math.sin(ang) * rad * 0.32)
    # spokes
    for sp in range(spokes):
        ang = phase + sp * math.tau / spokes
        b.line(cx + math.cos(ang) * rad * 0.34, cy + math.sin(ang) * rad * 0.34,
               cx + math.cos(ang) * rad * 0.95, cy + math.sin(ang) * rad * 0.95)


def draw(w, h, a, t):
    spin = 0.15 + a.level * 1.8 + a.beat * 0.6
    _phase["v"] += spin * (1.0 / 24) * math.tau * 1.5
    ph = _phase["v"]

    b = Braille(w, h)
    rad = min(b.pw / 5.0, b.ph / 2.6)
    y = b.ph / 2.0
    lx = b.pw * 0.28
    rx = b.pw * 0.72
    _reel(b, lx, y, rad, ph)
    _reel(b, rx, y, rad, -ph * 0.8)
    # tape path: over the top between hub tops, dipping in the middle
    x0, x1 = lx, rx
    for k in range(60):
        f = k / 59
        x = x0 + (x1 - x0) * f
        dip = math.sin(f * math.pi) * rad * 0.5
        b.plot(x, y - rad - 2 + dip)
    rows = b.rows(color=BRIGHT, edge_color=DIM)
    if h >= 3:
        rows[-1] = f"{DIM}  ▚▚ TAPE  {ACCENT}{'▶' if spin > 0.4 else '❚❚'} {int(spin*47):02d} ips{RST}"
    return rows


if __name__ == "__main__":
    run(draw, title="Spinning reels")
