"""What kinds of thing can have a dossier - discovered, not declared.

Same rule as sources: drop a module in this package with a module-level `SPEC`
and a new kind of dossier exists. An entity type declares which pages it gets,
which Wikidata descriptions identify it, and how to turn its identity record
into the context terms the relevance scorer uses to reject namesakes.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Callable

_registry: dict[str, "EntitySpec"] = {}


@dataclass
class EntitySpec:
    name: str
    label: str
    plural: str
    pages: tuple[str, ...]
    type_hints: tuple[str, ...] = ()
    description_hints: tuple[str, ...] = ()
    context_terms: Callable[[dict], list[str]] = lambda identity: []
    search_hint: Callable[[dict], str] = lambda identity: ""
    accent: str = "#e0a75e"
    blurb: str = ""
    order: int = 50
    extra: dict = field(default_factory=dict)


def _discover() -> dict[str, EntitySpec]:
    if _registry:
        return _registry
    package_name = __package__ or __name__.rsplit(".", 1)[0]
    package = importlib.import_module(package_name)
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_") or info.name == "registry":
            continue
        module = importlib.import_module(f"{package_name}.{info.name}")
        spec = getattr(module, "SPEC", None)
        if isinstance(spec, EntitySpec):
            _registry[spec.name] = spec
    return _registry


def all_types() -> list[EntitySpec]:
    return sorted(_discover().values(), key=lambda e: (e.order, e.name))


def get(name: str) -> EntitySpec | None:
    return _discover().get(name)


def default() -> EntitySpec:
    return get("person") or all_types()[0]
