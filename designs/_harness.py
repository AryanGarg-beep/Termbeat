#!/usr/bin/env python3
"""Shared scaffolding for the termbeat visualizer design sketches.

Each `designs/<name>.py` is a standalone preview of one idea from
`docs/visualizer-ideas.md`. Run one directly:

    python3 designs/waterfall.py

or flip through all of them:

    python3 designs/gallery.py

Every sketch renders full-screen against a *synthetic* audio model (no mpv, no
cava, no network) at ~24 FPS. Ctrl-C quits and restores the terminal.

A sketch supplies one function:

    draw(w, h, audio, t) -> list[str]      # h rows, each w visible cells

`audio` is a `FakeAudio`; `t` is seconds since start. Pure standard library.
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

try:
    import termios
    import tty
    HAS_TTY = True
except ImportError:                       # pragma: no cover - non-POSIX
    HAS_TTY = False

RST = "\033[0m"


def fg(r, g, b):
    return f"\033[38;2;{r};{g};{b}m"


def bg(r, g, b):
    return f"\033[48;2;{r};{g};{b}m"


# A small fixed palette so the sketches look like termbeat's "Classic Tuna".
DIM = fg(38, 115, 55)
MID = fg(90, 200, 110)
BRIGHT = fg(55, 255, 95)
ACCENT = fg(0, 220, 255)
WARN = fg(255, 210, 40)
HOT = fg(255, 120, 90)

BLOCKS = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
HBLOCKS = [" ", "▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]

_SGR = re.compile(r"\033\[[0-9;]*m")


def ansi_len(s: str) -> int:
    """Visible width, assuming every printable char is 1 cell (true for the
    ASCII / block / Braille glyphs these sketches use)."""
    return len(_SGR.sub("", s))


def fit(s: str, w: int, fill: str = " ") -> str:
    """Pad or trim `s` to exactly `w` visible cells (SGR-aware, never cuts an
    escape in half)."""
    out, vis = [], 0
    i, n = 0, len(s)
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


class FakeAudio:
    """Stand-in for termbeat's `update_physics` output.

    Exposes the same shape the real visualizers consume:
      bands[18]   ballistic 0..1     (fast attack, gravity fall)
      peaks[18]   floating peak-hold 0..1
      bass, mid, treble   0..1 band-slice energies
      beat        1.0 on a kick, decays to 0   (for beat-reactive sketches)
      level       overall RMS-ish 0..1
    """

    def __init__(self, n: int = 18):
        self.n = n
        self.bands = [0.0] * n
        self.peaks = [0.0] * n
        self.bass = self.mid = self.treble = 0.0
        self.beat = 0.0
        self.level = 0.0
        self._t = 0.0
        self._next_kick = 0.35
        self._kick_period = 0.46
        self._consts = [(1.0 + (i / n) * 2.6, i * 0.7, -i * 0.5) for i in range(n)]
        # spectral tilt: highs roll off like real music, so the top of a
        # spectrogram / EQ isn't a solid wall
        self._tilt = [(1.0 - (i / (n - 1)) * 0.62) ** 1.3 for i in range(n)]

    def step(self, dt: float):
        self._t += dt
        t = self._t
        # slow breathing envelope with occasional quiet passages
        env = math.sin(t * 0.13) * 0.5 + math.sin(t * 0.37 + 1.0) * 0.3 + 0.2
        song = max(0.05, 0.5 + 0.55 * env)
        kick = 0.0
        if t >= self._next_kick:
            self.beat = 1.0
            self._kick_period = random.uniform(0.34, 0.55)
            self._next_kick = t + self._kick_period
            kick = 1.0
        self.beat = max(0.0, self.beat - dt * 3.5)

        for i, (ff, p1, p2) in enumerate(self._consts):
            wobble = (math.sin(t * 3.2 * ff + p1) * 0.5
                      + math.cos(t * 2.1 * ff + p2) * 0.34
                      + random.uniform(-0.22, 0.30))
            bass_bias = max(0.0, (5 - i)) * 0.13
            target = self._tilt[i] * (0.12 + 0.88 * song) * (
                0.12 + wobble + bass_bias + kick * max(0.0, (6 - i)) * 0.16)
            target = max(0.0, min(1.0, target))
            b = self.bands[i]
            b += (target - b) * (0.6 if target >= b else 0.18)
            self.bands[i] = max(0.0, min(1.0, b))
            if self.bands[i] >= self.peaks[i]:
                self.peaks[i] = self.bands[i]
            else:
                self.peaks[i] = max(self.bands[i], self.peaks[i] - 0.018)

        self.bass = sum(self.bands[:5]) / 5.0
        self.mid = sum(self.bands[5:12]) / 7.0
        self.treble = sum(self.bands[12:]) / 6.0
        self.level = sum(self.bands) / self.n

    def sample(self, x: float) -> float:
        """A pseudo-waveform value in -1..1 for phase `x` (0..1 across the panel),
        for the oscilloscope-style sketches."""
        t = self._t
        return (
            math.sin(x * 8.6 + t * (2.6 + self.treble * 1.4)) * (0.9 + self.bass * 0.7)
            + math.cos(x * 18.0 - t * 1.8) * (0.5 + self.mid * 0.4)
            + math.sin(x * 38.0 + t * 3.5) * (0.2 + self.treble * 0.3)
        ) * 0.32 * (0.15 + self.level)


class Braille:
    """A 2x4-dots-per-cell canvas for the smooth curve / particle sketches.
    Mirrors the dot layout used by termbeat's `get_braille_wave_rows`."""

    _DOT = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))  # [y%4][x%2]

    def __init__(self, w_cells: int, h_cells: int):
        self.wc, self.hc = max(1, w_cells), max(1, h_cells)
        self.pw, self.ph = self.wc * 2, self.hc * 4
        self.grid = [[0] * self.wc for _ in range(self.hc)]

    def plot(self, x: float, y: float):
        xi, yi = int(x), int(y)
        if 0 <= xi < self.pw and 0 <= yi < self.ph:
            self.grid[yi >> 2][xi >> 1] |= Braille._DOT[yi & 3][xi & 1]

    def line(self, x0, y0, x1, y1):
        steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(steps + 1):
            f = i / steps
            self.plot(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f)

    def rows(self, color=BRIGHT, edge_color=None):
        top = self.hc - 1
        out = []
        for r, row in enumerate(self.grid):
            c = edge_color if (edge_color and r in (0, top)) else color
            out.append("".join(c + chr(0x2800 + v) + RST if v else " " for v in row))
        return out


# --------------------------------------------------------------------------- loop

def run(draw, *, fps: int = 24, title: str = "", audio: "FakeAudio | None" = None):
    """Render `draw` full-screen until Ctrl-C."""
    stop = {"v": False}
    for s in ("SIGINT", "SIGTERM", "SIGHUP"):
        sig = getattr(signal, s, None)
        if sig is not None:
            signal.signal(sig, lambda *_: stop.__setitem__("v", True))

    a = audio or FakeAudio()
    name = title or (draw.__doc__ or draw.__name__).strip().splitlines()[0]

    sys.stdout.write("\033[?1049h\033[?25l\033[2J")
    sys.stdout.flush()
    try:
        t0 = time.monotonic()
        last = t0
        while not stop["v"]:
            now = time.monotonic()
            a.step(min(now - last, 0.1))
            last = now
            cols, rows = shutil.get_terminal_size((100, 30))
            w, h = cols, max(1, rows - 1)
            body = draw(w, h, a, now - t0)
            head = fit(f"{ACCENT}{name}{RST}   {DIM}[Ctrl-C quits]{RST}", w)
            frame = ["\033[H" + head + "\033[K"]
            for r in range(h):
                line = body[r] if r < len(body) else ""
                frame.append(fit(line, w) + "\033[K")
            sys.stdout.write("\n".join(frame) + "\033[J")
            sys.stdout.flush()
            time.sleep(max(0.0, 1.0 / fps - (time.monotonic() - now)))
    finally:
        sys.stdout.write("\033[?25h\033[0m\033[?1049l")
        sys.stdout.flush()
        print("closed.")


class KeyReader:
    """Non-blocking single-key reader for gallery.py (cbreak + select)."""

    def __enter__(self):
        self.ok = HAS_TTY and sys.stdin.isatty()
        if self.ok:
            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        return self

    def __exit__(self, *_):
        if getattr(self, "ok", False):
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

    def get(self):
        if not getattr(self, "ok", False):
            return None
        if not select.select([self.fd], [], [], 0)[0]:
            return None
        b = os.read(self.fd, 8)
        if b in (b"\x1b[C", b"\x1bOC"):
            return "RIGHT"
        if b in (b"\x1b[D", b"\x1bOD"):
            return "LEFT"
        if b == b" ":
            return "SPACE"
        if b in (b"\r", b"\n"):
            return "ENTER"
        if b in (b"q", b"Q", b"\x03", b"\x1b"):
            return "QUIT"
        try:
            return b.decode("utf-8", "ignore")
        except Exception:
            return None
