"""Taleforge: a data-driven text RPG engine with Jan as narrator and voice.

The engine (taleforge/) owns every rule and number; campaigns/ and rulesets/
are the content. This file is only the HTTP surface for static/."""

from __future__ import annotations

import random
import re
import secrets
import sys
import threading
from functools import lru_cache
from pathlib import Path

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from taleforge import rules as R
from taleforge import saves
from taleforge.core import GameError
from taleforge.game import Game, start_game
from taleforge.narrator import DEFAULT_MODELS, ROLES, SHARED, Narrator, forge_jan
from taleforge.view import view
from taleforge.world import CAMPAIGNS, ContentError, World, list_campaigns, validate

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
sys.path.insert(0, str(SHARED))
from forge_guard import LocalOnly  # noqa: E402

app = FastAPI(title="Taleforge")
app.add_middleware(LocalOnly)
JAN = forge_jan.mount(app, "taleforge", roles=ROLES)
NARRATOR = Narrator(saves.patch_entry, owner=JAN)
ROLLS: dict[str, list[int]] = {}
GAME_LOCK = threading.Lock()
CAMPAIGN_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


@lru_cache(maxsize=8)
def world(cid: str) -> World:
    # A campaign id is a bare folder name; this also refuses Windows "\\",
    # ":" and ".." forms that a "/" check alone lets through.
    if not CAMPAIGN_ID.fullmatch(cid):
        raise ContentError("no such campaign")
    folder = CAMPAIGNS / cid
    if not (folder / "campaign.json").exists():
        raise ContentError("no such campaign")
    return World(folder)


def settings() -> dict:
    return {"narrate": bool(saves.read_settings().get("narrate", True))}


if not forge_jan.settings_path("taleforge").exists():
    # LFM2.5 1.2B for both roles (Relay task 310, 2026-10-24; the 4B was too
    # slow). Changeable in the app's Jan panel.
    JAN.update({"models": dict(DEFAULT_MODELS)})


def load(sid: str) -> Game:
    state = saves.read(sid)
    return Game(world(state["campaign"]), state)


def queue_jan(sid: str, game: Game, entries: list[dict]) -> None:
    if settings()["narrate"]:
        NARRATOR.submit(sid, game, entries)
    else:
        for e in entries:
            if e.get("jan"):
                e["pending"] = False


@app.exception_handler(GameError)
@app.exception_handler(R.RuleError)
@app.exception_handler(saves.SaveError)
@app.exception_handler(ContentError)
async def said(_request: Request, exc: Exception):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/api/campaigns")
def campaigns():
    out = []
    for c in list_campaigns():
        try:
            w = world(c["id"])
        except ContentError:
            continue
        counts = w.counts()
        out.append({**c, "intro": w.campaign.get("intro", ""), "counts": counts})
    return {"campaigns": out}


@app.get("/api/campaigns/{cid}/creation")
def creation(cid: str):
    w = world(cid)
    r = w.rules
    return {
        "campaign": {
            "id": w.id,
            "name": w.campaign.get("name"),
            "tagline": w.campaign.get("tagline", ""),
        },
        "ruleset": r.get("name", r["id"]),
        "labels": r.get("labels", {}),
        "abilities": r["abilities"],
        "ability_scores": r["ability_scores"],
        "skills": [
            {"id": s["id"], "name": s["name"], "ability": s["ability"]}
            for s in r["skills"]
        ],
        "classes": [
            {
                "id": c["id"],
                "name": c["name"],
                "about": c.get("about", ""),
                "hit_die": c["hit_die"],
                "primary": c["primary"],
                "skill_options": c["skill_options"],
                "skill_count": c["skill_count"],
                "abilities": [
                    {
                        "name": a["name"],
                        "level": a.get("level", 1),
                        "text": a.get("text", ""),
                    }
                    for a in c.get("abilities", [])
                ],
                "start_items": [w.item(i)["name"] for i in c.get("start_items", [])],
            }
            for c in r["classes"]
        ],
        "backgrounds": r["backgrounds"],
    }


@app.post("/api/campaigns/{cid}/roll")
def roll_scores(cid: str):
    w = world(cid)
    scores = R.roll_scores(w.rules, random.Random())
    token = secrets.token_hex(8)
    ROLLS[token] = scores
    if len(ROLLS) > 50:
        ROLLS.pop(next(iter(ROLLS)))
    return {"token": token, "scores": scores}


@app.get("/api/saves")
def list_saves():
    return {"saves": saves.listing()}


@app.post("/api/saves")
def new_game(body: dict = Body(...)):
    w = world(str(body.get("campaign", "")))
    spec = body.get("character") or {}
    if not isinstance(spec, dict):
        raise GameError("character must be an object")
    rolled = (
        ROLLS.get(str(spec.get("roll_token", "")))
        if spec.get("method") == "roll"
        else None
    )
    with GAME_LOCK:
        game = start_game(w, spec, rolled)
        sid = saves.new_id()
        entries = list(game.out)
        queue_jan(sid, game, entries)
        saves.write(sid, game.s)
        NARRATOR.start()
    return view(game, sid)


@app.get("/api/saves/{sid}")
def get_save(sid: str):
    return view(load(sid), sid)


@app.post("/api/saves/{sid}/act")
def act(sid: str, body: dict = Body(...)):
    with GAME_LOCK:
        with saves.LOCK:
            game = load(sid)
            out = game.act(body.get("action") or body)
            queue_jan(sid, game, out)
            saves.write(sid, game.s)
    return view(game, sid)


@app.get("/api/saves/{sid}/entries")
def entries(sid: str, ids: str = ""):
    """The current form of some log entries (the UI polls pending ones)."""
    want = set(ids.split(",")) if ids else set()
    log = saves.read(sid).get("log", [])
    return {"entries": [e for e in log if e.get("id") in want]}


@app.delete("/api/saves/{sid}")
def trash_save(sid: str):
    dest = saves.trash(sid)
    return {"trashed": dest.name}


@app.get("/api/settings")
def get_settings():
    chosen = JAN.settings()["models"]
    notes = []
    for role in ROLES:
        try:
            used = NARRATOR.model(role)
        except forge_jan.JanError:
            continue
        if chosen.get(role) and used != chosen[role]:
            notes.append(
                f"{role} uses {used}: the chosen {chosen[role]} is not in Jan yet"
                " (not installed, or added since Jan started: restart Jan)"
            )
    return {
        **settings(),
        "jan_error": NARRATOR.last_error,
        "roles": list(ROLES),
        "jan_notes": notes,
    }


@app.post("/api/settings")
def set_settings(body: dict = Body(...)):
    if "narrate" in body:
        saves.write_settings({"narrate": bool(body["narrate"])})
    return get_settings()


@app.get("/api/check/{cid}")
def check_campaign(cid: str):
    return {"problems": validate(world(cid))}


app.mount("/shared", StaticFiles(directory=SHARED), name="shared")
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
