"""Convert: drop a file, pick a format (see convert_core and converters/)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import convert_core as core

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR") or ROOT.parent.parent / "shared")
sys.path.insert(0, str(SHARED_DIR))
from forge_guard import LocalOnly  # noqa: E402
from forge_jobs import Job, JobStore, job_router  # noqa: E402

app = FastAPI(title="Convert")
app.add_middleware(LocalOnly)  # only its own pages, never another site
STORE = JobStore()
app.include_router(job_router(STORE))
CONVERTERS = core.load_converters()
SPOOL = core.DATA_DIR / "in"
if SPOOL.is_dir():
    shutil.rmtree(SPOOL)  # Convert's own copies of dropped files, from last time
core.sweep_leftovers(core.load_config(core.CONFIG))  # half-written, from a killed run


def cfg() -> dict:
    return core.load_config(core.CONFIG)


@app.exception_handler(core.ConvertError)
async def said(_request: Request, exc: core.ConvertError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def pick(cid: str):
    mod = CONVERTERS.get(cid)
    if mod is None:
        raise HTTPException(404, f"no converter called {cid}")
    return mod


@app.get("/api/state")
def state():
    c = cfg()
    tools = {
        name: {
            "ready": core.tool_ready(c, core.DATA_DIR, name),
            "version": spec["version"],
            "bytes": spec.get("bytes", 0),
        }
        for name, spec in c.get("tools", {}).items()
    }
    return {
        "converters": core.describe(CONVERTERS),
        "out_dir": str(core.out_dir(c)),
        "tools": tools,
        "recent": core.recent(c),
    }


@app.get("/api/choices")
def choices(name: str):
    return {"name": name, "choices": core.choices_for(CONVERTERS, name)}


def start(mod, src: Path, name: str, to: str, options: dict, spool: Path | None):
    c = cfg()
    core.clean_options(mod.CONVERTER, to, options)  # refuse bad options now

    def work(job: Job):
        try:
            job.result = core.convert(mod, src, name, to, options, job, c)
        finally:
            if spool is not None:
                shutil.rmtree(spool, ignore_errors=True)

    job = STORE.start(Job(f"convert-{mod.CONVERTER['id']}", "convert"), work)
    return {"job": job.id}


@app.post("/api/convert/file")
async def convert_file(
    request: Request, name: str, converter: str, to: str, options: str = "{}"
):
    """The dropped file is the body. It is written to Convert's own folder
    on the disk (not /tmp, which is memory) and removed once converted."""
    mod = pick(converter)
    name = core.safe_name(name)
    try:
        opts = json.loads(options)
    except ValueError:
        raise HTTPException(400, "options are not JSON") from None
    if not isinstance(opts, dict):
        raise HTTPException(400, "options are not JSON")
    c = cfg()
    size = int(request.headers.get("content-length") or 0)
    core.room_check(c, core.DATA_DIR, size * 2)  # the copy and the result
    spool = SPOOL / uuid.uuid4().hex[:10]
    spool.mkdir(parents=True)
    src = spool / name
    try:
        with src.open("wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
        return start(mod, src, name, to, opts, spool)
    except BaseException:
        shutil.rmtree(spool, ignore_errors=True)
        raise


@app.post("/api/convert/path")
def convert_path(body: dict = Body(...)):
    """A file already on this computer, by its path: nothing is copied."""
    mod = pick(str(body.get("converter", "")))
    src = Path(str(body.get("path", ""))).expanduser()
    if not src.is_absolute() or not src.is_file():
        raise HTTPException(400, "there is no file at that path")
    opts = body.get("options") or {}
    if not isinstance(opts, dict):
        raise HTTPException(400, "options are not an object")
    return start(mod, src, src.name, str(body.get("to", "")), opts, None)


@app.get("/api/recent")
def recent():
    return core.recent(cfg())


@app.get("/api/out/{name}")
def out(name: str):
    try:
        path = core.out_file(cfg(), name)
    except core.ConvertError:
        raise HTTPException(404, "no such file") from None
    return FileResponse(path, filename=path.name)


app.mount("/shared", StaticFiles(directory=SHARED_DIR), name="shared")
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
