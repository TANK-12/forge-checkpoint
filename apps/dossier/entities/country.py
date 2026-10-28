"""Country dossiers.

Current officeholders, election calendar and recent political events. Links its people and parties.
"""

from __future__ import annotations

from .registry import EntitySpec


def context_terms(identity: dict) -> list[str]:
    """Terms that tell this subject apart from anything with a similar name."""
    terms = [
        "government",
        "president",
        "prime minister",
        "parliament",
        "election",
    ]
    terms += identity.get("instance_of") or []
    return [t for t in terms if t][:14]


def search_hint(identity: dict) -> str:
    """Extra words added to web searches to keep results on the right subject."""
    return "government politics"


SPEC = EntitySpec(
    name="country",
    label="Country",
    plural="Countries",
    pages=(
        "overview",
        "everything",
        "profile",
        "news",
        "government",
        "economy",
        "society",
        "elections",
        "record",
        "network",
        "sources",
        "notes",
    ),
    type_hints=("Q6256", "Q3624078"),
    description_hints=("country", "sovereign state", "republic", "kingdom"),
    context_terms=context_terms,
    search_hint=search_hint,
    accent="#d98fd0",
    blurb="Current officeholders, election calendar and recent political events. Links its people and parties.",
    order=40,
)
