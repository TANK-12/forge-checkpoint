"""World Bank indicators: the economic and social numbers behind the politics.

A political dossier that says nothing about unemployment, inequality or
military spending is missing half the story, and these are the rare facts that
need no interpretation at all - they are published figures with a year attached.
They are emitted as dated timeline entries of kind `indicator`, so they need no
new storage shape and the `economy` page simply filters for them.

Free, no API key. The World Bank is treated as a primary source: it is the
publisher of the statistic, not someone reporting on it.

Resolving a country name to its ISO3 code lives in `countrycodes.py`, shared
with the Our World in Data adapter: both ask the same question, and a name
that resolves for one should resolve for the other.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from research.fetcher import Document
from research.scoring import SubjectProfile

from . import countrycodes
from .registry import Context, Harvest, SourceSpec

API = "https://api.worldbank.org/v2"

# Economic, social and military, in the order they are worth reading.
INDICATORS = {
    "NY.GDP.MKTP.CD": ("GDP", "US$", 1e9, "bn"),
    "NY.GDP.PCAP.CD": ("GDP per person", "US$", 1, ""),
    "SP.POP.TOTL": ("Population", "people", 1e6, "m"),
    "SL.UEM.TOTL.ZS": ("Unemployment", "% of labour force", 1, "%"),
    "FP.CPI.TOTL.ZG": ("Inflation", "% a year", 1, "%"),
    "SI.POV.GINI": ("Inequality (Gini)", "index", 1, ""),
    "SP.DYN.LE00.IN": ("Life expectancy", "years", 1, " yrs"),
    "MS.MIL.XPND.GD.ZS": ("Military spending", "% of GDP", 1, "%"),
    "GC.DOD.TOTL.GD.ZS": ("Government debt", "% of GDP", 1, "%"),
}


def fetch(subject: SubjectProfile, ctx: Context) -> Harvest:
    harvest = Harvest()
    country = countrycodes.country_for(subject, ctx)
    if not country:
        harvest.notes.append("No country to look up World Bank figures for")
        return harvest
    code = countrycodes.iso3(ctx.fetcher, country)
    if not code:
        harvest.notes.append(f"The World Bank has no country matching '{country}'")
        ctx.log(f"World Bank: no match for {country}")
        return harvest

    years = 8 if ctx.phase == "deep" else 3
    lines: list[str] = []

    # Nine independent requests to one host. Run together they cost about as
    # much as the slowest one instead of the sum of all nine.
    def _series(indicator: str):
        return indicator, ctx.fetcher.get_json(
            f"{API}/country/{code}/indicator/{indicator}",
            api=True,
            params={"format": "json", "mrnev": str(years)},
        )

    with ThreadPoolExecutor(max_workers=len(INDICATORS)) as pool:
        fetched = dict(pool.map(_series, list(INDICATORS)))

    for indicator, (label, unit, divisor, suffix) in INDICATORS.items():
        data = fetched.get(indicator)
        rows = data[1] if isinstance(data, list) and len(data) > 1 else []
        for row in rows or []:
            value = row.get("value")
            year = row.get("date")
            if value is None or not year:
                continue
            shown = value / divisor
            text = f"{shown:,.1f}{suffix}" if divisor > 1 or suffix else f"{shown:,.0f}"
            harvest.timeline.append(
                {
                    "date": str(year),
                    "end": "",
                    "title": f"{label}: {text}",
                    "kind": "indicator",
                    "detail": f"{label} ({unit}) for {country}, World Bank",
                    "source_id": "worldbank",
                    "url": f"https://data.worldbank.org/indicator/{indicator}?locations={code}",
                    "confidence": "verified",
                    "indicator": indicator,
                    "value": value,
                }
            )
        if rows:
            newest = rows[0]
            if newest.get("value") is not None:
                lines.append(
                    f"{label} ({newest['date']}): "
                    f"{newest['value'] / divisor:,.1f}{suffix}"
                )

    if lines:
        harvest.documents.append(
            Document(
                url=f"https://data.worldbank.org/country/{code}",
                title=f"World Bank indicators - {country}",
                text=f"World Bank figures for {country}. " + ". ".join(lines) + ".",
                tier="primary",
                origin="worldbank",
                domain="worldbank.org",
            )
        )
    ctx.log(f"World Bank: {len(harvest.timeline)} dated figures for {country} ({code})")
    return harvest


SPEC = SourceSpec(
    name="worldbank",
    label="World Bank",
    tier="primary",
    phases=("quick", "deep"),
    entity_types=("country", "political_system", "person", "party"),
    fetch=fetch,
    description="Economic, social and military indicators, dated, from the publisher.",
)
