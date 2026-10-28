"""Save slots for the station, in ~/ForgeGameData/janhollow/saves/.

A save is deliberately small: the clock, the settings, where each crew member
is, and the tail of the log. The station itself is never stored, because it is
built from the deck and room files every time -- so editing a room changes an
old save's station too, which is what you want while a game is being built.

The autosave slot is what the backend writes as it runs and reads when it
starts, so closing Forge and opening it again tomorrow finds the same day.
"""

import json
import os
import time

from . import content

AUTOSAVE = "auto"


def saves_dir():
    return os.path.join(content.data_root(), "saves")


# A file name has room for 255 bytes, and writing adds ".json.tmp"; a slot name
# longer than that was a 500. Capped in characters and in UTF-8 bytes, since
# one character can take four.
SLOT_MAX = 64
SLOT_MAX_BYTES = 200


def path_for(slot):
    safe = "".join(ch for ch in str(slot) if ch.isalnum() or ch in "-_")
    safe = safe[:SLOT_MAX]
    while len(safe.encode("utf-8")) > SLOT_MAX_BYTES:
        safe = safe[:-1]
    safe = safe or "slot"
    return os.path.join(saves_dir(), f"{safe}.json")


def write(slot, state):
    os.makedirs(saves_dir(), exist_ok=True)
    payload = dict(state, slot=slot, saved_at=time.time())
    target = path_for(slot)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, target)
    return target


def read(slot):
    try:
        with open(path_for(slot), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def delete(slot):
    try:
        os.remove(path_for(slot))
        return True
    except OSError:
        return False


def listing():
    directory = saves_dir()
    if not os.path.isdir(directory):
        return []
    rows = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        state = read(os.path.splitext(name)[0]) or {}
        rows.append(
            {
                "slot": state.get("slot", os.path.splitext(name)[0]),
                "day": state.get("day", 1),
                "clock": state.get("clock", ""),
                "minute": state.get("minute", 0),
                "saved_at": state.get("saved_at", 0),
                "crew": len(state.get("crew") or {}),
            }
        )
    return rows
