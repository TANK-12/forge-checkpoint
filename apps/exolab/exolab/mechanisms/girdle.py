"""A tilted gimbal riding on a passive two-joint girdle link.

The passive link lets the gimbal centre move up and down and forward and back
with the real shoulder joint, within its range. The cuffs drag it along, so
it lags by the force needed to move it (friction plus the weight the spring
does not carry: its own and the arm hardware hanging on it) divided by the
cuff stiffness. Sideways (medial) motion is
not tracked.
"""

from __future__ import annotations

import numpy as np

from .. import vec
from ..human import G
from ..vec import v
from . import Ctx, MechState, gimbal

KIND = "girdle"


def place(mech: dict, ctx: Ctx, prev: MechState | None = None) -> MechState:
    g = mech.get("girdle", {})
    b = ctx.body
    d = ctx.pose.gh - b.gh_rest
    fwd = float(
        np.clip(
            d[0],
            -g.get("range_back_mm", 40) / 1000,
            g.get("range_forward_mm", 40) / 1000,
        )
    )
    up = float(
        np.clip(
            d[1], -g.get("range_down_mm", 20) / 1000, g.get("range_up_mm", 60) / 1000
        )
    )
    track = v(fwd, up, 0.0)
    k = max(ctx.cuff_k, 1.0)
    moved = vec.norm(track)
    lag = (
        -vec.unit(track, v(0, 1, 0))
        * float(g.get("friction_n", 5.0))
        / k
        * min(1.0, moved / 0.005)
    )
    hung = float(g.get("moving_mass_kg", 1.0)) + ctx.carried_kg
    unbalanced = (1.0 - float(g.get("spring_balance", 0.8))) * hung * G
    sag = v(0.0, -unbalanced / k, 0.0)
    off = np.array(mech.get("centre_offset_mm", [0, 0, 0]), dtype=float) / 1000.0
    centre = b.gh_rest + off + track + lag + sag
    st = gimbal.solve(mech, centre, ctx, prev)
    st.passive = track
    rho = st.layout["pod_radius"]
    anchor = v(b.chest[0] - 0.13, b.gh_rest[1] - 0.10, b.gh_rest[2] * 0.3)
    end = centre + rho * st.axes[0]
    knee = (anchor + end) / 2 + v(-0.03, 0.04, 0.0)
    st.layout["girdle"] = [anchor, knee, end]
    st.layout["base"] = [anchor, anchor + v(0.0, -0.18, 0.0)]
    if abs(d[0] - fwd) > 1e-6 or abs(d[1] - up) > 1e-6:
        st.notes.append("girdle link at the end of its range")
    return st
