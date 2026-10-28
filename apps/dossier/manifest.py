"""A plain record of where research stood, rewritten every few minutes.

The queue is already on disk and resumes after a restart. This is the part a
person reads after a crash: what was running, what had just finished, what
failed, and how to carry on. It goes to the research drive and to the laptop's
own disk, so either one surviving is enough.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import dossier
import guard
import janidle
import store

EVERY_SECONDS = 300.0
FILENAME = "dossier-manifest.json"
# $DOSSIER_LAPTOP_COPY moves it (a Forge release has no ~/Forge/outputs).
LAPTOP_COPY = Path(
    os.environ.get("DOSSIER_LAPTOP_COPY")
    or Path.home() / "Forge" / "outputs" / FILENAME
)
BUILD_NOTES = Path(__file__).resolve().parent / "WIP.md"


def snapshot(
    state: dict,
    *,
    written: str,
    data_root: str,
    subjects: int,
    jan_models: list[str],
    available_mb: int,
) -> dict:
    jobs = state.get("jobs") or []
    finished = sorted(
        (j for j in jobs if j.get("status") == "done" and j.get("finished")),
        key=lambda j: j["finished"],
        reverse=True,
    )
    active = state.get("active_queue") or {}
    return {
        "written": written,
        "data_root": data_root,
        "queue": {
            "id": active.get("id", ""),
            "name": active.get("name", ""),
            "paused": bool(state.get("paused")),
            "redo_held": bool(active.get("redo_held")),
            "counts": state.get("counts") or {},
        },
        "running": [
            {
                "name": j.get("name", ""),
                "phase": j.get("phase", ""),
                "started": j.get("started", ""),
            }
            for j in state.get("in_flight") or []
        ],
        "recently_finished": [
            {"name": j.get("name", ""), "finished": j["finished"]}
            for j in finished[:20]
        ],
        "failures": list(state.get("errors") or []),
        "library_subjects": subjects,
        "jan_models_loaded": jan_models,
        "available_memory_mb": available_mb,
        "how_to_resume": (
            f"Nothing needs rebuilding. The queue is saved at {data_root}/queue.json "
            "and every finished subject is already merged into the library. Start "
            "Dossier again: jobs that were running go back to waiting on their own, "
            "and Start on the Jobs tab carries on from there."
        ),
    }


def write(payload: dict, paths: list[Path]) -> list[Path]:
    """Write to every path that will take it; one failing never stops the rest."""
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    written = []
    for path in paths:
        tmp = path.with_name(path.name + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            continue
        written.append(path)
    return written


def write_now(queue) -> list[Path]:
    root = store.data_root().path
    snap = snapshot(
        queue.state(),
        written=time.strftime("%Y-%m-%dT%H:%M:%S"),
        data_root=str(root),
        subjects=len(dossier.library()),
        jan_models=sorted(janidle.model_ticks()),
        available_mb=guard.available_mb(),
    )
    try:
        modified = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(BUILD_NOTES.stat().st_mtime)
        )
    except OSError:
        modified = ""
    snap["build_notes"] = {"path": str(BUILD_NOTES), "modified": modified}
    return write(snap, [root / FILENAME, LAPTOP_COPY])


def watch(queue, log=print, every: float = EVERY_SECONDS) -> threading.Thread:
    """Write the manifest now, then again every `every` seconds."""

    def loop():
        while True:
            try:
                write_now(queue)
            except Exception as e:
                log(f"[dossier] manifest: {type(e).__name__}: {e}")
            time.sleep(every)

    thread = threading.Thread(target=loop, daemon=True, name="manifest")
    thread.start()
    return thread
