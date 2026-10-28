"""The Forge content store: game content as plain JSON files, shared across apps.

The companion to forge_art.py. That module holds what things *look* like; this
one holds what they *are* -- a crop's growth schedule, a tool's verb, a foe's
health. The split matters: a turnip's sprite is universal pixel art that any
game could use, while its price and its growing season belong to a game.

The rule this file exists to enforce is that **adding content is adding a file**.
Nothing here lists what content exists; the store is discovered by scanning the
directory, exactly as Forge discovers its apps and forge_art discovers its packs.
Adding a new crop is one JSON file. Adding a whole new *kind* of content is one
entry in TYPES. Neither is a code change anywhere else.

The store lives outside any one app (~/ForgeGameData by default) because the
long-term direction is a studio rather than a single game: a second game shares
this store, and a future content editor writes it without knowing what consumes
it. Files are namespaced by game -- emberfield-turnip.json -- for the same
reason the art packs are.

A broken file is skipped and reported, never raised. A half-edited crop must not
stop a game from booting.
"""

import copy
import json
import os
import re
import tempfile

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


# --- what kinds of content exist -------------------------------------------
#
# "required" fields must be present and non-empty. "defaults" are filled in when
# absent, so a minimal file stays minimal and every consumer still sees a
# complete record. Adding a type here is the only code a new kind of content
# needs; adding an instance of one needs no code at all.

TYPES = {
    "items": {
        "label": "Items",
        "required": ("label",),
        "defaults": {
            "sprite": "",
            "stack": 99,
            "sell": 0,
            # What the stall charges for it. Zero means it is not for sale --
            # which is how the shop's stock is decided, rather than by a list of
            # stocked ids somewhere. Adding something to the shop is setting a
            # number on the item.
            "buy": 0,
            "kind": "material",  # material | tool | seed | weapon | food
            # Food only: hearts restored by eating it. Zero means the game
            # works it out from the sell price (Emberfield does this).
            "heals": 0,
            "tags": [],
        },
    },
    "tools": {
        "label": "Tools",
        "required": ("label", "verb"),
        "defaults": {
            "sprite": "",
            # The verb is the handler the game dispatches to. Keeping it a
            # string here rather than a class name means a tool is data, and a
            # new tool that reuses an existing verb needs no code at all.
            "verb": "",
            "range": 1,
            "power": 1,
        },
    },
    "crops": {
        "label": "Crops",
        "required": ("label", "stages", "sprite"),
        "defaults": {
            # Days spent in each growth stage. len(stages) is the number of
            # sprites the crop needs: sprite + "_0" .. "_N".
            "stages": [1, 1, 1],
            "seasons": ["spring", "summer", "autumn"],
            "seed_item": "",
            "yield_item": "",
            "yield_qty": 1,
            "regrow": 0,  # days to go back to bearing; 0 means single harvest
            "sprite": "",
        },
    },
    "foes": {
        "label": "Foes",
        "required": ("label", "sprite", "hp"),
        "defaults": {
            "sprite": "",
            "hp": 3,
            "speed": 22,
            "damage": 1,
            "touch": 7,
            "night_only": True,
            "weight": 10,
            "drops": [],
        },
    },
    "weapons": {
        "label": "Weapons",
        "required": ("label",),
        "defaults": {
            "sprite": "",
            "damage": 1,
            "shot_speed": 130,
            "cooldown": 0.32,
            "shot_sprite": "arrow",
            "range": 150,
        },
    },
    "loot": {
        "label": "Loot tables",
        "required": ("label",),
        "defaults": {
            # What a chest can hold. Tables are drawn by weight, so a rare table
            # is a small number rather than a special case in the code.
            "items": [],
            "gold_min": 0,
            "gold_max": 0,
            "weight": 10,
            "night_only": False,
            "min_day": 1,
        },
    },
    "sounds": {
        "label": "Sounds",
        "required": ("label", "event"),
        "defaults": {
            # Sounds are *synthesised*, not sampled: these fields are the recipe
            # a Web Audio graph is built from. That is a deliberate trade. A
            # folder of .wav files would sound better, but it would also be
            # megabytes on a laptop that is short on disk, un-editable without
            # an audio editor, and impossible to tune by hand. A dozen numbers
            # in a JSON file can be nudged until a hoe stroke sounds right.
            "event": "",  # the game event this plays on
            "wave": "triangle",  # sine | square | sawtooth | triangle | noise
            "freq": 440.0,  # starting pitch, Hz (ignored by noise)
            "freq_to": 0.0,  # glide target; 0 means hold
            "duration": 0.18,
            "attack": 0.005,
            "gain": 0.3,
            "filter": 0.0,  # low-pass cutoff, Hz; 0 means none
            "filter_to": 0.0,
            "detune": 0.0,  # a second voice this many cents away, for body
            "repeat": 1,  # play this many times...
            "repeat_gap": 0.0,  # ...spaced this far apart, for footsteps etc.
            "loop": False,  # ambience rather than an effect
        },
    },
    "npcs": {
        "label": "People",
        "required": ("label", "sprite"),
        "defaults": {
            # The villager sprite prefix; the game appends _down / _up / _left /
            # _right, the same contract the player sprite follows.
            "sprite": "",
            # A building id from world.regions["buildings"]. Where they sleep,
            # and where "home" in a schedule resolves to.
            "home": "",
            # [[hour, place], ...]. `place` is a region name ("town_centre"),
            # a landmark ("stall", "well", "cave_mouth"), a building id, or an
            # explicit [x, y]. The game walks them there on a real path.
            "schedule": [],
            # Canned things they say, cycled through on each talk. The LLM npc
            # layer (session 8) replaces the source of these, not the field.
            "lines": [],
            # True for the shopkeeper: talking opens the stall as well.
            "shop": False,
        },
    },
    "recipes": {
        "label": "Recipes",
        "required": ("label", "output"),
        "defaults": {
            # What it makes, by item id, and how many.
            "output": "",
            "output_qty": 1,
            # {item_id: qty} it consumes.
            "inputs": {},
            # Which fixture it is made at -- "workbench" or "cook" (the hearth).
            # The game shows a recipe only at the matching station.
            "station": "workbench",
            # An optional gate on a skill track, unread until skills land.
            "skill": "",
            "skill_level": 0,
            # If set, the recipe upgrades a tool instead of yielding an item:
            # `upgrades` is a tool id and `tier` the level it grants. The recipe
            # only shows when the tool is at tier-1, and crafting it raises the
            # tool's tier -- which the till/water verbs read to work a bigger
            # area. `output` is still required by the schema; point it at the
            # tool's own id for these.
            "upgrades": "",
            "tier": 0,
            # Icon; the game falls back to the output item's sprite.
            "sprite": "",
        },
    },
    "quests": {"label": "Quests", "required": ("label",), "defaults": {}},
    "structures": {
        # A floor plan: rows of legend keys, one key per tile. PixelForge can
        # generate these with a model; a game stamps them into a map. Kept here
        # rather than in a game's own folder because a hut is a hut.
        "label": "Structures",
        "required": ("label", "rows"),
        "defaults": {
            "legend": {},
            "rows": [],
            "w": 0,
            "h": 0,
            "tags": [],
            "source": "",
        },
    },
    "skills": {"label": "Skills", "required": ("label",), "defaults": {}},
    "shapes": {
        # Low-poly vector art: flat-shaded polygons, each painted with a
        # colour *role* ("snow", "rock", "accent") that the game resolves
        # against its palette, time of day and the Forge accent. Points are
        # pixels at scale 1, origin at the base centre, y up is negative.
        # Drift Peaks draws its whole world from these; a pine is a pine.
        "label": "Low-poly shapes",
        "required": ("label", "parts"),
        "defaults": {
            "parts": [],  # [{"role": "leaf", "points": [[x, y], ...]}]
            "kind": "prop",  # prop | rider | animal | pickup
            "place": {},  # how a game scatters it; the game reads its own keys
            "tags": [],
        },
    },
}


def content_root():
    """Where the store lives. FORGE_CONTENT_DIR overrides, which is what lets
    the tests run against a throwaway directory."""
    return os.environ.get("FORGE_CONTENT_DIR") or os.path.join(
        os.path.expanduser("~"), "ForgeGameData"
    )


class ContentError(Exception):
    """Content that cannot be trusted to load."""


class Store:
    """One content store: a set of types, scanned out of one directory.

    The module-level functions below are this class with the shared types and
    the top-level directory, which is what Emberfield and PixelForge use. A
    game whose content nothing else can consume -- an NPC's duty roster, a
    deck of a space station -- passes its own types and its own `game` name and
    gets its own folder, ~/ForgeGameData/<game>/<type>/, without adding
    game-specific types to the shared registry. Cosmos and Janhollow both keep
    a folder of that shape; this is the one scanner behind them.

    A type spec may carry a `check` callable taking the completed entry and
    returning a list of problems, for rules a required-fields list cannot say.
    """

    def __init__(self, types=None, game=""):
        self.types = TYPES if types is None else types
        self.game = game

    # --- where things are --------------------------------------------------

    def root(self):
        base = content_root()
        return os.path.join(base, self.game) if self.game else base

    def type_dir(self, type_name):
        return os.path.join(self.root(), type_name)

    def entry_path(self, type_name, entry_id):
        return os.path.join(self.type_dir(type_name), f"{entry_id}.json")

    def ensure_root(self):
        for type_name in self.types:
            os.makedirs(self.type_dir(type_name), exist_ok=True)
        return self.root()

    # --- validation --------------------------------------------------------

    def validate(self, type_name, entry):
        """Returns a list of human-readable problems; empty means good."""
        spec = self.types.get(type_name)
        if spec is None:
            return [f"{type_name!r} is not a content type"]
        problems = []
        entry_id = entry.get("id", "")
        if not _ID_RE.match(str(entry_id)):
            problems.append(f"id {entry_id!r} must be lowercase letters/digits/-/_")
        for field in spec["required"]:
            value = entry.get(field)
            if value is None or value == "" or value == []:
                problems.append(f"{entry_id or type_name}: {field!r} is required")
        if type_name == "crops":
            stages = entry.get("stages")
            if isinstance(stages, list) and (
                not stages or any(not isinstance(d, int) or d < 1 for d in stages)
            ):
                problems.append(f"{entry_id}: stages must be positive whole days")
        check = spec.get("check")
        if check is not None:
            problems += [
                f"{entry_id or type_name}: {p}"
                for p in check(self.complete(type_name, entry))
            ]
        return problems

    def complete(self, type_name, entry):
        """The entry with its type's defaults filled in, so consumers never have
        to guess whether a field is absent or deliberately zero."""
        merged = copy.deepcopy(self.types[type_name]["defaults"])
        merged.update(entry)
        merged["type"] = type_name
        return merged

    # --- reading and writing -----------------------------------------------

    def list_ids(self, type_name):
        directory = self.type_dir(type_name)
        if not os.path.isdir(directory):
            return []
        return sorted(
            os.path.splitext(name)[0]
            for name in os.listdir(directory)
            if name.endswith(".json") and not name.endswith(".tmp")
        )

    def load(self, type_name, entry_id):
        path = self.entry_path(type_name, entry_id)
        if not os.path.isfile(path):
            raise ContentError(f"no such {type_name} entry: {entry_id}")
        with open(path, "r", encoding="utf-8") as handle:
            return self.complete(type_name, json.load(handle))

    def save(self, type_name, entry, strict=True):
        if type_name not in self.types:
            raise ContentError(f"{type_name!r} is not a content type")
        problems = self.validate(type_name, entry)
        if problems and strict:
            raise ContentError("; ".join(problems[:5]))
        return _write_json(self.entry_path(type_name, entry["id"]), entry)

    def delete(self, type_name, entry_id):
        path = self.entry_path(type_name, entry_id)
        if os.path.isfile(path):
            os.remove(path)
            return True
        return False

    def store(self):
        """Everything a game needs in one response.

        Problems travel *with* the data rather than being raised, so a game can
        show "your turnip file is missing its stages" on screen instead of
        failing to boot or, worse, silently missing a crop.
        """
        self.ensure_root()
        out = {"root": self.root(), "game": self.game, "types": {}, "problems": []}
        for type_name in self.types:
            entries = {}
            for entry_id in self.list_ids(type_name):
                path = self.entry_path(type_name, entry_id)
                try:
                    with open(path, "r", encoding="utf-8") as handle:
                        raw = json.load(handle)
                except (OSError, ValueError) as exc:
                    out["problems"].append(f"{type_name}/{entry_id}.json: {exc}")
                    continue
                raw.setdefault("id", entry_id)
                problems = self.validate(type_name, raw)
                if problems:
                    out["problems"] += [
                        f"{type_name}/{entry_id}.json: {p}" for p in problems
                    ]
                    continue
                entries[entry_id] = self.complete(type_name, raw)
            out["types"][type_name] = entries
        return out


def _write_json(path, data):
    """Write via a temporary file and replace, so a crash or a second Forge
    session cannot leave a half-written entry behind."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    # A unique temporary name per write: two writers of the same entry (two
    # threads, or two apps) sharing one fixed ".tmp" made the second
    # os.replace fail with FileNotFoundError.
    fd, tmp = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".", suffix=".tmp", dir=folder
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path


# The shared store: the types above, at the top of ~/ForgeGameData. Every
# function here is the same call on that store, kept so the apps that predate
# the class need no change.
SHARED = Store()


def type_dir(type_name):
    return SHARED.type_dir(type_name)


def entry_path(type_name, entry_id):
    return SHARED.entry_path(type_name, entry_id)


def ensure_root():
    return SHARED.ensure_root()


def validate(type_name, entry):
    return SHARED.validate(type_name, entry)


def complete(type_name, entry):
    return SHARED.complete(type_name, entry)


def list_ids(type_name):
    return SHARED.list_ids(type_name)


def load(type_name, entry_id):
    return SHARED.load(type_name, entry_id)


def save(type_name, entry, strict=True):
    return SHARED.save(type_name, entry, strict=strict)


def store():
    return SHARED.store()
