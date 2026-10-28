"""Country name to ISO3 code, resolved once per process.

Two indicator sources now need the same thing: turn "Germany" - or whatever
Wikidata happened to call it - into `DEU`. Keeping one copy of the name fixes
here means a country that resolves for one source resolves for the other, and
adding a troublesome name is a single line rather than two.

This module has no `SPEC`, so the source registry walks past it exactly as it
walks past `properties.py`. It is shared code that happens to live next to the
adapters that use it.

The World Bank's country list is the lookup table because it is already fetched
for free, carries the ISO3 code as its `id`, and marks aggregates like "World"
and "Euro area" with no region so they can be dropped.
"""

from __future__ import annotations

import threading

API = "https://api.worldbank.org/v2"

# Wikidata labels that differ from the World Bank's country names. Only the
# ones that actually collide are listed; everything else matches on name.
NAME_FIXES = {
    "United States of America": "United States",
    "Russian Federation": "Russia",
    "Republic of Korea": "Korea, Rep.",
    "South Korea": "Korea, Rep.",
    "North Korea": "Korea, Dem. People's Rep.",
    "Iran": "Iran, Islamic Rep.",
    "Egypt": "Egypt, Arab Rep.",
    "Turkey": "Turkiye",
    "Türkiye": "Turkiye",
    "Venezuela": "Venezuela, RB",
    "Syria": "Syrian Arab Republic",
    "Slovakia": "Slovak Republic",
    "Czech Republic": "Czechia",
    "Democratic Republic of the Congo": "Congo, Dem. Rep.",
    "Republic of the Congo": "Congo, Rep.",
    "Laos": "Lao PDR",
    "Kyrgyzstan": "Kyrgyz Republic",
    "Yemen": "Yemen, Rep.",
    "Gambia": "Gambia, The",
    "Bahamas": "Bahamas, The",
    "Saint Lucia": "St. Lucia",
    "Hong Kong": "Hong Kong SAR, China",
    "Macau": "Macao SAR, China",
    "Federal Republic of Germany": "Germany",
    "United Kingdom of Great Britain and Northern Ireland": "United Kingdom",
    "Republic of India": "India",
}

_codes: dict[str, str] = {}
_lock = threading.Lock()


def _load(fetcher) -> dict[str, str]:
    """Fetch the country list once. Cheap afterwards, and thread-safe.

    The queue runs several subjects at a time, so two workers can arrive here
    together on a cold cache; without the lock they would both fetch.
    """
    global _codes
    with _lock:
        if _codes:
            return _codes
        data = fetcher.get_json(
            f"{API}/country", api=True, params={"format": "json", "per_page": "400"}
        )
        rows = data[1] if isinstance(data, list) and len(data) > 1 else []
        found: dict[str, str] = {}
        for row in rows or []:
            if (row.get("region") or {}).get("id") in ("NA", None, ""):
                continue  # aggregates like "World" and "Euro area"
            found[(row.get("name") or "").lower()] = row.get("id") or ""
        if found:
            _codes = found
        return _codes


def iso3(fetcher, name: str) -> str:
    """The ISO3 code for a country name, or "" when nothing matches."""
    if not name:
        return ""
    table = _load(fetcher)
    wanted = NAME_FIXES.get(name, name).lower()
    if wanted in table:
        return table[wanted]
    for label, code in table.items():
        if label.startswith(wanted) or wanted.startswith(label):
            return code
    return ""


def country_for(subject, ctx) -> str:
    """Which country an indicator source should look up for this subject.

    A country dossier is its own answer; for a person or a party it is the
    country they belong to, because the figures that matter politically are
    the ones for the place they operate in.
    """
    identity = ctx.identity or {}
    if ctx.entity_type == "country":
        return identity.get("label") or subject.name
    for key in ("country", "citizenship"):
        values = identity.get(key) or []
        if values:
            return values[0]
    return ""
