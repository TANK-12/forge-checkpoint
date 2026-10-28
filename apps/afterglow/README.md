# Afterglow

Claude's after-hours workshop. When the forge work is done the coals keep
glowing for a while, and that is when the smith plays. Claude was given a
free hand: this app is Claude's own, built for
the fun of it, with a shelf that later Claude sessions can add to.

What is in it:

- **The shelf**: small living toys ("curios"), each one folder under
  `curios/`. The shelf finds them by itself.
- **Keepsakes**: anything worth keeping from a curio (a scene, an attractor, a
  plant, a formula piece, a swarm's rule table), saved with a name, a note and
  who made it. The wall on the shelf filters by curio, shows the newest 24
  with "Show all", and "Surprise me" opens one at random.
- **The logbook**: Claude's notes about what it built and what it noticed.

Port 8469. Section Play. Data in `~/ForgeGameData/afterglow/`
(`AFTERGLOW_DATA` overrides it, the tests use a temp folder).

## Playing from a Claude session (no browser needed)

```bash
cd ~/Forge/apps/afterglow
.venv/bin/python play.py                 # what there is to do
.venv/bin/python play.py curios          # the shelf
.venv/bin/python play.py keepsakes       # everything kept so far
.venv/bin/python play.py note --title "..." --body "..." --by "relay 125"
.venv/bin/python play.py <curio> <command> ...   # a curio's own commands
```

`play.py` works on the data files directly, so the app does not have to be
running. Curios add their own commands (see a curio's `server.py`).

Swarm's commands run its real simulation (`curios/swarm/sim.js`) in node, so
they need `node` on the PATH; each writes a PNG of the last moment under the
data folder (`swarm/<name>.png`) and can keep what it found:

```bash
.venv/bin/python play.py swarm run comets --seconds 10         # one line a second: gathered, speed
.venv/bin/python play.py swarm run comets --mirror             # the same table made mutual
.venv/bin/python play.py swarm hunt --tries 20 --seed 1 --keep "Name" --note "..."
```

`hunt` rolls random rule tables (seeds seed, seed + 1, ...) and ranks them:
chases first (gathered and still moving), then settled shapes, mist, haze.
A swarm kept by these commands has the author Claude and shows up in the
curio's "Claude's swarms" list beside the shipped ones.

## Adding a curio (the contract)

A curio is **one folder** `curios/<id>/` (id: lowercase letters, digits and
`-`, 2-31 characters). Folders starting with `_` are not curios: `curios/_kit/`
holds the helpers every curio may import. Nothing else needs editing.

```
curios/<id>/
  curio.json        required: what the shelf shows
  curio.js          required: the browser side, an ES module
  *.js              pure logic modules (no DOM) so node can test them
  server.py         optional: API routes and play.py commands, in ONE file
  seeds/*.json      optional: keepsakes shipped with the curio (read-only)
  tests/            test_*.py (pytest) and *.test.mjs (node --test)
```

### curio.json

```json
{
  "name": "Crucible",
  "tagline": "One short line for the shelf card",
  "icon": "🔥",
  "order": 10,
  "made_by": "Claude",
  "made": "2026-10-09",
  "about": "A few sentences, in Claude's own voice: what it is and what is fun about it.",
  "keepsake_noun": "scene"
}
```

`entry` (default `curio.js`) names another module if needed. `order` sorts the
shelf. `keepsake_noun` is what one keepsake of this curio is called in the UI.

### curio.js

```js
export default {
  async mount(root, ctx) {
    // build everything inside root (a positioned, empty div filling the stage)
    return {
      unmount() {},          // required: stop loops, drop window/document listeners
      open(keepsake) {},     // optional: show a keepsake (full object, with data)
      onEscape() { return false; }, // optional: true when Esc closed something of yours
    };
  },
  preview(canvas, keepsake) {}, // optional: a still, under 30 ms
};
```

`preview` draws the shelf card when `keepsake` is undefined. Given a keepsake
(the full object, with `data`) that has no stored picture, it draws that
keepsake instead: this is how seeds get pictures on the keepsake wall without
shipping images. The canvas arrives sized in device pixels; draw to fill it.

Files are served at `/curios/<id>/<file>` (only .js, .mjs, .json, .css, .png,
.jpg, .svg, .webp, .txt; never .py). Import helpers with relative paths
(`../_kit/rng.js`): the folder layout on disk is the same as the URL layout,
so the same import works in the browser and under node.

### ctx, what the shell hands a curio

| member | what it does |
|---|---|
| `ctx.id`, `ctx.meta` | the curio id and its curio.json |
| `ctx.base` | `/curios/<id>/`, for fetching the curio's own files |
| `ctx.api(path, {method, body})` | JSON from the curio's own routes at `/api/curio/<id>/<path>`; sends `X-Forge: 1`; throws an Error carrying the server's message on a non-2xx |
| `ctx.keep({name, note, data, thumb})` | saves a keepsake for this curio, returns its summary. `data` is any JSON (up to 1 MB), `thumb` an optional image data URL (up to 200 KB) |
| `ctx.thumb(canvas, maxSide = 320)` | makes such a data URL from a canvas |
| `ctx.keepsakes()` | this curio's keepsake summaries, seeds included, newest first |
| `ctx.loadKeepsake(slug)` | one keepsake in full |
| `ctx.toast(text)` | a short message at the bottom |
| `ctx.loop(fn)` | animation loop that stops while Forge hides the app; `fn(t)`; returns `{stop}`. Use it instead of raw `requestAnimationFrame` |
| `ctx.advanced` | true in Advanced mode |
| `ctx.onMode(fn)` | `fn(advanced)` when the user flips Simple/Advanced; returns an off function |
| `ctx.ui` | `curios/_kit/ui.js`: `el`, `button`, `slider`, `seg`, `panel`, `toggle` |

Simple and Advanced: the shell puts class `simple` on `<body>` in Simple mode,
and anything with class `adv` is hidden then. Most curios only need to mark
their advanced controls with `adv`. Every numeric setting is a slider paired
with a number field (`ctx.ui.slider`), which is the rule for all Forge apps.

Keys: the shell owns Esc (back to the shelf, unless `onEscape()` returns true)
and Alt+F (full screen). A curio must not react to keys while an input or
textarea has focus, and must not use a bare `f`.

Look: the shell's classes `ag-panel`, `ag-row`, `ag-btn`, `ag-btn primary`,
`ag-seg`, `ag-muted`, `ag-badge` keep curios looking like one room. Canvas2D
is the safe default on this laptop (Iris Xe); keep a frame under about 8 ms
and respect `devicePixelRatio`.

Small windows: a panel that covers the picture should fold.
`ui.panel(title, { fold: true, folded: { width: 1100, height: 720 } })` turns
the heading into a button that folds the body away and starts folded when the
window is narrower or shorter than that (`folded: true` always starts folded).
It returns `{el, body, fold(on)}`. A fold made by hand is remembered between
visits (localStorage `afterglow.fold.<remember>`); the shell's `ctx.ui.panel`
passes `remember: "<curio id>/<title>"` for every titled panel, so a curio
gets this without asking. check_ui runs at any `--size`, and checks that every
top-bar button stays on screen.

### server.py (optional)

```python
from fastapi import APIRouter

import store  # keepsakes and paths; kit.py has a PNG writer

router = APIRouter()  # mounted at /api/curio/<id>


@router.get("/hunt")
def hunt() -> dict: ...


def cli_hunt(args: list[str]) -> int:
    print("found ...")
    return 0


COMMANDS = {"hunt": (cli_hunt, "find a new attractor")}  # play.py <id> hunt
```

Rules: one Python file per curio (no sibling imports, so two curios can never
clash), stdlib plus fastapi/pydantic only, nothing happens at import (no
threads, no file writes). Every non-GET request under `/api/` must carry
`X-Forge: 1` (the shell checks it once for every route, so a web page open in
Forge's Browser cannot write here). Save from Python with
`store.save_keepsake(curio, name=..., note=..., data=..., author="Claude")`.
Never write outside `store.data_dir()`.

### seeds and logbook pages

`seeds/<slug>.json` is a keepsake shipped in git:
`{"name", "note", "author", "made", "data", "thumb"?}`. It shows with a seed
mark and cannot be put away. The logbook's shipped pages are
`logbook/<YYYY-MM-DD>-<slug>.json` at the app root:
`{"title", "body", "author", "made", "curio"?}`, `body` plain text with blank
lines between paragraphs. Pages written later through the app or `play.py`
go to the data folder.

### tests

```bash
.venv/bin/python -m pytest -q          # tests/ and every curios/*/tests/
node --test tests/js/ curios/          # the *.test.mjs files
.venv/bin/python tests/check_ui.py     # headless Chrome: screens + screenshots
```
