#!/usr/bin/env python3
"""Dashboard split  (gui-ideas 1.3) — a persistent station list docked left,
the player right. Tab moves focus between panes; no overlay drawer.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, render_deck, run, box, fit, STATIONS, THEME_ORDER, RST


class App:
    title = "dashboard — split panes"

    def __init__(self):
        self.pl = Player()
        self.focus = 0            # 0 = list, 1 = player
        self.sel = 0
        self.theme = THEME_ORDER[0]
        self.ti = 0
        self.t = 0.0

    def step(self, dt):
        self.t += dt
        self.pl.step(dt)

    def handle(self, ev):
        if ev == "TAB":
            self.focus ^= 1
            return
        if ev == "t":
            self.ti = (self.ti + 1) % len(THEME_ORDER)
            self.theme = THEME_ORDER[self.ti]
            return
        if self.focus == 0:
            if ev == "DOWN":
                self.sel = (self.sel + 1) % len(STATIONS)
            elif ev == "UP":
                self.sel = (self.sel - 1) % len(STATIONS)
            elif ev == "ENTER":
                self.pl.tune(self.sel)
        else:
            if ev == "SPACE":
                self.pl.toggle_play()
            elif ev in ("n", "RIGHT"):
                self.pl.next()
            elif ev in ("p", "LEFT"):
                self.pl.prev()
            elif ev in ("+", "="):
                self.pl.nudge_volume(5)
            elif ev in ("-", "_"):
                self.pl.nudge_volume(-5)

    def render(self, w, h, th):
        lw = min(34, max(24, w // 3))
        rw = w - lw - 1
        # left: station list
        lfoc = self.focus == 0
        litems = []
        namew = lw - 6
        for i, s in enumerate(STATIONS):
            cur = "●" if i == self.pl.idx else " "
            mk = "►" if (i == self.sel and lfoc) else " "
            nm = (th['bright'] if i == self.sel and lfoc else
                  th['accent'] if i == self.pl.idx else th['text'])
            litems.append(f" {th['accent']}{mk}{RST}{th['dim']}{cur}{RST} "
                          f"{nm}{s[0][:namew]}{RST}")
        while len(litems) < h - 2:
            litems.append("")
        left = box(litems, lw, th,
                   title=("▸ " if lfoc else "  ") + "STATIONS",
                   style="heavy" if lfoc else "round")
        # right: player deck (no outer box — dashboard is the frame)
        rdeck = render_deck(self.pl, rw, h, th, self.t, viz=(h > 22),
                            hint="Tab: focus panes   Space/n/p   +/-")
        rows = []
        for i in range(h):
            l = left[i] if i < len(left) else " " * lw
            r = rdeck[i] if i < len(rdeck) else ""
            rows.append(fit(l, lw) + f"{th['frame']}│{RST}" + fit(r, rw))
        return rows


if __name__ == "__main__":
    run(App())
