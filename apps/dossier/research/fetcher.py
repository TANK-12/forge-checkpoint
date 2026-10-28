"""Getting pages without being a nuisance, and getting the words out of them.

Public research on public figures still means hitting other people's servers a
few thousand times, so this rate-limits per domain, honours robots.txt, and
identifies itself honestly with a contact address. Concurrency is capped low on
purpose: the machine is a laptop doing other things.

Extraction is deliberately plain - strip the furniture, keep the paragraphs.
A dedicated library would read a little better on hostile layouts, but this
avoids another dependency and the text only has to be good enough to quote from
and score against.
"""

from __future__ import annotations

import json
import re
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .canonical import canonical_url, registrable_domain

# Wikipedia and other APIs ask a tool for a way to reach whoever runs it:
# $DOSSIER_CONTACT, else the first line of contact.txt beside the library
# choice (~/.config/forge-dossier/), goes into every request's User-Agent.
CONTACT_FILE = Path(
    os.environ.get(
        "DOSSIER_CONTACT_FILE",
        str(Path.home() / ".config" / "forge-dossier" / "contact.txt"),
    )
)


def user_agent(contact: str | None = None) -> str:
    """The User-Agent every request sends, with the contact when one is set."""
    if contact is None:
        contact = os.environ.get("DOSSIER_CONTACT", "")
        if not contact.strip():
            try:
                contact = CONTACT_FILE.read_text(encoding="utf-8").split("\n")[0]
            except OSError:
                contact = ""
    contact = contact.strip()
    tail = f"; contact {contact}" if contact else ""
    return f"ForgeDossier/1.0 (personal research tool{tail})"


USER_AGENT = user_agent()
MIN_INTERVAL = float(os.environ.get("DOSSIER_CRAWL_INTERVAL", "0.5"))
# Documented APIs are built to be called in a loop and their limits are quotas,
# not spacing. Holding them to the crawl interval made nine World Bank
# indicator requests take nine seconds of pure waiting.
API_INTERVAL = float(os.environ.get("DOSSIER_API_INTERVAL", "0.1"))
TIMEOUT = 20.0
# Fetching is network-bound, so this costs almost no CPU and is the single
# biggest speed lever: a quick pass spent 40 seconds of its 55 waiting on
# sequential HTTP. Different domains are fetched at the same time; the same
# domain is still spaced out by MIN_INTERVAL.
FETCH_WORKERS = int(os.environ.get("DOSSIER_FETCH_WORKERS", "12"))
MAX_BYTES = 2_000_000

DROP_TAGS = [
    "script",
    "style",
    "nav",
    "footer",
    "aside",
    "form",
    "noscript",
    "svg",
    "header",
    "iframe",
    "figure",
]
DROP_HINTS = re.compile(
    r"(cookie|consent|newsletter|subscri|advert|promo|related|share|social|"
    r"comment|paywall|breadcrumb|sidebar|menu|nav)",
    re.I,
)
DATE_META = [
    ("meta", {"property": "article:published_time"}),
    ("meta", {"name": "article:published_time"}),
    ("meta", {"property": "og:published_time"}),
    ("meta", {"name": "date"}),
    ("meta", {"name": "pubdate"}),
    ("meta", {"itemprop": "datePublished"}),
]


@dataclass
class Document:
    """One fetched thing, before it is scored or clustered."""

    url: str
    title: str = ""
    text: str = ""
    published: str = ""
    tier: str = "unknown"
    origin: str = ""
    domain: str = field(default="")

    def __post_init__(self):
        self.url = canonical_url(self.url)
        if not self.domain:
            self.domain = registrable_domain(self.url)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "published": self.published,
            "tier": self.tier,
            "origin": self.origin,
            "domain": self.domain,
        }


def _iso(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
        "%d %B %Y",
        "%B %d, %Y",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
    ):
        try:
            return datetime.strptime(value[:40], fmt).date().isoformat()
        except Exception:
            continue
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", value)
    return m.group(0) if m else ""


class Fetcher:
    """Shared HTTP client with per-domain politeness and a robots cache."""

    def __init__(self, min_interval: float = MIN_INTERVAL, obey_robots: bool = True):
        self.min_interval = min_interval
        self.obey_robots = obey_robots
        self._last: dict[str, float] = {}
        self._domain_locks: dict[str, threading.Lock] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()
        self.client = httpx.Client(
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
            limits=httpx.Limits(
                max_connections=FETCH_WORKERS * 3,
                max_keepalive_connections=FETCH_WORKERS,
            ),
        )
        self.stats = {"fetched": 0, "blocked": 0, "failed": 0, "bytes": 0}

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _domain_lock(self, domain: str) -> threading.Lock:
        with self._lock:
            if domain not in self._domain_locks:
                self._domain_locks[domain] = threading.Lock()
            return self._domain_locks[domain]

    def _wait(self, domain: str, interval: float | None = None):
        """Space out requests to one domain without blocking the others.

        The lock held while sleeping is per domain, not global. Holding a
        single lock across the sleep would have serialised every fetch in the
        program and undone the point of fetching in parallel.
        """
        gap_wanted = self.min_interval if interval is None else interval
        with self._domain_lock(domain):
            last = self._last.get(domain, 0.0)
            gap = time.time() - last
            if gap < gap_wanted:
                time.sleep(gap_wanted - gap)
            self._last[domain] = time.time()

    def _allowed(self, url: str) -> bool:
        if not self.obey_robots:
            return True
        domain = registrable_domain(url)
        if domain not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                base = "/".join(url.split("/")[:3])
                r = self.client.get(f"{base}/robots.txt", timeout=8.0)
                if r.status_code == 200:
                    parser.parse(r.text.splitlines())
                else:
                    parser = None
            except Exception:
                parser = None
            self._robots[domain] = parser
        parser = self._robots[domain]
        if parser is None:
            return True
        try:
            return parser.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    def get(self, url: str, api: bool = False, **kw) -> httpx.Response | None:
        """`api=True` for documented public APIs.

        robots.txt governs crawling, and Wikimedia's disallows /w/ - which
        would block the very API they publish for programmatic use. API
        endpoints are called under their own terms instead; the rate limit
        and the identifying User-Agent still apply to every request.
        """
        domain = registrable_domain(url)
        if not api and not self._allowed(url):
            self.stats["blocked"] += 1
            return None
        self._wait(domain, API_INTERVAL if api else None)
        try:
            r = self.client.get(url, **kw)
        except Exception:
            self.stats["failed"] += 1
            return None
        if r.status_code >= 400:
            self.stats["failed"] += 1
            return None
        self.stats["fetched"] += 1
        self.stats["bytes"] += len(r.content)
        return r

    def get_json(self, url: str, api: bool = True, **kw):
        r = self.get(url, api=api, **kw)
        if r is None:
            return None
        try:
            return r.json()
        except Exception:
            return None

    def articles(
        self,
        urls: list[str],
        tier_for=None,
        origin: str = "",
        workers: int | None = None,
    ) -> list["Document"]:
        """Fetch and extract many pages at once.

        `tier_for` is called with each URL to decide its tier, so callers keep
        their own tiering rules. Order of the results is not guaranteed to
        match the input; callers here score everything afterwards anyway.
        """
        if not urls:
            return []
        count = min(workers or FETCH_WORKERS, max(len(urls), 1))
        jobs = [
            (self, url, tier_for(url) if tier_for else "unknown", origin)
            for url in urls
        ]
        with ThreadPoolExecutor(max_workers=count) as pool:
            results = list(pool.map(_articles_worker, jobs))
        return [doc for doc in results if doc is not None]

    def article(
        self, url: str, tier: str = "unknown", origin: str = ""
    ) -> Document | None:
        """Fetch a page and reduce it to title, body text and a date."""
        r = self.get(url)
        if r is None:
            return None
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype and "xml" not in ctype:
            return None
        title, text, published = extract(r.text[:MAX_BYTES], url)
        if not text:
            return None
        return Document(
            url=str(r.url),
            title=title,
            text=text,
            published=published,
            tier=tier,
            origin=origin,
        )


def _looks_like_noise(tag) -> bool:
    """Does this element's class or id mark it as page furniture?

    Matched against class tokens individually rather than the whole attribute.
    That distinction is not cosmetic: Wikipedia puts feature flags on the <html>
    element, one of which is `vector-feature-main-menu-pinned-clientpref-1`.
    A substring match on the joined attribute saw "menu", decomposed the root
    element, and returned an empty document for every Wikipedia page - and for
    any other site whose wrapper happened to contain one of these words.
    """
    if tag.name in ("html", "body", "main", "article"):
        return False
    tokens = list(tag.get("class") or [])
    if tag.get("id"):
        tokens.append(str(tag.get("id")))
    if tag.get("role") in ("navigation", "banner", "complementary", "search"):
        return True
    return any(DROP_HINTS.search(token) for token in tokens)


def _text_of(node) -> str:
    """Readable body text: paragraphs, quotes and list items, in order."""
    parts = []
    for element in node.find_all(["p", "blockquote", "li", "h2", "h3"]):
        text = element.get_text(" ", strip=True)
        if not text:
            continue
        words = len(text.split())
        if element.name in ("h2", "h3"):
            if 1 <= words <= 14:
                parts.append(text)
        elif element.name == "li":
            if words >= 10:
                parts.append(text)
        elif words >= 5:
            parts.append(text)
    return "\n\n".join(parts)


def _best_container(soup):
    """The element holding the actual article.

    Rather than trusting one tag name, every plausible container is scored by
    how much paragraph text it holds and the densest wins. Sites that use no
    <article> or <main> - most of them - still extract correctly.
    """
    candidates = []
    for node in soup.find_all(["article", "main", "div", "section"]):
        paragraphs = node.find_all("p", recursive=True)
        if not paragraphs:
            continue
        length = sum(len(p.get_text(" ", strip=True)) for p in paragraphs)
        if length < 200:
            continue
        # Prefer the tightest element holding the text, not its grandparents.
        depth = len(list(node.parents))
        candidates.append((length, depth, node))
    if not candidates:
        return soup
    best_length = max(c[0] for c in candidates)
    # Among containers holding nearly all the text, take the deepest.
    finalists = [c for c in candidates if c[0] >= best_length * 0.9]
    return max(finalists, key=lambda c: c[1])[2]


def _articles_worker(args):
    fetcher, url, tier, origin = args
    try:
        return fetcher.article(url, tier=tier, origin=origin)
    except Exception:
        return None


def extract(html: str, url: str = "") -> tuple[str, str, str]:
    """(title, body text, ISO date) from a raw HTML page."""
    # bs4 returns str | list[str] for attributes and untyped nodes from
    # find/find_all; the tree is treated as untyped rather than casting
    # at every access.
    soup: Any = BeautifulSoup(html, "lxml")

    title = ""
    if soup.title and soup.title.string:
        title = str(soup.title.string).strip()
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        title = str(og["content"]).strip()
    title = re.sub(r"\s*[|\-–]\s*[^|\-–]{0,40}$", "", title).strip() or title

    published = ""
    for tag, attrs in DATE_META:
        node = soup.find(tag, attrs=attrs)
        if node and node.get("content"):
            published = _iso(str(node["content"]))
            if published:
                break
    if not published:
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                blob = json.loads(script.string or "{}")
            except Exception:
                continue
            items = blob if isinstance(blob, list) else [blob]
            for item in items:
                if isinstance(item, dict) and item.get("datePublished"):
                    published = _iso(str(item["datePublished"]))
                    break
            if published:
                break
    if not published:
        node = soup.find("time")
        if node:
            published = _iso(
                str(node.get("datetime") or node.get_text(" ", strip=True))
            )

    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()

    # Strip furniture, but never anything holding a large share of the page -
    # that is the article itself, however its wrapper happens to be named.
    total = len(soup.find_all("p")) or 1
    for tag in soup.find_all(True):
        if not getattr(tag, "name", None) or tag.decomposed:
            continue
        if _looks_like_noise(tag) and len(tag.find_all("p")) <= max(2, total * 0.25):
            tag.decompose()

    text = _text_of(_best_container(soup))
    if len(text.split()) < 40:
        # Fall back to the whole document before giving up on the page.
        text = _text_of(soup)
    return title, re.sub(r"[ \t]+", " ", text).strip(), published


def now_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


_shared: "Fetcher | None" = None
_shared_lock = threading.Lock()


def shared() -> "Fetcher":
    """One Fetcher for the whole process.

    Per-domain pacing only means anything if every request goes through the
    same bookkeeping. When each concurrently-researched subject built its own
    Fetcher, three workers times eight threads hit the same handful of hosts -
    Wikidata, Wikipedia, DuckDuckGo - with no coordination at all, got
    throttled, and each subject went from 34 seconds to a median of 96. Sharing
    one is both more polite and considerably faster.
    """
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = Fetcher()
        return _shared
