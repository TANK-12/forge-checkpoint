"""Write the janhollow-station art pack into ~/ForgeArtData/packs/.

Janhollow reuses the crewroom packs for almost everything -- metal floors and
walls, consoles, reactors, star windows, plants, and eight anime crew sprites
with walk cycles -- because art in ForgeArtData belongs to no single app. This
pack is only what a station needs and a crew room does not: a door, a lift pad,
a floor grate and a bunk.

The sprites are palette-indexed rows against the crewroom palette, so they are
editable in Pixel Forge like every other pack, and a palette swap re-skins them
with everything else. The crewroom palette and packs ship in shared/art_seed/,
so this script copies whichever of them the library lacks first: Janhollow
is installed without the Crew Room, and on a fresh install it would otherwise
draw nothing.

    .venv/bin/python tools/seed_art.py [--force]
"""

import os
import sys

SHARED_DIR = os.environ.get("FORGE_SHARED_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "..", "shared"
)
sys.path.insert(0, os.path.abspath(SHARED_DIR))

import forge_art  # noqa: E402

PACK_ID = "janhollow-station"

# x/X: hull grey. R: deep panel. y/Y: station aqua. z: highlight. O: warning amber.
DOOR = [
    "XXXXXXXXXXXXXXXX",
    "XRRRRRRRRRRRRRRX",
    "XRyyyyyRyyyyyRRX",
    "XRyzzzyRyzzzyRRX",
    "XRyzYzyRyzYzyRRX",
    "XRyzzzyRyzzzyRRX",
    "XRyyyyyRyyyyyRRX",
    "XRRRRRRRRRRRRRRX",
    "XRRRRRRRRRRRRRRX",
    "XRyyyyyRyyyyyRRX",
    "XRyzzzyRyzzzyRRX",
    "XRyzYzyRyzYzyRRX",
    "XRyzzzyRyzzzyRRX",
    "XRyyyyyRyyyyyRRX",
    "XRRRRRRRRRRRRRRX",
    "XXXXXXXXXXXXXXXX",
]

LIFT = [
    "XXXXXXXXXXXXXXXX",
    "XRRRRRRRRRRRRRRX",
    "XRRRRRRyyRRRRRRX",
    "XRRRRRyzzyRRRRRX",
    "XRRRRyzzzzyRRRRX",
    "XRRRRRRyyRRRRRRX",
    "XRRRRRRyyRRRRRRX",
    "XRXXXXXXXXXXXXRX",
    "XRXXXXXXXXXXXXRX",
    "XRRRRRRyyRRRRRRX",
    "XRRRRRRyyRRRRRRX",
    "XRRRRyzzzzyRRRRX",
    "XRRRRRyzzyRRRRRX",
    "XRRRRRRyyRRRRRRX",
    "XRRRRRRRRRRRRRRX",
    "XXXXXXXXXXXXXXXX",
]

GRATE = [
    "XXXXXXXXXXXXXXXX",
    "XRRRXRRRXRRRXRRX",
    "XRRRXRRRXRRRXRRX",
    "XRRRXRRRXRRRXRRX",
    "XXXXXXXXXXXXXXXX",
    "XRRRXRRRXRRRXRRX",
    "XRRRXRRRXRRRXRRX",
    "XRRRXRRRXRRRXRRX",
    "XXXXXXXXXXXXXXXX",
    "XRRRXRRRXRRRXRRX",
    "XRRRXRRRXRRRXRRX",
    "XRRRXRRRXRRRXRRX",
    "XXXXXXXXXXXXXXXX",
    "XRRRXRRRXRRRXRRX",
    "XRRRXRRRXRRRXRRX",
    "XXXXXXXXXXXXXXXX",
]

BUNK = [
    "................",
    "................",
    "..XXXXXXXXXXXX..",
    "..XccccccccccX..",
    "..XcwwcbbbbbcX..",
    "..XcwwcbbbbbcX..",
    "..XccccbbbbbcX..",
    "..XcccccbbbbcX..",
    "..XccccccccccX..",
    "..XXXXXXXXXXXX..",
    "..X..........X..",
    "..X..........X..",
    "................",
    "................",
    "................",
    "................",
]

CRATE = [
    "................",
    "................",
    "..tttttttttttt..",
    "..tUUUUUUUUUUt..",
    "..tUttUUUUttUt..",
    "..tUtUtUUtUtUt..",
    "..tUtUUttUUtUt..",
    "..tUtUUttUUtUt..",
    "..tUtUtUUtUtUt..",
    "..tUttUUUUttUt..",
    "..tUUUUUUUUUUt..",
    "..tttttttttttt..",
    "................",
    "................",
    "................",
    "................",
]

LOCKER = [
    "................",
    ".XXXXXXXXXXXXXX.",
    ".XRRRRRRXRRRRRX.",
    ".XRyyyyRXRyyyyX.",
    ".XRyyyyRXRyyyyX.",
    ".XRRRRRRXRRRRRX.",
    ".XRRRRzRXRzRRRX.",
    ".XRRRRRRXRRRRRX.",
    ".XRyyyyRXRyyyyX.",
    ".XRyyyyRXRyyyyX.",
    ".XRRRRRRXRRRRRX.",
    ".XXXXXXXXXXXXXX.",
    "................",
    "................",
    "................",
    "................",
]

SPRITES = {
    "station_door": (DOOR, ["tile", "door"]),
    "station_lift": (LIFT, ["tile", "lift"]),
    "floor_grate": (GRATE, ["tile", "floor"]),
    "bunk": (BUNK, ["prop"]),
    "crate": (CRATE, ["prop"]),
    "locker": (LOCKER, ["prop"]),
}


def main():
    force = "--force" in sys.argv
    forge_art.ensure_root()
    for copied in forge_art.ensure_seeded():
        print("copied starting art", copied)
    path = forge_art.pack_path(PACK_ID)
    if os.path.exists(path) and not force:
        print(f"{path} already exists; pass --force to overwrite")
        return
    pack = {
        "id": PACK_ID,
        "label": "Janhollow — station fittings",
        "tile": 16,
        "default_palette": "crewroom",
        "sprites": {
            name: {
                "w": 16,
                "h": 16,
                "tags": tags,
                "frames": [{"ms": 0, "rows": rows}],
            }
            for name, (rows, tags) in SPRITES.items()
        },
    }
    forge_art.save_pack(pack)
    print("wrote", path, "with", len(SPRITES), "sprites")


if __name__ == "__main__":
    if {"-h", "--help"} & set(sys.argv[1:]):  # usage only, no work
        print(__doc__)
        sys.exit(0)
    main()
