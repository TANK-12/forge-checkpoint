"""Economy & society page.

Published indicators with a year attached - GDP, unemployment, inflation,
inequality, life expectancy, military spending, government debt.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {
        "blocks": [
            common.timeline_block(stored, kinds=["indicator"], limit=400),
            common.empty_hint(
                "Figures come from the World Bank, which publishes them - so they "
                "are treated as primary sources rather than as reporting. Each one "
                "links to the series it came from."
            ),
            common.claims_block(
                stored,
                contains=[
                    "econom",
                    "gdp",
                    "unemploy",
                    "inflation",
                    "budget",
                    "debt",
                    "tax",
                    "trade",
                    "growth",
                    "recession",
                    "poverty",
                    "wage",
                ],
            ),
        ]
    }


SPEC = PageSpec(
    name="economy",
    label="Economy & society",
    build=build,
    blurb="Published indicators, dated, with the political claims that touch them.",
)
