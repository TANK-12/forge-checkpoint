"""Fill in history: five years of news and the full article, for what is held.

A research pass now gathers both for any subject it touches, but a library of a
thousand subjects researched before that would otherwise only catch up one
watcher sweep at a time. This walks the library once:

1. download whatever months of the news archive are missing (sixty requests
   the first time, a couple after that);
2. for each subject with a Wikipedia article, match the archive against the
   article's title and every redirect to it, and fold the events in;
3. fetch the article itself for any subject that does not hold one yet.

No model is involved and nothing already stored is replaced - events merge on
the same date-and-title key as every research pass. It runs in its own thread,
can be stopped, and reindexes the library once at the end rather than after
every subject.
"""

from __future__ import annotations

import threading
from pathlib import Path

import dossier
import store
from research import news_archive as archive
from research.fetcher import now_iso, shared as shared_fetcher
from sources import wikipedia

_lock = threading.Lock()
_state: dict = {
    "running": False,
    "stage": "",
    "done": 0,
    "total": 0,
    "events_added": 0,
    "articles_added": 0,
    "started": "",
    "finished": "",
    "log": [],
}
_stop = threading.Event()


def _log(message: str) -> None:
    lines = _state["log"]
    lines.append(message)
    del lines[:-40]


def state(root: Path | None = None) -> dict:
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in _state.items()}
    try:
        out["archive"] = archive.status(root)
    except Exception as e:  # a missing drive must not break the Watch tab
        out["archive"] = {"error": f"{type(e).__name__}: {e}"}
    return out


def run(
    fetcher=None,
    root: Path | None = None,
    articles: bool = True,
    limit: int = 0,
    slugs: list[str] | None = None,
    refresh_articles: bool = False,
) -> dict:
    """The whole pass, synchronously. `start()` runs this in a thread.

    `slugs` limits it to named subjects - the per-dossier "Get new info"
    button. `refresh_articles` fetches a fresh copy of the article even when
    one is held; news still only ever merges in, so nothing stored is lost.
    """
    fetcher = fetcher or shared_fetcher()
    _stop.clear()
    _state.update(
        running=True,
        stage="news archive",
        done=0,
        total=0,
        events_added=0,
        articles_added=0,
        started=now_iso(),
        finished="",
        log=[],
    )
    try:
        held = archive.ensure(fetcher, root=root, log=_log, should_stop=_stop.is_set)
        _log(
            f"Archive: {held['fetched']} months downloaded, {held['failed']} failed, "
            f"{held['months']} in the window"
        )
        rows = dossier.library(root)
        if slugs:
            wanted = set(slugs)
            rows = [row for row in rows if row["slug"] in wanted]
        if limit:
            rows = rows[:limit]
        _state.update(stage="subjects", total=len(rows))
        for row in rows:
            if _stop.is_set():
                _log("Stopped")
                break
            _one(fetcher, row, root, articles, refresh_articles)
            _state["done"] += 1
        _state["stage"] = "reindexing"
        dossier.reindex(root)
    except Exception as e:
        _log(f"Stopped: {type(e).__name__}: {e}")
    finally:
        _state.update(running=False, stage="", finished=now_iso())
    return state(root)


def _one(
    fetcher, row: dict, root: Path | None, articles: bool, refresh: bool = False
) -> None:
    slug = row["slug"]
    subject = store.read_json(store.subject_dir(slug, root) / "subject.json", {})
    title = ((subject or {}).get("identity") or {}).get("wikipedia_title") or ""
    if not title:
        _log(f"{row.get('name', slug)}: no Wikipedia article to match - skipped")
        return
    titles = archive.titles_for(fetcher, title)
    events = archive.timeline_for(titles, root=root)
    article = None
    held_article = (store.subject_dir(slug, root) / "article.json").is_file()
    if articles and (refresh or not held_article):
        resolved, text = wikipedia.extract(fetcher, title)
        if resolved and text:
            article = wikipedia.article_from(resolved, text)
    changes = dossier.add_events(
        slug,
        events,
        report={
            "phase": "history",
            "started": now_iso(),
            "notes": [f"{len(events)} archive events matched {len(titles)} names"],
        },
        article=article,
        root=root,
    )
    _state["events_added"] += changes["timeline_added"]
    _state["articles_added"] += int(changes["article"])
    if changes["timeline_added"] or changes["article"]:
        _log(
            f"{row.get('name', slug)}: +{changes['timeline_added']} events"
            + (", article" if changes["article"] else "")
        )


def start(
    articles: bool = True,
    limit: int = 0,
    slugs: list[str] | None = None,
    refresh_articles: bool = False,
) -> bool:
    """Begin a pass in the background. False when one is already running."""
    with _lock:
        if _state["running"]:
            return False
        _state["running"] = True
    threading.Thread(
        target=run,
        kwargs={
            "articles": articles,
            "limit": limit,
            "slugs": slugs,
            "refresh_articles": refresh_articles,
        },
        daemon=True,
        name="history",
    ).start()
    return True


def stop() -> None:
    _stop.set()
