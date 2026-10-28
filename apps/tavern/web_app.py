"""Tavern: tabletop campaigns with Jan as the game master (see tavern_core)."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

import tavern_core as core

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
SHARED_DIR = core.SHARED_DIR
sys.path.insert(0, str(SHARED_DIR))
from forge_guard import LocalOnly  # noqa: E402

CFG = core.load_config()
app = FastAPI(title="Tavern")
app.add_middleware(LocalOnly)  # only its own pages, never another site
JAN = core.Jan(core.forge_jan.mount(app, "tavern", roles=core.ROLES))


@app.exception_handler(core.TavernError)
async def said(_request: Request, exc: core.TavernError):
    code = (
        409
        if isinstance(exc, core.Busy)
        else 503 if isinstance(exc, core.JanDown) else 400
    )
    return JSONResponse(status_code=code, content={"detail": str(exc)})


@app.get("/api/state")
def state():
    return {
        "worlds": core.load_worlds(),
        "terrain": CFG["terrain"],
        "map": CFG["map"],
        "party_max": CFG["party_max"],
        "campaigns": core.list_campaigns(),
    }


@app.post("/api/campaigns")
def new_campaign(body: dict = Body(...)):
    c = core.new_campaign(
        CFG,
        str(body.get("name", "")),
        str(body.get("world", "")),
        body.get("party") or [],
    )
    return core.view(c)


@app.get("/api/campaigns/{cid}")
def get_campaign(cid: str):
    return core.view(core.load(cid))


@app.delete("/api/campaigns/{cid}")
def trash_campaign(cid: str):
    core.trash(cid)
    return {"trashed": cid}


@app.post("/api/campaigns/{cid}/turn")
def turn(cid: str, body: dict = Body(default={})):
    return core.gm_turn(
        CFG, JAN, cid, str(body.get("who") or ""), str(body.get("text") or "")
    )


@app.post("/api/campaigns/{cid}/retry")
def retry(cid: str):
    return core.retry(CFG, JAN, cid)


@app.post("/api/campaigns/{cid}/recap")
def recap(cid: str):
    return core.recap_now(CFG, JAN, cid)


@app.post("/api/campaigns/{cid}/say")
def say(cid: str, body: dict = Body(...)):
    return core.say(
        CFG,
        cid,
        str(body.get("who") or ""),
        str(body.get("text") or ""),
        str(body.get("kind") or "say"),
    )


@app.post("/api/campaigns/{cid}/roll")
def roll(cid: str, body: dict = Body(...)):
    return core.do_roll(
        CFG,
        cid,
        str(body.get("expr") or ""),
        str(body.get("who") or ""),
        str(body.get("why") or ""),
        str(body.get("ask") or ""),
    )


@app.post("/api/campaigns/{cid}/party")
def save_member(cid: str, body: dict = Body(...)):
    return core.save_member(CFG, cid, body)


@app.delete("/api/campaigns/{cid}/party/{pid}")
def remove_member(cid: str, pid: str):
    return core.remove_member(cid, pid)


@app.post("/api/campaigns/{cid}/party/{pid}/hp")
def hp(cid: str, pid: str, body: dict = Body(...)):
    return core.adjust_hp(cid, pid, body.get("delta"))


@app.post("/api/campaigns/{cid}/maps")
def new_map(cid: str, body: dict = Body(...)):
    return core.new_map(
        CFG, cid, str(body.get("name") or ""), body.get("w"), body.get("h")
    )


@app.put("/api/campaigns/{cid}/maps/{mid}")
def save_map(cid: str, mid: str, body: dict = Body(...)):
    return core.save_map(CFG, cid, mid, body)


@app.get("/api/campaigns/{cid}/export")
def export(cid: str):
    return PlainTextResponse(
        core.markdown(cid),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="tavern-{cid}.md"'},
    )


app.mount("/shared", StaticFiles(directory=SHARED_DIR), name="shared")
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
