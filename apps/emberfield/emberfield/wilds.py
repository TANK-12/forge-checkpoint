"""The wilds: a fresh cavern every day/night cycle, harder after dark.

The counterpart to worldgen.py, and deliberately the opposite of it. The valley
is generated once per save and then kept, because it is the place that is meant
to become familiar. The wilds are meant to stay unfamiliar: they are regenerated
from the valley's seed *plus the day and whether it is night*, so the same save
gives you a different cavern every cycle, and the night version of any given day
is a harder map than its daytime one.

That seeding is the whole design in one line:

    seed = valley_seed * 7919 + day * 131 + (1 if night else 0)

It means the wilds are still completely deterministic -- a save reloaded on day
six at night gets the same cavern it had -- while never being the same place
twice in a row. Nothing about a run through the wilds needs storing.

The shape is a cellular-automata cave. That algorithm is a cliche for good
reason: it is a dozen lines of stdlib, it produces chambers joined by passages
rather than corridors joined by rooms, and it reads as *carved* rather than
*built*, which is the difference between this and the town.
"""

import random
from collections import deque

from . import worldgen

WIDTH, HEIGHT = 72, 56

# How the cavern gets meaner. Day and night are two different maps, not one map
# with a multiplier, but the numbers that drive them live here so the difficulty
# curve is one thing to read and one thing to tune.
DANGER = {
    "day": {"fill": 0.44, "smooth": 4, "foes": 6, "foe_bonus": 0.5, "pools": 2},
    "night": {"fill": 0.47, "smooth": 3, "foes": 11, "foe_bonus": 1.0, "pools": 4},
}


def seed_for(valley_seed, day, night):
    """The cavern's seed. Deterministic, so a reloaded save gets the cavern it
    had, and distinct per cycle, so it is never the same place twice running."""
    return (int(valley_seed) * 7919 + int(day) * 131 + (1 if night else 0)) % 2**31


WALLS = ("cave_wall_a", "cave_wall_b", "cave_wall_c")


def _wall(x, y):
    """Which wall variant sits at a cell.

    Chosen by position rather than at random so it is stable: the same cell is
    always the same stone, which matters because the ground is baked once and a
    wall that changed between bakes would shimmer.
    """
    return WALLS[(x * 7 + y * 13) % len(WALLS)]


def _carve(rng, width, height, fill, smooth):
    """Cellular-automata cave. True means solid rock.

    Starts as noise with a solid border, then repeatedly replaces each cell with
    whatever most of its neighbours are. Rock clumps into walls, space clumps
    into chambers, and the result is a cavern rather than a maze.
    """
    grid = [
        [
            (
                True
                if (x == 0 or y == 0 or x == width - 1 or y == height - 1)
                else rng.random() < fill
            )
            for x in range(width)
        ]
        for y in range(height)
    ]
    for _ in range(smooth):
        nxt = [row[:] for row in grid]
        for y in range(1, height - 1):
            for x in range(1, width - 1):
                walls = 0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        if grid[y + dy][x + dx]:
                            walls += 1
                nxt[y][x] = walls > 4 if walls != 4 else grid[y][x]
        grid = nxt
    return grid


def _largest_cavern(grid, width, height):
    """Every open cell reachable from the biggest chamber.

    The automaton reliably produces a few sealed pockets. Rather than trying to
    tunnel them together -- which tends to produce obviously artificial straight
    corridors -- the biggest connected space is kept and everything else is
    filled back in. A wilds you cannot reach half of is worse than a smaller one
    you can walk all of.
    """
    seen = [[False] * width for _ in range(height)]
    best = []
    for sy in range(1, height - 1):
        for sx in range(1, width - 1):
            if grid[sy][sx] or seen[sy][sx]:
                continue
            cells, queue = [], deque([(sx, sy)])
            seen[sy][sx] = True
            while queue:
                x, y = queue.popleft()
                cells.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        if not grid[ny][nx] and not seen[ny][nx]:
                            seen[ny][nx] = True
                            queue.append((nx, ny))
            if len(cells) > len(best):
                best = cells
    return set(best)


def generate(valley_seed, day=1, night=False, width=WIDTH, height=HEIGHT):
    """Build one cycle's cavern. Returns a worldgen.World, so the renderer, the
    collision code and the save format all treat it exactly like the valley."""
    seed = seed_for(valley_seed, day, night)
    rng = random.Random(seed)
    tuning = DANGER["night" if night else "day"]

    world = worldgen.World(seed, width, height)
    world.is_wilds = True

    grid = _carve(rng, width, height, tuning["fill"], tuning["smooth"])
    open_cells = _largest_cavern(grid, width, height)

    for y in range(height):
        for x in range(width):
            world.tiles[y][x] = "stone_floor" if (x, y) in open_cells else _wall(x, y)

    # Sand where the floor meets rock, so the chambers have an edge rather than
    # ending abruptly. Cheap, and it is what stops a cavern reading as a
    # black-and-grey blob.
    for x, y in list(open_cells):
        touching_rock = any(
            (x + dx, y + dy) not in open_cells
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
        )
        if touching_rock and rng.random() < 0.55:
            world.tiles[y][x] = "sand"

    _pools(world, open_cells, rng, tuning["pools"])

    # Connectivity is settled *after* the water goes in, not before.
    #
    # The first version computed the largest chamber from the rock alone and
    # then dropped pools into it. Water is solid, so on the tighter night
    # caverns a pool would sever the map and leave 99% of the floor marooned
    # behind it -- the reachability check reported 0.005 and the run was
    # unplayable. Anything the pools cut off is filled back in as rock, which
    # reads as a flooded dead end rather than as a bug.
    open_cells = _keep_largest_walkable(world)

    # The way home. Placed at the open cell nearest the south edge, because that
    # is the direction the valley is in and an exit you have to hunt for is a
    # tax rather than a challenge.
    entrance = min(open_cells, key=lambda c: (height - c[1], abs(c[0] - width // 2)))
    world.spawn = entrance
    world.tiles[entrance[1]][entrance[0]] = "path"

    # The far end: the open cell furthest from the entrance by actual walking
    # distance, not by straight line. That is where the reward goes when there
    # is a reward to place.
    world.regions = {
        "entrance": list(entrance),
        "deep": list(_furthest(world, entrance, open_cells)),
        "danger": tuning["foes"],
        "foe_bonus": tuning["foe_bonus"],
        "night": bool(night),
        "day": int(day),
    }

    _scatter_rubble(world, open_cells, rng)
    _place_chest(world, rng)
    world.rebuild_collision()

    # Rubble is sparse and small, but a boulder dropped in a one-tile passage
    # can still wall off a chamber. Cheaper to check and drop the offender than
    # to reason about chokepoints while placing them.
    while reachable_fraction(world) < 0.995 and world.objects:
        world.objects.pop()
        world.rebuild_collision()
    return world


def _keep_largest_walkable(world):
    """Recompute the biggest connected walkable region from the tiles as they
    actually are, and turn everything outside it back into rock.

    Run after the water, because water is solid and a pool across a passage
    silently strands whatever is behind it.
    """
    walkable = {
        (x, y)
        for y in range(world.height)
        for x in range(world.width)
        if not worldgen.TILES.get(world.tiles[y][x], {}).get("solid")
    }
    best = set()
    seen = set()
    for cell in walkable:
        if cell in seen:
            continue
        group, queue = set(), deque([cell])
        seen.add(cell)
        while queue:
            x, y = queue.popleft()
            group.add((x, y))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (x + dx, y + dy)
                if nxt in walkable and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        if len(group) > len(best):
            best = group
    for x, y in walkable - best:
        world.tiles[y][x] = _wall(x, y)
    return best


def _pools(world, open_cells, rng, count):
    """Standing water. Solid, so it shapes the fight as cover rather than being
    decoration you walk through."""
    cells = sorted(open_cells)
    for _ in range(count):
        if not cells:
            return
        cx, cy = cells[rng.randrange(len(cells))]
        radius = rng.randint(2, 4)
        for y in range(cy - radius, cy + radius + 1):
            for x in range(cx - radius, cx + radius + 1):
                if (x, y) not in open_cells:
                    continue
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius:
                    world.tiles[y][x] = "water"


def _furthest(world, start, open_cells):
    """Breadth-first walk to the most distant walkable cell. Used for the deep
    end, and incidentally proves the cavern is connected."""
    seen = {start}
    queue = deque([start])
    last = start
    while queue:
        x, y = queue.popleft()
        last = (x, y)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (x + dx, y + dy)
            if nxt in seen or nxt not in open_cells:
                continue
            if worldgen.TILES.get(world.tile(*nxt), {}).get("solid"):
                continue
            seen.add(nxt)
            queue.append(nxt)
    return last


def _place_chest(world, rng):
    """One chest, at the far end.

    The deep point was already being computed and handed back for exactly this
    and nothing was being put in it, which made a cavern a corridor: there was
    no reason to cross it. Which table it draws from is decided in the content
    store at the moment it is opened, not here, so the cavern only has to say
    where the reward is.
    """
    deep = tuple(world.regions["deep"])
    if world.solid_at(*deep):
        return
    world.objects = [obj for obj in world.objects if (obj["x"], obj["y"]) != deep]
    world.objects.append(
        {
            "sprite": "chest",
            "x": deep[0],
            "y": deep[1],
            "solid": True,
            "w": 1,
            "h": 1,
            "hit": [0.8, 0.6],
            "use": "chest",
        }
    )
    world.regions["chest"] = list(deep)


def _scatter_rubble(world, open_cells, rng):
    """Boulders and stumps of rock. Sparse on purpose: the cavern walls already
    give the space its shape, and filling the floor as densely as the valley's
    woodland would leave nowhere to back away to in a fight."""
    taken = set()
    cells = sorted(open_cells)
    attempts = int(len(cells) * 0.05)
    for _ in range(attempts):
        x, y = cells[rng.randrange(len(cells))]
        if (x, y) in taken:
            continue
        if world.tile(x, y) not in ("stone_floor", "sand"):
            continue
        # Never block the way in.
        if abs(x - world.spawn[0]) < 3 and abs(y - world.spawn[1]) < 3:
            continue
        name = "rock_large" if rng.random() < 0.3 else "rock_small"
        spec = worldgen.OBJECTS[name]
        footprint = [
            (x + dx, y - dy) for dx in range(spec["w"]) for dy in range(spec["h"])
        ]
        if any(p in taken or p not in open_cells for p in footprint):
            continue
        taken.update(footprint)
        world.objects.append(
            {
                "sprite": name,
                "x": x,
                "y": y,
                "solid": spec["solid"],
                "w": spec["w"],
                "h": spec["h"],
                "hit": list(spec["hit"]),
            }
        )
    world.objects.sort(key=lambda o: (o["y"], o["x"]))


def reachable_fraction(world):
    """What proportion of the non-solid floor you can actually walk to from the
    entrance. The property the tests care about: a cavern with marooned
    chambers is a generation bug, not a level design choice."""
    walkable = {
        (x, y)
        for y in range(world.height)
        for x in range(world.width)
        if not world.solid_at(x, y)
    }
    if not walkable:
        return 0.0
    start = tuple(world.spawn)
    if start not in walkable:
        return 0.0
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (x + dx, y + dy)
            if nxt in walkable and nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return len(seen) / len(walkable)
