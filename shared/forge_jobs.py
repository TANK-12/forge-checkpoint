"""Background jobs with a log stream, shared by the Forge apps that run long
tasks behind a page: MediaForge (every tool) and Media (yt-dlp, study).

A Job runs on its own thread. What it says goes into a queue as events:

    {"type": "log", "text": ...}
    {"type": "progress", "frac": 0.0 .. 1.0}
    {"type": "done"} or {"type": "error", "error": ...}

and the page reads them over server-sent events (GET /api/jobs/{id}/events,
the shape /shared/forge.js `forgeStream` expects). The queue has one reader:
a second connection steals events from the first, which is why the page
keeps one EventSource per job.

    store = JobStore()
    app.include_router(job_router(store))
    job = store.start(Job("subtitles"), lambda job: ...)

Kill: `job.stop()` (also spelled `kill_now()`) sets `stop_requested`, and
ends the subprocess in `job.proc` or the ffmpeg runner in `job.current_ffjob`
when there is one; work loops check `job.should_stop()` between steps.
"""

from __future__ import annotations

import asyncio
import json
import queue
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

KEEP_FINISHED = 20  # finished jobs kept so the page can still ask how one ended


class Job:
    def __init__(self, kind: str, tool: str = ""):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.tool = tool or kind.split("-")[0]
        self.status = "running"
        self.error: Optional[str] = None
        self.result: Any = None  # what the job hands back
        self.started = time.time()
        self.events: queue.Queue = queue.Queue()
        self.stop_requested = threading.Event()
        self.proc: Optional[subprocess.Popen] = None
        self.current_ffjob: Any = None  # anything with .kill()
        self.thread: Optional[threading.Thread] = None
        self.last_line = ""
        self.frac = 0.0  # latest progress, for the job list

    def log(self, text) -> None:
        self.last_line = str(text)
        self.events.put({"type": "log", "text": str(text)})

    def progress(self, frac) -> None:
        try:
            frac = max(0.0, min(1.0, float(frac)))
        except (TypeError, ValueError):
            return
        self.frac = frac
        self.events.put({"type": "progress", "frac": frac})

    def should_stop(self) -> bool:
        return self.stop_requested.is_set()

    def finish(self, status: str, error: Optional[str] = None) -> None:
        self.status, self.error = status, error
        self.events.put({"type": status, "error": error})

    def stop(self) -> None:
        self.stop_requested.set()
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
        if self.current_ffjob is not None:
            self.current_ffjob.kill()

    kill_now = stop

    def summary(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "tool": self.tool,
            "status": self.status,
            "error": self.error,
            "started": self.started,
            "frac": self.frac,
            "last_line": self.last_line[-200:],
        }


class JobStore:
    """The jobs one backend knows about. `jobs` is a plain dict, so tests can
    put a job in it by hand."""

    def __init__(self, keep: int = KEEP_FINISHED):
        self.jobs: dict[str, Job] = {}
        self.keep = keep

    def get(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def prune(self) -> None:
        finished = [j for j in self.jobs.values() if j.status != "running"]
        for old in finished[: max(0, len(finished) - self.keep)]:
            self.jobs.pop(old.id, None)

    def start(self, job: Job, work: Callable[[Job], Any]) -> Job:
        """Register `job` and run `work(job)` on a thread. An exception ends
        the job as an error with its message; returning ends it as done."""

        def run():
            try:
                work(job)
                job.finish("done")
            except Exception as e:  # the page shows the message
                job.finish("error", str(e) or e.__class__.__name__)

        self.prune()
        self.jobs[job.id] = job
        job.thread = threading.Thread(target=run, daemon=True)
        job.thread.start()
        return job


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def event_stream(job: Job):
    """Server-sent events for one job, batched: a burst of progress ticks
    (ffmpeg can send dozens in 120 ms) collapses into the latest one, flushed
    before the next log line so progress never overtakes the line it belongs
    to. A job that ended before anyone listened still sends its end."""
    while True:
        batch = []
        try:
            batch.append(await asyncio.to_thread(job.events.get, True, 5.0))
        except queue.Empty:
            if job.status != "running":
                yield _sse({"type": job.status, "error": job.error})
                return
            yield ": keep-alive\n\n"
            continue
        deadline = time.time() + 0.12
        while time.time() < deadline:
            try:
                batch.append(job.events.get_nowait())
            except queue.Empty:
                break
        last_progress = None
        for e in batch:
            if e["type"] == "progress":
                last_progress = e
                continue
            if last_progress:
                yield _sse(last_progress)
                last_progress = None
            yield _sse(e)
            if e["type"] in ("done", "error"):
                return
        if last_progress:
            yield _sse(last_progress)


def job_router(store: JobStore) -> APIRouter:
    """GET /api/jobs, GET /api/jobs/{id}, POST /api/jobs/{id}/stop and the
    event stream, for one store."""
    router = APIRouter()

    def _job(job_id: str) -> Job:
        job = store.get(job_id)
        if not job:
            raise HTTPException(404, "no such job")
        return job

    @router.get("/api/jobs")
    def list_jobs():
        return [
            j.summary() for j in sorted(store.jobs.values(), key=lambda j: -j.started)
        ]

    @router.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = _job(job_id)
        return {
            "id": job.id,
            "kind": job.kind,
            "status": job.status,
            "error": job.error,
            "result": job.result,
        }

    @router.post("/api/jobs/{job_id}/stop")
    def stop_job(job_id: str):
        _job(job_id).stop()
        return {"ok": True}

    @router.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str):
        job = _job(job_id)
        return StreamingResponse(
            event_stream(job),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


async def readable_validation_error(request: Request, exc: Exception):
    """A 422 whose detail is one line ("min_mb: Input should be a valid
    number"), so the page's toast can show it as is. Register with
    app.add_exception_handler(RequestValidationError, readable_validation_error)."""
    parts = []
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    for e in errors:
        where = [str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path")]
        parts.append((where[-1] + ": " if where else "") + str(e.get("msg", "")))
    return JSONResponse(status_code=422, content={"detail": "; ".join(parts)})


async def revalidate(request: Request, call_next):
    """Ask the hub's WebKit to check back before reusing a file; without a
    header it guesses and can keep an old script for hours after an edit.
    Register with app.middleware("http")(revalidate)."""
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-cache")
    return response
