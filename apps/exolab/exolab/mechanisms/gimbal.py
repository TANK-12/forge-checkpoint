"""Three motor axes meeting at one point (a spherical, or gimbal, shoulder).

Axis 1 is fixed to the back frame, axis 3 runs along the exo upper-arm link
(arm twist), axis 2 is square to both. When axes 1 and 3 line up the
mechanism loses a direction it can move in (gimbal lock): the closeness
measure is |det[a1 a2 a3]|, which for this layout equals the sine of the
angle between axes 1 and 3.
"""

from __future__ import annotations

import math

import numpy as np

from .. import human, vec
from ..vec import Vec, v
from . import Ctx, MechState

KIND = "gimbal"
HANG = v(0.0, -1.0, 0.0)


def first_axis(mech: dict) -> Vec:
    fa = mech.get("first_axis", {})
    return human.arm_dir(fa.get("plane_deg", 0.0), fa.get("elevation_deg", 90.0))


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _second(a1: Vec, a3: Vec, side: float, hint: Vec | None) -> Vec:
    """Axis 2 is square to axes 1 and 3. Of its two directions the design
    picks one (``j2_side``) and keeps it: a real 3-joint gimbal cannot swap
    without passing through gimbal lock, so this is the continuous branch.
    Only at exact lock, where any square axis fits, does the last one stay."""
    c = vec.cross(a1, a3)
    s = vec.norm(c)
    if s < 1e-9:
        if hint is not None:
            return hint
        return vec.unit(vec.cross(a1, v(1.0, 0.0, 0.0)), v(0.0, 0.0, 1.0))
    return (1.0 if side >= 0 else -1.0) * c / s


def solve(mech: dict, centre: Vec, ctx: Ctx, prev: MechState | None) -> MechState:
    p = ctx.pose
    a1 = first_axis(mech)
    a3 = vec.unit(p.elbow_pt - centre, p.u)
    side = float(mech.get("j2_side", 1.0))
    a2_ref = _second(a1, HANG, side, None)
    a2 = _second(a1, a3, side, prev.axes[1] if prev and prev.axes else a2_ref)
    q1 = vec.signed_angle(a2_ref, a2, a1)
    q2 = vec.signed_angle(a1, a3, a2) - vec.signed_angle(a1, HANG, a2_ref)
    roll_ref = vec.signed_angle(vec.cross(a2_ref, HANG), v(1.0, 0.0, 0.0), HANG)
    q3 = vec.signed_angle(vec.cross(a2, a3), p.R[:, 0], a3) - roll_ref
    q = [_wrap(q1), _wrap(q2), _wrap(q3)]
    if prev is not None and len(prev.q) == 3:
        # Follow the previous frame across the +-180 seam.
        q = [pq + _wrap(x - pq) for x, pq in zip(q, prev.q)]
    sing = abs(float(np.dot(a1, vec.cross(a2, a3))))
    rho = float(mech.get("pod_radius_m", 0.12))
    st = MechState(centre=centre, axes=[a1, a2, a3], q=q, sing=sing, link_dir=a3)
    st.layout = {
        "pod_radius": rho,
        "pods": [centre + rho * a1, centre + rho * a2, centre + rho * a3],
        "link1": [centre + rho * _slerp(a1, a2, t) for t in np.linspace(0, 1, 9)],
        "link2": [centre + rho * _slerp(a2, a3, t) for t in np.linspace(0, 1, 9)],
        "base": _base(ctx, centre, a1, rho),
    }
    st.clash = _clash(ctx, st.layout)
    return st


def _slerp(a: Vec, b: Vec, t: float) -> Vec:
    om = vec.angle_between(a, b)
    if om < 1e-6:
        return a
    return (math.sin((1 - t) * om) * a + math.sin(t * om) * b) / math.sin(om)


def _base(ctx: Ctx, centre: Vec, a1: Vec, rho: float) -> list[Vec]:
    """The back-frame strut from behind the shoulder blade to the first motor."""
    b = ctx.body
    anchor = v(b.chest[0] - 0.13, b.gh_rest[1] - 0.04, b.gh_rest[2] * 0.45)
    return [anchor, centre + rho * a1]


def _clash(ctx: Ctx, layout: dict) -> str:
    """Approximate body check of the links and the first two motors against
    the head (an ellipsoid with hair), the neck (a capsule) and the chest."""
    b = ctx.body
    head = b.head + v(0.01, 0.085, 0.0)
    pts = layout["link1"] + layout["link2"][:6] + layout["pods"][:2]
    for pt in pts:
        d = pt - head
        if (d[0] / 0.105) ** 2 + (d[1] / 0.125) ** 2 + (d[2] / 0.085) ** 2 < 1.0:
            return "head"
        if _seg_dist(pt, b.neck, b.head) < 0.065:
            return "neck"
        d = pt - b.chest
        if (d[0] / 0.10) ** 2 + (d[1] / 0.20) ** 2 + (d[2] / 0.085) ** 2 < 1.0:
            return "chest"
    return ""


def _seg_dist(p: Vec, a: Vec, b: Vec) -> float:
    ab = b - a
    t = float(np.clip(np.dot(p - a, ab) / max(float(np.dot(ab, ab)), 1e-12), 0.0, 1.0))
    return vec.norm(p - (a + t * ab))


def place(mech: dict, ctx: Ctx, prev: MechState | None = None) -> MechState:
    off = np.array(mech.get("centre_offset_mm", [0, 0, 0]), dtype=float) / 1000.0
    return solve(mech, ctx.body.gh_rest + off, ctx, prev)
