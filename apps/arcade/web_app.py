"""Arcade -- the games tab in Forge.

Four small 2D games live entirely in static/index.html. This backend exists for
exactly two things the browser cannot do on its own:

  1. Talk to Jan. The local LLM server is on another origin, so the page cannot
     reach it directly; /api/jan/chat proxies to it. The same page published as
     a claude.ai Artifact has no backend at all and falls back to a built-in
     template brain, so every game stays playable either way.

  2. Remember. Hearsay's NPCs keep a memory of what they were told, who told
     them, and what they have already claimed. That is persisted here so a
     reload does not wipe the case.

User data lives OUTSIDE this folder, the same way NovelForge and MediaForge do
it: ~/ForgeArcadeData/. Nothing here writes into the app directory.

Run standalone with:
    .venv/bin/python -m uvicorn web_app:app --host 127.0.0.1 --port 8433
"""

import json
import os
import tempfile
import time
from pathlib import Path

import httpx
import contextlib

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
# $ARCADE_DATA moves it (a Forge release keeps it in its own data folder).
DATA_DIR = Path(os.environ.get("ARCADE_DATA") or Path.home() / "ForgeArcadeData")
DATA_DIR.mkdir(parents=True, exist_ok=True)
SAVE_PATH = DATA_DIR / "hearsay_save.json"
# A Hearsay case is a few kB; anything near this is a runaway, not a save.
MAX_SAVE_BYTES = 1_000_000
# What the page may send to Jan: a short conversation, sane sampling.
MAX_MESSAGES = 40
MAX_CHAT_CHARS = 60_000
CHAT_ROLES = ("system", "user", "assistant")

# Jan is OpenAI-compatible. Override either with an env var if it moves.
JAN_BASE = os.environ.get("JAN_BASE_URL", "http://127.0.0.1:1337/v1")
JAN_MODEL = os.environ.get("JAN_MODEL", "")

app = FastAPI(title="Arcade")

# The Arcade's own Jan settings: which model its characters speak with, and how
# long that model may sit idle before its memory is given back (the owner, 2026-
# 09-16, "cause ram saving"). The helper is stdlib-only and shared by every Jan
# app; without it the Arcade behaves exactly as before.
import sys  # noqa: E402  (after the shared folder is known)

_SHARED_DIR = os.environ.get("FORGE_SHARED_DIR") or str(
    Path(__file__).resolve().parent.parent.parent / "shared"
)
if os.path.isdir(_SHARED_DIR) and _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)
# The no-cache helper lives in Forge's shared folder; without it the app
# still runs, the browser just guesses how long files stay fresh.
try:
    import forge_revalidate  # noqa: E402

    forge_revalidate.revalidate(app)
except ImportError:
    pass
try:
    import forge_jan

    _jan = forge_jan.mount(app, "arcade", roles=("chat",))
except Exception as _jan_error:  # the game still plays without the settings
    print(f"[arcade] Jan settings unavailable: {_jan_error}")
    _jan = None

_model_cache = {"name": JAN_MODEL, "checked": 0.0}


def _jan_model(client):
    """Whichever model Jan currently has loaded, cached for a minute.

    Jan's model id changes whenever the user swaps models in its UI, so
    hardcoding one guarantees a 404 the first time they switch.
    """
    if JAN_MODEL:
        return JAN_MODEL
    chosen = _jan.model_for("chat") if _jan else ""
    if chosen:
        return chosen
    now = time.time()
    if _model_cache["name"] and now - _model_cache["checked"] < 60:
        return _model_cache["name"]
    r = client.get(f"{JAN_BASE}/models", timeout=3.0)
    r.raise_for_status()
    data = r.json().get("data") or []
    if not data:
        raise RuntimeError("Jan is running but has no model loaded")
    _model_cache["name"] = data[0]["id"]
    _model_cache["checked"] = now
    return _model_cache["name"]


@contextlib.contextmanager
def _no_guard():
    """Stand-in for the Jan guard when the shared helper is not there."""
    yield


@app.get("/api/status")
def status():
    """Does the page have a backend, and is Jan reachable behind it?"""
    out = {"backend": True, "jan": False, "model": None, "detail": ""}
    try:
        with httpx.Client() as client:
            out["model"] = _jan_model(client)
            out["jan"] = True
    except Exception as e:
        out["detail"] = f"{type(e).__name__}: {e}"
    return out


def _number(payload: dict, key: str, default: float, low: float, high: float):
    """A number field from the page, or a plain 400 (it used to be a 500)."""
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(400, f"{key} must be a number")
    if not low <= value <= high:
        raise HTTPException(400, f"{key} must be between {low:g} and {high:g}")
    return value


def _chat_messages(payload: dict) -> list:
    """The conversation, checked before Jan is asked anything."""
    messages = payload.get("messages")
    if not messages:
        raise HTTPException(400, "messages required")
    if not isinstance(messages, list) or len(messages) > MAX_MESSAGES:
        raise HTTPException(400, f"messages must be a list of at most {MAX_MESSAGES}")
    total = 0
    for m in messages:
        if (
            not isinstance(m, dict)
            or m.get("role") not in CHAT_ROLES
            or not isinstance(m.get("content"), str)
        ):
            raise HTTPException(
                400, "each message needs a role (system, user, assistant) and text"
            )
        total += len(m["content"])
    if total > MAX_CHAT_CHARS:
        raise HTTPException(413, "the conversation is too long")
    return [{"role": m["role"], "content": m["content"]} for m in messages]


@app.post("/api/jan/chat")
def jan_chat(payload: dict):
    """One completion, in character. The game decides WHAT an NPC says; Jan
    only decides HOW they say it, which is why a small local model can't break
    the case logic."""
    body = {
        "messages": _chat_messages(payload),
        "temperature": float(_number(payload, "temperature", 0.85, 0, 2)),
        "max_tokens": int(_number(payload, "max_tokens", 160, 1, 1024)),
        "stream": False,
    }
    try:
        with httpx.Client() as client:
            body["model"] = _jan_model(client)
            # Naming the model is what loads it; the guard keeps the idle
            # release from unloading it mid-answer.
            with _jan.using(body["model"]) if _jan else _no_guard():
                r = client.post(f"{JAN_BASE}/chat/completions", json=body, timeout=90.0)
            if r.status_code >= 400:
                raise HTTPException(
                    502, f"Jan returned {r.status_code}: {r.text[:300]}"
                )
            data = r.json()
        text = (data["choices"][0]["message"]["content"] or "").strip()
        # Local models often narrate in asterisks or restate the name; the game
        # only wants the spoken line.
        for prefix in ("Assistant:", "AI:"):
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
        return {"text": text, "model": body["model"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            503, f"Jan unreachable at {JAN_BASE} ({type(e).__name__}: {e})"
        )


@app.get("/api/hearsay/save")
def hearsay_load():
    if not SAVE_PATH.is_file():
        return {"save": None}
    try:
        return {"save": json.loads(SAVE_PATH.read_text())}
    except Exception:
        return {"save": None}


@app.post("/api/hearsay/save")
def hearsay_save(payload: dict):
    try:
        data = json.dumps(payload, indent=1, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:  # a lone surrogate would save, then never load
        raise HTTPException(400, "the save holds text that is not valid unicode")
    if len(data) > MAX_SAVE_BYTES:
        raise HTTPException(413, "the save is too large")
    # written to a file of its own and moved into place, so a crash mid-write
    # or two saves at once never leave a half save that would wipe the case
    SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=SAVE_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(tmp, SAVE_PATH)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return {"saved": True, "path": str(SAVE_PATH)}


@app.delete("/api/hearsay/save")
def hearsay_clear():
    if SAVE_PATH.is_file():
        SAVE_PATH.unlink()
    return {"cleared": True}


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text()


# The shared Forge kit, when launched inside Forge. Mounted before the catch-all
# static mount, which would otherwise swallow the path.
_SHARED = os.environ.get("FORGE_SHARED_DIR", "")
if _SHARED and os.path.isdir(_SHARED):
    app.mount("/shared", StaticFiles(directory=_SHARED), name="shared")

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
