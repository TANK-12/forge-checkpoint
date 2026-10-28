"""Crew talking to each other, on the small model.

One line of dialogue is one request to the 0.8B, which answers in about
0.8 seconds. A conversation is two to four of those, alternating, with each
speaker shown what has been said so far.

The prompt shape was chosen by measurement rather than taste (2026-09-16,
four samples each): asking for JSON and asking the model to speak in the first
person as a named person both helped; adding a worked example made it copy the
example verbatim one time in four, so there is no example in the prompt and
`guard.CHECKS["echo"]` catches it anyway.

Nothing here decides when to talk -- that is director.py -- and nothing here
writes to the world except through `world.say` and `world.record_conversation`,
so a conversation is always applied under the world's own lock.
"""

from __future__ import annotations

import random

from . import guard
from . import player as player_module

# How warm the pair are, in words the model can use. Relationships are small
# integers in the crew files and drift by one per conversation.
WARMTH = {
    0: "You have barely spoken before.",
    1: "You get on well enough.",
    2: "You are friends.",
    3: "You are close friends.",
}

TONE = (
    "The mood aboard Janhollow is easy and domestic: small talk, work, food, "
    "the hum of the station. Nothing dramatic is happening."
)

# Three turns is where a 0.8B is still saying new things. At four it starts
# reciting the conversation back to itself, measured on 2026-09-16.
MAX_TURNS = 3
MIN_TURNS = 2
# One line is short. A bubble stays up long enough to read it twice.
BUBBLE_SECONDS = 7.0


def warmth(score: int) -> str:
    return WARMTH.get(max(0, min(3, int(score or 0))), WARMTH[3])


def system_prompt(world, speaker, listener) -> str:
    record = speaker.record
    where = world.station.locations.get(speaker.location, {})
    return (
        f"You are {record.get('label', speaker.id)}, the "
        f"{record.get('job', 'crew member').lower()} aboard the small space station Janhollow. "
        f"{record.get('personality', '')} "
        f"You are in the {where.get('label', 'station')}, {speaker.activity or 'at work'}. "
        f"You are speaking to {listener.record.get('label', listener.id)}, the "
        f"{listener.record.get('job', 'crew member').lower()}. "
        f"{warmth(record.get('relationships', {}).get(listener.id, 0))} "
        f"{TONE} "
        'Reply with JSON only, in this exact shape: {"line": "..."} '
        "The line is one sentence you say out loud, at most 18 words, in English. "
        "No narration, no stage directions, no name label, and never say your own name."
    )


def user_prompt(world, speaker, listener, said) -> str:
    parts = [f"It is {world.clock_now()} on day {world.day}."]
    memory = (speaker.memories or [])[-1:]
    if memory:
        parts.append(f"You remember: {memory[0]}")
    if said:
        parts.append("So far:")
        for who, line in said:
            parts.append(f"  {who}: {line}")
        parts.append(
            f"Reply to what {listener.record.get('label', listener.id)} just said. "
            "Say something new: do not repeat their words back to them."
        )
    else:
        parts.append(f"Say one thing to {listener.record.get('label', listener.id)}.")
    return "\n".join(parts)


def pick_pair(world, rng: random.Random):
    """Two crew in the same room, both standing still, awake and neither
    mid-sentence.

    Returns (speaker, listener) or None. Crew who are walking are left alone:
    a bubble over someone crossing a corridor reads as a bug. So are crew who
    are asleep: two people asleep in the same quarters used to chat.
    """
    by_room: dict[tuple[str, str], list] = {}
    for member in world.crew.values():
        if member.moving or member.saying or not member.location:
            continue
        if not player_module.awake(member):
            continue
        by_room.setdefault((member.deck, member.location), []).append(member)
    rooms = [people for people in by_room.values() if len(people) >= 2]
    if not rooms:
        return None
    people = rng.choice(rooms)
    pair = rng.sample(people, 2)
    return pair[0], pair[1]


def one_line(client, world, speaker, listener, said, rng, role="chatter"):
    """One validated line, or None. Retries once, then gives up quietly."""
    context = {
        "speaker": speaker.record.get("label", speaker.id),
        "listener": listener.record.get("label", listener.id),
        "where": speaker.location,
        "recent": [line for _, line in said],
    }
    system = system_prompt(world, speaker, listener)
    user = user_prompt(world, speaker, listener, said)
    for attempt in range(2):
        try:
            raw = client.chat(
                role,
                system,
                (
                    user
                    if attempt == 0
                    else user + "\nKeep it short and say something new."
                ),
                temperature=0.9 if attempt == 0 else 1.0,
                # Room to finish the sentence and close the JSON. The guard
                # caps the length; the token limit only ever truncated it.
                max_tokens=120,
                seed=rng.randrange(1 << 30),
            )
        except Exception as exc:  # JanError, or anything urllib raises
            world.note_model_problem(str(exc))
            return None
        line, problems = guard.check(raw, context)
        if not problems:
            return line
        world.record_rejection(raw, line, problems, context)
    return None


def converse(world, client, rng: random.Random):
    """One conversation, applied to the world as it happens.

    Lines are shown the moment they arrive rather than at the end, because a
    line takes about a second and holding them back makes the station feel
    laggy rather than alive.
    """
    pair = pick_pair(world, rng)
    if not pair:
        return None
    speaker, listener = pair
    turns = rng.randint(MIN_TURNS, MAX_TURNS)
    said: list[tuple[str, str]] = []
    talkers = (speaker, listener)
    for turn in range(turns):
        who = talkers[turn % 2]
        other = talkers[(turn + 1) % 2]
        if who.location != other.location or who.moving or other.moving:
            break  # somebody's schedule moved them on mid-conversation
        line = one_line(client, world, who, other, said, rng)
        if line is None:
            break
        said.append((who.record.get("label", who.id), line))
        world.say(who.id, line, BUBBLE_SECONDS)
    if not said:
        return None
    return world.record_conversation(speaker.id, listener.id, said)


# --- talking to you ---------------------------------------------------------

# What someone says when there is no model to ask. The owner chose this over
# silence: "They say something simple" — the station should never go mute just
# because Jan is off. Picked by job so it is at least in character.
FALLBACKS = {
    "cook": ["There is food if you want it.", "Mind the hot pan."],
    "station chief": ["Settling in?", "Everything in order, I hope."],
    "chief engineer": ["Busy. Mind the cables.", "She is running sweet today."],
    "botanist": ["The tomatoes are nearly there.", "Quiet in here, isn't it."],
    "medic": ["You look well enough.", "Come by the medbay if anything aches."],
    "comms officer": ["Nothing on the relay today.", "Quiet on all channels."],
    "dock hand": ["Watch the crates.", "Barge is due, or so they tell me."],
    "navigator, night watch": ["Odd hour to be up.", "The drift is steady."],
}
DEFAULT_FALLBACK = ["Hello.", "Busy just now.", "Good to see you."]


def fallback_line(member, rng):
    job = (member.record.get("job") or "").lower()
    return rng.choice(FALLBACKS.get(job, DEFAULT_FALLBACK))


def player_system_prompt(world, speaker):
    """Speaking to the player. Deliberately close to the crew-to-crew prompt:
    the same voice, the same shape, so a model that behaves for one behaves for
    the other."""
    record = speaker.record
    where = world.station.locations.get(speaker.location, {})
    player = world.player
    warmth_of = record.get("relationships", {}).get(player.id, 0)
    return (
        f"You are {record.get('label', speaker.id)}, the "
        f"{record.get('job', 'crew member').lower()} aboard the small space station Janhollow. "
        f"{record.get('personality', '')} "
        f"You are in the {where.get('label', 'station')}, {speaker.activity or 'at work'}. "
        f"You are speaking to {player.name}"
        f"{', ' + player.role if player.role else ', who arrived recently'}. "
        f"{warmth(warmth_of)} "
        f"{TONE} "
        'Reply with JSON only, in this exact shape: {"line": "..."} '
        "The line is one sentence you say out loud, at most 18 words, in English. "
        "No narration, no stage directions, no name label, and never say your own name."
    )


def reply_to_player(world, client, member, text, rng):
    """One crew member's answer to something you said. Falls back to a written
    line rather than going silent when Jan is not there."""
    context = {
        "speaker": member.record.get("label", member.id),
        "listener": world.player.name,
        "where": member.location,
        "recent": [line for _, line in _recent_with(world, member)],
    }
    memory = (member.memories or [])[-1:]
    parts = [f"It is {world.clock_now()} on day {world.day}."]
    if memory:
        parts.append(f"You remember: {memory[0]}")
    parts.append(f"{world.player.name} says to you: {text}")
    parts.append(
        "Reply to them. Say something new, and do not repeat their words back."
    )
    system = player_system_prompt(world, member)
    for attempt in range(2):
        try:
            raw = client.chat(
                "chatter",
                system,
                "\n".join(parts),
                temperature=0.9 if attempt == 0 else 1.0,
                max_tokens=120,
                seed=rng.randrange(1 << 30),
            )
        except Exception as exc:
            world.note_model_problem(str(exc))
            return fallback_line(member, rng), True
        line, problems = guard.check(raw, context)
        if not problems:
            return line, False
        world.record_rejection(raw, line, problems, context)
    return fallback_line(member, rng), True


def greet_player(world, client, member, rng):
    """An unprompted hello from someone you walked past. The owner picked "they
    greet you in passing" over being ignored until spoken to."""
    context = {
        "speaker": member.record.get("label", member.id),
        "listener": world.player.name,
        "recent": [],
    }
    system = player_system_prompt(world, member)
    user = (
        f"It is {world.clock_now()} on day {world.day}. "
        f"{world.player.name} has just walked past you. "
        "Say one short thing to them in passing: a greeting, a remark, "
        "something you happen to be thinking about."
    )
    try:
        raw = client.chat(
            "chatter",
            system,
            user,
            temperature=1.0,
            max_tokens=110,
            seed=rng.randrange(1 << 30),
        )
    except Exception as exc:
        world.note_model_problem(str(exc))
        return None
    line, problems = guard.check(raw, context)
    if problems:
        world.record_rejection(raw, line, problems, context)
        return None
    return line


def _recent_with(world, member):
    """The last few lines exchanged with this crew member, so a reply does not
    repeat the one before it."""
    out = []
    for conversation in world.conversations[-3:]:
        if member.id in conversation.get("speakers", []):
            out += [(entry["who"], entry["line"]) for entry in conversation["lines"]]
    return out[-4:]
