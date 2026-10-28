"""Attractors, the Python half: the same map, hunt, Lyapunov exponent and
density render as sprott.js / render.js, so a Claude session can hunt and
look at the result as a PNG without a browser.

    play.py attractors hunt [--seed N] [--keep NAME] [--note T] [--palette P]
    play.py attractors render CODE [--palette P] [--size WxH] [--points N]
    play.py attractors keep CODE --name N [--note T] [--palette P]

The sums run in the same order as the JS, so for the same code both sides
walk the same orbit and agree on the exponent (bits per iteration). The
random codes come from the same mulberry32 stream as curios/_kit/rng.js, so
`hunt --seed 1` finds the same attractor as the browser's hunt with seed 1.
Nothing happens at import; files are only written under store.data_dir().
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

import kit
import store

HERE = Path(__file__).resolve().parent
CURIO = "attractors"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXY"
ESCAPE = 1e6
FIXED = 1e-10
SEPARATION = 1e-6
CHAOS = 0.005
ITERATIONS = 12000
TRANSIENT = 1000
SAMPLE = 800
MIN_DIMENSION = 1.1
EXPOSURE = 1.25
GAMMA = 1.25
MASK = 0xFFFFFFFF

router = APIRouter()


# --- codes and the seeded stream ----------------------------------------------


def is_code(text: object) -> bool:
    if not isinstance(text, str):
        return False
    t = text.strip().upper()
    return len(t) == 12 and all(ch in LETTERS for ch in t)


def decode(code: str) -> list[float]:
    if not is_code(code):
        raise ValueError("a code is 12 letters from A to Y")
    return [(LETTERS.index(ch) - 12) / 10 for ch in code.strip().upper()]


def encode(coeffs: list[float]) -> str:
    return "".join(
        LETTERS[round(min(1.2, max(-1.2, float(v))) * 10) + 12] for v in coeffs
    )


def mulberry32(seed: int) -> Callable[[], float]:
    """The same stream as rng() in curios/_kit/rng.js."""
    state = seed & MASK

    def nxt() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & MASK
        t = state
        t = ((t ^ (t >> 15)) * (t | 1)) & MASK
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & MASK)) & MASK
        return ((t ^ (t >> 14)) & MASK) / 4294967296

    return nxt


def random_code(r: Callable[[], float]) -> str:
    return "".join(LETTERS[math.floor(r() * 25)] for _ in range(12))


# --- the map --------------------------------------------------------------------


def analyse(
    a: list[float],
    iterations: int = ITERATIONS,
    transient: int = TRANSIENT,
    sample: int = SAMPLE,
) -> dict[str, Any]:
    """Classify the orbit from (0.05, 0.05); see analyse() in sprott.js."""
    x = y = 0.05
    xe, ye = x + SEPARATION, y
    lsum = 0.0
    n = 0
    xmin = ymin = math.inf
    xmax = ymax = -math.inf
    stride = max(1, (iterations - transient) // max(1, sample))
    pts: list[tuple[float, float]] = []
    a0, a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11 = a
    for i in range(1, iterations + 1):
        xn = a0 + a1 * x + a2 * x * x + a3 * x * y + a4 * y + a5 * y * y
        yn = a6 + a7 * x + a8 * x * x + a9 * x * y + a10 * y + a11 * y * y
        if not abs(xn) + abs(yn) <= ESCAPE:
            return {
                "status": "escapes",
                "lyapunov": None,
                "bounds": None,
                "sample": [],
                "at": i,
            }
        if abs(xn - x) + abs(yn - y) < FIXED:
            return {
                "status": "fixed",
                "lyapunov": None,
                "bounds": [xn, xn, yn, yn],
                "sample": [(xn, yn)],
                "at": i,
            }
        xs = a0 + a1 * xe + a2 * xe * xe + a3 * xe * ye + a4 * ye + a5 * ye * ye
        ys = a6 + a7 * xe + a8 * xe * xe + a9 * xe * ye + a10 * ye + a11 * ye * ye
        dx = xs - xn
        dy = ys - yn
        d = math.sqrt(dx * dx + dy * dy)
        # met exactly: no sample, a fresh direction (see analyse() in sprott.js)
        met = d == 0
        if met:
            dx, dy = -(ye - y), xe - x
            d = math.sqrt(dx * dx + dy * dy)
            if d == 0:
                dx, dy, d = SEPARATION, 0.0, SEPARATION
        if i > transient:
            if not met:
                lsum += math.log(d / SEPARATION)
                n += 1
            xmin, xmax = min(xmin, xn), max(xmax, xn)
            ymin, ymax = min(ymin, yn), max(ymax, yn)
            if (i - transient) % stride == 0 and len(pts) < sample:
                pts.append((xn, yn))
        xe = xn + SEPARATION * dx / max(d, 1e-300)
        ye = yn + SEPARATION * dy / max(d, 1e-300)
        x, y = xn, yn
    lyap = lsum / n / math.log(2) if n else 0.0
    status = "chaotic"
    if lyap < -CHAOS:
        status = "cycle"
    elif lyap <= CHAOS:
        status = "loop"
    return {
        "status": status,
        "lyapunov": lyap,
        "bounds": [xmin, xmax, ymin, ymax],
        "sample": pts,
        "at": iterations,
    }


def dimension(
    sample: list[tuple[float, float]], bounds: list[float] | None
) -> float | None:
    """Correlation dimension from radii at 2% and 20% of the larger side."""
    if not bounds or len(sample) < 50:
        return None
    size = max(bounds[1] - bounds[0], bounds[3] - bounds[2])
    if not size > 0:
        return None
    r1, r2 = 0.02 * size, 0.2 * size
    q1, q2 = r1 * r1, r2 * r2
    c1 = c2 = 0
    for i, (xi, yi) in enumerate(sample):
        for xj, yj in sample[i + 1 :]:
            dx = xj - xi
            dy = yj - yi
            q = dx * dx + dy * dy
            if q < q2:
                c2 += 1
                if q < q1:
                    c1 += 1
    if c1 < 10:
        return None
    return math.log(c2 / c1) / math.log(r2 / r1)


def try_code(code: str, min_dimension: float = MIN_DIMENSION) -> dict[str, Any]:
    coeffs = decode(code)
    result = analyse(coeffs)
    dim = None
    if result["status"] == "chaotic":
        dim = dimension(result["sample"], result["bounds"])
    accepted = (
        result["status"] == "chaotic" and dim is not None and dim >= min_dimension
    )
    return {
        "code": code,
        "coeffs": coeffs,
        "result": result,
        "dimension": dim,
        "accepted": accepted,
    }


def hunt(
    seed: int, min_dimension: float = MIN_DIMENSION, max_tries: int = 20000
) -> dict[str, Any] | None:
    """The first accepted find from a seed, like hunt() in sprott.js."""
    r = mulberry32(seed)
    for tried in range(1, max_tries + 1):
        found = try_code(random_code(r), min_dimension)
        if found["accepted"]:
            return {**found, "tried": tried}
    return None


def describe(lyapunov: float | None, dim: float | None) -> list[str]:
    """The same two lines as describe() in sprott.js."""
    lt = "?" if lyapunov is None else f"{lyapunov:.3f}"
    dt = "unknown" if dim is None else f"about {dim:.2f}"
    first = f"Lyapunov exponent {lt} bits per iteration, correlation dimension {dt}."
    shape = "a dusting of points"
    if dim is not None:
        if dim < 1.15:
            shape = "fine threads, nearly a curve"
        elif dim < 1.4:
            shape = "folded ribbons"
        elif dim < 1.7:
            shape = "a smoky cloud of folds"
        else:
            shape = "a dense veil that almost fills its patch"
    pace = "and drifts apart slowly"
    if lyapunov is not None:
        if lyapunov >= 0.4:
            pace = "and scrambles neighbours fast"
        elif lyapunov >= 0.15:
            pace = "and stirs at a steady pace"
    return [first, f"It looks like {shape}, {pace}."]


NOT_CHAOTIC = {
    "loop": "it goes round a closed loop",
    "cycle": "it repeats a cycle of points",
    "fixed": "it settles to one point",
    "escapes": "it flies off to infinity",
}


def summary(status: str, lyapunov: float | None, dim: float | None) -> list[str]:
    """describe() for a chaotic find; plain words for anything else, which
    is no strange attractor and must not be described as one."""
    if status == "chaotic":
        return describe(lyapunov, dim)
    lines = []
    if lyapunov is not None:
        lines.append(f"Lyapunov exponent {lyapunov:.3f} bits per iteration.")
    lines.append(f"Not chaotic: {NOT_CHAOTIC.get(status, status)}.")
    return lines


# --- rendering ------------------------------------------------------------------


def palettes() -> dict[str, Any]:
    return json.loads((HERE / "palettes.json").read_text(encoding="utf-8"))


def tone_index(
    count: int,
    peak: int,
    exposure: float = EXPOSURE,
    gamma: float = GAMMA,
    fade: float = 1.0,
) -> int:
    if count <= 0 or peak <= 0:
        return 0
    v = min(1.0, math.log1p(count) / math.log1p(peak) * exposure * fade)
    return round(v ** (1 / gamma) * 255)


def render_rgb(
    coeffs: list[float],
    width: int,
    height: int,
    points: int = 1_000_000,
    palette: str = "ember",
    exposure: float = EXPOSURE,
    gamma: float = GAMMA,
) -> bytearray:
    """An RGB image of the attractor's density (needs a bounded orbit)."""
    info = analyse(coeffs)
    if info["bounds"] is None:
        raise ValueError("this map flies off to infinity; there is nothing to draw")
    x0, x1, y0, y1 = info["bounds"]
    bw, bh = max(x1 - x0, 1e-3), max(y1 - y0, 1e-3)
    margin = 0.07
    s = min(width * (1 - 2 * margin) / bw, height * (1 - 2 * margin) / bh)
    ox = width / 2 - (x0 + x1) / 2 * s
    oy = height / 2 + (y0 + y1) / 2 * s
    hist = [0] * (width * height)
    x, y = info["sample"][-1] if info["sample"] else (0.05, 0.05)
    a0, a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11 = coeffs
    for _ in range(points):
        xn = a0 + a1 * x + a2 * x * x + a3 * x * y + a4 * y + a5 * y * y
        y = a6 + a7 * x + a8 * x * x + a9 * x * y + a10 * y + a11 * y * y
        x = xn
        fx = ox + x * s
        fy = oy - y * s
        if 0 <= fx < width and 0 <= fy < height:
            hist[int(fy) * width + int(fx)] += 1
        elif not abs(x) + abs(y) < ESCAPE:
            break
    peak = max(hist)
    stops = palettes().get(palette, palettes()["ember"])["stops"]
    lut = [kit.ramp([tuple(c) for c in stops], i / 255) for i in range(256)]
    tones: dict[int, tuple[int, int, int]] = {}
    out = bytearray(width * height * 3)
    for i, c in enumerate(hist):
        rgb = tones.get(c)
        if rgb is None:
            rgb = tones[c] = lut[tone_index(c, peak, exposure, gamma)]
        out[3 * i : 3 * i + 3] = bytes(rgb)
    return out


def write_picture(
    code: str,
    coeffs: list[float],
    palette: str = "ember",
    size=(900, 600),
    points=1_200_000,
) -> Path:
    w, h = size
    rgb = render_rgb(coeffs, w, h, points, palette)
    suffix = "" if palette == "ember" else f"-{palette}"
    return kit.write_png(store.data_dir() / CURIO / f"{code}{suffix}.png", w, h, rgb)


def thumb_url(coeffs: list[float], palette: str = "ember") -> str:
    """A small PNG data URL for a keepsake card, kept under the 200 KB limit."""
    for w, h, pts in ((320, 200, 300_000), (240, 150, 200_000), (160, 100, 120_000)):
        url = kit.png_data_url(w, h, render_rgb(coeffs, w, h, pts, palette))
        if len(url) < store.MAX_THUMB:
            return url
    raise ValueError("the thumbnail would not fit")


def keepsake_data(found: dict[str, Any], palette: str = "ember") -> dict[str, Any]:
    return {
        "code": found["code"],
        "coeffs": found["coeffs"],
        "palette": palette,
        "exposure": EXPOSURE,
        "gamma": GAMMA,
        "lyapunov": found["result"]["lyapunov"],
        "dimension": found["dimension"],
    }


def report(found: dict[str, Any]) -> None:
    res = found["result"]
    print(f"{found['code']}  ({res['status']})")
    for line in summary(res["status"], res["lyapunov"], found["dimension"]):
        print(f"  {line}")


# --- API ------------------------------------------------------------------------


@router.get("/analyse/{code}")
def api_analyse(code: str) -> dict[str, Any]:
    if not is_code(code):
        raise HTTPException(400, "a code is 12 letters from A to Y")
    found = try_code(code.strip().upper())
    res = found["result"]
    return {
        "code": found["code"],
        "status": res["status"],
        "lyapunov": res["lyapunov"],
        "dimension": found["dimension"],
        "bounds": res["bounds"],
        "describe": summary(res["status"], res["lyapunov"], found["dimension"]),
    }


# --- play.py commands -----------------------------------------------------------


def _palette_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--palette", default="ember", choices=["ember", "dusk", "ice", "ink"]
    )


def cli_hunt(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="play.py attractors hunt")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--keep", metavar="NAME", default=None)
    parser.add_argument("--note", default="")
    parser.add_argument("--min-dimension", type=float, default=MIN_DIMENSION)
    _palette_arg(parser)
    opts = parser.parse_args(args)
    seed = opts.seed if opts.seed is not None else random.getrandbits(32)
    found = hunt(seed, opts.min_dimension)
    if found is None:
        print(f"Nothing chaotic enough turned up from seed {seed}.")
        return 1
    print(f"Seed {seed}: tried {found['tried']} codes.")
    report(found)
    path = write_picture(found["code"], found["coeffs"], opts.palette)
    print(f"Picture: {path}")
    if opts.keep:
        row = store.save_keepsake(
            CURIO,
            name=opts.keep,
            note=opts.note,
            data=keepsake_data(found, opts.palette),
            author="Claude",
            thumb=thumb_url(found["coeffs"], opts.palette),
        )
        print(f"Kept as {row['id']}")
    return 0


def _code_arg(text: str) -> str:
    if not is_code(text):
        raise argparse.ArgumentTypeError("a code is 12 letters from A to Y")
    return text.strip().upper()


def cli_render(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="play.py attractors render")
    parser.add_argument("code", type=_code_arg)
    parser.add_argument("--size", default="900x600")
    parser.add_argument("--points", type=int, default=1_200_000)
    _palette_arg(parser)
    opts = parser.parse_args(args)
    try:
        w, h = (int(v) for v in opts.size.lower().split("x"))
    except ValueError:
        parser.error("--size is WIDTHxHEIGHT, for example 900x600")
    if not (16 <= w <= 4000 and 16 <= h <= 4000):
        parser.error("--size must be between 16 and 4000 on each side")
    found = try_code(opts.code)
    report(found)
    if found["result"]["status"] == "escapes":
        return 1
    path = write_picture(opts.code, found["coeffs"], opts.palette, (w, h), opts.points)
    print(f"Picture: {path}")
    return 0


def cli_keep(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="play.py attractors keep")
    parser.add_argument("code", type=_code_arg)
    parser.add_argument("--name", required=True)
    parser.add_argument("--note", default="")
    _palette_arg(parser)
    opts = parser.parse_args(args)
    found = try_code(opts.code)
    report(found)
    if found["result"]["status"] == "escapes":
        print("Not kept: it flies off to infinity.")
        return 1
    row = store.save_keepsake(
        CURIO,
        name=opts.name,
        note=opts.note,
        data=keepsake_data(found, opts.palette),
        author="Claude",
        thumb=thumb_url(found["coeffs"], opts.palette),
    )
    print(f"Kept as {row['id']}")
    return 0


COMMANDS = {
    "hunt": (
        cli_hunt,
        "[--seed N] [--keep NAME]  find a strange attractor, write a PNG",
    ),
    "render": (cli_render, "CODE [--palette P] [--size WxH]  draw a code to a PNG"),
    "keep": (cli_keep, "CODE --name N [--note T]  keep a code as a keepsake"),
}
