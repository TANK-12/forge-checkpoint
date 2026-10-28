"""Gathering signals, and turning what is stored into findings.

One sweep reads every enabled source for a set of subjects and merges the
readings into their series. Merging rather than appending is what makes a sweep
safe to re-run: a point is keyed by the date it describes, so running twice in
one day corrects today's reading instead of doubling it.

Subjects are worked **most consequential first**, using the prominence figure
Dossier already stores, because the user was explicit that a job stopped early
should still have covered the names that matter.

The fetcher is Dossier's. It already carries per-domain pacing, robots
handling, retry and extraction that took a session to get right, and a second
copy here would drift out of step with it. That is the same "one real copy"
rule the user applies to models and voices.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import dossier_link
import store
from analysis import registry as analysers
from signals import registry as sources

# Dossier ships the fetcher this app needs. `research` is a package name unique
# to Dossier, and it imports nothing from Dossier's top level, so adding that
# directory to the path cannot shadow anything of ours.
DOSSIER_DIR = Path(
    os.environ.get("DOSSIER_DIR", Path(__file__).resolve().parent.parent / "dossier")
)
if str(DOSSIER_DIR) not in sys.path:
    sys.path.append(str(DOSSIER_DIR))


# How far back the first sweep of a source reads.
HISTORY_DAYS = 5 * 365 + 1
# Measured, not guessed: the 2026-09-12 sweep of 400 subjects wrote one every
# 4.6 s (median gap between the newest file of each subject's folder). Used only
# to tell the user roughly how long "Sweep the watchlist now" will take.
SECONDS_PER_SUBJECT = 5
# What "Sweep the watchlist now" asks for: the Signals tab's own default.
SWEEP_NOW_SUBJECTS = 25


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_fetcher():
    """Dossier's fetcher, or a clear failure if Dossier is not beside us."""
    try:
        from research.fetcher import Fetcher  # type: ignore
    except Exception as e:  # pragma: no cover - only when the install is broken
        raise RuntimeError(
            f"Foresight needs Dossier's fetcher at {DOSSIER_DIR} ({type(e).__name__}: {e})"
        )
    return Fetcher()


@dataclass
class Context:
    """What a source adapter is allowed to use while reading."""

    fetcher: object
    days: int = 60
    stored: dict = field(default_factory=dict)
    log: Callable[[str], None] = lambda message: None


def sweep_subject(
    slug: str,
    name: str,
    ctx: Context,
    only: tuple[str, ...] = (),
    root: Path | None = None,
    history: bool = False,
) -> dict:
    """Read every enabled source for one subject and merge what comes back.

    `history` reads the full five years from every source, including ones
    already stored. Readings merge by date, so every reading already held is
    kept - this only adds what a shorter first sweep never reached.
    """
    result = {"slug": slug, "name": name, "sources": {}, "errors": {}}
    held = store.sources_for(slug, root)
    for spec in sources.enabled_sources():
        if only and spec.name not in only:
            continue
        # The first reading of a source reaches back five years; after that a
        # sweep only needs the recent window. Without the history, a breakout
        # has a two-month baseline and a backtest has nothing to stand on.
        first_time = history or not any(
            key == spec.name or key.startswith(spec.name + ".") for key in held
        )
        source_ctx = (
            replace(ctx, days=max(ctx.days, HISTORY_DAYS)) if first_time else ctx
        )
        try:
            readings = spec.fetch(name, source_ctx)
        except Exception as e:
            # One flaky source must never cost the others. The failure is
            # recorded rather than swallowed, so a source that is quietly
            # broken shows up in the interface instead of just going silent.
            result["errors"][spec.name] = f"{type(e).__name__}: {e}"
            continue
        if not readings:
            result["sources"][spec.name] = {"added": 0, "updated": 0, "total": 0}
            continue
        # A source may publish several series - the World Bank returns nine
        # indicators for a country. They are stored apart because a series is
        # keyed by date, so together they would overwrite each other.
        grouped: dict[str, list[dict]] = {}
        for reading in readings:
            key = store.series_key(spec.name, getattr(reading, "series", ""))
            grouped.setdefault(key, []).append(reading.as_point())
        for key, points in grouped.items():
            result["sources"][key] = store.merge_series(slug, key, points, root)
    return result


def annotate_age(findings: list[dict], today: date | None = None) -> list[dict]:
    """Give each finding its age in days and whether it is still news.

    A spike from four weeks ago is not "what is moving". Each source says in
    its registry entry how long a reading stays fresh (a week for a daily
    count, a year and a half for an annual figure); past that it is `stale`
    and the page greys it out. A finding with no readable date has no age and
    is never called stale on a guess.
    """
    today = today or date.today()
    for finding in findings:
        age = None
        try:
            age = (today - date.fromisoformat(str(finding.get("at") or "")[:10])).days
        except ValueError:
            pass
        spec = sources.get(str(finding.get("source") or "").split(".", 1)[0])
        fresh = spec.fresh_days if spec else 7
        finding["age_days"] = age
        finding["stale"] = age is not None and age > fresh
    return findings


def findings_for(slug: str, name: str, root: Path | None = None) -> list[dict]:
    """Run every analyser over what is stored for one subject, each finding
    carrying its age (see `annotate_age`)."""
    series = {
        source: store.read_series(slug, source, root)
        for source in store.sources_for(slug, root)
    }
    if not series:
        return []
    out = []
    for spec in analysers.all_analysers():
        try:
            out.extend(f.as_dict() for f in spec.run(slug, name, series))
        except Exception:
            continue
    return annotate_age(out)


def interleave(findings: list[dict]) -> list[dict]:
    """Order findings so the top of the list is a MIX, not one kind of thing.

    Strict weight order is the obvious ranking and it makes the page useless.
    A breakout's weight saturates at eight sigma, so on any ordinary day two
    dozen pageview spikes all tie at 1.0 and every economic finding is pushed
    below the fold — which is exactly the complaint that "findings is usless",
    made when every reading in the app was a search count.

    So each kind is ranked within itself and the kinds are then taken in turn,
    strongest kind first. Nothing is hidden and nothing is reweighted; the same
    findings come back in an order that shows what is actually held.
    """
    by_kind: dict[str, list[dict]] = {}
    for finding in findings:
        by_kind.setdefault(finding.get("kind", ""), []).append(finding)
    for group in by_kind.values():
        group.sort(key=lambda f: (f.get("weight", 0), f.get("at", "")), reverse=True)
    # Strongest kind first, so a genuinely extraordinary day still leads.
    order = sorted(by_kind.values(), key=lambda g: g[0].get("weight", 0), reverse=True)
    out: list[dict] = []
    for row in range(max((len(g) for g in order), default=0)):
        for group in order:
            if row < len(group):
                out.append(group[row])
    return out


def all_findings(root: Path | None = None, limit: int = 200) -> list[dict]:
    """Everything worth reading right now, mixed so no one kind swamps it."""
    rows = {r["slug"]: r for r in dossier_link.library()}
    out: list[dict] = []
    for slug in store.subjects_with_signals(root):
        name = (rows.get(slug) or {}).get("name") or slug
        out.extend(findings_for(slug, name, root))
    return interleave(out)[:limit]


def held_subjects(root: Path | None = None) -> list[dict]:
    """Every subject that already has signals stored - what a history refresh
    brings up to date."""
    rows = {r["slug"]: r for r in dossier_link.library()}
    return [
        {
            "slug": slug,
            "name": (rows.get(slug) or {}).get("name") or slug,
            "entity_type": (rows.get(slug) or {}).get("entity_type", ""),
        }
        for slug in store.subjects_with_signals(root)
    ]


def watchlist(limit: int = 40) -> list[dict]:
    """Which subjects a sweep should cover, most consequential first."""
    return [
        {
            "slug": row["slug"],
            "name": row["name"],
            "entity_type": row.get("entity_type", ""),
        }
        for row in dossier_link.ranked(limit=limit)
    ]
