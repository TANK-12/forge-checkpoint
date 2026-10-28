"""In their own words page.

Verbatim quotes, with citations.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {
        "blocks": [
            common.quotes_block(stored),
            common.empty_hint(
                "Quotes come from Wikiquote, which pairs each one with its citation. "
                "A quote with no citation is shown but marked as uncited."
            ),
        ]
    }


SPEC = PageSpec(
    name="words",
    label="In their own words",
    build=build,
    blurb="Verbatim quotes, with citations.",
)
