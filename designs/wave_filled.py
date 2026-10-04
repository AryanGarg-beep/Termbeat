#!/usr/bin/env python3
"""Filled waveform  (idea 2.1) — solid fill between the trace and the centre line"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, fg, DIM, BRIGHT, ACCENT, RST

FILL = fg(20, 120, 90)


def draw(w, h, a, t):
    cen = (h - 1) / 2.0
    amp = (h / 2.0) * 0.92
    ys = [cen - a.sample(x / max(1, w - 1)) * amp * 3.0 for x in range(w)]
    rows = []
    for r in range(h):
        line = []
        for x in range(w):
            y = ys[x]
            lo, hi = (min(r, cen), max(r, cen))
            if abs(y - r) < 0.55:
                line.append(BRIGHT + "∿")
            elif (y <= r <= cen) or (cen <= r <= y):
                line.append(FILL + "▓")
            elif abs(r - cen) < 0.5:
                line.append(DIM + "─")
            else:
                line.append(" ")
        rows.append("".join(line) + RST)
    return rows


if __name__ == "__main__":
    run(draw, title="Filled waveform")
