"""Loops: a beat and loop maker (see loops_core)."""

from __future__ import annotations

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import loops_core as core
from loops_core import ROOT

from forge_guard import (
    LocalOnly,
)  # noqa: E402  (shared/, put on the path by loops_core)

STATIC = ROOT / "static"
INSTRUMENTS = core.load_instruments()
IDS = {i["id"] for i in INSTRUMENTS}

app = FastAPI(title="Loops")
app.add_middleware(LocalOnly)  # only its own pages, never another site


@app.exception_handler(core.LoopsError)
async def said(_request: Request, exc: core.LoopsError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/api/state")
def state():
    return {
        "instruments": INSTRUMENTS,
        "patterns": core.list_patterns(),
        "out_dir": str(core.out_dir()),
        "step_counts": list(core.STEP_COUNTS),
    }


@app.get("/api/patterns/{name}")
def get_pattern(name: str):
    return core.read_pattern(name, IDS)


@app.put("/api/patterns/{name}")
def put_pattern(name: str, pattern: dict = Body(...)):
    return core.save_pattern(name, pattern, IDS)


@app.delete("/api/patterns/{name}")
def delete_pattern(name: str):
    core.trash_pattern(name)
    return {"trashed": name}


@app.post("/api/export")
async def export(request: Request, name: str):
    size = request.headers.get("content-length") or "0"
    if not size.isdigit() or int(size) > core.MAX_WAV:
        raise HTTPException(413, "the WAV is over 200 MB; export fewer repeats")
    core.check_name(name)  # before reading the body
    path = core.export_wav(name, await core.read_capped(request.stream()))
    return {"saved": path.name, "path": str(path)}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/shared", StaticFiles(directory=core.SHARED_DIR), name="shared")
app.mount("/", StaticFiles(directory=STATIC), name="static")
