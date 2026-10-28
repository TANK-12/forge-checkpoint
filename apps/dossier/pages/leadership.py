"""Leadership page.

Who runs it.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {
        "blocks": [
            common.relations_block(stored),
            common.claims_block(
                stored,
                contains=[
                    "lead",
                    "chair",
                    "chief",
                    "head",
                    "director",
                    "founder",
                    "president",
                    "appoint",
                    "succeed",
                ],
            ),
        ]
    }


SPEC = PageSpec(
    name="leadership", label="Leadership", build=build, blurb="Who runs it."
)
