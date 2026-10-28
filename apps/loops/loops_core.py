"""Loops: patterns saved as JSON, loops exported as WAV files.

The page makes the sound (Web Audio) and renders a WAV itself; this side
keeps patterns in the data folder and writes exported WAVs into the loops
folder (~/Music/Loops), where Cut Room and the music video projects can
pick them up. An export never replaces a file: a name in use becomes
"name (2).wav". Deleting a pattern moves it to the desktop trash.

LOOPS_DATA_DIR and LOOPS_OUT_DIR override the two folders."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR") or ROOT.parent.parent / "shared")
sys.path.insert(0, str(SHARED_DIR))
from forge_static import free_names, plain_name  # noqa: E402

REGISTRY = ROOT / "instruments.json"
STEP_COUNTS = (8, 12, 16, 24, 32)
MAX_TRACKS = 24
MAX_NAME = 80
MAX_WAV = 200 * 1024 * 1024


class LoopsError(Exception):
    """Something the page should show as it is."""


def data_dir() -> Path:
    raw = os.environ.get("LOOPS_DATA_DIR")
    return Path(raw) if raw else Path.home() / ".local/share/forge/loops"


def out_dir() -> Path:
    raw = os.environ.get("LOOPS_OUT_DIR")
    return Path(raw) if raw else Path.home() / "Music" / "Loops"


def patterns_dir() -> Path:
    return data_dir() / "patterns"


def load_instruments(path: Path = REGISTRY) -> list[dict]:
    items = json.loads(path.read_text())["instruments"]
    ids = [i["id"] for i in items]
    if len(ids) != len(set(ids)):
        raise LoopsError("instruments.json has an id twice")
    if not 1 <= len(ids) <= MAX_TRACKS:
        raise LoopsError(f"instruments.json needs 1 to {MAX_TRACKS} instruments")
    return items


def check_name(name: object) -> str:
    """A pattern or loop name: one plain file name, short, no extension."""
    if not isinstance(name, str):
        raise LoopsError("the name is not text")
    clean = name.strip()
    if not clean or len(clean) > MAX_NAME or not plain_name(clean + ".json"):
        raise LoopsError(f"{name!r} cannot be a name: use letters, digits and spaces")
    return clean


def number(value: object, low: float, high: float, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LoopsError(f"{what} is not a number")
    if not math.isfinite(value) or not low <= value <= high:
        raise LoopsError(f"{what} must be between {low:g} and {high:g}")
    return float(value)


def check_pattern(pattern: object, instrument_ids: set[str]) -> dict:
    """The pattern as it will be saved, or LoopsError naming what is wrong."""
    if not isinstance(pattern, dict):
        raise LoopsError("the pattern is not an object")
    steps = pattern.get("steps")
    if steps not in STEP_COUNTS:
        raise LoopsError(f"steps must be one of {', '.join(map(str, STEP_COUNTS))}")
    tracks = pattern.get("tracks")
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= MAX_TRACKS:
        raise LoopsError(f"a pattern has 1 to {MAX_TRACKS} tracks")
    clean_tracks = []
    for n, track in enumerate(tracks, 1):
        if not isinstance(track, dict):
            raise LoopsError(f"track {n} is not an object")
        if track.get("instrument") not in instrument_ids:
            raise LoopsError(
                f"track {n}: unknown instrument {track.get('instrument')!r}"
            )
        cells = track.get("cells")
        if not isinstance(cells, list) or len(cells) != steps:
            raise LoopsError(f"track {n} needs {steps} cells")
        clean_tracks.append(
            {
                "instrument": track["instrument"],
                "gain": number(track.get("gain", 0.8), 0, 1.5, f"track {n} volume"),
                "mute": bool(track.get("mute", False)),
                "cells": [number(c, 0, 1, f"track {n} cell") for c in cells],
            }
        )
    return {
        "bpm": number(pattern.get("bpm"), 40, 240, "the tempo"),
        "swing": number(pattern.get("swing", 0), 0, 0.6, "the swing"),
        "steps": steps,
        "tracks": clean_tracks,
    }


def list_patterns() -> list[dict]:
    folder = patterns_dir()
    if not folder.is_dir():
        return []
    found = [
        {"name": p.stem, "mtime": p.stat().st_mtime}
        for p in folder.glob("*.json")
        if p.is_file() and not p.is_symlink()
    ]
    return sorted(found, key=lambda f: -f["mtime"])


def pattern_path(name: object) -> Path:
    return patterns_dir() / (check_name(name) + ".json")


def read_pattern(name: object, instrument_ids: set[str]) -> dict:
    """The saved pattern, checked like a save, and the instruments it used
    that are no longer in the registry (their tracks are left out)."""
    path = pattern_path(name)
    if not path.is_file() or path.is_symlink():
        raise LoopsError(f"no pattern called {name!r}")
    try:
        raw = json.loads(path.read_text())
        tracks = raw["tracks"]
        kept = [t for t in tracks if t.get("instrument") in instrument_ids]
        dropped = [str(t.get("instrument")) for t in tracks if t not in kept]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise LoopsError(f"{path.name} is not a Loops pattern") from None
    if not kept:
        raise LoopsError(f"none of the instruments in {path.name} are left")
    return {
        "pattern": check_pattern({**raw, "tracks": kept}, instrument_ids),
        "dropped": dropped,
    }


def save_pattern(name: object, pattern: object, instrument_ids: set[str]) -> dict:
    clean = check_pattern(pattern, instrument_ids)
    path = pattern_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise LoopsError("that pattern file is a link; it is left alone")
    # a fresh temp name made with O_EXCL: never a planted file or link
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(clean, indent=1))
    os.replace(tmp, path)
    return clean


def trash_pattern(name: object) -> None:
    path = pattern_path(name)
    if not path.is_file() or path.is_symlink():
        raise LoopsError(f"no pattern called {name!r}")
    # LOOPS_TRASH_CMD stands in for gio in the browser check (gio cannot
    # trash inside /tmp)
    custom = os.environ.get("LOOPS_TRASH_CMD")
    argv = [custom, str(path)] if custom else ["gio", "trash", "--", str(path)]
    done = subprocess.run(argv, capture_output=True, text=True)
    if done.returncode != 0:
        raise LoopsError(f"could not move it to the trash: {done.stderr.strip()}")


def is_wav(data: bytes) -> bool:
    return len(data) > 44 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


async def read_capped(chunks, limit: int = MAX_WAV) -> bytes:
    """The request body, refused as soon as it passes `limit` bytes."""
    got = bytearray()
    async for chunk in chunks:
        got += chunk
        if len(got) > limit:
            raise LoopsError("the WAV is over 200 MB; export fewer repeats")
    return bytes(got)


def export_wav(name: object, data: bytes) -> Path:
    """Writes the WAV into the loops folder under a name no file has."""
    if not is_wav(data):
        raise LoopsError("that is not a WAV file")
    if len(data) > MAX_WAV:
        raise LoopsError("the WAV is over 200 MB; export fewer repeats")
    folder = out_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for candidate in free_names(check_name(name) + ".wav"):
        path = folder / candidate
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return path
    raise LoopsError("every name like that is taken")
