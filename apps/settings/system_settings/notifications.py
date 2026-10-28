"""Notifications: do not disturb, which is GNOME's show-banners turned off."""

from __future__ import annotations

from . import fields
from .runner import Run, must

SCHEMA = "org.gnome.desktop.notifications"


def status(run: Run) -> dict:
    shown = run(["gsettings", "get", SCHEMA, "show-banners"], timeout=5)
    banners = shown.out.strip()
    if not shown.ok or banners not in ("true", "false"):
        return {"available": False, "why": shown.text() or "not a GNOME session"}
    lock = run(["gsettings", "get", SCHEMA, "show-in-lock-screen"], timeout=5)
    return {
        "available": True,
        "dnd": banners == "false",
        "lock_screen": lock.out.strip() == "true" if lock.ok else None,
    }


def dnd(body: dict, run: Run) -> dict:
    on = fields.flag(body, "on")
    must(
        run(["gsettings", "set", SCHEMA, "show-banners", "false" if on else "true"]),
        "could not switch do not disturb",
    )
    return {"dnd": on}


def lock_screen(body: dict, run: Run) -> dict:
    on = fields.flag(body, "on")
    must(
        run(
            [
                "gsettings",
                "set",
                SCHEMA,
                "show-in-lock-screen",
                "true" if on else "false",
            ]
        ),
        "could not change it",
    )
    return {"lock_screen": on}


def defaults(body: dict, run: Run) -> dict:
    """Banners on (do not disturb off) and on the lock screen, GNOME's own."""
    for key in ("show-banners", "show-in-lock-screen"):
        must(run(["gsettings", "reset", SCHEMA, key], timeout=5), "could not reset it")
    return {"reset": "notifications"}


ACTIONS = {"dnd": dnd, "lock_screen": lock_screen, "defaults": defaults}
