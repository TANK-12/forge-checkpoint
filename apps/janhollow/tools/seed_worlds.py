"""Write Janhollow's worlds content into ~/ForgeGameData/janhollow/.

Worlds are the planets, moons, stars, stations and wrecks the station can see
out of its viewports and reach from its docking ring. A world that exists is
left alone unless --force says otherwise.

    .venv/bin/python tools/seed_worlds.py [--force]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from janhollow import content  # noqa: E402

# Planets, moons, stars, stations, ships, wrecks, and fields visible from
# viewports and reachable from the docking ring. The visible_from list names
# location ids where you can see this body out a window.

WORLDS = [
    # Planets
    {
        "id": "terrestria",
        "label": "Terrestria",
        "kind": "planet",
        "sprite": "",
        "distance": "far",
        "colour": "#4a90c7",
        "description": "The home world, turning beneath the station in a slow dance. Most of the crew wake up thinking about someone down there.",
        "visible_from": ["observation", "bridge", "arboretum", "docking_ring"],
        "tags": ["home"],
    },
    {
        "id": "akaira",
        "label": "Akaira",
        "kind": "planet",
        "sprite": "",
        "distance": "far",
        "colour": "#d4a574",
        "description": "A desert world in the system, rust-coloured and dry. Nothing grows there, but the mining surveys say otherwise.",
        "visible_from": ["observation", "bridge", "docking_ring"],
        "tags": ["resource"],
    },
    {
        "id": "sorinn",
        "label": "Sorinn",
        "kind": "planet",
        "sprite": "",
        "distance": "passing",
        "colour": "#8b6f47",
        "description": "An ancient world that passes through the system on an elliptical path, appearing briefly every few years. The crew makes a game of spotting it.",
        "visible_from": ["observation", "bridge"],
        "tags": ["rare"],
    },
    {
        "id": "kalyst",
        "label": "Kalyst",
        "kind": "planet",
        "sprite": "",
        "distance": "far",
        "colour": "#5a4a8a",
        "description": "A distant gas giant barely visible to the naked eye, more a story than a world. The navigator has a theory about its moons.",
        "visible_from": ["observation", "bridge", "navigation"],
        "tags": [],
    },
    # Moons
    {
        "id": "terra-prime",
        "label": "Terra Prime",
        "kind": "moon",
        "sprite": "",
        "distance": "near",
        "colour": "#a8a8a8",
        "description": "Terrestria's largest moon, close enough that you can see its craters without a telescope. The old colony there never sent a second supply run.",
        "visible_from": ["observation", "bridge", "arboretum", "docking_ring"],
        "tags": ["natural"],
    },
    {
        "id": "luminara",
        "label": "Luminara",
        "kind": "moon",
        "sprite": "",
        "distance": "near",
        "colour": "#e8d9a8",
        "description": "The smaller moon, pale and quick across the sky. It rises just after dinner and sets before sleep, so most of the crew watches it without meaning to.",
        "visible_from": ["observation", "bridge", "arboretum"],
        "tags": ["natural"],
    },
    # Stars
    {
        "id": "kelios",
        "label": "Kelios",
        "kind": "star",
        "sprite": "",
        "distance": "far",
        "colour": "#ffdb58",
        "description": "The system's primary star, constant and warm. The reactor operator says it reminds her of home.",
        "visible_from": ["observation", "bridge", "arboretum", "docking_ring"],
        "tags": ["primary"],
    },
    {
        "id": "minor-star",
        "label": "Solis Minor",
        "kind": "star",
        "sprite": "",
        "distance": "far",
        "colour": "#ff8c42",
        "description": "A smaller, redder star barely visible in the system, yet old enough that the physicists argue about its history.",
        "visible_from": ["observation", "bridge", "navigation"],
        "tags": ["secondary"],
    },
    # Stations and Ships
    {
        "id": "rydian-station",
        "label": "Rydian Station",
        "kind": "station",
        "sprite": "",
        "distance": "near",
        "colour": "#888888",
        "description": "A trading post and refuelling station two days out. The crew takes turns during layovers, and there is always fresh coffee.",
        "visible_from": ["docking_ring", "cargo_bay", "observation"],
        "tags": ["trade", "port"],
    },
    {
        "id": "the-merchant",
        "label": "The Merchant's Rest",
        "kind": "ship",
        "sprite": "",
        "distance": "near",
        "colour": "#7a6d5f",
        "description": "A long-haul trader that passes through the system every season, always carrying something unexpected. The cook trades recipes with its crew.",
        "visible_from": ["docking_ring", "observation", "bridge"],
        "tags": ["trader"],
    },
    {
        "id": "haven-settlement",
        "label": "Haven Settlement",
        "kind": "station",
        "sprite": "",
        "distance": "far",
        "colour": "#6a8a5a",
        "description": "An orbital settlement built over decades, growing its own food and keeping its own counsel. Few ships dock there, but those that do speak well of it.",
        "visible_from": ["observation", "bridge", "docking_ring"],
        "tags": ["settlement"],
    },
    # Wreck
    {
        "id": "lost-horizon",
        "label": "The Lost Horizon",
        "kind": "wreck",
        "sprite": "",
        "distance": "passing",
        "colour": "#5a5a5a",
        "description": "An old freighter drifting in the dark, silent for years. The navigator keeps its coordinates in case something down there is ever worth recovering.",
        "visible_from": ["observation", "docking_ring"],
        "tags": ["derelict", "cautionary"],
    },
    # Fields
    {
        "id": "cascade-field",
        "label": "The Cascades",
        "kind": "field",
        "sprite": "",
        "distance": "near",
        "colour": "#cccccc",
        "description": "An asteroid field rich with interesting rocks, dangerous in places but beautiful to watch. The engineer dreams about salvage.",
        "visible_from": ["observation", "docking_ring", "bridge"],
        "tags": ["natural", "resource"],
    },
    {
        "id": "nebula-dust",
        "label": "The Veil",
        "kind": "field",
        "sprite": "",
        "distance": "far",
        "colour": "#9d7a8f",
        "description": "A dust nebula that shifts with the seasons, sometimes coloured red and sometimes blue depending on the light. The afternoon watch likes to watch it change.",
        "visible_from": ["observation", "bridge", "arboretum"],
        "tags": ["natural", "beautiful"],
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
    write("worlds", WORLDS, force)
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
