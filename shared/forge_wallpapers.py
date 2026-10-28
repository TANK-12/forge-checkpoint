"""The wallpaper collection: an index, look-alike copies, favourites, and setting one.

Shared by the Wallpapers app (which is built around it) and Settings (which
shows favourites). Standard library only; ImageMagick's `magick` reads sizes
and fingerprints, as it already does for `forge_theme`.

THE INDEX
    ~/.cache/forge/wallpaper-index.json holds, for every picture in the folder
    (sub-folders included), its size on disk, modification time, pixel size
    and a 256-bit difference hash. Reading those from a 4K-8K image costs
    about half a second, so a picture is only read again when its size or
    modification time changes. The first index of ~240 pictures takes a
    couple of minutes, niced; after that it is instant.

LOOK-ALIKE COPIES
    The same picture saved twice, re-encoded as PNG, or upscaled, has almost
    the same difference hash. Measured on the real folder: true copies sat at
    0, 3 and 6 bits apart and the closest two *different* pictures at 37, so
    anything within DUPLICATE_DISTANCE bits and of the same shape is one
    picture. The copy with the most pixels is kept (then the bigger file); the
    rest are marked `duplicate_of` and hidden in the picker, never touched on
    disk.

FAVOURITES
    ~/.config/forge/wallpapers.json, beside the Forge settings, because they
    are the user's choices rather than a cache.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import forge_theme

DUPLICATE_DISTANCE = 12
# Width/height ratios further apart than this are different framings, never
# the same picture, whatever the hash says.
ASPECT_TOLERANCE = 0.03
HASH_W, HASH_H = 17, 16
# A failed magick read is tried this many times, this many seconds apart.
PROBE_TRIES = 2
PROBE_RETRY_WAIT = 1.0
# Why the last probe of a picture failed, by path; build_index moves it onto
# the picture's row as "probe_error" so the app can say why it is not indexed.
LAST_PROBE_ERROR: dict[str, str] = {}

# How a picture becomes the desktop wallpaper, first match wins. Adding a
# wallpaper tool is one row here.
# How to set the desktop wallpaper, per desktop: the first entry for the
# running desktop (XDG_CURRENT_DESKTOP) whose tool is installed wins, and all
# of its commands run. The owner switches between Hyprland and GNOME; on GNOME
# the Hyprland tools may be installed but change nothing, so they are never
# tried there. GNOME keeps a second picture for dark mode. {path} is the file,
# {uri} its file:// link. Another desktop or tool is one more entry.
DESKTOP_SETTERS: list[dict] = [
    {"desktop": "hyprland", "commands": [["caelestia", "wallpaper", "-f", "{path}"]]},
    {"desktop": "hyprland", "commands": [["awww", "img", "{path}"]]},
    {"desktop": "hyprland", "commands": [["swww", "img", "{path}"]]},
    {
        "desktop": "gnome",
        "commands": [
            [
                "gsettings",
                "set",
                "org.gnome.desktop.background",
                "picture-uri",
                "{uri}",
            ],
            [
                "gsettings",
                "set",
                "org.gnome.desktop.background",
                "picture-uri-dark",
                "{uri}",
            ],
        ],
    },
]


def current_desktop() -> str:
    return os.environ.get("XDG_CURRENT_DESKTOP", "").lower()


_index_lock = threading.Lock()


def index_path(cache: Path | None = None) -> Path:
    return (cache or forge_theme.CACHE) / "wallpaper-index.json"


def favourites_path() -> Path:
    return forge_theme.CONFIG.parent / "wallpapers.json"


# --- fingerprints -------------------------------------------------------------


def hash_bits(raw: bytes) -> int:
    """A difference hash from a 17x16 greyscale image, one byte per pixel.

    Each bit says whether a pixel is brighter than its right-hand neighbour,
    which survives resizing, re-encoding and small colour shifts.
    """
    if len(raw) < HASH_W * HASH_H:
        raise ValueError("not enough pixels for a hash")
    bits = 0
    for y in range(HASH_H):
        row = y * HASH_W
        for x in range(HASH_W - 1):
            bits = (bits << 1) | (raw[row + x] > raw[row + x + 1])
    return bits


def distance(a: str, b: str) -> int:
    """Bits that differ between two hex hashes."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def probe(source: Path) -> dict | None:
    """Pixel size and hash of one picture, or None if it cannot be read."""
    tool = forge_theme._magick()
    if not tool:
        LAST_PROBE_ERROR[str(source)] = "ImageMagick is not installed"
        return None
    frame = f"{source}[0]"
    hash_command = [
        tool,
        "-define",
        "jpeg:size=128x128",
        frame,
        "-colorspace",
        "gray",
        "-resize",
        f"{HASH_W}x{HASH_H}!",
        "-depth",
        "8",
        "gray:-",
    ]
    if shutil.which("nice"):
        hash_command = ["nice", "-n", "15", *hash_command]
    # magick can fail on a good picture under memory pressure, so one failed
    # read is tried again before the picture counts as unreadable.
    for attempt in range(PROBE_TRIES):
        try:
            size = subprocess.run(
                [tool, "identify", "-ping", "-format", "%w %h\n", frame],
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            ).stdout.split()
            raw = subprocess.run(
                hash_command, capture_output=True, timeout=120, check=True
            ).stdout
            LAST_PROBE_ERROR.pop(str(source), None)
            return {
                "width": int(size[0]),
                "height": int(size[1]),
                "hash": f"{hash_bits(raw):064x}",
            }
        except (subprocess.SubprocessError, OSError, ValueError, IndexError) as exc:
            LAST_PROBE_ERROR[str(source)] = _probe_error(exc)
            if attempt + 1 < PROBE_TRIES:
                time.sleep(PROBE_RETRY_WAIT)
    return None


def _probe_error(exc: BaseException) -> str:
    """A short, readable reason a probe failed."""
    if isinstance(exc, subprocess.CalledProcessError):
        detail = exc.stderr
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", "replace")
        detail = (detail or "").strip().splitlines()
        tail = detail[-1] if detail else ""
        return f"magick exited with code {exc.returncode}" + (
            f": {tail[:200]}" if tail else ""
        )
    if isinstance(exc, subprocess.TimeoutExpired):
        return "magick took too long"
    return f"{type(exc).__name__}: {str(exc)[:200]}"


# --- the index ------------------------------------------------------------------


def _read_entries(cache: Path | None) -> dict:
    try:
        data = json.loads(index_path(cache).read_text(encoding="utf-8"))
        return data.get("entries", {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _row(name: str, source: Path, known: dict | None) -> tuple[dict, bool]:
    """(the index row, whether it is current) for one listed picture."""
    stat = source.stat()
    fresh = (
        bool(known)
        and known.get("bytes") == stat.st_size
        and known.get("mtime") == int(stat.st_mtime)
        and bool(known.get("hash"))
    )
    if fresh and known:
        return dict(known, name=name), True
    return {
        "name": name,
        "bytes": stat.st_size,
        "mtime": int(stat.st_mtime),
        "width": 0,
        "height": 0,
        "hash": "",
    }, False


def cached_index(
    directory: Path | None = None, cache: Path | None = None
) -> tuple[list[dict], int]:
    """The listing with whatever is already known, reading no pictures.

    Returns (rows, how many still need reading). This is what the picker shows
    at once while `build_index` works through the rest.
    """
    directory = directory or forge_theme.WALLPAPER_DIR
    entries = _read_entries(cache)
    rows, stale = [], 0
    for listed in forge_theme.list_wallpapers(directory):
        try:
            row, fresh = _row(
                listed["name"], directory / listed["name"], entries.get(listed["name"])
            )
        except OSError:
            continue
        rows.append(row)
        stale += 0 if fresh else 1
    return rows, stale


def build_index(
    directory: Path | None = None,
    cache: Path | None = None,
    probe_fn=None,
    progress=None,
) -> list[dict]:
    """Bring the index up to date, reading only new or changed pictures.

    `progress(done, total)` is called after each picture. Pictures that have
    gone from the folder drop out of the index.
    """
    directory = directory or forge_theme.WALLPAPER_DIR
    probe_fn = probe_fn or probe
    with _index_lock:
        entries = _read_entries(cache)
        listing = forge_theme.list_wallpapers(directory)
        rows = []
        for done, listed in enumerate(listing, start=1):
            source = directory / listed["name"]
            try:
                row, fresh = _row(listed["name"], source, entries.get(listed["name"]))
            except OSError:
                continue
            if not fresh:
                read = probe_fn(source)
                why = LAST_PROBE_ERROR.pop(str(source), "")
                if read:
                    row.update(read)
                else:
                    row["probe_error"] = why or "the picture could not be read"
            rows.append(row)
            if progress:
                progress(done, len(listing))
        out = index_path(cache)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps({"version": 1, "entries": {r["name"]: r for r in rows}}),
            encoding="utf-8",
        )
        tmp.replace(out)
        return rows


# --- look-alike copies ------------------------------------------------------------


def _aspect(row: dict) -> float:
    return row["width"] / row["height"] if row.get("width") and row.get("height") else 0


def mark_duplicates(rows: list[dict], limit: int = DUPLICATE_DISTANCE) -> list[dict]:
    """Copies of `rows`, each with `duplicate_of`: None for a picture to show,
    or the name of the better copy that stands in for it."""
    out: list[dict] = [{**r, "duplicate_of": None} for r in rows]
    hashed = [i for i, r in enumerate(out) if r.get("hash") and _aspect(r)]
    parent = {i: i for i in hashed}

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for n, i in enumerate(hashed):
        for j in hashed[n + 1 :]:
            a, b = out[i], out[j]
            if abs(_aspect(a) - _aspect(b)) > ASPECT_TOLERANCE * max(
                _aspect(a), _aspect(b)
            ):
                continue
            if distance(a["hash"], b["hash"]) <= limit:
                parent[root(j)] = root(i)

    groups: dict[int, list[int]] = {}
    for i in hashed:
        groups.setdefault(root(i), []).append(i)
    for members in groups.values():
        if len(members) < 2:
            continue
        best = min(
            members,
            key=lambda i: (
                -out[i]["width"] * out[i]["height"],
                -out[i]["bytes"],
                out[i]["name"].lower(),
            ),
        )
        for i in members:
            if i != best:
                out[i]["duplicate_of"] = out[best]["name"]
    return out


# --- favourites -------------------------------------------------------------------


def favourites() -> list[str]:
    try:
        data = json.loads(favourites_path().read_text(encoding="utf-8"))
        names = data.get("favourites", []) if isinstance(data, dict) else []
        return [n for n in names if isinstance(n, str)]
    except Exception:
        return []


def set_favourite(name: str, on: bool) -> list[str]:
    names = [n for n in favourites() if n != name]
    if on:
        names.append(name)
    path = favourites_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"favourites": names}, indent=2), encoding="utf-8")
    tmp.replace(path)
    return names


def catalogue(rows: list[dict]) -> list[dict]:
    """Rows ready for a picker: look-alikes marked, favourites flagged."""
    stars = set(favourites())
    return [dict(r, favourite=r["name"] in stars) for r in mark_duplicates(rows)]


# --- previews and setting one -------------------------------------------------------


def preview(source: Path, cache: Path | None = None) -> Path | None:
    """A whole-picture preview no bigger than 1600 px, uncropped, cached."""
    cache = cache or forge_theme.CACHE
    out = cache / "previews" / f"{forge_theme._key(source)}.jpg"
    if out.is_file():
        return out
    tool = forge_theme._magick()
    if not tool:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.stem}.{os.getpid()}.{threading.get_ident()}.jpg")
    ok = forge_theme._run(
        [
            tool,
            "-define",
            "jpeg:size=3200x3200",
            f"{source}[0]",
            "-resize",
            "1600x1600>",
            "-strip",
            "-quality",
            "85",
            str(tmp),
        ]
    )
    if not ok:
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(out)
    return out


def set_desktop(source: Path, runner=subprocess.run) -> tuple[bool, str]:
    """Make `source` the desktop wallpaper with the running desktop's tool."""
    desktop = current_desktop()
    for setter in DESKTOP_SETTERS:
        if setter["desktop"] not in desktop:
            continue
        tool = setter["commands"][0][0]
        if not shutil.which(tool):
            continue
        fill = {"{path}": str(source), "{uri}": source.as_uri()}
        try:
            for template in setter["commands"]:
                command = [fill.get(part, part) for part in template]
                runner(command, check=True, capture_output=True, timeout=60)
        except Exception as e:
            return False, f"{tool} could not set it ({e})"
        return True, f"Desktop wallpaper set with {tool}"
    names = ", ".join(sorted({s["commands"][0][0] for s in DESKTOP_SETTERS}))
    return (
        False,
        f"No desktop wallpaper tool found for this desktop (looked for {names})",
    )
