"""Luck check: is a strategy's result better than luck?

The account's own trades are replayed on a few hundred coin-flip copies of
the same days. In each copy every day's move is either kept or turned the
other way round the market's average drift (up 2% becomes down 2%), at
random, so the copies keep every trade, size, cost and day, and only the
luck of which way each day went differs. Where the account lands among them
says how unusual its result is. The odds it gives (p) count the account as
one more copy, so they can never claim more than the number of copies can
show: with 200 copies, beating every one of them still happens by luck one
time in 201.
"""

from __future__ import annotations

import dataclasses
import math
import random

from .engine import RunConfig, RunResult, run
from .series import Series
from .venues import Instrument, Venue


def profile(res: RunResult, targets: list[float]) -> dict:
    live = [x for x in targets if abs(x) > 1e-9]
    entries = max(1, res.account.entries)
    return {
        "entries": res.account.entries,
        "avg_hold": max(1.0, res.bars_in_market / entries),
        "size": (sum(abs(x) for x in live) / len(live)) if live else 1.0,
        "long_share": (sum(1 for x in live if x > 0) / len(live)) if live else 1.0,
        "time_in_market": res.bars_in_market / max(1, len(res.dates) - 1),
    }


def random_targets(n: int, prof: dict, rng: random.Random) -> list[float]:
    """Random entries matching the profile. Two draws per day, always, so a
    shorter series gives the same start (no peeking either)."""
    hold = prof["avg_hold"]
    q = min(0.95, prof["time_in_market"])
    trips_per_bar = prof["entries"] / max(1, n)
    p_enter = min(1.0, trips_per_bar / max(0.05, 1 - q))
    p_exit = 1 / hold
    pos = 0.0
    out: list[float] = []
    for _ in range(n):
        u, v = rng.random(), rng.random()
        if pos == 0.0:
            if u < p_enter:
                pos = prof["size"] * (1 if v < prof["long_share"] else -1)
        elif u < p_exit:
            pos = 0.0
        out.append(pos)
    return out


def drift(series: Series) -> float:
    """The window's average daily move, in log terms, close to close."""
    c = series.close
    if len(c) < 2 or c[0] <= 0 or c[-1] <= 0:
        return 0.0
    return math.log(c[-1] / c[0]) / (len(c) - 1)


def mirrored(series: Series, flips: list[bool], mean: float) -> Series:
    """The same days, each flipped day's move turned the other way round
    `mean` (log terms, against the day before's close): its open, high and
    low turn with it, so the bar keeps its shape. Day 0 stays as it is."""
    o, h, lo, c = [series.open[0]], [series.high[0]], [series.low[0]], [series.close[0]]
    for t in range(1, len(series)):
        prev = series.close[t - 1]
        bar = (series.open[t], series.high[t], series.low[t], series.close[t])
        if prev <= 0 or min(bar) <= 0:
            moves = [1.0, 1.0, 1.0, 1.0]
        else:
            lo_, lh, ll, lc = (math.log(x / prev) for x in bar)
            if flips[t]:
                lo_, lh, ll, lc = (
                    2 * mean - lo_,
                    2 * mean - ll,
                    2 * mean - lh,
                    2 * mean - lc,
                )
            moves = [math.exp(x) for x in (lo_, lh, ll, lc)]
        base = c[-1]
        o.append(base * moves[0])
        h.append(base * moves[1])
        lo.append(base * moves[2])
        c.append(base * moves[3])
    return dataclasses.replace(series, open=o, high=h, low=lo, close=c, notes=[])


def check(
    series: Series,
    targets: list[float],
    venue: Venue,
    inst: Instrument,
    cfg: RunConfig,
    res: RunResult,
    fx: list[float] | None = None,
    runs: int = 200,
    seed: int = 1,
    rates: dict[str, list[float]] | None = None,
) -> dict:
    prof = profile(res, targets)
    mine = res.equity[-1] if res.equity else 0.0
    skip = ""
    if prof["time_in_market"] > 0.95:
        skip = (
            "Always invested, so there is nothing to luck-check: compare it with "
            "the benchmark instead."
        )
    elif prof["entries"] < 2:
        n = int(prof["entries"])
        skip = f"{n} trade{'' if n == 1 else 's'} in these days: too few trades to luck-check."
    if skip:
        return {"skipped": True, "verdict": skip, "profile": _round(prof)}
    rng = random.Random(seed)
    mean = drift(series)
    finals = []
    for _ in range(runs):
        flips = [rng.random() < 0.5 for _ in range(len(series))]
        copy = mirrored(series, flips, mean)
        finals.append(run(copy, targets, venue, inst, cfg, fx, rates).equity[-1])
    finals.sort()
    below = sum(1 for x in finals if x < mine) + 0.5 * sum(
        1 for x in finals if x == mine
    )
    pct = 100 * below / runs
    at_or_above = sum(1 for x in finals if x >= mine)
    p = (1 + at_or_above) / (runs + 1)
    return {
        "skipped": False,
        "runs": runs,
        "percentile": round(pct, 1),
        "p": p,
        "median": round(finals[len(finals) // 2], 2),
        "p10": round(finals[len(finals) // 10], 2),
        "p90": round(finals[(len(finals) * 9) // 10], 2),
        "hist": histogram(finals, mine),
        "verdict": verdict(at_or_above, runs),
        "profile": _round(prof),
    }


def verdict(at_or_above: int, runs: int) -> str:
    """Words from the counts, never a share beaten: the account counts as one
    more copy, so even beating every copy is not "100%"."""
    p = (1 + at_or_above) / (runs + 1)
    if at_or_above == 0:
        did = f"None of the {runs} coin-flip copies of these days did as well"
    else:
        did = (
            f"{at_or_above} of {runs} coin-flip copies of these days did as well "
            "or better"
        )
    if p <= 0.05:
        return (
            f"{did}, paying the same costs. That is rare for luck alone, but one "
            "market and one stretch of days can still fool you."
        )
    if p <= 0.25:
        return (
            f"{did}. Luck alone does this well about {100 * p:.0f}% of the time, "
            "so this could easily be luck."
        )
    return f"{did}. No sign of skill here."


def histogram(values: list[float], mark: float, bins: int = 24) -> dict:
    lo = min(values + [mark])
    hi = max(values + [mark])
    width = (hi - lo) / bins or 1.0
    counts = [0] * bins
    for v in values:
        counts[min(bins - 1, int((v - lo) / width))] += 1
    return {
        "lo": round(lo, 2),
        "hi": round(hi, 2),
        "counts": counts,
        "mark": round(mark, 2),
    }


def _round(d: dict) -> dict:
    return {k: round(v, 3) if isinstance(v, float) else v for k, v in d.items()}
