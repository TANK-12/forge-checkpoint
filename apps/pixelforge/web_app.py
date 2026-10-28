"""Pixel Forge — the shared sprite and animation editor.

Edits the Forge sprite library in ~/ForgeArtData: palette-indexed character
rows, plus the palettes that colour them. The library is deliberately not owned
by any one app. Emberfield is its first consumer, but a sprite drawn here is
available to anything in Forge that reads the same store, which is why this is
its own workspace rather than a tab inside the game.

Writes go through forge_art, which validates geometry before saving and
replaces files atomically -- a half-written pack would break every app that
reads it, not just this one.
"""

import math
import os
import sys

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT, "static")
SHARED_DIR = os.environ.get("FORGE_SHARED_DIR") or os.path.join(
    ROOT, "..", "..", "shared"
)
sys.path.insert(0, os.path.abspath(SHARED_DIR))

import forge_art  # noqa: E402
import forge_content  # noqa: E402
import forge_jan  # noqa: E402

import janart  # noqa: E402

import forge_revalidate  # noqa: E402  (lives in the shared folder)

app = FastAPI(title="Pixel Forge")
forge_revalidate.revalidate(app)
forge_art.ensure_root()
forge_content.ensure_root()

# One role: something to draw with. The 4B is the default because it answered
# the shape prompt sensibly in about 45 s where the 0.8B could not hold the
# format at all; the 9B is better again and roughly twice as slow, and is one
# choice away in the Jan settings panel.
ART_MODEL = "Qwen3_5-4B-IQ4_XS"
jan = forge_jan.mount(app, "pixelforge", roles=("art",))

# Worlds are Janhollow's own content type, not the shared registry above --
# see janart.py's note on why this dict is copied from
# apps/janhollow/janhollow/content.py rather than imported from it. Scoping a
# Store to game="janhollow" gets the same ~/ForgeGameData/janhollow/worlds/
# folder that app reads, with no import between the two apps.
WORLD_TYPES = {
    "worlds": {
        "label": "Worlds",
        "required": ("label", "kind"),
        "defaults": {
            "kind": "planet",
            "sprite": "",
            "distance": "near",
            "colour": "#8fb7d9",
            "description": "",
            "visible_from": [],
            "tags": [],
        },
    }
}
worlds_store = forge_content.Store(WORLD_TYPES, game="janhollow")
worlds_store.ensure_root()


class PackBody(BaseModel):
    pack: dict


class PaletteBody(BaseModel):
    palette: dict


class SoundBody(BaseModel):
    sound: dict


@app.get("/api/art/library")
def library():
    return forge_art.library()


@app.get("/api/art/packs/{pack_id}")
def get_pack(pack_id: str):
    try:
        return forge_art.load_pack(pack_id)
    except forge_art.ArtError as e:
        raise HTTPException(404, str(e))


# Longest id that still makes a sane file name (a 300-character one was an
# OSError and a bare 500), and the longest free text kept with an entry.
ID_CAP = 64
TEXT_CAP = 200
LONG_TEXT_CAP = 4000


def _short(value) -> str:
    """A value cut short enough to quote back in an error message."""
    text = str(value)
    return text if len(text) <= 40 else text[:40] + "..."


def _id_problems(what: str, value) -> list:
    if len(str(value)) > ID_CAP:
        return [f"the {what} id {_short(value)!r} is longer than {ID_CAP} characters"]
    return []


def _text_problems(entry: dict, caps: dict) -> list:
    problems = []
    for key, cap in caps.items():
        value = entry.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > cap):
            problems.append(f"{key} must be text of at most {cap} characters")
    return problems


def _tags_problems(owner: str, tags) -> list:
    """Every reader does `"tile" in tags`: a number there broke Ask Jan."""
    if tags is None:
        return []
    if not isinstance(tags, list) or not all(
        isinstance(t, str) and len(t) <= TEXT_CAP for t in tags
    ):
        return [f"{owner}: tags must be a list of short words"]
    return []


def _pack_problems(pack: dict) -> list:
    """forge_art.validate_pack assumes every sprite is an object; a null or a
    number in its place raised inside it and came back as a bare 500. Tags,
    frames and over-long names are checked here too: the shared validator
    lets them through, and they broke readers (Ask Jan) later."""
    problems = _id_problems("pack", pack.get("id", ""))
    problems += _text_problems(pack, {"label": TEXT_CAP})
    sprites = pack.get("sprites")
    if isinstance(sprites, dict):
        bad = [str(n) for n, v in sprites.items() if not isinstance(v, dict)]
        if bad:
            return [f"{_short(name)}: a sprite must be an object" for name in bad[:6]]
        for name, sprite in sprites.items():
            if len(name) > TEXT_CAP:
                problems.append(f"sprite name {_short(name)!r} is too long")
                continue
            problems += _tags_problems(name, sprite.get("tags"))
            frames = sprite.get("frames")
            if frames is not None and not (
                isinstance(frames, list) and all(isinstance(f, dict) for f in frames)
            ):
                problems.append(f"{name}: frames must be a list of objects")
    if problems:
        return problems
    try:
        return forge_art.validate_pack(pack)
    except (AttributeError, TypeError, KeyError, IndexError) as exc:
        return [f"the pack is not shaped like one ({exc})"]


@app.post("/api/art/packs")
def put_pack(body: PackBody):
    """Save a whole pack. Whole-pack writes rather than per-sprite patches keep
    the file consistent and make the editor's undo trivial: it just re-posts the
    previous version."""
    problems = _pack_problems(body.pack)
    if problems:
        raise HTTPException(422, "; ".join(problems[:6]))
    return {"saved": True, "path": forge_art.save_pack(body.pack)}


@app.post("/api/art/palettes")
def put_palette(body: PaletteBody):
    problems = _palette_problems(body.palette)
    if not problems:
        try:
            problems = forge_art.validate_palette(body.palette)
        except (AttributeError, TypeError) as exc:
            problems = [f"the palette is not shaped like one ({exc})"]
    if problems:
        raise HTTPException(422, "; ".join(problems[:6]))
    return {"saved": True, "path": forge_art.save_palette(body.palette)}


def _palette_problems(palette: dict) -> list:
    problems = _id_problems("palette", palette.get("id", ""))
    problems += _text_problems(palette, {"label": TEXT_CAP})
    roles = palette.get("roles")
    if roles is not None and not (
        isinstance(roles, dict)
        and all(isinstance(v, str) and len(v) <= TEXT_CAP for v in roles.values())
    ):
        problems.append("roles must map colour keys to short text")
    return problems


@app.post("/api/art/validate")
def validate(body: PackBody):
    return {"problems": _pack_problems(body.pack)}


@app.get("/api/art/root")
def art_root():
    return {
        "root": forge_art.art_root(),
        "packs": forge_art.list_packs(),
        "palettes": forge_art.list_palettes(),
    }


@app.get("/api/sounds")
def sounds():
    """The sound half of the workspace.

    Sounds live in the *content* store, not the art store, because a game reads
    them alongside its crops and recipes. Pixel Forge edits them anyway: a
    sprite and the noise it makes are the same job, and splitting them into two
    apps would mean two windows to tune one hoe stroke.
    """
    store = forge_content.store()
    return {
        "root": forge_content.content_root(),
        "sounds": store["types"].get("sounds", {}),
        "defaults": forge_content.TYPES["sounds"]["defaults"],
        "problems": [p for p in store["problems"] if p.startswith("sounds/")],
    }


def _sound_problems(entry: dict) -> list:
    """Type checks the shared validator leaves out. Every game plays these
    numbers through Web Audio, where a string or NaN for a pitch throws on
    every play, so a wrong type is refused here rather than saved. Ranges are
    the editor's business (ForgeSound.FIELDS); this only keeps the shape."""
    problems = []
    for key, default in forge_content.TYPES["sounds"]["defaults"].items():
        if key not in entry:
            continue
        value = entry[key]
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, (int, float)):
            ok = (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            )
        else:
            ok = isinstance(value, str) and len(value) <= TEXT_CAP
        if not ok:
            problems.append(f"{key} is {str(value)[:40]!r}, not a usable value")
    label = entry.get("label")
    if label is not None and (not isinstance(label, str) or len(label) > TEXT_CAP):
        problems.append(f"the name must be text of at most {TEXT_CAP} characters")
    return problems


@app.post("/api/sounds")
def put_sound(body: SoundBody):
    entry = body.sound
    if not entry.get("id"):
        raise HTTPException(422, "a sound needs an id")
    problems = _id_problems("sound", entry["id"])
    if problems:  # the shared validator quotes the whole id back
        raise HTTPException(422, problems[0])
    problems = _sound_problems(entry) + forge_content.validate("sounds", entry)
    if problems:
        raise HTTPException(422, "; ".join(problems[:6]))
    return {"saved": True, "path": forge_content.save("sounds", entry)}


# --- asking Jan for art ------------------------------------------------------


class AskBody(BaseModel):
    prompt: str
    w: int = 16
    h: int = 16
    temperature: float = 0.8
    seed: int | None = None


# The last thing Jan drew, kept in memory so switching modes or reloading the
# page does not throw away a drawing that took a minute to make.
_last_art: dict = {}


def _art_model():
    return jan.model_for("art", ART_MODEL)


def _ask(system: str, user: str, body: AskBody, max_tokens: int):
    model = _art_model()
    with jan.using(model):
        return forge_jan.chat(
            model,
            system,
            user,
            temperature=body.temperature,
            max_tokens=max_tokens,
            timeout=900.0,
            seed=body.seed,
            wait=120.0,
        )


@app.get("/api/jan/art/ready")
def art_ready():
    """What the art maker has to work with, so the panel can say why it cannot
    run instead of failing when the button is pressed."""
    return {
        "model": _art_model(),
        "available": forge_jan.models(),
        "loaded": forge_jan.loaded_models(),
        "running": forge_jan.router_url() is not None,
        "sizes": list(janart.SIZES),
        "tiles": janart.tile_choices(),
    }


@app.post("/api/jan/art/sprite")
def jan_sprite(body: AskBody):
    """Ask for a sprite. Returns rows, a palette and any problems found.

    Nothing is saved: the page previews it and the person decides. A model that
    draws four bad toolboxes should cost four presses of a button, not four
    entries in the library.
    """
    w = max(4, min(96, body.w))
    h = max(4, min(96, body.h))
    try:
        raw = _ask(janart.sprite_prompt(w, h), body.prompt, body, 900)
    except forge_jan.JanError as exc:
        raise HTTPException(503, str(exc))
    try:
        rows, palette, problems = janart.make_sprite(raw, w, h)
    except janart.ArtError as exc:
        raise HTTPException(422, f"{exc}")
    out = {
        "kind": "sprite",
        "rows": rows,
        "palette": palette,
        "problems": problems,
        "w": w,
        "h": h,
        "model": _art_model(),
        "prompt": body.prompt,
        "raw": raw[:1200],
    }
    _last_art.clear()
    _last_art.update(out)
    return out


@app.post("/api/jan/art/structure")
def jan_structure(body: AskBody):
    """Ask for a floor plan: the same shapes, but each key is a tile id."""
    w = max(4, min(64, body.w))
    h = max(4, min(64, body.h))
    tiles = janart.tile_choices()
    try:
        raw = _ask(janart.structure_prompt(w, h, tiles), body.prompt, body, 900)
    except forge_jan.JanError as exc:
        raise HTTPException(503, str(exc))
    try:
        rows, legend, problems = janart.make_structure(raw, w, h, allowed=set(tiles))
    except janart.ArtError as exc:
        raise HTTPException(422, f"{exc}")
    out = {
        "kind": "structure",
        "rows": rows,
        "legend": legend,
        "problems": problems,
        "w": w,
        "h": h,
        "model": _art_model(),
        "prompt": body.prompt,
        "raw": raw[:1200],
    }
    _last_art.clear()
    _last_art.update(out)
    return out


@app.post("/api/jan/art/ship")
def jan_ship(body: AskBody):
    """Ask for a top-down ship plan. Same pixel pipeline as a sprite -- only
    the prompt differs, so hull, engines, bridge, cargo and an airlock come
    back as parts instead of a toolbox."""
    w = max(4, min(96, body.w))
    h = max(4, min(96, body.h))
    try:
        # A ship wants more parts than a toolbox (6-18 vs 4-14), so it gets a
        # bigger token budget than jan_sprite's 900.
        raw = _ask(janart.ship_prompt(w, h), body.prompt, body, 1400)
    except forge_jan.JanError as exc:
        raise HTTPException(503, str(exc))
    try:
        rows, palette, problems = janart.make_ship(raw, w, h)
    except janart.ArtError as exc:
        raise HTTPException(422, f"{exc}")
    out = {
        "kind": "ship",
        "rows": rows,
        "palette": palette,
        "problems": problems,
        "w": w,
        "h": h,
        "model": _art_model(),
        "prompt": body.prompt,
        "raw": raw[:1200],
    }
    _last_art.clear()
    _last_art.update(out)
    return out


class AskWorldBody(AskBody):
    """Same request shape as AskBody -- w/h just go unused, since a world has
    no size -- so it can still be passed straight through `_ask`."""


@app.post("/api/jan/art/world")
def jan_world(body: AskWorldBody):
    """Ask for a destination -- not pixels. Returns a worlds entry and any
    problems found; a field that does not fit is reported, never guessed at,
    and the page decides whether to still show it."""
    try:
        raw = _ask(janart.world_prompt(), body.prompt, body, 500)
    except forge_jan.JanError as exc:
        raise HTTPException(503, str(exc))
    try:
        entry, problems = janart.make_world(raw)
    except janart.ArtError as exc:
        raise HTTPException(422, f"{exc}")
    out = {
        "kind": "world",
        "entry": entry,
        "problems": problems,
        "model": _art_model(),
        "prompt": body.prompt,
        "raw": raw[:1200],
    }
    _last_art.clear()
    _last_art.update(out)
    return out


@app.get("/api/jan/art/last")
def last_art():
    """The most recent drawing, so the preview survives a reload."""
    return _last_art or {}


class KeepSpriteBody(BaseModel):
    pack: str
    name: str
    rows: list
    palette: dict
    w: int
    h: int
    tags: list = []


@app.post("/api/jan/art/keep-sprite")
def keep_sprite(body: KeepSpriteBody):
    """Save a previewed sprite into a pack, merging its colours into that
    pack's palette. Written through forge_art, so a sprite that does not
    validate never reaches the library."""
    pack_id = forge_art.slug(body.pack)
    name = forge_art.slug(body.name)
    problems = (
        _id_problems("pack", pack_id)
        + _id_problems("sprite", name)
        + _text_problems({"pack": body.pack}, {"pack": TEXT_CAP})
        + _tags_problems(name, body.tags)
    )
    if problems:
        raise HTTPException(422, "; ".join(problems[:6]))
    try:
        pack = forge_art.load_pack(pack_id)
    except (forge_art.ArtError, OSError, ValueError):
        pack = {
            "id": pack_id,
            "label": body.pack,
            "tile": body.w,
            "default_palette": pack_id,
            "sprites": {},
        }
    palette_id = pack.get("default_palette") or pack_id
    try:
        palette = forge_art.load_palette(palette_id)
    except (forge_art.ArtError, OSError, ValueError):
        palette = {"id": palette_id, "label": body.pack, "colors": {}}
    colors = dict(palette.get("colors") or {})
    for key, value in body.palette.items():
        colors.setdefault(key, value)
    palette["colors"] = colors

    pack.setdefault("sprites", {})[name] = {
        "w": body.w,
        "h": body.h,
        "tags": list(body.tags) + ["jan"],
        "frames": [{"ms": 0, "rows": list(body.rows)}],
    }
    pack["default_palette"] = palette_id
    # Both checked before either is written: the palette used to be saved
    # first, so a sprite that then failed left its colours merged in anyway
    # (and a bad colour came back as a 500 rather than a reason).
    try:
        problems = forge_art.validate_palette(palette) + _pack_problems(pack)
    except (AttributeError, TypeError) as exc:
        problems = [f"the drawing is not shaped like one ({exc})"]
    if problems:
        raise HTTPException(422, "; ".join(problems[:6]))
    try:
        forge_art.save_palette(palette)
        path = forge_art.save_pack(pack)
    except forge_art.ArtError as exc:
        raise HTTPException(422, str(exc))
    return {"saved": True, "pack": pack_id, "name": name, "path": path}


class KeepStructureBody(BaseModel):
    id: str
    label: str
    rows: list
    legend: dict
    w: int
    h: int
    tags: list = []
    source: str = ""


def _structure_problems(body: KeepStructureBody) -> list:
    """The shared store only checks that a label and rows exist, so a plan of
    width -1 made of numbers went to disk for every game to trip over. Same
    limits as the draw route (4-64 a side, but 1 is allowed for a hand-made
    strip), every row exactly w characters, every key in the legend."""
    if not (1 <= body.w <= 64 and 1 <= body.h <= 64):
        return [f"a floor plan is 1-64 tiles a side, not {body.w}x{body.h}"]
    if len(body.rows) != body.h:
        return [f"{len(body.rows)} rows for a plan {body.h} high"]
    problems = []
    legend = body.legend
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in legend.items()):
        problems.append("the legend must map single characters to tile ids")
    for i, row in enumerate(body.rows):
        if not isinstance(row, str) or len(row) != body.w:
            problems.append(f"row {i} is not {body.w} characters")
            continue
        unknown = {ch for ch in row if ch != "." and ch not in legend}
        if unknown:
            problems.append(f"row {i} uses {''.join(sorted(unknown))} with no tile")
    if len(body.label) > TEXT_CAP:
        problems.append(f"the label is longer than {TEXT_CAP} characters")
    if len(body.source) > LONG_TEXT_CAP:
        problems.append(f"the source is longer than {LONG_TEXT_CAP} characters")
    problems += _id_problems("structure", forge_art.slug(body.id))
    problems += _tags_problems("the plan", body.tags)
    return problems


@app.post("/api/jan/art/keep-structure")
def keep_structure(body: KeepStructureBody):
    """Save a floor plan as shared content, where any game can read it."""
    problems = _structure_problems(body)
    if problems:
        raise HTTPException(422, "; ".join(problems[:6]))
    entry = {
        "id": forge_art.slug(body.id),
        "label": body.label,
        "rows": list(body.rows),
        "legend": dict(body.legend),
        "w": body.w,
        "h": body.h,
        "tags": list(body.tags) + ["jan"],
        "source": body.source,
    }
    try:
        path = forge_content.save("structures", entry)
    except forge_content.ContentError as exc:
        raise HTTPException(422, str(exc))
    return {"saved": True, "id": entry["id"], "path": path}


class KeepWorldBody(BaseModel):
    id: str
    label: str
    kind: str
    distance: str
    colour: str
    description: str
    tags: list = []


@app.post("/api/jan/art/keep-world")
def keep_world(body: KeepWorldBody):
    """Save a previewed destination into Janhollow's worlds/ folder.

    Re-validated here rather than trusted from the preview: the guard in
    janart only *reports* a bad field, it does not stop a person editing the
    box afterwards, so nothing reaches disk without passing the same checks
    again."""
    entry, problems = janart.normalise_world(body.dict(exclude={"id"}))
    problems += _id_problems("world", forge_art.slug(body.id))
    problems += _text_problems(entry, {"label": TEXT_CAP, "description": LONG_TEXT_CAP})
    if problems:
        raise HTTPException(422, "; ".join(problems[:6]))
    entry["id"] = forge_art.slug(body.id)
    entry["tags"] = list(entry["tags"]) + ["jan"]
    try:
        path = worlds_store.save("worlds", entry)
    except forge_content.ContentError as exc:
        raise HTTPException(422, str(exc))
    return {"saved": True, "id": entry["id"], "path": path}


@app.get("/api/structures")
def list_structures():
    store = forge_content.store()
    return {
        "structures": store["types"].get("structures", {}),
        "problems": store["problems"],
    }


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as handle:
        return handle.read()


if os.path.isdir(SHARED_DIR):
    app.mount("/shared", StaticFiles(directory=SHARED_DIR), name="shared")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
