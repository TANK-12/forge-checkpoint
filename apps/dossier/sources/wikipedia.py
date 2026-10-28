"""Wikipedia: the encyclopedic baseline every dossier starts from.

Deliberately taken as one source rather than treated as truth. It is tiered
`encyclopedic`, which raises its weight in corroboration, but a claim resting
on Wikipedia alone is still only `reported` unless something independent backs
it up.

The whole article is kept, split into its sections, for the In depth page.
"""

from __future__ import annotations

import re

from research.fetcher import Document, now_iso
from research.scoring import SubjectProfile

from .registry import Context, Harvest, SourceSpec

API = "https://en.wikipedia.org/w/api.php"
REST = "https://en.wikipedia.org/api/rest_v1/page/summary/"

# Sections that are lists of links and references rather than information.
SKIP_SECTIONS = {
    "see also",
    "references",
    "notes",
    "external links",
    "further reading",
    "bibliography",
    "citations",
    "sources",
    "works cited",
    "footnotes",
    "explanatory notes",
    "general and cited sources",
}
_HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")


def split_sections(text: str) -> list[dict]:
    """The plain-text article as headed sections, reference lists left out.

    The extract API marks headings as `== Early life ==`. Everything before the
    first heading is the lead. Until this existed the whole article was
    downloaded and only its first paragraph kept, which is most of why a
    dossier read as a timeline and little else.
    """
    sections: list[dict] = []
    heading, level, lines = "Summary", 1, []
    skipping = False

    def close():
        body = "\n".join(line for line in lines if line.strip()).strip()
        if body and not skipping:
            sections.append({"heading": heading, "level": level, "text": body})

    for line in text.splitlines():
        found = _HEADING.match(line.strip())
        if not found:
            lines.append(line)
            continue
        close()
        level = len(found.group(1))
        heading = found.group(2)
        lines = []
        if level == 2:
            skipping = heading.lower() in SKIP_SECTIONS
    close()
    return sections


def extract(fetcher, title: str) -> tuple[str, str]:
    """(resolved article title, plain text), or ("", "") when there is none."""
    data = fetcher.get_json(
        API,
        params={
            "action": "query",
            "prop": "extracts",
            "explaintext": "1",
            "redirects": "1",
            "titles": title,
            "format": "json",
            "formatversion": "2",
        },
        api=True,
    )
    pages = ((data or {}).get("query") or {}).get("pages") or []
    if not pages or pages[0].get("missing"):
        return "", ""
    return pages[0].get("title") or title, pages[0].get("extract") or ""


def article_url(title: str) -> str:
    return f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"


def article_from(title: str, text: str) -> dict:
    """The stored shape of an article, or {} when it has no sections."""
    sections = split_sections(text)
    if not sections:
        return {}
    return {
        "title": title,
        "url": article_url(title),
        "fetched": now_iso(),
        "words": len(text.split()),
        "sections": sections,
    }


def fetch(subject: SubjectProfile, ctx: Context) -> Harvest:
    harvest = Harvest()
    title = ctx.identity.get("wikipedia_title") or subject.name

    resolved, text = extract(ctx.fetcher, title)
    if not resolved:
        harvest.notes.append(f"No English Wikipedia article for '{title}'")
        return harvest
    if not text:
        harvest.notes.append(f"Wikipedia article '{resolved}' had no extractable text")
        return harvest

    harvest.article = article_from(resolved, text)
    harvest.documents.append(
        Document(
            url=article_url(resolved),
            title=f"{resolved} - Wikipedia",
            text=text,
            tier="encyclopedic",
            origin="wikipedia",
        )
    )
    harvest.identity.setdefault("summary", text.split("\n")[0][:1200])
    ctx.log(f"Wikipedia: {resolved} ({len(text.split())} words)")
    return harvest


SPEC = SourceSpec(
    name="wikipedia",
    label="Wikipedia",
    tier="encyclopedic",
    phases=("quick", "deep"),
    entity_types=("*",),
    fetch=fetch,
    description="Full article text as the encyclopedic baseline, kept by section.",
)
