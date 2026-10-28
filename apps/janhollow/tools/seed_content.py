"""Write Janhollow's starting content into ~/ForgeGameData/janhollow/.

Run once to fill an empty store; run again after hand-editing and nothing is
lost, because an entry that already exists is left alone unless --force says
otherwise. Everything this writes is ordinary data: the station is four deck
files and twenty-four room files, the crew is eight files, and every one of
them can be edited, copied or deleted without touching a line of code.

    .venv/bin/python tools/seed_content.py [--force]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from janhollow import content  # noqa: E402

# --- the station ------------------------------------------------------------
#
# Every deck is the same 42x25 frame: a corridor crossing, four rooms above it
# and up to four below. Rooms are placed on that grid by hand rather than
# generated, so a room can be moved by editing two numbers.

DECK_FRAME = {
    "width": 42,
    "height": 25,
    "corridors": [[2, 12, 38, 2], [20, 3, 2, 20]],
    "lift": [20, 12],
    # Sprites from the 32px janhollow-deck pack. Walls are autotiled by the
    # renderer out of sixteen variants, so no deck names a wall sprite.
    "floor": "floor_plate",
    "wall": "wall",
    "palette": "janhollow",
}

# Column slots on the frame: (x, width). A room may span several by widening.
WIDE_LEFT = (2, 17)
SMALL = {"a": (2, 8), "b": (11, 8), "c": (23, 8), "d": (32, 8)}
TOP, BOTTOM = 3, 15
TALL = 8

DECKS = [
    {
        "id": "command",
        "label": "Command deck",
        "tagline": "The bridge, the long window and the quiet radio",
        "order": 1,
    },
    {
        "id": "habitat",
        "label": "Habitat ring",
        "tagline": "Bunks, the mess and the only good couch aboard",
        "order": 2,
    },
    {
        "id": "garden",
        "label": "Garden deck",
        "tagline": "Hydroponics, the medbay and the smell of wet soil",
        "order": 3,
    },
    {
        "id": "engineering",
        "label": "Engineering",
        "tagline": "The reactor, the cargo bay and the docking ring",
        "order": 4,
    },
]


# Props you walk over rather than into. Everything else stops you, and stops
# the crew too — they used to path straight through the furniture.
FLAT = {"rug", "towel_blue", "towel_pink", "sand", "sand_wet", "foam", "beach_sign"}


def room(rid, label, deck, slot, row, kind, props=(), tags=(), wide=False):
    x, w = WIDE_LEFT if wide else SMALL[slot]
    return {
        "id": rid,
        "label": label,
        "deck": deck,
        "rect": [x, row, w, TALL],
        "kind": kind,
        "props": [
            {"sprite": s, "x": px, "y": py, **({"solid": False} if s in FLAT else {})}
            for s, px, py in props
        ],
        "tags": list(tags),
    }


LOCATIONS = [
    # Command deck
    room(
        "bridge",
        "Bridge",
        "command",
        "a",
        TOP,
        "work",
        wide=True,
        props=[
            ("bridge_display", 7, 0),
            ("console", 3, 3),
            ("console", 5, 3),
            ("console", 11, 3),
            ("console", 13, 3),
            ("star_window", 1, 0),
        ],
        tags=["duty"],
    ),
    room(
        "comms",
        "Comms room",
        "command",
        "c",
        TOP,
        "work",
        props=[("server_rack", 1, 1), ("desk", 3, 4), ("corkboard", 4, 0)],
    ),
    room(
        "captains_office",
        "Chief's office",
        "command",
        "d",
        TOP,
        "work",
        props=[("desk", 2, 2), ("bookshelf", 5, 1), ("plant", 1, 5)],
    ),
    room(
        "observation",
        "Observation lounge",
        "command",
        "a",
        BOTTOM,
        "social",
        wide=True,
        props=[
            ("star_window", 3, 1),
            ("star_window", 7, 1),
            ("star_window", 11, 1),
            ("couch", 5, 4),
            ("beanbag", 9, 5),
            ("plant", 14, 5),
        ],
        tags=["evening"],
    ),
    room(
        "navigation",
        "Navigation",
        "command",
        "c",
        BOTTOM,
        "work",
        props=[("console", 2, 2), ("console", 4, 2), ("whiteboard", 1, 4)],
    ),
    room(
        "briefing",
        "Briefing room",
        "command",
        "d",
        BOTTOM,
        "social",
        props=[("counter", 2, 2), ("whiteboard", 4, 0), ("lamp", 1, 5)],
    ),
    # Habitat ring
    room(
        "mess_hall",
        "Mess hall",
        "habitat",
        "a",
        TOP,
        "social",
        wide=True,
        props=[
            ("kotatsu", 4, 3),
            ("bench", 3, 5),
            ("bench", 9, 5),
            ("counter", 13, 2),
            ("coffee_machine", 15, 2),
            ("plant", 1, 5),
        ],
        tags=["meals"],
    ),
    room(
        "galley",
        "Galley",
        "habitat",
        "c",
        TOP,
        "work",
        props=[("counter", 1, 2), ("counter", 3, 2), ("coffee_machine", 5, 2)],
    ),
    room(
        "lounge",
        "Crew lounge",
        "habitat",
        "d",
        TOP,
        "social",
        props=[("couch", 2, 3), ("aquarium", 5, 1), ("lamp", 1, 1), ("cat", 4, 5)],
        tags=["evening"],
    ),
    room(
        "quarters_port",
        "Port quarters",
        "habitat",
        "a",
        BOTTOM,
        "quarters",
        props=[
            ("bunk", 1, 1),
            ("bunk", 4, 1),
            ("bunk", 1, 4),
            ("bunk", 4, 4),
            ("locker", 6, 1),
            ("beanbag", 6, 5),
        ],
        tags=["sleep"],
    ),
    room(
        "quarters_starboard",
        "Starboard quarters",
        "habitat",
        "b",
        BOTTOM,
        "quarters",
        props=[
            ("bunk", 1, 1),
            ("bunk", 4, 1),
            ("bunk", 1, 4),
            ("bunk", 4, 4),
            ("locker", 6, 1),
            ("beanbag_green", 6, 5),
        ],
        tags=["sleep"],
    ),
    room(
        "gym",
        "Gym",
        "habitat",
        "c",
        BOTTOM,
        "social",
        props=[("towel_blue", 1, 1), ("bench", 3, 4), ("towel_pink", 6, 1)],
    ),
    room(
        "washroom",
        "Washroom",
        "habitat",
        "d",
        BOTTOM,
        "room",
        props=[("counter", 2, 2), ("towel_blue", 5, 4)],
    ),
    # Garden deck
    room(
        "hydroponics",
        "Hydroponics",
        "garden",
        "a",
        TOP,
        "garden",
        wide=True,
        props=[
            ("plant", 2, 2),
            ("plant", 5, 2),
            ("plant", 8, 2),
            ("plant", 11, 2),
            ("plant", 14, 2),
            ("palm", 3, 5),
            ("palm", 12, 5),
        ],
        tags=["duty", "quiet"],
    ),
    room(
        "medbay",
        "Medbay",
        "garden",
        "c",
        TOP,
        "work",
        props=[("bunk", 1, 1), ("bunk", 1, 4), ("counter", 5, 2), ("lamp", 6, 5)],
    ),
    room(
        "lab",
        "Lab",
        "garden",
        "d",
        TOP,
        "work",
        props=[("desk", 2, 2), ("server_rack", 5, 1), ("aquarium", 1, 5)],
    ),
    room(
        "arboretum",
        "Arboretum",
        "garden",
        "a",
        BOTTOM,
        "garden",
        wide=True,
        props=[
            ("palm", 2, 2),
            ("palm", 6, 4),
            ("palm", 11, 2),
            ("bench", 8, 5),
            ("plant", 14, 3),
            ("cat", 5, 5),
        ],
        tags=["quiet", "evening"],
    ),
    room(
        "water_plant",
        "Water reclamation",
        "garden",
        "c",
        BOTTOM,
        "work",
        props=[("reactor", 2, 2), ("console", 5, 4)],
    ),
    room(
        "library",
        "Reading room",
        "garden",
        "d",
        BOTTOM,
        "social",
        props=[
            ("bookshelf", 1, 1),
            ("bookshelf", 3, 1),
            ("couch", 4, 4),
            ("lamp", 6, 5),
        ],
        tags=["quiet"],
    ),
    # Engineering
    room(
        "reactor_room",
        "Reactor",
        "engineering",
        "a",
        TOP,
        "work",
        wide=True,
        props=[
            ("reactor", 7, 2),
            ("console", 4, 4),
            ("console", 11, 4),
            ("server_rack", 1, 1),
            ("server_rack", 15, 1),
        ],
        tags=["duty", "loud"],
    ),
    room(
        "workshop",
        "Workshop",
        "engineering",
        "c",
        TOP,
        "work",
        props=[("desk", 1, 2), ("whiteboard", 4, 1), ("item_file", 6, 4)],
    ),
    room(
        "machine_shop",
        "Machine shop",
        "engineering",
        "d",
        TOP,
        "work",
        props=[("counter", 2, 2), ("console", 5, 4)],
    ),
    room(
        "cargo_bay",
        "Cargo bay",
        "engineering",
        "a",
        BOTTOM,
        "work",
        wide=True,
        props=[
            ("crate", 2, 2),
            ("crate", 4, 2),
            ("crate", 3, 4),
            ("crate", 9, 2),
            ("crate", 11, 4),
            ("counter", 6, 2),
            ("bench", 13, 5),
        ],
        tags=["loud"],
    ),
    room(
        "docking_ring",
        "Docking ring",
        "engineering",
        "c",
        BOTTOM,
        "dock",
        props=[("star_window", 0, 0), ("console", 5, 4)],
        tags=["arrivals"],
    ),
    room(
        "suit_room",
        "Suit room",
        "engineering",
        "d",
        BOTTOM,
        "room",
        props=[
            ("locker", 1, 1),
            ("locker", 3, 1),
            ("locker", 5, 1),
            ("corkboard", 1, 4),
            ("bench", 4, 4),
        ],
    ),
]

# What a room stands on, where it is not the deck's default plate: soil where
# things grow, worn plate where the work is loudest. A room not listed here uses
# its deck's floor, so this stays short.
FLOORS = {
    "hydroponics": "floor_garden",
    "arboretum": "floor_garden",
    "reactor_room": "floor_plate_worn",
    "cargo_bay": "floor_plate_worn",
    "workshop": "floor_plate_worn",
    "machine_shop": "floor_plate_worn",
    "docking_ring": "floor_plate_worn",
}

for _location in LOCATIONS:
    if _location["id"] in FLOORS:
        _location["floor"] = FLOORS[_location["id"]]


# --- the crew ---------------------------------------------------------------
#
# Eight to start, which is what the owner asked for. Each one is a file; a ninth
# is a ninth file and needs nothing else. "aboard": false retires a crew member
# without losing who they were, because the narrator is allowed to transfer
# people off the station and bring new ones in.

CREW = [
    {
        "id": "vessa-oduya",
        "label": "Vessa Oduya",
        "job": "Station chief",
        "pronouns": "she/her",
        "sprite": "person1",
        "home": "quarters_port",
        "personality": "Dry, unhurried, notices everything and mentions a third of it.",
        "traits": ["steady", "observant"],
        "relationships": {"tamsin-reyes": 2, "co-amari": 1, "juno-park": 1},
        "schedule": [
            {"at": "06:40", "goto": "quarters_port", "activity": "waking up"},
            {"at": "07:10", "goto": "mess_hall", "activity": "coffee, first pot"},
            {"at": "08:00", "goto": "bridge", "activity": "morning watch"},
            {"at": "12:30", "goto": "mess_hall", "activity": "lunch"},
            {"at": "13:30", "goto": "captains_office", "activity": "paperwork"},
            {"at": "16:00", "goto": "bridge", "activity": "afternoon watch"},
            {"at": "18:30", "goto": "mess_hall", "activity": "dinner"},
            {"at": "20:00", "goto": "observation", "activity": "watching the drift"},
            {"at": "22:30", "goto": "quarters_port", "activity": "turning in"},
        ],
    },
    {
        "id": "bo-ferreira",
        "label": "Bo Ferreira",
        "job": "Cook",
        "pronouns": "he/him",
        "sprite": "person2",
        "home": "quarters_starboard",
        "personality": "Loud, warm, feeds people before they know they are hungry.",
        "traits": ["warm", "stubborn"],
        "relationships": {"mira-song": 2, "dez-halloway": 2},
        "schedule": [
            {"at": "05:30", "goto": "galley", "activity": "starting the bread"},
            {"at": "07:00", "goto": "mess_hall", "activity": "serving breakfast"},
            {
                "at": "09:30",
                "goto": "hydroponics",
                "activity": "arguing about tomatoes",
            },
            {"at": "11:00", "goto": "galley", "activity": "prep"},
            {"at": "12:15", "goto": "mess_hall", "activity": "serving lunch"},
            {"at": "14:00", "goto": "quarters_starboard", "activity": "a flat nap"},
            {"at": "16:30", "goto": "galley", "activity": "dinner prep"},
            {"at": "18:15", "goto": "mess_hall", "activity": "serving dinner"},
            {"at": "20:30", "goto": "lounge", "activity": "cards"},
            {"at": "23:00", "goto": "quarters_starboard", "activity": "sleep"},
        ],
    },
    {
        "id": "tamsin-reyes",
        "label": "Tamsin Reyes",
        "job": "Chief engineer",
        "pronouns": "she/her",
        "sprite": "person3",
        "home": "quarters_port",
        "personality": "Talks to the reactor more than to people, and it listens.",
        "traits": ["blunt", "tireless"],
        "relationships": {"vessa-oduya": 2, "ilya-novak": 1},
        "schedule": [
            {"at": "06:00", "goto": "reactor_room", "activity": "cold-start checks"},
            {"at": "08:30", "goto": "mess_hall", "activity": "breakfast, standing up"},
            {
                "at": "09:15",
                "goto": "workshop",
                "activity": "fixing the thing from yesterday",
            },
            {"at": "12:45", "goto": "mess_hall", "activity": "lunch"},
            {"at": "13:45", "goto": "reactor_room", "activity": "trim and tune"},
            {"at": "17:00", "goto": "machine_shop", "activity": "cutting a part"},
            {"at": "19:00", "goto": "mess_hall", "activity": "late dinner"},
            {
                "at": "20:30",
                "goto": "observation",
                "activity": "not talking about work",
            },
            {"at": "23:30", "goto": "quarters_port", "activity": "sleep"},
        ],
    },
    {
        "id": "ilya-novak",
        "label": "Ilya Novak",
        "job": "Botanist",
        "pronouns": "he/him",
        "sprite": "person4",
        "home": "quarters_starboard",
        "personality": "Gentle, slow to speak, keeps a running argument with the ventilation.",
        "traits": ["patient", "shy"],
        "relationships": {"bo-ferreira": 1, "mira-song": 1},
        "schedule": [
            {"at": "06:30", "goto": "hydroponics", "activity": "lights up, water on"},
            {"at": "08:15", "goto": "mess_hall", "activity": "breakfast"},
            {"at": "09:00", "goto": "hydroponics", "activity": "pruning"},
            {"at": "12:30", "goto": "mess_hall", "activity": "lunch"},
            {"at": "13:30", "goto": "arboretum", "activity": "soil samples"},
            {"at": "16:30", "goto": "lab", "activity": "writing it all down"},
            {"at": "18:30", "goto": "mess_hall", "activity": "dinner"},
            {"at": "20:00", "goto": "library", "activity": "reading"},
            {"at": "22:00", "goto": "quarters_starboard", "activity": "sleep"},
        ],
    },
    {
        "id": "mira-song",
        "label": "Mira Song",
        "job": "Medic",
        "pronouns": "she/her",
        "sprite": "person5",
        "home": "quarters_port",
        "personality": "Calm in a crisis, gossips shamelessly in every other hour.",
        "traits": ["calm", "curious"],
        "relationships": {"bo-ferreira": 2, "juno-park": 1},
        "schedule": [
            {"at": "07:00", "goto": "mess_hall", "activity": "breakfast"},
            {"at": "08:00", "goto": "medbay", "activity": "morning clinic"},
            {"at": "11:00", "goto": "gym", "activity": "making someone stretch"},
            {"at": "12:30", "goto": "mess_hall", "activity": "lunch"},
            {"at": "14:00", "goto": "medbay", "activity": "inventory"},
            {
                "at": "16:00",
                "goto": "arboretum",
                "activity": "a walk that counts as work",
            },
            {"at": "18:15", "goto": "mess_hall", "activity": "dinner"},
            {"at": "19:45", "goto": "lounge", "activity": "cards, badly"},
            {"at": "22:45", "goto": "quarters_port", "activity": "sleep"},
        ],
    },
    {
        "id": "co-amari",
        "label": "Cobalt Amari",
        "job": "Comms officer",
        "pronouns": "they/them",
        "sprite": "person6",
        "home": "quarters_starboard",
        "personality": "Half here, half listening to a signal nobody else can hear.",
        "traits": ["dreamy", "precise"],
        "relationships": {"vessa-oduya": 1, "juno-park": 2},
        "schedule": [
            {"at": "07:30", "goto": "mess_hall", "activity": "tea"},
            {"at": "08:30", "goto": "comms", "activity": "the morning traffic"},
            {"at": "12:30", "goto": "mess_hall", "activity": "lunch"},
            {"at": "13:30", "goto": "comms", "activity": "logging relays"},
            {"at": "17:30", "goto": "briefing", "activity": "the day's summary"},
            {"at": "18:30", "goto": "mess_hall", "activity": "dinner"},
            {"at": "20:00", "goto": "observation", "activity": "listening to nothing"},
            {"at": "23:15", "goto": "quarters_starboard", "activity": "sleep"},
        ],
    },
    {
        "id": "dez-halloway",
        "label": "Dez Halloway",
        "job": "Dock hand",
        "pronouns": "he/him",
        "sprite": "person7",
        "home": "quarters_starboard",
        "personality": "Cheerfully overcommitted, owes four people a favour.",
        "traits": ["cheerful", "scattered"],
        "relationships": {"bo-ferreira": 2, "tamsin-reyes": 1},
        "schedule": [
            {"at": "06:45", "goto": "mess_hall", "activity": "breakfast, twice"},
            {"at": "07:45", "goto": "docking_ring", "activity": "checking the seals"},
            {"at": "10:00", "goto": "cargo_bay", "activity": "moving crates"},
            {"at": "12:30", "goto": "mess_hall", "activity": "lunch"},
            {"at": "13:30", "goto": "cargo_bay", "activity": "the manifest"},
            {"at": "16:45", "goto": "suit_room", "activity": "drying suits"},
            {"at": "18:15", "goto": "mess_hall", "activity": "dinner"},
            {"at": "19:30", "goto": "gym", "activity": "lifting things for fun"},
            {"at": "22:15", "goto": "quarters_starboard", "activity": "sleep"},
        ],
    },
    {
        "id": "juno-park",
        "label": "Juno Park",
        "job": "Navigator, night watch",
        "pronouns": "she/her",
        "sprite": "person8",
        "home": "quarters_port",
        "personality": "Nocturnal, deadpan, knows where everything is at 3am.",
        "traits": ["nocturnal", "deadpan"],
        "relationships": {"co-amari": 2, "mira-song": 1},
        "schedule": [
            {"at": "00:30", "goto": "navigation", "activity": "plotting the drift"},
            {"at": "03:00", "goto": "observation", "activity": "the quiet hour"},
            {"at": "05:30", "goto": "mess_hall", "activity": "breakfast before anyone"},
            {"at": "06:30", "goto": "quarters_port", "activity": "sleep, finally"},
            {"at": "15:00", "goto": "gym", "activity": "waking up slowly"},
            {"at": "16:30", "goto": "library", "activity": "charts and coffee"},
            {"at": "18:45", "goto": "mess_hall", "activity": "dinner, her breakfast"},
            {"at": "20:30", "goto": "bridge", "activity": "taking the watch"},
        ],
    },
]

# --- narrator material ------------------------------------------------------
#
# Nothing reads these yet: session 3 gives them to the 4B narrator. They are
# seeded now so the format is on disk and editable from the first day.

EVENTS = [
    {
        "id": "supply-run",
        "label": "A supply barge docks",
        "prompt": "A slow supply barge is coming in. Crates, mail, and one thing nobody ordered.",
        "needs": ["dock"],
        "weight": 2,
        "tags": ["arrivals", "cozy"],
    },
    {
        "id": "quiet-fault",
        "label": "Something hums wrong",
        "prompt": "A small fault nobody can locate: a hum, a flicker, a door that sticks.",
        "needs": ["work"],
        "weight": 2,
        "tags": ["engineering"],
    },
    {
        "id": "harvest-night",
        "label": "The tomatoes are finally ready",
        "prompt": "The garden deck has produced something worth a shared meal.",
        "needs": ["garden"],
        "weight": 1,
        "tags": ["cozy", "meals"],
    },
]

QUESTS = [
    {
        "id": "find-the-hum",
        "label": "Find the hum",
        "giver_job": "Chief engineer",
        "prompt": "Walk the decks and work out which room the hum is loudest in.",
        "steps": [
            "Ask three crew where they hear it",
            "Stand in the loudest room",
            "Tell the engineer",
        ],
        "tags": ["starter"],
    },
    {
        "id": "dinner-for-eight",
        "label": "Dinner for eight",
        "giver_job": "Cook",
        "prompt": "The cook wants everyone in the mess at once, which has never happened.",
        "steps": ["Ask each crew member", "Be in the mess hall at dinner"],
        "tags": ["starter", "cozy"],
    },
]


def write(kind, entries, force):
    written, kept = 0, 0
    for entry in entries:
        path = content.STORE.entry_path(kind, entry["id"])
        if os.path.exists(path) and not force:
            kept += 1
            continue
        content.STORE.save(kind, entry)
        written += 1
    print(f"{kind}: {written} written, {kept} left alone")


def main():
    force = "--force" in sys.argv
    content.STORE.ensure_root()
    write("decks", [dict(DECK_FRAME, **deck) for deck in DECKS], force)
    write("locations", LOCATIONS, force)
    write("npcs", CREW, force)
    write("events", EVENTS, force)
    write("quests", QUESTS, force)
    result = content.store()
    print("store root:", result["root"])
    for problem in result["problems"]:
        print("  problem:", problem)
    print({k: len(v) for k, v in result["types"].items()})


if __name__ == "__main__":
    if {"-h", "--help"} & set(sys.argv[1:]):  # usage only, no work
        print(__doc__)
        sys.exit(0)
    main()
