"""Breakouts: when a subject stops behaving like itself.

Pure arithmetic, no model, no network. A subject's own history is its baseline,
and the finding is that today departs from it — which is a far better question
than "is this number big". Donald Trump's pageviews are always enormous; the
interesting day is the one where they are enormous *for him*.

The measure is a modified z-score built on the **median and the median absolute
deviation** rather than the mean and standard deviation. That is deliberate:
the mean and standard deviation are both dragged around by the very spikes
being looked for, so one huge day raises the bar enough to hide the next one.
The median barely moves.

Two guards against nonsense, both learned from how these series actually look:

* A series needs a real baseline before any claim is made about it. A subject
  watched for three days has no normal to depart from.
* A flat series has a MAD of zero, which would make every z-score infinite. A
  noise floor from counting statistics (the square root of the level) is used
  instead, so a subject sitting at 4 views a day that jumps to 9 does not
  report a thousand-sigma event — while a collapse from 500 to 5 still does.
"""

from __future__ import annotations

from datetime import date
from math import sqrt

from .registry import AnalyserSpec, Finding

# Below this many readings there is no baseline worth comparing against.
MIN_HISTORY = 10
# The most recent readings are the candidates; everything before is baseline.
RECENT = 3
# How many readings before those make up the baseline.
BASELINE = 90
# 0.6745 converts a median absolute deviation to a standard-deviation
# equivalent for normally distributed data, which is the usual convention.
MAD_TO_SIGMA = 0.6745
# Report at this many sigma and above.
THRESHOLD = 3.5


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def score(series: list[float]) -> tuple[float, float, float]:
    """(z-score of the last value, the baseline median, the spread used).

    Exposed separately from `run` so it can be tested against hand-worked
    numbers without building a whole subject on disk.
    """
    if len(series) < MIN_HISTORY:
        return 0.0, 0.0, 0.0
    # Only the recent past is "normal". With five years stored, a median over
    # all of it compares today against 2021 rather than against last quarter.
    baseline = (series[:-RECENT] or series[:-1])[-BASELINE:]
    latest = series[-1]
    median = _median(baseline)
    deviations = [abs(v - median) for v in baseline]
    mad = _median(deviations)
    # A perfectly flat baseline has no spread at all, so dividing by it would
    # make every move infinite. These are counts - views, stories, posts - so
    # their irreducible noise is roughly Poisson, which puts it at the square
    # root of the level. That is why a series sitting at 4 a day jumping to 9
    # is not news. A floor proportional to the median was tried first and was
    # wrong the other way: it made a collapse from 500 to 5 read as two sigma.
    spread = max(mad / MAD_TO_SIGMA, sqrt(max(median, 0.0)), 1.0)
    return (latest - median) / spread, median, spread


def cadence_days(points: list[dict]) -> float:
    """Median gap between readings, in days.

    A z-score against a subject's own baseline is the right question for a
    DAILY series and the wrong one for an annual one: economic indicators
    trend, so the newest year is routinely the largest value in the series and
    would be reported as a breakout every single time. Slow series belong to
    `level.py` instead, and this is how the two divide the work without either
    naming a source.
    """
    dates = sorted(str(p.get("date") or "") for p in points if p.get("date"))
    gaps = []
    for earlier, later in zip(dates, dates[1:]):
        try:
            gaps.append((date.fromisoformat(later) - date.fromisoformat(earlier)).days)
        except ValueError:
            continue
    if not gaps:
        return 0.0
    return _median([float(g) for g in gaps])


# Above this many days between readings a series is "slow" and is left alone.
SLOW_DAYS = 45


def run(slug: str, subject_name: str, series_by_source: dict) -> list[Finding]:
    findings = []
    for source, points in (series_by_source or {}).items():
        values = [float(p.get("value") or 0) for p in points if p.get("date")]
        if len(values) < MIN_HISTORY:
            continue
        if cadence_days(points) > SLOW_DAYS:
            continue
        z, median, _spread = score(values)
        if abs(z) < THRESHOLD:
            continue
        latest = points[-1]
        rising = z > 0
        findings.append(
            Finding(
                kind="breakout",
                subject=subject_name,
                slug=slug,
                headline=(
                    f"{subject_name}: {source} {'up' if rising else 'down'} sharply"
                ),
                detail=(
                    f"{latest.get('value')} on {latest.get('date')} against a usual "
                    f"{median:g} — {abs(z):.1f} sigma {'above' if rising else 'below'} "
                    f"its own baseline. {latest.get('detail', '')}"
                ).strip(),
                # Saturates at 8 sigma: past that it is already the most
                # interesting thing on the page and ranking finer is noise.
                weight=min(1.0, abs(z) / 8.0),
                source=source,
                at=str(latest.get("date") or ""),
                evidence=points[-14:],
            )
        )
    return findings


SPEC = AnalyserSpec(
    name="trend",
    label="Breakouts",
    run=run,
    description=(
        "Where a subject's own numbers depart from its own baseline, measured "
        "with a median-based z-score so one spike cannot hide the next."
    ),
    uses_model=False,
)
