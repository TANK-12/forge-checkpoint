"""Dossier - the research desk tab in Forge.

The backend does four things the page cannot: reach the open web, reach Jan,
write to the drive, and keep a work queue running while nobody is looking.
Everything about what a dossier contains lives in the three registries
(`sources/`, `entities/`, `pages/`), so this file stays a thin API over them
and never names an individual source, subject type or page.

Run standalone with:
    FORGE_SHARED_DIR=~/Forge/shared \\
    .venv/bin/python -m uvicorn web_app:app --host 127.0.0.1 --port 8437
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import ask as ask_mod
import briefing as briefing_mod
import guard
import dossier
import janidle
import manifest
import enrich
import entities.registry as entity_registry
import llm
import location
import pages.registry as page_registry
import jobqueue
import store
import watcher as watcher_mod
from research import arcs as arcs_mod
from research import graph as graph_mod
from research import speech as speech_mod
from research import seeds
from research.pipeline import research
from sources.registry import all_sources

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR", ROOT.parent.parent / "shared"))

if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
import forge_revalidate  # noqa: E402  (lives in the shared folder)

app = FastAPI(title="Dossier")
forge_revalidate.revalidate(app)


@app.exception_handler(store.BadSlug)
def _bad_slug(_request, _exc):
    """A slug that is not a folder name names no dossier."""
    return JSONResponse({"detail": "No dossier stored under that name"}, 404)


def _number(
    payload: dict,
    key: str,
    default: int,
    low: int | None = None,
    high: int | None = None,
) -> int:
    """A whole-number field from a request body. A wrong type is the caller's
    mistake and gets a 400 saying so, not a server error."""
    raw = payload.get(key, default)
    try:
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            raise TypeError(key)
        value = int(float(raw)) if isinstance(raw, str) else int(raw)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(400, f"'{key}' must be a number")
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value


# --- where the library lives ---------------------------------------------------


@app.get("/api/location")
def location_status(folder: str = ""):
    """The library folder in use, plus library-shaped folders found in
    ``folder`` (or home and any mounted drive when none is given)."""
    root = store.data_root()
    current = location.describe(root.path)
    out = {
        "current": {
            "path": str(root.path),
            "detail": root.detail,
            "subjects": current["subjects"] if current else 0,
        },
        "fixed": location.FIXED,
        "searched": [],
        "found": [],
    }
    if location.FIXED:  # kept with the rest of Forge's things: nothing to find
        return out
    places = [Path(folder).expanduser()] if folder else location.search_places()
    out["searched"] = [str(p) for p in places]
    out["found"] = [f for f in location.find(places) if f["path"] != str(root.path)]
    return out


@app.post("/api/location")
def location_choose(body: dict):
    if location.FIXED:
        raise HTTPException(
            403,
            "In Forge the library is kept with the rest of your things."
            " Move them all from Where your things are kept.",
        )
    try:
        location.choose(Path(str(body.get("path", ""))).expanduser())
    except ValueError as e:
        raise HTTPException(400, str(e))
    root = store.data_root(refresh=True)
    return {"path": str(root.path), "detail": root.detail}


# --- status -----------------------------------------------------------------


@app.get("/api/status")
def status():
    root = store.data_root()
    jan = llm.status()
    return {
        "backend": True,
        "jan": jan["jan"],
        "models": jan["models"],
        "tiers": jan["tiers"],
        "jan_detail": jan["detail"],
        "storage": {
            "path": str(root.path),
            "on_usb": root.on_usb,
            "detail": root.detail,
            "free_gb": round(store.free_bytes(root.path) / 1e9, 1),
            "fixed": location.FIXED,
        },
        "entity_types": [
            {
                "name": e.name,
                "label": e.label,
                "plural": e.plural,
                "blurb": e.blurb,
                "accent": e.accent,
                "pages": list(e.pages),
            }
            for e in entity_registry.all_types()
        ],
        "sources": [
            {
                "name": s.name,
                "label": s.label,
                "tier": s.tier,
                "phases": list(s.phases),
                "description": s.description,
            }
            for s in all_sources()
        ],
        "seeds": seeds.catalogue(),
    }


# --- the library ------------------------------------------------------------


@app.get("/api/library")
def library():
    rows = dossier.library()
    by_country: dict[str, dict] = {}
    for row in rows:
        stored_country = row.get("country") or ""
        key = stored_country or "Unattributed"
        bucket = by_country.setdefault(
            key, {"country": key, "subjects": 0, "types": {}}
        )
        bucket["subjects"] += 1
        bucket["types"][row["entity_type"]] = (
            bucket["types"].get(row["entity_type"], 0) + 1
        )
    return {"subjects": rows, "countries": list(by_country.values())}


@app.get("/api/subject/{slug}")
def subject(slug: str):
    stored = dossier.load(slug)
    if not stored:
        raise HTTPException(404, f"No dossier stored for '{slug}'")
    entity_type = (stored.get("subject") or {}).get("entity_type", "person")
    spec = entity_registry.get(entity_type) or entity_registry.default()
    built = []
    for name in spec.pages:
        page = page_registry.build_page(name, stored)
        page["name"] = name
        built.append(page)
    return {
        "subject": stored.get("subject", {}),
        "entity_type": entity_type,
        "accent": spec.accent,
        "pages": built,
        "counts": {
            "sources": len(stored.get("sources") or []),
            "claims": len(stored.get("claims") or []),
            "timeline": len(stored.get("timeline") or []),
            "quotes": len(stored.get("quotes") or []),
        },
        "history": (stored.get("history") or [])[-10:],
        # Only pictures actually on disk - a reference with no file behind it
        # would render as a broken image.
        "images": [
            {
                "kind": i.get("kind", ""),
                "label": i.get("label", ""),
                "credit": i.get("credit", ""),
                "url": f"/api/subject/{slug}/image/" + i["stored"].split("/", 1)[1],
            }
            for i in (stored.get("images") or [])
            if i.get("stored")
        ],
    }


@app.delete("/api/subject/{slug}")
def delete_subject(slug: str):
    if not dossier.delete(slug):
        raise HTTPException(404, f"No dossier stored for '{slug}'")
    return {"deleted": slug}


@app.get("/api/subject/{slug}/image/{name}")
def subject_image(slug: str, name: str):
    """Serve a picture already pulled down for this subject.

    Only files inside that subject's own images directory, and only names the
    subject's own images.json vouches for - a path from the URL is never joined
    onto the data root and trusted.
    """
    stored = dossier.load(slug)
    wanted = f"images/{name}"
    if not any(i.get("stored") == wanted for i in (stored.get("images") or [])):
        raise HTTPException(404, "No such picture for this subject")
    path = store.subject_dir(slug) / "images" / name
    if not path.is_file():
        raise HTTPException(404, "That picture has not been downloaded yet")
    return FileResponse(path)


@app.get("/api/subject/{slug}/texts")
def subject_texts(slug: str):
    return {"texts": dossier.saved_texts(slug)}


@app.get("/api/subject/{slug}/text/{source_id}")
def subject_text(slug: str, source_id: str):
    text = dossier.saved_text(slug, source_id)
    if text is None:
        raise HTTPException(404, "No saved text for that source")
    return {"source_id": source_id, "text": text}


@app.post("/api/subject/{slug}/notes")
def save_notes(slug: str, payload: dict):
    return dossier.save_notes(slug, str(payload.get("markdown", "")))


@app.post("/api/subject/{slug}/ask")
def ask_subject(slug: str, payload: dict):
    question = str(payload.get("question", "")).strip()
    if not question:
        raise HTTPException(400, "A question is required")
    return ask_mod.answer(slug, question)


# --- research ---------------------------------------------------------------


@app.post("/api/research")
def start_research(payload: dict):
    """Queue one subject. Returns immediately; the queue does the work."""
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "A name is required")
    q = jobqueue.get_queue()
    job = q.add(
        name,
        entity_type=str(payload.get("entity_type", "person")),
        phase=str(payload.get("phase", "quick")),
        qid=str(payload.get("qid", "")),
    )
    q.start()
    return job


@app.post("/api/research/now")
def research_now(payload: dict):
    """Run one subject synchronously. Used for a single quick look."""
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "A name is required")
    result = research(
        name,
        entity_type=str(payload.get("entity_type", "person")),
        phase=str(payload.get("phase", "quick")),
        log=lambda m: None,
    )
    changes = dossier.save(result)
    return {"slug": result["slug"], "report": result["report"], "changes": changes}


# --- the queue --------------------------------------------------------------


@app.get("/api/queue")
def queue_state():
    return jobqueue.get_queue().state()


@app.post("/api/queue/recipe")
def queue_recipe(payload: dict):
    recipe = str(payload.get("recipe", ""))
    if recipe not in seeds.RECIPES:
        raise HTTPException(400, f"No seed recipe called '{recipe}'")
    q = jobqueue.get_queue()
    # Left unset, this follows the active queue's own "redo subjects I already
    # hold" setting rather than a second control that could disagree with it.
    skip = payload.get("skip_existing")
    limit = _number(payload, "limit", 100)
    try:
        result = q.add_recipe(
            recipe,
            limit=limit,
            phase=str(payload.get("phase", "quick")),
            skip_existing=None if skip is None else bool(skip),
        )
    except Exception as e:
        raise HTTPException(502, f"Seeding failed: {type(e).__name__}: {e}")
    if payload.get("start", True):
        q.start()
    return result


@app.post("/api/queue/deepen")
def queue_deepen(payload: dict):
    limit = _number(payload, "limit", 25)
    q = jobqueue.get_queue()
    result = q.add_deep_for_held(limit=limit)
    if payload.get("start", True):
        q.start()
    return result


# --- several queues ---------------------------------------------------------
#
# One queue is active and the workers only pull from that one. Everything under
# /api/queue acts on whichever that is, so the older routes keep their meaning.


@app.get("/api/queues")
def list_queues():
    return {"queues": jobqueue.get_queue().queues()}


@app.post("/api/queues")
def create_queue(payload: dict):
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "A name is required")
    q = jobqueue.get_queue()
    made = q.create_queue(name, redo_held=bool(payload.get("redo_held", False)))
    if payload.get("activate", True):
        q.activate(made["id"])
    return {"queue": made, "queues": q.queues()}


@app.post("/api/queues/{queue_id}/activate")
def activate_queue(queue_id: str):
    q = jobqueue.get_queue()
    if not q.activate(queue_id):
        raise HTTPException(404, f"No queue with id '{queue_id}'")
    return q.state()


@app.post("/api/queues/{queue_id}/rename")
def rename_queue(queue_id: str, payload: dict):
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "A name is required")
    q = jobqueue.get_queue()
    if not q.rename(queue_id, name):
        raise HTTPException(404, f"No queue with id '{queue_id}'")
    return {"queues": q.queues()}


@app.post("/api/queues/{queue_id}/redo")
def set_queue_redo(queue_id: str, payload: dict):
    """Whether this queue may research subjects the library already holds."""
    q = jobqueue.get_queue()
    if not q.set_redo(queue_id, bool(payload.get("redo", False))):
        raise HTTPException(404, f"No queue with id '{queue_id}'")
    return q.state()


@app.delete("/api/queues/{queue_id}")
def delete_queue(queue_id: str):
    q = jobqueue.get_queue()
    if not q.delete_queue(queue_id):
        raise HTTPException(
            400, "That queue could not be deleted - the last one has to stay"
        )
    return {"deleted": queue_id, "queues": q.queues()}


@app.post("/api/queue/{action}")
def queue_control(action: str, payload: dict | None = None):
    q = jobqueue.get_queue()
    if action == "start":
        q.start()
    elif action == "pause":
        q.pause()
    elif action == "resume":
        q.resume()
    elif action == "stop":
        q.stop()
    elif action == "clear":
        q.clear_finished()
    elif action == "remove":
        q.remove(str((payload or {}).get("id", "")))
    else:
        raise HTTPException(400, f"Unknown queue action '{action}'")
    return q.state()


# --- speech -----------------------------------------------------------------
#
# Rendering uses the Piper install and the voice models NovelForge already has,
# rather than a second copy of a 120MB model in this app's venv.


@app.get("/api/speech")
def speech_state():
    return speech_mod.available()


@app.get("/api/subject/{slug}/tour")
def tour_text(slug: str):
    """The narration script, without rendering it. Fast, and readable."""
    script = speech_mod.tour_script(slug)
    if script.get("error"):
        raise HTTPException(404, script["error"])
    existing = speech_mod.existing_tour(slug)
    return {**script, "audio": ("/api/audio/" + existing) if existing else ""}


@app.post("/api/subject/{slug}/tour")
def tour_audio(slug: str, payload: dict | None = None):
    """Play the tour if it has been read already, otherwise queue the reading.

    A few minutes of narration takes over a minute of CPU, which is far too
    long to hold an HTTP request open - and queueing it means a whole list of
    subjects can be read overnight the same way they were researched.
    """
    existing = speech_mod.existing_tour(slug)
    if existing:
        return {"ready": True, "url": "/api/audio/" + existing}

    stored = dossier.load(slug)
    if not stored:
        raise HTTPException(404, f"No dossier stored for '{slug}'")
    state = speech_mod.available()
    if not state["ready"]:
        raise HTTPException(503, "; ".join(state["missing"]))

    q = jobqueue.get_queue()
    name = (stored.get("subject") or {}).get("name", slug)
    job = q.add(name, entity_type=stored.get("entity_type", "person"), phase="tour")
    if bool((payload or {}).get("start", True)):
        q.start()
    return {"ready": False, "queued": True, "job": job, "queue": q.active["name"]}


@app.post("/api/subject/{slug}/ask-aloud")
def ask_aloud(slug: str, payload: dict):
    """Answer from the stored evidence, then speak the answer.

    ask.py has already deleted any sentence that cites nothing, so what is
    spoken is exactly what would have been shown in writing.
    """
    question = str(payload.get("question", "")).strip()
    if not question:
        raise HTTPException(400, "A question is required")
    out = speech_mod.answer_aloud(
        slug, question, voice=str(payload.get("voice", speech_mod.DEFAULT_VOICE))
    )
    if not out.get("ok"):
        raise HTTPException(502, out.get("error", "Nothing could be said about that"))
    return {
        "url": "/api/audio/" + Path(out["path"]).name,
        "answer": out.get("answer", ""),
        "used": out.get("used", []),
    }


@app.get("/api/audio/{name}")
def audio_file(name: str):
    """Serve a rendered mp3. Only from the audio directory, only by name."""
    if "/" in name or "\\" in name or not name.endswith(".mp3"):
        raise HTTPException(400, "Not an audio file")
    path = store.data_root().path / speech_mod.AUDIO_DIR / name
    if not path.is_file():
        raise HTTPException(404, "No such recording")
    return FileResponse(path, media_type="audio/mpeg")


# --- connections ------------------------------------------------------------
#
# All of this is arithmetic over stored relations: no model is called, so it
# runs on the CPU and stays out of the way of whatever has the iGPU. A model
# asked how two people are connected would invent a plausible chain, which is
# the one thing this app exists not to produce.


@app.get("/api/graph")
def graph_stats(refresh: bool = False):
    g = graph_mod.current(refresh=refresh)
    held = [n for n in g.nodes.values() if n["held"]]
    busiest = sorted(g.nodes.values(), key=lambda n: -n["degree"])[:20]
    return {
        "nodes": len(g.nodes),
        "held": len(held),
        "named_only": len(g.nodes) - len(held),
        "edges": sum(len(v) for v in g.adj.values()) // 2,
        "most_connected": [
            {
                "key": n["key"],
                "name": n["name"],
                "held": n["held"],
                "links": n["degree"],
            }
            for n in busiest
        ],
    }


@app.get("/api/graph/{slug}")
def graph_around(slug: str, depth: int = 2, budget: int = 90):
    """The neighbourhood the mind map draws."""
    g = graph_mod.current()
    key = graph_mod.resolve(slug, g)
    if key is None:
        raise HTTPException(404, f"Nothing in the graph called '{slug}'")
    return g.around(key, depth=max(1, min(depth, 4)), budget=max(10, min(budget, 400)))


@app.get("/api/path")
def graph_path(start: str = "", goal: str = "", max_hops: int = 6):
    """How two subjects are linked, as a chain of stored relations."""
    if not start or not goal:
        raise HTTPException(400, "Both 'start' and 'goal' are required")
    g = graph_mod.current()
    a, b = graph_mod.resolve(start, g), graph_mod.resolve(goal, g)
    if a is None:
        raise HTTPException(404, f"Nothing in the graph called '{start}'")
    if b is None:
        raise HTTPException(404, f"Nothing in the graph called '{goal}'")
    hops = g.path(a, b, max_hops=max(1, min(max_hops, 8)))
    return {
        "start": g.nodes[a],
        "goal": g.nodes[b],
        "found": hops is not None,
        "hops": hops or [],
    }


# --- the world --------------------------------------------------------------


@app.get("/api/briefing")
def get_briefing(full: bool = False):
    """The briefing the page draws.

    The stored briefing keeps every event it considered - 200KB of it - but the
    panel shows a summary and a per-country rollup. Sending the whole thing on
    every page load made the first paint wait on a payload nothing reads, so
    the sample events are trimmed out unless `full=1` asks for them.
    """
    stored = briefing_mod.latest()
    if not stored:
        return {"generated": "", "countries": [], "summary": "", "events_total": 0}
    if full:
        return stored
    return {
        **{k: v for k, v in stored.items() if k not in ("countries", "cited_events")},
        "countries": [
            {
                "country": c["country"],
                "events": c["events"],
                "subjects": c["subjects"][:6],
                "latest": c["latest"],
            }
            for c in stored.get("countries", [])
        ],
        "cited_events_count": len(stored.get("cited_events", [])),
    }


@app.post("/api/briefing/rebuild")
def rebuild_briefing(payload: dict | None = None):
    payload = payload or {}
    kind = str(payload.get("kind", "manual"))
    if kind != "manual" and kind not in briefing_mod.KINDS:
        raise HTTPException(400, f"No kind of brief called '{kind}'")
    spec = briefing_mod.KINDS.get(kind)
    days = _number(payload, "days", spec["days"] if spec else 14, 1, 3650)
    built = briefing_mod.build(
        days=days, write_summary=bool(payload.get("summary", True))
    )
    briefing_mod.save(built, kind=kind)
    return built


@app.get("/api/briefings")
def list_briefings(kind: str = ""):
    """Every brief ever written, newest first."""
    return {
        "kinds": [
            {
                "name": k,
                "label": v["label"],
                "window_days": v["days"],
                "every_days": v["every_days"],
                "due": briefing_mod.due(k),
            }
            for k, v in briefing_mod.KINDS.items()
        ],
        "briefs": briefing_mod.history(kind),
    }


@app.get("/api/briefing/{kind}/{date}")
def read_briefing(kind: str, date: str):
    if kind != "manual" and kind not in briefing_mod.KINDS:
        raise HTTPException(404, f"No {kind} brief for {date}")
    found = briefing_mod.read(kind, date)
    if not found:
        raise HTTPException(404, f"No {kind} brief for {date}")
    return found


@app.post("/api/briefing/run-scheduled")
def run_scheduled_briefings(payload: dict | None = None):
    written = briefing_mod.run_scheduled(force=str((payload or {}).get("kind", "")))
    return {"written": written}


UNATTRIBUTED = "Unattributed"


def _world_places(row: dict) -> list[str]:
    """The places the map counts a subject under: at most its first two.

    Only the subject's own file is read: loading every dossier whole made the
    map the slowest call the page makes. A subject with no recorded place is
    counted under "Unattributed", which is a label the map makes up, not a
    value stored anywhere.
    """
    if row.get("entity_type") == "country":
        return [row["name"]]
    identity = dossier.load_subject(row["slug"]).get("identity") or {}
    places = identity.get("citizenship") or identity.get("country") or []
    return (places or [UNATTRIBUTED])[:2]


@app.get("/api/world")
def world():
    """Per-country totals for the map."""
    rows = dossier.library()
    counts: dict[str, dict] = {}
    for row in rows:
        for place in _world_places(row):
            bucket = counts.setdefault(
                place,
                {
                    "country": place,
                    "subjects": 0,
                    "types": {},
                    "claims": 0,
                    "disputed": 0,
                    "events": 0,
                    "names": [],
                },
            )
            bucket["subjects"] += 1
            bucket["types"][row["entity_type"]] = (
                bucket["types"].get(row["entity_type"], 0) + 1
            )
            bucket["claims"] += row.get("claims", 0)
            bucket["disputed"] += row.get("disputed", 0)
            bucket["events"] += row.get("timeline", 0)
            if len(bucket["names"]) < 40:
                bucket["names"].append(
                    {
                        "slug": row["slug"],
                        "name": row["name"],
                        "entity_type": row["entity_type"],
                    }
                )
    return {
        "countries": sorted(counts.values(), key=lambda c: c["subjects"], reverse=True)
    }


@app.get("/api/world/place")
def world_place(name: list[str] = Query(default=[])):
    """Every subject the map counts under any of these places.

    The map's panel lists 40 names a place. This is how the library shows all
    of them, exactly as counted: a text search cannot, because "Unattributed"
    is stored nowhere and "Republic of China" is also inside "People's
    Republic of China".
    """
    wanted = set(name)
    return {
        "slugs": [
            row["slug"]
            for row in dossier.library()
            if wanted.intersection(_world_places(row))
        ]
    }


# --- arcs drawn between countries -------------------------------------------


@app.get("/api/world/arcs")
def world_arcs():
    """Ties between countries, derived from stored relations.

    Arithmetic over data already on disk - no model is involved, so this can be
    answered while the iGPU is busy with a deep dive.
    """
    return {"arcs": arcs_mod.build(), "kinds": arcs_mod.kinds()}


# --- the news watcher -------------------------------------------------------


@app.get("/api/watch")
def watch_state():
    return watcher_mod.state(jobqueue.get_queue())


@app.post("/api/watch")
def watch_settings(payload: dict | None = None):
    patch = dict(payload or {})
    for key in ("every_hours", "per_sweep"):
        if key in patch:
            patch[key] = _number(patch, key, 0)
    watcher_mod.update(patch)
    return watcher_mod.state(jobqueue.get_queue())


@app.post("/api/watch/sweep")
def watch_sweep(payload: dict | None = None):
    """Refresh the stalest subjects now.

    `force` runs a sweep even when the watcher is switched off, which is what
    the button does; it still refuses to barge past a pause or a busy queue.
    """
    forced = bool((payload or {}).get("force", True))
    result = watcher_mod.sweep(jobqueue.get_queue(), force=forced)
    return {**result, "state": watcher_mod.state(jobqueue.get_queue())}


# --- filling in history -----------------------------------------------------
#
# Five years of news and the full encyclopedia article for subjects researched
# before either existed. See enrich.py.


@app.get("/api/history")
def history_state():
    return enrich.state()


@app.post("/api/history")
def history_start(payload: dict | None = None):
    payload = payload or {}
    started = enrich.start(
        articles=bool(payload.get("articles", True)),
        limit=_number(payload, "limit", 0, 0),
    )
    if not started:
        raise HTTPException(409, "History is already being filled in")
    return enrich.state()


@app.post("/api/history/stop")
def history_stop():
    enrich.stop()
    return enrich.state()


@app.post("/api/subject/{slug}/new-info")
def subject_new_info(slug: str):
    """Bring one held subject up to date with everything added since it was
    researched: five years of news and a fresh copy of the article.

    News merges in on the usual date-and-title key and nothing stored is
    removed. Runs in the background; progress is `GET /api/history`.
    """
    if not dossier.exists(slug):
        raise HTTPException(404, f"No dossier stored for '{slug}'")
    if not enrich.start(slugs=[slug], refresh_articles=True):
        raise HTTPException(
            409, "New information is already being fetched - wait for it to finish"
        )
    return enrich.state()


# --- the brief scheduler ----------------------------------------------------

_scheduler_started = False


def _brief_scheduler():
    """Write the daily and weekly briefs when they fall due, and sweep for news.

    A timer inside the app rather than anything external: the brief is only
    useful if it is already there when the user looks, and nothing should have
    to be remembered or left running elsewhere to make that happen.
    """
    while True:
        try:
            written = briefing_mod.run_scheduled()
            if written:
                print(f"[dossier] wrote briefs: {', '.join(written)}", flush=True)
        except Exception as e:
            print(f"[dossier] brief scheduler: {type(e).__name__}: {e}", flush=True)
        # The watcher shares this tick rather than running a second thread: it
        # only ever decides whether a sweep is due, which costs nothing, and a
        # sweep that is deferred is simply retried half an hour later.
        try:
            swept = watcher_mod.run_scheduled(jobqueue.get_queue())
            if swept.get("ran"):
                print(
                    f"[dossier] news watcher queued {swept['queued']} subjects",
                    flush=True,
                )
        except Exception as e:
            print(f"[dossier] news watcher: {type(e).__name__}: {e}", flush=True)
        time.sleep(1800)


@app.on_event("startup")
def _start_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    threading.Thread(target=_brief_scheduler, daemon=True, name="briefs").start()
    # A long unattended run must not be able to freeze the machine.
    guard.watch(
        jobqueue.get_queue(),
        log=lambda m: print(m, flush=True),
    )
    # Idle models hold gigabytes on a machine with no swap; Jan reloads on demand.
    janidle.watch(log=lambda m: print(m, flush=True))
    # A readable account of the run, so a crash leaves a record of where it stood.
    manifest.watch(jobqueue.get_queue(), log=lambda m: print(m, flush=True))


# --- static -----------------------------------------------------------------

if SHARED_DIR.is_dir():
    app.mount("/shared", StaticFiles(directory=str(SHARED_DIR)), name="shared")


@app.get("/")
def index():
    target = STATIC_DIR / "index.html"
    if not target.is_file():
        return JSONResponse({"error": "static/index.html is missing"}, status_code=500)
    return FileResponse(target)


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
