# gui/ — interface mock-ups

Runnable, interactive previews of the ideas in
[`../rs/gui-ideas.md`](../rs/gui-ideas.md). Nothing plays audio; a `Player`
fakes the state a real termbeat carries (station list, now-playing, volume,
elapsed, buffering, history) so the interface has something to move against.
Pure Python standard library.

## Running

```sh
python3 gui/gallery.py             # a launcher menu — ↑/↓, Enter to run one, q to return
python3 gui/tabs.py                # run one directly
python3 gui/_selftest.py           # headless: drive every mock, check it doesn't break
```

`q` / `Ctrl-C` quits any mock and restores the terminal. `mouse.py` turns on
terminal mouse reporting while it runs.

## What's here

| File | Idea | Try |
| :-- | :-- | :-- |
| `deck.py` | baseline player panel every other mock builds on | `space` `n`/`p` `+`/`-` `m` `t` |
| `tabs.py` | 1.4 — Now Playing / Stations / History / Settings / Help | `Tab` or `1`-`5`; arrows + `Enter` inside a tab |
| `dashboard.py` | 1.3 — split panes, station list left + player right | `Tab` switches focus; arrows + `Enter` |
| `mini_mode.py` | 1.1 — one-line status render (tmux / tiny window) | `f` toggles full ↔ mini |
| `command_palette.py` | 2.2 — fuzzy finder over stations + actions | `Ctrl-P` or `:`, type, `↑`/`↓`, `Enter` |
| `help_overlay.py` | 2.8 — grouped, dimmed key reference | `?` |
| `mouse.py` | 2.1 — click buttons, drag/wheel volume, click a station | use the mouse; shows the hit-map approach |
| `history_panel.py` | 3.2 — recently-played with timestamps | `h`; `↑`/`↓` scroll; `Enter` re-tune |
| `toasts.py` | 6.2 — transient stacking notifications | every key raises one; a blip fires on its own |
| `themes.py` | 4.1 — 10 palettes (termbeat 5 + Gruvbox/Nord/Dracula/Solarized/Mono) | `←`/`→` |
| `tuning_knob.py` | 5.1 — analog FM dial that sweeps through static and locks | `←`/`→` sweep; `n`/`p` next preset |
| `eq_panel.py` | 5.3 — 10-band graphic EQ with presets | `←`/`→` pick band, `↑`/`↓` adjust, `1`-`5` presets, `0` flat |
| `station_editor.py` | 7.2 — add/edit/remove a station in a form | `↑`/`↓` fields, type, `Ctrl-N`/`Ctrl-D`/`Ctrl-S`, `PgUp`/`PgDn` |
| `design_styles.py` | 4.3 — Rack Unit / Boombox / Teletext / Terminal-native / Braun | `←`/`→` |
| `boot_standby.py` | 4.5 + 1.6 — power-on animation, then an idle screensaver | wait; `b` replays boot; idle 12 s for standby |
| `tesla.py` | — car head-unit "MUSIC" screen (status bar, nav rail, neon cassette, climate strip), sketched from a reference image | `space` play · `n`/`p` track · `s`/`r` · `+`/`-` vol · `f` fav · `1`-`6` nav · `a` auto-demo |

Not mocked yet (from `rs/gui-ideas.md`): screensaver variants, focus/zen mode,
size presets, peek, row context menu, up-next, station info card, structured
now-playing, buffer readout, live log pane, session stats, auto theme, border
styles, Nerd-Font mode, dim-on-blur, preset bank, crossfade, balance, genre
chips, clipboard yank, now-playing splash, undo, first-run tour, keybinding
editor.

## Writing a mock

Each file is an `App` class + `if __name__ == "__main__": run(App())`.

```python
#!/usr/bin/env python3
"""My idea  (gui-ideas X.Y)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mock import Player, render_deck, run, THEME_ORDER

class App:
    title = "my idea"
    def __init__(self):
        self.pl = Player()
        self.theme = THEME_ORDER[0]      # a key of _mock.THEMES
        self.t = 0.0
    def step(self, dt):                   # optional
        self.t += dt
        self.pl.step(dt)
    def handle(self, ev):                 # ev: key string, or a "MOUSE_*:x:y" string
        if ev == "SPACE": self.pl.toggle_play()
    def render(self, w, h, th):           # -> list of h strings, w cells each
        return render_deck(self.pl, w, h, th, self.t)

if __name__ == "__main__":
    run(App())                            # run(App(), mouse=True) to get mouse events
```

`gallery.py` and `_selftest.py` pick it up automatically. Files starting with `_`
are ignored.

### `_mock.py` provides

- **`Player`** — `.station`, `.state` (`PLAYING`/`PAUSED`/`BUFFERING`), `.track`,
  `.track_elapsed` / `.track_len` (some stations have a duration, some are live),
  `.volume`, `.muted`, `.repeat`, `.listeners`, `.history` (deque of
  `(track, station, wallclock)`), and `.step(dt)` to advance it. Mutators:
  `tune(i)`, `next()`, `prev()`, `toggle_play()`, `nudge_volume(d)`,
  `toggle_mute()`.
- **`run(app, *, fps=30, mouse=False)`** — the full-screen loop + terminal
  setup/teardown + signal handling. Calls `app.step`, `app.handle`, `app.render`.
- **`render_deck(pl, w, h, th, t, *, progress=, spin=, viz=, hint=)`** — the
  shared termbeat-style player panel, returned as `h` rows of `w` cells.
- **`box(lines, w, th, title=, style=)`** — a framed panel; `style` ∈
  `round` `square` `double` `ascii` `heavy`.
- **`THEMES`** / `THEME_ORDER` — 10 palettes, each a dict of pre-built escape
  strings (`frame` `panel` `text` `dim` `accent` `bright` `warn` `accent_bg`).
- **`Input`** — `get()` returns per-frame events: key strings (`"UP"`, `"ENTER"`,
  `"CTRL_P"`, `"ESC"`, printable chars) and mouse strings
  (`"MOUSE_DOWN:x:y"`, `…UP`, `…DRAG`, `…WHEELUP`, `…WHEELDOWN`).
- **`mouse(ev)`** → `(kind, x, y)` or `None`.
- **`fit(s, w)`**, `center(s, w)`, `ansi_len(s)`, `marquee(text, w, t)`,
  `spinner(t)`, `hbar` / `dotbar`, `transport(pl, th)`, `volume_slider(pl, w, th)`,
  `fg` / `bg` / `RST`.

## Notes

- **Previews, not the real thing.** State is synthetic and the loop full-repaints
  every frame (no damage tracking). Fine for eyeballing; a real integration goes
  through termbeat's `emit_frame` diff renderer and reads `self.*` off the real
  `TermbeatPlayer`.
- `_selftest.py` prints ms/frame per mock — all are well under 0.4 ms at every
  size it tries.
- The `mouse.py` hit-map (`self.regions = [(x0,x1,y0,y1,action), …]` built during
  `render`, tested on click) is the pattern [`../rs/gui-ideas.md`](../rs/gui-ideas.md) calls out as the
  thing the current string-building renderers lack — it falls out naturally if
  the four `render_*` methods move to a declarative layout (improvement idea 3.2).
