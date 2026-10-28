"""Auto-close: his RAM and idle rules per app, which the RAM guard service
(apps/power/ram_guard.py) applies. The rules and the guard's status live in
shared/forge_autoclose.py; this panel only reads and saves them."""

from __future__ import annotations

import forge_autoclose  # shared/, on sys.path through web_app.py

from . import fields
from .runner import Run


def status(run: Run) -> dict:
    registry = forge_autoclose.load_registry()
    return dict(forge_autoclose.describe(registry), available=True)


def rule(body: dict, run: Run) -> dict:
    name = fields.text(body, "name")
    change = body.get("change")
    if not isinstance(change, dict) or not change:
        raise ValueError("change must list what to set")
    forge_autoclose.save_rule(forge_autoclose.load_registry(), name, change)
    return {"saved": name}


def reset(body: dict, run: Run) -> dict:
    name = fields.text(body, "name")
    forge_autoclose.save_rule(forge_autoclose.load_registry(), name, None)
    return {"reset": name}


ACTIONS = {"rule": rule, "reset": reset}
