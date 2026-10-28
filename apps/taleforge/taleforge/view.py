"""What the UI sees: the game state turned into plain panels. Read-only."""

from __future__ import annotations

from . import rules as R
from .dice import signed

LOG_TAIL = 150


def ability_rows(game) -> list[dict]:
    m = R.mods(game.pc)
    return [
        {
            "id": a["id"],
            "name": a["name"],
            "score": game.pc["abilities"][a["id"]],
            "mod": signed(m[a["id"]]),
        }
        for a in game.rules["abilities"]
    ]


def sheet(game) -> dict:
    pc, rules = game.pc, game.rules
    cls = rules["_classes"][pc["class"]]
    skills = [
        {
            "id": sk["id"],
            "name": sk["name"],
            "ability": sk["ability"],
            "bonus": signed(R.skill_bonus(rules, pc, sk["id"])),
            "proficient": sk["id"] in pc["skills"],
            "expert": sk["id"] in pc.get("expertise", []),
        }
        for sk in rules["skills"]
    ]
    abilities = []
    for ab in R.class_abilities(game.world, pc):
        abilities.append(
            {
                "id": ab["id"],
                "name": ab["name"],
                "kind": ab.get("kind"),
                "text": ab.get("text", ""),
                "uses": pc["uses"].get(ab["id"]) if ab.get("uses") else None,
                "max": ab.get("uses"),
                "per": ab.get("per"),
                "field": ab.get("kind") in ("heal", "restore", "advantage"),
            }
        )
    nxt = R.xp_for_next(rules, pc["level"])
    weapon = R.weapon(game.world, pc)
    return {
        "name": pc["name"],
        "pronouns": pc["pronouns"],
        "class": cls["name"],
        "background": rules["_backgrounds"][pc["background"]]["name"],
        "level": pc["level"],
        "xp": pc["xp"],
        "xp_next": nxt,
        "hp": pc["hp"],
        "max_hp": pc["max_hp"],
        "ac": game.player_ac() if game.s["combat"] else R.armour_class(game.world, pc),
        "attack": signed(R.attack_bonus(game.world, pc)),
        "weapon": weapon["name"],
        "damage": f"{weapon['damage']}{signed(R.mods(pc)[R.weapon_ability(pc, weapon)] + int(weapon.get('bonus', 0)))}",
        "proficiency": signed(R.proficiency(rules, pc["level"])),
        "abilities": ability_rows(game),
        "skills": skills,
        "powers": abilities,
        "ability_points": pc.get("ability_points", 0),
        "look": pc.get("look", ""),
    }


def here(game) -> dict:
    loc = game.location()
    region = game.world.data["regions"].get(game.region_id(), {})
    people = []
    for pid in game.people_here():
        is_comp = pid in game.world.data["companions"]
        c = game.comp(pid) if is_comp else None
        person = game.world.person(pid) or {}
        people.append(
            {
                "id": pid,
                "name": person.get("name", pid),
                "description": person.get("description", ""),
                "companion": is_comp,
                "in_party": bool(c and c["in_party"]),
                "can_recruit": bool(is_comp and c and not c["in_party"]),
                "met": pid in game.s["met"],
                "topics": game.topics(pid),
            }
        )
    exits = [
        {
            "to": e["to"],
            "label": e.get("label") or game.world.get("locations", e["to"])["name"],
            "name": game.world.get("locations", e["to"])["name"],
            "hours": e.get("hours", 0.25),
            "open": e["open"],
            "locked": e.get("locked", "") if not e["open"] else "",
            "visited": e["to"] in game.s["visited"],
            "check": bool(e.get("check")),
        }
        for e in game.exits()
    ]
    feats = [
        {
            "id": f["id"],
            "name": f["name"],
            "used": f["used"],
            "check": (f.get("check") or {}).get("skill", ""),
        }
        for f in game.features()
    ]
    shop = game.shop()
    shop_view = None
    if shop:
        shop_view = {
            "name": shop.get("name", "Shop"),
            "buys": shop.get("buys", True),
            "items": [
                {
                    "id": i,
                    "name": game.item_name(i),
                    "price": game.price(i),
                    "kind": game.world.item(i).get("kind"),
                    "text": game.world.item(i).get("text", ""),
                }
                for i in shop.get("items", [])
            ],
        }
    tags = loc.get("tags", [])
    can_sleep, how = game.can_sleep()
    return {
        "id": loc["id"],
        "name": loc["name"],
        "region": region.get("name", ""),
        "description": loc.get("description", ""),
        "tags": tags,
        "people": people,
        "exits": exits,
        "features": feats,
        "shop": shop_view,
        "can_explore": "wild" in tags,
        "board": "board" in tags,
        "can_sleep": can_sleep,
        "sleep_how": how,
        "rest_cost": loc.get("rest_cost", 0),
    }


def companions(game) -> list[dict]:
    out = []
    rel = game.rules["relationships"]
    for cid, comp in game.world.data["companions"].items():
        c = game.comp(cid)
        if cid not in game.s["met"] and not c["in_party"]:
            continue
        stage = "Acquainted"
        for st in rel["stages"]:
            if c["affection"] >= st["min"]:
                stage = st["name"]
        romance = next(
            (r["name"] for r in rel["romance_stages"] if r["id"] == c["romance"]), ""
        )
        out.append(
            {
                "id": cid,
                "name": comp["name"],
                "pronouns": comp.get("pronouns", ""),
                "class": comp.get("class", ""),
                "description": comp.get("description", ""),
                "affection": c["affection"],
                "stage": stage,
                "romance": romance if c["romance"] != "none" else "",
                "partner": game.s["partner"] == cid,
                "in_party": c["in_party"],
                "hp": c["hp"],
                "max_hp": c["max_hp"],
                "where": (
                    game.world.data["locations"].get(game.companion_location(cid) or "")
                    or {}
                ).get("name", ""),
                "heartbroken": game.flag(f"{cid}_heartbroken"),
            }
        )
    return out


def journal(game) -> list[dict]:
    out = []
    for qid, qs in game.s["quests"].items():
        q = game.quest(qid)
        if not q:
            continue
        stage = game.stage_def(qid) if qs["status"] == "active" else None
        out.append(
            {
                "id": qid,
                "name": q["name"],
                "kind": q.get("kind", "side"),
                "status": qs["status"],
                "summary": q.get("summary", ""),
                "objective": (stage or {}).get("objective", ""),
                "text": (stage or {}).get("text", ""),
                "generated": bool(q.get("generated")),
                "started": qs.get("started", 0),
            }
        )
    order = {"active": 0, "done": 1, "failed": 2, "dropped": 3}
    kinds = {"main": 0, "companion": 1, "side": 2}
    return sorted(
        out,
        key=lambda q: (
            order.get(q["status"], 3),
            kinds.get(q["kind"], 3),
            -q["started"],
        ),
    )


def bag(game) -> list[dict]:
    eq = set(v for v in game.pc["equipped"].values() if v)
    out = []
    for iid, n in game.s["inventory"].items():
        it = game.world.item(iid)
        out.append(
            {
                "id": iid,
                "name": it["name"],
                "count": n,
                "kind": it.get("kind"),
                "text": it.get("text", ""),
                "equipped": iid in eq,
                "value": game.price(iid, selling=True),
                "usable": it.get("kind") == "consumable",
                "equippable": it.get("kind") in ("weapon", "armor", "shield"),
                "giftable": it.get("kind") not in ("key",) and not it.get("unsellable"),
            }
        )
    return sorted(out, key=lambda x: (not x["equipped"], x["kind"] or "", x["name"]))


def scene(game) -> dict | None:
    sd = game.scene_def()
    if not sd:
        return None
    choices = []
    for i, ch in game.scene_choices():
        chk = ch.get("check")
        tag = ""
        if chk:
            name = (
                game.rules["_skills"][chk["skill"]]["name"]
                if chk.get("skill")
                else chk.get("ability", "").upper()
            )
            tag = f"{name} DC {game.dc(chk.get('dc', 'medium'))}"
        choices.append({"index": i, "text": ch["text"], "check": tag})
    return {"title": sd.get("title", ""), "choices": choices}


def combat(game) -> dict | None:
    cb = game.s["combat"]
    if not cb:
        return None
    return {
        "round": cb["round"],
        "enemies": [
            {
                "uid": e["uid"],
                "name": e["label"],
                "hp": e["hp"],
                "max_hp": e["max_hp"],
                "ac": e["ac"],
                "down": e["hp"] <= 0,
            }
            for e in cb["enemies"]
        ],
        "items": [b for b in bag(game) if b["usable"]],
    }


def view(game, sid: str, log_tail: int = LOG_TAIL) -> dict:
    s = game.s
    hour = s["hour"]
    ending = None
    if s["ending"]:
        e = game.world.endings.get(s["ending"], {"title": s["ending"], "text": ""})
        ending = {"id": s["ending"], "title": e.get("title"), "text": e.get("text")}
    return {
        "id": sid,
        "campaign": {
            "id": game.world.id,
            "name": game.world.campaign.get("name", ""),
            "genre": game.world.campaign.get("genre", ""),
        },
        "labels": game.rules.get("labels", {}),
        "turn": s["turn"],
        "day": s["day"],
        "clock": f"{int(hour):02d}:{int((hour % 1) * 60):02d}",
        "period": game.period(),
        "gold": s["gold"],
        "sheet": sheet(game),
        "here": here(game),
        "companions": companions(game),
        "journal": journal(game),
        "bag": bag(game),
        "scene": scene(game),
        "combat": combat(game),
        "ending": ending,
        "log": s["log"][-log_tail:],
    }
