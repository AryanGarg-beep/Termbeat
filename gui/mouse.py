#!/usr/bin/env python3
"""Mouse support  (gui-ideas 2.1) — click the transport buttons, drag the volume
slider, wheel over it, click a station in the list, click the dial to tune.

Shows the hit-map approach: render builds `self.regions = [(x0,x1,y0,y1, action)]`
as it lays out, and clicks are tested against it. Needs a terminal with mouse
reporting (most do).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, run, box, fit, mouse, STATIONS, THEME_ORDER, RST, marquee


class App:
    title = "mouse — click / drag / wheel"

    def __init__(self):
        self.pl = Player()
        self.regions = []
        self.hover = None
        self.theme = THEME_ORDER[0]
        self.ti = 0
        self.t = 0.0
        self.drag_vol = False

    def step(self, dt):
        self.t += dt
        self.pl.step(dt)

    def _hit(self, x, y):
        for (x0, x1, y0, y1, act) in self.regions:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return act
        return None

    def handle(self, ev):
        m = mouse(ev)
        if not m:
            if ev == "SPACE":
                self.pl.toggle_play()
            elif ev == "t":
                self.ti = (self.ti + 1) % len(THEME_ORDER)
                self.theme = THEME_ORDER[self.ti]
            return
        kind, x, y = m
        act = self._hit(x, y)
        if kind == "WHEELUP":
            self.pl.nudge_volume(4)
        elif kind == "WHEELDOWN":
            self.pl.nudge_volume(-4)
        elif kind == "DOWN":
            if act == "play":
                self.pl.toggle_play()
            elif act == "next":
                self.pl.next()
            elif act == "prev":
                self.pl.prev()
            elif act == "loop":
                self.pl.repeat = not self.pl.repeat
            elif act == "mute":
                self.pl.toggle_mute()
            elif isinstance(act, tuple) and act[0] == "vol":
                self._set_vol(x, act)
                self.drag_vol = True
            elif isinstance(act, tuple) and act[0] == "tune":
                self.pl.tune(act[1])
        elif kind == "DRAG" and self.drag_vol:
            for (x0, x1, y0, y1, a) in self.regions:
                if isinstance(a, tuple) and a[0] == "vol":
                    self._set_vol(max(x0, min(x1, x)), a)
        elif kind == "UP":
            self.drag_vol = False
        self.hover = act if kind in ("DOWN", "DRAG") else self.hover

    def _set_vol(self, x, act):
        _, x0, x1 = act
        self.pl.muted = False
        self.pl.volume = int(round((x - x0) / max(1, x1 - x0) * 100))
        self.pl.volume = max(0, min(100, self.pl.volume))

    def render(self, w, h, th):
        self.regions = []
        W = min(w, 84)
        left = (w - W) // 2
        inner = W - 2
        p = self.pl
        rows_body = []

        st = p.station
        rows_body.append(f" {th['accent']}♫ {th['bright']}termbeat{RST}"
                         f"{' ' * (inner - 22)}{th['dim']}[ {p.state} ]{RST}")
        rows_body.append(f"{th['frame']}{'─' * inner}{RST}")
        rows_body.append(fit(f"  {th['accent']}{st['name'].upper()}{RST}", inner))
        rows_body.append(fit(f"  {th['bright']}{marquee(p.track, inner - 4, self.t)}{RST}", inner))
        rows_body.append("")

        # transport row  (record button rects)
        btn_row_idx = len(rows_body)
        labels = [("⟳ LOOP", "loop", p.repeat),
                  ("◀◀ PREV", "prev", False),
                  ("❚❚ PAUSE" if p.playing else "▶ PLAY ", "play", p.playing),
                  ("NEXT ▶▶", "next", False)]
        seg = []
        cx = 4
        for lab, act, on in labels:
            txt = f"[ {lab} ]"
            col = th['accent'] if on else th['text']
            seg.append(col + txt + RST)
            self._btn(left + 1 + cx, left + cx + len(txt), btn_row_idx, act, rows_body)
            cx += len(txt) + 3
        rows_body.append("   " + "   ".join(seg))
        rows_body.append("")

        # volume slider  (record slider rect)
        vrow = len(rows_body)
        sx = 6
        sw = inner - 20
        n = int(round(p.volume / 100 * sw)) if not p.muted else 0
        bar = (th['warn'] + "░" * sw if p.muted else
               th['accent'] + "▰" * n + th['dim'] + "▱" * (sw - n))
        rows_body.append(f"  {th['text']}VOL {bar}{RST}  {th['accent']}"
                         f"{'MUT' if p.muted else f'{p.volume:3d}%'}{RST}")
        self.regions.append((left + 1 + sx, left + sx + sw, vrow, vrow, ("vol", left + 1 + sx, left + sx + sw)))
        mx = left + sx + sw + 3
        self.regions.append((mx, mx + 3, vrow, vrow, "mute"))
        rows_body.append("")

        # station list  (record a rect per row)
        rows_body.append(f"  {th['dim']}STATIONS  — click to tune{RST}")
        for i, s in enumerate(STATIONS):
            ridx = len(rows_body)
            cur = th['accent'] + "●" if i == p.idx else th['dim'] + " "
            hov = self.hover == ("tune", i)
            nm = th['bright'] if hov else (th['accent'] if i == p.idx else th['text'])
            rows_body.append(f"   {cur}{RST} {nm}{i+1:2d}. {s[0]:<20}{RST}"
                             f"{th['dim']}{s[1]:>7} MHz  [{s[2]}]{RST}")
            self.regions.append((left + 1, left + inner, ridx, ridx, ("tune", i)))

        boxed = box(rows_body, W, th, title="MOUSE  ·  wheel = volume")
        # shift region y by where the box lands
        top = max(0, (h - len(boxed)) // 2)
        self.regions = [(x0, x1, y0 + top + 1, y1 + top + 1, a) for (x0, x1, y0, y1, a) in self.regions]
        out = [""] * top + [(" " * left) + r for r in boxed]
        while len(out) < h:
            out.append("")
        return out[:h]

    def _btn(self, x0, x1, y, act, _rows):
        self.regions.append((x0, x1, y, y, act))


if __name__ == "__main__":
    run(App(), mouse=True)
