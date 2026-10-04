#!/usr/bin/env python3
"""Toasts  (gui-ideas 6.2) — transient bottom-right messages that stack and fade.
Every action raises one; a fake network blip raises a warning toast on its own.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, render_deck, run, fit, THEME_ORDER, RST


class Toasts:
    def __init__(self):
        self.items = []          # (text, kind, born)

    def push(self, text, kind="info"):
        self.items.append([text, kind, time.monotonic()])
        self.items = self.items[-4:]

    def render_into(self, rows, w, th):
        now = time.monotonic()
        self.items = [it for it in self.items if now - it[2] < 3.2]
        y = len(rows) - 2 - len(self.items)
        for k, (text, kind, born) in enumerate(self.items):
            age = now - born
            fade = th['dim'] if age > 2.4 else (
                th['warn'] if kind == "warn" else
                th['bright'] if kind == "ok" else th['accent'])
            icon = {"warn": "⚠", "ok": "✓", "info": "•"}[kind]
            box_ = f"{fade}▐ {icon} {text} {RST}"
            yy = y + k
            if 0 <= yy < len(rows):
                pad = max(0, w - len(f"▐ {icon} {text} ") - 2)
                rows[yy] = fit(" " * pad + box_, w)
        return rows


class App:
    title = "toasts — every action notifies"

    def __init__(self):
        self.pl = Player()
        self.toasts = Toasts()
        self.theme = THEME_ORDER[0]
        self.ti = 0
        self.t = 0.0
        self._blip_at = 6.0
        self.toasts.push("Welcome to termbeat", "ok")

    def step(self, dt):
        self.t += dt
        self.pl.step(dt)
        if self.t >= self._blip_at:
            self._blip_at = self.t + 9.0
            self.toasts.push("Network hiccup — reconnecting…", "warn")

    def handle(self, ev):
        p = self.pl
        if ev == "SPACE":
            p.toggle_play()
            self.toasts.push("Playing" if p.playing else "Paused")
        elif ev == "n":
            p.next()
            self.toasts.push(f"Tuned to {p.station['name']}", "ok")
        elif ev == "p":
            p.prev()
            self.toasts.push(f"Tuned to {p.station['name']}", "ok")
        elif ev in ("+", "="):
            p.nudge_volume(5)
            self.toasts.push(f"Volume {p.volume}%")
        elif ev in ("-", "_"):
            p.nudge_volume(-5)
            self.toasts.push(f"Volume {p.volume}%")
        elif ev == "m":
            p.toggle_mute()
            self.toasts.push("Muted" if p.muted else "Unmuted")
        elif ev == "f":
            self.toasts.push("Added to favourites", "ok")
        elif ev == "y":
            self.toasts.push(f"Copied: {p.track}", "ok")
        elif ev == "t":
            self.ti = (self.ti + 1) % len(THEME_ORDER)
            self.theme = THEME_ORDER[self.ti]
            self.toasts.push(f"Theme: {self.theme}")

    def render(self, w, h, th):
        rows = render_deck(self.pl, w, h, th, self.t,
                           hint="[Space] [n/p] [+/-] [m] [f] favourite [y] copy [t] theme")
        return self.toasts.render_into(rows, w, th)


if __name__ == "__main__":
    run(App())
