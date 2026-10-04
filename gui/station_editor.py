#!/usr/bin/env python3
"""In-app station editor  (gui-ideas 7.2) — add / edit / remove a station from a
form instead of hand-editing stations.json. ↑/↓ pick a field, type to edit,
Tab next field, Ctrl-S save (demo: just validates + toasts), Ctrl-N new,
Ctrl-D delete. Validates the URL scheme like the real `normalize_station`.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, run, box, fit, STATIONS, THEME_ORDER, RST

FIELDS = ["name", "url", "freq", "genre", "bitrate", "provider"]
PROVIDERS = ["somafm", "plaza", "rparad", "kexp", "generic"]


class App:
    title = "station editor — a form, not JSON"

    def __init__(self):
        self.stations = [dict(zip(FIELDS,
                          (s[0], f"https://ice.example.com/{s[0].lower().replace(' ','')}",
                           s[1], s[2], s[3], s[4]))) for s in STATIONS]
        self.i = 0
        self.f = 0
        self.msg = ""
        self.msg_t = 0.0
        self.theme = THEME_ORDER[0]
        self.pl = Player()
        self.t = 0.0

    def step(self, dt):
        self.t += dt

    @property
    def cur(self):
        return self.stations[self.i]

    def _validate(self):
        s = self.cur
        if not s["name"].strip():
            return "name is required"
        if not (s["url"].startswith("http://") or s["url"].startswith("https://")):
            return "url must start with http:// or https://"
        try:
            float(s["freq"])
        except ValueError:
            return "freq must be a number"
        return None

    def handle(self, ev):
        s = self.cur
        if ev == "DOWN" or ev == "TAB":
            self.f = (self.f + 1) % len(FIELDS)
        elif ev == "UP" or ev == "BACKTAB":
            self.f = (self.f - 1) % len(FIELDS)
        elif ev == "RIGHT" and self.f == FIELDS.index("provider"):
            s["provider"] = PROVIDERS[(PROVIDERS.index(s["provider"]) + 1) % len(PROVIDERS)]
        elif ev == "PAGEDOWN":
            self.i = (self.i + 1) % len(self.stations); self.f = 0
        elif ev == "PAGEUP":
            self.i = (self.i - 1) % len(self.stations); self.f = 0
        elif ev == "BACKSPACE":
            s[FIELDS[self.f]] = s[FIELDS[self.f]][:-1]
        elif ev == "CTRL_N":
            self.stations.append(dict(zip(FIELDS, ("", "https://", "0.0", "RADIO", "128k", "generic"))))
            self.i = len(self.stations) - 1; self.f = 0
            self._flash("new blank station")
        elif ev == "CTRL_D":
            if len(self.stations) > 1:
                self.stations.pop(self.i)
                self.i %= len(self.stations)
                self._flash("removed", "warn")
        elif ev == "CTRL_S":
            err = self._validate()
            self._flash(err or f"saved {len(self.stations)} stations ✓", "warn" if err else "ok")
        elif isinstance(ev, str) and len(ev) == 1 and ev.isprintable():
            s[FIELDS[self.f]] += ev

    def _flash(self, m, kind="ok"):
        self.msg = m
        self.msg_kind = kind
        self.msg_t = time.monotonic()

    def render(self, w, h, th):
        W = min(w, 76)
        left = (w - W) // 2
        inner = W - 2
        s = self.cur
        body = [f" {th['dim']}editing {th['bright']}{self.i+1}/{len(self.stations)}{RST}"
                f"{th['dim']}   PgUp/PgDn switch · Ctrl-N new · Ctrl-D delete · Ctrl-S save{RST}",
                f"{th['frame']}{'─' * inner}{RST}"]
        for k, name in enumerate(FIELDS):
            mark = th['accent'] + "►" if k == self.f else " "
            cursor = th['accent'] + "▌" if k == self.f else ""
            val = s[name]
            if name == "provider":
                val = f"‹ {val} ›"
            body.append(f" {mark}{RST} {th['dim']}{name:>9}{RST}  "
                        f"{th['text']}{val}{cursor}{RST}")
        body.append("")
        err = self._validate()
        if err:
            body.append(f" {th['warn']}⚠ {err}{RST}")
        else:
            body.append(f" {th['bright']}✓ valid — would write to ~/.config/termbeat/stations.json{RST}")
        if self.msg and time.monotonic() - self.msg_t < 3:
            col = th['warn'] if getattr(self, "msg_kind", "ok") == "warn" else th['accent']
            body.append(f" {col}» {self.msg}{RST}")
        boxed = box(body, W, th, title="STATION EDITOR")
        top = max(0, (h - len(boxed)) // 2)
        out = [""] * top + [" " * left + r for r in boxed]
        while len(out) < h:
            out.append("")
        return out[:h]


if __name__ == "__main__":
    run(App())
