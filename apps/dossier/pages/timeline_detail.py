"""Course of events page.

Everything dated, in order.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {"blocks": [common.timeline_block(stored, limit=1000)]}


SPEC = PageSpec(
    name="timeline_detail",
    label="Course of events",
    build=build,
    blurb="Everything dated, in order.",
)
