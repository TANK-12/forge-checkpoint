"""You, aboard Janhollow.

the owner asked for both halves of this game: watch it, and step into it. This is
the second half. The station does not change shape because you are in it -- you
are simulated by the same clock, blocked by the same furniture and carried by
the same lift as the crew.

His answers on 2026-09-16 shape what is here:

* **Free, smooth walking**, not tile-by-tile. You hold a direction and glide.
* **The narrator names you.** You arrive as "the new arrival" and the 4B gives
  you a name and a reason for being aboard a moment later, which is why joining
  does not block on a thirty-second model call.
* **Only small things** may be decided for you: errands and rumours, not your
  job or who you are close to.
* **Sitting** counts as doing something, and **sleeping** skips the night.
* **One ongoing life**, saved with the station.

Movement is authoritative here rather than in the page: the page posts which
way you are holding, and the tick moves you. That keeps one set of collision
rules for everybody and means a save always knows where you are.
"""

from __future__ import annotations

import math
import re
import time

# Things you can sit on. A prop is a seat because of what it is, not because of
# where it is, so adding a chair anywhere in the station makes it sittable.
SEATS = {
    "couch": "sitting",
    "bench": "sitting",
    "beanbag": "sitting",
    "beanbag_green": "sitting",
    "kotatsu": "sitting at the table",
    "bunk": "lying down",
    "bed": "lying down",
    "desk": "working at the desk",
    "console": "at the console",
    "bridge_display": "watching the display",
}

# Where you can sleep the night away.
BEDS = {"bunk", "bed", "beanbag", "couch"}

# Where you step in when nobody is awake, best first. The docking ring is the
# old arrival point and stays as the last resort.
ARRIVE_FALLBACKS = ("mess_hall", "docking_ring")

# A crew member doing one of these is not company. Matched as whole words in
# the schedule's activity, so "sleep, finally" counts and "turning in" does not.
ASLEEP = re.compile(r"\b(sleep|sleeping|asleep|nap)\b", re.IGNORECASE)

SPEED = 3.1  # tiles a second, a shade quicker than the crew
REACH = 2.6  # how far your voice carries, in tiles


class Player:
    """One person: you. Absent until you step in."""

    def __init__(self, station):
        self.station = station
        self.id = "you"
        self.name = "the new arrival"
        self.role = ""
        self.arrival = ""
        self.sprite = "helper_light_a"
        self.aboard = False
        self.deck = ""
        self.x = 0.0
        self.y = 0.0
        self.facing = "down"
        self.input = (0.0, 0.0)
        self.saying = ""
        self.saying_until = 0.0
        self.sitting = ""  # what you are doing while sat down
        self.seat = None  # the tile you are sat on
        self.named = False  # has the narrator got to you yet
        self.riding = 0.0
        self.pending_deck = ""
        # What you carry: up to carry.SLOTS of {uid, item}, and which slot is
        # in your hands. The rules for filling them live in carry.py.
        self.inventory: list[dict] = []
        self.held = 0

    # --- arriving -----------------------------------------------------------

    def join(self, at="docking_ring"):
        """Step in at the docking ring, as a new arrival should."""
        spot = self.station.standing_spot(at, index=3)
        location = self.station.locations.get(at)
        if not spot or not location:
            # Any walkable tile beats refusing to let someone play.
            for deck in self.station.decks.values():
                fallback = deck.nearest_walkable(deck.lift)
                if fallback:
                    self.deck, (self.x, self.y) = deck.id, fallback
                    break
        else:
            self.deck = location["deck"]
            self.x, self.y = float(spot[0]), float(spot[1])
        self.aboard = True
        self.input = (0.0, 0.0)
        self.sitting = ""
        self.seat = None
        return self

    def arrive(self, world):
        """Step in where people are (review JH-I2, 2026-10-09).

        The old arrival was the docking ring, which put you alone in an empty
        room with the whole crew off screen. Now you arrive in the room with
        the most awake crew in it, a step or so from one of them so "Talk to"
        is on the menu at once. With everybody asleep it is the Mess hall.
        Returns where you landed and who you are beside, for the page's toast
        and the log."""
        location_id, company = _busiest_room(world)
        if not location_id:
            for fallback in ARRIVE_FALLBACKS:
                if fallback in self.station.locations:
                    location_id = fallback
                    break
        if not location_id:
            self.join()
            return {"location": "", "label": "", "beside": "", "beside_label": ""}
        self.join(at=location_id)
        spot = self._spot_beside(world, location_id, company)
        if spot:
            self.x, self.y = spot
        beside = nearest_crew(world)
        if beside is not None and beside not in company:
            beside = None
        location = self.station.locations[location_id]
        return {
            "location": location_id,
            "label": location.get("label", location_id),
            "beside": beside.id if beside else "",
            "beside_label": beside.record.get("label", beside.id) if beside else "",
        }

    def _spot_beside(self, world, location_id, company):
        """A free tile in the room, clear of everybody, and when there is
        company a comfortable talking distance from the nearest of them."""
        location = self.station.locations[location_id]
        deck = self.station.decks[location["deck"]]
        here = [m for m in world.crew.values() if m.deck == deck.id]
        x0, y0, w, h = location["rect"]
        mid = (x0 + (w - 1) / 2, y0 + (h - 1) / 2)
        # Off the room's edge when possible: a corner spot put you half under
        # a label with the room around you rather than in it.
        inner = [
            (tx, ty)
            for tx, ty in location["tiles"]
            if x0 < tx < x0 + w - 1 and y0 < ty < y0 + h - 1
        ]
        best = None
        for tx, ty in inner + [t for t in location["tiles"] if t not in inner]:
            if not self._free(deck, float(tx), float(ty)):
                continue
            edge = 0.0 if (tx, ty) in inner else 2.0
            clear = min((math.hypot(m.x - tx, m.y - ty) for m in here), default=99.0)
            if clear < 0.9:
                continue
            if company:
                near = min(math.hypot(m.x - tx, m.y - ty) for m in company)
                if near > REACH - 0.2:
                    continue
                score = abs(near - 1.5) + edge
            else:
                score = math.hypot(tx - mid[0], ty - mid[1]) + edge
            score += 0.02 * math.hypot(tx - mid[0], ty - mid[1])
            if best is None or score < best[0]:
                best = (score, (float(tx), float(ty)))
        return best[1] if best else None

    def leave(self):
        self.aboard = False
        self.input = (0.0, 0.0)
        self.sitting = ""

    # --- moving -------------------------------------------------------------

    def tile(self):
        return (int(round(self.x)), int(round(self.y)))

    def hold(self, dx, dy):
        """The page says which way you are holding. Standing up is what moving
        means, so a direction cancels sitting. Anything that is not a finite
        number counts as letting go: a NaN here used to become your position
        and every snapshot after it failed to serialise."""
        if not (math.isfinite(dx) and math.isfinite(dy)):
            dx = dy = 0.0
        length = math.hypot(dx, dy)
        if length > 1:
            dx, dy = dx / length, dy / length
        self.input = (dx, dy)
        if length and self.sitting:
            self.stand()

    def step(self, seconds):
        if not self.aboard:
            return
        if self.riding > 0:
            self.riding -= seconds
            if self.riding <= 0:
                self._arrive_on_deck()
            return
        dx, dy = self.input
        if not dx and not dy:
            return
        deck = self.station.decks.get(self.deck)
        if not deck:
            return
        distance = SPEED * seconds
        # Each axis separately, so walking into a wall at an angle slides along
        # it instead of stopping you dead. It is the difference between a
        # character that feels alive and one that feels stuck.
        moved = False
        for axis_dx, axis_dy in ((dx, 0.0), (0.0, dy)):
            if not axis_dx and not axis_dy:
                continue
            nx = self.x + axis_dx * distance
            ny = self.y + axis_dy * distance
            if self._free(deck, nx, ny):
                self.x, self.y = nx, ny
                moved = True
        if abs(dx) > abs(dy):
            self.facing = "right" if dx > 0 else "left"
        elif dy:
            self.facing = "down" if dy > 0 else "up"
        _ = moved  # the lift is ridden on purpose now, not by standing on it

    def _free(self, deck, x, y):
        """You take up most of a tile, so all four of your corners have to be
        somewhere you are allowed to be."""
        for cx, cy in (
            (x - 0.3, y - 0.3),
            (x + 0.3, y - 0.3),
            (x - 0.3, y + 0.3),
            (x + 0.3, y + 0.3),
        ):
            if not deck.walkable(int(round(cx)), int(round(cy))):
                return False
        return True

    def on_lift(self):
        """Whether you are standing on or beside the lift pad."""
        deck = self.station.decks.get(self.deck)
        if not deck:
            return False
        lx, ly = deck.lift
        return abs(self.x - lx) <= 2.2 and abs(self.y - ly) <= 2.2

    def ride_to(self, deck_id):
        """Take the lift to a named deck. Chosen from a menu rather than
        triggered by walking onto the pad: the owner wanted to be able to cross
        the corridor without being taken somewhere."""
        if deck_id not in self.station.decks or deck_id == self.deck:
            return False
        if not self.on_lift():
            return False
        self.pending_deck = deck_id
        self.riding = 1.2
        self.input = (0.0, 0.0)
        self.sitting = ""
        return True

    def actions(self, world=None):
        """What you could do where you are standing.

        The page draws these as a menu on E or a click, so adding an
        interaction is an entry here rather than another key nobody remembers.
        """
        found = []
        if not self.aboard:
            return found
        if self.sitting:
            found.append({"kind": "stand", "label": "Stand up"})
        else:
            seat = self.seat_near()
            if seat:
                found.append(
                    {
                        "kind": "sit",
                        "label": f"Sit at the {seat['sprite'].replace('_', ' ')}",
                    }
                )
            if self.can_sleep():
                found.append({"kind": "sleep", "label": "Sleep till morning"})
        if self.on_lift():
            for deck in sorted(self.station.decks.values(), key=lambda d: d.order):
                if deck.id != self.deck:
                    found.append(
                        {
                            "kind": "ride",
                            "target": deck.id,
                            "label": f"Take the lift to {deck.label}",
                        }
                    )
        if world is not None:
            near = nearest_crew(world)
            if near:
                found.append(
                    {
                        "kind": "talk",
                        "target": near.id,
                        "label": f"Talk to {near.record.get('label', near.id)}",
                    }
                )
            # Imported here because carry.py asks this module who is nearby.
            from . import carry

            found.extend(carry.actions(world))
        return found

    def _arrive_on_deck(self):
        deck = self.station.decks.get(self.pending_deck)
        self.pending_deck = ""
        if not deck:
            return
        self.deck = deck.id
        # Step off the pad rather than onto it, or you ride again immediately.
        lx, ly = deck.lift
        for ox, oy in ((0, 2), (0, -1), (2, 0), (-1, 0), (0, 3), (3, 0)):
            if deck.walkable(lx + ox, ly + oy) and deck.at(lx + ox, ly + oy) != "lift":
                self.x, self.y = float(lx + ox), float(ly + oy)
                return
        self.x, self.y = float(lx), float(ly)

    # --- doing things -------------------------------------------------------

    def seat_near(self):
        """The nearest thing you could sit on, within arm's reach."""
        deck = self.station.decks.get(self.deck)
        if not deck:
            return None
        best = None
        for prop in deck.props:
            if prop["sprite"] not in SEATS:
                continue
            gap = math.hypot(prop["x"] - self.x, prop["y"] - self.y)
            if gap <= 1.8 and (best is None or gap < best[0]):
                best = (gap, prop)
        return best[1] if best else None

    def sit(self):
        prop = self.seat_near()
        if not prop:
            return None
        self.sitting = SEATS.get(prop["sprite"], "sitting")
        self.seat = (prop["x"], prop["y"])
        self.input = (0.0, 0.0)
        return prop

    def stand(self):
        self.sitting = ""
        self.seat = None

    def can_sleep(self):
        prop = self.seat_near()
        return bool(prop and prop["sprite"] in BEDS)

    @property
    def moving(self):
        return bool(self.input[0] or self.input[1]) or self.riding > 0

    # --- state --------------------------------------------------------------

    def to_dict(self):
        dx, dy = self.input
        return {
            "id": self.id,
            "vx": round(dx * SPEED, 3),
            "vy": round(dy * SPEED, 3),
            "speed": SPEED,
            "label": self.name,
            "role": self.role,
            "sprite": self.sprite,
            "aboard": self.aboard,
            "deck": self.deck,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "facing": self.facing,
            "moving": self.moving,
            "riding": self.riding > 0,
            "saying": self.saying,
            "sitting": self.sitting,
            "can_sleep": self.can_sleep() if self.aboard else False,
            "can_sit": bool(self.seat_near()) if self.aboard else False,
            "named": self.named,
            "arrival": self.arrival,
            "held": self.held,
        }

    def save_state(self):
        return {
            "name": self.name,
            "role": self.role,
            "arrival": self.arrival,
            "named": self.named,
            "aboard": self.aboard,
            "deck": self.deck,
            "x": self.x,
            "y": self.y,
            "facing": self.facing,
            "sitting": self.sitting,
            "inventory": [dict(slot) for slot in self.inventory],
            "held": self.held,
        }

    def load_state(self, state):
        if not state:
            return
        self.name = state.get("name", self.name)
        self.role = state.get("role", self.role)
        self.arrival = state.get("arrival", self.arrival)
        self.named = bool(state.get("named", False))
        self.aboard = bool(state.get("aboard", False))
        self.deck = state.get("deck", self.deck)
        self.x = float(state.get("x", self.x))
        self.y = float(state.get("y", self.y))
        self.facing = state.get("facing", self.facing)
        self.sitting = state.get("sitting", "")
        self.input = (0.0, 0.0)
        self.inventory = [
            {"uid": str(slot["uid"]), "item": str(slot["item"])}
            for slot in state.get("inventory") or []
            if isinstance(slot, dict) and "uid" in slot and "item" in slot
        ]
        self.held = int(state.get("held", 0) or 0)


def nearest_crew(world, within=REACH):
    """Who can hear you. Returns the closest crew member on your deck."""
    player = world.player
    if not player.aboard:
        return None
    best = None
    for member in world.crew.values():
        if member.deck != player.deck:
            continue
        gap = math.hypot(member.x - player.x, member.y - player.y)
        if gap <= within and (best is None or gap < best[0]):
            best = (gap, member)
    return best[1] if best else None


def awake(member):
    return not ASLEEP.search(member.activity or "")


def _busiest_room(world):
    """The room with the most awake crew actually in it, and who they are.
    Someone whose room is on another deck is still walking there and does not
    count. Ties go to a social room, then to the room's id, so the choice is
    the same every time."""
    rooms: dict[str, list] = {}
    for member in world.crew.values():
        location = world.station.locations.get(member.location)
        if not location or location["deck"] != member.deck or member.riding > 0:
            continue
        if awake(member):
            rooms.setdefault(member.location, []).append(member)
    if not rooms:
        return "", []

    def rank(item):
        location_id, people = item
        social = world.station.locations[location_id].get("kind") == "social"
        return (-len(people), not social, location_id)

    location_id, people = sorted(rooms.items(), key=rank)[0]
    return location_id, people


def bystanders(world, within=3.4):
    """Crew close enough to greet you unprompted. Someone asleep does not."""
    player = world.player
    if not player.aboard:
        return []
    close = []
    for member in world.crew.values():
        if member.deck != player.deck or member.saying or not awake(member):
            continue
        if math.hypot(member.x - player.x, member.y - player.y) <= within:
            close.append(member)
    return close


def now():
    return time.monotonic()
