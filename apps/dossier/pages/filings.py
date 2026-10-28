"""Filings page.

Primary documents, filed under legal obligation.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {
        "blocks": [
            common.timeline_block(stored, kinds=["filing"]),
            common.empty_hint(
                "SEC filings are treated as primary sources: a company is legally answerable "
                "for what it files, which is why these weigh heavily in corroboration."
            ),
        ]
    }


SPEC = PageSpec(
    name="filings",
    label="Filings",
    build=build,
    blurb="Primary documents, filed under legal obligation.",
)
