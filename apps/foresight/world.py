"""Everything that is known, behind one object the solvers and the chat share.

The rules tier and the model tiers need exactly the same material — what is in
Dossier's library, what signals have been gathered, what is moving. Putting it
behind one object means a question answered by arithmetic and the same question
answered by a model are looking at the identical facts, so their answers can be
compared honestly.

Nothing here calls a model. It is all reads off the drive.
"""

from __future__ import annotations

import re
from pathlib import Path

import dossier_link
import store
import sweep

# Words too common to identify anything. Matching a subject called "The
# Times" on the word "the" would be worse than matching nothing at all.
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "what",
    "who",
    "how",
    "why",
    "when",
    "where",
    "many",
    "much",
    "about",
    "tell",
    "show",
    "state",
    "states",
    "party",
    "war",
    "new",
    "national",
    "people",
    "world",
    "union",
    "great",
    "north",
    "south",
    "east",
    "west",
}
_STOPWORDS |= {
    # Compared against STEMS now, so "states" is covered by "state". These are
    # the words a question is built from rather than words that name anything.
    "held",
    "have",
    "change",
    "moving",
    "trending",
    "important",
    "recent",
}


def _stem(word: str) -> str:
    """Crude singular. Enough for the way people actually type.

    "chinas population" was refused outright: the library calls that subject
    "People's Republic of China", so the full-name pass cannot see it, and the
    only distinctive token left to match on is "china" -- while the question
    offered "chinas". A trailing s was the whole difference between a question
    that works and one that is turned away.
    """
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    # "-es" only comes off after a sibilant, which is where English actually
    # adds it: boxes, churches, kisses. Taking it off everything turned
    # "peoples" into "peopl", which stopped matching the stopword "people" and
    # quietly broke "chinas population" a second time -- the library calls that
    # subject "People's Republic of China".
    if (
        len(word) > 4
        and word.endswith("es")
        and word[:-2].endswith(("s", "x", "z", "ch", "sh"))
    ):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokens(text: str) -> set[str]:
    """Content words of a phrase, stemmed, with the useless ones dropped.

    Apostrophes are stripped rather than split on, so "china's" and "chinas"
    both arrive as "china".
    """
    flat = (text or "").lower().replace("\u2019", "").replace("'", "")
    return {
        _stem(w)
        for w in re.findall(r"[a-z0-9]+", flat)
        if len(w) >= 4 and _stem(w) not in _STOPWORDS
    }


def match_subject(rows: list[dict], text: str) -> dict | None:
    """Which stored subject a sentence is about, or None.

    Two passes, and the second one matters as much as the first.

    FULL NAME, longest first, so "Donald Trump" wins over "Donald" and a
    question about the European Union does not match "Europe".

    Then SURNAME, or any distinctive word of a name, because that is how people
    actually type. The library holds "Donald Trump"; the question was "trump",
    and with only the first pass it was turned away -- which is most of why the
    rules tier felt useless. Ties go to whichever subject Dossier holds the
    most about, so "trump" reaches the person rather than a company named after
    him.

    A module-level function rather than a method so the tests can drive the
    real rule instead of a stub reimplementing it, which is how the stub and
    the app drifted apart once already.
    """
    low = (text or "").lower()
    best = None
    for row in rows:
        name = (row.get("name") or "").lower()
        if len(name) < 3 or name not in low:
            continue
        if best is None or len(name) > len(best.get("name", "")):
            best = row
    if best is not None:
        return best

    asked = _tokens(low)
    if not asked:
        return None
    scored = None
    for row in rows:
        tokens = _tokens(row.get("name") or "")
        overlap = tokens & asked
        if not tokens or not overlap:
            continue
        # A single incidental word must not drag a subject in. "What is the
        # meaning of life" matched a company called Orange Life Insurance on
        # the word "life" -- a confident, irrelevant, correct-looking answer,
        # which is the worst thing this tier can do. So the overlap has to be
        # most of the QUESTION and most of the NAME, not one word of either.
        if len(overlap) < len(asked) / 2 or len(overlap) < len(tokens) / 2:
            continue
        held = (row.get("sources") or 0) + (row.get("timeline") or 0)
        score = (len(overlap), held)
        if scored is None or score > scored[0]:
            scored = (score, row)
    return scored[1] if scored else None


class World:
    """A read-only view over Dossier's library and Foresight's own signals."""

    def __init__(self, root: Path | None = None):
        self.root = root

    # --- counting -----------------------------------------------------------

    def coverage(self) -> dict:
        rows = dossier_link.library()
        watched = store.subjects_with_signals(self.root)
        sources = set()
        points = 0
        for slug in watched:
            for source in store.sources_for(slug, self.root):
                sources.add(source)
                points += len(store.read_series(slug, source, self.root))
        return {
            "subjects": len(rows),
            "watched": len(watched),
            "sources": len(sources),
            "points": points,
            "dossier_available": dossier_link.available(),
        }

    # --- finding things -----------------------------------------------------

    def findings(self, limit: int = 40) -> list[dict]:
        return sweep.all_findings(self.root, limit=limit)

    def find_subject(self, text: str) -> dict | None:
        """Which subject in Dossier's library this question is about."""
        return match_subject(dossier_link.library(), text)

    def findings_for(self, slug: str, name: str) -> list[dict]:
        """What is moving for ONE subject, rather than for the whole library."""
        return sweep.findings_for(slug, name, self.root)

    def subject_facts(self, slug: str) -> dict:
        """The plain stored facts about one subject, as Dossier keyed them.

        These come straight off Wikidata through Dossier's harvest -- a little
        over a hundred properties, each one a label like "Population" or "Head
        of government" against a value. Nothing here is derived or guessed, so
        a solver handing one back is quoting the library rather than answering
        a question, which is exactly what the rules tier is for.
        """
        stored = dossier_link.subject(slug)
        identity = (stored.get("subject") or {}).get("identity") or {}
        skip = {"candidates", "qid", "label", "aliases", "context_hint"}
        return {
            k: v
            for k, v in identity.items()
            if k not in skip and v not in (None, "", [], {})
        }

    def ranked(self, limit: int = 12, entity_types: tuple[str, ...] = ()) -> list[dict]:
        """The library ordered by how consequential each subject is."""
        return dossier_link.ranked(limit=limit, entity_types=entity_types)

    def subject_summary(self, slug: str, name: str) -> dict:
        """Everything held about one subject, counted rather than described."""
        stored = dossier_link.subject(slug)
        lines = [f"{name}:"]
        evidence: list[dict] = []

        if stored:
            identity = (stored.get("subject") or {}).get("identity") or {}
            description = identity.get("description") or ""
            if description:
                lines.append(f"  {description}")
            lines.append(
                f"  Dossier holds {len(stored.get('sources') or [])} sources, "
                f"{len(stored.get('claims') or [])} claims, "
                f"{len(stored.get('timeline') or [])} dated events and "
                f"{len(stored.get('quotes') or [])} quotes."
            )
            notes = (stored.get("notes") or {}).get("markdown") or ""
            if notes.strip():
                lines.append(f"  You have written {len(notes.split())} words of notes.")
        else:
            lines.append("  No dossier held - Dossier has not researched this yet.")

        sources = store.sources_for(slug, self.root)
        if not sources:
            lines.append("  No signals gathered yet.")
        for source in sources:
            series = store.read_series(slug, source, self.root)
            if not series:
                continue
            latest = series[-1]
            lines.append(
                f"  {source}: {len(series)} readings, latest {latest.get('value')} "
                f"on {latest.get('date')}"
            )
            evidence.append({"source": source, "points": series[-14:]})

        found = sweep.findings_for(slug, name, self.root)
        for item in found:
            lines.append(f"  ! {item['headline']} — {item['detail']}")
        evidence.extend(found)

        return {"text": "\n".join(lines), "evidence": evidence}

    # --- what a model should be shown ---------------------------------------

    def context_for(self, question: str, budget_chars: int = 12000) -> str:
        """The stored material most relevant to a question, as plain text.

        Retrieval rather than a giant context window: the machine has no swap
        and the KV cache is what eats memory, so a relevant slice is assembled
        instead of everything. Until embeddings land this is name matching plus
        whatever is currently moving, which is already most of what matters.
        """
        parts: list[str] = []
        hit = self.find_subject(question)
        if hit:
            parts.append(self.subject_summary(hit["slug"], hit["name"])["text"])
        movers = self.findings(limit=10)
        if movers:
            parts.append("Currently moving:")
            parts.extend(f"  {m['headline']} — {m['detail']}" for m in movers)
        stats = self.coverage()
        parts.append(
            f"Library: {stats['subjects']} subjects, {stats['watched']} watched, "
            f"{stats['points']} readings."
        )
        text = "\n".join(parts)
        return text[:budget_chars]
