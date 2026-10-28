"""The valley: one seeded, persistent map per save.

Design intent, because the shape of this file follows from it. The valley is
the part of Emberfield that is meant to become familiar -- the farm you learn,
the town you walk through daily, the cave mouth you come to dread. So it is
generated once from the save's seed and then kept, and later sessions mutate it
through events rather than regenerating it. The wilds beyond, which regenerate
every day/night cycle and get harder after dark, are a separate generator and
deliberately not this one.

Session 5 moved the *what* of a valley into `layout.py`: this file no longer
hardcodes the farm, the town or the cave at literal coordinates. It reads a
layout -- a list of places, each with a kind, a zone and a size -- finds good
ground for each, lays it, and wires a path network between them. Adding a
village was a line in the layout and a `kind` branch here; a future open-world
generator is a different layout plus a different `place_in_zone`.

Everything here is stdlib and deterministic: the same seed must always give the
same valley, or a save cannot be reloaded. That property is tested.
"""

import random

from . import layout as _layout

# Tile ids are sprite names in the shared art library. Keeping them identical
# means adding a terrain type is a sprite plus a line in TILES -- no third
# mapping table to keep in sync.
TILES = {
    "grass_a": {"solid": False, "kind": "grass"},
    "grass_b": {"solid": False, "kind": "grass"},
    "grass_c": {"solid": False, "kind": "grass"},
    "grass_d": {"solid": False, "kind": "grass"},
    "soil": {"solid": False, "kind": "soil"},
    "path": {"solid": False, "kind": "path"},
    "sand": {"solid": False, "kind": "sand"},
    "stone_floor": {"solid": False, "kind": "stone"},
    "tilled": {"solid": False, "kind": "farm"},
    "tilled_wet": {"solid": False, "kind": "farm"},
    "water": {"solid": True, "kind": "water"},
    "cliff_face": {"solid": True, "kind": "cliff"},
    # The wilds' walls. Separate from cliff_face because that tile is drawn as a
    # cliff *face*, with horizontal strata -- fine as the edge of the valley,
    # wallpaper when a whole cavern is made of it.
    "cave_wall_a": {"solid": True, "kind": "rock"},
    "cave_wall_b": {"solid": True, "kind": "rock"},
    "cave_wall_c": {"solid": True, "kind": "rock"},
    # Interiors (session 5). A house you walk into is its own little map, and
    # these are what it is made of. wood_floor is walkable; interior_wall is the
    # room's edge and is solid.
    "wood_floor": {"solid": False, "kind": "wood"},
    "interior_wall": {"solid": True, "kind": "wall"},
    "rug": {"solid": False, "kind": "wood"},
}

GRASS_VARIANTS = ("grass_a", "grass_b", "grass_c", "grass_d")

WIDTH, HEIGHT = _layout.DEFAULT_LAYOUT["size"]


# --- noise -----------------------------------------------------------------


def _value_noise(rng, w, h, cells):
    """Bilinear-interpolated value noise. Small, stdlib-only, and smooth enough
    for coastlines and moisture; a full Perlin implementation would not change
    how the result reads at this tile size."""
    gw, gh = cells + 1, cells + 1
    grid = [[rng.random() for _ in range(gw)] for _ in range(gh)]
    out = []
    for y in range(h):
        gy = y / h * cells
        y0 = int(gy)
        ty = gy - y0
        y1 = min(y0 + 1, gh - 1)
        row = []
        for x in range(w):
            gx = x / w * cells
            x0 = int(gx)
            tx = gx - x0
            x1 = min(x0 + 1, gw - 1)
            top = grid[y0][x0] * (1 - tx) + grid[y0][x1] * tx
            bottom = grid[y1][x0] * (1 - tx) + grid[y1][x1] * tx
            row.append(top * (1 - ty) + bottom * ty)
        out.append(row)
    return out


def _octaves(rng, w, h, cells, count=3):
    field = [[0.0] * w for _ in range(h)]
    amplitude, total = 1.0, 0.0
    for octave in range(count):
        layer = _value_noise(rng, w, h, cells * (2**octave))
        for y in range(h):
            for x in range(w):
                field[y][x] += layer[y][x] * amplitude
        total += amplitude
        amplitude *= 0.5
    for y in range(h):
        for x in range(w):
            field[y][x] /= total
    return field


# --- regions ---------------------------------------------------------------


class World:
    """A generated valley. Plain data: the renderer and the save file both
    consume this, and nothing here knows about either."""

    def __init__(self, seed, width, height):
        self.seed = seed
        self.width = width
        self.height = height
        self.tiles = [["grass_b"] * width for _ in range(height)]
        self.objects = []
        self.regions = {}
        self.spawn = (width // 2, height // 2)
        # Which kind of map this is. The valley, the wilds and a house interior
        # all share this class deliberately -- the renderer, the collision code
        # and the save format all treat them identically -- so the one thing
        # that differs travels as a flag rather than as a second class.
        self.is_wilds = False
        self.is_interior = False
        # Filled by generate() once objects exist. Declared here so solid_at()
        # works on a World built directly, e.g. by a test or a loaded save.
        self._blocked = set()

    def in_bounds(self, x, y):
        return 0 <= x < self.width and 0 <= y < self.height

    def tile(self, x, y):
        if not self.in_bounds(x, y):
            return "cliff_face"
        return self.tiles[y][x]

    def set_tile(self, x, y, tile):
        if self.in_bounds(x, y):
            self.tiles[y][x] = tile

    def solid_at(self, x, y):
        if not self.in_bounds(x, y):
            return True
        if TILES.get(self.tiles[y][x], {}).get("solid"):
            return True
        return (x, y) in self._blocked

    def rebuild_collision(self):
        """Recompute which tiles objects block. Called after generation and
        after anything adds or removes an object."""
        self._blocked = blocked_tiles(self.objects)
        return self._blocked

    def to_dict(self):
        return {
            "seed": self.seed,
            "width": self.width,
            "height": self.height,
            "tiles": ["\t".join(row) for row in self.tiles],
            "objects": self.objects,
            "regions": self.regions,
            "spawn": list(self.spawn),
            "is_wilds": self.is_wilds,
            "is_interior": self.is_interior,
        }


def _rect(world, x0, y0, x1, y1, tile):
    for y in range(max(0, y0), min(world.height, y1)):
        for x in range(max(0, x0), min(world.width, x1)):
            world.set_tile(x, y, tile)


def _carve_path(world, start, end, rng, tile="path", width=2):
    """An L-shaped, slightly wandering path.

    Paths are carved *after* terrain and *before* scatter, which is what
    guarantees the farm, town and cave are mutually reachable by construction
    rather than by luck -- the reachability test exists to keep that true.
    """
    x, y = start
    ex, ey = end
    cells = []
    while x != ex or y != ey:
        cells.append((x, y))
        if x != ex and (y == ey or rng.random() < 0.62):
            x += 1 if ex > x else -1
        else:
            y += 1 if ey > y else -1
    cells.append((ex, ey))
    for cx, cy in cells:
        for dy in range(width):
            for dx in range(width):
                px, py = cx + dx - width // 2, cy + dy - width // 2
                if world.in_bounds(px, py):
                    # Carve unconditionally, water and cliff included: a road
                    # that stops at the shoreline is not a road. Skipping those
                    # tiles left the route discontinuous, which stayed invisible
                    # only until the farm got a fence and sealed the last way
                    # out. Where the road meets water this reads as a ford;
                    # where it meets the cliffs, as a cut.
                    world.set_tile(px, py, tile)
    return cells


# --- placement -----------------------------------------------------------


def place_in_zone(world, elevation, moisture, zone, size, rng):
    """Where in a zone a place of the given footprint should sit.

    The zone is (fx, fy, fw, fh) as fractions of the world; the search is over
    top-left corners inside it. Each candidate is scored on flatness (the
    elevation should not vary much under a settlement) and dryness (nobody
    builds a town square in a marsh), and cliff or water anywhere under the
    footprint disqualifies it outright. Falls back to the zone's centre so a
    layout can never fail to place something.

    This is the one function an open-world port would replace: the layout says
    *what* and *roughly where*, this decides the exact tile, and everything
    downstream only ever reads world.regions.
    """
    fw_x = int(zone[0] * world.width)
    fw_y = int(zone[1] * world.height)
    zw = max(size[0] + 2, int(zone[2] * world.width))
    zh = max(size[1] + 2, int(zone[3] * world.height))
    w, h = size
    x_lo = max(1, fw_x)
    y_lo = max(1, fw_y)
    x_hi = min(world.width - w - 1, fw_x + zw - w)
    y_hi = min(world.height - h - 1, fw_y + zh - h)
    if x_hi < x_lo:
        x_hi = x_lo
    if y_hi < y_lo:
        y_hi = y_lo

    best = None
    best_score = -1e18
    step = 2
    for oy in range(y_lo, y_hi + 1, step):
        for ox in range(x_lo, x_hi + 1, step):
            elev = []
            wet = []
            rough = 0  # water and cliff tiles under the footprint
            for y in range(oy, oy + h):
                for x in range(ox, ox + w):
                    if world.tiles[y][x] in ("water", "cliff_face"):
                        rough += 1
                    elev.append(elevation[y][x])
                    wet.append(moisture[y][x])
            mean_e = sum(elev) / len(elev)
            var_e = sum((e - mean_e) ** 2 for e in elev) / len(elev)
            mean_w = sum(wet) / len(wet)
            # Rough tiles dominate: a pad with any water or cliff under it is
            # far worse than a merely uneven one. But it is still scored rather
            # than rejected, so the fall-back is the least-bad pad, not the
            # geometric centre of a marsh.
            score = -rough * 1000 - var_e * 40 - mean_w * 3.0
            if score > best_score:
                best_score = score
                best = (ox, oy)

    if best is None:
        best = (
            max(1, min(world.width - w - 1, fw_x + (zw - w) // 2)),
            max(1, min(world.height - h - 1, fw_y + (zh - h) // 2)),
        )
    return best


def _region_centre(r):
    return (r["x"] + r["w"] // 2, r["y"] + r["h"] // 2)


def _mst_edges(points):
    """A minimum spanning tree over (name, (x, y)) points, by tile distance.

    Prim's, small enough that anything cleverer would be showing off. The path
    network follows this so every settlement is connected with the least total
    road, and reachability holds by construction.
    """
    names = [p[0] for p in points]
    coords = {p[0]: p[1] for p in points}
    if len(names) < 2:
        return []
    inside = {names[0]}
    edges = []
    while len(inside) < len(names):
        best = None
        for a in inside:
            for b in names:
                if b in inside:
                    continue
                ax, ay = coords[a]
                bx, by = coords[b]
                d = abs(ax - bx) + abs(ay - by)
                if best is None or d < best[0]:
                    best = (d, a, b)
        assert best is not None  # a spanning tree always has a next edge
        edges.append((best[1], best[2]))
        inside.add(best[2])
    return edges


def generate(seed, width=None, height=None, layout=None):
    """Build the valley. Deterministic for a given seed."""
    layout = layout or _layout.DEFAULT_LAYOUT
    if width is None or height is None:
        width, height = layout["size"]
    rng = random.Random(seed)
    world = World(seed, width, height)

    elevation = _octaves(rng, width, height, 4, 3)
    moisture = _octaves(rng, width, height, 3, 2)

    # Terrain. The south-west is low and wet, so the shore lands there; the
    # north is high, which is where the cliffs and the cave mouth belong.
    for y in range(height):
        for x in range(width):
            north = 1.0 - (y / height)
            west = 1.0 - (x / width)
            e = elevation[y][x] * 0.62 + north * 0.38
            wetness = moisture[y][x] * 0.55 + west * 0.25 + (y / height) * 0.20
            if e > 0.74:
                tile = "cliff_face"
            elif wetness > 0.70:
                tile = "water"
            elif wetness > 0.645:
                tile = "sand"
            elif e > 0.63:
                tile = "stone_floor"
            else:
                tile = GRASS_VARIANTS[rng.randrange(len(GRASS_VARIANTS))]
            world.tiles[y][x] = tile

    # Place every layout entry on good ground, record its region, and lay it.
    specs = {p["name"]: p for p in layout["places"]}
    for spec in layout["places"]:
        ox, oy = place_in_zone(
            world, elevation, moisture, spec["zone"], spec["size"], rng
        )
        w, h = spec["size"]
        world.regions[spec["name"]] = {"x": ox, "y": oy, "w": w, "h": h}

    world.regions["buildings"] = []
    for spec in layout["places"]:
        _lay_place(world, spec, world.regions[spec["name"]], rng)

    # A gateway for each place: a guaranteed-walkable tile near its centre that
    # the path network can start and end on. The geometric centre may sit under
    # a well or a stall, and a road that ends inside a solid object is a road
    # that goes nowhere. The centre is still recorded for the HUD and the
    # reachability tests use the gateway.
    world.rebuild_collision()
    gates = {}
    for name, r in list(world.regions.items()):
        if isinstance(r, dict) and "w" in r:
            gx, gy = _walkable_near(world, *_region_centre(r))
            gates[name] = (gx, gy)
            world.regions[name + "_centre"] = [gx, gy]

    cave = world.regions["cave"]
    cave_mouth = (cave["x"] + cave["w"] // 2, cave["y"] + cave["h"] - 1)
    world.regions["cave_mouth"] = list(cave_mouth)
    gates["cave"] = cave_mouth

    points = [(name, gates[name]) for name in gates]
    for a, b in _mst_edges(points):
        _carve_path(world, gates[a], gates[b], rng)

    # The farm's fence goes on *after* the roads, so it can leave a gate exactly
    # where a road crosses the boundary. Fencing during _lay_farm sealed the
    # farm in before any road existed.
    _fence_the_farm(world, world.regions["farm"])

    world.rebuild_collision()
    world.spawn = _walkable_near(world, *gates["farm"])

    _scatter(world, rng)
    world.rebuild_collision()
    return world


def _walkable_near(world, x, y, radius=8):
    """The nearest non-solid tile to (x, y), spiralling out. Falls back to
    (x, y) so this never returns nothing."""
    if not world.solid_at(x, y):
        return (x, y)
    for r in range(1, radius + 1):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                nx, ny = x + dx, y + dy
                if world.in_bounds(nx, ny) and not world.solid_at(nx, ny):
                    return (nx, ny)
    return (x, y)


# --- laying a place ----------------------------------------------------


def _lay_place(world, spec, region, rng):
    kind = spec["kind"]
    if kind == "farm":
        _lay_farm(world, region, rng)
        _place_player_house(world, region)
    elif kind == "town":
        _lay_town(world, region, rng)
        _lay_settlement_buildings(world, spec, region, rng, count=5, kind="town")
        _place_well(world, region)
        _place_stall(world, region)
    elif kind == "village":
        _lay_town(world, region, rng)
        _lay_settlement_buildings(world, spec, region, rng, count=4, kind="village")
        _place_well(world, region)
    elif kind == "farmstead":
        _lay_farmstead(world, spec, region, rng)
    elif kind == "cave":
        _rect(
            world,
            region["x"],
            region["y"],
            region["x"] + region["w"],
            region["y"] + region["h"],
            "stone_floor",
        )


# Where the door tile of a house sits: one tile south of the sprite's bottom
# row, so a solid house never blocks its own doorway. Interiors are entered by
# pressing space on this tile.
HOUSE_W, HOUSE_H = 3, 3
HOUSE_HIT = (2.7, 2.5)


def _house_object(building_id, kind, x, y):
    return {
        "sprite": {
            "player": "house_player",
            "town": "house_town",
            "village": "house_village",
            "farmstead": "house_farmstead",
        }.get(kind, "house_town"),
        "x": x,
        "y": y,
        "solid": True,
        "w": HOUSE_W,
        "h": HOUSE_H,
        "hit": list(HOUSE_HIT),
        "use": "door",
        "building": building_id,
        "door": [x + HOUSE_W // 2, y + 1],
    }


def _register_building(world, obj, kind, settlement):
    world.regions["buildings"].append(
        {
            "id": obj["building"],
            "kind": kind,
            "sprite": obj["sprite"],
            "x": obj["x"],
            "y": obj["y"],
            "w": obj["w"],
            "h": obj["h"],
            "door": list(obj["door"]),
            "settlement": settlement,
        }
    )


def _place_player_house(world, farm):
    """The player's farmhouse, north-west of the worked plot.

    Replaces session 2's bare bed. Sleeping is how a day ends and how crops
    grow, so it has to happen at a place -- and now that place is a room you
    walk into. The bed lives in the interior (`interiors.py`); out here this is
    a solid building with a door tile you press space on.
    """
    plot = farm["plot"]
    x = max(farm["x"] + 1, plot["x"] - 5)
    y = plot["y"] + 1
    x = min(x, farm["x"] + farm["w"] - HOUSE_W - 1)
    for tile_x in range(x, x + HOUSE_W):
        world.set_tile(tile_x, y + 1, "path")  # a doorstep, kept clear
    obj = _house_object("emberfield-house-player", "player", x, y)
    world.objects.append(obj)
    _register_building(world, obj, "player", "farm")
    world.regions["house"] = list(obj["door"])


def _place_stall(world, town):
    """A market stall in the town square.

    Its stock is not decided here -- it sells whatever items in the content
    store carry a buy price above zero, so stocking something new is a number on
    an item file.
    """
    x = town["x"] + town["w"] // 2 - 1
    y = town["y"] + 3
    for tile_x in range(x - 1, x + 3):
        for tile_y in range(y - 1, y + 2):
            if world.tile(tile_x, tile_y) not in ("water", "cliff_face"):
                world.set_tile(tile_x, tile_y, "path")
    world.objects.append(
        {
            "sprite": "stall",
            "x": x,
            "y": y,
            "solid": True,
            "w": 2,
            "h": 2,
            "hit": [1.9, 0.9],
            "use": "shop",
        }
    )
    world.regions["stall"] = [x, y]


def _place_well(world, region):
    """A well at a settlement's centre. Somewhere for a schedule to send people,
    and the thing that reads as 'this is the square' from across the map."""
    cx, cy = _region_centre(region)
    for tile_x in range(cx - 1, cx + 2):
        for tile_y in range(cy - 1, cy + 2):
            if world.tile(tile_x, tile_y) not in ("water", "cliff_face"):
                world.set_tile(tile_x, tile_y, "stone_floor")
    world.objects.append(
        {
            "sprite": "well",
            "x": cx,
            "y": cy,
            "solid": True,
            "w": 2,
            "h": 2,
            "hit": [1.5, 1.3],
            # A deliberate fixture, like the stall and the bed: it stands at the
            # centre of a paved square on purpose, so the scatter test exempts it.
            "fixture": True,
        }
    )
    region.setdefault("props", []).append(["well", cx, cy])


def _lay_settlement_buildings(world, spec, region, rng, count, kind):
    """Drop `count` houses around the inside edge of a settlement, spaced out,
    each with a door onto the paving and an interior id the frontend can enter.
    """
    slots = []
    inset = 1
    y_top = region["y"] + inset + HOUSE_H
    y_bot = region["y"] + region["h"] - inset - 2
    for x in range(region["x"] + inset, region["x"] + region["w"] - HOUSE_W - inset, 5):
        slots.append((x, y_top))
        slots.append((x, y_bot))
    rng.shuffle(slots)

    placed = 0
    used = []
    for x, y in slots:
        if placed >= count:
            break
        if any(
            abs(x - ux) < HOUSE_W + 2 and abs(y - uy) < HOUSE_H + 2 for ux, uy in used
        ):
            continue
        footprint_ok = all(
            world.in_bounds(x + dx, y - dy)
            and world.tile(x + dx, y - dy) not in ("water", "cliff_face")
            for dx in range(HOUSE_W)
            for dy in range(HOUSE_H)
        )
        if not footprint_ok:
            continue
        bid = f"emberfield-house-{spec['name']}-{placed + 1}"
        obj = _house_object(bid, kind, x, y)
        # Pave the doorstep so the door is always reachable from the square.
        world.set_tile(obj["door"][0], obj["door"][1], "path")
        world.objects.append(obj)
        _register_building(world, obj, kind, spec["name"])
        used.append((x, y))
        placed += 1


def _drain(world, region, ground):
    """Turn every water or cliff tile inside a region into its ground tile.

    A homestead is cleared land: if the placement search could not find a pad
    entirely clear of the shoreline or the cliffs, the few intruding tiles are
    filled rather than left to wall the plot off from its own gate. Called by
    every settlement layer before it does anything else.
    """
    for y in range(region["y"], region["y"] + region["h"]):
        for x in range(region["x"], region["x"] + region["w"]):
            if world.tile(x, y) in ("water", "cliff_face"):
                world.set_tile(x, y, ground)


def _lay_farm(world, farm, rng):
    """The farm is cleared grass with a worked plot in it, not a slab of soil."""
    _drain(world, farm, "grass_b")
    for y in range(farm["y"], farm["y"] + farm["h"]):
        for x in range(farm["x"], farm["x"] + farm["w"]):
            world.set_tile(x, y, GRASS_VARIANTS[rng.randrange(len(GRASS_VARIANTS))])

    plot_w, plot_h = 8, 6
    px = farm["x"] + (farm["w"] - plot_w) // 2
    py = farm["y"] + (farm["h"] - plot_h) // 2
    for y in range(py, py + plot_h):
        for x in range(px, px + plot_w):
            world.set_tile(x, y, "tilled" if rng.random() > 0.18 else "soil")

    farm["plot"] = {"x": px, "y": py, "w": plot_w, "h": plot_h}


def _lay_farmstead(world, spec, farmstead, rng):
    """One family, out in the valley: a house and a small worked patch. A
    miniature of the player's farm, and home to one NPC."""
    _drain(world, farmstead, "grass_b")
    for y in range(farmstead["y"], farmstead["y"] + farmstead["h"]):
        for x in range(farmstead["x"], farmstead["x"] + farmstead["w"]):
            world.set_tile(x, y, GRASS_VARIANTS[rng.randrange(len(GRASS_VARIANTS))])

    hx = farmstead["x"] + 1
    hy = farmstead["y"] + HOUSE_H
    bid = f"emberfield-house-{spec['name']}"
    obj = _house_object(bid, "farmstead", hx, hy)
    world.set_tile(obj["door"][0], obj["door"][1], "path")
    world.objects.append(obj)
    _register_building(world, obj, "farmstead", spec["name"])

    plot_w, plot_h = 4, 3
    px = farmstead["x"] + farmstead["w"] - plot_w - 1
    py = farmstead["y"] + farmstead["h"] - plot_h - 1
    for y in range(py, py + plot_h):
        for x in range(px, px + plot_w):
            world.set_tile(x, y, "tilled" if rng.random() > 0.3 else "soil")
    farmstead["plot"] = {"x": px, "y": py, "w": plot_w, "h": plot_h}


def _lay_town(world, town, rng):
    """Paved streets broken up with stone, rather than one flat wash of path."""
    _drain(world, town, "path")
    for y in range(town["y"], town["y"] + town["h"]):
        for x in range(town["x"], town["x"] + town["w"]):
            world.set_tile(x, y, "stone_floor" if rng.random() > 0.82 else "path")


def _fence_the_farm(world, farm):
    """Post-and-rail around the farm, with the gate wherever the road reaches it.

    Placed after the paths are carved and before anything is scattered, so it
    can leave a gap exactly where the road meets the boundary. Enclosing the
    farm completely would cut the player off from the valley -- the
    reachability test is what keeps that from happening quietly.
    """
    x0, y0 = farm["x"] - 1, farm["y"] - 1
    x1, y1 = farm["x"] + farm["w"], farm["y"] + farm["h"]
    perimeter = []
    for x in range(x0, x1 + 1):
        perimeter += [(x, y0), (x, y1)]
    for y in range(y0 + 1, y1):
        perimeter += [(x0, y), (x1, y)]

    for x, y in perimeter:
        if not world.in_bounds(x, y):
            continue
        kind = TILES.get(world.tile(x, y), {}).get("kind")
        # Never fence across the road, or out over water and cliffs.
        if kind in ("path", "water", "cliff"):
            continue
        corner = x in (x0, x1) and y in (y0, y1)
        vertical = x in (x0, x1) and not corner
        sprite = (
            "fence_post" if corner else "fence_rail_v" if vertical else "fence_rail"
        )
        world.objects.append(
            {
                "sprite": sprite,
                "x": x,
                "y": y,
                "solid": True,
                "w": 1,
                "h": 1,
                "hit": list(FENCE_HITS[sprite]),
            }
        )


# Object footprints in tiles, used for placement and for drawing. An object is
# anchored at its bottom-centre tile, the way a tree stands on the ground rather
# than floating in the middle of its own sprite.
#
# "hit" is the collision shape, in tiles, and is deliberately NOT the footprint.
# A footprint says how much room the sprite needs; a hit box says what part of it
# your boots can actually walk into. An oak is three tiles tall and two wide, but
# only its trunk stops you -- treating the whole footprint as solid meant you
# collided with leaves two tiles above the ground and could never walk behind a
# tree. The box is anchored at the bottom-centre of the footprint and read as an
# ellipse, so you slide around a trunk's shoulder instead of catching on a
# square corner. Anything without a "hit" falls back to its base row.
OBJECTS = {
    "tree_oak": {"w": 2, "h": 3, "solid": True, "hit": (0.50, 0.34), "on": ("grass",)},
    "bush": {"w": 1, "h": 1, "solid": True, "hit": (0.72, 0.46), "on": ("grass",)},
    "rock_small": {
        "w": 1,
        "h": 1,
        "solid": True,
        "hit": (0.66, 0.44),
        "on": ("grass", "stone", "sand"),
    },
    "rock_large": {
        "w": 2,
        "h": 2,
        "solid": True,
        "hit": (1.40, 0.72),
        "on": ("stone", "grass"),
    },
    "stump": {"w": 1, "h": 1, "solid": True, "hit": (0.62, 0.40), "on": ("grass",)},
    "flowers_red": {"w": 1, "h": 1, "solid": False, "on": ("grass",)},
    "flowers_yellow": {"w": 1, "h": 1, "solid": False, "on": ("grass",)},
    "flowers_white": {"w": 1, "h": 1, "solid": False, "on": ("grass",)},
}

# The fence is post-and-rail, so its collision follows the rail rather than the
# tile: you should be able to stand close enough to lean on it.
FENCE_HITS = {
    "fence_post": (0.46, 0.46),
    "fence_rail": (1.00, 0.34),
    "fence_rail_v": (0.34, 1.00),
}

DEFAULT_HIT = (1.0, 1.0)


def hit_ellipse(obj):
    """The collision ellipse of a placed object, in tile units.

    Returns (cx, cy, rx, ry). Anchored at the bottom-centre of the footprint,
    which is where the object meets the ground -- the same anchor the renderer
    draws from, so what you see is what you bump into.
    """
    hw, hh = obj.get("hit") or DEFAULT_HIT
    cx = obj["x"] + obj.get("w", 1) / 2.0
    cy = (obj["y"] + 1) - hh / 2.0
    return cx, cy, hw / 2.0, hh / 2.0


def blocked_tiles(objects):
    """Every tile any solid object's ellipse touches at all.

    Overlap, not centre-containment: a two-tile-wide oak has its trunk on the
    seam between two tiles, so no tile centre falls inside a half-tile-wide
    ellipse and centre-testing would report the tree as thin air. Overlap
    testing is slightly stricter than the game's own pixel check, which is the
    safe direction -- if the reachability sweep finds a route under these
    rules, the player can certainly walk it.
    """
    blocked = set()
    for obj in objects:
        if not obj.get("solid"):
            continue
        cx, cy, rx, ry = hit_ellipse(obj)
        for ty in range(int(cy - ry), int(cy + ry) + 1):
            for tx in range(int(cx - rx), int(cx + rx) + 1):
                if (
                    cx + rx > tx
                    and cx - rx < tx + 1
                    and cy + ry > ty
                    and cy - ry < ty + 1
                ):
                    blocked.add((tx, ty))
    return blocked


# Weighted so the valley reads as woodland with clearings rather than an even
# sprinkle of everything.
SCATTER = [
    ("tree_oak", 34),
    ("bush", 16),
    ("rock_small", 12),
    ("rock_large", 4),
    ("stump", 4),
    ("flowers_red", 10),
    ("flowers_yellow", 10),
    ("flowers_white", 10),
]


def _clear_of_regions(world, x, y, margin=1):
    """True if (x, y) is clear of every laid region -- the farm, the settlements,
    the farmsteads and the cave. Iterates the regions dict rather than a fixed
    list, so a new place in the layout is protected from the scatter for free.
    """
    for name, r in world.regions.items():
        if not isinstance(r, dict) or "w" not in r:
            continue
        if (
            r["x"] - margin <= x < r["x"] + r["w"] + margin
            and r["y"] - margin <= y < r["y"] + r["h"] + margin
        ):
            return False
    return True


def _scatter(world, rng, density=0.09):
    """Place objects on ground that suits them, never on a path or in a region.

    Paths are excluded explicitly: a tree in the middle of the road would break
    the connectivity the carve step just guaranteed.
    """
    names = [n for n, _ in SCATTER]
    weights = [w for _, w in SCATTER]
    taken = {(o["x"], o["y"]) for o in world.objects}
    attempts = int(world.width * world.height * density * 2)
    for _ in range(attempts):
        x = rng.randrange(1, world.width - 2)
        y = rng.randrange(2, world.height - 2)
        if not _clear_of_regions(world, x, y):
            continue
        name = rng.choices(names, weights)[0]
        spec = OBJECTS[name]
        kind = TILES.get(world.tile(x, y), {}).get("kind")
        if kind not in spec["on"]:
            continue
        footprint = [
            (x + dx, y - dy) for dx in range(spec["w"]) for dy in range(spec["h"])
        ]
        if any(p in taken for p in footprint):
            continue
        if any(
            TILES.get(world.tile(px, py), {}).get("kind") == "path"
            for px, py in footprint
        ):
            continue
        if any(world.tile(px, py) == "water" for px, py in footprint):
            continue
        taken.update(footprint)
        placed = {
            "sprite": name,
            "x": x,
            "y": y,
            "solid": spec["solid"],
            "w": spec["w"],
            "h": spec["h"],
        }
        if spec.get("hit"):
            placed["hit"] = list(spec["hit"])
        world.objects.append(placed)
    world.objects.sort(key=lambda o: (o["y"], o["x"]))


def bfs_path(world, start, goal):
    """A shortest tile path from start to goal over non-solid tiles, or None.

    Promoted out of `reachable()` in session 5 because the NPC walk needs it
    too: greedily walking toward a target and sliding along walls wedges a
    villager behind the first tree between them, where a path that goes round
    does not. Cheap on a valley this size, and NPCs recompute it only when their
    schedule stop changes.
    """
    from collections import deque

    solid_objects = blocked_tiles(world.objects)

    def blocked(x, y):
        if not world.in_bounds(x, y):
            return True
        if TILES.get(world.tiles[y][x], {}).get("solid"):
            return True
        return (x, y) in solid_objects

    start = tuple(start)
    goal = tuple(goal)
    if blocked(*start) or blocked(*goal):
        return None
    prev: dict = {start: None}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        if cur == goal:
            path = []
            while cur is not None:
                path.append(list(cur))
                cur = prev[cur]
            return path[::-1]
        x, y = cur
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (x + dx, y + dy)
            if nxt not in prev and not blocked(*nxt):
                prev[nxt] = cur
                queue.append(nxt)
    return None


def reachable(world, start, goal):
    """Breadth-first walk over non-solid tiles. Used by the tests to prove the
    farm, town and cave are always connected, which is the one property a
    generated valley must never get wrong."""
    return bfs_path(world, start, goal) is not None
