#!/usr/bin/env python3
"""Tabbed views  (gui-ideas 1.4) — Now Playing / Stations / History / Settings / Help.

Keys: Tab / Shift-Tab or 1-5 switch tabs · arrows navigate within a tab ·
space play/pause · n/p station
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import (Player, render_deck, run, box, fit, STATIONS, THEME_ORDER, RST)

TABS = ["Now Playing", "Stations", "History", "Settings", "Help"]
SETTINGS = [("Design style", ["Retro Hi-Fi", "Modern Neo", "Minimal Zen", "Cyberpunk"]),
            ("Colour theme", THEME_ORDER),
            ("Metadata poll", ["15s", "30s", "60s"]),
            ("Adaptive FPS", ["on", "off"]),
            ("Album art", ["auto", "on", "off"]),
            ("Notifications", ["on", "off"])]


class App:
    title = "tabs — five-view shell"

    def __init__(self):
        self.pl = Player()
        self.tab = 0
        self.sel = 0
        self.setsel = 0
        self.setval = [0] * len(SETTINGS)
        self.theme = THEME_ORDER[0]
        self.t = 0.0

    def step(self, dt):
        self.t += dt
        self.pl.step(dt)

    def handle(self, ev):
        if ev == "TAB":
            self.tab = (self.tab + 1) % len(TABS); return
        if ev == "BACKTAB":
            self.tab = (self.tab - 1) % len(TABS); return
        if ev in "12345":
            self.tab = int(ev) - 1; return
        if ev == "SPACE":
            self.pl.toggle_play(); return
        if ev in ("n",):
            self.pl.next(); return
        if ev in ("p",):
            self.pl.prev(); return
        if self.tab == 1:  # stations
            if ev == "DOWN":
                self.sel = (self.sel + 1) % len(STATIONS)
            elif ev == "UP":
                self.sel = (self.sel - 1) % len(STATIONS)
            elif ev == "ENTER":
                self.pl.tune(self.sel)
                self.tab = 0
        elif self.tab == 3:  # settings
            if ev == "DOWN":
                self.setsel = (self.setsel + 1) % len(SETTINGS)
            elif ev == "UP":
                self.setsel = (self.setsel - 1) % len(SETTINGS)
            elif ev in ("RIGHT", "ENTER"):
                opts = SETTINGS[self.setsel][1]
                self.setval[self.setsel] = (self.setval[self.setsel] + 1) % len(opts)
                if self.setsel == 1:
                    self.theme = THEME_ORDER[self.setval[1]]
            elif ev == "LEFT":
                opts = SETTINGS[self.setsel][1]
                self.setval[self.setsel] = (self.setval[self.setsel] - 1) % len(opts)
                if self.setsel == 1:
                    self.theme = THEME_ORDER[self.setval[1]]

    def _tabbar(self, w, th):
        cells = []
        for i, name in enumerate(TABS):
            if i == self.tab:
                cells.append(f"{th['accent_bg']}{fg_dark()} {name} {RST}")
            else:
                cells.append(f"{th['dim']} {name} {RST}")
        return fit(" " + "".join(cells), w)

    def render(self, w, h, th):
        rows = [self._tabbar(w, th), f"{th['frame']}{'─' * w}{RST}", ""]
        area_h = h - 3
        if self.tab == 0:
            body = render_deck(self.pl, w, area_h, th, self.t)
        elif self.tab == 1:
            body = self._stations(w, area_h, th)
        elif self.tab == 2:
            body = self._history(w, area_h, th)
        elif self.tab == 3:
            body = self._settings(w, area_h, th)
        else:
            body = self._help(w, area_h, th)
        rows += body
        while len(rows) < h:
            rows.append("")
        return rows[:h]

    def _stations(self, w, h, th):
        inner = []
        for i, s in enumerate(STATIONS):
            cur = "●" if i == self.pl.idx else " "
            mark = "►" if i == self.sel else " "
            row = (f" {th['accent']}{mark}{RST} {th['dim']}{cur}{RST} "
                   f"{i+1:02d}. {th['bright'] if i==self.sel else th['text']}{s[0]:<18}{RST} "
                   f"{th['dim']}{s[1]:>6} MHz  [{s[2]:<6}]  {s[3]}  {s[4]}{RST}")
            inner.append(row)
        return box(inner, min(w, 76), th, title="STATION DIRECTORY  ↑/↓  Enter to tune")

    def _history(self, w, h, th):
        inner = []
        for tr, stn, when in list(self.pl.history)[:h - 4]:
            ago = int(time.time() - when)
            inner.append(f" {th['dim']}{ago//60:2d}m{ago%60:02d}s ago{RST}  "
                         f"{th['text']}{tr:<40}{RST} {th['dim']}{stn}{RST}")
        if not inner:
            inner = [f" {th['dim']}(nothing yet — change stations / wait for a track){RST}"]
        return box(inner, min(w, 80), th, title="RECENTLY PLAYED")

    def _settings(self, w, h, th):
        inner = []
        for i, (name, opts) in enumerate(SETTINGS):
            mark = "►" if i == self.setsel else " "
            val = opts[self.setval[i]]
            inner.append(f" {th['accent']}{mark}{RST} {th['text'] if i==self.setsel else th['dim']}"
                         f"{name:<16}{RST}  {th['dim']}‹{RST} {th['bright']}{val:^12}{RST} {th['dim']}›{RST}")
        return box(inner, min(w, 60), th, title="SETTINGS  ↑/↓ · ←/→ to change")

    def _help(self, w, h, th):
        keys = [("Space", "play / pause"), ("n / p", "next / previous station"),
                ("+ / -", "volume"), ("m", "mute"), ("Tab / 1-5", "switch view"),
                ("↑ / ↓", "move selection"), ("Enter", "tune / apply"),
                ("t", "cycle theme"), ("q", "quit")]
        inner = [f"  {th['accent']}{k:<10}{RST} {th['text']}{d}{RST}" for k, d in keys]
        return box(inner, min(w, 44), th, title="KEYS")


def fg_dark():
    return "\033[38;2;10;15;20m"


if __name__ == "__main__":
    run(App())
