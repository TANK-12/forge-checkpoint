"""Find the curios on the shelf and load their optional server.py.

A curio is a folder curios/<id>/ holding curio.json; folders starting with
"_" or "." are not curios (curios/_kit/ is the shared helper kit). Nothing
lists the curios anywhere else: dropping a folder in is the whole act of
adding one. A broken curio is reported in `problems` and skipped, never fatal.

server.py is imported under a name of its own, afterglow_curio_<id>, so two
curios can never shadow each other's modules. web_app.py and play.py load it
the same way, through load_server().
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import store

ENTRY = re.compile(r"^[A-Za-z0-9_-]+\.m?js$")


def discover(curios_dir: Path | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """(curio metas sorted by order then id, problems found on the way)."""
    root = curios_dir or store.CURIOS_DIR
    metas: list[dict[str, Any]] = []
    problems: list[str] = []
    if not root.is_dir():
        return metas, [f"{root} is missing"]
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or folder.name[0] in "_.":
            continue
        if folder.name == "__pycache__":
            continue
        if not store.CURIO_ID.fullmatch(folder.name):
            problems.append(f"{folder.name}: not a valid curio id")
            continue
        try:
            data = json.loads((folder / "curio.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            problems.append(f"{folder.name}: no curio.json")
            continue
        except (OSError, ValueError) as exc:
            problems.append(f"{folder.name}: curio.json does not read ({exc})")
            continue
        if not isinstance(data, dict) or not str(data.get("name") or "").strip():
            problems.append(f"{folder.name}: curio.json needs a name")
            continue
        try:  # Python reads NaN and 1e999; the shelf's JSON answer cannot hold them
            json.dumps(data, allow_nan=False)
        except ValueError:
            problems.append(f"{folder.name}: curio.json holds NaN or Infinity")
            continue
        entry = str(data.get("entry") or "curio.js")
        if not ENTRY.fullmatch(entry) or not (folder / entry).is_file():
            problems.append(f"{folder.name}: entry {entry!r} is missing")
            continue
        order = data.get("order", 100)
        metas.append(
            {
                **data,
                "id": folder.name,
                "entry": entry,
                "order": order if isinstance(order, (int, float)) else 100,
                "has_server": (folder / "server.py").is_file(),
            }
        )
    metas.sort(key=lambda m: (m["order"], m["id"]))
    return metas, problems


def module_name(curio: str) -> str:
    return "afterglow_curio_" + curio.replace("-", "_")


def load_server(curio: str, curios_dir: Path | None = None) -> ModuleType:
    """Import curios/<curio>/server.py (once; later calls reuse it)."""
    name = module_name(curio)
    if name in sys.modules:
        return sys.modules[name]
    path = (curios_dir or store.CURIOS_DIR) / curio / "server.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{path} cannot be imported")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def load_servers(
    metas: list[dict[str, Any]], curios_dir: Path | None = None
) -> tuple[dict[str, ModuleType], list[str]]:
    modules: dict[str, ModuleType] = {}
    problems: list[str] = []
    for meta in metas:
        if not meta.get("has_server"):
            continue
        try:
            modules[meta["id"]] = load_server(meta["id"], curios_dir)
        except KeyboardInterrupt:
            raise
        except (
            BaseException
        ) as exc:  # SystemExit too: a broken curio must not stop the others
            problems.append(f"{meta['id']}: server.py failed: {exc!r}")
            meta["server_error"] = repr(exc)
    return modules, problems


def mount_routers(app: Any, modules: dict[str, ModuleType]) -> list[str]:
    """Give each curio's `router` its prefix /api/curio/<id>; problems back."""
    from fastapi import APIRouter

    problems: list[str] = []
    for cid, module in modules.items():
        router = getattr(module, "router", None)
        if router is None:
            continue
        if not isinstance(router, APIRouter):
            problems.append(f"{cid}: server.py's router is not an APIRouter")
            continue
        try:
            app.include_router(router, prefix=f"/api/curio/{cid}")
        except Exception as exc:
            problems.append(f"{cid}: its routes could not be added: {exc!r}")
    return problems
