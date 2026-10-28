"""Everything page.

Every record held on this subject in one place, with nothing cut off.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {
        "blocks": [
            common.pictures_block(stored),
            common.rich_facts_block(stored),
            common.seats_block(stored),
            common.article_block(stored),
            common.news_block(stored),
            common.timeline_block(stored, exclude=["news", "coverage"], limit=0),
            common.claims_block(stored, limit=0),
            common.quotes_block(stored, limit=0),
            common.relations_block(stored),
            common.source_texts_block(stored),
            common.notes_block(stored),
        ]
    }


SPEC = PageSpec(
    name="everything",
    label="Everything",
    build=build,
    blurb="Every record held on this subject in one place, including the saved "
    "text of each source.",
)
