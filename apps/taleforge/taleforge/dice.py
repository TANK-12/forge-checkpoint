"""Dice: expressions like "d20", "2d6+3", "4d6kh3", "1d10+level" and d20 checks.

Every roll in the game goes through here, so a seeded random.Random makes a
whole game reproducible in tests."""

from __future__ import annotations

import random
import re

TERM = re.compile(
    r"([+-]?)(?:(\d{0,3})d(\d{1,4})(?:(kh|kl)(\d{1,3}))?|(\d{1,6})|([a-z_]+))"
)
MAX_DICE = 100


class DiceError(ValueError):
    pass


def roll(expr, rng: random.Random, names: dict | None = None) -> dict:
    """Roll an expression. Words in it ("level", "wis") are looked up in
    `names`. Returns {"expr", "rolls": [[kept dice]...], "total", "text"}."""
    if isinstance(expr, (int, float)):
        value = int(expr)
        return {"expr": str(value), "rolls": [], "total": value, "text": str(value)}
    clean = re.sub(r"\s+", "", str(expr).lower())
    # "1d6+-1" comes from adding a negative modifier; read it as "1d6-1"
    clean = clean.replace("+-", "-").replace("-+", "-").replace("--", "+")
    if not clean:
        raise DiceError("empty roll")
    names = names or {}
    pos, total, used, rolls, shown = 0, 0, 0, [], []
    while pos < len(clean):
        m = TERM.match(clean, pos)
        if not m or m.end() == pos or (pos and not m.group(1)):
            raise DiceError(f"cannot read the roll {expr!r}")
        sign = -1 if m.group(1) == "-" else 1
        mark = "-" if sign < 0 else ("+" if pos else "")
        if m.group(6) is not None:
            value = int(m.group(6))
            shown.append(f"{mark}{value}")
        elif m.group(7) is not None:
            word = m.group(7)
            if word not in names:
                raise DiceError(f"unknown word {word!r} in the roll {expr!r}")
            value = int(names[word])
            shown.append(f"{mark}{value}")
        else:
            count, sides = int(m.group(2) or 1), int(m.group(3))
            used += count
            if count < 1 or used > MAX_DICE or sides < 2:
                raise DiceError(f"cannot roll {expr!r}")
            dice = [rng.randint(1, sides) for _ in range(count)]
            kept = dice
            if m.group(4):
                keep = min(int(m.group(5)), count)
                ordered = sorted(dice, reverse=m.group(4) == "kh")
                kept = ordered[:keep]
            rolls.append(kept)
            value = sum(kept)
            shown.append(f"{mark}[{','.join(map(str, dice))}]")
        total += sign * value
        pos = m.end()
    return {"expr": str(expr), "rolls": rolls, "total": total, "text": "".join(shown)}


def average(expr, names: dict | None = None) -> float:
    """The expected value of an expression, for balancing and hit-die healing."""
    if isinstance(expr, (int, float)):
        return float(expr)
    clean = re.sub(r"\s+", "", str(expr).lower())
    # "1d6+-1" comes from adding a negative modifier; read it as "1d6-1"
    clean = clean.replace("+-", "-").replace("-+", "-").replace("--", "+")
    pos, total = 0, 0.0
    names = names or {}
    while pos < len(clean):
        m = TERM.match(clean, pos)
        if not m or m.end() == pos:
            raise DiceError(f"cannot read the roll {expr!r}")
        sign = -1 if m.group(1) == "-" else 1
        if m.group(6) is not None:
            value = float(m.group(6))
        elif m.group(7) is not None:
            value = float(names.get(m.group(7), 0))
        else:
            count, sides = int(m.group(2) or 1), int(m.group(3))
            keep = int(m.group(5)) if m.group(4) else count
            value = min(keep, count) * (sides + 1) / 2
        total += sign * value
        pos = m.end()
    return total


def valid(expr, names: tuple = ()) -> bool:
    try:
        roll(expr, random.Random(0), {n: 0 for n in names})
        return True
    except DiceError:
        return False


def d20(rng: random.Random, bonus: int, advantage: int = 0) -> dict:
    """One d20 roll plus a bonus. advantage > 0 rolls two and keeps the
    higher, < 0 keeps the lower. Returns {"dice", "natural", "bonus", "total"}."""
    dice = [rng.randint(1, 20)]
    if advantage:
        dice.append(rng.randint(1, 20))
    natural = max(dice) if advantage > 0 else min(dice) if advantage < 0 else dice[0]
    return {"dice": dice, "natural": natural, "bonus": bonus, "total": natural + bonus}


def modifier(score: int) -> int:
    return (int(score) - 10) // 2


def signed(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)
