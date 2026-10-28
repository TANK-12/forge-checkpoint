"""Slow series: where a published figure stands, and which way it is going.

WHY THIS IS A SEPARATE ANALYSER
    `trend.py` asks "is today unlike this subject's own normal", which is
    exactly right for a daily attention series and exactly wrong for an annual
    economic one. Economic indicators trend: the newest year is routinely the
    largest value in a GDP series, and a z-score would report a breakout every
    single time and never be interesting.

    The useful questions about a slow series are different, and they are the
    ones a person actually asks. Where does it stand? Which way has it moved
    since the last reading? Is that a break in a run, or more of the same? Is
    it the highest or lowest it has ever been?

    No model, no network. Arithmetic over what is already stored, which is what
    lets it run on the CPU while the iGPU is busy.

WHAT COUNTS AS WORTH SAYING
    Not every figure. A series that moved a fraction of a percent is not news,
    and a findings list that reports everything is a findings list nobody
    reads. A reading is reported when it is a record high or low for the series
    it belongs to, or when it moved more than `MOVE` from the previous reading.
    The level itself is always attached to the finding, because "unemployment
    rose 12%" is meaningless without knowing it rose to 4.1%.
"""

from __future__ import annotations

from datetime import date

from .registry import AnalyserSpec, Finding

# A series whose readings are further apart than this belongs here rather than
# to the breakout z-score. Kept identical in meaning to trend.SLOW_DAYS - the
# two analysers divide every series between them and neither names a source.
SLOW_DAYS = 45
# Below this many readings there is nothing to compare against.
MIN_HISTORY = 3
# Relative change from the previous reading that is worth reporting at all.
MOVE = 0.05


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def cadence_days(points: list[dict]) -> float:
    dates = sorted(str(p.get("date") or "") for p in points if p.get("date"))
    gaps = []
    for earlier, later in zip(dates, dates[1:]):
        try:
            gaps.append(
                float((date.fromisoformat(later) - date.fromisoformat(earlier)).days)
            )
        except ValueError:
            continue
    return _median(gaps) if gaps else 0.0


def _pretty(value: float) -> str:
    """A figure a person can read. 1.799e+12 is not one."""
    magnitude = abs(value)
    for size, suffix in ((1e12, "tn"), (1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if magnitude >= size:
            return f"{value / size:,.3g}{suffix}"
    if magnitude >= 10:
        return f"{value:,.4g}"
    return f"{value:,.3g}"


def _unit(points: list[dict]) -> str:
    """The unit the adapter wrote, so "57.88" does not stand alone.

    The adapters write "Government debt: 57.88 % of GDP (Australia, 2022)", so
    the unit is whatever sits between the figure and the bracket. A number
    without its unit is the kind of confident, unreadable output this app is
    supposed to avoid.
    """
    for point in reversed(points):
        detail = str(point.get("detail") or "")
        if ":" not in detail:
            continue
        tail = detail.split(":", 1)[1].strip()
        tail = tail.split(" (")[0].strip()
        parts = tail.split(None, 1)
        if len(parts) == 2:
            return parts[1].strip()
    return ""


def _label(points: list[dict], source: str) -> str:
    """What this series is called, taken from the reading's own detail.

    The adapters write "Unemployment: 4.09 % of labour force (Australia, 2025)",
    so the part before the colon is the indicator's own name. Falling back to
    the stored key means a source that writes no detail still reads sensibly.
    """
    for point in reversed(points):
        detail = str(point.get("detail") or "")
        if ":" in detail:
            return detail.split(":", 1)[0].strip()
    return source.split(".", 1)[-1].replace("-", " ")


def run(slug: str, subject_name: str, series_by_source: dict) -> list[Finding]:
    findings: list[Finding] = []
    for source, points in (series_by_source or {}).items():
        rows = [p for p in points if p.get("date") and p.get("value") is not None]
        if len(rows) < MIN_HISTORY or cadence_days(rows) <= SLOW_DAYS:
            continue
        rows = sorted(rows, key=lambda p: str(p.get("date")))
        values = [float(p["value"]) for p in rows]
        latest, previous = values[-1], values[-2]
        label = _label(rows, source)
        when = str(rows[-1].get("date") or "")[:4]

        change = (latest - previous) / abs(previous) if previous else 0.0
        # Compared against the readings BEFORE this one. Against the whole
        # series the latest value is trivially its own maximum, so every
        # series would report a record every time and the word would stop
        # meaning anything.
        earlier = values[:-1]
        high = latest > max(earlier)
        low = latest < min(earlier)

        if not (high or low or abs(change) >= MOVE):
            continue

        if high and len(values) > 3:
            note, weight = f"the highest in {len(values)} readings", 0.6
        elif low and len(values) > 3:
            note, weight = f"the lowest in {len(values)} readings", 0.6
        else:
            note, weight = "", 0.35
        # A big move is more interesting than a small one, but this never
        # outranks a real breakout in a live series - those saturate at 1.0.
        weight = min(0.75, weight + min(abs(change), 1.0) * 0.25)

        unit = _unit(rows)
        direction = "up" if change > 0 else "down" if change < 0 else "flat"
        shown = f"{_pretty(latest)} {unit}".strip()
        detail = f"{shown} in {when}, {direction} "
        detail += f"{abs(change) * 100:.1f}% from {_pretty(previous)}"
        if note:
            detail += f" — {note}"

        findings.append(
            Finding(
                kind="level",
                subject=subject_name,
                slug=slug,
                headline=f"{subject_name}: {label}",
                detail=detail,
                weight=weight,
                source=source,
                at=str(rows[-1].get("date") or ""),
                evidence=rows[-12:],
            )
        )
    return findings


SPEC = AnalyserSpec(
    name="level",
    label="Where the figures stand",
    run=run,
    description=(
        "For published figures that arrive yearly rather than daily: the latest "
        "level, which way it moved, and whether it is a record for that series."
    ),
    uses_model=False,
)
