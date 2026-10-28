"""Reading Dossier's library, strictly read-only.

Foresight is the layer above Dossier: Dossier settles what is true, Foresight
works out what it means and what to do about it. That division only holds if
this module never writes. **Nothing here opens a file for writing**, and the
one action Foresight can take against Dossier — asking it to research
something — goes through Dossier's own HTTP API, so its merge rules and its
queue stay in charge of its data.

Two ways in, and both matter:

* **On disk** for bulk reading. The index and the per-subject files are a
  documented, stable layout, and reading 1,212 small JSON files directly is far
  cheaper than a thousand HTTP round trips.
* **Over HTTP** for actions and for anything where Dossier's own logic should
  decide — queueing research, asking a question of a dossier.

The disk path degrades gracefully: if the drive is unplugged, the library
simply reads as empty rather than raising, and the header says so.
"""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path

import httpx

# Dossier's own roots. Read from the same environment variables Dossier uses,
# so pointing one at a different drive points both.
DOSSIER_USB = Path(
    os.environ.get("DOSSIER_USB_ROOT")
    or str(Path("/run/media") / getpass.getuser() / "Forge" / "DossierData")
)
DOSSIER_LOCAL = Path(
    os.environ.get("DOSSIER_LOCAL_ROOT", str(Path.home() / "DossierData-local"))
)
DOSSIER_API = os.environ.get("DOSSIER_API", "http://127.0.0.1:8437")
# The library folder chosen in Dossier's own Location setting (Dossier's
# location.py writes it). The owner moved the library off the drive on 2026-09-25;
# without this Foresight kept reading the near-empty local fallback.
DOSSIER_CHOICE = Path(
    os.environ.get(
        "DOSSIER_LOCATION_FILE",
        str(Path.home() / ".config" / "forge-dossier" / "location.json"),
    )
)

FILES = {
    "subject": "subject.json",
    "timeline": "timeline.json",
    "claims": "claims.json",
    "quotes": "quotes.json",
    "relations": "relations.json",
    "sources": "sources.json",
    "notes": "notes.json",
}


def _is_library(path: Path) -> bool:
    return (path / "index.json").is_file() or (path / "subjects").is_dir()


def chosen() -> Path | None:
    """The folder Dossier was pointed at, while it still holds a library.

    Dossier itself only accepts a folder with both an index.json and a
    subjects/ folder, so the same test is used here."""
    try:
        path = Path(json.loads(DOSSIER_CHOICE.read_text(encoding="utf-8"))["path"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if (path / "index.json").is_file() and (path / "subjects").is_dir():
        return path
    return None


def root() -> Path | None:
    """The library Dossier itself reads: its chosen folder first, then
    whichever of its two default roots has a library in it, or None."""
    choice = chosen()
    if choice is not None:
        return choice
    for candidate in (DOSSIER_USB, DOSSIER_LOCAL):
        if _is_library(candidate):
            return candidate
    return None


def available() -> bool:
    return root() is not None


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def library() -> list[dict]:
    """Every subject Dossier holds, as index rows. Empty if the drive is away."""
    base = root()
    if base is None:
        return []
    rows = _read_json(base / "index.json", [])
    return rows if isinstance(rows, list) else []


def subject(slug: str) -> dict:
    """One subject's stored files, keyed the way Dossier names them."""
    base = root()
    if base is None or not slug or slug in (".", "..") or "/" in slug or "\\" in slug:
        return {}
    directory = base / "subjects" / slug
    if not directory.is_dir():
        return {}
    out: dict = {}
    for key, filename in FILES.items():
        default = {} if key in ("subject", "notes") else []
        out[key] = _read_json(directory / filename, default)
    return out


def ranked(limit: int = 200, entity_types: tuple[str, ...] = ()) -> list[dict]:
    """The subjects most worth watching, most consequential first.

    Prominence — how many language Wikipedias carry an article — is the same
    ranking Dossier's bulk queue uses, and the user was explicit about wanting
    the consequential names worked first rather than an alphabetical slice.
    Rows without a prominence figure fall back to how much is held about them,
    so an unranked subject is not silently dropped.
    """
    rows = [
        r for r in library() if not entity_types or r.get("entity_type") in entity_types
    ]
    rows.sort(
        key=lambda r: (
            r.get("prominence") or 0,
            r.get("sources", 0) + r.get("timeline", 0),
        ),
        reverse=True,
    )
    return rows[:limit]


def status() -> dict:
    base = root()
    rows = library()
    return {
        "available": base is not None,
        "path": str(base) if base else "",
        "subjects": len(rows),
        "detail": (
            f"{len(rows)} subjects at {base}"
            if base
            else "Dossier's library is not reachable - is the drive plugged in?"
        ),
    }


# --- the one way Foresight acts on Dossier ---------------------------------


def api_up(timeout: float = 2.0) -> bool:
    try:
        with httpx.Client(timeout=timeout) as client:
            return client.get(f"{DOSSIER_API}/api/status").status_code == 200
    except Exception:
        return False


def request_research(
    name: str, entity_type: str = "person", phase: str = "quick", timeout: float = 10.0
) -> dict:
    """Ask Dossier to research a subject, through its own queue.

    Deliberately not a direct write into its library: Dossier's queue decides
    whether the subject is already held, its pipeline decides what gets stored,
    and its merge rules guarantee nothing already there is lost. Foresight only
    gets to ask.
    """
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{DOSSIER_API}/api/research",
                json={"name": name, "entity_type": entity_type, "phase": phase},
            )
        if response.status_code >= 400:
            return {
                "queued": False,
                "detail": f"Dossier returned {response.status_code}",
            }
        return {"queued": True, "detail": "queued with Dossier", "job": response.json()}
    except Exception as e:
        return {"queued": False, "detail": f"Dossier unreachable ({type(e).__name__})"}
