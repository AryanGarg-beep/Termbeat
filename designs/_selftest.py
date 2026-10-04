#!/usr/bin/env python3
"""Import every design, drive its draw() headless at many sizes, check it never
crashes and returns sane rows. Run: python3 designs/_selftest.py"""
import glob
import importlib.util
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _harness import FakeAudio, fit, ansi_len  # noqa: E402

SIZES = [(80, 24), (100, 29), (36, 8), (22, 5), (200, 55), (60, 12), (120, 40)]
FRAMES = 40

designs = sorted(
    os.path.basename(p)[:-3]
    for p in glob.glob(os.path.join(HERE, "*.py"))
    if not os.path.basename(p).startswith("_") and os.path.basename(p) != "gallery.py"
)

fails = []
for name in designs:
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        draw = mod.draw
    except Exception:
        fails.append((name, "import", traceback.format_exc(limit=2)))
        continue

    a = FakeAudio()
    ok = True
    t0 = time.perf_counter()
    calls = 0
    for (w, h) in SIZES:
        for f in range(FRAMES):
            a.step(1 / 24)
            try:
                rows = draw(w, h, a, f / 24)
            except Exception:
                fails.append((name, f"draw({w}x{h})", traceback.format_exc(limit=3)))
                ok = False
                break
            calls += 1
            if not isinstance(rows, list):
                fails.append((name, f"{w}x{h}", f"returned {type(rows).__name__}, not list"))
                ok = False
                break
            # harness fit()s each row, so just require it is str and not wildly long
            for r in rows[:h]:
                if not isinstance(r, str):
                    fails.append((name, f"{w}x{h}", f"row is {type(r).__name__}"))
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            break
    dt = (time.perf_counter() - t0) / max(1, calls) * 1000
    mark = "ok  " if ok else "FAIL"
    print(f"  {mark} {name:<20} {dt:5.2f} ms/frame avg")

print()
if fails:
    for name, where, msg in fails:
        print(f"--- {name} @ {where} ---\n{msg}")
    print(f"{len(fails)} failure(s)")
    sys.exit(1)
print(f"all {len(designs)} designs pass")
