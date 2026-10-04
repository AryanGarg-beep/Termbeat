#!/usr/bin/env python3
"""Analog VU needles  (idea 5.1) — two swinging gauges + peak LEDs
(revives the VU-meter look removed in termbeat v2)"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, Braille, fg, DIM, BRIGHT, HOT, RST

_l = {"v": 0.1, "pk": 0.0}
_r = {"v": 0.1, "pk": 0.0}
SCALE = "-20   -10   -5   -3  -1  0 +3"


def _gauge(bw, bh, val):
    """One needle gauge -> list of `bh` strings, each `bw` cells."""
    b = Braille(bw, bh)
    cx = b.pw / 2.0
    cy = b.ph - 2
    rad = min(b.pw / 2.0, b.ph) * 0.92
    a0, a1 = math.radians(-52), math.radians(52)
    for k in range(41):                       # arc + ticks
        ang = a0 + (a1 - a0) * (k / 40)
        r0 = rad * (0.70 if k % 5 == 0 else 0.82)
        for rr in range(int(r0), int(rad)):
            b.plot(cx + math.sin(ang) * rr, cy - math.cos(ang) * rr)
    na = a0 + (a1 - a0) * max(0.0, min(1.0, val))
    b.line(cx, cy, cx + math.sin(na) * rad * 0.94, cy - math.cos(na) * rad * 0.94)
    return b.rows(color=(HOT if val > 0.82 else BRIGHT), edge_color=DIM)


def draw(w, h, a, t):
    tl = a.level * (0.4 + 0.6 * (a.bass * 0.7 + a.mid * 0.3))
    tr = a.level * (0.4 + 0.6 * (a.mid * 0.3 + a.treble * 0.7))
    for m, tgt in ((_l, tl), (_r, tr)):
        m["v"] += (tgt - m["v"]) * 0.35
        m["pk"] = max(m["v"], m["pk"] - 0.02)

    gw = max(12, (w - 4) // 2)
    gh = max(4, h - 2)
    gl = _gauge(gw, gh, _l["v"])
    gr = _gauge(gw, gh, _r["v"])
    rows = [((gl[i] if i < len(gl) else "") + "  " + (gr[i] if i < len(gr) else ""))
            for i in range(gh)]

    lpk = (HOT + "● PK") if _l["pk"] > 0.85 else (DIM + "○ pk")
    rpk = (HOT + "● PK") if _r["pk"] > 0.85 else (DIM + "○ pk")
    rows.append(f"{DIM}  L  {lpk}{RST}{DIM}{' ' * max(2, gw - 6)}R  {rpk}{RST}")
    rows.append(f"{DIM}  {SCALE}{' ' * max(2, gw - len(SCALE))}{SCALE}{RST}")
    return rows


if __name__ == "__main__":
    run(draw, title="Analog VU needles")
