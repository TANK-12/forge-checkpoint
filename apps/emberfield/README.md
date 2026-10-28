# Emberfield

A valley to farm and a wilds to raid — Stardew Valley crossed with Realm of the
Mad God — with an optional layer where local models direct the world.

The valley is generated once per save and kept, because it is meant to become
familiar. The wilds are regenerated every day/night cycle and never stored,
because they are meant not to be. That difference is the point of both.

**Read `MANIFEST.json` first**, then `manifests/roadmap.json` for where this is
going, then the newest `manifests/session-NN.json`. This is
built over many sessions, so each one leaves its own record in
`manifests/session-NN.json` — what it intended, what it verified, what it got
wrong — and `MANIFEST.json` stays as the short entry point holding the current
state and what to do next. Each session record carries a `decision_record`
section with every question put to the user, the options offered, and their
answer quoted exactly, so you can see what was rejected and why the
architecture looks the way it does. This file is only how to run and extend it.

Port 8434. Discovered by Forge from `forge_app.json`; `forge.py` is untouched.
The one hub change is generic rather than app-specific: `hub/index.html` now
hides its sidebar when *any* workspace posts `{forge:"chrome",hidden:true}`, and
its iframes carry `allowfullscreen`. Emberfield uses it for the `f` key.

## The three modes

The base game is complete on its own — text and sound effects, fully
deterministic. Voice and the model layer stack on top and are independently
switchable in Settings. Neither is ever required.

| mode | what it adds |
|---|---|
| base | the whole game, no models, no voice |
| voice | pre-generated narrator and main-NPC lines, played from cache |
| llm | a director model shaping events, quests, the wilds and the economy |

Voice is **always pre-generated and cached, never synthesised while you play.**

## Why the compute budget exists

This machine has ten physical cores (two performance, eight efficiency), an
Iris Xe iGPU, 31 GiB shared between them, and **no swap**. Text generation runs
on the iGPU through Vulkan; Piper, Kokoro and faster-whisper run on the CPU
through onnxruntime. They share one memory bus, so generation starves speech of
bandwidth even when cores are free.

`emberfield/resources.py` therefore does two things: it pins background work to
six efficiency cores (leaving both performance cores for the game), and it runs
heavy jobs **one at a time** through `HeavyLane`. Pinning alone would not be
enough.

## Adding things

This is the rule that matters, and it follows the Forge convention:

* **A new crop, tool, foe, weapon or person** is one JSON file in
  `~/ForgeGameData`. No code. See below.
* **A new settlement** is one entry in `emberfield/layout.py` `DEFAULT_LAYOUT`
  plus a `kind` branch in `worldgen._lay_place`. Zones are fractions of the
  world, never tile coordinates.
* **A new terrain type** is one sprite in the art library plus one line in
  `worldgen.TILES`. Tile ids *are* sprite names — a test asserts every tile
  names a real sprite, so a rename in the editor cannot silently blank the map.
* **A new scatter object** is one sprite plus an entry in `worldgen.OBJECTS`
  and a weight in `SCATTER`.
* **A new sound** is one JSON file. There are no audio files in this project.
* **A new season or biome** is a palette file. No new art.
* **A new sprite** goes in a **new art pack**, never appended to an existing
  pack file — `tools/seed_art.py` skips packs that already exist on disk, so an
  append is silently lost until `--force`.

## The content store

Everything the game knows about a crop, a tool, a foe or a weapon lives in
`~/ForgeGameData` as ordinary JSON, one file per thing:

```
~/ForgeGameData/
  crops/emberfield-turnip.json
  items/emberfield-turnip-seed.json
  tools/emberfield-hoe.json
  foes/emberfield-slime.json
```

Nothing in the code lists what is in there. The game scans the directories at
boot, the same way Forge finds its apps and the art library finds its packs. So
**adding a crop is adding a file** — no code changes anywhere.

To add one, write two items (the seed and the produce) and a crop:

```json
{
  "id": "emberfield-pumpkin",
  "label": "Pumpkin",
  "sprite": "crop_pumpkin",
  "stages": [2, 3, 3, 4],
  "seasons": ["autumn"],
  "seed_item": "emberfield-pumpkin-seed",
  "yield_item": "emberfield-pumpkin",
  "yield_qty": 1,
  "regrow": 0
}
```

`stages` is days spent in each growth stage, so four numbers means the crop
needs four sprites named `crop_pumpkin_0` through `crop_pumpkin_3`. Draw them in
Pixel Forge. `regrow` above zero means it bears again instead of dying when
harvested. A test checks every crop's sprites and items actually exist, so a
typo shows up as a failing test rather than an invisible plant.

A tool is even smaller — the `verb` is the behaviour it dispatches to, so a
second tool reusing `till` or `water` needs no code at all:

```json
{ "id": "emberfield-hoe", "label": "Hoe", "verb": "till", "sprite": "tool_hoe" }
```

A **new kind of content** is one entry in `TYPES` in
`shared/forge_content.py`. `recipes` was filled in in session 6 (see
**Crafting** below); `quests` and `skills` are declared and still empty,
waiting for the sessions that build them.

`tools/seed_content.py` writes the starting content. Like the art seeder it
will not overwrite your edits without `--force`, and `--list` prints what the
store currently holds. If you break a file while editing it, the game says so
on the title screen and carries on without it rather than refusing to boot.

## Sound

There is not a single audio file in Emberfield. Every effect is *synthesised* at
runtime from a recipe in `~/ForgeGameData/sounds` — a dozen numbers describing a
small Web Audio graph:

```json
{
  "id": "emberfield-till", "label": "Hoe stroke", "event": "till",
  "wave": "noise", "duration": 0.22, "gain": 0.34,
  "filter": 1400, "filter_to": 240
}
```

`event` is what the game plays it on, so the wiring is data too: the code calls
`Sound.play("till")` and which file answers is decided in the content store. A
sound for a new event is one more file and no code at all.

The whole soundtrack is about four kilobytes. It is editable without an audio
editor — if the hoe sounds wrong, change `filter_to` and reload. The honest cost
is that this will never sound like recorded foley; it sounds like a synthesiser.
If that ever stops being the right trade, `static/audio.js` would grow a sample
path beside the synth path and a sound file would name a `.wav` instead of a
waveform.

`wave` is `sine`, `square`, `sawtooth`, `triangle` or `noise`. `freq_to` glides
the pitch, `filter_to` sweeps the low-pass, `detune` adds a second voice a few
cents away (one oscillator reads as a beep; two read as a sound), and `loop`
marks a bed used for ambience, whose level the game steers from the clock rather
than starting and stopping.

The synthesis itself is **not in this app**. It lives in `shared/forge_sound.js`
as `ForgeSound`, the companion to `forge_art.js`: one turns character rows into
pixels, the other turns a dozen numbers into a noise, and both are shared
because more than one app needs them. Emberfield plays these recipes; **Pixel
Forge edits them** (its Sounds tab), and what you hear in the editor is what the
game plays because it is the same code. `static/audio.js` is only the game's
half — which event maps to which recipe, the master volume, and the ambience
beds the clock steers.

`ForgeSound.FIELDS` describes every editable field with its range and a line of
help, so an editor builds its form by reading that list. A new field is one
entry there plus one in `forge_content.TYPES["sounds"]` — no editor change.

## The shop

The stall in the town square sells every item in the content store that carries
a **`buy` price above zero**, and buys back anything you are holding with a
`sell` price. There is no list of stocked items anywhere — putting something on
the shelf is setting a number on its item file:

```json
{ "id": "emberfield-turnip-seed", "label": "Turnip seeds", "kind": "seed",
  "sell": 12, "buy": 20 }
```

A test asserts that every crop's produce is worth more than its seed costs,
because a crop that quietly loses money would take a week of play to notice.

Chests at the deep end of each cavern draw from the `loot` content type —
weighted tables gated by day and by darkness, so making a reward rare is a
smaller `weight` rather than a branch in the code.

## The wilds

`emberfield/wilds.py` is the counterpart to `worldgen.py` and deliberately its
opposite. A cavern is seeded from the valley's seed **plus the day plus whether
it is night**:

```python
seed = valley_seed * 7919 + day * 131 + (1 if night else 0)
```

So it is different every cycle and identical when a save is reloaded — which
means nothing about a run down there needs storing, and nothing is. Day and
night are two different maps rather than one map with a difficulty multiplier:
the night cavern is carved tighter as well as populated more heavily.

Enter with `space` at the cave mouth, leave with `space` at the way you came in.
Entering parks the valley rather than discarding it, so your crops and worked
ground come back untouched. A save made underground always describes the valley.

**The dodge roll** (`q`) is the only movement option down there beyond walking.
It darts you a short way in whatever direction you are already holding — or the
way you face, if none — with the same half-second mercy window a hit gives you,
then locks out for most of a second. `ROLL` at the top of `play.js` holds all
four numbers. Mid-roll you cannot steer: committing is the cost of the
invulnerability. It is deliberately *not* a stamina bar — one cooldown you can
feel is easier to read mid-fight than a draining meter, and a bar would want a
UI, a regen rate and a food that refilled it. The roll resolves against walls
exactly like walking, so it cannot clip you through a fence; a self-test rolls
hard into all four directions and asserts you end somewhere you are allowed to
stand.

Two properties are tested and must stay true: the whole cavern is walkable
(water goes in *after* the chambers are carved and is solid, so connectivity is
settled last — an early version stranded 99% of the floor behind a pool), and
you never arrive inside a wall.

## The valley layout

`emberfield/worldgen.py` no longer hardcodes where the farm and the town go.
`emberfield/layout.py` holds `DEFAULT_LAYOUT` — a list of **places**, each with
a `kind`, a `zone` (fractions of the world, so the spec is
resolution-independent) and a `size` in tiles:

```python
{"name": "village", "kind": "village",
 "zone": (0.04, 0.06, 0.34, 0.34), "size": (19, 16)}
```

`worldgen.place_in_zone` scores candidate pads in the zone on flatness and
dryness and picks the best; `_mst_edges` wires a minimum-spanning-tree of roads
between the farm, the settlements, the farmsteads and the cave; `_drain` fills
any water or cliff that intrudes on a pad. Adding a settlement is **one entry
here plus a `kind` branch in `worldgen._lay_place`** — nothing else.

`place_in_zone` is deliberately the one seam an open-world or chunked generator
would replace. The renderer, the save format and the frontend all depend only
on the seed, the width, the height and the `regions` dict — never on a fixed
map size.

## Houses and interiors

Every house — yours, the townsfolk's, the villagers', the farmsteads' — is a
solid building with a **door tile** one row south of the sprite and a
**building id**. Press `space` on the door and `emberfield/interiors.py` swaps
in a small walled room, generated deterministically from the building id plus
the valley seed and **never stored**, exactly like a wilds cavern. Leaving puts
you back on the tile outside the door. A save made indoors describes the valley.

The player's house has the **bed** (`use: "sleep"` — this is where you sleep
now, session 2's bare bed moved inside) and a marked corner
(`regions["storage_spot"]`) for session 6's workbench and storage chest. Every
other house has a decorative bed, a table and a hearth.

`POST /api/interior {building, seed}` returns the room, mirroring `/api/wilds`.

## People

The valley's residents are a content type — `npcs` in
`shared/forge_content.TYPES`. One file per person:

```json
{
  "id": "emberfield-npc-maren", "label": "Maren", "sprite": "villager_a",
  "home": "emberfield-house-town-2",
  "schedule": [[7, "emberfield-house-town-2"], [10, "town_centre"],
               [14, "well"], [19, "emberfield-house-town-2"]],
  "lines": ["The town well's the old meeting spot. Habit outlives the reason."]
}
```

`home` is a building id the layout guarantees
(`emberfield-house-player`, `-town-1`..`-5`, `-village-1`..`-2`,
`-farmstead-north`, `-farmstead-east`). A `schedule` stop is a region name
(`town_centre`), a landmark (`stall`, `well`, `cave_mouth`), a building id, or
an explicit `[x, y]`; the game walks them there on a real BFS path. `shop: true`
makes talking to them open the stall. Adding a person is one file. The canned
`lines` become model-driven in session 8 without the field changing.

## Crafting

The player's house has a **workbench** (`use: "craft"`), a cooking **hearth**
(`use: "cook"`) and a storage **chest** (`use: "storage"`). Recipes are a
content type:

```json
{
  "id": "emberfield-glue", "label": "Boil slime into glue",
  "station": "workbench",
  "inputs": { "emberfield-slime-gel": 3 },
  "output": "emberfield-glue", "output_qty": 1
}
```

`station` is `"workbench"` or `"cook"`, and a recipe shows only at the matching
fixture. A test asserts every recipe names real items, and that workbench goods
sell for more than the sum of their inputs (cooked food is exempt — its value
is healing, not gold).

**Eating** (`e`, added 2026-10-19) spends that healing. It picks the smallest
meal you carry that fills the gap in your hearts (or the biggest one when none
can), so a turnip goes before a stew when you are one heart down. How much a
food heals is the optional `heals` field on its item in `~/ForgeGameData/items`;
a food without one heals one heart per 30 gold of sell price, at least one. The
seeder (`tools/seed_content.py`) writes `heals` for its three foods (turnip 1,
field ration 2, hearty stew 3) and an `eat` sound; existing stores keep working
without either, because the fallback gives the same numbers and the sound falls
back to the harvest one. The HUD shows how much food you carry.

The **chest** is the first interior state a save carries: the room regenerates
from its building id, but `S.storage` is written to the save like your pack and
your gold. Tools and the bow are filtered out of the deposit list so they can't
be lost in there.

**Tool upgrades** are recipes too. A recipe with an `upgrades` field (a tool id)
and a `tier` raises that tool's tier in `S.toolTier` — saved with everything
else — instead of yielding an item, and the `till` / `water` verbs read the
tier to work a `(2·tier+1)` square: tier 1 is a 3×3. The recipe only shows while
the tool is at `tier − 1`, so you climb the ladder a rung at a time. Represent
an upgrade this way, never as a new tool file — `startingKit` hands out every
tool, so a new one would be free.

> **Skills** (the last piece of session 6) are **not built yet** — recipes
> carry an unread `skill` / `skill_level` gate ready for them.

## Art

Sprites live in the shared library at `~/ForgeArtData`, edited in **Pixel
Forge**. Emberfield only reads them. `tools/seed_art.py` writes the starting
set; it is a seeder, not a pipeline, and will not overwrite your edits without
`--force`.

Terrain that wants *texture* rather than shape (grass, soil, sand) is generated
from a fixed seed; things with a silhouette (trees, rocks, the player, fences)
are hand-authored. Both end up as the same editable character rows.

## Running it

```bash
# inside Forge: just launch Forge, it appears in the sidebar
# standalone:
FORGE_SHARED_DIR=../../shared ./.venv/bin/python -m uvicorn web_app:app --port 8434 --reload

./.venv/bin/python -m pytest tests/ -q      # 123 tests
FORGE_SHARED_DIR=../../shared ./.venv/bin/python tools/seed_art.py       # default art
FORGE_SHARED_DIR=../../shared ./.venv/bin/python tools/seed_content.py   # default content
```

Farming, growth, combat and saving all live in the browser, so pytest cannot
reach them. They have their own checks, which run in a real page against the
real content store:

```
http://127.0.0.1:8434/?seed=777&selftest=1
```

It reports pass/fail on the page, **and posts the same result to
`/api/selftest`**. Read it from there when running headless: the checks that
render audio need real time to finish, and a browser driven with
`--virtual-time-budget` exits before they do.

Run it after touching anything under `static/` — the game code is
`static/index.html` (state and boot only) plus `world.js`, `render.js`,
`play.js`, `ui.js`, `audio.js`. The self-test (49 checks) is what makes a
refactor safe.

> Use `--reload`. Three separate bugs in one session were a running server still
> holding the previous version of a Python module.

A particular valley, which is also how the renderer gets checked without a
human at the keyboard:

```
http://127.0.0.1:8434/?seed=777&hour=10&zoom=3
```

`?hour=` sets the light, `?season=` the palette, `?zoom=` the scale, and
`?daysec=` the length of a day in real seconds — drop it to 60 while testing
anything that depends on days passing. `?screen=settings`, `?screen=shop`, `?screen=craft` and `?screen=storage`
open those directly. `?demo=` teleports you somewhere worth looking at:
`farm` (a plot at mixed growth), `tree` (behind an oak), `night` (outside after
dark with foes), `wilds` / `wilds-night` (straight into a cavern), `town` /
`village` / `farmstead` (standing in a settlement), `house` / `npc-house`
(inside an interior).

## Things worth knowing before you change the renderer

* The ground — tiles plus the procedural grass layer — is baked into **one
  offscreen canvas per palette** at world load. The frame loop is a single
  `drawImage`. Do not move per-tile drawing back into the loop.
* Blit at **integer pixels**. Non-integer destinations make pixel art shimmer
  as the camera moves.
* Day and night use two mechanisms deliberately: the palette swap for the big
  change, a colour wash for the gradual part.
* Collision is tested against the player's **feet**, not their centre.
* Interaction dispatches on an object's **`use`** field (`sleep`, `shop`,
  `chest`), not on its sprite name. A second stall needs no code.
* Shadows fall **away from their light source** — the sun outdoors, the player's
  torch underground — and there is a test on the sun vector, because getting the
  sign backwards looks perfectly fine in one screenshot and is wrong all day.
* An object's **collision shape is not its footprint**. The footprint says how
  much room the sprite needs; the `hit` box says what part of it your boots can
  walk into, and it is read as an ellipse so you slide around a trunk rather
  than catching on a corner. An oak is two tiles wide and three tall but only
  its trunk stops you. Treating the footprint as solid was a real bug: you
  collided with leaves two tiles above the ground and could never walk behind a
  tree.
* A day is **one number**, `day_seconds` in settings. It was accidentally two
  numbers multiplied together once, and a full day passed in twelve real
  seconds.
* Underground uses the night palette whatever the hour, and a flat cold wash
  instead of the time-of-day tint. There is no sun down there, so there is no
  sunset either.
* `cliff_face` is drawn as a cliff *face*, with horizontal strata. It is right
  at the edge of the valley and reads as banded wallpaper when a whole cavern is
  made of it — hence the separate `cave_wall_*` tiles.
* The page declares `color-scheme: dark` and styles `option` explicitly. Without
  both, dropdown popups render with the system's light palette while inheriting
  this theme's light text — white on white.
