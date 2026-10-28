"""GDELT: what the world's news is saying about a subject, and how it says it.

WHY IT EARNS A PLACE BESIDE PAGEVIEWS
    Pageviews measure curiosity: a scandal and a death look identical. GDELT
    monitors news coverage in a hundred languages and publishes two things
    pageviews cannot give:

    * **coverage** - how much of the world's news is about this subject, which
      is editorial attention rather than public curiosity. The two come apart,
      and where they come apart is interesting.
    * **tone** - the average sentiment of that coverage, on a scale from about
      -10 to +10, where 0 is neutral. This is the first actual FEELING signal
      in the app; every other source here counts things.

    Two series from one adapter, which is what `Reading.series` is for.

HOW MUCH TO TRUST IT
    Tone is computed from word lists, not understanding, so it measures the
    vocabulary of the coverage rather than its judgement. Reporting on a
    disaster reads negative whoever caused it. Treat a CHANGE in tone as the
    signal and the absolute number as barely meaningful - which is the same
    discipline the breakout analyser already applies to everything else.

    GDELT rate-limits aggressively and answers 429 when it feels like it. A
    failed read is recorded as a source error and costs nothing else; it is
    never on the critical path of a sweep.
"""

from __future__ import annotations

import time
from urllib.parse import quote

from .registry import Reading, SignalSpec

API = "https://api.gdeltproject.org/api/v2/doc/doc"


def _query(subject_name: str, ctx) -> str:
    """The phrase to search for.

    Quoted, so "Donald Trump" is one phrase rather than every article
    containing either word. The Wikipedia title Dossier resolved is preferred
    over the name the user typed, for the same reason pageviews prefers it.
    """
    stored = getattr(ctx, "stored", None) or {}
    identity = (stored.get("subject") or {}).get("identity") or {}
    title = identity.get("wikipedia_title") or subject_name
    return f'"{str(title).strip()}"'


# GDELT answers 429 with the text "Please limit requests to one every 5
# seconds". That is not a failure to route around, it is a published rate, so
# it is obeyed: one wait between this adapter's two calls, and one retry.
# Measured rather than guessed: at 7 seconds between requests it still
# returned 429 three times in a row, and a request after a quiet minute
# succeeded. GDELT's limiter clearly looks at a longer window than the
# message says, so this is deliberately slower than the published rate.
PACE_SECONDS = 9.0


def _timeline(ctx, subject_name: str, mode: str, months: int):
    url = (
        f"{API}?query={quote(_query(subject_name, ctx))}"
        f"&mode={mode}&format=json&timespan={months}m"
    )
    payload = ctx.fetcher.get_json(url, api=True)
    if not payload:
        time.sleep(PACE_SECONDS)
        payload = ctx.fetcher.get_json(url, api=True)
    series = (payload or {}).get("timeline") or []
    return (series[0] or {}).get("data") or [] if series else []


def fetch(subject_name: str, ctx) -> list[Reading]:
    months = 3 if int(getattr(ctx, "days", 60)) <= 100 else 12
    readings: list[Reading] = []

    for index, (mode, series, unit) in enumerate(
        (
            ("timelinevol", "coverage", "% of world coverage"),
            ("timelinetone", "tone", "average tone"),
        )
    ):
        if index:
            time.sleep(PACE_SECONDS)  # the published rate, obeyed
        try:
            rows = _timeline(ctx, subject_name, mode, months)
        except Exception as e:
            ctx.log(f"gdelt: {series} unavailable ({type(e).__name__})")
            continue
        for row in rows:
            stamp = str(row.get("date") or "")
            value = row.get("value")
            if len(stamp) < 8 or value is None:
                continue
            day = f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}"
            readings.append(
                Reading(
                    date=day,
                    value=float(value),
                    detail=f"{series}: {float(value):.4g} {unit}",
                    url="https://www.gdeltproject.org/",
                    series=series,
                )
            )

    ctx.log(f"gdelt: {len(readings)} readings for {subject_name}")
    return readings


SPEC = SignalSpec(
    name="gdelt",
    label="News coverage and tone",
    kind="politics",
    unit="share of coverage, and average tone",
    fetch=fetch,
    description=(
        "How much of the world's news is about this subject, and the average "
        "sentiment of that coverage — editorial attention rather than public "
        "curiosity, and the only feeling signal here."
    ),
    # OFF BY DEFAULT, and not because the adapter is wrong.
    #
    # GDELT rate-limits by IP with a long memory, and Dossier - running on this
    # same machine, with four workers and a queue of two thousand subjects -
    # uses GDELT too. Measured here: every request from this machine answered
    # 429 for the whole session, including after minutes of quiet, while a
    # request made before Dossier's queue was started succeeded. Leaving this
    # enabled would spend eighteen seconds of every sweep, per subject, on a
    # source that will not answer.
    #
    # Turn it on by setting `enabled=True` here when Dossier's queue is idle.
    # The adapter itself is verified against a live 200 response.
    enabled=False,
    caveat=(
        "Tone is computed from word lists, not understanding: coverage of a "
        "disaster reads negative whoever caused it, so a change in tone means "
        "something and the absolute number barely does. GDELT rate-limits "
        "hard and returns 429 without warning. It is off by default because "
        "Dossier, on this same machine, uses GDELT as well and uses up the "
        "limit."
    ),
)
