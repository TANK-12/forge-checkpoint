"""Prompts: a library of prompts with versions and outcomes (see prompts_core)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import prompts_core as core

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR") or ROOT.parent.parent / "shared")
sys.path.insert(0, str(SHARED_DIR))
from forge_guard import LocalOnly  # noqa: E402

app = FastAPI(title="Prompts")
app.add_middleware(LocalOnly)  # only its own pages, never another site


@app.exception_handler(core.PromptsError)
async def said(_request: Request, exc: core.PromptsError):
    code = 404 if isinstance(exc, core.NotFound) else 400
    return JSONResponse(status_code=code, content={"detail": str(exc)})


@app.get("/api/state")
def state():
    return {"targets": list(core.TARGETS.values()), "data_dir": str(core.data_dir())}


@app.get("/api/prompts")
def prompts(q: str = "", target: str = "", archived: bool = False):
    return core.list_prompts(q, target, archived)


@app.post("/api/prompts")
def create(body: dict = Body(...)):
    return core.create(body)


@app.get("/api/prompts/{pid}")
def one(pid: int):
    return core.get_prompt(pid)


@app.patch("/api/prompts/{pid}")
def change(pid: int, body: dict = Body(...)):
    return core.change(pid, body)


@app.post("/api/prompts/{pid}/versions")
def version(pid: int, body: dict = Body(...)):
    prompt, made = core.add_version(pid, body)
    return {"prompt": prompt, "made": made}


@app.post("/api/prompts/{pid}/results")
def result(pid: int, body: dict = Body(...)):
    return core.add_result(pid, body)


@app.patch("/api/results/{rid}")
def change_result(rid: int, body: dict = Body(...)):
    return core.change_result(rid, body)


@app.get("/api/export")
def export():
    return JSONResponse(
        core.export_all(),
        headers={"Content-Disposition": 'attachment; filename="prompts.json"'},
    )


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/shared", StaticFiles(directory=SHARED_DIR), name="shared")
app.mount("/", StaticFiles(directory=STATIC), name="static")
