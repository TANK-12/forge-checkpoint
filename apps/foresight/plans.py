"""Scenarios and plans — the half that makes this a foresight app.

WHAT A SCENARIO IS HERE
    Not a paragraph of atmosphere. A scenario is a set of branches, and **every
    branch carries dated, falsifiable indicators**: not "tensions may rise" but
    "Australia's unemployment is above 4.6% in the 2027 reading". An indicator
    names a stored series, a direction, a threshold and a date, which means it
    can be scored later by arithmetic with nobody's judgement involved.

    That is the whole design. A forecast you cannot mark is an opinion, and the
    ledger is what turns opinions into a track record.

THE LEDGER
    `score()` walks every indicator whose date has passed and reads the stored
    series to decide met / missed. No model is consulted, ever — the same
    separation Dossier keeps between its factual record and anything generated.
    A scenario written by the think tier is marked by the same arithmetic that
    marks one written by the rules tier, so the two can be compared honestly.

TWO WAYS TO WRITE ONE, AND THE RULES WAY IS NOT A FALLBACK
    `rules` extrapolates the stored series: it takes the recent rate of change,
    carries it forward, and states the result as a falsifiable claim. It uses
    no model, works with Jan switched off, and is genuinely useful — a
    straight-line projection is the baseline any cleverer forecast has to beat,
    and having it in the ledger beside the model's is how you find out whether
    the model is beating it.

    A model tier writes richer branches, and every indicator it proposes is
    forced through the same shape. Anything that does not name a series this
    app actually holds is DROPPED rather than kept as prose — the same rule
    Dossier applies to an uncited sentence.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

import store
from signals import registry as sources

PLANS = "plans"
# Where a deleted scenario goes. Moved aside rather than erased, so a click on
# the wrong card costs nothing: moving the file back restores it.
DELETED = "deleted"

# How far ahead a rules-tier projection looks. Long enough to be a forecast,
# short enough that the user finds out whether it was right.
HORIZONS = (
    (90, "in three months"),
    (365, "in a year"),
    # Annual series need a horizon longer than their own cadence or the claim
    # cannot be marked - the next figure will not have published.
    (730, "in two years"),
)
# What a rules-tier scenario can be asked to look at, one distance at a time.
# The short ones let a forecast come due within a fortnight on a daily series
# (fx, pageviews): the cheapest way to see the ledger mark something real. The
# backtest learns only the HORIZONS above, so a claim at a shorter distance
# carries no track record and is never left out because of one.
HORIZON_CHOICES = (
    (14, "in two weeks"),
    (30, "in a month"),
    *HORIZONS,
)


def horizons_for(days: int | None) -> tuple[tuple[int, str], ...]:
    """The usual three horizons, or the one chosen. A distance not offered is
    a ValueError, so nothing invents a horizon the page never showed."""
    if days is None:
        return HORIZONS
    for choice in HORIZON_CHOICES:
        if choice[0] == days:
            return (choice,)
    raise ValueError(f"No horizon of {days} days is offered")


def describe_horizons() -> list[dict]:
    return [{"days": days, "label": phrase} for days, phrase in HORIZON_CHOICES]


# Below this many readings a series has nothing to project from.
MIN_HISTORY = 4


# --- shape ------------------------------------------------------------------


@dataclass
class Indicator:
    """One falsifiable claim about one stored series.

    `series` is a key from `store.sources_for()` — "worldbank.unemployment",
    "fx.per-usd". `direction` is "above" or "below". That is deliberately the
    whole vocabulary: anything richer would need judgement to score, and an
    indicator that needs judgement is not an indicator.
    """

    series: str
    direction: str
    threshold: float
    by_date: str
    note: str = ""
    outcome: str = "pending"  # pending | met | missed | unscorable
    scored_on: str = ""
    observed: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Branch:
    name: str
    narrative: str = ""
    likelihood: str = ""
    indicators: list[Indicator] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "narrative": self.narrative,
            "likelihood": self.likelihood,
            "indicators": [i.as_dict() for i in self.indicators],
        }


@dataclass
class Scenario:
    id: str
    slug: str
    subject: str
    title: str
    created: str
    tier: str
    model: str = ""
    basis: str = ""
    branches: list[Branch] = field(default_factory=list)

    def as_dict(self) -> dict:
        out = {
            "id": self.id,
            "slug": self.slug,
            "subject": self.subject,
            "title": self.title,
            "created": self.created,
            "tier": self.tier,
            "model": self.model,
            "basis": self.basis,
            "branches": [b.as_dict() for b in self.branches],
        }
        out["record"] = tally(self)
        return out


def tally(scenario: Scenario) -> dict:
    counts: dict[str, int] = {"pending": 0, "met": 0, "missed": 0, "unscorable": 0}
    for branch in scenario.branches:
        for indicator in branch.indicators:
            counts[indicator.outcome] = counts.get(indicator.outcome, 0) + 1
    settled = counts["met"] + counts["missed"]
    out: dict = dict(counts)
    out["settled"] = settled
    # None, not 0.0: nothing having come due yet is not a 0% hit rate, and
    # showing one would be a lie the interface would repeat.
    out["accuracy"] = round(counts["met"] / settled, 3) if settled else None
    return out


# --- storage ----------------------------------------------------------------


def _dir(root: Path | None = None) -> Path:
    base = store.data_root().path if root is None else root
    return base / PLANS


def _path(scenario_id: str, root: Path | None = None) -> Path:
    safe = re.sub(r"[^a-z0-9-]", "", scenario_id.lower())
    return _dir(root) / f"{safe}.json"


def _from_dict(raw: dict) -> Scenario:
    branches = []
    for b in raw.get("branches") or []:
        branches.append(
            Branch(
                name=str(b.get("name") or ""),
                narrative=str(b.get("narrative") or ""),
                likelihood=str(b.get("likelihood") or ""),
                indicators=[Indicator(**i) for i in (b.get("indicators") or [])],
            )
        )
    return Scenario(
        id=str(raw.get("id") or ""),
        slug=str(raw.get("slug") or ""),
        subject=str(raw.get("subject") or ""),
        title=str(raw.get("title") or ""),
        created=str(raw.get("created") or ""),
        tier=str(raw.get("tier") or ""),
        model=str(raw.get("model") or ""),
        basis=str(raw.get("basis") or ""),
        branches=branches,
    )


def save(scenario: Scenario, root: Path | None = None) -> Scenario:
    store.write_json(_path(scenario.id, root), scenario.as_dict())
    return scenario


def load(scenario_id: str, root: Path | None = None) -> Scenario | None:
    raw = store.read_json(_path(scenario_id, root), None)
    return _from_dict(raw) if isinstance(raw, dict) else None


def all_scenarios(root: Path | None = None) -> list[Scenario]:
    directory = _dir(root)
    if not directory.is_dir():
        return []
    out = []
    for path in directory.glob("*.json"):
        raw = store.read_json(path, None)
        if isinstance(raw, dict):
            out.append(_from_dict(raw))
    out.sort(key=lambda s: s.created, reverse=True)
    return out


def delete(scenario_id: str, root: Path | None = None) -> bool:
    """Take a scenario off the ledger by moving it into plans/deleted/.

    all_scenarios() reads only the top folder, so a moved file no longer
    counts, and nothing is lost: moving it back brings it and its marks back.
    """
    path = _path(scenario_id, root)
    if not path.is_file():
        return False
    aside = path.parent / DELETED
    aside.mkdir(parents=True, exist_ok=True)
    os.replace(path, aside / path.name)
    return True


# --- the ledger: arithmetic only --------------------------------------------


def score(scenario: Scenario, root: Path | None = None) -> Scenario:
    """Mark every indicator whose date has passed, from the stored readings.

    No model is consulted. An indicator naming a series that does not exist, or
    one whose date has passed with no reading anywhere near it, is marked
    `unscorable` rather than guessed at — a forecast nobody can mark must not
    quietly count as a hit.
    """
    today = date.today().isoformat()
    for branch in scenario.branches:
        for indicator in branch.indicators:
            if indicator.outcome != "pending" or indicator.by_date > today:
                continue
            points = store.read_series(scenario.slug, indicator.series, root)
            usable = [
                p
                for p in points
                if p.get("date")
                and str(p["date"]) <= indicator.by_date
                and p.get("value") is not None
                # A reading that predates the forecast cannot test it. An
                # annual series whose next figure has not published yet would
                # otherwise be marked against the same number the projection
                # was drawn from, and every forecast would score as correct.
                and str(p["date"]) > scenario.created
            ]
            if not usable:
                indicator.outcome = "unscorable"
                indicator.scored_on = today
                continue
            latest = max(usable, key=lambda p: str(p["date"]))
            observed = float(latest["value"])
            indicator.observed = observed
            indicator.scored_on = today
            met = (
                observed > indicator.threshold
                if indicator.direction == "above"
                else observed < indicator.threshold
            )
            indicator.outcome = "met" if met else "missed"
    return scenario


def record(root: Path | None = None) -> dict:
    """The whole ledger: how this app has actually done, across every scenario."""
    counts: dict = {
        "pending": 0,
        "met": 0,
        "missed": 0,
        "unscorable": 0,
        "scenarios": 0,
    }
    by_tier: dict[str, dict] = {}
    for scenario in all_scenarios(root):
        counts["scenarios"] += 1
        line = tally(scenario)
        tier = by_tier.setdefault(
            scenario.tier, {"met": 0, "missed": 0, "pending": 0, "unscorable": 0}
        )
        for key in ("met", "missed", "pending", "unscorable"):
            counts[key] += line.get(key, 0)
            tier[key] += line.get(key, 0)
    for line in list(by_tier.values()) + [counts]:
        settled = int(line["met"]) + int(line["missed"])
        line["settled"] = settled
        line["accuracy"] = round(int(line["met"]) / settled, 3) if settled else None
    return {"totals": counts, "by_tier": by_tier, "backtest": lessons_summary(root)}


# --- learning from what already happened ------------------------------------
#
# The ledger only learns when a forecast comes due, which is months away. But
# the signals now hold years of history, so the same projection can be made
# from a point in the past and marked against what followed - today. That is
# a backtest, and it is how the rules tier learns which series a straight line
# is any good for, instead of asserting one for everything.

LEARNED = "learned"
# Places to stand in the past, per series and horizon, newest first.
MAX_TRIALS = 12
# Fewer trials than this and a lesson is not trusted enough to act on.
MIN_TRIALS = 3


def _latest_date(points: list[dict]) -> str:
    dates = [
        str(p["date"]) for p in points if p.get("date") and p.get("value") is not None
    ]
    return max(dates) if dates else ""


def _window(points: list[dict], origin: str, days: int, cadence: float) -> list[dict]:
    """The readings a projection standing at `origin` may use.

    Only readings at or before the origin: a backtest that peeks past where it
    stands is marking itself against the answer. And only recent ones: with
    five years of daily pageviews stored, a line fitted through all of it
    describes 2021, not the trend a three-month projection should carry.
    """
    lookback = max(2 * days, 6 * cadence, 30)
    start = (date.fromisoformat(origin[:10]) - timedelta(days=lookback)).isoformat()
    return [
        p
        for p in points
        if p.get("date")
        and p.get("value") is not None
        and start <= str(p["date"]) <= origin
    ]


def _middle(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def non_negative(series: str) -> bool:
    """Whether a stored series is a count, by its source's registry flag."""
    spec = sources.get(series.split(".", 1)[0])
    return bool(spec and spec.non_negative)


def whole_numbers(series: str) -> bool:
    """Whether a series counts whole things, by its source's registry flag."""
    spec = sources.get(series.split(".", 1)[0])
    return bool(spec and spec.whole_numbers)


def project(series: str, now: float, per_day: float, days: int) -> float:
    """A straight line carried forward, floored at zero for a count."""
    projected = now + per_day * days
    return max(projected, 0.0) if non_negative(series) else projected


def backtest(points: list[dict], series: str = "") -> list[dict]:
    """Stand at points in the past, project as the rules tier would, and mark it.

    Two methods are compared on the same trials: `trend`, the straight line
    `from_rules` draws, and `persistence`, which assumes nothing changes.
    Persistence needs no method at all, so a line that cannot beat it has not
    earned the right to make a claim. Ties go to persistence for that reason.
    """
    rows = sorted(
        (p for p in points if p.get("date") and p.get("value") is not None),
        key=lambda p: str(p["date"]),
    )
    if len(rows) <= MIN_HISTORY:
        return []
    cadence = _cadence_days(rows)
    first = date.fromisoformat(str(rows[0]["date"])[:10])
    last = date.fromisoformat(str(rows[-1]["date"])[:10])
    lessons = []
    for days, phrase in HORIZONS:
        if cadence and days < cadence * 1.1:
            continue
        step = timedelta(days=max(days // 2, int(cadence) or 1))
        origin = last - timedelta(days=days)
        trials: list[dict] = []
        while origin > first and len(trials) < MAX_TRIALS:
            stand = origin.isoformat()
            target = (origin + timedelta(days=days)).isoformat()
            origin -= step
            now, per_day, when = _slope(_window(rows, stand, days, cadence))
            if not when:
                continue
            # The same rule the ledger uses: the latest reading after the
            # forecast was made and no later than its date.
            later = [p for p in rows if stand < str(p["date"]) <= target]
            if not later:
                continue
            actual = float(later[-1]["value"])
            projected = project(series, now, per_day, days)
            scale = max(abs(actual), abs(now), 1e-9)
            claim = None
            if abs(projected - now) >= abs(now) * 0.005:
                threshold = (now + projected) / 2
                claim = actual > threshold if projected > now else actual < threshold
            trials.append(
                {
                    "at": stand,
                    "trend_error": abs(projected - actual) / scale,
                    "persistence_error": abs(now - actual) / scale,
                    "claim": claim,
                }
            )
        if len(trials) < MIN_TRIALS:
            continue
        claims = [t["claim"] for t in trials if t["claim"] is not None]
        hits = sum(1 for c in claims if c)
        trend_error = _middle([t["trend_error"] for t in trials])
        persistence_error = _middle([t["persistence_error"] for t in trials])
        lessons.append(
            {
                "horizon_days": days,
                "horizon": phrase,
                "trials": len(trials),
                "claims": len(claims),
                "hits": hits,
                "hit_rate": round(hits / len(claims), 3) if claims else None,
                "trend_error": round(trend_error, 4),
                "persistence_error": round(persistence_error, 4),
                "winner": "trend" if trend_error < persistence_error else "persistence",
                "from": trials[-1]["at"],
                "to": trials[0]["at"],
            }
        )
    return lessons


def _learned_path(slug: str, root: Path | None = None) -> Path:
    base = store.data_root().path if root is None else root
    return base / LEARNED / f"{re.sub(r'[^a-z0-9-]', '', slug.lower())}.json"


def learn(slug: str, root: Path | None = None) -> dict:
    """Backtest every series stored for one subject and keep what it taught."""
    series_lessons = {}
    for series in store.sources_for(slug, root):
        found = backtest(store.read_series(slug, series, root), series)
        if found:
            series_lessons[series] = found
    payload = {
        "slug": slug,
        "learned": date.today().isoformat(),
        "series": series_lessons,
    }
    store.write_json(_learned_path(slug, root), payload)
    return payload


def _lesson(lessons: dict, series: str, days: int) -> dict | None:
    for lesson in lessons.get(series) or []:
        if lesson.get("horizon_days") == days:
            return lesson
    return None


def _track(lesson: dict | None) -> str:
    if not lesson or not lesson.get("claims"):
        return ""
    return (
        f" (this claim held {lesson['hits']} of {lesson['claims']} times when "
        "backtested on this series)"
    )


def lessons_summary(root: Path | None = None) -> dict:
    """Everything the backtests have taught, across the library.

    Kept apart from the live ledger on purpose. A backtest is marked against
    history the method could in principle have been tuned on; a live forecast
    is marked against a future nobody had seen. Adding the two together would
    flatter the record.
    """
    base = store.data_root().path if root is None else root
    out: dict = {
        "subjects": 0,
        "series": 0,
        "claims": 0,
        "hits": 0,
        "trend_wins": 0,
        "persistence_wins": 0,
    }
    directory = base / LEARNED
    if directory.is_dir():
        for path in directory.glob("*.json"):
            raw = store.read_json(path, None)
            if not isinstance(raw, dict) or not raw.get("series"):
                continue
            out["subjects"] += 1
            for lessons in raw["series"].values():
                out["series"] += 1
                for lesson in lessons:
                    out["claims"] += int(lesson.get("claims") or 0)
                    out["hits"] += int(lesson.get("hits") or 0)
                    if lesson.get("winner") == "trend":
                        out["trend_wins"] += 1
                    else:
                        out["persistence_wins"] += 1
    out["hit_rate"] = round(out["hits"] / out["claims"], 3) if out["claims"] else None
    return out


# --- writing one: the rules tier --------------------------------------------


def _slope(points: list[dict]) -> tuple[float, float, str]:
    """(value now, change per day, the date of the latest reading).

    Ordinary least squares over the readings, which is the honest way to carry
    a noisy series forward. The last two points alone would make a projection
    hostage to one bad reading.
    """
    rows = [
        (date.fromisoformat(str(p["date"])), float(p["value"]))
        for p in points
        if p.get("date") and p.get("value") is not None
    ]
    if len(rows) < MIN_HISTORY:
        return 0.0, 0.0, ""
    rows.sort()
    origin = rows[-1][0]
    xs = [float((d - origin).days) for d, _ in rows]
    ys = [v for _, v in rows]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    slope = (
        sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
        if denominator
        else 0.0
    )
    return rows[-1][1], slope, origin.isoformat()


def _round_sig(value: float, digits: int = 6) -> float:
    """A threshold with 1803776455339.9253 in it is not a claim anyone can
    check at a glance."""
    if not value:
        return 0.0
    from math import floor, log10

    power = digits - int(floor(log10(abs(value)))) - 1
    return round(value, power)


def _pretty(value: float) -> str:
    magnitude = abs(value)
    for size, suffix in ((1e12, "tn"), (1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if magnitude >= size:
            return f"{value / size:,.3g}{suffix}"
    return f"{value:,.4g}"


def _cadence_days(points: list[dict]) -> float:
    """Median gap between readings. A horizon shorter than this is untestable:
    the next figure will not have published by then."""
    dates = sorted(str(p.get("date") or "") for p in points if p.get("date"))
    gaps = []
    for earlier, later in zip(dates, dates[1:]):
        try:
            gaps.append(
                float((date.fromisoformat(later) - date.fromisoformat(earlier)).days)
            )
        except ValueError:
            continue
    if not gaps:
        return 0.0
    gaps.sort()
    middle = len(gaps) // 2
    return gaps[middle] if len(gaps) % 2 else (gaps[middle - 1] + gaps[middle]) / 2


def from_rules(
    slug: str,
    subject: str,
    root: Path | None = None,
    horizon_days: int | None = None,
) -> Scenario:
    """A straight-line projection of every stored series, as falsifiable claims.

    This is the baseline a cleverer forecast has to beat, and it is the reason
    the plans tab still works with Jan switched off. `horizon_days` asks for one
    distance from HORIZON_CHOICES instead of the usual three.
    """
    horizons = horizons_for(horizon_days)
    today = date.today()
    branches: list[Branch] = []
    carried: list[Indicator] = []
    breaks: list[Indicator] = []

    lessons = learn(slug, root)["series"]
    skipped = 0
    too_young = 0
    for series in store.sources_for(slug, root):
        points = store.read_series(slug, series, root)
        latest = _latest_date(points)
        if not latest:
            continue
        label = series.split(".", 1)[-1].replace("-", " ")
        cadence = _cadence_days(points)
        for days, phrase in horizons:
            # An annual series projected three months out cannot be marked -
            # the next figure will not exist yet - so that claim is not made.
            if cadence and days < cadence * 1.1:
                continue
            by = (today + timedelta(days=days)).isoformat()
            # The claim is dated `by`, so the line runs from the last reading
            # to `by`, not `days` past the last reading: with readings a month
            # old, a two-week claim is really a six-week projection.
            ahead = max(
                days, (date.fromisoformat(by) - date.fromisoformat(latest[:10])).days
            )
            window = _window(points, latest, ahead, cadence)
            now, per_day, when = _slope(window)
            if not when:
                continue
            # A line is not carried further forward than its readings reach
            # back. Four days of forum posts projected two years out made
            # "14 today, 2,640 in two years" - a claim no history supports.
            reach = (
                date.fromisoformat(str(window[-1]["date"])[:10])
                - date.fromisoformat(str(window[0]["date"])[:10])
            ).days
            if reach < ahead:
                too_young += 1
                continue
            lesson = _lesson(lessons, series, days)
            # What the backtest taught: on this series, at this distance, a
            # straight line did no better than assuming nothing changes. Making
            # the claim anyway would be asserting a method known not to work.
            if (
                lesson
                and lesson["trials"] >= MIN_TRIALS
                and lesson["winner"] != "trend"
            ):
                skipped += 1
                continue
            projected = now + per_day * ahead
            if projected < 0 and non_negative(series):
                # "hn below -5.74 by 2028": a count cannot fall below nothing,
                # and a line that says it will has stopped describing the data.
                continue
            if abs(projected - now) < abs(now) * 0.005:
                continue  # a projection indistinguishable from today says nothing
            rising = projected > now
            # The claim is the MIDPOINT between today and the projection, so
            # "the trend continues" and "the trend stalls" genuinely differ.
            threshold = _round_sig((now + projected) / 2)
            if whole_numbers(series):
                threshold = float(round(threshold))
                if threshold < 1:
                    continue  # "hn below 0.09 stories" is not a claim worth making
            carried.append(
                Indicator(
                    series=series,
                    direction="above" if rising else "below",
                    threshold=threshold,
                    by_date=by,
                    note=(
                        f"{label} keeps moving as it has: "
                        f"{_pretty(now)} on {when} → about {_pretty(projected)} {phrase}"
                        + _track(lesson)
                    ),
                )
            )
            breaks.append(
                Indicator(
                    series=series,
                    direction="below" if rising else "above",
                    threshold=threshold,
                    by_date=by,
                    note=f"{label} stalls or turns instead",
                )
            )

    if carried:
        branches.append(
            Branch(
                name="The trend continues",
                narrative=(
                    "Every stored series carried forward at the rate it has been "
                    "moving. No judgement is involved and none is claimed — this "
                    "is the baseline a better forecast has to beat."
                ),
                likelihood="baseline",
                indicators=carried,
            )
        )
        branches.append(
            Branch(
                name="The trend breaks",
                narrative=(
                    "The exact complement of the branch above. Together they "
                    "cover every outcome, so the ledger always learns something."
                ),
                likelihood="complement",
                indicators=breaks,
            )
        )

    return Scenario(
        id=uuid.uuid4().hex[:12],
        slug=slug,
        subject=subject,
        title=f"{subject}: where the numbers are heading"
        + (f" {horizons[0][1]}" if horizon_days is not None else ""),
        created=today.isoformat(),
        tier="rules",
        basis=(
            f"{len(carried)} projections from {len(store.sources_for(slug, root))} "
            "stored series"
            + (
                f"; {skipped} left out because assuming no change beat a straight "
                "line when backtested"
                if skipped
                else ""
            )
            + (
                f"; {too_young} not made because the series is younger than the "
                "forecast would reach"
                if too_young
                else ""
            )
        ),
        branches=branches,
    )


# --- writing one: a model tier ----------------------------------------------

ASK = """You are writing a scenario about {subject}.

Reply with JSON only, in exactly this shape:

{{"title": "...",
  "branches": [
    {{"name": "...", "narrative": "2-3 sentences", "likelihood": "a rough chance",
      "indicators": [
        {{"series": "<one of the series listed below, copied exactly>",
          "direction": "above" | "below",
          "threshold": <number>,
          "by_date": "YYYY-MM-DD",
          "note": "what this would mean"}}
      ]}}
  ]}}

Rules you must follow:
- Two to four branches. They must be genuinely different futures.
- EVERY branch needs at least one indicator. An indicator must name one of the
  series below, exactly as written, and state a number and a date. A branch
  with no indicator is worthless and will be discarded.
- Dates must be in the future and within two years.
- Do not invent a series. Only these exist:

{series}

Here is what is actually stored about {subject}:

{context}
"""


def _series_menu(slug: str, root: Path | None = None) -> str:
    lines = []
    for series in store.sources_for(slug, root):
        points = store.read_series(slug, series, root)
        if not points:
            continue
        latest = points[-1]
        lines.append(
            f"  {series} — latest {latest.get('value')} on {latest.get('date')}"
            f" ({latest.get('detail', '')[:70]})"
        )
    return "\n".join(lines) or "  (nothing stored yet)"


def _salvage(text: str) -> dict:
    """The model's JSON, however it chose to wrap it."""
    if not text:
        return {}
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return {}


def from_model(
    slug: str,
    subject: str,
    tier: str,
    world,
    ask,
    root: Path | None = None,
) -> Scenario:
    """Ask a model for branches, then keep only what can actually be scored.

    `ask` is injected rather than imported so this is testable without Jan, and
    so the caller stays in charge of which tier runs.
    """
    known = set(store.sources_for(slug, root))
    prompt = ASK.format(
        subject=subject,
        series=_series_menu(slug, root),
        context=world.subject_summary(slug, subject)["text"],
    )
    answer = ask(prompt, tier)
    parsed = _salvage(getattr(answer, "text", "") or "")

    today = date.today()
    horizon = (today + timedelta(days=730)).isoformat()
    branches: list[Branch] = []
    dropped = 0
    for raw in parsed.get("branches") or []:
        indicators = []
        for item in raw.get("indicators") or []:
            series = str(item.get("series") or "")
            direction = str(item.get("direction") or "").lower()
            by_date = str(item.get("by_date") or "")
            # THE DISCIPLINE. An indicator that names a series this app does
            # not hold, or has no real date, cannot ever be marked - so it is
            # dropped rather than kept as decoration. Same rule as Dossier's
            # uncited sentence.
            if series not in known or direction not in ("above", "below"):
                dropped += 1
                continue
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", by_date) or not (
                today.isoformat() < by_date <= horizon
            ):
                dropped += 1
                continue
            try:
                threshold = float(item.get("threshold"))
            except (TypeError, ValueError):
                dropped += 1
                continue
            indicators.append(
                Indicator(
                    series=series,
                    direction=direction,
                    threshold=threshold,
                    by_date=by_date,
                    note=str(item.get("note") or ""),
                )
            )
        if not indicators:
            dropped += 1
            continue  # a branch that cannot be scored is not a branch
        branches.append(
            Branch(
                name=str(raw.get("name") or "Unnamed"),
                narrative=str(raw.get("narrative") or ""),
                likelihood=str(raw.get("likelihood") or ""),
                indicators=indicators,
            )
        )

    return Scenario(
        id=uuid.uuid4().hex[:12],
        slug=slug,
        subject=subject,
        title=str(parsed.get("title") or f"{subject}: scenarios"),
        created=today.isoformat(),
        tier=getattr(answer, "tier", tier),
        model=getattr(answer, "model", ""),
        basis=(
            f"{len(branches)} branches kept"
            + (f", {dropped} discarded as unscorable" if dropped else "")
        ),
        branches=branches,
    )
