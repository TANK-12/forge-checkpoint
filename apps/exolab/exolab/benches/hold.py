"""Hold a load still at standard poses."""

from __future__ import annotations

from ..arm import Rig, kinematics, loads
from . import check, frame_json, gravest, level_of, rules_for, worst

KIND = "hold"


def run(rig: Rig, test: dict, reg) -> dict:
    prm = test.get("params", {})
    rules = rules_for(rig, test)
    dur = float(prm.get("duration_s", 60))
    strength = rig.body.strength
    sustain = float(strength.get("shoulder_flexion_nm", 35)) * float(
        strength.get("sustained_fraction", 0.15)
    )
    verdict = "pass"
    rows, cards, frames = [], [], []
    s = rig.suit
    for ps in prm.get("poses", []):
        fr = kinematics(
            rig,
            ps["plane"],
            ps["elev"],
            ps.get("axial", 0),
            ps.get("elbow", 0),
            float(ps.get("payload_kg", 0)),
        )
        ld = loads(rig, fr)
        issues = check(rig, fr, ld, rules)
        if ld["human_shoulder_nm"] > float(strength.get("shoulder_flexion_nm", 35)):
            issues.append(
                {
                    "level": "fail",
                    "code": "human",
                    "part": "human",
                    "text": f"the wearer needs {ld['human_shoulder_nm']:.1f} N·m, more than their maximum",
                    "value": ld["human_shoulder_nm"],
                }
            )
        elif ld["human_shoulder_nm"] > sustain:
            issues.append(
                {
                    "level": "warn",
                    "code": "human",
                    "part": "human",
                    "text": f"the wearer carries {ld['human_shoulder_nm']:.1f} N·m, above the {sustain:.1f} N·m they can hold for long",
                    "value": ld["human_shoulder_nm"],
                }
            )
        lvl = level_of(issues)
        verdict = worst(verdict, lvl)
        watts = 0.0
        for key, tau in ld["torques"].items():
            j = (
                s.elbow
                if key == "elbow"
                else (
                    s.joints[int(key[1:]) - 1]
                    if key[1:].isdigit() and int(key[1:]) <= len(s.joints)
                    else None
                )
            )
            if j and j.powered:
                watts += 0.25 * j.power_cont * (tau / max(j.torque_cont, 1e-9)) ** 2
        load_pct = {}
        for key, tau in ld["torques"].items():
            j = (
                s.elbow
                if key == "elbow"
                else (
                    s.joints[int(key[1:]) - 1]
                    if key[1:].isdigit() and int(key[1:]) <= len(s.joints)
                    else None
                )
            )
            if j and j.powered:
                load_pct[key] = round(100 * abs(tau) / max(j.torque_cont, 1e-9))
        sf = min((b["safety"] for b in ld["structure"]), default=999.0)
        rows.append(
            {
                "name": ps["name"],
                "payload_kg": ps.get("payload_kg", 0),
                "level": lvl,
                "torques": {k: round(v, 2) for k, v in ld["torques"].items()},
                "load_pct": load_pct,
                "human_nm": round(ld["human_shoulder_nm"], 2),
                "human_sustain_nm": round(sustain, 2),
                "min_safety": sf,
                "hand_sag_mm": round(ld["hand_sag_mm"], 1),
                "watts": round(watts, 1),
                "energy_wh": round(2 * watts * dur / 3600, 3),
                "issues": issues,
            }
        )
        frames.append(frame_json(rig, fr, ld, issues, rules=rules))
        cards.append(
            {
                "level": lvl,
                "title": f"{ps['name']} · {ps.get('payload_kg', 0)} kg",
                "value": f"motor {max(load_pct.values(), default=0)}% · you {ld['human_shoulder_nm']:.1f} N·m",
                "text": "; ".join(i["text"] for i in gravest(issues)[:3])
                or f"held cleanly, hand sags {ld['hand_sag_mm']:.1f} mm, weakest beam safety {sf:.1f}",
            }
        )
    return {
        "kind": KIND,
        "verdict": verdict,
        "cards": cards,
        "rows": rows,
        "frames": frames,
        "duration_s": dur,
    }
