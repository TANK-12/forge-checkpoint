"""Elections page.

How and when power changes hands.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {
        "blocks": [
            common.timeline_block(stored, kinds=["office", "coverage"]),
            common.claims_block(
                stored,
                contains=[
                    "election",
                    "elected",
                    "vote",
                    "poll",
                    "ballot",
                    "referendum",
                    "turnout",
                    "coalition",
                    "majority",
                ],
            ),
        ]
    }


SPEC = PageSpec(
    name="elections",
    label="Elections",
    build=build,
    blurb="How and when power changes hands.",
)
