#!/usr/bin/env python3
"""Theme browser  (gui-ideas 4.1) — flip through the palette set (the 5 termbeat
themes plus Gruvbox / Nord / Dracula / Solarized / Mono) live on the real deck.
←/→ or [ ] change theme; the swatch strip shows each theme's key colours.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, render_deck, run, fit, THEMES, THEME_ORDER, THEMES as _T, RST, bg


class App:
    title = "themes — ←/→ to browse"

    def __init__(self):
        self.pl = Player()
        self.i = 0
        self.t = 0.0

    @property
    def theme(self):
        return THEME_ORDER[self.i]

    def step(self, dt):
        self.t += dt
        self.pl.step(dt)

    def handle(self, ev):
        if ev in ("RIGHT", "]", "n"):
            self.i = (self.i + 1) % len(THEME_ORDER)
        elif ev in ("LEFT", "[", "p"):
            self.i = (self.i - 1) % len(THEME_ORDER)
        elif ev == "SPACE":
            self.pl.toggle_play()

    def render(self, w, h, th):
        rows = render_deck(self.pl, w, h - 3, th, self.t,
                           hint="←/→ browse themes   Space play")
        # swatch strip
        strip = []
        for j, name in enumerate(THEME_ORDER):
            t2 = THEMES[name]
            sw = "".join(t2[k].replace("38", "48") + "  " + RST
                         for k in ("frame", "accent", "bright", "warn", "dim"))
            mark = th['bright'] + "▸ " if j == self.i else "  "
            strip.append(f"{mark}{th['text'] if j==self.i else th['dim']}{name:<14}{RST} {sw}")
        # two columns
        rows.append("")
        half = (len(strip) + 1) // 2
        for a in range(half):
            b = strip[a + half] if a + half < len(strip) else ""
            rows.append(fit(f"  {strip[a]:<44}", w // 2) + fit(b, w - w // 2))
        while len(rows) < h:
            rows.append("")
        return rows[:h]


if __name__ == "__main__":
    run(App())
