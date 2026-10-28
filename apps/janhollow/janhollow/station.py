"""The station itself: deck files and room files turned into walkable decks.

A deck file says how big the deck is and where its corridors and its lift are.
A room file says which deck it sits on and the rectangle it occupies. Nothing
says where the walls go, where the doors go, or which tiles can be walked on --
those are worked out here, so a room can be moved by editing two numbers in a
JSON file and everything still lines up.

The rules, in the order they are applied:

1. The deck starts as solid hull.
2. Corridors are carved first: they are the spine every room hangs off.
3. Each room's rectangle is carved as floor. Rooms are laid out with a gap of
   at least one tile between them, and that gap becomes their shared wall.
4. Any hull tile touching a floor becomes wall, which is why no file lists a
   single wall tile.
5. A room gets a door wherever its wall separates it from a corridor -- the
   tile nearest the room's centre, unless the room names one.
6. The lift is a 2x2 pad on the corridor. It is the only way between decks, so
   crossing the station means walking to the pad, riding, and walking on.

Everything here is pure: given the same content it builds the same decks, so a
save stores a seed and a clock rather than a copy of the station.
"""

import math
from collections import deque

HULL = "hull"
FLOOR = "floor"
WALL = "wall"
DOOR = "door"
LIFT = "lift"

WALKABLE = {FLOOR, DOOR, LIFT}


class Deck:
    """One deck, built. `grid[y][x]` is a tile id; `rooms` maps a location id to
    the tiles it owns."""

    def __init__(self, deck):
        self.id = deck["id"]
        self.label = deck["label"]
        self.tagline = deck.get("tagline", "")
        self.order = deck.get("order", 0)
        self.width = deck["width"]
        self.height = deck["height"]
        self.floor_sprite = deck.get("floor", "floor_metal")
        self.wall_sprite = deck.get("wall", "wall_metal")
        self.palette = deck.get("palette", "crewroom")
        self.lift = tuple(deck.get("lift", [0, 0]))
        self.grid = [[HULL] * self.width for _ in range(self.height)]
        self.rooms = {}
        self.doors = {}
        self.props = []
        # Tiles a person cannot stand on because there is furniture there. A
        # prop is solid unless its entry says otherwise, so a couch stops you
        # and a rug does not. Crew pathfinding reads the same set, which is why
        # they stopped walking through the consoles.
        self.solid = set()

    # --- building -----------------------------------------------------------

    def carve(self, rect, tile=FLOOR):
        x, y, w, h = rect
        carved = []
        for ty in range(max(0, y), min(self.height, y + h)):
            for tx in range(max(0, x), min(self.width, x + w)):
                self.grid[ty][tx] = tile
                carved.append((tx, ty))
        return carved

    def wall_in(self, tile):
        return tile in (WALL, HULL)

    def at(self, x, y):
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.grid[y][x]
        return HULL

    def walkable(self, x, y):
        return self.at(x, y) in WALKABLE and (x, y) not in self.solid

    def raise_walls(self):
        """Hull that touches floor becomes wall. Everything else stays hull and
        is drawn as open space, which is what makes the deck read as a station
        rather than a floor plan."""
        for y in range(self.height):
            for x in range(self.width):
                if self.grid[y][x] != HULL:
                    continue
                for dx, dy in (
                    (1, 0),
                    (-1, 0),
                    (0, 1),
                    (0, -1),
                    (1, 1),
                    (1, -1),
                    (-1, 1),
                    (-1, -1),
                ):
                    if self.at(x + dx, y + dy) == FLOOR:
                        self.grid[y][x] = WALL
                        break

    def cut_door(self, location_id, room_tiles, corridor_tiles, wanted=()):
        """A door is a wall tile with room on one side and corridor on the other.

        Picking the one nearest the room's centre keeps doors where a person
        would put them, and means a room that is moved keeps a sensible door
        without anyone editing a coordinate.
        """
        room = set(room_tiles)
        corridor = set(corridor_tiles)
        if len(wanted) == 2:
            x, y = int(wanted[0]), int(wanted[1])
            self.grid[y][x] = DOOR
            self.doors[location_id] = (x, y)
            return (x, y)
        cx = sum(t[0] for t in room) / len(room)
        cy = sum(t[1] for t in room) / len(room)
        best = None
        for y in range(self.height):
            for x in range(self.width):
                if self.grid[y][x] != WALL:
                    continue
                touches_room = any(
                    (x + dx, y + dy) in room
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                )
                touches_corridor = any(
                    (x + dx, y + dy) in corridor
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                )
                if touches_room and touches_corridor:
                    score = (x - cx) ** 2 + (y - cy) ** 2
                    if best is None or score < best[0]:
                        best = (score, x, y)
        if best is None:
            return None
        _, x, y = best
        self.grid[y][x] = DOOR
        self.doors[location_id] = (x, y)
        return (x, y)

    # --- using it -----------------------------------------------------------

    def path(self, start, goal):
        """Shortest walk from start to goal, as a list of tiles including goal.

        Breadth-first on a grid of at most a thousand walkable tiles: measured
        well under a millisecond, and it has the useful property of being the
        same path every time, so crew do not jitter between two equal routes.
        """
        if start == goal:
            return []
        if not self.walkable(*goal):
            goal = self.nearest_walkable(goal)
            if goal is None or start == goal:
                return []
        seen = {start: None}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            if current == goal:
                break
            x, y = current
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                step = (x + dx, y + dy)
                if step in seen or not self.walkable(*step):
                    continue
                seen[step] = current
                queue.append(step)
        if goal not in seen:
            return []
        route = []
        node = goal
        while node is not None and node != start:
            route.append(node)
            node = seen[node]
        route.reverse()
        return route

    def nearest_walkable(self, tile):
        x, y = tile
        best = None
        for ty in range(self.height):
            for tx in range(self.width):
                if not self.walkable(tx, ty):
                    continue
                score = (tx - x) ** 2 + (ty - y) ** 2
                if best is None or score < best[0]:
                    best = (score, (tx, ty))
        return best[1] if best else None

    def to_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "tagline": self.tagline,
            "order": self.order,
            "width": self.width,
            "height": self.height,
            "floor": self.floor_sprite,
            "wall": self.wall_sprite,
            "palette": self.palette,
            "lift": list(self.lift),
            "rows": ["".join(_LETTER[tile] for tile in row) for row in self.grid],
            "doors": {k: list(v) for k, v in self.doors.items()},
            "props": self.props,
            "solid": sorted(f"{x},{y}" for x, y in self.solid),
        }


# The grid travels to the browser as one character per tile, the same trick the
# sprite packs use: a deck is then about a kilobyte instead of a list of lists.
_LETTER = {HULL: " ", FLOOR: ".", WALL: "#", DOOR: "+", LIFT: "L"}
_TILE_OF = {v: k for k, v in _LETTER.items()}


def footprint(sprite_sizes, sprite, tile=32):
    """How many tiles a prop covers, as (wide, tall).

    The art is not one tile per prop: a bench is three tiles wide and a star
    window is fourteen. Nothing in the data said so, so props were placed as if
    each were a single tile and ended up hanging through walls and through each
    other.
    """
    width, height = sprite_sizes.get(sprite, (tile, tile))
    return (
        max(1, int(math.ceil(width / float(tile)))),
        max(1, int(math.ceil(height / float(tile)))),
    )


class Station:
    """Every deck, plus the lookups the simulation needs: which deck a location
    is on, where to stand in it, and how to get from one to another."""

    def __init__(self, decks, locations, sprite_sizes=None):
        self.sprite_sizes = dict(sprite_sizes or {})
        self.decks = {}
        self.locations = {}
        self.problems = []
        for deck_id, deck in sorted(
            decks.items(), key=lambda kv: kv[1].get("order", 0)
        ):
            built = Deck(dict(deck, id=deck_id))
            corridor = []
            for rect in deck.get("corridors", []):
                corridor += built.carve(rect)
            here = {
                lid: loc for lid, loc in locations.items() if loc.get("deck") == deck_id
            }
            room_tiles = {}
            for lid, loc in sorted(here.items()):
                room_tiles[lid] = built.carve(loc["rect"])
            built.raise_walls()
            for lid, loc in sorted(here.items()):
                if (
                    built.cut_door(
                        lid, room_tiles[lid], corridor, loc.get("door") or ()
                    )
                    is None
                ):
                    self.problems.append(
                        f"{lid}: no wall between this room and a corridor, so it has no door"
                    )
                rx, ry, rw, rh = loc["rect"]
                for prop in loc.get("props", []):
                    sprite = prop.get("sprite", "")
                    wide, tall = footprint(self.sprite_sizes, sprite)
                    x = rx + int(prop.get("x", 0))
                    y = ry + int(prop.get("y", 0))
                    # Keep the whole thing inside its own room. A prop that has
                    # to be nudged says so, because the fix belongs in the data
                    # rather than here.
                    fixed_x = max(rx, min(rx + rw - wide, x))
                    fixed_y = max(ry, min(ry + rh - tall, y))
                    if (fixed_x, fixed_y) != (x, y):
                        self.problems.append(
                            f"{lid}: {sprite} at {prop.get('x')},{prop.get('y')} is "
                            f"{wide}x{tall} tiles and does not fit; moved to "
                            f"{fixed_x - rx},{fixed_y - ry}"
                        )
                    placed = {
                        "sprite": sprite,
                        "x": fixed_x,
                        "y": fixed_y,
                        "w": wide,
                        "h": tall,
                        "location": lid,
                        "solid": prop.get("solid", True) is not False,
                    }
                    built.props.append(placed)
                    if placed["solid"]:
                        # Only the bottom row blocks you: a tall bookshelf is
                        # something you walk behind, not something you walk
                        # around, and blocking its whole height would wall off
                        # the rooms it stands in.
                        for tx in range(fixed_x, fixed_x + wide):
                            built.solid.add((tx, fixed_y + tall - 1))
                self.locations[lid] = dict(loc, id=lid, tiles=room_tiles[lid])
            for lid in here:
                door = built.doors.get(lid)
                if door and door in built.solid:
                    built.solid.discard(door)
                    self.problems.append(
                        f"{lid}: a prop was sitting in its doorway and has been made walkable"
                    )
            lx, ly = built.lift
            for dx in (0, 1):
                for dy in (0, 1):
                    if built.walkable(lx + dx, ly + dy):
                        built.grid[ly + dy][lx + dx] = LIFT
            self.decks[deck_id] = built
        for lid, loc in locations.items():
            if loc.get("deck") not in self.decks:
                self.problems.append(f"{lid}: no deck called {loc.get('deck')!r}")

    def deck_of(self, location_id):
        location = self.locations.get(location_id)
        return self.decks.get(location["deck"]) if location else None

    def standing_spot(self, location_id, index=0):
        """Where someone stands when they are "in" a room. Spread by index so a
        room with four people in it does not stack them on one tile."""
        location = self.locations.get(location_id)
        if not location:
            return None
        tiles = location["tiles"]
        deck = self.decks[location["deck"]]
        inner = [t for t in tiles if deck.walkable(*t)]
        if not inner:
            return None
        # Prefer tiles away from the walls, so people stand in the room rather
        # than pressed against the edge.
        x, y, w, h = location["rect"]
        middle = [t for t in inner if x < t[0] < x + w - 1 and y < t[1] < y + h - 1]
        pool = middle or inner
        return pool[(index * 7) % len(pool)]

    def to_dict(self):
        return {
            "decks": [
                deck.to_dict()
                for deck in sorted(self.decks.values(), key=lambda d: d.order)
            ],
            "locations": {
                lid: {k: v for k, v in loc.items() if k != "tiles"}
                for lid, loc in self.locations.items()
            },
            "problems": self.problems,
        }


def sprite_sizes_from_library(library):
    """Sprite dimensions, by bare name, out of an art library."""
    sizes = {}
    for pack in (library or {}).get("packs", {}).values():
        for name, sprite in pack.get("sprites", {}).items():
            sizes.setdefault(name, (sprite.get("w", 32), sprite.get("h", 32)))
    return sizes


def build(content_store, sprite_sizes=None):
    """Build the station from a content store dict, the shape
    janhollow.content.store() returns.

    `sprite_sizes` maps a sprite name to its pixel size so props can be laid out
    at their real footprint. Without it every prop is assumed to be one tile,
    which is what put a fourteen-tile window through three walls.
    """
    types = content_store.get("types", {})
    station = Station(
        types.get("decks", {}), types.get("locations", {}), sprite_sizes=sprite_sizes
    )
    station.problems += list(content_store.get("problems", []))
    return station
