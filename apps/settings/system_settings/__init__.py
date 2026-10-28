"""The System section of Settings: one module per panel, listed in panels.json.
(Moved here from the Claude app on 2026-10-19.)

    panels()                    [{id, label, icon, about, keywords}] in page order
    status(panel_id)            what the panel shows now
    act(panel_id, action, body) change something, then the fresh status

Each panel module has status(run) -> dict and ACTIONS {name: fn(body, run)}.
Actions raise ValueError for a bad request and runner.CommandFailed when the
system tool refused.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from . import runner

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "panels.json"


def panels() -> list[dict]:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return [
        {
            k: p[k]
            for k in ("id", "label", "icon", "about", "keywords", "reset")
            if k in p
        }
        for p in data["panels"]
    ]


def module(panel_id: str):
    if panel_id not in {p["id"] for p in panels()}:
        raise KeyError(panel_id)
    return importlib.import_module(f"{__name__}.{panel_id}")


def status(panel_id: str, run: runner.Run | None = None) -> dict:
    return module(panel_id).status(run or runner.run)


def act(panel_id: str, action: str, body: dict, run: runner.Run | None = None) -> dict:
    run = run or runner.run
    mod = module(panel_id)
    fn = mod.ACTIONS.get(action)
    if fn is None:
        raise KeyError(f"{panel_id}/{action}")
    if not isinstance(body, dict):
        raise ValueError("send a JSON object")
    said = fn(body, run) or {}
    return dict(mod.status(run), done=said)
