"""Prompts: one library of prompts for Suno, AI Studio, Claude, Jan and
anything else, with every version kept and what came out of each.

Kept in one SQLite file in the data folder (PROMPTS_DATA_DIR overrides
~/.local/share/forge/prompts). Nothing is ever removed from it: saving a
changed prompt adds a version, archiving hides a prompt, and removing a
result only hides it. targets.json is the registry of targets and the
boxes each one's prompts have."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "targets.json"
MAX_TITLE = 120
MAX_FIELD = 50_000
MAX_NOTE = 2_000
MAX_RESULT = 20_000
MAX_TAGS = 12

SCHEMA = """
create table if not exists prompts (
  id integer primary key,
  title text not null,
  target text not null,
  tags text not null default '[]',
  created real not null,
  updated real not null,
  archived integer not null default 0
);
create table if not exists versions (
  prompt_id integer not null references prompts(id),
  n integer not null,
  at real not null,
  fields text not null,
  note text not null default '',
  primary key (prompt_id, n)
);
create table if not exists results (
  id integer primary key,
  prompt_id integer not null references prompts(id),
  version integer not null,
  at real not null,
  text text not null,
  rating integer not null default 0,
  link text not null default '',
  hidden integer not null default 0
);
"""


class PromptsError(Exception):
    """Something the page should show as it is."""


class NotFound(PromptsError):
    pass


def data_dir() -> Path:
    raw = os.environ.get("PROMPTS_DATA_DIR")
    return Path(raw) if raw else Path.home() / ".local/share/forge/prompts"


def load_targets(path: Path = REGISTRY) -> list[dict]:
    items = json.loads(path.read_text())["targets"]
    ids = [t["id"] for t in items]
    if len(ids) != len(set(ids)):
        raise PromptsError("targets.json has an id twice")
    for t in items:
        fids = [f["id"] for f in t["fields"]]
        if not fids or len(fids) != len(set(fids)):
            raise PromptsError(f"target {t['id']} needs fields with ids used once")
    return items


TARGETS = {t["id"]: t for t in load_targets()}


@contextmanager
def db(write: bool = False):
    """A connection; with write=True the whole block is one transaction that
    holds the write lock from its first read, so two saves at once queue up
    instead of both reading the same newest version."""
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(folder / "prompts.sqlite3", timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        with con:
            if write:
                con.execute("begin immediate")
            yield con
    finally:
        con.close()


# ---------- checks ----------


def text(value: object, what: str, limit: int, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise PromptsError(f"{what} is not text")
    if len(value) > limit:
        raise PromptsError(f"{what} is over {limit:,} characters")
    if required and not value.strip():
        raise PromptsError(f"{what} is empty")
    return value


def check_target(target: object) -> str:
    if target not in TARGETS:
        raise PromptsError(f"unknown target {target!r}")
    return str(target)


def check_tags(tags: object) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, list) or len(tags) > MAX_TAGS:
        raise PromptsError(f"tags are a list of up to {MAX_TAGS}")
    out: list[str] = []
    for tag in tags:
        clean = text(tag, "a tag", 40).strip().lower()
        if clean and clean not in out:
            out.append(clean)
    return out


def check_fields(target: str, fields: object) -> dict[str, str]:
    """Only the target's boxes, each text; at least one not empty."""
    if not isinstance(fields, dict):
        raise PromptsError("the prompt's boxes are not an object")
    known = {f["id"]: f["label"] for f in TARGETS[target]["fields"]}
    extra = set(fields) - set(known)
    if extra:
        raise PromptsError(
            f"{TARGETS[target]['label']} has no box {sorted(extra)[0]!r}"
        )
    out = {fid: text(fields.get(fid), label, MAX_FIELD) for fid, label in known.items()}
    if not any(v.strip() for v in out.values()):
        raise PromptsError("the prompt is empty")
    return out


def check_flag(value: object, what: str) -> bool:
    if not isinstance(value, bool):
        raise PromptsError(f"{what} must be true or false")
    return value


def check_rating(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 5:
        raise PromptsError("a rating is a whole number from 0 to 5")
    return value


def check_link(value: object) -> str:
    link = text(value, "the link", 2000).strip()
    if link and not link.startswith(("http://", "https://", "/", "~/")):
        raise PromptsError("a link is a web address or a file path")
    return link


# ---------- reading ----------


def summary(con: sqlite3.Connection, row: sqlite3.Row) -> dict:
    last = con.execute(
        "select n, fields from versions where prompt_id = ? order by n desc limit 1",
        (row["id"],),
    ).fetchone()
    counted = con.execute(
        "select count(*), max(rating) from results where prompt_id = ? and not hidden",
        (row["id"],),
    ).fetchone()
    fields = json.loads(last["fields"])
    first = next((v for v in fields.values() if v.strip()), "")
    return {
        "id": row["id"],
        "title": row["title"],
        "target": row["target"],
        "tags": json.loads(row["tags"]),
        "updated": row["updated"],
        "archived": bool(row["archived"]),
        "versions": last["n"],
        "results": counted[0],
        "best": counted[1] or 0,
        "preview": " ".join(first.split())[:160],
    }


def list_prompts(q: str = "", target: str = "", archived: bool = False) -> list[dict]:
    words = q.lower().split()
    with db() as con:
        rows = con.execute(
            "select * from prompts where archived = ? order by updated desc",
            (int(archived),),
        ).fetchall()
        out = []
        for row in rows:
            if target and row["target"] != target:
                continue
            if words:
                last = con.execute(
                    "select fields from versions where prompt_id = ?"
                    " order by n desc limit 1",
                    (row["id"],),
                ).fetchone()
                hay = " ".join(
                    [
                        row["title"],
                        *json.loads(row["tags"]),
                        *json.loads(last["fields"]).values(),
                    ]
                ).lower()
                if not all(w in hay for w in words):
                    continue
            out.append(summary(con, row))
        return out


def get_prompt(pid: int) -> dict:
    with db() as con:
        row = con.execute("select * from prompts where id = ?", (pid,)).fetchone()
        if not row:
            raise NotFound(f"no prompt {pid}")
        out = summary(con, row)
        out["created"] = row["created"]
        out["history"] = [
            {
                "n": v["n"],
                "at": v["at"],
                "fields": json.loads(v["fields"]),
                "note": v["note"],
            }
            for v in con.execute(
                "select * from versions where prompt_id = ? order by n desc", (pid,)
            )
        ]
        out["outcomes"] = [
            {k: r[k] for k in ("id", "version", "at", "text", "rating", "link")}
            for r in con.execute(
                "select * from results where prompt_id = ? and not hidden"
                " order by at desc",
                (pid,),
            )
        ]
        return out


# ---------- writing ----------


def create(body: dict) -> dict:
    target = check_target(body.get("target"))
    title = text(body.get("title"), "the title", MAX_TITLE, required=True).strip()
    tags = check_tags(body.get("tags"))
    fields = check_fields(target, body.get("fields"))
    note = text(body.get("note"), "the note", MAX_NOTE)
    now = time.time()
    with db(write=True) as con:
        cur = con.execute(
            "insert into prompts (title, target, tags, created, updated)"
            " values (?, ?, ?, ?, ?)",
            (title, target, json.dumps(tags, ensure_ascii=False), now, now),
        )
        pid = int(cur.lastrowid or 0)
        con.execute(
            "insert into versions values (?, 1, ?, ?, ?)",
            (pid, now, json.dumps(fields, ensure_ascii=False), note),
        )
    return get_prompt(pid)


def existing(con: sqlite3.Connection, pid: int) -> sqlite3.Row:
    row = con.execute("select * from prompts where id = ?", (pid,)).fetchone()
    if not row:
        raise NotFound(f"no prompt {pid}")
    return row


def change(pid: int, body: dict) -> dict:
    """Title, tags and archived; the target only while it fits the boxes."""
    with db(write=True) as con:
        apply_changes(con, existing(con, pid), body)
    return get_prompt(pid)


def apply_changes(con: sqlite3.Connection, row: sqlite3.Row, body: dict) -> bool:
    """Write the title, tags, archived and target in body that differ from
    row; True if anything changed."""
    pid = row["id"]
    sets: dict[str, object] = {}
    if "title" in body:
        sets["title"] = text(body["title"], "the title", MAX_TITLE, True).strip()
    if "tags" in body:
        sets["tags"] = json.dumps(check_tags(body["tags"]), ensure_ascii=False)
    if "archived" in body:
        sets["archived"] = int(check_flag(body["archived"], "archived"))
    if "target" in body and body["target"] != row["target"]:
        target = check_target(body["target"])
        last = con.execute(
            "select fields from versions where prompt_id = ? order by n desc limit 1",
            (pid,),
        ).fetchone()
        check_fields(target, json.loads(last["fields"]))
        sets["target"] = target
    sets = {k: v for k, v in sets.items() if row[k] != v}
    if sets:
        sets["updated"] = time.time()
        assign = ", ".join(f"{k} = ?" for k in sets)
        con.execute(f"update prompts set {assign} where id = ?", (*sets.values(), pid))
    return bool(sets)


def add_version(pid: int, body: dict) -> tuple[dict, bool]:
    """Save from the editor in one go: the title and tags if given, and a new
    version if the boxes changed; (prompt, made a new version). Nothing is
    written if any part is refused."""
    with db(write=True) as con:
        row = existing(con, pid)
        fields = check_fields(row["target"], body.get("fields"))
        note = text(body.get("note"), "the note", MAX_NOTE)
        meta = {k: body[k] for k in ("title", "tags") if k in body}
        apply_changes(con, row, meta)
        last = con.execute(
            "select n, fields from versions where prompt_id = ? order by n desc limit 1",
            (pid,),
        ).fetchone()
        made = json.loads(last["fields"]) != fields
        if made:
            now = time.time()
            con.execute(
                "insert into versions values (?, ?, ?, ?, ?)",
                (pid, last["n"] + 1, now, json.dumps(fields, ensure_ascii=False), note),
            )
            con.execute("update prompts set updated = ? where id = ?", (now, pid))
    return get_prompt(pid), made


def add_result(pid: int, body: dict) -> dict:
    with db(write=True) as con:
        existing(con, pid)
        version = body.get("version")
        if not isinstance(version, int) or isinstance(version, bool):
            raise PromptsError("the version must be a whole number")
        known = con.execute(
            "select 1 from versions where prompt_id = ? and n = ?", (pid, version)
        ).fetchone()
        if not known:
            raise PromptsError(f"this prompt has no version {version!r}")
        con.execute(
            "insert into results (prompt_id, version, at, text, rating, link)"
            " values (?, ?, ?, ?, ?, ?)",
            (
                pid,
                version,
                time.time(),
                text(body.get("text"), "what came out", MAX_RESULT, True),
                check_rating(body.get("rating", 0)),
                check_link(body.get("link")),
            ),
        )
    return get_prompt(pid)


def change_result(rid: int, body: dict) -> dict:
    with db(write=True) as con:
        row = con.execute("select * from results where id = ?", (rid,)).fetchone()
        if not row:
            raise NotFound(f"no result {rid}")
        sets: dict[str, object] = {}
        if "text" in body:
            sets["text"] = text(body["text"], "what came out", MAX_RESULT, True)
        if "rating" in body:
            sets["rating"] = check_rating(body["rating"])
        if "link" in body:
            sets["link"] = check_link(body["link"])
        if "hidden" in body:
            sets["hidden"] = int(check_flag(body["hidden"], "hidden"))
        if sets:
            assign = ", ".join(f"{k} = ?" for k in sets)
            con.execute(
                f"update results set {assign} where id = ?", (*sets.values(), rid)
            )
        pid = row["prompt_id"]
    return get_prompt(pid)


def export_all() -> dict:
    """Everything, archived and hidden too, as one JSON-able object."""
    with db() as con:
        ids = [r["id"] for r in con.execute("select id from prompts order by id")]
        hidden = [
            dict(r)
            for r in con.execute("select * from results where hidden order by id")
        ]
    return {
        "exported": time.time(),
        "prompts": [get_prompt(pid) for pid in ids],
        "hidden_results": hidden,
    }
