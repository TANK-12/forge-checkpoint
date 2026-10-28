"""News archive: five years of dated world news naming this subject.

The archive itself lives in `research/news_archive.py` and is shared by the
whole library - sixty month pages downloaded once. This adapter only asks it
which events link to this subject's Wikipedia article, or to any redirect to
it, and files each one as a dated `news` entry carrying its outlet citations.

No model, no search engine and no name guessing: an event belongs to a subject
because a Wikipedia editor linked the subject's article in it.
"""

from __future__ import annotations

from research import news_archive as archive
from research.scoring import SubjectProfile

from .registry import Context, Harvest, SourceSpec


def fetch(subject: SubjectProfile, ctx: Context) -> Harvest:
    harvest = Harvest()
    title = ctx.identity.get("wikipedia_title") or ""
    if not title:
        harvest.notes.append(
            "News archive: no English Wikipedia article to match events against"
        )
        return harvest
    held = archive.ensure(ctx.fetcher, log=ctx.log)
    if held["failed"]:
        harvest.notes.append(
            f"News archive: {held['failed']} months did not download; "
            "they are retried on the next pass"
        )
    titles = archive.titles_for(ctx.fetcher, title)
    events = archive.timeline_for(titles)
    harvest.timeline.extend(events)
    ctx.log(
        f"News archive: {len(events)} events over {archive.YEARS} years "
        f"naming {title} ({len(titles)} names matched)"
    )
    return harvest


SPEC = SourceSpec(
    name="news_archive",
    label="News archive (5 years)",
    tier="encyclopedic",
    phases=("quick", "deep"),
    entity_types=("*",),
    fetch=fetch,
    description=(
        "Wikipedia's daily Current Events digest for the past five years: every "
        "item that links this subject, with the outlets it cites."
    ),
)
