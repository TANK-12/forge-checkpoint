"""Afterglow - Claude's after-hours workshop in Forge.

A shelf of small living toys ("curios") that Claude made for the fun of it,
keepsakes saved from them, and a logbook of Claude's notes. The toys run in
the browser; this backend only finds them and keeps what is worth keeping.

    /api/curios                 every curios/<id>/curio.json, found by scanning
    /curios/<id>/<file>         a curio's browser files (an extension whitelist)
    /api/curio/<id>/...         a curio's own routes, from its optional server.py
    /api/keepsakes              list (?curio=), save, edit, put away, thumbnails
    /api/logbook                Claude's notes: shipped pages plus new ones

Every non-GET request under /api/ must carry `X-Forge: 1`, so a web page open
in Forge's Browser (which can reach 127.0.0.1) cannot write here: a
cross-origin page cannot send that header without a CORS preflight, and this
app answers none. The contract for adding a curio is in README.md.

Run standalone with:
    FORGE_SHARED_DIR=~/Forge/shared \\
    .venv/bin/python -m uvicorn web_app:app --host 127.0.0.1 --port 8469
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import registry
import store

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR", ROOT.parent.parent / "shared"))
MAX_BODY = 2_500_000
CURIO_FILES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".css": "text/css",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".txt": "text/plain",
}
NO_STORE = {"Cache-Control": "no-store"}
# A page from elsewhere that re-points its own name at 127.0.0.1 (DNS
# rebinding) becomes same-origin and could send X-Forge; its Host header
# still carries its own name, so the API answers only to these.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

app = FastAPI(title="Afterglow")


def _local(host: str) -> bool:
    try:
        return urlsplit("//" + host).hostname in LOCAL_HOSTS
    except ValueError:
        return False


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and not _local(request.headers.get("host", "")):
        return JSONResponse(
            {"detail": "Afterglow answers only to 127.0.0.1 or localhost"},
            status_code=403,
        )
    if path.startswith("/api/") and request.method not in ("GET", "HEAD"):
        if request.headers.get("x-forge") != "1":
            return JSONResponse(
                {"detail": "writes need the X-Forge: 1 header"}, status_code=403
            )
        if "chunked" in request.headers.get("transfer-encoding", "").lower():
            # no length up front means no size check: refuse rather than buffer
            return JSONResponse(
                {"detail": "send a Content-Length with the body"}, status_code=411
            )
        size = request.headers.get("content-length")
        if size and size.isdigit() and int(size) > MAX_BODY:
            return JSONResponse({"detail": "that is too big to keep"}, status_code=413)
    response = await call_next(request)
    if not path.startswith("/api/"):
        # Forge's WebKit has run a stale app.js before; always revalidate.
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


@app.exception_handler(store.StoreError)
async def store_error(request: Request, exc: store.StoreError):  # noqa: ARG001
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


# --- the shelf -----------------------------------------------------------------

CURIOS, PROBLEMS = registry.discover()
SERVERS, SERVER_PROBLEMS = registry.load_servers(CURIOS)
PROBLEMS += SERVER_PROBLEMS
PROBLEMS += registry.mount_routers(app, SERVERS)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "curios": len(CURIOS)}


@app.get("/api/curios")
def curios() -> JSONResponse:
    counts: dict[str, int] = {}
    for row in store.list_keepsakes():
        counts[row["curio"]] = counts.get(row["curio"], 0) + 1
    rows = [{**meta, "keepsakes": counts.get(meta["id"], 0)} for meta in CURIOS]
    return JSONResponse({"curios": rows, "problems": PROBLEMS}, headers=NO_STORE)


def _curio_file(cid: str, rel: str) -> Path:
    if cid != "_kit" and cid not in {m["id"] for m in CURIOS}:
        raise HTTPException(404, "no such curio")
    parts = rel.split("/")
    if "\x00" in rel or any(
        not p or p.startswith(".") or p == "__pycache__" for p in parts
    ):
        raise HTTPException(404, "not served")
    folder = (store.CURIOS_DIR / cid).resolve()
    target = (folder / rel).resolve()
    if not target.is_relative_to(folder) or not target.is_file():
        raise HTTPException(404, "not found")
    if target.suffix not in CURIO_FILES or "tests" in parts[:-1]:
        raise HTTPException(404, "not served")
    return target


@app.get("/curios/{cid}/{rel:path}")
def curio_file(cid: str, rel: str) -> FileResponse:
    target = _curio_file(cid, rel)
    return FileResponse(
        target,
        media_type=CURIO_FILES[target.suffix],
        headers={"Cache-Control": "no-cache"},
    )


# --- keepsakes -----------------------------------------------------------------


class KeepIn(BaseModel):
    curio: str
    name: str
    note: str = ""
    data: Any = None
    thumb: str | None = None
    author: str | None = None


class EditIn(BaseModel):
    name: str | None = None
    note: str | None = None


def _known(curio: str) -> str:
    if curio not in {m["id"] for m in CURIOS}:
        raise store.NotFound(f"no curio called {curio!r}")
    return curio


@app.get("/api/keepsakes")
def keepsakes(curio: str | None = None) -> JSONResponse:
    rows = store.list_keepsakes(curio)
    return JSONResponse({"keepsakes": rows}, headers=NO_STORE)


@app.post("/api/keepsakes", status_code=201)
def keep(body: KeepIn) -> dict:
    return store.save_keepsake(
        _known(body.curio),
        name=body.name,
        note=body.note,
        data=body.data,
        thumb=body.thumb,
        author=body.author or store.user_name(),
    )


@app.get("/api/keepsakes/{curio}/{slug}")
def keepsake(curio: str, slug: str) -> JSONResponse:
    return JSONResponse(store.load_keepsake(curio, slug), headers=NO_STORE)


@app.get("/api/keepsakes/{curio}/{slug}/thumb")
def keepsake_thumb(curio: str, slug: str) -> Response:
    mime, data = store.thumb_bytes(curio, slug)
    return Response(data, media_type=mime, headers={"Cache-Control": "no-cache"})


@app.post("/api/keepsakes/{curio}/{slug}")
def edit(curio: str, slug: str, body: EditIn) -> dict:
    return store.edit_keepsake(curio, slug, name=body.name, note=body.note)


@app.post("/api/keepsakes/{curio}/{slug}/put-away")
def put_away(curio: str, slug: str) -> dict:
    store.put_away(curio, slug)
    return {"ok": True}


# --- logbook -------------------------------------------------------------------


class PageIn(BaseModel):
    title: str
    body: str
    author: str | None = None
    curio: str | None = None


@app.get("/api/logbook")
def logbook() -> JSONResponse:
    return JSONResponse({"pages": store.list_pages()}, headers=NO_STORE)


@app.post("/api/logbook", status_code=201)
def write_page(body: PageIn) -> dict:
    return store.add_page(
        body.title,
        body.body,
        author=body.author or store.user_name(),
        curio=_known(body.curio) if body.curio else None,
    )


# --- pages ---------------------------------------------------------------------

if SHARED_DIR.is_dir():
    app.mount("/shared", StaticFiles(directory=str(SHARED_DIR)), name="shared")


@app.get("/")
def index():
    target = STATIC_DIR / "index.html"
    if not target.is_file():
        return JSONResponse({"error": "static/index.html is missing"}, status_code=500)
    return FileResponse(target, headers={"Cache-Control": "no-cache"})


if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
