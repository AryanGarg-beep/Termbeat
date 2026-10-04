#!/usr/bin/env python3
"""termbeat render benchmark: frame time, output bytes, and diff-renderer potential.

Stubs out mpv/cava/metadata so this measures the pure Python render path with no
subprocesses and no audio. Run:  python3 bench/benchmark_render.py
"""
import os
import re
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from termbeat import app as radio  # noqa: E402


class StubStream:
    has_mpv = True
    NO_MPV = radio.StreamPlayer.NO_MPV
    STARTING = radio.StreamPlayer.STARTING
    IDLE = radio.StreamPlayer.IDLE
    BUFFERING = radio.StreamPlayer.BUFFERING
    PLAYING = radio.StreamPlayer.PLAYING
    PAUSED = radio.StreamPlayer.PAUSED
    ERROR = radio.StreamPlayer.ERROR

    def __init__(self, *a, **k):
        self.is_connected = True
    def health(self):
        return (self.PLAYING, True)
    def get_media_title(self):
        return ""
    def __getattr__(self, _):
        return lambda *a, **k: ""


class StubCava:
    """live=True feeds real-looking band data; live=False forces the pure-Python
    simulation path (monstercat filter), which is what runs when cava is absent."""
    live = False
    def __init__(self, n=18):
        self.n = n
    def set_suspended(self, v):
        pass
    def get_bands(self):
        if StubCava.live:
            t = time.time()
            import math
            return [abs(math.sin(t * (1 + i * 0.3))) for i in range(self.n)], True
        return [0.0] * self.n, False
    def cleanup(self):
        pass


class StubMeta:
    provider_of = staticmethod(radio.MetadataScraper.provider_of)

    def __init__(self, *a, **k):
        self.playlist = a[0] if a else []
    def set_active_provider(self, p):
        pass
    def set_active_station(self, station):
        pass
    def start(self):
        pass
    def stop(self):
        pass


radio.StreamPlayer = StubStream
radio.CavaStreamEngine = StubCava
radio.MetadataScraper = StubMeta


def emit_full(lines):
    """Byte-exact copy of the write in radio.py run()."""
    return "\033[H" + "\n".join(
        l + "\033[K" if not l.endswith("\033[K") else l for l in lines
    ) + "\033[J"


def emit_diff(lines, prev):
    """Row-granular damage tracking: rewrite only rows that changed."""
    if prev is None:
        return emit_full(lines), len(lines)
    parts = []
    changed = 0
    for i, l in enumerate(lines):
        if i >= len(prev) or l != prev[i]:
            parts.append(f"\033[{i+1};1H{l}\033[K")
            changed += 1
    return "".join(parts), changed


def emit_segdiff(lines, prev):
    """Segment-granular damage tracking, approximating what ratatui/notcurses do:
    within a changed row, rewrite only the span between the common prefix and
    common suffix. Lower bound on a true cell-diff, upper bound on row-diff."""
    if prev is None:
        return emit_full(lines)
    parts = []
    for i, l in enumerate(lines):
        o = prev[i] if i < len(prev) else ""
        if l == o:
            continue
        a = 0
        n = min(len(l), len(o))
        while a < n and l[a] == o[a]:
            a += 1
        b = 0
        while b < n - a and l[len(l) - 1 - b] == o[len(o) - 1 - b]:
            b += 1
        # back off to a safe boundary: never start or end inside an escape seq
        esc = l.rfind("\033", 0, a)
        if esc != -1 and not re.match(r"\033\[[0-9;]*[a-zA-Z]", l[esc:a]):
            a = esc
        seg = l[a:len(l) - b]
        parts.append(f"\033[{i+1};{a+1}H{seg}")
    return "".join(parts)


GEOMETRIES = [(80, 24), (102, 30), (101, 54), (200, 60)]
STYLES = ["Retro Hi-Fi", "Modern Neo", "Minimal Zen", "Cyberpunk", "TIDE"]
VIZ = ["Spectrum", "Osc/Braille"]
N = 500
WARMUP = 60
FPS = 22.2


def bench(app, style, viz, cols, rows):
    app.design_style = style
    app.viz_mode = viz
    app.tuning_glitch_frames = 0
    t_cfg = radio.THEMES[app.theme_idx]

    for f in range(WARMUP):
        app.t_sec = f * 0.045
        app.update_physics()
        app.render_frame(cols, rows, t_cfg, f)

    phys, rend = [], []
    full_bytes = diff_bytes = seg_bytes = 0
    changed_rows = total_rows = 0
    prev = None
    for f in range(N):
        app.t_sec = f * 0.045
        t0 = time.perf_counter()
        app.update_physics()
        t1 = time.perf_counter()
        lines = app.render_frame(cols, rows, t_cfg, f)
        t2 = time.perf_counter()
        phys.append((t1 - t0) * 1000)
        rend.append((t2 - t1) * 1000)

        full = emit_full(lines)
        d, ch = emit_diff(lines, prev)
        sg = emit_segdiff(lines, prev)
        full_bytes += len(full.encode())
        diff_bytes += len(d.encode())
        seg_bytes += len(sg.encode())
        changed_rows += ch
        total_rows += len(lines)
        prev = lines

    tot = [p + r for p, r in zip(phys, rend)]
    tot.sort()
    return {
        "phys_p50": statistics.median(phys),
        "rend_p50": statistics.median(rend),
        "p50": tot[len(tot) // 2],
        "p95": tot[int(len(tot) * 0.95)],
        "p99": tot[int(len(tot) * 0.99)],
        "max_fps": 1000.0 / (sum(tot) / len(tot)),
        "cpu_pct": (sum(tot) / len(tot)) * FPS / 10.0,
        "full_kbs": full_bytes / N * FPS / 1024,
        "diff_kbs": diff_bytes / N * FPS / 1024,
        "seg_kbs": seg_bytes / N * FPS / 1024,
        "changed_pct": 100.0 * changed_rows / max(1, total_rows),
    }


def main():
    cava_live = "--cava-live" in sys.argv
    paused = "--paused" in sys.argv
    StubCava.live = cava_live
    app = radio.TermbeatPlayer()
    app.is_playing = not paused
    app.is_stopped = False
    app.volume = 75

    label = ("PAUSED  " if paused else "PLAYING ") + (
        "cava LIVE (real bands)" if cava_live else "cava ABSENT (simulated bands)")
    print(f"\n{'='*118}\ntermbeat render benchmark  |  {N} frames/config  |  {label}  "
          f"|  python {sys.version.split()[0]}\n{'='*118}")
    hdr = (f"{'Geometry':>9} {'Style':<12} {'Viz':<12} {'phys':>7} {'rend':>7} "
           f"{'p50':>7} {'p95':>7} {'p99':>7} {'maxFPS':>8} {'CPU%':>6} "
           f"{'full KB/s':>10} {'rowdiff':>9} {'segdiff':>9} {'rows chg':>9}")
    print(hdr)
    print("-" * 128)
    worst = None
    for cols, rows in GEOMETRIES:
        for s, sname in enumerate(STYLES):
            # TIDE is its own visualizer and ignores viz_mode, so one row covers it
            for v, vname in enumerate(["(own)"] if sname == "TIDE" else VIZ):
                r = bench(app, s, v, cols, rows)
                if worst is None or r["p50"] > worst[0]["p50"]:
                    worst = (r, f"{sname}/{vname} {cols}x{rows}")
                print(f"{cols:>4}x{rows:<4} {sname:<12} {vname:<12} "
                      f"{r['phys_p50']:>6.2f}m {r['rend_p50']:>6.2f}m "
                      f"{r['p50']:>6.2f}m {r['p95']:>6.2f}m {r['p99']:>6.2f}m "
                      f"{r['max_fps']:>8.0f} {r['cpu_pct']:>5.1f}% "
                      f"{r['full_kbs']:>9.1f} {r['diff_kbs']:>8.1f} "
                      f"{r['seg_kbs']:>8.1f} {r['changed_pct']:>8.1f}%")
        print("-" * 128)
    print(f"worst config: {worst[1]}  p50={worst[0]['p50']:.2f} ms  "
          f"({worst[0]['cpu_pct']:.1f}% of one core at {FPS} FPS)\n")


if __name__ == "__main__":
    main()
