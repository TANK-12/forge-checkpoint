"""Garden: Claude's L-system plants that keep growing over real days.

The garden is one file, store.data_dir()/garden/garden.json. Each plant has a
genome, a name, who planted it, when, and its parents if crossed. Nothing in
the file changes as a plant grows: its generation is a pure function of the
hours since planting (growth_stage), so the garden has grown whenever someone
looks again. The first request that finds no garden file plants Claude's
starters, dated at that moment.

This file mirrors the browser's lsys.js for expansion, the effective maximum
generation and the growth stage, and words.js for the genome checks
(tests/test_agree.py runs tests/agree.mjs to pin both sides), and adds
what only Python does: crossing (POST /cross and `play.py garden cross`), a
small turtle and line rasteriser for a PNG of the whole garden, and the
play.py commands look, plant, cross and render.
"""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import os
import random
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

import kit
import store

router = APIRouter()

MAX_LEN = 20000
MAX_SEGMENTS = 4000
MAX_PLANTS = 40
MAX_PLANT_NAME = 40
SYMBOLS = re.compile(r"[A-Z+\-\[\]]+")
FLOWERS = ("star", "round", "bell", "spark")
NUMBERS = {
    # field: (low, high, default)
    "angle": (5.0, 60.0, 25.0),
    "len_decay": (0.5, 1.0, 0.85),
    "width_decay": (0.4, 1.0, 0.72),
    "jitter": (0.0, 20.0, 5.0),
    "bloom": (0.0, 0.6, 0.25),
    "hours_per_gen": (0.5, 48.0, 8.0),
}
# held across every read-modify-write of the garden file: FastAPI runs these
# routes on a thread pool, and two plantings at once must not lose one
_LOCK = threading.RLock()

# --- seeded randomness, the same as curios/_kit/rng.js -------------------------

MASK = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    return (a * b) & MASK


def mulberry32(seed: int):
    state = [seed & MASK]

    def nxt() -> float:
        state[0] = (state[0] + 0x6D2B79F5) & MASK
        t = state[0]
        t = _imul(t ^ (t >> 15), t | 1)
        t ^= (t + _imul(t ^ (t >> 7), t | 61)) & MASK
        return ((t ^ (t >> 14)) & MASK) / 4294967296

    return nxt


def hash_string(text: str) -> int:
    h = 0x811C9DC5
    for ch in str(text):
        h ^= ord(ch)
        h = _imul(h, 0x01000193)
    return h


# --- the L-system, mirroring lsys.js -------------------------------------------


def expand(genome: dict, gen: int) -> tuple[str, list[int], int]:
    """The string towards generation gen, its fresh flags and the generation
    reached: growth stops at the last one within MAX_LEN and MAX_SEGMENTS
    (see lsys.js)."""
    r = mulberry32(int(genome["seed"]))
    text = genome["axiom"]
    fresh = [1] * len(text)
    rules = genome["rules"]
    reached = 0
    for g in range(gen):
        out: list[str] = []
        flags: list[int] = []
        size = segments = 0
        for c in text:
            variants = rules.get(c)
            if not variants:
                out.append(c)
                flags.append(0)
                v = c
            else:
                v = (
                    variants[0]
                    if len(variants) == 1
                    else variants[int(r() * len(variants))]
                )
                keep = v.rfind(c)
                out.append(v)
                flags.extend(0 if k == keep else 1 for k in range(len(v)))
            size += len(v)
            segments += v.count("F")
            if size > MAX_LEN or segments > MAX_SEGMENTS:
                return text, fresh, reached
        text = "".join(out)
        fresh = flags
        reached = g + 1
    return text, fresh, reached


def effective_max_gen(genome: dict) -> int:
    return expand(genome, max(0, int(genome["max_gen"])))[2]


def _parse_time(text: str) -> datetime:
    when = datetime.fromisoformat(text)
    return when if when.tzinfo else when.astimezone()


def hours_grown(plant: dict, now: datetime | None = None, ahead: float = 0.0) -> float:
    now = now or datetime.now().astimezone()
    hours = (now - _parse_time(plant["planted"])).total_seconds() / 3600
    return max(0.0, hours + float(plant.get("head_start_hours") or 0) + ahead)


def growth_stage(
    plant: dict, max_gen: int, now: datetime | None = None, ahead: float = 0.0
) -> float:
    hpg = max(0.1, float(plant["genome"].get("hours_per_gen") or 6))
    return min(float(max_gen), hours_grown(plant, now, ahead) / hpg)


def _smooth(t: float) -> float:
    x = min(1.0, max(0.0, t))
    return x * x * (3 - 2 * x)


def stage_parts(stage: float, max_gen: int) -> tuple[int, float]:
    n = math.floor(stage)
    f = stage - n
    if n >= max_gen or f < 1e-6:
        return min(n, max_gen), 1.0
    return n + 1, _smooth(f)


# --- genomes -------------------------------------------------------------------


def _balanced(text: str) -> bool:
    depth = 0
    for c in text:
        depth += 1 if c == "[" else -1 if c == "]" else 0
        if depth < 0:
            return False
    return depth == 0


def _string(value: Any, what: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise store.StoreError(f"{what} must be 1 to {limit} symbols")
    if not SYMBOLS.fullmatch(value) or not _balanced(value):
        raise store.StoreError(
            f"{what} may only hold F, other capital letters, + - [ ] with brackets that pair up"
        )
    return value


def _finite(value: Any) -> bool:
    """A real, finite number (JSON lets NaN and Infinity through)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _number(raw: dict, key: str) -> float:
    low, high, default = NUMBERS[key]
    value = raw.get(key, default)
    if not _finite(value):
        raise store.StoreError(f"{key} must be a number")
    return round(min(high, max(low, float(value))), 4)


def clean_genome(raw: Any) -> dict:
    """A checked copy of a genome, numbers clamped into range; StoreError if unusable."""
    if not isinstance(raw, dict):
        raise store.StoreError("the genome must be an object")
    rules_in = raw.get("rules")
    if not isinstance(rules_in, dict) or not 1 <= len(rules_in) <= 3:
        raise store.StoreError("the genome needs 1 to 3 rules")
    rules: dict[str, list[str]] = {}
    for sym, variants in rules_in.items():
        if not isinstance(sym, str) or not re.fullmatch(r"[A-Z]", sym):
            raise store.StoreError("a rule rewrites one capital letter")
        if isinstance(variants, str):
            variants = [variants]
        if not isinstance(variants, list) or not 1 <= len(variants) <= 3:
            raise store.StoreError(f"rule {sym} needs 1 to 3 versions")
        rules[sym] = [_string(v, f"rule {sym}", 60) for v in variants]
    hues_in = raw.get("hues")
    if not isinstance(hues_in, dict):
        hues_in = {}
    hues = {}
    for key, default in (("stem", 30), ("leaf", 110), ("flower", 340)):
        value = hues_in.get(key, default)
        if not _finite(value):
            raise store.StoreError(f"the {key} hue must be a number")
        hues[key] = round(float(value) % 360, 2)
    flower = raw.get("flower", "round")
    if flower not in FLOWERS:
        raise store.StoreError(f"the flower must be one of {', '.join(FLOWERS)}")
    max_gen = raw.get("max_gen", 5)
    if not _finite(max_gen):
        raise store.StoreError("max_gen must be a number")
    seed = raw.get("seed", 1)
    if not _finite(seed):
        raise store.StoreError("the seed must be a number")
    genome = {
        "axiom": _string(raw.get("axiom", "X"), "the axiom", 20),
        "rules": rules,
        **{key: _number(raw, key) for key in NUMBERS},
        "hues": hues,
        "flower": flower,
        "max_gen": int(min(7, max(1, int(max_gen)))),
        "seed": int(seed) & MASK,
    }
    if effective_max_gen(genome) < 1:
        raise store.StoreError("this genome grows too big even in its first generation")
    return genome


X_SHAPES = [
    "F[+X][-X]FX",
    "F[+X]F[-X]+X",
    "F-[[X]+X]+F[+FX]-X",
    "F[-X]F[+X]-X",
    "FF[+X][-X]F[+X]X",
    "F[+X][-X]F[-X]X",
    "F[+FX]F[-FX]X",
]


def random_genome(seed: int) -> dict:
    """A fresh, pleasant genome fixed by the seed."""
    r = mulberry32(seed)

    def pick(items: list) -> Any:
        return items[int(r() * len(items))]

    variants = [pick(X_SHAPES)]
    if r() < 0.5:
        variants.append(pick(X_SHAPES))
    rules: dict[str, list[str]] = {"X": variants}
    if r() < 0.6:
        rules["F"] = ["FF"] if r() < 0.7 else ["FF", "F"]
    leaf = (70 + r() * 110) % 360
    genome = {
        "axiom": "X",
        "rules": rules,
        "angle": round(16 + r() * 22, 1),
        "len_decay": round(0.78 + r() * 0.2, 3),
        "width_decay": round(0.6 + r() * 0.2, 3),
        "jitter": round(2 + r() * 9, 1),
        "bloom": round(0.12 + r() * 0.3, 3),
        "hours_per_gen": round(6 + r() * 6, 1),
        "hues": {
            "stem": round((15 + r() * 40) % 360, 1),
            "leaf": round(leaf, 1),
            "flower": round(r() * 360, 1),
        },
        "flower": pick(list(FLOWERS)),
        "max_gen": 6,
        "seed": int(r() * 4294967296),
    }
    while genome["max_gen"] > 3:
        text, _, reached = expand(genome, genome["max_gen"])
        if reached == genome["max_gen"] and text.count("F") <= 2500:
            break
        genome["max_gen"] -= 1
    return clean_genome(genome)


def _mix_hue(a: float, b: float, t: float) -> float:
    delta = ((b - a + 540) % 360) - 180
    return (a + delta * t) % 360


def _flip_one(text: str, r) -> str:
    turns = [i for i, c in enumerate(text) if c in "+-"]
    if not turns:
        return text
    i = turns[int(r() * len(turns))]
    return text[:i] + ("-" if text[i] == "+" else "+") + text[i + 1 :]


def cross(a: dict, b: dict, seed: int) -> dict:
    """A child genome from two parents, fixed by the seed: each rule and
    number comes from one parent or a blend of both, plus a small mutation."""
    r = mulberry32(seed)
    axiom = a["axiom"] if r() < 0.5 else b["axiom"]
    order = sorted(
        set(a["rules"]) | set(b["rules"]), key=lambda s: (s not in axiom, s == "F", s)
    )
    rules: dict[str, list[str]] = {}
    for sym in order[:3]:
        own = a["rules"].get(sym)
        other = b["rules"].get(sym)
        if own and other and r() < 0.5:
            own, other = other, own
        chosen = list(own or other or [])
        if own and other and r() < 0.35 and len(chosen) < 3:
            extra = other[int(r() * len(other))]
            if extra not in chosen:
                chosen.append(extra)
        rules[sym] = chosen
    if r() < 0.3:
        sym = sorted(rules)[int(r() * len(rules))]
        k = int(r() * len(rules[sym]))
        rules[sym][k] = _flip_one(rules[sym][k], r)
    child: dict[str, Any] = {"axiom": axiom, "rules": rules}
    spread = {"angle": 3.0, "len_decay": 0.03, "width_decay": 0.03, "jitter": 1.5}
    for key in NUMBERS:
        t = r()
        value = a[key] + (b[key] - a[key]) * t
        value += (r() * 2 - 1) * spread.get(key, 0.0)
        child[key] = value
    child["hues"] = {
        key: round(
            _mix_hue(a["hues"][key], b["hues"][key], r()) + (r() * 2 - 1) * 12, 1
        )
        % 360
        for key in ("stem", "leaf", "flower")
    }
    child["flower"] = a["flower"] if r() < 0.5 else b["flower"]
    child["max_gen"] = round(a["max_gen"] + (b["max_gen"] - a["max_gen"]) * r())
    child["seed"] = int(r() * 4294967296)
    try:
        return clean_genome(child)
    except store.StoreError:
        # a mix that grows too big: keep the first parent's rules, still blended numbers
        child["rules"] = {k: list(v) for k, v in a["rules"].items()}
        child["axiom"] = a["axiom"]
        return clean_genome(child)


# --- the garden file -----------------------------------------------------------

STARTERS_FILE = Path(__file__).resolve().parent / "starters.json"


def garden_path() -> Path:
    return store.data_dir() / "garden" / "garden.json"


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write(garden: dict) -> None:
    path = garden_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".garden-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(garden, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _starters() -> dict:
    """Claude's starter plants (starters.json, shared with the shelf preview),
    dated now; each came as a seedling, so it has a few hours' head start."""
    shipped = json.loads(STARTERS_FILE.read_text(encoding="utf-8"))
    when = _now_text()
    plants = []
    for i, row in enumerate(shipped["plants"], start=1):
        plants.append(
            {
                "id": f"p{i}",
                "name": row["name"],
                "by": shipped["by"],
                "planted": when,
                "head_start_hours": row["head_start_hours"],
                "parents": None,
                "genome": clean_genome(row["genome"]),
            }
        )
    return {"version": 1, "next_id": len(plants) + 1, "plants": plants}


def load_garden() -> dict:
    """The garden, planting the starters when there is no garden file yet."""
    path = garden_path()
    with _LOCK:
        if not path.exists():
            garden = _starters()
            _write(garden)
            return garden
        try:
            garden = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise store.StoreError(f"the garden file cannot be read: {exc}") from exc
    if not isinstance(garden, dict) or not isinstance(garden.get("plants"), list):
        raise store.StoreError("the garden file is not a garden")
    return garden


def _clean_name(name: Any) -> str:
    text = " ".join(str(name or "").split())
    if not text:
        raise store.StoreError("the plant needs a name")
    if len(text) > MAX_PLANT_NAME:
        raise store.StoreError(f"keep the name under {MAX_PLANT_NAME} characters")
    return text


def _clean_by(by: Any) -> str:
    text = " ".join(str(by or "").split())[: store.MAX_AUTHOR]
    return text or store.user_name()


def find_plant(garden: dict, ref: str) -> dict:
    key = " ".join(str(ref).split()).lower()
    for field in ("id", "name"):  # an id wins over a plant named like one
        for plant in garden["plants"]:
            if str(plant.get(field, "")).lower() == key:
                return plant
    raise store.NotFound(f"no plant called {ref!r} in the garden")


def _add(garden: dict, plant: dict) -> dict:
    if len(garden["plants"]) >= MAX_PLANTS:
        raise store.Conflict(f"the garden has room for {MAX_PLANTS} plants")
    plant["id"] = f"p{garden.get('next_id', len(garden['plants']) + 1)}"
    garden["next_id"] = int(plant["id"][1:]) + 1
    garden["plants"].append(plant)
    _write(garden)
    return plant


def plant_seed(
    name: Any, by: Any = "", genome: Any = None, seed: int | None = None
) -> dict:
    clean = (
        clean_genome(genome)
        if genome is not None
        else random_genome(random.getrandbits(32) if seed is None else seed)
    )
    plant = {
        "name": _clean_name(name),
        "by": _clean_by(by),
        "planted": _now_text(),
        "head_start_hours": 0,
        "parents": None,
        "genome": clean,
    }
    with _LOCK:
        return _add(load_garden(), plant)


def cross_plants(
    a: str, b: str, name: Any, by: Any = "", seed: int | None = None
) -> dict:
    with _LOCK:
        return _cross_locked(load_garden(), a, b, name, by, seed)


def _cross_locked(
    garden: dict, a: str, b: str, name: Any, by: Any, seed: int | None
) -> dict:
    pa, pb = find_plant(garden, a), find_plant(garden, b)
    if pa["id"] == pb["id"]:
        raise store.StoreError("pick two different plants to cross")
    child = cross(
        pa["genome"], pb["genome"], random.getrandbits(32) if seed is None else seed
    )
    plant = {
        "name": _clean_name(name),
        "by": _clean_by(by),
        "planted": _now_text(),
        "head_start_hours": 0,
        "parents": [
            {"id": pa["id"], "name": pa["name"]},
            {"id": pb["id"], "name": pb["name"]},
        ],
        "genome": child,
    }
    return _add(garden, plant)


def rename_plant(ref: str, name: Any) -> dict:
    clean = _clean_name(name)
    with _LOCK:
        garden = load_garden()
        plant = find_plant(garden, ref)
        plant["name"] = clean
        _write(garden)
    return plant


# --- routes --------------------------------------------------------------------


class PlantIn(BaseModel):
    name: str
    by: str = ""
    genome: dict | None = None
    seed: int | None = None


class CrossIn(BaseModel):
    a: str
    b: str
    name: str
    by: str = ""
    seed: int | None = None


class RenameIn(BaseModel):
    id: str
    name: str


@router.get("/plants")
def get_plants() -> dict:
    garden = load_garden()
    return {"plants": garden["plants"], "now": _now_text(), "max": MAX_PLANTS}


@router.post("/plant")
def post_plant(body: PlantIn) -> dict:
    return plant_seed(body.name, body.by, body.genome, body.seed)


@router.post("/cross")
def post_cross(body: CrossIn) -> dict:
    return cross_plants(body.a, body.b, body.name, body.by, body.seed)


@router.post("/rename")
def post_rename(body: RenameIn) -> dict:
    return rename_plant(body.id, body.name)


# --- a PNG of the garden -------------------------------------------------------


def turtle(genome: dict, text: str, fresh: list[int], grow: float = 1.0) -> dict:
    """Segments [(x0, y0, x1, y1, depth)] and buds [(x, y, size, depth, flower)],
    y up, the same walk as lsys.js turtle()."""
    r = mulberry32((int(genome["seed"]) ^ 0x9E3779B9) & MASK)
    rad = math.pi / 180
    ang, jit, bloom = genome["angle"], genome["jitter"], genome["bloom"]
    x = y = 0.0
    h = 90.0
    depth = 0
    stack: list[tuple[float, float, float, int]] = []
    segs: list[tuple[float, float, float, float, int]] = []
    buds: list[tuple[float, float, float, int, bool]] = []
    bud_index = 0
    for i, c in enumerate(text):
        if c == "F":
            length = genome["len_decay"] ** depth * (0.94 + r() * 0.12)
            length *= grow if fresh[i] else 1.0
            nx, ny = x + math.cos(h * rad) * length, y + math.sin(h * rad) * length
            if length > 1e-4:
                segs.append((x, y, nx, ny, depth))
            x, y = nx, ny
        elif c == "+":
            h += ang + jit * (r() * 2 - 1)
        elif c == "-":
            h -= ang + jit * (r() * 2 - 1)
        elif c == "[":
            stack.append((x, y, h, depth))
            depth += 1
        elif c == "]":
            if stack:
                x, y, h, depth = stack.pop()
        elif "A" <= c <= "Z":
            pick = hash_string(f"{genome['seed']}:{bud_index}") / 4294967296
            bud_index += 1
            size = grow if fresh[i] else 1.0
            if size > 0.01:
                buds.append((x, y, size, depth, depth >= 1 and pick < bloom))
    return {"segs": segs, "buds": buds}


def _hsl(h: float, s: float, light: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, light, s)
    return round(r * 255), round(g * 255), round(b * 255)


SKIES = {
    "night": ((6, 7, 20), (24, 20, 44), 0.5),
    "dawn": ((40, 44, 96), (236, 140, 120), 0.75),
    "day": ((62, 132, 214), (214, 232, 246), 1.0),
    "dusk": ((42, 36, 96), (255, 140, 70), 0.75),
}


def sky_name(hour: float) -> str:
    if 5.2 <= hour < 7:
        return "dawn"
    if 7 <= hour < 18.2:
        return "day"
    if 18.2 <= hour < 21.2:
        return "dusk"
    return "night"


class Canvas:
    """An RGB byte buffer with discs and thick lines, y down."""

    def __init__(self, width: int, height: int):
        self.w, self.h = width, height
        self.buf = bytearray(width * height * 3)
        self._discs: dict[int, list[tuple[int, int]]] = {}

    def gradient(self, top: tuple, low: tuple, until: int) -> None:
        for y in range(self.h):
            t = min(1.0, y / max(1, until))
            row = bytes(round(a + (b - a) * t) for a, b in zip(top, low)) * self.w
            self.buf[y * self.w * 3 : (y + 1) * self.w * 3] = row

    def _offsets(self, radius: float) -> list[tuple[int, int]]:
        key = max(0, round(radius * 2))
        if key not in self._discs:
            rr = key / 2
            span = math.ceil(rr)
            self._discs[key] = [
                (dx, dy)
                for dy in range(-span, span + 1)
                for dx in range(-span, span + 1)
                if dx * dx + dy * dy <= rr * rr + 0.25
            ]
        return self._discs[key]

    def disc(self, cx: float, cy: float, radius: float, colour: tuple) -> None:
        px = bytes(colour)
        ix, iy = round(cx), round(cy)
        for dx, dy in self._offsets(radius):
            x, y = ix + dx, iy + dy
            if 0 <= x < self.w and 0 <= y < self.h:
                i = (y * self.w + x) * 3
                self.buf[i : i + 3] = px

    def line(
        self, x0: float, y0: float, x1: float, y1: float, width: float, colour: tuple
    ):
        radius = max(0.5, width / 2)
        dist = math.hypot(x1 - x0, y1 - y0)
        steps = max(1, math.ceil(dist / max(0.7, radius * 0.8)))
        for k in range(steps + 1):
            t = k / steps
            self.disc(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, radius, colour)


def render_png(
    path: Path, width: int = 1200, height: int = 600, hour: float | None = None
):
    """Draw every plant at its current stage onto soil under the hour's sky."""
    garden = load_garden()
    now = datetime.now().astimezone()
    hour = now.hour + now.minute / 60 if hour is None else hour
    hour = hour % 24 if math.isfinite(hour) else 0.0
    top, low, light = SKIES[sky_name(hour)]
    canvas = Canvas(width, height)
    ground = int(height * 0.86)
    canvas.gradient(top, low, ground)
    soil = (34, 24, 22)
    for y in range(ground, height):
        shade = tuple(
            round(c * (1 - 0.35 * (y - ground) / (height - ground))) for c in soil
        )
        canvas.buf[y * width * 3 : (y + 1) * width * 3] = bytes(shade) * width
    plants = garden["plants"]
    slot = width / max(1, len(plants))
    for n, plant in enumerate(plants):
        genome = plant["genome"]
        top_gen = effective_max_gen(genome)
        full_text, full_fresh, _ = expand(genome, top_gen)
        full = turtle(genome, full_text, full_fresh)
        xs = [p for s in full["segs"] for p in (s[0], s[2])] or [0.0]
        ys = [p for s in full["segs"] for p in (s[1], s[3])] or [1.0]
        span_x = max(1e-3, max(xs) - min(xs))
        scale = min(slot * 0.86 / span_x, height * 0.66 / max(1.0, max(ys)))
        cx = slot * (n + 0.5) - (max(xs) + min(xs)) / 2 * scale
        gen, grow = stage_parts(growth_stage(plant, top_gen, now), top_gen)
        text, fresh, _ = expand(genome, gen)
        geo = turtle(genome, text, fresh, grow)
        trunk = min(7.0, max(1.6, max(ys) * scale * 0.022))
        hues = genome["hues"]
        for x0, y0, x1, y1, depth in geo["segs"]:
            colour = _hsl(hues["stem"], 0.35, (0.24 + 0.04 * min(depth, 5)) * light)
            canvas.line(
                cx + x0 * scale,
                ground - y0 * scale,
                cx + x1 * scale,
                ground - y1 * scale,
                max(0.9, trunk * genome["width_decay"] ** depth),
                colour,
            )
        leaf_px = min(6.0, max(2.0, scale * 0.6))
        for x, y, size, depth, flower in geo["buds"]:
            px, py = cx + x * scale, ground - y * scale
            if flower:
                canvas.disc(
                    px,
                    py,
                    leaf_px * 0.9 * size,
                    _hsl(hues["flower"], 0.8, 0.62 * light),
                )
                canvas.disc(
                    px, py, leaf_px * 0.3 * size, _hsl(hues["flower"] + 30, 0.9, 0.85)
                )
            else:
                tone = 0.4 + 0.06 * (depth % 3)
                canvas.disc(
                    px, py, leaf_px * 0.6 * size, _hsl(hues["leaf"], 0.5, tone * light)
                )
        if gen == 0:
            canvas.disc(slot * (n + 0.5), ground - 2, 4, (120, 92, 60))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".render-", suffix=".png")
    os.close(fd)
    try:
        kit.write_png(tmp, width, height, canvas.buf)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


# --- play.py commands ----------------------------------------------------------


def describe(plant: dict, now: datetime | None = None) -> str:
    top = effective_max_gen(plant["genome"])
    stage = growth_stage(plant, top, now)
    hours = hours_grown(plant, now)
    days, rest = divmod(int(hours), 24)
    age = f"{days} d {rest} h" if days else f"{rest} h {int(hours * 60) % 60} m"
    parents = plant.get("parents") or []
    family = " x ".join(p["name"] for p in parents) if parents else "none"
    return (
        f"{plant['id']:>4}  {plant['name']}  planted by {plant['by']}, age {age}, "
        f"generation {math.floor(stage)} of {top}, parents: {family}"
    )


def cli_look(args: list[str]) -> int:
    garden = load_garden()
    print(f"Claude's garden: {len(garden['plants'])} plants, left to right.")
    for plant in garden["plants"]:
        print(describe(plant))
    return 0


def cli_plant(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="play.py garden plant")
    parser.add_argument("--name", required=True)
    parser.add_argument("--genome", help="a genome as JSON; a random one when left out")
    parser.add_argument("--by", default="Claude")
    parser.add_argument("--seed", type=int)
    opts = parser.parse_args(args)
    try:
        genome = json.loads(opts.genome) if opts.genome else None
    except ValueError as exc:
        raise store.StoreError(f"--genome is not JSON: {exc}") from exc
    plant = plant_seed(opts.name, opts.by, genome, opts.seed)
    print(f"Planted {plant['name']} ({plant['id']}).")
    print(describe(plant))
    return 0


def cli_cross(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="play.py garden cross")
    parser.add_argument("a", help="a plant id or name")
    parser.add_argument("b", help="a plant id or name")
    parser.add_argument("--name", required=True)
    parser.add_argument("--by", default="Claude")
    parser.add_argument("--seed", type=int)
    opts = parser.parse_args(args)
    plant = cross_plants(opts.a, opts.b, opts.name, opts.by, opts.seed)
    print(f"Crossed into {plant['name']} ({plant['id']}).")
    print(describe(plant))
    return 0


def cli_render(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="play.py garden render")
    parser.add_argument("--hour", type=float, help="sky hour 0-24 (default: now)")
    opts = parser.parse_args(args)
    path = render_png(store.data_dir() / "garden" / "render.png", hour=opts.hour)
    print(path)
    return 0


COMMANDS = {
    "look": (cli_look, "every plant: name, planter, age, generation, parents"),
    "plant": (cli_plant, "--name N [--genome JSON] [--by WHO]: plant a seed"),
    "cross": (cli_cross, "A B --name C [--by WHO]: cross two plants into a new one"),
    "render": (cli_render, "[--hour H]: a PNG of the whole garden; prints its path"),
}
