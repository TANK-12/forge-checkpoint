# Exo Lab

date: 2026-10-08 · for: both (the owner and Claude)

Half real-world physics test bench, half game, for powered exoskeletons and
mechs. The **tester** fits an exo suit to a VRM character and tests it, the
shoulder joint first: range of motion, gimbal lock, misalignment with the real
shoulder, strap pressure, motor torque and speed, beam strength and sag,
battery use. The **editor** changes the relative specs of materials, joints
and parts (stiffness, strength, weight, power) and re-runs the test live. The
**game** (`game.html`) plays exo soldiers whose jump, sprint, strength,
armour and energy come from the same specs.

Not part of Eighty Six. The plan, with the reasoning behind every choice, is
`docs/2026-10-08-plan.md`; status and next steps are in `WIP.md`.

## Run it

- In Forge: the sidebar entry "Exo Lab" (section play, port 8466).
- Alone:

      cd ~/Forge/apps/exolab
      FORGE_SHARED_DIR=~/Forge/shared .venv/bin/python -m uvicorn \
          web_app:app --host 127.0.0.1 --port 8466

  then open `http://127.0.0.1:8466/`. Pages: `#home` (Real-world tester or
  Game), `#tester?model=exo_full&test=shoulder_rom` (add `&tab=parts` and the
  editor opens on that tab), `game.html?model=exo_full&profile=<name>`
  (the page's Game links fill in the model and the saved profile picked in
  the tester; unsaved edits are not in it, and the link's hover text says
  so).

The game plays with a PS5 DualSense over USB or Bluetooth (Gamepad API);
pairing and the laptop check: `~/Forge/docs/library/exolab/2026-10-08-ps5-controller.md`.
In the Forge window it needs Forge reopened once after 2026-10-08 evening: app
frames are now allowed the pad, and Forge's pad-as-mouse service stays quiet
while the game is in front and sees the pad (in a pop-out window too).

## Layout

| Path | What |
|---|---|
| `web_app.py` | FastAPI: the page, `/shared` (three.js, three-vrm, theme), `/characters` (VRMs), the API. Caches bench runs and derived stats. |
| `exolab/` | The physics core. Plain Python and numpy, no engine, no web: this is what ports to Unity or Unreal. |
| `exolab/registry.py` | Loads every `data/<kind>/*.json`; profiles (knobs and overrides); `effective()` = override, else baseline x knob. |
| `exolab/skeleton.py`, `human.py` | Reads the VRM's bones; the human shoulder (girdle rhythm, range of motion, body segments, strength). |
| `exolab/parts.py` | Materials, beam sections, actuators and the suit's parts list with masses. |
| `exolab/mechanisms/` | One module per shoulder mechanism kind (`girdle`, `gimbal`, `cable`), found by scanning. |
| `exolab/arm.py` | `build()` a rig (body + suit), `kinematics()` (where the mechanism sits for an arm pose), `loads()` (statics: joint torques, strap pressure, beam safety, hand sag). |
| `exolab/benches/` | One module per test kind (`shoulder_rom`, `motions`, `hold`, `lift`, `close_fit`), found by scanning; `play()` adds the dynamics (speeds, accelerations, rotor inertia). |
| `exolab/body.py` | The VRM skin (mesh, bone weights, linear blend skinning) and the suit shells from the GLB, plus `TriGrid` (a triangle grid) and `nearest()` (signed distance to a mesh) for `close_fit`. |
| `exolab/derive.py` | Game stats from the specs (`GET /api/derive/<model>`), each with a `how` line. |
| `exolab/report.py` | Saves a dated markdown report of a run to `~/Forge/docs/library/exolab/`. |
| `data/` | Every material, actuator, mechanism, model, test, motion, human and power item, one JSON file each. `knobs.json` says which fields each knob scales; `limits.json` the range a typed number may take. |
| `static/index.html`, `app.css`, `js/` | The page: `main.js` (boot, routing), `store.js` (state, API, helpers), `tester.js`, `editor.js`, `view3d.js` (three.js scene), `suit.js` (VRM + suit GLB), `charts.js` (ROM map, line charts, Ashby chart). |
| `static/assets/suits/` | The fitted suit shells (GLB + sidecar JSON), built in Blender; see `docs/2026-10-08-suits.md`. The sidecar's `skin` field says what the body wears under the suit: `undersuit: true` tints all skin dark (full suit); `cover` turns the skin in a height band round a bone into dark shorts and leaves the limbs bare (light suit). |
| `static/game.html`, `static/game/`, `data/game/` | The game half; see `docs/2026-10-08-game.md`. `data/game/base.json` holds the base numbers `derive.py` uses. `static/game/controls.json` is the gamepad registry (PS5 DualSense layouts, bindings, menu moves, rumble) that `static/game/pad.js` reads. |
| `tests/` | pytest suites and `check_ui.py` (headless Chrome). |

## Adding things (one file each)

- A gamepad binding or another pad's layout: one entry in
  `static/game/controls.json`; the pause menu's list and the HUD's button
  names follow it.

- A material, actuator, motion, test, model or mechanism variant: one JSON file
  in the matching `data/` folder. Nothing in code lists them. Fields a knob
  should scale go in `data/knobs.json`.
- A new test kind: one module in `exolab/benches/` with `KIND = "..."` and
  `run(rig, test, reg) -> dict` (verdict, cards, and frames or rows), plus a
  `data/tests/*.json` with that `kind`. If a run can refuse a test's
  settings, add `save_errors(test, reg, prof) -> list[str]` so a profile
  with them is refused on save instead.
- A new shoulder mechanism kind: one module in `exolab/mechanisms/` with
  `KIND` and `place(mech, ctx, prev)`, plus a `data/mechanisms/*.json`.

## Profiles (the owner's edits)

A profile never changes `data/`. It holds `knobs` (relative multipliers
0.05 to 20 per item, or per part as `parts["<model>/<part>"]`) and
`overrides` (absolute values on any single field by dotted path, for example
`mechanisms.girdle_tracking["joints.0.actuator"] = "harmonic_m"`). The
power knob is a bigger motor all round: power x k multiplies a drive's
rated power, mass, remote mass and rotor inertia by k and its torque,
torque limit and top speed by the square root of k (the exponents are in
`data/knobs.json`), so x4 is twice the torque at four times the weight and
power is not free. Drives with no motor (the `motorless` kinds, passive
bearings and springs) take no power knob, only the knobs `part_knobs`
lists for their kind: a free bearing its weight, a spring its strength
and weight (the strength acts only where an arm joint uses the spring; a
leg drive with no motor is weight only); on the battery, power is more
cells, so more energy and more mass together. A per-part knob must be one
that `part_knobs` lists for that kind of part, on a part the model really
has; the editor drops one its part no longer reads (J1 swapped for a free
bearing loses its power knob, on every suit that shares the mechanism)
and says so, so Save still works. Saved
profiles live in `~/ForgeGameData/exolab/profiles/` (`EXOLAB_DATA` moves the
folder); `baseline` is the untouched data and is read-only, and names that
read like it are refused too (any case, spaces and marks left out, I, 1 or
7 for l, 0 for o, 4 for a, 8 or 6 for b, 5 for s, 3 for e). A bad override
(unknown field, wrong type, an id that does not exist, a number outside its
range, a text that is not one of its choices) or knob (unknown kind, item,
part or knob) is refused on save (400) and dropped with a warning on a run
(the run itself still answers). Rules between fields are checked on save
too: a human range whose planes do not rise, a motion a test plays with
keys under 0.05 s apart or shorter than 0.1 s at that test's frame rate,
and each test's own limits (the close fit's 300 frames in all and its
warn distances under `reach_mm`) are refused (400); a run meets such a
profile with a 400, not a warning. `data/limits.json` holds the range each
typed number may take; a field it does not list stays at or above zero when
its baseline is, may take either sign when its baseline is negative, and
stays within 1000 times its size. Its `text` block says which text fields
may change: a field whose shipped value is the id of an item of a kind in
`refs` takes any id of that kind (a pick), unless `fixed` names it (an
actuator's `kind` builds it; nothing reads the girdle's `joint`, nor a
cuff's `liner`, which is comfort only and shown as a note); a field
in `choices` takes one of its values; a field in `free` takes any text up
to `max_chars` (200) characters, though only an item's own top-level
`name` is free (a part's name is a key in the physics); every other text
field is fixed. The editor holds a typed number at its
limit and says so.

## API

`GET /api/registry`, `GET /api/model/{id}?profile=`, `POST /api/model`,
`POST /api/pose`, `POST /api/run`, `GET /api/derive/{id}`, `POST /api/derive`,
`GET /api/profiles`, `GET|PUT /api/profiles/{name}`,
`POST /api/profiles/{name}/copy`, `POST /api/report`, `POST /api/reload`.
A `profile` in a body is a saved name or an inline profile object. An
unknown model, test, motion or profile gives 404. A planned model, a bad
profile name, a profile saved with a bad edit, a test setting that would run
too long, a motion shorter than 0.1 s or with keys under 0.05 s apart, a
human range whose planes do not rise, and numbers that still break the
physics give 400 with the reason
(a run drops bad edits with a warning instead, see Profiles). A pose with a
number out of bounds, NaN or infinity gives 422; a copy onto an existing name
gives 409. `tests/test_bad_input.py` holds every bad input the two critics
tried; none gives a 500.

## Tester playback and pose

While a test's frames are on screen: Space plays or pauses, the left and right
arrows step one frame (with Shift ten), Home and End go to the ends, and W or
the Worst frame button jumps to the worst frame (fail before warn, then the
most problems). Keys typed into a field or a list, or pressed on a focused
button, link or editor fold, stay theirs. Pose mode's sliders each have a
number field beside them: a typed number moves the arm, goes to the slider's
step (0.3 kg on the 0.5 kg slider is 0.5) and one past the slider's end is
held at the end. Changing the model closes pose mode. A `#tester?...` link
paints the tester on its first frame.

In the game, the pause menu's Restart puts the range back in place (no page
reload), and the best lap is kept in the browser per suit and profile
(`static/game/records.js`); a faster lap says it is a new best.

## Tests

    cd ~/Forge/apps/exolab
    .venv/bin/python -m pytest tests -q          # core, benches, API, bad input, close fit
    .venv/bin/python tests/check_ui.py           # the page in headless Chrome

pytest puts profiles and reports in a scratch folder; `tests/test_suit_js.py`
runs the page's `suit.js` in node (skipped without node), and
`tests/test_pad.py` runs the game's pad mapping (`pad.js` with `controls.json`)
on fake DualSense states and into the real sim, and `main.js`'s pad wiring in a
node vm with a fake page and clock (`tests/js/main_pad.mjs`), also in node. `check_ui.py` starts its
own backend on a free port with scratch profiles, drives home, tester, editor,
playback and pose mode, and saves screenshots to `/tmp/exolab-shots`.
`tests/test_sweep_js.py` runs `tests/js/game_sim.mjs` (Restart in place, best
laps) and `tests/js/charts_labels.mjs` (limit labels never overprint) in node.
With `--port N` the UI check uses a backend already running there and skips
the save checks.

## What the numbers are

Statics and simple dynamics on a rigid arm model with a sprung scapula
(girdle rhythm), textbook material and motor values, and cuff straps as
springs. Not modelled: soft tissue in detail, muscle forces, heat, wear,
control-loop stability and impacts. Plan section 4 lists every formula and
its source; the page and every report say the same.

Verdict lines (warn/fail): gimbal lock 0.15/0.05, misalignment 10/30 mm,
beam safety factor 2/1, hand sag 15/40 mm; they are `DEFAULT_RULES` in
`exolab/benches/__init__.py`. The range sweep's headline is the share of
reachable arm directions the suit follows (95/85 %); a failing card under it
pulls a pass down to warn, a warning card leaves it alone. The "Range
tested" card warns, and caps the headline at warn, when the sweep covers
under half the directions the unedited human reaches at the same steps (a
narrowed range makes a pass say little); it reads at most 100%, and a
range wider than the usual one says so. Strap pressure and comfort limits come from the
human data (`data/human/`).

Close fit (`close_fit`) plays the shoulder motions with the fitted shells on
the skinned VRM body and measures, every frame, each shell's gap to the skin
(warn under 3 mm, fail inside it) and each moving shell pair's gap (warn
under 3 mm, fail under 0.5 mm or crossing). Depths are searched 10 mm deep
(`reach_mm`, 5 to 20; a shell that goes on deeper reads "10 mm or more"),
and an overlap between shells only shows down to the thinner wall, so read
it as "touching". Two shells built nearer than 3 mm on bones that keep their
rest relation show as an "at rest" pair. A run measures at most 300 frames
(all motions together). Profile edits to the motions are used; edits to a
shell's gap or thickness are not (the test reads the fitted suit file, and a
"Shell edits" card says so). The skin is only the `_SKIN` materials:
shells fitted over clothes or hair sit further off than their fit gap. Where
the pose puts the body through itself (the forearm sinking into the hips
with the arm down), that is reported as body self-contact and suit contacts
there are not counted. Frames carry `clash` marks (part, what it
hit, level, mm, point) that the 3D view draws as dots, and a `fit` block with
every shell's and pair's gap. Only the right arm moves; the left matches by
symmetry. Baseline numbers:
`~/Forge/docs/library/exolab/2026-10-08-close-fit.md`.
