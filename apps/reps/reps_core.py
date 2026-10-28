"""Reps: a log for workouts and habits, with streaks and simple charts.

A **tracker** is one thing to keep up (bench press, running, water, no
sugar). Its kind comes from `kinds.json`, a registry: each kind names the
fields an entry holds (reps and weight, minutes and distance, an amount,
or nothing for a plain yes/no habit), the default goal in days a week, and
which field the chart adds up (none means it counts entries). A new kind is
one entry there.

An **entry** is one logged set, run or tick, on one day. A day counts for
the streak when it has at least one entry. With a goal of 7 days a week the
streak is days in a row; with a smaller goal it is weeks in a row that met
the goal (weeks start on Monday). Today not done yet (or this week not met
yet) does not break a streak; the day or week before does.

Trackers are archived, never deleted. Entries can be removed one at a time,
for something logged by mistake.

Data: `~/.local/share/forge/reps/reps.json` (REPS_DATA_DIR moves it),
written whole through a temporary file that is synced to disk first. A file
that cannot be read as a log (not JSON, the wrong shape, or rows missing
what they need) is kept aside under a new name before anything is dropped,
never thrown away.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KINDS = Path(os.environ.get("REPS_KINDS") or ROOT / "kinds.json")
DATA_DIR = Path(
    os.environ.get("REPS_DATA_DIR") or Path.home() / ".local/share/forge/reps"
)
LOCK = threading.RLock()
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
ID_RE = re.compile(r"^[0-9a-f]{10}$")
NAME_MAX = 60
NOTE_MAX = 200
HISTORY_DAYS = 56
RECENT = 200


class RepsError(Exception):
    """Something the user can fix; shown as a 400."""


class NotFound(RepsError):
    """No such tracker or entry; shown as a 404."""


def load_kinds() -> dict[str, dict]:
    return json.loads(KINDS.read_text(encoding="utf-8"))


# --- storage ---------------------------------------------------------------


def data_path() -> Path:
    return DATA_DIR / "reps.json"


def good_tracker(t: object) -> bool:
    return (
        isinstance(t, dict)
        and all(isinstance(t.get(k), str) for k in ("id", "name", "kind"))
        and type(t.get("goal")) is int
        and 1 <= t["goal"] <= 7
    )


def good_entry(e: object) -> bool:
    return (
        isinstance(e, dict)
        and all(isinstance(e.get(k), str) for k in ("id", "tracker", "day"))
        and isinstance(e.get("values"), dict)
    )


def set_aside(path: Path, move: bool) -> None:
    kept = path.with_suffix(f".broken-{time.strftime('%Y%m%d-%H%M%S')}.json")
    n = 1
    while kept.exists():
        n += 1
        kept = path.with_suffix(f".broken-{time.strftime('%Y%m%d-%H%M%S')}-{n}.json")
    if move:
        os.replace(path, kept)
    else:
        shutil.copy2(path, kept)


def load() -> dict:
    """The log. A file that is not a log is moved aside and an empty one
    starts; rows missing what they need are dropped, with the whole file
    copied aside first."""
    with LOCK:
        path = data_path()
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return {"trackers": [], "entries": []}
        except OSError as e:
            raise RepsError(f"the log could not be read: {e}") from None
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            data = None
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("trackers", []), list)
            or not isinstance(data.get("entries", []), list)
        ):
            set_aside(path, move=True)
            return {"trackers": [], "entries": []}
        trackers = data.get("trackers", [])
        entries = data.get("entries", [])
        out = {
            "trackers": [t for t in trackers if good_tracker(t)],
            "entries": [e for e in entries if good_entry(e)],
        }
        if len(out["trackers"]) < len(trackers) or len(out["entries"]) < len(entries):
            set_aside(path, move=False)
            save(out)
        return out


def save(data: dict) -> None:
    path = data_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=1))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    folder = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)


def new_id() -> str:
    return secrets.token_hex(5)


def find_tracker(data: dict, tid: str) -> dict:
    for t in data["trackers"]:
        if t.get("id") == tid:
            return t
    raise NotFound("no such tracker")


# --- checking what comes in -----------------------------------------------


def clean_name(value: object) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise RepsError("give it a name")
    if len(name) > NAME_MAX:
        raise RepsError(f"keep the name under {NAME_MAX} characters")
    return name


def clean_goal(value: object) -> int:
    try:
        goal = int(str(value))
    except ValueError:
        raise RepsError("the goal is a number of days a week, 1 to 7") from None
    if not 1 <= goal <= 7:
        raise RepsError("the goal is a number of days a week, 1 to 7")
    return goal


def clean_day(value: object, today: dt.date) -> str:
    text = str(value or "") or today.isoformat()
    if not DAY_RE.match(text):
        raise RepsError("the day is written YYYY-MM-DD")
    try:
        day = dt.date.fromisoformat(text)
    except ValueError:
        raise RepsError(f"{text} is not a real day") from None
    if day > today:
        raise RepsError("that day has not happened yet")
    if day.year < 2000:
        raise RepsError("that day is too long ago")
    return text


def clean_values(kind: dict, values: object) -> dict[str, float]:
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise RepsError("the values are a set of named numbers")
    fields = {f["id"]: f for f in kind["fields"]}
    extra = set(values) - set(fields)
    if extra:
        raise RepsError(f"{kind['label']} has no {', '.join(sorted(extra))}")
    out: dict[str, float] = {}
    for fid, field in fields.items():
        raw = values.get(fid)
        if raw is None or raw == "":
            if field.get("required"):
                raise RepsError(f"{field['label']} is needed")
            continue
        if isinstance(raw, bool):
            raise RepsError(f"{field['label']} is a number")
        try:
            num = float(raw)
        except (TypeError, ValueError, OverflowError):
            raise RepsError(f"{field['label']} is a number") from None
        if num != num or not field["min"] <= num <= field["max"]:
            raise RepsError(
                f"{field['label']} goes from {field['min']} to {field['max']}"
            )
        out[fid] = int(num) if num == int(num) else round(num, 2)
    return out


# --- changes ---------------------------------------------------------------


def add_tracker(body: dict) -> dict:
    kinds = load_kinds()
    kind = str(body.get("kind", ""))
    if kind not in kinds:
        raise RepsError("pick a kind")
    goal = body.get("goal")
    tracker = {
        "id": new_id(),
        "name": clean_name(body.get("name")),
        "kind": kind,
        "goal": clean_goal(kinds[kind]["goal"] if goal in (None, "") else goal),
        "archived": False,
        "created": time.strftime("%Y-%m-%d"),
    }
    with LOCK:
        data = load()
        if any(
            t["name"].casefold() == tracker["name"].casefold() and not t.get("archived")
            for t in data["trackers"]
        ):
            raise RepsError(f"there is already a {tracker['name']}")
        data["trackers"].append(tracker)
        save(data)
    return tracker


def edit_tracker(tid: str, body: dict) -> dict:
    with LOCK:
        data = load()
        tracker = find_tracker(data, tid)
        name = clean_name(body["name"]) if "name" in body else tracker["name"]
        goal = clean_goal(body["goal"]) if "goal" in body else tracker["goal"]
        archived = (
            bool(body["archived"]) if "archived" in body else tracker.get("archived")
        )
        # checked whenever it ends up active, so a restore cannot make a twin
        if not archived and any(
            t is not tracker
            and t["name"].casefold() == name.casefold()
            and not t.get("archived")
            for t in data["trackers"]
        ):
            raise RepsError(f"there is already a {name}")
        tracker.update(name=name, goal=goal, archived=bool(archived))
        save(data)
    return tracker


def make_entry(tracker: dict, body: dict, today: dt.date) -> dict:
    kind = load_kinds().get(tracker["kind"])
    if kind is None:
        raise RepsError(f"the kind {tracker['kind']} is gone from kinds.json")
    note = " ".join(str(body.get("note") or "").split())
    if len(note) > NOTE_MAX:
        raise RepsError(f"keep the note under {NOTE_MAX} characters")
    entry = {
        "id": new_id(),
        "tracker": tracker["id"],
        "day": clean_day(body.get("day"), today),
        "values": clean_values(kind, body.get("values")),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if note:
        entry["note"] = note
    return entry


def log_entry(body: dict, today: dt.date) -> dict:
    with LOCK:
        data = load()
        tracker = find_tracker(data, str(body.get("tracker", "")))
        if tracker.get("archived"):
            raise RepsError(f"{tracker['name']} is archived")
        entry = make_entry(tracker, body, today)
        data["entries"].append(entry)
        save(data)
    return entry


def restore_entry(body: dict, today: dt.date) -> dict:
    """Undo a removal: the same entry back, with its id and time, checked
    like a new one. An archived tracker takes it too, since it is not new."""
    with LOCK:
        data = load()
        tracker = find_tracker(data, str(body.get("tracker", "")))
        entry = make_entry(tracker, body, today)
        eid, at = str(body.get("id", "")), str(body.get("at", ""))
        if ID_RE.match(eid):
            if any(e["id"] == eid for e in data["entries"]):
                raise RepsError("that entry is already there")
            entry["id"] = eid
        if AT_RE.match(at):
            entry["at"] = at
        data["entries"].append(entry)
        save(data)
    return entry


def remove_entry(eid: str) -> dict:
    with LOCK:
        data = load()
        for i, entry in enumerate(data["entries"]):
            if entry.get("id") == eid:
                del data["entries"][i]
                save(data)
                return entry
    raise NotFound("no such entry")


# --- streaks and charts ----------------------------------------------------


def monday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def entry_days(data: dict, tid: str) -> dict[dt.date, list[dict]]:
    out: dict[dt.date, list[dict]] = {}
    for e in data["entries"]:
        if e.get("tracker") != tid:
            continue
        try:
            day = dt.date.fromisoformat(str(e.get("day")))
        except ValueError:
            continue
        out.setdefault(day, []).append(e)
    return out


def longest_run(units: list[dt.date], step: int) -> int:
    best = run = 0
    prev = None
    for u in sorted(units):
        run = run + 1 if prev is not None and (u - prev).days == step else 1
        best = max(best, run)
        prev = u
    return best


def streak(days: set[dt.date], goal: int, today: dt.date) -> dict:
    """The current and best streak: days in a row for a daily goal, weeks
    in a row that met the goal otherwise. Today (or this week) still open
    does not break it."""
    if goal >= 7:
        current = 0
        day = today if today in days else today - dt.timedelta(days=1)
        while day in days:
            current += 1
            day -= dt.timedelta(days=1)
        return {"current": current, "best": longest_run(list(days), 1), "unit": "day"}
    weeks: dict[dt.date, int] = {}
    for d in days:
        weeks[monday(d)] = weeks.get(monday(d), 0) + 1
    met = {w for w, n in weeks.items() if n >= goal}
    week = monday(today)
    if week not in met:
        week -= dt.timedelta(days=7)
    current = 0
    while week in met:
        current += 1
        week -= dt.timedelta(days=7)
    return {"current": current, "best": longest_run(list(met), 7), "unit": "week"}


def chart_value(kind: dict, entries: list[dict]) -> float:
    field = kind["chart"].get("sum")
    if not field:
        return len(entries)
    total = sum(float((e.get("values") or {}).get(field) or 0) for e in entries)
    return int(total) if total == int(total) else round(total, 2)


def logged_at(entry: dict) -> str:
    return str(entry.get("at", ""))


def summary(
    tracker: dict, kinds: dict, data: dict, today: dt.date, day: dt.date | None = None
) -> dict:
    """A tracker with its streak, its week so far, today's entries and the
    entries on `day` (the day being logged, today unless another is picked)."""
    by_day = entry_days(data, tracker["id"])
    days = {d for d in by_day if d <= today}
    week_start = monday(today)
    return {
        **tracker,
        "streak": streak(days, tracker["goal"], today),
        "week": sum(1 for d in days if week_start <= d <= today),
        "week_days": [(week_start + dt.timedelta(days=i)) in days for i in range(7)],
        "today": sorted(by_day.get(today, []), key=logged_at),
        "on_day": sorted(by_day.get(day or today, []), key=logged_at),
        "known_kind": tracker["kind"] in kinds,
    }


def state(today: dt.date, day: str = "") -> dict:
    shown = dt.date.fromisoformat(clean_day(day, today))
    kinds = load_kinds()
    data = load()
    return {
        "today": today.isoformat(),
        "day": shown.isoformat(),
        "kinds": kinds,
        "trackers": [summary(t, kinds, data, today, shown) for t in data["trackers"]],
    }


def history(tid: str, today: dt.date, days: int = HISTORY_DAYS) -> dict:
    """The last `days` days as chart bars (zeros included), plus the most
    recent entries, newest first."""
    kinds = load_kinds()
    data = load()
    tracker = find_tracker(data, tid)
    kind = kinds.get(tracker["kind"])
    by_day = entry_days(data, tid)
    start = today - dt.timedelta(days=days - 1)
    bars = []
    for i in range(days):
        day = start + dt.timedelta(days=i)
        got = by_day.get(day, [])
        bars.append(
            {"day": day.isoformat(), "value": chart_value(kind, got) if kind else 0}
        )
    entries = [e for e in data["entries"] if e.get("tracker") == tid]
    entries.sort(key=lambda e: (str(e.get("day")), str(e.get("at"))), reverse=True)
    return {
        "tracker": summary(tracker, kinds, data, today),
        "chart": {"label": kind["chart"]["label"] if kind else "", "bars": bars},
        "entries": entries[:RECENT],
        "total_entries": len(entries),
        "days_logged": len(by_day),
    }
