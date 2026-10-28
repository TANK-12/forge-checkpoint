"""Where PrintForge looks for STL files, its settings, and the analysis cache.

Settings live in ~/.config/forge-printforge/settings.json and the per-file
analysis cache in ~/.cache/forge-printforge/info.json (both overridable with
PRINTFORGE_CONFIG_DIR / PRINTFORGE_CACHE_DIR, which the tests use). A file is
only ever served or analysed when it resolves inside one of the configured
roots and ends in .stl.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
from pathlib import Path

import stl

SKIP_DIRS = {".venv", "node_modules", "__pycache__", ".git", "wineprefix"}
MAX_DEPTH = 8
# Bump when stl.analyse gains or changes a field, so cached checks made by an
# older version are worked out again instead of missing the new field.
CACHE_VERSION = 2
_cache_lock = threading.Lock()
# Build reports: JSON files in a `reports` folder beside or above an STL.
REPORT_DIR = "reports"
REPORT_MAX_BYTES = 4_000_000
REPORT_MAX_FILES = 60
REPORT_MAX_FACTS = 14

DEFAULTS = {
    "roots": ["~/Models", "~/Downloads"],
    "advanced_mode": False,
    "bed": "filament 256 class",
    "beds": {
        "filament 256 class": [256, 256, 256],
        "filament 220 class": [220, 220, 250],
        "resin 218x123 class": [218, 123, 220],
        "resin 153x77 class": [153, 77, 165],
    },
    "color": "#c9c3b5",
    "light": 1.0,
    "overhang_angle": 45,
}


def config_dir() -> Path:
    return Path(
        os.environ.get("PRINTFORGE_CONFIG_DIR") or "~/.config/forge-printforge"
    ).expanduser()


def cache_dir() -> Path:
    return Path(
        os.environ.get("PRINTFORGE_CACHE_DIR") or "~/.cache/forge-printforge"
    ).expanduser()


def _number(x, lo: float, hi: float) -> bool:
    return (
        isinstance(x, (int, float))
        and not isinstance(x, bool)
        and math.isfinite(x)
        and lo <= x <= hi
    )


def _bed_ok(size) -> bool:
    return (
        isinstance(size, list)
        and len(size) == 3
        and all(_number(v, 1, 5000) for v in size)
    )


def _expands(root: str) -> bool:
    """A root whose ~ can be expanded (~nosuchuser cannot, and would make
    every library read fail)."""
    try:
        Path(root).expanduser()
    except RuntimeError:
        return False
    return True


# Why a stored or posted value is refused, per setting (None when it is fine).
CHECKS = {
    "roots": lambda v: (
        None
        if isinstance(v, list)
        and len(v) <= 64
        and all(
            isinstance(r, str) and 0 < len(r) <= 4096 and "\0" not in r and _expands(r)
            for r in v
        )
        else "roots must be a list of folder paths"
    ),
    "advanced_mode": lambda v: (
        None if isinstance(v, bool) else "mode must be true or false"
    ),
    "bed": lambda v: (
        None if isinstance(v, str) and 0 < len(v) <= 80 else "bed must be a bed name"
    ),
    "beds": lambda v: (
        None
        if isinstance(v, dict)
        and 0 < len(v) <= 32
        and all(
            isinstance(k, str) and 0 < len(k) <= 80 and _bed_ok(b) for k, b in v.items()
        )
        else "beds must map names to [width, depth, height] in mm (1 to 5000)"
    ),
    "color": lambda v: (
        None
        if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v)
        else "colour must look like #c9c3b5"
    ),
    "light": lambda v: (
        None if _number(v, 0.05, 5) else "light must be a number from 0.05 to 5"
    ),
    "overhang_angle": lambda v: (
        None
        if _number(v, 30, 80) and v % 5 == 0
        else "support angle must be 30 to 80 degrees in steps of 5"
    ),
}


def _settled(cur: dict) -> dict:
    """A bed that is not in the bed list falls back to the first bed."""
    if cur["bed"] not in cur["beds"]:
        cur["bed"] = next(iter(cur["beds"]))
    return cur


def load_settings() -> dict:
    """Stored settings over the defaults; a stored value that fails its check is ignored."""
    out = json.loads(json.dumps(DEFAULTS))
    p = config_dir() / "settings.json"
    if p.exists():
        try:
            stored = json.loads(p.read_text())
        except (OSError, ValueError):
            stored = {}
        if isinstance(stored, dict):
            for k, check in CHECKS.items():
                if k in stored and check(stored[k]) is None:
                    out[k] = stored[k]
    return _settled(out)


def save_settings(values: dict) -> dict:
    """Merge the known keys of `values` into the stored settings (ValueError if one is bad)."""
    cur = load_settings()
    for k, check in CHECKS.items():
        if k in values:
            why = check(values[k])
            if why:
                raise ValueError(why)
            cur[k] = values[k]
    _settled(cur)
    config_dir().mkdir(parents=True, exist_ok=True)
    (config_dir() / "settings.json").write_text(json.dumps(cur, indent=1))
    return cur


def root_labels(settings: dict | None = None) -> list[str]:
    """Each root as the real path on this system (no ~, native slashes), with
    "(not there)" after a folder that does not exist, for the empty-library text."""
    s = settings or load_settings()
    out = []
    for r in s["roots"]:
        try:
            p = os.path.normpath(os.path.expanduser(r))
        except (OSError, RuntimeError):
            p = str(r)
        out.append(p if os.path.isdir(p) else p + " (not there)")
    return out


def roots(settings: dict | None = None) -> list[Path]:
    s = settings or load_settings()
    out = []
    for r in s["roots"]:
        try:
            out.append(Path(r).expanduser().resolve())
        except (OSError, RuntimeError):
            continue  # an unexpandable ~user or a link loop: skip that root
    return out


def allowed(path: str, settings: dict | None = None) -> Path:
    """The resolved path if it is an .stl inside a root, else ValueError."""
    p = Path(path).expanduser().resolve()
    if p.suffix.lower() != ".stl" or not p.is_file():
        raise ValueError("not an STL file")
    for r in roots(settings):
        if p.is_relative_to(r):
            return p
    raise ValueError("outside the PrintForge folders")


def scale_of(path: Path) -> str | None:
    """A print scale written in the folder names, such as 1-35 or 1_35 -> '1:35'."""
    for part in reversed(path.parts[:-1]):
        m = re.fullmatch(r"1[-_:](\d{1,4})", part)
        if m:
            return f"1:{m.group(1)}"
    return None


def stamp(path: Path, st: os.stat_result | None = None) -> dict:
    """Size, time and triangle count of one STL, as the library lists them.
    The page compares path, size and `mtime_ns` to tell whether a file was
    exported again: a same-size re-export within the same second keeps the
    whole-second `mtime`. `mtime_ns` is a string because a nanosecond count
    is past what a JavaScript number holds exactly."""
    st = st or path.stat()
    return {
        "bytes": st.st_size,
        "mtime": int(st.st_mtime),
        "mtime_ns": str(st.st_mtime_ns),
        "triangles": stl.triangle_count(path),
    }


def scan(settings: dict | None = None) -> list[dict]:
    """Every STL under the roots, grouped by project (first folder under the root)."""
    out = []
    seen = set()
    for root in roots(settings):
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            d = Path(dirpath)
            dirnames[:] = [
                n
                for n in dirnames
                if not n.startswith(".")
                and n not in SKIP_DIRS
                and len(d.parts) - base_depth < MAX_DEPTH
            ]
            for name in filenames:
                if not name.lower().endswith(".stl"):
                    continue
                # a link out of the root, a broken link, a FIFO or a file
                # gone mid-scan skips that one entry, not the whole library
                try:
                    p = (d / name).resolve()
                    if p in seen or not p.is_file():
                        continue
                    rel = p.relative_to(root)
                    st = p.stat()
                except (OSError, RuntimeError, ValueError):
                    continue
                seen.add(p)
                out.append(
                    {
                        "path": str(p),
                        "name": p.stem,
                        "project": rel.parts[0] if len(rel.parts) > 1 else root.name,
                        "folder": (
                            str(Path(*rel.parts[1:-1])) if len(rel.parts) > 2 else ""
                        ),
                        "root": str(root),
                        **stamp(p, st),
                        "scale": scale_of(p),
                    }
                )
    out.sort(key=lambda f: (f["project"].lower(), f["folder"], f["name"].lower()))
    return out


def _cache() -> dict:
    p = cache_dir() / "info.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def info(path: Path) -> dict:
    """Cached analysis of one STL; recomputed when its size or nanosecond
    modification time (`st_mtime_ns`) changes, so a same-size re-export within
    the same second is analysed again, or when the cached result comes from an
    older CACHE_VERSION. Entries stamped in whole seconds miss once."""
    st = path.stat()
    stamp = [st.st_size, st.st_mtime_ns, CACHE_VERSION]
    hit = _cache().get(str(path))
    if hit and hit.get("stamp") == stamp:
        return hit["info"]
    result = stl.analyse(stl.read_triangles(path))
    # Two checks can finish at once (each request runs in its own thread):
    # read the cache again under the lock so neither drops the other's entry,
    # and write through a temp file of its own so neither renames the other's.
    with _cache_lock:
        cache = _cache()
        cache[str(path)] = {"stamp": stamp, "info": result}
        cache_dir().mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=cache_dir(), prefix="info.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(cache, handle)
            os.replace(tmp, cache_dir() / "info.json")
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    return result


def _fact(value):
    """A report value worth showing as one line, or None (nested or long)."""
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value if not isinstance(value, float) or math.isfinite(value) else None
    if isinstance(value, str):
        return value[:120]
    if (
        isinstance(value, list)
        and 0 < len(value) <= 4
        and all(_fact(x) is not None and not isinstance(x, list) for x in value)
    ):
        return value
    return None


def _report_facts(entry: dict) -> list:
    """[label, value] pairs from one report entry: its plain values, and the
    plain values one level down (`grow: {mm: 0.15}` becomes `grow mm`)."""
    out = []
    for key, value in entry.items():
        if key == "file":
            continue
        if isinstance(value, dict):
            for sub, inner in value.items():
                v = _fact(inner)
                if v is not None:
                    out.append([f"{key} {sub}".replace("_", " "), v])
        else:
            v = _fact(value)
            if v is not None:
                out.append([str(key).replace("_", " "), v])
    return out[:REPORT_MAX_FACTS]


def _entry_naming(data, path: Path, bases: list[Path], depth: int = 0):
    """(key, entry) of the first dict in a report whose "file" is `path`,
    read relative to each folder in `bases`; None when the report has none."""
    if depth > 3 or not isinstance(data, dict):
        return None
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        name = value.get("file")
        if isinstance(name, str) and name and "\0" not in name:
            for base in bases:
                try:
                    if (base / name).expanduser().resolve() == path:
                        return str(key), value
                except (OSError, RuntimeError, ValueError):
                    continue
        found = _entry_naming(value, path, bases, depth + 1)
        if found:
            return found
    return None


def report_for(path: Path, settings: dict | None = None) -> dict | None:
    """The newest build report that names this STL, or None.

    A build report is a JSON file in a `reports` folder in the STL's own
    folder or any folder above it inside the same PrintForge root (the print
    pipeline writes `print/reports/<milestone>_build.json` naming files such as
    `stl/1-35/statue_resin.stl`). Only plain values are returned, never the
    whole report."""
    root = next((r for r in roots(settings) if path.is_relative_to(r)), None)
    if root is None:
        return None
    best = None
    found = 0
    for folder in [path.parent, *path.parent.parents]:
        if not folder.is_relative_to(root):
            break
        rdir = folder / REPORT_DIR
        try:
            if not rdir.is_dir():
                continue
            names = sorted(rdir.glob("*.json"))[:REPORT_MAX_FILES]
        except OSError:
            continue
        for rp in names:
            try:
                real = rp.resolve()
                st = real.stat()
                if (
                    not real.is_file()
                    or not real.is_relative_to(root)
                    or st.st_size > REPORT_MAX_BYTES
                ):
                    continue
                data = json.loads(real.read_text(encoding="utf-8"))
            except (OSError, RuntimeError, ValueError):
                continue
            hit = _entry_naming(data, path, [folder, rdir])
            if not hit:
                continue
            found += 1
            if best is None or st.st_mtime > best[0]:
                best = (st.st_mtime, rp, data, hit)
    if best is None:
        return None
    mtime, rp, data, (key, entry) = best
    milestone = data.get("milestone") if isinstance(data, dict) else None
    try:
        stl_newer = path.stat().st_mtime > mtime + 1
    except OSError:
        stl_newer = False
    return {
        "report": rp.name,
        "folder": str(rp.parent),
        "modified": int(mtime),
        "milestone": milestone[:120] if isinstance(milestone, str) else None,
        "entry": key,
        "facts": _report_facts(entry),
        "others": found - 1,
        "stl_newer": stl_newer,
    }
