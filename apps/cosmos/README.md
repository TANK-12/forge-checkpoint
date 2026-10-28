# Cosmos

A real map of the solar system and the galaxy, plus gravity games. It is a Forge
hub app (port **8446**, the 🪐 tile) and runs standalone too.

It is built over several sessions. **A new session should read, in order:**
`MANIFEST.json` → `manifests/roadmap.json` → the newest `manifests/session-NN.json`
→ `WIP.md`.

## What it does now

**Solar system and galaxy map** (`#map`)

- The Sun, the eight planets, Pluto, Ceres, Haumea, Makemake and Eris, and 21
  moons at their real positions for any moment from 1600 to 2400. JPL's
  approximate planet elements are good from 1800 to 2050, and the map says so
  outside that window.
- Time runs from real time up to 10 years per second, forwards or backwards,
  or you can jump to any date.
- Orbit lines, labels that avoid overlapping, and click-for-details: distance
  from the Sun and Earth, light time, orbital speed and period, radius, mass.
- What is coming up in Earth's sky, in a body's details: the Moon's phase and
  how much of it is lit, its next full and new moon, and a planet's next
  opposition (when it is closest and up all night). Worked out from the
  ephemeris by `static/core/events.js`.
- The moons are fitted to JPL Horizons positions (`tools/fit_moons.mjs`):
  most sit within a degree or two of where JPL puts them from 2000 to 2045.
- Planets are enlarged so they stay visible, with a toggle for true sizes.
  Saturn and Uranus have rings, and every body is tilted to its real pole.
- One continuous zoom from a moon out to 109,389 real stars from the HYG
  catalogue. Each star's brightness is worked out from wherever the camera
  is, so flying out changes the sky. Star labels and search use proper names
  and Bayer/Flamsteed names ("α Centauri", "61 Cygni").
- At galaxy scale, a drawn model of the Milky Way is placed in the real
  galactic frame, with the Sun 8.2 kpc from the centre. It is labelled as a
  model.

**Gravity sandbox** (`#sandbox`)

- Place stars, planets, moons and black holes, then drag to throw them. A
  dotted path preview shows where they will go, and "circular orbit" help
  starts them on a stable orbit.
- Spray dust onto orbits, move bodies, pin them in place, follow one, and see
  whether its orbit is bound and its period.
- Bodies merge on collision, keeping mass and momentum; a black hole's size
  grows with its mass. Readouts show energy drift and momentum.
- Presets and saves are plain JSON in `~/ForgeGameData/cosmos/scenarios/`.
  Saving never overwrites an existing file.

**Orbit puzzles** (`#puzzles`)

- Launch a probe in 3D and let real gravity carry it to a goal:
  - reach a moving planet
  - settle into an orbit
  - pass rings in order
  - land gently
- Ten hand-made levels go from a first shot to a Jupiter slingshot. Levels 8
  to 10 use real masses and orbit sizes from `data/bodies`, with sizes drawn
  larger.
- **Endless mode** builds a new level each time. Each one is flown once to
  prove it can be solved before you see it.
- **Galaxy playground** is a huge explore level with no goal and no way to
  fail:
  - 40 star systems along three spiral arms round a black hole, about
    8,400 units across, with 92 planets and 10 asteroid belts
  - a painted galactic glow
  - flying close to a star discovers it, and every discovery is saved at
    once (`explore` in the progress file)
- **Aiming:** drag out from the probe, or type the speed, heading and
  elevation.
  - Time waits while you aim.
  - The dotted preview is the exact path. It gets shorter on harder levels.
- **Fuel** (delta-v) appears on later levels, for prograde, retrograde, radial
  and normal burns.
- A failed try leaves a faint **ghost** of its path.
- **Stars:** one for finishing, one for par (launch speed plus burns), one for
  a bonus goal.
- **Hazards:** planets, black holes, asteroid belts, and an edge of space set
  fifty times beyond the level so long shots work.
- Stars and best results are saved to
  `~/ForgeGameData/cosmos/puzzle-progress.json`.

## Controls

The map has a **Keys and controls** button (`?`). In short:

- **Mouse:** drag to turn, right-drag to pan, scroll to zoom, click for
  details, double-click to fly to something.
- **Keys:** `/` search, `space` play or pause time, `[` `]` speed, `r`
  backwards, `n` now, `h` home, `o`/`l`/`t` toggles, `c` follow.

**Sandbox keys:**

- **Tools:** `v` select, `s` star, `p` planet, `m` moon, `b` black hole, `d` dust.
- **Time:** `space` pause, `.` step, `[` `]` speed.
- **Bodies:** `c` follow, `Del` delete, `r` restart.
- **Toggles:** `t` trails, `g` path preview, `o` orbit help.

**Puzzle keys:**

- **Flight:** `space` launch or pause, `r` retry, `n` next level, `[` `]` time
  warp.
- **Aiming:** arrow keys nudge heading and speed.
- **Burns (hold):** `w` `s` prograde and retrograde, `a` `d` radial in and out,
  `q` `e` normal and anti-normal.
- **View:** `g` path preview, `c` follow the probe, `h` fit the level, `?` help.
- **Power saver / Smooth** (top bar): Power saver, the default, draws every
  other frame. Flying the galaxy measured 12.0 W that way, against 14.5 W on
  Smooth.

`f` is full screen everywhere; `Esc` backs out one level.

## How it is built

```
web_app.py              thin FastAPI: discovery, catalog files, scenario save
tools/build_star_catalog.py   HYG CSV -> packed binary (stdlib only)
data/bodies/*.json      one file per body: orbit, size, mass, colour, blurb
static/
  index.html, app.js    shell: menu built from /api/modes, hash routing
  core/                 shared by every mode, no DOM, tested under Node
    units.js            constants, Julian dates, distance formatting
    vec.js              3-vectors, equatorial -> ecliptic
    ephemeris.js        orbits from elements (Standish and Kepler models)
    nbody.js            2D gravity: leapfrog, particles, merging, prediction
    nbody3d.js          3D: bodies on Kepler rails, a free-falling probe, prediction
    puzzle.js           puzzle rules: level checks, launch, goals, hazards, burns, stars
    levelgen.js         endless levels (solvable by construction) and the level solver
    galaxy.js           the Milky Way model and the galactic frame
    color.js            star colour from B-V
    constellations.js   the 88 constellations, star name formatting
  modes/<id>/mode.json  a mode is discovered by this file
  modes/map/            view.js (Three.js scene) + mode.js (panels, input)
  modes/sandbox/        mode.js (Canvas 2D)
  modes/puzzles/        view.js (Three.js scene) + mode.js (screens, input, sound, saving)
  vendor/               Three.js 0.186 (MIT), saved locally
tools/solve_level.mjs   finds a winning launch for a level file; --write stores reference and par
tests/                  pytest (API, catalog, puzzles) and tests/js (node --test)
```

**Adding things is one file:**

- **A mode:** a folder `static/modes/<id>/` with `mode.json` and a module
  default-exporting `{ mount(root, ctx) }`.
- **A moon, planet or dwarf planet:** a JSON file in `data/bodies/`.
- **A puzzle level:** a JSON file in `~/ForgeGameData/cosmos/levels/`. Run
  `node tools/solve_level.mjs FILE --write` to give it a reference solution and
  a par; `puzzle.js` `checkLevel()` lists every field it understands.
- **A puzzle sound:** a `cosmos-<name>.json` recipe in `~/ForgeGameData/sounds/`
  whose `event` is launch, burn, waypoint, crash or win.
- **A sandbox preset:** a JSON file in `~/ForgeGameData/cosmos/scenarios/`.
  Its `generators` scatter particles, so a galaxy is a few lines, not
  thousands.

**Scale.** Positions are computed in doubles, in AU, on the CPU. Every frame,
the camera target is subtracted and the result is scaled so the camera always
sits 10 scene units from what it looks at. Star and galaxy clouds keep
parsec coordinates and get the same subtract-and-scale as an object
transform. See the header of `static/modes/map/view.js`.

## Data and where it lives

| What | Where | Size |
|---|---|---|
| Packed stars and names | `COSMOS_STARS_DIR` (Forge's data folder in a release), else `~/.cache/forge/cosmos/`: `stars-v1.bin` and `star-names.json` | 3.1 MB |
| HYG v4.4 source CSV | downloaded on demand by Get the stars, removed after the build | 13.6 MB |
| Sandbox presets and saves | `~/ForgeGameData/cosmos/scenarios/` | small |
| Puzzle levels | `~/ForgeGameData/cosmos/levels/` | about 60 KB |
| Puzzle stars and best results | `~/ForgeGameData/cosmos/puzzle-progress.json` | small |
| Puzzle sounds (recipes, no audio files) | `~/ForgeGameData/sounds/cosmos-*.json` | 2 KB |

The map's Get the stars button (or `.venv/bin/python
tools/build_star_catalog.py`) downloads the CSV and builds the catalog. With
`COSMOS_DRIVE_ROOT` set it also keeps a copy on that drive and refuses to write
there when the drive is not mounted. Without a catalog the map works and simply
has no stars.

**Credits:**

- **Planet elements:** JPL (Standish).
- **Dwarf planet elements:** JPL Small-Body Database.
- **Moon elements:** JPL planetary satellite mean elements, with each moon's
  mean anomaly and its rate refitted to JPL Horizons positions on 2026-10-19
  (`node tools/fit_moons.mjs` prints the fit; `--write` stores it).
- **Moon reference positions for the tests:** JPL Horizons
  (`tests/js/horizons-moons-2026-10-19.json`).
- **Planet reference positions for the tests:** JPL Horizons.
- **Star data:** HYG Database v4.4 by David Nash (astronexus.com), CC BY-SA 4.0.

## Running and checking

```
cd ~/Forge/apps/cosmos
FORGE_SHARED_DIR=~/Forge/shared .venv/bin/python -m uvicorn web_app:app --host 127.0.0.1 --port 8446
.venv/bin/python -m pytest -q tests          # API and catalog
node --test tests/js/                         # ephemeris, gravity, galaxy frame
python3 ../pulseforge/tools/shot.py "http://127.0.0.1:8446/#map" out.png --wait "document.querySelector('.stars-note')?.textContent.includes(' stars')"
```
