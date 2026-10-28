"""One research run, start to finish.

The order matters and is the whole speed argument. Identity is settled first,
because everything downstream depends on knowing which Angela Merkel this is.
Then sources are gathered, and the cheap deterministic work - canonical URLs,
story clustering, relevance arithmetic - runs on everything. Only what survives
that reaches a model, and only the top of what survives reaches the larger one.

A quick pass therefore costs roughly one model call per ambiguous document and
none at all for the rest; a deep dive spends its budget where the evidence is
already known to be relevant.
"""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

import entities.registry as entity_registry
import llm
import store
from research import claims as claims_mod
from research.canonical import canonical_url, registrable_domain
from research.corroborate import merge_claims
from research.dedupe import StoryClusterer
from research.fetcher import now_iso, shared as shared_fetcher
from research.scoring import SubjectProfile, score_document
from sources.registry import Context, Harvest, for_phase

QUICK_BUDGET = 15
DEEP_BUDGET = 80
DEEP_CLAIM_DOCS = 25
MIN_KEEP = 0.15


@dataclass
class RunReport:
    subject: str = ""
    entity_type: str = "person"
    phase: str = "quick"
    started: str = ""
    seconds: float = 0.0
    documents: int = 0
    skipped_known: int = 0
    duplicates_collapsed: int = 0
    clusters: int = 0
    triaged: int = 0
    rejected_by_triage: int = 0
    claims: int = 0
    verified: int = 0
    reported: int = 0
    disputed: int = 0
    dropped_unquoted: int = 0
    quotes: int = 0
    timeline: int = 0
    llm_used: bool = False
    claims_complete: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def source_id(url: str) -> str:
    return "s" + hashlib.blake2b(canonical_url(url).encode(), digest_size=5).hexdigest()


def read_articles(
    rows: list[dict],
    subject: SubjectProfile,
    report: RunReport,
    extract: Callable | None = None,
) -> list:
    """Read shortlisted articles into claims, one article at a time.

    A request that fails is noted and the next article is read; only Jan going
    away stops the reading. Any failure leaves the extraction marked incomplete,
    so the subject is not recorded as deep and a later pass tries again.
    """
    extract = extract or claims_mod.extract_claims
    found: list = []
    complete = True
    for row in rows:
        try:
            found.extend(
                extract(
                    row, subject, row["source_id"], row["cluster_id"], row["relevance"]
                )
            )
        except llm.JanRequestFailed as e:
            complete = False
            report.notes.append(
                f"Claim extraction skipped one article ({row['source_id']}): {e}"
            )
        except llm.JanUnavailable as e:
            complete = False
            report.notes.append(f"Claim extraction stopped: {e}")
            break
    report.claims_complete = complete
    return found


def _profile(name: str, identity: dict, spec) -> SubjectProfile:
    birth = identity.get("birth") or ""
    year = None
    if birth[:4].isdigit():
        year = int(birth[:4])
    aliases = [a for a in (identity.get("aliases") or []) if a][:6]
    if identity.get("label") and identity["label"] != name:
        aliases.append(identity["label"])
    return SubjectProfile(
        name=identity.get("label") or name,
        aliases=aliases,
        context_terms=spec.context_terms(identity),
        birth_year=year,
    )


def research(
    name: str,
    entity_type: str = "person",
    phase: str = "quick",
    qid: str = "",
    use_llm: bool = True,
    reuse_known: bool = True,
    log: Callable[[str], None] = print,
) -> dict:
    """Gather, score, dedupe, corroborate and return a whole dossier."""
    started = time.time()
    # Fixed here, once, before anything else runs. A loop further down once
    # rebound `name` to a source adapter's name, and every subject researched
    # after that point was stored under the wrong slug.
    slug = store.slugify(name)
    spec = entity_registry.get(entity_type) or entity_registry.default()
    report = RunReport(
        subject=name, entity_type=spec.name, phase=phase, started=now_iso()
    )

    budget = QUICK_BUDGET if phase == "quick" else DEEP_BUDGET
    harvest = Harvest()
    identity: dict = {"qid": qid} if qid else {}

    # What this subject already holds. Passed to the adapters so a refresh
    # fetches only what is genuinely new: a published article does not change,
    # and re-downloading a month of them to rediscover what is already stored
    # was most of the cost of keeping a library up to date. Read straight from
    # the stored file rather than importing the store layer, to keep this
    # module free of that dependency.
    known_urls: set[str] = set()
    if reuse_known:
        stored_sources = store.read_json(store.subject_dir(slug) / "sources.json", [])
        known_urls = {
            canonical_url(row.get("url", ""))
            for row in (stored_sources or [])
            if row.get("url")
        }

    # One Fetcher for the whole process, so per-domain pacing holds across
    # concurrently researched subjects rather than only within one.
    fetcher = shared_fetcher()
    ctx = Context(
        fetcher=fetcher,
        phase="identify",
        entity_type=spec.name,
        identity=identity,
        budget=budget,
        log=log,
        known_urls=known_urls,
    )

    # 1. Who is this? Everything downstream leans on the answer.
    for source in for_phase("identify", spec.name):
        try:
            harvest.extend(source.fetch(SubjectProfile(name=name), ctx))
        except Exception as e:
            report.notes.append(f"{source.name} failed during identify: {e}")
    identity.update(harvest.identity)
    subject = _profile(name, identity, spec)
    identity["context_hint"] = spec.search_hint(identity)
    ctx.identity = identity
    ctx.phase = phase
    log(f"Subject: {subject.name} - {identity.get('description','(no description)')}")
    log(f"Telling them apart by: {', '.join(subject.context_terms[:6]) or '(nothing)'}")

    # 2. Gather. Sources that already ran in identify are not re-run.
    #
    # Every remaining source is independent once identity is settled, and
    # each is almost entirely waiting on the network, so they run together.
    # Each gets its own Context: they share the fetcher (which is
    # thread-safe and keeps its own per-domain pacing) but not the budget,
    # which the loop used to mutate underneath them.
    done = {s.name for s in for_phase("identify", spec.name)}
    pending = [s for s in for_phase(phase, spec.name) if s.name not in done]

    def _gather(source):
        source_ctx = Context(
            fetcher=fetcher,
            phase=phase,
            entity_type=spec.name,
            identity=identity,
            budget=budget if source.name == "ddg_lite" else max(budget // 2, 8),
            log=log,
            known_urls=known_urls,
        )
        try:
            return source.name, source.fetch(subject, source_ctx), None
        except Exception as e:
            return source.name, None, e

    if pending:
        with ThreadPoolExecutor(max_workers=min(len(pending), 6)) as pool:
            for source_name, gathered, error in pool.map(_gather, pending):
                if error is not None:
                    report.notes.append(f"{source_name} failed: {error}")
                    log(f"{source_name}: failed ({error})")
                elif gathered is not None:
                    harvest.extend(gathered)
    report.notes.extend(harvest.notes)
    report.skipped_known = harvest.skipped_known
    if known_urls:
        log(
            f"Already held {len(known_urls)} sources; "
            f"{harvest.skipped_known} were skipped rather than refetched"
        )

    # 3. One row per document, deduped by canonical URL.
    by_url: dict[str, dict] = {}
    for doc in harvest.documents:
        row = doc.to_dict()
        row["source_id"] = source_id(row["url"])
        if row["url"] in by_url:
            continue
        by_url[row["url"]] = row
    docs = list(by_url.values())
    report.documents = len(docs)

    # 4. Relevance, then story clustering.
    for row in docs:
        rel = score_document(row, subject, tier=row.get("tier", "unknown"))
        row["relevance"] = rel.score
        row["relevance_breakdown"] = rel.breakdown
    docs.sort(key=lambda r: r["relevance"], reverse=True)

    clusterer = StoryClusterer()
    for row in docs:
        row["cluster_id"] = clusterer.add(row).cluster_id
    summary = clusterer.summary()
    report.clusters = summary["clusters"]
    report.duplicates_collapsed = summary["duplicates_collapsed"]
    log(
        f"{report.documents} documents -> {report.clusters} distinct stories "
        f"({report.duplicates_collapsed} duplicates collapsed)"
    )

    # 5. Ask the small model only about the genuinely ambiguous ones.
    jan_up = False
    if use_llm:
        try:
            jan_up = llm.status()["jan"]
        except Exception:
            jan_up = False
    if jan_up:
        report.llm_used = True
        for row in docs:
            if not claims_mod.needs_triage(row["relevance"]):
                continue
            try:
                keep, why = claims_mod.triage(row, subject, identity)
            except llm.JanUnavailable:
                break
            report.triaged += 1
            row["triage"] = {"kept": keep, "why": why}
            if not keep:
                row["relevance"] = round(row["relevance"] * 0.25, 3)
                report.rejected_by_triage += 1
        if report.triaged:
            log(
                f"Model triage: {report.triaged} borderline documents checked, "
                f"{report.rejected_by_triage} judged to be a different subject"
            )
    else:
        report.notes.append(
            "Jan was not reachable - sources gathered and scored, but no claims "
            "were extracted and no pages were written."
        )

    docs = [r for r in docs if r["relevance"] >= MIN_KEEP]
    docs.sort(key=lambda r: r["relevance"], reverse=True)

    # 6. Claims, from the most relevant full-text documents only.
    raw_claims = []
    if jan_up:
        # One document per story cluster. Reading a second copy of the same
        # report costs a minute of model time and adds nothing, because
        # corroboration already counts that cluster as a single voice.
        best_per_cluster: dict[str, dict] = {}
        for r in docs:
            if r.get("origin") in ("news_rss", "gdelt"):
                continue
            if len((r.get("text") or "").split()) < 60:
                continue
            current = best_per_cluster.get(r["cluster_id"])
            if current is None or r["relevance"] > current["relevance"]:
                best_per_cluster[r["cluster_id"]] = r
        readable = sorted(
            best_per_cluster.values(), key=lambda r: r["relevance"], reverse=True
        )
        # The quick pass deliberately reads no articles. It exists to fill a
        # library of hundreds fast, and Wikidata's dated offices and
        # Wikiquote's sourced quotes are already facts without a model.
        limit = DEEP_CLAIM_DOCS if phase == "deep" else 0
        if limit:
            raw_claims = read_articles(readable[:limit], subject, report)
            log(
                f"Read {min(len(readable), limit)} articles into {len(raw_claims)} claims"
            )
        else:
            log("Quick pass: no article reading (deep dive extracts claims)")

    graded = merge_claims(raw_claims)
    if jan_up and graded:
        try:
            extra = claims_mod.find_contradictions(graded, subject)
            for claim in graded:
                if claim.text in extra:
                    claim.conflicts.extend(extra[claim.text])
            graded = merge_claims(graded)
        except llm.JanUnavailable:
            pass

    report.claims = len(graded)
    for claim in graded:
        if claim.confidence == "verified":
            report.verified += 1
        elif claim.confidence == "reported":
            report.reported += 1
        elif claim.confidence == "disputed":
            report.disputed += 1

    # 7. Timeline: structured facts first, coverage after, deduped by day+title.
    timeline: list[dict] = []
    seen_events: set[tuple] = set()
    for event in harvest.timeline:
        key = (event.get("date", ""), (event.get("title") or "").lower()[:60])
        if not event.get("date") or key in seen_events:
            continue
        seen_events.add(key)
        timeline.append(event)
    timeline.sort(key=lambda e: (e.get("date") or "", e.get("title") or ""))
    report.timeline = len(timeline)

    quotes = []
    seen_quotes: set[str] = set()
    for q in harvest.quotes:
        key = (q.get("text") or "")[:80].lower()
        if not key or key in seen_quotes:
            continue
        seen_quotes.add(key)
        quotes.append(q)
    report.quotes = len(quotes)

    report.seconds = round(time.time() - started, 1)
    log(
        f"Done in {report.seconds}s: {report.claims} claims "
        f"({report.verified} verified, {report.reported} reported, "
        f"{report.disputed} disputed), {report.quotes} quotes, "
        f"{report.timeline} timeline entries"
    )

    return {
        "name": subject.name,
        "slug": slug,
        "entity_type": spec.name,
        "identity": identity,
        "context_terms": subject.context_terms,
        "timeline": timeline,
        "quotes": quotes,
        "relations": harvest.relations,
        "images": harvest.images,
        "article": harvest.article,
        "claims": [c.to_dict() for c in graded],
        "sources": [
            {
                "source_id": r["source_id"],
                "url": r["url"],
                "title": r["title"],
                "domain": r["domain"],
                "tier": r["tier"],
                "origin": r["origin"],
                "published": r["published"],
                "relevance": r["relevance"],
                "cluster_id": r["cluster_id"],
                "words": len((r.get("text") or "").split()),
                "triage": r.get("triage"),
                "relevance_breakdown": r.get("relevance_breakdown"),
            }
            for r in docs
        ],
        "texts": {r["source_id"]: r.get("text", "") for r in docs},
        "report": report.to_dict(),
        "updated": now_iso(),
    }
