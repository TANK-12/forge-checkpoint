"""House interiors: the little map you get when you walk through a door.

The indoor counterpart to `wilds.py`, and built the same way -- a `worldgen.World`
with a flag set (`is_interior`), generated deterministically and never stored. A
run through the wilds is not worth saving because it regenerates; a house
interior is not worth saving because its furniture is fixed by the building it
belongs to. Both come back identical from the same inputs.

An interior is a walled room of `wood_floor` with `interior_wall` around the
edge, a `door_mat` at the entrance carrying `use: "exit"`, and furniture chosen
by the building's kind. The player's house has the bed -- session 2's bed moved
indoors here -- and a marked corner the crafting session will fill. Every other
house is a bed, a table and a rug, and (from session 5's NPC layer) home to the
villager whose `home` names it.

Determinism comes from the building id plus the valley seed, so the same house
in the same save is always the same room.
"""

from . import worldgen

# Room size by building kind. Small on purpose: an interior is a place to do one
# or two things, not a second valley.
ROOMS = {
    "player": (15, 11),
    "town": (13, 9),
    "village": (13, 9),
    "farmstead": (13, 9),
}
DEFAULT_ROOM = (13, 9)


def _seed_for(building_id, valley_seed):
    h = 2166136261
    for ch in str(building_id):
        h = (h ^ ord(ch)) * 16777619 & 0xFFFFFFFF
    return (valley_seed * 2654435761 + h) & 0x7FFFFFFF


def _kind_of(building_id):
    for kind in ("player", "town", "village", "farmstead"):
        if kind in building_id:
            return kind
    return "town"


def generate(building_id, valley_seed):
    """Build one house interior. Returns a worldgen.World with is_interior set."""
    kind = _kind_of(building_id)
    w, h = ROOMS.get(kind, DEFAULT_ROOM)
    seed = _seed_for(building_id, valley_seed)
    world = worldgen.World(seed, w, h)
    world.is_interior = True

    for y in range(h):
        for x in range(w):
            edge = x == 0 or y == 0 or x == w - 1 or y == h - 1
            world.tiles[y][x] = "interior_wall" if edge else "wood_floor"

    # The way out: a mat on the bottom wall, and you spawn just above it.
    door_x = w // 2
    world.tiles[h - 1][door_x] = "wood_floor"
    world.objects.append(
        {
            "sprite": "door_mat",
            "x": door_x,
            "y": h - 1,
            "solid": False,
            "w": 1,
            "h": 1,
            "use": "exit",
        }
    )
    world.spawn = (door_x, h - 2)
    world.regions["exit"] = [door_x, h - 2]

    _furnish(world, kind)
    world.rebuild_collision()
    return world


def _bed(world, x, y, sleepable):
    obj = {
        "sprite": "bed",
        "x": x,
        "y": y,
        "solid": True,
        "w": 2,
        "h": 2,
        "hit": [1.7, 1.4],
    }
    # Only the player's own bed ends a day. A villager's bed is there for the
    # look of the room -- pressing space on it does nothing.
    if sleepable:
        obj["use"] = "sleep"
    world.objects.append(obj)
    world.regions["bed"] = [x, y]


def _prop(world, sprite, x, y, hit):
    world.objects.append(
        {
            "sprite": sprite,
            "x": x,
            "y": y,
            "solid": True,
            "w": 1,
            "h": 1,
            "hit": list(hit),
        }
    )


def _station(world, sprite, x, y, use, hit):
    """A prop you interact with: the hearth (station 'cook') or the workbench
    (station 'craft'). The crafting screen filters recipes by the station name
    the object carries."""
    world.objects.append(
        {
            "sprite": sprite,
            "x": x,
            "y": y,
            "solid": True,
            "w": 1,
            "h": 1,
            "hit": list(hit),
            "use": use,
            "station": "cook" if use == "cook" else "workbench",
        }
    )


def _furnish(world, kind):
    w, h = world.width, world.height
    # Rug in the middle of the floor -- decor, never solid.
    world.objects.append(
        {"sprite": "rug", "x": w // 2, "y": h - 3, "solid": False, "w": 1, "h": 1}
    )
    _bed(world, 2, 2, sleepable=(kind == "player"))

    if kind == "player":
        # The hearth cooks, the workbench crafts, the chest stores. These three
        # are the whole of session 6's crafting loop; the chest is the first
        # interior state a save carries.
        _station(world, "hearth", w - 3, 1, "cook", (0.9, 0.6))
        _station(world, "workbench", 2, h - 2, "craft", (0.9, 0.7))
        world.objects.append(
            {
                "sprite": "chest",
                "x": 4,
                "y": h - 2,
                "solid": True,
                "w": 1,
                "h": 1,
                "hit": [0.8, 0.7],
                "use": "storage",
            }
        )
        world.regions["storage_spot"] = [2, h - 2]
    else:
        _prop(world, "hearth", w - 3, 1, (0.9, 0.6))
        _prop(world, "table", w - 3, h - 3, (0.9, 0.7))

    world.objects.sort(key=lambda o: (o["y"], o["x"]))
