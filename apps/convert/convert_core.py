"""Convert: one file in, the same thing in another format out.

The converters are a registry with one file each in converters/. A file
there has CONVERTER, a dict that says what it reads and writes:

    CONVERTER = {
        "id": "images", "label": "Images", "order": 1,
        "from": ["png", "jpg", ...],      # extensions, lower case, no dot
        "to": ["png", "jpg", ...],
        "options": [{"id": "quality", "label": "Quality", "type": "number",
                     "min": 1, "max": 100, "default": 90, "for": ["jpg"]}],
        "needs": "pandoc",                 # optional: a pinned program
        "handoff": {"app": "mediaforge", "hash": "tool=enhance", ...},
    }

and convert(src, dst, to, opts, ctx), which writes dst (a temporary name
with the right extension; Convert moves it into place when it is whole). A
converter with a handoff instead of targets is a pointer to another Forge
app that already does that job (video: MediaForge's Video Enhancer).

Nothing in this file names a converter. Output goes to convert.json's
out_dir, under the file's own name with the new extension, never over a
file that is already there.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR") or ROOT.parent.parent / "shared")
sys.path.insert(0, str(SHARED_DIR))
import forge_fetch  # noqa: E402

CONVERTERS_DIR = ROOT / "converters"
CONFIG = Path(os.environ.get("CONVERT_CONFIG") or ROOT / "convert.json")
DATA_DIR = Path(
    os.environ.get("CONVERT_DATA_DIR") or Path.home() / ".local/share/forge/convert"
)
OPTION_TYPES = ("number", "choice")
BAD_NAME = re.compile(r"[\x00-\x1f/\\]")


class ConvertError(ValueError):
    """Something that cannot be done; the message says why, for the page."""


def load_config(path: Path = CONFIG) -> dict:
    return json.loads(path.read_text())


def out_dir(cfg: dict) -> Path:
    return Path(os.environ.get("CONVERT_OUT_DIR") or cfg["out_dir"]).expanduser()


# ---- the registry ------------------------------------------------------------


def load_converters(folder: Path = CONVERTERS_DIR) -> dict[str, ModuleType]:
    """Every converters/*.py, checked, by id, in their order."""
    found: list[ModuleType] = []
    for path in sorted(folder.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(
            f"convert_converters.{path.stem}", path
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        check_converter(mod, path.name)
        found.append(mod)
    found.sort(key=lambda m: (m.CONVERTER.get("order", 99), m.CONVERTER["id"]))
    out: dict[str, ModuleType] = {}
    for mod in found:
        cid = mod.CONVERTER["id"]
        if cid in out:
            raise ConvertError(f"two converters are called {cid}")
        out[cid] = mod
    return out


def check_converter(mod: ModuleType, where: str) -> None:
    c = getattr(mod, "CONVERTER", None)
    if not isinstance(c, dict):
        raise ConvertError(f"{where} has no CONVERTER")
    for key in ("id", "label", "from"):
        if not c.get(key):
            raise ConvertError(f"{where}: CONVERTER needs {key}")
    exts = [*c["from"], *c.get("to", [])]
    if any(e != e.lower() or e.startswith(".") for e in exts):
        raise ConvertError(f"{where}: extensions are lower case, with no dot")
    if c.get("to") and not callable(getattr(mod, "convert", None)):
        raise ConvertError(f"{where}: it has targets but no convert()")
    if not c.get("to") and not c.get("handoff"):
        raise ConvertError(f"{where}: it needs targets or a handoff")
    for opt in c.get("options", []):
        if opt.get("type") not in OPTION_TYPES or "default" not in opt:
            raise ConvertError(f"{where}: option {opt.get('id')} is not usable")


def describe(convs: dict[str, ModuleType]) -> list[dict]:
    """What the page needs: each converter's CONVERTER, as plain data."""
    return [json.loads(json.dumps(m.CONVERTER)) for m in convs.values()]


def ext_of(name: str) -> str:
    return Path(name).suffix.lower().lstrip(".")


def handoff_ready(handoff: dict) -> bool:
    """The app a handoff names is installed beside this one (a release may
    leave it out)."""
    return (Path(__file__).resolve().parent.parent / handoff["app"]).is_dir()


def choices_for(convs: dict[str, ModuleType], name: str) -> list[dict]:
    """Every converter that reads this file, with its targets (the file's
    own format left out) or its handoff."""
    ext = ext_of(name)
    same = {ext} | ({"jpg", "jpeg"} if ext in ("jpg", "jpeg") else set())
    out = []
    for cid, mod in convs.items():
        c = mod.CONVERTER
        if c.get("handoff") and not handoff_ready(c["handoff"]):
            if not c.get("to"):
                continue  # a pointer to an app this Forge does not have
            c = {k: v for k, v in c.items() if k != "handoff"}
        if ext in c["from"]:
            to = [t for t in c.get("to", []) if t not in same]
            out.append(
                {"converter": cid, "label": c["label"], "to": to}
                | ({"handoff": c["handoff"]} if c.get("handoff") else {})
            )
    return out


def clean_options(c: dict, to: str, given: dict) -> dict:
    """The options this converter has, for this target, within their limits;
    the defaults for anything not given."""
    out: dict[str, Any] = {}
    for opt in c.get("options", []):
        if opt.get("for") and to not in opt["for"]:
            continue
        v = given.get(opt["id"], opt["default"])
        if opt["type"] == "number":
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise ConvertError(f"{opt['label']} must be a number") from None
            lo, hi = opt.get("min", float("-inf")), opt.get("max", float("inf"))
            if not lo <= v <= hi:
                raise ConvertError(f"{opt['label']} must be from {lo:g} to {hi:g}")
            v = int(v) if float(v).is_integer() else v
        elif v not in [ch["id"] for ch in opt["choices"]]:
            raise ConvertError(f"{opt['label']} has no choice {v}")
        out[opt["id"]] = v
    return out


# ---- names and files -----------------------------------------------------------


def safe_name(name: str) -> str:
    """A dropped file's own name, with nothing that could leave a folder."""
    name = Path(str(name).replace("\\", "/")).name.strip()
    if not name or name in (".", "..") or BAD_NAME.search(name):
        raise ConvertError("that file name cannot be used")
    return name[:200]


def free_name(folder: Path, stem: str, ext: str) -> Path:
    """stem.ext, or stem (2).ext and on, whichever is not taken yet."""
    n = 1
    while True:
        cand = folder / (f"{stem}.{ext}" if n == 1 else f"{stem} ({n}).{ext}")
        if not cand.exists():
            return cand
        n += 1


def claim(tmp: Path, folder: Path, stem: str, ext: str) -> Path:
    """Move tmp to the first free name. A hard link fails when the name is
    taken, so two conversions finishing together never share one."""
    stem = stem.lstrip(".") or "converted"  # a hidden name could not be fetched
    while True:
        final = free_name(folder, stem, ext)
        try:
            os.link(tmp, final)
        except FileExistsError:
            continue
        except OSError:  # a disk without hard links: reserve the name first
            try:
                os.close(os.open(final, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            except FileExistsError:
                continue
            os.replace(tmp, final)
        return final


TEMP_PREFIX = ".converting-"


def sweep_leftovers(cfg: dict, older_than: float = 3600) -> int:
    """Remove Convert's own half-written files (".converting-*") that a
    killed backend left in the output folder. Only that prefix is touched."""
    folder = out_dir(cfg)
    if not folder.is_dir():
        return 0
    gone = 0
    for f in folder.glob(TEMP_PREFIX + "*"):
        if f.is_file() and time.time() - f.stat().st_mtime > older_than:
            f.unlink(missing_ok=True)
            gone += 1
    return gone


def recent(cfg: dict, limit: int = 30) -> list[dict]:
    folder = out_dir(cfg)
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {"name": p.name, "bytes": p.stat().st_size, "made": round(p.stat().st_mtime)}
        for p in files[:limit]
    ]


def out_file(cfg: dict, name: str) -> Path:
    """A file in the output folder, by name only."""
    p = out_dir(cfg) / safe_name(name)
    if p.name.startswith(".") or not p.is_file():
        raise ConvertError("no such file")
    return p


def room_check(cfg: dict, folder: Path, size: int) -> None:
    keep = float(cfg.get("keep_free_gb", 2)) * 1e9
    folder.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(folder).free - size < keep:
        raise ConvertError(
            f"that would leave less than {keep / 1e9:g} GB free on the disk"
        )


# ---- running a conversion ------------------------------------------------------


AT_ONCE = 2  # conversions running together; RAM is shared with Jan and Firefox
SLOTS = threading.BoundedSemaphore(AT_ONCE)


@dataclass
class Ctx:
    """What a converter gets besides the file: the job (log, progress, stop),
    the config and Convert's data folder, and tool() for pinned programs."""

    job: Any
    cfg: dict
    data: Path

    def tool(self, name: str) -> Path:
        spec = self.cfg["tools"][name]
        override = os.environ.get(f"CONVERT_{name.upper()}")
        if override:
            return Path(override)
        try:
            return forge_fetch.pinned_tool(
                {**spec, "name": name}, self.data / "bin", say=self.job.log
            )
        except forge_fetch.FetchError as e:
            raise ConvertError(str(e)) from None

    def run(self, argv: list[str], on_line: Callable[[str], None] | None = None) -> str:
        """Run a program as this job's process, so Stop ends it. Its output
        lines go to on_line; the last of them come back for an error."""
        if self.job.should_stop():
            raise ConvertError("stopped")
        proc = subprocess.Popen(
            [str(a) for a in argv],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            errors="replace",
        )
        self.job.proc = proc
        tail: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            tail = (tail + [line])[-12:]
            if on_line:
                on_line(line)
        proc.wait()
        self.job.proc = None
        if self.job.should_stop():
            raise ConvertError("stopped")
        if proc.returncode != 0:
            said = " | ".join(t for t in tail if t.strip())[-400:]
            raise ConvertError(f"{Path(argv[0]).name} failed: {said}")
        return "\n".join(tail)


def tool_ready(cfg: dict, data: Path, name: str) -> bool:
    if os.environ.get(f"CONVERT_{name.upper()}"):
        return True
    return forge_fetch.is_ready({**cfg["tools"][name], "name": name}, data / "bin")


def convert(
    mod: ModuleType,
    src: Path,
    name: str,
    to: str,
    opts: dict,
    job: Any,
    cfg: dict,
    data: Path | None = None,
) -> dict:
    """Convert src (called `name`) into `to`, in the output folder. The new
    file is written under a hidden name and moved into place whole; on any
    failure or Stop nothing is left behind. AT_ONCE run together; the rest
    wait their turn (and can be stopped while waiting)."""
    data = data or DATA_DIR
    c = mod.CONVERTER
    if to not in c.get("to", []):
        raise ConvertError(f"{c['label']} cannot make .{to}")
    if ext_of(name) not in c["from"]:
        raise ConvertError(f"{c['label']} cannot read .{ext_of(name)}")
    opts = clean_options(c, to, opts)
    folder = out_dir(cfg)
    room_check(cfg, folder, src.stat().st_size)
    if not SLOTS.acquire(blocking=False):
        job.log("Waiting for one of the others to finish")
        while not SLOTS.acquire(timeout=0.25):
            if job.should_stop():
                raise ConvertError("stopped")
    tmp = folder / f"{TEMP_PREFIX}{uuid.uuid4().hex[:8]}.{to}"
    try:
        job.log(f"{name} to .{to}")
        mod.convert(src, tmp, to, opts, Ctx(job, cfg, data))
        if job.should_stop():
            raise ConvertError("stopped")
        if not tmp.is_file() or tmp.stat().st_size == 0:
            raise ConvertError("the converter wrote nothing")
        final = claim(tmp, folder, Path(name).stem, to)
    finally:
        tmp.unlink(missing_ok=True)
        SLOTS.release()
    job.progress(1.0)
    job.log(f"Saved {final}")
    return {"name": final.name, "path": str(final), "bytes": final.stat().st_size}
