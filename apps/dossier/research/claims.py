"""Where the model is allowed to help, and where it is not trusted.

Two jobs go to Jan. Deciding whether an article is really about this subject
(cheap, the small model, thousands of times) and reading shortlisted text into
atomic claims (the larger model, a few dozen times).

Neither job is taken on trust. Every claim the model returns must quote a span,
and `_span_is_real` checks that span actually occurs in the source text before
the claim is allowed to exist. A model that invents a quotation gets its claim
dropped rather than believed, which is the difference between a research tool
and a plausible-sounding fiction generator.

Triage is also skipped wherever the arithmetic already knows the answer: only
documents whose deterministic relevance lands in the uncertain middle are worth
a model call. On a typical subject that is a small fraction of what was
gathered.
"""

from __future__ import annotations

import re

import llm
from research.corroborate import Claim, Evidence
from research.scoring import Relevance, SubjectProfile

# Below this the arithmetic is confident it is off-topic; above it, confident
# it is on-topic. Only the band between them is worth asking a model about.
TRIAGE_LOW = 0.28
TRIAGE_HIGH = 0.62
MAX_CHARS = 6000


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _span_is_real(span: str, source_text: str) -> bool:
    """Did this sentence actually appear in the article?

    Compared on normalized text so punctuation and whitespace differences are
    forgiven, but the words themselves must be there.
    """
    span_n, source_n = _norm(span), _norm(source_text)
    if len(span_n) < 12:
        return False
    if span_n in source_n:
        return True
    # Allow a trimmed quotation: most of a real sentence, contiguous.
    words = span_n.split()
    if len(words) >= 8:
        window = " ".join(words[: max(8, len(words) * 2 // 3)])
        return window in source_n
    return False


def needs_triage(relevance: float) -> bool:
    return TRIAGE_LOW <= relevance <= TRIAGE_HIGH


def triage(doc: dict, subject: SubjectProfile, identity: dict) -> tuple[bool, str]:
    """Is this document about our subject, or a namesake?"""
    who = identity.get("description") or ", ".join(subject.context_terms[:4])
    prompt = (
        f"Subject: {subject.name} - {who}.\n\n"
        f"Headline: {doc.get('title','')}\n"
        f"Extract: {(doc.get('text') or '')[:400]}\n\n"
        "Is this text about that exact subject, or about a different person or "
        "thing with a similar name? Reply only with JSON: "
        '{"about_subject": true or false, "why": "<8 words>"}'
    )
    result = llm.chat_json(
        "triage",
        [{"role": "user", "content": prompt}],
        default=None,
        max_tokens=40,
        temperature=0.0,
    )
    if not isinstance(result, dict) or "about_subject" not in result:
        # No answer is not a "no" - keep the document and let its relevance
        # score speak for itself.
        return True, "triage unavailable"
    return bool(result["about_subject"]), str(result.get("why", ""))[:80]


def relevant_paragraphs(
    text: str, subject: SubjectProfile, max_chars: int = 3200
) -> str:
    """The parts of an article that actually mention the subject.

    Sending a whole page costs prefill time on every token, and most of a news
    page is about something else. Selecting paragraphs deterministically is
    free and cuts the model's input by roughly half on a typical article.
    """
    names = [n.lower() for n in subject.full_names] + [subject.surname.lower()]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    keep, total = [], 0
    for para in paragraphs:
        low = para.lower()
        if not any(n in low for n in names):
            continue
        keep.append(para)
        total += len(para)
        if total >= max_chars:
            break
    if not keep:  # nothing named them; fall back to the opening
        return (text or "")[:max_chars]
    return "\n\n".join(keep)[:max_chars]


def _locate_sentence(anchor: str, source_text: str) -> str:
    """Find the sentence an anchor came from and return it in full.

    The model supplies only the opening words, so the sentence itself is read
    out of the article rather than reproduced by the model. A quotation in a
    dossier is therefore always the source's own words - the model never gets
    to author one.
    """
    anchor_n = _norm(anchor)
    if len(anchor_n) < 12:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", source_text or "")
    for sentence in sentences:
        if anchor_n in _norm(sentence):
            return sentence.strip()
    # The anchor may straddle a sentence break; fall back to a window.
    source_n = _norm(source_text)
    if anchor_n in source_n:
        idx = source_n.index(anchor_n)
        ratio = idx / max(len(source_n), 1)
        rough = int(ratio * len(source_text))
        return (source_text[rough : rough + 320]).strip()
    return ""


_FIGURE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _figures(text: str) -> set[str]:
    return {m.group(0).replace(",", "") for m in _FIGURE.finditer(text or "")}


def claim_matches_span(statement: str, span: str) -> bool:
    """A paraphrase may reword its sentence but must not change its figures.

    Every year, count or amount the claim states has to appear in the quoted
    sentence. Without this a claim saying 2024 was verified by a sentence about
    2016, because only the sentence's existence was checked.
    """
    return _figures(statement) <= _figures(span)


def extract_claims(
    doc: dict,
    subject: SubjectProfile,
    source_id: str,
    cluster_id: str,
    relevance: float,
    max_claims: int = 6,
) -> list[Claim]:
    """Read one document into atomic claims, each tied to a real sentence."""
    full_text = doc.get("text") or ""
    if len(full_text.split()) < 60:
        return []
    excerpt = relevant_paragraphs(full_text, subject)
    prompt = (
        f"Article about {subject.name}:\n\n{excerpt}\n\n"
        f"List up to {max_claims} factual claims this article makes about "
        f"{subject.name}. For each, give the claim in your own words, and "
        '"anchor": the FIRST SIX WORDS, copied exactly, of the sentence it came '
        "from. Skip opinion and anything about other people.\n"
        'Reply only with JSON: [{"claim": "...", "anchor": "..."}]'
    )
    raw = llm.chat_json(
        "reason",
        [{"role": "user", "content": prompt}],
        default=[],
        max_tokens=600,
        temperature=0.1,
    )
    if not isinstance(raw, list):
        return []

    claims: list[Claim] = []
    for item in raw[:max_claims]:
        if not isinstance(item, dict):
            continue
        statement = str(item.get("claim") or "").strip()
        anchor = str(item.get("anchor") or item.get("quote") or "").strip()
        if len(statement.split()) < 3:
            continue
        # The honesty gate. If the anchor is not in the article, the model was
        # working from memory rather than the text, and the claim is dropped.
        span = _locate_sentence(anchor, full_text)
        if not span or not claim_matches_span(statement, span):
            continue
        claims.append(
            Claim(
                text=statement,
                evidence=[
                    Evidence(
                        source_id=source_id,
                        cluster_id=cluster_id,
                        domain=doc.get("domain", ""),
                        tier=doc.get("tier", "unknown"),
                        relevance=relevance,
                        span=span,
                        url=doc.get("url", ""),
                    )
                ],
            )
        )
    return claims


def find_contradictions(
    claims: list[Claim], subject: SubjectProfile
) -> dict[str, list[str]]:
    """Ask the model whether any pair of claims cannot both be true.

    Runs after the deterministic conflict check and can only add to it. Nothing
    is resolved here - a contradiction is reported so the user can judge it.
    """
    candidates = [c for c in claims if c.confidence != "disputed"][:40]
    if len(candidates) < 2:
        return {}
    listing = "\n".join(f"{i}. {c.text}" for i, c in enumerate(candidates))
    prompt = (
        f"These are claims about {subject.name}, each numbered.\n\n{listing}\n\n"
        "List only pairs that CANNOT both be true - genuine factual "
        "contradictions, not differences of emphasis or opinion. If there are "
        "none, return [].\n"
        'Reply only with JSON: [{"a": <number>, "b": <number>, "why": "<12 words>"}]'
    )
    raw = llm.chat_json(
        "reason",
        [{"role": "user", "content": prompt}],
        default=[],
        max_tokens=400,
        temperature=0.0,
    )
    out: dict[str, list[str]] = {}
    if not isinstance(raw, list):
        return out
    for item in raw[:20]:
        try:
            a, b = int(item["a"]), int(item["b"])
            why = str(item.get("why", "")).strip()[:120]
            if a == b or not (0 <= a < len(candidates) and 0 <= b < len(candidates)):
                continue
        except Exception:
            continue
        note_a = f'contradicts: "{candidates[b].text[:70]}" ({why})'
        note_b = f'contradicts: "{candidates[a].text[:70]}" ({why})'
        out.setdefault(candidates[a].text, []).append(note_a)
        out.setdefault(candidates[b].text, []).append(note_b)
    return out
