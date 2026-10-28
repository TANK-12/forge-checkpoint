"""News events: how often the world's news digest names a subject, by month.

WHY IT IS HERE
    Every other attention signal starts the day it was first swept, or at best
    a few months back. Dossier now holds five years of Wikipedia's Current
    Events digest, and every item there links the people, countries and wars
    it is about. Counting the items that link a subject, month by month, gives
    a politics series with five years of history on its very first sweep.

READ ONLY
    The archive is Dossier's and lives in Dossier's library. This adapter never
    downloads a month into it - that is Dossier's job, started from its Watch
    tab or by any research pass - so an empty archive reads as no series here,
    not as a write into someone else's data.

    The current month is left out: it is not over, and a half-month count
    would read as a collapse.
"""

from __future__ import annotations

from datetime import date

from .registry import Reading, SignalSpec


def _archive():
    # Dossier's module, on the path `sweep` adds. Imported late so this file
    # still loads when Dossier is not beside Foresight.
    from research import news_archive  # type: ignore

    return news_archive


def fetch(subject_name: str, ctx) -> list[Reading]:
    import dossier_link

    root = dossier_link.root()
    identity = ((getattr(ctx, "stored", None) or {}).get("subject") or {}).get(
        "identity"
    ) or {}
    title = identity.get("wikipedia_title") or ""
    if root is None or not title:
        return []
    archive = _archive()
    this_month = date.today().strftime("%Y-%m")
    held = set(archive.held_months(root))
    months = [m for m in archive.months_in_window() if m in held and m != this_month]
    if not months:
        ctx.log("news_events: Dossier holds no news archive yet")
        return []
    titles = archive.titles_for(ctx.fetcher, title)
    counts = {month: 0 for month in months}
    for event in archive.match(titles, months=months, root=root):
        month = event["date"][:7]
        if month in counts:
            counts[month] += 1
    ctx.log(f"news_events: {sum(counts.values())} items over {len(months)} months")
    return [
        Reading(
            date=f"{month}-01",
            value=float(count),
            detail=f"{count} Current Events items linking {title} in {month}",
            url=archive.portal_url(month),
            sample=count,
            series="per-month",
        )
        for month, count in sorted(counts.items())
    ]


SPEC = SignalSpec(
    name="news_events",
    label="News events (Wikipedia)",
    kind="politics",
    unit="items a month",
    fetch=fetch,
    description=(
        "Items in Wikipedia's daily Current Events digest that link this subject, "
        "counted by month over the past five years."
    ),
    caveat=(
        "Measures what volunteer editors chose to record, which leans towards "
        "English-language and Western coverage. A subject linked under a "
        "different article - a ministry rather than its minister - is not "
        "counted. Months not yet downloaded by Dossier read as missing, not zero."
    ),
    non_negative=True,
    whole_numbers=True,
    fresh_days=45,  # monthly counts
)
