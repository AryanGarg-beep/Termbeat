#!/usr/bin/env python3
"""termbeat test suite. Standard library only - run with: python3 tests/test_termbeat.py

Covers the invariants the fixes depend on: exact row widths across every
layout, key parsing, cell-accurate marquee, config validation, and that the
damage-tracking renderer converges to the same screen as a full repaint.
"""
import importlib.util
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

_spec = importlib.util.spec_from_file_location("termbeat", os.path.join(ROOT, "termbeat", "app.py"))
tb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tb)

FAILURES = []


def check(cond, label, detail=""):
    if cond:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}   {detail}")
        FAILURES.append(label)


# --------------------------------------------------------------- test doubles

class StubStream:
    """Stands in for mpv; reuses the real state constants."""
    has_mpv = True
    NO_MPV = tb.StreamPlayer.NO_MPV
    STARTING = tb.StreamPlayer.STARTING
    IDLE = tb.StreamPlayer.IDLE
    BUFFERING = tb.StreamPlayer.BUFFERING
    PLAYING = tb.StreamPlayer.PLAYING
    PAUSED = tb.StreamPlayer.PAUSED
    ERROR = tb.StreamPlayer.ERROR

    def __init__(self, *a, **k):
        self.is_connected = True
        self.state = (tb.StreamPlayer.PLAYING, True)
    def health(self):
        return self.state
    def get_media_title(self):
        return ""
    def __getattr__(self, _):
        return lambda *a, **k: None


class StubCava:
    def __init__(self, n=18):
        self.n = n
        self.suspended = False
    def get_bands(self):
        return [0.0] * self.n, False
    def set_suspended(self, v):
        self.suspended = v
    def cleanup(self):
        pass


class StubMeta:
    provider_of = staticmethod(tb.MetadataScraper.provider_of)

    def __init__(self, *a, **k):
        self.playlist = a[0] if a else []
        self.provider = None
    def start(self):
        pass
    def stop(self):
        pass
    def set_active_provider(self, p):
        self.provider = p
    def set_active_station(self, station):
        self.provider = self.provider_of(station)
        self.station_id = station.get("id")


def make_app():
    """Build a player with the three subprocess-owning components stubbed out."""
    orig = (tb.StreamPlayer, tb.CavaStreamEngine, tb.MetadataScraper)
    tb.StreamPlayer, tb.CavaStreamEngine, tb.MetadataScraper = StubStream, StubCava, StubMeta
    try:
        app = tb.TermbeatPlayer()
    finally:
        tb.StreamPlayer, tb.CavaStreamEngine, tb.MetadataScraper = orig
    return app


# ------------------------------------------------------------- ansi screen model

class Screen:
    """Just enough terminal to verify what the renderer actually paints."""

    def __init__(self, cols, rows):
        self.cols, self.rows = cols, rows
        self.grid = [[" "] * cols for _ in range(rows)]
        self.cy = self.cx = 0

    def feed(self, data):
        i, n = 0, len(data)
        while i < n:
            ch = data[i]
            if ch == "\033":
                m = re.match(r"\033\[([0-9;]*)([A-Za-z])", data[i:])
                if not m:
                    i += 1
                    continue
                params, final = m.group(1), m.group(2)
                nums = [int(x) for x in params.split(";") if x != ""]
                if final == "H":
                    self.cy = (nums[0] - 1) if nums else 0
                    self.cx = (nums[1] - 1) if len(nums) > 1 else 0
                elif final == "K":
                    if 0 <= self.cy < self.rows:
                        for x in range(self.cx, self.cols):
                            self.grid[self.cy][x] = " "
                elif final == "J":
                    for y in range(self.cy + 1, self.rows):
                        self.grid[y] = [" "] * self.cols
                    if 0 <= self.cy < self.rows:
                        for x in range(self.cx, self.cols):
                            self.grid[self.cy][x] = " "
                i += m.end()
                continue
            if ch == "\n":
                self.cy += 1
                self.cx = 0
                i += 1
                continue
            if ch == "\r":
                self.cx = 0
                i += 1
                continue
            w = tb.char_width(ch)
            if 0 <= self.cy < self.rows and 0 <= self.cx < self.cols:
                self.grid[self.cy][self.cx] = ch
                for k in range(1, w):
                    if self.cx + k < self.cols:
                        self.grid[self.cy][self.cx + k] = ""
            self.cx += max(1, w)
            i += 1

    def text(self):
        return ["".join(row).rstrip() for row in self.grid]


# ------------------------------------------------------------------------ tests

def test_row_widths(app):
    geoms = [(80, 24), (102, 30), (101, 54), (200, 60), (70, 18), (120, 40)]
    bad = []
    for cols, rows in geoms:
        for style in range(len(app.design_names)):
            for viz in range(2):
                for drawer in (False, True):
                    app.design_style, app.viz_mode, app.show_drawer = style, viz, drawer
                    app.t_sec = 3.0
                    app.update_physics()
                    lines = app.render_frame(cols, rows, tb.THEMES[style % len(tb.THEMES)], 7)
                    if len(lines) > rows:
                        bad.append(f"{cols}x{rows} style{style} viz{viz}: {len(lines)} rows > {rows}")
                    for i, line in enumerate(lines):
                        if tb.str_width(line) > cols:
                            bad.append(f"{cols}x{rows} style{style} viz{viz} row{i}: "
                                       f"width {tb.str_width(line)} > {cols}")
    check(not bad, f"every layout fits its terminal (6 geometries x {len(app.design_names)} styles "
          "x 2 viz x drawer)", "; ".join(bad[:3]))


def test_tide(app):
    """TIDE: exact frame size everywhere, every band on screen, legible and quiet in silence."""
    geoms = [(70, 18), (80, 24), (101, 54), (132, 44), (200, 60)]
    names = ["KEXP 90.3 Seattle", "Nightwave Plaza", "Groove Salad", "Café Zürich & Co",
             "日本語", "Supercalifragilisticexpialidocious Radio"]
    stn = tb.PLAYLIST[app.current_track_idx]
    orig_name = stn["station"]
    real = sys.stdout
    app.design_style, app.viz_mode, app.is_playing = 4, 0, True
    try:
        bad, uncovered = [], []
        for name in names:
            stn["station"] = name
            for cols, rows in geoms:
                lay = app._tide_layout(name, cols, rows)
                bands = lay["bands"]
                covered = {b for lo, hi in bands for b in range(lo, hi)}
                ends = lay["line_off"][1:] + [lay["n"]]
                ordered = all([lo for lo, _ in bands[a:b]] == sorted(lo for lo, _ in bands[a:b])
                              for a, b in zip(lay["line_off"], ends))
                # bands follow horizontal position, not reading order: every line
                # starts at the band under its own left edge
                nb = len(app.band_heights)
                aligned = all(bands[a][0] == min(nb - 1, lay["x_off"][ln] * nb // lay["block_w"])
                              for ln, a in enumerate(lay["line_off"]))
                if covered != set(range(nb)) or not ordered or not aligned:
                    uncovered.append(f"{name!r} {cols}x{rows}")
                for theme in tb.THEMES:
                    for state in ("playing", "drawer", "static"):
                        app.update_physics()
                        app.show_drawer = state == "drawer"
                        app.tuning_glitch_frames = 5 if state == "static" else 0
                        lines = app.render_frame(cols, rows, theme, 7)
                        if len(lines) != rows or any(tb.str_width(l) != cols for l in lines):
                            bad.append(f"{name!r} {cols}x{rows} {theme['name']} {state}")
        check(not bad, "TIDE is exactly rows x cols for every theme, size, station and state",
              "; ".join(bad[:3]))
        check(not uncovered, "TIDE puts all 18 bands on screen, in horizontal order on every line",
              "; ".join(uncovered[:3]))

        # Silence: once the bars and peaks have fallen, no letter shows the gradient
        # or its cap, but the name is still drawn in the unlit colour.
        stn["station"] = orig_name
        app.show_drawer, app.tuning_glitch_frames, app.is_playing = False, 0, False
        for _ in range(80):
            app.update_physics()
        cols, rows, theme = 101, 54, tb.THEMES[0]
        lines = app.render_frame(cols, rows, theme, 7)
        type_region = "".join(lines[2:rows - 3])          # 2 margin rows above, 3 below
        grad, cap, unlit = app._tide_cache["sheet"][1]
        flooded = [c for c in grad + cap if tb.fg(*c) in type_region or tb.bg(*c) in type_region]
        drawn = tb.fg(*unlit) in type_region or tb.bg(*unlit) in type_region
        check(drawn and not flooded, "TIDE keeps the name drawn but unflooded in silence",
              f"drawn={drawn} flooded={flooded[:3]}")

        # Paused frames repeat exactly, so after the first repaint nothing is sent.
        sizes = []
        class Cap:
            def write(self, d): sizes.append(len(d))
            def flush(self): pass
        app._prev_lines = None
        sys.stdout = Cap()
        for f in range(20):
            app.t_sec = 300 + f * 0.2
            app.update_physics()
            app.emit_frame(app.render_frame(cols, rows, theme, f)[:rows])
        sys.stdout = real
        quiet = sum(sizes[1:])
        check(quiet < 200, f"paused TIDE is nearly silent ({quiet} bytes over 19 frames)")
    finally:
        sys.stdout = real
        stn["station"] = orig_name
        app.design_style, app.show_drawer, app.tuning_glitch_frames = 0, False, 0
        app.is_playing, app._prev_lines = True, None


def test_drawer_follows_selection(app):
    """The drawer sizes itself to its panel and never scrolls the selection out of view."""
    bad = []
    for style in range(len(app.design_names)):
        for cols, rows in [(70, 18), (80, 24), (102, 30), (132, 44)]:
            if style == 0 and rows >= 32:
                continue      # Studio Tower draws its own directory, not the drawer
            app.design_style, app.show_drawer = style, True
            app.drawer_selected_idx = app.drawer_scroll_offset = 0
            for _ in range(len(tb.PLAYLIST) + 2):
                app.handle_key("DOWN")
                want = f"{app.drawer_selected_idx + 1:02d}. "
                shown = [tb.ANSI_ESCAPE_RE.sub("", l)
                         for l in app.render_frame(cols, rows, tb.THEMES[0], 7)[:rows]]
                if not any("►" in t and want in t for t in shown):
                    bad.append(f"style{style} {cols}x{rows}: {want.strip()} off screen")
                    break
    app.design_style, app.show_drawer = 0, False
    check(not bad, "drawer keeps the selection on screen in every style", "; ".join(bad[:3]))


def test_hint_ribbon(app):
    """Every chassis style advertises [A] Add, and no hint bar is cut short."""
    bad = []
    for style in range(4):                  # TIDE has no hint bar
        for cols, rows in [(80, 24), (102, 30), (101, 54), (200, 60), (70, 18), (120, 40)]:
            app.design_style, app.show_drawer = style, False
            shown = [tb.ANSI_ESCAPE_RE.sub("", l)
                     for l in app.render_frame(cols, rows, tb.THEMES[0], 7)[:rows]]
            bar = [t for t in shown if "[D]" in t]
            if not bar or "[A]" not in bar[-1] or "Quit" not in bar[-1]:
                bad.append(f"style{style} {cols}x{rows}: {bar[-1].strip() if bar else 'no bar'}")
    app.design_style = 0
    check(not bad, "every chassis style shows [A] Add in an uncut hint bar", "; ".join(bad[:2]))


def test_station_editor(app):
    """A opens an add-station form that owns the keyboard, validates, appends to
    stations.json without touching existing entries, and tunes to the new station."""
    import json
    import tempfile
    saved = (tb.CONFIG_DIR, tb.CONFIG_FILE, tb.PLAYLIST, app.meta_worker.playlist,
             app.current_track_idx, app.config_mtime)
    tmp = tempfile.TemporaryDirectory()

    def type_text(text):
        for ch in text:
            app.handle_key("SPACE" if ch == " " else ch)

    def file_bytes():
        with open(tb.CONFIG_FILE, "rb") as f:
            return f.read()

    def file_json():
        with open(tb.CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)

    try:
        tb.CONFIG_DIR = tmp.name
        tb.CONFIG_FILE = os.path.join(tmp.name, "stations.json")
        original = [{"station": "Existing One", "url": "https://example.com/one.mp3", "genre": "X"},
                    {"station": "Existing Two", "url": "https://example.com/two.mp3", "extra": [1, 2]}]
        with open(tb.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(original, f)
        app.config_mtime = 0.0
        app.check_reload_stations()
        before = file_bytes()

        # The form owns the keyboard: q, n, digits and d type instead of quitting,
        # tuning or restyling, and Esc cancels without writing anything.
        app.design_style = 0
        cur = app.current_track_idx
        app.handle_key("a")
        opened = app.editor is not None
        alive = all(app.handle_key(k) for k in ("q", "n", "3", "d"))
        typed = app.editor["fields"]["name"] if app.editor else ""
        app.handle_key("ESC")
        check(opened and alive and typed == "qn3d" and app.editor is None
              and app.design_style == 0 and app.current_track_idx == cur and file_bytes() == before,
              "A opens the station form, which owns the keyboard; Esc cancels without writing",
              f"opened={opened} alive={alive} typed={typed!r}")

        app.handle_key("A")
        type_text("Night Owl")
        app.handle_key("BACKSPACE")
        app.handle_key("\x08")                    # the other backspace byte terminals send
        after_bs = app.editor["fields"]["name"]
        app.handle_key("\x15")                    # Ctrl-U
        cleared = app.editor["fields"]["name"]
        app.handle_key("ESC")
        check(after_bs == "Night O" and cleared == "",
              "the form edits with Space, Backspace and Ctrl-U", f"{after_bs!r} {cleared!r}")

        def attempt(name, url):
            app.handle_key("a")
            type_text(name)
            app.handle_key("TAB")
            type_text(url)
            app.handle_key("ENTER")
            refused = app.editor is not None and bool(app.editor["error"])
            app.handle_key("ESC")
            return refused
        rejected = [attempt("", "https://example.com/new.mp3"),
                    attempt("Local", "file:///etc/passwd"),
                    attempt("Dup", "https://example.com/two.mp3")]
        check(all(rejected) and file_bytes() == before,
              "the form rejects a blank name, a non-http URL and a duplicate, writing nothing",
              str(rejected))

        app.handle_key("a")
        type_text("Night Owl Radio")
        app.handle_key("TAB")
        type_text("https://stream.example.com/nightowl.mp3")
        app.handle_key("TAB")
        type_text("99.9")
        app.handle_key("ENTER")
        on_disk = file_json()
        new = on_disk[-1] if len(on_disk) == len(original) + 1 else {}
        idx = next((i for i, s in enumerate(tb.PLAYLIST) if s["url"] == new.get("url")), None)
        check(on_disk[:len(original)] == original and new.get("station") == "Night Owl Radio"
              and new.get("freq") == "99.9" and "provider" not in new and app.editor is None
              and idx is not None and app.current_track_idx == idx,
              "saving appends exactly one entry, leaves the others alone, and tunes to it", str(new))

        app.handle_key("a")
        type_text("Groove Again")
        app.handle_key("TAB")
        type_text("https://ice4.somafm.com/groovesalad-256-mp3")
        app.handle_key("ENTER")
        soma = file_json()[-1]
        check(soma.get("id") == "groovesalad",
              "a SomaFM stream is saved with its channel id, which now-playing needs", str(soma))

        with open(tb.CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write('[{"station": "half-typed", ')
        broken = file_bytes()
        app.handle_key("a")
        type_text("Another")
        app.handle_key("TAB")
        type_text("https://example.com/another.mp3")
        app.handle_key("ENTER")
        refused = app.editor is not None and "stations.json" in app.editor["error"]
        app.handle_key("ESC")
        check(refused and file_bytes() == broken,
              "saving refuses to overwrite a stations.json that isn't a valid list")

        bad = []
        app.handle_key("a")
        type_text("Size Check")
        for cols, rows in [(70, 18), (80, 24), (101, 54), (132, 44), (200, 60)]:
            for theme in tb.THEMES[::2]:
                lines = app.render_frame(cols, rows, theme, 7)
                if len(lines) != rows or any(tb.str_width(l) != cols for l in lines):
                    bad.append(f"{cols}x{rows} {theme['name']}")
        app.handle_key("ESC")
        check(not bad, "the station form is exactly rows x cols at every size", "; ".join(bad[:3]))
    finally:
        (tb.CONFIG_DIR, tb.CONFIG_FILE, tb.PLAYLIST, app.meta_worker.playlist,
         app.current_track_idx, app.config_mtime) = saved
        app.editor, app.tuning_glitch_frames = None, 0
        tmp.cleanup()


def test_cjk_titles(app):
    bad = []
    titles = ["坂本龍一 - 戦場のメリークリスマス", "Björk - Jóga", "日本語 mixed ASCII"]
    for title in titles:
        for w in (20, 48, 56):
            for off in range(0, 30, 7):
                app.marquee_offset = off
                app.is_playing = False
                got = app.get_marquee_text(title, w)
                if tb.str_width(got) != w:
                    bad.append(f"{title[:12]!r} w={w} off={off} -> {tb.str_width(got)}")
    app.is_playing = True
    check(not bad, "marquee is exactly N cells wide for CJK/accented titles", "; ".join(bad[:3]))


def test_key_parsing():
    cases = [
        (b"+", ["+"]), (b"++", ["+", "+"]), (b"+" * 8, ["+"] * 8),
        (b"\x1b[A\x1b[A", ["UP", "UP"]), (b"  ", ["SPACE", "SPACE"]),
        (b"\x1b[5~", ["PAGEUP"]), (b"\x1b[6~", ["PAGEDOWN"]), (b"\x1bOA", ["UP"]),
        (b"q\x1b[Bn", ["q", "DOWN", "n"]), (b"\xe6\x97\xa5", ["日"]),
        (b"\x1b[Z", ["BACKTAB"]), (b"\r", ["ENTER"]),
    ]
    bad = [f"{d!r}->{tb.parse_key_bytes(d)[0]}" for d, exp in cases
           if tb.parse_key_bytes(d)[0] != exp]
    check(not bad, "key parser splits multi-key reads correctly", "; ".join(bad))
    keys, left = tb.parse_key_bytes(b"n\x1b[")
    keys2, _ = tb.parse_key_bytes(left + b"A")
    check(keys == ["n"] and keys2 == ["UP"], "escape sequence split across reads is preserved")


def test_windows_portability():
    """Platform helpers, exercised for both platforms by flipping IS_WINDOWS."""
    keys, _ = tb.parse_key_bytes(tb.win_chars_to_bytes(
        ["\xe0", "H", "\x00", "P", "\xe0", "M", "\xe0", "K", "q", " ", "\r",
         "\x08", "\x00", "\x0f", "\xe0", "I", "\xe0", "Q", "日"]))
    check(keys == ["UP", "DOWN", "RIGHT", "LEFT", "q", "SPACE", "ENTER", "BACKSPACE",
                   "BACKTAB", "PAGEUP", "PAGEDOWN", "日"],
          "Windows console keys translate to the same keys as a VT terminal", str(keys))
    check(tb.parse_key_bytes(tb.win_chars_to_bytes(["\x00", "\x3b"]))[0] == [],
          "unmapped Windows scan codes (F1) are dropped, not typed as text")

    saved = (tb.IS_WINDOWS, dict(os.environ))
    try:
        os.environ.pop("XDG_CONFIG_HOME", None)
        os.environ["APPDATA"] = "C:\\Users\\x\\AppData\\Roaming"
        tb.IS_WINDOWS = True
        check(tb._user_dir("XDG_CONFIG_HOME", "~/.config", "APPDATA") == os.environ["APPDATA"],
              "Windows config lives in %APPDATA% when XDG is unset")
        check(tb.ipc_path(42) == "\\\\.\\pipe\\termbeat-mpv-42",
              "Windows mpv IPC is a named pipe", tb.ipc_path(42))
        kw = tb._child_popen_kwargs()
        check("preexec_fn" not in kw, "Windows Popen gets no preexec_fn (Popen rejects it)")
        os.environ["XDG_CONFIG_HOME"] = "/xdg"
        check(tb._user_dir("XDG_CONFIG_HOME", "~/.config", "APPDATA") == "/xdg",
              "an explicit XDG variable still wins on Windows")
        tb.IS_WINDOWS = False
        os.environ.pop("XDG_CONFIG_HOME")
        # a runtime dir keeps the simulated POSIX path off os.getuid, which a
        # real Windows host running this test doesn't have
        os.environ["XDG_RUNTIME_DIR"] = tempfile.gettempdir()
        check(tb._user_dir("XDG_CONFIG_HOME", "~/.config", "APPDATA")
              == os.path.expanduser("~/.config"), "POSIX ignores %APPDATA%")
        check(tb.ipc_path(42).endswith("mpv-42.sock"), "POSIX mpv IPC is a UNIX socket")
        check(tb._child_popen_kwargs().get("preexec_fn") is tb._die_with_parent,
              "POSIX children still get the parent-death hook")
    finally:
        tb.IS_WINDOWS = saved[0]
        os.environ.clear()
        os.environ.update(saved[1])


def test_config_validation():
    hostile = [
        {"station": "Evil", "url": "file:///etc/passwd"},
        {"station": "NoUrl"},
        "not a dict",
        {"station": "Sparse", "url": "https://example.com/s"},
    ]
    out = tb.normalize_playlist(hostile)
    check(len(out) == 1 and out[0]["station"] == "Sparse",
          "config rejects non-http urls, missing urls and non-objects", str(out))
    check(all(k in out[0] for k in tb.STATION_DEFAULTS),
          "surviving entries have every key the renderers index")


def test_width_parity():
    import unicodedata
    def legacy(s):
        if "\x1b" in s:
            s = tb.ANSI_ESCAPE_RE.sub("", s)
        if s.isascii():
            return len(s)
        return sum(2 if (ord(c) >= 0x1100 and
                         unicodedata.east_asian_width(c) in ("W", "F")) else 1 for c in s)
    samples = ["hello", "", "日本語テスト", "─│╭╮█▰▱●⟳♫∿▔", "mixed 日本 abc ▓",
               "\033[38;2;1;2;3mabc\033[0m", "▁▂▃▄▅▆▇█" * 12]
    bad = [s for s in samples if legacy(s) != tb.str_width(s)]
    check(not bad, "str_width matches the original on non-combining input", str(bad))
    check(tb.str_width("é") == 1, "combining marks are width 0 (was wrong before)")


def test_diff_renderer_converges(app):
    """Full repaint and incremental diffs must produce the same screen."""
    cols, rows = 102, 30
    app.design_style, app.viz_mode, app.show_drawer = 0, 0, False
    full_screen = Screen(cols, rows)
    diff_screen = Screen(cols, rows)
    app._prev_lines = None
    mismatch = None
    for f in range(25):
        app.t_sec = f * 0.045
        app.update_physics()
        lines = app.render_frame(cols, rows, tb.THEMES[0], f)
        lines = lines[:rows]

        # reference: what a full repaint of this exact frame paints
        ref = Screen(cols, rows)
        body = "\n".join("\033[0m" + (l if l.endswith("\033[K") else l + "\033[K")
                         for l in lines)
        ref.feed("\033[H" + body + "\033[J")

        # subject: the incremental stream the app actually emits
        buf = []
        real_stdout = sys.stdout
        class Cap:
            def write(self, d): buf.append(d)
            def flush(self): pass
        sys.stdout = Cap()
        try:
            app.emit_frame(lines)
        finally:
            sys.stdout = real_stdout
        diff_screen.feed("".join(buf))

        if diff_screen.text() != ref.text():
            for y, (a, b) in enumerate(zip(diff_screen.text(), ref.text())):
                if a != b:
                    mismatch = f"frame {f} row {y}: diff={a[:40]!r} full={b[:40]!r}"
                    break
            break
    check(mismatch is None, "damage-tracked output paints the same screen as a full repaint",
          mismatch or "")


def test_diff_saves_bytes(app):
    cols, rows = 101, 54
    app.design_style, app.viz_mode, app.show_drawer = 0, 0, False
    app._prev_lines = None
    buf = []
    real = sys.stdout
    class Cap:
        def write(self, d): buf.append(len(d))
        def flush(self): pass
    total_full = total_diff = 0
    for f in range(40):
        app.t_sec = f * 0.045
        app.update_physics()
        lines = app.render_frame(cols, rows, tb.THEMES[0], f)[:rows]
        total_full += len("\033[H" + "\n".join(
            l + "\033[K" for l in lines) + "\033[J")
        sys.stdout = Cap()
        try:
            app.emit_frame(lines)
        finally:
            sys.stdout = real
    total_diff = sum(buf)
    ratio = total_full / max(1, total_diff)
    check(ratio > 2.0, f"diff renderer cuts output bytes ({ratio:.1f}x smaller while playing)")
    # Paused steady state. The bars fall in ~20 frames after the pause, but a
    # peak-hold cap can take 5 + 8.0 / 0.16 = 55, so settle until both are down
    # and then measure what a genuinely idle deck emits. A fixed 40-frame settle
    # made this check fail whenever the random spectrum paused on a tall peak.
    app.is_playing = False
    for f in range(200):
        app.t_sec = 100 + f * 0.2
        app.update_physics()
        app.render_frame(cols, rows, tb.THEMES[0], f)
        if max(app.band_heights) == 0 and max(app.peak_heights) == 0:
            break
    app._prev_lines = None
    buf.clear()
    for f in range(40):
        app.t_sec = 200 + f * 0.2
        app.update_physics()
        lines = app.render_frame(cols, rows, tb.THEMES[0], f)[:rows]
        sys.stdout = Cap()
        try:
            app.emit_frame(lines)
        finally:
            sys.stdout = real
    paused_bytes = sum(buf[1:])          # ignore the first full repaint
    app.is_playing = True
    check(paused_bytes < 2000,
          f"paused steady state is nearly silent ({paused_bytes} bytes over 39 frames)")


def test_cava_suspend(app):
    app.is_playing, app.is_stopped = False, False
    app.update_physics()
    check(app.cava_engine.suspended, "cava is suspended while paused")
    app.is_playing = True
    app.update_physics()
    check(not app.cava_engine.suspended, "cava resumes on play")


def test_dead_stream_is_honest(app):
    app.is_playing, app.is_stopped = True, False
    app.stream_player.state = (tb.StreamPlayer.ERROR, False)
    app.update_physics()
    txt, _ = app.status_badge(tb.THEMES[0])
    check("ERROR" in txt or "✖" in txt, f"failed stream reports an error badge ({txt!r})")
    for _ in range(40):                  # let the ballistic decay run out
        app.update_physics()
    check(max(app.band_heights) == 0.0,
          "visualizer collapses when the stream is dead, instead of faking music",
          f"max band {max(app.band_heights):.2f}")
    before = app.track_elapsed
    for _ in range(5):
        app.update_physics()
    check(app.track_elapsed == before, "elapsed timer stops when audio is not flowing")
    app.stream_player.state = (tb.StreamPlayer.PLAYING, True)


def main():
    print("termbeat test suite\n" + "=" * 70)
    app = make_app()
    test_width_parity()
    test_key_parsing()
    test_windows_portability()
    test_config_validation()
    test_cjk_titles(app)
    test_row_widths(app)
    test_tide(app)
    test_drawer_follows_selection(app)
    test_hint_ribbon(app)
    test_station_editor(app)
    test_diff_renderer_converges(app)
    test_diff_saves_bytes(app)
    test_cava_suspend(app)
    test_dead_stream_is_honest(app)
    print("=" * 70)
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
