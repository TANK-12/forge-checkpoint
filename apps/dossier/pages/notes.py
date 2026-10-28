"""Your notes page.

Yours. Nothing automatic ever writes here.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {
        "blocks": [
            common.notes_block(stored),
            common.empty_hint(
                "This page is never written to by the research pipeline or by any model. "
                "Opinions, plans and working-out belong here, kept apart from the sourced record."
            ),
        ]
    }


SPEC = PageSpec(
    name="notes",
    label="Your notes",
    build=build,
    blurb="Yours. Nothing automatic ever writes here.",
)
