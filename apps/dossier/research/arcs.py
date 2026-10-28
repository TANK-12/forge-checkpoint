"""Country-to-country arcs for the world map.

The map already shades a country by how much is held about it. That answers
"where have I looked", but not "who is tied to whom", which is the question a
map is actually good at. This module turns stored relations into arcs drawn
between countries: who is fighting where, and who sits in a bloc together.

Like `graph.py` this is arithmetic over data already on disk. **No model is
involved and none should be.** An arc asserts something about the world, so it
has to be traceable to a stored relation and the dossier that recorded it - a
model asked which countries are allied would produce a plausible list, and a
plausible list is exactly what this app exists not to produce. Every arc
carries the subjects it came from, so the frontend can name them on hover.

Being model-free also means it runs on the CPU while the iGPU is busy, which is
how the user asked for connection work to be done.

Adding a kind of arc is one entry in `ARC_KINDS` and nothing else. The endpoint
does not name an arc kind, and neither does the frontend beyond colouring them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import dossier
import store

# One conflict can name dozens of participants, and every pair of them is a
# potential arc. Both caps keep a single messy subject from burying the map.
MAX_PARTIES = 8
MAX_ARCS = 600


@dataclass
class ArcKind:
    """One way a subject ties countries together.

    `shape` decides what is drawn:
      "to_place"        each party is joined to where the thing happened, which
                        is what the data actually says - Wikidata's participant
                        list does not record which side anyone was on, so
                        joining two participants to each other would assert a
                        hostility that is not in the record.
      "between_parties" every party joined to every other, for ties that really
                        are symmetric: two states in one bloc are each in it.
    """

    name: str
    label: str
    entity_type: str
    party_relations: tuple[str, ...]
    shape: str = "to_place"
    place_relations: tuple[str, ...] = ()
    reads: str = "linked to"
    blurb: str = ""


ARC_KINDS: dict[str, ArcKind] = {
    "conflict": ArcKind(
        name="conflict",
        label="Conflicts",
        entity_type="conflict",
        party_relations=("participant", "took part in", "involved in"),
        place_relations=("located in", "country"),
        shape="to_place",
        reads="fought in",
        blurb="A country joined to the place a conflict it took part in was fought.",
    ),
    "alliance": ArcKind(
        name="alliance",
        label="Alliances & blocs",
        entity_type="alliance",
        party_relations=("has member", "member of", "part of"),
        shape="between_parties",
        reads="in a bloc with",
        blurb="Two countries recorded as belonging to the same bloc.",
    ),
}


@dataclass
class Arc:
    a: str
    b: str
    kind: str
    reads: str
    via: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "a": self.a,
            "b": self.b,
            "kind": self.kind,
            "reads": self.reads,
            "weight": len(self.via),
            "via": self.via[:12],
        }


def _country_names(rows: list[dict]) -> set[str]:
    """Names that are countries, judged by a dossier saying so.

    A relation target is a bare name, so this is how "Finland" is told apart
    from "social democracy". Held country subjects are the only authority used;
    nothing is guessed from the shape of the word.
    """
    return {
        (row.get("name") or "").strip()
        for row in rows
        if row.get("entity_type") == "country" and row.get("name")
    }


def _targets(relations: list[dict], wanted: tuple[str, ...], countries: set[str]):
    """Country targets of the relations this arc kind cares about, in order."""
    seen: list[str] = []
    for relation in relations:
        if (relation.get("relation") or "") not in wanted:
            continue
        target = (relation.get("target") or "").strip()
        if target in countries and target not in seen:
            seen.append(target)
    return seen


def build(root: Path | None = None) -> list[dict]:
    """Every arc derivable from what is stored, strongest first.

    Arcs merge: two wars fought in the same place by the same country are one
    arc carrying both, so the map shows a thicker line rather than two
    identical ones stacked on each other.
    """
    rows = dossier.library(root)
    countries = _country_names(rows)
    merged: dict[tuple[str, str, str], Arc] = {}

    for row in rows:
        kind = ARC_KINDS.get(row.get("entity_type") or "")
        if kind is None:
            continue
        directory = store.subject_dir(row["slug"], root)
        relations = store.read_json(directory / dossier.FILES["relations"], []) or []
        if not relations:
            continue
        parties = _targets(relations, kind.party_relations, countries)[:MAX_PARTIES]
        if not parties:
            continue

        pairs: list[tuple[str, str]] = []
        if kind.shape == "to_place":
            places = _targets(relations, kind.place_relations, countries)
            if not places:
                continue  # where it happened is not recorded; say nothing
            place = places[0]
            pairs = [(party, place) for party in parties if party != place]
        else:
            pairs = [
                (parties[i], parties[j])
                for i in range(len(parties))
                for j in range(i + 1, len(parties))
            ]

        for a, b in pairs:
            first, second = (a, b) if a <= b else (b, a)
            key = (kind.name, first, second)
            arc = merged.get(key)
            if arc is None:
                arc = Arc(a=first, b=second, kind=kind.name, reads=kind.reads)
                merged[key] = arc
            arc.via.append({"name": row["name"], "slug": row["slug"]})

    ordered = sorted(
        merged.values(), key=lambda arc: (len(arc.via), arc.a), reverse=True
    )
    return [arc.as_dict() for arc in ordered[:MAX_ARCS]]


def kinds() -> list[dict]:
    """What kinds of arc exist, for the frontend's filter. Discovered, not declared."""
    return [
        {"name": k.name, "label": k.label, "reads": k.reads, "blurb": k.blurb}
        for k in ARC_KINDS.values()
    ]
