"""Writes Emberfield's starting art into the shared Forge sprite library.

Everything this emits is ordinary editable data: palette-indexed character
rows, saved to ~/ForgeArtData, openable in Pixel Forge. Nothing here is
privileged -- re-running it restores the defaults, and the user's edits are
what matter after that. It is a seeder, not an asset pipeline.

Distinctive shapes (the tree, the player, rocks, fences) are hand-authored
below as literal character art. Terrain that wants texture rather than shape
(grass, soil, sand, stone) is generated from a fixed seed so the noise is
tuned and reproducible instead of hand-placed pixel by pixel. Both end up in
the same format, so the editor cannot tell them apart.

Usage:  python tools/seed_art.py [--force]
"""

import argparse
import os
import random
import sys

sys.path.insert(
    0,
    os.environ.get("FORGE_SHARED_DIR")
    or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "shared"
    ),
)

import forge_art  # noqa: E402

TILE = 16

# --- palettes --------------------------------------------------------------
#
# Warm, slightly desaturated, low internal contrast: the Stardew register. The
# roles map gives the procedural nature layer and the renderer semantic names,
# so a season or a night palette can move a colour without the game code
# knowing which key moved.

SPRING = {
    "id": "emberfield-spring",
    "label": "Emberfield — spring",
    "colors": {
        "o": "#2b1f18",  # outline, a warm near-black rather than pure black
        "a": "#3f6b34",
        "b": "#4e8340",
        "c": "#5e9a4a",
        "d": "#74b258",
        "e": "#402d1f",
        "f": "#6b4a31",
        "g": "#8a6242",
        "h": "#33241a",
        "i": "#452f21",
        "j": "#1e4d6b",
        "k": "#2c6d91",
        "l": "#4a93b8",
        "m": "#cfe9f2",
        "n": "#4a4a52",
        "p": "#6b6b75",
        "q": "#8f8f9a",
        "r": "#b3b3bc",
        "s": "#d9c08c",
        "t": "#c2a674",
        "u": "#4a3524",
        "v": "#6e4f34",
        "w": "#93704b",
        "x": "#2f5c2a",
        "y": "#3f7a35",
        "z": "#55993f",
        "A": "#6cb04d",
        "B": "#c0483f",
        "C": "#e0b040",
        "D": "#eee6d8",
        "E": "#e8b48c",
        "F": "#c08a63",
        "G": "#6b3f27",
        "H": "#3f6ba8",
        "I": "#2c4e7a",
        "J": "#5a8cc4",
        "K": "#b8b0a0",
    },
    "roles": {
        "outline": "o",
        "grass_dark": "a",
        "grass_mid": "b",
        "grass_light": "c",
        "grass_hi": "d",
        "soil_dark": "e",
        "soil_mid": "f",
        "soil_light": "g",
        "tilled_dark": "h",
        "tilled_mid": "i",
        "water_deep": "j",
        "water_mid": "k",
        "water_light": "l",
        "foam": "m",
        "stone_dark": "n",
        "stone_mid": "p",
        "stone_light": "q",
        "stone_hi": "r",
        "sand": "s",
        "sand_dark": "t",
        "wood_dark": "u",
        "wood_mid": "v",
        "wood_light": "w",
        "leaf_dark": "x",
        "leaf_mid": "y",
        "leaf_light": "z",
        "leaf_hi": "A",
        "flower_red": "B",
        "flower_yellow": "C",
        "flower_white": "D",
        "skin": "E",
        "skin_shade": "F",
        "hair": "G",
        "cloth": "H",
        "cloth_shade": "I",
        "cloth_light": "J",
        "metal": "K",
    },
}


def _shift(hex_color, mul, add):
    """Nudge a colour toward a mood. Night is not simply 'darker': it loses
    saturation and pulls blue, which is what stops a night palette looking like
    the day palette with the brightness turned down."""
    n = int(hex_color[1:], 16)
    out = []
    for i, channel in enumerate(((n >> 16) & 255, (n >> 8) & 255, n & 255)):
        v = int(channel * mul[i] + add[i])
        out.append(max(0, min(255, v)))
    return "#%02x%02x%02x" % tuple(out)


def derive_palette(base, pid, label, mul, add, keep=()):
    colors = {}
    for key, value in base["colors"].items():
        colors[key] = value if key in keep else _shift(value, mul, add)
    return {"id": pid, "label": label, "colors": colors, "roles": dict(base["roles"])}


# --- authoring helpers -----------------------------------------------------


def rows_from(block):
    """A literal art block -> rows, ignoring blank lines and indentation."""
    return [line.strip() for line in block.strip("\n").split("\n") if line.strip()]


def sprite(w, h, frames, tags=(), ms=0):
    return {
        "w": w,
        "h": h,
        "tags": list(tags),
        "frames": [{"ms": ms, "rows": f} for f in frames],
    }


def static(rows, tags=()):
    return sprite(len(rows[0]), len(rows), [rows], tags)


def mirror(rows):
    return [row[::-1] for row in rows]


def overlay(base, top):
    """Composite `top` onto `base`, treating '.' in top as see-through."""
    out = []
    for y, row in enumerate(base):
        line = list(row)
        for x, char in enumerate(top[y]):
            if char != ".":
                line[x] = char
        out.append("".join(line))
    return out


def shift_v(rows, dy, fill="."):
    """Move art up or down inside its own box -- how the walk frames are made."""
    w = len(rows[0])
    blank = fill * w
    if dy == 0:
        return list(rows)
    if dy > 0:
        return [blank] * dy + rows[:-dy]
    return rows[-dy:] + [blank] * (-dy)


# --- procedural terrain ----------------------------------------------------


def noise_tile(rng, weights, size=TILE):
    """Weighted per-pixel scatter. Blunt, but for ground texture at 16x16 that
    is genuinely what reads best: structure comes from the scatter layers on
    top, not from the base."""
    keys, cuts, total = [], [], 0.0
    for key, weight in weights:
        total += weight
        keys.append(key)
        cuts.append(total)
    rows = []
    for _ in range(size):
        line = []
        for _ in range(size):
            roll = rng.random() * total
            for key, cut in zip(keys, cuts):
                if roll <= cut:
                    line.append(key)
                    break
        rows.append("".join(line))
    return rows


def speckle(rows, rng, char, count):
    """Scatter a few accent pixels -- pebbles in soil, a lighter blade in grass."""
    out = [list(r) for r in rows]
    h, w = len(rows), len(rows[0])
    for _ in range(count):
        out[rng.randrange(h)][rng.randrange(w)] = char
    return ["".join(r) for r in out]


def grass_tile(rng):
    base = noise_tile(rng, [("b", 62), ("a", 20), ("c", 16), ("d", 2)])
    return speckle(base, rng, "d", 3)


def soil_tile(rng):
    base = noise_tile(rng, [("f", 64), ("e", 22), ("g", 14)])
    return speckle(base, rng, "e", 4)


def sand_tile(rng):
    base = noise_tile(rng, [("s", 78), ("t", 22)])
    return speckle(base, rng, "t", 3)


def stone_tile(rng):
    base = noise_tile(rng, [("p", 60), ("n", 22), ("q", 18)])
    return speckle(base, rng, "r", 2)


def tilled_tile(rng, wet=False):
    """Furrows: ridge, shoulder, furrow.

    Three tones with a visible step between them is what makes tilled ground
    read as worked. The first version used two near-identical darks and the
    plot came out looking like brown noise on screen.
    """
    ridge, shoulder, furrow = ("g", "f", "h") if not wet else ("f", "e", "h")
    rows = []
    for y in range(TILE):
        band = y % 4
        if band == 0:
            row = [furrow] * TILE
        elif band == 2:
            row = [ridge if rng.random() > 0.2 else shoulder for _ in range(TILE)]
        else:
            row = [shoulder if rng.random() > 0.3 else furrow for _ in range(TILE)]
        rows.append("".join(row))
    return rows


def water_frames(rng):
    """Three frames of drifting ripple. Water that does not move makes a whole
    map look like a screenshot.

    The ripples are near-horizontal on purpose. An earlier version offset by
    (x + y*2), which produced a strong diagonal that tiled into a barber pole
    across any body of water bigger than a few tiles. Broken, drifting
    horizontal streaks read as a surface; regular diagonals read as a mistake.
    """
    streaks = [(rng.randrange(TILE), rng.randrange(TILE)) for _ in range(5)]
    frames = []
    for phase in range(3):
        rows = [["j"] * TILE for _ in range(TILE)]
        for y in range(TILE):
            for x in range(TILE):
                if rng.random() > 0.86:
                    rows[y][x] = "k"
        for sy, sx in streaks:
            y = (sy + phase) % TILE
            start = (sx + phase * 3) % TILE
            length = 3 + (sy % 3)
            for i in range(length):
                rows[y][(start + i) % TILE] = "k"
            rows[y][(start + length // 2) % TILE] = "l"
        frames.append(["".join(r) for r in rows])
    return frames


# --- shaped objects --------------------------------------------------------


def outline_outward(grid, char="o"):
    """Grow a 1px dark rim *outside* the silhouette rather than eating into it.

    Doing it outward is what keeps a 16px sprite from losing a quarter of its
    readable area to its own outline, and it is the reason Stardew-style art
    stays legible at this size.
    """
    h, w = len(grid), len(grid[0])
    out = [row[:] for row in grid]
    for y in range(h):
        for x in range(w):
            if grid[y][x] != ".":
                continue
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and grid[ny][nx] not in (".", char):
                    out[y][x] = char
                    break
    return out


def blob(rng, w, h, cx, cy, rx, ry, fill, dark, light, wobble=0.16):
    """An irregular ellipse with directional shading: light toward the upper
    left, dark toward the lower right, so a canopy or a boulder reads as round
    without needing a hand-placed gradient."""
    grid = [["." for _ in range(w)] for _ in range(h)]
    for y in range(h):
        for x in range(w):
            dx = (x + 0.5 - cx) / rx
            dy = (y + 0.5 - cy) / ry
            dist = dx * dx + dy * dy
            edge = 1.0 + (rng.random() - 0.5) * wobble
            if dist <= edge:
                if dist > edge * 0.70:
                    grid[y][x] = dark
                elif dx + dy < -0.50:
                    grid[y][x] = light
                else:
                    grid[y][x] = fill
    return grid


def sprinkle(grid, rng, char, count, only=()):
    h, w = len(grid), len(grid[0])
    placed = 0
    for _ in range(count * 40):
        if placed >= count:
            break
        y, x = rng.randrange(h), rng.randrange(w)
        if grid[y][x] != "." and (not only or grid[y][x] in only):
            grid[y][x] = char
            placed += 1
    return grid


def to_rows(grid):
    return ["".join(row) for row in grid]


def oak_tree(rng):
    """A low, heavy canopy over a short trunk.

    The first pass gave an 18-row trunk under a high canopy and read as a
    lamppost. A Stardew-register tree is mostly canopy: the trunk only needs to
    be long enough to show the sprite is standing on the ground.
    """
    w, h = 32, 48
    canopy = blob(rng, w, h, 16, 17, 14.5, 15.5, "y", "x", "z", wobble=0.10)
    canopy = sprinkle(canopy, rng, "A", 22, only=("y", "z"))
    canopy = sprinkle(canopy, rng, "x", 10, only=("y",))
    grid = outline_outward(canopy)
    # Trunk, drawn after the canopy so it tucks under it.
    for y in range(33, 45):
        for x in range(13, 19):
            grid[y][x] = "v"
        grid[y][13] = "u"
        grid[y][18] = "u"
        if y % 5 == 2:
            grid[y][16] = "w"
    for y in range(33, 45):  # rim the trunk where it leaves the canopy
        for x in (12, 19):
            if grid[y][x] == ".":
                grid[y][x] = "o"
    for x in range(11, 21):  # root flare
        grid[45][x] = "u"
        grid[46][x] = "o"
    return to_rows(grid)


def bush(rng):
    grid = blob(rng, 16, 16, 8, 9, 7.0, 6.2, "y", "x", "z")
    grid = sprinkle(grid, rng, "A", 6, only=("y", "z"))
    grid = sprinkle(grid, rng, "B", 3, only=("y", "x"))  # a few berries
    return to_rows(outline_outward(grid))


def rock(rng, size):
    half = size / 2.0
    grid = blob(
        rng,
        size,
        size,
        half,
        half + size * 0.08,
        half * 0.85,
        half * 0.72,
        "p",
        "n",
        "q",
        wobble=0.30,
    )
    grid = sprinkle(grid, rng, "r", max(2, size // 6), only=("q", "p"))
    return to_rows(outline_outward(grid))


def stump(rng):
    grid = blob(rng, 16, 16, 8, 10, 6.0, 4.6, "v", "u", "w", wobble=0.18)
    for x in range(5, 11):  # cut face
        grid[6][x] = "w"
    grid[7][7] = "w"
    grid[7][8] = "w"
    return to_rows(outline_outward(grid))


FENCE_POST = rows_from("""
    ................
    ................
    ......oooo......
    .....ovvvvo.....
    .....ovwwvo.....
    .....ovwwvo.....
    .....ovwwvo.....
    .....ovwwvo.....
    .....ovwwvo.....
    .....ovwwvo.....
    .....ovwwvo.....
    .....ovwwvo.....
    .....ovwwvo.....
    .....ovuuvo.....
    ......oooo......
    ................
    """)

FENCE_RAIL = rows_from("""
    ................
    ................
    ................
    ................
    oooooooooooooooo
    vvvvvvvvvvvvvvvv
    wwwwwwwwwwwwwwww
    oooooooooooooooo
    ................
    ................
    oooooooooooooooo
    vvvvvvvvvvvvvvvv
    wwwwwwwwwwwwwwww
    oooooooooooooooo
    ................
    ................
    """)

PLAYER_DOWN = rows_from("""
    ................
    .....oooooo.....
    ....oGGGGGGo....
    ...oGGGGGGGGo...
    ..oGGGGGGGGGGo..
    ..oGEEEEEEEEGo..
    ..oGEEEEEEEEGo..
    ..oEEoEEEEoEEo..
    ..oEEoEEEEoEEo..
    ..oEEEEEEEEEEo..
    ..oEEEEooEEEEo..
    ...oEEEEEEEEo...
    ....oFFFFFFo....
    ...oHHHHHHHHo...
    ..oHHHHHHHHHHo..
    .oEHHHHHHHHHHEo.
    .oEHHHHHHHHHHEo.
    .oEHHHHHHHHHHEo.
    ..oHHHHHHHHHHo..
    ..oIIIIIIIIIIo..
    ..oIIIIIIIIIIo..
    ...oIIIooIIIo...
    ...ovvo..ovvo...
    ....oo....oo....
    """)

PLAYER_UP = rows_from("""
    ................
    .....oooooo.....
    ....oGGGGGGo....
    ...oGGGGGGGGo...
    ..oGGGGGGGGGGo..
    ..oGGGGGGGGGGo..
    ..oGGGGGGGGGGo..
    ..oGGGGGGGGGGo..
    ..oGGGGGGGGGGo..
    ..oGGGGGGGGGGo..
    ..oGGGGGGGGGGo..
    ...oGGGGGGGGo...
    ....oFFFFFFo....
    ...oHHHHHHHHo...
    ..oHHHHHHHHHHo..
    .oEHHHHHHHHHHEo.
    .oEHHHHHHHHHHEo.
    .oEHHHHHHHHHHEo.
    ..oHHHHHHHHHHo..
    ..oIIIIIIIIIIo..
    ..oIIIIIIIIIIo..
    ...oIIIooIIIo...
    ...ovvo..ovvo...
    ....oo....oo....
    """)

PLAYER_SIDE = rows_from("""
    ................
    .....oooooo.....
    ....oGGGGGGGo...
    ...oGGGGGGGGGo..
    ...oGGGGGGGGGo..
    ...oGEEEEEEEGo..
    ...oGEEEEEEEo...
    ...oEEEoEEEEo...
    ...oEEEoEEEEo...
    ...oEEEEEEEEo...
    ...oEEEEEEEo....
    ....oEEEEEEo....
    ....oFFFFFFo....
    ....oHHHHHHo....
    ...oHHHHHHHHo...
    ...oHHHHHHHHEo..
    ...oHHHHHHHHEo..
    ...oHHHHHHHHEo..
    ...oHHHHHHHHo...
    ...oIIIIIIIIo...
    ...oIIIIIIIIo...
    ...oIIIIIIIIo...
    ....ovvvvo......
    .....oooo.......
    """)

# Frame B of the walk: the stance widens. Two frames is all a Stardew-register
# walk needs, and more would only make the 16px silhouette noisier.
STRIDE_FRONT = rows_from("""
    ...oIIIooIIIo...
    ..ovvo....ovvo..
    ...oo......oo...
    """)

STRIDE_SIDE = rows_from("""
    ...oIIIIIIIIo...
    ...ovvo.ovvo....
    ....oo...oo.....
    """)


def transpose(rows):
    """Rotate a square sprite a quarter turn -- how the vertical fence rail is
    made from the horizontal one, so the two always stay in step."""
    return ["".join(rows[y][x] for y in range(len(rows))) for x in range(len(rows[0]))]


def walk_pair(rows, stride):
    """Two frames from one pose: the still frame, and the same body with the
    last three rows replaced by a stride."""
    moving = rows[: len(rows) - len(stride)] + stride
    return [rows, moving]


def flower_patch(rng, color, count=4):
    """Small blossoms on a stem, scattered on transparency so a patch can sit
    over any ground tile rather than needing one baked variant per terrain."""
    grid = [["." for _ in range(TILE)] for _ in range(TILE)]
    for _ in range(count):
        cx, cy = rng.randrange(2, TILE - 2), rng.randrange(7, TILE - 3)
        for y in range(cy, min(TILE, cy + 3)):
            grid[y][cx] = "a"
        for dy, dx in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)):
            y, x = cy - 2 + dy, cx + dx
            if 0 <= y < TILE and 0 <= x < TILE:
                grid[y][x] = color
    return to_rows(grid)


def path_tile(rng):
    grid = [list(row) for row in soil_tile(rng)]
    for _ in range(7):  # trodden stones
        y, x = rng.randrange(TILE), rng.randrange(TILE)
        grid[y][x] = "p" if rng.random() > 0.4 else "q"
    return to_rows(grid)


def cliff_face(rng):
    rows = []
    for y in range(TILE):
        line = []
        for x in range(TILE):
            if y < 2:
                line.append("q")  # lit top lip
            elif (x + y // 3) % 7 == 0:
                line.append("n")  # vertical fissures
            else:
                line.append("p" if rng.random() > 0.25 else "n")
        rows.append("".join(line))
    return rows


# --- assembly --------------------------------------------------------------


# --- crops, tools, foes ----------------------------------------------------
#
# Session 2's art. Crops are generated from one shape function per growth stage
# so that adding a fourth crop is a colour and a fruit character rather than
# four more hand-drawn sprites; the tools, the bed and the foes are authored
# literally because their silhouettes are what make them readable at 16px.


def crop_stages(leaf, fruit, fruit_hi):
    """Four growth stages, bottom-anchored in a 16x16 tile.

    Built as a pixel grid rather than as literal character art, because these
    twelve sprites are the same shape three times over in different colours --
    and because hand-counting sixteen characters a row sixty-four times is
    exactly the sort of thing that silently produces a ragged sprite.

    The stages are deliberately different *shapes*, not one plant scaled up: at
    a glance across a field you should be able to tell a sprout from a ripe row
    without counting pixels, which is the thing a farming game asks of its art
    more than anything else.
    """
    L, F, H = leaf, fruit, fruit_hi

    def grid():
        return [["." for _ in range(TILE)] for _ in range(TILE)]

    def put(g, points, char):
        for x, y in points:
            if 0 <= x < TILE and 0 <= y < TILE:
                g[y][x] = char

    # A stem the plant grows up, and a pair of leaf fans that widen with age.
    def plant(stem_top, fans, leaf_char):
        g = grid()
        put(g, [(7, y) for y in range(stem_top, 15)], leaf_char)
        put(g, [(8, y) for y in range(stem_top + 2, 15)], leaf_char)
        for row, reach in fans:
            # Filled outward rather than stepped: a stepped fan leaves single
            # pixels floating off the stem and the plant reads as scattered
            # litter instead of one growing thing.
            for step in range(1, reach + 1):
                drop = step // 2
                put(g, [(7 - step, row + drop), (8 + step, row + drop)], leaf_char)
                if drop:
                    put(
                        g,
                        [(7 - step, row + drop - 1), (8 + step, row + drop - 1)],
                        leaf_char,
                    )
        put(g, [(6, 14), (9, 14)], "o")  # the soil shadow it stands in
        return g

    sprout = grid()
    put(sprout, [(7, 12), (7, 13), (8, 13)], L)
    put(sprout, [(6, 11), (8, 11), (9, 12)], L)
    put(sprout, [(6, 14), (9, 14)], "o")

    young = plant(9, [(10, 2), (12, 1)], L)
    grown = plant(5, [(6, 3), (9, 3), (12, 2)], L)

    ripe = plant(4, [(5, 4), (8, 3), (11, 2)], L)
    # The fruit sits high and centred so a ripe row reads as a line of colour.
    put(ripe, [(7, 4), (8, 4), (7, 5), (8, 5), (6, 5), (9, 5)], F)
    put(ripe, [(7, 3), (8, 3)], H)

    return [to_rows(g) for g in (sprout, young, grown, ripe)]


TOOL_HOE = """
................
................
.............ww.
............wvw.
...........wvw..
..........wvw...
.........wvw....
........wvw.....
.......wvw......
......wvw.......
.....wvw........
....qqqw........
...qrqq.........
...qqq..........
...oqo..........
................
"""

TOOL_CAN = """
................
................
................
.......ppp......
......p...p.....
.....pqqqp......
....pqqqqqp.....
...pqrqqqqp.....
..ppqqqqqqp.....
.pq.pqqqqqp.....
.pq.pqqqqqp.....
.pq.pqqqqqp.....
..p.pqqqqp......
....pppppp......
.....oooo.......
................
"""

TOOL_BOW = """
................
................
......www.......
.....wD..w......
....wD....w.....
...wD......w....
...wD......w....
..wD.......w....
..wD.......w....
..wD.......w....
...wD......w....
...wD......w....
....wD....w.....
.....wD..w......
......www.......
................
"""

SEED_BAG = """
................
................
................
......uuu.......
.....utttu......
....ustttsu.....
....stttttu.....
...sstttttsu....
...sstttttsu....
...ssttttts.u...
...sstCttCsu....
....ssttttsu....
....ssssssu.....
.....oooo.......
................
................
"""

ARROW = """
....................
..w.................
.wwqqqqqqqqqqqqqr...
..w.................
....................
"""

BED = """
................................
................................
..oooooooooooooooooooooooooooo..
..ouuuuuuuuuuuuuuuuuuuuuuuuuuo..
..ouDDDDDDDDDDBBBBBBBBBBBBBBuo..
..ouDDDDDDDDDDBBBBBBBBBBBBBBuo..
..ouDDDDDDDDDDBBBBBBBBBBBBBBuo..
..ouDDDDDDDDDDBHHHHHHHHHHHHBuo..
..ouDDDDDDDDDDBHHHHHHHHHHHHBuo..
..ouDDDDDDDDDDBHHHHHHHHHHHHBuo..
..ouDDDDDDDDDDBHHHHHHHHHHHHBuo..
..ouDDDDDDDDDDBBBBBBBBBBBBBBuo..
..ouuuuuuuuuuuuuuuuuuuuuuuuuuo..
..ovvvvvvvvvvvvvvvvvvvvvvvvvvo..
..oooooooooooooooooooooooooooo..
..ou..........................uo
..ou..........................uo
..oo..........................oo
................................
................................
................................
................................
................................
................................
................................
................................
................................
................................
................................
................................
................................
................................
"""


def slime(rng):
    """A low, wide, gelatinous dome. Low and wide on purpose: it has to read as
    something that oozes rather than something that stands."""
    grid = blob(rng, 16, 16, 8.0, 11.0, 6.2, 4.4, "z", "y", "A", wobble=0.22)
    for x in range(2, 14):
        for y in range(14, 16):
            if grid[y][x] != ".":
                grid[y][x] = "y"
    grid[8][5] = grid[8][6] = "m"  # a wet highlight, the only thing that says "gel"
    grid[9][5] = "m"
    grid[10][6] = grid[10][10] = "o"  # eyes
    grid[10][7] = grid[10][11] = "o"
    return to_rows(outline_outward(grid))


def wisp(rng):
    """A hot core in a soft halo. Reads as light rather than as a creature,
    which is what makes it feel different to fight even before it moves."""
    grid = blob(rng, 16, 16, 8.0, 8.0, 4.6, 4.6, "C", "B", "D", wobble=0.30)
    core = blob(rng, 16, 16, 8.0, 8.0, 2.2, 2.2, "D", "C", "D", wobble=0.15)
    for y in range(16):
        for x in range(16):
            if core[y][x] != ".":
                grid[y][x] = core[y][x]
    sprinkle(grid, rng, "C", 5)
    return to_rows(grid)  # deliberately no outline: it glows, it has no edge


def cave_wall(rng):
    """Rock seen from above, not a cliff seen from the side.

    The wilds first used the valley's cliff_face tile for its walls, which was
    wrong in a way that only showed up once a whole screen was made of it:
    cliff_face is drawn as a *face*, with horizontal strata, so tiling it across
    a cavern read as banded wallpaper rather than as stone. This is the same
    palette with the structure removed -- clumped noise with a few darker
    hollows, so a wall of it reads as mass.
    """
    grid = [
        ["n" if rng.random() < 0.55 else "p" for _ in range(TILE)] for _ in range(TILE)
    ]
    # A couple of darker pits per tile stop the noise reading as static.
    for _ in range(3):
        cx, cy = rng.randrange(TILE), rng.randrange(TILE)
        for y in range(max(0, cy - 2), min(TILE, cy + 2)):
            for x in range(max(0, cx - 2), min(TILE, cx + 2)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= 3:
                    grid[y][x] = "h"
    # And a few lighter chips, so it catches what little light there is.
    sprinkle(grid, rng, "q", 6)
    return to_rows(grid)


STALL = """
................................
................................
..BBBBBBBBBBBBBBBBBBBBBBBBBBBB..
.BDDBBBBDDBBBBDDBBBBDDBBBBDDBBB.
.BDDBBBBDDBBBBDDBBBBDDBBBBDDBBB.
..oooooooooooooooooooooooooooo..
..uvvvvvvvvvvvvvvvvvvvvvvvvvvu..
..u..........................u..
..u..CC...ss...zz...BB.......u..
..u.CCCC.ssss.zzzz.BBBB......u..
..u.CCCC.ssss.zzzz.BBBB......u..
..u..CC...ss...zz...BB.......u..
..u..........................u..
..uwwwwwwwwwwwwwwwwwwwwwwwwwwu..
..uvvvvvvvvvvvvvvvvvvvvvvvvvvu..
..oooooooooooooooooooooooooooo..
..u..........................u..
..u..........................u..
..oo........................oo..
................................
................................
................................
................................
................................
................................
................................
................................
................................
................................
................................
................................
................................
"""

CHEST = """
................
................
................
....oooooooo....
...ouuuuuuuuo...
...owwwwwwwwo...
...oCCCCCCCCo...
...ouuuuuuuuo...
...oooooooooo...
...ovvvvvvvvo...
...ovvvCCvvvo...
...ovvvCCvvvo...
...ovvvvvvvvo...
...oooooooooo...
....oooooooo....
................
"""


# --- buildings and interiors (session 5) ---------------------------------
#
# Houses you and the villagers walk into. Authored as literal blocks like the
# bed and the stall, because a building's silhouette -- a pitched roof over a
# doorway -- is what makes it read as a house rather than a crate at this size.
# The footprint is 3x3 tiles (48x48) so the door tile can sit one row south of
# the sprite and never be swallowed by the solid box.


def house(roof, wall, door="G", win="l"):
    """A 48x48 cottage: pitched roof, two windows, a centred door."""
    w, h = 48, 48
    g = [["." for _ in range(w)] for _ in range(h)]
    for y in range(4, 20):  # roof
        span = 3 + (y - 4) * 2
        for x in range(24 - span, 24 + span):
            if 0 <= x < w:
                g[y][x] = roof
    for x in range(2, 46):  # eaves
        if 0 <= x < w:
            g[20][x] = "o"
    for y in range(21, 46):  # walls
        for x in range(6, 42):
            g[y][x] = wall
        g[y][6] = g[y][41] = "o"
    for x in range(6, 42):
        g[45][x] = "o"
    for y in range(33, 45):  # door
        for x in range(21, 27):
            g[y][x] = door
    g[33][20] = g[33][27] = "o"
    for y in range(25, 31):  # windows
        for x in range(11, 17):
            g[y][x] = win
        for x in range(31, 37):
            g[y][x] = win
    return to_rows(outline_outward(g))


def well_sprite():
    """A round stone well, 32x32, two tiles."""
    g = [["." for _ in range(32)] for _ in range(32)]
    for y in range(12, 28):
        for x in range(6, 26):
            dx, dy = (x - 16) / 10.0, (y - 20) / 8.0
            if dx * dx + dy * dy <= 1.0:
                g[y][x] = "p" if (x + y) % 3 else "n"
    for x in range(8, 24):  # water surface
        g[19][x] = g[20][x] = "k"
    for x in (7, 24):  # posts
        for y in range(4, 18):
            g[y][x] = "v"
    for x in range(6, 26):  # little roof
        g[3][x] = "u"
    return to_rows(outline_outward(g))


DOOR_MAT = """
................
................
................
................
................
................
................
................
................
................
....GGGGGGGG....
...GwwwwwwwwG...
...GwwwwwwwwG...
....GGGGGGGG....
................
................
"""

HEARTH = """
.oooooooooooooo.
.onnnnnnnnnnnno.
.onqqqqqqqqqqno.
.onqoooooooqqno.
.onqoBBBBBoqqno.
.onqoBCCCBoqqno.
.onqoCCDCCoqqno.
.onqoBCCCBoqqno.
.onqoBBBBBoqqno.
.onqooooooooqno.
.onqqqqqqqqqqno.
.onGGGGGGGGGGno.
.oGGGGGGGGGGGGo.
.oGwwwwwwwwwwGo.
.oooooooooooooo.
................
"""

TABLE = """
................
................
................
...GGGGGGGGGG...
..GvvvvvvvvvvG..
..GwwwwwwwwwwG..
..oGGGGGGGGGGo..
....Gv....vG....
....Gv....vG....
....Gv....vG....
....Gv....vG....
....Gv....vG....
....oo....oo....
................
................
................
"""

WORKBENCH = """
................
....K.....K.....
...KKK..r.KK....
..oooooooooooo..
..ouuuuuuuuuuo..
..owwwwwwwwwwo..
..oGGGGGGGGGGo..
..oGvq....qvGo..
..oGv......vGo..
..oGv..KK..vGo..
..oGv..KK..vGo..
..oGv......vGo..
..oGv......vGo..
..ooo......ooo..
..oo........oo..
................
"""


def wood_floor_tile(rng):
    """Warm honey planks laid horizontally, with a dark seam between courses and
    a butt joint every few tiles. Reads clearly as a floor and clearly not as
    the wall, which the first pass did not -- both were brown noise."""
    rows = []
    seam_at = rng.randrange(5, 12)
    for y in range(TILE):
        line = []
        course_edge = y % 5 == 0
        for x in range(TILE):
            if course_edge:
                line.append("u")  # dark seam between plank courses
            elif x == (seam_at + (y // 5) * 7) % TILE:
                line.append("u")  # a butt joint
            else:
                line.append("g" if rng.random() > 0.22 else "w")  # honey / mid
        rows.append("".join(line))
    return rows


def interior_wall_tile(rng):
    """A whitewashed cob wall with dark timber studs -- deliberately lighter and
    cooler than the floor so the room has an edge you can see."""
    rows = []
    for y in range(TILE):
        line = []
        for x in range(TILE):
            if x % 8 == 0:
                line.append("o")  # timber stud
            elif y == 0 or y == TILE - 1:
                line.append("G")  # top and bottom plate
            else:
                line.append("D" if rng.random() > 0.14 else "K")  # plaster
        rows.append("".join(line))
    return rows


def rug_tile(rng):
    """A woven rug: a rust border, a cream field, a gold diamond in the middle."""
    rows = []
    for y in range(TILE):
        line = []
        for x in range(TILE):
            if x < 2 or x > 13 or y < 2 or y > 13:
                line.append("B")  # border
            elif abs(x - 8) + abs(y - 8) <= 4:
                line.append("C")  # centre diamond
            elif abs(x - 8) + abs(y - 8) == 5:
                line.append("F")
            else:
                line.append("s")  # field
        rows.append("".join(line))
    return rows


def villager(base_rows, stride, mapping):
    """A villager from the player's pose, recoloured. Same two-frame walk."""

    def recolor(rows):
        return ["".join(mapping.get(c, c) for c in row) for row in rows]

    return [recolor(f) for f in walk_pair(base_rows, stride)]


VILLAGER_LOOKS = {
    # id            hair  tunic  tunic-shade
    "villager_a": {"G": "G", "H": "B", "I": "u"},  # brown hair, rust tunic
    "villager_b": {"G": "n", "H": "z", "I": "x"},  # grey hair, green
    "villager_c": {"G": "u", "H": "C", "I": "v"},  # fair hair, gold coat
}


def build_packs():
    rng = random.Random(20260906)  # fixed: the defaults must be reproducible

    terrain = {}
    for i, name in enumerate(("grass_a", "grass_b", "grass_c", "grass_d")):
        terrain[name] = static(grass_tile(rng), ["terrain", "ground", "grass"])
    terrain["soil"] = static(soil_tile(rng), ["terrain", "ground"])
    terrain["path"] = static(path_tile(rng), ["terrain", "ground"])
    terrain["sand"] = static(sand_tile(rng), ["terrain", "ground"])
    terrain["stone_floor"] = static(stone_tile(rng), ["terrain", "ground"])
    terrain["tilled"] = static(tilled_tile(rng), ["terrain", "ground", "farm"])
    terrain["tilled_wet"] = static(
        tilled_tile(rng, wet=True), ["terrain", "ground", "farm"]
    )
    terrain["cliff_face"] = static(cliff_face(rng), ["terrain", "solid"])
    # Three variants, picked per tile by position hash, so a cavern wall breaks
    # up instead of repeating one stamp across forty tiles.
    for name in ("cave_wall_a", "cave_wall_b", "cave_wall_c"):
        terrain[name] = static(cave_wall(rng), ["terrain", "solid", "cave"])
    terrain["water"] = sprite(
        TILE, TILE, water_frames(rng), ["terrain", "liquid", "solid"], ms=420
    )

    nature = {
        "tree_oak": static(oak_tree(rng), ["object", "solid", "tree"]),
        "bush": static(bush(rng), ["object", "solid"]),
        "rock_small": static(rock(rng, 16), ["object", "solid"]),
        "rock_large": static(rock(rng, 32), ["object", "solid"]),
        "stump": static(stump(rng), ["object", "solid"]),
        "flowers_red": static(flower_patch(rng, "B"), ["object", "decor"]),
        "flowers_yellow": static(flower_patch(rng, "C"), ["object", "decor"]),
        "flowers_white": static(flower_patch(rng, "D"), ["object", "decor"]),
        "fence_post": static(FENCE_POST, ["object", "solid", "built"]),
        "fence_rail": static(FENCE_RAIL, ["object", "solid", "built"]),
        "fence_rail_v": static(transpose(FENCE_RAIL), ["object", "solid", "built"]),
    }

    actors = {
        "player_down": sprite(
            16, 24, walk_pair(PLAYER_DOWN, STRIDE_FRONT), ["actor"], ms=180
        ),
        "player_up": sprite(
            16, 24, walk_pair(PLAYER_UP, STRIDE_FRONT), ["actor"], ms=180
        ),
        "player_right": sprite(
            16, 24, walk_pair(PLAYER_SIDE, STRIDE_SIDE), ["actor"], ms=180
        ),
        "player_left": sprite(
            16,
            24,
            [mirror(f) for f in walk_pair(PLAYER_SIDE, STRIDE_SIDE)],
            ["actor"],
            ms=180,
        ),
    }

    items = {
        "tool_hoe": static(rows_from(TOOL_HOE), ["item", "tool"]),
        "tool_can": static(rows_from(TOOL_CAN), ["item", "tool"]),
        "tool_bow": static(rows_from(TOOL_BOW), ["item", "weapon"]),
        "seed_bag": static(rows_from(SEED_BAG), ["item", "seed"]),
        "arrow": static(rows_from(ARROW), ["projectile"]),
        "bed": static(rows_from(BED), ["object", "solid", "built"]),
        "stall": static(rows_from(STALL), ["object", "solid", "built"]),
        "chest": static(rows_from(CHEST), ["object", "solid", "built"]),
    }
    # Crops: one entry per stage, named <sprite>_<stage>, which is the contract
    # the crop's content file assumes. Three crops, four stages, twelve sprites,
    # and none of them hand-drawn -- adding a fourth crop is one line here.
    for crop_sprite, (leaf, fruit, fruit_hi) in {
        "crop_turnip": ("z", "D", "B"),
        "crop_barley": ("y", "C", "D"),
        "crop_emberbloom": ("x", "B", "C"),
    }.items():
        for index, rows in enumerate(crop_stages(leaf, fruit, fruit_hi)):
            items[f"{crop_sprite}_{index}"] = static(rows, ["crop", crop_sprite])

    foes = {
        "foe_slime": static(slime(rng), ["foe"]),
        "foe_wisp": static(wisp(rng), ["foe"]),
    }

    buildings = {
        "house_player": static(house("B", "s"), ["object", "solid", "built"]),
        "house_town": static(house("H", "K"), ["object", "solid", "built"]),
        "house_village": static(house("v", "s"), ["object", "solid", "built"]),
        "house_farmstead": static(house("u", "w"), ["object", "solid", "built"]),
        "well": static(well_sprite(), ["object", "solid", "built"]),
        "door_mat": static(rows_from(DOOR_MAT), ["object", "decor"]),
        "hearth": static(rows_from(HEARTH), ["object", "solid", "built"]),
        "table": static(rows_from(TABLE), ["object", "solid", "built"]),
        "workbench": static(rows_from(WORKBENCH), ["object", "solid", "built"]),
        "wood_floor": static(wood_floor_tile(rng), ["terrain", "ground", "indoor"]),
        "interior_wall": static(
            interior_wall_tile(rng), ["terrain", "solid", "indoor"]
        ),
        "rug": static(rug_tile(rng), ["terrain", "ground", "indoor"]),
    }

    villagers = {}
    for name, look in VILLAGER_LOOKS.items():
        villagers[name + "_down"] = sprite(
            16, 24, villager(PLAYER_DOWN, STRIDE_FRONT, look), ["actor", "npc"], ms=180
        )
        villagers[name + "_up"] = sprite(
            16, 24, villager(PLAYER_UP, STRIDE_FRONT, look), ["actor", "npc"], ms=180
        )
        villagers[name + "_right"] = sprite(
            16, 24, villager(PLAYER_SIDE, STRIDE_SIDE, look), ["actor", "npc"], ms=180
        )
        villagers[name + "_left"] = sprite(
            16,
            24,
            [mirror(f) for f in villager(PLAYER_SIDE, STRIDE_SIDE, look)],
            ["actor", "npc"],
            ms=180,
        )

    return [
        {
            "id": "emberfield-items",
            "label": "Emberfield — items, tools and crops",
            "tile": TILE,
            "default_palette": SPRING["id"],
            "sprites": items,
        },
        {
            "id": "emberfield-foes",
            "label": "Emberfield — foes",
            "tile": TILE,
            "default_palette": SPRING["id"],
            "sprites": foes,
        },
        {
            "id": "emberfield-terrain",
            "label": "Emberfield — terrain",
            "tile": TILE,
            "default_palette": SPRING["id"],
            "sprites": terrain,
        },
        {
            "id": "emberfield-nature",
            "label": "Emberfield — nature and objects",
            "tile": TILE,
            "default_palette": SPRING["id"],
            "sprites": nature,
        },
        {
            "id": "emberfield-actors",
            "label": "Emberfield — actors",
            "tile": TILE,
            "default_palette": SPRING["id"],
            "sprites": actors,
        },
        {
            "id": "emberfield-buildings",
            "label": "Emberfield — houses and interiors",
            "tile": TILE,
            "default_palette": SPRING["id"],
            "sprites": buildings,
        },
        {
            "id": "emberfield-villagers",
            "label": "Emberfield — villagers",
            "tile": TILE,
            "default_palette": SPRING["id"],
            "sprites": villagers,
        },
    ]


def build_palettes():
    """Seasons and night are the same sprites under different colour.

    Autumn and winter override the growing things explicitly, because a uniform
    channel shift can darken or warm a palette but cannot turn a green canopy
    gold or bury a field in snow.
    """
    summer = derive_palette(
        SPRING,
        "emberfield-summer",
        "Emberfield — summer",
        (1.04, 1.02, 0.94),
        (6, 4, 0),
    )
    autumn = derive_palette(
        SPRING,
        "emberfield-autumn",
        "Emberfield — autumn",
        (1.05, 0.94, 0.80),
        (8, 0, 0),
    )
    autumn["colors"].update(
        {
            "a": "#6b6330",
            "b": "#8a7a38",
            "c": "#a89344",
            "d": "#c4ab52",
            "x": "#7a4a1f",
            "y": "#a5652a",
            "z": "#c98a35",
            "A": "#e0a840",
        }
    )
    winter = derive_palette(
        SPRING,
        "emberfield-winter",
        "Emberfield — winter",
        (0.92, 0.96, 1.06),
        (26, 28, 34),
    )
    winter["colors"].update(
        {
            "a": "#9fb0c0",
            "b": "#c2d0da",
            "c": "#dde7ee",
            "d": "#f2f7fa",
            "x": "#41564f",
            "y": "#5a7166",
            "z": "#7b9184",
            "A": "#a8bcae",
        }
    )
    night = derive_palette(
        SPRING,
        "emberfield-night",
        "Emberfield — night",
        (0.52, 0.56, 0.80),
        (12, 16, 40),
        keep=("B", "C", "D"),  # lantern-lit flowers keep a little of their colour
    )
    return [SPRING, summer, autumn, winter, night]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite files that already exist (this discards your edits)",
    )
    args = parser.parse_args()

    root = forge_art.ensure_root()
    written, skipped, problems = [], [], []

    for palette in build_palettes():
        path = forge_art.palette_path(palette["id"])
        if os.path.exists(path) and not args.force:
            skipped.append(os.path.basename(path))
            continue
        problems += [
            f"{palette['id']}: {p}" for p in forge_art.validate_palette(palette)
        ]
        forge_art.save_palette(palette)
        written.append(os.path.basename(path))

    for pack in build_packs():
        path = forge_art.pack_path(pack["id"])
        if os.path.exists(path) and not args.force:
            skipped.append(os.path.basename(path))
            continue
        problems += [
            f"{pack['id']}: {p}" for p in forge_art.validate_pack(pack, SPRING)
        ]
        forge_art.save_pack(pack)
        written.append(os.path.basename(path))

    print(f"art root: {root}")
    for name in written:
        print(f"  wrote   {name}")
    for name in skipped:
        print(f"  kept    {name}  (already exists; --force to replace)")
    if problems:
        print("\nvalidation problems:")
        for problem in problems[:20]:
            print(f"  ! {problem}")
        return 1
    print("\nall packs and palettes validate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
