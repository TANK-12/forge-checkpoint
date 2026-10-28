"""Strategies are discovered: each module here with a `META` dict and a
`targets(series, params)` function is one strategy. Adding a strategy is
one new file in this folder, nothing else.

`targets` returns the wanted exposure after each close, from -1 (all in,
short) through 0 (out) to 1 (all in, long). The value at day t may use
prices up to day t only; tests check this for every strategy.

`META["order"]`, when present, lists parameter pairs [a, b] where a must
stay below b (a fast average shorter than the slow one); sweeps skip
combinations that break it and runs refuse them.
"""

from __future__ import annotations

import importlib
import math
import pkgutil
from types import ModuleType

_cache: dict[str, ModuleType] = {}


def load() -> dict[str, ModuleType]:
    if not _cache:
        for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
            mod = importlib.import_module(f"{__name__}.{info.name}")
            meta = getattr(mod, "META", None)
            if isinstance(meta, dict) and callable(getattr(mod, "targets", None)):
                _cache[meta["id"]] = mod
    return _cache


def params_for(meta: dict, given: dict | None) -> dict:
    """The strategy's parameters with defaults filled in and each value
    kept inside its allowed range."""
    given = given or {}
    out = {}
    for p in meta.get("params", []):
        v = given.get(p["key"], p["default"])
        try:
            v = float(v)
        except (TypeError, ValueError, OverflowError):  # 10**400 has no float
            v = float(p["default"])
        if not math.isfinite(v):
            v = float(p["default"])
        v = min(max(v, p["min"]), p["max"])
        out[p["key"]] = int(round(v)) if p.get("int", True) else v
    return out


def order_problem(meta: dict, params: dict) -> str:
    """Why these parameters break the strategy's order rule, or ""."""
    labels = {p["key"]: p.get("label", p["key"]) for p in meta.get("params", [])}
    for a, b in meta.get("order", []):
        if a in params and b in params and params[a] >= params[b]:
            return f"{labels.get(a, a)} has to be below {labels.get(b, b)}."
    return ""


def describe() -> list[dict]:
    return [mod.META for mod in load().values()]
