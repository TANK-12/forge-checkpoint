"""Positions on issues page.

Stated stance, and recorded action.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {
        "blocks": [
            common.claims_block(
                stored,
                contains=[
                    "polic",
                    "support",
                    "oppose",
                    "vote",
                    "back",
                    "reject",
                    "propos",
                    "pledg",
                    "promis",
                    "reform",
                    "tax",
                    "immigra",
                    "climate",
                    "defen",
                    "war",
                    "sanction",
                ],
            ),
        ]
    }


SPEC = PageSpec(
    name="positions",
    label="Positions on issues",
    build=build,
    blurb="Stated stance, and recorded action.",
)
