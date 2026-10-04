#!/usr/bin/env python3
"""Classic spectrum bars  (baseline — matches termbeat's current analyzer)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, BLOCKS, DIM, MID, BRIGHT, WARN, RST


def draw(w, h, a, t):
    n = max(8, min(w // 2, 48))
    gap = 1 if w >= n * 2 else 0
    pad = " " * max(0, (w - n * (1 + gap)) // 2)
    # colour by row: warm top, mid, bright bottom
    wc = max(1, h // 4)
    ac = max(1, h // 3)
    rowcol = [WARN] * wc + [MID] * ac + [BRIGHT] * max(1, h - wc - ac)
    vals = [a.bands[int(i * 17 / max(1, n - 1))] * h for i in range(n)]
    peaks = [a.peaks[int(i * 17 / max(1, n - 1))] * h for i in range(n)]
    rows = []
    for r in range(h):
        thr = h - 1 - r
        col = rowcol[min(r, len(rowcol) - 1)]
        line = [pad]
        for i in range(n):
            rem = vals[i] - thr
            if rem >= 1.0:
                line.append(col + "█")
            elif rem > 0.0:
                line.append(col + BLOCKS[max(1, min(8, int(rem * 8)))])
            elif 0.0 <= peaks[i] - thr < 1.0 and peaks[i] > 0.4:
                line.append(WARN + "▔")
            else:
                line.append(DIM + " ")
            if gap:
                line.append(" ")
        rows.append("".join(line) + RST)
    return rows


if __name__ == "__main__":
    run(draw, title="Classic spectrum bars")
