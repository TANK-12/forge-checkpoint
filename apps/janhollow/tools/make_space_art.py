"""Generate Janhollow's space art: ships, planets, moons, stars and event props.

Why this exists: the station and crew packs cover the deck a player walks on,
but Janhollow also has a starfield -- ships docking, a planet out the
viewport, an event prop dropped on the floor when something happens (mail
arrives, a pipe bursts, someone's birthday comes around). This generator
draws that set into a fourth pack, `janhollow-space`, following the same
model as `make_art32.py`: every sprite is palette-indexed rows, generated
procedurally from a name-seeded `random.Random` so the pack is
byte-identical across regenerations and never hand-edited pixel by pixel.

It deliberately reuses the `janhollow` palette that `make_art32.py` already
wrote (hull blue-grey, a teal accent, a warm-amber ramp, a rust ramp, and
glass/space tones) rather than defining a second one. That palette turns out
to cover space fine: the teal ramp doubles as ocean and engine glow, the rust
ramp doubles as derelict hull and a red dwarf's dim coal-like glow, and the
glass ramp doubles as ice and windows. No new colours are added.

Ships are drawn top-down (nose at the top, engines at the bottom), since the
game's camera looks straight down. Each ship is a width profile -- a list of
(y-fraction, half-width-fraction) points -- rasterised into a hull, shaded
left-to-right as if lit from the left, with a seam down the centreline,
running lights, windows and an engine glow at the stern. The same profile
function draws both the 64px and 32px version of a ship, so the two sizes
agree in shape.

Planets and moons are spheres: for every pixel inside the disc, the light
direction (fixed at upper-left) and the distance from the limb together pick
a shade band, which is what gives a round disc an actual terminator instead
of a flat tinted circle. Gas giant bands and ocean-world continents are
painted on top of that base shading, not instead of it.

    .venv/bin/python tools/make_space_art.py [--force]
"""

import math
import os
import random
import sys

SHARED_DIR = os.environ.get("FORGE_SHARED_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "..", "shared"
)
sys.path.insert(0, os.path.abspath(SHARED_DIR))

import forge_art  # noqa: E402

PACK_ID = "janhollow-space"
PALETTE_ID = "janhollow"

# Ramps within the existing janhollow palette, each ordered dark -> light.
HULL = ["a", "b", "c", "d", "e", "f", "g", "h"]
FLOOR = ["i", "j", "k", "l", "m", "n"]
TEAL = ["o", "p", "q", "r", "s", "t"]
WARM = ["u", "v", "w", "x", "y"]
RUST = ["z", "A", "B"]
GLASS = ["F", "E", "C", "D"]
SPACE = "G"
SHADOW = "H"


def rng_for(name):
    return random.Random(hash(name) & 0xFFFFFFFF)


def canvas(w, h, fill="."):
    return [[fill] * w for _ in range(h)]


def rows_of(grid):
    return ["".join(row) for row in grid]


def dims(grid):
    return len(grid[0]), len(grid)


def set_px(grid, x, y, key):
    w, h = dims(grid)
    if 0 <= x < w and 0 <= y < h:
        grid[y][x] = key


def get_px(grid, x, y):
    w, h = dims(grid)
    if 0 <= x < w and 0 <= y < h:
        return grid[y][x]
    return "."


def rect(grid, x, y, w, h, key, fill=True):
    gw, gh = dims(grid)
    for ty in range(y, min(gh, y + h)):
        for tx in range(x, min(gw, x + w)):
            if tx < 0 or ty < 0:
                continue
            if fill or ty in (y, y + h - 1) or tx in (x, x + w - 1):
                grid[ty][tx] = key


def hline(grid, y, x0, x1, key):
    w, _ = dims(grid)
    if 0 <= y < len(grid):
        for x in range(max(0, x0), min(w, x1 + 1)):
            grid[y][x] = key


def vline(grid, x, y0, y1, key):
    _, h = dims(grid)
    if 0 <= x < len(grid[0]):
        for y in range(max(0, y0), min(h, y1 + 1)):
            grid[y][x] = key


def speckle(grid, rng, keys, count, area=None):
    w, h = dims(grid)
    x0, y0, x1, y1 = area or (0, 0, w - 1, h - 1)
    for _ in range(count):
        x = rng.randint(x0, x1)
        y = rng.randint(y0, y1)
        grid[y][x] = rng.choice(keys)


# --- ships -------------------------------------------------------------


def _width_at(profile, yf):
    pts = sorted(profile, key=lambda p: p[0])
    for i in range(len(pts) - 1):
        y0, w0 = pts[i]
        y1, w1 = pts[i + 1]
        if y0 <= yf <= y1:
            if y1 == y0:
                return w0
            t = (yf - y0) / (y1 - y0)
            return w0 + (w1 - w0) * t
    return pts[-1][1]


def ship_hull(S, profile, ramp):
    """Rasterise a width profile into a hull, lit from the left."""
    grid = canvas(S, S)
    cx = (S - 1) / 2
    n = len(ramp)
    for y in range(S):
        yf = y / (S - 1)
        hw = _width_at(profile, yf) * S / 2
        if hw <= 0:
            continue
        left, right = cx - hw, cx + hw
        width = max(right - left, 1.0)
        for x in range(S):
            if left - 0.4 <= x <= right + 0.4:
                t = (x - left) / width
                shade = 1 - min(1.0, max(0.0, t))
                idx = int(round(shade * (n - 1)))
                grid[y][x] = ramp[max(0, min(n - 1, idx))]
    return grid


def _decorate_ship(grid, S, profile, rng, ramp, accent, lamp, glass, engine_rows=3):
    cx = (S - 1) / 2
    # centreline seam, darkest tone, wherever the hull is at least 3 wide
    for y in range(S):
        yf = y / (S - 1)
        hw = _width_at(profile, yf) * S / 2
        if hw >= 1.5:
            set_px(grid, int(round(cx)), y, ramp[0])
    # nose windows: a couple of bright dots just aft of the bow
    nose_y = max(1, round(S * 0.10))
    for dx in (-1, 1) if S >= 32 else (0,):
        set_px(grid, int(round(cx)) + dx, nose_y, glass)
    set_px(grid, int(round(cx)), nose_y + max(1, S // 32), glass)
    # running lights along the flanks, evenly spaced
    step = max(4, S // 6)
    for y in range(nose_y + 2, S - 2, step):
        yf = y / (S - 1)
        hw = _width_at(profile, yf) * S / 2
        if hw >= 2:
            set_px(grid, int(round(cx - hw)) + 1, y, lamp)
            set_px(grid, int(round(cx + hw)) - 1, y, lamp)
    # engine glow at the stern
    for i in range(engine_rows):
        y = S - 1 - i
        yf = y / (S - 1)
        hw = _width_at(profile, yf) * S / 2
        if hw < 1:
            continue
        glow = accent[max(0, len(accent) - 1 - i)]
        for x in range(int(round(cx - hw * 0.6)), int(round(cx + hw * 0.6)) + 1):
            set_px(grid, x, y, glow)
    speckle(grid, rng, [ramp[1], ramp[-2]], max(3, S // 6))
    return grid


def ship_shuttle(name, S):
    rng = rng_for(name)
    profile = [(0.0, 0.10), (0.12, 0.55), (0.55, 0.62), (0.85, 0.30), (1.0, 0.22)]
    grid = ship_hull(S, profile, HULL)
    grid = _decorate_ship(grid, S, profile, rng, HULL, TEAL, WARM[-1], GLASS[-1])
    # a pair of stubby wings at the widest point -- what breaks the pod
    # silhouette and makes it read as a craft rather than a seed
    cx = (S - 1) / 2
    wy0, wy1 = round(S * 0.42), round(S * 0.58)
    hw = _width_at(profile, 0.5) * S / 2
    span = max(2, round(S * 0.12))
    for y in range(wy0, wy1):
        set_px(grid, int(cx - hw) - 1, y, HULL[2])
        set_px(grid, int(cx - hw) - span, y, HULL[3])
        set_px(grid, int(cx + hw) + 1, y, HULL[2])
        set_px(grid, int(cx + hw) + span, y, HULL[3])
    hline(grid, wy0, int(cx - hw) - span, int(cx - hw) - 1, HULL[2])
    hline(grid, wy0, int(cx + hw) + 1, int(cx + hw) + span, HULL[2])
    hline(grid, wy1 - 1, int(cx - hw) - span, int(cx - hw) - 1, HULL[1])
    hline(grid, wy1 - 1, int(cx + hw) + 1, int(cx + hw) + span, HULL[1])
    return grid


def ship_barge(name, S):
    rng = rng_for(name)
    # near-vertical jumps between points read as a blocky hull, not a teardrop
    profile = [
        (0.0, 0.20),
        (0.06, 0.70),
        (0.08, 0.78),
        (0.80, 0.78),
        (0.84, 0.55),
        (0.92, 0.55),
        (1.0, 0.34),
    ]
    grid = ship_hull(S, profile, HULL)
    grid = _decorate_ship(grid, S, profile, rng, HULL, TEAL, WARM[-1], GLASS[-1], 2)
    # cargo pod seams across the wide midsection
    cx = (S - 1) / 2
    for frac in (0.24, 0.40, 0.56, 0.72):
        y = round(S * frac)
        hw = _width_at(profile, frac) * S / 2
        hline(grid, y, int(cx - hw) + 2, int(cx + hw) - 2, HULL[0])
    return grid


def ship_hauler(name, S):
    rng = rng_for(name)
    profile = [
        (0.0, 0.14),
        (0.08, 0.34),
        (0.35, 0.40),
        (0.50, 0.68),
        (0.85, 0.60),
        (1.0, 0.40),
    ]
    grid = ship_hull(S, profile, HULL)
    grid = _decorate_ship(grid, S, profile, rng, HULL, TEAL, WARM[-1], GLASS[-1], 2)
    # two long tow rails down the aft hold
    cx = (S - 1) / 2
    rail = max(3, round(S * 0.18))
    vline(grid, int(cx - rail), round(S * 0.45), S - 3, HULL[0])
    vline(grid, int(cx + rail), round(S * 0.45), S - 3, HULL[0])
    return grid


def ship_courier(name, S):
    rng = rng_for(name)
    profile = [(0.0, 0.06), (0.18, 0.28), (0.45, 0.24), (0.70, 0.34), (1.0, 0.16)]
    grid = ship_hull(S, profile, HULL)
    return _decorate_ship(grid, S, profile, rng, HULL, TEAL, GLASS[-1], GLASS[-1], 2)


def ship_wreck(name, S):
    rng = rng_for(name)
    profile = [(0.0, 0.12), (0.20, 0.50), (0.55, 0.58), (0.85, 0.32), (1.0, 0.20)]
    grid = ship_hull(S, profile, RUST + [RUST[-1]] * 2)
    grid = _decorate_ship(
        grid, S, profile, rng, RUST + [RUST[-1]] * 2, RUST, WARM[2], HULL[0], 1
    )
    # battle damage: punch ragged clusters of holes clean through the hull,
    # not just single pixels, so it reads as torn metal rather than noise
    clusters = max(3, S // 12)
    for _ in range(clusters):
        cx_h = rng.randint(2, S - 3)
        cy_h = rng.randint(2, S - 3)
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                if rng.random() < 0.6 and get_px(grid, cx_h + dx, cy_h + dy) != ".":
                    set_px(grid, cx_h + dx, cy_h + dy, ".")
    # a bite taken clean out of one flank
    bite_y = round(S * 0.35)
    yf = bite_y / (S - 1)
    hw = _width_at(profile, yf) * S / 2
    cx = (S - 1) / 2
    for y in range(bite_y, min(S, bite_y + max(3, S // 8))):
        for x in range(int(cx + hw) - max(3, S // 10), S):
            set_px(grid, x, y, ".")
    # embers of a fire that hasn't quite gone out
    for dx, dy in ((0, 0), (1, -1), (-1, 2)):
        set_px(grid, S // 2 + dx, round(S * 0.4) + dy, WARM[-1])
    return grid


SHIPS = {
    "ship_shuttle": ship_shuttle,
    "ship_barge": ship_barge,
    "ship_hauler": ship_hauler,
    "ship_courier": ship_courier,
    "ship_wreck": ship_wreck,
}
SHIP_SIZES = (64, 32)


# --- planets and moons ---------------------------------------------------


def sphere(S, rng, ramp, limb_darken=0.30, craters=None, band_fn=None):
    """A shaded disc: light fixed at upper-left, with limb darkening for a
    real terminator rather than a flat tinted circle."""
    grid = canvas(S, S)
    r = S / 2 - 1
    cx = cy = (S - 1) / 2
    n = len(ramp)
    inv_sqrt2 = 1 / math.sqrt(2)
    for y in range(S):
        for x in range(S):
            dx, dy = x - cx, y - cy
            dist = math.hypot(dx, dy)
            if dist > r:
                continue
            ld = 1.0 if dist == 0 else (-dx - dy) / dist * inv_sqrt2
            edge = dist / r
            t = (ld + 1) / 2 - edge * limb_darken
            idx = int(round(t * (n - 1)))
            idx = max(0, min(n - 1, idx))
            key = ramp[idx]
            if band_fn:
                override = band_fn(x, y, dx, dy, dist, r, idx, n)
                if override:
                    key = override
            grid[y][x] = key
    if craters:
        keys, count = craters
        placed = 0
        tries = 0
        while placed < count and tries < count * 8:
            tries += 1
            x = rng.randint(0, S - 1)
            y = rng.randint(0, S - 1)
            if math.hypot(x - cx, y - cy) <= r - 1:
                set_px(grid, x, y, rng.choice(keys))
                placed += 1
    return grid


def planet_rocky(name, S=64):
    rng = rng_for(name)

    def bands(x, y, dx, dy, dist, r, idx, n):
        if rng.random() < 0.015:
            return HULL[max(0, idx - 2)]
        return None

    grid = sphere(S, rng, HULL, 0.35, craters=(RUST[:2], round(S * 0.9)))
    return grid


def planet_ocean(name, S=64):
    rng = rng_for(name)
    grid = sphere(S, rng, TEAL, 0.30)
    r = S / 2 - 1
    cx = cy = (S - 1) / 2
    # a few continents: irregular clusters of hull-coloured land
    for _ in range(round(S / 16)):
        lx = rng.randint(int(cx - r * 0.6), int(cx + r * 0.6))
        ly = rng.randint(int(cy - r * 0.6), int(cy + r * 0.6))
        if math.hypot(lx - cx, ly - cy) > r - 3:
            continue
        blob = rng.randint(3, max(4, S // 8))
        for _ in range(blob):
            x = lx + rng.randint(-3, 3)
            y = ly + rng.randint(-3, 3)
            if math.hypot(x - cx, y - cy) <= r - 1:
                lit = 1 if (-((x - cx) + (y - cy))) >= 0 else 0
                set_px(grid, x, y, HULL[3 + lit])
    return grid


def planet_gas(name, S=64):
    rng = rng_for(name)
    band_ramp = WARM + [RUST[1]]

    def bands(x, y, dx, dy, dist, r, idx, n):
        band = int((y + dx * 0.15) // max(2, S // 16)) % len(band_ramp)
        base = band_ramp[band]
        # keep the terminator readable: bias band brightness by light side
        return base

    grid = sphere(S, rng, WARM, 0.30, band_fn=bands)
    # a storm spot
    r = S / 2 - 1
    cx = cy = (S - 1) / 2
    sx, sy = round(cx - r * 0.2), round(cy + r * 0.15)
    for dx in range(-2, 3):
        for dy in range(-1, 2):
            if math.hypot(sx + dx - cx, sy + dy - cy) <= r - 1:
                set_px(grid, sx + dx, sy + dy, RUST[1])
    return grid


def planet_ice(name, S=64):
    rng = rng_for(name)
    grid = sphere(S, rng, GLASS, 0.25, craters=(HULL[3:5], round(S * 0.5)))
    return grid


PLANETS = {
    "planet_rocky": planet_rocky,
    "planet_ocean": planet_ocean,
    "planet_gas": planet_gas,
    "planet_ice": planet_ice,
}


def moon(name, S=32):
    rng = rng_for(name)
    return sphere(S, rng, HULL[2:], 0.35, craters=(HULL[1:3], round(S * 0.8)))


MOONS = ["moon_a", "moon_b", "moon_c"]


# --- stars -----------------------------------------------------------------


def star(name, S, ramp, core):
    rng = rng_for(name)
    grid = canvas(S, S)
    cx = cy = (S - 1) / 2
    r = S / 2
    n = len(ramp)
    for y in range(S):
        for x in range(S):
            dx, dy = x - cx, y - cy
            dist = math.hypot(dx, dy)
            if dist > r:
                continue
            t = 1 - min(1.0, dist / r)
            idx = int(round(t * (n - 1)))
            grid[y][x] = ramp[max(0, min(n - 1, idx))]
    set_px(grid, round(cx), round(cy), core)
    # a soft bloom: a few dim pixels flaring past the disc
    spikes = max(2, S // 8)
    for _ in range(spikes):
        ang = rng.uniform(0, 2 * math.pi)
        dist = r + rng.uniform(0.5, r * 0.6)
        x = round(cx + math.cos(ang) * dist)
        y = round(cy + math.sin(ang) * dist)
        set_px(grid, x, y, ramp[0])
    return grid


STARS = {
    "star_yellow": lambda name, S: star(name, S, WARM, WARM[-1]),
    "star_dwarf": lambda name, S: star(name, S, RUST + [WARM[1]], WARM[1]),
    "star_blue": lambda name, S: star(name, S, GLASS, "D"),
}
STAR_SIZES = (32, 16)

STAR_POINTS = {
    "star_point_dim": "h",
    "star_point_mid": "t",
    "star_point_bright": "D",
}


# --- event props -------------------------------------------------------


def crate_stack(name, S=32):
    rng = rng_for(name)
    grid = canvas(S, S)
    boxes = [(2, 14, 16, 16), (12, 6, 15, 15), (4, 2, 14, 12)]
    for i, (x, y, w, h) in enumerate(boxes):
        rect(grid, x, y, w, h, HULL[3])
        rect(grid, x, y, w, h, HULL[2], fill=False)
        hline(grid, y + 1, x + 1, x + w - 2, HULL[4])
        vline(grid, x + 1, y + 1, y + h - 2, HULL[4])
        rect(grid, x + w // 2 - 1, y + 2, 2, h - 4, RUST[1])
        set_px(grid, x + 2, y + 2, TEAL[3])
    speckle(grid, rng, [HULL[1], HULL[4]], 10)
    return grid


def mail_sack(name, S=32):
    rng = rng_for(name)
    grid = canvas(S, S)
    cx = S // 2
    for y in range(10, S - 3):
        width = (
            round(9 - abs(y - (S - 3)) * 0.15) if y > 20 else round(6 + (y - 10) * 0.3)
        )
        width = max(3, min(10, width))
        hline(grid, y, cx - width, cx + width, RUST[1])
    for y in range(10, S - 3):
        w, _ = dims(grid)
        left = min((x for x in range(w) if grid[y][x] != "."), default=None)
        if left is not None:
            grid[y][left] = RUST[0]
    vline(grid, cx - 3, 5, 11, HULL[0])
    hline(grid, 5, cx - 5, cx + 5, HULL[0])
    for x in range(cx - 4, cx + 5, 2):
        set_px(grid, x, 7, RUST[2])
    set_px(grid, cx + 3, 16, TEAL[3])
    speckle(grid, rng, [RUST[0], RUST[2]], 14, (cx - 9, 10, cx + 9, S - 3))
    return grid


def toolbox(name, S=32):
    rng = rng_for(name)
    grid = canvas(S, S)
    rect(grid, 4, 14, 24, 12, HULL[3])
    rect(grid, 4, 14, 24, 2, HULL[4])
    rect(grid, 4, 24, 24, 2, HULL[1])
    for x in range(6, 27, 4):
        vline(grid, x, 15, 25, HULL[2])
    # handle arc, a shade lighter than the box so it doesn't vanish into it
    vline(grid, 11, 6, 13, HULL[1])
    vline(grid, 20, 6, 13, HULL[1])
    rect(grid, 11, 6, 10, 2, HULL[1])
    # latches
    set_px(grid, 9, 19, WARM[3])
    set_px(grid, 22, 19, WARM[3])
    set_px(grid, 9, 20, WARM[2])
    set_px(grid, 22, 20, WARM[2])
    speckle(grid, rng, [HULL[2], HULL[4]], 8, (5, 15, 26, 25))
    return grid


def coolant_puddle(name, S=32):
    rng = rng_for(name)
    grid = canvas(S, S)
    cx, cy = S // 2, S // 2 + 2
    for y in range(S):
        for x in range(S):
            dx, dy = (x - cx) / 1.6, (y - cy) / 1.0
            dist = math.hypot(dx, dy)
            if dist <= 8:
                grid[y][x] = TEAL[1]
            elif dist <= 9.5 and rng.random() < 0.5:
                grid[y][x] = TEAL[0]
    for _ in range(6):
        x = cx + rng.randint(-5, 5)
        y = cy + rng.randint(-4, 4)
        if get_px(grid, x, y) != ".":
            set_px(grid, x, y, TEAL[4])
    set_px(grid, cx - 2, cy - 1, TEAL[5])
    return grid


def sapling(name, S=32):
    rng = rng_for(name)
    grid = canvas(S, S)
    cx = S // 2
    rect(grid, cx - 6, 22, 12, 8, RUST[1])
    rect(grid, cx - 6, 22, 12, 2, RUST[2])
    rect(grid, cx - 6, 28, 12, 2, RUST[0])
    vline(grid, cx, 16, 22, RUST[1])
    leaves = [
        (cx, 12, TEAL[3]),
        (cx - 3, 14, TEAL[2]),
        (cx + 3, 14, TEAL[2]),
        (cx, 15, TEAL[4]),
        (cx - 2, 11, TEAL[4]),
        (cx + 2, 11, TEAL[4]),
        (cx, 9, TEAL[5]),
        (cx - 4, 16, TEAL[1]),
        (cx + 4, 16, TEAL[1]),
    ]
    for x, y, key in leaves:
        set_px(grid, x, y, key)
        set_px(grid, x + 1, y, key)
    speckle(grid, rng, [TEAL[2], TEAL[3]], 10, (cx - 5, 8, cx + 5, 17))
    return grid


def cake(name, S=32):
    rng = rng_for(name)
    grid = canvas(S, S)
    cx, cy = S // 2, 20
    for y in range(14, 26):
        for x in range(S):
            if math.hypot((x - cx) / 11.0, (y - cy) / 6.0) <= 1:
                grid[y][x] = WARM[3]
    hline(grid, 14, cx - 10, cx + 10, WARM[4])
    hline(grid, 25, cx - 8, cx + 8, WARM[1])
    for x in range(cx - 9, cx + 10, 3):
        set_px(grid, x, 20, RUST[1])
    for cxi in (cx - 6, cx, cx + 6):
        vline(grid, cxi, 8, 13, HULL[3])
        set_px(grid, cxi, 7, WARM[4])
        set_px(grid, cxi, 6, "D")
    speckle(grid, rng, [WARM[2], WARM[4]], 8, (cx - 9, 15, cx + 9, 24))
    return grid


def broken_panel(name, S=32):
    rng = rng_for(name)
    grid = canvas(S, S)
    rect(grid, 3, 3, S - 6, S - 6, HULL[2])
    rect(grid, 3, 3, S - 6, S - 6, HULL[1], fill=False)
    # a jagged crack from corner to corner
    x, y = 5, 5
    while x < S - 5 and y < S - 5:
        set_px(grid, x, y, "G")
        set_px(grid, x + 1, y, HULL[0])
        x += rng.choice([1, 1, 2])
        y += rng.choice([1, 2])
    # exposed wiring
    vline(grid, 10, 8, 20, TEAL[2])
    vline(grid, 11, 8, 20, RUST[1])
    for _ in range(6):
        px = rng.randint(4, S - 5)
        py = rng.randint(4, S - 5)
        set_px(grid, px, py, ".")
    # sparks
    sx, sy = S - 10, 10
    for _ in range(7):
        ang = rng.uniform(0, 2 * math.pi)
        length = rng.randint(2, 6)
        ex = round(sx + math.cos(ang) * length)
        ey = round(sy + math.sin(ang) * length)
        set_px(grid, ex, ey, rng.choice([WARM[4], "D"]))
    set_px(grid, sx, sy, "D")
    return grid


PROPS = {
    "crate_stack": crate_stack,
    "mail_sack": mail_sack,
    "toolbox": toolbox,
    "coolant_puddle": coolant_puddle,
    "sapling": sapling,
    "cake": cake,
    "broken_panel": broken_panel,
}


def build_sprites():
    sprites = {}
    for base, fn in SHIPS.items():
        for S in SHIP_SIZES:
            name = f"{base}_{S}"
            sprites[name] = {
                "w": S,
                "h": S,
                "tags": ["ship", base.split("_", 1)[1]],
                "frames": [{"ms": 0, "rows": rows_of(fn(name, S))}],
            }
    for name, fn in PLANETS.items():
        sprites[name] = {
            "w": 64,
            "h": 64,
            "tags": ["planet", name.split("_", 1)[1]],
            "frames": [{"ms": 0, "rows": rows_of(fn(name, 64))}],
        }
    for name in MOONS:
        sprites[name] = {
            "w": 32,
            "h": 32,
            "tags": ["moon"],
            "frames": [{"ms": 0, "rows": rows_of(moon(name, 32))}],
        }
    for base, fn in STARS.items():
        for S in STAR_SIZES:
            name = f"{base}_{S}"
            sprites[name] = {
                "w": S,
                "h": S,
                "tags": ["star", base.split("_", 1)[1]],
                "frames": [{"ms": 0, "rows": rows_of(fn(name, S))}],
            }
    for name, key in STAR_POINTS.items():
        sprites[name] = {
            "w": 1,
            "h": 1,
            "tags": ["star", "point"],
            "frames": [{"ms": 0, "rows": [key]}],
        }
    for name, fn in PROPS.items():
        sprites[name] = {
            "w": 32,
            "h": 32,
            "tags": ["prop", "event"],
            "frames": [{"ms": 0, "rows": rows_of(fn(name, 32))}],
        }
    return sprites


def main():
    force = "--force" in sys.argv
    forge_art.ensure_root()
    if os.path.exists(forge_art.pack_path(PACK_ID)) and not force:
        print(f"{PACK_ID} exists; pass --force to rebuild")
        return

    # Reuse the janhollow palette as-is; fail loudly if it has moved.
    forge_art.load_palette(PALETTE_ID)

    sprites = build_sprites()
    forge_art.save_pack(
        {
            "id": PACK_ID,
            "label": "Janhollow — space",
            "tile": 32,
            "default_palette": PALETTE_ID,
            "sprites": sprites,
        }
    )
    print(f"wrote {PACK_ID}: {len(sprites)} sprites")


if __name__ == "__main__":
    if {"-h", "--help"} & set(sys.argv[1:]):  # usage only, no work
        print(__doc__)
        sys.exit(0)
    main()
