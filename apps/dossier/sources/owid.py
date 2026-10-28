"""Our World in Data: the social and development figures behind the politics.

The World Bank source already covers the economic numbers. This adds the ones
that describe how a country's people actually live and how it is governed -
life expectancy, child mortality, poverty, urbanisation, emissions, the median
age, how happy people say they are, and whether the place is classed as a
democracy at all. Like the World Bank these are published figures with a year
attached, which makes them the rare facts that need no interpretation, so OWID
is treated as a primary source: it is the publisher of the series, not someone
reporting on it.

Free, no API key.

They are emitted as dated timeline entries of kind `indicator` with
`source_id: "owid"`, so they need no new storage shape: the existing Economy
page picks them up alongside the World Bank's, and the Society page filters on
the source to show these on their own.

**Two shapes of chart, declared per indicator.** OWID serves a chart's data as
CSV, and how it answers depends on the chart:

  "series"    a line chart. `country=~DEU` filters it and the whole history for
              that one country comes back. Fetched per subject.
  "snapshot"  a world map. The country filter is *ignored* and every country
              comes back for the latest year - about 5 KB, which is smaller
              than a filtered request would have been. Fetched once per process
              and read out of the cache for every subject afterwards.

Getting that wrong is what makes an adapter slow: asking for a snapshot chart
per subject would download the whole world a thousand times over.
"""

from __future__ import annotations

import csv
import io
import threading
from concurrent.futures import ThreadPoolExecutor

from research.fetcher import Document
from research.scoring import SubjectProfile

from . import countrycodes
from .registry import Context, Harvest, SourceSpec

GRAPHER = "https://ourworldindata.org/grapher"

# code: (slug, column, label, unit, suffix, shape)
#
# One line per indicator. Every slug and column here was checked against the
# live endpoint; a chart that had been renamed or withdrawn was dropped rather
# than left in to fail quietly.
INDICATORS: dict[str, tuple[str, str, str, str, str, str]] = {
    "life_expectancy": (
        "life-expectancy",
        "life_expectancy_0",
        "Life expectancy",
        "years at birth",
        " yrs",
        "series",
    ),
    "child_mortality": (
        "child-mortality",
        "child_mortality_rate",
        "Child mortality",
        "% of children dying before five",
        "%",
        "series",
    ),
    "co2_per_capita": (
        "co-emissions-per-capita",
        "emissions_total_per_capita",
        "CO₂ per person",
        "tonnes a year",
        " t",
        "series",
    ),
    "median_age": (
        "median-age",
        "median_age__sex_all__age_all__variant_estimates",
        "Median age",
        "years",
        " yrs",
        "series",
    ),
    "hdi": (
        "human-development-index",
        "hdi__sex_total",
        "Human development index",
        "0-1",
        "",
        "snapshot",
    ),
    "democracy": (
        "political-regime",
        "regime_row_owid",
        "Political regime",
        "Regimes of the World classification",
        "",
        "snapshot",
    ),
    "life_satisfaction": (
        "happiness-cantril-ladder",
        "cantril_ladder_score",
        "Life satisfaction",
        "0-10, self-reported",
        "",
        "snapshot",
    ),
    "urban_share": (
        "share-of-population-urban",
        "share__area_type_urban__data_type_estimates",
        "Urban population",
        "% of people",
        "%",
        "snapshot",
    ),
    "extreme_poverty": (
        "share-of-population-in-extreme-poverty",
        "headcount_ratio__ppp_version_2021__poverty_line_300__welfare_type_income_or"
        "_consumption__table_income_or_consumption_consolidated__survey_comparability"
        "_no_spells",
        "Extreme poverty",
        "% below $3 a day",
        "%",
        "snapshot",
    ),
}

# The regime classification is a number in the data and a word in the world.
# Reading "3" aloud would be meaningless, so it is translated here rather than
# left for a reader to look up.
REGIMES = {
    "0": "closed autocracy",
    "1": "electoral autocracy",
    "2": "electoral democracy",
    "3": "liberal democracy",
}

_snapshots: dict[str, dict[str, tuple[str, str]]] = {}
_snapshot_lock = threading.Lock()


def _rows(fetcher, slug: str, code: str = "") -> list[dict]:
    """One chart's CSV, parsed. Returns [] rather than raising on any failure."""
    params = {"csvType": "filtered", "useColumnShortNames": "true"}
    if code:
        params["country"] = f"~{code}"
    response = fetcher.get(f"{GRAPHER}/{slug}.csv", api=True, params=params)
    if response is None:
        return []
    text = getattr(response, "text", "") or ""
    if not text.startswith("entity,"):
        return []  # an error page, not a table
    try:
        return list(csv.DictReader(io.StringIO(text)))
    except Exception:
        return []


def _snapshot(fetcher, key: str) -> dict[str, tuple[str, str]]:
    """A map chart's latest value for every country, fetched once per process."""
    global _snapshots
    with _snapshot_lock:
        if key in _snapshots:
            return _snapshots[key]
    slug, column, _label, _unit, _suffix, _shape = INDICATORS[key]
    table: dict[str, tuple[str, str]] = {}
    for row in _rows(fetcher, slug):
        code = (row.get("code") or "").strip()
        value = (row.get(column) or "").strip()
        year = (row.get("year") or "").strip()
        if code and value and year:
            table[code] = (year, value)
    with _snapshot_lock:
        # Only cache a table that actually arrived, so a transient failure is
        # retried by the next subject instead of being remembered as empty.
        if table:
            _snapshots[key] = table
        return table


def _format(key: str, value: str) -> str:
    """The figure as it should read on the page."""
    _slug, _column, _label, _unit, suffix, _shape = INDICATORS[key]
    if key == "democracy":
        return REGIMES.get(value.split(".")[0], value)
    try:
        number = float(value)
    except ValueError:
        return value
    if abs(number) >= 100:
        return f"{number:,.0f}{suffix}"
    return f"{number:,.2f}{suffix}".replace(".00", "")


def _entries(key: str, country: str, code: str, pairs: list[tuple[str, str]]) -> list:
    slug, _column, label, unit, _suffix, _shape = INDICATORS[key]
    out = []
    for year, value in pairs:
        shown = _format(key, value)
        out.append(
            {
                "date": str(year),
                "end": "",
                "title": f"{label}: {shown}",
                "kind": "indicator",
                "detail": f"{label} ({unit}) for {country}, Our World in Data",
                "source_id": "owid",
                "url": f"{GRAPHER}/{slug}?country=~{code}",
                "confidence": "verified",
                "indicator": key,
                "value": value,
            }
        )
    return out


def fetch(subject: SubjectProfile, ctx: Context) -> Harvest:
    harvest = Harvest()
    country = countrycodes.country_for(subject, ctx)
    if not country:
        harvest.notes.append("No country to look up Our World in Data figures for")
        return harvest
    code = countrycodes.iso3(ctx.fetcher, country)
    if not code:
        harvest.notes.append(f"No ISO country code matches '{country}'")
        ctx.log(f"OWID: no code for {country}")
        return harvest

    # A quick pass wants the current picture; a deep dive wants the trend.
    years = 12 if ctx.phase == "deep" else 4
    series = [k for k, v in INDICATORS.items() if v[5] == "series"]
    snapshots = [k for k, v in INDICATORS.items() if v[5] == "snapshot"]
    lines: list[str] = []

    # Independent requests to one host, so they cost about as much together as
    # the slowest one rather than the sum of them.
    def _one(key: str):
        slug, column, _label, _unit, _suffix, _shape = INDICATORS[key]
        pairs = []
        for row in _rows(ctx.fetcher, slug, code):
            value = (row.get(column) or "").strip()
            year = (row.get("year") or "").strip()
            if value and year:
                pairs.append((year, value))
        return key, pairs[-years:]

    with ThreadPoolExecutor(max_workers=max(1, len(series))) as pool:
        fetched = dict(pool.map(_one, series))

    for key in snapshots:
        found = _snapshot(ctx.fetcher, key).get(code)
        fetched[key] = [found] if found else []

    for key in INDICATORS:
        pairs = fetched.get(key) or []
        if not pairs:
            continue
        harvest.timeline.extend(_entries(key, country, code, pairs))
        year, value = pairs[-1]
        lines.append(f"{INDICATORS[key][2]} ({year}): {_format(key, value)}")

    if lines:
        harvest.documents.append(
            Document(
                url=f"{GRAPHER}/life-expectancy?country=~{code}",
                title=f"Our World in Data - {country}",
                text=f"Our World in Data figures for {country}. "
                + ". ".join(lines)
                + ".",
                tier="primary",
                origin="owid",
                domain="ourworldindata.org",
            )
        )
    ctx.log(f"OWID: {len(harvest.timeline)} dated figures for {country} ({code})")
    return harvest


SPEC = SourceSpec(
    name="owid",
    label="Our World in Data",
    tier="primary",
    phases=("quick", "deep"),
    entity_types=("country", "political_system", "person", "party"),
    fetch=fetch,
    description="Health, development, democracy and environment figures, dated, from the publisher.",
)
