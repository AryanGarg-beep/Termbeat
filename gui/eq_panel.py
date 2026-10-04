#!/usr/bin/env python3
"""Graphic EQ  (gui-ideas 5.3) — a 10-band equaliser you actually adjust.
←/→ pick a band, ↑/↓ move it ±, 0 flattens it, number keys 1-5 load presets.
(Would map to mpv's `af=superequalizer` in the real app.)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, run, box, fit, THEME_ORDER, RST

BANDS = ["31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
PRESETS = {
    "1 Flat":     [0] * 10,
    "2 Bass":     [7, 6, 4, 2, 0, 0, 0, 0, 0, 0],
    "3 Vocal":    [-2, -1, 0, 2, 4, 4, 3, 1, 0, -1],
    "4 Treble":   [0, 0, 0, 0, 0, 1, 3, 5, 6, 7],
    "5 Loudness": [6, 4, 1, 0, -1, 0, 1, 3, 5, 6],
}
PNAMES = list(PRESETS)


class App:
    title = "graphic EQ — ↑/↓ adjust, 1-5 presets"

    def __init__(self):
        self.pl = Player()
        self.gain = [0] * 10
        self.sel = 0
        self.preset = "custom"
        self.theme = THEME_ORDER[0]
        self.t = 0.0

    def step(self, dt):
        self.t += dt
        self.pl.step(dt)

    def handle(self, ev):
        if ev == "RIGHT":
            self.sel = (self.sel + 1) % 10
        elif ev == "LEFT":
            self.sel = (self.sel - 1) % 10
        elif ev == "UP":
            self.gain[self.sel] = min(12, self.gain[self.sel] + 1)
            self.preset = "custom"
        elif ev == "DOWN":
            self.gain[self.sel] = max(-12, self.gain[self.sel] - 1)
            self.preset = "custom"
        elif ev == "0":
            self.gain[self.sel] = 0
            self.preset = "custom"
        elif ev in "12345":
            name = PNAMES[int(ev) - 1]
            self.gain = list(PRESETS[name])
            self.preset = name
        elif ev == "SPACE":
            self.pl.toggle_play()

    def render(self, w, h, th):
        W = min(w, 72)
        left = (w - W) // 2
        inner = W - 2
        SPAN = 12
        HROWS = 13
        body = [""]
        for r in range(HROWS):
            val = SPAN - r * (2 * SPAN / (HROWS - 1))     # +12 .. -12
            line = ["  "]
            for b in range(10):
                g = self.gain[b]
                col = th['accent'] if b == self.sel else (
                    th['bright'] if g > 0 else th['warn'] if g < 0 else th['dim'])
                if abs(val) < 0.9:
                    line.append(f"{th['dim']}──── ")     # 0 dB rule
                elif (g >= 0 and 0 <= val <= g) or (g < 0 and g <= val <= 0):
                    line.append(f"{col}█▊ ▊█ " if b == self.sel else f"{col} ██  ")
                elif abs(val - g) < 1.1:
                    line.append(f"{col} ▄▄  ")
                else:
                    line.append(f"{th['dim']}  ·  ")
            gnum = f"{th['dim']}{int(val):+3d}" if abs(val) < 0.9 or r % 3 == 0 else "   "
            body.append(fit("".join(line) + " " + gnum, inner))
        body.append(fit("   " + "".join(
            f"{th['accent'] if i == self.sel else th['dim']}{n:^5}" for i, n in enumerate(BANDS)), inner))
        body.append(fit("   " + "".join(
            f"{th['text']}{g:^+5d}" for g in self.gain), inner))
        body.append("")
        pl = "  ".join(f"{th['accent'] if n == self.preset else th['dim']}{n}{RST}" for n in PNAMES)
        body.append(fit(f"   {pl}    {th['dim']}0 = flat band{RST}", inner))
        boxed = box(body, W, th, title=f"10-BAND EQ   [{self.preset}]")
        top = max(0, (h - len(boxed)) // 2)
        out = [""] * top + [" " * left + r for r in boxed]
        while len(out) < h:
            out.append("")
        return out[:h]


if __name__ == "__main__":
    run(App())
