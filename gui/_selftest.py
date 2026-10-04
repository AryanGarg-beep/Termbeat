#!/usr/bin/env python3
"""Import every mock, drive it headless (feed a script of events, render at many
sizes), check it never crashes and returns sane rows.
Run: python3 gui/_selftest.py"""
import glob
import importlib.util
import os
import re
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _mock import THEMES, fit  # noqa: E402

SIZES = [(100, 30), (80, 24), (120, 40), (64, 20), (200, 55), (72, 18)]
SGR = re.compile(r"\033\[[0-9;]*m")
EVENTS = ["SPACE", "n", "n", "TAB", "DOWN", "DOWN", "ENTER", "RIGHT", "+", "+",
          "m", "t", "1", "2", "3", "4", "5", "BACKTAB", "p", "LEFT", "l",
          "MOUSE_DOWN:10:5", "MOUSE_DRAG:30:5", "MOUSE_UP:30:5",
          "MOUSE_WHEELUP:20:8", "MOUSE_WHEELDOWN:20:8", "CTRL_P", "ESC",
          "BACKSPACE", "a", "b", "/"]

mocks = sorted(
    os.path.basename(p)[:-3]
    for p in glob.glob(os.path.join(HERE, "*.py"))
    if not os.path.basename(p).startswith("_") and os.path.basename(p) != "gallery.py"
)

fails = []
for name in mocks:
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        App = mod.App
    except Exception:
        fails.append((name, "import", traceback.format_exc(limit=3)))
        continue

    ok = True
    t0 = time.perf_counter()
    frames = 0
    for (w, h) in SIZES:
        try:
            app = App()
        except Exception:
            fails.append((name, "App()", traceback.format_exc(limit=3)))
            ok = False
            break
        for k, ev in enumerate(EVENTS):
            if hasattr(app, "step"):
                app.step(0.1)
            try:
                app.handle(ev)
            except Exception:
                fails.append((name, f"handle({ev!r})", traceback.format_exc(limit=3)))
                ok = False
                break
            try:
                th = THEMES[getattr(app, "theme", "Classic Tuna")]
                rows = app.render(w, h - 1, th)
            except Exception:
                fails.append((name, f"render({w}x{h})", traceback.format_exc(limit=4)))
                ok = False
                break
            frames += 1
            if not isinstance(rows, list):
                fails.append((name, f"{w}x{h}", f"render returned {type(rows).__name__}"))
                ok = False
                break
            for r in rows:
                if not isinstance(r, str):
                    fails.append((name, f"{w}x{h}", f"row is {type(r).__name__}"))
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            break
    dt = (time.perf_counter() - t0) / max(1, frames) * 1000
    print(f"  {'ok  ' if ok else 'FAIL'} {name:<18} {dt:5.2f} ms/frame")

print()
if fails:
    for name, where, msg in fails:
        print(f"--- {name} @ {where} ---\n{msg}")
    print(f"{len(fails)} failure(s)")
    sys.exit(1)
print(f"all {len(mocks)} mocks pass")
