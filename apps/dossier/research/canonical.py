"""Turning many URLs for one article into a single identity.

The same story arrives as a Google News redirect, an AMP page, a syndication
partner's copy and three tracking-tagged shares. Counting those as separate
sources would inflate corroboration, which is the one number in a dossier that
has to stay honest. This module reduces a URL to a canonical form and to the
domain owner that independence is actually counted by.
"""

from __future__ import annotations

import base64
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

# Params that identify a campaign or a click, never a document.
JUNK_PREFIXES = ("utm_", "pk_", "mc_", "at_", "ns_", "cmpid", "cmp_")
JUNK_EXACT = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "igshid",
    "twclid",
    "ref",
    "ref_src",
    "referrer",
    "source",
    "spm",
    "cmpid",
    "smid",
    "smtyp",
    "partner",
    "sh",
    "share",
    "shared_from",
    "__twitter_impression",
    "guccounter",
    "amp",
    "output_type",
    "sref",
    "srnd",
    "taid",
    "leadSource",
    "ito",
    "CMP",
}

# Two-part public suffixes common enough to matter for news domains. A full
# public-suffix list would be a dependency for a handful of extra cases.
MULTI_SUFFIX = {
    "co.uk",
    "org.uk",
    "gov.uk",
    "ac.uk",
    "co.jp",
    "or.jp",
    "ne.jp",
    "co.nz",
    "co.za",
    "com.au",
    "net.au",
    "org.au",
    "gov.au",
    "com.br",
    "com.mx",
    "com.ar",
    "com.tr",
    "com.cn",
    "com.hk",
    "com.sg",
    "co.in",
    "co.kr",
    "com.ua",
    "co.il",
    "com.pk",
    "com.ph",
    "go.id",
    "co.id",
    "com.my",
}

_GNEWS_HOSTS = {"news.google.com"}
_AMP_TAIL = re.compile(r"(\.amp|/amp|/amp/|\?amp|amp\.html)$", re.I)


def _unwrap_google_news(url: str) -> str:
    """Google News wraps the real link in a base64 blob or a ?url= param."""
    parts = urlsplit(url)
    if parts.netloc.lower() not in _GNEWS_HOSTS:
        return url
    q = dict(parse_qsl(parts.query))
    for key in ("url", "u"):
        if q.get(key, "").startswith("http"):
            return unquote(q[key])
    m = re.search(r"/(?:articles|rss/articles)/([A-Za-z0-9_\-]+)", parts.path)
    if m:
        blob = m.group(1)
        pad = "=" * (-len(blob) % 4)
        try:
            raw = base64.urlsafe_b64decode(blob + pad)
            found = re.search(rb"https?://[\w\-./%?=&+:#~,;@!$'()*\[\]]+", raw)
            if found:
                return found.group(0).decode("utf-8", "ignore")
        except Exception:
            pass
    return url


def _strip_amp(path: str) -> str:
    """`/story/amp/` and `/story.amp` are the same document as `/story`."""
    path = re.sub(r"/amp(/|$)", "/", path, flags=re.I)
    path = _AMP_TAIL.sub("", path)
    return path or "/"


def canonical_url(url: str) -> str:
    """One URL per document, as stable as we can make it without fetching."""
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    url = _unwrap_google_news(url)
    parts = urlsplit(url)
    if not parts.netloc:
        return url

    scheme = "https"
    host = parts.netloc.lower().split("@")[-1]
    host = re.sub(r":(80|443)$", "", host)
    if host.startswith("www."):
        host = host[4:]
    for mobile in ("m.", "amp.", "mobile."):
        if host.startswith(mobile) and host.count(".") > 1:
            host = host[len(mobile) :]

    path = _strip_amp(parts.path)
    if len(path) > 1:
        path = path.rstrip("/")

    keep = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not (
            k.lower() in {j.lower() for j in JUNK_EXACT}
            or k.lower().startswith(JUNK_PREFIXES)
        )
    ]
    keep.sort()
    return urlunsplit((scheme, host, path, urlencode(keep), ""))


def registrable_domain(url_or_host: str) -> str:
    """The owner a source belongs to.

    Two BBC subdomains are one voice, not two, so corroboration counts this
    rather than the hostname.
    """
    host = url_or_host
    if "://" in host:
        host = urlsplit(host).netloc
    host = host.lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    bits = host.split(".")
    if len(bits) <= 2:
        return host
    last_two = ".".join(bits[-2:])
    if last_two in MULTI_SUFFIX and len(bits) >= 3:
        return ".".join(bits[-3:])
    return last_two


def same_document(a: str, b: str) -> bool:
    return canonical_url(a) == canonical_url(b)
