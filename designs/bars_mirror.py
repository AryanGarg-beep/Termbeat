#!/usr/bin/env python3
"""Mirrored bars  (idea 1.1) — bars grow up and down from a centre line"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, BLOCKS, DIM, MID, BRIGHT, ACCENT, RST

_INV = {1: "▔", 2: "🮂", 3: "🮃", 4: "▀", 5: "🮄", 6: "🮅", 7: "🮆", 8: "█"}


def draw(w, h, a, t):
    n = max(8, min(w // 2, 40))
    gap = 1 if w >= n * 2 else 0
    pad = " " * max(0, (w - n * (1 + gap)) // 2)
    mid = h // 2
    up_h = mid
    dn_h = h - mid - 1
    vals = [a.bands[int(i * 17 / max(1, n - 1))] for i in range(n)]
    rows = []
    for r in range(h):
        line = [pad]
        for i in range(n):
            if r < mid:                                   # upper half
                rem = vals[i] * up_h - (mid - 1 - r)
                col = ACCENT if r < mid - up_h // 2 else BRIGHT
                ch = "█" if rem >= 1 else (BLOCKS[max(1, min(8, int(rem * 8)))] if rem > 0 else " ")
                if ch == " ":
                    line.append(DIM + " ")
                else:
                    line.append(col + ch)
            elif r == mid:
                line.append(DIM + "─")
            else:                                          # lower half, flipped
                rem = vals[i] * dn_h - (r - mid - 1)
                col = MID
                if rem >= 1:
                    line.append(col + "█")
                elif rem > 0:
                    line.append(col + _INV.get(max(1, min(8, int(rem * 8))), "▀"))
                else:
                    line.append(DIM + " ")
            if gap:
                line.append(" ")
        rows.append("".join(line) + RST)
    return rows


if __name__ == "__main__":
    run(draw, title="Mirrored bars")
