"""Files - a file manager inside Forge.

A thin FastAPI layer over `fsops.py`, which holds every rule (path guard,
trash-only removal, copy/move jobs, thumbnails). The page is `static/`.

Every /api route needs either the header `X-Forge: 1` or `?t=<token>`. A web
page open in the Forge Browser can reach 127.0.0.1, but it cannot send that
header cross-origin without a CORS preflight this app never grants, and it
cannot read the token. The token form exists only for `<img>`/`<video>` src
URLs, which cannot carry headers.

Run standalone with:
    .venv/bin/python -m uvicorn web_app:app --host 127.0.0.1 --port 8458
"""

from __future__ import annotations

import os
import secrets
import sys
import time
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import fsops
import advanced

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR", ROOT.parent.parent / "shared"))
TOKEN = secrets.token_urlsafe(24)


def forge_only(
    x_forge: str | None = Header(default=None), t: str | None = Query(default=None)
) -> None:
    if x_forge != "1" and not (t and secrets.compare_digest(t, TOKEN)):
        raise HTTPException(403, "Send X-Forge: 1")


app = FastAPI(title="Forge Files")


@app.exception_handler(advanced.storage.StorageError)
@app.exception_handler(fsops.FsError)
async def fs_error(_req: Request, exc: fsops.FsError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(OSError)
async def os_error(_req: Request, exc: OSError) -> JSONResponse:
    """The system said no (no permission, a full or read-only drive): a plain
    sentence for the page instead of a bare server error."""
    if isinstance(exc, PermissionError):
        msg = "No permission for that here"
    else:
        msg = exc.strerror or str(exc) or "The system refused that"
    name = Path(str(exc.filename)).name if exc.filename else ""
    return JSONResponse({"detail": f"{msg} ({name})" if name else msg}, status_code=400)


guard = [Depends(forge_only)]


def openers() -> dict:
    """{".docx": [{role, label, icon}]}: the other Forge apps that open a
    file type, from their manifests' "opens" (shared/forge_open.py), for the
    "Open in <app>" menu items. Empty when shared/ is not there."""
    if str(SHARED_DIR) not in sys.path:
        sys.path.append(str(SHARED_DIR))
    try:
        import forge_open  # pyright: ignore[reportMissingImports]
    except ImportError:
        return {}
    return forge_open.openers()


@app.get("/api/session", dependencies=guard)
def session() -> dict:
    return {
        "token": TOKEN,
        "home": str(fsops.HOME),
        "openers": openers(),
        **fsops.places(),
    }


@app.get("/api/list", dependencies=guard)
def list_dir(path: str, hidden: bool = False) -> dict:
    out = fsops.list_dir(path, hidden)
    try:
        out.update(fsops.folder_info(out["path"]))
    except OSError:
        pass
    return out


@app.get("/api/stamp", dependencies=guard)
def stamp(path: str) -> dict:
    """Cheap change check for the open folder; the page relists only on a
    change. `clip` is the shared clipboard's number (/api/clip)."""
    return {"stamp": fsops.folder_stamp(path), "clip": CLIP["seq"]}


# The clipboard every Files window shares (2026-10-24): Copy or Cut in one
# window, Paste in another. Each window is its own page, and WebKit keeps a
# page in the hub's frame and one in its own window apart in localStorage,
# so it lives here. In memory only: a restart or a sleep empties it. `seq`
# starts from the clock, so a restarted backend's numbers are higher still.
CLIP: dict = {"op": None, "paths": [], "seq": time.time_ns() // 1_000_000}


@app.get("/api/clip", dependencies=guard)
def get_clip() -> dict:
    return CLIP


@app.post("/api/clip", dependencies=guard)
def set_clip(op: str | None = Body(None), paths: list[str] = Body([])) -> dict:
    """{op: "copy"|"move", paths} sets it; anything else empties it."""
    paths = [p for p in paths if p]
    if op in ("copy", "move") and paths:
        CLIP.update(op=op, paths=paths)
    else:
        CLIP.update(op=None, paths=[])
    CLIP["seq"] += 1
    return CLIP


@app.get("/api/search", dependencies=guard)
def search(path: str, q: str, hidden: bool = False) -> dict:
    return fsops.search(path, q, hidden)


@app.get("/api/text", dependencies=guard)
def text(path: str) -> dict:
    return fsops.read_text(path)


@app.get("/api/raw", dependencies=guard)
def raw(path: str) -> FileResponse:
    p = fsops.resolve(path)
    if not p.is_file():
        raise HTTPException(404, "Not a file")
    # Starlette answers Range requests, so audio and video seek.
    return FileResponse(p)


@app.get("/api/thumb", dependencies=guard)
def thumb(path: str) -> FileResponse:
    p = fsops.thumbnail(path)
    if p is None:
        raise HTTPException(404, "No thumbnail")
    return FileResponse(p, headers={"Cache-Control": "private, max-age=3600"})


@app.post("/api/mkdir", dependencies=guard)
def mkdir(parent: str = Body(...), name: str = Body(...)) -> dict:
    return {"path": fsops.make_folder(parent, name)}


@app.post("/api/rename", dependencies=guard)
def rename(path: str = Body(...), name: str = Body(...)) -> dict:
    return {"path": fsops.rename(path, name)}


@app.post("/api/trash", dependencies=guard)
def trash(paths: list[str] = Body(..., embed=True)) -> dict:
    return fsops.trash(paths)


@app.post("/api/restore", dependencies=guard)
def restore(paths: list[str] = Body(..., embed=True)) -> dict:
    return fsops.restore(paths)


@app.post("/api/archive", dependencies=guard)
def archive(op: str = Body(...), paths: list[str] = Body(...)) -> dict:
    return fsops.start_archive(op, paths).public()


@app.post("/api/upload", dependencies=guard)
async def upload(request: Request, dest: str, name: str) -> dict:
    """A file dropped in from outside Forge; the request body is the file."""
    size = request.headers.get("content-length", "")
    up = fsops.Upload(dest, name, int(size) if size.isdigit() else None)
    try:
        async for chunk in request.stream():
            up.write(chunk)
        return {"path": up.finish()}
    except BaseException:
        up.abort()
        raise


@app.post("/api/open", dependencies=guard)
def open_default(path: str = Body(..., embed=True)) -> dict:
    fsops.open_default(path)
    return {"ok": True}


@app.post("/api/transfer", dependencies=guard)
def transfer(
    op: str = Body(...), paths: list[str] = Body(...), dest: str = Body(...)
) -> dict:
    return fsops.start_transfer(op, paths, dest).public()


@app.get("/api/jobs/{job_id}", dependencies=guard)
def job(job_id: str) -> dict:
    j = fsops.JOBS.get(job_id)
    if j is None:
        raise HTTPException(404, "No such job")
    return j.public()


@app.get("/api/advanced/inspect", dependencies=guard)
def inspect_item(path: str) -> dict:
    return advanced.inspect(path)


@app.get("/api/advanced/hash", dependencies=guard)
def hash_item(path: str) -> dict:
    return advanced.checksum(path)


@app.get("/api/advanced/usage", dependencies=guard)
def disk_usage(path: str) -> dict:
    return advanced.usage(path)


@app.post("/api/advanced/rename/preview", dependencies=guard)
def preview_rename(
    paths: list[str] = Body(...),
    find: str = Body(""),
    replace: str = Body(""),
    prefix: str = Body(""),
) -> dict:
    return {"plan": advanced.rename_plan(paths, find, replace, prefix)}


@app.post("/api/advanced/rename/apply", dependencies=guard)
def apply_rename(plan: list[dict] = Body(..., embed=True)) -> dict:
    return advanced.rename_batch(plan)


if SHARED_DIR.is_dir():
    app.mount("/shared", StaticFiles(directory=str(SHARED_DIR)), name="shared")
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
