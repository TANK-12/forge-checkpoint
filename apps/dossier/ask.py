"""Answering a question about a subject from that subject's own evidence.

The model is given the stored claims, quotes and timeline for one subject and
nothing else, and every sentence it writes must cite one of them. Sentences
that cite nothing are removed before the answer is returned, so "not in the
sources" is a real possible answer rather than a thing the model has to be
trusted to say.
"""

from __future__ import annotations

import re

import dossier
import llm

MARKER = re.compile(r"\[(\d+)\]")
MAX_ITEMS = 60


def _evidence_pack(stored: dict, question: str) -> list[dict]:
    """The claims, quotes and events most worth showing for this question."""
    words = {w for w in re.findall(r"[a-z]{4,}", question.lower())}

    def overlap(text: str) -> int:
        return len(words & set(re.findall(r"[a-z]{4,}", (text or "").lower())))

    items: list[dict] = []
    for claim in stored.get("claims") or []:
        items.append(
            {
                "kind": "claim",
                "text": claim.get("text", ""),
                "confidence": claim.get("confidence", ""),
                "url": (claim.get("evidence") or [{}])[0].get("url", ""),
                "score": overlap(claim.get("text", "")) + claim.get("relevance", 0),
            }
        )
    for quote in stored.get("quotes") or []:
        items.append(
            {
                "kind": "quote",
                "text": f"\"{quote.get('text','')}\"",
                "confidence": "quoted",
                "url": quote.get("url", ""),
                "detail": quote.get("citation", ""),
                "score": overlap(quote.get("text", "")),
            }
        )
    for event in stored.get("timeline") or []:
        items.append(
            {
                "kind": "event",
                "text": f"{event.get('date','')}: {event.get('title','')}",
                "confidence": event.get("confidence", ""),
                "url": event.get("url", ""),
                "score": overlap(event.get("title", "")),
            }
        )
    items.sort(key=lambda i: i["score"], reverse=True)
    return [i for i in items if i["text"].strip()][:MAX_ITEMS]


def answer(slug: str, question: str) -> dict:
    stored = dossier.load(slug)
    if not stored:
        return {
            "answer": "",
            "error": "No dossier stored for that subject.",
            "used": [],
        }
    pack = _evidence_pack(stored, question)
    if not pack:
        return {
            "answer": "",
            "used": [],
            "error": "This dossier has no stored evidence yet. Run a research "
            "pass first.",
        }

    listing = "\n".join(f"[{i}] {item['text']}" for i, item in enumerate(pack))
    name = (stored.get("subject") or {}).get("name", slug)
    prompt = (
        f"Here is everything on file about {name}, each item numbered.\n\n"
        f"{listing}\n\n"
        f"Question: {question}\n\n"
        "Answer using ONLY these items. End every sentence with the numbers it "
        "rests on, like [4] or [4][9]. If the items do not answer the question, "
        "reply exactly: Not in the sources."
    )
    try:
        raw = llm.chat(
            "reason",
            [{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.1,
            priority="high",
        )
    except llm.JanUnavailable as e:
        return {"answer": "", "used": [], "error": str(e)}

    if raw.strip().lower().startswith("not in the sources"):
        return {"answer": "Not in the sources.", "used": [], "dropped": 0}

    kept, dropped, cited = [], 0, set()
    for sentence in re.split(r"(?<=[.!?])\s+", raw.strip()):
        markers = [int(m) for m in MARKER.findall(sentence)]
        if markers and all(0 <= m < len(pack) for m in markers):
            kept.append(sentence.strip())
            cited.update(markers)
        elif sentence.strip():
            dropped += 1
    if not kept:
        return {
            "answer": "Not in the sources.",
            "used": [],
            "dropped": dropped,
            "note": "The model answered without citing the stored evidence, so "
            "the answer was withheld.",
        }
    return {
        "answer": " ".join(kept),
        "dropped": dropped,
        "used": [{"n": n, **pack[n]} for n in sorted(cited)],
    }
