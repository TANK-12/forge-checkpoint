"""Political party dossiers.

Founding, ideology, leadership, splits, and what they actually voted for.
"""

from __future__ import annotations

from .registry import EntitySpec


def context_terms(identity: dict) -> list[str]:
    """Terms that tell this subject apart from anything with a similar name."""
    terms = ["party"]
    terms += identity.get("ideology") or []
    terms += identity.get("country") or []
    terms += identity.get("citizenship") or []
    return [t for t in terms if t][:14]


def search_hint(identity: dict) -> str:
    """Extra words added to web searches to keep results on the right subject."""
    country = (identity.get("country") or [""])[0]
    return f"political party {country}".strip()


SPEC = EntitySpec(
    name="party",
    label="Political party",
    plural="Parties",
    pages=(
        "overview",
        "everything",
        "profile",
        "news",
        "platform",
        "leadership",
        "record",
        "network",
        "sources",
        "notes",
    ),
    type_hints=("Q7278", "Q79913"),
    description_hints=("political party", "party"),
    context_terms=context_terms,
    search_hint=search_hint,
    accent="#7fb2ff",
    blurb="Founding, ideology, leadership, splits, and what they actually voted for.",
    order=20,
)
