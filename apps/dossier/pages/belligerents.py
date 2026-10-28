"""Belligerents page.

Who is fighting, and alongside whom.
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
                    "forces",
                    "troops",
                    "army",
                    "attack",
                    "offensive",
                    "defen",
                    "ally",
                    "backed",
                    "supplied",
                    "casualt",
                    "killed",
                    "ceasefire",
                ],
            ),
        ]
    }


SPEC = PageSpec(
    name="belligerents",
    label="Belligerents",
    build=build,
    blurb="Who is fighting, and alongside whom.",
)
