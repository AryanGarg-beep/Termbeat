#!/usr/bin/env python3
"""Peak-only  (idea 1.5) — just the floating caps; sparse, minimal (great for Zen)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, fg, DIM, BRIGHT, ACCENT, WARN, RST


def draw(w, h, a, t):
    n = max(10, min(w // 2, 44))
    gap = 1 if w >= n * 2 else 0
    pad = " " * max(0, (w - n * (1 + gap)) // 2)
    peaks = [a.peaks[int(i * 17 / max(1, n - 1))] for i in range(n)]
    bands = [a.bands[int(i * 17 / max(1, n - 1))] for i in range(n)]
    grid = [[" "] * n for _ in range(h)]
    for i in range(n):
        pr = int((1.0 - peaks[i]) * (h - 1))
        br = int((1.0 - bands[i]) * (h - 1))
        if 0 <= pr < h:
            grid[pr][i] = (WARN if peaks[i] > 0.8 else ACCENT) + "▄"
        if 0 <= br < h and br != pr:
            grid[br][i] = DIM + "·"
    rows = []
    for r in range(h):
        line = [pad]
        for i in range(n):
            line.append(grid[r][i] + RST if grid[r][i] != " " else " ")
            if gap:
                line.append(" ")
        rows.append("".join(line))
    return rows


if __name__ == "__main__":
    run(draw, title="Peak-only")
