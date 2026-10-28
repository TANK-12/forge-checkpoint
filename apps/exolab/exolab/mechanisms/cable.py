"""A soft cable exosuit: one cable from a shoulder-top anchor to the
upper-arm cuff. It has no joint centre to misalign and no gimbal lock, but it
can only pull, and only as well as its lever arm allows: overhead the cable
lies along the arm and gives almost nothing.
"""

from __future__ import annotations

import numpy as np

from .. import vec
from ..vec import v
from . import Ctx, MechState

KIND = "cable"


def place(mech: dict, ctx: Ctx, prev: MechState | None = None) -> MechState:
    p, b = ctx.pose, ctx.body
    anchor = p.gh + v(
        -float(mech.get("anchor_back_m", 0.03)),
        float(mech.get("anchor_up_m", 0.1)),
        -0.01,
    )
    cuff = p.gh + float(mech.get("cuff_fraction", 0.55)) * b.l_upper * p.u
    w = vec.unit(anchor - cuff)
    moment = vec.cross(cuff - p.gh, w)  # moment about the joint per newton
    st = MechState(
        centre=p.gh.copy(),
        axes=[],
        q=[vec.norm(anchor - cuff)],
        sing=1.0,
        link_dir=p.u.copy(),
    )
    st.cable = {
        "anchor": anchor,
        "cuff": cuff,
        "moment_per_n": moment,
        "tension_cont": float(mech.get("cable_tension_cont_n", 250)),
        "tension_peak": float(mech.get("cable_tension_peak_n", 500)),
    }
    st.layout = {"cable": [anchor, p.gh + v(0.0, 0.07, 0.0) + 0.02 * p.u, cuff]}
    return st
