#!/usr/bin/env python3
"""Launcher menu for the interface mock-ups.

    python3 gui/gallery.py

↑/↓ or j/k to move, Enter to run a mock, q to quit. Each mock runs as its own
process; when you quit it (q / Ctrl-C) you land back here.
"""
import glob
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _mock import Input, THEMES, fit, RST  # noqa: E402

SKIP = {"gallery", "_mock", "_selftest"}


def load():
    out = []
    for path in sorted(glob.glob(os.path.join(HERE, "*.py"))):
        name = os.path.basename(path)[:-3]
        if name in SKIP or name.startswith("_"):
            continue
        doc = ""
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            doc = (m.__doc__ or "").strip().splitlines()[0]
        except Exception as exc:            # pragma: no cover
            doc = f"(load error: {exc})"
        out.append((name, doc))
    return out


def main():
    items = load()
    if not items:
        print("no mocks found")
        return
    th = THEMES["Classic Tuna"]
    sel = 0
    sys.stdout.write("\033[?1049h\033[?25l")
    try:
        with Input() as keys:
            while True:
                cols, rows = os.get_terminal_size()
                buf = ["\033[H\033[2J"]
                buf.append(fit(f" {th['accent']}termbeat · interface mock-ups{RST}"
                               f"   {th['dim']}↑/↓ · Enter to run · q quits{RST}", cols))
                buf.append(fit(f" {th['frame']}{'─' * (cols - 2)}{RST}", cols))
                buf.append("")
                for i, (name, doc) in enumerate(items):
                    mark = f"{th['accent']} ▸ " if i == sel else "   "
                    nm = th['bright'] if i == sel else th['text']
                    buf.append(fit(f"{mark}{nm}{name:<18}{RST} {th['dim']}{doc}{RST}", cols))
                buf.append("")
                buf.append(fit(f" {th['dim']}also: python3 gui/<name>.py   ·   "
                               f"python3 gui/_selftest.py{RST}", cols))
                sys.stdout.write("\n".join(buf))
                sys.stdout.flush()

                ev = None
                while ev is None:
                    got = keys.get()
                    for e in got:
                        ev = e
                        break
                    if ev is None:
                        import time
                        time.sleep(0.03)
                if ev in ("q", "Q", "QUIT", "ESC"):
                    break
                if ev in ("DOWN", "j"):
                    sel = (sel + 1) % len(items)
                elif ev in ("UP", "k"):
                    sel = (sel - 1) % len(items)
                elif ev == "ENTER":
                    name = items[sel][0]
                    sys.stdout.write("\033[?1049l\033[?25h")
                    sys.stdout.flush()
                    subprocess.run([sys.executable, os.path.join(HERE, name + ".py")])
                    sys.stdout.write("\033[?1049h\033[?25l")
                    sys.stdout.flush()
    finally:
        sys.stdout.write("\033[?25h\033[0m\033[?1049l")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
