"""Shoulder mechanisms, one module per kind, found by scanning this package.

Each module sets ``KIND`` (the ``kind`` field in data/mechanisms/*.json) and
defines ``place(mech, ctx, prev) -> MechState``: where the mechanism sits and
how its joints are set while the human arm is in ``ctx.pose``. A new kind is
one new file here plus one data file; nothing else lists them.

All vectors are in the arm frame (x forward, y up, z lateral, right arm).
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from types import ModuleType

from ..human import ArmPose, Body
from ..vec import Vec


@dataclass
class Ctx:
    body: Body
    pose: ArmPose
    cuff_k: float  # total cuff stiffness across the limb, N/m
    carried_kg: float = 0.0  # exo arm hardware hanging on the mechanism


@dataclass
class MechState:
    centre: Vec  # rotation centre of the exo shoulder
    axes: list[Vec]  # unit joint axes, base to tip ([] for a cable)
    q: list[float]  # joint angles in radians (a cable: its length in metres)
    sing: float  # 1 = far from gimbal lock, 0 = locked
    link_dir: Vec  # direction of the exo upper-arm link
    layout: dict = field(default_factory=dict)  # drawing data
    notes: list[str] = field(default_factory=list)
    clash: str = ""  # what a link runs into, if anything
    passive: Vec | None = None  # girdle: how far the passive link moved
    cable: dict | None = None  # cable: anchor, cuff point, moment per newton


KINDS: dict[str, ModuleType] = {}


def _discover() -> None:
    for info in pkgutil.iter_modules(__path__):
        mod = importlib.import_module(f"{__name__}.{info.name}")
        kind = getattr(mod, "KIND", None)
        if isinstance(kind, str):
            KINDS[kind] = mod


def place(mech: dict, ctx: Ctx, prev: MechState | None = None) -> MechState:
    kind = mech.get("kind", "")
    if kind not in KINDS:
        raise ValueError(f"no shoulder mechanism of kind {kind!r}")
    return KINDS[kind].place(mech, ctx, prev)


_discover()
