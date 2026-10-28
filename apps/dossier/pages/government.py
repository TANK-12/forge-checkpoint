"""Government page.

Who currently holds office.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {
        "blocks": [
            common.facts_block(
                stored, [("description", "In short"), ("instance_of", "Type")]
            ),
            common.relations_block(stored),
            common.claims_block(
                stored,
                contains=[
                    "president",
                    "prime minister",
                    "chancellor",
                    "government",
                    "cabinet",
                    "ruling",
                    "leader",
                ],
            ),
        ]
    }


SPEC = PageSpec(
    name="government",
    label="Government",
    build=build,
    blurb="Who currently holds office.",
)
