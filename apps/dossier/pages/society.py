"""Society & development page.

The Economy page answers "how rich is this place". This one answers "what is it
like to live there, and how is it governed" - life expectancy, child mortality,
extreme poverty, urbanisation, the median age, emissions per person, how people
rate their own lives, and the regime classification.

It is its own tab rather than more rows on the Economy page because these are a
different question: a country can be wealthy and short-lived, or poor and
democratic, and stacking both sets in one list buries that. Filtering on the
source is what keeps the two apart without either page needing to know which
indicator codes the other collects.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {
        "blocks": [
            common.timeline_block(
                stored, kinds=["indicator"], source_ids=["owid"], limit=400
            ),
            common.empty_hint(
                "Figures come from Our World in Data, which publishes them - so "
                "they are treated as primary sources rather than as reporting. "
                "Each one links to the chart it was read from. Nothing here has "
                "been through a model."
            ),
            common.claims_block(
                stored,
                contains=[
                    "health",
                    "hospital",
                    "life expectancy",
                    "mortality",
                    "povert",
                    "inequal",
                    "education",
                    "school",
                    "housing",
                    "migrat",
                    "climate",
                    "emission",
                    "energy",
                    "democra",
                    "authoritarian",
                    "corrupt",
                    "human rights",
                ],
            ),
        ]
    }


SPEC = PageSpec(
    name="society",
    label="Society & development",
    build=build,
    blurb="How people live and how the place is governed, dated, from the publisher.",
)
