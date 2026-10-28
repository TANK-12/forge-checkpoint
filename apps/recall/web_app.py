"""Recall: flashcards with FSRS, cards from Study Companion (see recall_core)."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import recall_core as core

ROOT = Path(__file__).resolve().parent
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR") or ROOT.parent.parent / "shared")
sys.path.insert(0, str(SHARED_DIR))
from forge_guard import LocalOnly  # noqa: E402

app = FastAPI(title="Recall")
app.add_middleware(LocalOnly)  # only its own pages, never another site

LOCK = threading.Lock()  # one writer at a time; SQLite is shared by the threads
_db = None


def db():
    global _db
    if _db is None:
        _db = core.connect(core.DATA_DIR)
    return _db


def per_day() -> int:
    return int(core.load_config(core.CONFIG).get("new_per_day", 20))


class CardReq(BaseModel):
    deck: str
    front: str
    back: str


class AnswerReq(BaseModel):
    id: int
    rating: int


class ImportReq(BaseModel):
    source: str


def guarded(fn, *args):
    with LOCK:
        try:
            return fn(db(), *args)
        except core.RecallError as e:
            raise HTTPException(400, str(e)) from None


@app.get("/api/decks")
def get_decks():
    when = core.now()
    return {
        "decks": guarded(core.decks, when, per_day()),
        "all": guarded(core.counts, when, per_day()),
        "stats": guarded(core.stats, when),
    }


@app.get("/api/next")
def get_next(deck: str = ""):
    return guarded(core.next_card, core.now(), per_day(), deck)


@app.post("/api/answer")
def post_answer(req: AnswerReq):
    return guarded(core.answer, req.id, req.rating)


@app.get("/api/cards")
def get_cards(deck: str = "", q: str = ""):
    return {"cards": guarded(core.list_cards, deck, q)}


@app.post("/api/cards")
def post_card(req: CardReq):
    return {"id": guarded(core.add_card, req.deck, req.front, req.back)}


@app.put("/api/cards/{card}")
def put_card(card: int, req: CardReq):
    guarded(core.edit_card, card, req.front, req.back, req.deck)
    return {"ok": True}


@app.post("/api/cards/{card}/remove")
def remove_card(card: int):
    guarded(core.remove_card, card)
    return {"ok": True}


@app.get("/api/sources")
def get_sources():
    return {"sources": guarded(core.sources, core.load_config(core.CONFIG))}


@app.post("/api/import")
def post_import(req: ImportReq):
    return guarded(core.import_source, core.load_config(core.CONFIG), req.source)


app.mount("/shared", StaticFiles(directory=SHARED_DIR), name="shared")
app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
