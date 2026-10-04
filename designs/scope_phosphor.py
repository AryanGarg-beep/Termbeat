#!/usr/bin/env python3
"""Phosphor scope  (idea 2.4) — fading CRT trail: current trace bright, past traces dim"""
import os, sys
from collections import deque
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, Braille, fg, RST

_TRACES = deque(maxlen=7)
GLOW = [fg(20, 70, 45), fg(28, 100, 62), fg(40, 140, 85), fg(70, 190, 120),
        fg(120, 230, 150), fg(190, 250, 190), fg(235, 255, 235)]


def draw(w, h, a, t):
    b = Braille(w, h)
    pw, ph = b.pw, b.ph
    cen = (ph - 1) / 2.0
    amp = (ph / 2.0) * 0.9
    cur = []
    for px in range(pw):
        x = px / max(1, pw - 1)
        y = cen - a.sample(x) * amp * 3.0
        cur.append((px, y))
    _TRACES.append(cur)

    # composite oldest->newest into per-cell intensity
    inten = [[0] * b.wc for _ in range(b.hc)]
    for age, trace in enumerate(_TRACES):
        weight = age + 1
        prev = None
        for (px, y) in trace:
            if prev is not None:
                steps = max(1, int(abs(px - prev[0])) + int(abs(y - prev[1])))
                for s in range(steps + 1):
                    f = s / steps
                    xi = int(prev[0] + (px - prev[0]) * f)
                    yi = int(prev[1] + (y - prev[1]) * f)
                    if 0 <= xi < pw and 0 <= yi < ph:
                        cy, cx = yi >> 2, xi >> 1
                        b.grid[cy][cx] |= Braille._DOT[yi & 3][xi & 1]
                        if weight > inten[cy][cx]:
                            inten[cy][cx] = weight
            prev = (px, y)

    rows = []
    for cy in range(b.hc):
        line = []
        for cx in range(b.wc):
            v = b.grid[cy][cx]
            if v:
                col = GLOW[min(len(GLOW) - 1, inten[cy][cx])]
                line.append(col + chr(0x2800 + v) + RST)
            else:
                line.append(" ")
        rows.append("".join(line))
    return rows


if __name__ == "__main__":
    run(draw, title="Phosphor scope")
