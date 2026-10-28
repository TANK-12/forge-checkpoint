"""Carrying things, putting them down and giving them away.

the owner chose the shape on 2026-09-17:

* **Four slots.** What you carry shows in the play bar, and the slot you have
  selected is drawn in your hands.
* **Things are placed around the station.** Each item file in
  ~/ForgeGameData/janhollow/items/ names the rooms a copy starts in, so adding
  something to find is one file and no code.
* **Put down anywhere, and it stays.** The floor is saved with your life.
* **Likes and dislikes.** A crew member glad of what you brought warms to you
  by one, the same step talking gives. Anything else earns a polite thanks and
  no change, and only one gift a person a station day counts, so gifts cannot
  be farmed.

Everything here takes the world and holds its lock. Nothing here calls a model:
reactions are written lines, so gifts work with voices off.
"""

from __future__ import annotations

import math
import random

from .player import nearest_crew

SLOTS = 4
REACH = 1.3  # how close an item on the floor has to be to pick it up, in tiles

LIKED_LINES = [
    "Oh, {a} {item}! You remembered.",
    "For me? {A} {item} is exactly right.",
    "You know me too well. Thank you.",
    "That is the nicest thing today. Thank you.",
]
POLITE_LINES = [
    "Oh. {A} {item}. That is kind of you.",
    "Thank you. I will find somewhere for it.",
    "{A} {item}? Well, thank you.",
]
AGAIN_LINES = [
    "Twice in one day? You spoil me.",
    "Another one? Thank you, truly.",
]


def records(world):
    return (world.content.get("types") or {}).get("items") or {}


def describe(world, item_id):
    """What the page needs to draw and name an item."""
    record = records(world).get(item_id) or {}
    return {
        "item": item_id,
        "label": record.get("label", item_id),
        "article": record.get("article", "a"),
        "sprite": record.get("sprite", ""),
        "pack": record.get("pack", "janhollow-space"),
    }


def seed_floor(world):
    """Put one copy of every item in each room it starts in. Called for a new
    life; a loaded save replaces it with the floor as it was left."""
    placed = []
    taken = set()
    for item_id, record in sorted(records(world).items()):
        for n, location_id in enumerate(record.get("starts_in") or []):
            location = world.station.locations.get(location_id)
            if not location:
                continue
            spot = None
            # Stand clear of where the crew stand, and of other items.
            for index in range(4, 40):
                candidate = world.station.standing_spot(location_id, index=index)
                if candidate and (location["deck"], candidate) not in taken:
                    spot = candidate
                    break
            if not spot:
                continue
            taken.add((location["deck"], spot))
            placed.append(
                {
                    "uid": f"{item_id}-{n + 1}",
                    "item": item_id,
                    "deck": location["deck"],
                    "x": int(spot[0]),
                    "y": int(spot[1]),
                }
            )
    return placed


def floor_view(world):
    return [
        dict(describe(world, thing["item"]), **thing) for thing in world.floor_items
    ]


def carrying_view(world):
    return [
        dict(describe(world, slot["item"]), uid=slot["uid"])
        for slot in world.player.inventory
    ]


def item_near(world):
    player = world.player
    best = None
    for thing in world.floor_items:
        if thing["deck"] != player.deck:
            continue
        gap = math.hypot(thing["x"] - player.x, thing["y"] - player.y)
        if gap <= REACH and (best is None or gap < best[0]):
            best = (gap, thing)
    return best[1] if best else None


def held(world):
    player = world.player
    if 0 <= player.held < len(player.inventory):
        return player.inventory[player.held]
    return None


def _label(world, item_id):
    return describe(world, item_id)["label"]


def pick_up(world):
    with world.lock:
        player = world.player
        if not player.aboard:
            return {"ok": False, "why": "you are not aboard"}
        thing = item_near(world)
        if not thing:
            return {"ok": False, "why": "nothing to pick up here"}
        if len(player.inventory) >= SLOTS:
            return {"ok": False, "why": "your hands are full"}
        world.floor_items.remove(thing)
        player.inventory.append({"uid": thing["uid"], "item": thing["item"]})
        player.held = len(player.inventory) - 1
        return {"ok": True, "item": _label(world, thing["item"])}


def put_down(world):
    with world.lock:
        player = world.player
        slot = held(world)
        if not slot or not player.aboard:
            return {"ok": False, "why": "you are not carrying anything"}
        x, y = player.tile()
        player.inventory.remove(slot)
        player.held = max(0, min(player.held, len(player.inventory) - 1))
        world.floor_items.append(
            {
                "uid": slot["uid"],
                "item": slot["item"],
                "deck": player.deck,
                "x": x,
                "y": y,
            }
        )
        return {"ok": True, "item": _label(world, slot["item"])}


def select(world, index):
    with world.lock:
        if not 0 <= index < len(world.player.inventory):
            return {"ok": False, "why": "that slot is empty"}
        world.player.held = index
        return {
            "ok": True,
            "item": _label(world, world.player.inventory[index]["item"]),
        }


def give(world, rng=None):
    """Give what is in your hands to whoever is next to you."""
    rng = rng or random
    with world.lock:
        player = world.player
        slot = held(world)
        if not slot or not player.aboard:
            return {"ok": False, "why": "you are not carrying anything"}
        member = nearest_crew(world)
        if not member:
            return {"ok": False, "why": "nobody is close enough"}
        info = describe(world, slot["item"])
        name = member.record.get("label", member.id)
        liked = slot["item"] in (member.record.get("likes") or [])
        first_today = world.gifts_given.get(member.id) != world.day
        warmed = False
        if first_today:
            world.gifts_given[member.id] = world.day
            if liked:
                warmed = world.warm(member.id, player.id)
        pool = LIKED_LINES if liked else POLITE_LINES
        if not first_today:
            pool = AGAIN_LINES
        article = info["article"]
        line = rng.choice(pool).format(
            item=info["label"], a=article, A=article[:1].upper() + article[1:]
        )
        player.inventory.remove(slot)
        player.held = max(0, min(player.held, len(player.inventory) - 1))
        member.remember(f"{player.name} gave me {article} {info['label']}.")
        world.note(f"{player.name} gave {name} {article} {info['label']}.", kind="day")
        world.say(member.id, line, 5.0)
        return {
            "ok": True,
            "to": name,
            "item": info["label"],
            "liked": liked,
            "warmed": warmed,
            "line": line,
        }


def actions(world):
    """Menu entries for what you could do with things, where you stand."""
    found = []
    player = world.player
    if not player.aboard or player.sitting:
        return found
    thing = item_near(world)
    if thing and len(player.inventory) < SLOTS:
        found.append(
            {
                "kind": "pickup",
                "label": f"Pick up the {_label(world, thing['item'])}",
            }
        )
    slot = held(world)
    if slot:
        label = _label(world, slot["item"])
        member = nearest_crew(world)
        if member:
            found.append(
                {
                    "kind": "give",
                    "target": member.id,
                    "label": f"Give the {label} to {member.record.get('label', member.id)}",
                }
            )
        found.append({"kind": "drop", "label": f"Put down the {label}"})
    return found
