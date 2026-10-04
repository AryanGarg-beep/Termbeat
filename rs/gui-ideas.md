# termbeat — Interface / GUI Ideas

*Companion to [`improvement-ideas.md`](improvement-ideas.md) and
[`visualizer-ideas.md`](visualizer-ideas.md). This one is
about the terminal **interface** — layout, input, panels, chrome, widgets — not the audio
visualizer and not the fix backlog.*

> **Runnable mock-ups:** 15 of these are prototyped in [`../gui/`](../gui/) against a fake
> player. Run `python3 gui/gallery.py` for a launcher menu, or `python3 gui/<name>.py` for
> one. See `gui/README.md` for the file→idea map. Nothing is wired into `radio.py`.

Value / effort tags as before: **S** small · **M** medium · **L** large or needs a new
subsystem. Where an idea leans on the layout-engine refactor (idea 3.2 in
`improvement-ideas.md`), it says so.

---

## 1. Layout & window modes

| # | Idea | Detail | V / E |
| :-- | :-- | :-- | :-- |
| 1.1 | **Mini / status-line mode** | a one-line render (`♫ Groove Salad · Artist – Title · ▸ 75%`) suitable for a tmux `status-right`, a polybar module, or just a tiny window. Toggle with a key or `--mini`. | high / M |
| 1.2 | **Focus / zen mode** | hide all chrome — just album art (if enabled), the track line, and a thin progress rule, centred. `z` toggles. Minimal Zen is close; this goes further. | med / S |
| 1.3 | **Dashboard split (no drawer)** | a persistent station list docked left, the player right, instead of the overlay drawer. `Tab` moves focus between panes. Needs 3.2. | high / L |
| 1.4 | **Tabbed views** | `[Now Playing] [Stations] [History] [Settings] [Help]` along the top, `Tab`/`Shift-Tab` or number keys to switch. Turns the drawer + future settings/history into first-class views. Needs 3.2. | high / L |
| 1.5 | **Deliberate size presets** | not just responsive — `F1/F2/F3` for "Tower" / "Deck" / "Bar", each a fixed target size the app draws to and centres, ignoring extra space. | low / S |
| 1.6 | **Screensaver / standby** | after N idle minutes, drop to a bouncing-logo or full-screen-visualizer-no-chrome mode; any key restores. `--standby 10m`. | med / S |
| 1.7 | **Dock side** | drawer / sidebar can be left, right, or hidden (`[`, `]`). | low / S |
| 1.8 | **Portrait / thin mode** | a < 40-col vertical stack for phone-width terminals and side panes. Extends the existing breakpoint logic. | med / M |

## 2. Navigation & input

| # | Idea | Detail | V / E |
| :-- | :-- | :-- | :-- |
| 2.1 | **Mouse support** | SGR 1006 mouse: click the transport buttons, click a station row, drag the volume slider, click the frequency dial to tune, wheel over the volume to change it, wheel over the drawer to scroll. **Architectural note:** the renderers emit plain strings today, so this needs a hit-map built alongside each frame (region → action), or fixed per-layout button rects. Pairs with 3.2. | high / M–L |
| 2.2 | **Command palette** | `Ctrl-P` / `:` opens a fuzzy finder over *stations + every action* ("play def con", "theme matrix", "sleep 30m"). One widget replaces a lot of keybindings and is discoverable. | high / M |
| 2.3 | **Incremental search in the drawer** | `/` to filter the station list as you type; `n`/`N` to step matches. | med / S |
| 2.4 | **Vim keys in lists** | `j`/`k`/`g`/`G`/`Ctrl-D`/`Ctrl-U` in the drawer and any future list. | low / S |
| 2.5 | **History stack** | `<` / `>` walk back and forward through stations you've played this session, browser-style. | med / S |
| 2.6 | **Peek** | hold `l` to show the station list, release to dismiss (vs. toggle). | low / S |
| 2.7 | **Row context menu** | a key (or right-click) on a station → Play · Favourite · Edit · Copy URL · Remove. | med / M |
| 2.8 | **`?` help overlay** | a grouped, scrollable key reference over a dimmed frame. The status bar only ever shows a slice. | high / S |
| 2.9 | **Numeric entry** | type `v70` to set volume, `g12` to go to station 12, `88.5` to tune by frequency. | low / S |

## 3. Information panels

| # | Idea | Detail | V / E |
| :-- | :-- | :-- | :-- |
| 3.1 | **Track progress bar** | Nightwave Plaza and Radio Paradise return `position` + `length`; draw a real elapsed/total bar with a filled portion for those. Live streams keep the `[LIVE]` pill. | high / S |
| 3.2 | **Recently played** | a scrollable list of the last ~20 distinct tracks with wall-clock timestamps, per station or global. `h` toggles. | high / M |
| 3.3 | **Up next** | Radio Paradise exposes upcoming tracks — show 1–3 ahead when available. | med / M |
| 3.4 | **Station info card** | description, genre tags, current DJ (SomaFM has one), listener count, bitrate + codec, "on air since". Shown on hover/selection in the drawer or as a `[Info]` tab. | med / M |
| 3.5 | **Structured now-playing** | split `Artist – Title` into labelled fields (Artist / Title / Album / Year) where the API gives them, instead of one marquee string. | med / S |
| 3.6 | **Buffer / network readout** | a technical panel: buffered seconds (mpv `demuxer-cache-duration`), download kbps, reconnect count, codec, sample rate. `Ctrl-I`. | low / S |
| 3.7 | **Live log pane** | tail `~/.local/state/termbeat/termbeat.log` in a togglable pane for debugging. | low / S |
| 3.8 | **Session stats** | time listened, stations visited, tracks heard — shown on quit or in a tab. | low / S |

## 4. Chrome, themes, new design styles

| # | Idea | Detail | V / E |
| :-- | :-- | :-- | :-- |
| 4.1 | **More colour themes** | Gruvbox, Nord, Dracula, Solarized (light + dark), Tokyo Night, Catppuccin, a true **monochrome / no-colour** theme for TTYs and `NO_COLOR`. Each is one dict in `THEMES`. | high / S |
| 4.2 | **Auto theme** | pick light vs dark from the terminal background (OSC 11 query) or the clock (light by day). `--theme auto`. | med / M |
| 4.3 | **New design styles** | `render_*` siblings — "Rack Unit" (19" studio rack), "Boombox" (80s), "Walkman" (portable), "Teletext" (blocky 40-col ceefax), "Terminal-native" (no chassis art at all — clean typographic layout), "Braun" (Dieter Rams minimal). Cheaper once 3.2 lands. | med / M each |
| 4.4 | **Border style toggle** | rounded / square / double / ASCII-only, independent of the design aesthetic (helps on fonts with poor box-drawing). | low / S |
| 4.5 | **Boot sequence** | a brief "power on" animation on launch (segment test, VU sweep, "TUNING…"), skippable with any key. Fits the hi-fi conceit. | low / S |
| 4.6 | **CRT flourish** | optional subtle scanline dim + a one-frame roll on theme/station change. `--crt`. | low / S |
| 4.7 | **Nerd Font mode** | use powerline / Nerd Font glyphs for the transport and status icons when available (env sniff or a flag), ASCII fallback otherwise. | low / M |
| 4.8 | **Dim on blur** | terminal focus in/out events (`\033[?1004h`) → lower brightness when the terminal isn't focused. | low / S |
| 4.9 | **Configurable accent** | one accent colour override applied on top of any theme. | low / S |

## 5. Controls & widgets

| # | Idea | Detail | V / E |
| :-- | :-- | :-- | :-- |
| 5.1 | **Tuning knob** | lean into the FM metaphor: `←`/`→` sweep the frequency dial with static between stations and "lock" onto the nearest preset. Mouse-draggable. | med / M |
| 5.2 | **Preset bank** | six always-visible buttons `P1–P6`; number or click to recall, long-press / `Shift-n` to store the current station. Like a car radio. | med / M |
| 5.3 | **Graphic EQ panel** | mpv `af=superequalizer` — a real 10-band EQ with sliders you adjust with the keyboard or mouse; presets (Flat / Bass / Vocal / Loudness). | med / M |
| 5.4 | **Draggable volume / seek** | the volume slider (and 3.1's progress bar) respond to click + drag, not just `+`/`-`. | med / S (after 2.1) |
| 5.5 | **Sleep-timer dial** | a small clock-face widget; `[`/`]` add/remove 5 min; shows a countdown, then stops playback. | high / S |
| 5.6 | **Crossfade / gapless toggle** | mpv can crossfade on `loadfile`; a switch for it. | low / S |
| 5.7 | **Balance / mono** | `af=pan` for L/R balance and a mono fold-down toggle. | low / S |
| 5.8 | **Genre chip bar** | clickable chips (CHILL · SPACE · VAPOR · …) that filter the station list. | med / M |

## 6. Feedback & polish

| # | Idea | Detail | V / E |
| :-- | :-- | :-- | :-- |
| 6.1 | **Terminal title** | set the window/tab title via OSC 0 to `♫ Artist – Title — termbeat`, so it shows in the terminal tab and the OS taskbar. Restore on exit. Nearly free, high visibility. | high / S |
| 6.2 | **Toasts** | transient bottom-right messages — "Tuned to Groove Salad", "Added to favourites", "Reconnecting…". A small queue + fade. | med / S |
| 6.3 | **Buffering spinner** | a braille spinner next to the status badge while `BUFFERING`, instead of a static word. | med / S |
| 6.4 | **Copy to clipboard** | `y` yanks `Artist – Title` (or the station URL) via OSC 52 — works over SSH. | med / S |
| 6.5 | **Now-playing splash** | on track change, 2–3 s of a big centred artist/title (FIGlet-ish or just large spacing), then fade back. Opt-in. | low / M |
| 6.6 | **Confirm destructive actions** | a yes/no bar before removing a station or resetting config. | low / S |
| 6.7 | **Undo** | one-level undo for station-list edits. | low / M |
| 6.8 | **Bell hooks** | optional terminal bell on reconnect / error / track change (each individually opt-in). | low / S |

## 7. Onboarding & settings

| # | Idea | Detail | V / E |
| :-- | :-- | :-- | :-- |
| 7.1 | **In-app settings screen** | toggle options, pick theme/style, set poll interval, set min size — instead of hand-editing JSON. Writes the config file. | high / M |
| 7.2 | **In-app station editor** | a form to add / edit / remove a station (name, URL, freq, genre, provider) with validation, live-reloading into the running list. | high / M |
| 7.3 | **First-run tour** | a 3–4 card intro on the very first launch (keys, `?`, the drawer, themes). | med / S |
| 7.4 | **Keybinding editor** | a screen that lists actions and lets you rebind; persists to config. `handle_key` already routes by a single string. | low / M |
| 7.5 | **Context-adaptive hint bar** | the status bar already changes with the drawer; extend it to reflect focus (list vs player), playback state, and available actions. | med / S |

## 8. Small high-value wins (do any time)

| # | Idea | V / E |
| :-- | :-- | :-- |
| 8.1 | **`?` help overlay** (2.8) — the single biggest discoverability gain | high / S |
| 8.2 | **Terminal title** (6.1) — track name in the tab, ~15 lines | high / S |
| 8.3 | **Track progress bar** (3.1) — data is already fetched | high / S |
| 8.4 | **Monochrome / `NO_COLOR` theme** (4.1) — correctness for TTYs and pipes | high / S |
| 8.5 | **Sleep-timer dial** (5.5) | high / S |
| 8.6 | **Toasts** (6.2) — makes every other action feel responsive | med / S |
| 8.7 | **Buffering spinner** (6.3) | med / S |
| 8.8 | **Boot sequence** (4.5) — cheap character | low / S |

---

## If forced to pick five

1. **Mouse support** (2.1) — the biggest single change to how the thing *feels*; do it
   alongside the layout-engine refactor so hit-testing has somewhere to live.
2. **Command palette** (2.2) — discoverability + speed, and it scales as features grow.
3. **`?` help overlay** (2.8) + **terminal title** (6.1) — two tiny changes, outsized
   payoff.
4. **Track progress bar** (3.1) + **recently-played panel** (3.2) — the information users
   actually want from a radio and the metadata is already in hand.
5. **In-app settings + station editor** (7.1, 7.2) — removes the "hand-edit JSON" barrier
   that limits who can use it.

Tabbed views (1.4) or the dashboard split (1.3) is the higher-ceiling structural bet, but
both really want the layout-engine refactor first.

---

## Architectural notes

- **Hit-testing (for 2.1, 5.1, 5.4):** the four `render_*` methods build rows as strings
  with no record of what is where. Mouse support needs either (a) a `regions: list[(rect,
  action)]` the renderer populates as it lays out, or (b) fixed per-layout button
  rectangles keyed off the known chassis geometry. (a) is cleaner and falls out naturally
  if the renderers move to a declarative layout (idea 3.2).
- **Modal views (1.4, 7.1, 7.2, 2.2):** today `run()` has one render path. A small
  `self.view` enum + a dispatch in `render_frame`, with each view owning its own key
  handler, keeps this manageable without a framework.
- **Everything here stays standard-library.** Mouse, focus events, bracketed paste, OSC
  0/11/52 are all just escape sequences to write and parse — the same territory as the
  existing `parse_key_bytes`.
