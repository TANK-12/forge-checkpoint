"""Wikipedia pageviews: the cleanest measure of public attention there is.

Almost every other attention signal is polluted — news volume measures what
editors chose to publish, forum activity measures whoever is awake and angry.
Pageviews measure what people actually went and looked up, daily, for every
subject with an article, going back years. It is free, needs no key, and the
Wikimedia Foundation publishes it as a matter of policy.

It is the anchor signal for this app: a subject whose pageviews break out of
their own baseline is one something has happened to, and that is true whether
or not a newsroom noticed.

The API wants an exact article title, so the title is taken from what Dossier
already resolved through Wikidata rather than guessed from the subject's name.
"""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

from .registry import Reading, SignalSpec

API = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
    "/{project}/all-access/user/{title}/daily/{start}/{end}"
)


def article_title(subject_name: str, stored: dict | None = None) -> str:
    """The exact article title to ask for.

    Dossier stores the Wikipedia title it resolved through Wikidata, which is
    how "Bongbong Marcos" reaches the article actually called
    "Bongbong Marcos" rather than a 404 on a name the user typed.
    """
    identity = ((stored or {}).get("subject") or {}).get("identity") or {}
    for key in ("wikipedia_title", "wikipedia", "label"):
        value = identity.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return subject_name


def fetch(subject_name: str, ctx) -> list[Reading]:
    """Daily views for the window the context asks for."""
    title = article_title(subject_name, getattr(ctx, "stored", None))
    if not title:
        return []
    end = date.today() - timedelta(days=1)  # today is always incomplete
    start = end - timedelta(days=max(1, int(getattr(ctx, "days", 60))))
    url = API.format(
        project=getattr(ctx, "project", "en.wikipedia"),
        title=quote(title.replace(" ", "_"), safe=""),
        start=start.strftime("%Y%m%d"),
        end=end.strftime("%Y%m%d"),
    )
    payload = ctx.fetcher.get_json(url, api=True)
    items = (payload or {}).get("items") or []
    readings = []
    for item in items:
        stamp = str(item.get("timestamp") or "")
        views = item.get("views")
        if len(stamp) < 8 or views is None:
            continue
        readings.append(
            Reading(
                date=f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}",
                value=float(views),
                detail=f"{views:,} views of '{title}'",
                url=f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
            )
        )
    ctx.log(f"pageviews: {len(readings)} days for {title}")
    return readings


SPEC = SignalSpec(
    name="pageviews",
    label="Wikipedia attention",
    kind="attention",
    unit="views a day",
    fetch=fetch,
    description="Daily article views — what people actually went and looked up.",
    caveat=(
        "Measures curiosity, not sentiment or importance. A scandal and a death "
        "look identical here. Redirects are counted separately from the article "
        "they point at, so a subject known by two names can read low."
    ),
    non_negative=True,
    whole_numbers=True,
)
