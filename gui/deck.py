#!/usr/bin/env python3
"""Baseline player deck — the panel every other mock builds on.

Keys: space play/pause · n/p station · +/- volume · m mute · t theme · l loops
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, render_deck, run, THEME_ORDER


class App:
    title = "deck — baseline player"

    def __init__(self):
        self.pl = Player()
        self.ti = 0
        self.theme = THEME_ORDER[0]
        self.t = 0.0

    def step(self, dt):
        self.t += dt
        self.pl.step(dt)

    def handle(self, ev):
        p = self.pl
        if ev == "SPACE":
            p.toggle_play()
        elif ev in ("n", "RIGHT"):
            p.next()
        elif ev in ("p", "LEFT"):
            p.prev()
        elif ev in ("+", "=", "UP"):
            p.nudge_volume(5)
        elif ev in ("-", "_", "DOWN"):
            p.nudge_volume(-5)
        elif ev == "m":
            p.toggle_mute()
        elif ev == "l":
            p.repeat = not p.repeat
        elif ev == "t":
            self.ti = (self.ti + 1) % len(THEME_ORDER)
            self.theme = THEME_ORDER[self.ti]

    def render(self, w, h, th):
        return render_deck(self.pl, w, h, th, self.t)


if __name__ == "__main__":
    run(App())
