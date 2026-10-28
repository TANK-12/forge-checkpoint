"""Platform page.

What the party says it stands for.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {
        "blocks": [
            common.seats_block(stored),
            common.facts_block(
                stored,
                [
                    ("ideology", "Ideology"),
                    ("seats", "Seats"),
                    ("country", "Country"),
                    ("inception", "Founded"),
                ],
            ),
            common.claims_block(
                stored,
                contains=[
                    "polic",
                    "platform",
                    "manifesto",
                    "pledg",
                    "propos",
                    "support",
                    "oppose",
                    "reform",
                ],
            ),
        ]
    }


SPEC = PageSpec(
    name="platform",
    label="Platform",
    build=build,
    blurb="What the party says it stands for.",
)
