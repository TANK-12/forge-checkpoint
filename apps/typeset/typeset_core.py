"""Typeset: Typst documents with a live preview.

Each document is a folder in the documents folder (typeset.json docs_dir,
default ~/Documents/Typeset) holding main.typ and anything it uses
(pictures, a .bib). Typst compiles with --root set to that folder, so a
document reads nothing outside it. The preview is SVG pages in Typeset's
own cache; Export writes <name>.pdf beside main.typ.

The program is Typst, pinned in typeset.json and fetched once through
shared/forge_fetch.py (TYPESET_TYPST points at another one). New
documents start from templates/ (templates.json is the registry).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR") or ROOT.parent.parent / "shared")
sys.path.insert(0, str(SHARED_DIR))
import forge_fetch  # noqa: E402

CONFIG = Path(os.environ.get("TYPESET_CONFIG") or ROOT / "typeset.json")
TEMPLATES = ROOT / "templates"
DATA_DIR = Path(
    os.environ.get("TYPESET_DATA_DIR") or Path.home() / ".local/share/forge/typeset"
)
MAIN = "main.typ"
MAX_TEXT = 2_000_000  # characters in main.typ
BAD_NAME = re.compile(r"[/\\\x00-\x1f\x7f]")
DIAG = re.compile(r"^(?:(.+?):(\d+):(\d+): )?(error|warning): (.*)$")
AT_ONCE = threading.BoundedSemaphore(2)  # compiles running together
_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


class TypesetError(Exception):
    """Said to the person as it is."""


def load_config(path: Path = CONFIG) -> dict:
    return json.loads(path.read_text())


def load_templates(folder: Path = TEMPLATES) -> list[dict]:
    """templates.json, each entry checked to name a file that is there."""
    out, seen = [], set()
    for t in json.loads((folder / "templates.json").read_text()):
        for key in ("id", "label", "about", "file"):
            if not isinstance(t.get(key), str) or not t[key]:
                raise ValueError(f"template {t.get('id', '?')} has no {key}")
        if t["id"] in seen:
            raise ValueError(f"two templates are called {t['id']}")
        if not (folder / t["file"]).is_file():
            raise ValueError(f"template {t['id']}: {t['file']} is not there")
        seen.add(t["id"])
        out.append(t)
    return out


def docs_dir(cfg: dict) -> Path:
    return Path(os.environ.get("TYPESET_DOCS_DIR") or cfg["docs_dir"]).expanduser()


# ---- documents ------------------------------------------------------------------


def check_name(name: str) -> str:
    name = str(name).strip()
    if not name or len(name) > 80 or name.startswith(".") or BAD_NAME.search(name):
        raise TypesetError(
            "a document name needs 1 to 80 characters, no slashes,"
            " and cannot start with a dot"
        )
    return name


def folder_of(cfg: dict, name: str, links_ok: bool = False) -> Path:
    """An existing document's folder. Typst's --root does not stop it
    following a link out of the folder (checked with Typst 0.15.1), so a
    folder holding a link is refused for anything that reads or compiles."""
    folder = docs_dir(cfg) / check_name(name)
    if not (folder / MAIN).is_file():
        raise TypesetError(f"there is no document called {name}")
    if not links_ok:
        link = first_link(folder)
        if link:
            raise TypesetError(
                f"{link} is a link to somewhere else; Typeset does not follow"
                " links, so copy the file in instead"
            )
    return folder


def first_link(folder: Path) -> str:
    """The first symlink in a folder (or the folder itself), or ''."""
    if folder.is_symlink():
        return folder.name
    for top, dirs, files in os.walk(folder):
        for n in dirs + files:
            if os.path.islink(os.path.join(top, n)):
                return os.path.relpath(os.path.join(top, n), folder)
    return ""


def list_docs(cfg: dict) -> list[dict]:
    base = docs_dir(cfg)
    if not base.is_dir():
        return []
    out = []
    for d in base.iterdir():
        main = d / MAIN
        if d.is_dir() and not d.name.startswith(".") and main.is_file():
            out.append(
                {
                    "name": d.name,
                    "modified": main.stat().st_mtime,
                    "pdf": (d / f"{d.name}.pdf").is_file(),
                }
            )
    return sorted(out, key=lambda x: -x["modified"])


def create(cfg: dict, name: str, template: str, templates: list[dict]) -> dict:
    name = check_name(name)
    t = next((t for t in templates if t["id"] == template), None)
    if t is None:
        raise TypesetError(f"there is no template called {template}")
    folder = docs_dir(cfg) / name
    if folder.exists():
        raise TypesetError(f"{name} is already there")
    folder.mkdir(parents=True)
    write_text(folder / MAIN, (TEMPLATES / t["file"]).read_text())
    return {"name": name}


def write_text(path: Path, text: str) -> None:
    """Written under its own temporary name and moved over the old one, so a
    crash never leaves half a file."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.part")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_doc(cfg: dict, name: str) -> dict:
    folder = folder_of(cfg, name)
    return {
        "name": folder.name,
        "text": (folder / MAIN).read_text(errors="replace"),
        "assets": assets(folder),
        "pdf": (folder / f"{folder.name}.pdf").is_file(),
    }


def save(cfg: dict, name: str, text: str) -> None:
    if not isinstance(text, str):
        raise TypesetError("the text is missing")
    if len(text) > MAX_TEXT:
        raise TypesetError("that is too long for one document")
    folder = folder_of(cfg, name)
    # Its own lock, so a save never waits behind a compile (write_text is
    # atomic and Typst reads main.typ once).
    with lock_for(folder, "write"):
        write_text(folder / MAIN, text)


def assets(folder: Path) -> list[dict]:
    """The files a document can use: everything in its folder but main.typ,
    its own PDF and hidden files."""
    skip = {MAIN, f"{folder.name}.pdf"}
    return [
        {"name": f.name, "bytes": f.stat().st_size}
        for f in sorted(folder.iterdir())
        if f.is_file() and f.name not in skip and not f.name.startswith(".")
    ]


def add_asset(cfg: dict, name: str, filename: str, body: bytes) -> dict:
    """A picture or data file put beside main.typ, under a free name."""
    folder = folder_of(cfg, name)
    filename = Path(str(filename).replace("\\", "/")).name.strip()
    if not filename or filename.startswith(".") or BAD_NAME.search(filename):
        raise TypesetError("that file name cannot be used")
    stem, _, ext = filename.rpartition(".")
    ext = ext.lower()
    if not stem or ext not in cfg["asset_types"]:
        raise TypesetError(
            f"Typeset keeps {', '.join(cfg['asset_types'])} files beside a document"
        )
    if len(body) > cfg["asset_max_mb"] * 1e6:
        raise TypesetError(f"that file is over {cfg['asset_max_mb']} MB")
    if filename == MAIN or filename == f"{folder.name}.pdf":
        stem = stem + " copy"
    n = 1
    while True:
        cand = folder / (f"{stem}.{ext}" if n == 1 else f"{stem} ({n}).{ext}")
        try:
            with open(cand, "xb") as f:  # never over a file that is there
                f.write(body)
            return {"name": cand.name, "bytes": len(body)}
        except FileExistsError:
            n += 1


def rename(cfg: dict, name: str, to: str) -> dict:
    folder = folder_of(cfg, name, links_ok=True)
    to = check_name(to)
    new = folder.parent / to
    if new.exists():
        raise TypesetError(f"{to} is already there")
    with lock_for(folder):
        folder.rename(new)
        old_pdf = new / f"{name}.pdf"
        if old_pdf.is_file() and not (new / f"{to}.pdf").exists():
            old_pdf.rename(new / f"{to}.pdf")
    drop_preview(folder)
    return {"name": to}


def trash(cfg: dict, name: str) -> None:
    """The whole folder to the desktop trash (gio trash), never deleted."""
    folder = folder_of(cfg, name, links_ok=True)
    cmd = os.environ.get("TYPESET_TRASH_CMD", "gio trash").split()
    r = subprocess.run([*cmd, str(folder)], capture_output=True, text=True)
    if r.returncode != 0 or folder.exists():
        raise TypesetError(f"could not move it to the trash: {r.stderr.strip()}")
    drop_preview(folder)


# ---- compiling ------------------------------------------------------------------


def lock_for(folder: Path, kind: str = "compile") -> threading.Lock:
    with _locks_lock:
        return _locks.setdefault(f"{kind}:{folder}", threading.Lock())


def typst(cfg: dict) -> Path:
    override = os.environ.get("TYPESET_TYPST")
    if override:
        return Path(override)
    try:
        return forge_fetch.pinned_tool(
            {**cfg["tools"]["typst"], "name": "typst"}, DATA_DIR / "bin"
        )
    except forge_fetch.FetchError as e:
        raise TypesetError(str(e)) from None


def typst_ready(cfg: dict) -> bool:
    if os.environ.get("TYPESET_TYPST"):
        return True
    return forge_fetch.is_ready(
        {**cfg["tools"]["typst"], "name": "typst"}, DATA_DIR / "bin"
    )


def diagnostics(text: str) -> tuple[list[dict], list[dict]]:
    """Typst's short diagnostics, split into errors and warnings. A line that
    is not a diagnostic (a hint) is added to the one before it."""
    errors: list[dict] = []
    warnings: list[dict] = []
    last: dict | None = None
    for line in text.splitlines():
        m = DIAG.match(line.strip())
        if m:
            file, ln, col, kind, msg = m.groups()
            last = {
                "file": file or "",
                "line": int(ln) if ln else 0,
                "col": int(col) if col else 0,
                "message": msg,
            }
            (errors if kind == "error" else warnings).append(last)
        elif line.strip() and last is not None:
            last["message"] += " " + line.strip()
    return errors, warnings


def _run(cfg: dict, folder: Path, out: Path) -> tuple[int, str]:
    # prlimit sets the memory cap and then execs Typst (same process), which
    # is safer than preexec_fn in a threaded server.
    cap = int(cfg["memory_cap_gb"] * (1 << 30))
    argv = [
        "prlimit",
        f"--as={cap}",
        "--",
        str(typst(cfg)),
        "compile",
        "--root",
        str(folder),
        "--diagnostic-format",
        "short",
        "--package-cache-path",
        str(DATA_DIR / "packages"),
        "-j",
        "2",
        str(folder / MAIN),
        str(out),
    ]
    with AT_ONCE:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            errors="replace",
            cwd=folder,  # so diagnostics name files as the document does
            start_new_session=True,  # its own group, so a timeout stops it all
        )
        try:
            said, noise = proc.communicate(timeout=cfg["compile_timeout"])
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            return -1, f"error: it took over {cfg['compile_timeout']} s; stopped"
    return proc.returncode, noise + said


def preview_dir(folder: Path) -> Path:
    key = hashlib.sha1(str(folder).encode()).hexdigest()[:16]
    return DATA_DIR / "preview" / key


def drop_preview(folder: Path) -> None:
    shutil.rmtree(preview_dir(folder), ignore_errors=True)  # Typeset's own cache


def preview(cfg: dict, name: str, text: str | None = None) -> dict:
    """Save (when text is given) and compile to SVG pages. A failed compile
    keeps the last good pages, so the preview does not go blank mid-edit."""
    if text is not None:
        save(cfg, name, text)
    folder = folder_of(cfg, name)
    final = preview_dir(folder)
    with lock_for(folder):
        work = final.with_name(f"{final.name}.{uuid.uuid4().hex[:8]}.new")
        work.mkdir(parents=True)
        try:
            t0 = time.monotonic()
            code, said = _run(cfg, folder, work / "page-{p}.svg")
            ms = round((time.monotonic() - t0) * 1000)
            errors, warnings = diagnostics(said)
            pages = len(list(work.glob("page-*.svg")))
            if code == 0 and pages:
                old = final.with_name(f"{final.name}.{uuid.uuid4().hex[:8]}.old")
                if final.exists():
                    final.rename(old)
                work.rename(final)
                shutil.rmtree(old, ignore_errors=True)
            elif not errors:
                errors = [
                    {
                        "file": "",
                        "line": 0,
                        "col": 0,
                        "message": said.strip() or "Typst made no pages",
                    }
                ]
        finally:
            shutil.rmtree(work, ignore_errors=True)
        have = len(list(final.glob("page-*.svg"))) if final.is_dir() else 0
        v = str(int(final.stat().st_mtime_ns)) if final.is_dir() else "0"
    return {
        "ok": not errors,
        "pages": have,
        "v": v,
        "errors": errors,
        "warnings": warnings,
        "ms": ms,
    }


def page_file(cfg: dict, name: str, n: int) -> Path:
    page = preview_dir(folder_of(cfg, name)) / f"page-{int(n)}.svg"
    if not page.is_file():
        raise TypesetError("no such page")
    return page


def export_pdf(cfg: dict, name: str, text: str | None = None) -> dict:
    """<name>.pdf beside main.typ, replaced whole only when Typst succeeds."""
    if text is not None:
        save(cfg, name, text)
    folder = folder_of(cfg, name)
    pdf = folder / f"{folder.name}.pdf"
    tmp = folder / f".{folder.name}.{uuid.uuid4().hex[:8]}.pdf"
    with lock_for(folder):
        try:
            code, said = _run(cfg, folder, tmp)
            errors, _ = diagnostics(said)
            if code != 0 or not tmp.is_file():
                first = errors[0] if errors else {"line": 0, "message": said.strip()}
                where = f"line {first['line']}: " if first["line"] else ""
                raise TypesetError(f"the PDF was not made; {where}{first['message']}")
            os.replace(tmp, pdf)
        finally:
            tmp.unlink(missing_ok=True)
    return {"name": pdf.name, "path": str(pdf), "bytes": pdf.stat().st_size}
