"""Shelf: read-later articles kept offline as clean text and pictures (see shelf_core)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import shelf_core as core

ROOT = Path(__file__).resolve().parent
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR") or ROOT.parent.parent / "shared")
sys.path.insert(0, str(SHARED_DIR))
from forge_guard import LocalOnly  # noqa: E402

CFG_PATH = Path(os.environ.get("SHELF_CONFIG") or ROOT / "shelf.json")
app = FastAPI(title="Shelf")
app.add_middleware(LocalOnly)  # only its own pages, never another site

# swapped by the tests, so nothing there touches the network or the bin
fetcher: core.Fetcher = core.fetch
from forge_trash import trash  # noqa: E402  (gio, the macOS or Windows bin)

post = None


class SaveReq(BaseModel):
    url: str


class MarkReq(BaseModel):
    read: bool | None = None
    archived: bool | None = None


class SendReq(BaseModel):
    target: str
    name: str


def shelf() -> core.Shelf:
    return core.Shelf(core.load_config(CFG_PATH))


def found(fn, *a):
    try:
        return fn(*a)
    except KeyError as e:
        raise HTTPException(404, "that article is not on the shelf") from e


@app.get("/api/config")
def get_config():
    cfg = core.load_config(CFG_PATH)
    targets = [
        {k: t.get(k, "") for k in ("id", "label", "ask", "prefill")}
        for t in cfg["send_to"]
    ]
    return {"send_to": targets, "data": str(core.expand(cfg["data"]))}


@app.get("/api/articles")
def get_articles(view: str = "unread", q: str = ""):
    s = shelf()
    return {"articles": s.listing(view, q), "counts": s.counts()}


@app.get("/api/articles/{aid}")
def get_article(aid: str):
    return found(shelf().get, aid)


@app.post("/api/save")
def save(req: SaveReq):
    try:
        art, new = shelf().save(req.url, fetcher)
    except core.FetchError as e:
        raise HTTPException(400, str(e)) from e
    return {"article": art, "new": new}


@app.post("/api/articles/{aid}")
def mark(aid: str, req: MarkReq):
    flags = {k: v for k, v in req.model_dump().items() if v is not None}
    return found(lambda: shelf().mark(aid, **flags))


@app.delete("/api/articles/{aid}")
def remove(aid: str):
    try:
        found(shelf().remove, aid, trash)
    except (RuntimeError, OSError) as e:
        raise HTTPException(500, f"could not move it to the bin: {e}") from e
    return {"ok": True}


@app.get("/api/image/{aid}/{name}")
def image(aid: str, name: str):
    p = found(shelf().image, aid, name)
    return FileResponse(p, headers={"X-Content-Type-Options": "nosniff"})


@app.post("/api/send")
def send(req: SendReq):
    cfg = core.load_config(CFG_PATH)
    target = next((t for t in cfg["send_to"] if t["id"] == req.target), None)
    if target is None:
        raise HTTPException(404, "no such app to send to")
    try:
        core.send(target, req.name, post)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e
    return {"ok": True, "done": target.get("done", "sent")}


if SHARED_DIR.is_dir():
    app.mount("/shared", StaticFiles(directory=SHARED_DIR), name="shared")
app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
