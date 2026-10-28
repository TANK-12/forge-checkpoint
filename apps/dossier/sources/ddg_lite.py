"""DuckDuckGo Lite: finding the actual articles, then reading them.

This is where full article text comes from. The Lite endpoint returns plain
publisher URLs rather than the redirect wrappers a news aggregator hands out,
so each result can be fetched and extracted properly - and those fetches DO
respect robots.txt, because they are ordinary web crawling.
"""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from research.canonical import canonical_url, registrable_domain
from research.scoring import SubjectProfile

from .registry import Context, Harvest, SourceSpec

ENDPOINT = "https://lite.duckduckgo.com/lite/"

# Outlets whose reporting is treated as established rather than unknown. Not a
# judgement of who is right - only of who has a masthead and a corrections
# policy, which is what corroboration weighting is about.
MAJOR = {
    "reuters.com",
    "apnews.com",
    "bbc.co.uk",
    "bbc.com",
    "theguardian.com",
    "nytimes.com",
    "washingtonpost.com",
    "ft.com",
    "economist.com",
    "wsj.com",
    "bloomberg.com",
    "politico.com",
    "politico.eu",
    "afp.com",
    "npr.org",
    "aljazeera.com",
    "dw.com",
    "france24.com",
    "cnn.com",
    "nbcnews.com",
    "cbsnews.com",
    "abcnews.go.com",
    "spiegel.de",
    "lemonde.fr",
    "elpais.com",
    "thetimes.co.uk",
    "telegraph.co.uk",
    "independent.co.uk",
    "axios.com",
    "time.com",
    "newsweek.com",
    "cnbc.com",
    "forbes.com",
    "theatlantic.com",
}
PRIMARY_HINTS = (
    ".gov",
    ".gov.uk",
    "europa.eu",
    "parliament.uk",
    "congress.gov",
    "whitehouse.gov",
    "sec.gov",
    "un.org",
    "bundestag.de",
)
SKIP = {
    "youtube.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "tiktok.com",
    "reddit.com",
    "pinterest.com",
    "linkedin.com",
    "quora.com",
}


def tier_for(domain: str) -> str:
    if any(hint in domain for hint in PRIMARY_HINTS):
        return "primary"
    if domain in ("wikipedia.org", "wikiquote.org", "britannica.com"):
        return "encyclopedic"
    if domain in MAJOR:
        return "major"
    return "unknown"


def search(ctx: Context, query: str, limit: int) -> list[str]:
    r = ctx.fetcher.client.post(
        ENDPOINT,
        data={"q": query},
        timeout=25.0,
        headers={"Referer": "https://lite.duckduckgo.com/"},
    )
    if r.status_code >= 400:
        return []
    soup: Any = BeautifulSoup(r.text, "lxml")
    urls: list[str] = []
    for a in soup.select("a.result-link, a[href^='http']"):
        href = str(a.get("href") or "")
        if not href.startswith("http"):
            continue
        url = canonical_url(href)
        domain = registrable_domain(url)
        if domain in SKIP or "duckduckgo.com" in domain:
            continue
        if url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def fetch(subject: SubjectProfile, ctx: Context) -> Harvest:
    harvest = Harvest()
    hint = ctx.identity.get("context_hint") or ""
    queries = [f"{subject.name} {hint}".strip()]
    if ctx.phase == "deep":
        queries += [
            f'"{subject.name}" statement OR speech OR interview {hint}'.strip(),
            f'"{subject.name}" criticism OR controversy {hint}'.strip(),
            f'"{subject.name}" policy OR position OR voted {hint}'.strip(),
        ]

    # Collect every candidate first, then fetch them all at once. Fetching one
    # at a time was 40% of a quick pass and none of it was doing any work.
    seen: set[str] = set()
    candidates: list[str] = []
    already_held = 0
    for query in queries:
        for url in search(ctx, query, limit=ctx.budget):
            if url in seen:
                continue
            seen.add(url)
            # Canonicalised again here rather than trusting the caller: the
            # same article arrives with tracking parameters, as an AMP page or
            # behind an aggregator wrapper, and a skip that misses those
            # refetches the article it was meant to save.
            if canonical_url(url) in ctx.known_urls:
                # Already stored from an earlier run. A published article does
                # not change, so fetching it again costs a request and a parse
                # to rediscover something the dossier already holds.
                already_held += 1
                continue
            candidates.append(url)
        if len(candidates) >= ctx.budget * 2:
            break

    docs = ctx.fetcher.articles(
        candidates[: ctx.budget * 2],
        tier_for=lambda u: tier_for(registrable_domain(u)),
        origin="ddg_lite",
    )
    for doc in docs:
        if len(doc.text.split()) < 60:
            continue
        harvest.documents.append(doc)
        if len(harvest.documents) >= ctx.budget:
            break

    ctx.log(
        f"Web search: {len(harvest.documents)} new articles from "
        f"{len(candidates)} results"
        + (f", {already_held} already held (not refetched)" if already_held else "")
        + f" ({ctx.fetcher.stats['blocked']} blocked by robots.txt)"
    )
    harvest.skipped_known = already_held
    return harvest


SPEC = SourceSpec(
    name="ddg_lite",
    label="Web search",
    tier="unknown",
    phases=("quick", "deep"),
    entity_types=("*",),
    fetch=fetch,
    description="Finds and reads full article text from the open web.",
)
