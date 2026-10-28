"""The work queue: set it going and leave it.

A bulk run is meant to be started and forgotten for twelve hours, which means
it has to survive things going wrong. The queue lives on disk, not in memory,
so closing the app or losing power costs at most the subject that was mid-flight
- everything already researched is already merged and saved. On restart,
anything left marked `running` is put back to `queued` and picked up again.

There are several queues, and one of them is active. Workers only ever pull
from the active queue, so a list of companies can sit untouched while a list of
world leaders runs, and switching between them is one click. Each queue
remembers two things of its own across a shutdown: whether it is **paused**,
and whether it is allowed to **redo subjects already held**.

That second flag is the one that stops work being repeated. It is enforced when
a job actually comes up to run, not only when it was queued, because a subject
can arrive in the library between those two moments - researched by an earlier
queue, or by hand.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from pathlib import Path

import dossier
import store
from research import seeds
from research import images as images_mod
from research import speech as speech_mod
from research.fetcher import now_iso
from research.pipeline import research

QUEUE_FILE = "queue.json"
BACKUP_SUFFIX = ".v1-backup"
FORMAT_VERSION = 2
DEFAULT_QUEUE_NAME = "First run"
MAX_ERRORS_LOGGED = 40

# Where a job ends up. `skipped` means the subject was already held and the
# queue was not allowed to redo it - no work was done and nothing failed.
STATUS_ORDER = {"running": 0, "queued": 1, "failed": 2, "skipped": 3, "done": 4}


def _incomplete(job: dict) -> str:
    """Why a finished deep dive holds fewer claims than it should, or ''."""
    report = job.get("report") or {}
    if (
        job.get("status") != "done"
        or report.get("phase") != "deep"
        or report.get("claims_complete", True)
    ):
        return ""
    why = [
        n
        for n in report.get("notes") or []
        if n.startswith(("Jan", "Claim extraction"))
    ]
    return "finished without all its claims: " + (
        why[-1] if why else "claim extraction did not complete"
    )


# How many subjects are researched at once. Each subject is overwhelmingly
# waiting on the network - it already fetches its own sources in parallel - so
# several at a time costs little CPU and multiplies throughput. The models are
# a shared resource behind their own small semaphore, so this does not let LLM
# work run away.
WORKERS = int(os.environ.get("DOSSIER_QUEUE_WORKERS", "4"))


def new_queue(name: str, redo_held: bool = False) -> dict:
    return {
        "id": uuid.uuid4().hex[:10],
        "name": name or "Untitled queue",
        "created": now_iso(),
        "paused": False,
        "redo_held": bool(redo_held),
        "jobs": [],
    }


class ResearchQueue:
    def __init__(self, root: Path | None = None):
        self.root = root
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # The memory guard's hold is deliberately separate from the user's
        # pause. The guard pauses when the machine runs short of memory and
        # lifts it again later; if that shared one flag, lifting the guard's
        # hold would silently undo a pause the user meant to stick.
        self._guard_hold = threading.Event()
        self.log_lines: list[str] = []
        self.current: dict | None = None
        self._running: dict[int, dict] = {}
        self._idle_since: float | None = None
        self._threads: list[threading.Thread] = []
        self._queues: list[dict] = []
        self._active: str = ""
        self._load()

    # --- persistence -----------------------------------------------------

    @property
    def path(self) -> Path:
        return (self.root or store.data_root().path) / QUEUE_FILE

    def _load(self):
        data = store.read_json(self.path, None)
        if not data:
            self._queues = [new_queue(DEFAULT_QUEUE_NAME)]
            self._active = self._queues[0]["id"]
            return

        if "queues" in data:
            self._queues = data.get("queues") or []
            self._active = data.get("active") or ""
        else:
            # The original format: one flat list of jobs and nothing else.
            # Fold it into a single queue, keeping every job exactly as it is,
            # and keep a copy of the old file first - a long bulk run is a lot
            # of work to have riding on a migration.
            self._backup_v1()
            first = new_queue(DEFAULT_QUEUE_NAME)
            first["jobs"] = data.get("jobs") or []
            self._queues = [first]
            self._active = first["id"]

        if not self._queues:
            self._queues = [new_queue(DEFAULT_QUEUE_NAME)]
        if not any(q.get("id") == self._active for q in self._queues):
            self._active = self._queues[0]["id"]

        for q in self._queues:
            q.setdefault("id", uuid.uuid4().hex[:10])
            q.setdefault("name", DEFAULT_QUEUE_NAME)
            q.setdefault("created", now_iso())
            q.setdefault("paused", False)
            q.setdefault("redo_held", False)
            q.setdefault("jobs", [])
            # A job that was running when the process died never finished.
            for job in q["jobs"]:
                if job.get("status") == "running":
                    job["status"] = "queued"
                    job["note"] = "restarted after the app was closed mid-job"

    def _backup_v1(self):
        """Keep the pre-migration file. Never overwrite an existing backup."""
        target = self.path.with_name(self.path.name + BACKUP_SUFFIX)
        if target.exists() or not self.path.exists():
            return
        try:
            shutil.copy2(self.path, target)
        except OSError as e:
            # Worth saying out loud, but not worth refusing to start over.
            print(f"[dossier] could not back up {self.path}: {e}", flush=True)

    def _save(self):
        store.write_json(
            self.path,
            {
                "version": FORMAT_VERSION,
                "active": self._active,
                "queues": self._queues,
                "saved": now_iso(),
            },
        )

    # --- which queue is active -------------------------------------------

    @property
    def active(self) -> dict:
        for q in self._queues:
            if q["id"] == self._active:
                return q
        self._active = self._queues[0]["id"]
        return self._queues[0]

    @property
    def jobs(self) -> list[dict]:
        """The active queue's jobs. Everything below works against this."""
        return self.active["jobs"]

    @jobs.setter
    def jobs(self, rows: list[dict]):
        self.active["jobs"] = rows

    def queues(self) -> list[dict]:
        """One summary row per queue, for the picker."""
        with self._lock:
            out = []
            for q in self._queues:
                counts: dict[str, int] = {}
                for job in q["jobs"]:
                    counts[job["status"]] = counts.get(job["status"], 0) + 1
                out.append(
                    {
                        "id": q["id"],
                        "name": q["name"],
                        "created": q["created"],
                        "paused": q["paused"],
                        "redo_held": q["redo_held"],
                        "active": q["id"] == self._active,
                        "total": len(q["jobs"]),
                        "counts": counts,
                        "waiting": counts.get("queued", 0),
                    }
                )
            return out

    def create_queue(self, name: str, redo_held: bool = False) -> dict:
        with self._lock:
            q = new_queue(name, redo_held)
            self._queues.append(q)
            self._save()
            return q

    def activate(self, queue_id: str) -> bool:
        with self._lock:
            if not any(q["id"] == queue_id for q in self._queues):
                return False
            self._active = queue_id
            self._save()
            return True

    def rename(self, queue_id: str, name: str) -> bool:
        with self._lock:
            for q in self._queues:
                if q["id"] == queue_id:
                    q["name"] = name.strip() or q["name"]
                    self._save()
                    return True
            return False

    def set_redo(self, queue_id: str, redo: bool) -> bool:
        with self._lock:
            for q in self._queues:
                if q["id"] == queue_id:
                    q["redo_held"] = bool(redo)
                    self._save()
                    return True
            return False

    def delete_queue(self, queue_id: str) -> bool:
        """Remove a queue. The last one is never deleted - there has to be
        somewhere for new work to go."""
        with self._lock:
            if len(self._queues) <= 1:
                return False
            remaining = [q for q in self._queues if q["id"] != queue_id]
            if len(remaining) == len(self._queues):
                return False
            self._queues = remaining
            if self._active == queue_id:
                self._active = self._queues[0]["id"]
            self._save()
            return True

    # --- adding work -----------------------------------------------------

    def add_job(
        self,
        name: str,
        entity_type: str = "person",
        phase: str = "quick",
        qid: str = "",
        prominence: int = 0,
        country: str = "",
    ) -> tuple[dict, bool]:
        """Queue one subject. Returns (job, created).

        `created` is False when this subject is already in the active queue for
        this phase, so a caller can report what it actually added rather than
        what it was asked to add. Failed jobs deliberately do not count as
        already-present: re-queueing a recipe is how a failure gets retried.
        """
        slug = store.slugify(name)
        settled = ("queued", "running", "done", "skipped")
        with self._lock:
            for job in self.jobs:
                if (
                    job["slug"] == slug
                    and job["phase"] == phase
                    and job["status"] in settled
                ):
                    return job, False
            job = {
                "id": uuid.uuid4().hex[:10],
                "name": name,
                "slug": slug,
                "entity_type": entity_type,
                "phase": phase,
                "qid": qid,
                "prominence": prominence,
                "country": country,
                "status": "queued",
                "added": now_iso(),
                "started": "",
                "finished": "",
                "seconds": 0.0,
                "error": "",
                "note": "",
                "changes": {},
            }
            self.jobs.append(job)
            self._save()
        return job, True

    def add(self, *args, **kwargs) -> dict:
        """Queue one subject, returning the job. See `add_job` for whether it
        was actually created."""
        job, _created = self.add_job(*args, **kwargs)
        return job

    def add_recipe(
        self,
        recipe: str,
        limit: int = 100,
        phase: str = "quick",
        skip_existing: bool | None = None,
    ) -> dict:
        """Seed a whole recipe into the active queue.

        `skip_existing` defaults to the queue's own setting, so the one tickbox
        governs both seeding and running rather than two controls disagreeing.
        """
        if skip_existing is None:
            skip_existing = not self.active.get("redo_held", False)
        rows = seeds.run_recipe(recipe, limit=limit)
        added = already_held = already_queued = 0
        for row in rows:
            if skip_existing and dossier.exists(store.slugify(row["name"]), self.root):
                already_held += 1
                continue
            _job, created = self.add_job(
                row["name"],
                row["entity_type"],
                phase,
                row.get("qid", ""),
                row.get("prominence", 0),
                row.get("country", ""),
            )
            if created:
                added += 1
            else:
                already_queued += 1
        return {
            "recipe": recipe,
            "found": len(rows),
            "queued": added,
            "already_held": already_held,
            "already_queued": already_queued,
            "queue": self.active["name"],
        }

    def add_deep_for_held(self, limit: int = 50, min_prominence: int = 0) -> dict:
        """Queue deep dives for subjects already in the library, best first."""
        rows = sorted(
            dossier.library(self.root),
            key=lambda r: r.get("sources", 0),
            reverse=True,
        )
        added = 0
        for row in rows:
            if row.get("depth") == "deep":
                continue
            _job, created = self.add_job(
                row["name"], row.get("entity_type", "person"), "deep"
            )
            if created:
                added += 1
            if added >= limit:
                break
        return {"queued": added, "queue": self.active["name"]}

    # --- control ---------------------------------------------------------

    def _spin_up(self):
        """Bring the pool up to strength, without touching the pause flag.

        This used to return early if any worker was alive, which quietly left
        the queue running on a single thread: a worker started while the queue
        was momentarily empty found no job, exited, and was never replaced.
        """
        with self._lock:
            self._threads = [t for t in self._threads if t.is_alive()]
            self._stop.clear()
            while len(self._threads) < WORKERS:
                t = threading.Thread(
                    target=self._run,
                    daemon=True,
                    name=f"dossier-queue-{len(self._threads)}",
                )
                t.start()
                self._threads.append(t)
            self._thread = self._threads[0] if self._threads else None

    def start(self):
        """Start working: clears the active queue's pause and brings the pool
        up. This is what the Start button and queueing new work both do."""
        with self._lock:
            self.active["paused"] = False
            self._save()
        self._spin_up()

    def pause(self, by_guard: bool = False):
        """Stop starting new subjects. In-flight ones finish either way."""
        if by_guard:
            self._guard_hold.set()
            return
        with self._lock:
            self.active["paused"] = True
            self._save()

    def resume(self, by_guard: bool = False):
        if by_guard:
            self._guard_hold.clear()
        else:
            with self._lock:
                self.active["paused"] = False
                self._save()
        self._spin_up()

    def held(self) -> bool:
        """True while nothing new should be started."""
        return self._guard_hold.is_set() or bool(self.active.get("paused"))

    def stop(self):
        self._stop.set()

    def clear_finished(self):
        with self._lock:
            self.jobs = [j for j in self.jobs if j["status"] in ("queued", "running")]
            self._save()

    def remove(self, job_id: str) -> bool:
        with self._lock:
            before = len(self.jobs)
            self.jobs = [
                j
                for j in self.jobs
                if not (j["id"] == job_id and j["status"] == "queued")
            ]
            self._save()
            return len(self.jobs) < before

    # --- work already done -----------------------------------------------

    def held_depth(self, slug: str) -> str | None:
        """How deeply this subject is already held, or None if not held."""
        if not dossier.exists(slug, self.root):
            return None
        d = store.subject_dir(slug, self.root)
        subject = store.read_json(d / dossier.FILES["subject"], {}) or {}
        return subject.get("depth", "quick")

    def _skip_reason(self, job: dict) -> str:
        """Why this job needs no work, or '' if it should run.

        A quick pass on a subject already held adds nothing worth the network
        traffic. A deep dive still does, unless the stored dossier is already
        deep - so "Deepen 25 held subjects" keeps working exactly as before.
        """
        if self.active.get("redo_held"):
            return ""
        if job["phase"] == "tour":
            # Narration is over a minute of CPU for a few minutes of audio,
            # and the recording is keyed by the script's content - so if the
            # dossier has not changed since it was read, there is nothing to do.
            if speech_mod.existing_tour(job["slug"], root=self.root):
                return "already read aloud"
            return ""
        if job["phase"] == "images":
            # An images pass is only pointless when there is nothing left to
            # fetch. It is never "already held" in the research sense.
            stored = dossier.load(job["slug"], self.root)
            refs = stored.get("images") or []
            if refs and all(i.get("stored") for i in refs):
                return "every picture already downloaded"
            return ""
        depth = self.held_depth(job["slug"])
        if depth is None:
            return ""
        if job["phase"] == "deep" and depth != "deep":
            return ""
        return f"already held ({depth} pass)"

    # --- the worker ------------------------------------------------------

    def _next(self) -> dict | None:
        with self._lock:
            skipped_any = False
            while True:
                queued = [j for j in self.jobs if j["status"] == "queued"]
                if not queued:
                    if skipped_any:
                        self._save()
                    return None
                # Most-covered subjects first, and a quick pass before any deep
                # dive, so breadth arrives before depth.
                queued.sort(
                    key=lambda j: (j["phase"] == "deep", -j.get("prominence", 0))
                )
                job = queued[0]

                reason = self._skip_reason(job)
                if reason:
                    # Not saved per skip: a long run can skip hundreds in a row
                    # and the queue file is large, so one write covers them all
                    # when the loop settles.
                    job["status"] = "skipped"
                    job["note"] = reason
                    job["finished"] = now_iso()
                    skipped_any = True
                    self._log(f"[{job['name']}] skipped - {reason}")
                    continue

                job["status"] = "running"
                job["started"] = now_iso()
                self._save()
                self._running[threading.get_ident()] = job
                self.current = job
                return job

    def _log(self, message: str):
        line = f"{time.strftime('%H:%M:%S')}  {message}"
        self.log_lines.append(line)
        del self.log_lines[:-400]

    def _run(self):
        while not self._stop.is_set():
            if self.held():
                time.sleep(1.0)
                continue
            job = self._next()
            if job is None:
                with self._lock:
                    self._running.pop(threading.get_ident(), None)
                self.current = None
                # Idle, not finished. Work arrives while the queue is running -
                # a subject added by hand, a recipe seeded - and a worker that
                # exited on an empty queue was gone for good.
                self._idle_since = self._idle_since or time.time()
                if self._stop.wait(timeout=2.0):
                    break
                continue
            self._idle_since = None
            started = time.time()
            self._log(f"[{job['name']}] {job['phase']} pass starting")
            try:
                if job["phase"] == "tour":
                    out = speech_mod.narrate(job["slug"], root=self.root)
                    if not out.get("ok"):
                        raise RuntimeError(out.get("error", "rendering failed"))
                    changes = {
                        "audio": Path(out["path"]).name,
                        "lines": len(out["script"]["lines"]),
                        "bytes": out.get("bytes", 0),
                    }
                    with self._lock:
                        job["status"] = "done"
                        job["changes"] = changes
                    self._log(
                        f"[{job['name']}] read aloud: {changes['lines']} lines, "
                        f"{changes['bytes'] // 1024}KB"
                    )
                elif job["phase"] == "images":
                    # Downloading files, not researching. No model, no sources -
                    # it runs off the picture references an earlier pass stored.
                    changes = images_mod.fetch_for(
                        job["slug"], self.root, log=lambda m: self._log(m)
                    )
                    with self._lock:
                        job["status"] = "done"
                        job["changes"] = changes
                    self._log(
                        f"[{job['name']}] pictures: +{changes['fetched']} kept, "
                        f"{changes['skipped']} already here, {changes['failed']} unavailable"
                    )
                else:
                    result = research(
                        job["name"],
                        entity_type=job["entity_type"],
                        phase=job["phase"],
                        qid=job.get("qid", ""),
                        log=lambda m: self._log(f"  {m}"),
                    )
                    changes = dossier.save(result, self.root)
                    with self._lock:
                        job["status"] = "done"
                        job["changes"] = changes
                        job["report"] = result["report"]
                    self._log(
                        f"[{job['name']}] done in {result['report']['seconds']}s: "
                        f"+{changes['sources_added']} sources, "
                        f"+{changes['claims_added']} claims, "
                        f"+{changes['timeline_added']} events"
                    )
            except Exception as e:
                with self._lock:
                    job["status"] = "failed"
                    job["error"] = f"{type(e).__name__}: {e}"[:300]
                self._log(f"[{job['name']}] FAILED - {job['error']}")
            finally:
                with self._lock:
                    self._running.pop(threading.get_ident(), None)
                    job["finished"] = now_iso()
                    job["seconds"] = round(time.time() - started, 1)
                    self._save()
                self.current = None
        self._log("worker stopped")

    # --- reporting -------------------------------------------------------

    def state(self) -> dict:
        with self._lock:
            counts = {"queued": 0, "running": 0, "done": 0, "failed": 0, "skipped": 0}
            for job in self.jobs:
                counts[job["status"]] = counts.get(job["status"], 0) + 1
            done = [j for j in self.jobs if j["status"] == "done" and j["seconds"]]

            # Estimate per phase. A deep dive takes twenty times as long as a
            # quick pass, so one deep dive in the history was enough to put the
            # estimate for forty-five quick passes out by eight hours.
            def average_for(phase: str) -> float:
                matching = [j["seconds"] for j in done if j["phase"] == phase]
                if matching:
                    return sum(matching) / len(matching)
                return sum(j["seconds"] for j in done) / len(done) if done else 0.0

            outstanding = [j for j in self.jobs if j["status"] in ("queued", "running")]
            eta = sum(average_for(j["phase"]) for j in outstanding)
            average = (
                average_for("quick")
                if outstanding
                else (sum(j["seconds"] for j in done) / len(done) if done else 0.0)
            )
            active = self.active
            return {
                "counts": counts,
                "running": any(t.is_alive() for t in self._threads),
                "workers": len([t for t in self._threads if t.is_alive()]),
                "in_flight": list(self._running.values()),
                "paused": bool(active.get("paused")),
                "guard_hold": self._guard_hold.is_set(),
                "current": self.current,
                "average_seconds": round(average, 1),
                "eta_seconds": round(eta) if eta else None,
                "log": self.log_lines[-60:],
                "queues": self.queues(),
                "active_queue": {
                    "id": active["id"],
                    "name": active["name"],
                    "redo_held": bool(active.get("redo_held")),
                },
                # A deep dive that finished without its claims is a failure the
                # user needs to see; it used to be listed as done with no error.
                "errors": [
                    {"name": j["name"], "error": j["error"] or _incomplete(j)}
                    for j in self.jobs
                    if j["status"] == "failed" or _incomplete(j)
                ][:MAX_ERRORS_LOGGED],
                "jobs": sorted(
                    self.jobs,
                    key=lambda j: (
                        STATUS_ORDER.get(j["status"], 9),
                        -j.get("prominence", 0),
                    ),
                )[:200],
            }


_queue: ResearchQueue | None = None


def get_queue() -> ResearchQueue:
    global _queue
    if _queue is None:
        _queue = ResearchQueue()
    return _queue
