#!/usr/bin/env python3
"""Tuning knob / FM dial  (gui-ideas 5.1) — ←/→ sweep the analog dial; it drifts
through static between stations and 'locks' onto the nearest preset. Leans all
the way into the radio metaphor.
"""
import os, sys, math, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, run, box, fit, STATIONS, THEME_ORDER, RST, marquee

LO, HI = 87.5, 108.0
STATIC = "▓▒░ ·:'`^\"~-"


class App:
    title = "tuning knob — ←/→ to tune"

    def __init__(self):
        self.pl = Player()
        self.freq = float(STATIONS[0][1])
        self.target = self.freq
        self.locked = True
        self.t = 0.0
        self.theme = THEME_ORDER[0]

    def step(self, dt):
        self.t += dt
        self.pl.step(dt)
        # ease toward target; lock when close to a preset
        self.freq += (self.target - self.freq) * min(1.0, dt * 8)
        near = min(STATIONS, key=lambda s: abs(float(s[1]) - self.freq))
        if abs(float(near[1]) - self.freq) < 0.08:
            if not self.locked or self.pl.station["freq"] != near[1]:
                self.pl.tune(STATIONS.index(near))
            self.locked = True
        else:
            self.locked = False

    def handle(self, ev):
        step = 0.1
        if ev == "RIGHT":
            self.target = min(HI, self.target + step)
        elif ev == "LEFT":
            self.target = max(LO, self.target - step)
        elif ev == "n":
            nxt = [float(s[1]) for s in STATIONS if float(s[1]) > self.freq + 0.05]
            self.target = min(nxt) if nxt else self.target
        elif ev == "p":
            prv = [float(s[1]) for s in STATIONS if float(s[1]) < self.freq - 0.05]
            self.target = max(prv) if prv else self.target
        elif ev == "SPACE":
            self.pl.toggle_play()

    def _dial(self, w, th):
        span = HI - LO
        n = w
        marks = {int((float(s[1]) - LO) / span * (n - 1)): s for s in STATIONS}
        cur = int((self.freq - LO) / span * (n - 1))
        line = []
        for x in range(n):
            if x == cur:
                line.append(th['warn'] + "▮")
            elif x in marks:
                on = marks[x][0] == self.pl.station["name"]
                line.append((th['accent'] if on else th['dim']) + "┃")
            elif abs(x - cur) < 4 and not self.locked:
                line.append(th['dim'] + random.choice(STATIC))
            else:
                line.append(th['dim'] + "─")
        return "".join(line) + RST

    def render(self, w, h, th):
        W = min(w, 80)
        left = (w - W) // 2
        inner = W - 2
        p = self.pl
        st = "LOCKED" if self.locked else "· · · tuning · · ·"
        body = [
            "",
            fit(f"   {th['dim']}FM{RST}   {th['bright']}\033[1m{self.freq:6.1f}{RST} "
                f"{th['dim']}MHz{RST}      {th['accent'] if self.locked else th['warn']}{st}{RST}", inner),
            "",
            fit("  " + self._dial(inner - 4, th), inner),
            fit(f"  {th['dim']}{LO:.0f}{' ' * (inner - 12)}{HI:.0f}{RST}", inner),
            "",
            fit(f"   {th['dim']}NOW{RST}  {th['accent']}{st if not self.locked else p.station['name'].upper()}{RST}"
                if self.locked else f"   {th['dim']}(no station locked){RST}", inner),
            fit(f"   {th['bright']}{marquee(p.track, inner - 6, self.t) if self.locked else ''}{RST}", inner),
            "",
            fit(f"   {th['dim']}◀ / ▶  sweep    n / p  next preset    Space  play{RST}", inner),
        ]
        boxed = box(body, W, th, title="ANALOG TUNING DIAL")
        top = max(0, (h - len(boxed)) // 2)
        out = [""] * top + [" " * left + r for r in boxed]
        while len(out) < h:
            out.append("")
        return out[:h]


if __name__ == "__main__":
    run(App())
