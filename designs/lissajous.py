#!/usr/bin/env python3
"""Lissajous / X-Y scope  (idea 2.5) — two signals plotted against each other"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, Braille, fg, DIM, BRIGHT, ACCENT, RST


def draw(w, h, a, t):
    side = min(w, h * 2)                       # square in Braille pixels
    b = Braille(side // 2, h)
    pw, ph = b.pw, b.ph
    cx, cy = pw / 2.0, ph / 2.0
    rad = min(pw, ph) / 2.0 * (0.35 + 0.6 * a.level)
    fx = 3.0 + a.bass * 2.0
    fy = 2.0 + a.treble * 3.0
    phase = t * (0.7 + a.mid)
    pts = 400
    prev = None
    for k in range(pts + 1):
        u = k / pts * math.tau
        x = cx + math.sin(u * fx + phase) * rad
        y = cy + math.sin(u * fy) * rad
        if prev:
            b.line(prev[0], prev[1], x, y)
        prev = (x, y)
    left = " " * max(0, (w - b.wc) // 2)
    return [left + r for r in b.rows(color=BRIGHT if a.beat < 0.3 else ACCENT)]


if __name__ == "__main__":
    run(draw, title="Lissajous / X-Y scope")
