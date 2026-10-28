"""Wikiquote: things the subject actually said, with the citation attached.

This is the only source that hands over quotes already paired with where they
came from, which is exactly what an 'in their own words' page needs. The
wikitext convention is a quote line followed by indented source lines, so the
pairing is parsed rather than guessed at, and a quote with no citation is kept
but marked - never presented as sourced.
"""

from __future__ import annotations

import re

from research.fetcher import Document
from research.scoring import SubjectProfile

from .registry import Context, Harvest, SourceSpec

API = "https://en.wikiquote.org/w/api.php"

MARKUP = [
    (re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]"), r"\2"),
    (re.compile(r"\[\[([^\]]+)\]\]"), r"\1"),
    (re.compile(r"'''([^']+)'''"), r"\1"),
    (re.compile(r"''([^']+)''"), r"\1"),
    (re.compile(r"<ref[^>]*>.*?</ref>", re.S), ""),
    (re.compile(r"<ref[^>]*/>"), ""),
    (re.compile(r"<[^>]+>"), ""),
    (re.compile(r"\{\{[^}]*\}\}"), ""),
]
YEAR = re.compile(r"\b(1[6-9]\d{2}|20\d{2})\b")
SECTION = re.compile(r"^=+\s*(.+?)\s*=+\s*$")


def clean(text: str) -> str:
    for pattern, repl in MARKUP:
        text = pattern.sub(repl, text)
    return re.sub(r"\s+", " ", text).strip(" *:\t")


def parse_quotes(wikitext: str, limit: int) -> list[dict]:
    quotes: list[dict] = []
    section = ""
    current: dict | None = None
    for raw in wikitext.splitlines():
        line = raw.rstrip()
        heading = SECTION.match(line)
        if heading:
            section = clean(heading.group(1))
            # Everything past the quotes proper is other people talking.
            if section.lower().startswith(
                (
                    "quotes about",
                    "about ",
                    "misattributed",
                    "external links",
                    "see also",
                )
            ):
                current = None
            continue
        if section.lower().startswith(
            ("quotes about", "about ", "misattributed", "external links", "see also")
        ):
            continue
        if line.startswith("**") or line.startswith(":*"):
            if current is not None:
                citation = clean(line)
                if citation:
                    current["citation"] = citation
                    year = YEAR.search(citation)
                    if year:
                        current["date"] = year.group(1)
            continue
        if line.startswith("*"):
            body = clean(line)
            if len(body.split()) < 4:
                current = None
                continue
            current = {"text": body, "citation": "", "date": "", "topic": section}
            quotes.append(current)
            if len(quotes) >= limit:
                break
    return quotes


def fetch(subject: SubjectProfile, ctx: Context) -> Harvest:
    harvest = Harvest()
    title = ctx.identity.get("wikiquote_title") or subject.name
    data = ctx.fetcher.get_json(
        API,
        params={
            "action": "parse",
            "page": title,
            "prop": "wikitext",
            "format": "json",
            "formatversion": "2",
            "redirects": "1",
        },
        api=True,
    )
    wikitext = ((data or {}).get("parse") or {}).get("wikitext")
    if not wikitext:
        harvest.notes.append(f"No Wikiquote page for '{title}'")
        return harvest

    url = f"https://en.wikiquote.org/wiki/{title.replace(' ', '_')}"
    quotes = parse_quotes(wikitext, limit=max(ctx.budget * 4, 40))
    for q in quotes:
        q["source_id"] = "wikiquote"
        q["url"] = url
        q["sourced"] = bool(q["citation"])
    harvest.quotes.extend(quotes)

    if quotes:
        harvest.documents.append(
            Document(
                url=url,
                title=f"{title} - Wikiquote",
                text="\n\n".join(f"\"{q['text']}\" {q['citation']}" for q in quotes),
                tier="encyclopedic",
                origin="wikiquote",
            )
        )
    sourced = sum(1 for q in quotes if q["sourced"])
    ctx.log(f"Wikiquote: {len(quotes)} quotes ({sourced} with a citation)")
    return harvest


SPEC = SourceSpec(
    name="wikiquote",
    label="Wikiquote",
    tier="encyclopedic",
    phases=("quick", "deep"),
    entity_types=("person", "party", "organisation"),
    fetch=fetch,
    description="Verbatim quotations with their citations.",
)
