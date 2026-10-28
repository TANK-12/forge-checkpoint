"""Where a dossier lives on disk, and how it is written.

The portfolio is meant to grow forever, so it lives on a USB drive
rather than the internal disk (which sits at 95%). A USB drive is removable, so every
read of the data root goes through `data_root()`, which falls back to a local
directory when the drive is unplugged and tells the caller which one it got.

Writes are atomic: a temp file beside the target, then a rename. A yanked USB
mid-write leaves the previous good file, not a truncated one.
"""

from __future__ import annotations

import gzip
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

import location

USB_ROOT = Path(
    os.environ.get("DOSSIER_USB_ROOT")
    or str(Path("/run/media") / getpass.getuser() / "Forge" / "DossierData")
)
LOCAL_ROOT = Path(
    os.environ.get("DOSSIER_LOCAL_ROOT", str(Path.home() / "DossierData-local"))
)

SUBJECTS = "subjects"
CLUSTERS = "clusters"
RUNS = "runs"


@dataclass(frozen=True)
class Root:
    """Where we ended up writing, and whether that is the drive we wanted."""

    path: Path
    on_usb: bool
    detail: str


def _usable(path: Path) -> bool:
    """Can we actually write here right now?

    An unplugged USB usually leaves the mount point behind as an empty
    directory on the internal disk, so existence alone is not enough - we check
    that the mount is live and that a write succeeds.

    The probe file carries a unique name. A shared name raced with itself the
    moment several subjects were researched at once: one thread unlinked the
    probe another thread had just written, the second thread's unlink raised
    FileNotFoundError, and this returned False for a drive that was working
    perfectly well.
    """
    probe = None
    try:
        if not path.parent.exists():
            return False
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-probe-{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        return True
    except Exception:
        return False
    finally:
        if probe is not None:
            try:
                probe.unlink()
            except OSError:
                pass


_resolved: Root | None = None
_resolve_lock = threading.Lock()


def data_root(refresh: bool = False) -> Root:
    """Where the library lives, decided once for the life of the process.

    This used to re-decide on every call, which meant a single transient probe
    failure could send one subject's files to the fallback directory while
    everything around it went to the drive - splitting the library in two with
    nothing reporting an error. The location is now resolved once and reused;
    `refresh=True` re-checks deliberately, for a UI that wants to notice a
    drive being plugged in.
    """
    global _resolved
    with _resolve_lock:
        if _resolved is not None and not refresh:
            return _resolved
        if location.FIXED:
            if not _usable(LOCAL_ROOT):
                raise RuntimeError(f"No writable data directory: {LOCAL_ROOT}")
            _resolved = Root(
                LOCAL_ROOT, False, "Kept with the rest of your Forge things"
            )
            return _resolved
        chosen = location.saved()
        missing = ""
        if chosen and location.describe(chosen) and _usable(chosen):
            _resolved = Root(
                chosen,
                str(chosen).startswith("/run/media/"),
                f"The library folder you chose: {chosen}",
            )
            return _resolved
        if chosen:
            missing = f"Your chosen folder {chosen} was not found. "
        if os.path.ismount(USB_ROOT.parent) and _usable(USB_ROOT):
            _resolved = Root(
                USB_ROOT, True, missing + f"Drive mounted at {USB_ROOT.parent}"
            )
        elif _usable(LOCAL_ROOT):
            _resolved = Root(
                LOCAL_ROOT,
                False,
                missing + f"Drive not mounted - using the local folder at {LOCAL_ROOT}",
            )
        else:
            raise RuntimeError(
                f"No writable data directory: tried {USB_ROOT} and {LOCAL_ROOT}"
            )
        return _resolved


# The longest real slug is 128 characters (2026-10-08); a folder name may not
# pass 255 bytes, and a few files are named after the slug plus a suffix.
MAX_SLUG = 200


def slugify(name: str) -> str:
    """A stable directory name for a subject.

    exfat is case-insensitive, so the slug is lowercased to stop 'Blair' and
    'blair' fighting over one directory.
    """
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:MAX_SLUG].rstrip("-") or "unnamed"


class BadSlug(ValueError):
    """A subject name that is not a single folder name: empty, "." or "..", or
    a path. Slugs often arrive straight from a URL."""


def subject_dir(slug: str, root: Path | None = None) -> Path:
    # Before this check, DELETE /api/subject/.. removed the whole library
    # folder: subjects/.. is the library itself.
    if (
        not slug
        or len(slug) > MAX_SLUG
        or slug in (".", "..")
        or any(c in slug for c in "/\\\0")
    ):
        raise BadSlug(slug)
    base = root or data_root().path
    return base / SUBJECTS / slug


def ensure_subject(slug: str, root: Path | None = None) -> Path:
    d = subject_dir(slug, root)
    (d / "pages").mkdir(parents=True, exist_ok=True)
    (d / "text").mkdir(parents=True, exist_ok=True)
    return d


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


def write_text_gz(path: Path, text: str) -> int:
    """Store extracted article text compressed. Returns bytes written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return path.stat().st_size


def read_text_gz(path: Path, default: str = "") -> str:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return default


def read_text_bundle(directory: Path) -> dict:
    """Every stored article text for one subject, from a single file.

    One file per source looks tidier but is ruinous here: the USB drive is
    exfat with a 256 KB cluster, and a 181-byte extract still consumes a whole
    cluster. 675 of them turned 3.9 MB of real text into 303 MB on disk. One
    bundle per subject keeps the same content in one cluster-friendly file.
    """
    return read_json_gz(directory / "text.json.gz", {})


def write_text_bundle(directory: Path, texts: dict) -> int:
    write_json_gz(directory / "text.json.gz", texts)
    return (directory / "text.json.gz").stat().st_size


def read_json_gz(path: Path, default: Any = None) -> Any:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def write_json_gz(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, path)


def free_bytes(path: Path | None = None) -> int:
    target = path or data_root().path
    return shutil.disk_usage(target).free
