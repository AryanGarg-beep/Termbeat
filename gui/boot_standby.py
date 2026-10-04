#!/usr/bin/env python3
"""Boot sequence + standby  (gui-ideas 4.5 + 1.6).

On launch: a short "power on" animation (lamp test, VU sweep, TUNING…), any key
skips it. Then the deck. After ~12 s idle it drifts into a standby screensaver
(bouncing logo + clock); any key wakes it. Press `b` to replay the boot.
"""
import os, sys, time, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, render_deck, run, fit, center, THEME_ORDER, RST

BOOT_SECS = 3.2
IDLE_SECS = 12.0
LOGO = ["▛▀▘▛▀▖▛▀▖▛▚▀▖▛▀▖▛▀▘▛▀▖▛▀▖▛▀▖▐▀▘",
        "  ▌   ▌▛▀ ▌▐ ▌▛▀▖▛▀ ▛▀▖▌▐ ▌  ▌  ",
        "▙▄▖▌▗▖▌▙▄▘▌ ▌▙▄▘▙▄▖▌ ▌▙▄▘▌ ▌▐▄▖"]


class App:
    title = "boot + standby — b replays boot"

    def __init__(self):
        self.pl = Player()
        self.theme = THEME_ORDER[0]
        self.t = 0.0
        self.phase = "boot"
        self.phase_t = 0.0
        self.last_input = 0.0

    def step(self, dt):
        self.t += dt
        self.phase_t += dt
        self.pl.step(dt)
        if self.phase == "boot" and self.phase_t >= BOOT_SECS:
            self._to("deck")
        if self.phase == "deck" and self.t - self.last_input >= IDLE_SECS:
            self._to("standby")

    def _to(self, ph):
        self.phase = ph
        self.phase_t = 0.0

    def handle(self, ev):
        self.last_input = self.t
        if ev == "b":
            self._to("boot")
            return
        if self.phase == "boot":
            self._to("deck")
            return
        if self.phase == "standby":
            self._to("deck")
            return
        if ev == "SPACE":
            self.pl.toggle_play()
        elif ev == "n":
            self.pl.next()
        elif ev == "p":
            self.pl.prev()

    def render(self, w, h, th):
        if self.phase == "boot":
            return self._boot(w, h, th)
        if self.phase == "standby":
            return self._standby(w, h, th)
        idle = self.t - self.last_input
        rows = render_deck(self.pl, w, h, th, self.t,
                           hint=f"[b] replay boot   ·   standby in {max(0, IDLE_SECS-idle):.0f}s idle")
        return rows

    def _boot(self, w, h, th):
        p = self.phase_t / BOOT_SECS
        rows = [""] * (h // 2 - 4)
        for l in LOGO:
            rows.append(center(f"{th['accent']}{l}{RST}", w))
        rows.append("")
        if p < 0.35:
            lamps = "".join(th['bright'] + "●" if (i / 18) < p / 0.35 else th['dim'] + "○"
                            for i in range(18))
            rows.append(center(f"{lamps}{RST}   {th['dim']}lamp test{RST}", w))
        elif p < 0.7:
            k = (p - 0.35) / 0.35
            n = int(k * 30)
            rows.append(center(f"{th['accent']}{'▮' * n}{th['dim']}{'▯' * (30 - n)}{RST}"
                               f"   {th['dim']}VU sweep{RST}", w))
        else:
            dots = "." * (int((p - 0.7) * 12) % 4)
            rows.append(center(f"{th['warn']}TUNING{dots}{RST}", w))
        rows.append("")
        rows.append(center(f"{th['dim']}(any key skips){RST}", w))
        while len(rows) < h:
            rows.append("")
        return rows[:h]

    def _standby(self, w, h, th):
        grid = [[" "] * w for _ in range(h)]
        lw = max(len(x) for x in LOGO)
        px = int((math.sin(self.phase_t * 0.7) * 0.5 + 0.5) * max(1, w - lw - 2))
        py = int((math.sin(self.phase_t * 0.53 + 1) * 0.5 + 0.5) * max(1, h - 5))
        for dy, line in enumerate(LOGO):
            for dx, ch in enumerate(line):
                if ch != " " and 0 <= py + dy < h and 0 <= px + dx < w:
                    grid[py + dy][px + dx] = ch
        clock = time.strftime("%H:%M")
        rows = ["".join(r) for r in grid]
        rows[h - 1] = fit(f"{th['dim']}  standby · {clock} · any key wakes{RST}", w)
        return [f"{th['dim']}{r}{RST}" for r in rows[:h - 1]] + [rows[h - 1]]


if __name__ == "__main__":
    run(App())
