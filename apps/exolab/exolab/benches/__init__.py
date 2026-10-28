"""Bench tests, one module per kind, found by scanning this package.

Each module sets ``KIND`` (the ``kind`` field in data/tests/*.json) and
defines ``run(rig, test, reg) -> dict``. Shared here: the pass/warn/fail
checks, motion sampling with accelerations, and the per-frame data the page
draws (bone rotations for the character, the mechanism layout, forces).
"""

from __future__ import annotations

import importlib
import math
import pkgutil
from types import ModuleType

import numpy as np

from .. import human, vec
from ..arm import Frame, Rig, kinematics, loads

KINDS: dict[str, ModuleType] = {}
LEVELS = ("pass", "warn", "fail")

DEFAULT_RULES = {
    "sing_warn": 0.15,
    "sing_fail": 0.05,
    "misalign_warn_mm": 10.0,
    "misalign_fail_mm": 30.0,
    "safety_warn": 2.0,
    "safety_fail": 1.0,
    # Hand sag under load, from link bending plus drive compliance: past the
    # warn level the wearer feels the frame flex, past fail it gives way.
    "sag_warn_mm": 15.0,
    "sag_fail_mm": 40.0,
    # A range sweep over less than this share of the shipped human range (at
    # the same steps) says little, so it cannot read as a clean pass.
    "tested_warn_pct": 50.0,
}

# Work caps that keep a live re-run to a few seconds: the shortest motion
# (shorter ones divide by a vanishing time step) and the most frames in one.
MIN_MOTION_S = 0.1
MIN_KEY_GAP_S = 0.05  # the shipped motions keep their keys 0.25 s or more apart
MAX_FRAMES = 1000


def rules_for(rig: Rig, test: dict) -> dict:
    r = dict(DEFAULT_RULES)
    r["pressure_warn_kpa"] = float(rig.comfort.get("pressure_long_kpa", 4.3))
    r["pressure_fail_kpa"] = float(rig.comfort.get("pressure_short_kpa", 13.3))
    r.update(test.get("rules") or {})
    return r


def check(
    rig: Rig, fr: Frame, ld: dict, rules: dict, speeds: dict | None = None
) -> list[dict]:
    """Every problem in one frame: {level, code, part, text, value}."""
    out: list[dict] = []
    ms, s = fr.mech, rig.suit

    def add(level: str, code: str, part: str, text: str, value: float) -> None:
        out.append(
            {
                "level": level,
                "code": code,
                "part": part,
                "text": text,
                "value": round(value, 3),
            }
        )

    if rig.kind != "cable":
        for j, q in zip(s.joints, ms.q):
            lo, hi = j.limits
            if not lo <= q <= hi:
                add(
                    "fail",
                    "limit",
                    j.key,
                    f"{j.key} past its limit ({math.degrees(q):.0f} deg)",
                    math.degrees(q),
                )
        if ms.sing < rules["sing_fail"]:
            add(
                "fail",
                "lock",
                "J1",
                f"gimbal lock: axes 1 and 3 nearly line up ({ms.sing:.2f})",
                ms.sing,
            )
        elif ms.sing < rules["sing_warn"]:
            add("warn", "lock", "J1", f"close to gimbal lock ({ms.sing:.2f})", ms.sing)
        if ms.clash:
            add("fail", "clash", "J2", f"mechanism runs into the {ms.clash}", 1.0)
        mis = vec.norm(ms.centre - fr.pose.gh) * 1000
        if mis > rules["misalign_fail_mm"]:
            add(
                "fail",
                "misalign",
                "J1",
                f"centre {mis:.0f} mm off the shoulder joint",
                mis,
            )
        elif mis > rules["misalign_warn_mm"]:
            add(
                "warn",
                "misalign",
                "J1",
                f"centre {mis:.0f} mm off the shoulder joint",
                mis,
            )
    lo_e, hi_e = s.elbow.limits
    if not lo_e - 1e-6 <= math.radians(fr.pose.elbow) <= hi_e + 1e-6:
        add("fail", "limit", "elbow", "elbow past its limit", fr.pose.elbow)
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
        if j is None or not j.powered:
            continue
        if abs(tau) > j.torque_peak:
            add(
                "fail",
                "torque",
                key,
                f"{key} needs {abs(tau):.1f} N·m, peak is {j.torque_peak:.1f}",
                abs(tau) / max(j.torque_peak, 1e-9),
            )
        elif abs(tau) > j.torque_cont:
            add(
                "warn",
                "torque",
                key,
                f"{key} above its continuous torque ({abs(tau):.1f} of {j.torque_cont:.1f} N·m)",
                abs(tau) / max(j.torque_cont, 1e-9),
            )
        if speeds and key in speeds and abs(speeds[key]) > j.speed_max:
            add(
                "fail",
                "speed",
                key,
                f"{key} needs {abs(speeds[key]):.1f} rad/s, top speed is {j.speed_max:.1f}",
                abs(speeds[key]) / max(j.speed_max, 1e-9),
            )
    if ld.get("cable") and ld["assist_delivered"] < 0.5 * s.assist_share:
        add(
            "warn",
            "cable",
            "J1",
            f"cable gives only {ld['assist_delivered'] * 100:.0f}% assist here (poor leverage)",
            ld["assist_delivered"],
        )
    if ld.get("unpowered_nm", 0) > 1.0:
        add(
            "warn",
            "unpowered",
            "J3",
            f"an unpowered joint leaves {ld['unpowered_nm']:.1f} N·m to the wearer",
            ld["unpowered_nm"],
        )
    for c in ld["cuffs"]:
        if c["pressure_kpa"] > rules["pressure_fail_kpa"]:
            add(
                "fail",
                "pressure",
                c["id"],
                f"{c['name']} presses {c['pressure_kpa']:.1f} kPa (pain level)",
                c["pressure_kpa"],
            )
        elif c["pressure_kpa"] > rules["pressure_warn_kpa"]:
            add(
                "warn",
                "pressure",
                c["id"],
                f"{c['name']} presses {c['pressure_kpa']:.1f} kPa (not all-day)",
                c["pressure_kpa"],
            )
    for b in ld["structure"]:
        if b["safety"] < rules["safety_fail"]:
            add(
                "fail",
                "break",
                b["id"],
                f"{b['name']} breaks (safety factor {b['safety']:.2f})",
                b["safety"],
            )
        elif b["safety"] < rules["safety_warn"]:
            add(
                "warn",
                "break",
                b["id"],
                f"{b['name']} safety factor only {b['safety']:.2f}",
                b["safety"],
            )
    sag = float(ld.get("hand_sag_mm", 0.0))
    if sag > rules["sag_fail_mm"]:
        add("fail", "sag", "hand", f"hand sags {sag:.0f} mm (the frame gives way)", sag)
    elif sag > rules["sag_warn_mm"]:
        add("warn", "sag", "hand", f"hand sags {sag:.0f} mm (you feel it flex)", sag)
    return out


def level_of(issues: list[dict]) -> str:
    if any(i["level"] == "fail" for i in issues):
        return "fail"
    return "warn" if issues else "pass"


def worst(a: str, b: str) -> str:
    return a if LEVELS.index(a) >= LEVELS.index(b) else b


LOWER_WORSE = (
    "lock",
    "break",
    "fit",
    "clash",
    "overlap",
)  # issue codes whose value is worse when smaller


def graver(a: dict, b: dict) -> bool:
    """Is issue ``a`` worse than ``b``: a higher level, else a worse value."""
    la, lb = LEVELS.index(a["level"]), LEVELS.index(b["level"])
    if la != lb:
        return la > lb
    return (
        a["value"] < b["value"] if a["code"] in LOWER_WORSE else a["value"] > b["value"]
    )


def keep_worst(found: dict[tuple[str, str], dict], issues: list[dict]) -> None:
    """Keep the worst issue per (code, part) across frames."""
    for it in issues:
        key = (it["code"], it["part"])
        if key not in found or graver(it, found[key]):
            found[key] = it


def gravest(issues: list[dict]) -> list[dict]:
    """Issues sorted fails first."""
    return sorted(issues, key=lambda i: -LEVELS.index(i["level"]))


def _pt(a) -> list[float]:
    return vec.r3(vec.arm_to_body(np.asarray(a, dtype=float)), 4)


def layout(rig: Rig, fr: Frame, rules: dict | None = None) -> dict:
    """Everything the page draws for the right arm, in the body frame."""
    p, ms, s, b = fr.pose, fr.mech, rig.suit, rig.body
    r = rules or DEFAULT_RULES
    lat = p.R[:, 2]
    r_ua = b.limb_radius.get("upper_arm", 0.042)
    r_fa = b.limb_radius.get("forearm", 0.034)
    out: dict = {
        "kind": rig.kind,
        "gh": _pt(p.gh),
        "centre": _pt(ms.centre),
        "elbow": _pt(p.elbow_pt),
        "wrist": _pt(p.wrist),
        "hand": _pt(p.hand),
    }
    ua = s.links.get("upper_arm_link")
    fa = s.links.get("forearm_link")
    if rig.kind != "cable":
        rho = ms.layout["pod_radius"]
        off_u = r_ua + (ua.side_offset if ua else 0.02)
        off_f = r_fa + (fa.side_offset if fa else 0.02)
        ring = ms.centre + rho * ms.link_dir
        joint_e = fr.exo_elbow + lat * off_f
        out.update(
            {
                "axes": [vec.r3(vec.arm_to_body(a)) for a in ms.axes],
                "pods": [_pt(x) for x in ms.layout["pods"]],
                "link1": [_pt(x) for x in ms.layout["link1"]],
                "link2": [_pt(x) for x in ms.layout["link2"]],
                "base": [_pt(x) for x in ms.layout["base"]],
                "ring": {
                    "at": _pt(ring),
                    "axis": vec.r3(vec.arm_to_body(ms.link_dir)),
                    "radius": round(r_ua + 0.012, 4),
                },
                "upper_strut": [_pt(ring + lat * off_u), _pt(joint_e)],
                "elbow_joint": {
                    "at": _pt(joint_e),
                    "axis": vec.r3(vec.arm_to_body(lat)),
                },
                "fore_strut": [
                    _pt(joint_e),
                    _pt(joint_e + p.f * (fa.length if fa else 0.18)),
                ],
                "strut_d": [
                    round(ua.section.outer, 4) if ua else 0.024,
                    round(fa.section.outer, 4) if fa else 0.02,
                ],
            }
        )
        # The lock zone round axis 1: the lock measure is the sine of the angle
        # between axis 1 and the line from the exo centre to the elbow.
        out["lock"] = {
            "warn_deg": round(math.degrees(math.asin(min(1.0, r["sing_warn"]))), 2),
            "fail_deg": round(math.degrees(math.asin(min(1.0, r["sing_fail"]))), 2),
            "length": round(b.l_upper, 3),
        }
        if "girdle" in ms.layout:
            out["girdle"] = [_pt(x) for x in ms.layout["girdle"]]
    else:
        out["cable"] = [_pt(x) for x in ms.layout["cable"]]
    out["cuffs"] = [
        {
            "id": c["spec"]["id"],
            "at": _pt(c["exo"]),
            "axis": vec.r3(vec.arm_to_body(c["axis"])),
            "radius": round(c["spec"]["radius"], 4),
            "width": round(c["spec"]["width"], 4),
            "force": vec.r3(vec.arm_to_body(c["f_spring"]), 2),
        }
        for c in fr.cuffs
    ]
    return out


def frame_json(
    rig: Rig,
    fr: Frame,
    ld: dict,
    issues: list[dict],
    speeds: dict | None = None,
    rules: dict | None = None,
) -> dict:
    ms = fr.mech
    return {
        "t": round(fr.t, 3),
        "pose": {
            "plane": fr.pose.plane,
            "elev": fr.pose.elev,
            "axial": fr.pose.axial,
            "elbow": fr.pose.elbow,
        },
        "payload_kg": fr.payload,
        "bones": human.vrm_bones(fr.pose),
        "layout": layout(rig, fr, rules),
        "misalign_mm": round(vec.norm(ms.centre - fr.pose.gh) * 1000, 1),
        "sing": round(ms.sing, 3),
        "q_deg": (
            [round(math.degrees(x), 1) for x in ms.q] if rig.kind != "cable" else []
        ),
        "torques": {k: round(v, 2) for k, v in ld["torques"].items()},
        "speeds": {k: round(v, 2) for k, v in (speeds or {}).items()},
        "human_shoulder_nm": round(ld["human_shoulder_nm"], 2),
        "human_elbow_nm": round(ld["human_elbow_nm"], 2),
        "assist": round(ld["assist_delivered"], 3),
        "cuffs": ld["cuffs"],
        "structure": ld["structure"],
        "hand_sag_mm": round(ld["hand_sag_mm"], 1),
        "issues": issues,
        "level": level_of(issues),
    }


def check_motion(keys: list[dict], fps: float) -> tuple[list[dict], int]:
    """The keys sorted by time and the frame count, once the motion can be
    played: keys at least MIN_KEY_GAP_S apart, at least MIN_MOTION_S long,
    at most MAX_FRAMES at this frame rate (a ValueError says which not)."""
    if not fps > 0:
        raise ValueError("fps must be above 0")
    if not keys:
        raise ValueError("a motion needs keys")
    keys = sorted(keys, key=lambda k: k["t"])
    for a, b in zip(keys, keys[1:]):
        gap = b["t"] - a["t"]
        # a hair of slack: 0.3 - 0.25 is 0.04999999999999999 in binary
        if not gap >= MIN_KEY_GAP_S - 1e-9:
            raise ValueError(
                f"a motion's keys must be at least {MIN_KEY_GAP_S} s apart (two"
                f" are {gap:.6g} s apart at {a['t']:g} s)"
            )
    end = keys[-1]["t"]
    if not end >= MIN_MOTION_S:
        raise ValueError(
            f"a motion must last at least {MIN_MOTION_S} s (this one lasts {end:g} s)"
        )
    n = max(2, int(round(end * fps)) + 1)
    if n > MAX_FRAMES:
        raise ValueError(
            f"{n} frames in one motion is too slow to run live; the most is"
            f" {MAX_FRAMES}: lower the frame rate or shorten the motion"
        )
    return keys, n


def sample(keys: list[dict], fps: float) -> list[dict]:
    """Minimum-jerk blend between key poses, ``fps`` samples a second."""
    keys, n = check_motion(keys, fps)
    end = keys[-1]["t"]
    out = []
    for i in range(n):
        t = end * i / (n - 1)
        j = 0
        while j < len(keys) - 2 and t > keys[j + 1]["t"]:
            j += 1
        a, b = keys[j], keys[min(j + 1, len(keys) - 1)]
        span = b["t"] - a["t"]
        w = vec.min_jerk((t - a["t"]) / span) if span > 0 else 1.0
        pose = {
            f: a.get(f, 0.0) + (b.get(f, 0.0) - a.get(f, 0.0)) * w
            for f in ("plane", "elev", "axial", "elbow")
        }
        out.append(dict(pose, t=t))
    return out


def play(
    rig: Rig, keys: list[dict], fps: float, payload: float
) -> list[tuple[Frame, dict, dict]]:
    """Kinematics then inverse dynamics for a motion: (frame, loads, joint speeds)."""
    poses = sample(keys, fps)
    frames: list[Frame] = []
    prev = None
    for ps in poses:
        fr = kinematics(
            rig,
            ps["plane"],
            ps["elev"],
            ps["axial"],
            ps["elbow"],
            payload,
            prev,
            ps["t"],
        )
        frames.append(fr)
        prev = fr
    dt = 1.0 / fps
    segs = rig.body.segments
    out = []
    for i, fr in enumerate(frames):
        a = frames[max(0, i - 1)]
        c = frames[min(len(frames) - 1, i + 1)]
        span = (c.t - a.t) or dt
        acc: dict[str, np.ndarray] = {}
        for k, pt in enumerate(fr.points):
            pa, pc = a.points[k].pos, c.points[k].pos
            acc[pt.name] = (
                (pc - 2 * pt.pos + pa) / ((span / 2) ** 2)
                if c is not a
                else np.zeros(3)
            )
        spin = {}
        for name, rot_of in (
            ("upper_arm", lambda f: f.pose.R),
            ("forearm", lambda f: f.pose.R @ vec.rz(math.radians(f.pose.elbow))),
        ):
            sg = segs[name]
            inertia = sg.mass * np.diag([sg.k_perp**2, sg.k_long**2, sg.k_perp**2])

            def ang_mom(f0: Frame, f1: Frame) -> np.ndarray:
                w = vec.rot_log(rot_of(f1) @ rot_of(f0).T) / max(f1.t - f0.t, 1e-9)
                r = rot_of(f1)
                return r @ inertia @ r.T @ w

            if 0 < i < len(frames) - 1:
                spin[name] = (ang_mom(fr, c) - ang_mom(a, fr)) / (span / 2)
            else:
                spin[name] = np.zeros(3)
        ld = loads(rig, fr, acc, spin)
        if c is not a and 0 < i < len(frames) - 1:
            _rotor_torques(rig, ld, a, fr, c, span / 2)
        speeds = {}
        if rig.kind != "cable":
            for j in range(len(fr.mech.q)):
                speeds[f"J{j + 1}"] = (
                    (c.mech.q[j] - a.mech.q[j]) / span if c is not a else 0.0
                )
        else:
            spool = float(rig.suit.mech.get("spool_radius_m", 0.02))
            speeds["J1"] = (
                (c.mech.q[0] - a.mech.q[0]) / span / spool if c is not a else 0.0
            )
        speeds["elbow"] = (
            math.radians(c.pose.elbow - a.pose.elbow) / span if c is not a else 0.0
        )
        out.append((fr, ld, speeds))
    return out


def _rotor_torques(
    rig: Rig, ld: dict, a: Frame, fr: Frame, c: Frame, dt: float
) -> None:
    """Add the torque each geared motor spends spinning up its own rotor:
    reflected inertia (rotor x ratio squared) x joint acceleration."""
    s = rig.suit
    acc: dict[str, float] = {}
    if rig.kind != "cable":
        for j, jt in enumerate(s.joints[: len(fr.mech.q)]):
            acc[jt.key] = (c.mech.q[j] - 2 * fr.mech.q[j] + a.mech.q[j]) / dt**2
    acc["elbow"] = math.radians(c.pose.elbow - 2 * fr.pose.elbow + a.pose.elbow) / dt**2
    rotor = {}
    for key, qdd in acc.items():
        jt = s.elbow if key == "elbow" else s.joints[int(key[1:]) - 1]
        if jt.powered and jt.inertia > 0 and key in ld["torques"]:
            rotor[key] = jt.inertia * qdd
            ld["torques"][key] += rotor[key]
    ld["rotor"] = rotor


def energy(rig: Rig, played: list[tuple[Frame, dict, dict]], fps: float) -> dict:
    """Battery energy for one arm over a motion: motor output over efficiency
    plus copper loss (about a quarter of rated power at continuous torque).
    No regeneration."""
    s = rig.suit
    dt = 1.0 / fps
    total = 0.0
    peak_power = 0.0
    for _fr, ld, speeds in played:
        p = 0.0
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
            if j is None or not j.powered:
                continue
            mech = tau * speeds.get(key, 0.0)
            copper = 0.25 * j.power_cont * (tau / max(j.torque_cont, 1e-9)) ** 2
            p += max(0.0, mech) / max(j.efficiency, 0.05) + copper
        peak_power = max(peak_power, p)
        total += p * dt
    return {
        "energy_j": total,
        "peak_w": peak_power,
        "mean_w": total / max(dt * len(played), 1e-9),
    }


def motion_errors(reg, prof: dict, ids, fps: float) -> tuple[list[str], int]:
    """check_motion on each motion a test plays, as the profile has it: the
    problems, each naming its motion, and the frames the good ones make."""
    errors: list[str] = []
    frames = 0
    for mid in ids:
        try:
            keys = reg.effective("motions", mid, prof).get("keys") or []
            frames += check_motion(keys, fps)[1]
        except (ValueError, KeyError) as e:
            errors.append(f"motion {mid}: {e.args[0] if e.args else e}")
    return errors, frames


def cross_errors(reg, prof: dict) -> list[str]:
    """Rules between fields, checked when a profile is saved so that a
    profile that saves also runs: the human range's planes rise, a test's
    own keys pass check_motion at its frame rate, and each bench module's
    save_errors(test, reg, prof), when it has one, finds nothing (the
    motions a test plays, its frame cap, its distances). Only edits to the
    human, the motions or the tests can break them."""
    edits = prof.get("overrides") or {}
    if not any(kind in edits for kind in ("human", "motions", "tests")):
        return []
    errors: list[str] = []

    def keep(what: str, fn) -> None:
        try:
            fn()
        except (ValueError, KeyError) as e:
            errors.append(f"{what}{e.args[0] if e.args else e}")

    if "rom" in edits.get("human", {}):
        keep("", lambda: human.checked_rom(reg.effective("human", "rom", prof)))
    for tid in reg.ids("tests"):
        test = reg.effective("tests", tid, prof)
        prm = test.get("params") or {}
        if "keys" in prm:
            fps = float(prm.get("fps", 30))
            keep(f"test {tid}: ", lambda: check_motion(prm["keys"], fps))
        bench = KINDS.get(str(test.get("kind", "")))
        if bench is not None and hasattr(bench, "save_errors"):
            errors += bench.save_errors(test, reg, prof)
    return list(dict.fromkeys(errors))  # a motion two tests play says it once


def _discover() -> None:
    for info in pkgutil.iter_modules(__path__):
        mod = importlib.import_module(f"{__name__}.{info.name}")
        kind = getattr(mod, "KIND", None)
        if isinstance(kind, str):
            KINDS[kind] = mod


def run(rig: Rig, test: dict, reg) -> dict:
    kind = test.get("kind", "")
    if kind not in KINDS:
        raise ValueError(f"no bench for test kind {kind!r}")
    res = KINDS[kind].run(rig, test, reg)
    res.setdefault("test", test.get("id"))
    res.setdefault("model", rig.model_id)
    res.setdefault("about", test.get("about", ""))
    return res


_discover()
