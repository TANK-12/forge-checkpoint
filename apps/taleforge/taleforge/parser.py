"""Free text to an action. Deterministic on purpose: the ruleset's intent
words and skill verbs, plus the names of what is actually here. Anything it
cannot place becomes `freeform`, which Jan narrates without changing rules."""

from __future__ import annotations

import re

STOP = {
    "the",
    "a",
    "an",
    "to",
    "at",
    "on",
    "in",
    "into",
    "of",
    "and",
    "with",
    "my",
    "your",
    "her",
    "his",
    "their",
    "them",
    "him",
    "it",
    "this",
    "that",
    "some",
    "up",
    "down",
    "over",
    "for",
    "from",
    "about",
    "out",
    "i",
    "me",
    "we",
    "us",
    "go",
    "please",
}
WORD = re.compile(r"[a-z0-9']+")
QUOTE = re.compile(r"[\"“”](.+?)[\"“”]")


def words(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if w not in STOP and len(w) > 1]


def best(text: str, options: list[tuple[str, str]]) -> str | None:
    """The option id whose name shares the most words with the text."""
    have = set(words(text))
    scored = []
    for i, (oid, name) in enumerate(options):
        overlap = len(have & set(words(name)))
        if overlap:
            scored.append((overlap, -len(name), -i, oid))
    # ties go to the option listed first (the first foe, the nearest exit)
    return max(scored)[3] if scored else None


def has(text: str, phrase: str) -> bool:
    return re.search(r"(^|\W)" + re.escape(phrase) + r"($|\W)", text) is not None


def intent(rules: dict, text: str) -> str | None:
    """The intent whose keyword starts the sentence, else the first one named."""
    first = None
    for name, keys in rules.get("intents", {}).items():
        for k in keys:
            if text.startswith(k + " ") or text == k:
                return name
            if first is None and has(text, k):
                first = name
    return first


def parse(game, raw: str) -> dict:
    text = " ".join(raw.lower().split())
    rules = game.rules
    s = game.s
    people = [(p, game.person_name(p)) for p in game.people_here()]

    quoted = QUOTE.search(raw)
    if quoted and not s["scene"] and not s["combat"]:
        return {
            "do": "say",
            "text": quoted.group(1),
            "to": best(raw[: quoted.start()], people),
        }

    free = free_action(text)
    if free:
        return {"do": free}

    if s["scene"]:
        choices = game.scene_choices()
        if text.isdigit() and 1 <= int(text) <= len(choices):
            return {"do": "choose", "index": choices[int(text) - 1][0]}
        pick = best(text, [(str(i), ch["text"]) for i, ch in choices])
        if pick is not None:
            return {"do": "choose", "index": int(pick)}
        return {"do": "choose", "index": -1}

    if s["combat"]:
        return combat_parse(game, text)

    want = intent(rules, text)
    items = [(i, game.item_name(i)) for i in s["inventory"]]
    exits = [
        (
            e["to"],
            e.get("label", "") + " " + game.world.get("locations", e["to"])["name"],
        )
        for e in game.exits()
    ]
    feats = [(f["id"], f["name"]) for f in game.features()]
    gone = absent(game, text, people, exits + feats + items)
    if gone and want not in (
        "go",
        "look",
        "examine",
        "take",
        "buy",
        "sell",
        "use",
        "equip",
    ):
        # Naming someone who is elsewhere: let the engine say so plainly
        # instead of handing the line to whoever happens to be here.
        return {"do": "say", "text": raw.strip(), "to": gone}

    if want == "go":
        if has(text, "back") and s["prev_location"] in [e[0] for e in exits]:
            return {"do": "go", "to": s["prev_location"]}
        to = best(text, exits)
        if to:
            return {"do": "go", "to": to}
    if want == "look":
        thing = best(text, feats)
        return {"do": "examine", "feature": thing} if thing else {"do": "look"}
    if want in ("examine", "take"):
        thing = best(text, feats)
        if thing:
            return {"do": "examine", "feature": thing}
    if want == "talk":
        pid = best(text, people)
        if pid:
            tid = topic_for(game, pid, text)
            return (
                {"do": "topic", "to": pid, "topic": tid}
                if tid
                else {"do": "talk", "to": pid}
            )
    if want == "say":
        rest = raw.strip().split(" ", 1)[1] if " " in raw.strip() else ""
        if rest:
            return {"do": "say", "text": rest, "to": best(rest, people)}
    if want == "recruit":
        pid = best(text, people) or (people[0][0] if len(people) == 1 else None)
        if pid:
            return {"do": "recruit", "to": pid}
    if want == "dismiss":
        pid = best(text, [(c, game.person_name(c)) for c in game.party()])
        if pid:
            return {"do": "dismiss", "to": pid}
    if want == "give":
        pid, iid = best(text, people), best(text, items)
        if pid and iid:
            return {"do": "give", "to": pid, "item": iid}
    if want == "equip":
        iid = best(text, items)
        if iid:
            return {"do": "equip", "item": iid}
    if want == "use":
        iid = best(text, items)
        if iid:
            return {"do": "use", "item": iid}
    if want == "buy":
        shop = game.shop()
        if shop:
            iid = best(text, [(i, game.item_name(i)) for i in shop.get("items", [])])
            if iid:
                return {"do": "buy", "item": iid}
    if want == "sell":
        iid = best(text, items)
        if iid:
            return {"do": "sell", "item": iid}
    if want == "rest":
        long_rest = any(has(text, w) for w in ("sleep", "camp", "night", "long", "bed"))
        return {"do": "rest", "kind": "long" if long_rest else "short"}
    if want in ("explore", "inventory", "work", "help"):
        return {"do": want}
    if want == "attack":
        # hitting scenery is just a thing you try; there is no foe to roll against
        if best(text, feats):
            return {"do": "freeform", "text": raw.strip()}
        raise_peace(game)

    for pool, make in (
        (people, lambda p: {"do": "talk", "to": p}),
        (exits, lambda t: {"do": "go", "to": t}),
        (feats, lambda f: {"do": "examine", "feature": f}),
    ):
        hit = best(text, pool)
        if hit and len(words(text)) <= 4:
            return make(hit)

    skill = skill_for(rules, text)
    if skill:
        return {"do": "freeform", "text": raw.strip(), "skill": skill}
    if game.party() and (text.endswith("?") or has(text, "you")):
        return {"do": "say", "text": raw.strip(), "to": game.party()[0]}
    return {"do": "freeform", "text": raw.strip()}


USE_VERBS = ("use", "drink", "quaff", "eat", "potion", "draught", "heal me")


def free_action(text: str) -> str | None:
    """Looking around, help and the bag cost nothing, even mid-fight."""
    if (
        has(text, "inventory")
        or any(has(text, w) for w in ("my bag", "my pack", "my things"))
        or text in ("i", "inv", "bag", "what do i have")
    ):
        return "inventory"
    if text in ("help", "help me", "what can i do", "?"):
        return "help"
    if text in ("look", "look around", "l", "where am i"):
        return "look"
    return None


def raise_peace(game) -> None:
    from .core import GameError

    raise GameError(
        "there is nothing here that wants a fight; explore the wilds to find one"
    )


def absent(
    game, text: str, people: list[tuple[str, str]], scenery: list[tuple[str, str]]
) -> str | None:
    """A known person named in the text who is not here (nor matched by
    anyone who is), so the reply can say they are elsewhere."""
    if best(text, people):
        return None
    here = {p for p, _ in people}
    have = set(words(text)) - {w for _, name in scenery for w in words(name)}
    for kind in ("companions", "npcs"):
        for pid in game.world.data[kind]:
            # match on the id's own name part ("lyra", "brightwater_hollis"),
            # never on titles like "old" or "warden" that ordinary words share
            if pid not in here and pid.rsplit("_", 1)[-1] in have:
                return pid
    return None


def skill_for(rules: dict, text: str) -> str | None:
    for sk in rules["skills"]:
        for verb in sk.get("verbs", []):
            if has(text, verb):
                return sk["id"]
    return None


def topic_for(game, pid: str, text: str) -> str | None:
    if not has(text, "about"):
        return None
    tail = text.split("about", 1)[1]
    return best(tail, [(t["id"], t["prompt"]) for t in game.topics(pid)])


def combat_parse(game, text: str) -> dict:
    foes = [(e["uid"], e["label"]) for e in game.living()]
    if any(has(text, w) for w in ("flee", "run", "escape", "retreat")):
        return {"do": "flee"}
    if any(has(text, w) for w in ("defend", "block", "guard", "parry")):
        return {"do": "defend"}
    from . import rules as R

    items = [
        (i, game.item_name(i))
        for i in game.s["inventory"]
        if game.world.item(i).get("kind") == "consumable"
    ]
    using = any(has(text, w) for w in USE_VERBS)
    iid = best(text, items)
    if iid and using:
        return {"do": "item", "item": iid}
    abil = [
        (a["id"], a["name"])
        for a in R.class_abilities(game.world, game.pc)
        if a.get("kind") != "passive"
    ]
    aid = best(text, abil)
    if aid:
        return {"do": "ability", "id": aid, "target": best(text, foes)}
    if using and items:
        # "drink a potion" with no name given: the first thing that heals
        heal = [
            i
            for i, _ in items
            if any("heal" in e for e in game.world.item(i).get("use", []))
        ]
        return {"do": "item", "item": (heal or [items[0][0]])[0]}
    return {"do": "attack", "target": best(text, foes)}
