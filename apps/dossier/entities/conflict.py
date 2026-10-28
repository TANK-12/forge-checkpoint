"""Conflict or war dossiers.

Wars and armed conflicts: who is fighting, since when, over what, and where it stands.
"""

from __future__ import annotations

from .registry import EntitySpec


def context_terms(identity: dict) -> list[str]:
    """Terms that tell this subject apart from anything with a similar name."""
    terms = ["war", "conflict", "forces", "ceasefire", "offensive", "casualties"]
    terms += identity.get("country") or []
    return [t for t in terms if t][:14]


def search_hint(identity: dict) -> str:
    """Extra words added to web searches to keep results on the right subject."""
    return "war conflict fighting"


SPEC = EntitySpec(
    name="conflict",
    label="Conflict or war",
    plural="Conflicts & wars",
    pages=(
        "overview",
        "everything",
        "profile",
        "news",
        "belligerents",
        "timeline_detail",
        "record",
        "network",
        "sources",
        "notes",
    ),
    type_hints=("Q198", "Q350604", "Q180684"),
    description_hints=(
        "war",
        "conflict",
        "armed conflict",
        "civil war",
        "invasion",
        "insurgency",
    ),
    context_terms=context_terms,
    search_hint=search_hint,
    accent="#e0705f",
    blurb="Wars and armed conflicts: who is fighting, since when, over what, and where it stands.",
    order=70,
)
