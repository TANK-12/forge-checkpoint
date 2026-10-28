"""Alliance or bloc dossiers.

NATO, the EU, BRICS and the like: who is in, what binds them, and where they split.
"""

from __future__ import annotations

from .registry import EntitySpec


def context_terms(identity: dict) -> list[str]:
    """Terms that tell this subject apart from anything with a similar name."""
    terms = ["alliance", "treaty", "member states", "summit"]
    terms += identity.get("country") or []
    terms += identity.get("instance_of") or []
    return [t for t in terms if t][:14]


def search_hint(identity: dict) -> str:
    """Extra words added to web searches to keep results on the right subject."""
    return "alliance treaty member states"


SPEC = EntitySpec(
    name="alliance",
    label="Alliance or bloc",
    plural="Alliances & blocs",
    pages=(
        "overview",
        "everything",
        "profile",
        "news",
        "members",
        "record",
        "network",
        "sources",
        "notes",
    ),
    type_hints=("Q245065", "Q7278", "Q43229"),
    description_hints=(
        "alliance",
        "intergovernmental organization",
        "military alliance",
        "trade bloc",
        "union",
    ),
    context_terms=context_terms,
    search_hint=search_hint,
    accent="#8fd0d8",
    blurb="NATO, the EU, BRICS and the like: who is in, what binds them, and where they split.",
    order=60,
)
