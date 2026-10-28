"""Game stats from a suit's effective specs: what the game half plays with.

Each stat is a game rule fed by the physics core, not a physics result, and
its formula travels with it in ``how`` so the game and the editor can show
why a number moved. The human baselines and the game-only parts (boost pack,
energy buffer) live in ``data/game/base.json``. Engine-free: a Unity or
Unreal front end reads the same JSON from ``GET /api/derive/{model}``.
"""

from __future__ import annotations

import copy
import math
from typing import Callable

from . import arm
from .arm import Rig, kinematics, loads
from .benches import check, rules_for
from .parts import Joint
from .registry import Registry

G = 9.81
LOAD_CODES = ("torque", "break", "pressure")
Accept = Callable[[list[dict], dict], bool]


def _limit(rig: Rig, pose: dict, rules: dict, accept: Accept, top: float) -> float:
    """Largest payload per arm (kg) at ``pose`` that ``accept`` allows."""

    def ok(kg: float) -> bool:
        fr = kinematics(
            rig,
            pose["plane"],
            pose["elev"],
            pose.get("axial", 0),
            pose.get("elbow", 0),
            kg,
        )
        ld = loads(rig, fr)
        return accept(check(rig, fr, ld, rules), ld)

    if not ok(0.0):
        return 0.0
    if ok(top):
        return top
    lo, hi = 0.0, top
    for _ in range(16):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


def _full_assist(profile: dict | None, model_id: str) -> dict:
    """The profile with the shoulder carrying the whole arm (Strength mode)."""
    prof = copy.deepcopy(profile or {})
    over = prof.setdefault("overrides", {}).setdefault("models", {})
    over.setdefault(model_id, {})["shoulder.assist_share"] = 1.0
    return prof


def derive(reg: Registry, model_id: str, profile: dict | None) -> dict:
    rig = arm.build(reg, model_id, profile)
    strong_rig = arm.build(reg, model_id, _full_assist(profile, model_id))
    base = reg.effective("game", "base", profile)
    s, b = rig.suit, rig.body
    boost, armour, energy = base["boost"], base["armour"], base["energy"]
    exc = base["joint_excursion_rad"]
    body_kg, suit_kg = b.mass, s.mass
    kit_kg = float(base["kit_mass_kg"]) + float(boost["mass_kg"])
    total = body_kg + suit_kg + kit_kg

    legs = [j for j in s.legs.values() if j.powered]
    arms: list[Joint] = [j for j in [*s.joints, s.elbow] if j.powered]

    def push_work(j: Joint) -> float:
        by_torque = j.torque_peak * float(exc.get(j.key, 1.0))
        by_power = 0.25 * j.torque_peak * j.speed_max * float(base["push_time_s"])
        return min(by_torque, by_power) * j.efficiency

    leg_work = 2 * sum(push_work(j) for j in legs)
    human_jump_j = body_kg * G * float(base["human_jump_m"])
    jump = (human_jump_j + leg_work) / (total * G)
    dv = float(boost["impulse_ns"]) / total
    boost_jump = jump + dv**2 / (2 * G)

    duty = float(base["leg_duty"])
    p_human = float(base["human_sprint_w"])
    p_legs = 2 * sum(j.power_cont * j.efficiency * duty for j in legs)
    cap = float(base["sprint_cap_mps"])
    v_h = float(base["human_sprint_mps"])
    sprint = min(cap, v_h * (1 + p_legs / p_human) * body_kg / total)
    speed_k = float(base["speed_mode_power"])
    speed_mode = min(cap, v_h * (1 + speed_k * p_legs / p_human) * body_kg / total)
    v_slam = math.sqrt(2 * G * boost_jump) + dv
    slam_j = 0.5 * total * v_slam**2

    rules = rules_for(rig, {})
    human_max = float(b.strength.get("shoulder_flexion_nm", 35))

    def rated(issues: list[dict], ld: dict) -> bool:
        bad = any(
            i["code"] in LOAD_CODES and (i["level"] == "fail" or i["code"] == "torque")
            for i in issues
        )
        return not bad and ld["human_shoulder_nm"] <= human_max

    def strong(issues: list[dict], ld: dict) -> bool:
        bad = any(i["code"] in LOAD_CODES and i["level"] == "fail" for i in issues)
        return not bad and ld["human_shoulder_nm"] <= human_max

    def unbroken(issues: list[dict], ld: dict) -> bool:
        return not any(i["code"] == "break" and i["level"] == "fail" for i in issues)

    carry, out = base["poses"]["carry"], base["poses"]["hold_out"]
    lift_kg = 2 * _limit(rig, carry, rules, rated, 300.0)
    strength_lift_kg = 2 * max(
        _limit(strong_rig, carry, rules, strong, 300.0),
        _limit(rig, carry, rules, strong, 300.0),
    )
    hold_out_kg = 2 * _limit(rig, out, rules, rated, 300.0)
    break_kg = 2 * _limit(rig, carry, rules, unbroken, 1000.0)

    arm_exc, punch_exc = float(exc.get("arm", 1.2)), float(exc.get("punch", 0.8))
    throw_j = float(base["human_throw_j"]) + 2 * sum(
        j.torque_cont * arm_exc * j.efficiency for j in arms
    )
    strength_throw_j = float(base["human_throw_j"]) + 2 * sum(
        j.torque_peak * arm_exc * j.efficiency for j in arms
    )
    punch_j = float(base["human_punch_j"]) + sum(
        j.torque_cont * punch_exc * j.efficiency for j in arms
    )
    strength_punch_j = float(base["human_punch_j"]) + sum(
        j.torque_peak * punch_exc * j.efficiency for j in arms
    )
    links = [ln for ln in s.links.values() if ln.role in ("upper_arm", "forearm")]
    arm_kg = 2 * (
        sum(seg.mass for seg in b.segments.values())
        + sum(ln.mass for ln in links)
        + s.elbow.mass
    )

    body_area = float(armour["body_area_m2"])
    points = sum(
        sh["area"] * float(sh.get("thickness_mm", 2.5)) * sh["strength"] / 1e6
        for sh in s.shells
    ) / float(armour["ref_mpa"])
    shell_area = sum(sh["area"] for sh in s.shells)
    hp = float(armour["base_hp"]) * (
        1 + float(armour["hp_per_point"]) * points / body_area
    )

    drain = {
        "idle": float(energy["idle_w"]),
        "sprint": 2 * sum(j.power_cont * duty / max(j.efficiency, 0.1) for j in legs),
        "strength": 2 * sum(j.power_cont / max(j.efficiency, 0.1) for j in arms),
        "armour": float(energy["armour_w_per_m2"]) * shell_area,
        "cloak": float(energy["cloak_w_per_m2"]) * body_area,
    }
    drain["speed"] = drain["sprint"] * speed_k

    def r(x: float, nd: int = 2) -> float:
        return round(float(x), nd)

    return {
        "model": model_id,
        "name": s.model.get("name", model_id),
        "profile": (profile or {}).get("name", "baseline"),
        "mass": {
            "body_kg": r(body_kg, 1),
            "suit_kg": r(suit_kg, 1),
            "kit_kg": r(kit_kg, 1),
            "total_kg": r(total, 1),
        },
        "move": {
            "walk_mps": r(base["walk_mps"]),
            "sprint_mps": r(sprint),
            "speed_mode_mps": r(speed_mode),
            "jump_m": r(jump),
            "boost_jump_m": r(boost_jump),
            "dash_mps": r(sprint + dv),
            "dash_s": r(boost["dash_s"]),
            "slam_j": r(slam_j, 0),
            "slam_radius_m": r(1.5 + slam_j / 4000.0),
        },
        "strength": {
            "lift_kg": r(lift_kg, 1),
            "strength_lift_kg": r(strength_lift_kg, 1),
            "hold_out_kg": r(hold_out_kg, 1),
            "break_kg": r(break_kg, 1),
            "throw_j": r(throw_j, 0),
            "strength_throw_j": r(strength_throw_j, 0),
            "throw_cap_mps": r(base["throw_cap_mps"]),
            "arm_mass_kg": r(arm_kg, 1),
            "punch_j": r(punch_j, 0),
            "strength_punch_j": r(strength_punch_j, 0),
        },
        "armour": {
            "hp": r(hp, 0),
            "coverage": r(min(1.0, shell_area / body_area)),
            "armour_mode_damage_mult": r(armour["armour_mode_damage_mult"]),
        },
        "energy": {
            "battery_wh": r(s.battery_wh, 0),
            "bar_j": r(energy["buffer_j"], 0),
            "recharge_w": r(energy["recharge_w"], 0),
            "recharge_delay_s": r(energy["recharge_delay_s"]),
            "boost_j": r(boost["energy_j"], 0),
            "drain_w": {k: r(v, 0) for k, v in drain.items()},
            "battery_min_idle": r(s.battery_wh * 60 / max(drain["idle"], 1.0), 0),
        },
        "how": {
            "jump_m": "(your own jump work + leg drives' push work) / (total mass x g); push work per drive = min(peak torque x joint swing, a quarter of peak torque x top speed x push time) x efficiency",
            "boost_jump_m": "jump + (boost impulse / total mass)^2 / 2g",
            "sprint_mps": "your sprint x (1 + leg drive power / your sprint power) x body mass / total mass",
            "lift_kg": "two arms, crate held in front: the heaviest load with every motor within its continuous torque, no beam or strap failing and the wearer within their maximum",
            "strength_lift_kg": "the same with motors allowed up to their peak torque and the suit carrying the whole arm when that helps (Strength mode); without load-bearing gauntlets the arm straps' pressure usually sets the limit",
            "break_kg": "the load at which a beam's safety factor drops below 1 (the part breaks)",
            "throw_j": "your throw + both arms' drives (continuous torque x swing x efficiency); speed = sqrt(2 x energy / (object + arm mass))",
            "hp": "base 100 x (1 + 0.5 x shell protection per body area); protection = area x thickness x strength / 300 MPa",
            "drain_w": "sprint and speed from leg drive power, strength from arm drive power, armour per m2 of shell, cloak per m2 of body",
        },
        "note": "Game rules fed by the physics core. The tester's numbers are the physics; these are for play.",
    }
