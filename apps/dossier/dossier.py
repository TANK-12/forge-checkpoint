"""A dossier on disk: read it, merge new research into it, write it back.

The rule this module exists to enforce is that research accumulates. A second
run on a subject must never overwrite the first, never drop a fact that was
already established, and never record the same fact twice. Every merge is
therefore keyed:

  sources   by source id, which is the canonical URL - so the same article
            arriving from a different search does not become a second source
  claims    by statement similarity - a restatement adds its evidence to the
            claim that already exists rather than sitting beside it
  timeline  by date plus title
  quotes    by the text of the quote
  notes     never touched by anything automatic; they are the user's

Every run is also appended to a history, so it is always answerable why a fact
is in here and when it arrived.
"""

from __future__ import annotations

import threading
from pathlib import Path

import store
from research.corroborate import Claim, Evidence, grade, similarity
from research.fetcher import now_iso

# Several subjects can be researched at once, and while each writes to its own
# directory they all rebuild the one shared index. Serialising the write keeps
# that index consistent; the research itself stays parallel.
_write_lock = threading.RLock()

FILES = {
    "subject": "subject.json",
    "timeline": "timeline.json",
    "claims": "claims.json",
    "quotes": "quotes.json",
    "relations": "relations.json",
    "sources": "sources.json",
    "images": "images.json",
    "notes": "notes.json",
    "history": "history.json",
    "article": "article.json",
}
# Files holding one object rather than a list of records.
OBJECT_FILES = ("subject", "notes", "article")


def migrate_text_files(slug: str, root: Path | None = None) -> int:
    """Fold any legacy per-source text files into the one bundle.

    Safe to run repeatedly; it only removes a file after its content is in the
    bundle, so an interrupted migration loses nothing.
    """
    d = store.subject_dir(slug, root)
    legacy = d / "text"
    if not legacy.is_dir():
        return 0
    bundle = store.read_text_bundle(d)
    moved = 0
    for path in sorted(legacy.glob("*.txt.gz")):
        source_id = path.name[: -len(".txt.gz")]
        if source_id not in bundle:
            text = store.read_text_gz(path)
            if text:
                bundle[source_id] = text
                moved += 1
    if moved:
        store.write_text_bundle(d, bundle)
    for path in list(legacy.glob("*.txt.gz")):
        source_id = path.name[: -len(".txt.gz")]
        if source_id in bundle:
            path.unlink()
    try:
        legacy.rmdir()
    except OSError:
        pass
    return moved


def load(slug: str, root: Path | None = None) -> dict:
    d = store.subject_dir(slug, root)
    if not d.is_dir():
        return {}
    out = {"slug": slug}
    for key, filename in FILES.items():
        default = {} if key in OBJECT_FILES else []
        out[key] = store.read_json(d / filename, default)
    return out


def load_subject(slug: str, root: Path | None = None) -> dict:
    """Only subject.json: who or what this is, without the evidence.

    For callers that need a subject's identity across the whole library (the
    map's per-country totals). `load` reads ten files a subject; over 2,450
    subjects that was 1 s warm and 5 s cold, against 0.06 s for this.
    """
    try:
        d = store.subject_dir(slug, root)
    except store.BadSlug:
        return {}
    return store.read_json(d / FILES["subject"], {}) or {}


def exists(slug: str, root: Path | None = None) -> bool:
    return (store.subject_dir(slug, root) / FILES["subject"]).is_file()


def _held_dir(slug: str, root: Path | None) -> Path | None:
    # The slug arrives from a URL; only a name slugify could have produced is
    # allowed to become a path, so ".." never reaches the filesystem.
    if not slug or slug != store.slugify(slug) or not exists(slug, root):
        return None
    return store.subject_dir(slug, root)


def saved_texts(slug: str, root: Path | None = None) -> dict[str, int]:
    """Which sources have their text saved, with each one's word count."""
    d = _held_dir(slug, root)
    if d is None:
        return {}
    return {
        source_id: len(text.split())
        for source_id, text in store.read_text_bundle(d).items()
        if text
    }


def saved_text(slug: str, source_id: str, root: Path | None = None) -> str | None:
    d = _held_dir(slug, root)
    if d is None:
        return None
    return store.read_text_bundle(d).get(source_id) or None


def _merge_by_key(
    existing: list[dict], incoming: list[dict], key
) -> tuple[list[dict], int, int]:
    """Add what is new, leave what is there. Returns (merged, added, skipped)."""
    index = {key(item): item for item in existing}
    added = skipped = 0
    for item in incoming:
        k = key(item)
        if k in index:
            # Fill in fields the stored copy is missing, but never replace one
            # that already has a value - the earlier record stands.
            for field, value in item.items():
                if value and not index[k].get(field):
                    index[k][field] = value
            skipped += 1
            continue
        index[k] = item
        existing.append(item)
        added += 1
    return existing, added, skipped


def _merge_claims(
    existing: list[dict], incoming: list[dict]
) -> tuple[list[dict], int, int]:
    """Fold new claims into old ones by meaning, not by string equality."""
    added = merged = 0
    revived: list[Claim] = []
    for row in existing:
        revived.append(
            Claim(
                text=row["text"],
                evidence=[Evidence(**e) for e in row.get("evidence", [])],
                conflicts=list(row.get("conflicts") or []),
            )
        )
    for row in incoming:
        new_claim = Claim(
            text=row["text"],
            evidence=[Evidence(**e) for e in row.get("evidence", [])],
            conflicts=list(row.get("conflicts") or []),
        )
        for old in revived:
            if similarity(new_claim.text, old.text) >= 0.6:
                known = {(e.source_id, e.span[:60]) for e in old.evidence}
                for e in new_claim.evidence:
                    if (e.source_id, e.span[:60]) not in known:
                        old.evidence.append(e)
                old.conflicts = list(dict.fromkeys(old.conflicts + new_claim.conflicts))
                merged += 1
                break
        else:
            revived.append(new_claim)
            added += 1
    return [grade(c).to_dict() for c in revived], added, merged


def save(result: dict, root: Path | None = None) -> dict:
    """Merge one research result into the stored dossier. Returns what changed."""
    with _write_lock:
        return _save_locked(result, root)


def _save_locked(result: dict, root: Path | None = None) -> dict:
    slug = result["slug"]
    d = store.ensure_subject(slug, root)
    before = load(slug, root)

    subject = before.get("subject") or {}
    # Identity fields refresh (offices change); the record of when we first saw
    # this subject does not.
    subject.update(
        {
            "slug": slug,
            "name": result["name"],
            "entity_type": result["entity_type"],
            "identity": result["identity"],
            "context_terms": result["context_terms"],
            "updated": result["updated"],
        }
    )
    subject.setdefault("added", now_iso())
    subject.setdefault("depth", "quick")
    report = result["report"]
    # A deep dive that could not extract claims (Jan off, or failing) is not
    # deep, and recording it as deep made later queues skip it as done.
    if report.get("phase") == "deep" and report.get("claims_complete", True):
        subject["depth"] = "deep"

    sources, src_added, src_dup = _merge_by_key(
        before.get("sources") or [], result["sources"], lambda s: s["source_id"]
    )
    timeline, tl_added, tl_dup = _merge_by_key(
        before.get("timeline") or [],
        result["timeline"],
        lambda e: (e.get("date", ""), (e.get("title") or "").lower()[:60]),
    )
    quotes, q_added, q_dup = _merge_by_key(
        before.get("quotes") or [],
        result["quotes"],
        lambda q: (q.get("text") or "").lower()[:100],
    )
    images, img_added, _ = _merge_by_key(
        before.get("images") or [],
        result.get("images") or [],
        lambda i: (i.get("kind", ""), (i.get("commons_file") or "").lower()),
    )
    # A picture already pulled down keeps its local path; a re-run must not
    # forget where the file is just because the reference arrived again.
    stored_paths = {
        (i.get("kind", ""), (i.get("commons_file") or "").lower()): i.get("stored", "")
        for i in (before.get("images") or [])
        if i.get("stored")
    }
    for image in images:
        key = (image.get("kind", ""), (image.get("commons_file") or "").lower())
        if not image.get("stored") and stored_paths.get(key):
            image["stored"] = stored_paths[key]

    relations, r_added, _ = _merge_by_key(
        before.get("relations") or [],
        result["relations"],
        lambda r: (r.get("relation", ""), (r.get("target") or "").lower()),
    )
    claims, c_added, c_merged = _merge_claims(
        before.get("claims") or [], result["claims"]
    )

    timeline.sort(key=lambda e: (e.get("date") or "", e.get("title") or ""))
    sources.sort(key=lambda s: s.get("relevance", 0), reverse=True)

    # Article text goes into one compressed bundle per subject, merged so a
    # re-run adds new extracts without rewriting or losing the old ones.
    incoming = {k: v for k, v in (result.get("texts") or {}).items() if v}
    stored_text = 0
    if incoming:
        bundle = store.read_text_bundle(d)
        held = len(bundle)
        for source_id, text in incoming.items():
            bundle.setdefault(source_id, text)
        stored_text = len(bundle) - held
        if stored_text:
            store.write_text_bundle(d, bundle)

    changes = {
        "sources_added": src_added,
        "sources_already_known": src_dup,
        "timeline_added": tl_added,
        "timeline_already_known": tl_dup,
        "quotes_added": q_added,
        "quotes_already_known": q_dup,
        "relations_added": r_added,
        "images_added": img_added,
        "claims_added": c_added,
        "claims_merged_into_existing": c_merged,
        "texts_stored": stored_text,
    }
    history = before.get("history") or []
    history.append({"when": now_iso(), "report": result["report"], "changes": changes})

    store.write_json(d / FILES["subject"], subject)
    store.write_json(d / FILES["sources"], sources)
    store.write_json(d / FILES["timeline"], timeline)
    store.write_json(d / FILES["quotes"], quotes)
    store.write_json(d / FILES["relations"], relations)
    store.write_json(d / FILES["images"], images)
    store.write_json(d / FILES["claims"], claims)
    store.write_json(d / FILES["history"], history)
    # The encyclopedia article is one living document: a fresh copy replaces
    # the old one, and a run that did not fetch it leaves the stored one alone.
    if (result.get("article") or {}).get("sections"):
        store.write_json(d / FILES["article"], result["article"])
    # Notes are the user's. Create the file if missing; never write over it.
    if not (d / FILES["notes"]).exists():
        store.write_json(d / FILES["notes"], {"markdown": "", "updated": ""})

    reindex(root)
    return changes


def add_events(
    slug: str,
    events: list[dict],
    report: dict,
    article: dict | None = None,
    root: Path | None = None,
) -> dict:
    """Fold dated events (and optionally the article) into a held subject.

    For enrichment passes that add one kind of thing to many subjects. A full
    `save()` rebuilds the library index on every call, which over a thousand
    subjects on a USB drive is a million file reads; the caller reindexes once
    at the end instead. Same merge key as `save()`, so nothing is doubled.
    """
    with _write_lock:
        d = store.subject_dir(slug, root)
        if not (d / FILES["subject"]).is_file():
            return {"timeline_added": 0, "article": False}
        timeline, added, _ = _merge_by_key(
            store.read_json(d / FILES["timeline"], []) or [],
            events,
            lambda e: (e.get("date", ""), (e.get("title") or "").lower()[:60]),
        )
        timeline.sort(key=lambda e: (e.get("date") or "", e.get("title") or ""))
        wrote_article = bool((article or {}).get("sections"))
        if added:
            store.write_json(d / FILES["timeline"], timeline)
        if wrote_article:
            store.write_json(d / FILES["article"], article)
        changes = {"timeline_added": added, "article": wrote_article}
        if added or wrote_article:
            history = store.read_json(d / FILES["history"], []) or []
            history.append({"when": now_iso(), "report": report, "changes": changes})
            store.write_json(d / FILES["history"], history)
        return changes


def save_notes(slug: str, markdown: str, root: Path | None = None) -> dict:
    d = store.ensure_subject(slug, root)
    payload = {"markdown": markdown, "updated": now_iso()}
    store.write_json(d / FILES["notes"], payload)
    return payload


def regrade(slug: str, root: Path | None = None) -> dict:
    """Recompute confidence for a stored subject from the evidence already held.

    Confidence is derived, not observed, so when the corroboration rules change
    the stored verdicts are stale. This recomputes them without refetching
    anything and without touching the evidence itself - no claim, source or
    quote is added or removed.
    """
    d = store.subject_dir(slug, root)
    rows = store.read_json(d / FILES["claims"], [])
    before = {}
    after = {}
    revived = []
    for row in rows:
        before[row["confidence"]] = before.get(row["confidence"], 0) + 1
        claim = Claim(
            text=row["text"],
            evidence=[Evidence(**e) for e in row.get("evidence", [])],
        )
        graded = grade(claim)
        after[graded.confidence] = after.get(graded.confidence, 0) + 1
        revived.append(graded.to_dict())
    store.write_json(d / FILES["claims"], revived)
    reindex(root)
    return {"claims": len(revived), "before": before, "after": after}


def placing(subject: dict) -> dict:
    """The handful of facts that say where a subject sits in the world.

    A library list that shows only a name and a count is hard to read: it does
    not say which country a party contests, where a company is based, or what
    office a person holds. All of this is already in `subject.json`; it was
    simply never carried into the index the list is built from.

    Kept to one short string per field so a row stays a row.
    """
    identity = subject.get("identity") or {}

    def first(*keys) -> str:
        for key in keys:
            value = identity.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip():
                        return item.strip()
        return ""

    entity_type = subject.get("entity_type", "")
    # A country is its own country; saying so twice reads as a mistake.
    country = (
        ""
        if entity_type == "country"
        else first("Country", "country", "Citizenship", "citizenship")
    )
    return {
        "country": country,
        "role": first("Positions held", "Head of government", "Head of state", "Role"),
        "party": first("Party", "party"),
        "based": first("Headquarters", "Capital"),
        "industry": first("Industry", "industry", "Ideology", "ideology"),
    }


def reindex(root: Path | None = None) -> list[dict]:
    """Rebuild the library index from what is actually on disk.

    Deliberately defensive. The index is derived data, but it is also how the
    whole library is found, so a bad rebuild looks exactly like losing
    everything. This was seen for real: the data directory lives on an exfat
    USB drive, and while it was busy a `subject.json` read failed transiently -
    the subject was skipped and an EMPTY index was written over a good one.

    So a directory that holds a `subject.json` which will not parse is never
    treated as an absent subject. Its previous index row is carried forward,
    and if nothing at all could be read while subject directories exist, the
    old index is kept rather than replaced with nothing.
    """
    base_root = root or store.data_root().path
    base = base_root / store.SUBJECTS
    base.mkdir(parents=True, exist_ok=True)
    previous = {
        row.get("slug"): row
        for row in (store.read_json(base_root / "index.json", []) or [])
    }
    rows = []
    unreadable = 0
    candidates = 0
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        subject_path = d / FILES["subject"]
        if not subject_path.exists():
            continue  # a directory that was never a dossier
        candidates += 1
        subject = store.read_json(subject_path, None)
        if not subject:
            # The file is there but would not read. Keep what we last knew.
            unreadable += 1
            if d.name in previous:
                rows.append(previous[d.name])
            continue
        claims = store.read_json(d / FILES["claims"], [])
        rows.append(
            {
                **placing(subject),
                "slug": subject.get("slug", d.name),
                "name": subject.get("name", d.name),
                "entity_type": subject.get("entity_type", "person"),
                "description": (subject.get("identity") or {}).get("description", ""),
                "depth": subject.get("depth", "quick"),
                "updated": subject.get("updated", ""),
                "added": subject.get("added", ""),
                "sources": len(store.read_json(d / FILES["sources"], [])),
                "claims": len(claims),
                "verified": sum(1 for c in claims if c.get("confidence") == "verified"),
                "disputed": sum(1 for c in claims if c.get("confidence") == "disputed"),
                "timeline": len(store.read_json(d / FILES["timeline"], [])),
                "quotes": len(store.read_json(d / FILES["quotes"], [])),
            }
        )
    if candidates and not rows:
        # Every subject failed to read. That is a storage problem, not an
        # empty library - leave the existing index alone.
        return list(previous.values())
    store.write_json(base_root / "index.json", rows)
    return rows


def library(root: Path | None = None) -> list[dict]:
    """The index, rebuilt if it is missing or looks wrong.

    An empty index while subject directories exist means the index is stale or
    was damaged, not that there is nothing held, so it is rebuilt rather than
    believed.
    """
    base_root = root or store.data_root().path
    rows = store.read_json(base_root / "index.json", None)
    if rows:
        return rows
    subjects = base_root / store.SUBJECTS
    if rows is None or (subjects.is_dir() and any(subjects.iterdir())):
        return reindex(root)
    return rows


def delete(slug: str, root: Path | None = None) -> bool:
    import shutil

    # Only a name slugify could have produced is ever removed.
    if slug != store.slugify(slug):
        return False
    d = store.subject_dir(slug, root)
    if not d.is_dir():
        return False
    shutil.rmtree(d)
    reindex(root)
    return True
