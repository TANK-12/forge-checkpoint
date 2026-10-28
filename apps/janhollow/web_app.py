"""Janhollow — a space station that lives on its own, in a Forge workspace.

The station is data: four deck files, twenty-five room files and eight crew
files in ~/ForgeGameData/janhollow/. Adding a crew member is one more file in
npcs/; adding a deck is one more file in decks/. Nothing in this process holds
a list of what exists.

The simulation runs here rather than in the page (see janhollow/sim.py), so the
station can keep living with the tab closed when its away mode says it may.
The page polls /api/world/state and draws what it finds.

Models: Jan is wired through shared/forge_jan.py with two roles -- a 0.8B
"chatter" for crew lines and a 4B "narrator" for events and summaries -- which
gives this app its own model settings and hands the memory back when they go
idle. Session 1 uses neither: the settings surface is here, the calls are not.
"""

import os
import sys
import threading
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
import forge_jan  # noqa: E402

from janhollow import (  # noqa: E402
    carry,
    content,
    director as director_module,
    janclient,
    roles,
    saves,
    sim,
    station,
)

import forge_revalidate  # noqa: E402  (lives in the shared folder)

app = FastAPI(title="Janhollow")
forge_revalidate.revalidate(app)

# Two lanes, as the plan sets out: the small model writes crew lines, the big
# one narrates. Declaring both now means the settings panel is complete from
# the first session even though nothing calls them yet.
jan = forge_jan.mount(app, "janhollow", roles=("chatter", "narrator"))

_state_lock = threading.Lock()
_station: station.Station | None = None
_world: sim.World | None = None
_director: director_module.Director | None = None
_last_autosave = 0.0
AUTOSAVE_EVERY = 60.0

# One client for the process: it owns the single lane that keeps two Jan
# requests from ever running at once.
_jan_client = janclient.Client(guard=jan, preferences=roles.preferences())


def build_world(settings=None, save_state=None):
    """(Re)build the station from the content store and start its clock.

    Called at startup and whenever the content or the world is reset, so a file
    edited in ~/ForgeGameData shows up without restarting the backend.
    """
    global _station, _world, _director
    store = content.store()
    # Prop sizes come from the art library so the station can lay furniture out
    # at its real footprint rather than assuming one tile each.
    built = station.build(
        store, sprite_sizes=station.sprite_sizes_from_library(forge_art.library())
    )
    crew = list(store["types"].get("npcs", {}).values())
    world = sim.World(built, crew, settings=settings, content=store)
    world.reject_folder = content.data_root()
    if save_state:
        world.load_state(save_state)
        for member in world.crew.values():
            if not member.deck:
                member.place_at(member.location or member.record.get("home", ""))
    with _state_lock:
        if _world is not None:
            _world.stop()
        if _director is not None:
            _director.stop()
        _station, _world = built, world
        _director = director_module.Director(world, _jan_client)
    world.start()
    _director.start()
    return world


def world() -> sim.World:
    if _world is None:
        build_world(save_state=saves.read(saves.AUTOSAVE))
    assert _world is not None
    return _world


def autosave_if_due(force=False):
    global _last_autosave
    now = time.monotonic()
    if not force and now - _last_autosave < AUTOSAVE_EVERY:
        return
    _last_autosave = now
    state = world().save_state()
    state["clock"] = sim.clock_text(state["minute"])
    saves.write(saves.AUTOSAVE, state)


@app.on_event("startup")
def _startup():
    content.STORE.ensure_root()
    build_world(save_state=saves.read(saves.AUTOSAVE))


@app.on_event("shutdown")
def _shutdown():
    if _director is not None:
        _director.stop()
    if _world is not None:
        autosave_if_due(force=True)
        _world.stop()


# --- what the station is ----------------------------------------------------


@app.get("/api/station")
def get_station():  # noqa: D401
    """The built decks and rooms. The page bakes this once and then only polls
    for state, because the station does not change while you watch it."""
    built = _station or station.build(
        content.store(),
        sprite_sizes=station.sprite_sizes_from_library(forge_art.library()),
    )
    out = built.to_dict()
    if _director is not None:
        # A broken file of written lines is shown with the rest of the
        # content's problems instead of failing quietly.
        out["problems"] = list(out.get("problems") or []) + list(
            _director.written["problems"]
        )
    return out


@app.get("/api/content")
def get_content():
    """The raw content store, problems included, so a half-edited crew file
    shows up as a message on screen instead of a crew member who never appears."""
    return content.store()


@app.get("/api/art/library")
def art_library():
    return forge_art.library()


@app.get("/api/options")
def options():
    """Everything the settings panel needs to draw itself, so adding an away
    mode or a chatter level is an entry in sim.py and nothing else."""
    return {
        "away_modes": {
            key: {"label": mode["label"], "detail": mode["detail"]}
            for key, mode in sim.AWAY_MODES.items()
        },
        "chatter": {
            key: {"label": level["label"], "per_minute": level["per_minute"]}
            for key, level in sim.CHATTER_LEVELS.items()
        },
        "barks": {
            key: {"label": level["label"], "per_minute": level["per_minute"]}
            for key, level in sim.BARK_LEVELS.items()
        },
        "defaults": sim.DEFAULT_SETTINGS,
        "data_root": content.data_root(),
        "roles": roles.describe(),
    }


# --- the world --------------------------------------------------------------


@app.get("/api/world/state")
def world_state(since: int = 0):
    autosave_if_due()
    return world().snapshot(since=since)


class Presence(BaseModel):
    focused: bool = True


@app.post("/api/world/presence")
def world_presence(payload: Presence):
    """The page's heartbeat. Away modes are decided from this: no heartbeat for
    a few seconds means the tab is closed, not merely in the background."""
    live = world()
    summary = live.saw_page(payload.focused)
    snapshot = live.snapshot()
    snapshot["caught_up"] = summary
    return snapshot


class SettingsPatch(BaseModel):
    values: dict


@app.post("/api/world/settings")
def world_settings(patch: SettingsPatch):
    updated = world().update_settings(patch.values)
    autosave_if_due(force=True)
    return {"settings": updated}


class NewWorld(BaseModel):
    settings: dict = {}


@app.post("/api/world/new")
def world_new(payload: NewWorld):
    """Start the station over. The crew and the decks come back from their
    files, so 'new' means a new clock and a new log, not new content."""
    live = build_world(settings=payload.settings)
    autosave_if_due(force=True)
    return live.snapshot()


@app.post("/api/world/reload")
def world_reload():
    """Re-read the content store after editing a file, keeping the clock."""
    state = world().save_state()
    live = build_world(save_state=state)
    return live.snapshot()


@app.get("/api/world/voices")
def voices():
    """What the models are doing: what the director is up to, how many lines
    were said and how many the guard threw away."""
    live = world()
    return {
        "director": _director.status() if _director else {},
        "models": live.model_status,
        "settings": {
            "chatter": live.settings["chatter"],
            "barks": live.settings["barks"],
            "away_mode": live.settings["away_mode"],
        },
        "allowed_now": live.models_allowed(),
        "jan_online": _jan_client.online(),
        "roles": {
            "chatter": _jan_client.model_for("chatter"),
            "narrator": _jan_client.model_for("narrator"),
        },
    }


@app.post("/api/world/talk")
def talk_now():
    """Run one conversation immediately, whatever the schedule says.

    It exists because waiting a minute to find out whether the models are
    working is a bad way to check, and because it is a nice thing to be able to
    press.
    """
    live = world()
    if _director is None:
        raise HTTPException(503, "the station is still starting")
    before = live.model_status["conversations"]
    _director.talk()
    return {
        "happened": live.model_status["conversations"] > before,
        "conversation": live.conversations[-1] if live.conversations else None,
        "models": live.model_status,
    }


@app.post("/api/world/narrate")
def narrate_now():
    """Ask the narrator for today's event now. Slow on purpose: the 4B takes
    about twenty seconds."""
    live = world()
    if _director is None:
        raise HTTPException(503, "the station is still starting")
    _director.narrate_day()
    return {"day_story": live.day_story, "models": live.model_status}


# --- you --------------------------------------------------------------------


class Hold(BaseModel):
    dx: float = 0.0
    dy: float = 0.0


class Said(BaseModel):
    text: str


@app.post("/api/player/join")
def player_join():
    """Step in where awake crew are (the Mess hall when nobody is), beside
    one of them. You are "the new arrival" until the narrator gets to you,
    which happens in the background."""
    live = world()
    where = live.player.arrive(live)
    autosave_if_due(force=True)
    room = where["label"] or "the station"
    live.note(f"{live.player.name} came aboard and made for the {room}.", kind="day")
    return dict(live.snapshot()["player"], arrived=where)


@app.post("/api/player/leave")
def player_leave():
    live = world()
    live.player.leave()
    autosave_if_due(force=True)
    return live.snapshot()["player"]


@app.post("/api/player/hold")
def player_hold(body: Hold):
    """Which way you are holding. Sent when it changes, not every frame: the
    tick does the walking, so this is a few bytes on a key press."""
    live = world()
    live.player.hold(body.dx, body.dy)
    return {"ok": True}


@app.post("/api/player/sit")
def player_sit():
    live = world()
    if live.player.sitting:
        live.player.stand()
        return {"sitting": "", "stood": True}
    prop = live.player.sit()
    if not prop:
        return {"sitting": "", "nothing_here": True}
    return {"sitting": live.player.sitting, "on": prop["sprite"]}


class Ride(BaseModel):
    deck: str


@app.post("/api/player/ride")
def player_ride(body: Ride):
    """Take the lift to a chosen deck."""
    live = world()
    if not live.player.ride_to(body.deck):
        raise HTTPException(400, "you are not at the lift, or that is this deck")
    return {"riding": True, "to": body.deck}


@app.post("/api/player/sleep")
def player_sleep():
    """Sleep through to the morning. The narrator writes up what you missed."""
    live = world()
    if not live.player.can_sleep():
        raise HTTPException(400, "there is nothing to sleep on here")
    summary = live.sleep_until_morning()
    autosave_if_due(force=True)
    return {"summary": summary, "clock": live.clock_now(), "day": live.day}


@app.post("/api/player/say")
def player_say(body: Said):
    """Say something to whoever is close enough to hear it.

    Answered on this request rather than on the worker thread, because you are
    standing there waiting. A line takes about a second on the small model, and
    a written fallback arrives instantly when Jan is not running.
    """
    live = world()
    text = body.text.strip()[:200]
    if not text:
        raise HTTPException(400, "say something")
    if _director is None:
        raise HTTPException(503, "the station is still starting")
    answer = _director.answer_player(text)
    if answer is None:
        live.say(live.player.id, text, 5.0)
        return {"heard_by": None, "you": text}
    return {"heard_by": answer, "you": text}


class Carry(BaseModel):
    do: str
    slot: int = 0


@app.post("/api/player/carry")
def player_carry(body: Carry):
    """Pick up, put down, give, or choose which thing is in your hands. The
    rules are in janhollow/carry.py; this only routes to them."""
    live = world()
    if body.do == "pickup":
        result = carry.pick_up(live)
    elif body.do == "drop":
        result = carry.put_down(live)
    elif body.do == "give":
        result = carry.give(live)
    elif body.do == "select":
        result = carry.select(live, body.slot)
    else:
        raise HTTPException(400, "do must be pickup, drop, give or select")
    if result.get("ok") and body.do != "select":
        autosave_if_due(force=True)
    return result


# --- saves ------------------------------------------------------------------


@app.get("/api/saves")
def list_saves():
    return {"saves": saves.listing(), "folder": saves.saves_dir()}


@app.post("/api/saves/{slot}")
def write_save(slot: str):
    state = world().save_state()
    state["clock"] = sim.clock_text(state["minute"])
    return {"saved": True, "path": saves.write(slot, state)}


@app.get("/api/saves/{slot}")
def read_save(slot: str):
    state = saves.read(slot)
    if state is None:
        raise HTTPException(404, f"no save in slot {slot}")
    return state


@app.post("/api/saves/{slot}/load")
def load_save(slot: str):
    state = saves.read(slot)
    if state is None:
        raise HTTPException(404, f"no save in slot {slot}")
    return build_world(save_state=state).snapshot()


@app.delete("/api/saves/{slot}")
def drop_save(slot: str):
    return {"deleted": saves.delete(slot)}


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as handle:
        return handle.read()


# The shared kit must mount before the catch-all, which would swallow it.
if os.path.isdir(SHARED_DIR):
    app.mount("/shared", StaticFiles(directory=SHARED_DIR), name="shared")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
