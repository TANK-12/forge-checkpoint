"""How a question gets answered — and the tier that never asks a model.

Everything in this app that wants an answer asks for a **tier** rather than a
model, and one of the tiers is not a model at all:

    rules    arithmetic and lookups. No model, no network, no Jan.
    chat     the small model. Instant, conversational.
    analyse  the middle model. Triage, summarising, sentiment on the ambiguous band.
    think    the big model, thinking ON, minutes allowed. Scenarios and plans.

The user asked for `rules` directly: "make it so that math and rules can also be
a tier option that doesn't use an LLM to figure stuff out." It is the right
instinct and it is the same discipline that makes Dossier trustworthy — a
z-score cannot hallucinate, costs nothing, runs on the CPU while the iGPU is
busy, and gives the same answer twice. Anything a rule can settle, a rule
should settle.

Two consequences worth stating plainly:

* **The app works with Jan switched off.** Every `rules` answer is available
  with no model server running at all, which is most of what the Signals and
  Findings views show.
* **`prefer_rules` is a real setting.** With it on, a caller asking for a model
  tier gets the rules answer instead whenever a solver can handle the question,
  and is told that is what happened. Nothing silently degrades — the answer
  always says which tier actually produced it.

Solvers are declared here rather than discovered, because unlike sources and
analysers there are only ever a handful and each is a named capability the
interface offers as a button.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Callable

import llm
from signals import registry as sources

RULES = "rules"
MODEL_TIERS = ("chat", "analyse", "think")
ALL_TIERS = (RULES,) + MODEL_TIERS


@dataclass
class Tier:
    name: str
    label: str
    uses_model: bool
    description: str


TIERS = {
    RULES: Tier(
        RULES,
        "Rules & maths",
        False,
        "Arithmetic over what is stored. No model, works with Jan off, and "
        "gives the same answer every time.",
    ),
    "chat": Tier("chat", "Chat", True, "The small model. Instant, conversational."),
    "analyse": Tier(
        "analyse", "Analyse", True, "The middle model. Summarising and judgement."
    ),
    "think": Tier(
        "think",
        "Think hard",
        True,
        "The big model with thinking on, allowed to run for minutes. Scenarios "
        "and plans.",
    ),
}


@dataclass
class Answer:
    """Every answer says which tier produced it and whether a model was used."""

    text: str
    tier: str
    used_model: bool
    reasoning: str = ""
    model: str = ""
    seconds: float = 0.0
    evidence: list = None  # type: ignore[assignment]

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "tier": self.tier,
            "used_model": self.used_model,
            "reasoning": self.reasoning,
            "model": self.model,
            "seconds": self.seconds,
            "evidence": self.evidence or [],
        }


# --- solvers: questions arithmetic can answer on its own --------------------


@dataclass
class Solver:
    name: str
    label: str
    # handles(question) -> bool ; solve(question, world) -> Answer
    handles: Callable[[str], bool]
    solve: Callable[..., Answer]
    description: str = ""
    # A SECOND pass, run only if no keyword matched, and allowed to look at
    # what is actually stored.
    #
    # Keyword matching alone is why this tier used to refuse so much. "trump"
    # contains none of the trigger words, so it was turned away even though the
    # library holds a dossier under exactly that name; "population of
    # australia" was refused with the answer sitting in the subject's own
    # stored facts. A question that names something held is a question this
    # tier can answer, and only the library can say whether it does.
    handles_stored: Callable[..., bool] | None = None


def _has(question: str, *words: str) -> bool:
    """Whole-word matching, which substring matching is not.

    This started as a plain `in` check and routed "should I move to another
    country?" to the coverage solver, because "country" contains "count". A
    solver that grabs the wrong question is worse than one that grabs none:
    the user gets a confident, irrelevant, correct-looking number.
    """
    low = question.lower()
    return any(re.search(rf"\b{re.escape(w)}\b", low) for w in words)


def _today() -> date:
    return date.today()


# Past this many days the newest reading is old news and the answer says so.
STALE_AFTER_DAYS = 7


def _newest_note(findings: list[dict]) -> str:
    """When the freshest reading behind these findings is from, in words.

    "12 subjects are moving" read as news for a month after the last sweep.
    """
    today = _today()
    dated: list[tuple[date, int]] = []  # (reading date, days it stays news)
    fast: list[tuple[date, int]] = []
    for f in findings:
        try:
            when = date.fromisoformat(str(f.get("at") or "")[:10])
        except ValueError:
            continue
        spec = sources.get(str(f.get("source") or "").split(".", 1)[0])
        fresh = spec.fresh_days if spec else STALE_AFTER_DAYS
        dated.append((when, fresh))
        if fresh <= STALE_AFTER_DAYS:
            fast.append((when, fresh))
    if not dated:
        return ""
    newest = max(when for when, _ in dated)
    age = (today - newest).days
    ago = "today" if age <= 0 else f"{age} day{'' if age == 1 else 's'} ago"
    note = f"The newest reading is from {newest.isoformat()} ({ago})."
    # The daily sources decide: one annual figure that is still news (last
    # year's inflation) must not hide a page of month-old spikes. With no
    # daily source in the answer, it is old news only when all of it is.
    judged = fast or dated
    if all((today - when).days > fresh for when, fresh in judged):
        note += " That is old news: sweep the watchlist to see what is moving now."
    return note


def _solve_movers(question: str, world) -> Answer:
    """What is moving right now, straight out of the breakout arithmetic.

    Scoped to a subject when the question names one. "What changed in
    Australia" used to return the whole library's movers and mention Australia
    nowhere, which is an answer to a question nobody asked.
    """
    hit = world.find_subject(question)
    if hit:
        findings = world.findings_for(hit["slug"], hit["name"])
        if not findings:
            summary = world.subject_summary(hit["slug"], hit["name"])
            return Answer(
                f"Nothing is breaking out of its baseline for {hit['name']}. "
                f"Here is what is held:\n{summary['text']}",
                RULES,
                False,
                evidence=summary["evidence"],
            )
        lines = [f"{len(findings)} things are moving for {hit['name']}:"]
        lines.extend(f"  • {f['headline']} — {f['detail']}" for f in findings)
        if note := _newest_note(findings):
            lines.append(note)
        return Answer("\n".join(lines), RULES, False, evidence=findings)

    findings = world.findings(limit=12)
    if not findings:
        return Answer(
            "Nothing has broken out of its baseline yet. Either no signals have "
            "been gathered, or every subject is behaving normally.",
            RULES,
            False,
            evidence=[],
        )
    lines = [f"{len(findings)} subjects are moving unusually:"]
    for f in findings:
        lines.append(f"  • {f['headline']} — {f['detail']}")
    if note := _newest_note(findings):
        lines.append(note)
    return Answer("\n".join(lines), RULES, False, evidence=findings)


def _solve_coverage(question: str, world) -> Answer:
    """How much is actually held — a counting question, so it is counted.

    "How much is held turkey" is a question about Turkey, not about the
    library. If the question names a subject, count that subject.
    """
    hit = world.find_subject(question)
    if hit:
        return _solve_subject(question, world)
    stats = world.coverage()
    text = (
        f"{stats['subjects']} subjects in Dossier's library, "
        f"{stats['watched']} of them with signal series here, across "
        f"{stats['sources']} sources and {stats['points']} readings."
    )
    if not stats["dossier_available"]:
        text += (
            " Dossier's library is not reachable right now — is the drive "
            "plugged in?"
        )
    return Answer(text, RULES, False, evidence=[stats])


def _solve_subject(question: str, world) -> Answer:
    """The numbers held on whichever subject the question names."""
    hit = world.find_subject(question)
    if not hit:
        return Answer(
            "No subject in the library matches that name closely enough to be sure "
            "which one you meant.",
            RULES,
            False,
        )
    summary = world.subject_summary(hit["slug"], hit["name"])
    return Answer(summary["text"], RULES, False, evidence=summary["evidence"])


def _fact_key(question: str, facts: dict) -> str | None:
    """Which stored fact the question is asking for, if any.

    Deliberately matched against the keys THAT SUBJECT ACTUALLY HAS rather than
    a list written here: Dossier harvests a little over a hundred Wikidata
    properties, and hardcoding a second copy of that list would put it out of
    step the first time a property is added. Widening what the rules tier can
    answer is then a Dossier-side change, with nothing to edit here.
    """
    low = question.lower()
    best = None
    for key in facts:
        words = re.findall(r"[a-z]+", key.lower())
        if not words:
            continue
        # every word of the key has to be in the question, so "Head of
        # government" needs both "head" and "government" and does not answer a
        # question that only says "government"
        if all(re.search(rf"\b{re.escape(w)}\b", low) for w in words if len(w) > 2):
            if best is None or len(key) > len(best):
                best = key
    if best:
        return best
    # A few things people say that Wikidata does not call by that name.
    for phrase, key in ALIASES.items():
        if re.search(rf"\b{re.escape(phrase)}\b", low) and key in facts:
            return key
    return None


# Natural phrasings for facts whose stored label is something else. Small on
# purpose: everything that matches its own label is handled above.
ALIASES = {
    "how many people": "Population",
    "how big": "Population",
    "money": "Currency",
    "language": "Official language",
    "languages": "Official language",
    "leader": "Head of government",
    "president": "Head of state",
    "prime minister": "Head of government",
    "born": "birth",
    "died": "death",
    "founded": "inception",
    "when was": "inception",
    "started": "inception",
}


def _render(value) -> str:
    if isinstance(value, list):
        shown = [str(v) for v in value if str(v).strip()]
        if not shown:
            return ""
        if len(shown) > 6:
            return ", ".join(shown[:6]) + f" (and {len(shown) - 6} more)"
        return ", ".join(shown)
    return str(value)


def _solve_fact(question: str, world) -> Answer:
    """One stored fact about one named subject, quoted, not reasoned about."""
    hit = world.find_subject(question)
    if not hit:
        return _solve_subject(question, world)
    facts = world.subject_facts(hit["slug"])
    key = _fact_key(question, facts)
    if not key:
        return _solve_subject(question, world)
    value = _render(facts[key])
    if not value:
        return _solve_subject(question, world)
    text = f"{hit['name']} — {key}: {value}"
    # Say where it came from. A bare figure with no provenance is the thing
    # this whole app exists not to produce.
    if isinstance(facts[key], list) and len(facts[key]) > 1:
        # Wikidata keeps every value a property has ever had, so a list is a
        # record of all of them and not a statement about today. Saying so is
        # cheaper than being quietly wrong about who currently runs a country.
        text += (
            f"\n  Dossier holds {len(facts[key])} recorded values for this; they are "
            "everything Wikidata lists, not only the current one."
        )
    text += "\n  Stored by Dossier from Wikidata; it is a held fact, not a calculation."
    return Answer(
        text,
        RULES,
        False,
        evidence=[
            {"slug": hit["slug"], "name": hit["name"], "key": key, "value": facts[key]}
        ],
    )


# Which entity type a question is asking about, so "the most important
# countries" does not answer with people.
TYPE_WORDS = {
    "countries": "country",
    "country": "country",
    "nations": "country",
    "states": "country",
    "people": "person",
    "person": "person",
    "politicians": "person",
    "leaders": "person",
    "parties": "party",
    "party": "party",
    "companies": "company",
    "company": "company",
    "businesses": "company",
    "wars": "conflict",
    "conflicts": "conflict",
    "war": "conflict",
    "alliances": "alliance",
    "alliance": "alliance",
    "organisations": "organization",
    "organizations": "organization",
}


PLURALS = {"person": "people"}


def _solve_rank(question: str, world) -> Answer:
    """Who matters most, by the same ranking Dossier's own queue uses."""
    low = question.lower()
    wanted = tuple(
        {t for word, t in TYPE_WORDS.items() if re.search(rf"\b{word}\b", low)}
    )
    rows = world.ranked(limit=15, entity_types=wanted)
    if not rows:
        return Answer(
            "Nothing is held to rank yet — Dossier's library reads as empty. "
            "Is the drive plugged in?",
            RULES,
            False,
        )
    singular = wanted[0] if len(wanted) == 1 else "subject"
    plural = PLURALS.get(singular) or (
        (singular[:-1] + "ies") if singular.endswith("y") else (singular + "s")
    )
    lines = [f"The {len(rows)} most consequential {plural} in the library:"]
    for i, row in enumerate(rows, 1):
        held = (row.get("sources") or 0) + (row.get("timeline") or 0)
        detail = row.get("description") or row.get("entity_type") or ""
        lines.append(f"  {i}. {row.get('name')} — {detail} ({held} things held)")
    lines.append(
        "  Ranked by prominence where Dossier recorded it, and by how much is "
        "held otherwise. That is a measure of coverage, not of merit."
    )
    return Answer("\n".join(lines), RULES, False, evidence=rows)


SOLVERS = [
    Solver(
        "movers",
        "What is moving",
        lambda q: _has(
            q,
            "moving",
            "breakout",
            "spike",
            "unusual",
            "what changed",
            "what's new",
            "whats new",
            "trending",
        ),
        _solve_movers,
        "Subjects departing from their own baseline.",
    ),
    Solver(
        "coverage",
        "How much is held",
        lambda q: _has(q, "how many", "how much", "coverage", "library size", "count"),
        _solve_coverage,
        "Counts of subjects, sources and readings.",
    ),
    Solver(
        "rank",
        "Who matters most",
        lambda q: _has(
            q,
            "important",
            "most prominent",
            "most covered",
            "biggest",
            "top",
            "who matters",
            "best known",
            "most connected",
            "most significant",
            "rank",
        ),
        _solve_rank,
        "The library ordered by how consequential each subject is.",
    ),
    Solver(
        "fact",
        "A stored fact",
        # No keyword pass at all: whether this can answer depends entirely on
        # what the named subject has stored, which only the second pass knows.
        lambda q: False,
        _solve_fact,
        "One held fact about a named subject - population, currency, who leads it.",
        handles_stored=lambda q, world: (
            (
                lambda hit: bool(hit)
                and bool(_fact_key(q, world.subject_facts(hit["slug"])))
            )(world.find_subject(q))
        ),
    ),
    Solver(
        "subject",
        "One subject's numbers",
        lambda q: _has(
            q, "about", "tell me", "what do you have on", "who is", "show me"
        ),
        _solve_subject,
        "Everything stored about one named subject.",
        # Naming something held IS the question. This is what makes a bare
        # "trump" work instead of being turned away.
        handles_stored=lambda q, world: world.find_subject(q) is not None,
    ),
]


def solver_for(question: str, world=None) -> Solver | None:
    """Which solver takes this question, keywords first, the library second.

    Two passes rather than one because they answer different questions. The
    keyword pass catches the ways people ask for the arithmetic -- "what is
    moving", "how many". The stored pass catches questions that are only
    answerable because of what happens to be in the library, which no amount of
    keyword matching can know.
    """
    for solver in SOLVERS:
        try:
            if solver.handles(question):
                return solver
        except Exception:
            continue
    if world is None:
        return None
    for solver in SOLVERS:
        if solver.handles_stored is None:
            continue
        try:
            if solver.handles_stored(question, world):
                return solver
        except Exception:
            continue
    return None


def describe() -> list[dict]:
    """What the interface draws for the tier picker."""
    out = []
    for tier in ALL_TIERS:
        spec = TIERS[tier]
        out.append(
            {
                "name": spec.name,
                "label": spec.label,
                "uses_model": spec.uses_model,
                "description": spec.description,
                "solvers": (
                    [
                        {"name": s.name, "label": s.label, "description": s.description}
                        for s in SOLVERS
                    ]
                    if tier == RULES
                    else []
                ),
            }
        )
    return out


# --- answering --------------------------------------------------------------

SYSTEM = (
    "You are Foresight, a local analysis tool. You are talking to the person "
    "who built you, on their own machine. Be concrete and brief. When you are "
    "given stored readings or facts, use them and say what they are; when you "
    "are not, say plainly that you are reasoning without data rather than "
    "inventing figures. Never invent a number, a date or a source."
)


def answer(
    question: str,
    tier: str = RULES,
    world=None,
    prefer_rules: bool = True,
    context: str = "",
) -> Answer:
    """Answer a question at the requested tier.

    With `prefer_rules` on, a model tier still yields to a solver when one can
    handle the question — the cheapest correct answer wins. The returned tier
    always says what actually ran, so a rules answer is never passed off as the
    model's and the other way round.
    """
    question = (question or "").strip()
    if not question:
        return Answer("Ask me something.", RULES, False)

    if tier == RULES or prefer_rules:
        solver = solver_for(question, world)
        if solver is not None and world is not None:
            return solver.solve(question, world)
        if tier == RULES:
            # Say what it CAN do, with the words that work. A refusal that does
            # not teach you the next thing to type is just a dead end.
            return Answer(
                "The rules tier could not settle that one from stored numbers "
                "alone. It can answer:\n"
                '  • a name on its own — "Angela Merkel" — for everything held '
                "about it\n"
                '  • a stored fact — "population of Australia", "currency of '
                'Japan", "head of government of Germany"\n'
                '  • what is moving — "what changed", "what is trending"\n'
                '  • how much is held — "how many subjects"\n'
                '  • what matters most — "who is important", "the biggest '
                'countries"\n'
                "For anything needing judgement, switch to a model tier.",
                RULES,
                False,
            )

    messages = [{"role": "system", "content": SYSTEM}]
    if context:
        messages.append(
            {
                "role": "system",
                "content": "Here is what is actually stored, to reason from:\n"
                + context,
            }
        )
    messages.append({"role": "user", "content": question})
    try:
        result = llm.chat(tier, messages)
    except llm.NotEnoughMemory as e:
        # Say exactly why, and point at the tier that still works.
        return Answer(str(e), tier, False)
    except llm.JanUnavailable as e:
        # Degrade to the truth rather than to a guess.
        return Answer(
            f"Jan is not answering, so no model tier is available ({e}). The "
            "rules tier still works with Jan off.",
            tier,
            False,
        )
    return Answer(
        result["text"],
        tier,
        True,
        reasoning=result["reasoning"],
        model=result["model"],
        seconds=result["seconds"],
    )
