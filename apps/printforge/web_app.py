"""PrintForge -- look over 3D-print files (STL) before slicing them.

Lists every STL under the configured folders (by default ~/Models and
~/Downloads), shows it in a three.js view on a print bed, and checks what a
slicer would care about: watertight or not, separate shells, size, volume,
overhangs that need support and which print beds it fits, plus the print
pipeline's build report when one names the file. Nothing here writes to the STL files.
"""

from __future__ import annotations

import os
import subprocess
import sys

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import library
import stl

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT, "static")
SHARED_DIR = os.environ.get("FORGE_SHARED_DIR") or os.path.join(
    ROOT, "..", "..", "shared"
)
sys.path.insert(0, os.path.abspath(SHARED_DIR))

import forge_revalidate  # noqa: E402  (lives in SHARED_DIR)

app = FastAPI(title="PrintForge")
forge_revalidate.revalidate(app)


@app.exception_handler(RequestValidationError)
def _bad_request(_request: Request, exc: RequestValidationError):
    """A 422 naming each field and what is wrong with it. FastAPI's own reply
    echoes the rejected value back, which cannot be sent at all for a body
    of 1e999 (Infinity) or NaN, so that became a 500 instead."""
    detail = [
        {
            "loc": list(e.get("loc", ())),
            "msg": str(e.get("msg", "")),
            "type": e.get("type"),
        }
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


class SettingsIn(BaseModel):
    values: dict


class PathIn(BaseModel):
    path: str


def _checked(path: str):
    try:
        return library.allowed(path)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except OSError:
        raise HTTPException(404, "not an STL file")


@app.get("/api/settings")
def get_settings():
    return library.load_settings()


@app.post("/api/settings")
def post_settings(body: SettingsIn):
    try:
        return library.save_settings(body.values)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/library")
def get_library():
    s = library.load_settings()
    return {
        "roots": s["roots"],
        "roots_shown": library.root_labels(s),
        "files": library.scan(s),
    }


@app.get("/api/info")
def get_info(path: str = Query(...)):
    p = _checked(path)
    s = library.load_settings()
    try:
        result = dict(library.info(p))
    except (ValueError, OSError) as e:
        raise HTTPException(422, f"could not read this STL: {e}")
    result["scale"] = library.scale_of(p)
    result["bytes"] = p.stat().st_size
    if "size_mm" in result:
        result["fits"] = {
            name: stl.fits(result["size_mm"], bed) for name, bed in s["beds"].items()
        }
    # read fresh each time (not cached): the pipeline rewrites its reports
    result["report"] = library.report_for(p, s)
    return result


@app.get("/api/stat")
def get_stat(path: str = Query(...)):
    """Size and time of one print, so the page can tell a new export from the
    file it already shows without downloading it again."""
    p = _checked(path)
    try:
        return {"path": str(p), **library.stamp(p)}
    except OSError:
        raise HTTPException(404, "not an STL file")


@app.get("/api/stl")
def get_stl(path: str = Query(...)):
    p = _checked(path)
    return FileResponse(p, media_type="model/stl", filename=p.name)


@app.post("/api/open-folder")
def open_folder(body: PathIn):
    p = _checked(body.path)
    try:
        subprocess.Popen(
            ["xdg-open", str(p.parent)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        raise HTTPException(503, f"could not open the file manager ({e})")
    return {"ok": True, "folder": str(p.parent)}


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as handle:
        return handle.read()


if os.path.isdir(SHARED_DIR):
    app.mount("/shared", StaticFiles(directory=SHARED_DIR), name="shared")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
