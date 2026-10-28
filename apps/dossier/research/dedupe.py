"""Collapsing reprints of one story into one story.

A wire report from Reuters or AP is republished verbatim by dozens of outlets.
Left alone that produces a dossier that says the same thing forty times, and -
worse - a corroboration count of forty for what is really a single reporting
act. Everything here is deterministic; no model is involved.

SimHash gives a 64-bit fingerprint where similar documents differ in only a few
bits, so near-duplicates are found without comparing every pair of full texts.
A Jaccard check on the shingle sets confirms each match, because SimHash alone
will occasionally put two short unrelated documents close together.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

WORD = re.compile(r"[a-z0-9']+")
SHINGLE_SIZE = 5
# SimHash is only a prefilter to avoid comparing every pair of full texts;
# on short articles a one-word edit can move a surprising number of bits, so
# the gate is generous and Jaccard below makes the real decision.
HAMMING_LIMIT = 20
JACCARD_FLOOR = 0.5


def normalize(text: str) -> list[str]:
    return WORD.findall((text or "").lower())


def shingles(text: str, k: int = SHINGLE_SIZE) -> set[str]:
    words = normalize(text)
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def simhash(text: str, k: int = SHINGLE_SIZE) -> int:
    """64-bit fingerprint. Identical text gives an identical hash; a changed
    headline or an added byline moves it by only a bit or two."""
    grams = shingles(text, k)
    if not grams:
        return 0
    vector = [0] * 64
    for gram in grams:
        h = int.from_bytes(
            hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest(), "big"
        )
        for bit in range(64):
            vector[bit] += 1 if (h >> bit) & 1 else -1
    out = 0
    for bit in range(64):
        if vector[bit] > 0:
            out |= 1 << bit
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


@dataclass
class Cluster:
    """One reporting act, however many outlets carried it."""

    cluster_id: str
    fingerprint: int
    grams: set[str] = field(repr=False, default_factory=set)
    members: list[dict] = field(default_factory=list)

    @property
    def domains(self) -> set[str]:
        return {m.get("domain", "") for m in self.members if m.get("domain")}

    @property
    def lead(self) -> dict:
        """The member we treat as the canonical copy: earliest published, and
        failing that the first one we saw."""
        dated = [m for m in self.members if m.get("published")]
        if dated:
            return min(dated, key=lambda m: m["published"])
        return self.members[0]


class StoryClusterer:
    """Add documents one at a time; each lands in a new or existing cluster."""

    def __init__(
        self, hamming_limit: int = HAMMING_LIMIT, jaccard_floor: float = JACCARD_FLOOR
    ):
        self.hamming_limit = hamming_limit
        self.jaccard_floor = jaccard_floor
        self.clusters: list[Cluster] = []

    def add(self, doc: dict) -> Cluster:
        """`doc` needs `text`; `url`, `domain`, `title` and `published` are
        carried through untouched. Returns the cluster it joined."""
        text = doc.get("text") or doc.get("title") or ""
        fp = simhash(text)
        grams = shingles(text)
        for cluster in self.clusters:
            if hamming(fp, cluster.fingerprint) > self.hamming_limit:
                continue
            if jaccard(grams, cluster.grams) < self.jaccard_floor:
                continue
            cluster.members.append(doc)
            return cluster
        cluster = Cluster(
            cluster_id=f"c{len(self.clusters) + 1:04d}",
            fingerprint=fp,
            grams=grams,
            members=[doc],
        )
        self.clusters.append(cluster)
        return cluster

    def independent_domains(self) -> int:
        return len({d for c in self.clusters for d in c.domains})

    def summary(self) -> dict:
        total = sum(len(c.members) for c in self.clusters)
        return {
            "documents": total,
            "clusters": len(self.clusters),
            "duplicates_collapsed": total - len(self.clusters),
        }
