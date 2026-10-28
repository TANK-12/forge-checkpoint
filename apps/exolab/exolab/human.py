"""The human arm and shoulder girdle: pose, segment masses, range of motion.

Arm pose uses the ISB angles of the humerus relative to the thorax (Wu et al.
2005, Y-X-Y sequence), right arm, in the arm frame (x forward, y up, z
lateral):

    plane of elevation  0 = out to the side, 90 = straight forward,
                        negative = behind, above 90 = across the body
    elevation           0 = hanging, 90 = level, 180 = straight up
    axial rotation      clinical: 0 = neutral, positive = internal (forearm
                        swings toward the belly)
    elbow flexion       0 = straight

The humerus frame R has columns (anterior, long axis pointing from the elbow
up to the shoulder, lateral = elbow flexion axis); R = Ry(plane) Rx(-elev)
Ry(axial - plane). The ISB third angle is axial - plane: in the raw Y-X-Y
sequence "axial 0" with the arm raised forward would leave the elbow axis
pointing up; subtracting the plane keeps 0 = neutral everywhere and makes the
hanging arm the same pose for every plane. With the arm hanging (or raised
forward) and axial 0, elbow flexion swings the forearm forward (or up).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import vec
from .vec import Mat, Vec, v

G = 9.81
GRAVITY = v(0.0, -G, 0.0)
# Humerus frame in the VRM rest pose (T-pose, arm out sideways, palm down).
R_TPOSE = vec.rx(-math.pi / 2)


def arm_dir(plane_deg: float, elev_deg: float) -> Vec:
    """Unit vector from the shoulder joint toward the elbow."""
    p, e = math.radians(plane_deg), math.radians(elev_deg)
    return v(math.sin(e) * math.sin(p), -math.cos(e), math.sin(e) * math.cos(p))


def humerus_frame(plane_deg: float, elev_deg: float, axial_deg: float) -> Mat:
    return (
        vec.ry(math.radians(plane_deg))
        @ vec.rx(-math.radians(elev_deg))
        @ vec.ry(math.radians(axial_deg - plane_deg))
    )


def forearm_dir(r: Mat, flex_deg: float) -> Vec:
    b = math.radians(flex_deg)
    return r @ v(math.sin(b), -math.cos(b), 0.0)


def girdle_target(plane_deg: float, elev_deg: float, girdle: dict) -> Vec:
    """How far the shoulder joint centre wants to move (metres, arm frame)."""
    xs = girdle["elevation_deg"]
    up = float(np.interp(elev_deg, xs, girdle["up_mm"])) / 1000.0
    fwd = float(np.interp(elev_deg, xs, girdle["forward_mm"])) / 1000.0
    med = float(np.interp(elev_deg, xs, girdle["medial_mm"])) / 1000.0
    fwd *= math.sin(math.radians(plane_deg - girdle["forward_plane_neutral_deg"]))
    return v(fwd, up, -med)


def scapula_rotation(elev_deg: float, girdle: dict) -> float:
    """Scapular upward rotation in degrees for a thoracohumeral elevation."""
    r = girdle["rhythm"]
    return max(0.0, elev_deg - r["scapula_onset_deg"]) * r["scapula_slope"]


def checked_rom(rom: dict) -> dict:
    """The human range as given, once its planes rise from first to last
    with one top elevation each (every bench looks a plane up in it)."""
    planes = rom.get("plane_deg") or []
    tops = rom.get("max_elevation_deg") or []
    if len(planes) < 2 or len(planes) != len(tops):
        raise ValueError(
            "the human range needs two or more planes (plane_deg), one top"
            " elevation (max_elevation_deg) each"
        )
    if any(not b > a for a, b in zip(planes, planes[1:])):
        raise ValueError(
            "the human range's planes (plane_deg) must rise from first to last;"
            f" now {', '.join(f'{p:g}' for p in planes)}"
        )
    return rom


def max_elevation(plane_deg: float, rom: dict) -> float:
    return float(np.interp(plane_deg, rom["plane_deg"], rom["max_elevation_deg"]))


def axial_limits(elev_deg: float, rom: dict) -> tuple[float, float]:
    """(most external, most internal) axial rotation in degrees at an elevation."""
    k = 1.0 - rom["axial_shrink_overhead"] * min(1.0, max(0.0, elev_deg / 180.0))
    return -rom["axial_external_deg"] * k, rom["axial_internal_deg"] * k


def in_rom(plane: float, elev: float, axial: float, elbow: float, rom: dict) -> bool:
    lo, hi = axial_limits(elev, rom)
    return (
        rom["plane_deg"][0] <= plane <= rom["plane_deg"][-1]
        and 0.0 <= elev <= max_elevation(plane, rom) + 1e-9
        and lo - 1e-9 <= axial <= hi + 1e-9
        and 0.0 <= elbow <= rom["elbow_flexion_max_deg"]
    )


@dataclass
class Segment:
    name: str
    mass: float
    length: float
    com_frac: float
    k_perp: float  # radius of gyration about a transverse axis, metres
    k_long: float  # about the long axis, metres


@dataclass
class Body:
    """Fixed facts about the subject's right arm, in the arm frame."""

    sc: Vec  # base of the clavicle (VRM shoulder bone)
    gh_rest: Vec  # shoulder (glenohumeral) joint centre, arm hanging
    l_upper: float
    l_fore: float
    l_hand: float
    hand_offset: float
    mass: float
    segments: dict[str, Segment]
    limb_radius: dict[str, float]
    strength: dict
    hips: Vec
    chest: Vec
    neck: Vec
    head: Vec  # VRM head bone (base of the skull)


def body_from(skel: dict, subject: dict, segments: dict) -> Body:
    bones = {k: vec.body_to_arm(np.array(p)) for k, p in skel["bones"].items()}
    lengths = skel["lengths"]
    mass = float(subject["body_mass_kg"])
    table = segments[subject.get("sex", "female")]
    height = float(subject.get("height_m") or skel.get("height_estimate_m") or 1.65)
    l_upper, l_fore = lengths["upper_arm"], lengths["forearm"]
    l_hand = 0.0435 * height  # wrist to the third knuckle (de Leva's hand length)
    segs = {}
    for name, length in (("upper_arm", l_upper), ("forearm", l_fore), ("hand", l_hand)):
        row = table[name]
        r = row["r_pct"]
        segs[name] = Segment(
            name=name,
            mass=mass * row["mass_pct"] / 100.0,
            length=length,
            com_frac=row["com_pct"] / 100.0,
            k_perp=length * (r[0] + r[1]) / 200.0,
            k_long=length * r[2] / 100.0,
        )
    return Body(
        sc=bones["rightShoulder"],
        gh_rest=bones["rightUpperArm"],
        l_upper=l_upper,
        l_fore=l_fore,
        l_hand=l_hand,
        hand_offset=float(subject.get("hand_offset_m", 0.08)),
        mass=mass,
        segments=segs,
        limb_radius=dict(
            subject.get("limb_radius_m", {"upper_arm": 0.042, "forearm": 0.034})
        ),
        strength=dict(subject.get("strength", {})),
        hips=bones["hips"],
        chest=bones.get("upperChest", bones["chest"]),
        neck=bones["neck"],
        head=bones.get("head", bones["neck"] + v(0.0, 0.1, 0.0)),
    )


@dataclass
class ArmPose:
    plane: float
    elev: float
    axial: float
    elbow: float
    R: Mat
    C: Mat
    gh: Vec
    elbow_pt: Vec
    wrist: Vec
    hand: Vec
    u: Vec  # upper-arm direction (shoulder to elbow)
    f: Vec  # forearm direction (elbow to wrist)
    coms: dict[str, Vec] = field(default_factory=dict)


def pose(
    body: Body, girdle: dict, plane: float, elev: float, axial: float, elbow: float
) -> ArmPose:
    r = humerus_frame(plane, elev, axial)
    u = -r[:, 1]
    f = forearm_dir(r, elbow)
    # The joint centre moves by the girdle table itself; the clavicle
    # rotation that points at it is only for drawing the shrug.
    gh = body.gh_rest + girdle_target(plane, elev, girdle)
    clav = body.gh_rest - body.sc
    c = vec.arc(clav, gh - body.sc)
    e = gh + body.l_upper * u
    w = e + body.l_fore * f
    h = w + body.hand_offset * f
    s = body.segments
    coms = {
        "upper_arm": gh + s["upper_arm"].com_frac * body.l_upper * u,
        "forearm": e + s["forearm"].com_frac * body.l_fore * f,
        "hand": w + s["hand"].com_frac * body.l_hand * f,
    }
    return ArmPose(plane, elev, axial, elbow, r, c, gh, e, w, h, u, f, coms)


def vrm_bones(p: ArmPose, side: str = "right") -> dict[str, list[float]]:
    """Local rotations (quaternion x, y, z, w) for the VRM normalised bones."""
    c_body = vec.rot_arm_to_body(p.C)
    q_body = vec.rot_arm_to_body(p.R @ R_TPOSE.T)
    elbow = vec.ry(math.radians(p.elbow))
    out = {
        "Shoulder": vec.quat(c_body),
        "UpperArm": vec.quat(c_body.T @ q_body),
        "LowerArm": vec.quat(elbow),
    }
    if side == "left":
        # Mirror across the body's mid-plane: (x, y, z, w) -> (x, -y, -z, w).
        out = {k: [q[0], -q[1], -q[2], q[3]] for k, q in out.items()}
    return {side + k: q for k, q in out.items()}
