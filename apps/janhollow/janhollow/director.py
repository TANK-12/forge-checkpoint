"""When anything gets said: one background thread, and the only caller of Jan.

The simulation ticks ten times a second and must never wait for a model, so
every model call happens here instead, on a thread of its own. The world is
only ever touched through its own lock, so a conversation arriving mid-tick
cannot catch a crew member half-moved.

What it decides, in priority order:

1. A time-skip that is waiting for its paragraph -- you are standing there
   reading "6 hours passed while you were away", so this comes first.
2. A new station day that has not been narrated.
3. A conversation, if one is due.

What stops it:

* the away mode, through `world.models_allowed()`. "Idle when closed" means the
  crew keep to their day with the tab shut and nobody speaks until you return;
  that rule lives in sim.py and is simply obeyed here.
* the chatter setting, including "off", which is a level like any other.
* Jan being absent. Failures back off from 5 seconds to two minutes rather than
  hammering a server that is not there, and recover on the first success.

When no model is talking -- Voices off, or Jan backing off -- the crew still say
short written lines to each other and to you, from the registry in barks.py, at
the "barks" level in the settings. Those never call Jan.
"""

from __future__ import annotations

import random
import threading
import time

from . import barks, chatter, narrator, player as player_module

# How long between checks. Short enough that a due conversation starts promptly,
# long enough to cost nothing.
BEAT = 1.0
BACKOFF_START = 5.0
BACKOFF_MAX = 120.0
# A written reply comes this long after the line it answers, so the two read
# as a conversation rather than as two bubbles at once.
REPLY_GAP = 2.4


class Director:
    def __init__(self, world, client, seed=None, log=print, written=None):
        self.world = world
        self.client = client
        self.log = log
        self.rng = random.Random(seed)
        # The written lines, read once per world (Re-read content rebuilds it).
        self.written = barks.load() if written is None else written
        self.next_bark = 0.0
        self.pending_reply = None  # (when, who answers, who they answer, line)
        self.recent_barks: list[str] = []
        self.next_conversation = 0.0
        self.next_greeting = 0.0
        self.backoff = 0.0
        self.failures = 0
        self.busy = False
        self.last_reason = "starting"
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # --- when to speak ------------------------------------------------------

    def interval(self):
        """Seconds between conversations, from the chatter setting. Zero means
        the crew are quiet on purpose."""
        from . import sim

        level = sim.CHATTER_LEVELS.get(
            self.world.settings.get("chatter"), sim.CHATTER_LEVELS["moderate"]
        )
        per_minute = float(level.get("per_minute", 1.0))
        if per_minute <= 0:
            return 0.0
        return 60.0 / per_minute

    def due(self, now):
        gap = self.interval()
        if gap <= 0:
            return False
        if not self.next_conversation:
            # Spread the first one out a little so the station does not open
            # with everybody talking at once.
            self.next_conversation = now + self.rng.uniform(2.0, gap)
            return False
        return now >= self.next_conversation

    def bark_interval(self):
        """Seconds between written exchanges, from the barks setting; zero is
        off."""
        from . import sim

        level = sim.BARK_LEVELS.get(
            self.world.settings.get("barks"), sim.BARK_LEVELS["some"]
        )
        per_minute = float(level.get("per_minute", 0.0))
        return 60.0 / per_minute if per_minute > 0 else 0.0

    def schedule_next(self, now):
        gap = self.interval()
        jitter = self.rng.uniform(0.75, 1.35)
        self.next_conversation = now + max(5.0, gap * jitter)

    # --- one pass -----------------------------------------------------------

    def step(self, now=None):
        """One decision. Returns what it did, which is what the tests assert on."""
        now = time.monotonic() if now is None else now
        if self.reply_due(now):
            return self.deliver_reply()
        if self.backoff and now < self.backoff:
            # Jan is not answering: the written lines fill the silence.
            return self.bark(now) or "backing off"
        if self.interval() <= 0:
            # Crew chatter is off, and that means off: no conversations, no
            # narrator, nothing loaded. The two buttons in the settings pane
            # still work, because pressing one is asking for it. The written
            # lines are not a model, so they carry on at their own level.
            self.last_reason = "voices are off"
            return self.bark(now) or "voices off"
        if not self.world.models_allowed():
            self.last_reason = "away mode says no models right now"
            return "not allowed"

        summary = self.world.pending_summary
        if summary and summary.get("needs_narrator"):
            return self.run(self.narrate_skip, "time-skip summary")
        if self.world.take_new_day():
            return self.run(self.narrate_day, "the day's event")
        player = self.world.player
        if player.aboard and not player.named:
            return self.run(self.name_the_player, "naming the new arrival")
        if player.aboard and now >= self.next_greeting:
            # Someone you walked past says hello. Spaced out on its own timer so
            # standing in a busy mess hall is not a wall of greetings.
            self.next_greeting = now + self.rng.uniform(25.0, 70.0)
            if player_module.bystanders(self.world):
                return self.run(self.greet, "a greeting")
        if self.due(now):
            self.schedule_next(now)
            return self.run(self.talk, "a conversation")
        return "waiting"

    # --- written lines, when no model is talking ------------------------------

    def bark(self, now):
        """One written line if one is due, else None. Never calls Jan."""
        gap = self.bark_interval()
        if gap <= 0 or not self.written["sets"] or not self.world.barks_allowed():
            return None
        player = self.world.player
        if player.aboard and now >= self.next_greeting:
            self.next_greeting = now + self.rng.uniform(25.0, 70.0)
            near = player_module.bystanders(self.world)
            if near:
                member = self.rng.choice(near)
                line = barks.hello(self.written, self.world, member, self.rng)
                if line:
                    self.world.say(member.id, line, chatter.BUBBLE_SECONDS, True)
                    return "a written greeting"
        if not self.next_bark:
            # Like the conversations: spread out the first one.
            self.next_bark = now + self.rng.uniform(2.0, gap)
            return None
        if now < self.next_bark:
            return None
        self.next_bark = now + max(5.0, gap * self.rng.uniform(0.75, 1.35))
        pair = chatter.pick_pair(self.world, self.rng)
        if not pair:
            return None
        speaker, listener = pair
        picked = barks.exchange(
            self.written, self.world, speaker, listener, self.rng, self.recent_barks
        )
        if not picked:
            return None
        written, opener, reply = picked
        self.recent_barks = (self.recent_barks + [written])[-barks.RECENT :]
        self.world.say(speaker.id, opener, chatter.BUBBLE_SECONDS, True)
        if reply:
            self.pending_reply = (now + REPLY_GAP, listener.id, speaker.id, reply)
        return "a written line"

    def reply_due(self, now):
        return bool(self.pending_reply) and now >= self.pending_reply[0]

    def deliver_reply(self):
        """The answer to a written line, if both are still standing together
        and awake; somebody's schedule may have moved them on."""
        if not self.pending_reply:
            return None
        _, who, to, line = self.pending_reply
        self.pending_reply = None
        member = self.world.crew.get(who)
        other = self.world.crew.get(to)
        if not member or not other or member.moving or member.saying:
            return "a written reply dropped"
        together = member.deck == other.deck and member.location == other.location
        if not together or not player_module.awake(member):
            return "a written reply dropped"
        self.world.say(member.id, line, chatter.BUBBLE_SECONDS, True)
        return "a written reply"

    def run(self, job, what):
        self.busy = True
        self.last_reason = what
        try:
            job()
            self.failures = 0
            self.backoff = 0.0
            return what
        except Exception as exc:  # a model failure must never stop the station
            self.failures += 1
            wait = min(BACKOFF_MAX, BACKOFF_START * (2 ** (self.failures - 1)))
            self.backoff = time.monotonic() + wait
            self.world.note_model_problem(f"{type(exc).__name__}: {exc}")
            self.log(f"[janhollow] {what} failed ({exc}); waiting {wait:.0f}s")
            return f"{what} failed"
        finally:
            self.busy = False

    # --- the jobs -----------------------------------------------------------

    def talk(self):
        chatter.converse(self.world, self.client, self.rng)

    def narrate_day(self):
        story = narrator.day_event(self.world, self.client, self.rng)
        if story:
            self.world.set_day_story(story)
            self.world.remember_everyone(story["story"])

    def name_the_player(self):
        """Who you turned out to be. Runs once, after you are already walking
        around, because a thirty-second model call is no way to start a game."""
        found = narrator.name_the_arrival(self.world, self.client, self.rng)
        player = self.world.player
        with self.world.lock:
            player.named = True  # one attempt; a failure leaves you unnamed
            if found:
                player.name = found["name"]
                player.role = found.get("role", "")
                player.arrival = found.get("arrival", "")
                self.world.model_status["narrator_runs"] += 1
                self.world.note(
                    f"{player.name} came aboard — {player.role}. {player.arrival}",
                    kind="story",
                )

    def greet(self):
        near = player_module.bystanders(self.world)
        if not near:
            return
        member = self.rng.choice(near)
        line = chatter.greet_player(self.world, self.client, member, self.rng)
        if line:
            self.world.say(member.id, line, chatter.BUBBLE_SECONDS)

    def answer_player(self, text):
        """Your line, and one crew member's answer. Runs on the request rather
        than the worker: you are standing there waiting for it."""
        member = player_module.nearest_crew(self.world)
        if not member:
            return None
        self.world.say(self.world.player.id, text, chatter.BUBBLE_SECONDS)
        line, was_fallback = chatter.reply_to_player(
            self.world, self.client, member, text, self.rng
        )
        self.world.say(member.id, line, chatter.BUBBLE_SECONDS)
        with self.world.lock:
            warmth = int(member.relationships.get(self.world.player.id, 0))
            member.relationships[self.world.player.id] = min(3, warmth + 1)
            member.memories.append(f"{self.world.player.name} said: {text}")
            del member.memories[:-12]
        return {
            "who": member.record.get("label", member.id),
            "id": member.id,
            "line": line,
            "fallback": was_fallback,
        }

    def narrate_skip(self):
        summary = dict(self.world.pending_summary or {})
        story = narrator.time_skip_story(self.world, self.client, summary, self.rng)
        with self.world.lock:
            current = self.world.pending_summary
            if not current:
                return
            current["needs_narrator"] = False
            if story:
                current["story"] = story
                self.world.model_status["narrator_runs"] += 1
                self.world.note(story, kind="story")

    # --- the thread ---------------------------------------------------------

    def start(self):
        if self._thread:
            return self._thread

        def loop():
            while not self._stop.wait(BEAT):
                try:
                    self.step()
                except Exception as exc:
                    self.log(f"[janhollow] director: {type(exc).__name__}: {exc}")

        self._thread = threading.Thread(
            target=loop, daemon=True, name="janhollow-voices"
        )
        self._thread.start()
        return self._thread

    def stop(self):
        self._stop.set()

    def status(self):
        return {
            "busy": self.busy,
            "doing": self.last_reason,
            "failures": self.failures,
            "backing_off": max(0.0, self.backoff - time.monotonic()),
            "seconds_to_next": max(0.0, self.next_conversation - time.monotonic()),
            "written_sets": len(self.written["sets"]),
            "written_problems": list(self.written["problems"]),
            "jan": dict(self.client.stats),
        }
