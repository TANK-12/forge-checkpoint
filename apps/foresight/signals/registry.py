"""Where attention and feeling are read from — discovered, not declared.

Same rule as Dossier's three registries: any module dropped into this package
with a module-level `SPEC` is a signal source. Adding one is one new file and
no edits anywhere else; nothing in the backend or the frontend names an
individual source.

**A signal is not a fact, and the distinction is the point.** Dossier stores
things that are true and makes a model prove every claim against a source
sentence. A signal is a *measurement* — how many people read this article
today, how loudly a forum argued about it — and it is noisy, gameable and
often meaningless on its own. So signals live here, in their own store, and
never flow back into Dossier's factual record.

Every reading carries the date it describes and the source that produced it, so
a series can always be re-derived and a bad source can be dropped without
taking the rest with it.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Callable

# What a source measures. The interface draws a series by its kind, so a new
# source looks right without any frontend work.
#
# `attention`, `volume` and `feeling` are proxies - how loudly people are
# looking or arguing. `economy`, `markets` and `politics` are the real thing:
# published figures and observed events. The user asked for the second group
# directly, having correctly noticed that a search count "says nothing" alone.
KINDS = ("attention", "volume", "feeling", "economy", "markets", "politics")

_registry: dict[str, "SignalSpec"] = {}


@dataclass
class Reading:
    """One measurement of one subject on one day.

    `series` names WHICH measurement, for a source that publishes more than
    one. The World Bank returns nine indicators for a country, and a series is
    keyed by date: without this they would all land in one file and GDP would
    silently overwrite unemployment for the same year. Leave it empty for a
    source that measures a single thing, which is the common case.
    """

    date: str
    value: float
    detail: str = ""
    url: str = ""
    sample: int = 0
    series: str = ""

    def as_point(self) -> dict:
        return {
            "date": self.date,
            "value": self.value,
            "detail": self.detail,
            "url": self.url,
            "sample": self.sample,
        }


@dataclass
class SignalSpec:
    name: str
    label: str
    kind: str
    unit: str
    # fetch(subject_name, context) -> list[Reading]
    fetch: Callable[..., list]
    description: str = ""
    enabled: bool = True
    # Why this source might be wrong. Shown in the interface beside its series,
    # because a measurement presented without its bias is worse than none.
    caveat: str = ""
    needs_credentials: bool = False
    # A count (stories, posts, views) cannot go below zero, so a straight line
    # carried past zero is a claim about something impossible. Plans drop it.
    non_negative: bool = False
    # How many days a reading stays news. A daily count is old after a week;
    # an annual figure is the newest there is for well over a year.
    fresh_days: int = 7
    # Whole things counted (stories, posts, views): a plan threshold is a
    # whole number, and one under 1 ("below 0.09 stories") is not claimed.
    whole_numbers: bool = False


def _discover() -> dict[str, SignalSpec]:
    if _registry:
        return _registry
    package_name = __package__ or __name__.rsplit(".", 1)[0]
    package = importlib.import_module(package_name)
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_") or info.name == "registry":
            continue
        module = importlib.import_module(f"{package_name}.{info.name}")
        spec = getattr(module, "SPEC", None)
        if isinstance(spec, SignalSpec):
            _registry[spec.name] = spec
    return _registry


def all_sources() -> list[SignalSpec]:
    return sorted(_discover().values(), key=lambda s: (s.kind, s.name))


def get(name: str) -> SignalSpec | None:
    return _discover().get(name)


def enabled_sources() -> list[SignalSpec]:
    return [s for s in all_sources() if s.enabled and not s.needs_credentials]


def describe() -> list[dict]:
    """What the interface lists. Built from the registry, never hardcoded."""
    return [
        {
            "name": s.name,
            "label": s.label,
            "kind": s.kind,
            "unit": s.unit,
            "description": s.description,
            "caveat": s.caveat,
            "enabled": s.enabled,
            "needs_credentials": s.needs_credentials,
            "non_negative": s.non_negative,
            "fresh_days": s.fresh_days,
            "whole_numbers": s.whole_numbers,
        }
        for s in all_sources()
    ]
