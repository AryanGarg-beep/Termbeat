#!/usr/bin/env python3
"""
termbeat - 2x Scaled Retro Terminal Radio Player TUI
Features:
- Perfectly aligned 102-column layout (strictly measured 1-cell Unicode blocks)
- 18-band high-resolution Spectrum Equalizer across 7 vertical tiers
- Wide-screen laboratory Oscilloscope waveform
- Dual Stereo VU needle decibel meters (strictly 36 columns wide)
- Spacious full-sized transport buttons with text badges
- Wide 24-slot glowing volume slider using standard single-cell blocks
- Relaxed, chilled animation pacing (slowed-down marquee and audio dynamics)
- 5-Theme Color Engine (Toggle with [V] / [T])
- Full Station Directory Drawer (Toggle with [L])
- Analog FM Frequency Tuning Dial with momentary static FX
- Zero terminal overflow / zero border clipping guarantee
Zero external dependencies (pure Python standard library). No pip required.
"""

import atexit
import ctypes
import errno
import functools
import http.client
import itertools
import json
import logging
import math
import os
import random
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

try:
    import termios
    import tty
    HAS_TERMIOS = True
except ImportError:
    HAS_TERMIOS = False

IS_WINDOWS = os.name == "nt"
if IS_WINDOWS:
    import msvcrt


def _user_dir(xdg_var: str, posix_default: str, win_var: str) -> str:
    """Per-user base directory: $XDG_* if set, else %APPDATA%/%LOCALAPPDATA% on
    Windows, else the XDG default under $HOME."""
    base = os.environ.get(xdg_var)
    if not base and IS_WINDOWS:
        base = os.environ.get(win_var)
    return base or os.path.expanduser(posix_default)


def _init_logger():
    """Log to a file, never stdout - stdout is the UI. TERMBEAT_DEBUG=1 for
    DEBUG level. Failures are non-fatal: the app must run on a read-only home."""
    log = logging.getLogger("termbeat")
    log.setLevel(logging.DEBUG if os.environ.get("TERMBEAT_DEBUG") else logging.INFO)
    log.propagate = False
    try:
        state = _user_dir("XDG_STATE_HOME", "~/.local/state", "LOCALAPPDATA")
        d = os.path.join(state, "termbeat")
        os.makedirs(d, exist_ok=True)
        h = logging.FileHandler(os.path.join(d, "termbeat.log"), encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        log.addHandler(h)
    except Exception:
        log.addHandler(logging.NullHandler())
    return log


LOG = _init_logger()

# Resolved once, before any thread or fork exists, so the pre-exec hook below
# only calls an already-bound function pointer.
try:
    _LIBC = ctypes.CDLL("libc.so.6", use_errno=True)
except OSError:
    _LIBC = None

_PR_SET_PDEATHSIG = 1


def _die_with_parent():
    """pre-exec hook: ask the kernel to SIGTERM this child if we die.

    This is what stops mpv being orphaned - still streaming and still playing
    audio - when the terminal window is closed or we are killed outright.
    """
    if _LIBC is not None:
        try:
            _LIBC.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
        except Exception:
            pass


def _runtime_dir() -> str:
    """Per-user directory for the mpv IPC socket. $XDG_RUNTIME_DIR is mode 0700;
    the old /tmp/termbeat_mpv_<pid>.sock path was world-guessable."""
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base and os.path.isdir(base):
        d = os.path.join(base, "termbeat")
    elif IS_WINDOWS:
        # %LOCALAPPDATA% is already private to the user; there is no getuid
        d = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(),
                         "termbeat", "run")
    else:
        d = os.path.join(tempfile.gettempdir(), f"termbeat-{os.getuid()}")
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
    except OSError:
        return tempfile.gettempdir()
    return d


def ipc_path(pid: int) -> str:
    """mpv --input-ipc-server endpoint: a UNIX socket in the private runtime
    dir, or on Windows a named pipe (pipes live in their own namespace)."""
    if IS_WINDOWS:
        return rf"\\.\pipe\termbeat-mpv-{pid}"
    return os.path.join(_runtime_dir(), f"mpv-{pid}.sock")


def _child_popen_kwargs() -> dict:
    """Popen options that stop a child outliving us. POSIX uses the prctl
    pre-exec hook; Windows has no preexec_fn (Popen rejects it), so the child
    is put in a kill-on-close Job Object by _adopt_child instead."""
    if IS_WINDOWS:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {"preexec_fn": _die_with_parent}


_JOB = None


def _adopt_child(proc):
    """Windows: assign proc to a Job Object with KILL_ON_JOB_CLOSE. The job
    handle is held until we exit, at which point Windows closes it and kills
    every process in the job - the equivalent of PR_SET_PDEATHSIG."""
    global _JOB
    if not IS_WINDOWS or proc is None:
        return
    try:
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        if _JOB is None:
            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [(n, ctypes.c_ulonglong) for n in (
                    "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class BASIC_LIMIT(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                            ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD),
                            ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t),
                            ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t),
                            ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class EXTENDED_LIMIT(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", BASIC_LIMIT),
                            ("IoInfo", IO_COUNTERS),
                            ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]

            job = k32.CreateJobObjectW(None, None)
            if not job:
                raise ctypes.WinError(ctypes.get_last_error())
            info = EXTENDED_LIMIT()
            info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(job, 9, ctypes.byref(info),  # Extended
                                               ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            _JOB = job
        if not k32.AssignProcessToJobObject(_JOB, int(proc._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
    except Exception as exc:
        LOG.warning("could not tie pid %s to our lifetime: %s", proc.pid, exc)


class _PipeConn:
    """Windows named-pipe client with the socket subset StreamPlayer uses
    (recv, sendall, close).

    The handle is opened overlapped. A plain synchronous handle serialises all
    I/O on it, so the reader thread's blocking read would stall every command
    the main thread tries to send.
    """

    def __init__(self, path: str):
        import _winapi
        self._w = _winapi
        self._handle = _winapi.CreateFile(
            path, _winapi.GENERIC_READ | _winapi.GENERIC_WRITE, 0, _winapi.NULL,
            _winapi.OPEN_EXISTING, _winapi.FILE_FLAG_OVERLAPPED, _winapi.NULL)
        self._reading = None

    def _wait(self, ov, err):
        if err == self._w.ERROR_IO_PENDING:
            err = ov.GetOverlappedResult(True)[1]
        if err not in (0, 234):                         # 234 = ERROR_MORE_DATA
            raise OSError(None, "pipe I/O failed", None, err)

    def recv(self, size: int) -> bytes:
        if self._handle is None:
            raise OSError("pipe closed")
        try:
            ov, err = self._w.ReadFile(self._handle, size, overlapped=True)
            self._reading = ov
            self._wait(ov, err)
        except BrokenPipeError:
            return b""
        finally:
            self._reading = None
        return bytes(ov.getbuffer())

    def sendall(self, data: bytes):
        if self._handle is None:
            raise OSError("pipe closed")
        view = memoryview(data)
        while view:
            ov, err = self._w.WriteFile(self._handle, view, overlapped=True)
            self._wait(ov, err)
            view = view[ov.GetOverlappedResult(True)[0]:]

    def close(self):
        handle, self._handle = self._handle, None
        if handle is None:
            return
        ov = self._reading
        if ov is not None:
            try:
                ov.cancel()                 # wakes the reader with an OSError
            except OSError:
                pass
        self._w.CloseHandle(handle)

# Curated Premier Stations (100% Commercial-Free, Independent & High-Fidelity)
DEFAULT_PLAYLIST = [
    {
        "id": "groovesalad",
        "station": "Groove Salad",
        "freq": "88.5",
        "url": "https://ice1.somafm.com/groovesalad-128-mp3",
        "bitrate": "128kbps",
        "genre": "CHILL",
        "signal": "99%",
        "track": "Ambient Beats & Chilled Grooves [SomaFM]",
        "provider": "somafm",
    },
    {
        "id": "dronezone",
        "station": "Drone Zone",
        "freq": "91.3",
        "url": "https://ice1.somafm.com/dronezone-128-mp3",
        "bitrate": "128kbps",
        "genre": "SPACE",
        "signal": "96%",
        "track": "Atmospheric Ambient Space Music [SomaFM]",
        "provider": "somafm",
    },
    {
        "id": "deepspaceone",
        "station": "Deep Space One",
        "freq": "92.8",
        "url": "https://ice1.somafm.com/deepspaceone-128-mp3",
        "bitrate": "128kbps",
        "genre": "COSMIC",
        "signal": "95%",
        "track": "Deep Space Ambient & Interstellar Soundscapes [SomaFM]",
        "provider": "somafm",
    },
    {
        "id": "missioncontrol",
        "station": "Mission Control",
        "freq": "94.2",
        "url": "https://ice1.somafm.com/missioncontrol-128-mp3",
        "bitrate": "128kbps",
        "genre": "NASA",
        "signal": "97%",
        "track": "Ambient Music Mixed with Live NASA Comms [SomaFM]",
        "provider": "somafm",
    },
    {
        "id": "plaza",
        "station": "Nightwave Plaza",
        "freq": "96.0",
        "url": "https://radio.plaza.one/mp3",
        "bitrate": "128kbps",
        "genre": "VAPOR",
        "signal": "98%",
        "track": "24/7 Aesthetic Vaporwave & Future Funk [Plaza.one]",
        "provider": "plaza",
    },
    {
        "id": "vaporwaves",
        "station": "Vaporwaves",
        "freq": "97.5",
        "url": "https://ice1.somafm.com/vaporwaves-128-mp3",
        "bitrate": "128kbps",
        "genre": "SYNTH",
        "signal": "95%",
        "track": "Aesthetic Retro Synthesizer Vibes [SomaFM]",
        "provider": "somafm",
    },
    {
        "id": "defcon",
        "station": "Def Con Radio",
        "freq": "98.9",
        "url": "https://ice1.somafm.com/defcon-128-mp3",
        "bitrate": "128kbps",
        "genre": "HACK",
        "signal": "98%",
        "track": "Music for Hackers and Coders [SomaFM]",
        "provider": "somafm",
    },
    {
        "id": "cliqhop",
        "station": "cliqhop idm",
        "freq": "100.2",
        "url": "https://ice1.somafm.com/cliqhop-128-mp3",
        "bitrate": "128kbps",
        "genre": "IDM",
        "signal": "94%",
        "track": "Intelligent Dance Music & Glitch Beats [SomaFM]",
        "provider": "somafm",
    },
    {
        "id": "u80s",
        "station": "Underground 80s",
        "freq": "101.7",
        "url": "https://ice1.somafm.com/u80s-128-mp3",
        "bitrate": "128kbps",
        "genre": "NEWWAV",
        "signal": "95%",
        "track": "Early 80s UK Synthpop & New Wave [SomaFM]",
        "provider": "somafm",
    },
    {
        "id": "reyfm_lofi",
        "station": "REYFM Lo-Fi",
        "freq": "102.8",
        "url": "https://listen.reyfm.de/lofi_320kbps.mp3",
        "bitrate": "320kbps",
        "genre": "LOFI",
        "signal": "99%",
        "track": "24/7 Instrumental Lo-Fi & Chill Beats [REYFM]",
        "provider": "generic",
    },
    {
        "id": "suburbsofgoa",
        "station": "Suburbs of Goa",
        "freq": "103.9",
        "url": "https://ice1.somafm.com/suburbsofgoa-128-mp3",
        "bitrate": "128kbps",
        "genre": "WORLD",
        "signal": "93%",
        "track": "Desi Asian World Beats & Sitar Chill [SomaFM]",
        "provider": "somafm",
    },
    {
        "id": "beatblender",
        "station": "Beat Blender",
        "freq": "104.8",
        "url": "https://ice1.somafm.com/beatblender-128-mp3",
        "bitrate": "128kbps",
        "genre": "HOUSE",
        "signal": "92%",
        "track": "Deep House & Downtempo Grooves [SomaFM]",
        "provider": "somafm",
    },
    {
        "id": "radioparadise_main",
        "station": "Radio Paradise",
        "freq": "105.7",
        "url": "https://stream.radioparadise.com/mp3-128",
        "bitrate": "128kbps",
        "genre": "ECLTC",
        "signal": "99%",
        "track": "Eclectic Modern & Classic Rock, Electronica, World",
        "provider": "radioparadise",
    },
    {
        "id": "radioparadise_mellow",
        "station": "RP Mellow Mix",
        "freq": "106.4",
        "url": "https://stream.radioparadise.com/mellow-128",
        "bitrate": "128kbps",
        "genre": "MELLOW",
        "signal": "98%",
        "track": "Mellow Acoustic, Downtempo & Ambient Blend",
        "provider": "radioparadise",
    },
    {
        "id": "kexp",
        "station": "KEXP 90.3 Seattle",
        "freq": "90.3",
        "url": "https://kexp.streamguys1.com/kexp160.aac",
        "bitrate": "160kbps",
        "genre": "INDIE",
        "signal": "97%",
        "track": "Where the Music Matters [KEXP 90.3 FM]",
        "provider": "kexp",
    },
    {
        "id": "secretagent",
        "station": "Secret Agent",
        "freq": "107.9",
        "url": "https://ice1.somafm.com/secretagent-128-mp3",
        "bitrate": "128kbps",
        "genre": "SPY",
        "signal": "94%",
        "track": "The Soundtrack for Your Spy Life [SomaFM]",
        "provider": "somafm",
    },
]


CONFIG_DIR = os.path.join(_user_dir("XDG_CONFIG_HOME", "~/.config", "APPDATA"), "termbeat")
CONFIG_FILE = os.path.join(CONFIG_DIR, "stations.json")

# Every key the renderers index directly. Anything missing is filled in here so
# a hand-edited stations.json cannot raise KeyError in the middle of a frame.
STATION_DEFAULTS = {
    "id": "", "station": "Unknown Station", "freq": "00.0", "url": "",
    "bitrate": "128kbps", "genre": "RADIO", "signal": "95%",
    "track": "No track information", "provider": "generic",
}

_TEXT_KEYS = ("id", "station", "freq", "bitrate", "genre", "signal", "track", "provider")

# The [A] add-station form: its fields in order, and the providers the last one
# cycles through. "auto" leaves provider out and lets provider_of infer it.
EDITOR_FIELDS = ("name", "url", "freq", "genre", "bitrate", "provider")
EDITOR_PROVIDERS = ("auto", "somafm", "plaza", "radioparadise", "kexp", "generic")


def normalize_station(raw):
    """Validate and complete one station entry; None if unusable.

    The url goes straight to mpv, so only http(s) is accepted - a config file
    should not be able to make the player open arbitrary local paths.
    """
    if not isinstance(raw, dict):
        LOG.warning("ignoring station entry that is not an object: %r", raw)
        return None
    url = str(raw.get("url", "")).strip()
    if urllib.parse.urlsplit(url).scheme.lower() not in ("http", "https"):
        LOG.warning("ignoring station %r: unsupported url %r", raw.get("station", "?"), url[:80])
        return None
    item = dict(STATION_DEFAULTS)
    for key, value in raw.items():
        if value is not None:
            item[key] = value
    item["url"] = url
    for key in _TEXT_KEYS:
        item[key] = str(item[key])
    return item


def normalize_playlist(raw_list) -> list:
    if not isinstance(raw_list, list):
        return []
    return [i for i in (normalize_station(e) for e in raw_list) if i is not None]


def load_stations_config() -> list:
    """Load stations from the config file, writing defaults on first run."""
    try:
        if not os.path.exists(CONFIG_FILE):
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_PLAYLIST, f, indent=2)
            LOG.info("wrote default station list to %s", CONFIG_FILE)
            return normalize_playlist(DEFAULT_PLAYLIST)
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            stations = normalize_playlist(json.load(f))
        if stations:
            LOG.info("loaded %d stations from %s", len(stations), CONFIG_FILE)
            return stations
        LOG.warning("%s produced no usable stations; using defaults", CONFIG_FILE)
    except Exception as exc:
        LOG.warning("could not read %s (%s); using defaults", CONFIG_FILE, exc)
    return normalize_playlist(DEFAULT_PLAYLIST)


PLAYLIST = load_stations_config()

THEMES = [
    {
        "name": "Classic Tuna",
        "frame": (70, 95, 145),
        "title_bg": (24, 42, 82),
        "title_fg": (255, 255, 255),
        "deck_bg": (18, 26, 48),
        "lcd_bg": (6, 20, 12),
        "lcd_border": (32, 75, 48),
        "lcd_dim": (38, 115, 55),
        "lcd_bright": (55, 255, 95),
        "accent": (0, 220, 255),
        "warn": (255, 210, 40),
    },
    {
        "name": "Cyberpunk",
        "frame": (170, 45, 140),
        "title_bg": (46, 16, 68),
        "title_fg": (255, 255, 255),
        "deck_bg": (28, 14, 42),
        "lcd_bg": (16, 6, 26),
        "lcd_border": (110, 32, 95),
        "lcd_dim": (120, 45, 105),
        "lcd_bright": (0, 240, 255),
        "accent": (255, 25, 140),
        "warn": (255, 220, 40),
    },
    {
        "name": "Amber CRT",
        "frame": (155, 105, 35),
        "title_bg": (48, 32, 10),
        "title_fg": (255, 240, 200),
        "deck_bg": (32, 20, 8),
        "lcd_bg": (20, 12, 4),
        "lcd_border": (95, 62, 20),
        "lcd_dim": (140, 90, 25),
        "lcd_bright": (255, 185, 30),
        "accent": (255, 215, 50),
        "warn": (255, 110, 30),
    },
    {
        "name": "Matrix",
        "frame": (30, 115, 50),
        "title_bg": (8, 38, 16),
        "title_fg": (220, 255, 230),
        "deck_bg": (10, 25, 12),
        "lcd_bg": (4, 16, 6),
        "lcd_border": (22, 85, 38),
        "lcd_dim": (35, 120, 50),
        "lcd_bright": (50, 255, 85),
        "accent": (110, 255, 145),
        "warn": (240, 230, 40),
    },
    {
        "name": "Synthwave",
        "frame": (115, 60, 165),
        "title_bg": (40, 18, 68),
        "title_fg": (255, 230, 255),
        "deck_bg": (25, 12, 42),
        "lcd_bg": (18, 8, 30),
        "lcd_border": (98, 42, 125),
        "lcd_dim": (145, 60, 120),
        "lcd_bright": (255, 95, 185),
        "accent": (255, 165, 45),
        "warn": (255, 220, 50),
    },
    {
        "name": "Blue Hour",
        "frame": (44, 84, 99),
        "title_bg": (0, 46, 58),
        "title_fg": (232, 240, 248),
        "deck_bg": (13, 28, 33),
        "lcd_bg": (0, 16, 21),
        "lcd_border": (32, 66, 78),
        "lcd_dim": (58, 107, 125),
        "lcd_bright": (255, 236, 24),
        "accent": (0, 205, 255),
        "warn": (255, 125, 172),
    },
    {
        "name": "Ultraviolet",
        "frame": (98, 72, 98),
        "title_bg": (52, 29, 59),
        "title_fg": (232, 240, 248),
        "deck_bg": (30, 19, 34),
        "lcd_bg": (18, 7, 22),
        "lcd_border": (76, 54, 78),
        "lcd_dim": (124, 93, 123),
        "lcd_bright": (255, 187, 21),
        "accent": (231, 146, 255),
        "warn": (0, 225, 240),
    },
    {
        "name": "Ember",
        "frame": (92, 74, 44),
        "title_bg": (58, 33, 0),
        "title_fg": (232, 240, 248),
        "deck_bg": (33, 21, 13),
        "lcd_bg": (21, 9, 0),
        "lcd_border": (73, 57, 32),
        "lcd_dim": (116, 96, 58),
        "lcd_bright": (0, 255, 255),
        "accent": (255, 162, 0),
        "warn": (252, 139, 255),
    },
    {
        "name": "Deep Field",
        "frame": (62, 77, 107),
        "title_bg": (17, 40, 63),
        "title_fg": (232, 240, 248),
        "deck_bg": (16, 24, 38),
        "lcd_bg": (3, 12, 27),
        "lcd_border": (46, 60, 86),
        "lcd_dim": (82, 99, 134),
        "lcd_bright": (194, 226, 47),
        "accent": (93, 186, 255),
        "warn": (255, 127, 135),
    },
]


def fg(r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m"

def bg(r: int, g: int, b: int) -> str:
    return f"\033[48;2;{r};{g};{b}m"

RST = "\033[0m"

# Fixed colours that never vary with the theme, built once rather than rebuilt
# on every frame. Per-theme escapes are precomputed into THEMES as _c_* below;
# the renderers used to rebuild all of them every single frame.
C_DIM_CYAN = fg(35, 65, 80)
C_HINT_TEXT = fg(175, 200, 235)
C_VOL_LABEL = fg(180, 215, 250)
C_BTN_IDLE = fg(160, 195, 240)
C_ERROR = fg(255, 105, 105)
C_MUTED = fg(255, 120, 120)

# Cyberpunk deliberately ignores the active theme and uses a fixed neon palette.
CYBER_CYAN = fg(0, 240, 255)
CYBER_MAGENTA = fg(255, 0, 128)
CYBER_BRIGHT = fg(255, 255, 255)
CYBER_DIM = fg(80, 70, 110)
CYBER_AMBER = fg(255, 180, 0)

# Pre-compile theme palette ANSI escape sequences for zero-overhead access
for _t in THEMES:
    _t["_c_frame"] = fg(*_t["frame"])
    _t["_c_accent"] = fg(*_t["accent"])
    _t["_c_bright"] = fg(*_t["lcd_bright"])
    _t["_c_dim"] = fg(*_t["lcd_dim"])
    _t["_c_warn"] = fg(*_t["warn"])
    _t["_c_title_fg"] = fg(*_t["title_fg"])
    _t["_c_title_bg"] = bg(*_t["title_bg"])
    _t["_c_lcd_border"] = fg(*_t["lcd_border"])
    _t["_c_lcd_bg"] = bg(*_t["lcd_bg"])
    _t["_c_deck_bg"] = bg(*_t["deck_bg"])

# Frame pacing. The loop used to sleep a flat 0.045 s whatever was happening, so
# a paused deck repainted 22 times a second and pushed an unchanged 563 KB/s at
# 101x54 while only 0.2% of rows differed.
ACTIVE_FRAME_TIME = 0.045          # ~22 FPS while audio is flowing
IDLE_FRAME_TIME = 0.20             # ~5 FPS when paused, stopped or erroring
MARQUEE_CHARS_PER_SEC = 5.5        # matches the old frame//4 rate at 22 FPS
TIMER_BLINK_PERIOD = 1.1

# Guaranteed single-cell block characters
BLOCKS = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
STATIC_CHARS = "░▒▓#%*~+-=<>[]/\\$"

# 5x7 bitmap type for the TIDE design: seven pipe-delimited rows of five pixels,
# '#' lit. The period is there because "KEXP 90.3 Seattle" needs it.
FONT_5X7 = {
    "A": ".###.|#...#|#...#|#####|#...#|#...#|#...#",
    "B": "####.|#...#|#...#|####.|#...#|#...#|####.",
    "C": ".###.|#...#|#....|#....|#....|#...#|.###.",
    "D": "####.|#...#|#...#|#...#|#...#|#...#|####.",
    "E": "#####|#....|#....|####.|#....|#....|#####",
    "F": "#####|#....|#....|####.|#....|#....|#....",
    "G": ".###.|#...#|#....|#.###|#...#|#...#|.####",
    "H": "#...#|#...#|#...#|#####|#...#|#...#|#...#",
    "I": ".###.|..#..|..#..|..#..|..#..|..#..|.###.",
    "J": "..###|...#.|...#.|...#.|...#.|#..#.|.##..",
    "K": "#...#|#..#.|#.#..|##...|#.#..|#..#.|#...#",
    "L": "#....|#....|#....|#....|#....|#....|#####",
    "M": "#...#|##.##|#.#.#|#.#.#|#...#|#...#|#...#",
    "N": "#...#|#...#|##..#|#.#.#|#..##|#...#|#...#",
    "O": ".###.|#...#|#...#|#...#|#...#|#...#|.###.",
    "P": "####.|#...#|#...#|####.|#....|#....|#....",
    "Q": ".###.|#...#|#...#|#...#|#.#.#|#..#.|.##.#",
    "R": "####.|#...#|#...#|####.|#.#..|#..#.|#...#",
    "S": ".####|#....|#....|.###.|....#|....#|####.",
    "T": "#####|..#..|..#..|..#..|..#..|..#..|..#..",
    "U": "#...#|#...#|#...#|#...#|#...#|#...#|.###.",
    "V": "#...#|#...#|#...#|#...#|#...#|.#.#.|..#..",
    "W": "#...#|#...#|#...#|#.#.#|#.#.#|#.#.#|.#.#.",
    "X": "#...#|#...#|.#.#.|..#..|.#.#.|#...#|#...#",
    "Y": "#...#|#...#|.#.#.|..#..|..#..|..#..|..#..",
    "Z": "#####|....#|...#.|..#..|.#...|#....|#####",
    "0": ".###.|#...#|#..##|#.#.#|##..#|#...#|.###.",
    "1": "..#..|.##..|..#..|..#..|..#..|..#..|.###.",
    "2": ".###.|#...#|....#|...#.|..#..|.#...|#####",
    "3": "####.|....#|....#|.###.|....#|....#|####.",
    "4": "...#.|..##.|.#.#.|#..#.|#####|...#.|...#.",
    "5": "#####|#....|####.|....#|....#|#...#|.###.",
    "6": "..##.|.#...|#....|####.|#...#|#...#|.###.",
    "7": "#####|....#|...#.|..#..|.#...|.#...|.#...",
    "8": ".###.|#...#|#...#|.###.|#...#|#...#|.###.",
    "9": ".###.|#...#|#...#|.####|....#|...#.|.##..",
    " ": ".....|.....|.....|.....|.....|.....|.....",
    "-": ".....|.....|.....|#####|.....|.....|.....",
    "'": "..#..|..#..|.#...|.....|.....|.....|.....",
    ".": ".....|.....|.....|.....|.....|.##..|.##..",
}
# The lit (x, y) cells of each glyph, parsed once so drawing never re-splits.
_FONT_BITS = {
    ch: tuple((sx, sy) for sy, row in enumerate(g.split("|"))
              for sx, c in enumerate(row) if c == "#")
    for ch, g in FONT_5X7.items()
}
# How far TIDE stretches each letter away from the spectrum's mean level. Real
# cava bands move together, so a mild stretch keeps neighbouring letters apart;
# much more than this clips the quiet ends dark and pegs the loud middle full.
TIDE_EXPAND = 1.25

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


# Every codepoint whose display width is not exactly 1 cell: East Asian Wide and
# Fullwidth (2 cells), plus combining marks, zero-width characters and variation
# selectors (0 cells). Generated from unicodedata by classifying every codepoint
# in range(0x110000). Deliberately excludes the ambiguous-width box-drawing and
# block glyphs the UI is built from, so the fast path below stays hot.
_NONTRIVIAL_WIDTH_RE = re.compile("[" + "\u1100-\u115f\u231a-\u231b\u2329-\u232a\u23e9-\u23ec\u23f0\u23f3\u25fd-\u25fe\u2614-\u2615\u2630-\u2637\u2648-\u2653\u267f\u268a-\u268f\u2693\u26a1\u26aa-\u26ab\u26bd-\u26be\u26c4-\u26c5\u26ce\u26d4\u26ea\u26f2-\u26f3\u26f5\u26fa\u26fd\u2705\u270a-\u270b\u2728\u274c\u274e\u2753-\u2755\u2757\u2795-\u2797\u27b0\u27bf\u2b1b-\u2b1c\u2b50\u2b55\u2e80-\u2e99\u2e9b-\u2ef3\u2f00-\u2fd5\u2ff0-\u3029\u3030-\u303e\u3041-\u3096\u309b-\u30ff\u3105-\u312f\u3131-\u318e\u3190-\u31e5\u31ef-\u321e\u3220-\u3247\u3250-\ua48c\ua490-\ua4c6\ua960-\ua97c\uac00-\ud7a3\uf900-\ufaff\ufe10-\ufe19\ufe30-\ufe52\ufe54-\ufe66\ufe68-\ufe6b\uff01-\uff60\uffe0-\uffe6\U00016fe0-\U00016fe4\U00017000-\U000187f7\U00018800-\U00018cd5\U00018cff-\U00018d08\U0001aff0-\U0001aff3\U0001aff5-\U0001affb\U0001affd-\U0001affe\U0001b000-\U0001b122\U0001b132\U0001b150-\U0001b152\U0001b155\U0001b164-\U0001b167\U0001b170-\U0001b2fb\U0001d300-\U0001d356\U0001d360-\U0001d376\U0001f004\U0001f0cf\U0001f18e\U0001f191-\U0001f19a\U0001f200-\U0001f202\U0001f210-\U0001f23b\U0001f240-\U0001f248\U0001f250-\U0001f251\U0001f260-\U0001f265\U0001f300-\U0001f320\U0001f32d-\U0001f335\U0001f337-\U0001f37c\U0001f37e-\U0001f393\U0001f3a0-\U0001f3ca\U0001f3cf-\U0001f3d3\U0001f3e0-\U0001f3f0\U0001f3f4\U0001f3f8-\U0001f43e\U0001f440\U0001f442-\U0001f4fc\U0001f4ff-\U0001f53d\U0001f54b-\U0001f54e\U0001f550-\U0001f567\U0001f57a\U0001f595-\U0001f596\U0001f5a4\U0001f5fb-\U0001f64f\U0001f680-\U0001f6c5\U0001f6cc\U0001f6d0-\U0001f6d2\U0001f6d5-\U0001f6d7\U0001f6dc-\U0001f6df\U0001f6eb-\U0001f6ec\U0001f6f4-\U0001f6fc\U0001f7e0-\U0001f7eb\U0001f7f0\U0001f90c-\U0001f93a\U0001f93c-\U0001f945\U0001f947-\U0001f9ff\U0001fa70-\U0001fa7c\U0001fa80-\U0001fa89\U0001fa8f-\U0001fac6\U0001face-\U0001fadc\U0001fadf-\U0001fae9\U0001faf0-\U0001faf8\U00020000-\U0002fffd\U00030000-\U0003fffd\u0300-\u034e\u0350-\u036f\u0483-\u0487\u0591-\u05bd\u05bf\u05c1-\u05c2\u05c4-\u05c5\u05c7\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06dc\u06df-\u06e4\u06e7-\u06e8\u06ea-\u06ed\u0711\u0730-\u074a\u07eb-\u07f3\u07fd\u0816-\u0819\u081b-\u0823\u0825-\u0827\u0829-\u082d\u0859-\u085b\u0897-\u089f\u08ca-\u08e1\u08e3-\u08ff\u093c\u094d\u0951-\u0954\u09bc\u09cd\u09fe\u0a3c\u0a4d\u0abc\u0acd\u0b3c\u0b4d\u0bcd\u0c3c\u0c4d\u0c55-\u0c56\u0cbc\u0ccd\u0d3b-\u0d3c\u0d4d\u0dca\u0e38-\u0e3a\u0e48-\u0e4b\u0eb8-\u0eba\u0ec8-\u0ecb\u0f18-\u0f19\u0f35\u0f37\u0f39\u0f71-\u0f72\u0f74\u0f7a-\u0f7d\u0f80\u0f82-\u0f84\u0f86-\u0f87\u0fc6\u1037\u1039-\u103a\u108d\u135d-\u135f\u1714-\u1715\u1734\u17d2\u17dd\u18a9\u1939-\u193b\u1a17-\u1a18\u1a60\u1a75-\u1a7c\u1a7f\u1ab0-\u1abd\u1abf-\u1ace\u1b34\u1b44\u1b6b-\u1b73\u1baa-\u1bab\u1be6\u1bf2-\u1bf3\u1c37\u1cd0-\u1cd2\u1cd4-\u1ce0\u1ce2-\u1ce8\u1ced\u1cf4\u1cf8-\u1cf9\u1dc0-\u1dff\u200b-\u200f\u20d0-\u20dc\u20e1\u20e5-\u20f0\u2cef-\u2cf1\u2d7f\u2de0-\u2dff\u302a-\u302f\u3099-\u309a\ua66f\ua674-\ua67d\ua69e-\ua69f\ua6f0-\ua6f1\ua806\ua82c\ua8c4\ua8e0-\ua8f1\ua92b-\ua92d\ua953\ua9b3\ua9c0\uaab0\uaab2-\uaab4\uaab7-\uaab8\uaabe-\uaabf\uaac1\uaaf6\uabed\ufb1e\ufe00-\ufe0f\ufe20-\ufe2f\U000101fd\U000102e0\U00010376-\U0001037a\U00010a0d\U00010a0f\U00010a38-\U00010a3a\U00010a3f\U00010ae5-\U00010ae6\U00010d24-\U00010d27\U00010d69-\U00010d6d\U00010eab-\U00010eac\U00010efd-\U00010eff\U00010f46-\U00010f50\U00010f82-\U00010f85\U00011046\U00011070\U0001107f\U000110b9-\U000110ba\U00011100-\U00011102\U00011133-\U00011134\U00011173\U000111c0\U000111ca\U00011235-\U00011236\U000112e9-\U000112ea\U0001133b-\U0001133c\U0001134d\U00011366-\U0001136c\U00011370-\U00011374\U000113ce-\U000113d0\U00011442\U00011446\U0001145e\U000114c2-\U000114c3\U000115bf-\U000115c0\U0001163f\U000116b6-\U000116b7\U0001172b\U00011839-\U0001183a\U0001193d-\U0001193e\U00011943\U000119e0\U00011a34\U00011a47\U00011a99\U00011c3f\U00011d42\U00011d44-\U00011d45\U00011d97\U00011f41-\U00011f42\U0001612f\U00016af0-\U00016af4\U00016b30-\U00016b36\U00016ff0-\U00016ff1\U0001bc9e\U0001d165-\U0001d169\U0001d16d-\U0001d172\U0001d17b-\U0001d182\U0001d185-\U0001d18b\U0001d1aa-\U0001d1ad\U0001d242-\U0001d244\U0001e000-\U0001e006\U0001e008-\U0001e018\U0001e01b-\U0001e021\U0001e023-\U0001e024\U0001e026-\U0001e02a\U0001e08f\U0001e130-\U0001e136\U0001e2ae\U0001e2ec-\U0001e2ef\U0001e4ec-\U0001e4ef\U0001e5ee-\U0001e5ef\U0001e8d0-\U0001e8d6\U0001e944-\U0001e94a" + "]")

# Terminals in CJK locales often render ambiguous-width glyphs (the box-drawing
# and block characters this UI is made of) as 2 cells, which shears the chassis.
# Users on such a setup can export TERMBEAT_AMBIGUOUS_WIDTH=2.
AMBIGUOUS_IS_WIDE = os.environ.get("TERMBEAT_AMBIGUOUS_WIDTH", "1").strip() == "2"

_CHAR_WIDTH_CACHE = {}


def char_width(c: str) -> int:
    """Display width of one character, in cells (0, 1 or 2)."""
    w = _CHAR_WIDTH_CACHE.get(c)
    if w is None:
        if unicodedata.combining(c) or "\u200b" <= c <= "\u200f" or "\ufe00" <= c <= "\ufe0f":
            w = 0
        else:
            eaw = unicodedata.east_asian_width(c)
            w = 2 if (eaw in ("W", "F") or (eaw == "A" and AMBIGUOUS_IS_WIDE)) else 1
        _CHAR_WIDTH_CACHE[c] = w
    return w


@functools.lru_cache(maxsize=128)
def _measure(clean: str) -> int:
    """Width of an escape-free string.

    This used to be 55% of all render time, doing 4.8 million ord() calls per
    1500 frames. Two changes fix that: one C-level regex decides whether the
    string contains anything that is not exactly one cell wide (it almost never
    does), and a small cache absorbs the border and label rows that repeat every
    frame. 128 entries measured better than 8192 - a bigger cache just churns on
    the visualizer rows, which never repeat.
    """
    if not AMBIGUOUS_IS_WIDE and not _NONTRIVIAL_WIDTH_RE.search(clean):
        return len(clean)
    return sum(char_width(c) for c in clean)


def str_width(s: str) -> int:
    """Exact terminal display width, ignoring ANSI escapes and honouring wide
    and zero-width characters."""
    if "\x1b" in s:
        s = ANSI_ESCAPE_RE.sub("", s)
    if s.isascii():
        return len(s)
    return _measure(s)


@functools.lru_cache(maxsize=128)
def cell_slots(text: str) -> tuple:
    """Split a string into one entry per terminal cell.

    A wide glyph contributes itself plus an empty continuation slot, so indexing
    the result is indexing by screen cell. Combining marks fold into the cell
    they modify.
    """
    slots = []
    for ch in text:
        w = char_width(ch)
        if w == 0:
            for i in range(len(slots) - 1, -1, -1):
                if slots[i]:
                    slots[i] += ch
                    break
            continue
        slots.append(ch)
        if w == 2:
            slots.append("")
    return tuple(slots)


def truncate_ansi(s: str, max_width: int, return_width: bool = False):
    """Truncate an ANSI-formatted string so visible cells never exceed
    max_width. Escape sequences are copied whole and never cut in half."""
    result = []
    w = 0
    in_esc = False
    for ch in s:
        if ch == "\033":
            in_esc = True
            result.append(ch)
        elif in_esc:
            result.append(ch)
            if ch.isalpha():
                in_esc = False
        else:
            cw = 1 if ch.isascii() else char_width(ch)
            if w + cw > max_width:
                break
            result.append(ch)
            w += cw
    out = "".join(result) + RST
    if return_width:
        return out, w
    return out


def fit_row(content: str, target_width: int, bg_color: str = "", fill_char: str = " ") -> str:
    """Ensure row visible width is EXACTLY target_width (truncate if long, pad if short)."""
    vis_w = str_width(content)
    if vis_w > target_width:
        content, vis_w = truncate_ansi(content, target_width, return_width=True)
    if vis_w < target_width:
        return f"{content}{bg_color}{fill_char * (target_width - vis_w)}{RST}"
    return content


# --- TIDE type raster --------------------------------------------------------
# A half-pixel canvas: one cell is 1 px wide and 2 px tall, painted as U+2580
# with the top pixel as foreground and the bottom pixel as background.

HALF_BLOCK = "▀"

# SGR strings keyed by RGB. A TIDE frame only uses one gradient sample per pixel
# row plus a few fixed roles, and each gradient is a line between two theme
# colours, so these stay a few hundred entries however long the session runs.
_FG_SGR = {}
_BG_SGR = {}


def _lerp3(a: tuple, b: tuple, t: float) -> tuple:
    return (int(a[0] + (b[0] - a[0]) * t + 0.5),
            int(a[1] + (b[1] - a[1]) * t + 0.5),
            int(a[2] + (b[2] - a[2]) * t + 0.5))


class Pix:
    """Half-pixel raster buffer of RGB tuples, pre-filled with the ground."""
    __slots__ = ("w", "h", "buf")

    def __init__(self, w: int, h: int, ground: tuple):
        self.w = w
        self.h = h + (h & 1)                 # whole cells only
        self.buf = [ground] * (w * self.h)

    def set(self, x: int, y: int, rgb: tuple):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.buf[y * self.w + x] = rgb

    def to_rows(self) -> list:
        """One string per pair of pixel rows, exactly w cells each.

        Runs of cells with the same (fg, bg) share one escape, and only the half
        that changed is re-sent, so a flat stretch of ground or flood costs one
        sequence rather than one per cell.
        """
        w, buf = self.w, self.buf
        fg_c, bg_c = _FG_SGR, _BG_SGR
        rows = []
        for top in range(0, len(buf), 2 * w):
            parts = []
            cur_f = cur_b = None
            for (f, b), run in itertools.groupby(zip(buf[top:top + w], buf[top + w:top + 2 * w])):
                if f != cur_f:
                    s = fg_c.get(f)
                    if s is None:
                        s = fg_c[f] = fg(*f)
                    parts.append(s)
                    cur_f = f
                if b != cur_b:
                    s = bg_c.get(b)
                    if s is None:
                        s = bg_c[b] = bg(*b)
                    parts.append(s)
                    cur_b = b
                parts.append(HALF_BLOCK * len(list(run)))
            parts.append(RST)
            rows.append("".join(parts))
        return rows


def draw_word(pix: Pix, x: int, y: int, text: str, scale: int, gap: int, colour_fn) -> int:
    """Stamp text into pix in FONT_5X7 with its top-left at (x, y).

    Each font pixel becomes a scale x scale block, with gap px between glyphs.
    colour_fn(px, py, letter_index) colours every lit pixel (None leaves the
    ground); letter_index counts the non-space glyphs of text from 0. Glyphs
    that would fall outside pix are skipped. Returns the number of letters.
    """
    buf, w, h = pix.buf, pix.w, pix.h
    gh = 7 * scale
    li = 0
    for ch in text:
        bits = _FONT_BITS.get(ch)
        if ch != " " and bits is not None:
            if 0 <= x and x + 5 * scale <= w and 0 <= y and y + gh <= h:
                for sx, sy in bits:
                    x0 = x + sx * scale
                    for py in range(y + sy * scale, y + sy * scale + scale):
                        base = py * w
                        for px in range(x0, x0 + scale):
                            rgb = colour_fn(px, py, li)
                            if rgb is not None:
                                buf[base + px] = rgb
            li += 1
        x += 5 * scale + gap
    return li


# Escape sequences keyed by the exact bytes a terminal sends.
_SS3_KEYS = {b"A": "UP", b"B": "DOWN", b"C": "RIGHT", b"D": "LEFT",
             b"H": "HOME", b"F": "END"}
_CSI_KEYS = {
    b"\x1b[A": "UP", b"\x1b[B": "DOWN", b"\x1b[C": "RIGHT", b"\x1b[D": "LEFT",
    b"\x1b[H": "HOME", b"\x1b[F": "END", b"\x1b[Z": "BACKTAB",
    b"\x1b[1~": "HOME", b"\x1b[4~": "END",
    b"\x1b[5~": "PAGEUP", b"\x1b[6~": "PAGEDOWN",
}
# Windows console: msvcrt.getwch() reports special keys as a "\x00" or "\xe0"
# prefix plus a scan code. Rewritten to the VT sequences above so one parser
# serves both platforms.
_WIN_SCAN_KEYS = {
    "H": b"\x1b[A", "P": b"\x1b[B", "M": b"\x1b[C", "K": b"\x1b[D",
    "G": b"\x1b[H", "O": b"\x1b[F", "I": b"\x1b[5~", "Q": b"\x1b[6~",
    "\x0f": b"\x1b[Z",
}
# Upper bound on keys acted on per frame, so a paste or a stuck key cannot queue
# hundreds of station changes.
MAX_KEYS_PER_FRAME = 32


def win_chars_to_bytes(chars) -> bytes:
    """Translate a run of msvcrt.getwch() results into terminal key bytes."""
    out = bytearray()
    it = iter(chars)
    for ch in it:
        if ch in ("\x00", "\xe0"):
            out += _WIN_SCAN_KEYS.get(next(it, ""), b"")
        elif ch == "\x08":
            out += b"\x7f"                      # Backspace, as POSIX terminals send it
        else:
            out += ch.encode("utf-8", errors="ignore")
    return bytes(out)


def parse_key_bytes(data: bytes):
    """Split a raw terminal read into individual keys.

    Returns (keys, leftover), where leftover is a trailing partial escape
    sequence or partial UTF-8 character to prepend to the next read.

    The old implementation compared the *whole* 32-byte read against single-key
    patterns, so any two keys arriving inside one frame matched nothing and were
    silently discarded: holding a key down did nothing at all.
    """
    keys = []
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if b == 0x1B:
            if i + 1 >= n:
                return keys, data[i:]
            nxt = data[i + 1]
            if nxt == 0x4F:                              # SS3: ESC O <final>
                if i + 2 >= n:
                    return keys, data[i:]
                keys.append(_SS3_KEYS.get(data[i + 2:i + 3], "ESC"))
                i += 3
                continue
            if nxt == 0x5B:                              # CSI: ESC [ params final
                j = i + 2
                while j < n and 0x30 <= data[j] <= 0x3F:
                    j += 1
                while j < n and 0x20 <= data[j] <= 0x2F:
                    j += 1
                if j >= n:
                    return keys, data[i:]
                keys.append(_CSI_KEYS.get(data[i:j + 1], "ESC"))
                i = j + 1
                continue
            keys.append("ESC")
            i += 1
            continue
        if b == 0x09:
            keys.append("TAB"); i += 1; continue
        if b in (0x0D, 0x0A):
            keys.append("ENTER"); i += 1; continue
        if b == 0x20:
            keys.append("SPACE"); i += 1; continue
        if b == 0x03:
            keys.append("QUIT"); i += 1; continue
        if b == 0x7F:
            keys.append("BACKSPACE"); i += 1; continue
        if b < 0x80:
            length = 1
        elif b >= 0xF0:
            length = 4
        elif b >= 0xE0:
            length = 3
        elif b >= 0xC0:
            length = 2
        else:
            i += 1                                       # stray continuation byte
            continue
        if i + length > n:
            return keys, data[i:]
        try:
            keys.append(data[i:i + length].decode("utf-8"))
        except UnicodeDecodeError:
            pass
        i += length
    return keys, b""


class RawInput:
    """Non-blocking keyboard reader with correct multi-key and escape handling."""

    # A lone ESC is indistinguishable from the start of an arrow-key sequence
    # until more bytes arrive or enough time passes.
    ESC_TIMEOUT = 0.05

    def __init__(self):
        self._pending = b""
        self._esc_at = None

    def __enter__(self):
        self.win = IS_WINDOWS and sys.stdin.isatty()
        if not HAS_TERMIOS or not sys.stdin.isatty():
            return self
        try:
            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        except Exception as exc:
            LOG.warning("could not set cbreak mode: %s", exc)
        return self

    def __exit__(self, *args):
        if HAS_TERMIOS and hasattr(self, "old"):
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
            except Exception as exc:
                LOG.warning("could not restore terminal mode: %s", exc)

    def wait_readable(self, timeout: float) -> bool:
        """Sleep until a key arrives or timeout elapses; True if input waits.
        Lets the idle frame rate drop without making keys feel laggy."""
        if timeout <= 0:
            return False
        if getattr(self, "win", False):
            # console handles cannot be select()ed; poll kbhit in short steps
            deadline = time.monotonic() + timeout
            while not msvcrt.kbhit():
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                time.sleep(min(0.01, left))
            return True
        if not HAS_TERMIOS or not hasattr(self, "fd") or not sys.stdin.isatty():
            time.sleep(timeout)
            return False
        try:
            r, _, _ = select.select([self.fd], [], [], timeout)
            return bool(r)
        except (OSError, ValueError):
            time.sleep(timeout)
            return False

    def get_keys(self, limit=MAX_KEYS_PER_FRAME):
        """Every key pressed since the last call, in order, at most limit of
        them. limit=None keeps them all, which a pasted URL needs."""
        if getattr(self, "win", False):
            data = self._pending + self._read_windows()
            self._pending = b""
        elif not HAS_TERMIOS or not sys.stdin.isatty() or not hasattr(self, "fd"):
            return []
        else:
            data = self._pending
            self._pending = b""
            data += self._read_posix()
        keys = []
        if data:
            keys, self._pending = parse_key_bytes(data)
        now = time.monotonic()
        if self._pending == b"\x1b":
            if self._esc_at is None:
                self._esc_at = now
            elif now - self._esc_at > self.ESC_TIMEOUT:
                keys.append("ESC")
                self._pending = b""
                self._esc_at = None
        else:
            self._esc_at = None
        if limit is not None and len(keys) > limit:
            LOG.debug("dropping %d excess keys this frame", len(keys) - limit)
            keys = keys[:limit]
        return keys

    @staticmethod
    def _read_windows() -> bytes:
        chars = []
        while msvcrt.kbhit() and len(chars) < 8192:
            chars.append(msvcrt.getwch())
            if chars[-1] in ("\x00", "\xe0"):
                chars.append(msvcrt.getwch())    # the scan code is always queued with it
        return win_chars_to_bytes(chars)

    def _read_posix(self) -> bytes:
        data = b""
        while True:
            try:
                r, _, _ = select.select([self.fd], [], [], 0)
            except (OSError, ValueError):
                break
            if not r:
                break
            try:
                chunk = os.read(self.fd, 1024)
            except OSError as exc:
                if exc.errno != errno.EINTR:
                    break
                continue
            if not chunk:
                break
            data += chunk
            if len(data) > 8192:
                break
        return data


class StreamPlayer:
    """Headless mpv audio engine driven over a private UNIX socket.

    A dedicated reader thread drains everything mpv sends. That is not optional:
    mpv replies to every command, and when nothing reads those replies the socket
    write queue reaches the kernel limit (212,992 bytes) after roughly 300
    commands - about 70 seconds of ordinary volume adjustment. Measured
    consequence: mpv jumps from 2.8% to 100% of a CPU core and silently ignores
    every later command, while the UI keeps showing PLAYING. Draining the socket
    is what keeps the player controllable.

    The connection is also supervised: mpv starts on a background thread so the
    first frame is not delayed, and if it dies or the socket drops it is
    restarted and the desired state (url, volume, pause, mute) re-applied.
    """

    OBSERVED = ("pause", "core-idle", "paused-for-cache", "media-title",
                "idle-active", "demuxer-cache-duration")

    NO_MPV, STARTING, IDLE, BUFFERING, PLAYING, PAUSED, ERROR = (
        "NO MPV", "CONNECTING", "IDLE", "BUFFERING", "PLAYING", "PAUSED",
        "STREAM ERROR")

    def __init__(self):
        self.proc = None
        self.sock = None
        # Windows: prefer mpv.exe over the mpv.com console wrapper, which
        # PATHEXT ranks first, so terminate() reaches the real player
        self.mpv_bin = (IS_WINDOWS and shutil.which("mpv.exe")) or shutil.which("mpv")
        self.has_mpv = self.mpv_bin is not None
        self.is_connected = False
        self.sock_path = ipc_path(os.getpid())

        self._send_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._props = {}
        self._running = True
        self._reader = None
        self._last_error = ""
        self._load_failed = False
        self._connect_attempts = 0

        # Desired state, re-applied after any reconnect.
        self._want_url = None
        self._want_volume = 75
        self._want_pause = False
        self._want_mute = False

        if self.has_mpv:
            atexit.register(self.cleanup)
            threading.Thread(target=self._supervise, daemon=True).start()
        else:
            LOG.warning("mpv not found on PATH - audio disabled, UI still runs")

    # ---------------------------------------------------------------- lifecycle

    def _supervise(self):
        """Start mpv, keep it alive, reconnect on failure. Never blocks the UI."""
        backoff = 0.4
        while self._running:
            if not self.is_connected:
                if self._start_and_connect():
                    backoff = 0.4
                else:
                    self._connect_attempts += 1
                    time.sleep(backoff)
                    backoff = min(10.0, backoff * 2)
                    continue
            time.sleep(0.5)
            if self.proc is not None and self.proc.poll() is not None:
                LOG.warning("mpv exited (rc=%s); restarting", self.proc.returncode)
                self._drop_connection()

    def _start_and_connect(self) -> bool:
        if self.proc is None or self.proc.poll() is not None:
            if not self._spawn_mpv():
                return False
        deadline = time.monotonic() + 5.0
        while self._running and time.monotonic() < deadline:
            sock = self._try_connect()
            if sock is not None:
                self.sock = sock
                self.is_connected = True
                self._last_error = ""
                self._reader = threading.Thread(target=self._read_loop, daemon=True)
                self._reader.start()
                self._apply_desired_state()
                LOG.info("connected to mpv at %s", self.sock_path)
                return True
            time.sleep(0.05)
        return False

    def _try_connect(self):
        """One connection attempt to mpv's IPC endpoint; None if not ready."""
        if IS_WINDOWS:
            # never stat() the pipe first: that opens it and uses up mpv's instance
            try:
                return _PipeConn(self.sock_path)
            except OSError:
                return None
        if not os.path.exists(self.sock_path):
            return None
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(self.sock_path)
        except OSError:
            sock.close()
            return None
        return sock

    def _spawn_mpv(self) -> bool:
        try:
            if not IS_WINDOWS and os.path.exists(self.sock_path):
                os.remove(self.sock_path)
        except OSError:
            pass
        cmd = [
            self.mpv_bin or "mpv", "--no-video", "--idle", f"--input-ipc-server={self.sock_path}",
            "--really-quiet", "--audio-display=no",
            "--cache=yes", "--demuxer-max-bytes=8MiB",
        ]
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, **_child_popen_kwargs(),
            )
            _adopt_child(self.proc)
            LOG.info("started mpv pid=%s", self.proc.pid)
            return True
        except Exception as exc:
            LOG.error("failed to start mpv: %s", exc)
            self._last_error = str(exc)
            self.proc = None
            return False

    def _drop_connection(self):
        self.is_connected = False
        sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        with self._state_lock:
            self._props.clear()

    # ------------------------------------------------------------------ reading

    def _read_loop(self):
        """Drain mpv's output forever. This is the fix for the saturation bug."""
        sock = self.sock
        buf = b""
        while self._running and sock is not None and self.sock is sock:
            try:
                chunk = sock.recv(65536)
            except OSError as exc:
                if getattr(exc, "errno", None) == errno.EINTR:
                    continue
                LOG.info("mpv socket read ended: %s", exc)
                break
            if not chunk:
                LOG.info("mpv closed the IPC socket")
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if line:
                    self._handle_message(line)
            if len(buf) > (1 << 20):        # runaway partial line; resynchronise
                buf = b""
        if self.sock is sock:
            self._drop_connection()

    def _handle_message(self, raw: bytes):
        try:
            msg = json.loads(raw.decode("utf-8", errors="replace"))
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(msg, dict):
            return
        event = msg.get("event")
        if event == "property-change":
            name = msg.get("name")
            if name:
                with self._state_lock:
                    self._props[name] = msg.get("data")
        elif event == "end-file":
            reason = msg.get("reason", "")
            if reason in ("error", "unknown"):
                self._load_failed = True
                self._last_error = str(msg.get("file_error") or reason)
                LOG.warning("mpv end-file: %s", self._last_error)
        elif event in ("start-file", "file-loaded"):
            self._load_failed = False
            self._last_error = ""
        elif event is None and msg.get("error") not in (None, "success"):
            LOG.debug("mpv command error: %s", msg.get("error"))

    # ------------------------------------------------------------------ writing

    def _send_cmd(self, command_list) -> bool:
        sock = self.sock
        if not self.is_connected or sock is None:
            return False
        payload = (json.dumps({"command": command_list}) + "\n").encode("utf-8")
        with self._send_lock:
            try:
                sock.sendall(payload)
                return True
            except OSError as exc:
                LOG.warning("mpv send failed: %s", exc)
                self._last_error = str(exc)
                self._drop_connection()
                return False

    def _apply_desired_state(self):
        for name in self.OBSERVED:
            self._send_cmd(["observe_property", 1, name])
        self._send_cmd(["set_property", "volume", self._want_volume])
        self._send_cmd(["set_property", "mute", self._want_mute])
        if self._want_url:
            self._send_cmd(["loadfile", self._want_url, "replace"])
            self._send_cmd(["set_property", "pause", self._want_pause])

    # -------------------------------------------------------------- public API

    def load_stream(self, url: str):
        self._want_url = url
        self._want_pause = False
        self._load_failed = False
        self._send_cmd(["loadfile", url, "replace"])

    def set_pause(self, paused: bool):
        self._want_pause = bool(paused)
        self._send_cmd(["set_property", "pause", bool(paused)])

    def set_volume(self, volume: int):
        vol = max(0, min(100, int(volume)))
        self._want_volume = vol
        self._send_cmd(["set_property", "volume", vol])

    def set_mute(self, muted: bool):
        self._want_mute = bool(muted)
        self._send_cmd(["set_property", "mute", bool(muted)])

    def stop(self):
        self._want_url = None
        self._send_cmd(["stop"])

    def get_media_title(self) -> str:
        """Current ICY title, delivered by property observation - no round trip."""
        with self._state_lock:
            title = self._props.get("media-title")
        return str(title) if title else ""

    def health(self):
        """(state, is_really_playing).

        The UI must not claim PLAYING unless mpv actually is: the old code faked
        a spectrum and ticked a timer over a dead stream with no way to tell.
        """
        if not self.has_mpv:
            return self.NO_MPV, False
        if not self.is_connected:
            return (self.ERROR if self._connect_attempts > 3 else self.STARTING), False
        with self._state_lock:
            props = dict(self._props)
        if self._load_failed:
            return self.ERROR, False
        if not self._want_url or props.get("idle-active"):
            return self.IDLE, False
        if props.get("paused-for-cache"):
            return self.BUFFERING, False
        if props.get("pause"):
            return self.PAUSED, False
        if props.get("core-idle"):
            return self.BUFFERING, False
        return self.PLAYING, True

    def last_error(self) -> str:
        return self._last_error

    def cleanup(self):
        self._running = False
        self._drop_connection()
        proc, self.proc = self.proc, None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
        try:
            if not IS_WINDOWS and os.path.exists(self.sock_path):
                os.remove(self.sock_path)
        except OSError as exc:
            LOG.debug("could not remove %s: %s", self.sock_path, exc)


class HttpSession:
    """Tiny keep-alive JSON client with ETag revalidation. Standard library only.

    Replaces one fresh TCP+TLS handshake per request. Measured on the four
    metadata endpoints, 93-96% of the wire bytes for the small ones were
    handshake overhead - a 295-byte answer cost 6,764 bytes - and SomaFM's
    52 KB channel directory was re-downloaded every 12 seconds to read one
    string. Keep-alive plus If-None-Match removes nearly all of it.
    """

    def __init__(self, user_agent: str = "termbeat/2.1"):
        self.user_agent = user_agent
        self._conns = {}
        self._etags = {}
        self._cache = {}
        self._lock = threading.Lock()

    def _close(self, key):
        conn = self._conns.pop(key, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def get_json(self, url: str, timeout: float = 6.0):
        parts = urllib.parse.urlsplit(url)
        key = (parts.scheme, parts.netloc)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        with self._lock:
            for attempt in (0, 1):
                conn = self._conns.get(key)
                if conn is None:
                    factory = (http.client.HTTPSConnection if parts.scheme == "https"
                               else http.client.HTTPConnection)
                    conn = factory(parts.netloc, timeout=timeout)
                    self._conns[key] = conn
                headers = {
                    "User-Agent": self.user_agent,
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "Connection": "keep-alive",
                }
                etag = self._etags.get(url)
                if etag:
                    headers["If-None-Match"] = etag
                try:
                    conn.request("GET", path, headers=headers)
                    resp = conn.getresponse()
                    body = resp.read()
                except Exception:
                    self._close(key)
                    if attempt == 0:
                        continue                # stale pooled connection; retry
                    raise
                if resp.status == 304:
                    return self._cache.get(url)
                if resp.status != 200:
                    raise OSError(f"HTTP {resp.status} for {url}")
                new_etag = resp.getheader("ETag")
                if new_etag:
                    self._etags[url] = new_etag
                data = json.loads(body.decode("utf-8", errors="replace"))
                self._cache[url] = data
                return data
        return None

    def close(self):
        with self._lock:
            for key in list(self._conns):
                self._close(key)


class MetadataScraper(threading.Thread):
    """Fetches on-air track titles, polling only the provider actually tuned.

    The original polled all four provider APIs every 12 seconds regardless of
    what was playing: 1,200 HTTPS requests/hour and a measured 24.4 MB/hour,
    43% of the bandwidth of the audio stream itself. Now the tuned provider is
    polled every 30 s, all providers are swept only every 10 minutes to keep the
    directory's listener counts roughly current, and failures back off.
    """

    TUNED_INTERVAL = 30.0
    SWEEP_INTERVAL = 600.0
    MAX_BACKOFF = 300.0

    # Full-directory endpoints, used only for the slow sweep that refreshes
    # listener counts for stations you are not currently listening to.
    ENDPOINTS = {
        "somafm": "https://api.somafm.com/channels.json",
        "plaza": "https://api.plaza.one/status",
        "radioparadise": "https://api.radioparadise.com/api/now_playing",
        "kexp": "https://api.kexp.org/v2/plays/?limit=1",
    }

    # SomaFM publishes a per-channel now-playing feed. Measured: 2,691 bytes
    # against 52,751 for the full channels.json, a 20x saving on the endpoint
    # that dominates this app's metadata traffic.
    SOMAFM_CHANNEL_URL = "https://api.somafm.com/songs/{id}.json"

    def __init__(self, playlist):
        super().__init__(daemon=True)
        self.playlist = playlist
        self.running = True
        self.session = HttpSession()
        self._active_provider = None
        self._active_id = None
        self._next_due = {}
        self._backoff = {}
        self._wake = threading.Event()

    def set_active_station(self, station: dict):
        """Called when the station changes; makes the new station due at once."""
        provider = self.provider_of(station)
        station_id = station.get("id") or None
        if (provider, station_id) != (self._active_provider, self._active_id):
            self._active_provider = provider
            self._active_id = station_id
            self._next_due["tuned"] = 0.0
            self._wake.set()

    def set_active_provider(self, provider: str):
        """Back-compat shim for callers that only know the provider name."""
        if provider != self._active_provider:
            self._active_provider = provider
            self._active_id = None
            self._next_due["tuned"] = 0.0
            self._wake.set()

    def _tuned_request(self):
        """(url, apply_fn) for the currently tuned station, or None."""
        provider = self._active_provider
        if provider not in self.ENDPOINTS:
            return None
        if provider == "somafm" and self._active_id:
            return (self.SOMAFM_CHANNEL_URL.format(id=self._active_id),
                    self._apply_somafm_channel)
        return self.ENDPOINTS[provider], getattr(self, f"_apply_{provider}")

    def _apply_somafm_channel(self, data):
        """Per-channel feed: newest song first, for the tuned station only."""
        songs = data.get("songs") or []
        if not songs:
            return
        song = songs[0]
        artist = (song.get("artist") or "").strip()
        title = (song.get("title") or "").strip()
        track = f"{artist} - {title}" if (artist and title) else (title or None)
        if not track:
            return
        for item in self.playlist:
            if item.get("id") == self._active_id:
                item["track"] = track

    @staticmethod
    def provider_of(item: dict) -> str:
        prov = (item.get("provider") or "").strip().lower()
        if prov and prov != "generic":
            return prov
        url = item.get("url", "")
        for name, host in (("somafm", "somafm.com"), ("plaza", "plaza.one"),
                           ("radioparadise", "radioparadise.com"), ("kexp", "kexp.org")):
            if host in url:
                return name
        return prov or "generic"

    def run(self):
        last_sweep = 0.0
        while self.running:
            now = time.monotonic()
            if now >= self._next_due.get("tuned", 0.0):
                req = self._tuned_request()
                if req is not None:
                    self._poll("tuned", req[0], req[1], now)
            if now - last_sweep >= self.SWEEP_INTERVAL:
                last_sweep = now
                for provider in self.ENDPOINTS:
                    if not self.running:
                        break
                    if self._has_provider(provider):
                        self._poll(provider, self.ENDPOINTS[provider],
                                   getattr(self, f"_apply_{provider}"), now)
            self._wake.wait(1.0)
            self._wake.clear()
        self.session.close()

    def _has_provider(self, provider: str) -> bool:
        return any(self.provider_of(i) == provider for i in self.playlist)

    def _poll(self, slot: str, url: str, apply_fn, now: float):
        try:
            data = self.session.get_json(url, timeout=6.0)
        except Exception as exc:
            wait = min(self.MAX_BACKOFF,
                       max(self.TUNED_INTERVAL, self._backoff.get(slot, 15.0) * 2))
            self._backoff[slot] = wait
            self._next_due[slot] = now + wait
            LOG.info("metadata poll failed for %s (%s); retry in %.0fs", slot, exc, wait)
            return
        self._backoff[slot] = 15.0
        self._next_due[slot] = now + self.TUNED_INTERVAL
        if data is None:
            return
        try:
            apply_fn(data)
        except Exception as exc:
            LOG.warning("failed to apply %s metadata: %s", slot, exc)

    def _items(self, provider: str):
        return [i for i in self.playlist if self.provider_of(i) == provider]

    def _apply_somafm(self, data):
        channels = {ch.get("id"): ch for ch in data.get("channels", [])}
        for item in self._items("somafm"):
            ch = channels.get(item.get("id"))
            if not ch:
                continue
            if ch.get("lastPlaying"):
                item["track"] = ch["lastPlaying"]
            try:
                listeners = int(ch.get("listeners"))
            except (TypeError, ValueError):
                continue
            item["listeners"] = listeners
            item["signal"] = f"{min(99, max(88, 80 + listeners // 20))}%"

    def _apply_plaza(self, data):
        song = data.get("song") or {}
        artist = (song.get("artist") or "").strip()
        title = (song.get("title") or "").strip()
        now_playing = f"{artist} - {title}" if (artist and title) else (title or None)
        try:
            listeners = int(data.get("listeners") or 0)
        except (TypeError, ValueError):
            listeners = 0
        for item in self._items("plaza"):
            if now_playing:
                item["track"] = now_playing
            if song.get("length"):
                item["track_duration"] = int(song["length"])
            if song.get("position") is not None:
                item["track_elapsed"] = int(song["position"])
            if listeners:
                item["listeners"] = listeners
                item["signal"] = f"{min(99, max(88, 80 + listeners // 10))}%"

    def _apply_radioparadise(self, data):
        artist = (data.get("artist") or "").strip()
        title = (data.get("title") or "").strip()
        track = f"{artist} - {title}" if (artist and title) else (title or None)
        if not track:
            return
        for item in self._items("radioparadise"):
            item["track"] = track
            if data.get("time"):
                try:
                    item["track_duration"] = int(data["time"])
                except (TypeError, ValueError):
                    pass

    def _apply_kexp(self, data):
        results = data.get("results") or []
        if not results:
            return
        play = results[0]
        artist = (play.get("artist") or "").strip()
        song = (play.get("song") or "").strip()
        track = f"{artist} - {song}" if (artist and song) else (song or None)
        if not track:
            return
        for item in self._items("kexp"):
            item["track"] = track

    def stop(self):
        self.running = False
        self._wake.set()


class CavaStreamEngine:
    """Headless CAVA subprocess engine streaming real-time audio spectrum via raw ASCII pipe."""
    def __init__(self, num_bars: int = 18):
        self.num_bars = num_bars
        self.cava_path = shutil.which("cava")
        self.has_cava = self.cava_path is not None
        self.raw_bands = [0.0] * self.num_bars
        self.last_update = 0.0
        self.lock = threading.Lock()
        self.proc = None
        self.running = False
        self.conf_path = None
        self.is_suspended = False
        if self.has_cava:
            self._start_cava()
            atexit.register(self.cleanup)
        else:
            LOG.info("cava not found on PATH - using the simulated spectrum")

    def _start_cava(self):
        try:
            fd, self.conf_path = tempfile.mkstemp(
                prefix="cava-", suffix=".conf", dir=_runtime_dir())
            cfg = f"""[general]
bars = {self.num_bars}
framerate = 30

[input]
method = pulse
source = auto

[output]
method = raw
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = 100
bar_delimiter = 59
frame_delimiter = 10

[smoothing]
monstercat = 1
waves = 0
noise_reduction = 77
"""
            with os.fdopen(fd, "w") as f:
                f.write(cfg)

            self.proc = subprocess.Popen(
                [self.cava_path, "-p", self.conf_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                **_child_popen_kwargs(),
            )
            _adopt_child(self.proc)
            self.running = True
            self.thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.thread.start()
            LOG.info("started cava pid=%s", self.proc.pid)
        except Exception as exc:
            LOG.error("failed to start cava: %s", exc)
            self.has_cava = False
            self.running = False
            self.cleanup()

    def _reader_loop(self):
        while self.running and self.proc and self.proc.stdout:
            try:
                line = self.proc.stdout.readline()
                if not line:
                    break
                tokens = [t for t in line.strip().split(";") if t]
                if len(tokens) >= self.num_bars:
                    vals = [max(0.0, min(1.0, float(t) / 100.0)) for t in tokens[:self.num_bars]]
                    with self.lock:
                        self.raw_bands = vals
                        self.last_update = time.time()
            except Exception:
                break
        self.running = False

    def set_suspended(self, suspended: bool):
        """Freeze cava while playback is paused.

        Measured: a running cava costs 2.1% of a core computing an FFT of
        silence, and nothing ever stopped it. SIGSTOP/SIGCONT is instant and
        avoids paying PulseAudio reconnection cost on every pause.
        """
        suspended = bool(suspended)
        if suspended == self.is_suspended or self.proc is None:
            return
        try:
            self.proc.send_signal(signal.SIGSTOP if suspended else signal.SIGCONT)
            self.is_suspended = suspended
        except Exception as exc:
            LOG.debug("could not %s cava: %s", "suspend" if suspended else "resume", exc)

    def get_bands(self) -> tuple[list[float], bool]:
        with self.lock:
            # Active if updated within last 0.5s and has non-trivial audio signal
            is_active = (time.time() - self.last_update < 0.5) and any(v > 0.02 for v in self.raw_bands)
            return list(self.raw_bands), is_active

    def cleanup(self):
        self.running = False
        if self.proc:
            try:
                if self.is_suspended:
                    # a SIGSTOPped process cannot act on SIGTERM
                    self.proc.send_signal(signal.SIGCONT)
                    self.is_suspended = False
            except Exception:
                pass
            try:
                self.proc.terminate()
                self.proc.wait(timeout=0.3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
        if self.conf_path and os.path.exists(self.conf_path):
            try:
                os.remove(self.conf_path)
            except OSError:
                pass
            self.conf_path = None


class TermbeatPlayer:
    def __init__(self):
        self.running = True
        self.is_playing = True
        self.is_stopped = False
        self.repeat_mode = True
        self.current_track_idx = 0
        self.volume = 75
        self.prev_volume = 75
        self.is_muted = False
        self.elapsed_seconds = 0
        # Wall clock for animation. The old code derived time from the frame
        # counter as `frame * 0.04` while the loop actually slept 0.045 s plus
        # render time, so every waveform ran ~12% slow and drifted.
        self.t0 = time.monotonic()
        self.t_sec = 0.0
        self._prev_lines = None
        self._cleaned_up = False
        self._monstercat_table = {}
        self.stream_state = StreamPlayer.STARTING
        self.stream_live = False
        self.last_tick = time.time()
        self.current_song_title = ""
        self.track_elapsed = 0
        self.track_duration = None
        self.last_track_tick = time.time()

        # Visualizer modes: 0: Spectrum, 1: Oscilloscope
        self.viz_mode = 0
        self.viz_names = ["SPECTRUM", "OSCILLOSCOPE"]

        self.theme_idx = 0

        self.show_drawer = False
        self.drawer_selected_idx = 0
        self.drawer_scroll_offset = 0
        self.drawer_page = 7          # stations the drawer showed last frame
        self.editor = None            # the [A] add-station form's state while it is open
        self.config_mtime = 0.0
        self.physics_tick = 0

        self.tuning_glitch_frames = 0
        self.target_freq = PLAYLIST[0]["freq"]

        self.button_flash = [0] * 4

        # 18 frequency bands across 8 height levels (CAVA architecture)
        self.num_bands = 18
        self.max_height = 8.0
        self.band_heights = [4.0] * self.num_bands
        self.cava_engine = CavaStreamEngine(self.num_bands)
        self.cava_fall = [0.0] * self.num_bands
        self.cava_peak = [0.0] * self.num_bands
        self.peak_heights = [0.0] * self.num_bands
        self.peak_hold_frames = [0] * self.num_bands
        self.bass_energy = 0.0
        self.mid_energy = 0.0
        self.treble_energy = 0.0
        self._sim_band_constants = [
            (1.0 + (i / self.num_bands) * 2.5, max(0.0, (5 - i) * 0.5), i * 0.6, -i * 0.4)
            for i in range(self.num_bands)
        ]

        self.marquee_offset = 0

        # Viewport resilience & btop resize handling
        self.min_cols = 70
        self.min_rows = 18
        self.last_cols = 0
        self.last_rows = 0
        self.needs_clear = False

        # 5 Design Aesthetics (Toggle on the fly with [D])
        self.design_style = 0
        self.design_names = ["RETRO HI-FI", "MODERN NEO", "MINIMAL ZEN", "CYBERPUNK", "TIDE"]
        # TIDE's last layout, gradient sheet and type rows, each with its key
        self._tide_cache = {}

        # Stream audio engine & live metadata
        self.stream_player = StreamPlayer()
        self.stream_player.set_volume(self.volume)
        self.meta_worker = MetadataScraper(PLAYLIST)
        self.meta_worker.start()
        if self.is_playing and PLAYLIST:
            station = PLAYLIST[self.current_track_idx]
            self.stream_player.load_stream(station["url"])
            self.meta_worker.set_active_station(station)

    def handle_sigwinch(self, *args):
        self.needs_clear = True

    def status_badge(self, t_cfg: dict, compact: bool = False):
        """(text, colour) describing what is *actually* happening.

        This used to be derived purely from our own is_playing/is_stopped flags,
        so a stream that never connected, failed, or was stalled rebuffering
        still read as a green PLAYING.
        """
        if self.is_stopped:
            return ("■ STOP" if compact else "■ STOPPED"), C_ERROR
        state = self.stream_state
        if state == StreamPlayer.NO_MPV:
            return ("⚠ NOMPV" if compact else "⚠ NO MPV"), t_cfg["_c_warn"]
        if state == StreamPlayer.ERROR:
            return ("✖ ERR" if compact else "✖ STREAM ERROR"), C_ERROR
        if not self.is_playing:
            return ("❚❚ PAUS" if compact else "❚❚ PAUSED"), t_cfg["_c_warn"]
        if state in (StreamPlayer.BUFFERING, StreamPlayer.STARTING):
            return ("◌ BUF" if compact else "◌ BUFFERING"), t_cfg["_c_warn"]
        if state == StreamPlayer.IDLE:
            return ("◌ IDLE" if compact else "◌ IDLE"), t_cfg["_c_dim"]
        return ("● PLAY" if compact else "● PLAYING"), t_cfg["_c_bright"]

    def timer_colon(self) -> str:
        """Blinking separator for the elapsed clock, on a wall clock so the
        blink rate does not change with the frame rate."""
        if not self.is_playing:
            return ":"
        return ":" if (self.t_sec % TIMER_BLINK_PERIOD) < (TIMER_BLINK_PERIOD * 0.66) else " "

    def cycle_design_style(self):
        self.design_style = (self.design_style + 1) % len(self.design_names)
        self.needs_clear = True

    def render_btop_size_warning(self, cols: int, rows: int) -> str:
        """Render exact btop-style terminal-too-small notification."""
        c_red = "\033[91m"
        c_green = "\033[92m"
        c_white = "\033[1;37m"
        rst = "\033[0m"

        w_col = c_green if cols >= self.min_cols else c_red
        h_col = c_green if rows >= self.min_rows else c_red

        content_lines = [
            f"{c_white}Terminal size too small:{rst}",
            f"{c_white} Width = {w_col}{cols}{rst}{c_white} Height = {h_col}{rows}{rst}",
            "",
            f"{c_white}Needed for current config:{rst}",
            f"{c_white} Width = {self.min_cols} Height = {self.min_rows}{rst}",
        ]

        total_lines = len(content_lines)
        top_space = max(0, (rows - total_lines) // 2)

        buf = []
        for _ in range(top_space):
            buf.append("\033[K")

        for line in content_lines:
            vis_w = str_width(line)
            left_pad = max(0, (cols - vis_w) // 2)
            buf.append(f"{' ' * left_pad}{line}\033[K")

        return "\033[H" + "\n".join(buf) + "\033[J"

    def stop_app(self, *args):
        LOG.info("shutdown signal received")
        self.running = False

    def flash_button(self, idx: int):
        if 0 <= idx < len(self.button_flash):
            self.button_flash[idx] = 4

    def trigger_tuning(self):
        self.tuning_glitch_frames = 5
        self.target_freq = PLAYLIST[self.current_track_idx]["freq"]

    def _tune(self, idx: int):
        """Switch station and tell every subsystem (was three near-identical
        copies of this body)."""
        if not PLAYLIST:
            return
        self.current_track_idx = idx % len(PLAYLIST)
        station = PLAYLIST[self.current_track_idx]
        now = time.time()
        self.elapsed_seconds = 0
        self.current_song_title = ""
        self.track_elapsed = 0
        self.track_duration = None
        self.last_tick = now
        self.last_track_tick = now
        self.marquee_offset = 0
        self.is_stopped = False
        self.is_playing = True
        self.trigger_tuning()
        self.stream_player.load_stream(station["url"])
        self.stream_player.set_pause(False)
        if hasattr(self, "meta_worker"):
            # only the tuned provider is polled now, so it must be told at once
            self.meta_worker.set_active_station(station)
        LOG.info("tuned to %s", station["station"])

    def next_track(self):
        self.flash_button(3)
        self._tune(self.current_track_idx + 1)

    def prev_track(self):
        self.flash_button(1)
        self._tune(self.current_track_idx - 1)

    def select_preset(self, idx: int):
        if 0 <= idx < len(PLAYLIST):
            self._tune(idx)

    def cycle_viz_mode(self):
        self.viz_mode = (self.viz_mode + 1) % len(self.viz_names)

    def cycle_theme(self):
        self.theme_idx = (self.theme_idx + 1) % len(THEMES)

    def check_reload_stations(self, force: bool = False):
        """Reload the station list if the config file changed on disk. force
        skips the mtime comparison, for right after the editor has written it:
        a coarse filesystem clock could otherwise hide that write."""
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            mtime = os.path.getmtime(CONFIG_FILE)
            if mtime <= self.config_mtime and not force:
                return
            self.config_mtime = mtime
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                stations = normalize_playlist(json.load(f))
            if not stations:
                LOG.warning("reload produced no usable stations; keeping current list")
                return
            global PLAYLIST
            PLAYLIST = stations
            if hasattr(self, "meta_worker"):
                self.meta_worker.playlist = stations
            self.current_track_idx = min(self.current_track_idx, len(PLAYLIST) - 1)
            self.drawer_selected_idx = min(self.drawer_selected_idx, len(PLAYLIST) - 1)
            LOG.info("reloaded %d stations", len(stations))
        except Exception as exc:
            LOG.warning("station reload failed: %s", exc)

    def toggle_drawer(self):
        self.show_drawer = not self.show_drawer
        if self.show_drawer:
            self.check_reload_stations()
            self.drawer_selected_idx = self.current_track_idx
            # Center the selected item in the scroll window
            page = self.drawer_page
            self.drawer_scroll_offset = max(0, min(len(PLAYLIST) - page, self.drawer_selected_idx - page // 2))

    def open_station_editor(self):
        """[A]: a blank add-station form. While it is open it owns the keyboard."""
        self.show_drawer = False
        self.editor = {"fields": {f: "" for f in EDITOR_FIELDS if f != "provider"},
                       "provider": "auto", "field": 0, "error": ""}

    def _editor_key(self, key: str) -> bool:
        """Every key while the form is open, so q, n, d and digits type rather
        than quit, tune or restyle. Enter saves; Ctrl-S is not used because the
        terminal keeps it for XON/XOFF flow control and it would freeze output."""
        ed = self.editor
        field = EDITOR_FIELDS[ed["field"]]
        if key == "QUIT":
            return False
        if key == "ESC":
            self.editor = None
        elif key in ("TAB", "DOWN"):
            ed["field"] = (ed["field"] + 1) % len(EDITOR_FIELDS)
        elif key in ("BACKTAB", "UP"):
            ed["field"] = (ed["field"] - 1) % len(EDITOR_FIELDS)
        elif key in ("LEFT", "RIGHT"):
            if field == "provider":
                step = 1 if key == "RIGHT" else -1
                i = EDITOR_PROVIDERS.index(ed["provider"])
                ed["provider"] = EDITOR_PROVIDERS[(i + step) % len(EDITOR_PROVIDERS)]
        elif key == "ENTER":
            ed["error"] = self._editor_problem() or self._save_new_station() or ""
        elif field != "provider":
            value = ed["fields"][field]
            if key in ("BACKSPACE", "\x08"):
                value = value[:-1]
            elif key == "\x15":                          # Ctrl-U
                value = ""
            elif key == "SPACE":
                value += " "
            elif len(key) == 1 and key.isprintable():
                value += key
            ed["fields"][field] = value[:256]
            ed["error"] = ""
        return True

    def _editor_problem(self):
        """Why the form can't be saved yet, or None. The URL rule is the one
        normalize_station applies when stations.json is loaded."""
        f = self.editor["fields"]
        url = f["url"].strip()
        if not f["name"].strip():
            return "name is required"
        parts = urllib.parse.urlsplit(url)
        if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
            return "url must start with http:// or https://"
        for stn in PLAYLIST:
            if stn["url"] == url:
                return f"already saved as {stn['station']}"
        return None

    def _editor_entry(self) -> dict:
        """The stations.json entry the form describes: only what was filled in,
        plus an id."""
        f = self.editor["fields"]
        entry = {"station": f["name"].strip(), "url": f["url"].strip()}
        for key in ("freq", "genre", "bitrate"):
            if f[key].strip():
                entry[key] = f[key].strip()
        if self.editor["provider"] != "auto":
            entry["provider"] = self.editor["provider"]
        if MetadataScraper.provider_of(entry) == "somafm":
            # SomaFM's now-playing feed is looked up by channel id, the first
            # part of the stream path: /groovesalad-128-mp3 -> groovesalad.
            path = urllib.parse.urlsplit(entry["url"]).path.strip("/")
            entry["id"] = path.split("/")[-1].split("-")[0].split(".")[0]
        else:
            slug = re.sub(r"[^a-z0-9]+", "-", entry["station"].lower()).strip("-") or "station"
            taken = {s.get("id") for s in PLAYLIST}
            sid, n = slug, 2
            while sid in taken:
                sid, n = f"{slug}-{n}", n + 1
            entry["id"] = sid
        return entry

    def _save_new_station(self):
        """Append the form to stations.json, reload, and tune to the new station.
        Returns an error message, or None once saved (the form then closes).

        Append-only: the existing entries are read back as they are on disk and
        written out unchanged, and a file that doesn't parse is never replaced -
        it may be one the user is half-way through editing by hand.
        """
        entry = self._editor_entry()
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if not isinstance(raw, list):
                    raise ValueError("not a list")
            else:
                raw = [dict(s) for s in DEFAULT_PLAYLIST]
        except (ValueError, OSError):
            return "stations.json isn't a valid list - fix it first"
        raw.append(entry)
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".stations.", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(raw, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                if os.path.exists(CONFIG_FILE):
                    shutil.copymode(CONFIG_FILE, tmp)
                os.replace(tmp, CONFIG_FILE)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as exc:
            return f"could not write stations.json: {exc.strerror or exc}"
        LOG.info("added station %r to %s", entry["station"], CONFIG_FILE)
        self.check_reload_stations(force=True)
        self.editor = None
        idx = next((i for i, s in enumerate(PLAYLIST) if s["url"] == entry["url"]), None)
        if idx is not None:
            self._tune(idx)
        return None

    def toggle_play(self):
        self.flash_button(2)
        if self.is_stopped:
            self._tune(self.current_track_idx)
        else:
            self.is_playing = not self.is_playing
            self.stream_player.set_pause(not self.is_playing)

    def stop_playback(self):
        self.is_stopped = True
        self.is_playing = False
        self.elapsed_seconds = 0
        self.track_elapsed = 0
        self.current_song_title = ""
        self.stream_player.stop()

    def toggle_repeat(self):
        self.flash_button(0)
        self.repeat_mode = not self.repeat_mode

    def toggle_mute(self):
        if self.is_muted:
            self.volume = self.prev_volume if self.prev_volume > 0 else 50
            self.is_muted = False
            self.stream_player.set_volume(self.volume)
            self.stream_player.set_mute(False)
        else:
            self.prev_volume = self.volume
            self.volume = 0
            self.is_muted = True
            self.stream_player.set_mute(True)

    def apply_monstercat_filter(self, bars: list, monstercat: float = 1.0) -> list:
        """CAVA's Monstercat spatial smoothing filter (from cava.c)."""
        n = len(bars)
        res = list(bars)
        if monstercat <= 0.0:
            return res
        # factor ** distance is loop-invariant per distance; table it once
        table = self._monstercat_table.get((monstercat, n))
        if table is None:
            factor = monstercat * 1.5
            table = [factor ** d for d in range(n)]
            self._monstercat_table[(monstercat, n)] = table
        for z in range(n):
            val = bars[z]
            if val <= 0.0:
                continue
            for m_y in range(z - 1, -1, -1):
                propagated = val / table[z - m_y]
                if propagated > res[m_y]:
                    res[m_y] = propagated
            for m_y in range(z + 1, n):
                propagated = val / table[m_y - z]
                if propagated > res[m_y]:
                    res[m_y] = propagated
        return res

    def update_physics(self):
        now = time.time()

        # Ask mpv what is actually happening rather than trusting what we last
        # asked it to do. Without this the UI showed a moving spectrum, a
        # ticking timer and a green PLAYING badge over a dead stream.
        self.stream_state, self.stream_live = self.stream_player.health()
        if not self.stream_player.has_mpv:
            # No audio backend installed: the deck still animates so it behaves
            # like a player, and the badge says NO MPV.
            self.stream_live = self.is_playing and not self.is_stopped

        wants_audio = self.is_playing and not self.is_stopped
        # cava costs ~2% of a core doing an FFT of silence; freeze it when paused
        self.cava_engine.set_suspended(not wants_audio)

        if wants_audio and self.stream_live:
            if now - self.last_tick >= 1.0:
                self.elapsed_seconds += int(now - self.last_tick)
                self.last_tick = now

            # Song change detection and live track elapsed tracking
            cur_stn = PLAYLIST[self.current_track_idx]
            new_title = cur_stn.get("track", "")
            if new_title and new_title != self.current_song_title:
                self.current_song_title = new_title
                api_elapsed = cur_stn.get("track_elapsed")
                self.track_elapsed = api_elapsed if (api_elapsed is not None and api_elapsed > 0) else 0
                self.track_duration = cur_stn.get("track_duration")
                self.last_track_tick = now
            else:
                if not self.track_duration and cur_stn.get("track_duration"):
                    self.track_duration = cur_stn.get("track_duration")
                if now - self.last_track_tick >= 1.0:
                    delta = int(now - self.last_track_tick)
                    self.track_elapsed += delta
                    self.last_track_tick = now
        else:
            # Not actually playing: hold the clocks still so a pause or a
            # buffering stall is not credited to the track when audio returns.
            self.last_tick = now
            self.last_track_tick = now

        # Silence the visualizer whenever audio is not genuinely flowing, so a
        # buffering or failed stream reads as dead rather than as music.
        if self.is_muted or not wants_audio or not self.stream_live:
            effective_vol = 0.0
        else:
            effective_vol = self.volume / 100.0

        # 1. Fetch live CAVA stream data or generate pure-Python CAVA simulation
        live_bands, has_live_cava = self.cava_engine.get_bands()

        if has_live_cava and effective_vol > 0.01:
            # Scale 0.0-1.0 to 0.0-max_height with perceptual volume curve
            target_bands = [
                min(self.max_height, b * self.max_height * (effective_vol ** 0.65) * 1.15)
                for b in live_bands
            ]
        else:
            if self.is_playing and not self.is_stopped and effective_vol > 0.01:
                t = time.time()
                raw_impulses = []
                for i in range(self.num_bands):
                    freq_factor, bass_boost, p1, p2 = self._sim_band_constants[i]
                    wave = (
                        math.sin(t * (3.2 * freq_factor) + p1) * 1.8 +
                        math.cos(t * (2.1 * freq_factor) + p2) * 1.2 +
                        random.uniform(-0.5, 1.3)
                    )
                    val = max(0.4, (2.6 + wave + bass_boost) * effective_vol)
                    raw_impulses.append(val)
                target_bands = self.apply_monstercat_filter(raw_impulses, monstercat=1.0)
                target_bands = [min(self.max_height, max(0.2, b)) for b in target_bands]
            else:
                target_bands = [0.0] * self.num_bands

        # 2. CAVA Quadratic Gravity Ballistics & Fast Attack Spring
        for i in range(self.num_bands):
            tgt = target_bands[i]
            if tgt >= self.band_heights[i]:
                # Fast attack spring
                self.band_heights[i] += (tgt - self.band_heights[i]) * 0.60
                self.cava_peak[i] = self.band_heights[i]
                self.cava_fall[i] = 0.0
            else:
                # CAVA quadratic gravity deceleration
                self.cava_fall[i] += 0.035
                fall_decay = self.cava_peak[i] * (1.0 - (self.cava_fall[i] ** 2) * 1.25)
                self.band_heights[i] = max(0.0, max(tgt, fall_decay))

            self.band_heights[i] = max(0.0, min(self.max_height, self.band_heights[i]))

            # 3. Floating Peak Hold Indicators
            if self.band_heights[i] >= self.peak_heights[i]:
                self.peak_heights[i] = self.band_heights[i]
                self.peak_hold_frames[i] = 5
            else:
                if self.peak_hold_frames[i] > 0:
                    self.peak_hold_frames[i] -= 1
                else:
                    self.peak_heights[i] = max(self.band_heights[i], self.peak_heights[i] - 0.16)

        # 4. Multi-band Energy Extraction for Cross-Mode Reactivity
        self.bass_energy = sum(self.band_heights[:5]) / (5.0 * self.max_height)
        self.mid_energy = sum(self.band_heights[5:12]) / (7.0 * self.max_height)
        self.treble_energy = sum(self.band_heights[12:]) / (6.0 * self.max_height)

        for i in range(len(self.button_flash)):
            if self.button_flash[i] > 0:
                self.button_flash[i] -= 1

        if self.tuning_glitch_frames > 0:
            self.tuning_glitch_frames -= 1

        self.physics_tick += 1
        # media-title now arrives by property observation, so reading it is a
        # dict lookup rather than a blocking IPC round trip.
        if self.physics_tick % 10 == 0 and wants_audio:
            cur_stn = PLAYLIST[self.current_track_idx]
            track = cur_stn.get("track", "")
            if cur_stn.get("provider") == "generic" or not track or "[SomaFM]" in track:
                m_title = self.stream_player.get_media_title()
                if m_title and m_title != track:
                    cur_stn["track"] = m_title

    def get_equalizer_rows(self, target_w: int, total_rows: int, t_cfg: dict) -> list:
        """Visualizer Mode 0: Batch CAVA Spectrum Analyzer across all vertical rows."""
        c_bright = t_cfg["_c_bright"]
        c_warn = t_cfg["_c_warn"]
        c_accent = t_cfg["_c_accent"]
        c_dim = t_cfg["_c_dim"]

        if total_rows <= 5:
            row_colors = [c_warn, c_accent, c_accent, c_bright, c_bright]
        else:
            w_rows = max(1, total_rows // 4)
            a_rows = max(1, total_rows // 3)
            b_rows = max(1, total_rows - w_rows - a_rows)
            row_colors = [c_warn] * w_rows + [c_accent] * a_rows + [c_bright] * b_rows

        peak_colors = [c_warn if r <= max(1, total_rows // 4) else c_accent for r in range(total_rows)]

        num_bars = max(10, target_w // 2 if target_w >= 20 else target_w)
        use_spaces = (target_w >= num_bars * 2)
        n_raw = len(self.band_heights)

        scale = total_rows / 8.0
        bar_vals = []
        peak_vals = []
        denom = max(1, num_bars - 1)
        raw_b = self.band_heights
        raw_p = self.peak_heights
        for i in range(num_bars):
            pos = i * (n_raw - 1) / denom
            idx = int(pos)
            frac = pos - idx
            idx_next = min(idx + 1, n_raw - 1)
            bar_vals.append(((1.0 - frac) * raw_b[idx] + frac * raw_b[idx_next]) * scale)
            peak_vals.append(((1.0 - frac) * raw_p[idx] + frac * raw_p[idx_next]) * scale)

        bars_w = num_bars * 2 if use_spaces else num_bars
        pad_l = " " * max(0, (target_w - bars_w) // 2)

        out_rows = []
        for r in range(total_rows):
            color = row_colors[min(r, len(row_colors) - 1)]
            p_col = peak_colors[r]
            threshold = float(total_rows - 1 - r)
            chars = [pad_l]
            for i in range(num_bars):
                val = bar_vals[i]
                rem = val - threshold
                p_val = peak_vals[i]
                p_rem = p_val - threshold

                if rem >= 1.0:
                    chars.append(f"{color}█")
                elif rem > 0.0:
                    block_idx = int(rem * 8)
                    chars.append(f"{color}{BLOCKS[max(1, min(8, block_idx))]}")
                elif 0.0 <= p_rem < 1.0 and p_val > 0.4:
                    chars.append(f"{p_col}▔")
                else:
                    chars.append(f"{c_dim} ")

                if use_spaces:
                    chars.append(" ")
            out_rows.append(fit_row("".join(chars), target_w))
        return out_rows


    def get_oscilloscope_rows(self, target_w: int, total_rows: int, t_sec: float, t_cfg: dict) -> list:
        """Visualizer Mode 1: Batch Oscilloscope Waveform across all vertical rows."""
        c_bright = t_cfg["_c_bright"]
        c_accent = t_cfg["_c_accent"]
        c_dim = t_cfg["_c_dim"]

        effective_vol = 0.0 if (self.is_muted or self.is_stopped or not self.is_playing) else (self.volume / 100.0)
        center_y = (total_rows - 1) / 2.0
        amp = (total_rows / 8.0) * effective_vol
        mid_row = int(center_y)

        if effective_vol < 0.02:
            out_rows = []
            flat_str = fit_row(f"{c_dim}─" * target_w, target_w)
            blank_str = " " * target_w
            target_mid_rows = (mid_row, mid_row + 1) if total_rows > 4 else (mid_row,)
            for r in range(total_rows):
                out_rows.append(flat_str if r in target_mid_rows else blank_str)
            return out_rows

        w_factor = 1.0 / float(target_w)
        phase1 = t_sec * (2.6 + self.treble_energy * 1.4)
        phase2 = -t_sec * 1.8
        phase3 = t_sec * 3.5
        scale1 = (1.3 + self.bass_energy * 0.8)
        scale2 = (0.8 + self.mid_energy * 0.5)
        scale3 = (0.3 + self.treble_energy * 0.4)

        cols_data = []
        for x in range(target_w):
            x_norm = x * w_factor
            val = (
                math.sin(x_norm * 8.6 + phase1) * scale1 +
                math.cos(x_norm * 18.0 + phase2) * scale2 +
                math.sin(x_norm * 38.0 + phase3) * scale3
            ) * amp
            yf = center_y - (val * 1.25)
            yi = int(round(yf))
            cols_data.append((yf, yi))

        out_rows = []
        for r in range(total_rows):
            chars = []
            is_edge = (r in (0, total_rows - 1))
            wave_char = f"{c_accent}\033[1m~\033[22m" if is_edge else f"{c_bright}\033[1m∿\033[22m"
            for yf, yi in cols_data:
                if yi == r:
                    chars.append(wave_char)
                elif abs(yf - r) < 0.65:
                    chars.append(f"{c_dim}·")
                else:
                    chars.append(" ")
            out_rows.append(fit_row("".join(chars), target_w))
        return out_rows


    def get_braille_wave_rows(self, target_w: int, total_rows: int, t_sec: float, t_cfg: dict) -> list:
        """Visualizer: High-Resolution Braille Waveform Batch Generation (sub-pixel grid)."""
        c_bright = t_cfg["_c_bright"]
        c_accent = t_cfg["_c_accent"]
        c_dim = t_cfg["_c_dim"]

        effective_vol = 0.0 if (self.is_muted or self.is_stopped or not self.is_playing) else (self.volume / 100.0)
        total_sub_h = total_rows * 4
        center_sub_y = (total_sub_h - 1) / 2.0
        amp = (total_sub_h / 2.5) * effective_vol

        col0_dots = (0x01, 0x02, 0x04, 0x40)
        col1_dots = (0x08, 0x10, 0x20, 0x80)

        grid = [[0] * target_w for _ in range(total_rows)]

        if effective_vol < 0.02:
            sub_mid = int(center_sub_y)
            r_mid = sub_mid // 4
            rem_mid = sub_mid % 4
            if 0 <= r_mid < total_rows:
                dot = col0_dots[rem_mid] | col1_dots[rem_mid]
                for cx in range(target_w):
                    grid[r_mid][cx] = dot
        else:
            w_factor = 1.0 / float(max(1, target_w * 2))
            phase1 = t_sec * (2.8 + self.treble_energy * 1.5)
            phase2 = -t_sec * 1.8
            phase3 = t_sec * 4.2
            scale1 = (0.55 + self.bass_energy * 0.35)
            scale2 = (0.30 + self.mid_energy * 0.25)
            scale3 = (0.15 + self.treble_energy * 0.2)

            for char_x in range(target_w):
                base_x = char_x * 2

                x_norm0 = base_x * w_factor
                val0 = (
                    math.sin(x_norm0 * 14.0 + phase1) * scale1 +
                    math.cos(x_norm0 * 22.0 + phase2) * scale2 +
                    math.sin(x_norm0 * 35.0 + phase3) * scale3
                )
                y_sub0 = int(round(center_sub_y - val0 * amp))
                r0 = y_sub0 // 4
                if 0 <= r0 < total_rows:
                    grid[r0][char_x] |= col0_dots[y_sub0 % 4]

                x_norm1 = (base_x + 1) * w_factor
                val1 = (
                    math.sin(x_norm1 * 14.0 + phase1) * scale1 +
                    math.cos(x_norm1 * 22.0 + phase2) * scale2 +
                    math.sin(x_norm1 * 35.0 + phase3) * scale3
                )
                y_sub1 = int(round(center_sub_y - val1 * amp))
                r1 = y_sub1 // 4
                if 0 <= r1 < total_rows:
                    grid[r1][char_x] |= col1_dots[y_sub1 % 4]

        out_rows = []
        for r in range(total_rows):
            color = c_accent if (r in (0, total_rows - 1)) else c_bright
            chars = []
            for d in grid[r]:
                if d:
                    chars.append(f"{color}{chr(0x2800 + d)}{RST}")
                else:
                    chars.append(" ")
            out_rows.append(fit_row("".join(chars), target_w))
        return out_rows


    def get_tuning_glitch_rows(self, target_w: int, total_rows: int, t_cfg: dict) -> list:
        """Generates dynamic static glitch tuning animation rows confined to the visualizer display area."""
        c_bright = t_cfg["_c_bright"]
        c_warn = t_cfg["_c_warn"]
        c_accent = t_cfg["_c_accent"]
        c_dim = t_cfg["_c_dim"]

        current_track = PLAYLIST[self.current_track_idx]
        stn_name = current_track.get("station", "RADIO").upper()

        # Responsive tape header based on width
        if target_w >= 36:
            tape = f"PRESET ··· [ {stn_name} ] ··· TUNING"
        elif target_w >= 22:
            tape = f"TUNING: [ {stn_name} ]"
        elif target_w >= 14:
            tape = f"TUNE {stn_name}"
        else:
            tape = "TUNING"

        # Responsive locking message
        if target_w >= 50:
            lock_msg = f">> LOCKING DIGITAL AUDIO STREAM ... [{stn_name}] <<"
        elif target_w >= 30:
            lock_msg = f">> LOCKING STREAM: {stn_name} <<"
        elif target_w >= 18:
            lock_msg = f">> LOCK: {stn_name} <<"
        else:
            lock_msg = f">> {stn_name} <<"

        rows = []
        lock_row_idx = min(2, total_rows // 2) if total_rows > 3 else (1 if total_rows > 1 else -1)

        for r in range(total_rows):
            if r == 0:
                centered_tape = tape.center(target_w)
                rows.append(fit_row(f"{c_warn}\033[1m{centered_tape}\033[22m{RST}", target_w))
            elif r == lock_row_idx:
                centered_lock = lock_msg.center(target_w)
                rows.append(fit_row(f"{c_accent}\033[1m{centered_lock}\033[22m{RST}", target_w))
            else:
                # one call per row, not per cell: 2.3x faster, same uniform noise
                row_str = f"{c_dim}{''.join(random.choices(STATIC_CHARS, k=target_w))}{RST}"
                rows.append(fit_row(row_str, target_w))

        return rows


    def get_marquee_text(self, text: str, target_w: int, frame: int = 0) -> str:
        """Seamless scrolling ticker, exactly target_w cells wide.

        Offsets and slices are measured in cells, not codepoints. Track titles
        come from live APIs and routinely contain accented or CJK text; the old
        version scrolled with len() and sliced with [offset:offset+w], so for
        those titles the slice was the wrong width and the fallback truncation
        made the ticker visibly jitter and shrink.
        """
        if target_w <= 0:
            return ""
        slots = cell_slots(f"~~~ {text} ~~~     ")
        n = len(slots)
        if n == 0:
            return " " * target_w

        if self.is_playing and not self.is_stopped:
            # time-based, so scroll speed does not change with the frame rate
            self.marquee_offset = int(self.t_sec * MARQUEE_CHARS_PER_SEC) % n

        offset = self.marquee_offset % n
        out = []
        width = 0
        k = 0
        while width < target_w:
            slot = slots[(offset + k) % n]
            k += 1
            if not slot:
                out.append(" ")          # second half of a wide glyph
                width += 1
                continue
            w = char_width(slot[0])
            if width + w > target_w:
                out.append(" ")          # wide glyph would overflow the field
                width += 1
                continue
            out.append(slot)
            width += w
            if w == 2:
                k += 1                   # skip our own continuation slot
        return "".join(out)


    def render_button(self, idx: int, label: str, t_cfg: dict, active: bool = False, modern: bool = False) -> str:
        is_flashing = (self.button_flash[idx] > 0)
        c_accent = t_cfg["_c_accent"]
        b_l, b_r = ("(", ")") if modern else ("[", "]")

        if is_flashing:
            return f"\033[48;2;255;210;40m\033[38;2;10;20;30m\033[1m{b_l} {label} {b_r}{RST}"
        else:
            if active:
                return f"{c_accent}{b_l} {label} {b_r}{RST}"
            else:
                return f"{C_BTN_IDLE}{b_l} {label} {b_r}{RST}"

    def render_transport_bar(self, inner_w: int, t_cfg: dict, bg_col: str = "", modern: bool = False) -> str:
        """Render responsive transport controls fitting strictly within inner_w columns."""
        play_lbl_lg = ("❚❚ PAUSE" if modern else "|| PAUSE") if (self.is_playing and not self.is_stopped) else "▶ PLAY  "
        play_lbl_sm = ("❚❚ Pause" if modern else "❚❚ Pause") if (self.is_playing and not self.is_stopped) else "▶ Play  "
        play_lbl_xs = "❚❚" if (self.is_playing and not self.is_stopped) else "▶ "

        loop_lbl_lg = ("⟳ Loop" if modern else "⟳ LOOP ●") if self.repeat_mode else ("⟳ Loop" if modern else "⟳ LOOP ○")
        loop_lbl_sm = "⟳ Loop" if modern else "⟳ LOOP"
        loop_lbl_xs = "⟳"

        prev_lbl_lg = "◀ Prev" if modern else "|◀ PREV"
        prev_lbl_sm = "◀ Prev" if modern else "◀ PREV"
        prev_lbl_xs = "◀"

        next_lbl_lg = "Next ▶" if modern else "NEXT ▶|"
        next_lbl_sm = "Next ▶" if modern else "NEXT ▶"
        next_lbl_xs = "▶"

        if inner_w >= 68:
            b0 = self.render_button(0, loop_lbl_lg, t_cfg, active=self.repeat_mode, modern=modern)
            b1 = self.render_button(1, prev_lbl_lg, t_cfg, modern=modern)
            b2 = self.render_button(2, play_lbl_lg, t_cfg, active=(self.is_playing and not self.is_stopped), modern=modern)
            b3 = self.render_button(3, next_lbl_lg, t_cfg, modern=modern)
            gap = "      "
        elif inner_w >= 54:
            b0 = self.render_button(0, loop_lbl_sm, t_cfg, active=self.repeat_mode, modern=modern)
            b1 = self.render_button(1, prev_lbl_sm, t_cfg, modern=modern)
            b2 = self.render_button(2, play_lbl_sm, t_cfg, active=(self.is_playing and not self.is_stopped), modern=modern)
            b3 = self.render_button(3, next_lbl_sm, t_cfg, modern=modern)
            gap = "   "
        elif inner_w >= 44:
            b0 = self.render_button(0, loop_lbl_xs, t_cfg, active=self.repeat_mode, modern=modern)
            b1 = self.render_button(1, prev_lbl_xs, t_cfg, modern=modern)
            b2 = self.render_button(2, play_lbl_xs, t_cfg, active=(self.is_playing and not self.is_stopped), modern=modern)
            b3 = self.render_button(3, next_lbl_xs, t_cfg, modern=modern)
            gap = "  "
        else:
            b0 = self.render_button(0, loop_lbl_xs, t_cfg, active=self.repeat_mode, modern=modern)
            b1 = self.render_button(1, prev_lbl_xs, t_cfg, modern=modern)
            b2 = self.render_button(2, play_lbl_xs, t_cfg, active=(self.is_playing and not self.is_stopped), modern=modern)
            b3 = self.render_button(3, next_lbl_xs, t_cfg, modern=modern)
            gap = " "

        btns = f"{b0}{gap}{b1}{gap}{b2}{gap}{b3}"
        sp = max(0, (inner_w - str_width(btns)) // 2)
        return fit_row(f"{' ' * sp}{btns}", inner_w, bg_col)

    def render_status_bar(self, inner_w: int, t_cfg: dict, style_label: str = "", bg_col: str = "", mode: str = "box") -> str:
        """Render responsive footer status bar fitting strictly within inner_w columns."""
        c_hint_key = t_cfg["_c_accent"]
        c_hint_txt = C_HINT_TEXT

        # Fullest wording first; take the first that fits, so the bar is never
        # cut short. Fixed width thresholds used to truncate it at some sizes
        # (Modern Neo at 70 columns ended "[Q] Qui").
        style = f" Style ({style_label})" if style_label else " Style"
        full = [("[D]", style), ("[V]", " Viz"), ("[T]", " Theme"), ("[L]", " Stations"),
                ("[A]", " Add"), ("[+/-]", " Vol"), ("[Q]", " Quit")]
        variants = (
            (full, "   "),
            (full, "  "),
            ([("[D]", " Style"), ("[V]", " Viz"), ("[T]", " Theme"), ("[L]", " List"),
              ("[A]", " Add"), ("[+/-]", " Vol"), ("[Q]", " Quit")], "  "),
            ([("[D]", "Style"), ("[V]", "Viz"), ("[T]", "Theme"), ("[L]", "List"),
              ("[A]", "Add"), ("[+/-]", "Vol"), ("[Q]", "Quit")], "  "),
            ([("[D]", "Style"), ("[V]", "Viz"), ("[T]", "Thm"), ("[L]", "Stn"),
              ("[A]", "Add"), ("[Q]", "Quit")], "  "),
        )
        room = inner_w - (3 if mode == "bracket" else 0)
        for items, sep in variants:
            txt = sep.join(f"{c_hint_key}{k}{c_hint_txt}{v}" for k, v in items)
            if str_width(txt) <= room:
                break

        if mode == "box":
            sp = max(0, (inner_w - str_width(txt)) // 2)
            return fit_row(f"{' ' * sp}{txt}", inner_w, bg_col)
        elif mode == "bracket":
            c_frame = t_cfg["_c_accent"]
            rem_dashes = max(0, inner_w - str_width(txt) - 3)
            fill_part = f"─ {txt} {c_frame}{'─' * rem_dashes}"
            return fit_row(fill_part, inner_w, fill_char="─")
        else:
            sp = max(0, (inner_w - str_width(txt)) // 2)
            return fit_row(f"{' ' * sp}{txt}", inner_w)

    def render_drawer_rows(self, lcd_inner_w: int, t_cfg: dict, max_rows: int = 8) -> list:
        """Render the station directory as exactly max_rows rows, lcd_inner_w wide:
        a header plus as many stations as the panel has room for. It used to be
        a fixed 7, which left tall panels mostly empty and let the selection
        scroll out of view in panels shorter than 8 rows."""
        c_bright = t_cfg["_c_bright"]
        c_accent = t_cfg["_c_accent"]
        c_dim = t_cfg["_c_dim"]
        c_warn = t_cfg["_c_warn"]

        total_stns = len(PLAYLIST)
        visible_slots = max(1, max_rows - 1)
        self.drawer_page = visible_slots

        # Keep selected item visible in scrolling window
        if self.drawer_selected_idx < self.drawer_scroll_offset:
            self.drawer_scroll_offset = self.drawer_selected_idx
        elif self.drawer_selected_idx >= self.drawer_scroll_offset + visible_slots:
            self.drawer_scroll_offset = self.drawer_selected_idx - visible_slots + 1

        # Bound scroll offset
        max_offset = max(0, total_stns - visible_slots)
        self.drawer_scroll_offset = max(0, min(max_offset, self.drawer_scroll_offset))

        rows = []
        start_num = self.drawer_scroll_offset + 1
        end_num = min(total_stns, self.drawer_scroll_offset + visible_slots)
        up_arr = "▲" if self.drawer_scroll_offset > 0 else " "
        down_arr = "▼" if (self.drawer_scroll_offset + visible_slots < total_stns) else " "

        hdr = f"  {c_accent}\033[1mSTATION DIRECTORY\033[22m {c_bright}({start_num:02d}-{end_num:02d} of {total_stns:02d}) {c_dim}{up_arr} [▲/▼: Scroll, Enter: Tune, L/Esc: Close] {down_arr}"
        rows.append(fit_row(hdr, lcd_inner_w))

        for slot in range(visible_slots):
            i = self.drawer_scroll_offset + slot
            if i < total_stns:
                stn = PLAYLIST[i]
                is_cur = (i == self.current_track_idx)
                is_sel = (i == self.drawer_selected_idx)

                cursor = "►" if is_sel else ("●" if is_cur else " ")
                prov_str = f"[{stn.get('provider', 'STREAM').upper():<8}]"
                name_str = stn['station'][:20].ljust(20)
                genre_str = f"[{stn.get('genre', 'RADIO'):<6}]"

                sig_val = int(str(stn.get('signal', '95%')).replace('%', ''))
                sig_slots = 12
                sig_filled = int((sig_val / 100.0) * sig_slots)
                sig_bar = "█" * sig_filled + "░" * (sig_slots - sig_filled)

                bitrate_str = stn.get('bitrate', '128kbps')
                sig_str = f"{stn.get('signal', '95%'):<4}"

                if is_sel:
                    line_str = f" {c_bright}\033[1m{cursor} {i+1:02d}. {name_str} {c_accent}{prov_str} {c_warn}{genre_str} {c_dim}SIG:[{sig_bar}] {sig_str} {c_bright}{bitrate_str}\033[22m"
                else:
                    line_str = f" {c_dim}{cursor} {i+1:02d}. {name_str} {prov_str} {genre_str} SIG:[{sig_bar}] {sig_str} {bitrate_str}"
                rows.append(fit_row(line_str, lcd_inner_w))
            else:
                rows.append(fit_row(" ", lcd_inner_w))

        return rows

    def render_station_editor(self, cols: int, rows: int, t_cfg: dict) -> list:
        """The [A] add-station form: a centred box, exactly rows x cols, in the
        current theme. It replaces the whole frame in every design style, since
        some styles' panels are only 4-5 rows tall."""
        ed = self.editor
        c_frame, c_accent, c_bright = t_cfg["_c_frame"], t_cfg["_c_accent"], t_cfg["_c_bright"]
        c_dim, c_warn = t_cfg["_c_dim"], t_cfg["_c_warn"]
        W = min(cols - 4, 84)
        inner = W - 2
        val_w = max(8, inner - 17)
        labels = {"name": "name", "url": "stream url", "freq": "freq", "genre": "genre",
                  "bitrate": "bitrate", "provider": "provider"}

        body = [f" {c_dim}Adds a station to the end of stations.json, then tunes to it.{RST}", ""]
        for i, field in enumerate(EDITOR_FIELDS):
            active = i == ed["field"]
            mark = f"{c_accent}►{RST}" if active else " "
            if field == "provider":
                p = ed["provider"]
                if p == "auto":
                    p = f"auto ({MetadataScraper.provider_of({'url': ed['fields']['url']})})"
                value, cursor = f"‹ {p} ›", ""
            else:
                value = ed["fields"][field]
                if str_width(value) > val_w - 1:          # keep the end of a long URL in view
                    while str_width(value) > val_w - 2:
                        value = value[1:]
                    value = "…" + value
                cursor = f"{c_accent}▌" if active else ""
            text = c_bright if active else ""
            body.append(f" {mark} {c_dim}{labels[field]:>10}{RST}  {text}{value}{cursor}{RST}")
        body.append("")
        problem = ed["error"] or self._editor_problem()
        if problem:
            body.append(f" {c_warn}⚠ {problem}{RST}")
        else:
            body.append(f" {c_bright}✓ ready - Enter saves and tunes{RST}")
        body.append("")
        for hint in ("Enter save & tune · Esc cancel · Tab/↑↓ field · ←→ provider · Ctrl-U clear",
                     "Enter save · Esc cancel · Tab/↑↓ field · ←→ provider",
                     "Enter save · Esc cancel · Tab next"):
            if str_width(hint) + 1 <= inner:
                break
        body.append(f" {c_dim}{hint}{RST}")

        title = " ADD STATION "
        box = [f"{c_frame}╭─{c_accent}\033[1m{title}\033[22m{c_frame}"
               f"{'─' * max(0, inner - 1 - len(title))}╮{RST}"]
        box += [f"{c_frame}│{RST}{fit_row(line, inner)}{c_frame}│{RST}" for line in body]
        box.append(f"{c_frame}╰{'─' * inner}╯{RST}")

        pad = " " * max(0, (cols - W) // 2)
        blank = fit_row("", cols)
        out = [blank] * max(0, (rows - len(box)) // 2)
        out += [fit_row(pad + r, cols) for r in box]
        while len(out) < rows:
            out.append(blank)
        return out[:rows]

    def handle_key(self, key: str) -> bool:
        """Act on one key. Returns False to quit."""
        if self.editor is not None:
            return self._editor_key(key)
        if key in ("q", "Q", "QUIT"):
            return False
        if key == "ESC":
            if self.show_drawer:
                self.show_drawer = False
                return True
            return False
        if key in ("v", "V"):
            self.cycle_viz_mode()
        elif key in ("t", "T"):
            self.cycle_theme()
        elif key in ("d", "D"):
            self.cycle_design_style()
        elif key in ("l", "L"):
            self.toggle_drawer()
        elif key in ("a", "A"):
            self.open_station_editor()
        elif self.show_drawer:
            if key == "UP":
                self.drawer_selected_idx = (self.drawer_selected_idx - 1) % len(PLAYLIST)
            elif key == "DOWN":
                self.drawer_selected_idx = (self.drawer_selected_idx + 1) % len(PLAYLIST)
            elif key == "PAGEUP":
                self.drawer_selected_idx = max(0, self.drawer_selected_idx - self.drawer_page)
            elif key == "PAGEDOWN":
                self.drawer_selected_idx = min(len(PLAYLIST) - 1, self.drawer_selected_idx + self.drawer_page)
            elif key == "HOME":
                self.drawer_selected_idx = 0
            elif key == "END":
                self.drawer_selected_idx = len(PLAYLIST) - 1
            elif key == "ENTER":
                self.select_preset(self.drawer_selected_idx)
                self.show_drawer = False
        elif key == "SPACE":
            self.toggle_play()
        elif key in ("n", "N", "RIGHT"):
            self.next_track()
        elif key in ("p", "P", "LEFT"):
            self.prev_track()
        elif key in ("s", "S"):
            self.stop_playback()
        elif key in ("r", "R"):
            self.toggle_repeat()
        elif key in ("m", "M"):
            self.toggle_mute()
        elif key in ("UP", "+", "="):
            self.adjust_volume(+5)
        elif key in ("DOWN", "-", "_"):
            self.adjust_volume(-5)
        elif key.isdigit() and 1 <= int(key) <= len(PLAYLIST):
            self.select_preset(int(key) - 1)
        return True

    def adjust_volume(self, delta: int):
        if self.is_muted:
            self.is_muted = False
            self.stream_player.set_mute(False)
        self.volume = max(0, min(100, self.volume + delta))
        self.stream_player.set_volume(self.volume)

    def emit_frame(self, lines: list) -> int:
        """Write only the rows that changed since the previous frame.

        The old loop re-serialised and re-sent the whole screen every frame: a
        measured 563 KB/s at 101x54 while playing, and the same 563 KB/s while
        paused, where only 0.2% of rows actually differ. Damage tracking cuts
        that by roughly 9x playing and ~490x paused, and removes the same
        multiple of parsing and repaint work from the terminal emulator on the
        other end of the pty - the larger of the two costs.

        Rows are addressed absolutely and each is prefixed with a reset, so a
        row never depends on colour state left behind by the row above it.
        """
        prev = self._prev_lines
        if prev is None or len(prev) != len(lines):
            body = "\n".join(
                "\033[0m" + (l if l.endswith("\033[K") else l + "\033[K") for l in lines)
            payload = "\033[H" + body + "\033[J"
        else:
            parts = ["\033[%d;1H\033[0m%s\033[K" % (i + 1, line)
                     for i, line in enumerate(lines) if line != prev[i]]
            if not parts:
                self._prev_lines = lines
                return 0
            payload = "".join(parts)
        sys.stdout.write(payload)
        sys.stdout.flush()
        self._prev_lines = lines
        return len(payload)

    def run(self):
        # Alternate screen buffer, hide cursor, clear
        sys.stdout.write("\033[?1049h\033[?25l\033[2J\033[H")
        sys.stdout.flush()

        with RawInput() as user_input:
            try:
                frame = 0
                next_deadline = time.monotonic()
                while self.running:
                    # The add-station form takes every key, so a pasted URL
                    # arrives whole; otherwise the cap guards against a paste
                    # queueing dozens of station changes.
                    limit = None if self.editor is not None else MAX_KEYS_PER_FRAME
                    for key in user_input.get_keys(limit):
                        if not self.handle_key(key):
                            self.running = False
                            break
                    if not self.running:
                        break

                    self.t_sec = time.monotonic() - self.t0
                    self.update_physics()

                    t_cfg = THEMES[self.theme_idx]
                    cols, rows = shutil.get_terminal_size((104, 30))

                    if (cols, rows) != (self.last_cols, self.last_rows) or self.needs_clear:
                        self.last_cols, self.last_rows = cols, rows
                        self.needs_clear = False
                        self._prev_lines = None          # force a full repaint
                        sys.stdout.write("\033[2J\033[H")
                        sys.stdout.flush()

                    if cols < self.min_cols or rows < self.min_rows:
                        sys.stdout.write(self.render_btop_size_warning(cols, rows))
                        sys.stdout.flush()
                        self._prev_lines = None
                    else:
                        lines = self.render_frame(cols, rows, t_cfg, frame)
                        # Never emit more rows than the terminal has: one row too
                        # many scrolls the whole frame on every tick.
                        if len(lines) > rows:
                            lines = lines[:rows]
                        self.emit_frame(lines)

                    frame += 1

                    # Adaptive pacing with drift correction. Waiting on stdin
                    # rather than sleeping keeps keys instant at the idle rate.
                    active = (self.is_playing and not self.is_stopped
                              and self.tuning_glitch_frames == 0)
                    next_deadline += ACTIVE_FRAME_TIME if active else IDLE_FRAME_TIME
                    now = time.monotonic()
                    if next_deadline < now:
                        next_deadline = now              # fell behind; resync
                    user_input.wait_readable(next_deadline - now)
            except Exception:
                LOG.exception("fatal error in main loop")
                raise
            finally:
                self.cleanup()

    def render_frame(self, cols: int, rows: int, t_cfg: dict, frame: int) -> list:
        if self.editor is not None:
            return self.render_station_editor(cols, rows, t_cfg)
        if self.design_style == 1:
            return self.render_modern_neo(cols, rows, t_cfg, frame)
        elif self.design_style == 2:
            return self.render_minimal_zen(cols, rows, t_cfg, frame)
        elif self.design_style == 3:
            return self.render_cyberpunk(cols, rows, t_cfg, frame)
        elif self.design_style == 4:
            return self.render_tide(cols, rows, t_cfg)
        else:
            return self.render_retro_hifi(cols, rows, t_cfg, frame)

    def _tide_layout(self, name: str, cols: int, rows: int) -> dict:
        """TIDE's form-factor selection: wrap the station name, pick the largest
        type scale that fits, and give each letter its slice of the spectrum.
        It depends only on the name and the terminal size, so it runs once per
        station or resize, not per frame."""
        key = (name, cols, rows)
        hit = self._tide_cache.get("layout")
        if hit is not None and hit[0] == key:
            return hit[1]

        # Uppercase, fold accents onto their base letter, and turn anything the
        # font cannot draw into a space so it never claims a band.
        text = unicodedata.normalize("NFKD", name.upper())
        text = "".join(c if c in FONT_5X7 else " " for c in text if not unicodedata.combining(c))
        words = text.split() or ["RADIO"]
        avail = rows - 5          # 2 margin rows above the type, 3 transport rows below

        def wrap(max_chars):
            lines, cur = [], ""
            for wd in words:
                if not cur:
                    cur = wd
                elif len(cur) + 1 + len(wd) <= max_chars:
                    cur += " " + wd
                else:
                    lines.append(cur)
                    cur = wd
            lines.append(cur)
            return lines

        def height_px(scale, n_lines):
            return n_lines * 7 * scale + (n_lines - 1) * 2 * scale

        for scale in range(6, 0, -1):
            gap = max(1, scale // 2)
            max_chars = (cols + gap) // (5 * scale + gap)
            lines = wrap(max_chars)
            if (max(len(l) for l in lines) <= max_chars
                    and (height_px(scale, len(lines)) + 1) // 2 <= avail):
                break
        else:
            # Nothing fits whole: smallest type, long words and extra lines cut.
            scale, gap = 1, 1
            max_chars = (cols + 1) // 6
            words = [wd[:max_chars] for wd in words]
            lines = wrap(max_chars)[:max(1, (2 * avail + 2) // 9)]

        glyph_h = 7 * scale
        widths = [len(l) * 5 * scale + (len(l) - 1) * gap for l in lines]
        block_w = min(cols, max(widths))
        block_h = height_px(scale, len(lines))
        block_h += block_h & 1
        line_of_py = [0] * block_h
        x_off, tops, baselines, line_off = [], [], [], []
        nb = len(self.band_heights)
        pitch = 5 * scale + gap
        bands = []
        n = 0
        for ln, line in enumerate(lines):
            top = ln * (glyph_h + 2 * scale)
            x_off.append(max(0, (block_w - widths[ln]) // 2))     # centre each line
            tops.append(top)
            baselines.append(top + glyph_h)
            line_off.append(n)
            n += sum(1 for c in line if c != " ")
            for py in range(top, top + glyph_h):
                line_of_py[py] = ln
            # Bands follow horizontal position, as the gradient follows height:
            # every line runs low to high left to right, and the middle of the
            # spectrum sits in the middle of the screen however the name wraps.
            # Letter spans meet halfway between letters, so spaces split between
            # their neighbours, and the widest line covers all the bands.
            centres = [x_off[ln] + j * pitch + 5 * scale / 2 for j, c in enumerate(line) if c != " "]
            edges = ([x_off[ln]] + [(a + b) / 2 for a, b in zip(centres, centres[1:])]
                     + [x_off[ln] + widths[ln]])
            for b_left, b_right in zip(edges, edges[1:]):
                lo = min(nb - 1, max(0, int(b_left * nb / block_w)))
                hi = min(nb, max(lo + 1, int(b_right * nb / block_w)))
                bands.append((lo, hi))

        lay = {"key": key, "avail": avail, "scale": scale, "gap": gap, "lines": lines,
               "block_w": block_w, "block_h": block_h, "x_off": x_off, "tops": tops,
               "baselines": baselines, "line_off": line_off, "line_of_py": line_of_py,
               "bands": bands, "n": n}
        self._tide_cache["layout"] = (key, lay)
        return lay

    def render_retro_hifi(self, cols: int, rows: int, t_cfg: dict, frame: int) -> list:
        current_track = PLAYLIST[self.current_track_idx]
        C_FRAME = t_cfg["_c_frame"]
        C_TITLE_BG = ""
        C_TITLE_FG = t_cfg["_c_title_fg"]
        C_TAG_CYAN = t_cfg["_c_accent"]
        C_DECK_BG = ""
        C_LCD_BG = ""
        C_LCD_BORDER = t_cfg["_c_lcd_border"]
        C_LCD_DIM = t_cfg["_c_dim"]
        C_LCD_BRIGHT = t_cfg["_c_bright"]
        C_LCD_AMBER = t_cfg["_c_warn"]
        C_CYAN = t_cfg["_c_accent"]
        C_CYAN_DIM = C_DIM_CYAN
        C_HINT_KEY = t_cfg["_c_accent"]
        C_HINT_TXT = C_HINT_TEXT

        is_portrait_tall = (rows >= 32 and cols >= 70)
        is_compact_80 = (cols < 102 and not is_portrait_tall)

        if is_portrait_tall:
            # === STUDIO TOWER MODE (e.g. 101 x 54) ===
            W = min(100, cols - (cols % 2))
            inner_w = W - 2
            margin_left = max(0, (cols - W) // 2)
            pad = " " * margin_left

            if rows >= 40:
                avail_dir_slots = min(len(PLAYLIST), 16)
                viz_h = max(8, min(24, rows - 32 - 2))
            else:
                viz_h = 8
                avail_dir_slots = min(len(PLAYLIST), max(6, rows - 16 - viz_h))

            chassis_h = 16 + viz_h + avail_dir_slots
            top_space = max(0, (rows - chassis_h) // 2)
            lines = ["" for _ in range(top_space)]

            viz_tag = self.viz_names[self.viz_mode]
            title_txt = f"{C_TITLE_BG}{C_CYAN} ♫ {C_TITLE_FG}\033[1mtermbeat\033[22m {C_CYAN_DIM}// STUDIO TOWER{RST}"
            right_tag = f"{C_TAG_CYAN}[ {viz_tag} ] [RETRO HI-FI] [ FM STEREO ]{RST}"
            sp = max(0, inner_w - str_width(title_txt) - str_width(right_tag))
            title_bar = f"{title_txt}{C_TITLE_BG}{' ' * sp}{right_tag}"
            lines.append(f"{pad}{C_FRAME}╭{'─' * inner_w}╮{RST}")
            lines.append(f"{pad}{C_FRAME}│{fit_row(title_bar, inner_w, C_TITLE_BG)}{C_FRAME}│{RST}")
            lines.append(f"{pad}{C_FRAME}├{'─' * inner_w}┤{RST}")

            viz_w = inner_w - 4
            v_hdr = f"── {viz_tag} (HIGH-RESOLUTION) ──"
            v_top = fit_row(f"─{v_hdr}", viz_w, fill_char="─")
            lines.append(f"{pad}{C_FRAME}│ {C_LCD_BORDER}╭{v_top}╮{RST} {C_FRAME}│{RST}")
            t_sec = self.t_sec
            if self.tuning_glitch_frames > 0:
                v_rows = self.get_tuning_glitch_rows(viz_w, viz_h, t_cfg)
            elif self.viz_mode == 0:
                v_rows = self.get_equalizer_rows(viz_w, viz_h, t_cfg)
            else:
                v_rows = self.get_oscilloscope_rows(viz_w, viz_h, t_sec, t_cfg)
            for r in range(viz_h):
                v_str = v_rows[r] if r < len(v_rows) else " " * viz_w
                lines.append(f"{pad}{C_FRAME}│ {C_LCD_BORDER}│{C_LCD_BG}{fit_row(v_str, viz_w, C_LCD_BG)}{C_LCD_BORDER}│{RST} {C_FRAME}│{RST}")
            lines.append(f"{pad}{C_FRAME}│ {C_LCD_BORDER}╰{'─' * viz_w}╯{RST} {C_FRAME}│{RST}")
            lines.append(f"{pad}{C_FRAME}├{'─' * inner_w}┤{RST}")

            try:
                listeners_cnt = int(current_track.get("listeners", 0))
            except Exception:
                listeners_cnt = 0
            bit_tag = f"{current_track.get('bitrate', '128kbps')}"
            stats_str = f"{listeners_cnt:,} Online  {bit_tag}" if listeners_cnt > 0 else bit_tag
            stn_line = f"  STATION: {C_CYAN}\033[1m{current_track['station'].upper()}\033[22m{RST}"
            stn_sp = max(1, inner_w - str_width(stn_line) - str_width(stats_str) - 2)
            np_r0 = f"{stn_line}{' ' * stn_sp}{C_CYAN}{stats_str}  "

            track_w = max(32, min(56, int((inner_w - 14) * 0.58)))
            track_disp = self.get_marquee_text(current_track['track'], track_w, frame)
            np_r1 = f"  TRACK:   {C_LCD_BRIGHT}\033[1m{track_disp}\033[22m  "

            mins = self.track_elapsed // 60
            secs = self.track_elapsed % 60
            timer_colon = self.timer_colon()
            if self.track_duration and self.track_duration > 0:
                d_mins = self.track_duration // 60
                d_secs = self.track_duration % 60
                time_str = f"Elapsed:  {mins:02d}{timer_colon}{secs:02d} / {d_mins:02d}:{d_secs:02d}"
            else:
                time_str = f"Elapsed:  {mins:02d}{timer_colon}{secs:02d}  [LIVE]"
            status_txt, status_col = self.status_badge(t_cfg)
            np_r2 = f"  {C_LCD_DIM}{time_str}{' ' * max(2, inner_w - str_width(time_str) - str_width(status_txt) - 4)}{status_col}\033[1m{status_txt}\033[22m  "

            lines.append(f"{pad}{C_FRAME}│{fit_row(np_r0, inner_w, C_DECK_BG)}{C_FRAME}│{RST}")
            lines.append(f"{pad}{C_FRAME}│{fit_row(np_r1, inner_w, C_DECK_BG)}{C_FRAME}│{RST}")
            lines.append(f"{pad}{C_FRAME}│{fit_row(np_r2, inner_w, C_DECK_BG)}{C_FRAME}│{RST}")

            lines.append(f"{pad}{C_FRAME}│{self.render_transport_bar(inner_w, t_cfg, C_DECK_BG)}{C_FRAME}│{RST}")

            slots = max(8, min(24, (inner_w - 28) // 2))
            filled = int((self.volume / 100.0) * slots)
            vol_bar = f"{C_CYAN}{'▰' * filled}{C_CYAN_DIM}{'▱' * (slots - filled)}{RST}"
            vol_str = f"{C_VOL_LABEL}VOLUME: [{vol_bar}]   {C_CYAN}{self.volume:3d}%{RST}"
            v_sp1 = max(0, (inner_w - str_width(vol_str)) // 2)
            lines.append(f"{pad}{C_FRAME}│{fit_row(' ' * v_sp1 + vol_str, inner_w, C_DECK_BG)}{C_FRAME}│{RST}")
            lines.append(f"{pad}{C_FRAME}├{'─' * inner_w}┤{RST}")

            dir_hdr = f"  {C_CYAN}\033[1mSTATION DIRECTORY\033[22m {C_LCD_BRIGHT}(All {len(PLAYLIST)} Channels Online)  {C_LCD_DIM}[N/P: Tune, Space: Pause]{RST}"
            lines.append(f"{pad}{C_FRAME}│{fit_row(dir_hdr, inner_w, C_TITLE_BG)}{C_FRAME}│{RST}")
            for i in range(avail_dir_slots):
                stn = PLAYLIST[i]
                is_cur = (i == self.current_track_idx)
                cur_marker = f"{C_CYAN}\033[1m●\033[22m" if is_cur else " "
                p_tag = f"[{stn.get('provider', 'STREAM').upper():<7}]"
                s_name = stn['station'][:22].ljust(22)
                g_tag = f"[{stn.get('genre', 'RADIO'):<6}]"
                b_tag = stn.get('bitrate', '128k')
                try:
                    l_cnt = f"{int(stn.get('listeners', 0)):,} onl"
                except Exception:
                    l_cnt = ""
                if is_cur:
                    stn_line = f"  {cur_marker} {C_LCD_BRIGHT}\033[1m{i+1:02d}. {s_name}\033[22m {C_CYAN}{p_tag} {C_LCD_AMBER}{g_tag}{RST} {C_LCD_DIM}{l_cnt:>10}  {b_tag}{RST}"
                else:
                    stn_line = f"  {cur_marker} {C_LCD_DIM}{i+1:02d}. {s_name} {p_tag} {g_tag} {l_cnt:>10}  {b_tag}{RST}"
                lines.append(f"{pad}{C_FRAME}│{fit_row(stn_line, inner_w, C_DECK_BG)}{C_FRAME}│{RST}")

            lines.append(f"{pad}{C_FRAME}├{'─' * inner_w}┤{RST}")
            lines.append(f"{pad}{C_FRAME}│{self.render_status_bar(inner_w, t_cfg, 'Retro', C_TITLE_BG, mode='box')}{C_FRAME}│{RST}")
            lines.append(f"{pad}{C_FRAME}╰{'─' * inner_w}╯{RST}")
            while len(lines) < rows:
                lines.append("")
            return lines

        elif is_compact_80:
            # === DECK-78 COMPACT MODE (e.g. 79 x 19) ===
            W = min(78, cols - (cols % 2))
            inner_w = W - 2
            margin_left = max(0, (cols - W) // 2)
            pad = " " * margin_left

            chassis_h = 15
            top_space = max(0, (rows - chassis_h) // 2)
            lines = ["" for _ in range(top_space)]

            viz_tag = self.viz_names[self.viz_mode]
            title_txt = f"{C_TITLE_BG}{C_CYAN} ♫ {C_TITLE_FG}\033[1mtermbeat\033[22m"
            tag_str = f"{C_TAG_CYAN}[ {viz_tag} ] [FM STEREO]{RST}"
            sp = max(0, inner_w - str_width(title_txt) - str_width(tag_str))
            t_bar = f"{title_txt}{C_TITLE_BG}{' ' * sp}{tag_str}"
            lines.append(f"{pad}{C_FRAME}╭{'─' * inner_w}╮{RST}")
            lines.append(f"{pad}{C_FRAME}│{fit_row(t_bar, inner_w, C_TITLE_BG)}{C_FRAME}│{RST}")
            lines.append(f"{pad}{C_FRAME}├{'─' * inner_w}┤{RST}")

            lcd_w = inner_w - 4
            left_viz_w = 22
            right_w = lcd_w - left_viz_w - 3

            stn_name = current_track['station'].upper()
            try:
                l_cnt = f"{int(current_track.get('listeners', 0)):,} onl"
            except Exception:
                l_cnt = ""
            stn_sp = max(1, right_w - str_width(stn_name) - str_width(l_cnt))
            c_r0 = f"{C_CYAN}\033[1m{stn_name}\033[22m{' ' * stn_sp}{C_LCD_DIM}{l_cnt}"

            track_disp = self.get_marquee_text(current_track['track'], right_w, frame)
            c_r1 = f"{C_LCD_BRIGHT}\033[1m{track_disp}\033[22m"

            status_txt, status_col = self.status_badge(t_cfg, compact=True)
            genre_lbl = f"{current_track['genre']} / STEREO"
            g_sp = max(1, right_w - str_width(genre_lbl) - str_width(status_txt))
            c_r2 = f"{C_LCD_DIM}{genre_lbl}{' ' * g_sp}{status_col}\033[1m{status_txt}\033[22m"

            mins = self.track_elapsed // 60
            secs = self.track_elapsed % 60
            timer_colon = self.timer_colon()
            if self.track_duration and self.track_duration > 0:
                d_mins = self.track_duration // 60
                d_secs = self.track_duration % 60
                time_str = f"Elapsed: {mins:02d}{timer_colon}{secs:02d} / {d_mins:02d}:{d_secs:02d}"
            else:
                time_str = f"Elapsed: {mins:02d}{timer_colon}{secs:02d} [LIVE]"
            c_r3 = f"{C_LCD_BRIGHT}{time_str:<{right_w}}"
            c_r4 = " " * right_w

            r_rights = [c_r0, c_r1, c_r2, c_r3, c_r4]

            lines.append(f"{pad}{C_FRAME}│ {C_LCD_BORDER}╭{'─' * lcd_w}╮{RST} {C_FRAME}│{RST}")
            t_sec = self.t_sec
            if self.show_drawer:
                drawer_items = self.render_drawer_rows(lcd_w, t_cfg, 5)
                for r in range(5):
                    r_str = drawer_items[r] if r < len(drawer_items) else " " * lcd_w
                    lines.append(f"{pad}{C_FRAME}│ {C_LCD_BORDER}│{C_LCD_BG}{fit_row(r_str, lcd_w, C_LCD_BG)}{C_LCD_BORDER}│{RST} {C_FRAME}│{RST}")
            else:
                if self.tuning_glitch_frames > 0:
                    v_rows = self.get_tuning_glitch_rows(left_viz_w, 5, t_cfg)
                elif self.viz_mode == 0:
                    v_rows = self.get_equalizer_rows(left_viz_w, 5, t_cfg)
                else:
                    v_rows = self.get_oscilloscope_rows(left_viz_w, 5, t_sec, t_cfg)
                for r in range(5):
                    v_str = v_rows[r] if r < len(v_rows) else " " * left_viz_w
                    row_c = f" {v_str}  {r_rights[r]} "
                    lines.append(f"{pad}{C_FRAME}│ {C_LCD_BORDER}│{C_LCD_BG}{fit_row(row_c, lcd_w, C_LCD_BG)}{C_LCD_BORDER}│{RST} {C_FRAME}│{RST}")

            lines.append(f"{pad}{C_FRAME}│ {C_LCD_BORDER}╰{'─' * lcd_w}╯{RST} {C_FRAME}│{RST}")

            lines.append(f"{pad}{C_FRAME}│{self.render_transport_bar(inner_w, t_cfg, C_DECK_BG)}{C_FRAME}│{RST}")

            slots = max(8, min(16, (inner_w - 24) // 2))
            filled = int((self.volume / 100.0) * slots)
            vol_bar = f"{C_CYAN}{'▰' * filled}{C_CYAN_DIM}{'▱' * (slots - filled)}{RST}"
            vol_str = f"{C_VOL_LABEL}VOLUME: [{vol_bar}]  {C_CYAN}{self.volume:3d}%{RST}"
            v_sp1 = max(0, (inner_w - str_width(vol_str)) // 2)
            lines.append(f"{pad}{C_FRAME}│{fit_row(' ' * v_sp1 + vol_str, inner_w, C_DECK_BG)}{C_FRAME}│{RST}")
            lines.append(f"{pad}{C_FRAME}├{'─' * inner_w}┤{RST}")

            lines.append(f"{pad}{C_FRAME}│{self.render_status_bar(inner_w, t_cfg, 'Retro', C_TITLE_BG, mode='box')}{C_FRAME}│{RST}")
            lines.append(f"{pad}{C_FRAME}╰{'─' * inner_w}╯{RST}")
            while len(lines) < rows:
                lines.append("")
            return lines

        else:
            # === STANDARD 102-COLUMN MODE ===
            W = 102
            inner_w = 100
            margin_left = max(0, (cols - W) // 2)
            pad = " " * margin_left

            chassis_h = 18
            top_space = max(0, (rows - chassis_h) // 2)
            lines = ["" for _ in range(top_space)]

            viz_tag = self.viz_names[self.viz_mode]
            style_tag = self.design_names[self.design_style]
            title_content = (
                f"{C_TITLE_BG}{C_CYAN} ♫ "
                f"{C_TITLE_FG}\033[1mtermbeat\033[22m"
            )
            loop_tag = f"{C_CYAN}\033[1m[ ⟳ LOOP ON ]\033[22m " if self.repeat_mode else f"{C_DIM_CYAN}[ ⟳ LOOP OFF ] "
            status_tag = f"{loop_tag}{C_TAG_CYAN}[ {viz_tag} ] [ FM STEREO ] {RST}"
            free_sp = inner_w - str_width(title_content) - str_width(status_tag)
            title_bar_str = f"{title_content}{C_TITLE_BG}{' ' * max(0, free_sp)}{status_tag}"

            lines.append(f"{pad}{C_FRAME}╭{'─' * inner_w}╮{RST}")
            lines.append(f"{pad}{C_FRAME}│{fit_row(title_bar_str, inner_w, C_TITLE_BG)}{C_FRAME}│{RST}")
            lines.append(f"{pad}{C_FRAME}├{'─' * inner_w}┤{RST}")

            lcd_inner_w = 92
            deck_margin = 3

            if self.show_drawer:
                drawer_rows = self.render_drawer_rows(lcd_inner_w, t_cfg)
                lcd_rows = [f"{C_LCD_BG}{r}{RST}" for r in drawer_rows]
            else:
                right_pane_w = 48
                try:
                    listeners_cnt = int(current_track.get("listeners", 0))
                except (ValueError, TypeError):
                    listeners_cnt = 0
                bit_tag = f"{current_track.get('bitrate', '128kbps')}"
                if listeners_cnt > 0:
                    stream_data = f"{listeners_cnt:,} Online  {bit_tag}"
                else:
                    stream_data = f"{bit_tag}"

                stn_disp = current_track['station'].upper()
                avail_stn_w = max(8, right_pane_w - 1 - str_width(stream_data))
                if str_width(stn_disp) > avail_stn_w:
                    stn_disp = stn_disp[:avail_stn_w - 1] + "…"
                stn_pad = max(1, right_pane_w - str_width(stn_disp) - str_width(stream_data))
                r0 = f"{C_CYAN}\033[1m{stn_disp}\033[22m{' ' * stn_pad}{C_CYAN}{stream_data}"

                ticker_disp = self.get_marquee_text(current_track['track'], right_pane_w, frame)
                r1 = f"{C_LCD_BRIGHT}\033[1m{ticker_disp}\033[22m"

                status_txt, status_col = self.status_badge(t_cfg)

                genre_lbl = f"Genre:    {current_track['genre']} / STEREO"
                genre_pad = max(1, right_pane_w - str_width(genre_lbl) - str_width(status_txt))
                r_genre = f"{C_LCD_DIM}{genre_lbl}{' ' * genre_pad}{status_col}\033[1m{status_txt}\033[22m"

                mins = self.track_elapsed // 60
                secs = self.track_elapsed % 60
                timer_colon = self.timer_colon()
                if self.track_duration and self.track_duration > 0:
                    d_mins = self.track_duration // 60
                    d_secs = self.track_duration % 60
                    time_str = f"Elapsed:  {mins:02d}{timer_colon}{secs:02d} / {d_mins:02d}:{d_secs:02d}"
                else:
                    time_str = f"Elapsed:  {mins:02d}{timer_colon}{secs:02d}  [LIVE]"
                r_time = f"{C_LCD_BRIGHT}{time_str:<{right_pane_w}}"

                r_rights = [
                    r0,
                    r1,
                    " " * right_pane_w,
                    r_genre,
                    " " * right_pane_w,
                    r_time,
                    " " * right_pane_w,
                    " " * right_pane_w,
                ]

                t_sec = self.t_sec
                if self.tuning_glitch_frames > 0:
                    v_rows = self.get_tuning_glitch_rows(36, 8, t_cfg)
                elif self.viz_mode == 0:
                    v_rows = self.get_equalizer_rows(36, 8, t_cfg)
                else:
                    v_rows = self.get_oscilloscope_rows(36, 8, t_sec, t_cfg)

                lcd_rows = []
                for i in range(8):
                    v_s = v_rows[i] if i < len(v_rows) else " " * 36
                    row_content = f"  {v_s}    {r_rights[i]}  "
                    lcd_rows.append(f"{C_LCD_BG}{fit_row(row_content, lcd_inner_w, C_LCD_BG)}{RST}")

            d_pad = f"{C_DECK_BG}{' ' * deck_margin}{RST}"
            lines.append(f"{pad}{C_FRAME}│{d_pad}{C_LCD_BORDER}╭{'─' * lcd_inner_w}╮{RST}{d_pad}{C_FRAME}│{RST}")
            for r_content in lcd_rows:
                formatted_lcd = fit_row(r_content, lcd_inner_w, C_LCD_BG)
                lines.append(f"{pad}{C_FRAME}│{d_pad}{C_LCD_BORDER}│{formatted_lcd}{C_LCD_BORDER}│{RST}{d_pad}{C_FRAME}│{RST}")
            lines.append(f"{pad}{C_FRAME}│{d_pad}{C_LCD_BORDER}╰{'─' * lcd_inner_w}╯{RST}{d_pad}{C_FRAME}│{RST}")
            deck_row1 = self.render_transport_bar(inner_w, t_cfg, C_DECK_BG)

            slots = 28
            filled = int((self.volume / 100.0) * slots)
            if self.is_muted:
                vol_bar = f"{C_ERROR}{'▱' * slots}{RST}"
                vol_disp = f"{C_MUTED}VOLUME: [{vol_bar}]   MUTED{RST}"
            else:
                vol_bar = f"{C_CYAN}{'▰' * filled}{C_CYAN_DIM}{'▱' * (slots - filled)}{RST}"
                vol_disp = f"{C_VOL_LABEL}VOLUME: [{vol_bar}]   {C_CYAN}{self.volume:3d}%{RST}"

            vol_w = str_width(vol_disp)
            v_sp1 = max(0, (inner_w - vol_w) // 2)
            v_sp2 = max(0, inner_w - vol_w - v_sp1)
            deck_row2 = f"{C_DECK_BG}{' ' * v_sp1}{vol_disp}{' ' * v_sp2}{RST}"

            lines.append(f"{pad}{C_FRAME}│{fit_row(deck_row1, inner_w, C_DECK_BG)}{C_FRAME}│{RST}")
            lines.append(f"{pad}{C_FRAME}│{fit_row(deck_row2, inner_w, C_DECK_BG)}{C_FRAME}│{RST}")
            lines.append(f"{pad}{C_FRAME}├{'─' * inner_w}┤{RST}")

            if self.show_drawer:
                status_bar = (
                    f"{C_TITLE_BG} "
                    f"{C_HINT_KEY}[▲/▼]{C_HINT_TXT} Navigate Directory   "
                    f"{C_HINT_KEY}[Enter]{C_HINT_TXT} Tune Channel   "
                    f"{C_HINT_KEY}[L/Esc]{C_HINT_TXT} Close Drawer   "
                    f"{C_HINT_KEY}[Q]{C_HINT_TXT} Quit Player"
                )
            else:
                # Exactly 100 cells. It used to be 119 and was cut off before
                # [M] Mute and [Q] Quit.
                status_bar = (
                    f"{C_TITLE_BG} "
                    f"{C_HINT_KEY}[Space]{C_HINT_TXT} Play/Pause  "
                    f"{C_HINT_KEY}[N/P]{C_HINT_TXT} Stn  "
                    f"{C_HINT_KEY}[V]{C_HINT_TXT} Viz  "
                    f"{C_HINT_KEY}[T]{C_HINT_TXT} Theme  "
                    f"{C_HINT_KEY}[D]{C_HINT_TXT} Style  "
                    f"{C_HINT_KEY}[L]{C_HINT_TXT} List  "
                    f"{C_HINT_KEY}[A]{C_HINT_TXT} Add  "
                    f"{C_HINT_KEY}[M]{C_HINT_TXT} Mute  "
                    f"{C_HINT_KEY}[Q]{C_HINT_TXT} Quit"
                )
            lines.append(f"{pad}{C_FRAME}│{fit_row(status_bar, inner_w, C_TITLE_BG)}{C_FRAME}│{RST}")
            lines.append(f"{pad}{C_FRAME}╰{'─' * inner_w}╯{RST}")
            while len(lines) < rows:
                lines.append("")
            return lines

    def render_modern_neo(self, cols: int, rows: int, t_cfg: dict, frame: int) -> list:
        current_track = PLAYLIST[self.current_track_idx]
        C_FRAME = t_cfg["_c_accent"]
        C_CYAN = t_cfg["_c_accent"]
        C_BRIGHT = t_cfg["_c_bright"]
        C_DIM = t_cfg["_c_dim"]
        C_WARN = t_cfg["_c_warn"]

        W = min(cols - 2, 98 if cols >= 100 else (cols - (cols % 2)))
        inner_w = W - 2
        margin_left = max(0, (cols - W) // 2)
        pad = " " * margin_left

        if rows >= 26:
            viz_h = min(18, max(6, rows - 18))
        else:
            viz_h = 6

        chassis_h = 9 + viz_h
        top_space = max(0, (rows - chassis_h) // 2)
        lines = ["" for _ in range(top_space)]

        stn_hdr = f" ♫ {current_track['station'].upper()} "
        badge_txt, _ = self.status_badge(t_cfg, compact=True)
        live_bg = "\033[1;42;30m" if self.stream_live else "\033[1;43;30m"
        pill_badge = f"{live_bg} {badge_txt.split(' ')[-1]} \033[0m {C_CYAN}[{current_track.get('bitrate', '128k')} AAC]{RST}"
        h_sp = max(0, inner_w - str_width(stn_hdr) - str_width(pill_badge))
        hdr_line = f"{C_CYAN}\033[1m{stn_hdr}\033[22m{' ' * h_sp}{pill_badge}"
        lines.append(f"{pad}{C_FRAME}╭─ RADIO STREAM {'─' * max(0, inner_w - 15)}╮{RST}")
        lines.append(f"{pad}{C_FRAME}│{fit_row(hdr_line, inner_w)}{C_FRAME}│{RST}")

        pill_w = str_width(pill_badge)
        track_w = max(20, (inner_w - pill_w - 3) - 4)
        track_disp = self.get_marquee_text(current_track['track'], track_w, frame)
        track_line = f"  {C_BRIGHT}\033[1m▶ {track_disp}\033[22m{RST}"
        lines.append(f"{pad}{C_FRAME}│{fit_row(track_line, inner_w)}{C_FRAME}│{RST}")

        mins = self.track_elapsed // 60
        secs = self.track_elapsed % 60
        timer_colon = self.timer_colon()
        cur_t = f"{mins:02d}{timer_colon}{secs:02d}"
        if self.track_duration and self.track_duration > 0:
            d_mins = self.track_duration // 60
            d_secs = self.track_duration % 60
            tot_t = f"{d_mins:02d}:{d_secs:02d}"
            p_slots = max(10, inner_w - str_width(cur_t) - str_width(tot_t) - 8)
            prog = min(1.0, max(0.0, self.track_elapsed / float(self.track_duration)))
            dot_idx = int(prog * (p_slots - 1))
            bar_chars = ["━"] * p_slots
            if 0 <= dot_idx < p_slots:
                bar_chars[dot_idx] = "●"
            prog_bar = f"  {C_BRIGHT}{cur_t}{RST} {C_CYAN}{''.join(bar_chars)}{RST} {C_DIM}{tot_t}{RST}  "
        else:
            p_slots = max(10, inner_w - str_width(cur_t) - 20)
            prog_bar = f"  {C_BRIGHT}{cur_t}{RST} {C_CYAN}{'━' * p_slots}{RST} {C_WARN}[● LIVE STREAM]{RST}  "
        lines.append(f"{pad}{C_FRAME}│{fit_row(prog_bar, inner_w)}{C_FRAME}│{RST}")
        viz_tag = self.viz_names[self.viz_mode]
        hdr_viz = f"├─ {viz_tag} "
        lines.append(f"{pad}{C_FRAME}{hdr_viz}{'─' * max(0, inner_w - str_width(hdr_viz) + 1)}┤{RST}")

        t_sec = self.t_sec
        viz_w = inner_w - 4
        if self.show_drawer:
            v_rows = self.render_drawer_rows(viz_w, t_cfg, viz_h)
        elif self.tuning_glitch_frames > 0:
            v_rows = self.get_tuning_glitch_rows(viz_w, viz_h, t_cfg)
        else:
            if self.viz_mode == 0:
                v_rows = self.get_equalizer_rows(viz_w, viz_h, t_cfg)
            else:
                v_rows = self.get_braille_wave_rows(viz_w, viz_h, t_sec, t_cfg)

        for r in range(viz_h):
            v_str = v_rows[r] if r < len(v_rows) else " " * viz_w
            lines.append(f"{pad}{C_FRAME}│  {fit_row(v_str, viz_w)}  {C_FRAME}│{RST}")

        lines.append(f"{pad}{C_FRAME}├{'─' * inner_w}┤{RST}")
        lines.append(f"{pad}{C_FRAME}│{self.render_transport_bar(inner_w, t_cfg, modern=True)}{C_FRAME}│{RST}")

        slots = max(8, min(24, (inner_w - 24) // 2))
        filled = int((self.volume / 100.0) * slots)
        vol_bar = f"{C_CYAN}{'▰' * filled}{C_DIM}{'▱' * (slots - filled)}{RST}"
        vol_disp = f"Volume: {self.volume:3d}%  {vol_bar}"
        v_sp1 = max(0, (inner_w - str_width(vol_disp)) // 2)
        lines.append(f"{pad}{C_FRAME}│{fit_row(' ' * v_sp1 + vol_disp, inner_w)}{C_FRAME}│{RST}")

        s_inner = self.render_status_bar(inner_w, t_cfg, "Modern", mode="bracket")
        lines.append(f"{pad}{C_FRAME}╰{s_inner}{C_FRAME}╯{RST}")
        while len(lines) < rows:
            lines.append("")
        return lines

    def render_minimal_zen(self, cols: int, rows: int, t_cfg: dict, frame: int) -> list:
        current_track = PLAYLIST[self.current_track_idx]
        C_CYAN = t_cfg["_c_accent"]
        C_BRIGHT = t_cfg["_c_bright"]
        C_DIM = t_cfg["_c_dim"]
        C_WARN = t_cfg["_c_warn"]

        W = min(cols - 4, 88 if cols >= 92 else (cols - 2))
        margin_left = max(0, (cols - W) // 2)
        pad = " " * margin_left

        if rows >= 24:
            viz_h = min(16, max(4, rows - 20))
        else:
            viz_h = 4

        chassis_h = 10 + viz_h
        top_space = max(0, (rows - chassis_h) // 2)
        lines = ["" for _ in range(top_space)]

        stn_hdr = f"♫ {current_track['station'].upper()}"
        try:
            l_cnt = f"{int(current_track.get('listeners', 0)):,} Listeners"
        except Exception:
            l_cnt = ""
        meta_str = f"{l_cnt} · {current_track.get('bitrate', '128k')} AAC · {current_track.get('provider', 'SomaFM').title()}"
        sp = max(1, W - str_width(stn_hdr) - str_width(meta_str))
        lines.append(f"{pad}{C_CYAN}\033[1m{stn_hdr}\033[22m{' ' * sp}{C_DIM}{meta_str}{RST}")
        lines.append(f"{pad}{C_DIM}{'─' * W}{RST}")

        track_disp = self.get_marquee_text(current_track['track'], W, frame)
        lines.append(f"{pad}{C_BRIGHT}\033[1m{track_disp}\033[22m{RST}")

        mins = self.track_elapsed // 60
        secs = self.track_elapsed % 60
        timer_colon = self.timer_colon()
        if self.track_duration and self.track_duration > 0:
            d_mins = self.track_duration // 60
            d_secs = self.track_duration % 60
            time_str = f"Elapsed: {mins:02d}{timer_colon}{secs:02d} / {d_mins:02d}:{d_secs:02d}"
        else:
            time_str = f"Elapsed: {mins:02d}{timer_colon}{secs:02d}  [LIVE]"
        status_txt, status_col = self.status_badge(t_cfg)
        e_sp = max(1, W - str_width(time_str) - str_width(status_txt))
        lines.append(f"{pad}{C_DIM}{time_str}{' ' * e_sp}{status_col}\033[1m{status_txt}\033[22m{RST}")
        lines.append("")

        t_sec = self.t_sec
        if self.show_drawer:
            v_rows = self.render_drawer_rows(W, t_cfg, viz_h)
        elif self.tuning_glitch_frames > 0:
            v_rows = self.get_tuning_glitch_rows(W, viz_h, t_cfg)
        else:
            if self.viz_mode == 0:
                v_rows = self.get_equalizer_rows(W, viz_h, t_cfg)
            else:
                v_rows = self.get_oscilloscope_rows(W, viz_h, t_sec, t_cfg)

        for r in range(viz_h):
            v_str = v_rows[r] if r < len(v_rows) else " " * W
            lines.append(f"{pad}{v_str}")

        lines.append(f"{pad}{C_DIM}{'─' * W}{RST}")

        lines.append(f"{pad}{self.render_transport_bar(W, t_cfg)}")

        slots = max(8, min(20, (W - 22) // 2))
        filled = int((self.volume / 100.0) * slots)
        vol_bar = f"{C_CYAN}{'▰' * filled}{C_DIM}{'▱' * (slots - filled)}{RST}"
        vol_disp = f"VOLUME: [{vol_bar}]  {self.volume:3d}%"
        v_sp1 = max(0, (W - str_width(vol_disp)) // 2)
        lines.append(f"{pad}{fit_row(' ' * v_sp1 + vol_disp, W)}")
        lines.append(f"{pad}{C_DIM}{'─' * W}{RST}")

        lines.append(f"{pad}{self.render_status_bar(W, t_cfg, 'Zen', mode='plain')}")
        while len(lines) < rows:
            lines.append("")
        return lines

    def render_cyberpunk(self, cols: int, rows: int, t_cfg: dict, frame: int) -> list:
        current_track = PLAYLIST[self.current_track_idx]
        C_CYAN = CYBER_CYAN
        C_MAGENTA = CYBER_MAGENTA
        C_BRIGHT = CYBER_BRIGHT
        C_DIM = CYBER_DIM
        C_AMBER = CYBER_AMBER
        C_FRAME = C_MAGENTA

        W = min(cols - 4, 94 if cols >= 96 else (cols - (cols % 2)))
        inner_w = W - 2
        margin_left = max(0, (cols - W) // 2)
        pad = " " * margin_left

        if rows >= 26:
            viz_h = min(16, max(6, rows - 20))
        else:
            viz_h = 6

        title_txt = f"{C_CYAN}\033[1m// NET.RADIO // CYBERBEAT-2077\033[22m{RST}"
        _cyber_state, _ = self.status_badge(t_cfg, compact=True)
        tag_txt = f"{C_MAGENTA}[{_cyber_state}] [STEREO_V2.0]{RST}"
        t_sp = max(0, inner_w - str_width(title_txt) - str_width(tag_txt))
        t_line = f"{title_txt}{' ' * t_sp}{tag_txt}"

        stn_tag = f" STATION: {C_CYAN}\033[1m[{current_track['station'].upper()}]\033[22m{RST}"
        track_tag = f"TRACK: {C_AMBER}{current_track['track'][:max(10, inner_w - str_width(stn_tag) - 14)]}{RST} "
        i_sp = max(1, inner_w - str_width(stn_tag) - str_width(track_tag))
        track_line = stn_tag + (" " * i_sp) + track_tag

        box_rows = []
        box_rows.append(f"{C_FRAME}╭{'─' * inner_w}╮{RST}")
        box_rows.append(f"{C_FRAME}│{fit_row(t_line, inner_w)}{C_FRAME}│{RST}")
        box_rows.append(f"{C_FRAME}├{'─' * inner_w}┤{RST}")
        box_rows.append(f"{C_FRAME}│{fit_row(track_line, inner_w)}{C_FRAME}│{RST}")
        box_rows.append(f"{C_FRAME}├{'─' * inner_w}┤{RST}")

        t_sec = self.t_sec
        viz_w = inner_w - 4
        if self.show_drawer:
            v_rows = self.render_drawer_rows(viz_w, t_cfg, viz_h)
        elif self.tuning_glitch_frames > 0:
            v_rows = self.get_tuning_glitch_rows(viz_w, viz_h, t_cfg)
        else:
            if self.viz_mode == 0:
                v_rows = self.get_equalizer_rows(viz_w, viz_h, t_cfg)
            else:
                v_rows = self.get_braille_wave_rows(viz_w, viz_h, t_sec, t_cfg)

        for r in range(viz_h):
            v_str = v_rows[r] if r < len(v_rows) else " " * viz_w
            box_rows.append(f"{C_FRAME}│  {fit_row(v_str, viz_w)}  {C_FRAME}│{RST}")

        box_rows.append(f"{C_FRAME}├{'─' * inner_w}┤{RST}")
        box_rows.append(f"{C_FRAME}│{self.render_transport_bar(inner_w, t_cfg)}{C_FRAME}│{RST}")

        mins = self.track_elapsed // 60
        secs = self.track_elapsed % 60
        timer_colon = self.timer_colon()
        time_str = f"ELAPSED: {mins:02d}{timer_colon}{secs:02d} [LIVE]"
        bar_slots = max(6, min(20, (inner_w - 30) // 2))
        filled_dots = int((self.volume / 100.0) * bar_slots)
        vol_str = f"VOLUME: {C_CYAN}{'━' * filled_dots}●{'─' * max(0, bar_slots - filled_dots)}{RST} {self.volume:3d}%"
        b_sp = max(1, inner_w - str_width(vol_str) - str_width(time_str) - 4)
        c_deck_r2 = f"  {vol_str}{' ' * b_sp}{C_AMBER}{time_str}  "
        box_rows.append(f"{C_FRAME}│{fit_row(c_deck_r2, inner_w)}{C_FRAME}│{RST}")

        s_inner = self.render_status_bar(inner_w, t_cfg, "Cyberpunk", mode="bracket")
        box_rows.append(f"{C_FRAME}╰{fit_row(s_inner, inner_w, fill_char='─')}{C_FRAME}╯{RST}")

        chassis_h = len(box_rows)
        top_space = max(0, (rows - chassis_h) // 2)

        lines = ["" for _ in range(top_space)]
        for b_row in box_rows:
            lines.append(f"{pad}{b_row}")

        while len(lines) < rows:
            lines.append("")

        return lines

    def _tide_type_rows(self, lay: dict, t_cfg: dict) -> list:
        """Rasterise the station name, each letter flooded to its slice of the
        spectrum. Returns the finished rows of the type block, cols wide."""
        accent, bright = t_cfg["accent"], t_cfg["lcd_bright"]
        ground, dim, warn = t_cfg["lcd_bg"], t_cfg["lcd_dim"], t_cfg["warn"]
        cache = self._tide_cache
        scale, block_h = lay["scale"], lay["block_h"]

        # The sheet: one gradient behind the whole block, fixed in frame space
        # rather than per glyph. The block maps onto t in [0, 0.5], so the
        # ping-pong runs one way - accent at the bottom, lcd_bright at the top -
        # and a drift term added to t later would wrap without a seam.
        sheet_key = (lay["key"], accent, bright, ground, dim, warn)
        hit = cache.get("sheet")
        if hit is not None and hit[0] == sheet_key:
            grad_row, cap_row, unlit = hit[1]
        else:
            grad_row, cap_row = [], []
            span = max(1, block_h - 1)
            for py in range(block_h):
                t = 0.5 * (block_h - 1 - py) / span
                tt = t * 2.0 if t < 0.5 else (1.0 - t) * 2.0
                g = _lerp3(accent, bright, tt)
                grad_row.append(g)
                cap_row.append(_lerp3(g, (255, 255, 255), 0.45))
            unlit = _lerp3(ground, dim, 0.42)
            cache["sheet"] = (sheet_key, (grad_row, cap_row, unlit))

        # Each letter averages the bands under its horizontal span (worked out in
        # _tide_layout), so the spectrum's shape reads across every line the way
        # the bars show it, its middle in the middle of the screen.
        bh, ph = self.band_heights, self.peak_heights
        full = self.max_height
        vals, pks = [], []
        for lo, hi in lay["bands"]:
            k = (hi - lo) * full
            vals.append(sum(bh[lo:hi]) / k)
            pks.append(sum(ph[lo:hi]) / k)
        # Stretch each letter away from the spectrum's mean: the overall level
        # survives and neighbouring letters stay apart. Monotonic, so a peak
        # never lands below its flood, and silence stays at exactly zero.
        m = sum(bh) / (len(bh) * full)
        glyph_h = 7 * scale
        flood = tuple(round(min(1.0, max(0.0, m + (v - m) * TIDE_EXPAND)) * glyph_h) for v in vals)
        peak = tuple(round(min(1.0, max(0.0, m + (p - m) * TIDE_EXPAND)) * glyph_h) for p in pks)

        # Paused or silent frames repeat exactly; skip the raster for them.
        rows_key = (sheet_key, flood, peak)
        hit = cache.get("rows")
        if hit is not None and hit[0] == rows_key:
            return hit[1]

        line_of_py, line_off, base = lay["line_of_py"], lay["line_off"], lay["baselines"]
        pk_w = min(2, scale)

        def colour_fn(px, py, li):
            ln = line_of_py[py]
            g = line_off[ln] + li
            h = base[ln] - py                      # 1 .. glyph_h above the baseline
            f = flood[g]
            if h <= f:                             # under the flood the sheet shows
                return cap_row[py] if f - h < scale else grad_row[py]
            p = peak[g]
            if p > f and p - pk_w < h <= p:
                return warn
            return unlit

        pix = Pix(lay["block_w"], block_h, ground)
        for ln, line in enumerate(lay["lines"]):
            draw_word(pix, lay["x_off"][ln], lay["tops"][ln], line, scale, lay["gap"], colour_fn)

        cols = lay["key"][1]
        c_ground = t_cfg["_c_lcd_bg"]
        left = c_ground + " " * ((cols - lay["block_w"]) // 2)
        body = [fit_row(left + r, cols, c_ground) for r in pix.to_rows()]
        cache["rows"] = (rows_key, body)
        return body

    def render_tide(self, cols: int, rows: int, t_cfg: dict) -> list:
        current_track = PLAYLIST[self.current_track_idx]
        C_DIM = t_cfg["_c_dim"]
        C_ACCENT = t_cfg["_c_accent"]
        C_GROUND = t_cfg["_c_lcd_bg"]

        lay = self._tide_layout(current_track["station"], cols, rows)
        avail = lay["avail"]

        prov = str(current_track.get("provider") or "stream").upper()
        net_l = f"  NET · {prov} · {current_track.get('freq', '')} FM"
        net_r = f"{current_track.get('bitrate', '128kbps')} · {current_track.get('genre', 'RADIO')}  "
        n_sp = max(1, cols - str_width(net_l) - str_width(net_r))
        lines = [fit_row(f"{C_DIM}{net_l}{' ' * n_sp}{net_r}{RST}", cols), fit_row("", cols)]

        if self.show_drawer:
            # Without this, [L] would open a drawer nobody can see that still
            # captures the arrow keys and Enter.
            dw = min(cols - 4, 96)
            d_pad = " " * ((cols - dw) // 2)
            d_rows = min(avail, len(PLAYLIST) + 1)          # header + every station that fits
            body = [fit_row(d_pad + r, cols) for r in self.render_drawer_rows(dw, t_cfg, d_rows)]
            filler = fit_row("", cols)
        elif self.tuning_glitch_frames > 0:
            # The same static burst the other styles show on a station change,
            # filling the whole type region on the ground colour.
            filler = fit_row(C_GROUND, cols, C_GROUND)
            body = [fit_row(C_GROUND + r, cols, C_GROUND)
                    for r in self.get_tuning_glitch_rows(cols, avail, t_cfg)]
        else:
            body = self._tide_type_rows(lay, t_cfg)
            filler = fit_row(C_GROUND, cols, C_GROUND)
        body = body[:avail]
        top_pad = (avail - len(body)) // 2
        lines.extend([filler] * top_pad)
        lines.extend(body)
        lines.extend([filler] * (avail - top_pad - len(body)))

        lines.append(self.render_transport_bar(cols, t_cfg))

        mins = self.track_elapsed // 60
        secs = self.track_elapsed % 60
        timer_colon = self.timer_colon()
        if self.track_duration and self.track_duration > 0:
            d_mins = self.track_duration // 60
            d_secs = self.track_duration % 60
            time_str = f"{mins:02d}{timer_colon}{secs:02d} / {d_mins:02d}:{d_secs:02d}"
        else:
            time_str = f"{mins:02d}{timer_colon}{secs:02d}  [LIVE]"
        status_txt, status_col = self.status_badge(t_cfg)
        e_sp = max(1, cols - 4 - str_width(time_str) - str_width(status_txt))
        lines.append(fit_row(f"  {C_DIM}{time_str}{' ' * e_sp}{status_col}\033[1m{status_txt}\033[22m{RST}", cols))

        slots = max(8, min(24, (cols - 24) // 2))
        if self.is_muted:
            vol_disp = f"{C_DIM}VOLUME [{C_ERROR}{'▱' * slots}{C_DIM}]  {C_MUTED}MUTED{RST}"
        else:
            filled = int((self.volume / 100.0) * slots)
            vol_disp = (f"{C_DIM}VOLUME [{C_ACCENT}{'▰' * filled}{C_DIM}{'▱' * (slots - filled)}]"
                        f"  {C_ACCENT}{self.volume:3d}%{RST}")
        v_sp = max(0, (cols - str_width(vol_disp)) // 2)
        lines.append(fit_row(' ' * v_sp + vol_disp, cols))

        while len(lines) < rows:
            lines.append(fit_row("", cols))
        return lines[:rows]

    def cleanup(self):
        if getattr(self, "_cleaned_up", False):
            return
        self._cleaned_up = True
        for name, action in (("cava_engine", "cleanup"), ("meta_worker", "stop"),
                             ("stream_player", "cleanup")):
            obj = getattr(self, name, None)
            if obj is not None:
                try:
                    getattr(obj, action)()
                except Exception:
                    LOG.exception("error shutting down %s", name)
        sys.stdout.write("\033[?25h\033[0m\033[?1049l")
        sys.stdout.flush()
        print("📻 termbeat closed. Thanks for listening! 🎵")
        LOG.info("termbeat exited cleanly")


def _windows_console_vt():
    """Turn on VT escape processing for the Windows console so the ANSI/truecolor
    output works unchanged (Windows Terminal has it on already; conhost needs
    it asked for). Returns a callable that restores the previous mode."""
    try:
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetStdHandle.restype = wintypes.HANDLE
        handle = k32.GetStdHandle(-11)                   # STD_OUTPUT_HANDLE
        mode = wintypes.DWORD()
        if not k32.GetConsoleMode(handle, ctypes.byref(mode)):
            return lambda: None
        old = mode.value
        k32.SetConsoleMode(handle, old | 0x0004)          # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return lambda: k32.SetConsoleMode(handle, old)
    except Exception as exc:
        LOG.warning("could not enable VT mode: %s", exc)
        return lambda: None


def main():
    restore_console = lambda: None
    if IS_WINDOWS:
        restore_console = _windows_console_vt()
        try:
            sys.stdout.reconfigure(encoding="utf-8")      # box drawing, not cp1252
        except (AttributeError, ValueError):
            pass
    app = TermbeatPlayer()
    # SIGHUP is what a terminal sends when its window closes - the most common
    # way people quit a TUI. It used to be unhandled, so Python died without
    # running atexit: the IPC socket and cava config were left behind and mpv
    # was orphaned, still streaming and still playing audio.
    # SIGBREAK is Windows' Ctrl-Break / console-window-closed signal.
    for signame in ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK"):
        sig = getattr(signal, signame, None)
        if sig is not None:
            try:
                signal.signal(sig, app.stop_app)
            except (OSError, ValueError):
                pass
    if hasattr(signal, "SIGWINCH"):
        try:
            signal.signal(signal.SIGWINCH, app.handle_sigwinch)
        except (OSError, ValueError):
            pass
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        restore_console()


if __name__ == "__main__":
    main()
