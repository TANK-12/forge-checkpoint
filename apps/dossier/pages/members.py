"""Members page.

Who is in, and on what terms.
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
                    "member",
                    "join",
                    "accede",
                    "withdraw",
                    "leave",
                    "expel",
                    "treaty",
                    "signator",
                ],
            ),
        ]
    }


SPEC = PageSpec(
    name="members", label="Members", build=build, blurb="Who is in, and on what terms."
)
