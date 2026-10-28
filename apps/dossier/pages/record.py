"""Record & disputes page.

Contested items, both sides kept.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    disputed = common.claims_block(stored, confidence=["disputed"])
    # An empty disputed block drew "No claims yet" above a list of real claims.
    blocks = [disputed] if disputed["claims"] else []
    blocks.append(
        common.empty_hint(
            "Disputed claims are shown first and are never resolved automatically - "
            "where sources disagree, both readings are kept so the judgement stays yours."
        )
    )
    blocks.append(common.claims_block(stored, confidence=["verified", "reported"]))
    return {"blocks": blocks}


SPEC = PageSpec(
    name="record",
    label="Record & disputes",
    build=build,
    blurb="Contested items, both sides kept.",
)
