"""Generated work: side quests built from a campaign's templates/ so the
world never runs dry. The engine picks the targets and the reward from the
region's own data; Jan only retells the hook (see game.do_take_work)."""

from __future__ import annotations

from typing import Any

OFFERS = 3
ACTIVE_MAX = 3


def templates(game) -> list[dict]:
    return list(game.world.data["templates"].values())


def _region(game) -> dict:
    return game.world.data["regions"].get(game.region_id(), {})


def _places(game, tag: str | None = None) -> list[dict]:
    rid = game.region_id()
    here = game.s["location"]
    return [
        loc
        for loc in game.world.data["locations"].values()
        if loc.get("region") == rid
        and loc["id"] != here
        and (tag is None or tag in loc.get("tags", []))
    ]


def _hops(game) -> dict[str, int]:
    """Steps along exits from where the player stands to every place."""
    locs = game.world.data["locations"]
    dist = {game.s["location"]: 0}
    edge = [game.s["location"]]
    while edge:
        nxt = []
        for lid in edge:
            for ex in locs.get(lid, {}).get("exits", []):
                if ex["to"] not in dist and game.cond(ex.get("when")):
                    dist[ex["to"]] = dist[lid] + 1
                    nxt.append(ex["to"])
        edge = nxt
    return dist


def _giver(game) -> tuple[str, str]:
    """(npc id or "", display name) of whoever posts the work."""
    npcs = [p for p in game.people_here() if p in game.world.data["npcs"]]
    if npcs:
        pid = game.rng.choice(npcs)
        return pid, game.person_name(pid)
    names = _region(game).get("wilds", {}).get("names") or ["a local"]
    return "", game.rng.choice(names)


def _plural(monster: dict) -> str:
    name = monster.get("plural") or monster["name"]
    if monster.get("plural"):
        return name
    if name.endswith("f"):
        return name[:-1] + "ves"
    return name if name.endswith("s") else name + "s"


def build(game, tpl: dict) -> dict | None:
    """One generated quest from a template, or None if the region lacks the
    pieces (no monsters for a slay, no finds for a fetch)."""
    wilds = _region(game).get("wilds", {})
    lvl = game.pc["level"]
    giver_id, giver = _giver(game)
    wild = _places(game, "wild") or _places(game)
    place = game.rng.choice(wild) if wild else game.location()
    lo, hi = tpl.get("count", [1, 1])
    count = game.rng.randint(int(lo), int(hi))
    words = {
        "giver": giver,
        "place": place["name"],
        "region": _region(game).get("name", ""),
        "count": str(count),
    }
    gid = f"gen_{game.s['gen_count'] + 1}"
    stage: dict[str, Any] = {"id": "start"}
    extra: dict = {}
    kind = tpl.get("kind")
    if kind == "slay":
        groups = [
            g for g in wilds.get("encounters", []) if g.get("min_level", 1) <= lvl
        ]
        if not groups:
            return None
        mid = game.rng.choice(game.rng.choice(groups)["monsters"])
        m = game.world.get("monsters", mid)
        words.update(
            monster=m["name"], monster_plural=_plural(m) if count > 1 else m["name"]
        )
        have = game.s["kills"].get(mid, 0)
        stage.update(
            objective=f"Defeat {count} {words['monster_plural']} (explore {words['region'] or 'the wilds'})",
            complete_when={"kills": {mid: have + count}},
        )
        extra["target"] = {"monster": mid, "count": count, "from": have}
    elif kind == "fetch":
        finds = wilds.get("finds", [])
        if not finds:
            return None
        iid = game.rng.choice(finds)
        words["item"] = game.item_name(iid)
        home = game.s["location"]
        stage.update(
            objective=f"Bring {words['item']} back to {game.location()['name']}",
            complete_when={"has_item": iid, "location": home},
            on_complete=[{"take": iid}],
        )
        extra.update(fetch=iid, giver=giver_id)
    elif kind == "deliver":
        targets = _places(game, "town") or _places(game)
        if not targets:
            return None
        # a delivery should be a trip, not the next room
        far = _hops(game)
        reach = [t for t in targets if t["id"] in far]
        targets = [t for t in reach if far[t["id"]] >= 2] or reach
        if not targets:
            return None
        dest = game.rng.choice(targets)
        words["place"] = dest["name"]
        stage.update(
            objective=f"Deliver the parcel to {dest['name']}",
            complete_when={"location": dest["id"]},
            on_complete=[{"reveal": dest["id"]}],
        )
        extra["reveal"] = dest["id"]
    else:
        return None
    rw = tpl.get("reward", {})
    words.setdefault("monster_plural", "")
    words.setdefault("monster", "")
    words.setdefault("item", "")
    fill = _Fill(words)
    quest = {
        "id": gid,
        "name": tpl.get("title", "Work").format_map(fill),
        "kind": "side",
        "generated": True,
        "template": tpl["id"],
        "level": lvl,
        "summary": tpl.get("hook", "").format_map(fill),
        "stages": [
            {**stage, "text": tpl.get("hook", "").format_map(fill), "next": "done"}
        ],
        "rewards": {
            "xp": int(rw.get("xp_per_level", 50)) * lvl,
            "gold": int(rw.get("gold_per_level", 10)) * lvl,
        },
        **extra,
    }
    if kind == "slay":
        quest["reveal"] = place["id"]
    return quest


class _Fill(dict):
    def __missing__(self, key):
        return ""


def offers(game) -> list[dict]:
    """Today's work at this board: up to OFFERS quests, the same all day."""
    s = game.s
    key = f"{s['location']}:{s['day']}"
    cache = s.setdefault("offers", {})
    if cache.get("key") != key:
        made = []
        pool = templates(game)
        for _ in range(OFFERS * 3):
            if len(made) >= OFFERS or not pool:
                break
            tpl = game.rng.choices(pool, weights=[t.get("weight", 1) for t in pool])[0]
            q = build(game, tpl)
            if q:
                s["gen_count"] += 1
                made.append(q)
        cache.clear()
        cache.update(key=key, list=made)
    return [
        {
            "id": q["id"],
            "name": q["name"],
            "summary": q["summary"],
            "rewards": q["rewards"],
        }
        for q in cache["list"]
    ]


def take(game, qid: str) -> dict:
    from .core import GameError

    cache = game.s.get("offers", {})
    q = next((x for x in cache.get("list", []) if x["id"] == qid), None)
    if q is None:
        raise GameError("that job is no longer on offer")
    active = [
        k
        for k, v in game.s["quests"].items()
        if v.get("status") == "active" and k.startswith("gen_")
    ]
    if len(active) >= ACTIVE_MAX:
        raise GameError(f"you already have {ACTIVE_MAX} jobs on; finish one first")
    cache["list"].remove(q)
    if q.get("fetch"):
        # what you already carry does not count: core.give sets <id>_found
        # when one turns up after the job was taken
        q["stages"][0]["complete_when"]["flag"] = qid + "_found"
    game.s["generated"][qid] = q
    game.start_quest(qid)
    if q.get("reveal"):
        game._eff_reveal(q["reveal"])
    return q


def abandon(game, qid: str) -> dict:
    from .core import GameError

    q = game.s["generated"].get(qid)
    if q is None or game.qstatus(qid) != "active":
        raise GameError("you have no job like that to drop")
    game.s["quests"][qid]["status"] = "dropped"
    return q


def rumour(game) -> str:
    """A rumour from the region's own lines; Jan dresses it up."""
    wilds = _region(game).get("wilds", {})
    pool = list(wilds.get("rumours", [])) + list(wilds.get("sights", []))
    if not pool:
        return "'Nothing worth repeating, friend.'"
    return "'They say " + game.rng.choice(pool).rstrip(".").lower() + ".'"
