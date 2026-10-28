"""Finding the library folder again after it moved, and remembering the choice.

the owner moved the library off the drive onto the laptop (2026-09-25).
Every file inside the library is stored relative to the library folder, so
relinking means pointing Dossier at the folder, not rewriting thousands of
paths. The choice is saved here and beats the drive in
`store.data_root`, so plugging the drive back in cannot split the library
between an old copy and the new one.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

CHOICE_FILE = Path(
    os.environ.get(
        "DOSSIER_LOCATION_FILE",
        str(Path.home() / ".config" / "forge-dossier" / "location.json"),
    )
)

# A Forge release keeps the library with the rest of the user's things
# (DOSSIER_LOCAL_ROOT inside Forge's place, which Forge moves as a whole):
# no folder of its own is chosen or searched for, and the chooser is hidden.
FIXED = os.environ.get("DOSSIER_FIXED_LOCATION", "") not in ("", "0")

# Never searched: caches, virtualenvs, and the vendored Wine prefix.
SKIP = {"node_modules", "__pycache__", "wineprefix", "site-packages", "backups"}
MAX_DEPTH = 5


def describe(path: Path | str) -> dict | None:
    """A library folder has an index.json and a subjects/ folder."""
    path = Path(path)
    if not (path / "index.json").is_file() or not (path / "subjects").is_dir():
        return None
    subjects = sum(1 for p in (path / "subjects").iterdir() if p.is_dir())
    return {
        "path": str(path),
        "subjects": subjects,
        "modified": (path / "index.json").stat().st_mtime,
    }


def find(folders: Sequence[Path | str], depth: int = MAX_DEPTH) -> list[dict]:
    """Every library folder under the given folders, most subjects first."""
    found: dict[str, dict] = {}

    def walk(folder: Path, left: int) -> None:
        info = describe(folder)
        if info:
            found[info["path"]] = info
            return  # a library's own subfolders are not libraries
        if left == 0:
            return
        try:
            children = sorted(folder.iterdir())
        except OSError:
            return
        for child in children:
            if (
                child.name.startswith(".")
                or child.name in SKIP
                or child.is_symlink()
                or not child.is_dir()
            ):
                continue
            walk(child, left - 1)

    for folder in folders:
        if Path(folder).is_dir():
            walk(Path(folder), depth)
    return sorted(found.values(), key=lambda f: (-f["subjects"], f["path"]))


def search_places() -> list[Path]:
    """Home plus any mounted drives."""
    places = [Path.home()]
    for media in (Path("/run/media") / Path.home().name, Path("/mnt")):
        if media.is_dir():
            places.append(media)
    return places


def saved() -> Path | None:
    try:
        return Path(json.loads(CHOICE_FILE.read_text())["path"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def choose(path: Path | str) -> dict:
    """Remember a library folder; refuses a folder that is not one."""
    info = describe(path)
    if not info:
        raise ValueError(
            f"{path} is not a Dossier library (no index.json and subjects/)"
        )
    CHOICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHOICE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"path": info["path"]}))
    tmp.replace(CHOICE_FILE)
    return info
