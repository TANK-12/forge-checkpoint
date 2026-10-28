"""IMF World Economic Outlook: the only source here that reports the future.

WHY IT EARNS A PLACE BESIDE THE WORLD BANK
    The World Bank publishes what an economy DID. The IMF's World Economic
    Outlook publishes what its staff expect it to do, several years out, and
    revises those projections twice a year. That is a different kind of fact
    and it is worth keeping separate: a projection is an institution's stated
    expectation, which is a real and checkable thing, and it is not a
    measurement.

    Every entry is therefore marked `projection` rather than `indicator` when
    its year is in the future, and its title says so. Storing a forecast
    alongside a measurement without labelling it is the one way this source
    could make the library less trustworthy instead of more.

    It also unblocks the thing the app above this one exists for: a scenario
    can be scored against what the IMF expected, and the IMF can be scored
    against what happened.

FREE, NO KEY
    The DataMapper API needs no registration. It answers with every country in
    one payload whatever country you ask for, so the filtering is done here.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date

from research.fetcher import Document
from research.scoring import SubjectProfile

from . import countrycodes
from .registry import Context, Harvest, SourceSpec

API = "https://www.imf.org/external/datamapper/api/v1"

# The WEO series worth carrying. Growth and the deficit are the two an ordinary
# reader actually wants; the rest place them.
INDICATORS = {
    "NGDP_RPCH": ("Real GDP growth", "% a year"),
    "PCPIPCH": ("Inflation, IMF", "% a year"),
    "LUR": ("Unemployment, IMF", "% of labour force"),
    "GGXCNL_NGDP": ("Government balance", "% of GDP"),
    "GGXWDG_NGDP": ("Government debt, IMF", "% of GDP"),
    "BCA_NGDPD": ("Current account", "% of GDP"),
}

# How far back to carry history, so a dossier is not swamped by 1980.
FIRST_YEAR = 2015


def fetch(subject: SubjectProfile, ctx: Context) -> Harvest:
    harvest = Harvest()
    country = countrycodes.country_for(subject, ctx)
    if not country:
        harvest.notes.append("No country to look up IMF figures for")
        return harvest
    code = countrycodes.iso3(ctx.fetcher, country)
    if not code:
        harvest.notes.append(f"No IMF country matching '{country}'")
        ctx.log(f"IMF: no match for {country}")
        return harvest

    def _one(indicator: str):
        return indicator, ctx.fetcher.get_json(f"{API}/{indicator}/{code}", api=True)

    with ThreadPoolExecutor(max_workers=len(INDICATORS)) as pool:
        fetched = dict(pool.map(_one, list(INDICATORS)))

    this_year = date.today().year
    lines: list[str] = []
    for indicator, (label, unit) in INDICATORS.items():
        payload = fetched.get(indicator) or {}
        # The API answers with every country whatever one you asked for.
        series = ((payload.get("values") or {}).get(indicator) or {}).get(code) or {}
        newest_actual = None
        for year, value in sorted(series.items()):
            if not year.isdigit() or int(year) < FIRST_YEAR or value is None:
                continue
            # >= , not > : the WEO publishes the CURRENT year as a staff
            # estimate too. The year is not over, so the figure has not been
            # observed, and calling it a measurement would be wrong by exactly
            # the margin this source exists to keep visible.
            ahead = int(year) >= this_year
            harvest.timeline.append(
                {
                    "date": str(year),
                    "end": "",
                    "title": (
                        f"{label}: {float(value):,.4g} {unit}"
                        + (" (IMF projection)" if ahead else "")
                    ),
                    # A projection is not a measurement and must never be
                    # stored as one. The economy page filters on this.
                    "kind": "projection" if ahead else "indicator",
                    "detail": (
                        f"{label} ({unit}) for {country}, IMF World Economic Outlook"
                        + (
                            " - a projection by IMF staff, not an observed figure."
                            if ahead
                            else "."
                        )
                    ),
                    "source_id": "imf",
                    "url": f"https://www.imf.org/external/datamapper/{indicator}@WEO/{code}",
                    "confidence": "reported" if ahead else "verified",
                    "indicator": indicator,
                    "value": float(value),
                }
            )
            if not ahead:
                newest_actual = (year, float(value))
        if newest_actual:
            lines.append(
                f"{label} ({newest_actual[0]}): {newest_actual[1]:,.4g} {unit}"
            )

    if lines:
        harvest.documents.append(
            Document(
                url=f"https://www.imf.org/external/datamapper/profile/{code}",
                title=f"IMF World Economic Outlook - {country}",
                text=(
                    f"IMF World Economic Outlook figures for {country}. "
                    + ". ".join(lines)
                    + ". Projections for later years are IMF staff estimates."
                ),
                tier="primary",
                origin="imf",
                domain="imf.org",
            )
        )
    projected = sum(1 for t in harvest.timeline if t["kind"] == "projection")
    ctx.log(
        f"IMF: {len(harvest.timeline)} figures for {country} ({code}), "
        f"{projected} of them projections"
    )
    return harvest


SPEC = SourceSpec(
    name="imf",
    label="IMF World Economic Outlook",
    tier="primary",
    phases=("quick", "deep"),
    entity_types=("country", "political_system"),
    fetch=fetch,
    description=(
        "Growth, inflation, unemployment, deficit, debt and the current account "
        "- including the IMF's own projections, stored as projections."
    ),
)
