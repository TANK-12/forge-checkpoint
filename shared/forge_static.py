#!/usr/bin/env python3
"""Forge's static server: one small stdlib process per static app.

WHAT THIS IS
    Apps of kind "static" (see forge_kinds.py) are built web pages with no
    backend of their own: Excalidraw, BentoPDF, EmulatorJS. forge.py starts
    this server for each one on the app's own port, so each page has its own
    origin and so its own browser storage. Stdlib only: no venv, about 15 MB.

    Besides the files it adds a tiny save-to-disk API under /forge-files/ so
    a page can keep copies in the app's data folder, outside the browser:

        GET    /forge-files/            the saved files: [{name, size, mtime}]
        GET    /forge-files/<name>      one file (HEAD gives its size)
        PUT    /forge-files/<name>      save the request body as <name>
        DELETE /forge-files/<name>      move it to the trash (gio trash)

    Names are one file name as people write them ("Zelda, The (USA) [!].nes",
    accents and all): no folders, no leading dot, no control characters, at
    most NAME_MAX bytes. PUT /forge-files/<name>?new never replaces a file:
    when the name is taken it saves as "name (2).ext" (then 3, 4, ...) and
    answers with the name it used.

    It listens on 127.0.0.1 only and answers 421 to a Host that is not this
    laptop (DNS rebinding). A change (PUT, POST, DELETE), and anything under
    /forge-files/, must come from the app's own page: another Origin, even
    another port on this laptop or "null", gets 403, and so does a request
    from another site or port (Sec-Fetch-Site) that is not a page load; the
    saved files are never opened as a page from elsewhere, and are served
    sandboxed, so a saved .html or .svg cannot act as the app.

    --spa (manifest "spa": true) is for one-page apps that route by path
    (IT-Tools' /json-viewer): a path with no file and no dot in its last
    part gets index.html, so a reload or a deep link opens the page.

    --shared DIR (manifest "shared": true) also serves Forge's shared/
    folder at /shared/, as every uvicorn app does, so a Forge-built page
    with no backend (Focus) can use the kit: forge.css, forge.js, the
    guard-free helpers. Its folders are never listed.

RUN
    python3 forge_static.py --root DIR --port N [--data DIR] [--spa]
                            [--shared DIR] [--header "Name: value"]...
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forge_guard import LOCAL_HOSTS, SAFE_METHODS, host_of  # noqa: E402

MAX_SAVE = 200 * 1024 * 1024
NAME_MAX = 240  # bytes; leaves room for the ".<name>.part" file under 255
FILES = "/forge-files/"

for ext, kind in {
    ".wasm": "application/wasm",
    ".mjs": "text/javascript",
    ".js": "text/javascript",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".webmanifest": "application/manifest+json",
    ".data": "application/octet-stream",
    ".7z": "application/octet-stream",
    ".woff2": "font/woff2",
}.items():
    mimetypes.add_type(kind, ext)


def plain_name(name: str) -> bool:
    """One file name in the data folder: no folder parts, not hidden."""
    return (
        bool(name)
        and not name.startswith(".")
        and "/" not in name
        and "\\" not in name
        and not any(ord(c) < 32 or ord(c) == 127 for c in name)
        and len(name.encode("utf-8", "surrogateescape")) <= NAME_MAX
    )


def safe_name(raw: str) -> str | None:
    name = unquote(raw)
    return name if plain_name(name) else None


def free_names(name: str):
    """name, then "stem (2).ext", "stem (3).ext" ... while they are plain
    names, for a save that must not replace anything."""
    yield name
    stem, dot, ext = name.rpartition(".")
    if not stem:  # no extension, or only a leading one
        stem, dot, ext = name, "", ""
    for n in range(2, 1000):
        candidate = f"{stem} ({n}){dot}{ext}"
        if plain_name(candidate):
            yield candidate


def listing(data: Path) -> list[dict]:
    if not data.is_dir():
        return []
    out = []
    for p in sorted(data.iterdir()):
        if p.is_file() and plain_name(p.name):
            st = p.stat()
            out.append({"name": p.name, "size": st.st_size, "mtime": st.st_mtime})
    return out


def under_shared(path: str) -> bool:
    bare = urlsplit(path).path
    return bare == "/shared" or bare.startswith("/shared/")


def make_handler(
    root: Path,
    data: Path,
    headers: list[tuple[str, str]],
    spa: bool = False,
    shared: Path | None = None,
):
    class Handler(SimpleHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def log_message(self, format, *args):  # quiet: one line per error only
            if len(args) > 1 and str(args[1])[:1] in ("4", "5"):
                sys.stderr.write("%s\n" % (format % args))

        sandboxed = False

        def translate_path(self, path: str) -> str:
            """/shared/... from Forge's shared folder when --shared names it;
            the parent class drops any ".." on the way, as for the app's own
            files, and a link that leads out of the folder is answered as
            missing."""
            if shared is None or not under_shared(path):
                return super().translate_path(path)
            self.directory = str(shared)
            try:
                local = super().translate_path(path[len("/shared") :] or "/")
            finally:
                self.directory = str(root)
            home = os.path.realpath(shared)
            real = os.path.realpath(local)
            if real != home and not real.startswith(home + os.sep):
                return os.path.join(home, ".forge-no-such-file")
            return local

        def list_directory(self, path):
            if shared is not None and under_shared(self.path):
                self.send_error(404, "no listing here")
                return None
            return super().list_directory(path)

        def end_headers(self):
            if self.sandboxed:
                # a saved file opened as a page is its own null origin
                self.send_header("Content-Security-Policy", "sandbox")
                self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in headers:
                self.send_header(key, value)
            if self.path.endswith((".html", "/")):
                self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def _send(self, code: int, body: bytes, kind: str = "application/json"):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, value) -> None:
            self._send(code, json.dumps(value).encode())

        def parse_request(self) -> bool:
            """forge_guard's two rules, before any do_* method runs."""
            if not super().parse_request():
                return False
            self.sandboxed = False  # one connection can carry many requests
            refuse = self._refusal()
            if refuse is None:
                return True
            self.close_connection = True  # its body, if any, is left unread
            self._json(refuse[0], {"error": refuse[1]})
            return False

        def _refusal(self) -> tuple[int, str] | None:
            host = self.headers.get("Host", "")
            if host_of(host) not in LOCAL_HOSTS:
                return 421, "not a local address"
            path = urlsplit(self.path).path
            files = path.startswith(FILES) or path == FILES.rstrip("/")
            if self.command in SAFE_METHODS and not files:
                return None  # the app's own files: a page load from anywhere
            origin = self.headers.get("Origin")
            if origin is not None and origin.lower() != "http://" + host.lower():
                return 403, "not from this app's own page"
            site = self.headers.get("Sec-Fetch-Site", "")
            mode = self.headers.get("Sec-Fetch-Mode", "")
            if site in ("cross-site", "same-site") and (files or mode != "navigate"):
                return 403, "not from this app's own page"
            return None

        def _spa_path(self) -> None:
            """A one-page app's route (no such file, no dot in the last
            part) is answered with its index.html."""
            if not spa:
                return
            parts = urlsplit(self.path)
            last = parts.path.rsplit("/", 1)[-1]
            if "." in last or os.path.exists(self.translate_path(self.path)):
                return
            self.path = "/" + (f"?{parts.query}" if parts.query else "")

        def _file_name(self) -> str | None:
            return safe_name(urlsplit(self.path).path[len(FILES) :])

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == FILES or path == FILES.rstrip("/"):
                return self._json(200, listing(data))
            if path.startswith(FILES):
                name = self._file_name()
                target = data / name if name else None
                if not target or not target.is_file():
                    return self._json(404, {"error": "no such file"})
                kind = (
                    mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                )
                self.sandboxed = True
                return self._send(200, target.read_bytes(), kind)
            self._spa_path()
            if self._send_brotli():
                return None
            return super().do_GET()

        def _send_brotli(self) -> bool:
            """A built site that ships file.br beside file (BentoPDF does, for
            its large WebAssembly) gets the small copy when the browser takes
            brotli: the same bytes once unpacked, far fewer to read."""
            if "br" not in (self.headers.get("Accept-Encoding") or ""):
                return False
            local = self.translate_path(self.path)
            if os.path.isdir(local):
                local = os.path.join(local, "index.html")
            packed = local + ".br"
            if not (os.path.isfile(local) and os.path.isfile(packed)):
                return False
            body = Path(packed).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(local))
            self.send_header("Content-Encoding", "br")
            self.send_header("Vary", "Accept-Encoding")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True

        def do_HEAD(self):
            """EmulatorJS asks a file's size before fetching it."""
            path = urlsplit(self.path).path
            if not path.startswith(FILES):
                self._spa_path()
                return super().do_HEAD()
            name = self._file_name()
            target = data / name if name else None
            self.send_response(200 if target and target.is_file() else 404)
            if target and target.is_file():
                kind = mimetypes.guess_type(target.name)[0]
                self.send_header("Content-Type", kind or "application/octet-stream")
                self.send_header("Content-Length", str(target.stat().st_size))
            else:
                self.send_header("Content-Length", "0")
            self.end_headers()

        def do_PUT(self):
            if not urlsplit(self.path).path.startswith(FILES):
                return self._json(405, {"error": "only /forge-files/ takes uploads"})
            name = self._file_name()
            if not name:
                return self._json(400, {"error": "a plain file name is needed"})
            try:
                size = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                size = -1
            if size < 0 or size > MAX_SAVE:
                return self._json(413, {"error": "too big or no length"})
            body = self.rfile.read(size)
            data.mkdir(parents=True, exist_ok=True)
            tmp = data / f".{name}.part"
            tmp.write_bytes(body)
            if "new" not in parse_qs(urlsplit(self.path).query, True):
                os.replace(tmp, data / name)
                return self._json(200, {"saved": name, "size": size})
            for free in free_names(name):
                try:
                    os.link(tmp, data / free)  # fails when the name is taken
                except FileExistsError:
                    continue
                tmp.unlink()
                return self._json(200, {"saved": free, "size": size})
            tmp.unlink()
            return self._json(409, {"error": "no free name left"})

        do_POST = do_PUT

        def do_DELETE(self):
            name = self._file_name() if self.path.startswith(FILES) else None
            target = data / name if name else None
            if not target or not target.is_file():
                return self._json(404, {"error": "no such file"})
            done = subprocess.run(
                ["gio", "trash", str(target)], capture_output=True, text=True
            )
            if done.returncode != 0:
                return self._json(500, {"error": done.stderr.strip() or "trash failed"})
            return self._json(200, {"trashed": name})

    return Handler


def parse_header(text: str) -> tuple[str, str]:
    key, _, value = text.partition(":")
    if not key.strip() or not value.strip():
        raise argparse.ArgumentTypeError(f"not 'Name: value': {text!r}")
    return key.strip(), value.strip()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Forge static server")
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--port", required=True, type=int)
    ap.add_argument("--data", type=Path, default=None)
    ap.add_argument("--header", action="append", type=parse_header, default=[])
    ap.add_argument("--spa", action="store_true", help="index.html for app routes")
    ap.add_argument("--shared", type=Path, default=None, help="served at /shared/")
    args = ap.parse_args(argv)
    data = args.data or (args.root / ".forge-files")
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(args.root, data, args.header, args.spa, args.shared),
    )
    server.daemon_threads = True
    print(f"[forge_static] {args.root} on http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
