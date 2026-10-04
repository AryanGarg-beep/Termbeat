#!/usr/bin/env python3
"""LED dot-matrix panel  (idea 1.6) — discrete dots, dim grid always visible (VFD look)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, fg, DIM, BRIGHT, WARN, HOT, RST

OFF = fg(20, 55, 30)


def draw(w, h, a, t):
    n = max(8, min(w // 3, 32))
    cell = 3 if w >= n * 3 else 2
    pad = " " * max(0, (w - n * cell) // 2)
    vals = [a.bands[int(i * 17 / max(1, n - 1))] for i in range(n)]
    peaks = [a.peaks[int(i * 17 / max(1, n - 1))] for i in range(n)]
    rows = []
    for r in range(h):
        thr = (h - 1 - r) / max(1, h - 1)
        line = [pad]
        for i in range(n):
            lit = vals[i] >= thr
            ispk = abs(peaks[i] - thr) < (0.5 / h)
            if lit:
                col = HOT if thr > 0.75 else (WARN if thr > 0.45 else BRIGHT)
                dot = col + "●"
            elif ispk:
                dot = WARN + "○"
            else:
                dot = OFF + "·"
            line.append(dot + " " * (cell - 1))
        rows.append("".join(line) + RST)
    return rows


if __name__ == "__main__":
    run(draw, title="LED dot-matrix panel")
