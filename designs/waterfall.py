#!/usr/bin/env python3
"""Waterfall / spectrogram  (idea 1.2) — scrolling history, colour + glyph = magnitude"""
import os, sys
from collections import deque
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, fg, RST

_HIST = deque(maxlen=600)
# level -> (glyph, colour); low levels are near-invisible so structure shows
STEPS = [
    (" ", ""),
    ("·", fg(30, 70, 45)),
    ("░", fg(40, 120, 70)),
    ("▒", fg(55, 175, 95)),
    ("▓", fg(90, 220, 120)),
    ("█", fg(170, 245, 170)),
    ("█", fg(245, 255, 245)),
]


def draw(w, h, a, t):
    _HIST.append(tuple(a.bands))
    cols = list(_HIST)[-w:]
    off = w - len(cols)
    rows = []
    for r in range(h):
        bi = int((h - 1 - r) / max(1, h - 1) * 17)   # top row = highest band
        line = []
        for c in range(w):
            j = c - off
            if 0 <= j < len(cols):
                v = cols[j][bi]
                g, col = STEPS[min(len(STEPS) - 1, int(v * (len(STEPS) - 1) * 1.3))]
                line.append(col + g if col else " ")
            else:
                line.append(" ")
        rows.append("".join(line) + RST)
    return rows


if __name__ == "__main__":
    run(draw, title="Waterfall / spectrogram")
