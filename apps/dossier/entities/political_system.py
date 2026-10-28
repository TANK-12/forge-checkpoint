"""Political system dossiers.

How a country actually governs: chambers, terms, how a law passes, how a leader is removed.
"""

from __future__ import annotations

from .registry import EntitySpec


def context_terms(identity: dict) -> list[str]:
    """Terms that tell this subject apart from anything with a similar name."""
    terms = ["government", "constitution", "parliament", "election"]
    terms += identity.get("country") or []
    return [t for t in terms if t][:14]


def search_hint(identity: dict) -> str:
    """Extra words added to web searches to keep results on the right subject."""
    country = (identity.get("country") or [""])[0]
    return f"government constitution {country}".strip()


SPEC = EntitySpec(
    name="political_system",
    label="Political system",
    plural="Political systems",
    pages=(
        "overview",
        "everything",
        "profile",
        "news",
        "how_it_works",
        "institutions",
        "economy",
        "society",
        "elections",
        "sources",
        "notes",
    ),
    type_hints=("Q1307214", "Q28108"),
    description_hints=(
        "form of government",
        "political system",
        "constitution",
        "parliament",
        "legislature",
        "electoral system",
    ),
    context_terms=context_terms,
    search_hint=search_hint,
    accent="#9ad07f",
    blurb="How a country actually governs: chambers, terms, how a law passes, how a leader is removed.",
    order=30,
)
