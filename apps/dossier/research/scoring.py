"""How related is this thing to this person, as a number.

Every source and every claim carries a relevance between 0 and 1 rather than a
yes/no flag, so the dossier can be read at any strictness with a slider instead
of being re-crawled. The score is a weighted blend of content signals, then
multiplied by factors that can only ever reduce it: an untrustworthy source
tier, and - the one that matters most - the suspicion that this is a different
person who happens to share the name.

Every score returns its own breakdown, so the interface can answer "why 0.42?"
instead of asking to be trusted.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime

# What kind of source this is, and how much that alone is worth.
TIER_WEIGHT = {
    "primary": 1.0,  # the person's own filing, transcript, vote record
    "encyclopedic": 1.0,  # Wikipedia, Wikidata, Wikiquote
    "major": 0.95,  # established news organisation
    "regional": 0.88,
    "aggregator": 0.78,  # syndicators, news portals
    "unknown": 0.62,
}

WEIGHTS = {
    "title": 0.32,
    "density": 0.20,
    "prominence": 0.14,
    "agency": 0.12,
    "context": 0.22,
}

# Words that suggest the name is doing something rather than being listed.
_VERBISH = {
    "said",
    "says",
    "told",
    "argued",
    "claimed",
    "announced",
    "denied",
    "wrote",
    "voted",
    "signed",
    "met",
    "warned",
    "called",
    "urged",
    "accused",
    "added",
    "confirmed",
    "rejected",
    "backed",
    "promised",
    "won",
    "lost",
    "resigned",
    "became",
    "has",
    "had",
    "was",
    "were",
    "is",
    "will",
    "would",
    "did",
    "does",
}


@dataclass
class SubjectProfile:
    """Who we are scoring against, and what tells them apart from namesakes."""

    name: str
    aliases: list[str] = field(default_factory=list)
    context_terms: list[str] = field(
        default_factory=list
    )  # party, office, country, employer
    birth_year: int | None = None

    @property
    def surname(self) -> str:
        bits = [b for b in re.split(r"\s+", self.name.strip()) if b]
        return bits[-1] if bits else self.name

    @property
    def full_names(self) -> list[str]:
        return [n for n in [self.name, *self.aliases] if n]


@dataclass
class Relevance:
    score: float
    breakdown: dict

    def __float__(self) -> float:
        return self.score


def _count(haystack: str, needle: str) -> int:
    if not needle:
        return 0
    return len(re.findall(rf"\b{re.escape(needle.lower())}\b", haystack))


def _first_position(haystack: str, needles: list[str]) -> float:
    """0.0 = named in the opening words, 1.0 = named only at the very end."""
    hits = [haystack.find(n.lower()) for n in needles]
    hits = [h for h in hits if h >= 0]
    if not hits or not haystack:
        return 1.0
    return min(hits) / max(len(haystack), 1)


def _agency_ratio(text: str, names: list[str]) -> float:
    """Of the times the name appears, how often is it the actor in the
    sentence rather than an item in a list?"""
    total = 0
    acting = 0
    for name in names:
        for m in re.finditer(rf"\b{re.escape(name.lower())}\b", text):
            total += 1
            tail = text[m.end() : m.end() + 40].strip()
            first = re.split(r"[^a-z']+", tail)[0] if tail else ""
            if first in _VERBISH or first.endswith("ed") or first.endswith("'s"):
                acting += 1
    if not total:
        return 0.0
    return acting / total


def score_document(
    doc: dict,
    subject: SubjectProfile,
    tier: str = "unknown",
    today: date | None = None,
) -> Relevance:
    """`doc` carries `title`, `text` and optionally `published` (ISO date)."""
    title = (doc.get("title") or "").lower()
    text = (doc.get("text") or "").lower()
    body = f"{title}\n{text}"
    words = max(len(body.split()), 1)
    names = [n.lower() for n in subject.full_names]

    full_hits = sum(_count(body, n) for n in names)
    surname_hits = _count(body, subject.surname)

    if any(n in title for n in names):
        title_signal = 1.0
    elif subject.surname.lower() in title:
        title_signal = 0.55
    else:
        title_signal = 0.0

    # Saturating: 8 mentions per 1000 words is already unambiguously about them.
    per_k = (full_hits + 0.5 * max(surname_hits - full_hits, 0)) / words * 1000
    density_signal = min(per_k / 8.0, 1.0)

    prominence_signal = 1.0 - _first_position(body, names or [subject.surname.lower()])
    agency_signal = _agency_ratio(body, names or [subject.surname.lower()])

    terms = [t.lower() for t in subject.context_terms if t]
    present = [t for t in terms if t in body]
    if subject.birth_year and str(subject.birth_year) in body:
        present.append(str(subject.birth_year))
    context_signal = min(len(present) / 3.0, 1.0) if terms else 0.5

    base = (
        WEIGHTS["title"] * title_signal
        + WEIGHTS["density"] * density_signal
        + WEIGHTS["prominence"] * prominence_signal
        + WEIGHTS["agency"] * agency_signal
        + WEIGHTS["context"] * context_signal
    )

    # The namesake guard. No distinguishing context at all, and only the
    # surname to go on, is the classic wrong-person article.
    if terms and not present:
        disambiguation = 0.30 if full_hits == 0 else 0.62
    elif full_hits == 0 and surname_hits > 0:
        disambiguation = 0.55
    else:
        disambiguation = 1.0

    tier_factor = TIER_WEIGHT.get(tier, TIER_WEIGHT["unknown"])

    recency = 1.0
    published = doc.get("published")
    if published and tier not in ("encyclopedic", "primary"):
        try:
            when = datetime.fromisoformat(str(published)[:10]).date()
            years = max((today or date.today()) - when, when - when).days / 365.25
            recency = 0.85 + 0.15 * math.exp(-years / 6.0)
        except Exception:
            recency = 1.0

    score = max(0.0, min(1.0, base * disambiguation * tier_factor * recency))
    return Relevance(
        score=round(score, 3),
        breakdown={
            "title": round(title_signal, 3),
            "density": round(density_signal, 3),
            "prominence": round(prominence_signal, 3),
            "agency": round(agency_signal, 3),
            "context": round(context_signal, 3),
            "context_terms_found": present,
            "base": round(base, 3),
            "disambiguation": round(disambiguation, 3),
            "tier": tier,
            "tier_factor": tier_factor,
            "recency": round(recency, 3),
            "mentions": {"full": full_hits, "surname": surname_hits, "words": words},
        },
    )


def score_claim(
    claim_text: str, source_scores: list[float], subject: SubjectProfile
) -> float:
    """A claim inherits from its best source, nudged by whether the claim
    itself actually names the subject."""
    if not source_scores:
        return 0.0
    best = max(source_scores)
    low = (claim_text or "").lower()
    names = [n.lower() for n in subject.full_names]
    if any(n in low for n in names):
        factor = 1.0
    elif subject.surname.lower() in low:
        factor = 0.92
    else:
        factor = 0.8
    return round(max(0.0, min(1.0, best * factor)), 3)
