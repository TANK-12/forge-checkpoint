"""Generate Janhollow's 32-pixel art: station tiles, and the crew at twice the size.

Why this exists: the station was drawn with the 16-pixel crewroom tiles, where a
metal floor is four pixels of detail and a wall is the same. At 32 the same tile
holds panel seams, rivets, wear, a lit edge and a scuffed corner, which is most
of what makes a deck look like a place rather than a grid.

Two halves:

* **Tiles are generated**, not drawn by hand, because a station wants dozens of
  near-identical panels with different wear. Every tile is deterministic from
  its name, so regenerating the pack gives byte-identical art and a pack can be
  thrown away and rebuilt at any time.
* **The crew are upscaled** with EPX (Scale2x), the pixel-art doubling rule that
  rounds a diagonal instead of turning one pixel into a 2x2 block. Drawing new
  32x48 people would have meant losing the eight anime crew the crewroom pack
  already has; EPX keeps them and makes them the same resolution as the floor
  they stand on. Mixing 16-pixel characters with 32-pixel tiles is the thing
  that actually looks wrong, and this is the cheap way out of it.

Walls are an autotile set: sixteen variants named wall_0 to wall_15, one per
combination of which sides have another wall next to them. The renderer picks
by neighbour, so a corner looks like a corner without any file saying so.

    .venv/bin/python tools/make_art32.py [--force]
"""

import os
import random
import sys

SHARED_DIR = os.environ.get("FORGE_SHARED_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "..", "shared"
)
sys.path.insert(0, os.path.abspath(SHARED_DIR))

import forge_art  # noqa: E402

TILE = 32
DECK_PACK = "janhollow-deck"
CREW_PACK = "janhollow-crew"
PALETTE_ID = "janhollow"

# A palette with enough steps to shade a panel. The tiles get their own palette
# rather than borrowing the crewroom one, so the deck can be re-skinned -- night
# shift, red alert, a rusted derelict -- without touching a sprite.
PALETTE = {
    "id": PALETTE_ID,
    "label": "Janhollow — station",
    "colors": {
        # hull, dark to light
        "a": "#0a0e16",
        "b": "#131a26",
        "c": "#1c2534",
        "d": "#273244",
        "e": "#334056",
        "f": "#425067",
        "g": "#53627a",
        "h": "#67768f",
        # floor plate, cool blue-grey
        "i": "#1a2230",
        "j": "#232e3f",
        "k": "#2c384c",
        "l": "#374559",
        "m": "#445266",
        "n": "#536174",
        # teal, the station's own colour
        "o": "#0f3b3a",
        "p": "#176059",
        "q": "#23857a",
        "r": "#35b3a2",
        "s": "#5bd6c4",
        "t": "#9df0e4",
        # warm light: lamps, warning strips, rust
        "u": "#3a2a14",
        "v": "#7a5420",
        "w": "#c08a2e",
        "x": "#f0b44a",
        "y": "#ffd98a",
        # rust and dirt
        "z": "#4a2e22",
        "A": "#6d4630",
        "B": "#8f5f3e",
        # white-ish highlights and glass
        "C": "#c9d6e4",
        "D": "#eef5ff",
        "E": "#7fa6c8",
        "F": "#2b4a66",
        # deep space and shadow
        "G": "#05070d",
        "H": "#0c1119",
    },
    "roles": {
        "hull": "d",
        "hull_dark": "b",
        "hull_light": "g",
        "floor": "k",
        "floor_light": "n",
        "accent": "s",
        "lamp": "x",
        "space": "G",
    },
}


def canvas(fill="."):
    return [[fill] * TILE for _ in range(TILE)]


def rows_of(grid):
    return ["".join(row) for row in grid]


def rect(grid, x, y, w, h, key, fill=True):
    for ty in range(y, min(TILE, y + h)):
        for tx in range(x, min(TILE, x + w)):
            if tx < 0 or ty < 0:
                continue
            if fill or ty in (y, y + h - 1) or tx in (x, x + w - 1):
                grid[ty][tx] = key


def hline(grid, y, x0, x1, key):
    if 0 <= y < TILE:
        for x in range(max(0, x0), min(TILE, x1 + 1)):
            grid[y][x] = key


def vline(grid, x, y0, y1, key):
    if 0 <= x < TILE:
        for y in range(max(0, y0), min(TILE, y1 + 1)):
            grid[y][x] = key


def speckle(grid, rng, keys, count, area=None):
    """Wear. Without it every panel is identical and the deck reads as wallpaper."""
    x0, y0, x1, y1 = area or (0, 0, TILE - 1, TILE - 1)
    for _ in range(count):
        x = rng.randint(x0, x1)
        y = rng.randint(y0, y1)
        grid[y][x] = rng.choice(keys)


def rng_for(name):
    return random.Random(hash(name) & 0xFFFFFFFF)


# --- floors -----------------------------------------------------------------


def floor_plate(name, base="k", light="n", dark="i", seam="b", wear=True):
    """A deck plate: four panels, bolted, lit from the top left."""
    rng = rng_for(name)
    grid = canvas(base)
    for y in range(TILE):
        for x in range(TILE):
            if (x + y) % 11 == 0:
                grid[y][x] = light
    # panel seams down the middle and across
    hline(grid, 0, 0, TILE - 1, seam)
    vline(grid, 0, 0, TILE - 1, seam)
    hline(grid, TILE // 2, 0, TILE - 1, seam)
    vline(grid, TILE // 2, 0, TILE - 1, seam)
    # a lit edge just inside each seam, which is what gives the plate depth
    hline(grid, 1, 1, TILE - 1, light)
    vline(grid, 1, 1, TILE - 1, light)
    hline(grid, TILE // 2 + 1, 1, TILE - 1, light)
    vline(grid, TILE // 2 + 1, 1, TILE - 1, light)
    hline(grid, TILE - 1, 0, TILE - 1, dark)
    vline(grid, TILE - 1, 0, TILE - 1, dark)
    # bolts in the corners of each panel
    for cy in (3, TILE // 2 + 3):
        for cx in (3, TILE // 2 + 3):
            grid[cy][cx] = dark
            grid[cy - 1][cx] = light
    if wear:
        speckle(grid, rng, [light, dark], 26)
        speckle(grid, rng, [dark], 8)
    return grid


def floor_grate(name):
    """Corridor grating: slats with darkness under them."""
    rng = rng_for(name)
    grid = canvas("j")
    for y in range(TILE):
        for x in range(TILE):
            if y % 4 in (0, 1):
                grid[y][x] = "l" if y % 4 == 0 else "k"
            else:
                grid[y][x] = "i" if (x % 8) in (0, 1) else "b"
    for x in range(0, TILE, 8):
        vline(grid, x, 0, TILE - 1, "i")
        vline(grid, min(TILE - 1, x + 1), 0, TILE - 1, "m")
    speckle(grid, rng, ["m", "i"], 18)
    return grid


def floor_garden(name):
    """Soil trays, for the garden deck: darker, warmer, with growth."""
    rng = rng_for(name)
    grid = canvas("z")
    for y in range(TILE):
        for x in range(TILE):
            grid[y][x] = rng.choice(["z", "z", "A", "u"])
    hline(grid, 0, 0, TILE - 1, "c")
    vline(grid, 0, 0, TILE - 1, "c")
    speckle(grid, rng, ["p", "q"], 22)
    speckle(grid, rng, ["B"], 10)
    return grid


# --- walls, as an autotile set ----------------------------------------------

NORTH, EAST, SOUTH, WEST = 1, 2, 4, 8


def wall_tile(mask):
    """One wall variant. `mask` says which sides have another wall beside them,
    so the open sides get a finished, lit edge and the joined sides do not."""
    rng = rng_for(f"wall{mask}")
    grid = canvas("d")
    # panel texture
    for y in range(TILE):
        for x in range(TILE):
            if (x // 4 + y // 8) % 2 == 0:
                grid[y][x] = "e"
    for x in range(0, TILE, 8):
        vline(grid, x, 0, TILE - 1, "c")
    hline(grid, TILE // 2, 0, TILE - 1, "c")
    speckle(grid, rng, ["f", "c"], 30)

    # A lit top edge and a dark bottom edge on every side that faces a room.
    if not mask & NORTH:
        hline(grid, 0, 0, TILE - 1, "C")
        hline(grid, 1, 0, TILE - 1, "h")
        hline(grid, 2, 0, TILE - 1, "g")
        hline(grid, 3, 0, TILE - 1, "f")
    if not mask & SOUTH:
        hline(grid, TILE - 1, 0, TILE - 1, "G")
        hline(grid, TILE - 2, 0, TILE - 1, "a")
        hline(grid, TILE - 3, 0, TILE - 1, "b")
    if not mask & WEST:
        vline(grid, 0, 0, TILE - 1, "h")
        vline(grid, 1, 0, TILE - 1, "g")
    if not mask & EAST:
        vline(grid, TILE - 1, 0, TILE - 1, "G")
        vline(grid, TILE - 2, 0, TILE - 1, "b")
    return grid


def hull(name):
    """Outside the station: black, with the odd distant star."""
    rng = rng_for(name)
    grid = canvas("G")
    for _ in range(3):
        grid[rng.randrange(TILE)][rng.randrange(TILE)] = "E"
    return grid


# --- fittings ---------------------------------------------------------------


def door(name):
    rng = rng_for(name)
    grid = canvas("c")
    rect(grid, 0, 0, TILE, TILE, "c")
    rect(grid, 2, 2, TILE - 4, TILE - 4, "o")
    for half, x0 in ((0, 3), (1, TILE // 2 + 1)):
        rect(grid, x0, 3, TILE // 2 - 4, TILE - 6, "p")
        rect(grid, x0 + 1, 4, TILE // 2 - 6, TILE - 8, "q")
        vline(grid, x0 + 1, 4, TILE - 5, "r")
    vline(grid, TILE // 2 - 1, 2, TILE - 3, "a")
    vline(grid, TILE // 2, 2, TILE - 3, "b")
    # the light above the door
    rect(grid, TILE // 2 - 3, 0, 6, 2, "s")
    grid[0][TILE // 2 - 1] = "t"
    grid[0][TILE // 2] = "t"
    hline(grid, TILE - 1, 0, TILE - 1, "a")
    speckle(grid, rng, ["p"], 6, (4, 5, TILE - 5, TILE - 6))
    return grid


def lift(name):
    grid = canvas("i")
    rect(grid, 0, 0, TILE, TILE, "i")
    rect(grid, 1, 1, TILE - 2, TILE - 2, "j")
    rect(grid, 3, 3, TILE - 6, TILE - 6, "k")
    # chevrons, up and down
    for i in range(5):
        hline(grid, 6 + i, TILE // 2 - i, TILE // 2 + i, "s" if i < 3 else "r")
        hline(grid, TILE - 7 - i, TILE // 2 - i, TILE // 2 + i, "s" if i < 3 else "r")
    hline(grid, TILE // 2 - 1, 4, TILE - 5, "o")
    hline(grid, TILE // 2, 4, TILE - 5, "p")
    for x in range(2, TILE - 2, 6):
        grid[2][x] = "x"
        grid[TILE - 3][x] = "x"
    return grid


def viewport(name):
    """A window onto space, with the station's frame around it."""
    rng = rng_for(name)
    grid = canvas("d")
    rect(grid, 0, 0, TILE, TILE, "d")
    rect(grid, 2, 2, TILE - 4, TILE - 4, "c")
    rect(grid, 3, 3, TILE - 6, TILE - 6, "G")
    for _ in range(9):
        x = rng.randint(4, TILE - 5)
        y = rng.randint(4, TILE - 5)
        grid[y][x] = rng.choice(["C", "D", "E", "s"])
    # frame highlights
    hline(grid, 2, 2, TILE - 3, "g")
    vline(grid, 2, 2, TILE - 3, "f")
    hline(grid, TILE - 3, 2, TILE - 3, "a")
    vline(grid, TILE - 3, 2, TILE - 3, "b")
    return grid


def light_strip(name):
    """A floor tile with a lit strip, for corridors."""
    grid = floor_plate(name)
    hline(grid, TILE // 2 - 1, 2, TILE - 3, "q")
    hline(grid, TILE // 2, 2, TILE - 3, "s")
    hline(grid, TILE // 2 + 1, 2, TILE - 3, "t")
    hline(grid, TILE // 2 + 2, 2, TILE - 3, "q")
    return grid


TILES = {
    "floor_plate": lambda: floor_plate("floor_plate"),
    "floor_plate_worn": lambda: floor_plate(
        "floor_plate_worn", base="j", light="m", dark="a", seam="a"
    ),
    "floor_grate": lambda: floor_grate("floor_grate"),
    "floor_garden": lambda: floor_garden("floor_garden"),
    "floor_strip": lambda: light_strip("floor_strip"),
    "hull": lambda: hull("hull"),
    "door": lambda: door("door"),
    "lift": lambda: lift("lift"),
    "viewport": lambda: viewport("viewport"),
}


# --- EPX, for the crew and the props ----------------------------------------


def epx(rows):
    """Scale2x/EPX: one pixel becomes four, but a diagonal becomes a diagonal.

    The rule, for pixel P with neighbours A above, B right, C left, D below:
    the four output pixels are P unless two adjacent neighbours agree with each
    other and disagree across, in which case that corner takes their colour.
    That is what rounds a jagged edge instead of doubling it.
    """
    h = len(rows)
    w = len(rows[0]) if h else 0

    def at(x, y):
        if 0 <= x < w and 0 <= y < h:
            return rows[y][x]
        return rows[max(0, min(h - 1, y))][max(0, min(w - 1, x))] if h else "."

    out = []
    for y in range(h):
        top, bottom = [], []
        for x in range(w):
            p = at(x, y)
            a, b, c, d = at(x, y - 1), at(x + 1, y), at(x - 1, y), at(x, y + 1)
            one = two = three = four = p
            if c == a and c != d and a != b:
                one = a
            if a == b and a != c and b != d:
                two = b
            if d == c and d != b and c != a:
                three = c
            if b == d and b != a and d != c:
                four = d
            top += [one, two]
            bottom += [three, four]
        out.append("".join(top))
        out.append("".join(bottom))
    return out


def upscale_pack(library, pack_id, want=None):
    """Every sprite in a pack, at twice the size."""
    pack = library["packs"].get(pack_id)
    if not pack:
        return {}
    out = {}
    for name, sprite in pack["sprites"].items():
        if want and not want(name):
            continue
        out[name] = {
            "w": sprite["w"] * 2,
            "h": sprite["h"] * 2,
            "tags": list(sprite.get("tags", [])) + ["x2"],
            "frames": [
                {"ms": frame.get("ms", 0), "rows": epx(frame["rows"])}
                for frame in sprite["frames"]
            ],
        }
    return out


def main():
    force = "--force" in sys.argv
    forge_art.ensure_root()
    if os.path.exists(forge_art.pack_path(DECK_PACK)) and not force:
        print(f"{DECK_PACK} exists; pass --force to rebuild")
        return

    forge_art.save_palette(PALETTE)

    sprites = {}
    for name, build in TILES.items():
        sprites[name] = {
            "w": TILE,
            "h": TILE,
            "tags": ["tile", name.split("_")[0]],
            "frames": [{"ms": 0, "rows": rows_of(build())}],
        }
    for mask in range(16):
        sprites[f"wall_{mask}"] = {
            "w": TILE,
            "h": TILE,
            "tags": ["tile", "wall", "autotile"],
            "frames": [{"ms": 0, "rows": rows_of(wall_tile(mask))}],
        }
    forge_art.save_pack(
        {
            "id": DECK_PACK,
            "label": "Janhollow — deck, 32px",
            "tile": TILE,
            "default_palette": PALETTE_ID,
            "sprites": sprites,
        }
    )
    print(f"wrote {DECK_PACK}: {len(sprites)} sprites at {TILE}px")

    library = forge_art.library()
    crew = upscale_pack(library, "crewroom-characters")
    props = upscale_pack(library, "crewroom-props")
    tiles16 = upscale_pack(
        library, "janhollow-station", want=lambda n: n in ("bunk", "crate", "locker")
    )
    forge_art.save_pack(
        {
            "id": CREW_PACK,
            "label": "Janhollow — crew and fittings, doubled",
            "tile": TILE,
            "default_palette": "crewroom",
            "sprites": {**crew, **props, **tiles16},
        }
    )
    print(
        f"wrote {CREW_PACK}: {len(crew)} crew sprites, {len(props)} props, {len(tiles16)} fittings"
    )


if __name__ == "__main__":
    if {"-h", "--help"} & set(sys.argv[1:]):  # usage only, no work
        print(__doc__)
        sys.exit(0)
    main()
