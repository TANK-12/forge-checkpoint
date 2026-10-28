"""What Janhollow is made of: decks, locations, crew, events and quests.

Every one of those is a JSON file in ~/ForgeGameData/janhollow/<type>/, and
nothing in the code lists what exists. Adding a crew member is one file in
npcs/; adding a whole deck is one file in decks/ plus the rooms that sit on it.
The scanner, the validation and the "problems travel with the data" rule all
come from shared/forge_content.py -- this module only declares the types.

The types live here rather than in the shared registry because nothing else can
consume them: a duty roster and a lift shaft mean nothing to Emberfield. The
shared store keeps the types that cross games (items, sounds, crops); a game
with its own vocabulary gets its own folder, which is the shape Cosmos already
uses for its levels.
"""

import os
import re
import sys

SHARED_DIR = os.environ.get("FORGE_SHARED_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "shared"
)
sys.path.insert(0, os.path.abspath(SHARED_DIR))

import forge_content  # noqa: E402

GAME = "janhollow"

_CLOCK_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _check_deck(deck):
    """A deck has to be a rectangle big enough to hold a lift."""
    problems = []
    for field in ("width", "height"):
        value = deck.get(field)
        if not isinstance(value, int) or value < 8:
            problems.append(f"{field} must be a whole number of tiles, 8 or more")
    lift = deck.get("lift")
    if not (
        isinstance(lift, list)
        and len(lift) == 2
        and all(isinstance(n, int) for n in lift)
    ):
        problems.append("lift must be [x, y] in tiles")
    if not isinstance(deck.get("corridors"), list) or not deck["corridors"]:
        problems.append("corridors must be a non-empty list of [x, y, w, h]")
    return problems


def _check_location(location):
    rect = location.get("rect")
    if not (
        isinstance(rect, list)
        and len(rect) == 4
        and all(isinstance(n, int) for n in rect)
    ):
        return ["rect must be [x, y, width, height] in tiles"]
    if rect[2] < 3 or rect[3] < 3:
        return ["rect must be at least 3x3 so the room has an inside"]
    return []


def _check_npc(npc):
    """The schedule is the part a person is most likely to get wrong by hand,
    so it is the part that is checked: real times, in order, going somewhere."""
    problems = []
    schedule = npc.get("schedule")
    if not isinstance(schedule, list) or not schedule:
        return ["schedule must be a list of {at, goto, activity}"]
    last = ""
    for entry in schedule:
        if not isinstance(entry, dict):
            problems.append("every schedule entry must be an object")
            continue
        at = str(entry.get("at", ""))
        if not _CLOCK_RE.match(at):
            problems.append(f"schedule time {at!r} must look like 07:30")
        elif at <= last:
            problems.append(f"schedule time {at} is not after {last}")
        else:
            last = at
        if not entry.get("goto"):
            problems.append(f"schedule entry at {at or '?'} has no goto location")
    return problems


TYPES = {
    "decks": {
        "label": "Decks",
        "required": ("label", "width", "height"),
        "check": _check_deck,
        "defaults": {
            "order": 0,
            "width": 40,
            "height": 24,
            # Where the lift opens on this deck. The same tile on every deck is
            # not required: the shaft is logical, not geometric.
            "lift": [20, 12],
            # Walkable spine of the deck, carved before the rooms. Data rather
            # than a generator so a deck can be redrawn without code.
            "corridors": [[2, 11, 36, 2]],
            "floor": "floor_metal",
            "wall": "wall_metal",
            "palette": "crewroom",
            "tagline": "",
        },
    },
    "locations": {
        "label": "Locations",
        "required": ("label", "deck"),
        "check": _check_location,
        "defaults": {
            "deck": "",
            "rect": [2, 2, 6, 5],
            # What happens here, used by schedules and later by the narrator.
            "kind": "room",  # room | quarters | work | social | garden | dock
            "floor": "",  # falls back to the deck's floor
            "props": [],  # [{"sprite": "console", "x": 1, "y": 1}] room-relative
            "door": [],  # [x, y] absolute; computed when left out
            "tags": [],
        },
    },
    "npcs": {
        "label": "Crew",
        "required": ("label", "job"),
        "check": _check_npc,
        "defaults": {
            "job": "",
            "pronouns": "they/them",
            "personality": "",
            "sprite": "person1",
            "home": "",
            "speed": 2.6,  # tiles a second
            "schedule": [],
            "relationships": {},
            "traits": [],
            # Item ids this person is glad to be given. A liked gift warms
            # them; anything else is only polite. See janhollow/carry.py.
            "likes": [],
            "arrived_day": 1,
            # Crew can come and go: a member who has transferred off keeps their
            # file and stops being spawned, rather than being deleted.
            "aboard": True,
        },
    },
    "worlds": {
        # What you can see out of a viewport and what the docking ring connects
        # to: planets, moons, stars, other stations, wrecks. Seeded as data so a
        # new destination is one file, and so the narrator has somewhere real to
        # send a barge from.
        "label": "Worlds",
        "required": ("label", "kind"),
        "defaults": {
            "kind": "planet",  # planet | moon | star | station | ship | wreck | field
            "sprite": "",
            "distance": "near",  # near | far | passing
            "colour": "#8fb7d9",
            "description": "",
            "visible_from": [],  # location ids whose viewports show it
            "tags": [],
        },
    },
    "items": {
        # Things you can pick up, carry and give away. The sprite must already
        # exist in the named pack: the narrator is not allowed to invent an
        # item nothing can draw. One copy starts in each room in starts_in.
        "label": "Items",
        "required": ("label", "sprite"),
        "defaults": {
            "sprite": "",
            "pack": "janhollow-space",
            "article": "a",
            "starts_in": [],
            "tags": [],
        },
    },
    "events": {
        "label": "Events",
        "required": ("label",),
        "defaults": {
            "prompt": "",
            "weight": 1,
            "needs": [],  # location kinds or crew jobs the event wants present
            "tags": [],
        },
    },
    "quests": {
        "label": "Quests",
        "required": ("label",),
        "defaults": {
            "prompt": "",
            "giver_job": "",
            "steps": [],
            "tags": [],
        },
    },
}

STORE = forge_content.Store(TYPES, game=GAME)


def data_root():
    return STORE.root()


def store():
    return STORE.store()
