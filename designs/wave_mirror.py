#!/usr/bin/env python3
"""Mirror "eye"  (idea 2.2) — wave on top, its mirror on the bottom, meeting at centre"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, fg, DIM, BRIGHT, ACCENT, RST

INNER = fg(25, 130, 110)


def draw(w, h, a, t):
    cen = (h - 1) / 2.0
    amp = (h / 2.0) * 0.95
    dev = [abs(a.sample(x / max(1, w - 1))) * amp * 3.0 for x in range(w)]
    rows = []
    for r in range(h):
        line = []
        for x in range(w):
            d = min(dev[x], amp)
            top = cen - d
            bot = cen + d
            if abs(r - top) < 0.55 or abs(r - bot) < 0.55:
                line.append(ACCENT + "◆")
            elif top < r < bot:
                # brighter toward the centre line
                line.append((BRIGHT if abs(r - cen) < d * 0.4 else INNER) + "▒")
            else:
                line.append(" ")
        rows.append("".join(line) + RST)
    return rows


if __name__ == "__main__":
    run(draw, title='Mirror "eye"')
