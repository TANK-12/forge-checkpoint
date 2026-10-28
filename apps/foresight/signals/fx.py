"""Exchange rates: the fastest-moving number a country has.

WHY IT IS HERE
    An economy's published figures arrive once a year. Its currency reprices
    every day the market is open, and it reprices on exactly the events this
    app is watching for — a government falling, a central bank surprising
    everyone, a war starting. It is the one genuinely financial series that is
    free, daily, and needs no key.

    Rates come from the European Central Bank's daily reference rates, through
    frankfurter.app. The ECB is the publisher; this is a primary source.

WHAT IT MEANS, AND WHAT IT DOES NOT
    The series is **units of this currency per US dollar**, so it RISES when
    the currency weakens. That direction is stated on the reading itself,
    because a chart that silently means the opposite of what you assume is
    worse than no chart.

    The ECB publishes about thirty currencies. A country whose currency is not
    among them reads nothing at all, which is correct behaviour: a missing
    series is honest, an invented one is not. The dollar itself is skipped for
    the obvious reason.
"""

from __future__ import annotations

from datetime import date, timedelta

from .registry import Reading, SignalSpec

# frankfurter.app moved here; the old host now answers every request with a
# 301, which the fetcher follows but which cost a round trip per subject.
API = "https://api.frankfurter.dev/v1"

# The currencies the ECB publishes, by the names Wikidata uses for them. A
# bounded table for a bounded list - there is no lookup service for this, and
# guessing a currency code from a label would invent data.
CURRENCIES = {
    "australian dollar": "AUD",
    "bulgarian lev": "BGN",
    "brazilian real": "BRL",
    "canadian dollar": "CAD",
    "swiss franc": "CHF",
    "renminbi": "CNY",
    "chinese yuan": "CNY",
    "yuan": "CNY",
    "czech koruna": "CZK",
    "danish krone": "DKK",
    "euro": "EUR",
    "pound sterling": "GBP",
    "british pound": "GBP",
    "hong kong dollar": "HKD",
    "hungarian forint": "HUF",
    "indonesian rupiah": "IDR",
    "israeli new shekel": "ILS",
    "indian rupee": "INR",
    "icelandic krona": "ISK",
    "japanese yen": "JPY",
    "yen": "JPY",
    "south korean won": "KRW",
    "mexican peso": "MXN",
    "malaysian ringgit": "MYR",
    "norwegian krone": "NOK",
    "new zealand dollar": "NZD",
    "philippine peso": "PHP",
    "polish zloty": "PLN",
    "romanian leu": "RON",
    "swedish krona": "SEK",
    "singapore dollar": "SGD",
    "thai baht": "THB",
    "turkish lira": "TRY",
    "south african rand": "ZAR",
}


def currency_for(ctx) -> tuple[str, str]:
    """(ISO code, the label it came from), or ("", "") if there is no rate."""
    stored = getattr(ctx, "stored", None) or {}
    identity = (stored.get("subject") or {}).get("identity") or {}
    values = identity.get("Currency") or identity.get("currency") or []
    if isinstance(values, str):
        values = [values]
    for label in values:
        code = CURRENCIES.get(str(label).strip().lower())
        if code and code != "USD":
            return code, str(label)
    return "", ""


def fetch(subject_name: str, ctx) -> list[Reading]:
    code, label = currency_for(ctx)
    if not code:
        return []
    end = date.today()
    start = end - timedelta(days=max(30, int(getattr(ctx, "days", 60))))
    url = f"{API}/{start.isoformat()}..{end.isoformat()}?from=USD&to={code}"
    payload = ctx.fetcher.get_json(url, api=True)
    rates = (payload or {}).get("rates") or {}
    readings = []
    for day, row in sorted(rates.items()):
        value = row.get(code)
        if value is None:
            continue
        readings.append(
            Reading(
                date=day,
                value=float(value),
                # Spelled out on every reading: this number going UP means the
                # currency is getting WEAKER, which is the opposite of what a
                # rising line usually suggests.
                detail=f"{float(value):,.4g} {code} per US$ — higher means a weaker {label}",
                url=f"{API}/{day}?from=USD&to={code}",
                series="per-usd",
            )
        )
    ctx.log(f"fx: {len(readings)} days of {code}")
    return readings


SPEC = SignalSpec(
    name="fx",
    label="Currency (ECB)",
    kind="markets",
    unit="units per US dollar",
    fetch=fetch,
    description=(
        "The subject's currency against the US dollar, daily, from the European "
        "Central Bank's reference rates — the fastest-moving number a country has."
    ),
    caveat=(
        "Quoted per US dollar, so the line RISES when the currency WEAKENS. "
        "The ECB publishes about thirty currencies; a country outside that list "
        "reads nothing rather than an approximation. Reference rates are fixed "
        "once each working day and are not a traded price."
    ),
    non_negative=True,
)
