"""Lemmy: a second forum, with a different crowd from Hacker News.

One forum is an anecdote. Lemmy is federated, openly readable without a key,
and its largest instances skew politically engaged and more European than
Hacker News does — so where the two agree, the agreement means something, and
where they diverge, the divergence is itself the finding.

It is a much smaller sample than Reddit, which it is often described as
replacing, and that is recorded honestly on the spec rather than glossed over:
a handful of posts is not public opinion.

Read from one instance's search API, which federates in content from across the
network. The instance is configurable because instances go down, defederate and
change policy, and hardcoding one would make the source quietly stop working.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, timedelta

from .registry import Reading, SignalSpec

INSTANCE = os.environ.get("FORESIGHT_LEMMY_INSTANCE", "https://lemmy.world")


def fetch(subject_name: str, ctx) -> list[Reading]:
    days = max(1, int(getattr(ctx, "days", 60)))
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    payload = ctx.fetcher.get_json(
        f"{INSTANCE}/api/v3/search",
        api=True,
        params={
            "q": subject_name,
            "type_": "Posts",
            "sort": "New",
            "limit": "50",
            "listing_type": "All",
        },
    )
    posts = (payload or {}).get("posts") or []

    by_day: dict[str, list[dict]] = defaultdict(list)
    for entry in posts:
        published = str((entry.get("post") or {}).get("published") or "")[:10]
        if len(published) == 10 and published >= cutoff:
            by_day[published].append(entry)

    readings = []
    for day, entries in sorted(by_day.items()):
        score = sum(int((e.get("counts") or {}).get("score") or 0) for e in entries)
        comments = sum(
            int((e.get("counts") or {}).get("comments") or 0) for e in entries
        )
        top = max(entries, key=lambda e: int((e.get("counts") or {}).get("score") or 0))
        post = top.get("post") or {}
        readings.append(
            Reading(
                date=day,
                value=float(len(entries)),
                detail=(
                    f"{len(entries)} posts, {score} score, {comments} comments — "
                    f"top: {(post.get('name') or '')[:80]}"
                ),
                url=post.get("ap_id") or INSTANCE,
                sample=comments,
            )
        )
    ctx.log(f"lemmy: {len(readings)} days, {len(posts)} posts for {subject_name}")
    return readings


SPEC = SignalSpec(
    name="lemmy",
    label="Lemmy",
    kind="volume",
    unit="posts a day",
    fetch=fetch,
    description="Federated forum posts, scores and comment counts.",
    caveat=(
        "A small sample — often single-figure post counts — from a politically "
        "engaged, more European crowd than Hacker News. Useful as a second "
        "opinion against HN, not as a measure of public opinion on its own."
    ),
    non_negative=True,
    whole_numbers=True,
)
