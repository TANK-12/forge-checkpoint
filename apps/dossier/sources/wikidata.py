"""Wikidata: who this is, and the dated skeleton of their career.

This runs first for a reason. Resolving a name to a Q-number settles the
identity question up front - occupation, country, party, birth year - and those
terms become the context the relevance scorer uses to throw out articles about
a different person with the same name.

It also hands over the timeline almost free. Offices held are stored with start
and end dates as structured data, so the spine of the dossier needs no model at
all and cannot be hallucinated.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from research.fetcher import Document
from research.scoring import SubjectProfile

from .properties import IMAGES, IMAGES_PER_KIND, PROPERTIES, edges_from, image_url
from .registry import Context, Harvest, SourceSpec

API = "https://www.wikidata.org/w/api.php"


def _clean_date(value: str) -> str:
    """Wikidata pads unknown months and days with zeros: 1993-00-00 means
    "some time in 1993". Keep the precision that actually exists."""
    if not value:
        return ""
    parts = value.split("-")
    if len(parts) == 3 and parts[1] == "00":
        return parts[0]
    if len(parts) == 3 and parts[2] == "00":
        return f"{parts[0]}-{parts[1]}"
    return value


# The properties worth reading, and what they mean in a dossier.
P = {
    "instance_of": "P31",
    "occupation": "P106",
    "citizenship": "P27",
    "party": "P102",
    "birth": "P569",
    "death": "P570",
    "position": "P39",
    "employer": "P108",
    "educated": "P69",
    "member_of": "P463",
    "chair": "P488",
    "founded_by": "P112",
    "inception": "P571",
    "ideology": "P1142",
    "country": "P17",
    "head_of_gov": "P6",
    "office_held_by": "P1308",
    "legislative_body": "P194",
    "ceo": "P169",
    "board": "P3320",
    "owner": "P127",
    "industry": "P452",
    "spouse": "P26",
    "seats": "P1410",
    "participant": "P710",
    "start_time": "P580",
    "end_time": "P582",
    "located": "P276",
    "casualties": "P1120",
}
# Chamber kinds. A party's standing is judged in the elected lower house, so
# that chamber is preferred over an upper house even when the upper one is
# larger - Britain's House of Lords has 808 seats against the Commons' 650.
# The specific chamber types ("house of commons", "house of lords") sit one
# subclass step below these, which is why P279 is followed one level.
LOWER_HOUSE = "Q375928"
UPPER_HOUSE = "Q637846"

# Which instance-of values fit which kind of dossier, so a search for a party
# does not come back with a person.
TYPE_HINTS = {
    "person": ("Q5",),
    "party": ("Q7278", "Q79913"),
    "country": ("Q6256", "Q3624078", "Q3024240"),
    "organisation": ("Q4830453", "Q783794", "Q6881511", "Q43229"),
    "political_system": ("Q1307214", "Q28108", "Q7278", "Q1307214"),
}


def _get(ctx: Context, params: dict):
    params = {"format": "json", "formatversion": "2", **params}
    return ctx.fetcher.get_json(API, params=params, api=True)


def _labels(ctx: Context, ids: list[str]) -> dict[str, str]:
    """Resolve Q-numbers to readable names, 50 per request, all at once.

    Reading the full fact table means a well-documented subject needs several
    hundred labels. Sequential batches turned identity resolution into the
    slowest step of a quick pass; the batches do not depend on each other.
    """
    out: dict[str, str] = {}
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return out
    chunks = [ids[i : i + 50] for i in range(0, len(ids), 50)]

    def _batch(chunk: list[str]):
        return _get(
            ctx,
            {
                "action": "wbgetentities",
                "ids": "|".join(chunk),
                "props": "labels",
                "languages": "en",
            },
        )

    if len(chunks) == 1:
        results = [_batch(chunks[0])]
    else:
        with ThreadPoolExecutor(max_workers=min(len(chunks), 6)) as pool:
            results = list(pool.map(_batch, chunks))
    for data in results:
        for qid, entity in ((data or {}).get("entities") or {}).items():
            label = (entity.get("labels") or {}).get("en", {}).get("value")
            if label:
                out[qid] = label
    return out


def _value(snak) -> tuple[str, str]:
    """(kind, value) for the bits of a claim we care about."""
    try:
        dv = snak["mainsnak"]["datavalue"]
    except Exception:
        return "", ""
    if dv["type"] == "wikibase-entityid":
        return "qid", dv["value"]["id"]
    if dv["type"] == "time":
        return "time", _clean_date(dv["value"]["time"].lstrip("+")[:10])
    if dv["type"] == "string":
        return "string", dv["value"]
    if dv["type"] == "monolingualtext":
        return "string", dv["value"]["text"]
    if dv["type"] == "quantity":
        # Net worth, revenue, population, casualties - all quantities, and all
        # silently discarded until now.
        amount = str(dv["value"].get("amount", "")).lstrip("+")
        unit = str(dv["value"].get("unit", "") or "")
        return "quantity", f"{amount}|{unit.rsplit('/', 1)[-1] if unit != '1' else ''}"
    return "", ""


def _readable_quantity(raw: str, units: dict[str, str]) -> str:
    """Format a quantity the way a person would write it."""
    amount, _, unit_qid = raw.partition("|")
    try:
        value = float(amount)
    except ValueError:
        return amount
    if value >= 1_000_000_000_000:
        shown = f"{value / 1_000_000_000_000:,.1f} trillion"
    elif value >= 1_000_000_000:
        shown = f"{value / 1_000_000_000:,.1f} billion"
    elif value >= 1_000_000:
        shown = f"{value / 1_000_000:,.1f} million"
    elif value == int(value):
        shown = f"{int(value):,}"
    else:
        shown = f"{value:,.2f}"
    unit = units.get(unit_qid, "")
    return f"{shown} {unit}".strip()


def _qualifier_time(claim, prop: str) -> str:
    try:
        dv = claim["qualifiers"][prop][0]["datavalue"]["value"]["time"]
        return _clean_date(dv.lstrip("+")[:10])
    except Exception:
        return ""


def _best_statement(statements: list) -> dict | None:
    """The statement Wikidata itself considers current.

    A party carries a seat count for every parliamentary term it has ever sat
    in, so picking the first one gives a figure that may be decades old.
    Wikidata marks the current value with preferred rank; failing that, the
    latest point-in-time qualifier wins.
    """
    if not statements:
        return None
    preferred = [st for st in statements if st.get("rank") == "preferred"]
    pool = preferred or [st for st in statements if st.get("rank") != "deprecated"]
    if not pool:
        return None

    def when(st) -> str:
        return _qualifier_time(st, "P585") or ""

    dated = [st for st in pool if when(st)]
    if dated:
        return max(dated, key=when)
    return pool[0]


def _quantity(statement: dict) -> float | None:
    try:
        return float(statement["mainsnak"]["datavalue"]["value"]["amount"])
    except Exception:
        return None


def _seat_share(ctx: Context, claims: dict) -> dict:
    """Seats held, the chamber they are held in, and the share that represents.

    A bare seat count says little - 200 seats is a landslide in one parliament
    and a rump in another - so the chamber total is fetched and the proportion
    computed, with every part kept so the figure can be checked.

    Parties sit in more than one chamber, and Wikidata's preferred statement is
    not always the one that matters: Germany's CDU came back as 17 of 69 in the
    Bundesrat rather than its Bundestag standing. The primary chamber is
    therefore taken to be the LARGEST one the party sits in, which picks the
    lower house essentially everywhere, and the others are kept alongside it.
    """
    statements = [
        st for st in claims.get(P["seats"], []) if st.get("rank") != "deprecated"
    ]
    if not statements:
        return {}

    # Group by chamber, keeping the most current statement for each.
    by_body: dict[str, list] = {}
    for st in statements:
        try:
            body = st["qualifiers"]["P194"][0]["datavalue"]["value"]["id"]
        except Exception:
            body = ""
        by_body.setdefault(body, []).append(st)
    current = {body: _best_statement(sts) for body, sts in by_body.items()}
    current = {b: st for b, st in current.items() if st is not None}
    if not current:
        return {}

    # Which countries is this party OF? Needed to tell its own parliament from
    # a supranational one it also sits in.
    home_countries = set()
    for st in claims.get(P["country"], []):
        kind, value = _value(st)
        if kind == "qid":
            home_countries.add(value)

    body_qids = [b for b in current if b]
    totals: dict[str, int] = {}
    labels: dict[str, str] = {}
    domestic: dict[str, bool] = {}
    body_kinds: dict[str, set] = {}
    if body_qids:
        # One request covers every chamber the party sits in.
        data = _get(
            ctx,
            {
                "action": "wbgetentities",
                "ids": "|".join(body_qids[:20]),
                "props": "claims|labels",
                "languages": "en",
            },
        )
        for qid, body in ((data or {}).get("entities") or {}).items():
            labels[qid] = (body.get("labels") or {}).get("en", {}).get("value", "")
            body_claims = body.get("claims") or {}
            total_statement = _best_statement(body_claims.get("P1342", []))
            total = _quantity(total_statement) if total_statement else None
            if total and total > 0:
                totals[qid] = int(total)
            body_countries = set()
            for st in body_claims.get("P17", []):
                kind, value = _value(st)
                if kind == "qid":
                    body_countries.add(value)
            domestic[qid] = bool(home_countries & body_countries)
            kinds = set()
            for st in body_claims.get("P31", []):
                kind, value = _value(st)
                if kind == "qid":
                    kinds.add(value)
            body_kinds[qid] = kinds

    # Resolve what kind of chamber each one is, following subclass one step so
    # that "house of commons" is recognised as a lower house.
    all_kinds = {k for kinds in body_kinds.values() for k in kinds}
    lower_kinds, upper_kinds = {LOWER_HOUSE}, {UPPER_HOUSE}
    if all_kinds:
        data = _get(
            ctx,
            {
                "action": "wbgetentities",
                "ids": "|".join(sorted(all_kinds)[:40]),
                "props": "claims",
            },
        )
        for qid, kind_entity in ((data or {}).get("entities") or {}).items():
            parents = set()
            for st in (kind_entity.get("claims") or {}).get("P279") or []:
                kind, value = _value(st)
                if kind == "qid":
                    parents.add(value)
            if LOWER_HOUSE in parents:
                lower_kinds.add(qid)
            if UPPER_HOUSE in parents:
                upper_kinds.add(qid)

    chambers = []
    for body_qid, statement in current.items():
        seats = _quantity(statement)
        if seats is None:
            continue
        entry = {
            "seats": int(seats),
            "body": labels.get(body_qid, ""),
            "total": totals.get(body_qid, 0),
            "domestic": domestic.get(body_qid, False),
            "lower_house": bool(body_kinds.get(body_qid, set()) & lower_kinds),
            "upper_house": bool(body_kinds.get(body_qid, set()) & upper_kinds),
            "url": f"https://www.wikidata.org/wiki/{body_qid}" if body_qid else "",
        }
        if entry["total"]:
            entry["share"] = round(seats / entry["total"], 4)
        chambers.append(entry)
    if not chambers:
        return {}

    # The party's own national parliament first, then by size. Germany's CDU
    # sits in the European Parliament (720 seats), the Bundestag (630) and the
    # Bundesrat (69); size alone picks the European Parliament, which is not
    # where a national party's standing is judged.
    chambers.sort(
        key=lambda c: (
            c["domestic"],
            c["lower_house"],
            not c["upper_house"],
            c["total"],
            c["seats"],
        ),
        reverse=True,
    )
    primary = chambers[0]
    out = {
        "seats": primary["seats"],
        "seats_body": primary["body"],
        "seats_body_url": primary["url"],
        "seats_chambers": chambers,
    }
    if primary.get("total"):
        out["seats_total"] = primary["total"]
        out["seats_share"] = primary["share"]
    return out


def _pick_candidate(
    ctx: Context, candidates: list[dict], entity_type: str
) -> tuple[str, bool]:
    """Choose between same-named Wikidata entries by what they actually ARE.

    Searching "Labour Party (UK)" returned the 1992 Labour Party leadership
    ELECTION as the top hit, and matching on description text does not save
    you - that election's description contains the word "party" too. So the
    candidates' `instance of` (P31) is read and compared against the Q-numbers
    the entity type already declares. One extra request settles it.
    """
    import entities.registry as entity_registry

    spec = entity_registry.get(entity_type)
    wanted = set(spec.type_hints) if spec else set()
    if not wanted or len(candidates) < 2:
        return candidates[0]["id"], not wanted

    ids = [c["id"] for c in candidates[:10]]
    data = _get(
        ctx,
        {
            "action": "wbgetentities",
            "ids": "|".join(ids),
            "props": "claims",
            "languages": "en",
        },
    )
    entities_found = (data or {}).get("entities") or {}
    for candidate in candidates[:10]:
        claims = (entities_found.get(candidate["id"]) or {}).get("claims") or {}
        kinds = set()
        for statement in claims.get("P31", []):
            kind, value = _value(statement)
            if kind == "qid":
                kinds.add(value)
        if kinds & wanted:
            return candidate["id"], True
    return candidates[0]["id"], False


def search_entity(ctx: Context, name: str, entity_type: str) -> list[dict]:
    data = _get(
        ctx,
        {
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "uselang": "en",
            "limit": 10,
            "type": "item",
        },
    )
    return (data or {}).get("search") or []


def fetch(subject: SubjectProfile, ctx: Context) -> Harvest:
    harvest = Harvest()
    qid = ctx.identity.get("qid")

    if not qid:
        candidates = search_entity(ctx, subject.name, ctx.entity_type)
        if not candidates:
            harvest.notes.append(f"Wikidata has no entry matching '{subject.name}'")
            return harvest
        qid, matched = _pick_candidate(ctx, candidates, ctx.entity_type)
        if not matched and "(" in subject.name:
            # Lists carry disambiguators - "Labour Party (UK)" - and Wikidata's
            # search does worse with them than without. Try the bare name
            # before settling for a candidate of the wrong kind.
            plain = re.sub(r"\s*\([^)]*\)", "", subject.name).strip()
            if plain and plain != subject.name:
                retry = search_entity(ctx, plain, ctx.entity_type)
                if retry:
                    better, matched_retry = _pick_candidate(ctx, retry, ctx.entity_type)
                    if matched_retry:
                        qid, candidates = better, retry
                        ctx.log(f"Wikidata: retried as '{plain}'")
        harvest.identity["candidates"] = [
            {
                "qid": c["id"],
                "label": c.get("label", ""),
                "description": c.get("description", ""),
            }
            for c in candidates[:8]
        ]
        ctx.log(
            f"Wikidata: {subject.name} -> {qid} ({candidates[0].get('description','')})"
        )

    data = _get(
        ctx,
        {
            "action": "wbgetentities",
            "ids": qid,
            "props": "claims|labels|descriptions|sitelinks|aliases",
            "languages": "en",
        },
    )
    entity = ((data or {}).get("entities") or {}).get(qid)
    if not entity:
        harvest.notes.append(f"Wikidata entity {qid} could not be read")
        return harvest

    claims = entity.get("claims") or {}
    label = (entity.get("labels") or {}).get("en", {}).get("value", subject.name)
    description = (entity.get("descriptions") or {}).get("en", {}).get("value", "")
    aliases = [a["value"] for a in (entity.get("aliases") or {}).get("en", [])]
    sitelinks = entity.get("sitelinks") or {}

    # Everything we will need a readable name for.
    wanted_qids: list[str] = []
    simple: dict[str, list[tuple[str, str]]] = {}
    for key, prop in P.items():
        for claim in claims.get(prop, []):
            kind, value = _value(claim)
            if not kind:
                continue
            simple.setdefault(key, []).append((kind, value))
            if kind == "qid":
                wanted_qids.append(value)

    # And every property the fact table asks for. These arrived in the same
    # response all along; reading only a handful of them was throwing away most
    # of what Wikidata knows about the subject.
    rich: dict[str, list[tuple[str, str]]] = {}
    for code, (fact_label, _group, kind_hint) in PROPERTIES.items():
        statements = [
            st for st in claims.get(code, []) if st.get("rank") != "deprecated"
        ]
        if not statements:
            continue
        if kind_hint == "one":
            best = _best_statement(statements)
            statements = [best] if best else []
        for claim in statements:
            kind, value = _value(claim)
            if not kind:
                continue
            rich.setdefault(fact_label, []).append((kind, value))
            if kind == "qid":
                wanted_qids.append(value)
            elif kind == "quantity":
                unit = value.partition("|")[2]
                if unit.startswith("Q"):
                    wanted_qids.append(unit)

    for claim in claims.get(P["position"], []):
        kind, value = _value(claim)
        if kind == "qid":
            wanted_qids.append(value)

    names = _labels(ctx, wanted_qids)

    def readable(key: str) -> list[str]:
        out = []
        for kind, value in simple.get(key, []):
            out.append(names.get(value, value) if kind == "qid" else value)
        return out

    facts: dict[str, list[str] | str] = {}
    for fact_label, values in rich.items():
        shown = []
        for kind, value in values:
            if kind == "qid":
                shown.append(names.get(value, value))
            elif kind == "quantity":
                shown.append(_readable_quantity(value, names))
            else:
                shown.append(value)
        shown = [v for v in dict.fromkeys(shown) if v]
        if not shown:
            continue
        kind_hint = next(
            (k for (lbl, _g, k) in PROPERTIES.values() if lbl == fact_label), "list"
        )
        facts[fact_label] = shown[0] if kind_hint in ("one", "time") else shown[:25]

    identity = {
        **facts,
        "qid": qid,
        "label": label,
        "description": description,
        "aliases": aliases,
        "occupation": readable("occupation"),
        "citizenship": readable("citizenship"),
        "party": readable("party"),
        "employer": readable("employer"),
        "educated_at": readable("educated"),
        "ideology": readable("ideology"),
        "industry": readable("industry"),
        "country": readable("country"),
        "instance_of": readable("instance_of"),
        "birth": (readable("birth") or [""])[0],
        "death": (readable("death") or [""])[0],
        "inception": (readable("inception") or [""])[0],
        "wikipedia_title": (sitelinks.get("enwiki") or {}).get("title", ""),
        "wikiquote_title": (sitelinks.get("enwikiquote") or {}).get("title", ""),
        "wikidata_url": f"https://www.wikidata.org/wiki/{qid}",
        # How many language Wikipedias carry an article on this subject. It is
        # the best free proxy for consequence there is: a sitting head of
        # government has dozens, a backbench councillor has one. Bulk jobs use
        # it to spend their hours on figures who actually matter.
        "prominence": len(sitelinks),
    }
    identity.update(_seat_share(ctx, claims))
    harvest.identity.update(identity)

    # The timeline spine: offices and roles, with their dates.
    for claim in claims.get(P["position"], []):
        kind, value = _value(claim)
        if kind != "qid":
            continue
        start = _qualifier_time(claim, "P580")
        end = _qualifier_time(claim, "P582")
        harvest.timeline.append(
            {
                "date": start or end,
                "end": end,
                "title": names.get(value, value),
                "kind": "office",
                "detail": f"Held office: {names.get(value, value)}",
                "source_id": f"wikidata:{qid}",
                "url": identity["wikidata_url"],
                "confidence": "verified",
            }
        )

    for key, kind, template in (
        ("birth", "life", "Born"),
        ("death", "life", "Died"),
        ("inception", "founding", "Founded"),
    ):
        when = identity.get(key)
        if when:
            harvest.timeline.append(
                {
                    "date": when,
                    "end": "",
                    "title": template,
                    "kind": kind,
                    "detail": f"{template}: {when}",
                    "source_id": f"wikidata:{qid}",
                    "url": identity["wikidata_url"],
                    "confidence": "verified",
                }
            )

    # The connection graph, driven entirely by `properties.RELATIONS`. This
    # used to be four relation kinds named here in the code, which is why the
    # graph was so thin: the data for the rest was already in `facts` and was
    # simply never turned into edges.
    # Pictures arrive in the same claims payload as everything else, so they
    # cost nothing extra to collect. Only the reference is stored here; the
    # file itself is pulled down by the images pass.
    for code, (kind, label) in IMAGES.items():
        kept = 0
        for claim in claims.get(code, []):
            value_kind, filename = _value(claim)
            if value_kind != "string" or not filename:
                continue
            # Wikidata often carries half a dozen portraits of the same person.
            # Measured on Angela Merkel: five portraits came to 900KB, and a
            # thousand subjects at that rate is most of a gigabyte for pictures
            # nobody looks past the first of.
            if kept >= IMAGES_PER_KIND:
                break
            kept += 1
            harvest.images.append(
                {
                    "kind": kind,
                    "label": label,
                    "commons_file": filename,
                    "url": image_url(filename),
                    "credit": "Wikimedia Commons",
                    "source_id": f"wikidata:{qid}",
                    "stored": "",
                }
            )

    for relation, target in edges_from(identity):
        harvest.relations.append(
            {
                "relation": relation,
                "target": target,
                "source_id": f"wikidata:{qid}",
                "url": identity["wikidata_url"],
            }
        )

    # Only the plain string lists describe the subject; structured ones (the
    # per-chamber seat breakdown) are data, not prose.
    summary_bits = [description] + [
        f"{k.replace('_', ' ')}: {', '.join(v)}"
        for k, v in identity.items()
        if isinstance(v, list) and v and all(isinstance(item, str) for item in v)
    ]
    harvest.documents.append(
        Document(
            url=identity["wikidata_url"],
            title=f"{label} - Wikidata",
            text=f"{label}. {'. '.join(b for b in summary_bits if b)}.",
            published=identity.get("birth", ""),
            tier="encyclopedic",
            origin="wikidata",
        )
    )
    return harvest


SPEC = SourceSpec(
    name="wikidata",
    label="Wikidata",
    tier="encyclopedic",
    phases=("identify", "quick", "deep"),
    entity_types=("*",),
    fetch=fetch,
    description="Structured identity and dated offices. Anchors who the subject is.",
)
