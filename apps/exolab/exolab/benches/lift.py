"""Lift a box from waist to overhead and back, over and over."""

from __future__ import annotations

from ..arm import Rig
from . import (
    check,
    energy,
    frame_json,
    gravest,
    keep_worst,
    level_of,
    play,
    rules_for,
    worst,
)

KIND = "lift"


def run(rig: Rig, test: dict, reg) -> dict:
    prm = test.get("params", {})
    rules = rules_for(rig, test)
    fps = float(prm.get("fps", 30))
    per_arm = float(prm.get("box_kg", 10)) / 2.0
    played = play(rig, prm["keys"], fps, per_arm)
    verdict = "pass"
    frames: list[dict] = []
    issues_seen: dict[tuple[str, str], dict] = {}
    peaks: dict[str, float] = {}
    series = {"t": [], "power_w": []}
    for i, (fr, ld, speeds) in enumerate(played):
        issues = check(rig, fr, ld, rules, speeds)
        verdict = worst(verdict, level_of(issues))
        keep_worst(issues_seen, issues)
        for k, t in ld["torques"].items():
            peaks["torque_" + k] = max(peaks.get("torque_" + k, 0.0), abs(t))
        for k, w in speeds.items():
            peaks["speed_" + k] = max(peaks.get("speed_" + k, 0.0), abs(w))
        if i % max(1, int(fps // 15)) == 0 or i == len(played) - 1:
            frames.append(frame_json(rig, fr, ld, issues, speeds, rules))
    en = energy(rig, played, fps)
    per_lift_j = 2 * en["energy_j"]  # both arms
    usable = float(prm.get("usable_battery", 0.8)) * rig.suit.battery_wh * 3600
    lifts = usable / per_lift_j if per_lift_j > 0 else None  # nothing draws
    cycle_s = max(float(k["t"]) for k in prm["keys"])  # typed in any order
    cards = [
        {
            "level": verdict,
            "title": "Lift",
            "value": f"{per_arm * 2:.0f} kg box",
            "text": "; ".join(
                i["text"] for i in gravest(list(issues_seen.values()))[:3]
            )
            or "every frame within limits",
        },
        {
            "level": "pass",
            "title": "Energy per lift",
            "value": f"{per_lift_j:.0f} J",
            "text": f"both arms, peak {2 * en['peak_w']:.0f} W, mean {2 * en['mean_w']:.0f} W",
        },
        (
            {
                "level": "pass" if lifts >= 500 else "warn",
                "title": "Lifts per charge",
                "value": f"{lifts:.0f}",
                "text": f"{rig.suit.battery_wh:.0f} Wh battery, {cycle_s:.1f} s a lift: about {lifts * cycle_s / 3600:.1f} h of steady lifting (arms only)",
            }
            if lifts is not None
            else {
                "level": "warn",
                "title": "Lifts per charge",
                "value": "no draw",
                "text": "no powered arm drive takes power from the battery, so the wearer does all the lifting",
            }
        ),
    ]
    return {
        "kind": KIND,
        "verdict": verdict,
        "cards": cards,
        "peaks": {k: round(v, 2) for k, v in peaks.items()},
        "energy_per_lift_j": round(per_lift_j, 1),
        "lifts_per_charge": round(lifts, 0) if lifts is not None else None,
        "frames": frames,
        "series": series,
    }
