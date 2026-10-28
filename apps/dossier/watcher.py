"""The news watcher: keeps the library current without being asked.

News is gathered per subject when that subject is researched, and the briefing
assembles whatever is already stored. Nothing polled for new events on its own,
so a library left alone slowly went stale and the briefing quietly described an
older world. This closes that loop: on a timer, the subjects that have gone
longest without a refresh are queued for another quick pass, and the ordinary
merge rules fold whatever is new into what is already held.

Three things it deliberately will not do, because a watcher that runs unattended
for months has to be a good citizen of a machine that is also being used:

  * It never interrupts work the user started. If the active queue still has
    jobs waiting or running, the sweep is deferred rather than shouldered in.
  * It never clears a pause. A paused queue is a decision, and the whole point
    of the pause surviving a restart is that it survives everything.
  * It never overrides the memory guard. If the guard is holding the queue
    because the machine is short of memory, the sweep waits for another day.

The settings and the sweep history live on disk beside the research, so the
schedule survives a restart the same way the queue does.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import dossier
import store

FILE = "watcher.json"
QUEUE_NAME = "News watcher"

DEFAULTS = {
    "enabled": False,
    # Every six hours, twelve subjects at a time, is about two sweeps of a
    # thousand-subject library a month at a cost of a few minutes of CPU each.
    "every_hours": 6,
    "per_sweep": 12,
    "last_sweep": "",
    "last_result": "",
    "sweeps": [],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _path(root: Path | None = None) -> Path:
    return (root or store.data_root().path) / FILE


def settings(root: Path | None = None) -> dict:
    """The saved settings, with anything missing filled in from the defaults."""
    saved = store.read_json(_path(root), {}) or {}
    return {**DEFAULTS, **saved}


def update(patch: dict, root: Path | None = None) -> dict:
    """Change settings without losing the sweep history."""
    current = settings(root)
    if "enabled" in patch:
        current["enabled"] = bool(patch["enabled"])
    if "every_hours" in patch:
        current["every_hours"] = max(1, min(168, int(patch["every_hours"])))
    if "per_sweep" in patch:
        current["per_sweep"] = max(1, min(200, int(patch["per_sweep"])))
    store.write_json(_path(root), current)
    return current


def due(root: Path | None = None) -> bool:
    """Has enough time passed since the last sweep?"""
    config = settings(root)
    if not config.get("enabled"):
        return False
    last = config.get("last_sweep") or ""
    if not last:
        return True
    try:
        when = datetime.fromisoformat(last)
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - when >= timedelta(
        hours=int(config.get("every_hours", 6))
    )


def stale(limit: int, root: Path | None = None) -> list[dict]:
    """The held subjects that have gone longest without a refresh.

    `updated` is written every time a subject is saved, so sorting by it is
    exactly "least recently looked at". A subject with no timestamp sorts first
    - it predates the field, which makes it the stalest thing in the library.
    """
    rows = dossier.library(root)
    return sorted(rows, key=lambda r: (r.get("updated") or ""))[:limit]


def _watch_queue(queue) -> dict:
    """The watcher's own queue, created once.

    It is set to redo subjects it already holds, because refreshing a held
    subject is the entire job - with that off, every sweep would queue twelve
    subjects and skip all twelve.
    """
    for row in queue.queues():
        if row["name"] == QUEUE_NAME:
            return row
    created = queue.create_queue(QUEUE_NAME, redo_held=True)
    return {"id": created["id"], "name": created["name"]}


def blocked_by(queue) -> str:
    """Why a sweep cannot run right now, or "" if it can."""
    state = queue.state()
    if state.get("guard_hold"):
        return "the memory guard is holding the queue"
    if state.get("paused"):
        return "the active queue is paused"
    counts = state.get("counts") or {}
    if counts.get("queued") or counts.get("running"):
        return f"the {state['active_queue']['name']} queue is still working"
    return ""


def sweep(queue, root: Path | None = None, force: bool = False) -> dict:
    """Queue quick passes over the stalest subjects. Returns what happened."""
    config = settings(root)
    if not force and not config.get("enabled"):
        return {"ran": False, "reason": "the watcher is switched off", "queued": 0}

    reason = blocked_by(queue)
    if reason:
        # Deliberately not recorded as the last sweep: a deferred sweep should
        # be retried on the next tick, not counted as having happened.
        return {"ran": False, "reason": reason, "queued": 0}

    subjects = stale(int(config.get("per_sweep", 12)), root)
    if not subjects:
        return {"ran": False, "reason": "nothing is held yet", "queued": 0}

    target = _watch_queue(queue)
    queue.activate(target["id"])
    queued = 0
    for row in subjects:
        _job, created = queue.add_job(
            row["name"], row.get("entity_type", "person"), "quick"
        )
        if created:
            queued += 1
    queue.start()

    record = {
        "at": now_iso(),
        "queued": queued,
        "subjects": [
            {"slug": r["slug"], "name": r["name"], "was_updated": r.get("updated", "")}
            for r in subjects
        ],
    }
    config["last_sweep"] = record["at"]
    config["last_result"] = f"queued {queued} of {len(subjects)}"
    config["sweeps"] = ([record] + list(config.get("sweeps") or []))[:40]
    store.write_json(_path(root), config)
    return {"ran": True, "reason": "", "queued": queued, "subjects": record["subjects"]}


def run_scheduled(queue, root: Path | None = None) -> dict:
    """Sweep if one is due. Called on a timer by the backend."""
    if not due(root):
        return {"ran": False, "reason": "not due", "queued": 0}
    return sweep(queue, root)


def freshest(limit: int = 12, root: Path | None = None) -> list[dict]:
    """What the watcher has most recently brought in, newest first.

    Read from the index rather than by opening every subject, so this stays
    cheap on a USB drive with a thousand subjects on it.
    """
    rows = [r for r in dossier.library(root) if r.get("updated")]
    rows.sort(key=lambda r: r.get("updated") or "", reverse=True)
    return [
        {
            "slug": r["slug"],
            "name": r["name"],
            "entity_type": r.get("entity_type", ""),
            "updated": r.get("updated", ""),
            "timeline": r.get("timeline", 0),
            "sources": r.get("sources", 0),
        }
        for r in rows[:limit]
    ]


def state(queue, root: Path | None = None) -> dict:
    """Everything the Watch tab draws."""
    config = settings(root)
    return {
        **config,
        "due": due(root),
        "blocked": blocked_by(queue),
        "queue_name": QUEUE_NAME,
        "next_up": [
            {"slug": r["slug"], "name": r["name"], "updated": r.get("updated", "")}
            for r in stale(int(config.get("per_sweep", 12)), root)
        ],
        "freshest": freshest(12, root),
        "held": len(dossier.library(root)),
    }
