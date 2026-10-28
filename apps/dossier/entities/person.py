"""Person dossiers.

Politicians, officials, executives and other public figures.
"""

from __future__ import annotations

from .registry import EntitySpec


def context_terms(identity: dict) -> list[str]:
    """Terms that tell this subject apart from anything with a similar name."""
    terms = []
    terms += identity.get("occupation") or []
    terms += identity.get("party") or []
    terms += identity.get("citizenship") or []
    terms += identity.get("employer") or []
    for entry in (identity.get("positions") or [])[:6]:
        terms.append(entry)
    return [t for t in terms if t][:14]


def search_hint(identity: dict) -> str:
    """Extra words added to web searches to keep results on the right subject."""
    bits = (identity.get("occupation") or [])[:1] + (identity.get("citizenship") or [])[
        :1
    ]
    return " ".join(bits)


SPEC = EntitySpec(
    name="person",
    label="Person",
    plural="People",
    pages=(
        "overview",
        "everything",
        "profile",
        "news",
        "career",
        "words",
        "positions",
        "record",
        "network",
        "sources",
        "notes",
    ),
    type_hints=("Q5",),
    description_hints=(
        "politician",
        "president",
        "minister",
        "chancellor",
        "senator",
        "chief executive",
        "businessman",
        "businesswoman",
        "economist",
        "diplomat",
    ),
    context_terms=context_terms,
    search_hint=search_hint,
    accent="#e0a75e",
    blurb="Politicians, officials, executives and other public figures.",
    order=10,
)
