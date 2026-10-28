"""Reps: a workout and habit log with streaks and charts (see reps_core)."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import reps_core as core

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
SHARED_DIR = ROOT.parent.parent / "shared"
sys.path.insert(0, str(SHARED_DIR))
from forge_guard import LocalOnly  # noqa: E402

app = FastAPI(title="Reps")
app.add_middleware(LocalOnly)  # only its own pages, never another site


def today() -> dt.date:
    return dt.date.today()


@app.exception_handler(core.RepsError)
async def said(_request: Request, exc: core.RepsError):
    code = 404 if isinstance(exc, core.NotFound) else 400
    return JSONResponse(status_code=code, content={"detail": str(exc)})


@app.get("/api/state")
def state(day: str = ""):
    return core.state(today(), day)


@app.post("/api/trackers")
def add_tracker(body: dict = Body(...)):
    return core.add_tracker(body)


@app.patch("/api/trackers/{tid}")
def edit_tracker(tid: str, body: dict = Body(...)):
    return core.edit_tracker(tid, body)


@app.get("/api/trackers/{tid}/history")
def history(tid: str):
    return core.history(tid, today())


@app.post("/api/entries")
def log_entry(body: dict = Body(...)):
    return core.log_entry(body, today())


@app.post("/api/entries/restore")
def restore_entry(body: dict = Body(...)):
    return core.restore_entry(body, today())


@app.delete("/api/entries/{eid}")
def remove_entry(eid: str):
    return core.remove_entry(eid)


app.mount("/shared", StaticFiles(directory=SHARED_DIR), name="shared")
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
