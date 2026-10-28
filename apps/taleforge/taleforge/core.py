"""The rules engine's core: game state, conditions, effects, quests and scenes.

The engine is the only thing that changes the state. Jan is handed facts
afterwards and asked to describe them; nothing Jan writes is read back as a
rule (see narrator.py)."""

from __future__ import annotations

import random
from typing import Any
import time

from . import rules as R
from .dice import DiceError, d20, roll, signed
from .vocab import ROMANCE_ORDER
from .world import World

LOG_CAP = 400
MEMORY_CAP = 12


class GameError(ValueError):
    """An action that cannot be taken right now; the message says why."""


def new_state(world: World, pc: dict) -> dict:
    start = world.campaign.get("start", {})
    state = {
        "version": 1,
        "campaign": world.id,
        "created": time.time(),
        "turn": 0,
        "day": 1,
        "hour": float(start.get("hour", 8)),
        "pc": pc,
        "gold": 0,
        "inventory": {},
        "location": start["location"],
        "prev_location": start["location"],
        "last_safe": start["location"],
        "visited": [],
        "known": [],
        "flags": [],
        "unlocked": [],
        "quests": {},
        "generated": {},
        "gen_count": 0,
        "kills": {},
        "companions": {},
        "met": [],
        "partner": "none",
        "reputation": {},
        "done": [],
        "scene": None,
        "scene_queue": [],
        "combat": None,
        "log": [],
        "ending": None,
        "freeform_xp": [],
        "entry_seq": 0,
    }
    for cid, comp in world.data["companions"].items():
        state["companions"][cid] = companion_state(comp)
    return state


def companion_state(comp: dict) -> dict:
    hp = int(comp.get("combat", {}).get("hp", 10))
    return {
        "affection": int(comp.get("start_affection", 0)),
        "romance": "none",
        "in_party": False,
        "hp": hp,
        "max_hp": hp,
        "memories": [],
        "tone_turns": {},
        "gift_turn": -99,
        "seen_reactions": [],
        "arc_done": [],
        "history": [],
    }


def as_list(v: Any) -> list:
    return v if isinstance(v, list) else [v]


class GameCore:
    """State plus the condition and effect languages. Subclasses add actions."""

    def __init__(self, world: World, state: dict, rng: random.Random | None = None):
        self.world = world
        self.rules = world.rules
        self.s = state
        self.rng = rng or random.Random()
        self.out: list[dict] = []
        self.pending_combat: list[str] | None = None
        self.trigger = "any"
        for cid, comp in world.data["companions"].items():
            state["companions"].setdefault(cid, companion_state(comp))

    # output -----------------------------------------------------------------
    def emit(self, kind: str, text: str = "", **extra) -> dict:
        self.s["entry_seq"] = self.s.get("entry_seq", 0) + 1
        entry = {
            "id": f"e{self.s['entry_seq']}",
            "kind": kind,
            "text": text,
            "turn": self.s["turn"],
        }
        entry.update(extra)
        self.out.append(entry)
        self.s["log"].append(entry)
        if len(self.s["log"]) > LOG_CAP:
            del self.s["log"][: len(self.s["log"]) - LOG_CAP]
        return entry

    def chip(self, text: str, tone: str = "info") -> None:
        self.emit("chip", text, tone=tone)

    def label(self, key: str, default: str) -> str:
        return self.rules.get("labels", {}).get(key, default)

    # small lookups ------------------------------------------------------------
    @property
    def pc(self) -> dict:
        return self.s["pc"]

    def flag(self, name: str) -> bool:
        return name in self.s["flags"]

    def comp(self, cid: str) -> dict:
        return self.s["companions"][cid]

    def party(self) -> list[str]:
        return [cid for cid, c in self.s["companions"].items() if c["in_party"]]

    def location(self) -> dict:
        return self.world.get("locations", self.s["location"])

    def region_id(self) -> str:
        return self.location().get("region", "")

    def period(self) -> str:
        hour = self.s["hour"] % 24
        current = "day"
        for p in self.rules["time"]["periods"]:
            if hour >= p["from"]:
                current = p["id"]
        return current

    def pass_time(self, hours: float) -> None:
        self.s["hour"] += float(hours)
        while self.s["hour"] >= 24:
            self.s["hour"] -= 24
            self.s["day"] += 1

    def quest(self, qid: str) -> dict | None:
        return self.s["generated"].get(qid) or self.world.data["quests"].get(qid)

    def qstatus(self, qid: str) -> str:
        return self.s["quests"].get(qid, {}).get("status", "none")

    def item_name(self, iid: str) -> str:
        it = self.world.data["items"].get(iid)
        return it["name"] if it else iid

    def person_name(self, pid: str) -> str:
        p = self.world.person(pid)
        return p["name"] if p else pid

    def dc(self, value) -> int:
        if isinstance(value, (int, float)):
            return int(value)
        return int(self.rules["difficulty"].get(str(value), 13))

    def done_once(self, key: str) -> bool:
        return key in self.s["done"]

    def mark_once(self, key: str) -> None:
        if key not in self.s["done"]:
            self.s["done"].append(key)

    # conditions ---------------------------------------------------------------
    def cond(self, c: dict | None) -> bool:
        if not c:
            return True
        return all(self._cond_key(k, v) for k, v in c.items())

    def _cond_key(self, key: str, v: Any) -> bool:
        s, pc = self.s, self.pc
        many = as_list(v)
        if key == "flag":
            return all(f in s["flags"] for f in many)
        if key == "not_flag":
            return not any(f in s["flags"] for f in many)
        if key == "has_item":
            return all(s["inventory"].get(i, 0) > 0 for i in many)
        if key == "item_count":
            return all(s["inventory"].get(i, 0) >= int(n) for i, n in v.items())
        if key == "not_item":
            return not any(s["inventory"].get(i, 0) > 0 for i in many)
        if key == "gold":
            return s["gold"] >= int(v)
        if key == "level":
            return pc["level"] >= int(v)
        if key == "ability":
            return all(pc["abilities"].get(a, 0) >= int(n) for a, n in v.items())
        if key == "skill":
            return all(sk in pc["skills"] for sk in many)
        if key == "class":
            return pc["class"] in many
        if key == "background":
            return pc["background"] in many
        if key == "location":
            return s["location"] in many
        if key == "region":
            return self.region_id() in many
        if key == "visited":
            return all(loc in s["visited"] for loc in many)
        if key == "quest_active":
            return all(self.qstatus(q) == "active" for q in many)
        if key == "quest_done":
            return all(self.qstatus(q) == "done" for q in many)
        if key == "quest_failed":
            return all(self.qstatus(q) == "failed" for q in many)
        if key == "quest_not_started":
            return all(self.qstatus(q) == "none" for q in many)
        if key == "quest_stage":
            return all(
                self.qstatus(q) == "active" and s["quests"][q]["stage"] == st
                for q, st in v.items()
            )
        if key == "affection":
            return all(self.comp(c)["affection"] >= int(n) for c, n in v.items())
        if key == "affection_below":
            return all(self.comp(c)["affection"] < int(n) for c, n in v.items())
        if key == "romance":
            return all(
                ROMANCE_ORDER.index(self.comp(c)["romance"]) >= ROMANCE_ORDER.index(st)
                for c, st in v.items()
            )
        if key == "partner":
            return s["partner"] in many
        if key == "in_party":
            return all(self.comp(c)["in_party"] for c in many)
        if key == "not_in_party":
            return not any(self.comp(c)["in_party"] for c in many)
        if key == "met":
            return all(p in s["met"] for p in many)
        if key == "reputation":
            return all(s["reputation"].get(f, 0) >= int(n) for f, n in v.items())
        if key == "time":
            return self.period() in many
        if key == "kills":
            return all(s["kills"].get(m, 0) >= int(n) for m, n in v.items())
        if key == "chance":
            return self.rng.random() < float(v)
        if key == "all":
            return all(self.cond(sub) for sub in v)
        if key == "any":
            return any(self.cond(sub) for sub in v)
        if key == "not":
            return not self.cond(v)
        raise GameError(f"unknown condition {key!r}")

    # checks -------------------------------------------------------------------
    def check(self, chk: dict, label: str = "", advantage: int = 0) -> bool:
        """Roll a skill or ability check, show it, and return success."""
        rules = self.rules
        if chk.get("skill"):
            skill = rules["_skills"][chk["skill"]]
            bonus = R.skill_bonus(rules, self.pc, chk["skill"])
            name = skill["name"]
        else:
            ability = chk.get("ability", "str")
            bonus = R.mods(self.pc)[ability]
            name = next(
                (a["name"] for a in rules["abilities"] if a["id"] == ability), ability
            )
        if chk.get("advantage_when") and self.cond(chk["advantage_when"]):
            advantage = max(advantage, 1)
        if self.s.get("advantage"):
            advantage = max(advantage, 1)
            self.s["advantage"] = False
        dc = self.dc(chk.get("dc", "medium"))
        r = d20(self.rng, bonus, advantage)
        cr = rules["check_rules"]
        if r["natural"] >= cr.get("crit_success", 20):
            ok = True
        elif r["natural"] <= cr.get("crit_fail", 1):
            ok = False
        else:
            ok = r["total"] >= dc
        dice = r["dice"]
        shown = (
            f"d20 ({' / '.join(map(str, dice))})"
            if len(dice) > 1
            else f"d20 ({dice[0]})"
        )
        text = f"{name}: {shown} {signed(bonus)} = {r['total']} vs DC {dc}, {'success' if ok else 'failure'}"
        if r["natural"] == 20:
            text += " (natural 20)"
        elif r["natural"] == 1:
            text += " (natural 1)"
        self.emit(
            "roll",
            text,
            label=label or name,
            skill=name,
            dice=dice,
            natural=r["natural"],
            bonus=bonus,
            total=r["total"],
            dc=dc,
            success=ok,
            advantage=advantage,
        )
        return ok

    # effects ------------------------------------------------------------------
    def apply(self, effects: list | None) -> None:
        for eff in effects or []:
            for key, value in eff.items():
                getattr(self, "_eff_" + key)(value)

    def _eff_flag(self, v):
        for f in v if isinstance(v, list) else [v]:
            if f not in self.s["flags"]:
                self.s["flags"].append(f)

    def _eff_clear_flag(self, v):
        for f in v if isinstance(v, list) else [v]:
            if f in self.s["flags"]:
                self.s["flags"].remove(f)

    def _item_count(self, v) -> tuple[str, int]:
        if isinstance(v, dict):
            return v["item"], int(v.get("count", 1))
        return v, 1

    def _eff_give(self, v):
        iid, n = self._item_count(v)
        self.give(iid, n)

    def give(self, iid: str, n: int = 1, quiet: bool = False) -> None:
        self.world.item(iid)
        self.s["inventory"][iid] = self.s["inventory"].get(iid, 0) + n
        for qid in self.s["generated"]:
            # a fetch job counts only what turns up after it was taken
            if (
                self.s["generated"][qid].get("fetch") == iid
                and self.qstatus(qid) == "active"
            ):
                if qid + "_found" not in self.s["flags"]:
                    self.s["flags"].append(qid + "_found")
        if not quiet:
            more = f" x{n}" if n > 1 else ""
            self.chip(f"Gained {self.item_name(iid)}{more}", "good")

    def _eff_take(self, v):
        iid, n = self._item_count(v)
        self.take(iid, n)

    def take(self, iid: str, n: int = 1, quiet: bool = False) -> bool:
        have = self.s["inventory"].get(iid, 0)
        if have <= 0:
            return False
        left = max(0, have - n)
        if left:
            self.s["inventory"][iid] = left
        else:
            del self.s["inventory"][iid]
            for slot, eq in self.pc["equipped"].items():
                if eq == iid:
                    self.pc["equipped"][slot] = None
        if not quiet:
            self.chip(f"Lost {self.item_name(iid)}", "bad")
        return True

    def _eff_gold(self, v):
        amount = int(v)
        self.s["gold"] = max(0, self.s["gold"] + amount)
        word = self.label("gold", "gold")
        self.chip(f"{signed(amount)} {word}", "good" if amount >= 0 else "bad")

    def _eff_xp(self, v):
        self.gain_xp(int(v))

    def gain_xp(self, amount: int) -> None:
        if amount <= 0:
            return
        self.pc["xp"] += amount
        self.chip(f"+{amount} {self.label('xp', 'XP')}", "good")
        for line in R.level_up(self.world, self.pc, self.rng):
            self.emit("level", line)
            for cid in self.party():
                c = self.comp(cid)
                c["max_hp"] += 5
                c["hp"] += 5

    def names(self) -> dict:
        return R.names_for(self.rules, self.pc)

    def _eff_heal(self, v):
        amount = roll(v, self.rng, self.names())["total"]
        self.heal(max(0, amount))

    def heal(self, amount: int) -> None:
        pc = self.pc
        before = pc["hp"]
        pc["hp"] = min(pc["max_hp"], pc["hp"] + amount)
        if pc["hp"] > before:
            self.chip(f"+{pc['hp'] - before} {self.label('hp', 'HP')}", "good")

    def _eff_damage(self, v):
        amount = max(0, roll(v, self.rng, self.names())["total"])
        self.hurt(amount)

    def hurt(self, amount: int) -> None:
        pc = self.pc
        pc["hp"] = max(0, pc["hp"] - amount)
        self.chip(f"-{amount} {self.label('hp', 'HP')}", "bad")
        if pc["hp"] == 0 and not self.s["combat"]:
            pc["hp"] = 1
            self.emit(
                "system", "You are badly hurt. Rest before anything else goes wrong."
            )

    def _eff_affection(self, v):
        for cid, n in v.items():
            self.add_affection(cid, int(n))

    def add_affection(self, cid: str, n: int, why: str = "") -> None:
        if not n:
            return
        rel = self.rules["relationships"]
        c = self.comp(cid)
        c["affection"] = max(rel["min"], min(rel["max"], c["affection"] + n))
        name = self.person_name(cid).split()[0]
        self.chip(f"{name} {signed(n)}", "love" if n > 0 else "bad")
        if why:
            self.remember(cid, why)

    def remember(self, cid: str, text: str) -> None:
        mem = self.comp(cid)["memories"]
        mem.append(f"Day {self.s['day']}: {text}")
        del mem[:-MEMORY_CAP]

    def _eff_romance(self, v):
        for cid, stage in v.items():
            c = self.comp(cid)
            if ROMANCE_ORDER.index(stage) > ROMANCE_ORDER.index(c["romance"]):
                c["romance"] = stage
                stage_name = next(
                    (
                        r["name"]
                        for r in self.rules["relationships"]["romance_stages"]
                        if r["id"] == stage
                    ),
                    stage,
                )
                self.chip(f"{self.person_name(cid).split()[0]}: {stage_name}", "love")
                self.remember(cid, f"our romance became: {stage_name}")
            elif stage == "none":
                c["romance"] = "none"

    def _eff_commit(self, v):
        cid = v
        self.s["partner"] = cid
        self.chip(f"You and {self.person_name(cid).split()[0]} are together", "love")
        for other, c in self.s["companions"].items():
            if other != cid and ROMANCE_ORDER.index(c["romance"]) >= 1:
                c["romance"] = "none"
                self._eff_flag(f"{other}_heartbroken")
                self.add_affection(other, -15, "you chose someone else")

    def _eff_reputation(self, v):
        for fid, n in v.items():
            self.s["reputation"][fid] = self.s["reputation"].get(fid, 0) + int(n)
            name = self.world.get("factions", fid)["name"]
            self.chip(f"{name} {signed(int(n))}", "good" if int(n) > 0 else "bad")

    def _eff_start_quest(self, v):
        self.start_quest(v)

    def _eff_complete_quest(self, v):
        self.complete_quest(v)

    def _eff_fail_quest(self, v):
        if self.qstatus(v) == "active":
            self.s["quests"][v]["status"] = "failed"
            self.emit(
                "quest",
                f"Quest failed: {(self.quest(v) or {}).get('name', v)}",
                tone="bad",
            )

    def _eff_stage(self, v):
        for qid, sid in v.items():
            if self.qstatus(qid) == "none":
                self.start_quest(qid, quiet=True)
            if self.qstatus(qid) == "active":
                self.s["quests"][qid]["stage"] = sid
                self.announce_stage(qid)

    def _eff_join(self, v):
        c = self.comp(v)
        if not c["in_party"]:
            c["in_party"] = True
            if v not in self.s["met"]:
                self.s["met"].append(v)
            lines = self.world.get("companions", v).get("lines", {})
            self.emit("chip", f"{self.person_name(v)} joins you", tone="love")
            if lines.get("join"):
                self.emit("speech", lines["join"], speaker=v, name=self.person_name(v))
            self.remember(v, "joined you on the road")

    def _eff_leave(self, v):
        c = self.comp(v)
        if c["in_party"]:
            c["in_party"] = False
            self.chip(f"{self.person_name(v)} leaves the party", "info")

    def _eff_move(self, v):
        self.world.get("locations", v)
        self.s["prev_location"] = self.s["location"]
        self.s["location"] = v
        self.visit(v)

    def visit(self, loc: str) -> None:
        if loc not in self.s["visited"]:
            self.s["visited"].append(loc)
        if loc not in self.s["known"]:
            self.s["known"].append(loc)
        if "safe" in self.world.get("locations", loc).get("tags", []):
            self.s["last_safe"] = loc

    def _eff_combat(self, v):
        self.pending_combat = list(v)

    def _eff_scene(self, v):
        self.s["scene_queue"].append(v)

    def _eff_message(self, v):
        self.emit("message", str(v))

    def _eff_hours(self, v):
        self.pass_time(float(v))

    def _eff_reveal(self, v):
        for loc in v if isinstance(v, list) else [v]:
            if loc not in self.s["known"]:
                self.s["known"].append(loc)
                self.chip(
                    f"New place: {self.world.get('locations', loc)['name']}", "info"
                )

    def _eff_unlock(self, v):
        if v not in self.s["unlocked"]:
            self.s["unlocked"].append(v)

    def _eff_ending(self, v):
        self.s["ending"] = v
        ending = self.world.endings.get(v, {"title": v, "text": ""})
        self.emit("ending", ending.get("text", ""), title=ending.get("title", v))

    # quests -------------------------------------------------------------------
    def start_quest(self, qid: str, quiet: bool = False) -> None:
        if self.qstatus(qid) != "none":
            return
        q = self.quest(qid)
        if not q:
            raise GameError(f"no quest {qid!r}")
        self.s["quests"][qid] = {
            "status": "active",
            "stage": q["stages"][0]["id"],
            "started": self.s["turn"],
        }
        if not quiet:
            self.emit("quest", f"New quest: {q['name']}", tone="new", quest=qid)
            self.announce_stage(qid)

    def announce_stage(self, qid: str) -> None:
        stage = self.stage_def(qid)
        if stage and stage.get("objective"):
            self.chip(f"Objective: {stage['objective']}", "info")

    def stage_def(self, qid: str) -> dict | None:
        q = self.quest(qid)
        st = self.s["quests"].get(qid, {}).get("stage")
        if not q:
            return None
        return next((x for x in q["stages"] if x["id"] == st), None)

    def complete_quest(self, qid: str) -> None:
        if self.qstatus(qid) == "done":
            return
        q = self.quest(qid)
        if not q:
            return
        self.s["quests"].setdefault(qid, {"started": self.s["turn"]})
        self.s["quests"][qid].update(status="done", stage="done")
        self.emit("quest", f"Quest complete: {q['name']}", tone="done", quest=qid)
        rw = q.get("rewards", {})
        if rw.get("gold"):
            self._eff_gold(rw["gold"])
        for iid in rw.get("items", []):
            self.give(iid)
        if rw.get("affection"):
            self._eff_affection(rw["affection"])
        if rw.get("reputation"):
            self._eff_reputation(rw["reputation"])
        if rw.get("xp"):
            self.gain_xp(int(rw["xp"]))
        for cid in self.party():
            self.remember(cid, f"we finished '{q['name']}' together")

    def update_quests(self) -> None:
        for _ in range(12):
            moved = False
            for qid, qs in list(self.s["quests"].items()):
                if qs.get("status") != "active":
                    continue
                q = self.quest(qid)
                if not q:
                    continue
                if q.get("fail_when") and self.cond(q["fail_when"]):
                    self._eff_fail_quest(qid)
                    moved = True
                    continue
                stage = self.stage_def(qid)
                if not stage or not stage.get("complete_when"):
                    continue
                if not self.cond(stage["complete_when"]):
                    continue
                self.apply(stage.get("on_complete"))
                nxt = stage.get("next", "done")
                if nxt == "done":
                    self.complete_quest(qid)
                elif nxt == "fail":
                    self._eff_fail_quest(qid)
                else:
                    qs["stage"] = nxt
                    self.announce_stage(qid)
                moved = True
            if not moved:
                return

    # scenes -------------------------------------------------------------------
    def scene_def(self) -> dict | None:
        sc = self.s["scene"]
        if not sc:
            return None
        return sc.get("inline") or self.world.get("scenes", sc["id"])

    def start_scene(self, sid: str | None = None, inline: dict | None = None) -> None:
        scene = inline or self.world.get("scenes", sid or "")
        if scene.get("once") and sid and self.done_once("scene:" + sid):
            return
        self.s["scene"] = {"id": sid, "inline": inline, "node": "start"}
        if scene.get("title"):
            self.emit("scene_title", scene["title"])
        self.enter_node("start")

    def enter_node(self, nid: str) -> None:
        scene = self.scene_def()
        if scene is None:
            return
        if nid == "end":
            self.end_scene()
            return
        node = scene["nodes"][nid]
        self.s["scene"]["node"] = nid
        speaker = node.get("speaker")
        self.emit(
            "scene",
            node.get("text", ""),
            speaker=speaker,
            name=self.person_name(speaker) if speaker else "",
        )
        if speaker and speaker not in self.s["met"]:
            self.s["met"].append(speaker)
        self.apply(node.get("effects"))
        if self.pending_combat or self.s["ending"]:
            self.end_scene()
            return
        if not node.get("choices") and not node.get("next"):
            self.end_scene()

    def scene_choices(self) -> list[tuple[int, dict]]:
        """The choices on offer now, with their index in the node's list."""
        scene = self.scene_def()
        if not scene:
            return []
        node = scene["nodes"][self.s["scene"]["node"]]
        if not node.get("choices"):
            return [(0, {"text": "Continue", "next": node.get("next", "end")})]
        return [
            (i, ch) for i, ch in enumerate(node["choices"]) if self.cond(ch.get("when"))
        ]

    def choose(self, index: int) -> None:
        offered = dict(self.scene_choices())
        if index not in offered:
            raise GameError("that choice is not on offer")
        ch = offered[index]
        self.emit("player", ch["text"])
        nxt = ch.get("next", "end")
        if ch.get("check"):
            if self.check(ch["check"]):
                self.apply(ch.get("effects"))
            else:
                self.apply(ch.get("fail_effects"))
                nxt = ch.get("fail_next", nxt)
        else:
            self.apply(ch.get("effects"))
        if self.pending_combat or self.s["ending"]:
            self.end_scene()
            return
        self.enter_node(nxt)

    def end_scene(self) -> None:
        sc = self.s["scene"]
        if sc and sc.get("id"):
            self.mark_once("scene:" + sc["id"])
        self.s["scene"] = None
