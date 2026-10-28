"""Keep a Forge backend answering only its own pages.

Every Forge backend listens on 127.0.0.1, but a web page anywhere can still
reach it: a cross-site form post needs no permission from the browser, and
DNS rebinding lets a page read replies under a host name of its own.
`LocalOnly` is an ASGI middleware (app.add_middleware(LocalOnly)) that

- answers 421 to a request whose Host is not 127.0.0.1, localhost or [::1]
  (any port), so a rebound name reads nothing
- answers 403 to a request that changes something (anything but GET, HEAD
  and OPTIONS) when it carries an Origin from anywhere else

Requests with no Origin (curl, the Forge window's own navigation) pass.
Tests must use TestClient(app, base_url="http://127.0.0.1").
"""

from __future__ import annotations

from urllib.parse import urlsplit

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def host_of(value: str) -> str:
    """The bare host of a Host header or an Origin URL, lower case."""
    if "//" not in value:
        value = "//" + value
    try:
        return (urlsplit(value).hostname or "").lower()
    except ValueError:
        return ""


class LocalOnly:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = {
                k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]
            }
            if host_of(headers.get("host", "")) not in LOCAL_HOSTS:
                return await self.refuse(scope, send, 421, "not a local address")
            origin = headers.get("origin")
            unsafe = scope["type"] == "websocket" or scope["method"] not in SAFE_METHODS
            if unsafe and origin and host_of(origin) not in LOCAL_HOSTS:
                return await self.refuse(scope, send, 403, "another site asked")
        await self.app(scope, receive, send)

    @staticmethod
    async def refuse(scope, send, status: int, why: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = ('{"detail": "%s"}' % why).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
