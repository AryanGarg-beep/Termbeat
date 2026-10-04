#!/usr/bin/env python3
"""New chassis styles  (gui-ideas 4.3) — ←/→ cycle alternative frame treatments
for the *same* player: Rack Unit, Boombox, Teletext, Terminal-native, Braun.
Same data, very different skin — the argument for a data-driven layout engine.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, run, box, fit, center, marquee, transport, volume_slider, THEME_ORDER, RST

STYLES = ["Rack Unit", "Boombox", "Teletext", "Terminal-native", "Braun"]


class App:
    title = "design styles — ←/→ to cycle"

    def __init__(self):
        self.pl = Player()
        self.s = 0
        self.theme = THEME_ORDER[0]
        self.t = 0.0

    @property
    def style(self):
        return STYLES[self.s]

    def step(self, dt):
        self.t += dt
        self.pl.step(dt)

    def handle(self, ev):
        if ev in ("RIGHT", "n"):
            self.s = (self.s + 1) % len(STYLES)
        elif ev in ("LEFT", "p"):
            self.s = (self.s - 1) % len(STYLES)
        elif ev == "SPACE":
            self.pl.toggle_play()

    def render(self, w, h, th):
        fn = [self._rack, self._boombox, self._teletext, self._native, self._braun][self.s]
        W = min(w, 84)
        left = (w - W) // 2
        body = fn(W, th)
        top = max(0, (h - len(body)) // 2)
        out = [""] * top + [" " * left + r for r in body]
        while len(out) < h:
            out.append("")
        return out[:h]

    def _line(self, w, th):
        p = self.pl
        return [
            f"{th['accent']}{p.station['name'].upper()}{RST}   {th['dim']}{p.station['freq']} · {p.station['bitrate']} · {p.listeners:,} online{RST}",
            f"{th['bright']}{marquee(p.track, w, self.t)}{RST}",
            volume_slider(p, w - 16, th),
            transport(p, th),
        ]

    def _rack(self, w, th):
        inner = self._line(w - 8, th)
        rows = [f"{th['frame']}╒{'═' * (w - 2)}╕{RST}",
                fit(f"{th['frame']}│ ◉    {th['dim']}TB-9000  RACK TUNER  ·  1U{RST}", w - 1) + f"{th['frame']}│{RST}",
                f"{th['frame']}╞{'═' * (w - 2)}╡{RST}"]
        for l in inner:
            rows.append(fit(f"{th['frame']}│   {RST}{l}", w - 1) + f"{th['frame']}│{RST}")
        rows.append(f"{th['frame']}╘{'═' * (w - 2)}╛{RST}")
        rows.append(f"   {th['dim']}○ ○ ○ ○ ○ ○      ▭ ▭ ▭      ◉ POWER{RST}")
        return rows

    def _boombox(self, w, th):
        sp = "◜◝\n◟◞"
        rows = [center(f"{th['warn']}▄▄▄▄▄▄▄▄▄▄▄▄▄▄  ░▒▓ BOOMBOX ▓▒░  ▄▄▄▄▄▄▄▄▄▄▄▄▄▄{RST}", w)]
        rows.append("")
        deck = box(self._line(w - 24, th), w - 16, th, style="heavy")
        spk = [f"{th['dim']}╭────╮", "│ ◉◉ │", "│ ◉◉ │", "╰────╯"]
        for i, d in enumerate(deck):
            l = spk[i] if i < len(spk) else "      "
            r = spk[i] if i < len(spk) else "      "
            rows.append(fit(f" {th['dim']}{l}{RST} {d} {th['dim']}{r}{RST}", w))
        rows.append(center(f"{th['dim']}▮▮▮▮  ▶ ❚❚ ◀◀ ▶▶  ▮▮▮▮   ⊙ handle ⊙{RST}", w))
        return rows

    def _teletext(self, w, th):
        p = self.pl
        W = min(w, 42)
        rows = [f"{th['accent_bg']}\033[38;2;10;12;16m{fit(' P450  TERMBEAT RADIO      ' + __import__('time').strftime('%a %d %b %H:%M'), W)}{RST}",
                ""]
        rows.append(f"{th['bright']}  {p.station['name'].upper()}{RST}")
        rows.append(f"{th['warn']}  {'▀' * (W - 4)}{RST}")
        for chunk in [p.track[i:i + W - 4] for i in range(0, len(p.track), W - 4)][:3]:
            rows.append(f"{th['text']}  {chunk}{RST}")
        rows.append("")
        rows.append(f"{th['accent']}  VOL {'█' * (p.volume // 8)}{th['dim']}{'░' * (12 - p.volume // 8)}{RST}")
        rows.append(f"{th['dim']}  {'red' if not p.playing else 'grn'} PLAY   ylw NEXT   cyn LIST{RST}")
        rows.append("")
        rows.append(f"{th['dim']}  100 Index   200 Guide   300 DJ{RST}")
        return rows

    def _native(self, w, th):
        p = self.pl
        e = int(p.track_elapsed if p.track_len else p.elapsed)
        return [
            f"{th['accent']}{p.station['name']}{RST} {th['dim']}· {p.station['freq']} · {p.state.lower()}{RST}",
            f"{th['bright']}{p.track}{RST}",
            f"{th['dim']}{e // 60}:{e % 60:02d}"
            f"{('/' + str(p.track_len // 60) + ':' + f'{p.track_len % 60:02d}') if p.track_len else ' live'}"
            f"   vol {p.volume}%   {'loop' if p.repeat else ''}{RST}",
            "",
            f"{th['dim']}space play · n/p station · +/- vol · l list · q quit{RST}",
        ]

    def _braun(self, w, th):
        p = self.pl
        W = min(w, 56)
        n = int(p.volume / 100 * (W - 8))
        rows = [
            f"{th['dim']}┌{'─' * (W - 2)}┐{RST}",
            fit(f"{th['dim']}│{RST}  {th['text']}{p.station['name']}{RST}", W - 1) + f"{th['dim']}│{RST}",
            fit(f"{th['dim']}│{RST}  {th['dim']}{marquee(p.track, W - 8, self.t)}{RST}", W - 1) + f"{th['dim']}│{RST}",
            fit(f"{th['dim']}│{RST}  {th['accent']}{'│' * n}{th['dim']}{'│' * (W - 8 - n)}{RST}", W - 1) + f"{th['dim']}│{RST}",
            fit(f"{th['dim']}│{RST}  {th['dim']}◦ ◦ ◦ ◦{'  ' * 6}{'▶' if p.playing else '❚❚'}{RST}", W - 1) + f"{th['dim']}│{RST}",
            f"{th['dim']}└{'─' * (W - 2)}┘{RST}",
        ]
        return rows


if __name__ == "__main__":
    run(App())
