"""The pages a dossier is made of - discovered, not declared.

A page is one module with a `SPEC`, and an entity type lists the page names it
wants. Every page returns the same shape: a title and a list of blocks, each
block naming its own kind. The frontend knows how to draw a handful of kinds
(facts, timeline, claims, quotes, sources, relations, prose, notes) and nothing
about any individual page, so a new page is one file here and no frontend work.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Callable

_registry: dict[str, "PageSpec"] = {}


@dataclass
class PageSpec:
    name: str
    label: str
    build: Callable[[dict], dict]
    blurb: str = ""
    icon: str = ""


def _discover() -> dict[str, PageSpec]:
    if _registry:
        return _registry
    package_name = __package__ or __name__.rsplit(".", 1)[0]
    package = importlib.import_module(package_name)
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_") or info.name in ("registry", "common"):
            continue
        module = importlib.import_module(f"{package_name}.{info.name}")
        spec = getattr(module, "SPEC", None)
        if isinstance(spec, PageSpec):
            _registry[spec.name] = spec
    return _registry


def get(name: str) -> PageSpec | None:
    return _discover().get(name)


def all_pages() -> list[PageSpec]:
    return list(_discover().values())


def build_page(name: str, stored: dict) -> dict:
    spec = get(name)
    if spec is None:
        return {
            "title": name,
            "blocks": [
                {"kind": "prose", "text": f"No page type called '{name}' is installed."}
            ],
        }
    page = spec.build(stored)
    page.setdefault("title", spec.label)
    page.setdefault("name", spec.name)
    page.setdefault("blurb", spec.blurb)
    return page
