"""Cosmos - a real map of the solar system and the galaxy, and gravity games.

The backend is deliberately thin. The ephemeris, the physics and all drawing
run in the browser (static/core/ and static/modes/). This serves:

    /api/modes          every static/modes/<id>/mode.json, found by scanning
    /api/bodies         every data/bodies/*.json, found by scanning
    /api/catalog        whether the star catalog is present, and where
    /api/stars          the packed star positions (tools/build_star_catalog.py)
    /api/star-names     names and details of the named stars
    /api/scenarios      sandbox presets in ~/ForgeGameData/cosmos/scenarios
    /api/levels         orbit puzzle levels in ~/ForgeGameData/cosmos/levels
    /api/puzzles/progress   stars and best results, one JSON file
    /api/sounds         the cosmos-* sound recipes in ~/ForgeGameData/sounds

The star catalog lives in COSMOS_STARS_DIR (or on COSMOS_DRIVE_ROOT, with that
folder as the copy for when the drive is unplugged). Without it the map still
works with no stars, and offers "Get the stars": POST /api/catalog/get
downloads the free HYG catalog (about 14 MB) and builds it there.

Run standalone with:
    FORGE_SHARED_DIR=~/Forge/shared \\
    .venv/bin/python -m uvicorn web_app:app --host 127.0.0.1 --port 8446
"""

from __future__ import annotations

import json
import math
import os
import re
import struct
import sys
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
MODES_DIR = STATIC_DIR / "modes"
BODIES_DIR = ROOT / "data" / "bodies"
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR", ROOT.parent.parent / "shared"))
# What a player makes; $COSMOS_DATA moves it (a Forge release sets it).
COSMOS_DATA = Path(
    os.environ.get("COSMOS_DATA") or Path.home() / "ForgeGameData" / "cosmos"
)
SCENARIO_DIR = COSMOS_DATA / "scenarios"
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import build_star_catalog as catalog  # noqa: E402

if SHARED_DIR.is_dir() and str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
forge_content: Any
try:
    import forge_content  # noqa: E402
except ImportError:  # running without the Forge shared kit: no sounds
    forge_content = None

LEVEL_DIR = COSMOS_DATA / "levels"
PROGRESS_FILE = COSMOS_DATA / "puzzle-progress.json"
SOUND_PREFIX = "cosmos-"
GOAL_TYPES = {"reach", "orbit", "waypoints", "land", "explore"}
BODY_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
MAX_FOUND = 1000
NO_STORE = {"Cache-Control": "no-store"}

# Searched in order; the first folder holding a built catalog wins.
CATALOG_SOURCES: list[tuple[str, Path]] = (
    [("drive", catalog.DRIVE_DIR)] if catalog.DRIVE_DIR else []
) + [("local", catalog.CACHE_DIR)]

# "Get the stars": one download at a time, run on a thread so the page can
# keep asking how it is going.
FETCH: dict[str, Any] = {"state": "idle", "message": ""}
FETCH_LOCK = threading.Lock()

BODY_KINDS = {"star", "planet", "moon", "blackhole"}
MAX_BODIES = 2000
MAX_PARTICLES = 50000
MAX_GENERATORS = 32
SCENARIO_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")

import forge_revalidate  # noqa: E402  (lives in the shared folder)

app = FastAPI(title="Cosmos")
forge_revalidate.revalidate(app)


def _load_json(path: Path) -> dict[str, Any] | None:
    """A JSON object from disk, or None if the file is unreadable or not an object.
    One broken file should hide itself, not take the whole list down."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def list_modes() -> list[dict[str, Any]]:
    modes = []
    if MODES_DIR.is_dir():
        for folder in MODES_DIR.iterdir():
            data = _load_json(folder / "mode.json") if folder.is_dir() else None
            if data is None:
                continue
            data["id"] = folder.name
            data.setdefault("entry", "mode.js")
            data.setdefault("order", 100)
            modes.append(data)
    return sorted(modes, key=lambda m: (m["order"], m["id"]))


def list_bodies() -> list[dict[str, Any]]:
    bodies = []
    for path in BODIES_DIR.glob("*.json"):
        data = _load_json(path)
        if data is not None and data.get("id"):
            bodies.append(data)
    return sorted(bodies, key=lambda b: (b.get("order", 1000), b["id"]))


def find_catalog() -> tuple[str, Path] | None:
    for label, folder in CATALOG_SOURCES:
        try:
            if (folder / catalog.STARS_FILE).is_file() and (
                folder / catalog.NAMES_FILE
            ).is_file():
                return label, folder
        except OSError:  # a drive pulled out mid-check
            continue
    return None


def _star_count(folder: Path) -> int | None:
    try:
        with (folder / catalog.STARS_FILE).open("rb") as fh:
            magic, _version, count = catalog.HEADER.unpack(fh.read(catalog.HEADER.size))
    except (OSError, struct.error):
        return None
    return count if magic == catalog.MAGIC else None


@app.get("/api/modes")
def modes():
    return {"modes": list_modes()}


@app.get("/api/bodies")
def bodies():
    return {"bodies": list_bodies()}


@app.get("/api/catalog")
def catalog_status():
    found = find_catalog()
    if found is None:
        return {
            "available": False,
            "source": None,
            "count": 0,
            "credit": catalog.CREDIT,
            "hint": "Get the stars: a free download of about 110,000 real stars "
            "(the HYG database, 14 MB).",
            "fetch": dict(FETCH),
        }
    label, folder = found
    count = _star_count(folder)
    return {
        "available": count is not None,
        "source": label,
        "path": str(folder),
        "count": count or 0,
        "credit": catalog.CREDIT,
        "fetch": dict(FETCH),
    }


def _fetch_stars(out_dir: Path) -> None:
    try:
        result = catalog.fetch_and_build(out_dir)
        message = f"{result['count']:,} stars"
        state = "done"
    except Exception as e:  # noqa: BLE001  (shown to the player, not raised)
        print(f"cosmos: the stars could not be fetched: {e!r}", file=sys.stderr)
        state = "error"
        if isinstance(e, OSError):
            message = (
                "The stars could not be fetched: the internet could not be"
                " reached. Check the connection and try again."
            )
        else:
            message = f"The stars could not be fetched ({e})."
    with FETCH_LOCK:
        FETCH.update(state=state, message=message)


@app.post("/api/catalog/get")
def catalog_get():
    """Start fetching the star catalog into the local folder (once)."""
    with FETCH_LOCK:
        if FETCH["state"] == "getting":
            return dict(FETCH)
        FETCH.update(state="getting", message="Downloading the star catalog…")
    out_dir = CATALOG_SOURCES[-1][1]
    threading.Thread(target=_fetch_stars, args=(out_dir,), daemon=True).start()
    return dict(FETCH)


def _catalog_file(name: str, media_type: str) -> FileResponse:
    found = find_catalog()
    if found is None:
        raise HTTPException(404, "The star catalog is not available.")
    return FileResponse(
        found[1] / name,
        media_type=media_type,
        headers={"Cache-Control": "max-age=3600"},
    )


@app.get("/api/stars")
def stars():
    return _catalog_file(catalog.STARS_FILE, "application/octet-stream")


@app.get("/api/star-names")
def star_names():
    return _catalog_file(catalog.NAMES_FILE, "application/json")


# --- scenarios ----------------------------------------------------------------


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60].strip("-")
    return slug or "scenario"


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def validate_scenario(s: dict[str, Any]) -> None:
    """Raise ValueError with a plain reason if a scenario cannot be saved."""
    name = s.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise ValueError("A scenario needs a name of 1 to 80 characters.")
    for key in ("G", "softening", "dt"):
        if key in s and not (_finite(s[key]) and s[key] >= 0):
            raise ValueError(f"{key} must be a number of zero or more.")
    bodies = s.get("bodies", [])
    if not isinstance(bodies, list) or len(bodies) > MAX_BODIES:
        raise ValueError(f"bodies must be a list of at most {MAX_BODIES}.")
    for i, b in enumerate(bodies):
        if not isinstance(b, dict):
            raise ValueError(f"Body {i + 1} is not an object.")
        for key in ("m", "r"):
            if not (_finite(b.get(key)) and b[key] > 0):
                raise ValueError(f"Body {i + 1}: {key} must be a positive number.")
        for key in ("x", "y", "vx", "vy"):
            if not _finite(b.get(key, 0)):
                raise ValueError(f"Body {i + 1}: {key} must be a number.")
        if b.get("kind", "planet") not in BODY_KINDS:
            raise ValueError(f"Body {i + 1}: unknown kind {b.get('kind')!r}.")
    particles = s.get("particles", [])
    if not isinstance(particles, list) or len(particles) > MAX_PARTICLES:
        raise ValueError(f"particles must be a list of at most {MAX_PARTICLES}.")
    for p in particles:
        if not (isinstance(p, list) and len(p) == 5 and all(_finite(v) for v in p)):
            raise ValueError("Each particle must be [x, y, vx, vy, colour index].")
    generators = s.get("generators", [])
    if not isinstance(generators, list) or len(generators) > MAX_GENERATORS:
        raise ValueError(f"generators must be a list of at most {MAX_GENERATORS}.")


def _summary(sid: str, s: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": sid,
        "name": s.get("name", sid),
        "description": s.get("description", ""),
        "order": s.get("order", 1000),
        "bodies": len(s.get("bodies", [])),
        "particles": len(s.get("particles", []))
        + sum(int(g.get("count", 0)) for g in s.get("generators", [])),
        "saved": bool(s.get("saved")),
    }


@app.get("/api/scenarios")
def scenarios():
    rows = []
    if SCENARIO_DIR.is_dir():
        for path in SCENARIO_DIR.glob("*.json"):
            data = _load_json(path)
            if data is not None:
                rows.append(_summary(path.stem, data))
    rows.sort(key=lambda r: (r["saved"], r["order"], r["name"].lower()))
    return {"scenarios": rows, "folder": str(SCENARIO_DIR)}


@app.get("/api/scenarios/{sid}")
def scenario(sid: str):
    if not SCENARIO_ID.match(sid):
        raise HTTPException(404, "No such scenario.")
    data = _load_json(SCENARIO_DIR / f"{sid}.json")
    if data is None:
        raise HTTPException(404, "No such scenario.")
    return data


@app.post("/api/scenarios")
def save_scenario(payload: dict[str, Any]):
    try:
        validate_scenario(payload)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    base = slugify(payload["name"])
    sid, n = base, 2
    while (SCENARIO_DIR / f"{sid}.json").exists():
        sid, n = f"{base}-{n}", n + 1
    data = {"version": 1, **payload, "saved": True}
    tmp = SCENARIO_DIR / f".{sid}.json.part"
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(SCENARIO_DIR / f"{sid}.json")
    return {"id": sid, "scenario": _summary(sid, data)}


# --- orbit puzzles ------------------------------------------------------------


def _level_summary(lid: str, data: dict[str, Any]) -> dict[str, Any]:
    goal = data.get("goal") or {}
    listed = data.get("bodies")
    bodies = listed if isinstance(listed, list) else []
    return {
        "id": lid,
        "name": data.get("name", lid),
        "order": data.get("order", 1000),
        "caption": data.get("caption", ""),
        "goal": goal.get("type", ""),
        "discoverable": sum(
            1
            for b in bodies
            if isinstance(b, dict) and b.get("kind") in ("star", "blackhole")
        ),
    }


@app.get("/api/levels")
def levels():
    """Every level file, found by scanning. A file that is not JSON, or has no
    known goal, hides itself; the game checks the rest when it loads one."""
    rows = []
    if LEVEL_DIR.is_dir():
        for path in LEVEL_DIR.glob("*.json"):
            data = _load_json(path) if SCENARIO_ID.match(path.stem) else None
            goal = data.get("goal") if data else None
            if isinstance(goal, dict) and goal.get("type") in GOAL_TYPES:
                rows.append(_level_summary(path.stem, data or {}))
    rows.sort(key=lambda r: (r["order"], r["name"].lower()))
    return JSONResponse({"levels": rows, "folder": str(LEVEL_DIR)}, headers=NO_STORE)


@app.get("/api/levels/{lid}")
def level(lid: str):
    if not SCENARIO_ID.match(lid):
        raise HTTPException(404, "No such level.")
    data = _load_json(LEVEL_DIR / f"{lid}.json")
    if data is None:
        raise HTTPException(404, "No such level.")
    data["id"] = lid
    return JSONResponse(data, headers=NO_STORE)


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def read_progress() -> dict[str, Any]:
    data = _load_json(PROGRESS_FILE) or {}
    rows = data.get("levels")
    endless = data.get("endless")
    explore = data.get("explore")
    return {
        "version": 1,
        "levels": rows if isinstance(rows, dict) else {},
        "endless": {
            "best_difficulty": _count((endless or {}).get("best_difficulty")),
        },
        "explore": explore if isinstance(explore, dict) else {},
    }


def merge_discoveries(progress: dict[str, Any], result: dict[str, Any]) -> None:
    """Fold an explore flight in: the union of stars found, the farthest point
    reached and the longest flight. Raise ValueError for a malformed result."""
    lid = result.get("explore")
    if not isinstance(lid, str) or not SCENARIO_ID.match(lid):
        raise ValueError("That is not a level id.")
    found = result.get("found")
    if not isinstance(found, list) or len(found) > MAX_FOUND:
        raise ValueError(f"found must be a list of at most {MAX_FOUND} ids.")
    if not all(isinstance(f, str) and BODY_ID.match(f) for f in found):
        raise ValueError("found must hold body ids.")
    for key in ("farthest", "time"):
        if key in result and not (_finite(result[key]) and result[key] >= 0):
            raise ValueError(f"{key} must be a number of zero or more.")
    old = progress["explore"].get(lid)
    row = dict(old) if isinstance(old, dict) else {}
    kept = [f for f in row.get("found", []) if isinstance(f, str)]
    row["found"] = sorted(set(kept) | set(found))[:MAX_FOUND]
    for key, best in (("farthest", "farthest"), ("time", "longest_flight")):
        if key in result:
            prior = row.get(best)
            row[best] = max(prior, result[key]) if _finite(prior) else result[key]
    row["probes"] = _count(row.get("probes")) + (
        1 if result.get("ended") is True else 0
    )
    progress["explore"][lid] = row


def merge_result(progress: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Fold one finished flight into the saved progress, keeping the best of
    everything. Raise ValueError with a plain reason for a malformed result."""
    if "explore" in result:
        merge_discoveries(progress, result)
        return progress
    lid = result.get("level")
    if lid is not None:
        if not isinstance(lid, str) or not SCENARIO_ID.match(lid):
            raise ValueError("That is not a level id.")
        stars = result.get("stars")
        if not (isinstance(stars, int) and not isinstance(stars, bool)) or not (
            0 <= stars <= 3
        ):
            raise ValueError("stars must be a whole number from 0 to 3.")
        won = result.get("won")
        if not isinstance(won, bool):
            raise ValueError("won must be true or false.")
        for key in ("cost", "time"):
            if key in result and not (_finite(result[key]) and result[key] >= 0):
                raise ValueError(f"{key} must be a number of zero or more.")
        old = progress["levels"].get(lid)
        row = dict(old) if isinstance(old, dict) else {}
        row["plays"] = _count(row.get("plays")) + 1
        row["stars"] = max(_count(row.get("stars")), stars)
        if won:
            row["wins"] = _count(row.get("wins")) + 1
            for key, best in (("cost", "best_cost"), ("time", "best_time")):
                if key in result:
                    prior = row.get(best)
                    row[best] = (
                        min(prior, result[key]) if _finite(prior) else result[key]
                    )
        progress["levels"][lid] = row
        return progress
    if "endless_difficulty" in result:
        reached = result["endless_difficulty"]
        if not (isinstance(reached, int) and not isinstance(reached, bool)) or not (
            1 <= reached <= 100000
        ):
            raise ValueError("endless_difficulty must be a whole number of 1 or more.")
        endless = progress["endless"]
        endless["best_difficulty"] = max(endless["best_difficulty"], reached)
        return progress
    raise ValueError("Send a level result or an endless difficulty.")


@app.get("/api/puzzles/progress")
def progress():
    return JSONResponse(read_progress(), headers=NO_STORE)


@app.post("/api/puzzles/progress")
def save_progress(payload: dict[str, Any]):
    try:
        merged = merge_result(read_progress(), payload)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PROGRESS_FILE.is_file() and _load_json(PROGRESS_FILE) is None:
        # Keep an unreadable file rather than write over whatever it held.
        PROGRESS_FILE.replace(PROGRESS_FILE.with_name(PROGRESS_FILE.name + ".broken"))
    tmp = PROGRESS_FILE.with_name(f".{PROGRESS_FILE.name}.part")
    tmp.write_text(json.dumps(merged, indent=1), encoding="utf-8")
    tmp.replace(PROGRESS_FILE)
    return merged


@app.get("/api/sounds")
def sounds():
    """The cosmos-* recipes from the shared sound store. A broken recipe is
    reported by name instead of silencing the others."""
    if forge_content is None:
        return {"sounds": [], "problems": ["The Forge shared kit is missing."]}
    rows, problems = [], []
    for sid in forge_content.list_ids("sounds"):
        if not sid.startswith(SOUND_PREFIX):
            continue
        try:
            entry = forge_content.load("sounds", sid)
        except (OSError, ValueError, forge_content.ContentError) as exc:
            problems.append(f"sounds/{sid}.json: {exc}")
            continue
        entry["id"] = entry.get("id") or sid
        found = forge_content.validate("sounds", entry)
        if found:
            problems += [f"sounds/{sid}.json: {p}" for p in found]
            continue
        rows.append(entry)
    return {"sounds": rows, "problems": problems}


if SHARED_DIR.is_dir():
    app.mount("/shared", StaticFiles(directory=str(SHARED_DIR)), name="shared")


@app.get("/")
def index():
    target = STATIC_DIR / "index.html"
    if not target.is_file():
        return JSONResponse({"error": "static/index.html is missing"}, status_code=500)
    return FileResponse(target)


if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
