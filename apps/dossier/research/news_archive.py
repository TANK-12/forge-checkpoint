"""Five years of the world's news, from Wikipedia's Current Events portal.

WHY THIS SOURCE
    Every news adapter Dossier had looked backwards a few weeks at most. Google
    News returns what is recent, GDELT's article search covers a rolling three
    months and is rate-limited from this machine, and so a dossier held dated
    offices from Wikidata and almost no news. The user asked for the past year
    and the past five years.

    The Current Events portal is a daily, edited digest of world news going
    back decades. Each item is one or two sentences that **cite the outlets
    they came from**, and - the part that makes it worth building on - every
    person, country, party and war named in an item is a wiki link. Linking an
    event to a subject is therefore an exact article-title match, not a guess
    from a surname, which is the same standard Wikidata identity already sets.

HOW IT IS STORED
    One month of the portal is one API request (the month page transcludes
    every day), so five years is sixty requests - done once, library-wide, and
    shared by every subject. Each month is parsed into plain events and kept at
    `news_archive/YYYY-MM.json` beside the library. A month that ended more than
    a week before it was fetched is final and never fetched again; the current
    and last month are refreshed after `FRESH_SECONDS`, because the portal is
    still being written.

WHAT AN EVENT IS NOT
    A summary written by Wikipedia editors, not a primary report. Every event
    keeps its outlet citations so the original can be opened, and the adapter
    files these as `reported`, never `verified`.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from bs4 import BeautifulSoup, Tag

API = "https://en.wikipedia.org/w/api.php"
ARCHIVE_DIR = "news_archive"
YEARS = 5
# The current month is still being written; a finished month is not.
FRESH_SECONDS = 6 * 3600
FINAL_AFTER_DAYS = 7
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
# Links into these namespaces are furniture, not subjects.
_SKIP_NAMESPACES = (
    "File:",
    "Category:",
    "Portal:",
    "Help:",
    "Wikipedia:",
    "Template:",
    "Special:",
    "Talk:",
)


# --- which months -----------------------------------------------------------


def months_in_window(today: date | None = None, years: int = YEARS) -> list[str]:
    """Every month from `years` ago up to and including this one, oldest first."""
    today = today or date.today()
    year, month = today.year - years, today.month
    out = []
    while (year, month) <= (today.year, today.month):
        out.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def portal_title(month_key: str) -> str:
    year, month = month_key.split("-")
    return f"Portal:Current events/{MONTHS[int(month) - 1]} {year}"


def portal_url(month_key: str) -> str:
    return "https://en.wikipedia.org/wiki/" + portal_title(month_key).replace(" ", "_")


# --- parsing ----------------------------------------------------------------


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", text)


def _is_citation(node) -> bool:
    return (
        isinstance(node, Tag)
        and node.name == "a"
        and "external" in (node.get("class") or [])
    )


def _wiki_title(anchor: Tag) -> str:
    href = str(anchor.get("href") or "")
    title = str(anchor.get("title") or "")
    if not href.startswith("/wiki/") or not title:
        return ""
    if title.startswith(_SKIP_NAMESPACES):
        return ""
    return title


def _own_parts(li: Tag) -> tuple[str, list[str], list[dict]]:
    """The text, wiki links and citations belonging to this item itself.

    A nested list is a child item and is read separately, so it is excluded
    here; otherwise a topic heading would swallow every event beneath it.
    """
    words: list[str] = []
    links: list[str] = []
    citations: list[dict] = []
    for child in li.children:
        if isinstance(child, Tag) and child.name in ("ul", "ol"):
            continue
        if isinstance(child, Tag) and child.name == "a":
            # find_all() searches below a tag, never the tag itself.
            anchors = [child]
        elif isinstance(child, Tag):
            anchors = child.find_all("a")
        else:
            words.append(str(child))
            continue
        for anchor in anchors:
            if _is_citation(anchor):
                outlet = _clean(anchor.get_text(" ")).strip("() ")
                url = str(anchor.get("href") or "")
                if url and not any(c["url"] == url for c in citations):
                    citations.append({"outlet": outlet, "url": url})
            else:
                title = _wiki_title(anchor)
                if title and title not in links:
                    links.append(title)
        if _is_citation(child):
            continue
        # Text of a tag with its citation anchors left out.
        for piece in child.descendants:
            if isinstance(piece, str) and not any(
                _is_citation(parent) for parent in piece.parents if parent is not li
            ):
                words.append(str(piece))
    return _clean("".join(words)), links, citations


def _walk(ul: Tag, day: str, category: str, topics: list[str], out: list[dict]) -> None:
    for li in ul.find_all("li", recursive=False):
        text, links, citations = _own_parts(li)
        nested = li.find_all(["ul", "ol"], recursive=False)
        if nested:
            # A heading such as "Russo-Ukrainian War": its links become the
            # topic chain of every event filed beneath it.
            for sub in nested:
                _walk(sub, day, category, topics + links, out)
            if not citations:
                continue
        if not text or len(text) < 12:
            continue
        out.append(
            {
                "date": day,
                "category": category,
                "text": text,
                "links": links,
                "topics": list(dict.fromkeys(topics)),
                "citations": citations,
            }
        )


def parse_month(html: str) -> list[dict]:
    """Every event on one rendered month page, in page order."""
    soup = BeautifulSoup(html, "lxml")
    events: list[dict] = []
    for block in soup.select("div.current-events-main"):
        stamp = block.select_one(".bday")
        day = (stamp.get_text() if stamp else "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            continue
        content = block.select_one(".current-events-content")
        if content is None:
            continue
        category = ""
        for child in content.children:
            if not isinstance(child, Tag):
                continue
            if child.name in ("p", "div") and child.find("b"):
                category = _clean(child.get_text(" "))
            elif child.name in ("ul", "ol"):
                _walk(child, day, category, [], events)
    return events


# --- storage ----------------------------------------------------------------


def archive_dir(root: Path | None = None) -> Path:
    if root is None:
        import store

        root = store.data_root().path
    return root / ARCHIVE_DIR


def _month_path(month_key: str, root: Path | None = None) -> Path:
    return archive_dir(root) / f"{month_key}.json"


def _read(path: Path) -> dict:
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(path: Path, payload: dict) -> None:
    import json
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _is_final(month_key: str, fetched: str) -> bool:
    year, month = (int(x) for x in month_key.split("-"))
    first_of_next = date(year + (month == 12), month % 12 + 1, 1)
    try:
        when = datetime.fromisoformat(fetched).date()
    except ValueError:
        return False
    return (when - first_of_next).days >= FINAL_AFTER_DAYS


def needs_fetch(month_key: str, root: Path | None = None, now: float = 0.0) -> bool:
    held = _read(_month_path(month_key, root))
    if not held.get("fetched"):
        return True
    if held.get("final"):
        return False
    try:
        age = (now or time.time()) - datetime.fromisoformat(held["fetched"]).timestamp()
    except ValueError:
        return True
    return age > FRESH_SECONDS


_fetch_lock = threading.Lock()


def fetch_month(fetcher, month_key: str, root: Path | None = None) -> int | None:
    """Download and store one month. Returns the event count, or None on failure."""
    data = fetcher.get_json(
        API,
        params={
            "action": "parse",
            "page": portal_title(month_key),
            "prop": "text",
            "format": "json",
            "formatversion": "2",
        },
        api=True,
    )
    html = ((data or {}).get("parse") or {}).get("text") or ""
    if not html:
        return None
    events = parse_month(html)
    fetched = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    _write(
        _month_path(month_key, root),
        {
            "month": month_key,
            "fetched": fetched,
            "final": _is_final(month_key, fetched),
            "url": portal_url(month_key),
            "events": events,
        },
    )
    _index_cache.pop((str(root), month_key), None)
    return len(events)


def ensure(
    fetcher,
    months: list[str] | None = None,
    root: Path | None = None,
    log: Callable[[str], None] = lambda message: None,
    should_stop: Callable[[], bool] = lambda: False,
) -> dict:
    """Make sure every month in the window is held. Safe to call from any thread.

    Only one caller downloads at a time; the others wait and then find the
    months already there, so four workers starting at once cost sixty requests
    rather than two hundred and forty.
    """
    months = months or months_in_window()
    fetched = failed = 0
    with _fetch_lock:
        for month_key in months:
            if should_stop():
                break
            if not needs_fetch(month_key, root):
                continue
            count = fetch_month(fetcher, month_key, root)
            if count is None:
                failed += 1
                log(f"News archive: {month_key} did not download")
            else:
                fetched += 1
                log(f"News archive: {month_key} - {count} events")
    return {"months": len(months), "fetched": fetched, "failed": failed}


# --- reading ----------------------------------------------------------------

# (root, month) -> (mtime, events, {casefolded title: [event index]})
_index_cache: dict[tuple[str, str], tuple[float, list[dict], dict[str, list[int]]]] = {}
_index_lock = threading.Lock()


def _month_index(
    month_key: str, root: Path | None = None
) -> tuple[list[dict], dict[str, list[int]]]:
    path = _month_path(month_key, root)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return [], {}
    key = (str(root), month_key)
    with _index_lock:
        cached = _index_cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1], cached[2]
    events = _read(path).get("events") or []
    index: dict[str, list[int]] = {}
    for i, event in enumerate(events):
        for title in {t.casefold() for t in event.get("links", [])} | {
            t.casefold() for t in event.get("topics", [])
        }:
            index.setdefault(title, []).append(i)
    with _index_lock:
        _index_cache[key] = (mtime, events, index)
    return events, index


def held_months(root: Path | None = None) -> list[str]:
    directory = archive_dir(root)
    if not directory.is_dir():
        return []
    return sorted(
        p.stem for p in directory.glob("*.json") if re.fullmatch(r"\d{4}-\d{2}", p.stem)
    )


def status(root: Path | None = None) -> dict:
    window = months_in_window()
    held = held_months(root)
    events = sum(len(_month_index(m, root)[0]) for m in held)
    return {
        "window_start": window[0],
        "window_end": window[-1],
        "months_in_window": len(window),
        "months_held": len([m for m in window if m in held]),
        "events": events,
        "oldest": held[0] if held else "",
        "newest": held[-1] if held else "",
    }


def match(
    titles: set[str] | list[str],
    months: list[str] | None = None,
    root: Path | None = None,
) -> list[dict]:
    """Events naming any of these article titles, newest first.

    Each result carries `how`: `topic` when the subject is the heading the
    event was filed under, `named` when it is linked in the sentence itself.
    """
    wanted = {t.casefold() for t in titles if t}
    if not wanted:
        return []
    out = []
    for month_key in months or months_in_window():
        events, index = _month_index(month_key, root)
        hits: set[int] = set()
        for title in wanted:
            hits.update(index.get(title, ()))
        for i in sorted(hits):
            event = events[i]
            topical = any(t.casefold() in wanted for t in event.get("topics", []))
            out.append({**event, "how": "topic" if topical else "named"})
    out.sort(key=lambda e: e["date"], reverse=True)
    return out


def titles_for(fetcher, title: str) -> set[str]:
    """The article title plus every redirect to it.

    Portal editors link whatever name reads naturally - "Zelenskyy", "Russian"
    - and those are redirects, so the canonical title alone would miss most of
    what names a subject. One request.
    """
    if not title:
        return set()
    data = fetcher.get_json(
        API,
        params={
            "action": "query",
            "titles": title,
            "redirects": "1",
            "prop": "redirects",
            "rdnamespace": "0",
            "rdlimit": "max",
            "format": "json",
            "formatversion": "2",
        },
        api=True,
    )
    titles = {title}
    for page in ((data or {}).get("query") or {}).get("pages") or []:
        if page.get("title"):
            titles.add(page["title"])
        for redirect in page.get("redirects") or []:
            if redirect.get("title"):
                titles.add(redirect["title"])
    return titles


# How many archive events one subject keeps. A country is linked from thousands
# of items a year; past this, the ones filed under the subject as a topic and
# the most recent are kept first.
CAP = 1500


def to_timeline(event: dict) -> dict:
    citations = event.get("citations") or []
    outlets = ", ".join(c["outlet"] for c in citations if c.get("outlet"))
    where = " › ".join(event.get("topics") or [])
    detail_bits = [b for b in (event.get("category"), where) if b]
    if outlets:
        detail_bits.append(f"reported by {outlets}")
    return {
        "date": event["date"],
        "end": "",
        "title": event["text"],
        "kind": "news",
        "detail": " · ".join(detail_bits),
        "source_id": "news_archive",
        "url": citations[0]["url"] if citations else "",
        "citations": citations,
        "category": event.get("category", ""),
        "topics": event.get("topics", []),
        "how": event.get("how", ""),
        "confidence": "reported",
    }


def timeline_for(titles: set[str], root: Path | None = None, cap: int = CAP) -> list:
    events = match(titles, root=root)
    if len(events) > cap:
        # Stable sort: topic events first, each group still newest first.
        events = sorted(events, key=lambda e: e["how"] != "topic")[:cap]
    return [to_timeline(e) for e in events]
