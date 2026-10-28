"""In depth page.

The whole encyclopedia article, section by section.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    block = common.article_block(stored)
    if not block["sections"]:
        return {
            "blocks": [
                common.empty_hint(
                    "No article held yet. A research pass, or Fill in history on "
                    "the Watch tab, pulls the full Wikipedia article."
                )
            ]
        }
    return {"blocks": [block]}


SPEC = PageSpec(
    name="profile",
    label="In depth",
    build=build,
    blurb="The whole encyclopedia article, section by section.",
)
