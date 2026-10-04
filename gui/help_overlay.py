#!/usr/bin/env python3
"""Help overlay  (gui-ideas 2.8) — '?' opens a grouped, dimmed key reference.
Any key closes it.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, render_deck, run, box, fit, RST

GROUPS = [
    ("Playback", [("Space", "play / pause"), ("s", "stop"), ("m", "mute"),
                  ("+  -", "volume ±5"), ("r", "toggle loop")]),
    ("Tuning", [("n  →", "next station"), ("p  ←", "previous station"),
                ("1-9", "jump to preset"), ("l", "station directory"),
                ("<  >", "history back / forward")]),
    ("View", [("d", "cycle design style"), ("t", "cycle colour theme"),
              ("v", "cycle visualizer"), ("z", "focus / zen mode"),
              ("F1-F3", "size preset")]),
    ("App", [("?", "this help"), (":", "command palette"), (",", "settings"),
             ("y", "copy now-playing"), ("q  Esc", "quit")]),
]


class App:
    title = "help overlay — press ?"

    def __init__(self):
        self.pl = Player()
        self.show = False
        self.t = 0.0

    def step(self, dt):
        self.t += dt
        self.pl.step(dt)

    def handle(self, ev):
        if self.show:
            self.show = False
            return
        if ev == "?":
            self.show = True
        elif ev == "SPACE":
            self.pl.toggle_play()
        elif ev == "n":
            self.pl.next()
        elif ev == "p":
            self.pl.prev()

    def render(self, w, h, th):
        base = render_deck(self.pl, w, h, th, self.t,
                           hint="[?] keys   [Space] play   [n/p] station")
        if not self.show:
            return base
        import re
        base = [f"{th['dim']}{re.sub(r'\033\\[[0-9;]*m','',r)}{RST}" for r in base]
        pw = min(w - 6, 72)
        inner = []
        for gi, (title, keys) in enumerate(GROUPS):
            if gi:
                inner.append("")
            inner.append(f" {th['accent']}{title.upper()}{RST}")
            for k, d in keys:
                inner.append(f"   {th['bright']}{k:<9}{RST} {th['text']}{d}{RST}")
        ov = box(inner, pw, th, title="KEYS  ·  any key closes")
        top = max(0, (len(base) - len(ov)) // 2)
        left = (w - pw) // 2
        for i, line in enumerate(ov):
            if top + i < len(base):
                base[top + i] = " " * left + line
        return base


if __name__ == "__main__":
    run(App())
