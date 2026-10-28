"""The exo arm fitted to the human arm, pose by pose.

``build`` resolves a model against a profile into a ``Rig`` (the subject's
body from the character's own skeleton, the suit's parts, the human data).
``kinematics`` places the human arm and the exo for one pose; ``loads``
works out cuff forces and pressures, joint torques, what the human still
carries and the beam stresses, either holding still or with accelerations
from a motion (d'Alembert: each mass needs m (a - g) from its supports).

The physics covers the right arm in the arm frame; the left arm is its
mirror image.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import human, mechanisms, parts, skeleton, vec
from .human import GRAVITY, ArmPose, Body
from .mechanisms import Ctx, MechState
from .registry import CHAR_DIR, Registry
from .vec import Vec


def character_path(char_id: str) -> Path:
    folder = CHAR_DIR / char_id
    found = sorted(folder.glob("*.vrm"))
    if not found:
        raise FileNotFoundError(f"no .vrm in {folder}")
    return found[0]


@dataclass
class Rig:
    model_id: str
    profile: dict
    body: Body
    skel: dict
    suit: parts.Suit
    girdle: dict
    rom: dict
    comfort: dict
    character: str

    @property
    def kind(self) -> str:
        return str(self.suit.mech.get("kind", ""))

    def cuff_k(self, cuff: dict, axial: bool = False) -> float:
        key = "cuff_axial_n_per_mm" if axial else "cuff_normal_n_per_mm"
        return (
            float(self.comfort.get(key, 3.0)) * 1000.0 * cuff.get("stiffness_mult", 1.0)
        )


def build(reg: Registry, model_id: str, profile: dict | None) -> Rig:
    prof = profile or {}
    subject = reg.effective("human", "subject", prof)
    model = reg.effective("models", model_id, prof)
    char = str(model.get("character") or subject.get("character", "hairsample_female"))
    skel = skeleton.load(str(character_path(char)))
    body = human.body_from(skel, subject, reg.effective("human", "segments", prof))
    suit = parts.resolve(reg, model_id, prof, skel["lengths"])
    return Rig(
        model_id=model_id,
        profile=prof,
        body=body,
        skel=skel,
        suit=suit,
        girdle=reg.effective("human", "girdle", prof),
        rom=human.checked_rom(reg.effective("human", "rom", prof)),
        comfort=reg.effective("human", "comfort", prof),
        character=char,
    )


@dataclass
class Point:
    name: str
    mass: float
    pos: Vec
    human: bool  # True: the human's own arm (the exo carries assist_share of it)
    joints: tuple[str, ...]  # exo joints whose torque it loads


@dataclass
class Frame:
    t: float
    pose: ArmPose
    mech: MechState
    payload: float
    exo_elbow: Vec
    link_len: float
    cuffs: list[dict]
    points: list[Point] = field(default_factory=list)


SHOULDER = ("J1", "J2", "J3")


def kinematics(
    rig: Rig,
    plane: float,
    elev: float,
    axial: float,
    elbow: float,
    payload: float = 0.0,
    prev: Frame | None = None,
    t: float = 0.0,
) -> Frame:
    b, s = rig.body, rig.suit
    p = human.pose(b, rig.girdle, plane, elev, axial, elbow)
    k_total = sum(rig.cuff_k(c) for c in s.cuffs) or 3000.0
    ms = mechanisms.place(
        s.mech, Ctx(b, p, k_total, s.arm_kg), prev.mech if prev else None
    )
    o, a3 = ms.centre, ms.link_dir
    slider = bool(s.mech.get("slider"))
    link_len = vec.norm(p.elbow_pt - o) if slider or rig.kind == "cable" else b.l_upper
    ex = o + link_len * a3 if rig.kind != "cable" else p.elbow_pt.copy()
    cuffs = []
    for c in s.cuffs:
        if c.get("segment") == "forearm":
            h = p.elbow_pt + c["at"] * b.l_fore * p.f
            x = ex + c["at"] * b.l_fore * p.f
            axis = p.f
        else:
            h = p.gh + c["at"] * b.l_upper * p.u
            x = o + c["at"] * link_len * a3
            axis = p.u
        d = x - h if rig.kind != "cable" else np.zeros(3)
        d_ax = float(np.dot(d, axis)) * axis
        d_n = d - d_ax
        f_spring = rig.cuff_k(c) * d_n + rig.cuff_k(c, axial=True) * d_ax
        cuffs.append(
            dict(spec=c, human=h, exo=x, delta=d, axis=axis, f_spring=f_spring)
        )
    pts: list[Point] = []
    seg = b.segments
    arm_shells = {"UpperArm": 0.0, "LowerArm": 0.0, "Hand": 0.0}
    for sh in s.shells:
        if sh.get("bone") in arm_shells:
            arm_shells[sh["bone"]] += sh["mass"] / max(1, sh.get("copies", 1))
    pts.append(
        Point(
            "upper arm",
            seg["upper_arm"].mass + arm_shells["UpperArm"],
            p.coms["upper_arm"],
            True,
            SHOULDER,
        )
    )
    pts.append(
        Point(
            "forearm",
            seg["forearm"].mass + arm_shells["LowerArm"],
            p.coms["forearm"],
            True,
            SHOULDER + ("elbow",),
        )
    )
    pts.append(
        Point(
            "hand",
            seg["hand"].mass + arm_shells["Hand"],
            p.coms["hand"],
            True,
            SHOULDER + ("elbow",),
        )
    )
    if payload > 0:
        # Gripped by load-bearing gauntlets the load is the frame's, not the arm's.
        pts.append(
            Point("payload", payload, p.hand.copy(), not s.grip, SHOULDER + ("elbow",))
        )
    if rig.kind != "cable":
        j = s.joints
        pods = ms.layout["pods"]
        if len(j) > 1:
            pts.append(Point("J2 drive", j[1].mass, pods[1], False, ("J1",)))
        if len(j) > 2:
            pts.append(Point("J3 drive", j[2].mass, pods[2], False, ("J1", "J2")))
        ua = s.links.get("upper_arm_link")
        if ua:
            pts.append(
                Point(
                    "upper-arm strut", ua.mass, o + 0.5 * link_len * a3, False, SHOULDER
                )
            )
        pts.append(Point("elbow drive", s.elbow.mass, ex.copy(), False, SHOULDER))
        fa = s.links.get("forearm_link")
        if fa:
            pts.append(
                Point(
                    "forearm strut",
                    fa.mass,
                    ex + 0.5 * fa.length * p.f,
                    False,
                    SHOULDER + ("elbow",),
                )
            )
    for c in cuffs:
        fore = c["spec"].get("segment") == "forearm"
        js = SHOULDER + (("elbow",) if fore else ())
        pts.append(Point(c["spec"]["name"], c["spec"]["mass"], c["exo"], False, js))
    return Frame(t, p, ms, payload, ex, link_len, cuffs, pts)


def _need(pt: Point, acc: dict[str, Vec] | None) -> Vec:
    a = acc.get(pt.name) if acc else None
    return pt.mass * ((a if a is not None else 0.0) - GRAVITY)


def loads(
    rig: Rig,
    fr: Frame,
    acc: dict[str, Vec] | None = None,
    spin: dict[str, Vec] | None = None,
) -> dict:
    """Forces and torques for one frame. ``acc``: acceleration per point name;
    ``spin``: rate of change of angular momentum per human segment."""
    s, b, p, ms = rig.suit, rig.body, fr.pose, fr.mech
    share = s.assist_share
    o, ex = ms.centre, fr.exo_elbow
    spin = spin or {}
    m_h_gh = np.zeros(3)  # human arm load about the shoulder joint (all of it)
    m_h_el = np.zeros(3)  # human forearm load about the human elbow
    for pt in (q for q in fr.points if q.human):
        f = _need(pt, acc)
        m_h_gh += vec.cross(pt.pos - p.gh, f)
        if "elbow" in pt.joints:
            m_h_el += vec.cross(pt.pos - p.elbow_pt, f)
    m_h_gh += spin.get("upper_arm", 0.0) + spin.get("forearm", 0.0)
    m_h_el += spin.get("forearm", 0.0)

    def moment_about(c: Vec, joint: str) -> Vec:
        m = np.zeros(3)
        for pt in fr.points:
            if joint in pt.joints:
                w = share if pt.human else 1.0
                m += w * vec.cross(pt.pos - c, _need(pt, acc))
        if joint in SHOULDER:
            m += share * (spin.get("upper_arm", 0.0) + spin.get("forearm", 0.0))
        elif joint == "elbow":
            m += share * spin.get("forearm", 0.0)
        return m

    torques: dict[str, float] = {}
    delivered = share
    cable = None
    if rig.kind == "cable" and ms.cable:
        need = moment_about(o, "J1")
        mu = ms.cable["moment_per_n"]
        mm = float(np.dot(mu, mu))
        tension = max(0.0, float(np.dot(need, mu)) / mm) if mm > 1e-12 else 0.0
        cap = ms.cable["tension_peak"]
        t_used = min(tension, cap)
        got = vec.norm(t_used * mu)
        delivered = share * (got / vec.norm(need) if vec.norm(need) > 1e-9 else 1.0)
        spool = float(s.mech.get("spool_radius_m", 0.02))
        torques["J1"] = t_used * spool
        cable = {
            "tension_n": t_used,
            "tension_needed_n": tension,
            "lever_m": vec.norm(mu),
        }
    else:
        for i, ax in enumerate(ms.axes):
            key = f"J{i + 1}"
            torques[key] = float(np.dot(ax, moment_about(o, key)))
    e_axis = p.R[:, 2]
    torques["elbow"] = float(np.dot(e_axis, moment_about(ex, "elbow")))

    # What the human still carries, plus the cuff springs' pull (misalignment).
    human_gh = (1.0 - delivered) * m_h_gh
    unpowered = 0.0  # torque an unpowered or spring joint cannot give: the human's
    for key, tau in torques.items():
        jt = _joint(s, key)
        if (
            jt is not None
            and not jt.powered
            and not (rig.kind == "cable" and key == "J1")
        ):
            unpowered += max(
                0.0, abs(tau) - (jt.torque_cont if jt.kind == "passive_spring" else 0.0)
            )
    human_el = (1.0 - share) * m_h_el
    cuff_out = []
    for c in fr.cuffs:
        spec = c["spec"]
        fore = spec.get("segment") == "forearm"
        human_gh -= vec.cross(c["human"] - p.gh, c["f_spring"])
        if fore:
            human_el -= vec.cross(c["human"] - p.elbow_pt, c["f_spring"])
        # Support force the cuff passes to the limb, square to the limb.
        axis = c["axis"]
        lever = spec["at"] * (b.l_fore if fore else b.l_upper)
        target = share * (m_h_el if fore else m_h_gh)
        target = target - float(np.dot(target, axis)) * axis
        f_assist = vec.cross(target, axis) / max(lever, 1e-3)
        if not fore:
            f_assist = f_assist * 0.6  # the forearm cuff carries the rest
        f_n = f_assist + (c["f_spring"] - float(np.dot(c["f_spring"], axis)) * axis)
        pressure = vec.norm(f_n) / max(spec["area"], 1e-6) / 1000.0
        cuff_out.append(
            {
                "id": spec["id"],
                "name": spec["name"],
                "misalign_mm": round(vec.norm(c["delta"]) * 1000, 1),
                "spring_n": round(vec.norm(c["f_spring"]), 1),
                "force_n": round(vec.norm(f_n), 1),
                "pressure_kpa": round(pressure, 2),
            }
        )

    struct = structure(rig, fr, acc, share)
    sag = 0.0
    for key, tau in torques.items():
        jt = _joint(s, key)
        if jt is None or not jt.powered or (rig.kind == "cable" and key != "elbow"):
            continue
        lever = vec.norm(p.hand - (ex if key == "elbow" else o))
        sag += abs(tau) / max(jt.stiffness, 1.0) * lever
    sag += sum(x.get("tip_mm", 0.0) for x in struct) / 1000.0
    return {
        "torques": torques,
        "human_shoulder_nm": vec.norm(human_gh) + unpowered,
        "unpowered_nm": unpowered,
        "human_elbow_nm": abs(float(np.dot(e_axis, human_el))),
        "assist_delivered": delivered,
        "cuffs": cuff_out,
        "structure": struct,
        "hand_sag_mm": sag * 1000.0,
        "cable": cable,
    }


def _joint(s: parts.Suit, key: str) -> parts.Joint | None:
    if key == "elbow":
        return s.elbow
    i = int(key[1:]) - 1 if key.startswith("J") and key[1:].isdigit() else -1
    return s.joints[i] if 0 <= i < len(s.joints) else None


def _beam(link: parts.Link, moment: Vec, axis: Vec, length: float) -> dict:
    torsion = float(np.dot(moment, axis))
    bend = vec.norm(moment - torsion * axis)
    sec = link.section
    if sec.c <= 0 or sec.inertia <= 0:
        raise ValueError(f"{link.name} has no cross-section; give it a size")
    sigma = bend * sec.c / max(sec.inertia, 1e-15)
    tau = abs(torsion) * sec.c / max(sec.polar, 1e-15)
    vm = (sigma**2 + 3 * tau**2) ** 0.5
    tip = bend * length**2 / (3.0 * max(link.stiffness, 1e-9))
    return {
        "id": link.id,
        "name": link.name,
        "material": link.material.name,
        "stress_mpa": round(vm / 1e6, 2),
        "safety": round(link.yield_strength / vm, 2) if vm > 1 else 999.0,
        "fatigue_safety": round(link.fatigue / vm, 2) if vm > 1 else 999.0,
        "tip_mm": round(tip * 1000, 2),
        "mass_kg": round(link.mass, 3),
    }


def structure(
    rig: Rig, fr: Frame, acc: dict[str, Vec] | None, share: float
) -> list[dict]:
    s, ms, p = rig.suit, fr.mech, fr.pose
    out = []

    def moment(root: Vec, pick) -> Vec:
        m = np.zeros(3)
        for pt in fr.points:
            if pick(pt):
                w = share if pt.human else 1.0
                m += w * vec.cross(pt.pos - root, _need(pt, acc))
        return m

    if rig.kind != "cable":
        o, a3 = ms.centre, ms.link_dir
        rho = float(s.mech.get("pod_radius_m", 0.12))
        ua = s.links.get("upper_arm_link")
        if ua:
            root = o + rho * a3
            m = moment(
                root,
                lambda q: "J3" in q.joints and q.name not in ("J3 drive", "J2 drive"),
            )
            out.append(_beam(ua, m, a3, max(0.05, fr.link_len - rho)))
        fa = s.links.get("forearm_link")
        if fa:
            m = moment(fr.exo_elbow, lambda q: "elbow" in q.joints)
            out.append(_beam(fa, m, p.f, fa.length))
        gl = s.links.get("girdle_link")
        if gl and rig.kind == "girdle" and "girdle" in ms.layout:
            anchor = ms.layout["girdle"][0]
            m = moment(anchor, lambda q: True)
            out.append(
                _beam(gl, m, vec.unit(ms.layout["girdle"][2] - anchor), gl.length)
            )
    bf = s.links.get("back_frame")
    if bf:
        root = rig.body.hips + np.array([-0.12, 0.0, 0.0])
        m = 2.0 * moment(root, lambda q: True)  # both arms
        out.append(
            _beam(
                bf, m * np.array([1.0, 1.0, 0.0]), np.array([0.0, 1.0, 0.0]), bf.length
            )
        )
    return out
