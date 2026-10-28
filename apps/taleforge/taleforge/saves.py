"""Saved games: one JSON file per game under the app's data folder. Nothing
is ever deleted; "move to trash" moves the file into trash/."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

DATA = Path(
    os.environ.get("TALEFORGE_DATA") or Path.home() / ".local/share/forge/taleforge"
)
SID = re.compile(r"^[a-z0-9]{8,32}$")
LOCK = threading.RLock()


class SaveError(ValueError):
    pass


def folder() -> Path:
    d = DATA / "saves"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path(sid: str) -> Path:
    if not SID.match(sid or ""):
        raise SaveError("no such save")
    return folder() / f"{sid}.json"


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def write(sid: str, state: dict) -> None:
    with LOCK:
        state["updated"] = time.time()
        p = path(sid)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False))
        tmp.replace(p)


def read(sid: str) -> dict:
    with LOCK:
        p = path(sid)
        if not p.exists():
            raise SaveError("no such save")
        return json.loads(p.read_text())


def listing() -> list[dict]:
    out = []
    for p in folder().glob("*.json"):
        try:
            s = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        pc = s.get("pc", {})
        out.append(
            {
                "id": p.stem,
                "campaign": s.get("campaign", ""),
                "name": pc.get("name", "?"),
                "class": pc.get("class", ""),
                "level": pc.get("level", 1),
                "location": s.get("location", ""),
                "day": s.get("day", 1),
                "ending": s.get("ending"),
                "updated": s.get("updated", 0),
            }
        )
    return sorted(out, key=lambda x: -x["updated"])


def patch_entry(sid: str, eid: str, text: str | None, note: str) -> bool:
    """Put Jan's retelling into a logged entry (or mark it settled)."""
    with LOCK:
        try:
            s = read(sid)
        except SaveError:
            return False
        for e in reversed(s.get("log", [])):
            if e.get("id") == eid:
                e["pending"] = False
                e["jan_note"] = note
                if text:
                    e["jan_text"] = text
                write(sid, s)
                return True
    return False


def trash(sid: str) -> Path:
    with LOCK:
        p = path(sid)
        if not p.exists():
            raise SaveError("no such save")
        d = DATA / "trash"
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"{sid}-{int(time.time())}.json"
        p.replace(dest)
        return dest


def read_settings() -> dict:
    try:
        return json.loads((DATA / "settings.json").read_text())
    except (OSError, ValueError):
        return {}


def write_settings(changes: dict) -> dict:
    current = {**read_settings(), **changes}
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "settings.json").write_text(json.dumps(current, indent=2))
    return current
