"""Sources page.

Everything this dossier rests on.
"""

from __future__ import annotations

from . import common
from .registry import PageSpec


def build(stored: dict) -> dict:
    return {"blocks": [common.sources_block(stored)]}


SPEC = PageSpec(
    name="sources",
    label="Sources",
    build=build,
    blurb="Everything this dossier rests on.",
)
