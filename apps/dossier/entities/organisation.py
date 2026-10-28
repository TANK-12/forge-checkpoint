"""Company or organisation dossiers.

Leadership, ownership, filings, lobbying and political donations where they can be sourced.
"""

from __future__ import annotations

from .registry import EntitySpec


def context_terms(identity: dict) -> list[str]:
    """Terms that tell this subject apart from anything with a similar name."""
    terms = []
    terms += identity.get("industry") or []
    terms += identity.get("country") or []
    terms += identity.get("instance_of") or []
    return [t for t in terms if t][:14]


def search_hint(identity: dict) -> str:
    """Extra words added to web searches to keep results on the right subject."""
    industry = (identity.get("industry") or [""])[0]
    return f"company {industry}".strip()


SPEC = EntitySpec(
    name="organisation",
    label="Company or organisation",
    plural="Companies & organisations",
    pages=(
        "overview",
        "everything",
        "profile",
        "news",
        "leadership",
        "filings",
        "record",
        "network",
        "sources",
        "notes",
    ),
    type_hints=("Q4830453", "Q783794", "Q43229"),
    description_hints=(
        "company",
        "corporation",
        "organization",
        "organisation",
        "nonprofit",
        "think tank",
        "lobby",
    ),
    context_terms=context_terms,
    search_hint=search_hint,
    accent="#e08f7f",
    blurb="Leadership, ownership, filings, lobbying and political donations where they can be sourced.",
    order=50,
)
