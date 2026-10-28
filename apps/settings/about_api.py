"""The About card's backend: version, edition, licence and the support report.

A thin layer over three shared modules, so the release launcher and any
other app get the same answers:

- `shared/forge_edition.py` (editions registry `forge_editions.json` plus the
  licence file) gives one dict with everything the card shows.
- `shared/forge_licence.py` checks a licence file offline and installs it
  (a bad one is refused and nothing is written) or moves it aside.
- `shared/forge_diag.py` writes a new, scrubbed support report zip to
  Downloads.

Every route needs the System guards (X-Forge: 1 and a local Host). Adding or
removing a licence changes Forge, so the Business lock refuses it with 423
while it is shut; making a report only writes a new file, so it is allowed.
The editions are declared, not enforced: nothing here switches a feature off.
"""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, HTTPException

import forge_diag
import forge_edition
import forge_licence
import forge_lock

MAX_LICENCE_BYTES = 16_384


def make_router(guards: list, look_locks: Callable[[], bool]) -> APIRouter:
    """The /api/about routes, behind the caller's guards and lock rule."""
    router = APIRouter(prefix="/api/about", dependencies=guards)

    def reply(**extra) -> dict:
        return {**forge_edition.describe(), **extra}

    @router.get("")
    def about() -> dict:
        return reply()

    @router.post("/licence")
    def add_licence(payload: dict) -> dict:
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(400, "That file is empty.")
        try:
            size = len(text.encode("utf-8"))
        except UnicodeEncodeError:
            raise HTTPException(400, "That file is not plain text.")
        if size > MAX_LICENCE_BYTES:
            raise HTTPException(400, "That file is too big to be a Forge licence.")
        forge_lock.check(look_locks())
        result = forge_licence.install(text)
        if result["state"] == "invalid":
            raise HTTPException(
                400, f"Not added: this licence file is not valid ({result['reason']})."
            )
        return reply(added=True)

    @router.post("/licence/remove")
    def remove_licence() -> dict:
        forge_lock.check(look_locks())
        moved = forge_licence.remove()
        return reply(moved_to=moved.name if moved else None)

    @router.post("/report")
    def support_report() -> dict:
        try:
            path = forge_diag.make()
        except (forge_diag.DiagError, OSError) as error:
            raise HTTPException(500, f"The report could not be made: {error}")
        return {
            "name": path.name,
            "folder": str(path.parent),
            "bytes": path.stat().st_size,
        }

    return router
