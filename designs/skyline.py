#!/usr/bin/env python3
"""Filled skyline  (idea 1.4) — area under the spectrum, filled solid, with windows"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, BLOCKS, fg, DIM, RST

BODY = fg(30, 90, 130)
EDGE = fg(120, 220, 255)
WIN = fg(255, 230, 120)


def draw(w, h, a, t):
    # interpolate 18 bands across the full width
    height = []
    for x in range(w):
        p = x * 17 / max(1, w - 1)
        i = int(p)
        f = p - i
        j = min(17, i + 1)
        height.append((a.bands[i] * (1 - f) + a.bands[j] * f) * h)
    rows = []
    for r in range(h):
        thr = h - 1 - r
        line = []
        for x in range(w):
            hv = height[x]
            rem = hv - thr
            if rem >= 1.0:
                # sparse lit windows in the solid interior (not on the roofline)
                if rem > 2.0 and ((x * 7 + r * 13) % 17 == 0):
                    line.append(WIN + "▪")
                else:
                    line.append(BODY + "█")
            elif rem > 0.05:
                line.append(EDGE + BLOCKS[max(1, min(8, int(rem * 8)))])
            else:
                line.append(" ")
        rows.append("".join(line) + RST)
    return rows


if __name__ == "__main__":
    run(draw, title="Filled skyline")
