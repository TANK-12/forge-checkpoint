"""Keepsakes and logbook pages: the only things Afterglow writes.

A keepsake is one JSON file, keepsakes/<curio>/<slug>.json in the data
folder, holding a name, a note, who made it, when, the curio's own `data` and
an optional thumbnail as an image data URL. Seeds are the same shape, shipped
in git as curios/<id>/seeds/<slug>.json, and are read-only. Nothing is ever
deleted: "put away" moves a file into keepsakes/<curio>/put-away/.

A logbook page is one JSON file too: shipped pages in logbook/ at the app
root, new ones in the data folder's logbook/.

The data folder is ~/ForgeGameData/afterglow, or $AFTERGLOW_DATA when set
(the tests point it at a temp folder). It is read on every call, never cached.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

APP = Path(__file__).resolve().parent
CURIOS_DIR = APP / "curios"
SHIPPED_LOGBOOK = APP / "logbook"

CURIO_ID = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
THUMB = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$")

MAX_NAME = 80
MAX_NOTE = 4000
MAX_AUTHOR = 60
MAX_DATA = 1_000_000
MAX_THUMB = 200_000
MAX_TITLE = 120
MAX_BODY = 20_000
MAX_DEPTH = 64
PUT_AWAY = "put-away"


class StoreError(Exception):
    """A request the store refuses; `status` is the HTTP code it maps to."""

    status = 400


class NotFound(StoreError):
    status = 404


class Conflict(StoreError):
    status = 409


def data_dir() -> Path:
    env = os.environ.get("AFTERGLOW_DATA")
    return Path(env) if env else Path.home() / "ForgeGameData" / "afterglow"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def slugify(text: str, fallback: str = "keepsake") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:48].strip("-")
    return slug or fallback


def _check_curio(curio: str) -> str:
    if not isinstance(curio, str) or not CURIO_ID.fullmatch(curio):
        raise StoreError(f"not a curio id: {curio!r}")
    return curio


def _check_slug(slug: str) -> str:
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        raise NotFound(f"no keepsake called {slug!r}")
    return slug


def _clean_text(value: Any, limit: int, what: str, required: bool = False) -> str:
    text = "" if value is None else str(value).strip()
    # Half an emoji (a lone surrogate, e.g. from a JS .slice()) cannot be
    # written as UTF-8; keep the rest of the text and mark the gap.
    text = "".join("\ufffd" if 0xD800 <= ord(c) <= 0xDFFF else c for c in text)
    if required and not text:
        raise StoreError(f"{what} is empty")
    if len(text) > limit:
        raise StoreError(f"{what} is longer than {limit} characters")
    return text


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _depth(value: Any) -> int:
    """How deeply lists and dicts nest inside value (a scalar is 0)."""
    deepest, stack = 0, [(value, 1)]
    while stack:
        item, level = stack.pop()
        if isinstance(item, dict):
            item = list(item.values())
        if isinstance(item, list):
            deepest = max(deepest, level)
            if level <= MAX_DEPTH:
                stack += [(child, level + 1) for child in item]
    return deepest


def _encode(data: Any, indent: int | None = 1, depth: int = MAX_DEPTH + 1) -> bytes:
    """data as UTF-8 JSON, or a StoreError saying why it cannot be kept.

    Everything is checked before a file is opened, so a refused save never
    leaves half a file behind to take the name. `depth` defaults to a whole
    file: a keepsake's data one level down inside its wrapper."""
    if _depth(data) > depth:
        raise StoreError(f"the data is nested more than {MAX_DEPTH} levels deep")
    try:
        text = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=indent)
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise StoreError("the data holds broken text (half of a character)") from exc
    except ValueError as exc:
        raise StoreError(
            "the data holds NaN or Infinity, which JSON cannot keep"
        ) from exc
    except (TypeError, RecursionError) as exc:
        raise StoreError(f"the data cannot be written as JSON ({exc})") from exc


def _write_new(path: Path, blob: bytes) -> bool:
    """Write a file that must not exist yet; False when it already does."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fh = path.open("xb")
    except FileExistsError:
        return False
    try:
        with fh:
            fh.write(blob)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return True


def _replace(path: Path, blob: bytes) -> None:
    """Swap in new contents; a temp file of its own, so writers never collide."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@contextmanager
def _locked() -> Iterator[None]:
    """One writer at a time across threads and processes (the app and play.py).

    flock locks belong to an open file, so two threads that each open the
    lock file wait for each other just as two processes do. On Windows the
    first byte of the file is locked instead (msvcrt.locking, which retries
    for about ten seconds before giving up), and a lock there likewise
    belongs to one open file."""
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / ".lock").open("a") as fh:
        if sys.platform == "win32":
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if sys.platform == "win32":
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fh, fcntl.LOCK_UN)


# --- keepsakes -----------------------------------------------------------------


def _live_dir(curio: str) -> Path:
    return data_dir() / "keepsakes" / curio


def _seed_dir(curio: str, curios_dir: Path | None = None) -> Path:
    return (curios_dir or CURIOS_DIR) / curio / "seeds"


def _summary(curio: str, slug: str, data: dict, seed: bool) -> dict:
    thumb = data.get("thumb")
    has_thumb = isinstance(thumb, str) and bool(THUMB.fullmatch(thumb))
    return {
        "id": f"{curio}/{slug}",
        "curio": curio,
        "slug": slug,
        "name": str(data.get("name") or slug),
        "note": str(data.get("note") or ""),
        "author": str(data.get("author") or ""),
        "made": str(data.get("made") or ""),
        "seed": seed,
        "thumb": f"/api/keepsakes/{curio}/{slug}/thumb" if has_thumb else None,
    }


def _files(curio: str, curios_dir: Path | None) -> list[tuple[Path, bool]]:
    found: list[tuple[Path, bool]] = []
    for folder, seed in (
        (_seed_dir(curio, curios_dir), True),
        (_live_dir(curio), False),
    ):
        if folder.is_dir():
            found += [
                (p, seed)
                for p in folder.glob("*.json")
                if SLUG.fullmatch(p.stem) is not None
            ]
    return found


def list_keepsakes(
    curio: str | None = None, curios_dir: Path | None = None
) -> list[dict]:
    """Summaries, newest first. A file that does not parse is skipped."""
    if curio is None:
        names: set[str] = set()
        for root in (curios_dir or CURIOS_DIR, data_dir() / "keepsakes"):
            if root.is_dir():
                names |= {p.name for p in root.iterdir() if CURIO_ID.fullmatch(p.name)}
        curios = sorted(names)
    else:
        curios = [_check_curio(curio)]
    rows = []
    for name in curios:
        for path, seed in _files(name, curios_dir):
            data = _read_json(path)
            if data is not None:
                rows.append(_summary(name, path.stem, data, seed))
    rows.sort(key=lambda r: (r["made"], r["slug"]), reverse=True)
    return rows


def _find(curio: str, slug: str, curios_dir: Path | None) -> tuple[Path, bool]:
    _check_curio(curio)
    _check_slug(slug)
    live = _live_dir(curio) / f"{slug}.json"
    if live.is_file():
        return live, False
    seed = _seed_dir(curio, curios_dir) / f"{slug}.json"
    if seed.is_file():
        return seed, True
    raise NotFound(f"no keepsake {curio}/{slug}")


def load_keepsake(curio: str, slug: str, curios_dir: Path | None = None) -> dict:
    path, seed = _find(curio, slug, curios_dir)
    data = _read_json(path)
    if data is None:
        raise StoreError(f"{curio}/{slug} does not read as JSON")
    full = _summary(curio, slug, data, seed)
    full["data"] = data.get("data")
    return full


def thumb_bytes(
    curio: str, slug: str, curios_dir: Path | None = None
) -> tuple[str, bytes]:
    data = _read_json(_find(curio, slug, curios_dir)[0]) or {}
    match = THUMB.fullmatch(str(data.get("thumb") or ""))
    if not match:
        raise NotFound(f"{curio}/{slug} has no picture")
    try:
        return f"image/{match.group(1)}", base64.b64decode(match.group(2))
    except (binascii.Error, ValueError) as exc:
        raise NotFound(f"{curio}/{slug} has a broken picture") from exc


def save_keepsake(
    curio: str,
    *,
    name: str,
    note: str = "",
    data: Any = None,
    author: str = "Claude",
    thumb: str | None = None,
    curios_dir: Path | None = None,
) -> dict:
    """Save a new keepsake and return its summary. Never overwrites."""
    _check_curio(curio)
    clean = {
        "name": _clean_text(name, MAX_NAME, "the name", required=True),
        "note": _clean_text(note, MAX_NOTE, "the note"),
        "author": _clean_text(author, MAX_AUTHOR, "the author") or "Claude",
        "made": now(),
        "data": data,
    }
    if len(_encode(data, indent=None, depth=MAX_DEPTH)) > MAX_DATA:
        raise StoreError(f"the data is bigger than {MAX_DATA // 1000} KB")
    if thumb:
        if (
            not isinstance(thumb, str)
            or len(thumb) > MAX_THUMB
            or not THUMB.fullmatch(thumb)
        ):
            raise StoreError(
                f"the picture must be a png, jpeg or webp data URL under {MAX_THUMB // 1000} KB"
            )
        clean["thumb"] = thumb
    blob = _encode(clean)
    base = slugify(clean["name"])
    seeds = _seed_dir(curio, curios_dir)
    away = _live_dir(curio) / PUT_AWAY
    with _locked():
        for n in range(1, 1000):
            slug = base if n == 1 else f"{base[:44]}-{n}"
            if (seeds / f"{slug}.json").exists() or (away / f"{slug}.json").exists():
                continue
            if _write_new(_live_dir(curio) / f"{slug}.json", blob):
                return _summary(curio, slug, clean, False)
    raise Conflict(f"too many keepsakes called {base!r}")


def edit_keepsake(
    curio: str,
    slug: str,
    *,
    name: str | None = None,
    note: str | None = None,
    curios_dir: Path | None = None,
) -> dict:
    with _locked():
        path, seed = _find(curio, slug, curios_dir)
        if seed:
            raise Conflict("a seed keepsake ships with the app and cannot be changed")
        data = _read_json(path)
        if data is None:
            raise StoreError(f"{curio}/{slug} does not read as JSON")
        if name is not None:
            data["name"] = _clean_text(name, MAX_NAME, "the name", required=True)
        if note is not None:
            data["note"] = _clean_text(note, MAX_NOTE, "the note")
        _replace(path, _encode(data))
    return _summary(curio, slug, data, False)


def put_away(curio: str, slug: str, curios_dir: Path | None = None) -> Path:
    """Move a keepsake into put-away/ (kept on disk, gone from the app)."""
    with _locked():
        path, seed = _find(curio, slug, curios_dir)
        if seed:
            raise Conflict("a seed keepsake ships with the app and cannot be put away")
        target = path.parent / PUT_AWAY / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        n = 2
        while target.exists():
            target = path.parent / PUT_AWAY / f"{slug}-{n}.json"
            n += 1
        try:
            os.replace(path, target)
        except FileNotFoundError as exc:
            raise NotFound(f"no keepsake {curio}/{slug}") from exc
    return target


def user_name() -> str:
    """Who is playing: the name Forge's welcome gave (FORGE_USER_NAME), else
    "you". Never a built-in person's name, so a fresh install reads right."""
    name = " ".join(os.environ.get("FORGE_USER_NAME", "").split())[:MAX_AUTHOR]
    return name or "you"


# --- logbook -------------------------------------------------------------------


def _page(path: Path, shipped: bool) -> dict | None:
    data = _read_json(path)
    if data is None or not str(data.get("title") or "").strip():
        return None
    curio = data.get("curio")
    return {
        "id": path.stem,
        "title": str(data["title"]),
        "body": str(data.get("body") or ""),
        "author": str(data.get("author") or ""),
        "made": str(data.get("made") or ""),
        "curio": (
            curio if isinstance(curio, str) and CURIO_ID.fullmatch(curio) else None
        ),
        "shipped": shipped,
    }


def list_pages(shipped_dir: Path | None = None) -> list[dict]:
    pages = []
    for folder, shipped in (
        (shipped_dir or SHIPPED_LOGBOOK, True),
        (data_dir() / "logbook", False),
    ):
        if folder.is_dir():
            for path in folder.glob("*.json"):
                page = _page(path, shipped)
                if page is not None:
                    pages.append(page)
    pages.sort(key=lambda p: (p["made"], p["id"]), reverse=True)
    return pages


def add_page(
    title: str, body: str, author: str = "Claude", curio: str | None = None
) -> dict:
    page = {
        "title": _clean_text(title, MAX_TITLE, "the title", required=True),
        "body": _clean_text(body, MAX_BODY, "the page", required=True),
        "author": _clean_text(author, MAX_AUTHOR, "the author") or "Claude",
        "made": now(),
    }
    if curio:
        page["curio"] = _check_curio(curio)
    blob = _encode(page)
    stamp = page["made"].replace(":", "").replace("T", "-")
    folder = data_dir() / "logbook"
    for n in range(1, 1000):
        stem = f"{stamp}-{slugify(page['title'], 'page')[:40]}"
        stem = stem if n == 1 else f"{stem}-{n}"
        if _write_new(folder / f"{stem}.json", blob):
            made = _page(folder / f"{stem}.json", False)
            assert made is not None
            return made
    raise Conflict("too many logbook pages with this title this second")
