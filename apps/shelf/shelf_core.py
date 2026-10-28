"""Shelf: read-later articles, kept offline as clean text and pictures.

WHAT IT DOES
    save(url) fetches a page, lets trafilatura cut it down to the article
    (title, author, date, text, pictures), cleans that HTML to an allow-list
    of tags (shelf.json "tags"; no scripts, no styles, links only to http,
    https and mailto), downloads the pictures beside it and stores it:

        <data>/shelf.db                 SQLite: one row per article, plus an
                                        FTS5 index over title, author, text
        <data>/articles/<id>/article.html   the cleaned article
        <data>/articles/<id>/images/        its pictures, served by Shelf

    Fetching happens in Shelf's backend, so a URL may never point at this
    laptop or the home network: every address a host name resolves to, and
    every redirect, must be a public one (SHELF_ALLOW_LOCAL=1 lifts this for
    tests only).

    send(entry, name) passes an article on to another app through the
    shelf.json "send_to" registry (Dossier researches a name from it).
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "noscript"}
DROP_WITH_CONTENT |= {"svg", "math", "template", "form", "button", "select"}
VOID = {"img", "br", "hr", "embed", "source", "track", "wbr", "input", "area"}
IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
}


def expand(p: str) -> Path:
    return Path(os.path.expanduser(p))


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text())
    if os.environ.get("SHELF_DATA"):
        cfg["data"] = os.environ["SHELF_DATA"]
    return cfg


# --- fetching, public addresses only -----------------------------------------


class FetchError(RuntimeError):
    pass


def allow_local() -> bool:
    return os.environ.get("SHELF_ALLOW_LOCAL") == "1"


def check_public(url: str) -> None:
    """Refuse a URL that is not http(s) or has no usable host and port. The
    address itself is checked when connecting (_public_socket)."""
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port  # raises ValueError for a port that is not a number
    except ValueError as e:
        raise FetchError("that address does not read as one") from e
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("only http and https addresses can be saved")


def _public_socket(host: str, port: int, timeout: float) -> socket.socket:
    """Resolve once, refuse anything not on the public internet (loopback,
    the home network, link-local and the like) and connect to that same
    checked address, so a second DNS answer cannot point somewhere else."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise FetchError(f"no such site: {host}") from e
    if not allow_local():
        for info in infos:
            if not ipaddress.ip_address(info[4][0]).is_global:
                raise FetchError(f"{host} is not a public address")
    last: OSError = OSError(f"could not connect to {host}")
    for family, kind, proto, _, addr in infos:
        sock = socket.socket(family, kind, proto)
        sock.settimeout(timeout)
        try:
            sock.connect(addr)
            return sock
        except OSError as e:
            sock.close()
            last = e
    raise last


class _PublicHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = _public_socket(self.host, self.port, self.timeout or 20)


class _PublicHTTPS(http.client.HTTPSConnection):
    def connect(self):
        sock = _public_socket(self.host, self.port, self.timeout or 20)
        ctx = ssl.create_default_context()
        self.sock = ctx.wrap_socket(sock, server_hostname=self.host)


class _PublicHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PublicHTTP, req)


class _PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PublicHTTPS, req)


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public(newurl)  # the scheme; the address is checked on connect
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# no ProxyHandler: a proxy from the environment would hide the real address
_opener = urllib.request.OpenerDirector()
for _h in (
    _PublicHTTPHandler(),
    _PublicHTTPSHandler(),
    _Redirects(),
    urllib.request.HTTPErrorProcessor(),
    urllib.request.HTTPDefaultErrorHandler(),
):
    _opener.add_handler(_h)


@dataclass
class Fetched:
    url: str
    body: bytes
    content_type: str
    charset: str | None = None


def fetch(url: str, cfg: dict, limit_mb: float | None = None) -> Fetched:
    """One page or picture, at most limit_mb and cfg["deadline"] seconds."""
    check_public(url)
    limit = int((limit_mb or cfg["max_page_mb"]) * 1024 * 1024)
    deadline = time.monotonic() + cfg.get("deadline", 60)
    req = urllib.request.Request(url, headers={"User-Agent": cfg["user_agent"]})
    try:
        with _opener.open(req, timeout=cfg["timeout"]) as r:
            chunks, size = [], 0
            while size <= limit:
                if time.monotonic() > deadline:
                    raise FetchError("the site is sending too slowly")
                chunk = r.read1(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            body = b"".join(chunks)
            final = r.geturl()
            ctype = r.headers.get_content_type()
            charset = r.headers.get_content_charset()
    except urllib.error.HTTPError as e:
        raise FetchError(f"the site answered {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise FetchError(f"could not reach it: {getattr(e, 'reason', e)}") from e
    except ValueError as e:  # http.client.InvalidURL and the like
        raise FetchError("that address does not read as one") from e
    if len(body) > limit:
        raise FetchError(f"bigger than {limit // 1048576} MB")
    return Fetched(final, body, ctype, charset)


def decode(page: Fetched) -> str:
    """The page as text: the charset the site named, else trafilatura's
    guess from the bytes (meta charset, then detection)."""
    if page.charset:
        try:
            return page.body.decode(page.charset)
        except (LookupError, UnicodeDecodeError):
            pass
    from trafilatura.utils import decode_file

    return decode_file(page.body, max_size=len(page.body) + 1)


Fetcher = Callable[..., Fetched]


# --- cleaning ------------------------------------------------------------------


class Cleaner(HTMLParser):
    """Rebuilds HTML keeping only allowed tags and a few safe attributes.
    Pictures are kept only when `image_src` maps their URL to a local one."""

    def __init__(self, tags: set[str], image_src: Callable[[str], str | None]):
        super().__init__(convert_charrefs=True)
        self.tags, self.image_src = tags, image_src
        self.out: list[str] = []
        self.open: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            if tag not in VOID:
                self.skip += 1
            return
        if self.skip or tag not in self.tags:
            return
        a = {k: v or "" for k, v in attrs}
        keep = ""
        if tag == "a":
            href = a.get("href", "").strip()
            if re.match(r"^(https?:|mailto:)", href, re.I):
                keep = (
                    f' href="{escape(href)}" rel="noopener noreferrer" target="_blank"'
                )
        elif tag == "img":
            src = self.image_src(a.get("src", ""))
            if not src:
                return
            keep = (
                f' src="{escape(src)}" alt="{escape(a.get("alt", ""))}" loading="lazy"'
            )
        elif tag in ("td", "th"):
            for k in ("colspan", "rowspan"):
                if a.get(k, "").isdigit():
                    keep += f' {k}="{a[k]}"'
        self.out.append(f"<{tag}{keep}>")
        if tag not in VOID:
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:  # <script/>: nothing inside to drop
            return
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.open and self.open[-1] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in self.open:
            return
        while self.open:
            t = self.open.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data, quote=False))

    def result(self) -> str:
        self.close()
        return "".join(self.out) + "".join(f"</{t}>" for t in reversed(self.open))


def clean(html: str, cfg: dict, image_src: Callable[[str], str | None]) -> str:
    c = Cleaner(set(cfg["tags"]), image_src)
    c.feed(html)
    return c.result()


def image_urls(html: str, cfg: dict) -> list[str]:
    """The remote pictures the cleaner would keep, in order: found by the
    same pass, so one inside <noscript> or an <svg> is never downloaded."""
    seen: list[str] = []

    def note(src: str) -> None:
        if src.startswith(("http://", "https://")) and src not in seen:
            seen.append(src)

    clean(html, cfg, note)
    return seen


# --- extraction ----------------------------------------------------------------


def extract(html: str, url: str, min_words: int = 20) -> dict:
    import trafilatura

    meta = trafilatura.bare_extraction(
        html, url=url, include_images=True, include_links=True, with_metadata=True
    )
    body = trafilatura.extract(
        html,
        url=url,
        output_format="html",
        include_images=True,
        include_links=True,
        include_formatting=True,
    )
    # plain words for search and counting: no link or picture markup
    text = trafilatura.extract(html, output_format="txt", url=url) or ""
    if not body or len(text.split()) < min_words:
        raise FetchError("no article found on that page")

    def field(name: str) -> str:
        return str(getattr(meta, name, None) or "")

    return {
        "title": field("title") or urllib.parse.urlsplit(url).hostname or url,
        "author": field("author"),
        "published": field("date"),
        "site": field("sitename") or field("hostname"),
        "html": body,
        "text": text,
    }


# --- the shelf -----------------------------------------------------------------


SCHEMA = """
create table if not exists articles (
  id text primary key, url text unique, title text, author text, site text,
  published text, saved real, words integer, read integer default 0,
  archived integer default 0, images integer default 0
);
create virtual table if not exists search using fts5(id unindexed, title, author, body);
"""

COLUMNS = (
    "id",
    "url",
    "title",
    "author",
    "site",
    "published",
    "saved",
    "words",
    "read",
    "archived",
    "images",
)


class Shelf:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.root = expand(cfg["data"])
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.db_path = self.root / "shelf.db"
        with self.db() as db:
            db.executescript(SCHEMA)

    def db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def folder(self, aid: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{12}", aid):
            raise KeyError(aid)
        return self.root / "articles" / aid

    def row(self, r: sqlite3.Row) -> dict:
        d = {k: r[k] for k in COLUMNS}
        d["read"], d["archived"] = bool(d["read"]), bool(d["archived"])
        d["minutes"] = max(1, round((d["words"] or 0) / self.cfg["words_per_minute"]))
        return d

    def by_url(self, url: str) -> dict | None:
        with self.db() as db:
            r = db.execute("select * from articles where url = ?", (url,)).fetchone()
        return self.row(r) if r else None

    def get(self, aid: str) -> dict:
        with self.db() as db:
            r = db.execute("select * from articles where id = ?", (aid,)).fetchone()
        if not r:
            raise KeyError(aid)
        d = self.row(r)
        f = self.folder(aid) / "article.html"
        d["html"] = f.read_text() if f.is_file() else ""
        return d

    def listing(self, view: str = "unread", q: str = "") -> list[dict]:
        where = {
            "unread": "not a.read and not a.archived",
            "all": "not a.archived",
            "archived": "a.archived",
        }.get(view, "1")
        words = re.findall(r"\w+", q, re.UNICODE)
        with self.db() as db:
            if words:
                match = " ".join('"' + w.replace('"', "") + '"*' for w in words)
                rows = db.execute(
                    "select a.*, snippet(search, 3, '<mark>', '</mark>', ' … ', 18) as snip"
                    " from search join articles a on a.id = search.id"
                    f" where search match ? and {where} order by rank limit 200",
                    (match,),
                ).fetchall()
            else:
                rows = db.execute(
                    f"select a.*, '' as snip from articles a where {where}"
                    " order by saved desc limit 500"
                ).fetchall()
        out = []
        for r in rows:
            d = self.row(r)
            # the snippet is FTS5 text with only our <mark> added; escape the rest
            d["snippet"] = (
                escape(r["snip"])
                .replace("&lt;mark&gt;", "<mark>")
                .replace("&lt;/mark&gt;", "</mark>")
            )
            out.append(d)
        return out

    def counts(self) -> dict:
        with self.db() as db:
            r = db.execute(
                "select sum(not read and not archived), sum(not archived), sum(archived)"
                " from articles"
            ).fetchone()
        return {"unread": r[0] or 0, "all": r[1] or 0, "archived": r[2] or 0}

    def mark(self, aid: str, **flags: bool) -> dict:
        self.get(aid)
        with self.db() as db:
            for k, v in flags.items():
                if k in ("read", "archived"):
                    db.execute(
                        f"update articles set {k} = ? where id = ?", (int(v), aid)
                    )
        return self.get(aid)

    def remove(self, aid: str, trash: Callable[[Path], None]) -> None:
        self.get(aid)
        folder = self.folder(aid)
        if folder.exists():
            trash(folder)
        with self.db() as db:
            db.execute("delete from articles where id = ?", (aid,))
            db.execute("delete from search where id = ?", (aid,))

    def save(self, url: str, fetcher: Fetcher = fetch) -> tuple[dict, bool]:
        """(article, True) when newly saved; (article, False) when it was
        already on the shelf under that address."""
        url = url.strip()
        if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            raise FetchError("only http and https addresses can be saved")
        known = self.by_url(url)
        if known:
            return known, False
        page = fetcher(url, self.cfg)
        if page.content_type not in ("text/html", "application/xhtml+xml"):
            raise FetchError(f"that is a {page.content_type} file, not a page")
        known = self.by_url(page.url)
        if known:
            return known, False
        art = extract(decode(page), page.url, self.cfg.get("min_words", 20))
        aid = hashlib.sha256(page.url.encode()).hexdigest()[:12]
        folder = self.folder(aid)
        (folder / "images").mkdir(parents=True, exist_ok=True)
        local = self._pictures(aid, art["html"], fetcher)
        html = clean(art["html"], self.cfg, local.get)
        (folder / "article.html").write_text(html)
        try:
            self._insert(aid, page.url, art, len(local))
        except sqlite3.IntegrityError:  # saved by a second click meanwhile
            pass
        return self.get(aid), True

    def _insert(self, aid: str, url: str, art: dict, images: int) -> None:
        words = len(art["text"].split())
        with self.db() as db:
            db.execute(
                "insert into articles (id, url, title, author, site, published, saved,"
                " words, images) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    aid,
                    url,
                    art["title"],
                    art["author"],
                    art["site"],
                    art["published"],
                    time.time(),
                    words,
                    images,
                ),
            )
            db.execute(
                "insert into search (id, title, author, body) values (?, ?, ?, ?)",
                (aid, art["title"], art["author"], art["text"]),
            )

    def _pictures(self, aid: str, html: str, fetcher: Fetcher) -> dict[str, str]:
        """Download the article's pictures; {remote url: local url}. A picture
        that fails, is too big or is not an image is left out."""
        out: dict[str, str] = {}
        stop = time.monotonic() + self.cfg.get("pictures_deadline", 120)
        for n, src in enumerate(image_urls(html, self.cfg)[: self.cfg["max_images"]]):
            if time.monotonic() > stop:
                break
            try:
                got = fetcher(src, self.cfg, self.cfg["max_image_mb"])
            except FetchError:
                continue
            ext = IMAGE_TYPES.get(got.content_type)
            if not ext:
                continue
            name = f"{n:03d}{ext}"
            (self.folder(aid) / "images" / name).write_bytes(got.body)
            out[src] = f"/api/image/{aid}/{name}"
        return out

    def image(self, aid: str, name: str) -> Path:
        if not re.fullmatch(r"\d{3}\.[a-z]{3,4}", name):
            raise KeyError(name)
        p = self.folder(aid) / "images" / name
        if not p.is_file():
            raise KeyError(name)
        return p


# --- passing an article on -----------------------------------------------------


def fill(value, name: str):
    if isinstance(value, str):
        return value.replace("{name}", name)
    if isinstance(value, dict):
        return {k: fill(v, name) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, name) for v in value]
    return value


def send(target: dict, name: str, post: Callable | None = None) -> None:
    name = name.strip()
    if not name:
        raise ValueError("a name is needed")
    body = json.dumps(fill(target["body"], name)).encode()
    req = urllib.request.Request(
        target["url"],
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with (post or urllib.request.urlopen)(req, timeout=15) as r:
            r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{target['label']}: it answered {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(
            f"could not reach it ({getattr(e, 'reason', e)}); is it open in Forge?"
        ) from e
