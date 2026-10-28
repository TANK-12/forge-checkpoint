"""The game: every player action, and what the world does after it.

`Game.act(action)` is the only way state changes. An action is a small dict
(`{"do": "go", "to": "brightwater_docks"}`); free text goes through
parser.py first and comes back as one of these. What happened is returned as
log entries. Entries that Jan may retell carry a `jan` job (see narrator.py);
their `text` is the hand-written fallback and is already final without Jan.
"""

from __future__ import annotations

import random
import re

from . import generator
from . import rules as R
from .combat import Combat
from .core import GameError, new_state
from .dice import roll
from .vocab import ROMANCE_ORDER
from .world import World

PARTY_MAX = 3
COMBAT_DOS = ("attack", "ability", "item", "defend", "flee")
FREE_DOS = ("look", "help", "inventory")
WARM_TONES = ("kind", "flirt", "joke", "brave")
NEGATIONS = ("not", "no", "never", "dont", "nor")
TEXT_KEYS = (
    "do",
    "text",
    "to",
    "topic",
    "id",
    "item",
    "kind",
    "skill",
    "ability",
    "target",
    "feature",
)


def start_game(
    world: World, spec: dict, rolled: list[int] | None = None, seed=None
) -> "Game":
    """A new game from the character creation form."""
    pc = R.new_character(world, spec, rolled)
    game = Game(world, new_state(world, pc), random.Random(seed))
    game.begin()
    return game


class Game(Combat):
    def begin(self) -> None:
        s, start = self.s, self.world.campaign.get("start", {})
        cls = self.rules["_classes"][self.pc["class"]]
        bg = self.rules["_backgrounds"][self.pc["background"]]
        for iid in (
            cls.get("start_items", []) + bg.get("items", []) + start.get("items", [])
        ):
            self.give(iid, quiet=True)
        s["gold"] = (
            int(cls.get("start_gold", 0))
            + int(bg.get("gold", 0))
            + int(start.get("gold", 0))
        )
        for iid in list(s["inventory"]):
            self.auto_equip(iid)
        s["flags"] += [f for f in start.get("flags", []) if f not in s["flags"]]
        self.visit(s["location"])
        for loc in start.get("reveal", []):
            if loc not in s["known"]:
                s["known"].append(loc)
        self.emit(
            "intro",
            self.world.campaign.get("intro", ""),
            title=self.world.campaign.get("name", ""),
        )
        for qid in start.get("quests", []):
            self.start_quest(qid)
        self.describe(jan=True)
        self.after()

    # the one entry point ----------------------------------------------------
    def act(self, action: dict) -> list[dict]:
        self.out = []
        self.trigger = "any"
        if not isinstance(action, dict):
            raise GameError("an action must be an object")
        for key in TEXT_KEYS:
            if key in action and not isinstance(action[key], (str, type(None))):
                raise GameError(f"{key} must be text")
        if self.s["ending"]:
            raise GameError("this story has ended; start a new one")
        do = str(action.get("do", ""))
        if do == "text":
            from .parser import parse

            text = str(action.get("text", "")).strip()[:500]
            if not text:
                raise GameError("type what you do")
            action = parse(self, text)
            do = action["do"]
        self.s["turn"] += 1
        if self.s["scene"] and do != "choose" and do not in FREE_DOS:
            raise GameError("finish the scene first: pick one of the choices")
        if self.s["combat"] and do in FREE_DOS:
            getattr(self, "do_" + do)(action)
            return self.out
        if self.s["combat"] and do not in COMBAT_DOS:
            raise GameError(
                "you are in a fight: attack, use an ability or item, defend or flee"
            )
        if self.s["combat"]:
            self.combat_action(action)
            self.narrate_round()
        else:
            handler = getattr(self, "do_" + do, None)
            if handler is None:
                raise GameError(f"there is no action called {do!r}")
            handler(action)
            if do not in ("look", "choose", "equip", "raise", "help", "inventory"):
                self.pass_time(self.rules["time"].get("hours_per_action", 0.25))
        self.after()
        return self.out

    # after every action -----------------------------------------------------
    def after(self) -> None:
        for _ in range(6):
            self.reactions()
            self.update_quests()
            if self.s["ending"]:
                return
            if self.pending_combat and not self.s["scene"]:
                ids, self.pending_combat = self.pending_combat, None
                self.start_combat(ids)
                return
            if self.s["combat"] or self.s["scene"]:
                return
            self.arc_triggers()
            if not self.s["scene_queue"]:
                return
            sid = self.s["scene_queue"].pop(0)
            if not self.done_once("scene:" + sid) or not self.world.get(
                "scenes", sid
            ).get("once"):
                self.start_scene(sid)

    def reactions(self) -> None:
        for cid in self.party():
            c = self.comp(cid)
            for i, r in enumerate(
                self.world.get("companions", cid).get("reactions", [])
            ):
                key = r.get("flag") or f"r{i}"
                if key in c["seen_reactions"] or not self.flag(r.get("flag", "")):
                    continue
                if r.get("when") and not self.cond(r["when"]):
                    continue
                c["seen_reactions"].append(key)
                if r.get("text"):
                    self.emit(
                        "speech", r["text"], speaker=cid, name=self.person_name(cid)
                    )
                self.add_affection(cid, int(r.get("amount", 0)), r.get("memory", ""))

    def arc_triggers(self) -> None:
        """Offer the next romance scene once its requirements hold. A stage
        counts as done only when the romance actually reaches it; a scene
        that ends without it (and without a decline) comes back after
        `arc_retry_days`, at most `arc_offers` times in all."""
        rel = self.rules["relationships"]
        retry = float(rel.get("arc_retry_days", 2))
        # a scene can come back once (or arc_offers times), never forever
        max_offers = int(rel.get("arc_offers", 2))
        for cid in self.party():
            c = self.comp(cid)
            comp = self.world.get("companions", cid)
            if self.flag(f"{cid}_romance_declined") or not comp.get(
                "romanceable", True
            ):
                continue
            if self.s["partner"] not in ("none", cid):
                continue
            offered = c.setdefault("arc_offered", {})
            for step in comp.get("arc", []):
                if step["stage"] in c["arc_done"]:
                    continue
                if ROMANCE_ORDER.index(c["romance"]) >= ROMANCE_ORDER.index(
                    step["stage"]
                ):
                    c["arc_done"].append(step["stage"])
                    continue
                if step["scene"] in self.s["scene_queue"]:
                    break
                last = offered.get(step["stage"])
                tries = c.setdefault("arc_tries", {})
                if last is not None and (
                    self.s["day"] - last < retry
                    or tries.get(step["stage"], 0) >= max_offers
                ):
                    break
                trig = step.get("trigger", "any")
                if trig != "any" and trig != self.trigger:
                    break
                if self.cond(step.get("requires")):
                    offered[step["stage"]] = self.s["day"]
                    tries[step["stage"]] = tries.get(step["stage"], 0) + 1
                    if "scene:" + step["scene"] in self.s["done"]:
                        self.s["done"].remove("scene:" + step["scene"])
                    self.s["scene_queue"].append(step["scene"])
                break

    # Jan jobs -----------------------------------------------------------------
    def prose(self, text: str, facts: list[str], kind: str = "prose", **extra) -> dict:
        """A narration entry: `text` now, Jan's retelling of `facts` later."""
        return self.emit(kind, text, jan={"role": "narration", "facts": facts}, **extra)

    def narrate_round(self) -> None:
        cb = self.s["combat"]
        facts = list(cb["facts"]) if cb else []
        last = [e for e in self.out if e["kind"] == "combat_end"]
        if last and not facts:
            facts = ["The fight ends: " + last[-1]["text"]]
        if facts:
            self.emit(
                "prose",
                "",
                jan={"role": "narration", "facts": facts, "short": True},
                quiet=True,
            )

    # where you are --------------------------------------------------------------
    def describe(self, jan: bool = False) -> None:
        loc = self.location()
        facts = [
            f"Place: {loc['name']}. {loc.get('description', '')}",
            f"Time: {self.period()}.",
        ]
        here = [self.person_name(p) for p in self.people_here()]
        if here:
            facts.append("People here: " + ", ".join(here) + ".")
        self.emit(
            "place",
            loc.get("description", ""),
            title=loc["name"],
            loc=loc["id"],
            jan=(
                {"role": "narration", "facts": facts, "describe": True} if jan else None
            ),
        )

    def do_look(self, a: dict) -> None:
        self.describe(jan=True)

    def people_here(self) -> list[str]:
        here = []
        loc = self.s["location"]
        for nid, npc in self.world.data["npcs"].items():
            if self.npc_location(npc) == loc:
                here.append(nid)
        for cid in self.world.data["companions"]:
            c = self.comp(cid)
            if c["in_party"] or self.companion_location(cid) == loc:
                here.append(cid)
        return here

    def npc_location(self, npc: dict) -> str | None:
        where = npc.get("location")
        if isinstance(where, list):
            for w in where:
                if self.cond(w.get("when")):
                    return w["location"]
            return None
        if npc.get("gone_when") and self.cond(npc["gone_when"]):
            return None
        return where

    def companion_location(self, cid: str) -> str | None:
        c = self.comp(cid)
        if c["in_party"]:
            return self.s["location"]
        return c.get("at") or self.npc_location(self.world.get("companions", cid))

    def exits(self) -> list[dict]:
        """Exits on offer here: each with `open` and, if shut, `locked` text."""
        shown = []
        for ex in self.location().get("exits", []):
            ok = self.cond(ex.get("when"))
            if not ok and not ex.get("locked"):
                continue
            shown.append({**ex, "open": ok})
        return shown

    def do_go(self, a: dict) -> None:
        to = a.get("to", "")
        ex = next((e for e in self.exits() if e["to"] == to), None)
        if ex is None:
            raise GameError("you cannot get there from here")
        if not ex["open"]:
            raise GameError(ex.get("locked") or "that way is shut for now")
        if ex.get("check") and not self.check(ex["check"], "Getting there"):
            self.apply(ex.get("fail"))
            self.emit(
                "message", ex.get("fail_text", "You do not make it through this time.")
            )
            return
        self.pass_time(float(ex.get("hours", 0.25)))
        here = self.s["location"]
        self.s["prev_location"] = here
        self.s["location"] = to
        first = to not in self.s["visited"]
        self.visit(to)
        self.trigger = "travel"
        long_trip = float(ex.get("hours", 0.25)) >= 2
        if long_trip:
            region = self.world.data["regions"].get(self.region_id(), {})
            if region.get("travel_text"):
                self.emit("message", region["travel_text"])
            self.banter()
        self.describe(jan=first or long_trip)
        self.on_enter()
        if not self.s["scene_queue"] and not self.pending_combat:
            self.roll_encounter(long_trip)

    def banter(self) -> None:
        party = self.party()
        if not party or self.rng.random() > 0.5:
            return
        cid = self.rng.choice(party)
        lines = self.world.get("companions", cid).get("lines", {}).get("banter", [])
        if lines:
            self.speech(
                cid,
                self.rng.choice(lines),
                prompt="A remark on the road while travelling.",
            )

    def on_enter(self) -> None:
        loc = self.location()
        for i, oe in enumerate(loc.get("on_enter", [])):
            key = f"enter:{loc['id']}:{i}"
            if oe.get("once") and self.done_once(key):
                continue
            if not self.cond(oe.get("when")):
                continue
            self.mark_once(key)
            self.apply(oe.get("effects"))
            if oe.get("scene"):
                self.s["scene_queue"].append(oe["scene"])

    def roll_encounter(self, long_trip: bool) -> None:
        loc = self.location()
        enc = loc.get("encounter") or {}
        if enc.get("monsters") and self.rng.random() < float(enc.get("chance", 0)):
            self.ambush(self.rng.choice(enc["monsters"]))
            return
        if long_trip and "wild" in loc.get("tags", []):
            wilds = (
                self.world.data["regions"].get(self.region_id(), {}).get("wilds", {})
            )
            if self.rng.random() < float(wilds.get("encounter_chance", 0)) * 0.6:
                group = self.pick_encounter(wilds)
                if group:
                    self.ambush(group)

    def pick_encounter(self, wilds: dict) -> list[str] | None:
        lvl = self.pc["level"]
        groups = [
            g
            for g in wilds.get("encounters", [])
            if g.get("min_level", 1) <= lvl <= g.get("max_level", 99)
            and self.cond(g.get("when"))
        ]
        if not groups:
            return None
        g = self.rng.choices(groups, weights=[x.get("weight", 1) for x in groups])[0]
        return list(g["monsters"])

    def ambush(self, monsters: list[str]) -> None:
        names = ", ".join(self.world.get("monsters", m)["name"] for m in monsters)
        self.prose(
            f"Trouble finds you: {names}.",
            [f"Hostile creatures appear and attack: {names}."],
        )
        self.pending_combat = list(monsters)

    # looking closer -----------------------------------------------------------
    def features(self) -> list[dict]:
        loc = self.location()
        shown = []
        for f in loc.get("features", []):
            key = f"{loc['id']}:{f['id']}"
            if f.get("hidden") and key not in self.s.setdefault("revealed", []):
                continue
            if not self.cond(f.get("when")):
                continue
            used = f.get("once") and self.done_once("feature:" + key)
            shown.append({**f, "used": bool(used)})
        return shown

    def do_examine(self, a: dict) -> None:
        fid = a.get("feature", "")
        f = next((x for x in self.features() if x["id"] == fid), None)
        if f is None:
            raise GameError("there is nothing like that to examine here")
        key = f"{self.s['location']}:{fid}"
        if f["used"]:
            self.emit("message", f"You have already been over {f['name']}.")
            return
        self.prose(
            f.get("text", ""),
            [f"The player examines {f['name']}: {f.get('text', '')}"],
            title=f["name"],
        )
        if f.get("check"):
            ok = self.check(f["check"], f["name"])
            self.apply(f.get("success") if ok else f.get("fail"))
            if ok and f.get("success_text"):
                self.emit("message", f["success_text"])
            if not ok and f.get("fail_text"):
                self.emit("message", f["fail_text"])
            if ok or f.get("once_even_on_fail"):
                if f.get("once"):
                    self.mark_once("feature:" + key)
        else:
            self.apply(f.get("success"))
            if f.get("once"):
                self.mark_once("feature:" + key)
        self.reveal_hidden_near()

    def reveal_hidden_near(self) -> None:
        loc = self.location()
        revealed = self.s.setdefault("revealed", [])
        for f in loc.get("features", []):
            key = f"{loc['id']}:{f['id']}"
            if f.get("hidden") and key not in revealed and self.cond(f.get("when")):
                revealed.append(key)
                self.chip(f"You notice {f['name']}", "info")

    # people -------------------------------------------------------------------
    def present(self, pid: str) -> dict:
        person = self.world.person(pid)
        if person is None:
            raise GameError("nobody by that name")
        if pid not in self.people_here():
            raise GameError(f"{self.person_name(pid)} is not here")
        return person

    def do_talk(self, a: dict) -> None:
        pid = a.get("to", "")
        person = self.present(pid)
        first = pid not in self.s["met"]
        if first:
            self.s["met"].append(pid)
        self.trigger = "talk"
        is_comp = pid in self.world.data["companions"]
        if is_comp and not first:
            lines = person.get("lines", {}).get("greet") or [person.get("greeting", "")]
            line = self.rng.choice(lines)
        else:
            line = person.get("greeting", "")
        self.s["talking_to"] = pid
        self.speech(
            pid,
            line,
            prompt="The player comes over to talk. Greet them in your own way.",
        )
        self.offer_topics(pid)

    def offer_topics(self, pid: str) -> None:
        topics = self.topics(pid)
        if topics:
            self.emit("topics", "", to=pid, name=self.person_name(pid), topics=topics)

    def topics(self, pid: str) -> list[dict]:
        person = self.world.person(pid) or {}
        out = []
        for t in person.get("topics", []):
            if t.get("once") and self.done_once(f"topic:{pid}:{t['id']}"):
                continue
            if self.cond(t.get("when")):
                out.append(
                    {"id": t["id"], "prompt": t["prompt"], "check": t.get("check")}
                )
        for qid in person.get("quests", []):
            q = self.world.data["quests"].get(qid)
            if q and self.qstatus(qid) == "none" and self.cond(q.get("requires")):
                out.append(
                    {"id": "quest:" + qid, "prompt": f"Ask about work: {q['name']}"}
                )
        if person.get("rumours") and generator.templates(self):
            out.append({"id": "rumour", "prompt": "Any rumours?"})
        return out

    def do_topic(self, a: dict) -> None:
        pid, tid = a.get("to", ""), a.get("topic", "")
        person = self.present(pid)
        if tid not in [t["id"] for t in self.topics(pid)]:
            raise GameError("that is not something to ask them about right now")
        if pid not in self.s["met"]:
            self.s["met"].append(pid)
        self.trigger = "talk"
        self.s["talking_to"] = pid
        if tid.startswith("quest:"):
            qid = tid[6:]
            q = self.world.get("quests", qid)
            self.emit("player", f"Ask about work: {q['name']}")
            self.speech(
                pid,
                q.get("offer") or q.get("summary", ""),
                prompt=f"You offer the player this job: {q.get('summary', '')}",
            )
            self.start_quest(qid)
            return
        if tid == "rumour":
            self.emit("player", "Any rumours?")
            self.speech(
                pid,
                generator.rumour(self),
                prompt="Share a local rumour in a sentence or two.",
            )
            return
        t = next(x for x in person["topics"] if x["id"] == tid)
        self.emit("player", t["prompt"])
        if t.get("once"):
            self.mark_once(f"topic:{pid}:{tid}")
        if t.get("check") and not self.check(t["check"], t["prompt"]):
            self.speech(pid, t.get("fail_text") or "They will not say more.", jan=False)
            self.apply(t.get("fail_effects"))
            return
        self.speech(pid, t.get("text", ""), jan=False)
        self.apply(t.get("effects"))
        self.offer_topics(pid)

    def speech(
        self, pid: str, text: str, prompt: str = "", jan: bool = True, said: str = ""
    ) -> dict:
        """A line spoken by an NPC or companion. With `jan`, the dialogue
        model may say it its own way; `text` is what they say without Jan."""
        job = (
            {"role": "dialogue", "speaker": pid, "prompt": prompt, "said": said}
            if jan
            else None
        )
        return self.emit(
            "speech", text, speaker=pid, name=self.person_name(pid), jan=job
        )

    def do_say(self, a: dict) -> None:
        text = str(a.get("text", "")).strip()[:400]
        if not text:
            raise GameError("say something")
        here = self.people_here()
        pid = a.get("to") or self.listener(here)
        if pid and pid not in here and self.world.person(pid) is not None:
            raise GameError(f"{self.person_name(pid)} is not here")
        self.emit("player", f"“{text}”", said=True)
        if not pid or pid not in here:
            self.prose(
                "Your words hang in the air; nobody here answers.",
                [f"The player says aloud: {text}. Nobody is near enough to answer."],
            )
            return
        if pid not in self.s["met"]:
            self.s["met"].append(pid)
        self.trigger = "talk"
        if pid in self.world.data["companions"]:
            self.companion_reply(pid, text)
        else:
            person = self.world.person(pid) or {}
            self.speech(
                pid,
                person.get(
                    "idle",
                    f"{person.get('name', 'They')} hears you out and nods slowly.",
                ),
                said=text,
            )

    def listener(self, here: list[str]) -> str:
        """Who hears a line said to nobody in particular: whoever you last
        spoke with if they are still here, else a companion, else anyone."""
        last = self.s.get("talking_to")
        if last in here:
            return last
        comps = [p for p in here if p in self.world.data["companions"]]
        if comps:
            return comps[0]
        return here[0] if here else ""

    def companion_reply(self, cid: str, text: str) -> None:
        comp = self.world.get("companions", cid)
        c = self.comp(cid)
        tone = self.tone_of(text)
        lines = comp.get("lines", {})
        key = tone or "neutral"
        mood = ""
        if tone:
            amount = self.tone_amount(cid, tone)
            cool = int(self.rules["relationships"].get("tone_cooldown_turns", 4))
            # one warm mood change per companion per cooldown, whatever the
            # tone, so cycling compliments and jokes cannot farm affection;
            # rudeness always counts
            last = max(c["tone_turns"].values(), default=-99)
            if amount < 0 or (amount and self.s["turn"] - last >= cool):
                c["tone_turns"][tone] = self.s["turn"]
                self.add_affection(
                    cid,
                    amount,
                    f"you were {tone} with me" if amount > 0 else f"you were {tone}",
                )
            if tone == "flirt":
                key = "flirt_yes" if amount > 0 else "flirt_no"
            mood = {
                "flirt_yes": "They are flirting with you and you welcome it.",
                "flirt_no": "They are flirting with you and you are not ready for that; turn it aside.",
                "kind": "They are being kind to you.",
                "rude": "They are being rude to you and it stings.",
                "joke": "They are joking with you.",
                "curious": "They are asking about you.",
                "brave": "They are spoiling for a fight.",
                "cautious": "They are urging caution.",
            }.get(key, "")
        options = (
            lines.get(key) or lines.get("neutral") or [comp.get("greeting", "...")]
        )
        c["history"].append({"who": "player", "text": text})
        reply = self.rng.choice(options) if isinstance(options, list) else str(options)
        entry = self.speech(cid, reply, prompt=mood, said=text)
        entry["tone"] = tone
        c["history"].append({"who": cid, "text": reply, "entry": entry["id"]})
        del c["history"][:-12]

    def tone_of(self, text: str) -> str:
        """The one tone a line clearly carries, or "" when none or a tie.
        A warm word right after a negation ("not sorry") does not count."""
        low = " " + re.sub(r"[^a-z' ]+", " ", text.lower()) + " "
        counts: dict[str, int] = {}
        for tone, words in self.rules.get("tones", {}).items():
            n = 0
            for w in words:
                for m in re.finditer(
                    r"(?<![a-z'])" + re.escape(w) + r"(?![a-z'])", low
                ):
                    before = low[: m.start()].split()[-2:]
                    if tone in WARM_TONES and any(
                        b in NEGATIONS or b.endswith("n't") for b in before
                    ):
                        continue
                    n += 1
            if n:
                counts[tone] = n
        if not counts:
            return ""
        top = max(counts.values())
        best = [t for t, n in counts.items() if n == top]
        return best[0] if len(best) == 1 else ""

    def tone_amount(self, cid: str, tone: str) -> int:
        spec = self.world.get("companions", cid).get("tones", {}).get(tone, 0)
        if isinstance(spec, dict):
            if self.comp(cid)["affection"] >= int(spec.get("min_affection", -100)):
                return int(spec.get("amount", 0))
            return int(spec.get("below", 0))
        return int(spec)

    def do_recruit(self, a: dict) -> None:
        cid = a.get("to", "")
        if cid not in self.world.data["companions"]:
            raise GameError("only companions can join you")
        comp = self.present(cid)
        c = self.comp(cid)
        if c["in_party"]:
            raise GameError(f"{comp['name']} is already with you")
        if len(self.party()) >= PARTY_MAX:
            raise GameError(
                f"your party is full ({PARTY_MAX}); part ways with someone first"
            )
        rec = comp.get("recruit", {})
        if not self.cond(rec.get("when")):
            self.speech(
                cid,
                rec.get(
                    "refuse", f"{comp['name'].split()[0]} shakes their head. 'Not yet.'"
                ),
                prompt="The player asks you to join them. You are not ready to; say so.",
            )
            return
        if c["affection"] < int(rec.get("min_affection", -30)):
            self.speech(
                cid,
                "'After the way you've treated me? No.'",
                prompt="The player asks you to join them, but they have treated you badly. Refuse.",
            )
            return
        if rec.get("scene") and not self.done_once("scene:" + rec["scene"]):
            self.s["scene_queue"].append(rec["scene"])
            return
        self.speech(cid, rec.get("text", ""), jan=False)
        self._eff_join(cid)
        c.pop("at", None)

    def do_dismiss(self, a: dict) -> None:
        cid = a.get("to", "")
        if cid not in self.party():
            raise GameError("they are not travelling with you")
        lines = self.world.get("companions", cid).get("lines", {})
        self.speech(cid, lines.get("leave", "'I'll wait here, then.'"), jan=False)
        self.comp(cid)["in_party"] = False
        self.comp(cid)["at"] = self.s["location"]
        self.chip(f"{self.person_name(cid)} stays at {self.location()['name']}", "info")

    def do_give(self, a: dict) -> None:
        pid, iid = a.get("to", ""), a.get("item", "")
        person = self.present(pid)
        if self.s["inventory"].get(iid, 0) <= 0:
            raise GameError("you do not have that")
        item = self.world.item(iid)
        if item.get("unsellable") or item.get("kind") == "key":
            raise GameError(f"you need to keep {item['name']}")
        for qid, qs in self.s["quests"].items():
            q = self.quest(qid) or {}
            need = dict((self.stage_def(qid) or {}).get("complete_when") or {})
            need.pop("location", None)
            if (
                qs.get("status") == "active"
                and q.get("fetch") == iid
                and q.get("giver") == pid
                and self.cond(need)
            ):
                self.take(iid)
                self.emit("player", f"You hand {item['name']} to {person['name']}.")
                self.complete_quest(qid)
                return
        if pid not in self.world.data["companions"]:
            gifts = person.get("gifts", {})
            if iid not in gifts:
                raise GameError(f"{person['name']} has no use for that")
            self.take(iid)
            self.emit("player", f"You give {item['name']} to {person['name']}.")
            self.apply(gifts[iid] if isinstance(gifts[iid], list) else [])
            return
        c = self.comp(pid)
        gifts = person.get("gifts", {})
        cool = int(self.rules["relationships"].get("gift_cooldown_turns", 6))
        self.take(iid)
        self.emit("player", f"You give {item['name']} to {person['name']}.")
        amount = int(gifts.get(iid, gifts.get("default", 1)))
        if self.s["turn"] - c["gift_turn"] < cool:
            amount = min(amount, 1)
        c["gift_turn"] = self.s["turn"]
        self.add_affection(pid, amount, f"you gave me {item['name']}")
        lines = person.get("lines", {})
        key = "gift_love" if amount >= 4 else "gift_dislike" if amount < 0 else "gift"
        options = lines.get(key) or lines.get("kind") or ["'Thank you.'"]
        feel = (
            "you love it"
            if amount >= 4
            else "you dislike it" if amount < 0 else "it is a nice thought"
        )
        self.speech(
            pid,
            self.rng.choice(options),
            prompt=f"The player gives you {item['name']}; {feel}.",
        )

    # scenes -------------------------------------------------------------------
    def do_choose(self, a: dict) -> None:
        if not self.s["scene"]:
            raise GameError("there is nothing to choose right now")
        try:
            index = int(a.get("index", -1))
        except (TypeError, ValueError):
            raise GameError("pick a choice by its number") from None
        self.choose(index)

    # things you carry -----------------------------------------------------------
    def auto_equip(self, iid: str) -> None:
        item = self.world.item(iid)
        slot = {"weapon": "weapon", "armor": "armor", "shield": "shield"}.get(
            item.get("kind", "")
        )
        if slot and not self.pc["equipped"].get(slot):
            self.pc["equipped"][slot] = iid

    def do_equip(self, a: dict) -> None:
        iid = a.get("item", "")
        if self.s["inventory"].get(iid, 0) <= 0:
            raise GameError("you do not have that")
        item = self.world.item(iid)
        slot = {"weapon": "weapon", "armor": "armor", "shield": "shield"}.get(
            item.get("kind", "")
        )
        if not slot:
            raise GameError(f"you cannot equip {item['name']}")
        eq = self.pc["equipped"]
        if eq.get(slot) == iid:
            eq[slot] = None
            self.emit("system", f"You put away {item['name']}.")
            return
        eq[slot] = iid
        self.emit("system", f"You equip {item['name']}.")

    def do_use(self, a: dict) -> None:
        iid = a.get("item", "")
        if self.s["inventory"].get(iid, 0) <= 0:
            raise GameError("you do not have that")
        item = self.world.item(iid)
        if item.get("kind") != "consumable":
            raise GameError(f"{item['name']} is not something you can use like that")
        self.take(iid, quiet=True)
        self.emit("system", f"You use {item['name']}.")
        self.apply(item.get("use"))

    def do_ability(self, a: dict) -> None:
        self.use_ability(a.get("id", ""), None, in_combat=False)

    def do_raise(self, a: dict) -> None:
        R.raise_ability(self.rules, self.pc, a.get("ability", ""))
        name = next(
            x["name"] for x in self.rules["abilities"] if x["id"] == a["ability"]
        )
        self.emit("level", f"{name} rises to {self.pc['abilities'][a['ability']]}.")

    # shops --------------------------------------------------------------------
    def shop(self) -> dict | None:
        sh = self.location().get("shop")
        if sh and self.cond(sh.get("when")):
            return sh
        return None

    def price(self, iid: str, selling: bool = False) -> int:
        value = int(self.world.item(iid).get("value", 1))
        if selling:
            return max(1, value // 2)
        return max(1, value)

    def do_buy(self, a: dict) -> None:
        sh = self.shop()
        iid = a.get("item", "")
        if not sh or iid not in sh.get("items", []):
            raise GameError("that is not for sale here")
        cost = self.price(iid)
        if self.s["gold"] < cost:
            raise GameError(
                f"that costs {cost} {self.label('gold', 'gold')} and you have {self.s['gold']}"
            )
        self._eff_gold(-cost)
        self.give(iid)
        self.auto_equip(iid)

    def do_sell(self, a: dict) -> None:
        sh = self.shop()
        iid = a.get("item", "")
        if not sh or not sh.get("buys", True):
            raise GameError("nobody here is buying")
        if self.s["inventory"].get(iid, 0) <= 0:
            raise GameError("you do not have that")
        item = self.world.item(iid)
        if item.get("unsellable") or item.get("kind") == "key":
            raise GameError(f"you should keep {item['name']}")
        self.take(iid)
        self._eff_gold(self.price(iid, selling=True))

    # resting ------------------------------------------------------------------
    def can_sleep(self) -> tuple[bool, str]:
        tags = self.location().get("tags", [])
        if "safe" in tags:
            return True, ""
        if "wild" in tags:
            return True, "camp"
        return False, "this is no place to sleep; find an inn, a temple or open country"

    def do_rest(self, a: dict) -> None:
        kind = a.get("kind") or "short"
        if kind not in ("short", "long"):
            raise GameError("rest is short or long")
        spec = self.rules["rest"][kind]
        limit = self.rules["rest"].get("short_per_long")
        if kind == "short" and limit is not None:
            if self.s.get("short_rests", 0) >= int(limit):
                raise GameError(
                    f"you have caught your breath {limit} times already; you need a proper sleep"
                )
        if kind == "long":
            ok, how = self.can_sleep()
            if not ok:
                raise GameError(how)
            cost = int(self.location().get("rest_cost", 0))
            if cost:
                if self.s["gold"] < cost:
                    raise GameError(
                        f"a bed here costs {cost} {self.label('gold', 'gold')}"
                    )
                self._eff_gold(-cost)
            if how == "camp":
                wilds = (
                    self.world.data["regions"]
                    .get(self.region_id(), {})
                    .get("wilds", {})
                )
                if self.rng.random() < float(wilds.get("encounter_chance", 0)) * 0.5:
                    group = self.pick_encounter(wilds)
                    if group:
                        self.pass_time(2)
                        self.ambush(group)
                        return
        self.pass_time(float(spec.get("hours", 1)))
        self.s["short_rests"] = (
            0 if kind == "long" else self.s.get("short_rests", 0) + 1
        )
        if spec.get("heal") == "all":
            self.heal(self.pc["max_hp"])
        else:
            self.heal(R.hit_die_heal(self.world, self.pc, self.rng))
        for cid in self.party():
            c = self.comp(cid)
            c["hp"] = (
                c["max_hp"]
                if kind == "long"
                else min(c["max_hp"], c["hp"] + c["max_hp"] // 2)
            )
        for ab in R.class_abilities(self.world, self.pc):
            if ab.get("uses") and (
                spec.get("restores") == "all" or ab.get("per") == "short"
            ):
                self.pc["uses"][ab["id"]] = ab["uses"]
        self.trigger = "rest"
        label = self.label("rest_long" if kind == "long" else "rest_short", kind)
        facts = [
            f"The party rests ({label}) at {self.location()['name']}, {self.period()}."
        ]
        if self.party():
            facts.append(
                "With you: "
                + ", ".join(self.person_name(c) for c in self.party())
                + "."
            )
        fallback = (
            "You sleep, and wake rested."
            if kind == "long"
            else "You take an hour to catch your breath."
        )
        self.prose(fallback, facts)

    # the open world -------------------------------------------------------------
    def do_explore(self, a: dict) -> None:
        loc = self.location()
        if "wild" not in loc.get("tags", []):
            raise GameError("there is no open country to explore here")
        region = self.world.data["regions"].get(self.region_id(), {})
        wilds = region.get("wilds", {})
        self.pass_time(1)
        self.trigger = "travel"
        r = self.rng.random()
        chance = float(wilds.get("encounter_chance", 0.25))
        if r < chance:
            group = self.pick_encounter(wilds)
            if group:
                self.ambush(group)
                return
        events = [
            e
            for e in wilds.get("events", [])
            if self.cond(e.get("when"))
            and not (e.get("once", True) and self.done_once("event:" + e["id"]))
        ]
        if events and self.rng.random() < 0.55:
            ev = self.rng.choices(events, weights=[e.get("weight", 1) for e in events])[
                0
            ]
            self.mark_once("event:" + ev["id"])
            self.prose(
                ev.get("text", ""),
                [f"While exploring {loc['name']}: {ev.get('text', '')}"],
                title=ev.get("title", ""),
            )
            if ev.get("check"):
                ok = self.check(ev["check"], ev.get("title", "Event"))
                self.apply(ev.get("success") if ok else ev.get("fail"))
                done_text = ev.get("success_text") if ok else ev.get("fail_text")
                if done_text:
                    self.emit("message", done_text)
            else:
                self.apply(ev.get("effects") or ev.get("success"))
            return
        finds = wilds.get("finds", [])
        if finds and self.rng.random() < 0.45:
            iid = self.rng.choice(finds)
            name = self.item_name(iid)
            self.prose(
                f"Off the path you find {name}.",
                [f"While exploring {loc['name']} the player finds {name}."],
            )
            self.give(iid)
            return
        sights = wilds.get("sights", [])
        sight = self.rng.choice(sights) if sights else "The country is quiet."
        self.prose(
            sight,
            [
                f"A quiet hour exploring {loc['name']} in {region.get('name', '')}. Atmosphere: {sight}",
                "Nothing dangerous happens.",
            ],
        )
        if self.rng.random() < 0.3:
            self.banter()

    def do_work(self, a: dict) -> None:
        if "board" not in self.location().get("tags", []):
            raise GameError("there is no notice board or work to be had here")
        offers = generator.offers(self)
        if not offers:
            self.emit("message", "Nothing new is posted today.")
            return
        self.emit("offers", "Work on offer:", offers=offers)

    def do_take_work(self, a: dict) -> None:
        q = generator.take(self, a.get("id", ""))
        self.prose(
            q["summary"],
            [f"The player takes on a job: {q['name']}. {q['summary']}"],
            title=q["name"],
        )

    def do_abandon(self, a: dict) -> None:
        q = generator.abandon(self, a.get("id", ""))
        self.emit("quest", f"Job dropped: {q['name']}", tone="bad", quest=q["id"])

    # anything else --------------------------------------------------------------
    def do_freeform(self, a: dict) -> None:
        text = str(a.get("text", "")).strip()[:300]
        skill = a.get("skill")
        if skill and skill not in self.rules["_skills"]:
            raise GameError(f"there is no skill called {skill!r}")
        loc = self.location()
        self.emit("player", text)
        facts = [f"At {loc['name']}, the player tries: {text}"]
        if skill:
            chk = {
                "skill": skill,
                "dc": self.rules["check_rules"].get("freeform_dc", "medium"),
            }
            ok = self.check(chk, self.rules["_skills"][skill]["name"])
            facts.append(
                "It succeeds."
                if ok
                else "It fails, without lasting harm beyond what the game says."
            )
            key = f"{loc['id']}:{skill}"
            if ok:
                self.reveal_named(text)
                if key not in self.s["freeform_xp"]:
                    self.s["freeform_xp"].append(key)
                    self.gain_xp(int(self.rules["check_rules"].get("freeform_xp", 10)))
            elif self.rules["_skills"][skill].get("risk") and self.rng.random() < 0.5:
                risk = self.rules["_skills"][skill]["risk"]
                self.hurt(max(1, roll(risk, self.rng)["total"]))
                facts.append("The player takes a small knock for it.")
            pool = self.rules.get("freeform_success" if ok else "freeform_fail") or [
                "..."
            ]
            self.prose(self.rng.choice(pool), facts)
            return
        facts.append(
            "No roll was needed. Describe it briefly; nothing is gained or lost."
        )
        self.prose("You do it. Nothing much changes.", facts)

    def reveal_named(self, text: str) -> None:
        low = text.lower()
        loc = self.location()
        revealed = self.s.setdefault("revealed", [])
        for f in loc.get("features", []):
            key = f"{loc['id']}:{f['id']}"
            words = [
                w for w in f["name"].lower().replace("the ", "").split() if len(w) > 3
            ]
            if f.get("hidden") and key not in revealed and any(w in low for w in words):
                revealed.append(key)
                self.chip(f"You find {f['name']}", "good")

    def do_help(self, a: dict) -> None:
        self.emit(
            "system",
            "Type what you do in plain words: go to the docks, talk to Lyra, examine the fountain, "
            "attack, explore, rest, buy a sword, or say something to a companion in quotes. "
            "The buttons on the right do the same things.",
        )

    def do_inventory(self, a: dict) -> None:
        inv = self.s["inventory"]
        if not inv:
            self.emit("system", "You carry nothing but the clothes you stand in.")
            return
        items = ", ".join(
            f"{self.item_name(i)}" + (f" x{n}" if n > 1 else "") for i, n in inv.items()
        )
        self.emit(
            "system",
            f"You carry: {items}. {self.s['gold']} {self.label('gold', 'gold')}.",
        )
