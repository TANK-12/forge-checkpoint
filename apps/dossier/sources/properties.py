"""Which Wikidata properties become facts in a dossier.

One line per property. Adding a fact to every dossier in the library is a
single entry here and nothing else - no change to the adapter, the pages or the
frontend.

The point of this table is that the data was always there and was being thrown
away: a subject like Angela Merkel carries 271 distinct properties and 471
statements, and the first version of this adapter read about twenty of them.
The rest cost nothing extra, because they arrive in the same request.

Each entry is `code: (label, group, kind)`.
  group  decides which panel it appears under
  kind   "list" keeps every value, "one" keeps the current/best single value,
         "time" is a date
"""

from __future__ import annotations

import re

GROUPS = [
    ("identity", "Who they are"),
    ("life", "Life"),
    ("career", "Career"),
    ("education", "Education"),
    ("affiliation", "Affiliations"),
    ("record", "Record"),
    ("wealth", "Money"),
    ("organisation", "Organisation"),
    ("conflict", "Conflict"),
    ("state", "State"),
]

PROPERTIES: dict[str, tuple[str, str, str]] = {
    # --- who they are
    "P31": ("Type", "identity", "list"),
    "P106": ("Occupation", "identity", "list"),
    "P27": ("Citizenship", "identity", "list"),
    "P1477": ("Birth name", "identity", "one"),
    "P1449": ("Nickname", "identity", "list"),
    "P103": ("Native language", "identity", "list"),
    "P1412": ("Languages spoken", "identity", "list"),
    "P140": ("Religion", "identity", "list"),
    # --- life
    "P569": ("Born", "life", "time"),
    "P19": ("Place of birth", "life", "one"),
    "P570": ("Died", "life", "time"),
    "P20": ("Place of death", "life", "one"),
    "P509": ("Cause of death", "life", "one"),
    "P551": ("Residence", "life", "list"),
    "P26": ("Spouse", "life", "list"),
    "P40": ("Children", "life", "list"),
    "P22": ("Father", "life", "one"),
    "P25": ("Mother", "life", "one"),
    "P3373": ("Siblings", "life", "list"),
    # --- career
    "P39": ("Positions held", "career", "list"),
    "P108": ("Employer", "career", "list"),
    "P937": ("Works in", "career", "list"),
    "P3602": ("Stood in election", "career", "list"),
    "P241": ("Military branch", "career", "list"),
    "P410": ("Military rank", "career", "one"),
    "P607": ("Conflicts involved in", "career", "list"),
    "P800": ("Notable work", "career", "list"),
    # --- education
    "P69": ("Educated at", "education", "list"),
    "P512": ("Academic degree", "education", "list"),
    "P812": ("Field of study", "education", "list"),
    "P184": ("Doctoral advisor", "education", "one"),
    # --- affiliation
    "P102": ("Party", "affiliation", "list"),
    "P463": ("Member of", "affiliation", "list"),
    "P1416": ("Affiliation", "affiliation", "list"),
    "P737": ("Influenced by", "affiliation", "list"),
    "P1142": ("Ideology", "affiliation", "list"),
    "P1387": ("Political alignment", "affiliation", "one"),
    # --- record: the parts a political dossier exists for
    "P166": ("Awards", "record", "list"),
    "P1411": ("Nominated for", "record", "list"),
    "P1399": ("Convicted of", "record", "list"),
    "P1596": ("Penalty", "record", "list"),
    "P793": ("Significant events", "record", "list"),
    "P1344": ("Took part in", "record", "list"),
    # --- money
    "P2218": ("Net worth", "wealth", "one"),
    "P2139": ("Revenue", "wealth", "one"),
    "P2295": ("Net profit", "wealth", "one"),
    "P2403": ("Total assets", "wealth", "one"),
    # --- organisation
    "P571": ("Founded", "organisation", "time"),
    "P576": ("Dissolved", "organisation", "time"),
    "P112": ("Founded by", "organisation", "list"),
    "P169": ("Chief executive", "organisation", "one"),
    "P488": ("Chairperson", "organisation", "one"),
    "P159": ("Headquarters", "organisation", "list"),
    "P1128": ("Employees", "organisation", "one"),
    "P452": ("Industry", "organisation", "list"),
    "P127": ("Owned by", "organisation", "list"),
    "P355": ("Subsidiaries", "organisation", "list"),
    "P414": ("Listed on", "organisation", "list"),
    "P1454": ("Legal form", "organisation", "one"),
    "P1410": ("Seats", "organisation", "one"),
    # --- conflict
    "P710": ("Participants", "conflict", "list"),
    "P276": ("Location", "conflict", "list"),
    "P828": ("Cause", "conflict", "list"),
    "P1120": ("Deaths", "conflict", "one"),
    "P1339": ("Injured", "conflict", "one"),
    "P1590": ("Civilian casualties", "conflict", "one"),
    # --- state
    "P35": ("Head of state", "state", "list"),
    "P6": ("Head of government", "state", "list"),
    "P1082": ("Population", "state", "one"),
    "P30": ("Continent", "state", "list"),
    "P37": ("Official language", "state", "list"),
    "P38": ("Currency", "state", "list"),
    "P122": ("Form of government", "state", "list"),
    "P194": ("Legislature", "state", "list"),
    "P17": ("Country", "state", "list"),
    "P150": ("Subdivisions", "state", "list"),
    "P36": ("Capital", "state", "one"),
    "P2131": ("GDP (nominal)", "state", "one"),
    "P2132": ("GDP per person", "state", "one"),
    "P1081": ("Human development index", "state", "one"),
    "P421": ("Time zone", "state", "list"),
    "P2250": ("Life expectancy", "state", "one"),
    "P1622": ("Drives on", "state", "one"),
    # --- more of who they are
    "P734": ("Family name", "identity", "one"),
    "P735": ("Given name", "identity", "list"),
    "P21": ("Gender", "identity", "one"),
    "P172": ("Ethnic group", "identity", "list"),
    "P1303": ("Instrument", "identity", "list"),
    "P101": ("Field of work", "identity", "list"),
    # --- more career
    "P2868": ("Role", "career", "list"),
    "P1308": ("Officeholder", "career", "list"),
    "P1830": ("Owner of", "career", "list"),
    # --- more record
    "P1533": ("Family", "record", "list"),
    "P2632": ("Detained at", "record", "list"),
    "P1343": ("Described by", "record", "list"),
    "P3342": ("Significant person", "record", "list"),
    # --- more organisation
    "P749": ("Parent organisation", "organisation", "list"),
    "P361": ("Part of", "organisation", "list"),
    "P527": ("Has part", "organisation", "list"),
    "P1056": ("Product", "organisation", "list"),
    "P2226": ("Market capitalisation", "organisation", "one"),
    "P3320": ("Board member", "organisation", "list"),
    "P1037": ("Director", "organisation", "list"),
    # --- more conflict
    "P582": ("Ended", "conflict", "time"),
    "P156": ("Followed by", "conflict", "list"),
    "P155": ("Preceded by", "conflict", "list"),
    "P1027": ("Conferred by", "conflict", "list"),
}

# Which of those facts are also *connections* - an edge from this subject to
# another entity, rather than a plain attribute about it. Keyed by the label
# above, so adding an edge kind to the whole library is one line here and
# nothing else: the harvest reads this table rather than naming relations
# itself, which is how it used to work and why the graph only ever had four
# kinds in it.
#
# The value is how the edge reads in a sentence, subject first:
# "Angela Merkel -> educated at -> University of Leipzig".
RELATIONS: dict[str, str] = {
    # affiliation
    "Party": "member of",
    "Member of": "member of",
    "Affiliation": "affiliated with",
    "Influenced by": "influenced by",
    "Ideology": "ideology",
    "Political alignment": "aligned with",
    # career
    "Employer": "employed by",
    "Positions held": "held office",
    "Conflicts involved in": "involved in",
    "Took part in": "took part in",
    "Significant events": "involved in",
    "Military branch": "served in",
    # education
    "Educated at": "educated at",
    "Doctoral advisor": "doctoral advisor",
    "Field of study": "studied",
    # life
    "Spouse": "spouse",
    "Children": "parent of",
    "Father": "child of",
    "Mother": "child of",
    "Siblings": "sibling of",
    "Place of birth": "born in",
    "Citizenship": "citizen of",
    "Religion": "religion",
    # record
    "Awards": "awarded",
    "Convicted of": "convicted of",
    # organisation
    "Has part": "has member",
    "Part of": "part of",
    "Parent organisation": "part of",
    "Founded by": "founded by",
    "Chief executive": "chief executive",
    "Chairperson": "chairperson",
    "Owned by": "owned by",
    "Subsidiaries": "parent of",
    "Headquarters": "based in",
    "Industry": "industry",
    # conflict and state
    "Participants": "participant",
    "Head of state": "head of state",
    "Head of government": "head of government",
    "Legislature": "legislature",
    "Country": "country",
    "Location": "located in",
}


# Pictures. Kept apart from PROPERTIES because a picture is not a fact you read
# in a sentence - it is a file, with its own licence and its own storage cost.
# Each value is a Commons filename, not a URL, so it is turned into one below.
IMAGES: dict[str, tuple[str, str]] = {
    "P18": ("portrait", "The main picture of the subject"),
    "P41": ("flag", "Flag"),
    "P94": ("arms", "Coat of arms"),
    "P154": ("logo", "Logo"),
    "P109": ("signature", "Signature"),
    "P1442": ("grave", "Grave"),
    "P2716": ("collage", "Collage"),
}

# Commons serves any file by name through Special:FilePath, which redirects to
# the real thumbnail. No API key and no separate lookup request.
COMMONS_FILEPATH = "https://commons.wikimedia.org/wiki/Special:FilePath/"

# How many pictures of one kind are worth keeping per subject.
IMAGES_PER_KIND = 2


def image_url(filename: str, width: int = 640) -> str:
    """A fetchable URL for a Commons filename, at a sane size.

    Full-resolution Commons originals run to tens of megabytes for a single
    portrait, which is not what a dossier needs and not what should be pulled
    onto a USB drive a thousand times over.
    """
    from urllib.parse import quote

    name = quote(filename.strip().replace(" ", "_"))
    return f"{COMMONS_FILEPATH}{name}?width={int(width)}"


def edges_from(identity: dict) -> list[tuple[str, str]]:
    """Every connection this subject's facts imply, as (relation, target).

    Deduplicated case-insensitively, because the same organisation can arrive
    under two labels ("Party" and "Member of") and one edge is enough.
    """
    edges: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for fact_label, relation in RELATIONS.items():
        value = identity.get(fact_label)
        if not value:
            continue
        targets = value if isinstance(value, list) else [value]
        for target in targets:
            if not isinstance(target, str) or not target.strip():
                continue
            target = target.strip()
            key = (relation, target.lower())
            if key in seen:
                continue
            seen.add(key)
            edges.append((relation, target))
    return edges


# Kept out on purpose: identifiers and cross-references (P214 VIAF, P213 ISNI,
# and the hundreds of other database ids), images and media, and coordinates.
# They are the bulk of those 271 properties and none of them is a fact anyone
# reads a dossier for.

# Which subjects each panel belongs on. A country has no seat count and a war
# has no doctoral advisor; showing them anyway made a dossier look careless and
# put a meaningless "Deaths: 593,865" on France.
GROUP_SCOPE: dict[str, tuple[str, ...]] = {
    "identity": (),  # empty means every subject type
    "life": ("person",),
    "career": ("person",),
    "education": ("person",),
    "affiliation": ("person", "party", "organisation", "alliance", "country"),
    "record": ("person", "party", "organisation", "alliance"),
    "wealth": ("person", "organisation"),
    "organisation": ("organisation", "party", "alliance"),
    "conflict": ("conflict",),
    "state": ("country", "political_system"),
}

GROUP_LABELS = dict(GROUPS)
GROUP_ORDER = [g for g, _ in GROUPS]


UNRESOLVED = re.compile(r"^Q\d+$")


def applies_to(group: str, entity_type: str) -> bool:
    scope = GROUP_SCOPE.get(group, ())
    return not scope or entity_type in scope


def grouped(identity: dict, entity_type: str = "") -> list[dict]:
    """Turn a stored identity into ordered panels for display.

    Panels that do not describe this kind of subject are left out, and raw
    Q-numbers are dropped: an entity with no English label is not a fact a
    reader can use, and printing "Q3052772" as a head of state is worse than
    saying nothing.
    """
    buckets: dict[str, list[dict]] = {}
    for code, (label, group, _kind) in PROPERTIES.items():
        if entity_type and not applies_to(group, entity_type):
            continue
        value = identity.get(label)
        if not value:
            continue
        if isinstance(value, list):
            value = ", ".join(
                dict.fromkeys(
                    str(v) for v in value if v and not UNRESOLVED.match(str(v))
                )
            )
        elif UNRESOLVED.match(str(value)):
            continue
        if not str(value).strip():
            continue
        buckets.setdefault(group, []).append({"label": label, "value": str(value)})
    return [
        {"group": g, "label": GROUP_LABELS[g], "rows": buckets[g]}
        for g in GROUP_ORDER
        if buckets.get(g)
    ]
