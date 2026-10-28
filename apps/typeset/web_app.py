"""Typeset: Typst documents with a live preview (see typeset_core)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import typeset_core as core

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR") or ROOT.parent.parent / "shared")
sys.path.insert(0, str(SHARED_DIR))
from forge_guard import LocalOnly  # noqa: E402

app = FastAPI(title="Typeset")
app.add_middleware(LocalOnly)  # only its own pages, never another site
TEMPLATES = core.load_templates()
# An SVG page opened on its own must not run anything in this origin.
SVG_CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"


def cfg() -> dict:
    return core.load_config(core.CONFIG)


@app.exception_handler(core.TypesetError)
async def said(_request: Request, exc: core.TypesetError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def text_of(body: dict) -> str | None:
    text = body.get("text")
    if text is not None and not isinstance(text, str):
        raise HTTPException(400, "the text is not a string")
    return text


@app.get("/api/state")
def state():
    c = cfg()
    spec = c["tools"]["typst"]
    return {
        "docs_dir": str(core.docs_dir(c)),
        "docs": core.list_docs(c),
        "templates": TEMPLATES,
        "typst": {
            "ready": core.typst_ready(c),
            "version": spec["version"],
            "bytes": spec.get("bytes", 0),
        },
    }


@app.post("/api/docs")
def new_doc(body: dict = Body(...)):
    return core.create(
        cfg(), str(body.get("name", "")), str(body.get("template", "")), TEMPLATES
    )


@app.get("/api/docs/{name}")
def get_doc(name: str):
    return core.read_doc(cfg(), name)


@app.put("/api/docs/{name}")
def put_doc(name: str, body: dict = Body(...)):
    text = text_of(body)
    if text is None:
        raise HTTPException(400, "the text is missing")
    core.save(cfg(), name, text)
    return {"ok": True}


@app.post("/api/docs/{name}/preview")
def preview(name: str, body: dict = Body(default={})):
    return core.preview(cfg(), name, text_of(body))


@app.get("/api/docs/{name}/page/{n}")
def page(name: str, n: int):
    try:
        path = core.page_file(cfg(), name, n)
    except core.TypesetError:
        raise HTTPException(404, "no such page") from None
    return FileResponse(
        path,
        media_type="image/svg+xml",
        headers={"Content-Security-Policy": SVG_CSP, "Cache-Control": "no-cache"},
    )


@app.post("/api/docs/{name}/pdf")
def make_pdf(name: str, body: dict = Body(default={})):
    return core.export_pdf(cfg(), name, text_of(body))


@app.get("/api/docs/{name}/pdf")
def get_pdf(name: str):
    folder = core.folder_of(cfg(), name)
    pdf = folder / f"{folder.name}.pdf"
    if not pdf.is_file():
        raise HTTPException(404, "export it first")
    return FileResponse(pdf, filename=pdf.name, media_type="application/pdf")


@app.post("/api/docs/{name}/assets")
async def add_asset(name: str, request: Request, filename: str):
    c = cfg()
    limit = c["asset_max_mb"] * 1e6
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise HTTPException(400, f"that file is over {c['asset_max_mb']} MB")
    return core.add_asset(c, name, filename, bytes(body))


@app.post("/api/docs/{name}/rename")
def rename(name: str, body: dict = Body(...)):
    return core.rename(cfg(), name, str(body.get("to", "")))


@app.post("/api/docs/{name}/trash")
def trash(name: str):
    core.trash(cfg(), name)
    return {"ok": True}


app.mount("/shared", StaticFiles(directory=SHARED_DIR), name="shared")
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
