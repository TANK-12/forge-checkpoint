"""Network page.

Who and what this connects to.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {"blocks": [common.relations_block(stored)]}


SPEC = PageSpec(
    name="network", label="Network", build=build, blurb="Who and what this connects to."
)
