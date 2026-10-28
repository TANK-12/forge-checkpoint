"""Named motions played with the exo on, frame by frame."""

from __future__ import annotations

from .. import vec
from ..arm import Rig
from ..registry import NotFound
from . import (
    check,
    energy,
    frame_json,
    gravest,
    keep_worst,
    level_of,
    motion_errors,
    play,
    rules_for,
    worst,
)

KIND = "motions"


def save_errors(test: dict, reg, prof: dict) -> list[str]:
    """What a run of this test would refuse in a saved profile: a motion it
    plays that check_motion refuses at its frame rate."""
    prm = test.get("params") or {}
    ids = prm.get("motions", reg.ids("motions"))
    return motion_errors(reg, prof, ids, float(prm.get("fps", 30)))[0]


def run(rig: Rig, test: dict, reg) -> dict:
    prm = test.get("params", {})
    rules = rules_for(rig, test)
    fps = float(prm.get("fps", 30))
    only = prm.get("only")
    ids = [m for m in prm.get("motions", reg.ids("motions")) if not only or m == only]
    if only and not ids:
        raise NotFound(f"no motion named {only!r} in this test")
    verdict = "pass"
    motions = []
    for mid in ids:
        mo = reg.effective("motions", mid, rig.profile)
        payload = float(mo.get("payload_kg", 0.0))
        played = play(rig, mo["keys"], fps, payload)
        frames, lvl = [], "pass"
        peaks: dict[str, float] = {}
        worst_issue: dict[tuple[str, str], dict] = {}
        for i, (fr, ld, speeds) in enumerate(played):
            issues = check(rig, fr, ld, rules, speeds)
            lvl = worst(lvl, level_of(issues))
            keep_worst(worst_issue, issues)
            for k, t in ld["torques"].items():
                peaks["torque_" + k] = max(peaks.get("torque_" + k, 0.0), abs(t))
            for k, w in speeds.items():
                peaks["speed_" + k] = max(peaks.get("speed_" + k, 0.0), abs(w))
            peaks["misalign_mm"] = max(
                peaks.get("misalign_mm", 0.0),
                vec.norm(fr.mech.centre - fr.pose.gh) * 1000,
            )
            peaks["kpa"] = max(
                [peaks.get("kpa", 0.0)] + [c["pressure_kpa"] for c in ld["cuffs"]]
            )
            peaks["human_nm"] = max(peaks.get("human_nm", 0.0), ld["human_shoulder_nm"])
            if i % max(1, int(fps // 15)) == 0 or i == len(played) - 1:
                frames.append(frame_json(rig, fr, ld, issues, speeds, rules))
        en = energy(rig, played, fps)
        verdict = worst(verdict, lvl)
        motions.append(
            {
                "id": mid,
                "name": mo.get("name", mid),
                "about": mo.get("about", ""),
                "payload_kg": payload,
                "level": lvl,
                "issues": gravest(list(worst_issue.values())),
                "peaks": {k: round(v, 2) for k, v in peaks.items()},
                "energy_j": round(en["energy_j"], 1),
                "peak_w": round(en["peak_w"], 1),
                "frames": frames,
            }
        )
    cards = [
        {
            "level": m["level"],
            "title": m["name"],
            "value": f"{m['peaks'].get('misalign_mm', 0):.0f} mm · {m['peak_w']:.0f} W",
            "text": "; ".join(i["text"] for i in m["issues"][:3]) or "followed cleanly",
        }
        for m in motions
    ]
    return {"kind": KIND, "verdict": verdict, "cards": cards, "motions": motions}
