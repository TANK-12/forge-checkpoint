"""Recall: flashcards scheduled with FSRS (shared/forge_fsrs.py).

Cards live in one SQLite file, <data>/recall.db:

- decks:   id, name
- cards:   id, deck, front, back, source key (imported cards only), the
           py-fsrs card as JSON, when it is due (epoch seconds), how many
           times it was answered, removed (cards are never deleted, only
           hidden, so a re-import does not bring back a removed card)
- reviews: one row per answer, with py-fsrs's review log

Cards come from the page or from the sources in recall.json, read by the
functions in IMPORTERS (one per kind). A re-import adds new cards and
updates the words of changed ones, keeping their schedule.

A deck's queue: cards already learned that are due, oldest first; then new
cards, up to recall.json's new_per_day a day across all decks.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

ROOT = Path(__file__).resolve().parent
FORGE = ROOT.parent.parent
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR") or ROOT.parent.parent / "shared")
sys.path.insert(0, str(SHARED_DIR))
import forge_fsrs  # noqa: E402

DATA_DIR = Path(
    os.environ.get("RECALL_DATA_DIR") or Path.home() / ".local/share/forge/recall"
)
CONFIG = Path(os.environ.get("RECALL_CONFIG") or ROOT / "recall.json")
LONGEST = 4000  # characters on one side of a card

SCHEMA = """
CREATE TABLE IF NOT EXISTS decks (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY,
    deck INTEGER NOT NULL REFERENCES decks(id),
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    source_key TEXT UNIQUE,
    source_hash TEXT,
    fsrs TEXT NOT NULL,
    due REAL NOT NULL,
    answered INTEGER NOT NULL DEFAULT 0,
    removed INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS cards_due ON cards(deck, removed, answered, due);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    card INTEGER NOT NULL REFERENCES cards(id),
    rating INTEGER NOT NULL,
    at REAL NOT NULL,
    log TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reviews_at ON reviews(at);
"""


class RecallError(ValueError):
    """Something the page asked for that cannot be done; the message says why."""


@dataclass
class Found:
    """One card a source offers: its deck, its two sides and a stable key."""

    deck: str
    front: str
    back: str
    key: str


def load_config(path: Path = CONFIG) -> dict:
    return json.loads(path.read_text())


def connect(data: Path = DATA_DIR) -> sqlite3.Connection:
    data.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(data / "recall.db", timeout=10, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    cols = {r[1] for r in db.execute("PRAGMA table_info(cards)")}
    if "source_hash" not in cols:  # databases from before 2026-10-20 evening
        db.execute("ALTER TABLE cards ADD COLUMN source_hash TEXT")
    return db


def now() -> datetime:
    return datetime.now(timezone.utc)


def start_of_day(when: datetime) -> float:
    """Local midnight before `when`, as epoch seconds: a day of new cards."""
    local = when.astimezone()
    return local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def clean(text: str, side: str) -> str:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise RecallError(f"the {side} of a card cannot be empty")
    if len(text) > LONGEST:
        raise RecallError(f"the {side} is longer than {LONGEST} characters")
    return text


# ---- decks and cards --------------------------------------------------------


def deck_id(db: sqlite3.Connection, name: str) -> int:
    """The deck called name, made when it is not there yet."""
    name = " ".join(name.split())
    if not name:
        raise RecallError("a deck needs a name")
    if len(name) > 80:
        raise RecallError("a deck name is at most 80 characters")
    row = db.execute("SELECT id FROM decks WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    return int(db.execute("INSERT INTO decks(name) VALUES (?)", (name,)).lastrowid or 0)


def add_card(
    db: sqlite3.Connection,
    deck: str,
    front: str,
    back: str,
    key: str | None = None,
    when: datetime | None = None,
    source_hash: str | None = None,
    commit: bool = True,
) -> int:
    at = when or now()
    card = forge_fsrs.new_card(at)
    front, back = clean(front, "front"), clean(back, "back")  # before a deck is made
    cur = db.execute(
        "INSERT INTO cards(deck, front, back, source_key, source_hash, fsrs, due,"
        " created) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            deck_id(db, deck),
            front,
            back,
            key,
            source_hash,
            json.dumps(card),
            forge_fsrs.due_at(card).timestamp(),
            at.timestamp(),
        ),
    )
    if commit:
        db.commit()
    return int(cur.lastrowid or 0)


def get_card(db: sqlite3.Connection, card: int) -> sqlite3.Row:
    row = db.execute(
        "SELECT c.*, d.name AS deck_name FROM cards c JOIN decks d ON d.id = c.deck"
        " WHERE c.id = ? AND c.removed = 0",
        (card,),
    ).fetchone()
    if row is None:
        raise RecallError("no such card")
    return row


def edit_card(
    db: sqlite3.Connection, card: int, front: str, back: str, deck: str | None = None
) -> None:
    get_card(db, card)
    fields: list[Any] = [clean(front, "front"), clean(back, "back")]
    sql = "UPDATE cards SET front = ?, back = ?"
    if deck is not None:
        sql += ", deck = ?"
        fields.append(deck_id(db, deck))
    db.execute(sql + " WHERE id = ?", (*fields, card))
    db.commit()


def remove_card(db: sqlite3.Connection, card: int) -> None:
    """Hide a card. Kept in the file, so its reviews stay and a re-import
    of the same source does not bring it back."""
    get_card(db, card)
    db.execute("UPDATE cards SET removed = 1 WHERE id = ?", (card,))
    db.commit()


def card_json(row: sqlite3.Row, when: datetime | None = None) -> dict:
    card = json.loads(row["fsrs"])
    out = {
        "id": row["id"],
        "deck": row["deck_name"],
        "front": row["front"],
        "back": row["back"],
        "imported": row["source_key"] is not None,
        "answered": row["answered"],
        "due": row["due"],
        "state": "new" if not row["answered"] else forge_fsrs.state_name(card),
    }
    if row["answered"]:
        out["recall"] = round(forge_fsrs.recall_chance(card, when), 3)
    return out


def list_cards(
    db: sqlite3.Connection, deck: str = "", q: str = "", limit: int = 200
) -> list[dict]:
    sql = (
        "SELECT c.*, d.name AS deck_name FROM cards c JOIN decks d ON d.id = c.deck"
        " WHERE c.removed = 0"
    )
    args: list[Any] = []
    if deck:
        sql += " AND d.name = ?"
        args.append(deck)
    for word in q.split():
        like = (
            "%"
            + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        sql += " AND (c.front LIKE ? ESCAPE '\\' OR c.back LIKE ? ESCAPE '\\')"
        args += [like, like]
    sql += " ORDER BY c.id DESC LIMIT ?"
    args.append(limit)
    return [card_json(r) for r in db.execute(sql, args)]


# ---- the queue --------------------------------------------------------------


def new_seen_today(db: sqlite3.Connection, when: datetime) -> int:
    """Cards answered for the first time since local midnight, all decks."""
    row = db.execute(
        "SELECT COUNT(*) FROM (SELECT card, MIN(at) AS first FROM reviews GROUP BY card)"
        " WHERE first >= ?",
        (start_of_day(when),),
    ).fetchone()
    return int(row[0])


def new_left(db: sqlite3.Connection, when: datetime, per_day: int) -> int:
    return max(0, per_day - new_seen_today(db, when))


def _where_deck(deck: str) -> tuple[str, list[Any]]:
    if not deck:
        return "", []
    return " AND d.name = ?", [deck]


def counts(
    db: sqlite3.Connection, when: datetime, per_day: int, deck: str = ""
) -> dict:
    extra, args = _where_deck(deck)
    base = "FROM cards c JOIN decks d ON d.id = c.deck WHERE c.removed = 0" + extra
    due = db.execute(
        f"SELECT COUNT(*) {base} AND c.answered > 0 AND c.due <= ?",
        (*args, when.timestamp()),
    ).fetchone()[0]
    new = db.execute(f"SELECT COUNT(*) {base} AND c.answered = 0", args).fetchone()[0]
    total = db.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
    return {
        "due": due,
        "new": new,
        "new_today": min(new, new_left(db, when, per_day)),
        "total": total,
    }


def decks(db: sqlite3.Connection, when: datetime, per_day: int) -> list[dict]:
    out = []
    for row in db.execute("SELECT name FROM decks ORDER BY name COLLATE NOCASE"):
        c = counts(db, when, per_day, row["name"])
        if c["total"]:
            out.append({"name": row["name"], **c})
    return out


def next_card(
    db: sqlite3.Connection, when: datetime, per_day: int, deck: str = ""
) -> dict:
    """The card to show next, with what each answer would do, or when the
    next one comes due when nothing is due now."""
    extra, args = _where_deck(deck)
    base = (
        "SELECT c.*, d.name AS deck_name FROM cards c JOIN decks d ON d.id = c.deck"
        " WHERE c.removed = 0" + extra
    )
    row = db.execute(
        base + " AND c.answered > 0 AND c.due <= ? ORDER BY c.due LIMIT 1",
        (*args, when.timestamp()),
    ).fetchone()
    if row is None and new_left(db, when, per_day):
        row = db.execute(
            base + " AND c.answered = 0 ORDER BY c.id LIMIT 1", args
        ).fetchone()
    left = counts(db, when, per_day, deck)
    if row is None:
        soon = db.execute(
            "SELECT MIN(c.due) FROM cards c JOIN decks d ON d.id = c.deck"
            " WHERE c.removed = 0 AND c.answered > 0" + extra,
            args,
        ).fetchone()[0]
        return {"card": None, "next_due": soon, "left": left}
    intervals = forge_fsrs.next_intervals(json.loads(row["fsrs"]), when)
    return {
        "card": card_json(row, when),
        "after": {str(k): v for k, v in intervals.items()},
        "left": left,
    }


def answer(
    db: sqlite3.Connection, card: int, rating: int, when: datetime | None = None
) -> dict:
    at = when or now()
    row = get_card(db, card)
    try:
        updated, log = forge_fsrs.review(json.loads(row["fsrs"]), rating, at)
    except ValueError as e:
        raise RecallError(str(e)) from None
    due = forge_fsrs.due_at(updated).timestamp()
    db.execute(
        "UPDATE cards SET fsrs = ?, due = ?, answered = answered + 1 WHERE id = ?",
        (json.dumps(updated), due, card),
    )
    db.execute(
        "INSERT INTO reviews(card, rating, at, log) VALUES (?, ?, ?, ?)",
        (card, rating, at.timestamp(), json.dumps(log)),
    )
    db.commit()
    return {"due": due}


def stats(db: sqlite3.Connection, when: datetime) -> dict:
    """Today's answers, and how often a learned card was remembered over the
    last 30 days (anything but Again on a card answered before)."""
    today = start_of_day(when)
    done = db.execute(
        "SELECT COUNT(*) FROM reviews WHERE at >= ?", (today,)
    ).fetchone()[0]
    rows = db.execute(
        "SELECT r.rating FROM reviews r WHERE r.at >= ? AND EXISTS"
        " (SELECT 1 FROM reviews p WHERE p.card = r.card AND p.at < r.at)",
        (when.timestamp() - 30 * 86400,),
    ).fetchall()
    kept = sum(1 for r in rows if r[0] != forge_fsrs.AGAIN)
    tomorrow = (datetime.fromtimestamp(today) + timedelta(days=2)).timestamp()
    soon = db.execute(
        "SELECT COUNT(*) FROM cards WHERE removed = 0 AND answered > 0 AND due < ?",
        (tomorrow,),
    ).fetchone()[0]
    return {
        "today": done,
        "remembered": round(kept / len(rows), 3) if rows else None,
        "checked": len(rows),
        "due_by_tomorrow": soon,
    }


# ---- importing --------------------------------------------------------------


def _key(source: str, *parts: str) -> str:
    return source + ":" + ":".join(parts)


def source_root(source: dict) -> Path:
    """A source's folder: "{forge}" is the Forge folder, "~" the home."""
    return Path(str(source.get("root", "")).replace("{forge}", str(FORGE))).expanduser()


def _usable(config: dict) -> list[dict]:
    """The sources whose app ("app": its folder under apps/) is installed;
    a release without Study Companion offers no import from it."""
    return [
        s
        for s in config.get("sources", [])
        if not s.get("app") or (FORGE / "apps" / s["app"]).is_dir()
    ]


def _courses(root: Path) -> Iterator[Path]:
    if root.is_dir():
        for course in sorted(root.iterdir()):
            if course.is_dir() and not course.name.startswith("."):
                yield course


def study_bank(source: dict) -> Iterator[Found]:
    """Study Companion's question banks: data/<course>/questions/*.jsonl, one
    question per line ({id, question, steps, answer}); bad lines skipped."""
    for course in _courses(source_root(source)):
        for bank in sorted((course / "questions").glob("*.jsonl")):
            for line in bank.read_text(errors="replace").splitlines():
                try:
                    q = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(q, dict):
                    continue
                front = str(q.get("question") or "").strip()
                answer_text = str(q.get("answer") or "").strip()
                if not front or not answer_text:
                    continue
                steps = [str(s) for s in q.get("steps") or [] if str(s).strip()]
                back = answer_text + ("\n\n" + "\n".join(steps) if steps else "")
                ident = str(
                    q.get("id") or hashlib.sha1(front.encode()).hexdigest()[:12]
                )
                yield Found(
                    course.name,
                    front,
                    back,
                    _key(source["id"], course.name, bank.stem, ident),
                )


def note_lines(source: dict) -> Iterator[Found]:
    """Lines written as `front :: back` in a course's notes (a leading list
    mark is dropped). The key is the file and the front, so editing the back
    of a card in the notes updates it; the same front twice in one file
    keeps the first."""
    patterns = source.get("include") or ["*.txt", "*.md"]
    seen: set[str] = set()
    for course in _courses(source_root(source)):
        for path in sorted(course.rglob("*")):
            if not path.is_file() or not any(
                fnmatch.fnmatch(path.name, p) for p in patterns
            ):
                continue
            for line in path.read_text(errors="replace").splitlines():
                front, sep, back = line.partition("::")
                if not sep:
                    continue
                front = front.strip().lstrip("-*+ ").strip()
                back = back.strip()
                if front and back:
                    rel = path.relative_to(course).as_posix()
                    ident = hashlib.sha1(f"{rel}\0{front}".encode()).hexdigest()[:12]
                    key = _key(source["id"], course.name, ident)
                    if key not in seen:
                        seen.add(key)
                        yield Found(course.name, front, back, key)


IMPORTERS: dict[str, Callable[[dict], Iterator[Found]]] = {
    "study_bank": study_bank,
    "note_lines": note_lines,
}


def source_of(config: dict, source_id: str) -> dict:
    for source in _usable(config):
        if source.get("id") == source_id:
            if source.get("kind") not in IMPORTERS:
                raise RecallError(f"no importer for {source.get('kind')!r}")
            return source
    raise RecallError("no such source")


def sources(db: sqlite3.Connection, config: dict) -> list[dict]:
    """Each source with how many cards it offers and how many are in Recall."""
    out = []
    for source in _usable(config):
        kind = IMPORTERS.get(source.get("kind", ""))
        found = list(kind(source)) if kind else []
        have = db.execute(
            "SELECT COUNT(*) FROM cards WHERE source_key LIKE ? ESCAPE '\\'",
            (source["id"].replace("_", "\\_").replace("%", "\\%") + ":%",),
        ).fetchone()[0]
        out.append(
            {
                "id": source["id"],
                "label": source.get("label", source["id"]),
                "about": source.get("about", ""),
                "root": str(source_root(source)),
                "offers": len(found),
                "decks": sorted({f.deck for f in found}),
                "have": have,
            }
        )
    return out


def text_hash(front: str, back: str) -> str:
    return hashlib.sha1(f"{front}\0{back}".encode()).hexdigest()


def import_source(
    db: sqlite3.Connection, config: dict, source_id: str, when: datetime | None = None
) -> dict:
    """Add the cards a source offers that Recall does not have yet, and update
    the words of ones whose source changed since the last import (their
    schedule stays). A card edited in Recall keeps the edit; removed cards
    stay removed. All in one transaction: an error leaves nothing half done."""
    source = source_of(config, source_id)
    added = changed = same = kept = skipped = 0
    try:
        for f in IMPORTERS[source["kind"]](source):
            try:
                front, back = clean(f.front, "front"), clean(f.back, "back")
            except RecallError:
                skipped += 1
                continue
            h = text_hash(front, back)
            row = db.execute(
                "SELECT id, front, back, source_hash FROM cards WHERE source_key = ?",
                (f.key,),
            ).fetchone()
            if row is None:
                try:
                    add_card(db, f.deck, front, back, f.key, when, h, commit=False)
                except RecallError:  # a course folder that cannot be a deck name
                    skipped += 1
                    continue
                added += 1
            elif row["source_hash"] == h:
                same += 1
            elif (
                row["source_hash"]
                and text_hash(row["front"], row["back"]) != row["source_hash"]
            ):
                kept += 1  # edited in Recall since it came in: his words win
            else:
                db.execute(
                    "UPDATE cards SET front = ?, back = ?, source_hash = ? WHERE id = ?",
                    (front, back, h, row["id"]),
                )
                if (row["front"], row["back"]) == (front, back):
                    same += 1  # a card from before hashes, now hashed
                else:
                    changed += 1
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {
        "added": added,
        "changed": changed,
        "same": same,
        "kept": kept,
        "skipped": skipped,
    }
