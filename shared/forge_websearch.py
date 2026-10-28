"""Web search for Forge apps, stdlib only: DuckDuckGo's HTML page, with its
Lite page as the fallback, and a plain-text reader for one result.

the owner (2026-10-07): "also make web search work" for the local chat.
No API key and no extra package, so any app's virtualenv can use it.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)
HTML_URL = "https://html.duckduckgo.com/html/?q="
LITE_URL = "https://lite.duckduckgo.com/lite/"  # answers a POST only


@dataclass
class Result:
    title: str
    url: str
    snippet: str


def _get(url: str, timeout: float, form: dict | None = None) -> str:
    data = urllib.parse.urlencode(form).encode() if form else None
    headers = {"User-Agent": UA, "Referer": url.split("?")[0]}
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read(2_000_000).decode(charset, "replace")


def _plain(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def _real(href: str) -> str:
    """DuckDuckGo wraps result links in a redirect (…/l/?uddg=<real url>)."""
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    query = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
    return query.get("uddg", [href])[0]


def parse_html(page: str) -> list[Result]:
    results = []
    for link in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=class="result__a"|$)',
        page,
        re.S,
    ):
        snippet = re.search(
            r'class="result__snippet"[^>]*>(.*?)</a>', link.group(3), re.S
        )
        url = _real(link.group(1))
        if "duckduckgo.com/y.js" in url:  # an advert
            continue
        results.append(
            Result(
                _plain(link.group(2)), url, _plain(snippet.group(1)) if snippet else ""
            )
        )
    return results


def parse_lite(page: str) -> list[Result]:
    results = []
    links = list(
        re.finditer(
            r"<a[^>]+href=\"([^\"]+)\"[^>]*class=['\"]result-link['\"][^>]*>(.*?)</a>",
            page,
            re.S,
        )
    )
    snippets = re.findall(r"class=['\"]result-snippet['\"][^>]*>(.*?)</td>", page, re.S)
    for i, link in enumerate(links):
        results.append(
            Result(
                _plain(link.group(2)),
                _real(link.group(1)),
                _plain(snippets[i]) if i < len(snippets) else "",
            )
        )
    return results


def search(query: str, limit: int = 6, timeout: float = 15.0) -> list[Result]:
    """Up to `limit` results for `query`. Raises OSError when neither page
    answers; an empty list means the search really found nothing."""
    query = query.strip()
    if not query:
        return []
    quoted = urllib.parse.quote_plus(query)
    error: OSError | None = None
    for url, form, parse in (
        (HTML_URL + quoted, None, parse_html),
        (LITE_URL, {"q": query}, parse_lite),
    ):
        try:
            found = parse(_get(url, timeout, form))
        except OSError as exc:
            error = exc
            continue
        if found:
            return found[:limit]
    if error:
        raise error
    return []


INSTANT_URL = "https://api.duckduckgo.com/?format=json&no_html=1&skip_disambig=1&q="


def instant(query: str, timeout: float = 8.0) -> dict | None:
    """DuckDuckGo's instant answer for `query` (a calculation, a definition or
    an encyclopedia abstract): {"text", "source", "url"}, or None when there
    is none or the request fails."""
    query = query.strip()
    if not query:
        return None
    try:
        data = json.loads(_get(INSTANT_URL + urllib.parse.quote_plus(query), timeout))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for key, source, url in (
        ("Answer", "DuckDuckGo", ""),
        (
            "AbstractText",
            data.get("AbstractSource") or "",
            data.get("AbstractURL") or "",
        ),
        (
            "Definition",
            data.get("DefinitionSource") or "",
            data.get("DefinitionURL") or "",
        ),
    ):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return {"text": _plain(value), "source": source, "url": url}
    return None


WIKI_SEARCH = "https://en.wikipedia.org/w/api.php?action=query&list=search&srlimit=1&format=json&srsearch="
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"


def wikipedia(query: str, timeout: float = 8.0) -> dict | None:
    """The opening of the Wikipedia article that best fits `query`:
    {"text", "source", "url"}, or None. The fallback when DuckDuckGo turns
    a run of searches away with its bot check."""
    query = query.strip()
    if not query:
        return None
    try:
        found = json.loads(_get(WIKI_SEARCH + urllib.parse.quote_plus(query), timeout))
        hits = found["query"]["search"]
        if not hits:
            return None
        title = hits[0]["title"]
        page = json.loads(
            _get(
                WIKI_SUMMARY + urllib.parse.quote(title.replace(" ", "_"), safe=""),
                timeout,
            )
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
    text = page.get("extract") if isinstance(page, dict) else None
    if not isinstance(text, str) or not text.strip():
        return None
    link = ((page.get("content_urls") or {}).get("desktop") or {}).get("page") or ""
    return {"text": text.strip(), "source": f"Wikipedia: {title}", "url": link}


def page_text(url: str, limit: int = 6000, timeout: float = 15.0) -> str:
    """The readable text of one web page, scripts and markup removed."""
    if not re.match(r"https?://", url):
        url = "https://" + url
    page = _get(url, timeout)
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    page = re.sub(
        r"<(script|style|noscript|svg|nav|footer|header)\b.*?</\1>",
        " ",
        page,
        flags=re.S | re.I,
    )
    page = re.sub(r"<(br|p|div|li|h\d|tr)\b[^>]*>", "\n", page, flags=re.I)
    lines = [_plain(line) for line in re.sub(r"<[^>]+>", " ", page).splitlines()]
    text = "\n".join(line for line in lines if len(line) > 1)
    head = _plain(title.group(1)) + "\n" if title else ""
    return (head + text)[:limit]


def text(query: str, limit: int = 6) -> str:
    """Numbered results as plain text, for a chat or a model's context."""
    try:
        found = search(query, limit)
    except OSError as exc:
        return f"The web search failed: {exc}"
    if not found:
        return f"No web results for {query}."
    return "\n".join(
        f"{i}. {r.title}\n   {r.url}\n   {r.snippet[:240]}"
        for i, r in enumerate(found, 1)
    )
