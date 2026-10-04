#!/usr/bin/env python3
"""Mini / status-line mode  (gui-ideas 1.1) — a one-line player render for a
tmux status-right, a polybar module, or a tiny window. `f` toggles full <-> mini.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, render_deck, run, fit, marquee, spinner, THEME_ORDER, RST


def mini_line(pl, w, th, t):
    icon = {"PLAYING": "▶", "PAUSED": "❚❚", "BUFFERING": spinner(t)}[pl.state]
    st = pl.station
    vol = "🔇" if pl.muted else f"{pl.volume:d}%"
    if pl.track_len:
        prog = f"{int(pl.track_elapsed)//60}:{int(pl.track_elapsed)%60:02d}"
    else:
        prog = "LIVE"
    left = f"{th['accent']}{icon} {th['bright']}{st['name']}{RST} {th['dim']}·{RST} "
    right = f" {th['dim']}·{RST} {th['accent']}{prog}{RST} {th['dim']}·{RST} {th['text']}{vol}{RST}"
    room = max(6, w - len(f"{icon} {st['name']} · ") - len(f" · {prog} · {vol}") - 2)
    mid = f"{th['text']}{marquee(pl.track, room, t)}{RST}"
    return fit(f" {left}{mid}{right}", w)


class App:
    title = "mini mode — press f"

    def __init__(self):
        self.pl = Player()
        self.full = False
        self.theme = THEME_ORDER[0]
        self.t = 0.0

    def step(self, dt):
        self.t += dt
        self.pl.step(dt)

    def handle(self, ev):
        if ev == "f":
            self.full = not self.full
        elif ev == "SPACE":
            self.pl.toggle_play()
        elif ev == "n":
            self.pl.next()
        elif ev == "p":
            self.pl.prev()
        elif ev in ("+", "="):
            self.pl.nudge_volume(5)
        elif ev in ("-", "_"):
            self.pl.nudge_volume(-5)

    def render(self, w, h, th):
        if self.full:
            return render_deck(self.pl, w, h, th, self.t,
                               hint="[f] collapse to one line   [Space] play   [n/p] station")
        rows = [""] * (h // 2 - 2)
        rows.append(f"{th['dim']}  as a tmux  status-right  /  a 1-line window:{RST}")
        rows.append("")
        rows.append(f"{th['frame']}  ┌{'─' * (min(w, 84) - 4)}┐{RST}")
        rows.append(f"{th['frame']}  │{RST}" + fit(mini_line(self.pl, min(w, 84) - 6, th, self.t),
                                                   min(w, 84) - 4) + f"{th['frame']}│{RST}")
        rows.append(f"{th['frame']}  └{'─' * (min(w, 84) - 4)}┘{RST}")
        rows.append("")
        rows.append(f"{th['dim']}  [f] expand    [Space] play/pause    [n/p] station    [+/-] vol{RST}")
        while len(rows) < h:
            rows.append("")
        return rows[:h]


if __name__ == "__main__":
    run(App())
