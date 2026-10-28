"""Vault: one browser for assets on disk and from Poly Haven (see vault_core)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import vault_core as core

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR") or ROOT.parent.parent / "shared")
sys.path.insert(0, str(SHARED_DIR))
from forge_guard import LocalOnly  # noqa: E402

app = FastAPI(title="Vault")
app.add_middleware(LocalOnly)  # only its own pages, never another site


@app.exception_handler(core.VaultError)
async def said(_request: Request, exc: core.VaultError):
    code = 404 if isinstance(exc, core.NotFound) else 400
    return JSONResponse(status_code=code, content={"detail": str(exc)})


@app.get("/api/state")
def state():
    return {
        "kinds": list(core.KINDS.values()),
        "targets": list(core.TARGETS.values()),
        "sources": core.sources(),
        "godot_projects": core.godot_projects(),
    }


@app.get("/api/items")
def items(q: str = "", kind: str = "", source: str = ""):
    return core.list_items(q, kind, source)


@app.post("/api/refresh")
def refresh():
    core.INDEX.clear()
    return {"total": len(core.INDEX.all())}


@app.get("/api/items/{item_id}")
def item(item_id: str):
    return core.get_item(item_id)


@app.get("/api/items/{item_id}/thumb")
def thumb(item_id: str):
    return FileResponse(core.thumb(item_id), headers={"Cache-Control": "max-age=3600"})


@app.get("/api/items/{item_id}/f/{rel:path}")
def item_file(item_id: str, rel: str):
    return FileResponse(core.item_file(item_id, rel))


@app.post("/api/items/{item_id}/send/{target}")
async def send(item_id: str, target: str, body: dict = Body(default={})):
    return await run_in_threadpool(core.send, item_id, target, body)


@app.post("/api/folders")
def add_folder(body: dict = Body(...)):
    return core.add_folder(str(body.get("path") or ""))


@app.delete("/api/folders/{source_id}")
def forget_folder(source_id: str):
    return core.forget_folder(source_id)


@app.get("/api/polyhaven")
def ph_search(kind: str = "models", q: str = ""):
    return core.ph_search(kind, q)


@app.get("/api/polyhaven/thumb/{asset_id}")
def ph_thumb(asset_id: str):
    return FileResponse(
        core.ph_thumb(asset_id), headers={"Cache-Control": "max-age=86400"}
    )


@app.post("/api/polyhaven/get")
def ph_get(body: dict = Body(...)):
    return core.ph_get(str(body.get("id") or ""), str(body.get("res") or "1k"))


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/shared", StaticFiles(directory=SHARED_DIR), name="shared")
app.mount("/", StaticFiles(directory=STATIC), name="static")
