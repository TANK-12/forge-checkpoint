"""Tavern: tabletop campaigns with Jan as the game master.

A campaign is one JSON file in the data folder (campaigns/<id>.json) holding
the party, the story log, the maps and a running summary. Nothing else is
written anywhere.

    world       one of worlds/*.json (setting, tone, roles, opening); adding a
                world is dropping one more file there
    party       up to party_max characters: name, role, hp, max_hp, notes
    log         the story, oldest first; every entry has a number `n`, a kind
                (say: a player's action, gm: the game master, roll: dice,
                note: out of character) and the text
    summary     the story so far, in Jan's words, for everything before
                `summarised`; Jan sees the summary and the recent entries only
    maps        grid maps: rows of terrain keys (tavern.json "terrain") and
                tokens with a name, a colour and a square

The game master's reply may carry tags, which are taken out of the text:

    [roll 1d20+2 Aria Stealth]   asks for a roll; the page shows it as a button
    [hp Aria -4]                  hurts (or with +, heals) a party member

Dice are rolled here, never by Jan: `roll("4d6kh3+2")` keeps the three
highest of four six-sided dice and adds two.
"""

from __future__ import annotations

import json
import os
import random
import re
import secrets
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR") or ROOT.parent.parent / "shared")
sys.path.insert(0, str(SHARED_DIR))
import forge_jan  # noqa: E402
from forge_trash import TrashError  # noqa: E402
from forge_trash import trash as move_to_trash  # noqa: E402

CONFIG = Path(os.environ.get("TAVERN_CONFIG") or ROOT / "tavern.json")
WORLDS = Path(os.environ.get("TAVERN_WORLDS") or ROOT / "worlds")
DATA_DIR = Path(
    os.environ.get("TAVERN_DATA_DIR") or Path.home() / ".local/share/forge/tavern"
)
ROLES = ("gm", "recap")
NAME_MAX = 60
ID_RE = re.compile(r"^[a-z0-9]{6,32}$")
LOCK = threading.RLock()
BUSY: set[str] = set()  # campaigns whose game master is writing


class TavernError(Exception):
    """Something the player should read: bad input or a missing campaign."""


class Busy(TavernError):
    pass


class JanDown(TavernError):
    pass


# --- settings and worlds ----------------------------------------------------


def load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def load_worlds() -> dict[str, dict]:
    worlds = {}
    for path in sorted(WORLDS.glob("*.json")):
        try:
            world = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(world, dict) and world.get("id") == path.stem:
            worlds[path.stem] = world
    return dict(sorted(worlds.items(), key=lambda kv: kv[1].get("order", 99)))


# --- dice -------------------------------------------------------------------

TERM_RE = re.compile(r"([+-]?)(?:(\d{0,4})d(\d{1,5})(?:(kh|kl)(\d{1,4}))?|(\d{1,6}))")
EXPR_MAX = 120


def roll(expr: str, cfg: dict, rng: random.Random | None = None) -> dict:
    """Rolls a dice expression like "d20", "2d6+3" or "4d6kh3 - 1".

    Returns {expr, parts, total, text}; each part has its rolls and the ones
    kept. Raises TavernError for anything else."""
    limits = cfg["dice"]
    rng = rng or secrets.SystemRandom()
    clean = re.sub(r"\s*([+-])\s*", r"\1", str(expr).lower().strip())
    if not clean:
        raise TavernError("write a roll like 1d20+3")
    if len(clean) > EXPR_MAX:
        raise TavernError(f"a roll is at most {EXPR_MAX} characters")
    if re.search(r"\s", clean):
        raise TavernError(f"cannot read the roll {expr!r}; try 1d20+3 or 4d6kh3")
    parts, pos, total, dice_used = [], 0, 0, 0
    while pos < len(clean):
        m = TERM_RE.match(clean, pos)
        if not m or m.end() == pos or (parts and not m.group(1)):
            raise TavernError(f"cannot read the roll {expr!r}; try 1d20+3 or 4d6kh3")
        sign = -1 if m.group(1) == "-" else 1
        if m.group(6) is not None:
            value = int(m.group(6))
            parts.append({"term": m.group(0).lstrip("+"), "sign": sign, "sum": value})
            total += sign * value
        else:
            count = int(m.group(2) or 1)
            sides = int(m.group(3))
            keep = int(m.group(5)) if m.group(4) else count
            dice_used += count
            if not 1 <= count or dice_used > limits["max_dice"]:
                raise TavernError(f"at most {limits['max_dice']} dice in one roll")
            if not 2 <= sides <= limits["max_sides"]:
                raise TavernError(f"dice have 2 to {limits['max_sides']} sides")
            if not 1 <= keep <= count:
                raise TavernError("keep between 1 and the number of dice")
            rolls = [rng.randint(1, sides) for _ in range(count)]
            order = sorted(range(count), key=lambda i: rolls[i], reverse=True)
            if m.group(4) == "kl":
                order.reverse()
            kept_at = set(order[:keep])
            kept = [r for i, r in enumerate(rolls) if i in kept_at]
            value = sum(kept)
            parts.append(
                {
                    "term": m.group(0).lstrip("+"),
                    "sign": sign,
                    "rolls": rolls,
                    "kept": [i in kept_at for i in range(count)],
                    "sum": value,
                }
            )
            total += sign * value
        if len(parts) > limits["max_terms"]:
            raise TavernError(f"at most {limits['max_terms']} parts in one roll")
        pos = m.end()
    return {
        "expr": clean,
        "parts": parts,
        "total": total,
        "text": roll_text(parts, total),
    }


def roll_text(parts: list[dict], total: int) -> str:
    out = []
    for i, p in enumerate(parts):
        sign = "-" if p["sign"] < 0 else "+"
        lead = ("- " if p["sign"] < 0 else "") if i == 0 else f"{sign} "
        if "rolls" in p:
            shown = [str(r) if k else f"({r})" for r, k in zip(p["rolls"], p["kept"])]
            out.append(f"{lead}{p['term'].lstrip('+-')} [{', '.join(shown)}]")
        else:
            out.append(f"{lead}{p['sum']}")
    return " ".join(out) + f" = {total}"


# --- the game master's tags -------------------------------------------------

ROLL_TAG = re.compile(r"\[roll:?\s+([^\]]+)\]", re.I)
HP_TAG = re.compile(r"\[hp:?\s+([^\]]+)\]", re.I)
HP_PAIR = re.compile(r"([^\d,;+\-]+?)\s*([+-]\s*\d{1,4})")
DICE_WORD = re.compile(r"^[0-9dkhl+\-]+$", re.I)


def find_member(party: list[dict], name: str) -> dict | None:
    """A party member by full name, else the one member whose name holds
    every given word ("Aria" or "Vale" finds Aria Vale). None when nobody
    or more than one member fits."""
    want = name.strip().lower()
    if not want:
        return None
    for m in party:
        if m["name"].lower() == want:
            return m
    words = set(want.split())
    fits = [m for m in party if words <= set(m["name"].lower().split())]
    return fits[0] if len(fits) == 1 else None


def read_tags(
    text: str, party: list[dict], cfg: dict
) -> tuple[str, list[dict], list[dict]]:
    """(text without tags, roll asks, hp changes). A roll ask is
    {expr, who, why}; who is a party member's name or "". An hp change is
    {id, who, delta}. A tag that cannot be rolled, or names someone not in
    the party, is left in the text so the table sees it."""
    asks: list[dict] = []
    hp: list[dict] = []

    def roll_tag(m: re.Match) -> str:
        words = m.group(1).split()
        for k in range(len(words), 0, -1):
            expr = " ".join(words[:k])
            if all(DICE_WORD.match(w) for w in words[:k]) and readable(cfg, expr):
                break
        else:
            return m.group(0)
        rest = words[k:]
        who, why = "", " ".join(rest)
        for n in range(min(3, len(rest)), 0, -1):
            member = find_member(party, " ".join(rest[:n]))
            if member:
                who, why = member["name"], " ".join(rest[n:])
                break
        asks.append(
            {
                "expr": re.sub(r"\s+", "", expr).lower(),
                "who": who,
                "why": why[:NAME_MAX],
            }
        )
        return ""

    def hp_tag(m: re.Match) -> str:
        found = []
        for name, delta in HP_PAIR.findall(m.group(1)):
            name = re.sub(r"^(and|&)\s+", "", name.strip(" ,;&"), flags=re.I)
            member = find_member(party, name)
            if not member:
                return m.group(0)
            found.append(
                {
                    "id": member["id"],
                    "who": member["name"],
                    "delta": int(delta.replace(" ", "")),
                }
            )
        if not found:
            return m.group(0)
        hp.extend(found)
        return ""

    clean = HP_TAG.sub(hp_tag, ROLL_TAG.sub(roll_tag, text))
    clean = re.sub(r"[ \t]{2,}", " ", clean)
    clean = re.sub(r"[ \t]+\n", "\n", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean, asks, hp


# --- campaigns --------------------------------------------------------------


def campaigns_dir() -> Path:
    return DATA_DIR / "campaigns"


def path_of(cid: str) -> Path:
    if not ID_RE.match(str(cid)):
        raise TavernError("no such campaign")
    return campaigns_dir() / f"{cid}.json"


def load(cid: str) -> dict:
    try:
        return json.loads(path_of(cid).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TavernError("no such campaign") from None


def save(c: dict) -> None:
    c["updated"] = time.time()
    path = path_of(c["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def text_of(value, name: str, limit: int, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise TavernError(f"{name} is empty")
    if len(text) > limit:
        raise TavernError(f"{name} is longer than {limit} characters")
    return text


def int_of(value, name: str, low: int, high: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise TavernError(f"{name} is not a number") from None
    if not low <= n <= high:
        raise TavernError(f"{name} must be {low} to {high}")
    return n


def blank_map(cfg: dict, name: str, w: int, h: int) -> dict:
    floor = cfg["terrain"][0]["key"]
    return {
        "id": secrets.token_hex(4),
        "name": name,
        "w": w,
        "h": h,
        "cells": [floor * w for _ in range(h)],
        "tokens": [],
    }


def member(cfg: dict, world: dict, raw: dict, old: dict | None = None) -> dict:
    hp_default = int(world.get("hp", 10))
    max_hp = int_of(
        raw.get("max_hp", (old or {}).get("max_hp", hp_default)), "max HP", 1, 999
    )
    hp = int_of(raw.get("hp", (old or {}).get("hp", max_hp)), "HP", -999, 999)
    hp = max(-max_hp, min(max_hp, hp))
    return {
        "id": (old or {}).get("id") or secrets.token_hex(4),
        "name": text_of(raw.get("name", (old or {}).get("name")), "the name", NAME_MAX),
        "role": text_of(
            raw.get("role", (old or {}).get("role", "")), "the role", NAME_MAX, False
        ),
        "hp": hp,
        "max_hp": max_hp,
        "notes": text_of(
            raw.get("notes", (old or {}).get("notes", "")), "the notes", 1000, False
        ),
    }


def new_campaign(cfg: dict, name: str, world_id: str, party: list[dict]) -> dict:
    worlds = load_worlds()
    if world_id not in worlds:
        raise TavernError("no such world")
    world = worlds[world_id]
    if not isinstance(party, list) or not party:
        raise TavernError("the party needs at least one character")
    if len(party) > cfg["party_max"]:
        raise TavernError(f"at most {cfg['party_max']} characters")
    members = [member(cfg, world, p if isinstance(p, dict) else {}) for p in party]
    names = [m["name"].lower() for m in members]
    if len(set(names)) != len(names):
        raise TavernError("two characters have the same name")
    first = blank_map(cfg, "Map 1", cfg["map"]["w"], cfg["map"]["h"])
    for i, m in enumerate(members):
        first["tokens"].append(
            {
                "id": m["id"],
                "name": m["name"],
                "color": PALETTE[i % len(PALETTE)],
                "x": 2 + i,
                "y": 2,
            }
        )
    c = {
        "id": secrets.token_hex(6),
        "name": text_of(name, "the campaign name", NAME_MAX),
        "world": world_id,
        "created": time.time(),
        "party": members,
        "log": [],
        "next_n": 1,
        "summary": "",
        "summarised": 0,
        "maps": [first],
        "map": first["id"],
    }
    with LOCK:
        save(c)
    return c


PALETTE = [
    "#e0b354",
    "#5fb3d9",
    "#d9675f",
    "#7fc77a",
    "#b48ae0",
    "#e08ac0",
    "#d9a25f",
    "#8ad9cf",
]


def list_campaigns() -> list[dict]:
    out = []
    for path in campaigns_dir().glob("*.json"):
        try:
            c = json.loads(path.read_text(encoding="utf-8"))
            out.append(
                {
                    "id": c["id"],
                    "name": c["name"],
                    "world": c["world"],
                    "party": [m["name"] for m in c["party"]],
                    "entries": len(c["log"]),
                    "updated": float(c.get("updated", 0)),
                }
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue  # an unreadable campaign file is skipped, not fatal
    return sorted(out, key=lambda c: -c["updated"])


def view(c: dict) -> dict:
    return {**c, "busy": c["id"] in BUSY}


def add_entry(c: dict, kind: str, who: str, text: str, **extra) -> dict:
    entry = {
        "n": c["next_n"],
        "kind": kind,
        "who": who,
        "text": text,
        "at": time.time(),
        **extra,
    }
    c["next_n"] += 1
    c["log"].append(entry)
    return entry


def who_of(c: dict, who) -> str:
    name = str(who or "").strip()
    if not name:
        return ""
    m = find_member(c["party"], name)
    if not m or m["name"] != name:
        raise TavernError(f"{name} is not in the party")
    return name


def say(cfg: dict, cid: str, who: str, text: str, kind: str = "say") -> dict:
    if kind not in ("say", "note"):
        raise TavernError("say or note")
    with LOCK:
        c = load(cid)
        add_entry(
            c, kind, who_of(c, who), text_of(text, "the text", cfg["story"]["text_max"])
        )
        save(c)
        return view(c)


def do_roll(
    cfg: dict, cid: str, expr: str, who: str = "", why: str = "", ask: str = ""
) -> dict:
    """Rolls and logs it. `ask` is "<n>.<i>": the game master's request this
    answers, which is then marked done."""
    with LOCK:
        c = load(cid)
        name = who_of(c, who)
        asked = None
        if ask:
            n, _, i = str(ask).partition(".")
            for e in c["log"]:
                if str(e["n"]) == n and e["kind"] == "gm":
                    asks = e.get("asks") or []
                    if i.isdigit() and int(i) < len(asks):
                        asked = asks[int(i)]
            if asked and asked.get("done"):
                raise TavernError("that roll has already been made")
        result = roll(expr, cfg)
        entry = add_entry(
            c, "roll", name, text_of(why, "the reason", NAME_MAX, False), roll=result
        )
        if asked:
            asked["done"] = entry["n"]
        save(c)
        return view(c)


def set_hp(m: dict, delta: int) -> dict:
    """Moves a member's HP, kept between minus max HP and max HP; returns
    the change made."""
    before = m["hp"]
    m["hp"] = max(-m["max_hp"], min(m["max_hp"], m["hp"] + delta))
    return {"id": m["id"], "who": m["name"], "delta": m["hp"] - before}


def member_of(c: dict, change: dict) -> dict | None:
    """The member an hp change was made to: by id (older entries: by name)."""
    if change.get("id"):
        return next((m for m in c["party"] if m["id"] == change["id"]), None)
    return find_member(c["party"], change.get("who", ""))


def adjust_hp(cid: str, pid: str, delta) -> dict:
    with LOCK:
        c = load(cid)
        m = next((m for m in c["party"] if m["id"] == pid), None)
        if not m:
            raise TavernError("no such character")
        set_hp(m, int_of(delta, "the change", -999, 999))
        save(c)
        return view(c)


def save_member(cfg: dict, cid: str, raw: dict) -> dict:
    with LOCK:
        c = load(cid)
        world = load_worlds().get(c["world"], {})
        old = next((m for m in c["party"] if m["id"] == raw.get("id")), None)
        if raw.get("id") and not old:
            raise TavernError("no such character")
        if not old and len(c["party"]) >= cfg["party_max"]:
            raise TavernError(f"at most {cfg['party_max']} characters")
        m = member(cfg, world, raw, old)
        if any(
            o["name"].lower() == m["name"].lower() and o["id"] != m["id"]
            for o in c["party"]
        ):
            raise TavernError("two characters have the same name")
        if old:
            c["party"][c["party"].index(old)] = m
            for mp in c["maps"]:
                for t in mp["tokens"]:
                    if t["id"] == m["id"]:
                        t["name"] = m["name"]
        else:
            c["party"].append(m)
            shown = next((mp for mp in c["maps"] if mp["id"] == c.get("map")), None)
            if shown and len(shown["tokens"]) < cfg["map"]["max_tokens"]:
                taken = {(t["x"], t["y"]) for t in shown["tokens"]}
                free = [
                    (x, y)
                    for y in range(shown["h"])
                    for x in range(shown["w"])
                    if (x, y) not in taken
                ]
                if free:
                    x, y = min(free, key=lambda p: (abs(p[1] - 2), abs(p[0] - 2)))
                    shown["tokens"].append(
                        {
                            "id": m["id"],
                            "name": m["name"],
                            "color": PALETTE[(len(c["party"]) - 1) % len(PALETTE)],
                            "x": x,
                            "y": y,
                        }
                    )
        save(c)
        return view(c)


def remove_member(cid: str, pid: str) -> dict:
    with LOCK:
        c = load(cid)
        if len(c["party"]) == 1:
            raise TavernError("the party needs at least one character")
        before = len(c["party"])
        c["party"] = [m for m in c["party"] if m["id"] != pid]
        if len(c["party"]) == before:
            raise TavernError("no such character")
        for mp in c["maps"]:
            mp["tokens"] = [t for t in mp["tokens"] if t["id"] != pid]
        save(c)
        return view(c)


# --- maps -------------------------------------------------------------------


def new_map(cfg: dict, cid: str, name: str, w, h) -> dict:
    side = cfg["map"]["max_side"]
    with LOCK:
        c = load(cid)
        mp = blank_map(
            cfg,
            text_of(name, "the map name", NAME_MAX),
            int_of(w, "the width", 4, side),
            int_of(h, "the height", 4, side),
        )
        c["maps"].append(mp)
        c["map"] = mp["id"]
        save(c)
        return view(c)


def save_map(cfg: dict, cid: str, mid: str, raw: dict) -> dict:
    """Replaces a map's name, cells and tokens with checked copies, and makes
    it the map shown."""
    keys = {t["key"] for t in cfg["terrain"]}
    with LOCK:
        c = load(cid)
        mp = next((m for m in c["maps"] if m["id"] == mid), None)
        if not mp:
            raise TavernError("no such map")
        if "name" in raw:
            mp["name"] = text_of(raw["name"], "the map name", NAME_MAX)
        if "cells" in raw:
            cells = raw["cells"]
            if (
                not isinstance(cells, list)
                or len(cells) != mp["h"]
                or not all(
                    isinstance(r, str) and len(r) == mp["w"] and set(r) <= keys
                    for r in cells
                )
            ):
                raise TavernError("the map's squares do not fit its size")
            mp["cells"] = cells
        if "tokens" in raw:
            tokens = raw["tokens"]
            if not isinstance(tokens, list) or len(tokens) > cfg["map"]["max_tokens"]:
                raise TavernError(f"at most {cfg['map']['max_tokens']} tokens")
            clean = []
            for t in tokens:
                if not isinstance(t, dict):
                    raise TavernError("a token is not readable")
                color = str(t.get("color") or PALETTE[0])
                if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                    raise TavernError("a token's colour is not #rrggbb")
                clean.append(
                    {
                        "id": str(t.get("id") or secrets.token_hex(4))[:16],
                        "name": text_of(t.get("name"), "a token's name", NAME_MAX),
                        "color": color,
                        "x": int_of(t.get("x"), "a token's column", 0, mp["w"] - 1),
                        "y": int_of(t.get("y"), "a token's row", 0, mp["h"] - 1),
                    }
                )
            mp["tokens"] = clean
        c["map"] = mp["id"]
        save(c)
        return view(c)


def map_story(cfg: dict, c: dict) -> str:
    """The shown map in words, for the game master."""
    mp = next((m for m in c["maps"] if m["id"] == c.get("map")), None)
    if not mp or not mp["tokens"]:
        return ""
    names = {t["key"]: t["label"].lower() for t in cfg["terrain"]}
    where = [
        f"{t['name']} at column {t['x'] + 1}, row {t['y'] + 1} ({names.get(mp['cells'][t['y']][t['x']], 'ground')})"
        for t in mp["tokens"]
    ]
    return (
        f"The table's map, {mp['name']} ({mp['w']} by {mp['h']} squares): "
        + "; ".join(where)
        + "."
    )


# --- the game master --------------------------------------------------------


def system_prompt(cfg: dict, c: dict, world: dict) -> str:
    party = "; ".join(
        f"{m['name']}"
        + (f", {m['role']}" if m["role"] else "")
        + f", {m['hp']} of {m['max_hp']} HP"
        + (f" ({m['notes']})" if m["notes"] else "")
        for m in c["party"]
    )
    parts = [
        f"You are the game master of a tabletop role-playing campaign called {c['name']}.",
        f"Setting: {world.get('blurb', '')}",
        f"Tone: {world.get('tone', '')}",
        f"The players' characters: {party}.",
        "Describe what they see and hear, and play everyone else in the world."
        " Never decide what the players' characters think, say or do."
        " Reply in under 180 words, then ask what they do.",
        "When the outcome of an action is uncertain, ask for a roll with a tag"
        " like [roll 1d20+2 Aria Stealth] and stop; the players roll and you"
        " tell what happens next turn, a higher total being better.",
        "When a character is hurt or healed, add a tag like [hp Aria -4] or [hp Aria +3].",
    ]
    story = map_story(cfg, c)
    if story:
        parts.append(story)
    if c["summary"]:
        parts.append("The story so far: " + c["summary"])
    return "\n".join(parts)


def line_of(e: dict) -> str:
    who = e["who"] or "The party"
    if e["kind"] == "roll":
        why = f" for {e['text']}" if e["text"] else ""
        return f"{who} rolls {e['roll']['expr']}{why}: {e['roll']['text']}"
    if e["kind"] == "note":
        return f"(Out of character, {who}: {e['text']})"
    return f"{who}: {e['text']}"


def messages_for(cfg: dict, c: dict, world: dict, opening: bool) -> list[dict]:
    """System prompt, then the recent story as alternating user and assistant
    turns (players, rolls and notes are the user; the game master is the
    assistant), ending on a user turn."""
    # Everything not yet in the summary: folding keeps that near fold_at
    # entries. Twice that is the cap for when recaps keep failing.
    cap = 2 * cfg["story"]["fold_at"]
    recent = c["log"][max(c["summarised"], len(c["log"]) - cap) :]
    turns: list[dict] = []
    for e in recent:
        role = "assistant" if e["kind"] == "gm" else "user"
        text = e["text"] if role == "assistant" else line_of(e)
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n" + text
        else:
            turns.append({"role": role, "content": text})
    if opening:
        turns.append(
            {"role": "user", "content": world.get("opening", "Begin the campaign.")}
        )
    elif not turns or turns[-1]["role"] == "assistant":
        turns.append(
            {"role": "user", "content": "(The players wait. Go on with the scene.)"}
        )
    if turns[0]["role"] == "assistant":
        turns.insert(0, {"role": "user", "content": "(The story so far continues.)"})
    return [{"role": "system", "content": system_prompt(cfg, c, world)}, *turns]


class Jan:
    """The game master's voice. Tests swap `ask` for a fake."""

    def __init__(self, owner=None):
        self.owner = owner  # forge_jan.AppJan, or None in tests

    def model(self, role: str) -> str:
        chosen = self.owner.model_for(role) if self.owner else ""
        if chosen and not is_embedding(chosen):
            return chosen
        found = [m for m in forge_jan.models() if not is_embedding(m)]
        if not found:
            raise JanDown(
                "Jan is not running or has no chat model; start Jan, then try again"
            )
        return found[0]

    def ask(
        self, role: str, messages: list[dict], max_tokens: int, temperature: float
    ) -> str:
        model = self.model(role)
        try:
            if self.owner:
                with self.owner.using(model):
                    return forge_jan.chat_messages(
                        model,
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout=180,
                    )
            return forge_jan.chat_messages(
                model,
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=180,
            )
        except forge_jan.JanError as e:
            raise JanDown(f"Jan could not answer: {e}") from e


def readable(cfg: dict, expr: str) -> bool:
    try:
        roll(expr, cfg, random.Random(0))
    except TavernError:
        return False
    return True


def is_embedding(model: str) -> bool:
    low = model.lower()
    return "embed" in low or "sentence-transformer" in low


def fold(cfg: dict, jan: Jan, cid: str) -> bool:
    """Folds older entries into the summary once more than fold_at are
    unsummarised, keeping the last `recent` as they are. A failed recap is
    skipped (the game goes on with the older summary)."""
    st = cfg["story"]
    with LOCK:
        c = load(cid)
        if len(c["log"]) - c["summarised"] <= st["fold_at"]:
            return False
        upto = len(c["log"]) - st["recent"]
        old = c["log"][c["summarised"] : upto]
        prior = c["summary"]
    events = "\n".join(
        line_of(e) if e["kind"] != "gm" else "Game master: " + e["text"] for e in old
    )
    messages = [
        {
            "role": "system",
            "content": "You keep the notes for a tabletop role-playing campaign."
            " Write the story so far in under 250 words of plain prose: who the"
            " characters met, where they went, what they found or carry, wounds,"
            " promises and open threads. No headings.",
        },
        {
            "role": "user",
            "content": (f"The story so far: {prior}\n\n" if prior else "")
            + "What happened next:\n"
            + events,
        },
    ]
    try:
        summary = jan.ask("recap", messages, st["recap_max_tokens"], 0.3)
    except JanDown:
        return False
    with LOCK:
        c = load(cid)
        c["summary"] = summary.strip()
        c["summarised"] = upto
        save(c)
    return True


def gm_turn(cfg: dict, jan: Jan, cid: str, who: str = "", text: str = "") -> dict:
    """The player's action (if any) goes in the log, then the game master
    answers. With no text the game master goes on, or opens the campaign when
    the log is empty."""
    with LOCK:
        if cid in BUSY:
            raise Busy("the game master is still writing")
        c = load(cid)
        if text.strip():
            add_entry(
                c,
                "say",
                who_of(c, who),
                text_of(text, "the text", cfg["story"]["text_max"]),
            )
            save(c)
        BUSY.add(cid)
    try:
        fold(cfg, jan, cid)
        return answer(cfg, jan, cid)
    finally:
        BUSY.discard(cid)


def take_back(c: dict, n: int) -> None:
    """Removes entry n and undoes the HP changes it made."""
    entry = next((e for e in c["log"] if e["n"] == n), None)
    if not entry:
        return
    c["log"].remove(entry)
    for h in entry.get("hp") or []:
        m = member_of(c, h)
        if m:
            set_hp(m, -h["delta"])
    c["summarised"] = min(c["summarised"], len(c["log"]))


def answer(cfg: dict, jan: Jan, cid: str, replace: int | None = None) -> dict:
    """Asks the game master and logs the reply. The caller holds BUSY. With
    `replace` (the n of the last GM reply) Jan is asked as if that reply
    had never been written, and it is swapped out only once the new one is
    in hand, so a failure leaves the story as it was."""
    with LOCK:
        c = load(cid)
    if replace is not None:
        take_back(c, replace)
    world = load_worlds().get(c["world"], {})
    opening = not any(e["kind"] == "gm" for e in c["log"])
    st = cfg["story"]
    reply = jan.ask(
        "gm",
        messages_for(cfg, c, world, opening),
        st["gm_max_tokens"],
        st["temperature"],
    )
    with LOCK:
        c = load(cid)
        if replace is not None:
            take_back(c, replace)
        clean, asks, hp = read_tags(reply, c["party"], cfg)
        applied = []
        for h in hp:
            m = member_of(c, h)
            if m:
                applied.append(set_hp(m, h["delta"]))
        add_entry(c, "gm", "", clean or "…", asks=asks, hp=applied)
        save(c)
        return view(c)


def claim(cid: str) -> dict:
    """Marks the campaign busy (409 if it already is) and returns it."""
    with LOCK:
        if cid in BUSY:
            raise Busy("the game master is still writing")
        c = load(cid)
        BUSY.add(cid)
        return c


def retry(cfg: dict, jan: Jan, cid: str) -> dict:
    """Asks again for the game master's last reply (taking back its HP
    changes). Only when that reply is the last entry."""
    with LOCK:
        c = claim(cid)
        if not c["log"] or c["log"][-1]["kind"] != "gm":
            BUSY.discard(cid)
            raise TavernError("only the game master's last reply can be asked again")
    try:
        return answer(cfg, jan, cid, replace=c["log"][-1]["n"])
    finally:
        BUSY.discard(cid)


def recap_now(cfg: dict, jan: Jan, cid: str) -> dict:
    """The summary brought up to the recent entries now, whatever the count."""
    st = dict(cfg["story"])
    st["fold_at"] = st["recent"]
    claim(cid)
    try:
        if not fold({**cfg, "story": st}, jan, cid):
            with LOCK:
                c = load(cid)
            if len(c["log"]) - c["summarised"] > st["recent"]:
                raise JanDown(
                    "Jan could not write the recap; try again when Jan is running"
                )
        with LOCK:
            return view(load(cid))
    finally:
        BUSY.discard(cid)


# --- out --------------------------------------------------------------------


def markdown(cid: str) -> str:
    c = load(cid)
    world = load_worlds().get(c["world"], {})
    out = [
        f"# {c['name']}",
        "",
        f"*{world.get('label', c['world'])}*",
        "",
        "## Party",
        "",
    ]
    for m in c["party"]:
        role = f", {m['role']}" if m["role"] else ""
        out.append(
            f"- **{m['name']}**{role}, {m['hp']}/{m['max_hp']} HP"
            + (f": {m['notes']}" if m["notes"] else "")
        )
    if c["summary"]:
        out += ["", "## Story so far", "", c["summary"]]
    out += ["", "## Log", ""]
    for e in c["log"]:
        if e["kind"] == "gm":
            out += [e["text"], ""]
        elif e["kind"] == "roll":
            out += [f"> 🎲 {line_of(e)}", ""]
        elif e["kind"] == "note":
            out += [f"> *{line_of(e)}*", ""]
        else:
            out += [f"**{e['who'] or 'The party'}:** {e['text']}", ""]
    return "\n".join(out).rstrip() + "\n"


def trash(cid: str) -> None:
    """Moves a campaign file to the system's trash (forge_trash), never rm."""
    with LOCK:
        if cid in BUSY:
            raise Busy("the game master is still writing")
        path = path_of(cid)
        if not path.is_file():
            raise TavernError("no such campaign")
        try:
            move_to_trash(path)
        except TrashError as e:
            raise TavernError("could not move it to the trash: " + str(e)[:200])
