"""Terminal - real shells inside Forge.

`ptyhost.py` owns the shells; this file serves the page and one WebSocket per
open tab. Protocol on `/ws/{id}`: the page sends text frames of JSON
(`{"t": "in", "d": "..."}`, `{"t": "resize", "cols", "rows"}`), the server
sends the shell's raw output as binary frames and `{"t": "exit", "code"}` as
text when the shell ends. On attach the kept scrollback is replayed first.

A shell is the most dangerous thing a local web server can hand out, so:
- /api routes need `X-Forge: 1` (a cross-origin page cannot send it without
  a CORS preflight, which is never granted);
- the WebSocket, which cannot carry custom headers, needs the per-run token
  from /api/session **and** an Origin equal to this server's own address.

Run standalone with:
    .venv/bin/python -m uvicorn web_app:app --host 127.0.0.1 --port 8459
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Body, Depends, FastAPI, Header, HTTPException, WebSocket
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

from ptyhost import Registry

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR", ROOT.parent.parent / "shared"))
TOKEN = secrets.token_urlsafe(24)
terms = Registry()


class HideToken(logging.Filter):
    """uvicorn logs every WebSocket address, ?t=<token> included, into
    outputs/terminal.log. The token is masked there, so the log never holds a
    working key to the shells."""

    TOKEN_RE = re.compile(r"([?&]t=)[^&\s\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        text = record.getMessage()
        if "t=" in text:
            record.msg, record.args = self.TOKEN_RE.sub(r"\1…", text), ()
        return True


for _name in ("uvicorn.error", "uvicorn.access"):
    logging.getLogger(_name).addFilter(HideToken())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    terms.close_all()
    await asyncio.sleep(0.2)


if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
import forge_revalidate  # noqa: E402  (lives in the shared folder)

app = FastAPI(title="Forge Terminal", lifespan=lifespan)
forge_revalidate.revalidate(app)


def forge_only(x_forge: str | None = Header(default=None)) -> None:
    if x_forge != "1":
        raise HTTPException(403, "Send X-Forge: 1")


guard = [Depends(forge_only)]


@app.get("/api/session", dependencies=guard)
def session() -> dict:
    return {"token": TOKEN, "home": str(Path.home())}


@app.get("/api/terms", dependencies=guard)
def list_terms() -> list[dict]:
    return terms.list()


@app.post("/api/terms", dependencies=guard)
async def new_term(
    cwd: str | None = Body(default=None),
    cols: int = Body(default=100),
    rows: int = Body(default=30),
) -> dict:
    return terms.create(cwd, cols, rows).public()


@app.delete("/api/terms/{tid}", dependencies=guard)
def close_term(tid: str) -> dict:
    if not terms.remove(tid):
        raise HTTPException(404, "No such terminal")
    return {"ok": True}


def same_origin(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin", "")
    host = ws.headers.get("host", "")
    return bool(origin) and urlsplit(origin).netloc == host


# Close codes the page acts on. A close before accept reaches a browser only
# as 1006, so a same-origin page is accepted first and then told why.
STALE_TOKEN, NO_SHELL, TAKEN = 4403, 4404, 4409


def handle(term, msg: object) -> None:
    """One message from the page; anything malformed is ignored."""
    if not isinstance(msg, dict):
        return
    if msg.get("t") == "in":
        if isinstance(msg.get("d"), str):
            # a lone surrogate (JSON "\ud800") cannot be UTF-8: write "?"
            term.write(msg["d"].encode("utf-8", "replace"))
    elif msg.get("t") == "resize":
        try:
            term.resize(msg.get("cols", 80), msg.get("rows", 24))
        except (TypeError, ValueError, OverflowError):
            pass


@app.websocket("/ws/{tid}")
async def attach(ws: WebSocket, tid: str) -> None:
    if not same_origin(ws):
        await ws.close(code=STALE_TOKEN)
        return
    # bytes: compare_digest raises on a str with non-ASCII characters
    token_ok = secrets.compare_digest(
        ws.query_params.get("t", "").encode(), TOKEN.encode()
    )
    term = terms.get(tid)
    if not token_ok or term is None:
        # the page's own origin: say why, so it can fetch a new token (the
        # backend restarted) or mark the shell as gone instead of retrying
        await ws.accept()
        await ws.close(code=NO_SHELL if token_ok else STALE_TOKEN)
        return
    await ws.accept()
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    # Replay what the screen had, then stream. One page per shell: a second
    # attach (the same tab reopened elsewhere) takes over from the first.
    for other in list(term.listeners):
        other(None)
    term.listeners.clear()
    term.listeners.add(queue.put_nowait)
    if term.buffer:
        await ws.send_bytes(bytes(term.buffer))

    async def pump() -> None:
        while True:
            data = await queue.get()
            if data is None:
                if not term.alive:
                    await ws.send_text(
                        json.dumps({"t": "exit", "code": term.exit_code})
                    )
                    await ws.close()
                else:  # another page attached to this shell
                    await ws.close(code=TAKEN)
                return
            # Coalesce bursts (a `cat` of a big file) into fewer frames.
            while not queue.empty() and len(data) < 256 * 1024:
                more = queue.get_nowait()
                if more is None:
                    queue.put_nowait(None)
                    break
                data += more
            await ws.send_bytes(data)

    sender = asyncio.create_task(pump())
    if not term.alive:
        queue.put_nowait(None)
    try:
        while True:
            frame = await ws.receive()
            if frame["type"] == "websocket.disconnect":
                break
            if frame.get("text") is None:  # the page never sends binary
                continue
            try:
                msg = json.loads(frame["text"])
            except json.JSONDecodeError:
                continue
            handle(term, msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        term.listeners.discard(queue.put_nowait)
        sender.cancel()


if SHARED_DIR.is_dir():
    app.mount("/shared", StaticFiles(directory=str(SHARED_DIR)), name="shared")
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
