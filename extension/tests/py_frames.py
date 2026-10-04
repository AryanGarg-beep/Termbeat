#!/usr/bin/env python3
"""Render reference frames from the terminal app for the extension's parity test.

Prints JSON: the station list plus, for each case, the Retro Hi-Fi rows with
ANSI stripped. The state is fixed (no physics step, no randomness) so the JS
deck can be put in exactly the same state and must produce the same text.
"""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location("tbtests", os.path.join(ROOT, "tests", "test_termbeat.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
tb = mod.tb

STATE = json.loads(sys.argv[1])
CASES = json.loads(sys.argv[2])

app = mod.make_app()
app.is_playing = True
app.is_stopped = False
app.repeat_mode = True
app.volume = STATE["volume"]
app.is_muted = False
app.stream_state = tb.StreamPlayer.PLAYING
app.track_elapsed = STATE["trackElapsed"]
app.track_duration = None
app.t_sec = STATE["tSec"]
app.band_heights = list(STATE["bands"])
app.peak_heights = list(STATE["peaks"])
app.bass_energy, app.mid_energy, app.treble_energy = STATE["energy"]
app.design_style = 0
app.tuning_glitch_frames = 0

frames = {}
for case in CASES:
    app.viz_mode = case["viz"]
    app.show_drawer = case["drawer"]
    app.drawer_selected_idx = case.get("sel", 0)
    app.drawer_scroll_offset = 0
    t_cfg = tb.THEMES[case.get("theme", 0)]
    lines = app.render_frame(case["cols"], case["rows"], t_cfg, 0)
    frames[case["name"]] = [tb.ANSI_ESCAPE_RE.sub("", l) for l in lines]

print(json.dumps({"stations": tb.PLAYLIST, "frames": frames}, ensure_ascii=False))
