#!/usr/bin/env python3
"""Recently played  (gui-ideas 3.2) — a scrollable list of the last tracks with
timestamps. `h` toggles the panel; ↑/↓ scroll; Enter re-tunes that station.
Speed is boosted so history fills quickly.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, render_deck, run, box, fit, STATIONS, THEME_ORDER, RST


class App:
    title = "recently played — press h"

    def __init__(self):
        self.pl = Player()
        self.pl._next_track_at = 4.0          # roll tracks fast for the demo
        self.show = True
        self.scroll = 0
        self.theme = THEME_ORDER[0]
        self.t = 0.0

    def step(self, dt):
        self.t += dt
        self.pl.step(dt * 3)                  # 3x time so the list grows

    def handle(self, ev):
        if ev == "h":
            self.show = not self.show
        elif ev == "SPACE":
            self.pl.toggle_play()
        elif ev == "n":
            self.pl.next()
        elif ev == "p":
            self.pl.prev()
        elif self.show and ev == "DOWN":
            self.scroll += 1
        elif self.show and ev == "UP":
            self.scroll = max(0, self.scroll - 1)
        elif self.show and ev == "ENTER":
            hist = list(self.pl.history)
            if hist:
                stn = hist[min(self.scroll, len(hist) - 1)][1]
                for i, s in enumerate(STATIONS):
                    if s[0] == stn:
                        self.pl.tune(i)
                        break

    def render(self, w, h, th):
        if not self.show:
            return render_deck(self.pl, w, h, th, self.t,
                               hint="[h] show history   [Space] play   [n/p] station")
        deck_h = min(12, h // 2)
        rows = render_deck(self.pl, w, deck_h, th, self.t, viz=False,
                           hint="[h] hide history")
        rows = [r for r in rows if r.strip() or True][:deck_h]
        pw = min(w - 4, 86)
        pad = " " * ((w - pw) // 2)
        hist = list(self.pl.history)
        self.scroll = min(self.scroll, max(0, len(hist) - 1))
        view = hist[self.scroll:self.scroll + (h - deck_h - 4)]
        inner = []
        now = time.time()
        for i, (tr, stn, when) in enumerate(view):
            ago = int(now - when)
            am = f"{ago//60}m{ago%60:02d}s" if ago >= 60 else f"{ago:>2d}s"
            cur = "►" if i == 0 and self.scroll == 0 else " "
            inner.append(f" {th['accent']}{cur}{RST} {th['dim']}{am:>7} ago{RST}  "
                         f"{th['text']}{tr:<44}{RST} {th['dim']}{stn}{RST}")
        if not inner:
            inner = [f" {th['dim']}collecting… tracks roll every few seconds in this demo{RST}"]
        panel = box(inner, pw, th,
                    title=f"RECENTLY PLAYED  ({len(hist)})  ↑/↓ scroll · Enter re-tune")
        rows += [pad + p for p in panel]
        while len(rows) < h:
            rows.append("")
        return rows[:h]


if __name__ == "__main__":
    run(App())
