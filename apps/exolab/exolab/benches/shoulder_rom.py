"""Sweep the whole human shoulder range and see what the exo can follow."""

from __future__ import annotations

import numpy as np

from .. import human, vec
from ..arm import Rig, kinematics, loads
from . import check, level_of, rules_for, worst

KIND = "shoulder_rom"
# Plane x elevation cells a live re-run can afford (about 2 ms each).
MAX_CELLS = 3000


def run(rig: Rig, test: dict, reg) -> dict:
    prm = test.get("params", {})
    rules = rules_for(rig, test)
    rom = rig.rom
    ps = float(prm.get("plane_step", 10))
    es = float(prm.get("elev_step", 10))
    elbow = float(prm.get("elbow_deg", 30))
    if not (ps > 0 and es > 0):
        raise ValueError("the plane and elevation steps must be above 0")
    planes = list(np.arange(rom["plane_deg"][0], rom["plane_deg"][-1] + 1e-6, ps))
    elevs = list(np.arange(0.0, 180.0 + 1e-6, es))
    if not planes:
        raise ValueError("the human range has no plane to sweep (plane_deg)")
    if len(planes) * len(elevs) > MAX_CELLS:
        raise ValueError(
            f"a range sweep of {len(planes) * len(elevs)} cells is too slow to run"
            f" live; the most is {MAX_CELLS}: use bigger plane or elevation steps"
        )
    cells = []
    counts = {"pass": 0, "warn": 0, "fail": 0}
    worst_mis = (0.0, None)
    worst_kpa = (0.0, None)
    min_sing = (2.0, None)
    reasons: dict[str, int] = {}
    for pl in planes:
        prev = None
        for el in elevs:
            # The arm's direction in the body frame, for the 3D reach dome.
            d = vec.r3(vec.arm_to_body(human.arm_dir(pl, el)), 3)
            if el > human.max_elevation(pl, rom) + 1e-6:
                cells.append({"plane": pl, "elev": el, "level": "out", "dir": d})
                continue
            twists = [0.0]
            if prm.get("check_twist", True):
                lo, hi = human.axial_limits(el, rom)
                twists += [lo, hi]
            lvl, why, mis_mm, kpa, sing = "pass", "", 0.0, 0.0, 1.0
            for ax in twists:
                fr = kinematics(
                    rig, pl, el, ax, elbow, 0.0, prev if ax == 0.0 else None
                )
                if ax == 0.0:
                    prev = fr
                ld = loads(rig, fr)
                issues = check(rig, fr, ld, rules)
                if ax != 0.0:
                    # At the twist extremes only the joint limits matter.
                    issues = [i for i in issues if i["code"] == "limit"]
                lv = level_of(issues)
                if (
                    lv != "pass"
                    and worst(lv, lvl) == lv
                    and lv != lvl
                    or (lv == "fail" and not why)
                ):
                    why = issues[0]["text"] if issues else ""
                lvl = worst(lvl, lv)
                if ax == 0.0:
                    mis_mm = vec.norm(fr.mech.centre - fr.pose.gh) * 1000
                    kpa = max((c["pressure_kpa"] for c in ld["cuffs"]), default=0.0)
                    sing = fr.mech.sing
                for i in issues:
                    reasons[i["code"]] = reasons.get(i["code"], 0) + 1
            counts[lvl] += 1
            if mis_mm > worst_mis[0]:
                worst_mis = (mis_mm, (pl, el))
            if kpa > worst_kpa[0]:
                worst_kpa = (kpa, (pl, el))
            if rig.kind != "cable" and sing < min_sing[0]:
                min_sing = (sing, (pl, el))
            cells.append(
                {
                    "plane": float(pl),
                    "elev": float(el),
                    "level": lvl,
                    "why": why,
                    "misalign_mm": round(mis_mm, 1),
                    "kpa": round(kpa, 2),
                    "sing": round(sing, 3),
                    "dir": d,
                }
            )
    reach = sum(counts.values())
    # The same sweep over the shipped human range: a pass over a sliver of
    # the range (an edited range squeezed flat or low) says little.
    usual = human.checked_rom(reg.get("human", "rom"))
    usual_reach = sum(
        el <= human.max_elevation(pl, usual) + 1e-6
        for pl in np.arange(usual["plane_deg"][0], usual["plane_deg"][-1] + 1e-6, ps)
        for el in elevs
    )
    tested = 100.0 * reach / max(usual_reach, 1)
    few = tested < rules["tested_warn_pct"]
    followed = 100.0 * (counts["pass"] + counts["warn"]) / max(reach, 1)
    clean = 100.0 * counts["pass"] / max(reach, 1)
    verdict = (
        "pass"
        if followed >= rules["followed_pass_pct"]
        else ("warn" if followed >= rules["followed_warn_pct"] else "fail")
    )
    cards = [
        {
            "level": verdict,
            "title": "Range followed",
            "value": f"{followed:.0f}%",
            "text": f"of the {reach} arm directions a person can reach, the exo follows {followed:.0f}% ({clean:.0f}% with no warning at all).",
        },
        {
            "level": (
                "fail"
                if worst_mis[0] > rules["misalign_fail_mm"]
                else ("warn" if worst_mis[0] > rules["misalign_warn_mm"] else "pass")
            ),
            "title": "Worst misalignment",
            "value": f"{worst_mis[0]:.0f} mm",
            "text": _where(
                worst_mis[1], "between the exo centre and the real shoulder joint"
            ),
        },
        {
            "level": (
                "fail"
                if worst_kpa[0] > rules["pressure_fail_kpa"]
                else ("warn" if worst_kpa[0] > rules["pressure_warn_kpa"] else "pass")
            ),
            "title": "Worst strap pressure",
            "value": f"{worst_kpa[0]:.1f} kPa",
            "text": _where(
                worst_kpa[1], f"(all-day limit {rules['pressure_warn_kpa']} kPa)"
            ),
        },
    ]
    cards.append(
        {
            "level": "warn" if few else "pass",
            "title": "Range tested",
            "value": f"{min(tested, 100.0):.0f}%",
            "text": (
                f"the sweep covers {'only ' if few else ''}{reach} arm directions, "
                + (
                    f"more than the usual human range ({usual_reach} at these steps)."
                    if reach > usual_reach
                    else f"{tested:.0f}% of the usual human range at these steps"
                    + (", so a pass says little." if few else ".")
                )
            ),
        }
    )
    if rig.kind != "cable":
        cards.append(
            {
                "level": (
                    "fail"
                    if min_sing[0] < rules["sing_fail"]
                    else ("warn" if min_sing[0] < rules["sing_warn"] else "pass")
                ),
                "title": "Closest to gimbal lock",
                "value": f"{min_sing[0]:.2f}",
                "text": _where(min_sing[1], "(1 = far, 0 = locked)"),
            }
        )
    # The headline is the share of directions followed; a card that fails
    # somewhere in the range still keeps it from reading as a clean pass.
    if few or any(c["level"] == "fail" for c in cards[1:]):
        verdict = worst(verdict, "warn")
    return {
        "kind": KIND,
        "verdict": verdict,
        "cards": cards,
        "metrics": {
            "followed_pct": round(followed, 1),
            "clean_pct": round(clean, 1),
            "tested_pct": round(tested, 1),
            "worst_misalign_mm": round(worst_mis[0], 1),
            "worst_kpa": round(worst_kpa[0], 2),
            "min_sing": round(min_sing[0], 3) if rig.kind != "cable" else None,
            "reasons": reasons,
        },
        "map": {
            "planes": [float(x) for x in planes],
            "elevs": [float(x) for x in elevs],
            "elbow": elbow,
            "cells": cells,
            "gh": vec.r3(vec.arm_to_body(rig.body.gh_rest), 4),
            "reach_m": round(rig.body.l_upper + rig.body.l_fore, 3),
        },
    }


def _where(at, tail: str) -> str:
    if not at:
        return tail
    return f"at plane {at[0]:.0f}°, elevation {at[1]:.0f}° {tail}"
