"""Overview page.

Who this is, and the timeline.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    blocks = [
        common.facts_block(
            stored,
            [
                ("description", "In short"),
                ("occupation", "Occupation"),
                ("party", "Party"),
                ("citizenship", "Country"),
                ("ideology", "Ideology"),
                ("industry", "Industry"),
                ("birth", "Born"),
                ("death", "Died"),
                ("inception", "Founded"),
                ("seats", "Seats"),
                ("employer", "Employer"),
                ("prominence", "Language Wikipedias"),
            ],
        ),
    ]
    blocks.append(common.seats_block(stored))
    blocks.append(common.rich_facts_block(stored))
    summary = (stored.get("subject") or {}).get("identity", {}).get("summary")
    if summary:
        blocks.append(common.prose(summary))
    # News has its own page; mixed in here it would bury the offices and dates.
    blocks.append(common.timeline_block(stored, exclude=["news"]))
    if not (stored.get("timeline") or []):
        blocks.append(
            common.empty_hint(
                "No dated events yet. Run a research pass to build the timeline."
            )
        )
    return {"blocks": blocks}


SPEC = PageSpec(
    name="overview",
    label="Overview",
    build=build,
    blurb="Who this is, and the timeline.",
)
