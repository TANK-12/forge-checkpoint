"""Turn-based combat: initiative-free rounds of the player, then companions,
then enemies. Every roll is shown; Jan only narrates the round afterwards."""

from __future__ import annotations

import re

from . import rules as R
from .core import GameCore, GameError
from .dice import d20, roll, signed

DICE_TERM = re.compile(r"(\d*)d(\d+)")


def crit_expr(expr: str) -> str:
    """Double every die in an expression for a critical hit: 1d8+3 -> 2d8+3."""
    return DICE_TERM.sub(
        lambda m: f"{int(m.group(1) or 1) * 2}d{m.group(2)}", str(expr)
    )


class Combat(GameCore):
    # starting and ending ----------------------------------------------------
    def start_combat(self, monster_ids: list[str]) -> None:
        enemies = []
        for n, mid in enumerate(monster_ids):
            m = self.world.get("monsters", mid)
            hp = max(1, roll(m["hp"], self.rng)["total"])
            enemies.append(
                {
                    "uid": f"x{n + 1}",
                    "id": mid,
                    "name": m["name"],
                    "hp": hp,
                    "max_hp": hp,
                    "ac": int(m.get("ac", 10)),
                }
            )
        names = [e["name"] for e in enemies]
        counts: dict[str, int] = {}
        for e in enemies:
            counts[e["name"]] = counts.get(e["name"], 0) + 1
        for e in enemies:
            if counts[e["name"]] > 1:
                idx = sum(
                    1 for x in enemies[: enemies.index(e) + 1] if x["name"] == e["name"]
                )
                e["label"] = f"{e['name']} {idx}"
            else:
                e["label"] = e["name"]
        self.s["combat"] = {
            "enemies": enemies,
            "round": 1,
            "guard": 0,
            "guard_rounds": 0,
            "defending": False,
            "sneak_used": False,
            "facts": [],
        }
        self.s["advantage"] = False
        self.emit("combat_start", "Fight: " + ", ".join(names), enemies=names)
        self.mark_party_for_combat()

    def mark_party_for_combat(self) -> None:
        for cid in self.party():
            c = self.comp(cid)
            if c["hp"] <= 0:
                c["hp"] = 1

    def living(self) -> list[dict]:
        cb = self.s["combat"]
        return [e for e in cb["enemies"] if e["hp"] > 0] if cb else []

    def enemy(self, uid: str | None) -> dict:
        alive = self.living()
        if not alive:
            raise GameError("there is nothing left to fight")
        if not uid:
            return alive[0]
        for e in alive:
            if e["uid"] == uid:
                return e
        raise GameError("that enemy is not standing")

    def fact(self, text: str) -> None:
        if self.s["combat"] is not None:
            self.s["combat"]["facts"].append(text)

    # the player's turn ----------------------------------------------------------
    def combat_action(self, action: dict) -> None:
        cb = self.s["combat"]
        if not cb:
            raise GameError("you are not in a fight")
        cb["facts"] = []
        cb["defending"] = False
        do = action.get("do")
        if do == "attack":
            self.player_attacks(action.get("target"))
        elif do == "ability":
            self.use_ability(action.get("id", ""), action.get("target"))
        elif do in ("item", "use"):
            self.combat_item(action.get("item") or action.get("id") or "")
        elif do == "defend":
            cb["defending"] = True
            self.emit("combat", "You raise your guard.")
            self.fact("The player takes a defensive stance.")
        elif do == "flee":
            if self.try_flee():
                return
        else:
            raise GameError(
                "in a fight you can attack, use an ability or item, defend or flee"
            )
        self.after_player_turn()

    def after_player_turn(self) -> None:
        if self.finish_if_won():
            return
        self.companions_act()
        if self.finish_if_won():
            return
        self.enemies_act()
        cb = self.s["combat"]
        if cb is None:
            return
        if self.pc["hp"] <= 0:
            self.defeat()
            return
        cb["round"] += 1
        cb["sneak_used"] = False
        if cb["guard_rounds"] > 0:
            cb["guard_rounds"] -= 1
            if cb["guard_rounds"] == 0:
                cb["guard"] = 0

    def attacks_per_action(self) -> int:
        n = 1
        for a in R.class_abilities(self.world, self.pc):
            if a.get("kind") == "passive" and a.get("attacks"):
                n = max(n, int(a["attacks"]))
        return n

    def player_attacks(self, target: str | None, times: int | None = None) -> None:
        for _ in range(times or self.attacks_per_action()):
            if not self.living():
                return
            self.weapon_attack(
                self.enemy(target)
                if target and self._alive(target)
                else self.enemy(None)
            )

    def _alive(self, uid: str) -> bool:
        return any(e["uid"] == uid for e in self.living())

    def weapon_attack(self, foe: dict) -> None:
        item = R.weapon(self.world, self.pc)
        bonus = R.attack_bonus(self.world, self.pc)
        ability = R.weapon_ability(self.pc, item)
        dmg_expr = (
            f"{item['damage']}+{R.mods(self.pc)[ability] + int(item.get('bonus', 0))}"
        )
        self.resolve_attack(foe, bonus, dmg_expr, item["name"], weapon_hit=True)

    def resolve_attack(
        self, foe: dict, bonus: int, dmg_expr: str, what: str, weapon_hit: bool = False
    ) -> bool:
        adv = 1 if self.s.get("advantage") else 0
        self.s["advantage"] = False
        r = d20(self.rng, bonus, adv)
        crit = r["natural"] == 20
        hit = crit or (r["natural"] != 1 and r["total"] >= foe["ac"])
        dice = r["dice"]
        shown = (
            f"d20 ({' / '.join(map(str, dice))})"
            if len(dice) > 1
            else f"d20 ({dice[0]})"
        )
        text = f"Attack {foe['label']} with {what}: {shown} {signed(bonus)} = {r['total']} vs AC {foe['ac']}, "
        if not hit:
            self.emit(
                "roll",
                text + "miss",
                success=False,
                natural=r["natural"],
                label="Attack",
            )
            self.fact(f"The player attacks {foe['label']} with {what} and misses.")
            return False
        expr = crit_expr(dmg_expr) if crit else dmg_expr
        dmg = max(1, roll(expr, self.rng, self.names())["total"])
        sneak = self.sneak_bonus() if weapon_hit else ""
        extra = 0
        if sneak:
            extra = roll(crit_expr(sneak) if crit else sneak, self.rng)["total"]
            dmg += extra
        text += ("critical hit" if crit else "hit") + f", {dmg} damage"
        if extra:
            text += f" (sneak attack +{extra})"
        self.emit(
            "roll", text, success=True, natural=r["natural"], label="Attack", crit=crit
        )
        self.fact(
            f"The player {'critically ' if crit else ''}hits {foe['label']} with {what}"
            + (" with a sneak attack" if extra else "")
            + "."
        )
        self.damage_enemy(foe, dmg)
        return True

    def sneak_bonus(self) -> str:
        cb = self.s["combat"]
        if cb is None or cb["sneak_used"]:
            return ""
        for a in R.class_abilities(self.world, self.pc):
            if a.get("kind") == "passive" and a.get("bonus_damage"):
                cb["sneak_used"] = bool(a.get("once_per_round", True))
                return R.scaled(a, self.pc["level"], "bonus_damage")
        return ""

    def damage_enemy(self, foe: dict, dmg: int) -> None:
        foe["hp"] = max(0, foe["hp"] - dmg)
        if foe["hp"] == 0:
            self.emit("combat", f"{foe['label']} falls.", tone="good")
            self.fact(f"{foe['label']} is defeated.")
        else:
            left = foe["hp"] / foe["max_hp"]
            if left < 0.35:
                self.fact(f"{foe['label']} is badly hurt.")

    def ability_def(self, aid: str) -> dict:
        for a in R.class_abilities(self.world, self.pc):
            if a["id"] == aid:
                return a
        raise GameError("you do not have that ability")

    def spend_use(self, ab: dict) -> None:
        if not ab.get("uses"):
            return
        left = self.pc["uses"].get(ab["id"], 0)
        if left <= 0:
            raise GameError(f"{ab['name']} is spent until you rest")
        self.pc["uses"][ab["id"]] = left - 1

    def use_ability(self, aid: str, target: str | None, in_combat: bool = True) -> None:
        ab = self.ability_def(aid)
        kind = ab.get("kind")
        if kind == "passive":
            raise GameError(f"{ab['name']} is always on")
        if in_combat is False and kind in (
            "attack",
            "damage",
            "area",
            "extra_attack",
            "guard",
        ):
            raise GameError(f"{ab['name']} is for a fight")
        self.spend_use(ab)
        self.emit(
            "ability", f"{ab['name']}: {ab.get('text', '')}".strip(), ability=ab["id"]
        )
        self.fact(f"The player uses {ab['name']}.")
        names = self.names()
        if kind == "attack":
            ability = ab.get(
                "ability", self.rules["_classes"][self.pc["class"]]["primary"]
            )
            bonus = R.mods(self.pc)[ability] + R.proficiency(
                self.rules, self.pc["level"]
            )
            foe = self.enemy(target if target and self._alive(target) else None)
            self.resolve_attack(foe, bonus, R.scaled(ab, self.pc["level"]), ab["name"])
        elif kind == "damage":
            foe = self.enemy(target if target and self._alive(target) else None)
            dmg = max(1, roll(R.scaled(ab, self.pc["level"]), self.rng, names)["total"])
            self.emit(
                "roll",
                f"{ab['name']} hits {foe['label']} for {dmg} damage",
                success=True,
                label=ab["name"],
            )
            self.damage_enemy(foe, dmg)
        elif kind == "area":
            dc = R.spell_dc(self.world, self.pc)
            for foe in self.living():
                m = self.world.get("monsters", foe["id"])
                dmg = max(
                    1, roll(R.scaled(ab, self.pc["level"]), self.rng, names)["total"]
                )
                saved, nat = R.save_roll(self.rng, m.get("level", 1), dc)
                if saved:
                    dmg //= 2
                self.emit(
                    "roll",
                    f"{foe['label']} {'saves' if saved else 'fails to save'} (DC {dc}): {dmg} damage",
                    success=not saved,
                    label=ab["name"],
                )
                self.damage_enemy(foe, dmg)
        elif kind == "heal":
            amount = roll(ab.get("amount", "1d8"), self.rng, names)["total"]
            self.heal_party(ab.get("target", "self"), max(1, amount))
        elif kind == "guard":
            cb = self.s["combat"]
            if cb is not None:
                cb["guard"] = int(ab.get("ac", 2))
                cb["guard_rounds"] = int(ab.get("rounds", 1)) + 1
            self.chip(f"+{ab.get('ac', 2)} AC", "good")
        elif kind == "advantage":
            self.s["advantage"] = True
            self.chip("Advantage on your next roll", "good")
        elif kind == "extra_attack":
            self.player_attacks(target, self.attacks_per_action() * 2)
        elif kind == "restore":
            for rid in ab.get("restores", []):
                for a in R.class_abilities(self.world, self.pc):
                    if a["id"] == rid and a.get("uses"):
                        self.pc["uses"][rid] = a["uses"]
            self.chip("Power restored", "good")

    def heal_party(self, target: str, amount: int) -> None:
        if target == "party":
            self.heal(amount)
            for cid in self.party():
                self.heal_companion(cid, amount)
            return
        if target == "ally":
            hurt = [(self.pc["hp"] / self.pc["max_hp"], "pc")]
            hurt += [
                (self.comp(c)["hp"] / self.comp(c)["max_hp"], c) for c in self.party()
            ]
            who = min(hurt)[1]
            if who != "pc":
                self.heal_companion(who, amount)
                return
        self.heal(amount)

    def heal_companion(self, cid: str, amount: int) -> None:
        c = self.comp(cid)
        before = c["hp"]
        c["hp"] = min(c["max_hp"], c["hp"] + amount)
        if c["hp"] > before:
            self.chip(
                f"{self.person_name(cid).split()[0]} +{c['hp'] - before} HP", "good"
            )

    def combat_item(self, iid: str) -> None:
        if self.s["inventory"].get(iid, 0) <= 0:
            raise GameError("you do not have that")
        item = self.world.item(iid)
        if item.get("kind") != "consumable":
            raise GameError(f"{item['name']} is not something you can use in a fight")
        self.take(iid, quiet=True)
        self.emit("combat", f"You use {item['name']}.")
        self.fact(f"The player uses {item['name']}.")
        self.apply(item.get("use"))

    def try_flee(self) -> bool:
        combat = self.rules["combat"]
        bosses = any(
            self.world.get("monsters", e["id"]).get("boss") for e in self.living()
        )
        dc = combat.get("flee_dc", "medium")
        if bosses:
            dc = self.dc(dc) + 3
        if self.check(
            {"skill": combat.get("flee_skill", "acrobatics"), "dc": dc}, "Flee"
        ):
            self.s["combat"] = None
            self.emit("combat_end", "You get away.", outcome="fled")
            back = self.s.get("prev_location") or self.s["location"]
            if back != self.s["location"]:
                self.s["prev_location"], self.s["location"] = self.s["location"], back
                self.emit("system", f"You fall back to {self.location()['name']}.")
            return True
        self.emit("combat", "You cannot break away.")
        self.fact("The player tries to flee and fails.")
        return False

    # everyone else ------------------------------------------------------------
    def companion_stats(self, cid: str) -> dict:
        base = self.world.get("companions", cid).get("combat", {})
        lvl = self.pc["level"]
        return {
            "attack": int(base.get("attack", 3)) + (lvl - 1) // 3,
            "damage": f"{base.get('damage', '1d6')}+{(lvl - 1) // 2}",
            "ac": int(base.get("ac", 12)),
            "name": base.get("name", "a weapon"),
        }

    def companions_act(self) -> None:
        for cid in self.party():
            c = self.comp(cid)
            if c["hp"] <= 0 or not self.living():
                continue
            st = self.companion_stats(cid)
            foe = min(self.living(), key=lambda e: e["hp"])
            r = d20(self.rng, st["attack"])
            first = self.person_name(cid).split()[0]
            hit = r["natural"] == 20 or (r["natural"] != 1 and r["total"] >= foe["ac"])
            if hit:
                expr = crit_expr(st["damage"]) if r["natural"] == 20 else st["damage"]
                dmg = max(1, roll(expr, self.rng)["total"])
                self.emit(
                    "roll",
                    f"{first} attacks {foe['label']}: {r['total']} vs AC {foe['ac']}, hit, {dmg} damage",
                    success=True,
                    who=cid,
                    label=first,
                )
                self.fact(f"{first} hits {foe['label']} with {st['name']}.")
                self.damage_enemy(foe, dmg)
            else:
                self.emit(
                    "roll",
                    f"{first} attacks {foe['label']}: {r['total']} vs AC {foe['ac']}, miss",
                    success=False,
                    who=cid,
                    label=first,
                )
                self.fact(f"{first} attacks {foe['label']} and misses.")

    def player_ac(self) -> int:
        cb = self.s["combat"] or {}
        ac = R.armour_class(self.world, self.pc) + int(cb.get("guard", 0))
        if cb.get("defending"):
            ac += int(self.rules["combat"].get("defend_ac", 2))
        return ac

    def enemies_act(self) -> None:
        for foe in self.living():
            m = self.world.get("monsters", foe["id"])
            for _ in range(int(m.get("attacks", 1))):
                targets = [("pc", self.player_ac())]
                targets += [
                    (cid, self.companion_stats(cid)["ac"])
                    for cid in self.party()
                    if self.comp(cid)["hp"] > 0
                ]
                who, ac = (
                    targets[0]
                    if self.rng.random() < 0.6 or len(targets) == 1
                    else self.rng.choice(targets[1:])
                )
                r = d20(self.rng, int(m.get("attack", 3)))
                hit = r["natural"] == 20 or (r["natural"] != 1 and r["total"] >= ac)
                tname = "you" if who == "pc" else self.person_name(who).split()[0]
                if not hit:
                    self.emit(
                        "roll",
                        f"{foe['label']} attacks {tname}: d20 ({r['natural']}) {signed(r['bonus'])} = {r['total']} vs AC {ac}, miss",
                        success=True,
                        enemy=True,
                        label=foe["label"],
                    )
                    self.fact(f"{foe['label']} attacks {tname} and misses.")
                    continue
                expr = crit_expr(m["damage"]) if r["natural"] == 20 else m["damage"]
                dmg = max(1, roll(expr, self.rng)["total"])
                self.emit(
                    "roll",
                    f"{foe['label']} attacks {tname}: d20 ({r['natural']}) {signed(r['bonus'])} = {r['total']} vs AC {ac}, hit, {dmg} damage",
                    success=False,
                    enemy=True,
                    label=foe["label"],
                )
                self.fact(f"{foe['label']} hits {tname}.")
                if who == "pc":
                    self.pc["hp"] = max(0, self.pc["hp"] - dmg)
                    if self.pc["hp"] == 0:
                        return
                else:
                    c = self.comp(who)
                    c["hp"] = max(0, c["hp"] - dmg)
                    if c["hp"] == 0:
                        self.emit("combat", f"{tname} goes down!", tone="bad")
                        self.fact(f"{tname} is knocked down.")

    # outcomes -----------------------------------------------------------------
    def finish_if_won(self) -> bool:
        cb = self.s["combat"]
        if not cb or self.living():
            return False
        xp, gold, loot, after = 0, 0, [], []
        for e in cb["enemies"]:
            m = self.world.get("monsters", e["id"])
            xp += int(m.get("xp", 0))
            gold += max(0, roll(m.get("gold", "0"), self.rng)["total"])
            for drop in m.get("loot", []):
                if self.rng.random() < float(drop.get("chance", 1)):
                    loot.append(drop["item"])
            self.s["kills"][e["id"]] = self.s["kills"].get(e["id"], 0) + 1
            after += m.get("on_defeat", [])
        self.s["combat"] = None
        self.emit("combat_end", "Victory.", outcome="won")
        self.fact("The fight is won.")
        if gold:
            self._eff_gold(gold)
        for iid in loot:
            self.give(iid)
        self.apply(after)
        self.gain_xp(xp)
        for cid in self.party():
            c = self.comp(cid)
            if c["hp"] <= 0:
                c["hp"] = 1
        return True

    def defeat(self) -> None:
        d = self.rules["combat"].get("defeat", {})
        self.s["combat"] = None
        self.emit("combat_end", d.get("text", "You are defeated."), outcome="lost")
        lost = int(self.s["gold"] * float(d.get("gold_loss", 0.25)))
        if lost:
            self._eff_gold(-lost)
        self.pc["hp"] = int(d.get("hp", 1))
        for cid in self.party():
            self.comp(cid)["hp"] = 1
        self.s["prev_location"] = self.s["location"]
        self.s["location"] = self.s.get("last_safe") or self.s["location"]
        self.pass_time(8)
        (
            self.s["flags"].append("was_defeated")
            if "was_defeated" not in self.s["flags"]
            else None
        )
