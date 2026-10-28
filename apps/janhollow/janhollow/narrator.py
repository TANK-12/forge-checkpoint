"""The narrator: the big model, used rarely and never where anyone is waiting.

The 4B answers in about twenty seconds on this laptop (measured 2026-09-16:
21.4 s for 74 tokens), which is fine for something that runs once a station day
and unacceptable anywhere near a request. It runs on the director's worker
thread, and the world carries on ticking while it thinks.

It has three jobs:

* the day's event, chosen from the seeded templates in events/ and written up
  from what the crew actually did yesterday;
* the paragraph for a time-skip, which session 1 already records as
  `pending_summary` and until now showed as one bare sentence;
* nothing else. Memories and relationships are moved by the conversations
  themselves, in sim.py, because a model is not needed to know who talked to
  whom and making it guess would only add a way to be wrong.
"""

from __future__ import annotations

import random

from . import guard

SYSTEM = (
    "You are the narrator of Janhollow, a small, cosy space station with a crew of eight. "
    "You write warm, plain prose about ordinary life aboard: work, food, weather in the "
    "hydroponics, the hum of the reactor. Nothing violent, nothing cosmic, no emergencies "
    "unless you are told there is one. Never address the reader and never mention models, "
    "prompts or games."
)


def _event_fits(event, kinds, jobs):
    """An event's `needs` are location kinds or crew jobs that must be aboard.

    It means a barge event cannot fire on a station with no dock, without any
    code knowing what a dock is.
    """
    for need in event.get("needs") or ():
        if need not in kinds and need not in jobs:
            return False
    return True


def choose_event(world, rng: random.Random):
    events = list((world.content.get("types", {}).get("events") or {}).values())
    kinds = {loc.get("kind", "") for loc in world.station.locations.values()}
    jobs = {m.record.get("job", "").lower() for m in world.crew.values()}
    usable = [e for e in events if _event_fits(e, kinds, jobs)]
    if not usable:
        return None
    weights = [max(1, int(e.get("weight", 1))) for e in usable]
    return rng.choices(usable, weights=weights, k=1)[0]


def yesterday(world, limit=14):
    """What the crew actually did, in the narrator's own words later."""
    lines = []
    for entry in world.log[-80:]:
        if entry.get("kind") in ("move", "said"):
            lines.append(f"{entry['at']} {entry['text']}")
    return lines[-limit:]


def day_event(world, client, rng: random.Random):
    """The day's happening. Returns {headline, story, event} or None."""
    event = choose_event(world, rng)
    crew = ", ".join(
        f"{m.record.get('label')} ({m.record.get('job')})" for m in world.crew.values()
    )
    parts = [
        f"It is the morning of day {world.day} aboard Janhollow.",
        f"The crew: {crew}.",
    ]
    happened = yesterday(world)
    if happened:
        parts.append("Yesterday, in order:")
        parts += [f"  {line}" for line in happened]
    if event:
        parts.append(f"Today's happening: {event.get('prompt') or event.get('label')}")
    parts.append(
        'Write it up. Reply with JSON only: {"headline": "...", "story": "..."} — '
        "the headline at most eight words, the story two or three sentences."
    )
    try:
        raw = client.chat(
            "narrator",
            SYSTEM,
            "\n".join(parts),
            temperature=0.85,
            max_tokens=320,
            timeout=600.0,
            wait=90.0,
            seed=rng.randrange(1 << 30),
        )
    except Exception as exc:
        world.note_model_problem(str(exc))
        return None

    story, problems = guard.check(raw, {"speaker": "", "recent": []}, key="story")
    headline, _ = guard.check(raw, {"speaker": "", "recent": []}, key="headline")
    # The narrator writes prose, so the one-sentence rules do not apply to it:
    # only the rules about being real, English text are kept.
    problems = [p for p in problems if p.split(":")[0] in _PROSE_RULES]
    if problems or not story:
        world.record_rejection(
            raw, story, problems or ["empty: no story"], {"speaker": "narrator"}
        )
        return None
    return {
        "headline": headline or "A day aboard",
        "story": story,
        "event": (event or {}).get("id", ""),
    }


def time_skip_story(world, client, summary, rng: random.Random):
    """The paragraph for a time-skip: what you missed while you were away."""
    hours = max(1, round(summary.get("minutes", 0) / 60))
    crew = ", ".join(m.record.get("label", "") for m in world.crew.values())
    parts = [
        f"{hours} hours passed aboard Janhollow with nobody watching: "
        f"from {summary.get('from')} to {summary.get('to')}.",
        f"The crew aboard: {crew}.",
    ]
    happened = yesterday(world, limit=10)
    if happened:
        parts.append("The last things anyone saw:")
        parts += [f"  {line}" for line in happened]
    parts.append(
        'Say what happened in those hours. Reply with JSON only: {"story": "..."} — '
        "two or three quiet sentences, nothing dramatic."
    )
    try:
        raw = client.chat(
            "narrator",
            SYSTEM,
            "\n".join(parts),
            temperature=0.85,
            max_tokens=280,
            timeout=600.0,
            wait=90.0,
            seed=rng.randrange(1 << 30),
        )
    except Exception as exc:
        world.note_model_problem(str(exc))
        return None
    story, problems = guard.check(raw, {"speaker": "", "recent": []}, key="story")
    problems = [p for p in problems if p.split(":")[0] in _PROSE_RULES]
    if problems or not story:
        world.record_rejection(
            raw, story, problems or ["empty: no story"], {"speaker": "narrator"}
        )
        return None
    return story


# Which of the guard's rules apply to prose. The narrator is allowed several
# sentences and is allowed to name the crew, so the length and self-reference
# rules are dropped; being English, real text and not a stage direction is not
# negotiable for anything shown on screen.
_PROSE_RULES = {"empty", "no_letters", "not_english", "narration", "repetition"}


def name_the_arrival(world, client, rng):
    """Who you are. The owner chose "the narrator names you" over typing a name.

    Called once, shortly after you step in, and never on the path of anything
    you are waiting for -- you are aboard and walking around as "the new
    arrival" while this runs.
    """
    crew = ", ".join(
        f"{m.record.get('label')} ({m.record.get('job')})" for m in world.crew.values()
    )
    user = (
        f"Someone new has just come aboard Janhollow through the docking ring on day {world.day}. "
        f"The crew are: {crew}. "
        "Invent who they are: a name, what they have come aboard to do, and one sentence "
        "about their arrival. Keep it ordinary and warm — a person joining a small station, "
        "not a chosen one. "
        'Reply with JSON only: {"name": "...", "role": "...", "arrival": "..."} — '
        "the name two words at most, the role a few words, the arrival one sentence."
    )
    try:
        raw = client.chat(
            "narrator",
            SYSTEM,
            user,
            temperature=0.9,
            max_tokens=220,
            timeout=600.0,
            wait=90.0,
            seed=rng.randrange(1 << 30),
        )
    except Exception as exc:
        world.note_model_problem(str(exc))
        return None
    name, _ = guard.check(raw, {"speaker": "", "recent": []}, key="name")
    role, _ = guard.check(raw, {"speaker": "", "recent": []}, key="role")
    arrival, problems = guard.check(raw, {"speaker": "", "recent": []}, key="arrival")
    problems = [p for p in problems if p.split(":")[0] in _PROSE_RULES]
    if not name or problems:
        world.record_rejection(
            raw, name, problems or ["empty: no name"], {"speaker": "narrator"}
        )
        return None
    return {"name": name[:40], "role": role[:60], "arrival": arrival}
