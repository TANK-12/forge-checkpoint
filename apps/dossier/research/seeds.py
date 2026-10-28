"""Where a bulk job gets its list of subjects from.

A set-and-forget run needs hundreds of names, and typing them is not the point.
These recipes ask Wikidata for a real list - every current head of government,
every party holding seats, the conflicts that are actually running - and each
one comes back with the Q-number already attached, so the pipeline never has to
guess which person a name refers to.

Adding a recipe is one entry in RECIPES. Each is plain SPARQL against the
public query service, which needs no key.
"""

from __future__ import annotations

import time

import httpx

ENDPOINT = "https://query.wikidata.org/sparql"
from research.fetcher import USER_AGENT as UA

RECIPES: dict[str, dict] = {
    "heads_of_government": {
        "label": "Every current head of government",
        "entity_type": "person",
        "description": "Sitting prime ministers, chancellors and equivalents worldwide.",
        "sparql": """
            SELECT ?item ?itemLabel ?countryLabel ?links WHERE {
              ?country wdt:P31 wd:Q6256 ; wdt:P6 ?item .
              ?item wikibase:sitelinks ?links .
              SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
            }
            ORDER BY DESC(?links)
        """,
    },
    "heads_of_state": {
        "label": "Every current head of state",
        "entity_type": "person",
        "description": "Sitting presidents and monarchs worldwide.",
        "sparql": """
            SELECT ?item ?itemLabel ?countryLabel ?links WHERE {
              ?country wdt:P31 wd:Q6256 ; wdt:P35 ?item .
              ?item wikibase:sitelinks ?links .
              SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
            }
            ORDER BY DESC(?links)
        """,
    },
    "countries": {
        "label": "Every sovereign country",
        "entity_type": "country",
        "description": "The map layer: one dossier per sovereign state.",
        "sparql": """
            SELECT ?item ?itemLabel ?links WHERE {
              ?item wdt:P31 wd:Q3624078 .
              ?item wikibase:sitelinks ?links .
              FILTER NOT EXISTS { ?item wdt:P576 ?dissolved }
              SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
            }
            ORDER BY DESC(?links)
        """,
    },
    "ruling_parties": {
        "label": "Parties holding seats in national legislatures",
        "entity_type": "party",
        "description": "Parties with a recorded seat count - the ones that govern or oppose.",
        "sparql": """
            SELECT DISTINCT ?item ?itemLabel ?countryLabel ?links ?seats WHERE {
              ?item wdt:P31 wd:Q7278 ; wdt:P1410 ?seats ; wdt:P17 ?country .
              ?item wikibase:sitelinks ?links .
              FILTER(?seats > 0)
              SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
            }
            ORDER BY DESC(?links)
        """,
    },
    "ongoing_conflicts": {
        "label": "Armed conflicts with no recorded end",
        "entity_type": "conflict",
        "description": "Wars and armed conflicts that are still running.",
        "sparql": """
            SELECT DISTINCT ?item ?itemLabel ?links WHERE {
              ?item wdt:P31/wdt:P279* wd:Q350604 ; wdt:P580 ?start .
              ?item wikibase:sitelinks ?links .
              FILTER NOT EXISTS { ?item wdt:P582 ?end }
              FILTER(YEAR(?start) > 2000)
              SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
            }
            ORDER BY DESC(?links)
        """,
    },
    "alliances": {
        "label": "International alliances and blocs",
        "entity_type": "alliance",
        "description": "NATO, the EU, BRICS and other intergovernmental blocs.",
        "sparql": """
            SELECT DISTINCT ?item ?itemLabel ?links WHERE {
              ?item wdt:P31/wdt:P279* wd:Q245065 .
              ?item wikibase:sitelinks ?links .
              FILTER NOT EXISTS { ?item wdt:P576 ?dissolved }
              SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
            }
            ORDER BY DESC(?links)
        """,
    },
    "historic_wars": {
        "label": "The wars that shaped the world",
        "entity_type": "conflict",
        "description": "Major armed conflicts through history, most written-about first.",
        "sparql": """
            SELECT DISTINCT ?item ?itemLabel ?links WHERE {
              ?item wdt:P31/wdt:P279* wd:Q198 ; wdt:P580 ?start .
              ?item wikibase:sitelinks ?links .
              FILTER(?links > 25)
              SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
            }
        """,
    },
    "historic_leaders": {
        "label": "Historic heads of state and government",
        "entity_type": "person",
        "description": "Leaders who have left office or died - the people the present grew out of.",
        "sparql": """
            SELECT DISTINCT ?item ?itemLabel ?links WHERE {
              ?item wdt:P31 wd:Q5 ; wdt:P39 ?position ; wdt:P570 ?died .
              ?position wdt:P279* wd:Q2285706 .
              ?item wikibase:sitelinks ?links .
              FILTER(?links > 60)
              SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
            }
        """,
    },
    "treaties": {
        "label": "Treaties and agreements",
        "entity_type": "alliance",
        "description": "The written settlements that ended wars and built the current order.",
        "sparql": """
            SELECT DISTINCT ?item ?itemLabel ?links WHERE {
              ?item wdt:P31/wdt:P279* wd:Q131569 .
              ?item wikibase:sitelinks ?links .
              FILTER(?links > 20)
              SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
            }
        """,
    },
    "empires_and_states": {
        "label": "Empires and former states",
        "entity_type": "country",
        "description": "States that no longer exist but still explain current borders and grievances.",
        "sparql": """
            SELECT DISTINCT ?item ?itemLabel ?links WHERE {
              ?item wdt:P31/wdt:P279* wd:Q3024240 .
              ?item wikibase:sitelinks ?links .
              FILTER(?links > 40)
              SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
            }
        """,
    },
    "revolutions": {
        "label": "Revolutions and uprisings",
        "entity_type": "conflict",
        "description": "Moments when a political order was overturned from inside.",
        "sparql": """
            SELECT DISTINCT ?item ?itemLabel ?links WHERE {
              ?item wdt:P31/wdt:P279* wd:Q10931 .
              ?item wikibase:sitelinks ?links .
              FILTER(?links > 20)
              SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
            }
        """,
    },
    "ancient_civilisations": {
        "label": "Ancient civilisations and early states",
        "entity_type": "country",
        "description": "States founded before 500 AD - where the written record starts.",
        "sparql": """
            SELECT ?item ?itemLabel ?links WHERE {
              ?item wdt:P31/wdt:P279* wd:Q3024240 ;
                    wdt:P571 ?inception ;
                    wikibase:sitelinks ?links .
              FILTER(YEAR(?inception) < 500)
              SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
            }
            ORDER BY DESC(?links)
        """,
    },
    "ancient_rulers": {
        "label": "Rulers of the ancient world",
        "entity_type": "person",
        "description": "Pharaohs and Roman emperors, most written-about first.",
        "sparql": """
            SELECT ?item ?itemLabel ?links WHERE {
              VALUES ?position { wd:Q37110 wd:Q842606 }
              ?item wdt:P39 ?position ; wdt:P570 ?died ; wikibase:sitelinks ?links .
              SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
            }
            ORDER BY DESC(?links)
        """,
    },
    "party_politicians": {
        "label": "Politicians, by party",
        "entity_type": "person",
        "description": "People who belong to a political party, most written-about first - the benches behind the leaders.",
        "sparql": """
            SELECT ?item ?itemLabel ?links WHERE {
              ?item wdt:P106 wd:Q82955 ; wdt:P102 ?party ; wikibase:sitelinks ?links .
              FILTER(?links > 60)
              SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
            }
            ORDER BY DESC(?links)
        """,
    },
    "largest_companies": {
        "label": "Companies by revenue",
        "entity_type": "organisation",
        "description": "The businesses big enough to have political weight.",
        "sparql": """
            SELECT ?item ?itemLabel ?revenue WHERE {
              ?item wdt:P31/wdt:P279* wd:Q4830453 ; wdt:P2139 ?revenue .
              FILTER(?revenue > 20000000000)
              SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
            }
            ORDER BY DESC(?revenue)
        """,
    },
}


def run_recipe(name: str, limit: int = 400, timeout: float = 120.0) -> list[dict]:
    """Returns [{name, qid, entity_type, country}] for one recipe."""
    recipe = RECIPES.get(name)
    if not recipe:
        raise KeyError(f"No seed recipe called '{name}'")
    query = recipe["sparql"].strip() + f"\nLIMIT {int(limit)}"
    last_error = ""
    for pause in (0.0, 3.0, 9.0):
        if pause:
            time.sleep(pause)
        try:
            r = httpx.get(
                ENDPOINT,
                params={"query": query, "format": "json"},
                headers={"User-Agent": UA, "Accept": "application/sparql-results+json"},
                timeout=timeout,
            )
            if r.status_code == 429:
                last_error = "rate limited"
                continue
            r.raise_for_status()
            rows = r.json()["results"]["bindings"]
            break
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            rows = None
    if rows is None:
        raise RuntimeError(f"Wikidata query service failed ({last_error})")

    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        qid = row.get("item", {}).get("value", "").rsplit("/", 1)[-1]
        label = row.get("itemLabel", {}).get("value", "")
        if not qid or not label or qid in seen or label.startswith("Q"):
            continue
        seen.add(qid)
        try:
            prominence = int(row.get("links", {}).get("value", 0))
        except Exception:
            prominence = 0
        out.append(
            {
                "name": label,
                "qid": qid,
                "entity_type": recipe["entity_type"],
                "country": row.get("countryLabel", {}).get("value", ""),
                "prominence": prominence,
                "seats": row.get("seats", {}).get("value", ""),
            }
        )
    # Most-covered first, so a job that is stopped early has still done the
    # subjects that matter most.
    out.sort(key=lambda r: r["prominence"], reverse=True)
    return out


def catalogue() -> list[dict]:
    return [
        {
            "name": key,
            "label": r["label"],
            "entity_type": r["entity_type"],
            "description": r["description"],
        }
        for key, r in RECIPES.items()
    ]
