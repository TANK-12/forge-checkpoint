"""How many independent sources actually stand behind a claim.

This is the number a dossier lives or dies by, so it is computed pessimistically
and by hand rather than asked of a model.

Two rules do the work:

* One story cluster is one reporting act. Forty outlets running the same wire
  copy is one source, not forty. `dedupe.StoryClusterer` supplies the clusters.
* One outlet is one voice. The same newspaper reporting a thing twice on two
  days is still that newspaper, so independence counts distinct domain owners
  across distinct clusters.

Contradictions are surfaced, never resolved. When sources disagree the claim is
marked `disputed` and both sides are kept, because deciding which one is true
is exactly the judgement the user wants to make themselves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "to",
    "in",
    "on",
    "at",
    "for",
    "and",
    "or",
    "is",
    "was",
    "were",
    "be",
    "been",
    "by",
    "with",
    "that",
    "this",
    "as",
    "it",
    "his",
    "her",
    "their",
    "he",
    "she",
    "they",
    "from",
    "has",
    "had",
    "have",
}

AUTHORITATIVE = {"primary", "encyclopedic"}
CLAIM_MATCH_FLOOR = 0.6

NEGATION = re.compile(
    r"\b(not|never|no|denied|denies|rejected|refused|failed to|did ?n[o']t|was ?n[o']t|"
    r"has ?n[o']t|would ?n[o']t|untrue|false)\b",
    re.I,
)
# A figure and the word it measures: "16 years", "890,000 people", "3 seats".
QUANTITY = re.compile(r"\b(\d[\d,.]*)\s+([a-z]{3,})", re.I)


@dataclass
class Evidence:
    """One source's backing for one claim."""

    source_id: str
    cluster_id: str
    domain: str
    tier: str = "unknown"
    relevance: float = 0.0
    span: str = ""
    url: str = ""


@dataclass
class Claim:
    text: str
    evidence: list[Evidence] = field(default_factory=list)
    confidence: str = "unsourced"
    independent: int = 0
    conflicts: list[str] = field(default_factory=list)
    relevance: float = 0.0

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "independent_sources": self.independent,
            "relevance": self.relevance,
            "conflicts": self.conflicts,
            "evidence": [
                {
                    "source_id": e.source_id,
                    "cluster_id": e.cluster_id,
                    "domain": e.domain,
                    "tier": e.tier,
                    "relevance": e.relevance,
                    "span": e.span,
                    "url": e.url,
                }
                for e in self.evidence
            ],
        }


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def independent_sources(evidence: list[Evidence]) -> int:
    """Distinct voices, after syndication and repeat-reporting collapse.

    Each story cluster contributes at most one voice, identified by the domain
    that carried it; the same domain appearing in several clusters still
    contributes one.
    """
    voices: set[str] = set()
    by_cluster: dict[str, list[Evidence]] = {}
    for e in evidence:
        by_cluster.setdefault(e.cluster_id or e.source_id, []).append(e)
    for members in by_cluster.values():
        # Prefer an authoritative member as the cluster's representative.
        best = sorted(
            members,
            key=lambda e: (e.tier not in AUTHORITATIVE, -e.relevance),
        )[0]
        voices.add(best.domain or best.source_id)
    return len(voices)


def detect_conflicts(claim: Claim) -> list[str]:
    """Do the supporting spans disagree with each other?

    Deterministic and deliberately narrow: a negation on one side but not the
    other, or two different numbers where a claim only allows one. Anything
    subtler is left to the model pass, which can only ever add to this list.
    """
    spans = [e.span for e in claim.evidence if e.span]
    if len(spans) < 2:
        return []
    notes: list[str] = []
    negated = [bool(NEGATION.search(s)) for s in spans]
    if any(negated) and not all(negated):
        notes.append("some sources negate what others assert")
    # Compare like with like. Two spans disagree only when they give different
    # numbers of THE SAME THING - "16 years" against "18 years". An incidental
    # year in one span and a duration in another are not a disagreement, and
    # treating them as one produced false "disputed" verdicts on claims every
    # source actually agreed about.
    measured: list[dict[str, set[str]]] = []
    for span in spans:
        found: dict[str, set[str]] = {}
        for number, unit in QUANTITY.findall(span):
            found.setdefault(unit.lower().rstrip("s"), set()).add(
                number.replace(",", "").rstrip(".")
            )
        measured.append(found)
    for i, a in enumerate(measured):
        for b in measured[i + 1 :]:
            for unit in set(a) & set(b):
                if not (a[unit] & b[unit]):
                    notes.append(
                        f"sources give different figures for {unit}: "
                        f"{'/'.join(sorted(a[unit]))} against {'/'.join(sorted(b[unit]))}"
                    )
                    return notes
    return notes


def grade(claim: Claim) -> Claim:
    """Assign the confidence tier. Conflicts outrank everything else."""
    claim.independent = independent_sources(claim.evidence)
    claim.conflicts = list(dict.fromkeys(claim.conflicts + detect_conflicts(claim)))
    has_authoritative = any(e.tier in AUTHORITATIVE for e in claim.evidence)

    if claim.conflicts:
        claim.confidence = "disputed"
    elif not claim.evidence:
        claim.confidence = "unsourced"
    elif claim.independent >= 2 and (has_authoritative or claim.independent >= 3):
        claim.confidence = "verified"
    elif claim.independent >= 1:
        claim.confidence = "reported"
    else:
        claim.confidence = "unsourced"
    if claim.evidence:
        claim.relevance = round(max(e.relevance for e in claim.evidence), 3)
    return claim


def merge_claims(raw: list[Claim]) -> list[Claim]:
    """Fold restatements of the same fact together so the dossier says a thing
    once, with all of its backing, instead of five times."""
    merged: list[Claim] = []
    for claim in raw:
        for existing in merged:
            if similarity(claim.text, existing.text) >= CLAIM_MATCH_FLOOR:
                existing.evidence.extend(claim.evidence)
                existing.conflicts.extend(claim.conflicts)
                if len(claim.text) < len(existing.text):
                    existing.text = claim.text
                break
        else:
            merged.append(claim)
    return [grade(c) for c in merged]
