"""Analysers: what turns stored signals into something worth reading.

Discovered, not declared — drop in a module with a `SPEC` and it runs. Same
rule as everything else here.

**Rules first, model only where it earns it.** This is the same discipline that
makes Dossier trustworthy: arithmetic decides everything it can decide, and a
model is called only for the genuinely ambiguous middle. A z-score does not
hallucinate, costs nothing, and runs on the CPU while the iGPU is busy — so a
breakout in attention is detected by arithmetic, and a model is only ever asked
what a breakout might *mean*.

Every finding carries the readings it was computed from, so the interface can
show its working and the user can disagree with it.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Callable

_registry: dict[str, "AnalyserSpec"] = {}


@dataclass
class Finding:
    """One thing worth telling the user, with its evidence attached."""

    kind: str
    subject: str
    slug: str
    headline: str
    detail: str = ""
    # 0-1. How much this deserves attention relative to other findings.
    weight: float = 0.0
    source: str = ""
    at: str = ""
    evidence: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "slug": self.slug,
            "headline": self.headline,
            "detail": self.detail,
            "weight": round(self.weight, 3),
            "source": self.source,
            "at": self.at,
            "evidence": self.evidence[:20],
        }


@dataclass
class AnalyserSpec:
    name: str
    label: str
    # run(slug, subject_name, series_by_source) -> list[Finding]
    run: Callable[..., list]
    description: str = ""
    uses_model: bool = False


def _discover() -> dict[str, AnalyserSpec]:
    if _registry:
        return _registry
    package_name = __package__ or __name__.rsplit(".", 1)[0]
    package = importlib.import_module(package_name)
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_") or info.name == "registry":
            continue
        module = importlib.import_module(f"{package_name}.{info.name}")
        spec = getattr(module, "SPEC", None)
        if isinstance(spec, AnalyserSpec):
            _registry[spec.name] = spec
    return _registry


def all_analysers() -> list[AnalyserSpec]:
    return sorted(_discover().values(), key=lambda a: a.name)


def get(name: str) -> AnalyserSpec | None:
    return _discover().get(name)


def describe() -> list[dict]:
    return [
        {
            "name": a.name,
            "label": a.label,
            "description": a.description,
            "uses_model": a.uses_model,
        }
        for a in all_analysers()
    ]
