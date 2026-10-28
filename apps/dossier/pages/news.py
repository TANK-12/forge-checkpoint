"""News page.

Five years of dated news naming this subject, newest first.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    block = common.news_block(stored)
    if not block["total"]:
        return {
            "blocks": [
                common.empty_hint(
                    "No news held yet. A research pass, or Fill in history on the "
                    "Watch tab, matches this subject against five years of "
                    "Wikipedia's Current Events."
                )
            ]
        }
    return {
        "blocks": [
            block,
            common.empty_hint(
                "Archive items are Wikipedia's Current Events summaries, linked to "
                "this subject by its article title and filed as reported, not "
                "verified. Each one names the outlets it came from."
            ),
        ]
    }


SPEC = PageSpec(
    name="news",
    label="News",
    build=build,
    blurb="Five years of dated news naming this subject, newest first.",
)
