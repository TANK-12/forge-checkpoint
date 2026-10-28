# Drift Peaks

An endless downhill snowboarding game in the spirit of Alto's Adventure: our
own name, art and rider. Flat-shaded low-poly mountains, a day and night
cycle, weather, and colours that follow the Forge accent. A Forge app (port
8457, section "play", fullscreen auto).

## Play
- **Space / Up / W / click / tap**: jump. **Hold in the air**: backflip.
  Land with the board roughly along the slope (Landing forgiveness setting).
- Chained tricks (flips, grinds, rock bounces, chasms, goat catches) build a
  combo; at x3 you get a speed boost. The combo banks after ~2 s on the snow.
- **Goals** mode: 3 goals per level, 12 levels, a crash ends the run.
  **Zen** mode: no score, a fall just puts you back on the snow.
  **Today** mode: the same mountain all day and a new one tomorrow; the title
  shows today's best distance, points and runs. The title opens on the mode
  you rode last.
- A flag stands where your best run ended (Goals: best ever; Today: today's
  best) and riding past it says so. Settings: "Flag at your best distance".
- **Esc / P** pauses. Deep links: `#ride`, `#zen`, `#daily`, `#art`,
  `#settings`.

## How it is built
| File | What it is |
|---|---|
| `web_app.py` | Thin FastAPI: shapes, levels, save, sounds, music list, `/shared` mount |
| `static/js/music.js`, `music/` | Background music: every track in `DRIFTPEAKS_MUSIC` (default `music/`, git-ignored) in turn; with none, `static/js/tune.js` plays the game's own generated tune. Settings names the folder |
| `static/js/world.js` | The mountain. `FEATURES` registry of stretches (run, kicker, chasm, rocks, ropes, goat, village), weighted by distance |
| `static/js/rider.js` | Pure physics `step()` returning events; landing check, grinds, crash, zen `recover()` |
| `static/js/render.js` | Sky, sun/moon/stars/aurora, three low-poly ranges, the slope, props, rider + scarf |
| `static/js/weather.js` | `WEATHER` registry (clear, snow, blizzard, rain, fog, storm, sand gusts) |
| `static/js/palette.js` | Time-of-day keyframes; colour *roles* resolved per frame with the Forge accent |
| `static/js/modes.js` | `MODES` registry (Goals, Zen, Today): the title's buttons, the `#links`, and what a run does |
| `static/js/save.js` | `mergeSave`: the save is read before anything is written back; runs ridden while it could not be read are laid on top of it |
| `static/js/settings.js` | `SETTINGS` registry; the panel (simple/advanced, slider + number) is built from it |
| `static/js/goals.js` | Goal counting against `data/levels.json` |
| `data/shapes/*.json` | Shipped low-poly art (seeded into the shared store) |
| `data/levels.json`, `data/sounds.json` | Goal levels; sound recipes (seeded into the shared store) |

**Art is data.** Every shape is flat polygons painted with colour roles, kept in
the shared Forge content store as `~/ForgeGameData/shapes/driftpeaks-<id>.json`
(new `shapes` type in `shared/forge_content.py`). The shipped copies are seeded
once; the store copy is what the game reads and what the in-game **Art** screen
edits (Save / Put the original back). Adding decor = one shape file with
`"place": {"kind": "decor", "weight": n}`.

Saves: `~/ForgeGameData/driftpeaks/save.json` (bests, coins, goals done, settings,
the last mode, today's best). The page writes nothing until it has read the save
once: if the backend was restarting when the page opened, it reads again with
backoff, then adds what was ridden meanwhile on top (`static/js/save.js`).

## Tests
    .venv/bin/python -m pytest -q tests     # API (26)
    node --test tests/js/                   # mountain, physics, goals, modes, save (26)

Headless Chrome checks (Flatpak Chrome, not collected by pytest):
`tests/check_sweep.py` (first frame, modes, Today, the flag, resize, a save
that could not be read, 20 checks; sandboxed) and `tests/check_ui.py` (rest, save retry, Art, 13
checks). Both take a port in `DRIFTPEAKS_CHECK_PORT`. `tests/check_music.py`
still uses the real shared store.
