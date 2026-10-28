"""Loading rule sets and campaigns from JSON, and checking them.

A campaign is a folder: campaign.json plus one sub-folder per kind of thing
(vocab.KINDS). Every file in a sub-folder is either one entity (it has an
"id") or holds a list under the kind's name. Nothing here knows any genre."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import vocab

ROOT = Path(__file__).resolve().parent.parent
RULESETS = ROOT / "rulesets"
CAMPAIGNS = ROOT / "campaigns"
ID = re.compile(r"^[a-z0-9_]+$")


class ContentError(ValueError):
    pass


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ContentError(f"{path}: not valid JSON ({exc})") from exc


def load_ruleset(rid: str, root: Path = RULESETS) -> dict:
    path = root / f"{rid}.json"
    if not path.is_file():
        raise ContentError(f"no rule set {rid!r}")
    rules = read_json(path)
    rules["_skills"] = {s["id"]: s for s in rules["skills"]}
    rules["_classes"] = {c["id"]: c for c in rules["classes"]}
    rules["_backgrounds"] = {b["id"]: b for b in rules["backgrounds"]}
    rules["_abilities"] = [a["id"] for a in rules["abilities"]]
    return rules


class World:
    """One campaign with its rule set: read-only content."""

    def __init__(self, folder: Path, rulesets: Path = RULESETS):
        self.folder = Path(folder)
        self.campaign = read_json(self.folder / "campaign.json")
        self.id = self.campaign["id"]
        self.rules = load_ruleset(self.campaign["ruleset"], rulesets)
        self.data: dict[str, dict[str, dict]] = {kind: {} for kind in vocab.KINDS}
        self.sources: dict[tuple[str, str], str] = {}
        self.duplicates: list[str] = []
        for kind in vocab.KINDS:
            sub = self.folder / kind
            if not sub.is_dir():
                continue
            for path in sorted(sub.rglob("*.json")):
                raw = read_json(path)
                entries = (
                    raw.get(kind)
                    if isinstance(raw, dict) and "id" not in raw
                    else [raw]
                )
                if not isinstance(entries, list):
                    raise ContentError(
                        f"{path}: expected an entity or {{{kind!r}: [...]}}"
                    )
                for entry in entries:
                    eid = entry.get("id", "") if isinstance(entry, dict) else ""
                    if not eid:
                        raise ContentError(f"{path}: an entry has no id")
                    if eid in self.data[kind]:
                        self.duplicates.append(
                            f"{kind}/{eid} in {path.name} and {self.sources[(kind, eid)]}"
                        )
                    self.data[kind][eid] = entry
                    self.sources[(kind, eid)] = path.name
        self.endings = {e["id"]: e for e in self.campaign.get("endings", [])}
        for cid, comp in self.data["companions"].items():
            for step in comp.get("arc", []):
                req = step.get("requires", {})
                if isinstance(req.get("affection"), (int, float)):
                    req["affection"] = {cid: req["affection"]}
        for loc in self.data["locations"].values():
            for f in loc.get("features", []):
                once_if_rewarding(f, ("success", "effects"))
        for kind in ("npcs", "companions"):
            for person in self.data[kind].values():
                for t in person.get("topics", []):
                    once_if_rewarding(t, ("effects", "success"))

    # lookups ---------------------------------------------------------------
    def get(self, kind: str, eid: str) -> dict:
        try:
            return self.data[kind][eid]
        except KeyError:
            raise ContentError(f"no {kind[:-1]} {eid!r} in {self.id}") from None

    def person(self, pid: str) -> dict | None:
        return self.data["companions"].get(pid) or self.data["npcs"].get(pid)

    def item(self, iid: str) -> dict:
        return self.get("items", iid)

    def counts(self) -> dict[str, int]:
        return {kind: len(v) for kind, v in self.data.items()}


def rewarding(effects) -> bool:
    """True if a list of effects gives xp, items, gold, affection or standing."""
    for eff in effects or []:
        if not isinstance(eff, dict):
            continue
        for key, val in eff.items():
            if key not in vocab.REWARD_EFFECTS:
                continue
            if key in ("give", "xp"):
                return True
            if key == "gold":
                if isinstance(val, (int, float)) and val > 0:
                    return True
                if isinstance(val, str) and val.strip() not in ("", "0"):
                    return not val.strip().startswith("-")
            if isinstance(val, dict) and any(
                isinstance(n, (int, float)) and n > 0 for n in val.values()
            ):
                return True
    return False


def once_if_rewarding(entry: dict, fields: tuple[str, ...]) -> None:
    """Rewards are not farmable: such an entry is once-only by default."""
    if "once" in entry or entry.get("repeat"):
        return
    if any(rewarding(entry.get(f)) for f in fields):
        entry["once"] = True


def list_campaigns(root: Path = CAMPAIGNS) -> list[dict]:
    found = []
    for path in sorted(root.glob("*/campaign.json")):
        try:
            c = read_json(path)
        except ContentError:
            continue
        found.append(
            {
                "id": c["id"],
                "name": c.get("name", c["id"]),
                "tagline": c.get("tagline", ""),
                "ruleset": c.get("ruleset", ""),
                "order": c.get("order", 99),
                "genre": c.get("genre", ""),
            }
        )
    return sorted(found, key=lambda c: (c["order"], c["name"]))


# --- validation ------------------------------------------------------------


class _Checker:
    def __init__(self, world: World):
        self.w = world
        self.problems: list[str] = list(f"duplicate id {d}" for d in world.duplicates)
        rules = world.rules
        self.rule_ids = {
            "abilities": set(rules["_abilities"]),
            "skills": set(rules["_skills"]),
            "classes": set(rules["_classes"]),
            "backgrounds": set(rules["_backgrounds"]),
        }
        self.periods = {p["id"] for p in rules["time"]["periods"]}
        self.difficulty = set(rules["difficulty"])

    def bad(self, where: str, text: str) -> None:
        self.problems.append(f"{where}: {text}")

    def ref(self, where: str, kind: str, value) -> None:
        if kind == "people":
            if not self.w.person(str(value)):
                self.bad(where, f"no npc or companion {value!r}")
            return
        if kind == "endings":
            if value not in self.w.endings:
                self.bad(where, f"no ending {value!r} in campaign.json")
            return
        if kind.startswith("rules:"):
            if value not in self.rule_ids[kind[6:]]:
                self.bad(where, f"no {kind[6:-1]} {value!r} in the rule set")
            return
        if value not in self.w.data.get(kind, {}):
            self.bad(where, f"no {kind[:-1]} {value!r}")

    def refs(self, where: str, kind: str, value) -> None:
        for v in value if isinstance(value, list) else [value]:
            self.ref(where, kind, v)

    def stage_ref(self, where: str, value) -> None:
        if not isinstance(value, dict):
            self.bad(where, "expected {quest: stage}")
            return
        for qid, sid in value.items():
            quest = self.w.data["quests"].get(qid)
            if not quest:
                self.bad(where, f"no quest {qid!r}")
            elif sid not in {s["id"] for s in quest.get("stages", [])}:
                self.bad(where, f"quest {qid!r} has no stage {sid!r}")

    def cond(self, where: str, c) -> None:
        if c is None:
            return
        if not isinstance(c, dict):
            self.bad(where, f"a condition must be a dict, got {c!r}")
            return
        for key, value in c.items():
            if key not in vocab.CONDITIONS:
                self.bad(where, f"unknown condition {key!r}")
                continue
            target = vocab.CONDITIONS[key]
            if target == "list":
                for i, sub in enumerate(value if isinstance(value, list) else []):
                    self.cond(f"{where}.{key}[{i}]", sub)
                if not isinstance(value, list):
                    self.bad(where, f"{key} takes a list")
            elif target == "cond":
                self.cond(f"{where}.not", value)
            elif target == "stage":
                self.stage_ref(where, value)
            elif target and target.startswith("keys:"):
                if not isinstance(value, dict):
                    self.bad(where, f"{key} takes a dict")
                    continue
                for k in value:
                    self.ref(where, target[5:], k)
                if key == "romance":
                    for v in value.values():
                        if v not in vocab.ROMANCE_ORDER:
                            self.bad(where, f"no romance stage {v!r}")
            elif target == "rules:abilities":
                for k in value if isinstance(value, dict) else [value]:
                    self.ref(where, target, k)
            elif target == "companions" and key == "partner" and value == "none":
                continue
            elif target:
                self.refs(where, target, value)
            elif key == "time":
                for v in value if isinstance(value, list) else [value]:
                    if v not in self.periods:
                        self.bad(where, f"no time of day {v!r}")

    def effects(self, where: str, effects) -> None:
        if effects is None:
            return
        if not isinstance(effects, list):
            self.bad(where, "effects must be a list")
            return
        for i, eff in enumerate(effects):
            here = f"{where}[{i}]"
            if not isinstance(eff, dict):
                self.bad(here, f"an effect must be a dict, got {eff!r}")
                continue
            for key, value in eff.items():
                if key not in vocab.EFFECTS:
                    self.bad(here, f"unknown effect {key!r}")
                    continue
                target = vocab.EFFECTS[key]
                if key in ("give", "take") and isinstance(value, dict):
                    self.ref(here, "items", value.get("item"))
                elif target == "stage":
                    self.stage_ref(here, value)
                elif target and target.startswith("keys:"):
                    if not isinstance(value, dict):
                        self.bad(here, f"{key} takes a dict")
                        continue
                    for k in value:
                        self.ref(here, target[5:], k)
                    if key == "romance":
                        for v in value.values():
                            if v not in vocab.ROMANCE_ORDER:
                                self.bad(here, f"no romance stage {v!r}")
                elif target:
                    self.refs(here, target, value)
                elif key in ("heal", "damage"):
                    from .dice import valid

                    if not valid(value, ("level",)):
                        self.bad(here, f"cannot roll {value!r}")

    def check(self, where: str, chk) -> None:
        if chk is None:
            return
        if not isinstance(chk, dict) or not ("skill" in chk or "ability" in chk):
            self.bad(where, "a check needs a skill or an ability")
            return
        if "skill" in chk:
            self.ref(where, "rules:skills", chk["skill"])
        if "ability" in chk:
            self.ref(where, "rules:abilities", chk["ability"])
        dc = chk.get("dc", "medium")
        if not isinstance(dc, int) and dc not in self.difficulty:
            self.bad(where, f"unknown dc {dc!r}")
        self.cond(where + ".advantage_when", chk.get("advantage_when"))

    def fields(self, kind: str, eid: str, entry: dict) -> None:
        if not ID.match(eid):
            self.bad(f"{kind}/{eid}", "ids are lowercase letters, digits and _")
        for key in entry:
            if key not in vocab.FIELDS[kind] and not key.startswith("_"):
                self.bad(f"{kind}/{eid}", f"unknown field {key!r}")

    def run(self) -> list[str]:
        w = self.w
        for kind in vocab.KINDS:
            for eid, entry in w.data[kind].items():
                self.fields(kind, eid, entry)
                getattr(self, "_" + kind)(f"{kind}/{eid}", entry)
        start = w.campaign.get("start", {})
        self.ref("campaign.start", "locations", start.get("location"))
        self.refs("campaign.start", "quests", start.get("quests", []))
        self.refs("campaign.start", "items", start.get("items", []))
        return self.problems

    def _regions(self, where, r):
        self.ref(where, "factions", r["faction"]) if r.get("faction") else None
        wilds = r.get("wilds", {})
        for i, enc in enumerate(wilds.get("encounters", [])):
            self.refs(f"{where}.encounters[{i}]", "monsters", enc.get("monsters", []))
        for i, ev in enumerate(wilds.get("events", [])):
            here = f"{where}.events[{i}]"
            self.cond(here, ev.get("when"))
            self.check(here, ev.get("check"))
            self.effects(here + ".success", ev.get("success"))
            self.effects(here + ".fail", ev.get("fail"))
            self.effects(here + ".effects", ev.get("effects"))
        self.refs(where + ".finds", "items", wilds.get("finds", []))

    def _locations(self, where, loc):
        self.ref(where, "regions", loc.get("region"))
        for i, ex in enumerate(loc.get("exits", [])):
            here = f"{where}.exits[{i}]"
            self.ref(here, "locations", ex.get("to"))
            self.cond(here, ex.get("when"))
            self.check(here, ex.get("check"))
            self.effects(here + ".fail", ex.get("fail"))
        for f in loc.get("features", []):
            here = f"{where}.features.{f.get('id')}"
            self.cond(here, f.get("when"))
            self.check(here, f.get("check"))
            self.effects(here + ".success", f.get("success"))
            self.effects(here + ".fail", f.get("fail"))
        self.refs(where + ".npcs", "people", loc.get("npcs", []))
        self.refs(where + ".shop", "items", loc.get("shop", {}).get("items", []))
        for i, oe in enumerate(loc.get("on_enter", [])):
            here = f"{where}.on_enter[{i}]"
            self.cond(here, oe.get("when"))
            self.effects(here, oe.get("effects"))
            if oe.get("scene"):
                self.ref(here, "scenes", oe["scene"])
        for group in loc.get("encounter", {}).get("monsters", []):
            self.refs(where + ".encounter", "monsters", group)

    def _npcs(self, where, n):
        place = n.get("location")
        if isinstance(place, list):
            for i, p in enumerate(place):
                self.ref(f"{where}.location[{i}]", "locations", p.get("location"))
                self.cond(f"{where}.location[{i}]", p.get("when"))
        elif place:
            self.ref(where, "locations", place)
        if n.get("faction"):
            self.ref(where, "factions", n["faction"])
        for t in n.get("topics", []):
            here = f"{where}.topics.{t.get('id')}"
            self.cond(here, t.get("when"))
            self.check(here, t.get("check"))
            self.effects(here, t.get("effects"))
            self.effects(here + ".fail_effects", t.get("fail_effects"))
        self.refs(where + ".quests", "quests", n.get("quests", []))

    def _companions(self, where, c):
        self._npcs(where, c)
        if c.get("class"):
            self.ref(where, "rules:classes", c["class"])
        rec = c.get("recruit", {})
        self.cond(where + ".recruit", rec.get("when"))
        if rec.get("scene"):
            self.ref(where + ".recruit", "scenes", rec["scene"])
        for k in c.get("gifts", {}):
            if k != "default":
                self.ref(where + ".gifts", "items", k)
        for i, a in enumerate(c.get("arc", [])):
            here = f"{where}.arc[{i}]"
            self.cond(here, a.get("requires"))
            self.ref(here, "scenes", a.get("scene"))
            if a.get("stage") not in vocab.ROMANCE_ORDER:
                self.bad(here, f"no romance stage {a.get('stage')!r}")
            if a.get("trigger", "any") not in vocab.TRIGGERS:
                self.bad(here, f"unknown trigger {a.get('trigger')!r}")
        if c.get("personal_quest"):
            self.ref(where, "quests", c["personal_quest"])
        combat = c.get("combat", {})
        for key in ("hp", "ac", "attack", "damage"):
            if key not in combat:
                self.bad(where + ".combat", f"missing {key}")

    def _quests(self, where, q):
        if q.get("giver"):
            self.ref(where, "people", q["giver"])
        ids = [s.get("id") for s in q.get("stages", [])]
        if not ids:
            self.bad(where, "a quest needs stages")
        for s in q.get("stages", []):
            here = f"{where}.stages.{s.get('id')}"
            self.cond(here, s.get("complete_when"))
            self.effects(here + ".on_complete", s.get("on_complete"))
            nxt = s.get("next", "done")
            if nxt not in ids and nxt not in ("done", "fail"):
                self.bad(here, f"next stage {nxt!r} does not exist")
        rewards = q.get("rewards", {})
        self.refs(where + ".rewards", "items", rewards.get("items", []))
        for k in rewards.get("affection", {}):
            self.ref(where + ".rewards", "companions", k)
        for k in rewards.get("reputation", {}):
            self.ref(where + ".rewards", "factions", k)
        self.cond(where + ".fail_when", q.get("fail_when"))

    def _scenes(self, where, s):
        nodes = s.get("nodes", {})
        if "start" not in nodes:
            self.bad(where, "a scene needs a start node")
        for nid, node in nodes.items():
            here = f"{where}.{nid}"
            if node.get("speaker"):
                self.ref(here, "people", node["speaker"])
            self.effects(here, node.get("effects"))
            targets = [node.get("next")] if node.get("next") else []
            for i, ch in enumerate(node.get("choices", [])):
                there = f"{here}.choices[{i}]"
                self.cond(there, ch.get("when"))
                self.check(there, ch.get("check"))
                self.effects(there, ch.get("effects"))
                self.effects(there + ".fail_effects", ch.get("fail_effects"))
                targets += [ch.get("next", "end")]
                if ch.get("check"):
                    targets.append(ch.get("fail_next", ch.get("next", "end")))
            for t in targets:
                if t != "end" and t not in nodes:
                    self.bad(here, f"goes to missing node {t!r}")

    def _items(self, where, it):
        if it.get("kind") not in vocab.ITEM_KINDS:
            self.bad(where, f"unknown item kind {it.get('kind')!r}")
        self.effects(where + ".use", it.get("use"))
        if it.get("damage"):
            from .dice import valid

            if not valid(it["damage"]):
                self.bad(where, f"cannot roll {it['damage']!r}")

    def _monsters(self, where, m):
        from .dice import valid

        for key in ("hp", "damage"):
            if not valid(m.get(key, "")):
                self.bad(where, f"cannot roll {key} {m.get(key)!r}")
        for loot in m.get("loot", []):
            self.ref(where + ".loot", "items", loot.get("item"))
        self.effects(where + ".on_defeat", m.get("on_defeat"))

    def _factions(self, where, f):
        if not f.get("ranks"):
            self.bad(where, "a faction needs ranks")

    def _templates(self, where, t):
        if t.get("kind") not in vocab.TEMPLATE_KINDS:
            self.bad(where, f"unknown template kind {t.get('kind')!r}")
        self.refs(where, "regions", t.get("regions", []))


def validate(world: World) -> list[str]:
    """Every broken reference and unknown key in a campaign; [] when clean."""
    return _Checker(world).run()
