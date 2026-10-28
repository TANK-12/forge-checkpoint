"""Crew small talk without a model: short written lines from a registry.

With Voices off, or Jan not answering, the station used to go silent: the crew
walked their day and said nothing, which made it a clock and a list (app review
JH-F4, 2026-10-09). This module is the station's own voice when no model is
talking. It never calls Jan and loads nothing.

The lines are data. Every file in `barks/` (shipped with the app) and in
`~/ForgeGameData/janhollow/barks/` (yours, optional) is one set:

    {
      "label": "Galley talk",
      "jobs": ["cook"],               speaker's job; empty means anyone
      "rooms": ["galley", "social"],  room ids or room kinds; empty means anywhere
      "hours": ["morning"],           morning, day, evening, night; empty means any time
      "weight": 1,                    how often this set is picked among those that fit
      "exchanges": [
        {"say": "Hungry, {listener}?", "replies": ["Always.", "Later, thanks."]}
      ],
      "hello": ["There's bread on, {you}."]
    }

`say` is the speaker's line and one of `replies` is the listener's answer.
`hello` is what the speaker says to you in passing. Lines may use {listener},
{speaker}, {you}, {room} and {time}; a name is the first name. A file in your
folder with the same name as a shipped one replaces it, and a new name adds a
set, so new talk is one new file and nothing else.
"""

from __future__ import annotations

import json
import os
import re

from . import content

SHIPPED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "barks"
)

# Four parts of the day, by station hour. Data, so a fifth is one entry.
PARTS_OF_DAY = (
    ("night", 0, 5),
    ("morning", 5, 11),
    ("day", 11, 17),
    ("evening", 17, 22),
    ("night", 22, 24),
)

# How many openers to keep from repeating back to back.
RECENT = 12

_FIELD = re.compile(r"\{(\w+)\}")


def folders():
    """Shipped sets first, then yours, so yours win on a shared name."""
    return [SHIPPED_DIR, os.path.join(content.data_root(), "barks")]


def _strings(value):
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _lower(value):
    return [item.lower() for item in _strings(value)]


def _clean(raw, name):
    """One set with every bad part dropped, plus what was wrong with it."""
    problems = []
    if not isinstance(raw, dict):
        return None, [f"barks/{name}: must be a JSON object"]
    exchanges = []
    for index, item in enumerate(raw.get("exchanges") or []):
        say = item.get("say") if isinstance(item, dict) else None
        if not isinstance(say, str) or not say.strip():
            problems.append(f"barks/{name}: exchange {index + 1} has no say line")
            continue
        exchanges.append({"say": say.strip(), "replies": _strings(item.get("replies"))})
    hello = _strings(raw.get("hello"))
    if not exchanges and not hello:
        problems.append(f"barks/{name}: has no exchanges and no hello lines")
        return None, problems
    hours = _lower(raw.get("hours"))
    known = {part for part, _, _ in PARTS_OF_DAY}
    for hour in hours:
        if hour not in known:
            problems.append(f"barks/{name}: unknown hour {hour!r}")
    weight = raw.get("weight", 1)
    if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight < 0:
        problems.append(f"barks/{name}: weight must be a number, 0 or more")
        weight = 1
    entry = {
        "id": name,
        "label": str(raw.get("label") or name),
        "jobs": _lower(raw.get("jobs")),
        "rooms": _lower(raw.get("rooms")),
        "hours": [hour for hour in hours if hour in known],
        "weight": float(weight),
        "exchanges": exchanges,
        "hello": hello,
    }
    return entry, problems


def load(dirs=None):
    """Every set from every folder: {"sets": {id: set}, "problems": [...]}.

    A file that does not parse is a problem, not a crash, the same rule as the
    rest of the station's content."""
    sets, problems = {}, []
    for folder in dirs if dirs is not None else folders():
        if not os.path.isdir(folder):
            continue
        for file_name in sorted(os.listdir(folder)):
            if not file_name.endswith(".json"):
                continue
            name = file_name[: -len(".json")]
            try:
                with open(os.path.join(folder, file_name), encoding="utf-8") as handle:
                    raw = json.load(handle)
            except (OSError, ValueError) as exc:
                problems.append(f"barks/{name}: could not be read ({exc})")
                continue
            entry, found = _clean(raw, name)
            problems += found
            if entry:
                sets[name] = entry
    return {"sets": sets, "problems": problems}


def part_of_day(minute):
    hour = (float(minute) % 1440.0) / 60.0
    for part, start, end in PARTS_OF_DAY:
        if start <= hour < end:
            return part
    return "day"


def first_name(label):
    return (str(label or "").split() or [""])[0]


def fill(text, values):
    """Put names into a line. An unknown {field} is left as written, so a typo
    in a file shows on screen instead of crashing the director."""
    return _FIELD.sub(lambda m: str(values.get(m.group(1), m.group(0))), text)


def _room(world, member):
    location = world.station.locations.get(member.location, {})
    return (member.location or "").lower(), (location.get("kind") or "").lower()


def fits(entry, job, room_id, room_kind, part):
    if entry["jobs"] and job not in entry["jobs"]:
        return False
    if (
        entry["rooms"]
        and room_id not in entry["rooms"]
        and room_kind not in entry["rooms"]
    ):
        return False
    if entry["hours"] and part not in entry["hours"]:
        return False
    return True


def names(line, people):
    """Whether a line as written names one of `people` (first names, whole
    words). Someone does not talk about themselves in the third person, or
    about the person they are talking to: "Ask Mira" is not said to Mira."""
    return any(
        person and re.search(rf"\b{re.escape(person)}\b", line) for person in people
    )


def _candidates(registry, world, member, field):
    job = (member.record.get("job") or "").lower()
    room_id, room_kind = _room(world, member)
    part = part_of_day(world.minute)
    return [
        entry
        for entry in registry["sets"].values()
        if entry[field]
        and entry["weight"] > 0
        and fits(entry, job, room_id, room_kind, part)
    ]


def your_name(world):
    """Your first name, or "newcomer" while you are still "the new arrival"
    (the narrator names you, and with no model nobody does)."""
    name = str(world.player.name or "")
    if not name or name.lower().startswith("the "):
        return "newcomer"
    return first_name(name)


def _values(world, speaker, listener):
    location = world.station.locations.get(speaker.location, {})
    return {
        "speaker": first_name(speaker.record.get("label", speaker.id)),
        "listener": listener,
        "you": your_name(world),
        "room": (location.get("label") or "station").lower(),
        "time": world.clock_now(),
    }


def exchange(registry, world, speaker, listener, rng, recent=()):
    """(written, opener, reply) for two crew in the same room, or None when
    nothing fits. `written` is the opener as it stands in the file, for the
    caller's `recent` list; openers in `recent` are skipped while anything else
    fits. The reply is "" when the exchange has none."""
    sets = _candidates(registry, world, speaker, "exchanges")
    if not sets:
        return None
    me = first_name(speaker.record.get("label", speaker.id))
    them = first_name(listener.record.get("label", listener.id))
    options = [
        (entry, item)
        for entry in sets
        for item in entry["exchanges"]
        if not names(item["say"], (me, them))
    ]
    if not options:
        return None
    fresh = [pair for pair in options if pair[1]["say"] not in recent]
    pool = fresh or options
    weights = [entry["weight"] / len(entry["exchanges"]) for entry, _ in pool]
    entry, item = rng.choices(pool, weights=weights, k=1)[0]
    opener = fill(item["say"], _values(world, speaker, them))
    replies = [line for line in item["replies"] if not names(line, (me, them))]
    reply = ""
    if replies:
        reply = fill(rng.choice(replies), _values(world, listener, me))
    return item["say"], opener, reply


def hello(registry, world, member, rng):
    """What `member` says to you in passing, or None when nothing fits."""
    sets = _candidates(registry, world, member, "hello")
    if not sets:
        return None
    me = first_name(member.record.get("label", member.id))
    lines = [
        (entry, line)
        for entry in sets
        for line in entry["hello"]
        if not names(line, (me,))
    ]
    if not lines:
        return None
    weights = [entry["weight"] / len(entry["hello"]) for entry, _ in lines]
    _, line = rng.choices(lines, weights=weights, k=1)[0]
    return fill(line, _values(world, member, your_name(world)))
