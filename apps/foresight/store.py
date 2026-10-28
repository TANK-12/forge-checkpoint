"""Where Foresight's own data lives, and how it is written.

Signals accumulate forever — a daily attention figure per subject, for a
thousand subjects, never stops growing — so this follows Dossier onto the USB
drive rather than the internal disk. It is a **sibling** directory, not a
tenant of Dossier's: `ForesightData/` beside `DossierData/`. Foresight reads
Dossier's library and never writes a byte into it, which is what keeps the
factual record something the user can trust hasn't been edited by a planner.

A USB drive is removable, so `data_root()` falls back to a local directory and says
which one it got, exactly as Dossier does. Writes are atomic — temp file beside
the target, then a rename — so a yanked drive mid-write leaves the previous
good file rather than a truncated one.

Signal series are stored one file per subject per source, holding a dated list.
That shape is deliberate: a sweep appends today's reading and rewrites one
small file, rather than rewriting a single enormous one, and a corrupt file
costs one series instead of the lot.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dossier_link

USB_ROOT = Path(
    os.environ.get("FORESIGHT_USB_ROOT")
    or str(Path("/run/media") / getpass.getuser() / "Forge" / "ForesightData")
)
LOCAL_ROOT = Path(
    os.environ.get("FORESIGHT_LOCAL_ROOT", str(Path.home() / "ForesightData-local"))
)

SIGNALS = "signals"
FINDINGS = "findings"
CHATS = "chats"


@dataclass(frozen=True)
class Root:
    """Where we ended up writing, and whether that is the drive we wanted."""

    path: Path
    on_usb: bool
    detail: str


def _usable(path: Path) -> bool:
    """Can we actually write here right now?

    An unplugged USB usually leaves the mount point behind as an empty
    directory on the internal disk, so existence alone is not enough. The probe
    filename carries a uuid because several workers can arrive here at once,
    and a shared probe name meant one thread deleting the file another had just
    written — which reported a perfectly good drive as unwritable.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-probe-{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


_resolved: Root | None = None
_resolve_lock = threading.Lock()


def _beside_dossier() -> Path | None:
    """ForesightData/ beside the library Dossier was pointed at, if it exists.

    Never created here: an existing folder is the sign that Foresight's data
    moved together with Dossier's library."""
    library = dossier_link.chosen()
    if library is None:
        return None
    beside = library.parent / "ForesightData"
    return beside if beside.is_dir() else None


def data_root(refresh: bool = False) -> Root:
    """Where Foresight's data lives, decided once for the life of the process."""
    global _resolved
    with _resolve_lock:
        if _resolved is not None and not refresh:
            return _resolved
        beside = _beside_dossier()
        if beside is not None and _usable(beside):
            _resolved = Root(
                beside,
                str(beside).startswith("/run/media/"),
                f"Beside the Dossier library you chose: {beside}",
            )
        elif os.path.ismount(USB_ROOT.parent) and _usable(USB_ROOT):
            _resolved = Root(USB_ROOT, True, f"Drive mounted at {USB_ROOT.parent}")
        elif _usable(LOCAL_ROOT):
            _resolved = Root(
                LOCAL_ROOT,
                False,
                (
                    f"Saved in {LOCAL_ROOT}"
                    if LOCAL_ROOT == USB_ROOT
                    else f"Drive not mounted - using the local folder at {LOCAL_ROOT}"
                ),
            )
        else:
            raise RuntimeError(
                f"No writable data directory: tried {USB_ROOT} and {LOCAL_ROOT}"
            )
        return _resolved


# Matches Dossier's limit. A 200 kB slug used to start a sweep and fill its
# log, and made POST /api/plans a 500 (file name too long).
MAX_SLUG = 200


def slugify(name: str) -> str:
    """A stable directory name. Lowercased, because exfat is case-insensitive
    and 'Blair' and 'blair' must not fight over one directory.

    This matches Dossier's slugify exactly, which is what lets a Foresight
    signal series line up with the dossier it belongs to.
    """
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:MAX_SLUG].rstrip("-") or "unnamed"


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def series_key(source: str, series: str = "") -> str:
    """The name a series is stored under.

    `worldbank.unemployment` rather than a colon or a subdirectory: the key
    becomes a filename, and `Path.stem` strips only the last suffix, so the
    dotted form round-trips through `sources_for()` unchanged.
    """
    if not series:
        return source
    tidy = re.sub(r"[^a-z0-9]+", "-", series.strip().lower()).strip("-")
    return f"{source}.{tidy}" if tidy else source


class BadSlug(ValueError):
    """A subject slug that is not a single folder name: empty, "." or "..", or
    a path. Slugs often arrive straight from a URL or a request body."""


def check_slug(slug: str) -> str:
    if (
        not isinstance(slug, str)
        or not slug
        or len(slug) > MAX_SLUG
        or slug in (".", "..")
        or any(c in slug for c in "/\\\0")
    ):
        raise BadSlug(slug)
    return slug


def series_path(slug: str, source: str, root: Path | None = None) -> Path:
    check_slug(slug)
    base = root or data_root().path
    return base / SIGNALS / slug / f"{source}.json"


def read_series(slug: str, source: str, root: Path | None = None) -> list[dict]:
    """One subject's readings from one source, oldest first."""
    rows = read_json(series_path(slug, source, root), [])
    return rows if isinstance(rows, list) else []


def merge_series(
    slug: str, source: str, points: list[dict], root: Path | None = None
) -> dict:
    """Add readings to a series without ever losing or doubling one.

    A point is identified by its date, so re-running today's sweep overwrites
    today's reading rather than appending a second one — the same accumulate-
    never-duplicate rule Dossier uses for sources and events. A later sweep
    reporting a *corrected* figure for an earlier date wins, because the
    publisher revising a number is the only reason it would change.
    """
    existing: dict[str, dict] = {}
    for previous in read_series(slug, source, root):
        date = str(previous.get("date") or "")
        if date:
            existing[date] = previous
    added = 0
    updated = 0
    for point in points:
        date = str(point.get("date") or "")
        if not date:
            continue
        if date not in existing:
            added += 1
        elif existing[date] != point:
            updated += 1
        existing[date] = point
    merged = [existing[k] for k in sorted(existing)]
    write_json(series_path(slug, source, root), merged)
    return {"added": added, "updated": updated, "total": len(merged)}


def subjects_with_signals(root: Path | None = None) -> list[str]:
    base = (root or data_root().path) / SIGNALS
    if not base.is_dir():
        return []
    return sorted(d.name for d in base.iterdir() if d.is_dir())


def sources_for(slug: str, root: Path | None = None) -> list[str]:
    base = (root or data_root().path) / SIGNALS / check_slug(slug)
    if not base.is_dir():
        return []
    return sorted(p.stem for p in base.glob("*.json"))


def free_bytes(path: Path | None = None) -> int:
    try:
        return shutil.disk_usage(path or data_root().path).free
    except Exception:
        return -1
