#!/usr/bin/env python3
"""Flip through every visualizer sketch in this folder.

    python3 designs/gallery.py            # auto-advances every 9 s
    python3 designs/gallery.py fire       # start on a given sketch

Keys:  ->/n next   <-/p prev   space pause auto-advance   r reseed audio   q quit
"""
import glob
import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _harness import FakeAudio, KeyReader, fit, ACCENT, DIM, WARN, BRIGHT, RST

SKIP = {"gallery", "_harness", "_selftest"}
AUTO_SECS = 9.0
FPS = 24


def load():
    mods = []
    for path in sorted(glob.glob(os.path.join(HERE, "*.py"))):
        name = os.path.basename(path)[:-3]
        if name in SKIP or name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(m)
            doc = (m.draw.__doc__ or m.__doc__ or "").strip().splitlines()[0]
        except Exception as exc:                       # pragma: no cover
            print(f"skip {name}: {exc}")
            continue
        mods.append((name, m.draw, doc))
    return mods


def main():
    designs = load()
    if not designs:
        print("no designs found")
        return
    idx = 0
    if len(sys.argv) > 1:
        for i, (n, _, _) in enumerate(designs):
            if n == sys.argv[1]:
                idx = i
                break

    audio = FakeAudio()
    paused_auto = False
    sys.stdout.write("\033[?1049h\033[?25l\033[2J")
    sys.stdout.flush()
    try:
        with KeyReader() as keys:
            t0 = time.monotonic()
            last = t0
            switched = t0
            while True:
                now = time.monotonic()
                audio.step(min(now - last, 0.1))
                last = now

                k = keys.get()
                if k == "QUIT":
                    break
                elif k in ("RIGHT", "n", "N"):
                    idx = (idx + 1) % len(designs)
                    switched = now
                elif k in ("LEFT", "p", "P"):
                    idx = (idx - 1) % len(designs)
                    switched = now
                elif k == "SPACE":
                    paused_auto = not paused_auto
                    switched = now
                elif k in ("r", "R"):
                    audio.__init__()
                if not paused_auto and now - switched >= AUTO_SECS:
                    idx = (idx + 1) % len(designs)
                    switched = now

                cols, rows = os.get_terminal_size()
                w, h = cols, max(1, rows - 2)
                name, draw, doc = designs[idx]
                try:
                    body = draw(w, h, audio, now - t0)
                except Exception as exc:               # keep the gallery alive
                    body = [f"{WARN}{name} raised {type(exc).__name__}: {exc}{RST}"]

                tag = "AUTO" if not paused_auto else "HELD"
                head = fit(f"{ACCENT}{idx + 1:2d}/{len(designs)}  {BRIGHT}{name}{RST}"
                           f"   {DIM}{doc}{RST}", w)
                foot = fit(f"{DIM}->/n  <-/p  space:{tag}  r:reseed  q:quit{RST}", w)
                out = ["\033[H" + head + "\033[K"]
                for r in range(h):
                    out.append(fit(body[r] if r < len(body) else "", w) + "\033[K")
                out.append(foot + "\033[K")
                sys.stdout.write("\n".join(out) + "\033[J")
                sys.stdout.flush()
                time.sleep(max(0.0, 1.0 / FPS - (time.monotonic() - now)))
    finally:
        sys.stdout.write("\033[?25h\033[0m\033[?1049l")
        sys.stdout.flush()
        print("closed.")


if __name__ == "__main__":
    main()
