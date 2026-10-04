#!/usr/bin/env python3
"""Modular Design HUD  —  a terminal take on the "AESTHETIC MISTAKES / CIRCLES
AND ROUNDS" poster: the big dark turntable, the sweeping outer arc, and a
central sunburst dial with a needle. The sunburst ticks, needle, arc segment
and dot grid are driven by the fake audio.
"""
import os, sys, math, random, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import run, fg, RST

ORANGE = fg(255, 140, 20)
ORANGE_HI = fg(255, 185, 90)
AMBER = fg(210, 110, 15)
WHITE = fg(235, 235, 235)
GREY = fg(95, 95, 95)
GREYD = fg(48, 48, 48)
BLACK = fg(15, 15, 15)
_SGR = re.compile(r"\033\[[0-9;]*m")


# ------------------------------------------------------------ braille canvas

class HUD:
    _DOT = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))

    def __init__(self, wc, hc):
        self.wc, self.hc = wc, hc
        self.pw, self.ph = wc * 2, hc * 4
        self.g = [[0] * wc for _ in range(hc)]
        self.c = {}

    def plot(self, x, y, col):
        xi, yi = int(round(x)), int(round(y))
        if 0 <= xi < self.pw and 0 <= yi < self.ph:
            cy, cx = yi >> 2, xi >> 1
            self.g[cy][cx] |= HUD._DOT[yi & 3][xi & 1]
            self.c[(cy, cx)] = col

    def line(self, x0, y0, x1, y1, col):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(n + 1):
            f = i / n
            self.plot(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, col)

    def arc(self, cx, cy, r, a0, a1, col, ry=None):
        ry = ry if ry is not None else r
        n = max(24, int(abs(a1 - a0) * max(r, ry)))
        for i in range(n + 1):
            a = a0 + (a1 - a0) * i / n
            self.plot(cx + math.cos(a) * r, cy + math.sin(a) * ry, col)

    def rows(self):
        out = []
        for cy in range(self.hc):
            row = []
            for cx in range(self.wc):
                v = self.g[cy][cx]
                row.append(self.c.get((cy, cx), GREY) + chr(0x2800 + v) + RST if v else " ")
            out.append(row)                      # list of per-cell strings
        return out


# --------------------------------------------- character overlay onto cells

def stamp(cells, r, c, s, col):
    if not (0 <= r < len(cells)):
        return
    row = cells[r]
    for i, ch in enumerate(s):
        if ch != " " and 0 <= c + i < len(row):
            row[c + i] = col + ch + RST


def vstamp(cells, r, c, s, col, up=False):
    for i, ch in enumerate(s):
        stamp(cells, r - i if up else r + i, c, ch, col)


# ------------------------------------------------------------------- render

def draw(w, h, a, t):
    cv = HUD(w, h)
    pw, ph = cv.pw, cv.ph
    cx, cy = pw * 0.40, ph * 0.48
    R = min(pw * 0.42, ph * 0.40)

    # big turntable circle
    cv.arc(cx, cy, R, 0, math.tau, GREYD)
    cv.arc(cx, cy, R - 1, 0, math.tau, GREYD)

    # outer arc ring + a bright orange segment sweeping round it
    rr0 = R + 5
    cv.arc(cx, cy, rr0, math.radians(-118), math.radians(64), GREY)
    cv.arc(cx, cy, rr0 + 2, math.radians(-118), math.radians(64), GREY)
    s0 = -1.3 + (t * 0.45) % math.tau
    span = 0.45 + a.bass * 0.8
    for rr in (rr0, rr0 + 1, rr0 + 2, rr0 + 3):
        cv.arc(cx, cy, rr, s0, s0 + span, ORANGE)

    # central sunburst dial (offset up-left of the big circle centre)
    dx, dy = cx - R * 0.16, cy - R * 0.12
    r_in = R * 0.13
    for k in range(9):                                   # filled disk
        cv.arc(dx, dy, r_in * (0.12 + k * 0.11), 0, math.tau, AMBER)
    N = 72
    for i in range(N):
        ang = i / N * math.tau - math.pi / 2
        band = a.bands[int(i / N * 18) % 18]
        b0 = r_in * 1.4
        ln = r_in * (0.35 + band * 1.0)
        col = ORANGE_HI if band > 0.45 else (ORANGE if band > 0.14 else GREYD)
        cv.line(dx + math.cos(ang) * b0, dy + math.sin(ang) * b0,
                dx + math.cos(ang) * (b0 + ln), dy + math.sin(ang) * (b0 + ln), col)
    na = -math.pi / 2 + math.sin(t * 0.55) * 1.15 + a.beat * 0.5
    for o in (-0.04, 0.0, 0.04):
        cv.line(dx, dy, dx + math.cos(na + o) * r_in * 0.95,
                dy + math.sin(na + o) * r_in * 0.95, ORANGE_HI)

    cells = cv.rows()
    hub = (int(dy // 4), int(dx // 2))
    stamp(cells, hub[0], hub[1], "●", BLACK)

    # ---- chrome overlay
    bc = ORANGE_HI if a.beat > 0.4 else ORANGE
    stamp(cells, 0, 0, "┏━━", bc); stamp(cells, 1, 0, "┃", bc)
    stamp(cells, 0, w - 3, "━━┓", bc); stamp(cells, 1, w - 1, "┃", bc)
    stamp(cells, h - 1, 0, "┗━━", bc); stamp(cells, h - 2, 0, "┃", bc)
    stamp(cells, h - 1, w - 3, "━━┛", bc); stamp(cells, h - 2, w - 1, "┃", bc)

    stamp(cells, 1, w // 2 - 1, "══", ORANGE)
    stamp(cells, 2, w // 2 - 1, "══", ORANGE)

    stamp(cells, 3, 3, "┌───▶", ORANGE); stamp(cells, 4, 3, "│", ORANGE)
    stamp(cells, 4, w - 10, "◀────", ORANGE); stamp(cells, 3, w - 6, "▲", ORANGE)

    md = "MODULAR DESIGN"
    # runs down-right from ~10 o'clock on the big circle, clear of the dial
    ang = math.radians(-158)
    r0 = int((cy + math.sin(ang) * R * 0.88) // 4)
    c0 = int((cx + math.cos(ang) * R * 0.88) // 2)
    for i, ch in enumerate(md):
        stamp(cells, r0 + i, c0 + i, ch, WHITE)

    lab = "CIRCLES AND ROUNDS"
    vstamp(cells, h // 2 - len(lab) // 2, w - 2, lab, ORANGE)
    stamp(cells, h // 2 + 8, w - 5, "04", ORANGE_HI)

    am = "AESTHETIC MISTAKES"
    vstamp(cells, h - 3, 6, am, WHITE, up=True)
    for k in range(5):
        stamp(cells, h - 3 - k * 3, 2, f"0{k + 1}", ORANGE if k == 3 else GREY)
    stamp(cells, h - 3 - 3 * 3, 5, "▪", ORANGE)

    # dot texture block, right side, mid height — twinkles with treble
    dr0, dc0 = h // 2 - 4, w - 20
    for rr in range(8):
        for cc in range(0, 14, 2):
            if random.random() < 0.20 + a.treble * 0.55:
                stamp(cells, dr0 + rr, dc0 + cc, "·", GREY)

    para = ["THE NKH STUDIO IS READY", "TO HELP CREATE AND", "EXECUTE OUTSTANDING",
            "PRINT AND MOBILE WORK."]
    for i, ln in enumerate(para):
        stamp(cells, 6 + i, w - 26, ln, GREYD)
    for i in range(3):
        stamp(cells, 11 + i, w - 26, "▬" * 9, ORANGE if i == 0 else GREY)

    stamp(cells, h - 6, w // 2 - 3, "N K H", ORANGE)
    stamp(cells, h - 5, w // 2 - 10, "DESIGN AND PRODUCTION", ORANGE)

    frac = (t * 0.07) % 1.0
    bw = min(w - 24, 54)
    bl = (w - bw) // 2
    n = int(frac * bw)
    hn = min(n, bw // 3)
    bar = "◖" + "".join("╱" if i % 2 == 0 else "─" for i in range(hn)) \
          + "━" * (n - hn) + "─" * (bw - n) + "◗"
    stamp(cells, h - 2, bl - 1, bar, ORANGE)
    stamp(cells, h - 3, bl + n, "▲", ORANGE_HI)

    return ["".join(row) for row in cells]


if __name__ == "__main__":
    run(draw, title="Modular Design HUD", fps=20)
