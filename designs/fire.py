#!/usr/bin/env python3
"""Doom fire  (idea 3.1) — cellular fire, flame height driven by bass"""
import os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, fg, RST

# heat -> glyph + colour
PAL = [
    (" ", ""),
    ("░", fg(70, 20, 10)),
    ("▒", fg(140, 40, 10)),
    ("▓", fg(210, 80, 15)),
    ("▓", fg(255, 140, 30)),
    ("█", fg(255, 200, 70)),
    ("█", fg(255, 240, 160)),
    ("█", fg(255, 255, 230)),
]
_state = {"grid": None, "w": 0, "h": 0}


def draw(w, h, a, t):
    st = _state
    if st["grid"] is None or st["w"] != w or st["h"] != h:
        st["grid"] = [[0] * w for _ in range(h)]
        st["w"], st["h"] = w, h
    g = st["grid"]
    # bottom row = fuel, brightness from bass + kick
    base = 5 + int(a.bass * 2) + (1 if a.beat > 0.5 else 0)
    for x in range(w):
        flick = random.random()
        g[h - 1][x] = max(0, min(7, base if flick > 0.15 else base - 2))
    # propagate upward with random cooling and horizontal drift
    for y in range(h - 2, -1, -1):
        for x in range(w):
            src = x + random.randint(-1, 1)
            src = min(w - 1, max(0, src))
            cool = random.randint(0, 2)
            g[y][x] = max(0, g[y + 1][src] - cool)
    rows = []
    for y in range(h):
        line = []
        for x in range(w):
            ch, col = PAL[g[y][x]]
            line.append((col + ch) if col else " ")
        rows.append("".join(line) + RST)
    return rows


if __name__ == "__main__":
    run(draw, title="Doom fire")
