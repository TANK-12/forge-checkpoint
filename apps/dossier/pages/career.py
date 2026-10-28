"""Career & offices page.

Roles held, with dates.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {
        "blocks": [
            common.timeline_block(stored, kinds=["office", "life"]),
            common.claims_block(
                stored,
                contains=[
                    "elect",
                    "appoint",
                    "serv",
                    "office",
                    "minister",
                    "chancellor",
                    "president",
                    "resign",
                    "chief executive",
                    "chair",
                ],
            ),
        ]
    }


SPEC = PageSpec(
    name="career",
    label="Career & offices",
    build=build,
    blurb="Roles held, with dates.",
)
