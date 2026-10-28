"""World Bank indicators: the economic numbers, as series rather than trivia.

WHY THIS EXISTS
    Until this landed, every signal here measured **attention** — how many
    people looked a subject up, how loudly a forum argued about it. The user
    put it plainly: "i want it to store finlcian and economic and polotacl
    things not just how may time they wrer searche dup, that says nothing".
    They are right. A pageview spike tells you something happened; it cannot
    tell you whether a country's unemployment is rising or its debt is running
    away.

    These are the rare numbers that need no interpretation: a published figure
    with a year attached, from the organisation that publishes it. Free, no API
    key, and treated as a primary source.

WHAT IT IS NOT
    Annual, and revised. A World Bank series is not a daily signal and must
    never be read like one — see `analysis/level.py`, which is the analyser
    written for slow series, and note that the breakout z-score deliberately
    ignores sources whose readings are years apart.

THE INDICATOR LIST IS DOSSIER'S
    Imported from `sources/worldbank.py` rather than copied. Dossier already
    harvests exactly these nine for its economy page; a second list here would
    drift the first time one was added, and the user's standing rule is one
    real copy of a shared thing.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .registry import Reading, SignalSpec

API = "https://api.worldbank.org/v2"

# Fallback only. The real list is Dossier's, imported below; this exists so a
# Foresight running without Dossier beside it still reads something useful
# rather than raising at import time.
_FALLBACK = {
    "NY.GDP.MKTP.CD": ("GDP", "US$"),
    "SL.UEM.TOTL.ZS": ("Unemployment", "% of labour force"),
    "FP.CPI.TOTL.ZG": ("Inflation", "% a year"),
}


def indicators() -> dict[str, tuple[str, str]]:
    try:
        from sources.worldbank import INDICATORS  # type: ignore

        return {
            code: (label, unit) for code, (label, unit, *_rest) in INDICATORS.items()
        }
    except Exception:
        return dict(_FALLBACK)


def _iso3(ctx, country: str) -> str:
    """The World Bank's own country code, asked of the World Bank.

    Dossier's `countrycodes` does this too, but it wants a SubjectProfile and
    a Dossier Context. The question is one request, so it is asked directly
    rather than dragging that shape across the boundary.
    """
    payload = ctx.fetcher.get_json(f"{API}/country?format=json&per_page=400", api=True)
    rows = (payload or [None, []])[1] or []
    want = country.strip().lower()
    for row in rows:
        name = str(row.get("name") or "").lower()
        if name == want:
            return str(row.get("id") or "")
    for row in rows:
        name = str(row.get("name") or "").lower()
        if want and (want in name or name in want):
            return str(row.get("id") or "")
    return ""


def _country_for(subject_name: str, ctx) -> str:
    """Which country's figures to read.

    A country is itself; anything else is read through the country Dossier
    recorded for it, so "Angela Merkel" reads Germany's numbers. That is a
    deliberate choice: a politician has no GDP, but the economy they are
    answerable for is the context their signals should be read against.
    """
    stored = getattr(ctx, "stored", None) or {}
    identity = (stored.get("subject") or {}).get("identity") or {}
    kind = str((stored.get("subject") or {}).get("entity_type") or "")
    if kind == "country":
        return subject_name
    for key in ("country", "Country", "citizenship"):
        value = identity.get(key)
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str) and value.strip():
            return value.strip()
    if kind == "country" or not kind:
        return subject_name
    return ""


def fetch(subject_name: str, ctx) -> list[Reading]:
    country = _country_for(subject_name, ctx)
    if not country:
        return []
    code = _iso3(ctx, country)
    if not code:
        ctx.log(f"worldbank: no country code for {country}")
        return []

    codes = indicators()

    def _one(indicator: str):
        url = (
            f"{API}/country/{code}/indicator/{indicator}"
            f"?format=json&per_page=40&mrnev=20"
        )
        return indicator, ctx.fetcher.get_json(url, api=True)

    with ThreadPoolExecutor(max_workers=min(len(codes), 9)) as pool:
        fetched = dict(pool.map(_one, list(codes)))

    readings: list[Reading] = []
    for indicator, (label, unit) in codes.items():
        payload = fetched.get(indicator)
        rows = (payload or [None, []])[1] or []
        for row in rows:
            value, year = row.get("value"), row.get("date")
            if value is None or not year:
                continue
            readings.append(
                Reading(
                    # Dated to the last day of the year it describes, so it
                    # sorts and merges beside daily readings without pretending
                    # to have been measured on a particular day.
                    date=f"{year}-12-31",
                    value=float(value),
                    detail=f"{label}: {float(value):,.4g} {unit} ({country}, {year})",
                    url=f"https://data.worldbank.org/indicator/{indicator}?locations={code}",
                    # One series per indicator. Without this they share a file
                    # and, being keyed by date, silently overwrite each other.
                    series=label,
                )
            )
    readings.sort(key=lambda r: r.date)
    ctx.log(f"worldbank: {len(readings)} figures for {country} ({code})")
    return readings


SPEC = SignalSpec(
    name="worldbank",
    label="Economy (World Bank)",
    kind="economy",
    unit="mixed, per indicator",
    fetch=fetch,
    description=(
        "GDP, GDP per person, population, unemployment, inflation, inequality, "
        "life expectancy, military spending and government debt — published "
        "figures with a year attached."
    ),
    caveat=(
        "Annual and revised, not a daily signal: a value can change years after "
        "the fact because the publisher restated it, and the newest year is "
        "often missing for smaller economies. Read the level and the direction, "
        "never a day-to-day move. A subject that is not a country is read "
        "through the country Dossier recorded for it."
    ),
    # Annual figures publish months after the year ends: last year's is news.
    fresh_days=548,
)
