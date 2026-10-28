"""Hacker News: argument volume and engagement, with the text attached.

Reddit is the obvious forum to read and it now returns 403 to anything without
OAuth, so Hacker News is the one substantial public forum still readable with
no key at all. Its Algolia index gives, per story: points, comment count, and
the date — which is an engagement measurement — plus the comment text itself,
which is what the sentiment analyser reads.

Two numbers come out of this, deliberately kept apart:

* **volume** — how many stories mentioned the subject that day. Attention.
* **engagement** — points and comments per story. How much people cared enough
  to argue, which is a different and more interesting thing than how many
  outlets wrote something.

The obvious and important caveat is the audience. This is one demographic —
largely technical, largely American, largely male — and it is recorded on the
spec so the interface always shows it beside the number. A signal presented
without its bias is worse than no signal.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from .registry import Reading, SignalSpec

SEARCH = "https://hn.algolia.com/api/v1/search_by_date"


def fetch(subject_name: str, ctx) -> list[Reading]:
    days = max(1, int(getattr(ctx, "days", 60)))
    since = date.today() - timedelta(days=days)
    payload = ctx.fetcher.get_json(
        SEARCH,
        api=True,
        params={
            "query": subject_name,
            "tags": "story",
            "hitsPerPage": "200",
            "numericFilters": f"created_at_i>{int(since.strftime('%s') or 0)}",
        },
    )
    hits = (payload or {}).get("hits") or []

    # Group by day: one reading per day, not one per story, so the series lines
    # up with every other source and can be compared against them.
    by_day: dict[str, list[dict]] = defaultdict(list)
    for hit in hits:
        stamp = str(hit.get("created_at") or "")[:10]
        if len(stamp) == 10:
            by_day[stamp].append(hit)

    readings = []
    for day, stories in sorted(by_day.items()):
        points = sum(int(s.get("points") or 0) for s in stories)
        comments = sum(int(s.get("num_comments") or 0) for s in stories)
        top = max(stories, key=lambda s: int(s.get("points") or 0))
        readings.append(
            Reading(
                date=day,
                value=float(len(stories)),
                detail=(
                    f"{len(stories)} stories, {points} points, {comments} comments — "
                    f"top: {(top.get('title') or '')[:80]}"
                ),
                url=f"https://news.ycombinator.com/item?id={top.get('objectID')}",
                sample=comments,
            )
        )
    ctx.log(
        f"hacker news: {len(readings)} days, {len(hits)} stories for {subject_name}"
    )
    return readings


SPEC = SignalSpec(
    name="hn",
    label="Hacker News",
    kind="volume",
    unit="stories a day",
    fetch=fetch,
    description="Story count, points and comment volume — how much a forum argued.",
    caveat=(
        "One narrow audience: largely technical, largely American. Excellent on "
        "technology, companies and policy that touches them; close to silent on "
        "most of the world's politics. Never read a low number here as 'nobody "
        "cares' — only as 'this audience did not'."
    ),
    non_negative=True,
    whole_numbers=True,
)
