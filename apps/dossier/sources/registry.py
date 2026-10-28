"""The list of places a dossier can be built from - discovered, not declared.

Any module dropped into this package that defines a module-level `SPEC` is a
source. Adding one is one new file and no edits anywhere else; nothing in the
backend, the pipeline or the frontend names an individual source.

An adapter's `fetch` gets a SubjectProfile and a Context and returns a Harvest:
documents to score and cluster, plus any structured facts it can supply for
free. Wikidata's dated offices, for instance, are a timeline already - no model
needs to read prose to work them out.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Callable

from research.fetcher import Document, Fetcher
from research.scoring import SubjectProfile

# When a source runs. `identify` settles who we are talking about, `quick` is
# the fast pass every subject gets, `deep` only runs on a deep dive.
PHASES = ("identify", "quick", "deep")


@dataclass
class Harvest:
    documents: list[Document] = field(default_factory=list)
    timeline: list[dict] = field(default_factory=list)
    quotes: list[dict] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    identity: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    skipped_known: int = 0
    # The full encyclopedia article as headed sections. One living document
    # per subject, so it replaces the stored copy rather than merging into it.
    article: dict = field(default_factory=dict)

    def extend(self, other: "Harvest") -> "Harvest":
        self.skipped_known += other.skipped_known
        if other.article and not self.article:
            self.article = other.article
        self.documents.extend(other.documents)
        self.timeline.extend(other.timeline)
        self.quotes.extend(other.quotes)
        self.relations.extend(other.relations)
        self.images.extend(other.images)
        self.notes.extend(other.notes)
        for k, v in other.identity.items():
            self.identity.setdefault(k, v)
        return self


@dataclass
class Context:
    """What an adapter is allowed to use while gathering."""

    fetcher: Fetcher
    phase: str = "quick"
    entity_type: str = "person"
    identity: dict = field(default_factory=dict)
    budget: int = 15  # max documents this adapter should return
    log: Callable[[str], None] = lambda msg: None
    # Canonical URLs already stored for this subject. Adapters that fetch
    # ordinary web articles skip these: a news story published last month does
    # not change, so re-downloading and re-parsing it on every refresh is pure
    # waste. Encyclopedic sources deliberately ignore this - a Wikipedia page
    # or a Wikidata entity is one living document whose content DOES change.
    known_urls: set = field(default_factory=set)


@dataclass
class SourceSpec:
    name: str
    label: str
    tier: str
    phases: tuple[str, ...]
    entity_types: tuple[str, ...]
    fetch: Callable[[SubjectProfile, Context], Harvest]
    description: str = ""
    enabled: bool = True


_registry: dict[str, SourceSpec] = {}


def _discover() -> dict[str, SourceSpec]:
    if _registry:
        return _registry
    package_name = __package__ or __name__.rsplit(".", 1)[0]
    package = importlib.import_module(package_name)
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_") or info.name == "registry":
            continue
        module = importlib.import_module(f"{package_name}.{info.name}")
        spec = getattr(module, "SPEC", None)
        if isinstance(spec, SourceSpec):
            _registry[spec.name] = spec
    return _registry


def all_sources() -> list[SourceSpec]:
    return sorted(_discover().values(), key=lambda s: s.name)


def get(name: str) -> SourceSpec | None:
    return _discover().get(name)


def for_phase(phase: str, entity_type: str) -> list[SourceSpec]:
    """Sources that apply to this kind of subject at this stage.

    `entity_types=("*",)` means "any subject". Only genuinely restricted
    sources name types - SEC filings are meaningless for a war - so adding a
    new kind of dossier stays one new file, with nothing here to edit.
    """
    return [
        s
        for s in all_sources()
        if s.enabled
        and phase in s.phases
        and ("*" in s.entity_types or entity_type in s.entity_types)
    ]
