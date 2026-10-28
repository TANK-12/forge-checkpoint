"""The state of the world, assembled from what is actually in the library.

After a bulk job finishes there is a lot of new dated material and no obvious
way in. This builds the way in: what changed, where, and which subjects it
touched - grouped by country so it reads as a picture of the world rather than
a list of edits.

The same discipline as everywhere else applies. The briefing is assembled from
stored, dated, sourced events by ordinary Python. A model is used only to write
the connecting sentences, it is shown only those events, and every line it
writes has to carry an event marker or it is removed before anyone sees it.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, timedelta

from pathlib import Path

import dossier
import llm
import store
from research.fetcher import now_iso


def _recent_events(days: int, limit_per_subject: int = 25) -> list[dict]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    events: list[dict] = []
    for row in dossier.library():
        stored = dossier.load(row["slug"])
        subject_events = [
            e for e in (stored.get("timeline") or []) if (e.get("date") or "") >= cutoff
        ]
        subject_events.sort(key=lambda e: e.get("date", ""), reverse=True)
        for event in subject_events[:limit_per_subject]:
            events.append(
                {
                    **event,
                    "subject": row["name"],
                    "slug": row["slug"],
                    "entity_type": row.get("entity_type", "person"),
                    "country": (
                        (
                            stored.get("subject", {})
                            .get("identity", {})
                            .get("citizenship")
                            or stored.get("subject", {})
                            .get("identity", {})
                            .get("country")
                            or ["Unattributed"]
                        )[0]
                        if isinstance(
                            (
                                stored.get("subject", {})
                                .get("identity", {})
                                .get("citizenship")
                                or stored.get("subject", {})
                                .get("identity", {})
                                .get("country")
                            ),
                            list,
                        )
                        else "Unattributed"
                    ),
                }
            )
    events.sort(key=lambda e: e.get("date", ""), reverse=True)
    return events


def build(days: int = 14, write_summary: bool = True) -> dict:
    """Assemble the briefing. Deterministic first, prose second."""
    events = _recent_events(days)
    library = dossier.library()

    by_country: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        by_country[event["country"] or "Unattributed"].append(event)

    kinds = Counter(e.get("kind", "other") for e in events)
    coverage = Counter(row.get("entity_type", "person") for row in library)

    countries = [
        {
            "country": country,
            "events": len(rows),
            "subjects": sorted({r["subject"] for r in rows}),
            "latest": rows[0]["date"],
            "sample": rows[:6],
        }
        for country, rows in sorted(
            by_country.items(), key=lambda kv: len(kv[1]), reverse=True
        )
    ]

    summary = ""
    used: list[dict] = []
    dropped = 0
    if write_summary and events:
        used = events[:30]
        listing = "\n".join(
            f"[{i}] {e['date']} {e['subject']} ({e['country']}): {e.get('title','')}"
            for i, e in enumerate(used)
        )
        # Asking a small model to append citation markers to free prose does not
        # work: it produced one sentence with no usable marker and the citation
        # gate stripped the lot. Asking for structure does work - the model
        # supplies the point and the event numbers it rests on, and the prose is
        # assembled here, so a citation cannot be forgotten or invented.
        prompt = (
            f"Dated events from the past {days} days, each numbered:\n\n"
            f"{listing}\n\n"
            "Summarise what these show, as at most six points. Each point must "
            "name the events it comes from by number. Use only what is listed.\n"
            'Reply only with JSON: [{"point": "...", "events": [0, 3]}]'
        )
        try:
            raw = llm.chat_json(
                "reason",
                [{"role": "user", "content": prompt}],
                default=[],
                max_tokens=600,
                temperature=0.2,
                timeout=600.0,
                priority="high",
            )
        except llm.JanUnavailable:
            raw = []
        points = []
        if isinstance(raw, list):
            for item in raw[:6]:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("point") or "").strip().rstrip(".")
                refs = [
                    n
                    for n in (item.get("events") or [])
                    if isinstance(n, int) and 0 <= n < len(used)
                ]
                if len(text.split()) < 4:
                    continue
                if not refs:
                    dropped += 1
                    continue
                markers = "".join(f"[E{n}]" for n in sorted(set(refs))[:6])
                points.append(f"{text} {markers}.")
        summary = " ".join(points)

    return {
        "generated": now_iso(),
        "window_days": days,
        "events_total": len(events),
        "subjects_in_library": len(library),
        "coverage_by_type": dict(coverage),
        "event_kinds": dict(kinds),
        "countries": countries,
        "summary": summary,
        "summary_points_dropped": dropped,
        "cited_events": used,
        "jan_available": bool(summary),
    }


# How far back each kind of brief looks. Daily reaches back two days rather
# than one so a brief is not empty just because nothing was published in the
# small hours; weekly covers the working week and a weekend either side.
KINDS = {
    "daily": {"days": 2, "every_days": 1, "label": "Daily brief"},
    "weekly": {"days": 9, "every_days": 7, "label": "Weekly brief"},
}
ARCHIVE = "briefings"


def _archive_dir(kind: str, root: Path | None = None) -> Path:
    base = (root or store.data_root().path) / ARCHIVE / kind
    base.mkdir(parents=True, exist_ok=True)
    return base


def _slim(payload: dict) -> dict:
    """What gets archived: everything a reader needs, none of the bulk.

    A full brief carries every event it considered - 250 KB of it. Keeping that
    for every day of the year would be most of a gigabyte on a filesystem whose
    minimum file size is 256 KB, for material already stored on each subject.
    """
    return {
        **{k: v for k, v in payload.items() if k not in ("countries", "cited_events")},
        "countries": [
            {
                "country": c["country"],
                "events": c["events"],
                "subjects": c["subjects"][:8],
                "latest": c["latest"],
            }
            for c in payload.get("countries", [])[:40]
        ],
        "highlights": [
            {
                "date": e.get("date", ""),
                "subject": e.get("subject", ""),
                "country": e.get("country", ""),
                "title": e.get("title", ""),
                "url": e.get("url", ""),
            }
            for e in payload.get("cited_events", [])[:40]
        ],
    }


def save(payload: dict, kind: str = "manual", root: Path | None = None) -> Path:
    """Archive a brief under its kind and date, and make it the latest."""
    base_root = root or store.data_root().path
    payload = {**payload, "kind": kind}
    slim = _slim(payload)
    target = _archive_dir(kind, root) / f"{payload.get('generated') or now_iso()}.json"
    store.write_json(target, slim)

    store.write_json(base_root / "briefing.json", payload)
    history = store.read_json(base_root / "briefing-history.json", [])
    history = [
        h
        for h in history
        if not (
            h.get("kind") == kind and h.get("generated") == payload.get("generated")
        )
    ]
    history.append(
        {
            "kind": kind,
            "generated": payload.get("generated", ""),
            "window_days": payload.get("window_days"),
            "events_total": payload.get("events_total", 0),
            "countries": len(payload.get("countries") or []),
            "summary": payload.get("summary", ""),
        }
    )
    history.sort(key=lambda h: (h.get("generated", ""), h.get("kind", "")))
    store.write_json(base_root / "briefing-history.json", history[-400:])
    return target


def latest(root: Path | None = None) -> dict:
    return store.read_json((root or store.data_root().path) / "briefing.json", {})


def history(kind: str = "", root: Path | None = None) -> list[dict]:
    rows = store.read_json(
        (root or store.data_root().path) / "briefing-history.json", []
    )
    rows = [r for r in rows if not kind or r.get("kind") == kind]
    return list(reversed(rows))


def read(kind: str, date: str, root: Path | None = None) -> dict:
    return store.read_json(_archive_dir(kind, root) / f"{date}.json", {})


def due(kind: str, root: Path | None = None) -> bool:
    """Is a brief of this kind overdue?"""
    spec = KINDS.get(kind)
    if not spec:
        return False
    existing = sorted(p.stem for p in _archive_dir(kind, root).glob("*.json"))
    if not existing:
        return True
    try:
        last = date.fromisoformat(existing[-1])
    except ValueError:
        return True
    return (date.today() - last).days >= spec["every_days"]


def run_scheduled(root: Path | None = None, force: str = "") -> list[str]:
    """Generate whichever briefs are due. Returns the kinds that were written.

    Called on a timer by the backend, so the daily and weekly briefs exist
    without anyone remembering to ask for them.
    """
    written = []
    for kind, spec in KINDS.items():
        if force and force != kind:
            continue
        if not force and not due(kind, root):
            continue
        try:
            payload = build(days=spec["days"], write_summary=True)
        except Exception:
            continue
        if not payload.get("events_total"):
            continue
        save(payload, kind=kind, root=root)
        written.append(kind)
    return written
