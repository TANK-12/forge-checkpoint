"""Emberfield — a farming valley and a hostile wilds, in one Forge workspace.

Serves the game page and the small amount of state a browser cannot own: the
shared sprite library, settings, and save files. The game itself runs entirely
in the page; this process does no per-frame work and never blocks on a model.

Save data lives in ~/EmberfieldData, outside the app directory, following the
convention the other Forge apps use.
"""

import os
import sys
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT, "static")
SHARED_DIR = os.environ.get("FORGE_SHARED_DIR") or os.path.join(
    ROOT, "..", "..", "shared"
)
sys.path.insert(0, os.path.abspath(SHARED_DIR))

import forge_art  # noqa: E402
import forge_content  # noqa: E402

from emberfield import (
    config,
    interiors,
    resources,
    saves,
    wilds,
    worldgen,
)  # noqa: E402

app = FastAPI(title="Emberfield")


@app.middleware("http")
async def revalidate(request, call_next):
    """Ask the browser to check back before reusing a file. Without a header
    it guesses, and for scripts last touched weeks ago it keeps them for days:
    a fresh index.html then runs against stale scripts and the game never
    boots. The check is a cheap 304 when nothing changed."""
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-cache")
    return response


config.ensure_dirs()
_settings = config.load_settings()


class SettingsPatch(BaseModel):
    values: dict


class NewWorld(BaseModel):
    seed: int | None = None
    death_rule: str = "character"  # soft | character | full
    name: str = "Emberfield"


@app.get("/api/art/library")
def art_library():
    """The whole sprite library in one response. It is a few hundred kilobytes
    of text and the game bakes it once at boot, so paging it would only add
    latency."""
    return forge_art.library()


@app.get("/api/content")
def content_store():
    """All game content in one response, the same way the art library is served.

    Problems travel with the data rather than being raised, so a half-edited
    crop file shows up as a message on screen instead of a game that will not
    boot. Adding a crop is adding a file to this store -- there is no list of
    what exists anywhere in the code.
    """
    return forge_content.store()


@app.get("/api/settings")
def get_settings():
    return _settings


@app.post("/api/settings")
def update_settings(patch: SettingsPatch):
    values, problems = config.clean_settings(patch.values)
    if problems:
        raise HTTPException(422, "; ".join(problems))
    _settings.update(values)
    config.save_settings(_settings)
    resources.LANE.set_enabled(bool(_settings.get("serialise_heavy_work", True)))
    return _settings


@app.get("/api/capabilities")
def capabilities():
    """What this machine can actually do right now.

    The settings page reads this so the voice and LLM toggles can say why they
    are unavailable instead of failing silently when switched on.
    """
    return {
        "resources": resources.describe(int(_settings.get("heavy_cores", 6))),
        "voice": _voice_capability(),
        "llm": {
            "base": _settings.get("jan_base"),
            # Deliberately not probed here: a blocking network call on a page
            # load is exactly the kind of stall this app is built to avoid.
            "checked": False,
        },
        "art_root": forge_art.art_root(),
    }


def _voice_capability():
    """Piper and Kokoro live in NovelForge's virtualenv, and its voices are
    already downloaded. Emberfield reuses both rather than duplicating 453 MB."""
    voices_dir = config.TTS_VOICES_DIR
    present = []
    if os.path.isdir(voices_dir):
        present = sorted(
            name for name in os.listdir(voices_dir) if name.endswith((".onnx", ".bin"))
        )
    return {
        "voices_dir": voices_dir,
        "voices_present": present,
        "ready": bool(present),
        "cache": config.VOICE_CACHE,
        "cache_budget_mb": _settings.get("voice_bake_budget_mb", 200),
    }


@app.post("/api/world/new")
def new_world(payload: NewWorld):
    seed = payload.seed if payload.seed is not None else int(time.time() * 1000) % 2**31
    world = worldgen.generate(seed)
    # The title screen lets you name a valley now; the name is shown on the
    # save card, so it is kept to one line and never empty.
    name = " ".join(payload.name.split())[:60] or "Emberfield"
    return {
        "world": world.to_dict(),
        "tiles_meta": worldgen.TILES,
        "death_rule": payload.death_rule,
        "name": name,
    }


# The browser self-test posts its results here so an automated run can read them
# without scraping the page. It exists because the checks that render audio
# offline need real time to finish, and a headless browser driven with a virtual
# clock exits before they do -- so the page reports out of band instead.
_selftest_result: dict = {}


@app.post("/api/selftest")
def post_selftest(payload: dict):
    _selftest_result.clear()
    _selftest_result.update(payload)
    return {"received": True}


@app.get("/api/selftest")
def get_selftest():
    return _selftest_result or {"status": "no run recorded"}


class WildsRequest(BaseModel):
    seed: int
    day: int = 1
    night: bool = False


@app.post("/api/wilds")
def new_wilds(payload: WildsRequest):
    """One cycle's cavern.

    Regenerated from the valley's seed plus the day and whether it is night, so
    it is different every cycle and identical when a save is reloaded. Nothing
    about a run through the wilds is ever stored.
    """
    world = wilds.generate(payload.seed, payload.day, payload.night)
    return {
        "world": world.to_dict(),
        "tiles_meta": worldgen.TILES,
        "wilds": True,
    }


class InteriorRequest(BaseModel):
    building: str
    seed: int


@app.post("/api/interior")
def house_interior(payload: InteriorRequest):
    """One house's interior.

    The indoor counterpart to /api/wilds. Regenerated from the building id plus
    the valley's seed, so it is the same room every time you walk in and nothing
    about it needs storing. A save made indoors describes the valley, exactly as
    one made underground does.
    """
    world = interiors.generate(payload.building, payload.seed)
    return {
        "world": world.to_dict(),
        "tiles_meta": worldgen.TILES,
        "interior": True,
    }


@app.get("/api/saves")
def list_saves():
    return saves.list_saves()


@app.get("/api/saves/{slot}")
def read_save(slot: str):
    data = saves.load(slot)
    if data is None:
        raise HTTPException(404, f"no save in slot {slot}")
    return data


@app.post("/api/saves/{slot}")
def write_save(slot: str, payload: dict):
    return {"saved": True, "path": saves.save(slot, payload)}


@app.delete("/api/saves/{slot}")
def delete_save(slot: str):
    return {"deleted": saves.delete(slot)}


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as handle:
        return handle.read()


# The shared kit must mount before the catch-all, which would swallow it.
if os.path.isdir(SHARED_DIR):
    app.mount("/shared", StaticFiles(directory=SHARED_DIR), name="shared")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
