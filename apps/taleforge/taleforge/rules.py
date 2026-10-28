"""Character numbers: ability modifiers, proficiency, armour class, attack
bonuses, levelling and new characters. Everything is read from the rule set."""

from __future__ import annotations

import random

from .dice import average, d20, modifier, roll
from .world import World


class RuleError(ValueError):
    """The player asked for something the rules do not allow."""


def level_row(rules: dict, level: int) -> dict:
    rows = [r for r in rules["levels"] if r["level"] <= level]
    return rows[-1] if rows else rules["levels"][0]


def proficiency(rules: dict, level: int) -> int:
    return int(level_row(rules, level)["proficiency"])


def mods(pc: dict) -> dict[str, int]:
    return {a: modifier(s) for a, s in pc["abilities"].items()}


def names_for(rules: dict, pc: dict) -> dict:
    """Words a dice expression may use: level, prof and each ability mod."""
    names = dict(mods(pc))
    names["level"] = pc["level"]
    names["prof"] = proficiency(rules, pc["level"])
    return names


def skill_bonus(rules: dict, pc: dict, skill: str) -> int:
    spec = rules["_skills"][skill]
    bonus = mods(pc)[spec["ability"]]
    if skill in pc.get("skills", []):
        bonus += proficiency(rules, pc["level"])
    if skill in pc.get("expertise", []):
        bonus += proficiency(rules, pc["level"])
    return bonus


def armour_class(world: World, pc: dict) -> int:
    rules = world.rules
    dex = mods(pc)["dex"] if "dex" in pc["abilities"] else 0
    eq = pc.get("equipped", {})
    ac = rules["combat"].get("base_ac", 10) + dex
    if eq.get("armor"):
        armor = world.item(eq["armor"])
        cap = armor.get("dex_cap")
        ac = armor.get("ac", 10) + (dex if cap is None else min(dex, cap))
    if eq.get("shield"):
        ac += world.item(eq["shield"]).get("ac_bonus", 2)
    return ac


def weapon(world: World, pc: dict) -> dict:
    wid = pc.get("equipped", {}).get("weapon")
    if wid:
        return world.item(wid)
    combat = world.rules["combat"]
    return {
        "id": "",
        "name": "bare hands",
        "damage": combat.get("unarmed_damage", "1d4"),
        "ability": combat.get("unarmed_ability", "str"),
    }


def weapon_ability(pc: dict, item: dict) -> str:
    ability = item.get("ability", "str")
    m = mods(pc)
    if ability == "finesse":
        return "dex" if m.get("dex", 0) >= m.get("str", 0) else "str"
    return ability if ability in m else "str"


def attack_bonus(world: World, pc: dict) -> int:
    item = weapon(world, pc)
    return (
        mods(pc)[weapon_ability(pc, item)]
        + proficiency(world.rules, pc["level"])
        + int(item.get("bonus", 0))
    )


def spell_dc(world: World, pc: dict) -> int:
    cls = world.rules["_classes"][pc["class"]]
    ability = cls.get("spell_attack") or cls.get("primary", "int")
    return 8 + proficiency(world.rules, pc["level"]) + mods(pc)[ability]


def class_abilities(world: World, pc: dict) -> list[dict]:
    cls = world.rules["_classes"][pc["class"]]
    return [a for a in cls.get("abilities", []) if a.get("level", 1) <= pc["level"]]


def scaled(ability: dict, level: int, key: str = "damage") -> str:
    """An ability's dice at a level: its `scale` table overrides `key`."""
    value = ability.get(key, "0")
    for at, dice in sorted(ability.get("scale", {}).items(), key=lambda kv: int(kv[0])):
        if level >= int(at):
            value = dice
    return value


def xp_for_next(rules: dict, level: int) -> int | None:
    for row in rules["levels"]:
        if row["level"] == level + 1:
            return int(row["xp"])
    return None


def max_level(rules: dict) -> int:
    return max(r["level"] for r in rules["levels"])


def level_up(world: World, pc: dict, rng: random.Random) -> list[str]:
    """Raise the level while XP allows. Returns lines describing each gain."""
    rules = world.rules
    lines = []
    while pc["level"] < max_level(rules):
        need = xp_for_next(rules, pc["level"])
        if need is None or pc["xp"] < need:
            break
        pc["level"] += 1
        cls = rules["_classes"][pc["class"]]
        gain = max(1, cls["hit_die"] // 2 + 1 + mods(pc).get("con", 0))
        pc["max_hp"] += gain
        pc["hp"] += gain
        row = level_row(rules, pc["level"])
        pc["ability_points"] = pc.get("ability_points", 0) + int(
            row.get("ability_points", 0)
        )
        new = [
            a["name"] for a in cls.get("abilities", []) if a.get("level") == pc["level"]
        ]
        for a in cls.get("abilities", []):
            if a.get("level") == pc["level"] and a.get("uses"):
                pc["uses"][a["id"]] = a["uses"]
        text = f"{rules['labels'].get('level', 'Level')} {pc['level']}: +{gain} max {rules['labels'].get('hp', 'HP')}"
        if new:
            text += ", new: " + ", ".join(new)
        if row.get("ability_points"):
            text += f", {row['ability_points']} ability points to spend"
        lines.append(text)
    return lines


def raise_ability(rules: dict, pc: dict, ability: str) -> None:
    if pc.get("ability_points", 0) <= 0:
        raise RuleError("no ability points to spend")
    if ability not in pc["abilities"]:
        raise RuleError(f"no ability {ability!r}")
    cap = rules["ability_scores"].get("max", 20)
    if pc["abilities"][ability] >= cap:
        raise RuleError(f"that score is already at {cap}")
    pc["abilities"][ability] += 1
    pc["ability_points"] -= 1
    if ability == "con":
        pc["max_hp"] += pc["level"] if pc["abilities"]["con"] % 2 == 0 else 0
        pc["hp"] = min(pc["hp"], pc["max_hp"])


def roll_scores(rules: dict, rng: random.Random) -> list[int]:
    expr = rules["ability_scores"].get("roll", "4d6kh3")
    return [roll(expr, rng)["total"] for _ in rules["_abilities"]]


def check_scores(
    rules: dict, method: str, scores: dict, rolled: list[int] | None
) -> None:
    ids = rules["_abilities"]
    if sorted(scores) != sorted(ids):
        raise RuleError("give a score for every ability")
    values = [int(scores[a]) for a in ids]
    spec = rules["ability_scores"]
    if method == "array":
        if sorted(values) != sorted(spec["standard_array"]):
            raise RuleError("use each number of the standard array once")
    elif method == "point_buy":
        pb = spec["point_buy"]
        if any(v < pb["min"] or v > pb["max"] for v in values):
            raise RuleError(f"point buy scores run from {pb['min']} to {pb['max']}")
        cost = sum(pb["cost"][str(v)] for v in values)
        if cost > pb["budget"]:
            raise RuleError(f"that costs {cost} points; the budget is {pb['budget']}")
    elif method == "roll":
        if not rolled or sorted(values) != sorted(rolled):
            raise RuleError("use the numbers you rolled, each once")
    else:
        raise RuleError(f"unknown way to set scores: {method!r}")


# what each field of the creation form must be
SPEC_SHAPES = {
    "name": str,
    "pronouns": str,
    "class": str,
    "background": str,
    "method": str,
    "scores": dict,
    "skills": list,
    "expertise": list,
}


def new_character(world: World, spec: dict, rolled: list[int] | None = None) -> dict:
    """Build a level 1 character from the creation form, or raise RuleError."""
    rules = world.rules
    for key, kind in SPEC_SHAPES.items():
        if spec.get(key) is not None and not isinstance(spec[key], kind):
            raise RuleError(f"the character form's {key} is not filled in properly")
    name = str(spec.get("name", "")).strip()[:40]
    if not name:
        raise RuleError("your character needs a name")
    cls = rules["_classes"].get(spec.get("class", ""))
    if not cls:
        raise RuleError("pick a class")
    bg = rules["_backgrounds"].get(spec.get("background", ""))
    if not bg:
        raise RuleError("pick a background")
    try:
        scores = {a: int(v) for a, v in (spec.get("scores") or {}).items()}
    except (TypeError, ValueError):
        raise RuleError("ability scores must be whole numbers") from None
    check_scores(rules, spec.get("method", "array"), scores, rolled)
    chosen = [
        s
        for s in spec.get("skills") or []
        if isinstance(s, str) and s not in bg["skills"]
    ]
    if len(set(chosen)) != cls["skill_count"] or any(
        s not in cls["skill_options"] for s in chosen
    ):
        raise RuleError(
            f"choose {cls['skill_count']} different skills from the {cls['name']} list"
        )
    skills = list(dict.fromkeys(bg["skills"] + chosen))
    expertise = [
        s for s in spec.get("expertise") or [] if isinstance(s, str) and s in skills
    ][: cls.get("expertise", 0)]
    if cls.get("expertise") and len(expertise) < cls["expertise"]:
        expertise = (expertise + [s for s in chosen if s not in expertise])[
            : cls["expertise"]
        ]
    pc = {
        "name": name,
        "pronouns": str(spec.get("pronouns") or "they/them")[:20],
        "class": cls["id"],
        "background": bg["id"],
        "level": 1,
        "xp": 0,
        "abilities": scores,
        "skills": skills,
        "expertise": expertise,
        "ability_points": 0,
        "uses": {},
        "equipped": {"weapon": None, "armor": None, "shield": None},
        "look": str(spec.get("look", ""))[:300],
    }
    pc["max_hp"] = max(1, cls["hit_die"] + modifier(scores.get("con", 10)))
    pc["hp"] = pc["max_hp"]
    for a in class_abilities(world, pc):
        if a.get("uses"):
            pc["uses"][a["id"]] = a["uses"]
    return pc


def hit_die_heal(world: World, pc: dict, rng: random.Random) -> int:
    cls = world.rules["_classes"][pc["class"]]
    return max(1, roll(f"1d{cls['hit_die']}", rng)["total"] + mods(pc).get("con", 0))


def save_roll(rng: random.Random, level: int, dc: int) -> tuple[bool, int]:
    """A monster's saving throw: d20 + half its level against a DC."""
    r = d20(rng, int(level) // 2)
    return r["total"] >= dc, r["natural"]


def expected(expr) -> float:
    return average(expr)
