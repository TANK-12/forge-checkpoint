"""The Forge sprite library: palette-indexed pixel art, shared across apps.

A sprite is stored as rows of single characters, each character an index into a
named palette. That choice is deliberate and load-bearing:

  * it is hand-authorable in a text editor, so art can be written as data;
  * it is editable in a GUI without a binary asset pipeline;
  * it diffs cleanly and costs kilobytes rather than megabytes;
  * and because colour lives in a separate palette file, re-skinning a whole
    world -- a season, night, weather, a different biome -- is a palette swap
    rather than a second copy of every sprite.

The store lives outside any one app (~/ForgeArtData by default) because the
art is meant to be universal: Emberfield is its first consumer, not its owner.
Packs and palettes are *discovered* by scanning the directory, mirroring how
Forge discovers apps -- adding one is a new file, never a registry edit.
"""

import json
import os
import re
import shutil
import unicodedata

TRANSPARENT = "."

# Legal palette keys. TRANSPARENT is reserved and never appears here.
PALETTE_KEYS = "abcdefghijklmnopqrstuvwxyz" "ABCDEFGHIJKLMNOPQRSTUVWXYZ" "0123456789"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def art_root():
    """Where the library lives. FORGE_ART_DIR overrides, which is what makes
    the tests able to run against a throwaway directory."""
    return os.environ.get("FORGE_ART_DIR") or os.path.join(
        os.path.expanduser("~"), "ForgeArtData"
    )


def packs_dir():
    return os.path.join(art_root(), "packs")


def palettes_dir():
    return os.path.join(art_root(), "palettes")


def ensure_root():
    for path in (packs_dir(), palettes_dir()):
        os.makedirs(path, exist_ok=True)
    return art_root()


# Starting art that more than one app draws with (the crewroom palette and its
# character, prop and tile packs: the Crew Room and Janhollow both use them).
# It ships beside this module so an app works on a fresh install even when the
# app that first drew the art is not installed.
SEED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "art_seed")


def ensure_seeded(seed_dir=None):
    """Copy the seed folder's packs and palettes that are missing from the
    library (same layout: packs/, palettes/). A file that exists is never
    overwritten, because it may hold edits. Returns the relative paths copied."""
    seed_dir = seed_dir or SEED_DIR
    copied = []
    root = art_root()
    for folder, _dirs, files in os.walk(seed_dir):
        for name in files:
            if not name.endswith(".json"):
                continue
            source = os.path.join(folder, name)
            relative = os.path.relpath(source, seed_dir)
            target = os.path.join(root, relative)
            if os.path.exists(target):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            tmp = target + ".tmp"
            shutil.copyfile(source, tmp)
            os.replace(tmp, target)
            copied.append(relative.replace(os.sep, "/"))
    return sorted(copied)


# --- validation ------------------------------------------------------------


class ArtError(Exception):
    """A pack or palette that cannot be trusted to render."""


def slug(text):
    """Filesystem- and URL-safe id. Used when the editor creates something new,
    so a human can type a label and still get a sane filename."""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "untitled"


def validate_palette(palette):
    """Returns a list of human-readable problems; empty means good."""
    problems = []
    pid = palette.get("id", "")
    if not _ID_RE.match(str(pid)):
        problems.append(f"palette id {pid!r} must be lowercase letters/digits/-/_")
    colors = palette.get("colors")
    if not isinstance(colors, dict) or not colors:
        return problems + ["palette has no colors"]
    for key, value in colors.items():
        if key == TRANSPARENT:
            problems.append(f"'{TRANSPARENT}' is reserved for transparency")
        elif key not in PALETTE_KEYS:
            problems.append(f"colour key {key!r} is not a single legal character")
        if not _HEX_RE.match(str(value)):
            problems.append(f"colour {key!r} is {value!r}, not a #rrggbb hex string")
    return problems


def validate_sprite(name, sprite, colors):
    problems = []
    w, h = sprite.get("w"), sprite.get("h")
    if not isinstance(w, int) or not isinstance(h, int) or w < 1 or h < 1:
        return [f"{name}: w/h must be positive integers"]
    frames = sprite.get("frames")
    if not isinstance(frames, list) or not frames:
        return [f"{name}: needs at least one frame"]
    for index, frame in enumerate(frames):
        rows = frame.get("rows")
        if not isinstance(rows, list) or len(rows) != h:
            problems.append(
                f"{name} frame {index}: expected {h} rows, got {len(rows or [])}"
            )
            continue
        for y, row in enumerate(rows):
            if len(row) != w:
                problems.append(
                    f"{name} frame {index} row {y}: expected {w} chars, got {len(row)}"
                )
                continue
            for char in row:
                if char != TRANSPARENT and char not in colors:
                    problems.append(
                        f"{name} frame {index} row {y}: {char!r} is not in the palette"
                    )
                    break
    return problems


def validate_pack(pack, palette=None):
    problems = []
    if not _ID_RE.match(str(pack.get("id", ""))):
        problems.append(
            f"pack id {pack.get('id')!r} must be lowercase letters/digits/-/_"
        )
    sprites = pack.get("sprites")
    if not isinstance(sprites, dict) or not sprites:
        return problems + ["pack has no sprites"]
    # Without a palette we can still check geometry, which is the half that
    # actually breaks rendering; unknown colours only render as gaps.
    colors = (palette or {}).get("colors", {}) if palette else None
    for name, sprite in sprites.items():
        if colors is None:
            problems += validate_sprite(name, sprite, {c: 1 for c in PALETTE_KEYS})
        else:
            problems += validate_sprite(name, sprite, colors)
    return problems


# --- reading and writing ---------------------------------------------------


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path, data):
    """Write via a temporary file and replace, so a crash or a second Forge
    session cannot leave a half-written pack behind."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)
    return path


def _list_ids(directory):
    if not os.path.isdir(directory):
        return []
    return sorted(
        os.path.splitext(name)[0]
        for name in os.listdir(directory)
        if name.endswith(".json") and not name.endswith(".tmp")
    )


def list_packs():
    return _list_ids(packs_dir())


def list_palettes():
    return _list_ids(palettes_dir())


def pack_path(pack_id):
    return os.path.join(packs_dir(), f"{slug(pack_id)}.json")


def palette_path(palette_id):
    return os.path.join(palettes_dir(), f"{slug(palette_id)}.json")


def load_pack(pack_id):
    path = pack_path(pack_id)
    if not os.path.isfile(path):
        raise ArtError(f"no such pack: {pack_id}")
    return _read_json(path)


def load_palette(palette_id):
    path = palette_path(palette_id)
    if not os.path.isfile(path):
        raise ArtError(f"no such palette: {palette_id}")
    return _read_json(path)


def save_pack(pack, strict=True):
    problems = validate_pack(pack)
    if problems and strict:
        raise ArtError("; ".join(problems[:5]))
    return _write_json(pack_path(pack["id"]), pack)


def save_palette(palette, strict=True):
    problems = validate_palette(palette)
    if problems and strict:
        raise ArtError("; ".join(problems[:5]))
    return _write_json(palette_path(palette["id"]), palette)


def library():
    """Everything a consumer needs in one response: the whole library is a few
    hundred kilobytes of text, so a game loads it once at boot rather than
    fetching sprites one at a time."""
    ensure_root()
    packs, palettes = {}, {}
    for pack_id in list_packs():
        try:
            packs[pack_id] = load_pack(pack_id)
        except (ArtError, ValueError, OSError):
            continue  # a broken file should not take the whole library down
    for palette_id in list_palettes():
        try:
            palettes[palette_id] = load_palette(palette_id)
        except (ArtError, ValueError, OSError):
            continue
    return {"root": art_root(), "packs": packs, "palettes": palettes}
