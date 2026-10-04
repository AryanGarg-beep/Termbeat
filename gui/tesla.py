#!/usr/bin/env python3
"""Car head-unit music screen  —  a terminal take on the Tesla-style "MUSIC"
mock (orange neon on black, status bar, nav rail, cassette, climate strip).

Keys: space play/pause · n/p track · s shuffle · r repeat · +/- volume ·
f favourite · 1-6 nav icon · Tab left rail · a auto-demo toggle
"""
import os, sys, time, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, Braille, run, fit, center, ansi_len, fg, RST

ORANGE = fg(255, 140, 30)
ORANGE_D = fg(150, 78, 20)
WHITE = fg(235, 235, 235)
GREY = fg(120, 120, 120)
GREYD = fg(70, 70, 70)
GLOW = fg(255, 175, 90)

SONGS = [
    ("HOOKED ON A FEELING", "Blue Swede", 289),
    ("AFRICA", "Toto", 295),
    ("TAKE ON ME", "a-ha", 225),
    ("BLUE MONDAY", "New Order", 448),
    ("MIDNIGHT CITY", "M83", 244),
    ("THE CHAIN", "Fleetwood Mac", 271),
]
NAV = ["♪", "◤", "⚡", "⊕", "◉", "☎"]      # music nav charge apps media phone
RAIL = ["♪", "≣", "★", "⚙"]


def cassette(w_cells, h_cells, t, playing):
    b = Braille(w_cells, h_cells)
    pw, ph = b.pw, b.ph
    m = 3
    body_b = ph * 0.80
    # shell
    b.rrect(m, m, pw - m, body_b, rad=6, color=GLOW)
    # label window
    b.rrect(m + 7, m + 5, pw - m - 7, ph * 0.52, rad=3, color=ORANGE)
    # two reels inside the window
    ry = ph * 0.30
    rr = min(pw * 0.11, ph * 0.16)
    spin = t * (3.2 if playing else 0.0)
    b.circle(pw * 0.30, ry, rr * 1.9, ORANGE_D)          # platter behind left reel
    for k, cx in enumerate((pw * 0.33, pw * 0.67)):
        b.circle(cx, ry, rr, ORANGE)
        b.circle(cx, ry, rr * 0.38, ORANGE)
        for s in range(6):
            a = spin * (1 if k == 0 else -1) + s * math.tau / 6
            b.line(cx + math.cos(a) * rr * 0.4, ry + math.sin(a) * rr * 0.4,
                   cx + math.cos(a) * rr * 0.82, ry + math.sin(a) * rr * 0.82, ORANGE)
    # front lip / pinch rollers
    b.line(m + 8, body_b, pw - m - 8, body_b, GLOW)
    b.rrect(m + 8, ph * 0.60, pw - m - 8, body_b - 1, rad=2, color=ORANGE_D)
    for cx in (pw * 0.34, pw * 0.42, pw * 0.58, pw * 0.66):
        b.circle(cx, ph * 0.71, 1.6, ORANGE)
    return b.render(ORANGE)


class App:
    title = "car head-unit · MUSIC"
    theme = "Cyberpunk"

    def __init__(self):
        self.pl = Player()
        self.si = 0
        self.elapsed = 0.0
        self.playing = True
        self.shuffle = False
        self.repeat = False
        self.fav = {0}
        self.vol = 6
        self.nav = 0
        self.rail = 0
        self.t = 0.0
        self.auto = True
        self._auto_at = 8.0

    @property
    def song(self):
        return SONGS[self.si]

    def step(self, dt):
        self.t += dt
        if self.playing:
            self.elapsed += dt
            if self.elapsed >= self.song[2]:
                self._advance(1)
        if self.auto and self.t >= self._auto_at:
            self._auto_at = self.t + 15.0
            self._advance(1)

    def _advance(self, d):
        self.si = (self.si + d) % len(SONGS)
        self.elapsed = 0.0

    def handle(self, ev):
        if ev == "SPACE":
            self.playing = not self.playing
        elif ev == "n":
            self._advance(1)
        elif ev == "p":
            self._advance(-1)
        elif ev == "s":
            self.shuffle = not self.shuffle
        elif ev == "r":
            self.repeat = not self.repeat
        elif ev in ("+", "=", "UP"):
            self.vol = min(11, self.vol + 1)
        elif ev in ("-", "_", "DOWN"):
            self.vol = max(0, self.vol - 1)
        elif ev == "f":
            self.fav ^= {self.si}
        elif ev == "a":
            self.auto = not self.auto
        elif ev in "123456":
            self.nav = int(ev) - 1
        elif ev == "TAB":
            self.rail = (self.rail + 1) % len(RAIL)

    # ---- pieces
    def _statusbar(self, w):
        clk = time.strftime("%-I:%M %p")
        batt = "▮▮▮▮▮"
        left = f"{WHITE}T E S L A{RST}   {GREY}⚙ JOHN ▾{RST}"
        right = f"{GREY}86% {ORANGE}{batt}{RST}   {GREY}AT&T 4G   69°{RST}"
        mid = f"{WHITE}{clk}{RST}"
        gap1 = max(1, (w - ansi_len(left) - ansi_len(mid) - ansi_len(right)) // 2)
        gap2 = max(1, w - ansi_len(left) - ansi_len(mid) - ansi_len(right) - gap1)
        return fit(f"{left}{' ' * gap1}{mid}{' ' * gap2}{right}", w)

    def _navrail(self, w):
        cells = []
        for i, ic in enumerate(NAV):
            if i == self.nav:
                cells.append(f"{ORANGE}( {ic} ){RST}")
            else:
                cells.append(f"{GREY}( {ic} ){RST}")
        s = "     ".join(cells)
        return center(s, w)

    def _transport(self, w):
        icons = ["⤨ ", "◁◁", "❚❚" if self.playing else "▶ ", "▷▷", "⟳ "]
        active = 2
        tops, mids, bots = [], [], []
        for i, ic in enumerate(icons):
            b = ORANGE if i == active else WHITE
            tops.append(f"{b}┌────┐{RST}")
            mids.append(f"{b}│ {ic} │{RST}")
            bots.append(f"{b}└────┘{RST}")
        return [center("   ".join(tops), w), center("   ".join(mids), w),
                center("   ".join(bots), w)]

    def _progress(self, w):
        cur = int(self.elapsed)
        tot = self.song[2]
        frac = self.elapsed / tot
        bw = min(w - 20, 60)
        n = int(frac * bw)
        pad = (w - bw - 16) // 2
        head = (" " * pad + f"{GREY}{cur//60:02d}:{cur%60:02d}"
                + " " * (bw - 8) + f"{GREYD}{tot//60:02d}:{tot%60:02d}{RST}")
        bar = " " * pad + f"{ORANGE}{'━' * n}{GREYD}{'━' * (bw - n)}{RST}"
        return [fit(head, w), fit(bar, w)]

    def _climate(self, w):
        seat2 = f"{ORANGE}⛭²{RST}" if True else GREY + "⛭"
        cells = [f"{WHITE}▙ CAR{RST}", f"{ORANGE}23{RST}", f"{ORANGE}⛭ 2{RST}",
                 f"{WHITE}❄FRT{RST}", f"{GREY}CUSTOM AUTO{RST} {ORANGE}ON{RST}",
                 f"{WHITE}❄REAR{RST}", f"{ORANGE}⛭ 3{RST}", f"{ORANGE}20{RST}",
                 f"{WHITE}🔊 {self.vol}{RST}"]
        total = sum(ansi_len(c) for c in cells)
        gap = max(2, (w - total) // (len(cells) - 1))
        return fit((" " * gap).join(cells), w)

    def render(self, w, h, th):
        W = min(w, 104)
        left = (w - W) // 2
        pad = " " * left
        rows = []
        rows.append(pad + self._statusbar(W))
        rows.append(pad + f"{GREYD}{'─' * W}{RST}")
        rows.append(pad + self._navrail(W))
        rows.append("")
        # header + left rail sit beside the body
        railcol = []
        for i, ic in enumerate(RAIL):
            railcol.append(f"{ORANGE if i == self.rail else GREY} {ic} {RST}")
        rows.append(pad + f"  {ORANGE}◎ {WHITE}\033[1mM U S I C{RST}   {GREY}PLAYING NOW{RST}")
        rows.append(pad + f"{GREYD}{'─' * W}{RST}")

        body_h = max(8, h - len(rows) - 9)
        cw = min(W - 12, 62)
        ch = min(body_h - 1, 13)
        cas = cassette(cw // 2, ch, self.t, self.playing)
        casleft = (W - cw) // 2
        for i in range(ch):
            rl = railcol[i] if i < len(railcol) else "   "
            line = cas[i] if i < len(cas) else ""
            rows.append(pad + fit(f" {rl} " + " " * (casleft - 4) + line, W))
        rows.append("")
        rows += [pad + fit(r, W) for r in self._transport(W)]
        rows.append("")
        rows += [pad + fit(r, W) for r in self._progress(W)]
        rows.append("")
        title, artist, _ = self.song
        rows.append(pad + fit(f"        {ORANGE}\033[1m{title}{RST} {GREY}— {GREYD}{artist.upper()}{RST}", W))
        rows.append(pad + fit(f"        {GREY}{artist}{RST}", W))
        rows.append("")
        star = f"{ORANGE}★{RST}" if self.si in self.fav else f"{GREY}☆{RST}"
        rows.append(pad + center(f"{ORANGE}⤳ share{RST}        {star} favourite        "
                                 f"{ORANGE}≣+ add{RST}", W))
        while len(rows) < h - 2:
            rows.append("")
        rows.append(pad + f"{GREYD}{'┈' * W}{RST}")
        rows.append(pad + self._climate(W))
        return rows[:h]


if __name__ == "__main__":
    run(App())
