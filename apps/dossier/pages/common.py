"""Shared block builders. Pages compose these rather than repeating them."""

from __future__ import annotations

KIND_ORDER = ["office", "life", "founding", "filing", "coverage", "other"]


def facts_block(stored: dict, keys: list[tuple[str, str]]) -> dict:
    identity = (stored.get("subject") or {}).get("identity") or {}
    rows = []
    for key, label in keys:
        value = identity.get(key)
        if isinstance(value, list):
            value = ", ".join(dict.fromkeys(str(v) for v in value if v))
        if value:
            rows.append({"label": label, "value": str(value)})
    return {"kind": "facts", "rows": rows}


def timeline_block(
    stored: dict,
    kinds: list[str] | None = None,
    exclude: list[str] | None = None,
    limit: int = 400,
    source_ids: list[str] | None = None,
) -> dict:
    """Dated events, filtered however the page wants them.

    `source_ids` exists because two publishers now supply indicators. Filtering
    on the source is what lets one page show the economic series and another
    the social ones without either having to know which indicator codes the
    other collects.
    """
    events = stored.get("timeline") or []
    if kinds:
        events = [e for e in events if e.get("kind") in kinds]
    if exclude:
        events = [e for e in events if e.get("kind") not in exclude]
    if source_ids:
        events = [e for e in events if e.get("source_id") in source_ids]
    events = sorted(events, key=lambda e: e.get("date") or "")
    # Past the limit, the newest are kept: a long record cut at its oldest
    # entries would hide exactly what happened lately.
    return {"kind": "timeline", "events": events[-limit:] if limit else events}


def years_ago(years: int) -> str:
    from datetime import date

    today = date.today()
    try:
        return today.replace(year=today.year - years).isoformat()
    except ValueError:  # 29 February
        return today.replace(year=today.year - years, day=28).isoformat()


def news_block(stored: dict, kinds: tuple[str, ...] = ("news", "coverage")) -> dict:
    """Dated news, newest first, split into the past year and the four before.

    The year counts are included so a page can say how much is held beyond
    what it draws.
    """
    events = [
        e
        for e in (stored.get("timeline") or [])
        if e.get("kind") in kinds and e.get("date")
    ]
    events.sort(key=lambda e: e.get("date") or "", reverse=True)
    one, five = years_ago(1), years_ago(5)
    groups = [
        {"label": "Past year", "events": [e for e in events if e["date"] >= one]},
        {
            "label": "One to five years ago",
            "events": [e for e in events if five <= e["date"] < one],
        },
        {"label": "Older", "events": [e for e in events if e["date"] < five]},
    ]
    by_year: dict[str, int] = {}
    for event in events:
        by_year[event["date"][:4]] = by_year.get(event["date"][:4], 0) + 1
    return {
        "kind": "news",
        "total": len(events),
        "by_year": dict(sorted(by_year.items(), reverse=True)),
        "groups": [g for g in groups if g["events"]],
    }


def article_block(stored: dict) -> dict:
    article = stored.get("article") or {}
    return {
        "kind": "article",
        "title": article.get("title", ""),
        "url": article.get("url", ""),
        "fetched": article.get("fetched", ""),
        "words": article.get("words", 0),
        "sections": article.get("sections") or [],
    }


def claims_block(
    stored: dict,
    contains: list[str] | None = None,
    confidence: list[str] | None = None,
    limit: int = 200,
) -> dict:
    claims = stored.get("claims") or []
    if confidence:
        claims = [c for c in claims if c.get("confidence") in confidence]
    if contains:
        needles = [n.lower() for n in contains]
        claims = [
            c
            for c in claims
            if any(n in (c.get("text") or "").lower() for n in needles)
        ]
    order = {"disputed": 0, "verified": 1, "reported": 2, "unsourced": 3}
    claims = sorted(
        claims,
        key=lambda c: (
            order.get(c.get("confidence", "unsourced"), 9),
            -c.get("relevance", 0),
        ),
    )
    return {"kind": "claims", "claims": claims[:limit] if limit else claims}


def quotes_block(stored: dict, limit: int = 300) -> dict:
    quotes = stored.get("quotes") or []
    return {"kind": "quotes", "quotes": quotes[:limit] if limit else quotes}


def pictures_block(stored: dict) -> dict:
    """Pictures on disk. The page draws them from the subject's image list."""
    held = [i for i in (stored.get("images") or []) if i.get("stored")]
    return {"kind": "pictures", "count": len(held)}


def source_texts_block(stored: dict) -> dict:
    """Every source, each openable to its saved text.

    The text itself loads on demand: a subject's saved texts can run to
    megabytes, and every page of a dossier arrives in one response.
    """
    subject = stored.get("subject") or {}
    return {
        "kind": "source_texts",
        "slug": stored.get("slug") or subject.get("slug", ""),
        "sources": stored.get("sources") or [],
    }


def relations_block(stored: dict, only: list[str] | None = None) -> dict:
    relations = stored.get("relations") or []
    if only:
        relations = [r for r in relations if r.get("relation") in only]
    return {"kind": "relations", "relations": relations}


def sources_block(stored: dict) -> dict:
    return {"kind": "sources", "sources": stored.get("sources") or []}


def notes_block(stored: dict) -> dict:
    notes = stored.get("notes") or {}
    return {
        "kind": "notes",
        "markdown": notes.get("markdown", ""),
        "updated": notes.get("updated", ""),
    }


def rich_facts_block(stored: dict) -> dict:
    """Everything Wikidata knows about the subject, grouped for reading.

    Driven entirely by `sources/properties.py`, so adding a fact to every
    dossier in the library is one line in that table.
    """
    from sources.properties import grouped

    subject = stored.get("subject") or {}
    identity = subject.get("identity") or {}
    entity_type = subject.get("entity_type", "")
    return {"kind": "grouped_facts", "panels": grouped(identity, entity_type)}


def seats_block(stored: dict) -> dict:
    """Seats held as a share of the chamber, not a bare number.

    Returns an empty block when the subject holds no seats, so pages can
    include it unconditionally and it simply does not draw.
    """
    identity = (stored.get("subject") or {}).get("identity") or {}
    if not identity.get("seats"):
        return {"kind": "seats", "seats": 0}
    return {
        "kind": "seats",
        "seats": identity.get("seats", 0),
        "total": identity.get("seats_total", 0),
        "share": identity.get("seats_share", 0),
        "body": identity.get("seats_body", ""),
        "url": identity.get("seats_body_url", ""),
        "chambers": identity.get("seats_chambers", []),
    }


def prose(text: str) -> dict:
    return {"kind": "prose", "text": text}


def empty_hint(text: str) -> dict:
    return {"kind": "hint", "text": text}
