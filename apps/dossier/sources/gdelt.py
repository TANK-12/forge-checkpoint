"""GDELT: worldwide news coverage, including outside the English-language press.

Useful for figures who are covered heavily in one country and barely elsewhere.
It is a free service with no key and a firm rate limit - a 429 was returned
while this was being built - so it backs off and gives up quietly rather than
holding up a research run. It is never on the critical path.
"""

from __future__ import annotations

import time

from research.canonical import canonical_url, registrable_domain
from research.fetcher import Document, _iso
from research.scoring import SubjectProfile

from .registry import Context, Harvest, SourceSpec

API = "https://api.gdeltproject.org/api/v2/doc/doc"
BACKOFF = (2.0, 6.0)


def _records_to_ask(wanted: int, known_urls: set) -> int:
    """How many articles to request so held ones can be replaced.

    The API has no paging: one request returns at most `maxrecords`. On a
    first run that is exactly what is wanted. On a refresh some of what comes
    back is already held and is skipped, so the request asks for up to as many
    extra as the subject holds, at most double (150, inside GDELT's 250 limit).
    New articles then take the held ones' place unless more than that many of
    the top results are already held.
    """
    return wanted + min(len(known_urls), wanted)


def fetch(subject: SubjectProfile, ctx: Context) -> Harvest:
    harvest = Harvest()
    wanted = min(ctx.budget * 2, 75)
    params = {
        "query": f'"{subject.name}"',
        "mode": "artlist",
        "format": "json",
        "maxrecords": str(_records_to_ask(wanted, ctx.known_urls)),
        "sort": "hybridrel",
    }
    data = None
    for attempt, pause in enumerate((0.0, *BACKOFF)):
        if pause:
            time.sleep(pause)
        r = ctx.fetcher.get(API, api=True, params=params)
        if r is None:
            continue
        if r.status_code == 429:
            continue
        try:
            data = r.json()
            break
        except Exception:
            continue
    if not data:
        harvest.notes.append("GDELT was rate-limited or unreachable; skipped")
        ctx.log("GDELT: skipped (rate-limited)")
        return harvest

    already_held = 0
    for art in data.get("articles") or []:
        if len(harvest.documents) >= wanted:
            break
        url = art.get("url") or ""
        if not url:
            continue
        # A story the subject already holds adds nothing on a refresh; skipping
        # it lets the budget go to articles that are actually new.
        if canonical_url(url) in ctx.known_urls:
            already_held += 1
            continue
        title = art.get("title") or ""
        published = _iso((art.get("seendate") or "")[:8].replace("", "")) or ""
        if not published and art.get("seendate"):
            raw = art["seendate"][:8]
            published = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if len(raw) == 8 else ""
        harvest.documents.append(
            Document(
                url=url,
                title=title,
                text=f"{title}. {art.get('domain','')} "
                f"({art.get('sourcecountry','')}, {art.get('language','')}).",
                published=published,
                tier="unknown",
                origin="gdelt",
                domain=registrable_domain(url),
            )
        )
    ctx.log(
        f"GDELT: {len(harvest.documents)} articles indexed"
        + (f", {already_held} already held" if already_held else "")
    )
    harvest.skipped_known = already_held
    return harvest


SPEC = SourceSpec(
    name="gdelt",
    label="GDELT",
    tier="unknown",
    phases=("deep",),
    entity_types=("*",),
    fetch=fetch,
    description="International news index, including non-English coverage.",
)
