"""The station's day: a clock, eight schedules and the walking in between.

This runs in the backend rather than the page, for one reason: the owner asked
that a world be able to keep living while the tab is closed, and chose four
away modes for it. A simulation that lives in a browser tab cannot do that.
The page is a window onto this, not the owner of it.

What a tick does, in order:

1. Decide how much time to advance, which is what the away mode governs.
2. Move the clock by that much. A day is `day_minutes` of real time -- 40 by
   default, his answer -- so one real second is 1440/(day_minutes*60) station
   minutes.
3. Give each crew member their scheduled destination, and walk them a step
   towards it. Crossing decks means the lift, because that is the only way.
4. Note anything worth remembering in the log.

Nothing here talks to a model. Sessions 2 and 3 add the chatter and the
narrator on top of this clock; the hooks they need -- `models_allowed`,
`pending_summary`, the log -- are already here and already saved.
"""

import math
import random
import threading
import time

from . import carry, guard, player as player_module

DAY_MINUTES = 1440

# How the world behaves when you are not looking at it. The owner picked all four
# and made "pause when unfocused" the default. A mode is data: which presence
# states let the clock run, which let a model be used, and whether coming back
# fast-forwards the time you missed.
AWAY_MODES = {
    "pause_unfocused": {
        "label": "Pause when unfocused",
        "detail": "The station holds still the moment you look away.",
        "runs_when": ("focused",),
        "models_when": ("focused",),
        "catch_up": False,
    },
    "run_closed": {
        "label": "Keep running when closed",
        "detail": "Life aboard carries on, and the crew keep talking, even with the tab shut.",
        "runs_when": ("focused", "open", "closed"),
        "models_when": ("focused", "open", "closed"),
        "catch_up": False,
    },
    "idle_closed": {
        "label": "Idle when closed",
        "detail": "The crew keep to their day with the tab shut, but no model runs until you return.",
        "runs_when": ("focused", "open", "closed"),
        "models_when": ("focused", "open"),
        "catch_up": False,
    },
    "time_skip": {
        "label": "Time-skip summary",
        "detail": "Nothing runs while you are away; on your return the station jumps ahead and tells you what you missed.",
        "runs_when": ("focused", "open"),
        "models_when": ("focused", "open"),
        "catch_up": True,
    },
}

CHATTER_LEVELS = {
    "off": {"label": "Off", "per_minute": 0.0},
    "quiet": {"label": "Quiet", "per_minute": 0.25},
    "moderate": {"label": "Moderate", "per_minute": 1.0},
    "lively": {"label": "Lively", "per_minute": 2.0},
}

# Written lines: what the crew say when no model is talking (Voices off, or
# Jan not answering). They cost nothing and load nothing; see barks.py. A level
# is data, like the chatter levels: label and exchanges a minute.
BARK_LEVELS = {
    "off": {"label": "Off", "per_minute": 0.0},
    "some": {"label": "Now and then", "per_minute": 1.0},
    "often": {"label": "Often", "per_minute": 2.5},
}

DEFAULT_SETTINGS = {
    "day_minutes": 40.0,  # real minutes for one station day
    "away_mode": "pause_unfocused",
    # Off until you ask for it. The owner opened the game by accident and found
    # it had started a language model: "i dont wnat it to run jan when i only
    # accidentaly went int o th app tab". Nothing here loads a model until the
    # chatter level is turned up or a button is pressed, so wandering into the
    # tab costs nothing.
    "chatter": "off",
    # On, because a station that says nothing with Voices off was the review's
    # biggest complaint, and these lines never touch a model.
    "barks": "some",
    "start_hour": 7.0,
}

# A presence heartbeat older than this means the page is gone, not just quiet.
CLOSED_AFTER = 12.0
# A time-skip never replays more than this, so a week away is one morning.
MAX_SKIP_MINUTES = 12 * 60
RIDE_SECONDS = 1.6
LOG_CAP = 240
# What a crew member carries from one day to the next. Small on purpose: disk is
# short, and a 0.8B model given twelve memories writes worse lines than one
# given the last thing that happened.
MEMORY_CAP = 12
CONVERSATION_CAP = 30
# Relationships drift by one per conversation and stop here, so nobody becomes
# everybody's best friend by week two.
RELATIONSHIP_CAP = 3


def _number(value):
    """A finite float from a settings value, or None. True is not a number
    here, and neither is a 400-digit integer (float() overflows on it)."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def clamp_settings(values, base=None):
    """Settings with every bad value dropped. A bad value keeps what `base`
    had (the current settings, on an update), or the default."""
    out = clamp_settings(base) if base is not None else dict(DEFAULT_SETTINGS)
    for key, value in (values or {}).items():
        if key not in out:
            continue
        if key == "day_minutes":
            # Up to four real days to one station day: the owner asked for
            # "much longer game days", and at the top of this range the
            # crew move about as fast as a houseplant, which is the point.
            number = _number(value)
            if number is not None:
                out[key] = max(2.0, min(5760.0, number))
        elif key == "away_mode":
            if isinstance(value, str) and value in AWAY_MODES:
                out[key] = value
        elif key == "chatter":
            if isinstance(value, str) and value in CHATTER_LEVELS:
                out[key] = value
        elif key == "barks":
            if isinstance(value, str) and value in BARK_LEVELS:
                out[key] = value
        elif key == "start_hour":
            number = _number(value)
            if number is not None:
                out[key] = max(0.0, min(23.99, number))
    return out


def clock_text(minute):
    minute = int(minute) % DAY_MINUTES
    return f"{minute // 60:02d}:{minute % 60:02d}"


def minutes_of(at):
    hour, _, minute = str(at).partition(":")
    try:
        return int(hour) * 60 + int(minute)
    except ValueError:
        return 0


def scheduled(entries, minute):
    """The schedule entry in force at `minute`, wrapping past midnight.

    A crew member is always somewhere: before their first entry of the day they
    are still living their last one from yesterday.
    """
    if not entries:
        return None
    best = None
    for entry in entries:
        at = minutes_of(entry.get("at"))
        if at <= minute and (best is None or at >= minutes_of(best.get("at"))):
            best = entry
    return best or max(entries, key=lambda e: minutes_of(e.get("at")))


class Crew:
    """One crew member, walking."""

    def __init__(self, record, station, index):
        self.id = record["id"]
        self.record = record
        self.station = station
        self.index = index
        self.speed = float(record.get("speed", 2.6) or 2.6)
        self.location = record.get("home") or ""
        self.activity = "settling in"
        self.deck = ""
        self.x = 0.0
        self.y = 0.0
        self.facing = "down"
        self.path = []
        self.riding = 0.0
        self.pending_deck = ""
        # What they are saying right now, and until when (monotonic seconds).
        # The bubble lives on the crew member rather than in a list of bubbles
        # so that it cannot outlive whoever said it.
        self.saying = ""
        self.saying_until = 0.0
        # Relationships start from the crew file and then drift, so the file
        # stays the starting point rather than the current truth.
        self.relationships = dict(record.get("relationships") or {})
        self.memories: list[str] = []

    # --- placement ----------------------------------------------------------

    def place_at(self, location_id):
        spot = self.station.standing_spot(location_id, self.index)
        location = self.station.locations.get(location_id)
        if not spot or not location:
            return False
        self.location = location_id
        self.deck = location["deck"]
        self.x, self.y = float(spot[0]), float(spot[1])
        self.path = []
        self.riding = 0.0
        self.pending_deck = ""
        return True

    def tile(self):
        return (int(round(self.x)), int(round(self.y)))

    # --- moving -------------------------------------------------------------

    def head_for(self, location_id):
        """Route to a location, via the lift when it is on another deck."""
        location = self.station.locations.get(location_id)
        if not location or not self.deck:
            return
        # Whatever they were saying, they are walking away mid-sentence.
        self.saying = ""
        self.saying_until = 0.0
        self.location = location_id
        if location["deck"] == self.deck:
            goal = self.station.standing_spot(location_id, self.index)
            self.pending_deck = ""
        else:
            deck = self.station.decks.get(self.deck)
            goal = deck.lift if deck else None
            self.pending_deck = location["deck"]
        if goal:
            self.path = self.station.decks[self.deck].path(self.tile(), tuple(goal))

    def step(self, seconds):
        if self.riding > 0:
            self.riding -= seconds
            if self.riding <= 0:
                self.arrive_on_deck()
            return
        remaining = self.speed * seconds
        while remaining > 0 and self.path:
            tx, ty = self.path[0]
            dx, dy = tx - self.x, ty - self.y
            distance = math.hypot(dx, dy)
            if distance <= remaining or distance < 1e-6:
                self.x, self.y = float(tx), float(ty)
                remaining -= distance
                self.path.pop(0)
            else:
                self.x += dx / distance * remaining
                self.y += dy / distance * remaining
                remaining = 0
            if abs(dx) > abs(dy):
                self.facing = "right" if dx > 0 else "left"
            elif abs(dy) > 1e-6:
                self.facing = "down" if dy > 0 else "up"
        if not self.path and self.pending_deck:
            self.riding = RIDE_SECONDS

    def arrive_on_deck(self):
        """Step out of the lift on the deck the schedule wanted."""
        deck = self.station.decks.get(self.pending_deck)
        self.pending_deck = ""
        if not deck:
            return
        self.deck = deck.id
        self.x, self.y = float(deck.lift[0]), float(deck.lift[1])
        goal = self.station.standing_spot(self.location, self.index)
        if goal:
            self.path = deck.path(self.tile(), tuple(goal))

    @property
    def moving(self):
        return bool(self.path) or self.riding > 0

    def velocity(self):
        """Which way this crew member is moving, in tiles a second.

        Sent to the page so it can carry them along between polls instead of
        easing towards a target that only arrives three times a second, which
        is what made everyone walk in visible steps.
        """
        if self.riding > 0 or not self.path:
            return (0.0, 0.0)
        tx, ty = self.path[0]
        dx, dy = tx - self.x, ty - self.y
        distance = math.hypot(dx, dy)
        if distance < 1e-6:
            return (0.0, 0.0)
        return (dx / distance * self.speed, dy / distance * self.speed)

    def to_dict(self):
        vx, vy = self.velocity()
        return {
            "id": self.id,
            "label": self.record.get("label", self.id),
            "vx": round(vx, 3),
            "vy": round(vy, 3),
            "job": self.record.get("job", ""),
            "sprite": self.record.get("sprite", "person1"),
            "pronouns": self.record.get("pronouns", "they/them"),
            "deck": self.deck,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "facing": self.facing,
            "activity": self.activity,
            "location": self.location,
            "moving": self.moving,
            "riding": self.riding > 0,
            "saying": self.saying,
            "memories": len(self.memories),
        }

    def remember(self, text):
        self.memories.append(text)
        del self.memories[:-MEMORY_CAP]

    def save_state(self):
        return {
            "location": self.location,
            "activity": self.activity,
            "deck": self.deck,
            "x": self.x,
            "y": self.y,
            "facing": self.facing,
            "relationships": dict(self.relationships),
            "memories": list(self.memories),
        }

    def load_state(self, state):
        self.location = state.get("location", self.location)
        self.activity = state.get("activity", self.activity)
        self.deck = state.get("deck", self.deck)
        self.x = float(state.get("x", self.x))
        self.y = float(state.get("y", self.y))
        self.facing = state.get("facing", self.facing)
        self.relationships = dict(state.get("relationships") or self.relationships)
        self.memories = list(state.get("memories") or [])[-MEMORY_CAP:]
        self.path = []


class World:
    """The whole station, ticking. One lock guards it; the tick thread and the
    request handlers both go through that lock, so a snapshot is never a
    half-moved crew member."""

    def __init__(
        self,
        station,
        crew_records: list[dict],
        settings=None,
        day=1,
        minute=None,
        content: dict | None = None,
    ):
        self.station = station
        self.settings = clamp_settings(settings or {})
        self.day = day
        self.minute = (
            float(minute) if minute is not None else self.settings["start_hour"] * 60.0
        )
        self.lock = threading.RLock()
        self.log = []
        self.pending_summary = None
        # The content store, kept so the narrator can read the seeded events
        # without re-scanning the disk on every station day.
        self.content = content or {"types": {}}
        self.conversations: list[dict] = []
        self.player = player_module.Player(station)
        self.day_story: dict | None = None
        # Set when the clock rolls past midnight; the director picks it up and
        # clears it. A flag rather than a callback so the tick stays synchronous
        # and nothing slow can ever run on it.
        self.new_day_pending = False
        self.model_status = {
            "lines": 0,
            "conversations": 0,
            "rejected": 0,
            "last_problem": "",
            "last_error": "",
            "narrator_runs": 0,
            "written": 0,  # written lines (barks.py), not model output
        }
        self.presence = "closed"
        self.last_seen = 0.0
        # Where rejected model output is written. Set by web_app; left empty in
        # tests, which keeps the guard's log off disk.
        self.reject_folder = ""

        self.last_tick = time.monotonic()
        self.running = False
        self._thread = None
        self._stop = threading.Event()
        self.crew = {}
        for index, record in enumerate(
            sorted(crew_records, key=lambda r: r.get("id", ""))
        ):
            if not record.get("aboard", True):
                continue
            member = Crew(record, station, index)
            start = scheduled(record.get("schedule", []), int(self.minute))
            member.place_at((start or {}).get("goto") or record.get("home") or "")
            if start:
                member.activity = start.get("activity", "")
            self.crew[member.id] = member
        # Things lying about the station, and who has had a gift today. A new
        # life seeds the floor from the item files; a save replaces both.
        self.floor_items: list[dict] = carry.seed_floor(self)
        self.gifts_given: dict[str, int] = {}

    # --- time ---------------------------------------------------------------

    @property
    def mode(self):
        return AWAY_MODES.get(self.settings["away_mode"], AWAY_MODES["pause_unfocused"])

    def minutes_per_second(self):
        return DAY_MINUTES / (self.settings["day_minutes"] * 60.0)

    def presence_now(self, now):
        if self.presence == "focused" and now - self.last_seen < CLOSED_AFTER:
            return "focused"
        if now - self.last_seen < CLOSED_AFTER:
            return "open"
        return "closed"

    def saw_page(self, focused, now=None):
        """The page says it is still there. Returns the catch-up summary if the
        away mode had frozen the station while it was gone."""
        now = time.monotonic() if now is None else now
        with self.lock:
            was = self.presence_now(now)
            self.presence = "focused" if focused else "open"
            self.last_seen = now
            if was == "closed" and self.mode["catch_up"]:
                return self.catch_up(now)
        return None

    def catch_up(self, now):
        """Time-skip: jump the clock forward over the time the page was away and
        put the crew where they should be, rather than replaying every step."""
        missed = max(0.0, (now - self.last_tick)) * self.minutes_per_second()
        missed = min(missed, MAX_SKIP_MINUTES)
        self.last_tick = now
        if missed < 1:
            return None
        before = f"day {self.day}, {clock_text(self.minute)}"
        self.advance_clock(missed)
        for member in self.crew.values():
            entry = scheduled(member.record.get("schedule", []), int(self.minute))
            if entry:
                member.activity = entry.get("activity", "")
                member.place_at(entry.get("goto") or member.location)
        summary = {
            "minutes": round(missed),
            "from": before,
            "to": f"day {self.day}, {clock_text(self.minute)}",
            # The 4B narrator turns this into a paragraph in session 3. Until
            # then the page shows the plain version.
            "needs_narrator": True,
        }
        self.pending_summary = summary
        self.note(
            f"{round(missed / 60)} hours passed while you were away.", kind="skip"
        )
        return summary

    def sleep_until_morning(self, hour=7.0):
        """Skip the night. Returns the summary the narrator will write up.

        The crew are put where their schedules say they should be rather than
        walked there, exactly as a time-skip does -- sleeping through eight
        hours should not mean simulating eight hours.
        """
        with self.lock:
            target = hour * 60.0
            minutes = (target - self.minute) % DAY_MINUTES
            if minutes < 1:
                minutes += DAY_MINUTES
            before = f"day {self.day}, {clock_text(self.minute)}"
            self.advance_clock(minutes)
            for member in self.crew.values():
                entry = scheduled(member.record.get("schedule", []), int(self.minute))
                if entry:
                    member.activity = entry.get("activity", "")
                    member.place_at(entry.get("goto") or member.location)
            summary = {
                "minutes": round(minutes),
                "from": before,
                "to": f"day {self.day}, {clock_text(self.minute)}",
                "needs_narrator": True,
                "slept": True,
            }
            self.pending_summary = summary
            self.note(
                f"{self.player.name} slept through to {clock_text(self.minute)}.",
                kind="skip",
            )
            return summary

    def advance_clock(self, minutes):
        self.minute += minutes
        while self.minute >= DAY_MINUTES:
            self.minute -= DAY_MINUTES
            self.day += 1
            self.new_day_pending = True
            self.note(f"Day {self.day} begins aboard Janhollow.", kind="day")

    # --- the tick -----------------------------------------------------------

    def tick(self, now=None):
        """One step. Returns the real seconds that were applied, which is zero
        when the away mode says the station is holding still."""
        now = time.monotonic() if now is None else now
        with self.lock:
            elapsed = max(0.0, now - self.last_tick)
            self.last_tick = now
            state = self.presence_now(now)
            if state not in self.mode["runs_when"]:
                return 0.0
            elapsed = min(elapsed, 5.0)  # a suspended laptop must not fast-forward
            self.advance_clock(elapsed * self.minutes_per_second())
            for member in self.crew.values():
                if member.saying and now >= member.saying_until:
                    member.saying = ""
                self.follow_schedule(member)
                member.step(elapsed)
            if self.player.saying and now >= self.player.saying_until:
                self.player.saying = ""
            self.player.step(elapsed)
            return elapsed

    def follow_schedule(self, member):
        entry = scheduled(member.record.get("schedule", []), int(self.minute))
        if not entry:
            return
        goal = entry.get("goto")
        if goal and goal != member.location:
            member.head_for(goal)
            member.activity = entry.get("activity", "")
            where = self.station.locations.get(goal, {}).get("label", goal)
            self.note(
                f"{member.record.get('label', member.id)} heads to {where}"
                f" — {member.activity}.",
                kind="move",
                who=member.id,
            )
        elif entry.get("activity") and entry["activity"] != member.activity:
            member.activity = entry["activity"]

    def clock_now(self):
        return clock_text(self.minute)

    # --- what the models add ------------------------------------------------

    def say(self, member_id, line, seconds, written=False):
        """Put a line in someone's mouth, with a bubble that expires. Works for
        the player as well as the crew, so your own words appear over your head
        exactly as theirs do. A written line (barks.py) is counted apart from
        the model's, so the Voices panel still says what the models did."""
        with self.lock:
            if member_id == self.player.id:
                self.player.saying = line
                self.player.saying_until = time.monotonic() + seconds
                self.note(f"{self.player.name}: {line}", kind="said", who=member_id)
                return self.player
            member = self.crew.get(member_id)
            if not member:
                return None
            member.saying = line
            member.saying_until = time.monotonic() + seconds
            self.model_status["written" if written else "lines"] += 1
            self.note(
                f"{member.record.get('label', member_id)}: {line}",
                kind="said",
                who=member_id,
            )
            return member

    def record_conversation(self, a_id, b_id, said):
        """File a finished conversation: both sides remember it, and thinking
        well of someone is what talking to them does."""
        with self.lock:
            conversation = {
                "day": self.day,
                "at": clock_text(self.minute),
                "where": self.crew[a_id].location if a_id in self.crew else "",
                "lines": [{"who": who, "line": line} for who, line in said],
                "speakers": [a_id, b_id],
            }
            self.conversations.append(conversation)
            del self.conversations[:-CONVERSATION_CAP]
            self.model_status["conversations"] += 1
            for one, other in ((a_id, b_id), (b_id, a_id)):
                member = self.crew.get(one)
                friend = self.crew.get(other)
                if not member or not friend:
                    continue
                score = int(member.relationships.get(other, 0))
                member.relationships[other] = min(RELATIONSHIP_CAP, score + 1)
                where = self.station.locations.get(member.location, {}).get(
                    "label", "the station"
                )
                theirs = next(
                    (
                        line
                        for who, line in reversed(said)
                        if who != member.record.get("label", one)
                    ),
                    "",
                )
                remembered = f"In the {where}, {friend.record.get('label', other)} said: {theirs}"
                if theirs:
                    member.memories.append(remembered)
                    del member.memories[:-MEMORY_CAP]
            return conversation

    def warm(self, member_id, other_id):
        """One step warmer, capped. Returns whether anything changed."""
        with self.lock:
            member = self.crew.get(member_id)
            if not member:
                return False
            score = int(member.relationships.get(other_id, 0))
            member.relationships[other_id] = min(RELATIONSHIP_CAP, score + 1)
            return member.relationships[other_id] != score

    def remember_everyone(self, text):
        """Something the whole crew lived through, such as the day's event."""
        with self.lock:
            for member in self.crew.values():
                member.memories.append(text)
                del member.memories[:-MEMORY_CAP]

    def record_rejection(self, raw, line, problems, context=None):
        """A line the guard refused. Counted for the panel, written to
        rejected.jsonl for whoever tunes the prompt next."""
        with self.lock:
            self.model_status["rejected"] += 1
            self.model_status["last_problem"] = "; ".join(problems)[:160]
        if self.reject_folder:
            try:
                guard.log_rejection(self.reject_folder, raw, line, problems, context)
            except OSError:
                pass

    def note_model_problem(self, text):
        with self.lock:
            self.model_status["last_error"] = str(text)[:200]

    def take_new_day(self):
        """True once per station day, for whoever is going to narrate it."""
        with self.lock:
            if not self.new_day_pending:
                return False
            self.new_day_pending = False
            return True

    def set_day_story(self, story):
        with self.lock:
            self.day_story = story
            self.model_status["narrator_runs"] += 1
            self.note(f"{story['headline']} — {story['story']}", kind="story")

    def models_allowed(self):
        """Whether a Jan model may be used right now. Session 2 asks this before
        every line of chatter; the away mode is what answers."""
        with self.lock:
            return self.presence_now(time.monotonic()) in self.mode["models_when"]

    def barks_allowed(self):
        """Whether a written line may be said now: the clock is running and
        the page is open. No model is involved, so the away mode's model rule
        does not apply, but a line nobody can see is only log clutter."""
        with self.lock:
            state = self.presence_now(time.monotonic())
            return state != "closed" and state in self.mode["runs_when"]

    def note(self, text, kind="note", who=""):
        self.log.append(
            {
                "day": self.day,
                "at": clock_text(self.minute),
                "text": text,
                "kind": kind,
                "who": who,
            }
        )
        if len(self.log) > LOG_CAP:
            del self.log[: len(self.log) - LOG_CAP]

    # --- the thread ---------------------------------------------------------

    def start(self, hertz=30.0):
        if self._thread:
            return self._thread
        self.last_tick = time.monotonic()
        self.running = True

        def loop():
            period = 1.0 / hertz
            while not self._stop.wait(period):
                try:
                    self.tick()
                except Exception:  # a bad tick must not kill the station
                    self.last_tick = time.monotonic()

        self._thread = threading.Thread(target=loop, daemon=True, name="janhollow-sim")
        self._thread.start()
        return self._thread

    def stop(self):
        self._stop.set()
        self.running = False

    # --- what the page sees -------------------------------------------------

    def snapshot(self, since=0):
        with self.lock:
            return {
                "day": self.day,
                "minute": round(self.minute, 2),
                "clock": clock_text(self.minute),
                "settings": dict(self.settings),
                "presence": self.presence_now(time.monotonic()),
                "running": self.running,
                "crew": [member.to_dict() for member in self.crew.values()],
                "log": self.log[since:][-60:],
                "log_length": len(self.log),
                "pending_summary": self.pending_summary,
                "conversations": self.conversations[-6:],
                "models": dict(self.model_status),
                "day_story": self.day_story,
                "player": dict(
                    self.player.to_dict(),
                    actions=self.player.actions(self),
                    carrying=carry.carrying_view(self),
                ),
                "items": carry.floor_view(self),
            }

    def save_state(self):
        with self.lock:
            return {
                "day": self.day,
                "minute": self.minute,
                "settings": dict(self.settings),
                "log": self.log[-LOG_CAP:],
                "crew": {cid: c.save_state() for cid, c in self.crew.items()},
                "pending_summary": self.pending_summary,
                "conversations": self.conversations[-CONVERSATION_CAP:],
                "day_story": self.day_story,
                "player": self.player.save_state(),
                "floor_items": [dict(thing) for thing in self.floor_items],
                "gifts_given": dict(self.gifts_given),
            }

    def load_state(self, state):
        with self.lock:
            self.day = int(state.get("day", self.day))
            self.minute = float(state.get("minute", self.minute))
            self.settings = clamp_settings(state.get("settings") or self.settings)
            self.log = list(state.get("log") or [])[-LOG_CAP:]
            self.pending_summary = state.get("pending_summary")
            self.conversations = list(state.get("conversations") or [])[
                -CONVERSATION_CAP:
            ]
            self.day_story = state.get("day_story")
            self.player.load_state(state.get("player"))
            # A save from before carrying existed keeps the freshly seeded floor.
            if "floor_items" in state:
                self.floor_items = [dict(t) for t in state.get("floor_items") or []]
            self.gifts_given = dict(state.get("gifts_given") or {})
            for cid, crew_state in (state.get("crew") or {}).items():
                if cid in self.crew:
                    self.crew[cid].load_state(crew_state)
            self.last_tick = time.monotonic()

    def update_settings(self, values):
        with self.lock:
            self.settings = clamp_settings(values or {}, base=self.settings)
            return dict(self.settings)
