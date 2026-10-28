"""Make the hub's browser check back before it reuses an app's files.

Without a Cache-Control header, browsers (the hub's WebKit, headless Chrome)
guess how long a file stays fresh from its Last-Modified date, and kept
running a days-old script for hours after an update: Cutroom's logic.js
beside a new app.js (relay task 166), PixelForge's editor_state.js beside a
new index.html (2026-10-20). "no-cache" does not stop caching; it makes the
browser ask first, and the answer is a quick 304 when nothing changed.

Every FastAPI app adds it with one line after making its app:

    import forge_revalidate
    forge_revalidate.revalidate(app)

A response that sets its own Cache-Control (a sprite sheet kept for a day,
a stream marked no-store) keeps it. `skip` lists path prefixes left alone.
About ten apps carry their own copy of this middleware; they can switch to
this one whenever they are next edited.
"""

from __future__ import annotations

from typing import Iterable


def revalidate(app, skip: Iterable[str] = ()):
    """Add the middleware to a FastAPI/Starlette `app`; returns the app."""
    prefixes = tuple(skip)

    @app.middleware("http")
    async def forge_revalidate(request, call_next):
        response = await call_next(request)
        if not (prefixes and request.url.path.startswith(prefixes)):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    return app
