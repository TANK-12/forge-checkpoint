"""Numbers about a run, for the whole period or a slice of it."""

from __future__ import annotations

import math
import statistics

from .engine import RunResult
from .series import days_between


def xirr(flows: list[tuple[str, float]]) -> float | None:
    """Money-weighted yearly return. Money in is negative, the final value
    positive. -1.0 means everything was lost."""
    if not flows:
        return None
    t0 = flows[0][0]
    pts = [(days_between(t0, d) / 365.25, v) for d, v in flows if v]
    if not any(v > 0 for _, v in pts):
        return -1.0
    if not any(v < 0 for _, v in pts):
        return None

    def npv(r: float) -> float:
        return sum(v / (1 + r) ** t for t, v in pts)

    lo, hi = -0.9999, 10.0
    if npv(hi) > 0:
        return hi
    if npv(lo) < 0:
        return -1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-9:
            break
    return (lo + hi) / 2


def segment(
    res: RunResult, a: int = 0, b: int | None = None, cash_rate_pct: float = 0.0
) -> dict:
    """Stats for days a..b (inclusive)."""
    n = len(res.dates)
    b = n - 1 if b is None else b
    if n == 0 or b <= a:
        return {"days": 0}
    dates = res.dates[a : b + 1]
    twr = res.twr[a : b + 1]
    eq = res.equity[a : b + 1]
    flows = res.flows[a : b + 1]
    years = max(days_between(dates[0], dates[-1]) / 365.25, 1 / 365.25)
    growth = twr[-1] / twr[0] if twr[0] > 0 else 0.0
    cagr = growth ** (1 / years) - 1 if growth > 0 else -1.0

    peak = twr[0]
    max_dd = 0.0
    rets: list[float] = []
    for i in range(1, len(twr)):
        if twr[i] > peak:
            peak = twr[i]
        if peak > 0:
            max_dd = max(max_dd, 1 - twr[i] / peak)
        if twr[i - 1] > 0:
            rets.append(twr[i] / twr[i - 1] - 1)
    vol = sharpe = None
    if len(rets) > 2:
        mean = sum(rets) / len(rets)
        var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
        sd = math.sqrt(var)
        vol = sd * math.sqrt(252)
        if sd > 0:
            sharpe = (mean - cash_rate_pct / 100 / 252) / sd * math.sqrt(252)

    months: dict[str, float] = {}
    for d, v in zip(dates, twr):
        months[d[:7]] = v
    month_vals = list(months.values())
    worst_month = None
    prev = twr[0]
    for v in month_vals:
        if prev > 0:
            r = v / prev - 1
            worst_month = r if worst_month is None else min(worst_month, r)
        prev = v

    money_in = eq[0] + sum(flows[1:])
    cash_flows = [(dates[0], -eq[0])]
    cash_flows += [(dates[i], -flows[i]) for i in range(1, len(dates)) if flows[i]]
    cash_flows.append((dates[-1], eq[-1]))
    return {
        "start": dates[0],
        "end": dates[-1],
        "days": len(dates),
        "years": round(years, 2),
        "final": round(eq[-1], 2),
        "money_in": round(money_in, 2),
        "profit": round(eq[-1] - money_in, 2),
        "growth": round(growth, 4),
        "cagr": round(cagr, 4),
        "money_weighted": _r(xirr(cash_flows)),
        "max_drawdown": round(max_dd, 4),
        "volatility": _r(vol),
        "sharpe": _r(sharpe, 2),
        "worst_month": _r(worst_month),
    }


def _r(x: float | None, places: int = 4) -> float | None:
    return None if x is None else round(x, places)


def trade_stats(res: RunResult) -> dict:
    acct = res.account
    trips = acct.round_trips
    wins = [t for t in trips if t["result"] > 0]
    n = len(res.dates)
    return {
        "entries": acct.entries,
        "fills": len(acct.trades),
        "round_trips": len(trips),
        "win_rate": round(len(wins) / len(trips), 3) if trips else None,
        "time_in_market": round(res.bars_in_market / max(1, n - 1), 3),
        "avg_hold_days": (
            round(res.bars_in_market / acct.entries, 1) if acct.entries else None
        ),
        "costs": {k: round(v, 2) for k, v in acct.costs.items()},
        "costs_total": round(sum(acct.costs.values()), 2),
        "interest": round(acct.interest, 2),
        "dividends": round(acct.dividends, 2),
        "closeouts": acct.closeouts,
        "stops_hit": acct.stops_hit,
        "written_off": round(acct.protected, 2),
    }


def best_of_k(k: int, p: float = 0.95) -> float:
    """Chance that at least one of k skill-free tries clears the p bar."""
    return 1 - p ** max(0, k)


def spread(values: list[float]) -> dict:
    """10th, 50th and 90th percentile, nearest rank."""
    v = sorted(values)
    k = len(v)
    return {
        "p10": round(v[k // 10], 2),
        "p50": round(statistics.median(v), 2),
        "p90": round(v[(k * 9) // 10], 2),
    }


def max_fall(growth: list[float]) -> float:
    """Biggest drop from a high, as a fraction, of a growth-of-$1 line."""
    peak, worst = 0.0, 0.0
    for g in growth:
        peak = max(peak, g)
        if peak > 0:
            worst = max(worst, 1 - g / peak)
    return worst
