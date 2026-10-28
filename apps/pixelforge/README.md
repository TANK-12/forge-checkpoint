# PixelForge

The shared **sprite and sound** editor for Forge. Port 8435.

It edits the sprite library in `~/ForgeArtData` and the sounds in
`~/ForgeGameData`, neither of which is **owned by any one app**. Emberfield is
their first consumer; anything else in Forge that reads the same stores sees
your edits immediately. That is why this is its own workspace rather than a tab
inside the game.

The header switches between the two halves. They share a window because they
are the same job: tuning a hoe stroke means looking at the dirt *and* hearing
the scrape, and splitting that across two apps would mean two windows for one
decision.

## Keys

Ctrl+Z / Ctrl+Shift+Z (or Ctrl+Y) undo and redo, Ctrl+S saves the open pack or
sound, [ and ] step frames, Space plays, = and - zoom, G toggles the grid,
E erases (transparent), M mirrors left and right, O shows the previous frame
faintly (onion skin). The list lives in `static/editor_state.js`
(`SHORTCUTS`); "unsaved changes" means the document differs from what is on
disk, so undoing back to it reads clean.

The drawing tools carry their own keys: B pencil, F fill, L line, R box,
I pick (takes the colour under the cursor, then goes back to the last tool).
They live in `static/tools.js` (`TOOLS`), which has no DOM and is tested by
`node --test tests/`; a new tool is one entry there, and the toolbar, tooltip
and key come from it. Each stroke, fill or shape is one undo step.

## The format

A sprite is rows of single characters, each an index into a named palette:

```json
{ "id": "grass_base", "w": 16, "h": 16,
  "frames": [ { "ms": 0, "rows": ["aabbabaa…", "…"] } ],
  "tags": ["terrain"] }
```

Colour lives in the palette, not the sprite. Recolouring an entire world — a
season, night, a different biome — is therefore one palette file rather than a
second copy of every sprite. It is also hand-authorable, diffs cleanly, and
costs kilobytes.

`.` is transparent and is the one reserved character.

## Layout

```
~/ForgeArtData/
  packs/*.json       sprites, grouped
  palettes/*.json    colours, plus a `roles` map giving semantic names
```

Both are **discovered by scanning**, mirroring how Forge discovers apps —
adding a pack is a new file, never a registry edit.

The `roles` map (`grass_mid`, `water_deep`, `skin`, …) is what lets a game draw
procedural detail in colours that belong to the current palette instead of
hardcoding hex values. Hover a swatch to see its role.

## Using it

Click a pack, then a sprite. Left-click paints with the selected colour,
right-click erases. Frames run along the bottom with a hold time each and a
live preview. **Save pack** writes the whole pack atomically after validating
geometry — a row of the wrong length is refused rather than saved, because a
broken pack would break every app reading the library, not just this one.

Editing a palette colour changes every sprite using that key. **Save palette**
is a separate button.

## Sounds

There are no audio files anywhere in Forge. A sound is a recipe — a dozen
numbers describing a small Web Audio graph — stored as the `sounds` content
type in `~/ForgeGameData`:

```json
{ "id": "emberfield-till", "label": "Hoe stroke", "event": "till",
  "wave": "noise", "duration": 0.22, "gain": 0.34,
  "filter": 1400, "filter_to": 240 }
```

The same trade as the sprites: it will never sound like recorded foley, but it
is four kilobytes instead of megabytes on a laptop short on disk, and a hoe
that sounds wrong is a number to nudge rather than a sample to re-record.

`event` is the game event the sound plays on, so the wiring is data too — a
game calls `Sound.play("till")` and which recipe answers is decided here.

**The editor knows nothing about what a sound contains.** The form is built by
reading `ForgeSound.FIELDS` in `shared/forge_sound.js`, which carries each
field's label, range and a line of help. A new field is one entry there plus
one in `forge_content.TYPES["sounds"]`; this app does not change.

The waveform is the sound **rendered offline and measured**, not a drawing of
the settings. That matters: a filter cutoff below the pitch, or an attack longer
than the sound, produces a perfectly valid graph that is perfectly silent and
throws nothing at all. A flat line and the word "silent" catch it before you
reach for the speakers. Peak and rms are shown, and a clipping peak turns the
trace red.

Playback and rendering both go through `shared/forge_sound.js` — the same
module the game plays with — so what you hear here is exactly what the game
will make.

## Safety

Writes go through `shared/forge_art.py` and `shared/forge_content.py`:
validated, then written to a temporary file and replaced. More than one Forge session can be open against this home
directory at once, and a half-written pack is worse than no pack.


## Ask Jan

The third mode in the header. Describe something, and a local model designs it
while this app draws it.

**The model does not draw pixels.** That was measured, not assumed: asked on
2026-09-16 for a 16×16 grid of palette characters, the 4B returned sixteen rows
of pure transparency and the 9B returned rows of 16, 17 and 18 characters with
scattered noise in them. Asked instead for a short list of shapes — rectangles,
ellipses, lines and single pixels, with a palette — both models produced
sensible, well-formed output first time. So the division of labour is: **Jan
composes, `janart.py` draws.**

Four kinds, three of them one prompt shape:

- **Sprite** — shapes on a pixel canvas, previewed and then saved into an art
  pack, merging its colours into that pack's palette.
- **Floor plan** — the same shapes at *tile* scale, where each key is the id of
  a tile sprite instead of a colour. The tile ids offered to the model are read
  out of the library, so a tile drawn today is offered tomorrow. Saved as a
  `structures` entry in `~/ForgeGameData`, where any game can read it.
- **Ship** — a top-down plan (hull, engines, bridge, cargo, airlock), drawn
  with the exact same shape list and rasteriser as a sprite at 48×48 or 64×64.
  Only the prompt differs. Saved into an art pack, same as a sprite — the panel
  defaults the pack to `ships`.

The fourth kind is not pixels at all:

- **World** — a destination seen from a viewport: a planet, moon, star,
  station, ship or wreck. The model is asked for six fields — label, kind,
  distance, colour, description, tags — matching the `worlds` type in
  Janhollow's `apps/janhollow/janhollow/content.py`. Every field is checked:
  `kind` must be one of the values that module allows, `distance` one of
  `near`/`far`/`passing`, `colour` a bare `#rrggbb`. A field that does not fit
  is reported and blanked rather than guessed at, and the whole entry is
  refused a second time on Save, not just trusted from the preview. Saved as a
  `worlds` entry in `~/ForgeGameData/janhollow/worlds`.

Everything that comes back is repaired where it can be and refused where it
cannot: hex codes in the colour field, fenced code blocks, a legend where a
palette was asked for, coordinates off the canvas and trailing commas are all
things these models actually did. A drawing that is empty, a single flat colour,
or one rectangle over the whole canvas is reported rather than shown — and
**nothing is saved until you press Save**, so a bad result costs a button press.

Expect 60–80 seconds a drawing on the 4B. Floor plans are the half that earns
its keep: a 12×9 crew cabin came back with a wall border, a wood floor, a rug, a
bed and a door in the wall. Sprites are a sketching aid — a red toolbox is
recognisable and crude. The model is chosen in the panel; the 9B draws better
and takes about twice as long.
