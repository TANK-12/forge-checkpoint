"""Runs one app's backend for the release launcher (forge_portable.py).

    python forge_serve.py web_app:app --port 8441     (from the app's folder)

The same as `python -m uvicorn web_app:app --host 127.0.0.1 --port 8441`,
with two guards a release needs:

- Only requests addressed to this machine by name are answered: the Host
  header must be 127.0.0.1, localhost or [::1]. A web page that points its own
  domain at 127.0.0.1 (DNS rebinding) still sends its own name, so it gets a
  403 instead of driving an app (Terminal's shell, Settings' folders).
- A change (any method but GET, HEAD and OPTIONS, and every WebSocket) is
  taken only from a page on this machine. Another site's page may post a
  form or a plain-text fetch to 127.0.0.1 without asking first, and FastAPI
  reads a JSON body whatever its Content-Type, so a foreign Origin gets a 403.
- The backend ends when the launcher that started it has gone, even when the
  launcher was killed outright: it watches $FORGE_PARENT_PID.

forge_core.AppManager(guard=True) starts backends this way; forge.py's own
backends still run plain uvicorn. Standard library apart from uvicorn.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import threading
import time

LOCAL_NAMES = ("127.0.0.1", "localhost", "[::1]")
# A page on this machine, as a browser names it in the Origin header.
LOCAL_ORIGIN = re.compile(r"http://(127\.0\.0\.1|localhost|\[::1\])(:\d{1,5})?")
# What any page may ask of any site; CORS keeps the answer from a foreign one.
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
REFUSED = b"Forge answers only to this machine."
CROSS_SITE = b"Forge takes changes only from its own pages."
# Pages of this machine may show a backend's pages in a frame (the hub frames
# every app); another site's page may not, so it cannot put an app under a
# decoy and have it clicked. CSP has no way to write [::1] here.
FRAME_RULE = "frame-ancestors 'self' http://127.0.0.1:* http://localhost:*"


def header(scope: dict, name: bytes) -> str | None:
    """A request header's value, or None when it was not sent."""
    for key, value in scope.get("headers") or []:
        if key == name:
            return value.decode("latin-1")
    return None


def host_name(host: str) -> str:
    """The name part of a Host header: 'localhost:8441' -> 'localhost'."""
    host = host.strip().lower()
    if host.startswith("["):
        return host[: host.find("]") + 1] if "]" in host else host
    return host.split(":", 1)[0]


def cross_site(scope: dict) -> bool:
    """Whether a page on another site sent this change. Browsers name the
    page in Origin ("null" for sandboxed and file pages); a request without
    one passes unless Sec-Fetch-Site says cross-site, since programs (the
    launcher, curl) send neither."""
    if scope["type"] == "http" and scope.get("method", "GET") in SAFE_METHODS:
        return False
    origin = header(scope, b"origin")
    if origin is not None:
        return not LOCAL_ORIGIN.fullmatch(origin.strip().lower())
    return (header(scope, b"sec-fetch-site") or "").strip().lower() == "cross-site"


async def refuse(scope, receive, send, why: bytes) -> None:
    """A 403 saying `why`; a WebSocket is closed with 1008 (policy) instead."""
    if scope["type"] == "websocket":
        await receive()  # websocket.connect
        await send({"type": "websocket.close", "code": 1008})
        return
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(why)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": why})


def framed(send):
    """`send` with FRAME_RULE added to each HTTP answer's headers."""

    async def send_framed(message):
        if message["type"] == "http.response.start":
            headers = list(message.get("headers") or [])
            headers.append((b"content-security-policy", FRAME_RULE.encode()))
            message = {**message, "headers": headers}
        await send(message)

    return send_framed


class HostGuard:
    """ASGI middleware: refuses HTTP and WebSocket requests whose Host is not
    this machine's own name, and changes sent from another site's page, and
    tells the browser no other site may frame what it answers; everything
    else (lifespan) passes through."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            send = framed(send)
        if scope["type"] in ("http", "websocket"):
            if host_name(header(scope, b"host") or "") not in LOCAL_NAMES:
                return await refuse(scope, receive, send, REFUSED)
            if cross_site(scope):
                return await refuse(scope, receive, send, CROSS_SITE)
        await self.app(scope, receive, send)


def end_self() -> None:
    """What the launcher's own stop does: this backend and its helpers end."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(os.getpid())],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        os._exit(0)
    try:
        if os.getpgid(0) == os.getpid():
            os.killpg(os.getpid(), signal.SIGTERM)  # its own group: helpers too
        else:
            os.kill(os.getpid(), signal.SIGTERM)  # never the starter's group
    except OSError:
        os.kill(os.getpid(), signal.SIGTERM)
    time.sleep(5)  # uvicorn's own shutdown normally ends the process first
    os._exit(0)


def watch_parent(pid: int, every: float = 1.0) -> None:
    """Returns once process `pid` has ended."""
    if os.name == "nt":
        import ctypes

        kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            if getattr(ctypes, "get_last_error")() == 87:  # no such process
                return
            threading.Event().wait()  # cannot watch it: never end because of it
        kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)  # INFINITE
        kernel32.CloseHandle(handle)
        return
    if os.getppid() == pid:
        # A child whose parent ends is handed to another parent.
        while os.getppid() == pid:
            time.sleep(every)
        return
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        time.sleep(every)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Forge app's backend.")
    parser.add_argument("app", help="module:attribute, as uvicorn takes it")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    # As `python -m uvicorn` run from the app's folder: its modules come first.
    sys.path[0] = os.getcwd()
    import uvicorn
    from uvicorn.importer import import_from_string

    parent = os.environ.get("FORGE_PARENT_PID", "")
    if parent.isdigit():

        def watch() -> None:
            watch_parent(int(parent))
            end_self()

        threading.Thread(target=watch, name="forge-parent", daemon=True).start()
    app = HostGuard(import_from_string(args.app))
    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
