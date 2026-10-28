"""Save slots on disk.

Written through a temporary file and replaced atomically, because more than one
Forge session can be open against this home directory at once and a half-written
save is worse than no save.
"""

import json
import os
import time

from . import config


def _path(slot):
    safe = "".join(c for c in str(slot) if c.isalnum() or c in "-_")[:40] or "slot"
    return os.path.join(config.SAVES_DIR, f"{safe}.json")


def list_saves():
    """Every readable save, the most recently played first.

    They used to come back in file-name order ("valley-1234" before
    "valley-99"), so the valley you played last night could sit anywhere in the
    list."""
    config.ensure_dirs()
    out = []
    for name in sorted(os.listdir(config.SAVES_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(config.SAVES_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        out.append(
            {
                "slot": os.path.splitext(name)[0],
                "name": data.get("name", "Emberfield"),
                "day": data.get("day", 1),
                "death_rule": data.get("death_rule", "character"),
                "saved_at": data.get("saved_at"),
                "seed": data.get("world", {}).get("seed"),
                "season": (data.get("clock") or {}).get("season"),
                "gold": data.get("gold"),
            }
        )
    out.sort(key=_newest_first)
    return out


def _newest_first(entry):
    stamp = entry.get("saved_at")
    return -stamp if isinstance(stamp, (int, float)) else 0


def load(slot):
    path = _path(slot)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def save(slot, data):
    config.ensure_dirs()
    payload = dict(data)
    payload["saved_at"] = time.time()
    path = _path(slot)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))
    os.replace(tmp, path)
    return path


def delete(slot):
    path = _path(slot)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False
