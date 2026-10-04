#!/usr/bin/env python3
"""Shared scaffolding for the termbeat interface / GUI mock-ups.

Each `gui/<name>.py` is a standalone, interactive preview of one idea from
`docs/gui-ideas.md`. Nothing plays audio; a `Player` fakes the state a real
termbeat carries (station list, now-playing, volume, elapsed, buffering,
history) so the interface has something to move.

    python3 gui/tabs.py            # one mock, full screen
    python3 gui/gallery.py         # a launcher menu for all of them

Ctrl-C / q quits and restores the terminal. Pure standard library.
"""

import math
import os
import random
import re
import select
import shutil
import signal
import sys
import time
from collections import deque

try:
    import termios
    import tty
    HAS_TTY = True
except ImportError:                       # pragma: no cover
    HAS_TTY = False

RST = "\033[0m"
_SGR = re.compile(r"\033\[[0-9;]*m")


def fg(r, g, b):
    return f"\033[38;2;{r};{g};{b}m"


def bg(r, g, b):
    return f"\033[48;2;{r};{g};{b}m"


def ansi_len(s: str) -> int:
    return len(_SGR.sub("", s))


def fit(s: str, w: int, fill: str = " ") -> str:
    """Pad / trim to exactly `w` visible cells, never cutting an SGR escape."""
    out, vis, i, n = [], 0, 0, len(s)
    while i < n and vis < w:
        if s[i] == "\033":
            j = s.find("m", i)
            if j == -1:
                break
            out.append(s[i:j + 1])
            i = j + 1
        else:
            out.append(s[i])
            vis += 1
            i += 1
    out.append(RST)
    if vis < w:
        out.append(fill * (w - vis))
    return "".join(out)


def center(s: str, w: int) -> str:
    pad = max(0, (w - ansi_len(s)) // 2)
    return fit(" " * pad + s, w)


def mouse(ev):
    """('DOWN'|'UP'|'DRAG'|'WHEELUP'|'WHEELDOWN', x, y) for a mouse event, else None."""
    if isinstance(ev, str) and ev.startswith("MOUSE_"):
        kind, x, y = ev[6:].split(":")
        return kind, int(x), int(y)
    return None


# --------------------------------------------------------------------- themes

def _theme(frame, panel, text, dim, accent, bright, warn):
    return {
        "frame": fg(*frame), "panel": bg(*panel), "text": fg(*text),
        "dim": fg(*dim), "accent": fg(*accent), "bright": fg(*bright),
        "warn": fg(*warn), "accent_bg": bg(*accent),
    }


THEMES = {
    "Classic Tuna": _theme((70, 95, 145), (12, 18, 32), (210, 222, 240),
                           (90, 110, 150), (0, 220, 255), (55, 255, 95), (255, 210, 40)),
    "Cyberpunk":    _theme((170, 45, 140), (20, 10, 30), (235, 220, 245),
                           (120, 70, 130), (255, 25, 140), (0, 240, 255), (255, 220, 40)),
    "Amber CRT":    _theme((155, 105, 35), (24, 15, 6), (255, 226, 170),
                           (150, 100, 45), (255, 190, 60), (255, 200, 90), (255, 120, 40)),
    "Matrix":       _theme((30, 115, 50), (6, 14, 8), (200, 255, 210),
                           (40, 110, 55), (110, 255, 145), (60, 255, 100), (230, 240, 60)),
    "Synthwave":    _theme((115, 60, 165), (20, 10, 34), (250, 230, 255),
                           (120, 70, 140), (255, 95, 185), (0, 235, 255), (255, 200, 60)),
    "Gruvbox":      _theme((146, 131, 116), (29, 32, 33), (235, 219, 178),
                           (124, 111, 100), (215, 153, 33), (184, 187, 38), (250, 189, 47)),
    "Nord":         _theme((76, 86, 106), (46, 52, 64), (216, 222, 233),
                           (97, 110, 136), (136, 192, 208), (163, 190, 140), (235, 203, 139)),
    "Dracula":      _theme((98, 114, 164), (40, 42, 54), (248, 248, 242),
                           (98, 114, 164), (189, 147, 249), (80, 250, 123), (255, 184, 108)),
    "Solarized":    _theme((88, 110, 117), (0, 43, 54), (147, 161, 161),
                           (88, 110, 117), (38, 139, 210), (133, 153, 0), (181, 137, 0)),
    "Mono":         _theme((160, 160, 160), (16, 16, 16), (220, 220, 220),
                           (110, 110, 110), (255, 255, 255), (235, 235, 235), (200, 200, 200)),
}
THEME_ORDER = list(THEMES)


# --------------------------------------------------------------- fake state

STATIONS = [
    # name, freq, genre, bitrate, provider, track_seconds (None = live-only)
    ("Groove Salad",     "88.5",  "CHILL",  "128k", "somafm", None),
    ("Drone Zone",       "91.3",  "SPACE",  "128k", "somafm", None),
    ("Mission Control",   "94.2",  "NASA",   "128k", "somafm", None),
    ("Nightwave Plaza",  "96.0",  "VAPOR",  "128k", "plaza",  214),
    ("Def Con Radio",    "98.9",  "HACK",   "128k", "somafm", None),
    ("Underground 80s",  "101.7", "NEWWAV", "128k", "somafm", None),
    ("Radio Paradise",   "105.7", "ECLTC",  "128k", "rparad", 268),
    ("KEXP Seattle",     "90.3",  "INDIE",  "160k", "kexp",   201),
]

_TRACKS = [
    "S1gns Of L1fe - Illumination", "Tycho - Awake", "Boards of Canada - Roygbiv",
    "Bonobo - Kerala", "Com Truise - Propagation", "HOME - Resonance",
    "Carbon Based Lifeforms - Photosynthesis", "ODESZA - A Moment Apart",
    "Little People - Start Shootin'", "Emancipator - Soon It Will Be Cold Enough",
]


class Player:
    """Everything the interface needs to render, minus the audio."""

    def __init__(self):
        self.idx = 0
        self.volume = 72
        self.prev_volume = 72
        self.playing = True
        self.muted = False
        self.repeat = True
        self.buffering = 0.0                 # seconds of buffering remaining
        self.elapsed = 0.0                   # session seconds on this station
        self.track = random.choice(_TRACKS)
        self.track_elapsed = 0.0
        self.track_len = STATIONS[0][5]
        self._next_track_at = random.uniform(30, 55)
        self.history = deque(maxlen=40)      # (track, station, wallclock)
        self.listeners = random.randint(900, 3200)

    # ---- derived
    @property
    def station(self):
        s = STATIONS[self.idx]
        return {"name": s[0], "freq": s[1], "genre": s[2], "bitrate": s[3],
                "provider": s[4]}

    @property
    def state(self):
        if self.buffering > 0:
            return "BUFFERING"
        if not self.playing:
            return "PAUSED"
        return "PLAYING"

    # ---- mutation
    def step(self, dt):
        if self.buffering > 0:
            self.buffering = max(0.0, self.buffering - dt)
            return
        if not self.playing:
            return
        self.elapsed += dt
        self.track_elapsed += dt
        if self.track_len and self.track_elapsed >= self.track_len:
            self._roll_track()
        elif not self.track_len and self.elapsed >= self._next_track_at:
            self._roll_track()
            self._next_track_at = self.elapsed + random.uniform(30, 55)
        self.listeners += random.randint(-3, 3)

    def _roll_track(self):
        self.history.appendleft((self.track, self.station["name"], time.time()))
        self.track = random.choice(_TRACKS)
        self.track_elapsed = 0.0

    def tune(self, i):
        i %= len(STATIONS)
        if i == self.idx:
            return
        self.history.appendleft((self.track, self.station["name"], time.time()))
        self.idx = i
        self.track = random.choice(_TRACKS)
        self.track_elapsed = 0.0
        self.track_len = STATIONS[i][5]
        self.elapsed = 0.0
        self._next_track_at = random.uniform(30, 55)
        self.buffering = random.uniform(0.8, 1.8)
        self.listeners = random.randint(900, 3200)
        self.playing = True

    def next(self):
        self.tune(self.idx + 1)

    def prev(self):
        self.tune(self.idx - 1)

    def toggle_play(self):
        self.playing = not self.playing

    def nudge_volume(self, d):
        if self.muted:
            self.muted = False
        self.volume = max(0, min(100, self.volume + d))

    def toggle_mute(self):
        self.muted = not self.muted


# ---------------------------------------------------------------- widgets

def hbar(frac, w, th, fillc="█", emptyc="░"):
    frac = max(0.0, min(1.0, frac))
    n = int(round(frac * w))
    return th["accent"] + fillc * n + th["dim"] + emptyc * (w - n) + RST


def dotbar(frac, w, th):
    n = int(round(max(0.0, min(1.0, frac)) * (w - 1)))
    return th["accent"] + "━" * n + th["bright"] + "●" + th["dim"] + "─" * (w - 1 - n) + RST


def marquee(text, w, t, speed=5.0):
    unit = f"   {text}   ◆"
    if not unit:
        return " " * w
    off = int(t * speed) % len(unit)
    s = (unit * (w // len(unit) + 3))[off:off + w]
    return fit(s, w)


SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def spinner(t):
    return SPIN[int(t * 12) % len(SPIN)]


def transport(pl, th, focus=None, compact=False):
    labels = (("⟳", "◀◀", "❚❚" if pl.playing else "▶", "▶▶")
              if compact else
              ("⟳ LOOP", "◀◀ PREV", "❚❚ PAUSE" if pl.playing else "▶ PLAY ", "NEXT ▶▶"))
    out = []
    for i, lab in enumerate(labels):
        on = (i == 0 and pl.repeat) or (i == 2 and pl.playing)
        col = th["accent_bg"] + fg(10, 15, 20) if i == focus else (
            th["accent"] if on else th["dim"])
        out.append(f"{col} [ {lab} ] {RST}")
    return "  ".join(out)


def volume_slider(pl, w, th):
    if pl.muted:
        return f"{th['warn']}VOL {'░' * w}  MUTED{RST}"
    n = int(round(pl.volume / 100 * w))
    return (f"{th['text']}VOL {th['accent']}{'▰' * n}{th['dim']}{'▱' * (w - n)}"
            f"  {th['accent']}{pl.volume:3d}%{RST}")


def box(inner, w, th, title="", style="round"):
    """Frame `inner` (list of strings, already <= w-2 wide) in a w-wide box."""
    sets = {
        "round":  "╭╮╰╯─│", "square": "┌┐└┘─│", "double": "╔╗╚╝═║",
        "ascii":  "++++-|", "heavy":  "┏┓┗┛━┃",
    }
    tl, tr, bl, br, h, v = sets.get(style, sets["round"])
    fr = th["frame"]
    top = f"{fr}{tl}{h * (w - 2)}{tr}{RST}"
    if title:
        t = f" {title} "
        top = fit(f"{fr}{tl}{h}{h}{th['bright']}{t}{fr}", w - 1, h) + f"{fr}{tr}{RST}"
    rows = [top]
    for line in inner:
        rows.append(f"{fr}{v}{RST}{fit(line, w - 2)}{fr}{v}{RST}")
    rows.append(f"{fr}{bl}{h * (w - 2)}{br}{RST}")
    return rows


# ------------------------------------------------------------------ input

class Input:
    """Keys + SGR-1006 mouse. `get()` returns a list of events per frame.

    Key events are strings ("q", "UP", "ENTER", "CTRL_P", "ESC", ...).
    Mouse events are also strings: "MOUSE_DOWN:x:y", "MOUSE_UP:x:y",
    "MOUSE_DRAG:x:y", "MOUSE_WHEELUP:x:y", "MOUSE_WHEELDOWN:x:y" (1-based cells).
    Use `mouse(ev)` to decode one -> (kind, x, y) or None.
    """

    def __init__(self, mouse=False):
        self.mouse = mouse
        self._buf = b""

    def __enter__(self):
        self.ok = HAS_TTY and sys.stdin.isatty()
        if self.ok:
            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        if self.mouse:
            sys.stdout.write("\033[?1000h\033[?1006h")
            sys.stdout.flush()
        return self

    def __exit__(self, *_):
        if self.mouse:
            sys.stdout.write("\033[?1006l\033[?1000l")
            sys.stdout.flush()
        if getattr(self, "ok", False):
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

    def get(self):
        if not getattr(self, "ok", False):
            return []
        while select.select([self.fd], [], [], 0)[0]:
            try:
                chunk = os.read(self.fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            self._buf += chunk
        ev, self._buf = _parse(self._buf)
        return ev


_CSI = {
    "A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT", "H": "HOME", "F": "END",
    "Z": "BACKTAB", "5~": "PAGEUP", "6~": "PAGEDOWN", "3~": "DEL", "2~": "INS",
}


def _parse(buf: bytes):
    ev, i, n = [], 0, len(buf)
    while i < n:
        b = buf[i]
        if b == 0x1B:
            if i + 1 >= n:
                return ev, buf[i:]
            if buf[i + 1] == 0x5B:                       # CSI
                if buf[i + 2:i + 3] == b"<":             # SGR mouse
                    j = i + 3
                    while j < n and buf[j] not in (0x4D, 0x6D):
                        j += 1
                    if j >= n:
                        return ev, buf[i:]
                    body = buf[i + 3:j].decode("ascii", "ignore")
                    final = buf[j]
                    try:
                        bcode, x, y = (int(p) for p in body.split(";"))
                    except ValueError:
                        i = j + 1
                        continue
                    if bcode & 64:
                        kind = "WHEELUP" if bcode & 1 == 0 else "WHEELDOWN"
                    elif bcode & 32:
                        kind = "DRAG"
                    elif final == 0x4D:
                        kind = "DOWN"
                    else:
                        kind = "UP"
                    ev.append(f"MOUSE_{kind}:{x}:{y}")
                    i = j + 1
                    continue
                j = i + 2
                while j < n and 0x30 <= buf[j] <= 0x3F:
                    j += 1
                while j < n and 0x20 <= buf[j] <= 0x2F:
                    j += 1
                if j >= n:
                    return ev, buf[i:]
                seq = buf[i + 2:j + 1].decode("ascii", "ignore")
                ev.append(_CSI.get(seq, "ESC"))
                i = j + 1
                continue
            if buf[i + 1] == 0x4F and i + 2 < n:         # SS3
                ev.append(_CSI.get(chr(buf[i + 2]), "ESC"))
                i += 3
                continue
            ev.append("ESC")
            i += 1
            continue
        if b == 0x0D or b == 0x0A:
            ev.append("ENTER"); i += 1; continue
        if b == 0x09:
            ev.append("TAB"); i += 1; continue
        if b == 0x7F:
            ev.append("BACKSPACE"); i += 1; continue
        if b == 0x20:
            ev.append("SPACE"); i += 1; continue
        if b == 0x03:
            ev.append("QUIT"); i += 1; continue
        if b < 0x20:
            ev.append(f"CTRL_{chr(b + 64)}"); i += 1; continue
        # utf-8
        ln = 1 if b < 0x80 else 4 if b >= 0xF0 else 3 if b >= 0xE0 else 2
        if i + ln > n:
            return ev, buf[i:]
        try:
            ev.append(buf[i:i + ln].decode("utf-8"))
        except UnicodeDecodeError:
            pass
        i += ln
    return ev, b""


# -------------------------------------------------------------------- loop

def run(app, *, fps=30, mouse=False):
    """`app` needs: .render(w, h, th) -> list[str]  and  .handle(ev) -> bool
    (return False to quit).  Optional: .theme (name), .title, .step(dt)."""
    stop = {"v": False}
    for s in ("SIGINT", "SIGTERM", "SIGHUP"):
        sig = getattr(signal, s, None)
        if sig:
            signal.signal(sig, lambda *_: stop.__setitem__("v", True))

    sys.stdout.write("\033[?1049h\033[?25l\033[2J")
    sys.stdout.flush()
    try:
        with Input(mouse=mouse) as inp:
            t0 = last = time.monotonic()
            while not stop["v"]:
                now = time.monotonic()
                dt = now - last
                last = now
                if hasattr(app, "step"):
                    app.step(dt)
                for ev in inp.get():
                    if ev in ("q", "Q", "QUIT"):
                        stop["v"] = True
                        break
                    if app.handle(ev) is False:
                        stop["v"] = True
                        break
                if stop["v"]:
                    break
                cols, rows = shutil.get_terminal_size((100, 30))
                th = THEMES[getattr(app, "theme", "Classic Tuna")]
                title = getattr(app, "title", app.__class__.__name__)
                head = fit(f"{th['accent']}{title}{RST}  "
                           f"{th['dim']}[q quits]{RST}", cols)
                body = app.render(cols, rows - 1, th)
                out = ["\033[H" + head + "\033[K"]
                for r in range(rows - 1):
                    out.append(fit(body[r] if r < len(body) else "", cols) + "\033[K")
                sys.stdout.write("\n".join(out) + "\033[J")
                sys.stdout.flush()
                time.sleep(max(0.0, 1.0 / fps - (time.monotonic() - now)))
    finally:
        sys.stdout.write("\033[?25h\033[0m\033[?1049l")
        sys.stdout.flush()
        print("closed.")


# ----------------------------------------------------- shared player deck

def render_deck(pl, w, h, th, t, *, progress=True, spin=True, viz=True,
                hint="[Space] play  [n/p] station  [+/-] vol  [l] list  [t] theme"):
    """The common termbeat-style player panel, reused by most mock-ups.
    Returns exactly `h` rows, each `w` cells."""
    W = min(w, 92)
    pad = " " * ((w - W) // 2)
    inner = W - 2
    st = pl.station
    rows = []

    # header
    tag = f"{th['accent']}[ {pl.state} ]{RST}" + (
        f" {th['dim']}{spinner(t)}{RST}" if (spin and pl.state == 'BUFFERING') else "")
    left = f"{th['accent']}♫ {th['bright']}termbeat{RST}"
    rows.append(fit(f"{left}{' ' * max(1, inner - ansi_len(left) - ansi_len(tag))}{tag}", inner))
    rows.append(f"{th['frame']}{'─' * inner}{RST}")

    # station + listeners
    nm = f"{th['accent']}{st['name'].upper()}{RST}"
    meta = f"{th['dim']}{pl.listeners:,} online · {st['bitrate']} · {st['genre']}{RST}"
    rows.append(fit(f"  {nm}{' ' * max(1, inner - ansi_len(nm) - ansi_len(meta) - 4)}{meta}  ", inner))
    # track marquee
    rows.append(fit(f"  {th['bright']}{marquee(pl.track, inner - 4, t)}{RST}  ", inner))

    # progress / live line
    if progress:
        if pl.track_len:
            cur = int(pl.track_elapsed)
            tot = int(pl.track_len)
            bar = dotbar(pl.track_elapsed / pl.track_len, inner - 18, th)
            line = f"  {th['dim']}{cur//60}:{cur%60:02d}{RST} {bar} {th['dim']}{tot//60}:{tot%60:02d}{RST}  "
        else:
            e = int(pl.elapsed)
            line = f"  {th['dim']}{e//60}:{e%60:02d}{RST} {th['accent']}{'━' * (inner - 22)}{RST} {th['warn']}● LIVE{RST}  "
        rows.append(fit(line, inner))
    rows.append("")

    # optional mini spectrum
    if viz:
        for r in range(min(4, max(0, h - 12))):
            bars = []
            for i in range(inner - 6):
                v = abs(math.sin(t * 2.3 + i * 0.5) * 0.5 + math.sin(t * 1.1 + i) * 0.4)
                lvl = 4 - r
                bars.append(th["bright"] + "█" if v * 5 >= lvl else th["dim"] + " ")
            rows.append(fit("   " + "".join(bars) + RST, inner))
        rows.append("")

    rows.append(fit("  " + transport(pl, th), inner))
    rows.append(fit("  " + volume_slider(pl, inner - 18, th), inner))
    rows.append(f"{th['frame']}{'─' * inner}{RST}")
    rows.append(fit(f" {th['dim']}{hint}{RST}", inner))

    boxed = box(rows, W, th)
    top_pad = max(0, (h - len(boxed)) // 2)
    out = [""] * top_pad + [pad + r for r in boxed]
    while len(out) < h:
        out.append("")
    return out[:h]


# --------------------------------------------------- braille line canvas

class Braille:
    """2x4-dots-per-cell canvas for clean line art (circles, rects, needles).
    Tracks a per-cell colour so different shapes can glow differently."""

    _DOT = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))  # [y%4][x%2]

    def __init__(self, wc, hc):
        self.wc, self.hc = max(1, wc), max(1, hc)
        self.pw, self.ph = self.wc * 2, self.hc * 4
        self.grid = [[0] * self.wc for _ in range(self.hc)]
        self.col = {}                       # (cy, cx) -> colour escape

    def plot(self, x, y, color=None):
        xi, yi = int(round(x)), int(round(y))
        if 0 <= xi < self.pw and 0 <= yi < self.ph:
            cy, cx = yi >> 2, xi >> 1
            self.grid[cy][cx] |= Braille._DOT[yi & 3][xi & 1]
            if color:
                self.col[(cy, cx)] = color

    def line(self, x0, y0, x1, y1, color=None):
        steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(steps + 1):
            f = i / steps
            self.plot(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, color)

    def circle(self, cx, cy, r, color=None, a0=0.0, a1=math.tau, ry=None):
        ry = ry if ry is not None else r
        steps = max(24, int((a1 - a0) * max(r, ry)))
        for i in range(steps + 1):
            a = a0 + (a1 - a0) * i / steps
            self.plot(cx + math.cos(a) * r, cy + math.sin(a) * ry, color)

    def rrect(self, x0, y0, x1, y1, rad=3, color=None):
        self.line(x0 + rad, y0, x1 - rad, y0, color)
        self.line(x0 + rad, y1, x1 - rad, y1, color)
        self.line(x0, y0 + rad, x0, y1 - rad, color)
        self.line(x1, y0 + rad, x1, y1 - rad, color)
        for cx, cy, a0 in ((x0 + rad, y0 + rad, math.pi), (x1 - rad, y0 + rad, -math.pi / 2),
                           (x1 - rad, y1 - rad, 0.0), (x0 + rad, y1 - rad, math.pi / 2)):
            self.circle(cx, cy, rad, color, a0, a0 + math.pi / 2)

    def render(self, default_color):
        out = []
        for cy in range(self.hc):
            row = []
            for cx in range(self.wc):
                v = self.grid[cy][cx]
                if v:
                    row.append(self.col.get((cy, cx), default_color) + chr(0x2800 + v) + RST)
                else:
                    row.append(" ")
            out.append("".join(row))
        return out

    def compose(self, overlay, default_color):
        """overlay: {(row, col): (char, colour)} drawn on top of the braille."""
        out = []
        for cy in range(self.hc):
            row = []
            for cx in range(self.wc):
                o = overlay.get((cy, cx))
                if o:
                    row.append(o[1] + o[0] + RST)
                    continue
                v = self.grid[cy][cx]
                if v:
                    row.append(self.col.get((cy, cx), default_color) + chr(0x2800 + v) + RST)
                else:
                    row.append(" ")
            out.append("".join(row))
        return out
