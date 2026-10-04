#!/usr/bin/env python3
"""Horizontal bars  (idea 1.3) — one band per row, grows left to right"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, HBLOCKS, fg, DIM, MID, BRIGHT, WARN, ACCENT, RST

LABELS = ["SUB", "60", "90", "130", "180", "250", "350", "500", "700", "1k",
          "1k4", "2k", "2k8", "4k", "5k6", "8k", "11k", "16k"]


def draw(w, h, a, t):
    n = min(18, h)
    bar_w = max(4, w - 8)
    rows = []
    for r in range(h):
        if r >= n:
            rows.append("")
            continue
        bi = int(r * 17 / max(1, n - 1))
        v = a.bands[bi]
        pk = a.peaks[bi]
        full = int(v * bar_w)
        frac = v * bar_w - full
        col = BRIGHT if v > 0.66 else (WARN if v > 0.4 else MID)
        cells = [col + "█" * full]
        if frac > 0 and full < bar_w:
            cells.append(col + HBLOCKS[max(1, min(8, int(frac * 8)))])
            full += 1
        cells.append(DIM + "·" * max(0, bar_w - full))
        pkpos = min(bar_w - 1, int(pk * bar_w))
        lab = LABELS[bi] if bi < len(LABELS) else str(bi)
        line = f"{ACCENT}{lab:>4} {''.join(cells)}{RST}"
        rows.append(line)
    return rows


if __name__ == "__main__":
    run(draw, title="Horizontal bars")
