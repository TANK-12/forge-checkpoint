"""A model's parts resolved against a profile: materials, beam sections,
links, joints (actuators), cuffs, shells, battery and the mass budget.

Knobs reach a part on two levels: the material or actuator type (every part
made of it) and the part itself (``knobs.parts["<model>/<part>"]``). For a
part, stiffness scales E·I (links), torsional stiffness (joints) or the strap
stiffness (cuffs); strength scales the allowed stress or torque; weight scales
the mass; power makes a joint's motor bigger (torque and top speed by the
square root, watts, mass and rotor inertia in proportion, as data/knobs.json
says) or adds battery cells (energy and mass). A drive with no motor takes
no power.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .registry import ROOT, Registry, clamp_knob, set_path

SUIT_DIR = ROOT / "static" / "assets" / "suits"


@dataclass
class Section:
    shape: str
    area: float  # m^2
    inertia: float  # second moment of area, m^4
    polar: float  # torsion constant, m^4
    c: float  # outer fibre distance, m
    outer: float  # outer diameter or height, m (drawing)


def section(spec: dict) -> Section:
    t = float(spec.get("wall_mm", 2.0)) / 1000.0
    if spec.get("shape", "tube") == "rect":
        w, h = float(spec["w_mm"]) / 1000.0, float(spec["h_mm"]) / 1000.0
        t = min(t, min(w, h) / 2.0)
        wi, hi = w - 2 * t, h - 2 * t
        area = w * h - wi * hi
        inertia = (w * h**3 - wi * hi**3) / 12.0
        wm, hm = w - t, h - t
        polar = 2.0 * t * (wm * hm) ** 2 / (wm + hm) if wm + hm > 0 else 0.0
        return Section("rect", area, inertia, polar, h / 2.0, h)
    d = float(spec.get("d_mm", 25.0)) / 1000.0
    ro = d / 2.0
    ri = max(0.0, ro - t)
    inertia = math.pi / 4.0 * (ro**4 - ri**4)
    return Section("tube", math.pi * (ro**2 - ri**2), inertia, 2.0 * inertia, ro, d)


@dataclass
class Material:
    id: str
    name: str
    category: str
    colour: str
    density: float  # kg/m^3
    modulus: float  # Pa
    yield_strength: float  # Pa
    fatigue: float  # Pa


@dataclass
class Link:
    id: str
    name: str
    role: str
    material: Material
    section: Section
    length: float
    mass: float
    stiffness: float  # effective E*I, N m^2
    yield_strength: float  # Pa, after the part's strength knob
    fatigue: float
    side_offset: float


@dataclass
class Joint:
    key: str  # part key, e.g. "J1", "elbow"
    name: str
    actuator_id: str
    kind: str
    mass: float
    remote_mass: float
    torque_cont: float
    torque_peak: float
    speed_max: float
    efficiency: float
    stiffness: float
    power_cont: float
    backdrivable: bool
    limits: tuple[float, float]  # radians
    inertia: float = 0.0  # rotor inertia seen at the joint (x ratio squared), kg m^2
    motor: bool = True  # False for the knobs.json "motorless" kinds

    @property
    def powered(self) -> bool:
        """A motor that gives torque: a passive drive stays unpowered even
        with a torque typed onto it."""
        return self.motor and self.torque_cont > 0


@dataclass
class Suit:
    model: dict
    mech: dict
    joints: list[Joint]
    elbow: Joint
    links: dict[str, Link]
    cuffs: list[dict]
    shells: list[dict]
    legs: dict[str, Joint]
    battery_wh: float
    assist_share: float
    masses: dict[str, float] = field(default_factory=dict)
    grip: bool = False  # load-bearing gauntlets: a held load goes into the frame

    @property
    def mass(self) -> float:
        return sum(self.masses.values())

    @property
    def arm_kg(self) -> float:
        """Exo hardware on one arm past the shoulder base: drives, struts, cuffs."""
        struts = sum(
            ln.mass for ln in self.links.values() if ln.role in ("upper_arm", "forearm")
        )
        return (
            sum(j.mass for j in self.joints)
            + self.elbow.mass
            + struts
            + sum(c["mass"] for c in self.cuffs)
        )


def part_knobs(profile: dict | None, model_id: str, part: str) -> dict[str, float]:
    raw = ((profile or {}).get("knobs", {}).get("parts", {}) or {}).get(
        f"{model_id}/{part}", {}
    )
    return {k: clamp_knob(x) for k, x in raw.items()}


def material(reg: Registry, mat_id: str, profile: dict | None) -> Material:
    m = reg.effective("materials", mat_id, profile)
    return Material(
        id=mat_id,
        name=m.get("name", mat_id),
        category=m.get("category", "metal"),
        colour=m.get("colour", "#aaaaaa"),
        density=float(m["density_kg_m3"]),
        modulus=float(m["youngs_modulus_gpa"]) * 1e9,
        yield_strength=float(m["yield_strength_mpa"]) * 1e6,
        fatigue=float(m.get("fatigue_strength_mpa", m["yield_strength_mpa"] * 0.4))
        * 1e6,
    )


def joint(
    reg: Registry,
    act_id: str,
    key: str,
    name: str,
    limits_deg: list[float],
    profile: dict | None,
    model_id: str,
) -> Joint:
    a = reg.effective("actuators", act_id, profile)
    k = part_knobs(profile, model_id, key)
    motor = not reg.motorless(a)
    if not motor:
        k.pop("power", None)  # no motor to make bigger
    # A part knob scales the same fields by the same powers as the type's
    # knob (data/knobs.json): power x4 is twice the torque (gearbox limit
    # included) at twice the speed, for four times the mass and rotor; a
    # stronger drive is a heavier one. Strength is the gearbox alone.
    for knob, mult in k.items():
        for fname, exp in reg.knob_fields("actuators", knob).items():
            if isinstance(a.get(fname), (int, float)):
                a[fname] = a[fname] * mult**exp
    # Continuous torque never tops the capped peak, and a gearbox that slips
    # at 0 gives no torque at all.
    peak = min(
        float(a.get("torque_peak_nm", 0.0)),
        float(a.get("torque_limit_nm", a.get("torque_peak_nm", 0.0))),
    )
    return Joint(
        key=key,
        name=name,
        actuator_id=act_id,
        kind=str(a.get("kind", "rotary")),
        mass=float(a.get("mass_kg", 0.0)),
        remote_mass=float(a.get("remote_mass_kg", 0.0)),
        torque_cont=min(float(a.get("torque_cont_nm", 0.0)), peak),
        torque_peak=peak,
        speed_max=float(a.get("speed_max_rad_s", 10.0)),
        efficiency=float(a.get("efficiency", 0.8)),
        stiffness=float(a.get("stiffness_nm_rad", 1000.0)),
        power_cont=float(a.get("power_cont_w", 0.0)),
        backdrivable=bool(a.get("backdrivable", True)),
        limits=(math.radians(limits_deg[0]), math.radians(limits_deg[1])),
        inertia=float(a.get("rotor_inertia_kgm2", 0.0))
        * float(a.get("gear_ratio", 1.0)) ** 2,
        motor=motor,
    )


def suit_sidecar(asset: str | None) -> dict[str, float]:
    """Outer areas measured on the Blender shells, when they exist."""
    if not asset:
        return {}
    p = SUIT_DIR / f"{asset}.json"
    if not p.exists():
        return {}
    try:
        parts = json.loads(p.read_text()).get("parts", [])
    except (OSError, ValueError):
        return {}
    areas: dict[str, float] = {}
    for it in parts:
        if isinstance(it.get("area_m2"), (int, float)):
            pid = str(it.get("part", it.get("name", "")))
            areas[pid] = areas.get(pid, 0.0) + float(it["area_m2"])
    return areas


def resolve(
    reg: Registry, model_id: str, profile: dict | None, body_lengths: dict[str, float]
) -> Suit:
    model = reg.effective("models", model_id, profile)
    if model.get("status") != "ready":
        raise ValueError(f"{model.get('name', model_id)} is planned, not built yet")
    sh = model.get("shoulder", {})
    mech = reg.model_mechanism(model, profile)
    joints = [
        joint(
            reg,
            j["actuator"],
            f"J{i + 1}",
            j["name"],
            j["limits_deg"],
            profile,
            model_id,
        )
        for i, j in enumerate(mech.get("joints", []))
    ]
    el = model.get("elbow", {})
    elbow = joint(
        reg,
        el["actuator"],
        "elbow",
        "Elbow",
        el.get("limits_deg", [0, 145]),
        profile,
        model_id,
    )
    legs = {
        name: joint(
            reg, spec["actuator"], name, name.title(), [-120, 120], profile, model_id
        )
        for name, spec in (model.get("legs") or {}).items()
        if isinstance(spec, dict) and "actuator" in spec
    }
    links: dict[str, Link] = {}
    for spec in model.get("links", []):
        mat = material(reg, spec["material"], profile)
        sec = section(spec["section"])
        k = part_knobs(profile, model_id, spec["id"])
        length = spec.get("length_m") or {
            "upper_arm": body_lengths.get("upper_arm", 0.3),
            "forearm": body_lengths.get("forearm", 0.25) * 0.8,
        }.get(spec.get("role", ""), 0.3)
        links[spec["id"]] = Link(
            id=spec["id"],
            name=spec.get("name", spec["id"]),
            role=spec.get("role", ""),
            material=mat,
            section=sec,
            length=float(length),
            mass=mat.density * sec.area * float(length) * k.get("weight", 1.0),
            stiffness=mat.modulus * sec.inertia * k.get("stiffness", 1.0),
            yield_strength=mat.yield_strength * k.get("strength", 1.0),
            fatigue=mat.fatigue * k.get("strength", 1.0),
            side_offset=float(spec.get("side_offset_mm", 20)) / 1000.0,
        )
    radius = {"upper_arm": 0.042, "forearm": 0.034}
    cuffs = []
    for spec in model.get("cuffs", []):
        mat = material(reg, spec.get("material", "pa12"), profile)
        k = part_knobs(profile, model_id, spec["id"])
        r = (
            radius.get(spec.get("segment", "upper_arm"), 0.04)
            + spec.get("gap_mm", 5) / 1000.0
        )
        width = float(spec.get("width_mm", 50)) / 1000.0
        mass = (
            2
            * math.pi
            * r
            * width
            * spec.get("thickness_mm", 2.5)
            / 1000.0
            * mat.density
        )
        cuffs.append(
            dict(
                spec,
                radius=r,
                width=width,
                area=width
                * 2.0
                * r,  # pressure over half the cuff pushes with p x width x diameter
                mass=mass * k.get("weight", 1.0),
                stiffness_mult=k.get("stiffness", 1.0),
                material_name=mat.name,
            )
        )
    measured = suit_sidecar(model.get("suit_asset"))
    shells = []
    for spec in model.get("shells", []):
        mat = material(reg, spec["material"], profile)
        k = part_knobs(profile, model_id, spec["id"])
        copies = 2 if spec.get("mirror") else 1
        area = measured.get(spec["id"], float(spec.get("area_m2", 0.03)) * copies)
        mass = area * spec.get("thickness_mm", 2.5) / 1000.0 * mat.density
        shells.append(
            dict(
                spec,
                copies=copies,
                area=area,
                area_measured=spec["id"] in measured,
                mass=mass * k.get("weight", 1.0),
                strength=mat.yield_strength * k.get("strength", 1.0),
                material_name=mat.name,
            )
        )
    bat = model.get("battery", {})
    pw = reg.effective("power", bat.get("power", "li_ion_21700"), profile)
    kb = part_knobs(profile, model_id, "battery")
    # Power on the battery is more cells: more energy and more mass. Weight
    # alone is a heavier case and adds no energy.
    cells_kg = float(bat.get("mass_kg", 1.0)) * kb.get("power", 1.0)
    battery_wh = cells_kg * float(pw.get("specific_energy_wh_kg", 180))
    bat_mass = cells_kg * kb.get("weight", 1.0)
    masses: dict[str, float] = {}
    for j in joints:
        masses[f"Shoulder {j.key} (x2)"] = 2 * (j.mass + j.remote_mass)
    masses["Elbow drives (x2)"] = 2 * (elbow.mass + elbow.remote_mass)
    for name, j in legs.items():
        masses[f"{name.title()} drives (x2)"] = 2 * (j.mass + j.remote_mass)
    for ln in links.values():
        masses[ln.name + ("" if ln.role == "back_frame" else " (x2)")] = ln.mass * (
            1 if ln.role == "back_frame" else 2
        )
    if mech.get("kind") == "girdle":
        masses["Girdle links (x2)"] = 2 * float(
            mech.get("girdle", {}).get("moving_mass_kg", 1.0)
        )
    legs_spec = model.get("legs") or {}
    if "strut_section" in legs_spec:
        mat = material(reg, legs_spec.get("strut_material", "al_7075_t6"), profile)
        sec = section(legs_spec["strut_section"])
        leg_len = body_lengths.get("thigh", 0.4) + body_lengths.get("shank", 0.4)
        masses["Leg struts (x2)"] = 2 * mat.density * sec.area * leg_len
    for c in cuffs:
        masses[c["name"] + " (x2)"] = 2 * c["mass"]
    for s in shells:
        masses[s["name"] + (" (x2)" if s["copies"] == 2 else "")] = s["mass"]
    masses["Battery"] = bat_mass
    for name, m in (model.get("extras_mass_kg") or {}).items():
        masses[name[:1].upper() + name[1:]] = float(m)
    return Suit(
        model=model,
        mech=mech,
        joints=joints,
        elbow=elbow,
        links=links,
        cuffs=cuffs,
        shells=shells,
        legs=legs,
        battery_wh=battery_wh,
        assist_share=float(sh.get("assist_share", 0.5)),
        masses=masses,
        grip=bool(model.get("hand_grip", False)),
    )
