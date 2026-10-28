"""What a valley contains, as plain data rather than as code.

`worldgen.py` used to hold the farm, the town and the cave at literal
coordinates. That made "add a village" a surgical edit in the middle of the
generator. This module pulls the *what* out of the *how*: a layout is a list of
places, each with a kind, a rough zone to sit in, and a size. The generator
reads the layout and does the same work it always did -- find ground, lay the
place, wire the paths -- for whatever the layout names.

The point is portability. The valley today is a single fixed-size map. A later
open-world or chunked generator is a different layout plus a different placement
strategy in `worldgen.place_in_zone` -- nothing in the renderer, the save format
or the frontend has to know the map got bigger or infinite, because all three
already depend only on the seed, the width, the height and the regions dict.

A "zone" is (fx, fy, fw, fh) as fractions of the world, so a layout is
resolution-independent: the same spec lays out a 128x96 valley and a 512x512
one. "size" is in tiles.
"""

# Kinds the generator knows how to lay. Adding a kind is a branch in
# worldgen._lay_place, not a new data shape here.
#
#   farm       the player's home plot: cleared grass, a worked patch, a fence
#              with a gate, and the player's house (you sleep inside it)
#   town       the largest settlement: a paved square, the market stall, a
#              well, and several houses with doors
#   village    a smaller settlement: a green with a well and a few houses
#   farmstead  one house, a small plot, a light fence -- a single family out in
#              the valley
#   cave       the mouth of the wilds, cut into the northern cliffs

DEFAULT_LAYOUT = {
    "size": (128, 96),
    "places": [
        # name        kind         zone (fx, fy, fw, fh)          size (w, h)
        {
            "name": "farm",
            "kind": "farm",
            "zone": (0.03, 0.54, 0.36, 0.42),
            "size": (22, 16),
        },
        {
            "name": "town",
            "kind": "town",
            "zone": (0.58, 0.48, 0.40, 0.44),
            "size": (28, 21),
        },
        {
            "name": "village",
            "kind": "village",
            "zone": (0.04, 0.06, 0.34, 0.34),
            "size": (19, 16),
        },
        {
            "name": "farmstead-north",
            "kind": "farmstead",
            "zone": (0.60, 0.05, 0.34, 0.28),
            "size": (11, 10),
        },
        {
            "name": "farmstead-east",
            "kind": "farmstead",
            "zone": (0.66, 0.30, 0.30, 0.24),
            "size": (11, 10),
        },
        {
            "name": "cave",
            "kind": "cave",
            "zone": (0.40, 0.0, 0.24, 0.10),
            "size": (6, 4),
        },
    ],
}

# The settlements and farmsteads, in the order the path network should prefer to
# string them together. The generator connects the farm to the nearest place and
# builds out from there, but this hints the trunk road.
TRUNK_ORDER = ("farm", "town", "village", "cave")


def settlement_names(layout=DEFAULT_LAYOUT):
    return [p["name"] for p in layout["places"] if p["kind"] != "cave"]


def places_of_kind(kind, layout=DEFAULT_LAYOUT):
    return [p for p in layout["places"] if p["kind"] == kind]
