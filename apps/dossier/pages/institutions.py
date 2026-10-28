"""Institutions page.

The bodies that hold the power.
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
                    "assembly",
                    "senate",
                    "court",
                    "council",
                    "commission",
                    "ministry",
                    "bank",
                    "army",
                ],
            ),
        ]
    }


SPEC = PageSpec(
    name="institutions",
    label="Institutions",
    build=build,
    blurb="The bodies that hold the power.",
)
