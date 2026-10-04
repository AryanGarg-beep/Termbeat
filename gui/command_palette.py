#!/usr/bin/env python3
"""Command palette  (gui-ideas 2.2) — Ctrl-P / ':' opens a fuzzy finder over
stations + every action. Type to filter, ↑/↓ to move, Enter to run, Esc closes.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, render_deck, run, box, fit, STATIONS, THEME_ORDER, RST

ACTIONS = [
    ("play/pause", "toggle_play"), ("next station", "next"), ("prev station", "prev"),
    ("mute", "mute"), ("volume up", "volup"), ("volume down", "voldown"),
    ("sleep timer 30m", "sleep"), ("toggle loop", "loop"), ("cycle theme", "theme"),
    ("open station list", "list"), ("copy now playing", "copy"), ("quit", "quit"),
]


def fuzzy(q, s):
    q = q.lower()
    s = s.lower()
    if not q:
        return 0
    i = 0
    score = 0
    run_ = 0
    for ch in s:
        if i < len(q) and ch == q[i]:
            i += 1
            run_ += 1
            score += run_
        else:
            run_ = 0
    return score if i == len(q) else -1


class App:
    title = "command palette — Ctrl-P"

    def __init__(self):
        self.pl = Player()
        self.open = False
        self.q = ""
        self.sel = 0
        self.theme = THEME_ORDER[0]
        self.ti = 0
        self.t = 0.0
        self.flash = ""

    def step(self, dt):
        self.t += dt
        self.pl.step(dt)

    def _items(self):
        rows = []
        for name, act in ACTIONS:
            sc = fuzzy(self.q, name)
            if sc >= 0:
                rows.append((sc + 5, f"⚡ {name}", ("act", act)))
        for i, s in enumerate(STATIONS):
            sc = fuzzy(self.q, s[0] + " " + s[2])
            if sc >= 0:
                rows.append((sc, f"📻 {s[0]}  ·  {s[2]}", ("tune", i)))
        rows.sort(key=lambda r: -r[0])
        return rows

    def handle(self, ev):
        if not self.open:
            if ev in ("CTRL_P", ":"):
                self.open = True
                self.q = ""
                self.sel = 0
            elif ev == "SPACE":
                self.pl.toggle_play()
            elif ev == "n":
                self.pl.next()
            elif ev == "p":
                self.pl.prev()
            return
        # palette open
        if ev == "ESC":
            self.open = False
        elif ev == "BACKSPACE":
            self.q = self.q[:-1]
            self.sel = 0
        elif ev == "DOWN":
            self.sel += 1
        elif ev == "UP":
            self.sel = max(0, self.sel - 1)
        elif ev == "ENTER":
            items = self._items()
            if items:
                self._run(items[min(self.sel, len(items) - 1)][2])
            self.open = False
        elif isinstance(ev, str) and len(ev) == 1 and ev.isprintable():
            self.q += ev
            self.sel = 0

    def _run(self, target):
        kind, val = target
        if kind == "tune":
            self.pl.tune(val)
            self.flash = f"Tuned to {STATIONS[val][0]}"
        elif val == "toggle_play":
            self.pl.toggle_play()
        elif val == "next":
            self.pl.next()
        elif val == "prev":
            self.pl.prev()
        elif val == "mute":
            self.pl.toggle_mute()
        elif val == "volup":
            self.pl.nudge_volume(10)
        elif val == "voldown":
            self.pl.nudge_volume(-10)
        elif val == "theme":
            self.ti = (self.ti + 1) % len(THEME_ORDER)
            self.theme = THEME_ORDER[self.ti]
        elif val == "loop":
            self.pl.repeat = not self.pl.repeat
        else:
            self.flash = f"(demo) action: {val}"

    def render(self, w, h, th):
        base = render_deck(self.pl, w, h, th, self.t,
                           hint="[Ctrl-P] command palette   [Space] play   [n/p] station")
        if self.flash:
            base[-2] = fit(f"  {th['warn']}✓ {self.flash}{RST}", w)
        if not self.open:
            return base
        # dim + overlay
        base = [f"{th['dim']}{_strip(r)}{RST}" for r in base]
        items = self._items()
        self.sel = min(self.sel, max(0, len(items) - 1))
        pw = min(w - 8, 64)
        inner = [f" {th['bright']}> {th['text']}{self.q}{th['accent']}▌{RST}",
                 f"{th['frame']}{'─' * (pw - 2)}{RST}"]
        for i, (_, label, _t) in enumerate(items[:h - 10]):
            mark = th['accent_bg'] + "\033[38;2;10;15;20m" if i == self.sel else ""
            inner.append(f"{mark} {label:<{pw-4}} {RST}")
        if not items:
            inner.append(f" {th['dim']}no matches{RST}")
        ov = box(inner, pw, th, title="RUN A COMMAND  (Esc closes)")
        top = 3
        left = (w - pw) // 2
        for i, line in enumerate(ov):
            if top + i < len(base):
                base[top + i] = " " * left + line
        return base


def _strip(s):
    import re
    return re.sub(r"\033\[[0-9;]*m", "", s)


if __name__ == "__main__":
    run(App())
