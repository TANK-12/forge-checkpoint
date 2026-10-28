"""How it works page.

The mechanics of governing.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {
        "blocks": [
            common.facts_block(
                stored,
                [
                    ("description", "In short"),
                    ("country", "Country"),
                    ("instance_of", "Type"),
                ],
            ),
            common.claims_block(
                stored,
                contains=[
                    "parliament",
                    "chamber",
                    "elect",
                    "term",
                    "vote",
                    "constitution",
                    "law",
                    "court",
                    "appoint",
                    "dissolv",
                    "majority",
                    "veto",
                ],
            ),
        ]
    }


SPEC = PageSpec(
    name="how_it_works",
    label="How it works",
    build=build,
    blurb="The mechanics of governing.",
)
