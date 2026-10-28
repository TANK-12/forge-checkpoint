"""Google News: what was reported, when, and by whom - headlines only.

A deliberate limitation, documented rather than papered over: Google News RSS
links do not resolve to the publisher. They point at an interstitial that
fetches the real URL client-side, so the article body is not reachable from
here. Rather than scrape around that, this adapter takes what the feed honestly
provides - headline, outlet and timestamp - and marks every document
`headline_only`.

That is still worth having. A hundred dated headlines from distinct outlets is
a good event timeline and a real corroboration signal. Claim extraction skips
these, because a headline is not evidence of its own contents; `ddg_lite`
supplies the full articles.
"""

from __future__ import annotations

import feedparser

from research.canonical import canonical_url, registrable_domain
from research.fetcher import Document, _iso
from research.scoring import SubjectProfile

from .registry import Context, Harvest, SourceSpec

FEED = "https://news.google.com/rss/search"


def fetch(subject: SubjectProfile, ctx: Context) -> Harvest:
    harvest = Harvest()
    query = subject.name
    if ctx.identity.get("context_hint"):
        query = f"{query} {ctx.identity['context_hint']}"

    r = ctx.fetcher.get(
        FEED,
        api=True,
        params={
            "q": query,
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        },
    )
    if r is None:
        harvest.notes.append("Google News did not respond")
        return harvest

    parsed = feedparser.parse(r.text)
    seen: set[str] = set()
    already_held = 0
    considered = 0
    for entry in parsed.entries:
        # A headline already stored for this subject is already on its
        # timeline; skipping it, outside the window below, leaves room in the
        # budget for new ones.
        if canonical_url(getattr(entry, "link", "") or "") in ctx.known_urls:
            already_held += 1
            continue
        considered += 1
        if considered > ctx.budget * 3:
            break
        outlet = ""
        if getattr(entry, "source", None):
            outlet = entry.source.get("title", "")
        title = entry.title or ""
        # The feed appends " - Outlet" to every headline.
        if outlet and title.endswith(f" - {outlet}"):
            title = title[: -len(outlet) - 3]
        key = title.lower().strip()
        if not title or key in seen:
            continue
        seen.add(key)
        published = _iso(getattr(entry, "published", ""))
        # The feed names outlets, not domains. Independence counts distinct
        # voices, so a stable key per outlet name is enough - and it reads
        # better than a fabricated hostname.
        if "." in outlet:
            domain = registrable_domain(outlet)
        elif outlet:
            domain = outlet.lower().replace(" ", "-")
        else:
            domain = "news.google.com"
        doc = Document(
            url=entry.link,
            title=title,
            text=f"{title}. Reported by {outlet or 'an unnamed outlet'}"
            f"{' on ' + published if published else ''}.",
            published=published,
            tier="aggregator",
            origin="news_rss",
            domain=domain,
        )
        harvest.documents.append(doc)
        if published:
            harvest.timeline.append(
                {
                    "date": published,
                    "end": "",
                    "title": title,
                    "kind": "coverage",
                    "detail": f"Reported by {outlet}" if outlet else "Reported",
                    "source_id": "news_rss",
                    "url": entry.link,
                    "confidence": "reported",
                    "headline_only": True,
                }
            )
        if len(harvest.documents) >= ctx.budget * 2:
            break

    for doc in harvest.documents:
        doc.origin = "news_rss"
    ctx.log(
        f"Google News: {len(harvest.documents)} headlines"
        + (f", {already_held} already held" if already_held else "")
    )
    harvest.skipped_known = already_held
    return harvest


SPEC = SourceSpec(
    name="news_rss",
    label="Google News",
    tier="aggregator",
    phases=("quick", "deep"),
    entity_types=("*",),
    fetch=fetch,
    description="Dated headlines and outlets. Headline-only; no article bodies.",
)
