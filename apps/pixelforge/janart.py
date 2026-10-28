"""Ask Jan for a sprite or a structure, and get pixels back.

**The model does not draw pixels.** That was measured, not assumed. Asked on
2026-09-16 for a 16x16 grid of palette characters, the 4B returned sixteen rows
of pure transparency -- an empty image -- and the 9B returned rows of 16, 17 and
18 characters with a scattering of diagonal noise in them. Neither was a
toolbox. Asked instead for a short list of shapes, both models produced
sensible, well-formed parts on the first try.

So the division of labour here is: **Jan composes, this file draws.** The model
returns a palette and a handful of rectangles, ellipses, lines and pixels; the
rasteriser below turns those into the palette-indexed character rows that the
whole Forge art library is made of. The same trick works at two scales:

* a **sprite** is shapes on a pixel canvas, saved into an art pack;
* a **structure** is shapes on a *tile* canvas -- a room, a hut, a cargo bay --
  where each colour key is the id of a tile sprite instead of a colour. Saved as
  content, so a game can stamp it into a map;
* a **ship** is a sprite by another name -- a top-down plan drawn with the same
  shape list and the same rasteriser, only the prompt changes (hull, engines,
  bridge, cargo, airlock instead of a toolbox).

A fourth kind, **world**, breaks that pattern on purpose: a destination is not
pixels at all, it is six short fields (label, kind, distance, colour,
description, tags) that match Janhollow's own `worlds` content type. The model
is asked for those fields directly and they are validated the same way a
picture is judged -- a field that does not fit is reported, not guessed at.

Everything a model sends is repaired where it can be and rejected where it
cannot: hex colours in the key field, missing sizes, coordinates off the canvas
and fenced code blocks are all things these models actually did.
"""

from __future__ import annotations

import json
import os
import re
import sys

SHARED_DIR = os.environ.get("FORGE_SHARED_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "shared"
)
sys.path.insert(0, os.path.abspath(SHARED_DIR))

import forge_art  # noqa: E402

TRANSPARENT = forge_art.TRANSPARENT
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_SHORT_HEX = re.compile(r"^#[0-9a-fA-F]{3}$")
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_OBJECT = re.compile(r"\{.*\}", re.S)

MAX_PARTS = 40
MIN_PARTS = 2
SIZES = (8, 12, 16, 24, 32, 48, 64)


class ArtError(Exception):
    """What came back cannot be turned into a picture."""


# --- the prompts ------------------------------------------------------------

SPRITE_SYSTEM = """You design pixel art by listing shapes, which a renderer draws for you.

Reply with JSON only, in this shape:
{"palette": {"a": "#rrggbb", "b": "#rrggbb"},
 "parts": [{"shape": "rect", "x": 2, "y": 3, "w": 6, "h": 4, "color": "a", "fill": true}]}

Rules:
- The canvas is {w} wide and {h} tall. x goes right from 0, y goes down from 0.
- "shape" is one of: rect, ellipse, line, pixel. A line uses x, y, x2, y2.
- "color" is a KEY from your palette, never a hex code.
- Parts are drawn in order, so put the background first and details last.
- Use between 4 and 14 parts, and between 2 and 6 colours.
- Leave the background transparent by not covering it: only draw the object.
- Shade it: a lighter colour on the top-left of a form and a darker one on the
  bottom-right is what makes pixel art read as solid."""

STRUCTURE_SYSTEM = """You design the floor plan of a building by listing shapes, which a renderer draws.

Reply with JSON only, in this shape:
{"legend": {"a": "<tile id>", "b": "<tile id>"},
 "parts": [{"shape": "rect", "x": 0, "y": 0, "w": 8, "h": 6, "color": "a", "fill": false}]}

Rules:
- The plan is {w} tiles wide and {h} tiles tall. Each part covers whole tiles.
- "shape" is one of: rect, ellipse, line, pixel. A line uses x, y, x2, y2.
- "color" is a KEY from your legend, and each legend value must be one of the
  tile ids listed below, spelled exactly.
- Draw in order: the floor first as a filled rect, then the walls as an
  unfilled rect around it, then a door, then the furniture as single pixels.
- Use between 4 and 12 parts.
- Available tile ids: {tiles}"""


def sprite_prompt(w: int, h: int) -> str:
    return SPRITE_SYSTEM.replace("{w}", str(w)).replace("{h}", str(h))


def structure_prompt(w: int, h: int, tiles) -> str:
    listed = ", ".join(sorted(tiles)[:60])
    return (
        STRUCTURE_SYSTEM.replace("{w}", str(w))
        .replace("{h}", str(h))
        .replace("{tiles}", listed)
    )


SHIP_SYSTEM = """You design a top-down ship plan by listing shapes, which a renderer draws for you.

Reply with JSON only, in this shape:
{"palette": {"a": "#rrggbb", "b": "#rrggbb"},
 "parts": [{"shape": "rect", "x": 2, "y": 3, "w": 6, "h": 4, "color": "a", "fill": true}]}

Rules:
- The canvas is {w} wide and {h} tall, seen from directly above. x goes right
  from 0, y goes down from 0; up is the bow, down is the stern.
- "shape" is one of: rect, ellipse, line, pixel. A line uses x, y, x2, y2.
- "color" is a KEY from your palette, never a hex code.
- Parts are drawn in order, so put the hull first and details last.
- Include at least: a hull outline, engines at the stern, a bridge or cockpit
  near the bow, a cargo bay, and an airlock or hatch set into the hull.
- Use between 6 and 18 parts, and between 3 and 7 colours.
- Leave the background transparent by not covering it: only draw the ship.
- Shade it: a lighter colour on the top-left of a form and a darker one on the
  bottom-right is what makes pixel art read as solid."""


def ship_prompt(w: int, h: int) -> str:
    return SHIP_SYSTEM.replace("{w}", str(w)).replace("{h}", str(h))


# A world is not drawn at all -- see the module docstring. The prompt asks for
# the same six fields Janhollow's worlds/ type expects, spelled out so the
# model does not have to guess a schema it has never seen.
WORLD_SYSTEM = """You describe one destination visible from a station viewport: a planet, moon, star, other station, ship or wreck.

Reply with JSON only, in this shape:
{"label": "Kessleron", "kind": "planet", "distance": "far",
 "colour": "#3a5f7a", "description": "a rust-banded gas giant with two thin rings",
 "tags": ["gas giant", "uninhabited"]}

Rules:
- "kind" is one of: planet, moon, star, station, ship, wreck, field.
- "distance" is one of: near, far, passing.
- "colour" is a single hex colour, #rrggbb, the dominant colour seen from a
  viewport -- not a palette, just one colour.
- "description" is one or two sentences, written for a screen, not a spec.
- "tags" is a short list of lowercase one- or two-word tags."""


def world_prompt() -> str:
    return WORLD_SYSTEM


def tile_choices(limit: int = 60):
    """Tile-ish sprites in the library, for the structure prompt to choose from.

    Taken from the library rather than a list here, so a tile drawn today is
    offered to the model tomorrow.
    """
    names = set()
    for pack in forge_art.library()["packs"].values():
        for name, sprite in pack.get("sprites", {}).items():
            tags = sprite.get("tags") if isinstance(sprite, dict) else None
            tags = tags if isinstance(tags, list) else []  # a hand-edited file
            if "tile" in tags or name.startswith(("floor", "wall")):
                names.add(name)
    return sorted(names)[:limit]


# --- reading what came back -------------------------------------------------


def _extract_json(raw: str):
    """The bare JSON value in a reply, repaired the same ways every kind here
    needs: fenced code blocks and trailing commas are things these models
    actually sent, for shapes and for world fields alike.
    """
    text = _FENCE.sub("", (raw or "").strip()).strip()
    match = _OBJECT.search(text)
    if not match:
        raise ArtError("no JSON object in the reply")
    blob = match.group(0)
    for candidate in (
        blob,
        blob.replace(",\n}", "\n}").replace(",}", "}").replace(",]", "]"),
    ):
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    raise ArtError("the reply was not a JSON object")


def parse(raw: str) -> dict:
    """The model's reply as {palette, parts}, repaired where it can be.

    Every repair here is something one of these models actually did.
    """
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise ArtError("the reply was not a JSON object")

    palette = data.get("palette")
    if not isinstance(palette, dict):
        # Asked for a structure it sends a legend, and models mix the two names
        # up in either direction, so both are accepted for both.
        legend = data.get("legend")
        palette = legend if isinstance(legend, dict) else {}
    palette = {str(k): v for k, v in palette.items()}

    parts = data.get("parts")
    if not isinstance(parts, list):
        raise ArtError("the reply had no parts list")
    return {"palette": palette, "parts": parts[:MAX_PARTS]}


def normalise_colours(spec: dict) -> dict:
    """Turn whatever it called a colour into palette keys.

    The 4B put hex codes straight into the `color` field instead of using its
    own palette keys, so a hex there gets a key allocated for it.
    """
    palette = {}
    for key, value in spec["palette"].items():
        value = str(value).strip()
        if _SHORT_HEX.match(value):
            value = "#" + "".join(ch * 2 for ch in value[1:])
        if _HEX.match(value):
            palette[key[:1] or "a"] = value.lower()
    by_hex = {v: k for k, v in palette.items()}

    free = [k for k in forge_art.PALETTE_KEYS if k not in palette]

    for part in spec["parts"]:
        if not isinstance(part, dict):
            continue
        colour = str(part.get("color", "")).strip()
        if _SHORT_HEX.match(colour):
            colour = "#" + "".join(ch * 2 for ch in colour[1:])
        if _HEX.match(colour.lower()):
            colour = colour.lower()
            if colour in by_hex:
                part["color"] = by_hex[colour]
            elif free:
                key = free.pop(0)
                palette[key] = colour
                by_hex[colour] = key
                part["color"] = key
        else:
            part["color"] = colour[:1]
    spec["palette"] = palette
    return spec


# --- drawing ----------------------------------------------------------------


def _blank(w, h):
    return [[TRANSPARENT] * w for _ in range(h)]


def _put(grid, x, y, key):
    if 0 <= y < len(grid) and 0 <= x < len(grid[0]):
        grid[y][x] = key


def _rect(grid, x, y, w, h, key, fill):
    for ty in range(y, y + h):
        for tx in range(x, x + w):
            if fill or ty in (y, y + h - 1) or tx in (x, x + w - 1):
                _put(grid, tx, ty, key)


def _ellipse(grid, x, y, w, h, key, fill):
    rx, ry = max(w / 2, 0.5), max(h / 2, 0.5)
    cx, cy = x + rx - 0.5, y + ry - 0.5
    for ty in range(y, y + h):
        for tx in range(x, x + w):
            dx = (tx - cx) / rx
            dy = (ty - cy) / ry
            d = dx * dx + dy * dy
            if d <= 1.0 and (fill or d >= 0.42):
                _put(grid, tx, ty, key)


def _line(grid, x0, y0, x1, y1, key):
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    for _ in range(dx + dy + 2):
        _put(grid, x0, y0, key)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy


def rasterise(spec: dict, w: int, h: int) -> list[str]:
    """Shapes into rows of palette keys. Parts are drawn in order, back to front."""
    grid = _blank(w, h)
    drawn = 0
    for part in spec["parts"]:
        if not isinstance(part, dict):
            continue
        key = str(part.get("color", ""))[:1]
        if not key or key == TRANSPARENT or key not in spec["palette"]:
            continue
        shape = str(part.get("shape", "rect")).lower()
        x = _whole(part.get("x"), 0)
        y = _whole(part.get("y"), 0)
        fill = part.get("fill", True) is not False
        if shape == "pixel":
            _put(grid, x, y, key)
        elif shape == "line":
            _line(grid, x, y, _whole(part.get("x2"), x), _whole(part.get("y2"), y), key)
        else:
            pw = max(1, _whole(part.get("w"), 1))
            ph = max(1, _whole(part.get("h"), 1))
            if shape == "ellipse":
                _ellipse(grid, x, y, pw, ph, key, fill)
            else:
                _rect(grid, x, y, pw, ph, key, fill)
        drawn += 1
    if drawn < MIN_PARTS:
        raise ArtError(f"only {drawn} parts could be drawn")
    return ["".join(row) for row in grid]


def _whole(value, fallback):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return fallback


# --- judging it -------------------------------------------------------------


def judge(rows, palette, dense=False) -> list[str]:
    """Problems with the finished picture. Empty means it is worth showing.

    `dense` is for floor plans, where covering every tile is the correct answer
    rather than a runaway rectangle -- a room is a floor with walls round it.
    """
    problems = []
    filled = sum(1 for row in rows for ch in row if ch != TRANSPARENT)
    total = sum(len(row) for row in rows) or 1
    used = {ch for row in rows for ch in row if ch != TRANSPARENT}
    if not filled:
        problems.append("nothing was drawn")
    elif filled / total < 0.04:
        problems.append("almost nothing was drawn")
    elif filled / total > 0.97 and not dense:
        problems.append("one shape covered the whole canvas")
    if len(used) < 2:
        problems.append("it is a single flat colour")
    missing = used - set(palette)
    if missing:
        problems.append(f"used colours that are not in the palette: {sorted(missing)}")
    return problems


def make_sprite(raw: str, w: int, h: int):
    """(rows, palette, problems) from one model reply."""
    spec = normalise_colours(parse(raw))
    rows = rasterise(spec, w, h)
    return rows, spec["palette"], judge(rows, spec["palette"])


def make_ship(raw: str, w: int, h: int):
    """(rows, palette, problems). A ship is drawn exactly like a sprite -- the
    only difference is the prompt, which asks for hull, engines, bridge,
    cargo and an airlock instead of a toolbox."""
    return make_sprite(raw, w, h)


def make_structure(raw: str, w: int, h: int, allowed=None):
    """(rows, legend, problems). The legend maps a key to a tile sprite id, and
    a tile the library does not have is dropped rather than drawn."""
    spec = parse(raw)
    legend = {}
    for key, value in spec["palette"].items():
        value = str(value).strip()
        if allowed is not None and value not in allowed:
            continue
        legend[key[:1]] = value
    spec["palette"] = legend
    if not legend:
        # Nothing it named is a real tile, so there is nothing to draw. Reported
        # rather than raised: the page should say why, and the raw reply is
        # still worth showing to whoever is tuning the prompt.
        blank = [TRANSPARENT * w for _ in range(h)]
        return blank, legend, ["none of its tiles exist in the library"]
    rows = rasterise(spec, w, h)
    return rows, legend, judge(rows, legend, dense=True)


# --- worlds -------------------------------------------------------------
#
# Not pixels: a world is the six fields Janhollow's worlds/ type wants. The
# schema lives in apps/janhollow/janhollow/content.py -- these sets and this
# regex are copied from it, not imported from it, because that file is being
# edited elsewhere while this one is written and a live import could shift
# under this app without warning.

WORLD_KINDS = {"planet", "moon", "star", "station", "ship", "wreck", "field"}
WORLD_DISTANCES = {"near", "far", "passing"}
_WORLD_COLOUR = re.compile(r"^#[0-9a-f]{6}$")


def normalise_world(data: dict) -> tuple[dict, list[str]]:
    """(entry, problems) for one parsed reply.

    Mirrors `judge`: a field that does not fit is reported, not invented, and
    is blanked out in the entry rather than left holding a bad value -- so a
    caller can tell "valid but empty" from "the model got this wrong" by
    reading the problems list, not by re-checking every field itself.
    """
    problems = []

    label = str(data.get("label", "")).strip()
    if not label:
        problems.append("no label")

    kind = str(data.get("kind", "")).strip().lower()
    if kind not in WORLD_KINDS:
        problems.append(f"kind {kind!r} must be one of {sorted(WORLD_KINDS)}")

    distance = str(data.get("distance", "")).strip().lower()
    if distance not in WORLD_DISTANCES:
        problems.append(
            f"distance {distance!r} must be one of {sorted(WORLD_DISTANCES)}"
        )

    # The 4B sent both 3- and 6-digit hex and mixed case for sprite colours,
    # so the same repair used there runs here before the strict check.
    colour = str(data.get("colour", "")).strip().lower()
    if _SHORT_HEX.match(colour):
        colour = "#" + "".join(ch * 2 for ch in colour[1:])
    if not _WORLD_COLOUR.match(colour):
        problems.append(f"colour {colour!r} must look like #rrggbb")
        colour = ""

    description = str(data.get("description", "")).strip()
    if not description:
        problems.append("no description")

    tags_in = data.get("tags")
    if isinstance(tags_in, list):
        tags = [str(t).strip() for t in tags_in if str(t).strip()][:8]
    elif tags_in:
        problems.append("tags must be a list")
        tags = []
    else:
        tags = []

    entry = {
        "label": label,
        "kind": kind if kind in WORLD_KINDS else "",
        "distance": distance if distance in WORLD_DISTANCES else "",
        "colour": colour,
        "description": description,
        "tags": tags,
    }
    return entry, problems


def make_world(raw: str) -> tuple[dict, list[str]]:
    """(entry, problems) from one model reply.

    Only an unparsable reply raises -- exactly as `parse` does for shapes.
    A field that does not fit is reported in `problems` instead, so the page
    can show what came back and let a person decide, the same as a bad
    drawing is shown rather than hidden.
    """
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise ArtError("the reply was not a JSON object")
    return normalise_world(data)
