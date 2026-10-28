"""Where should the weekly money go? The Plan tab's answer.

Each path in paths.json gets a fan of possible futures: the 10th, 50th and
90th percentile balance at the end of each year, the share of futures that
end with less than was put in, the worst fall on the way and a rough
after-tax figure. Savings and fund paths replay 12-month runs of real months
(Australian shares, US shares in Australian dollars, the RBA cash rate),
picked at random and joined end to end. Every path sees the same months in a
future, so paths are only ever compared under the same luck. The CFD path is
the Lab's coin-flip trader on random windows of real prices.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field

from . import data, stats
from .engine import RunConfig
from .lab import Lab, LabError

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_YEARS = 40
MAX_WEEKLY = 5000.0
MAX_START = 10_000_000.0
MAX_GOAL = 100_000_000.0
FUND_KINDS = ("cash", "fund")


class PlanError(ValueError):
    pass


def load_paths() -> dict:
    with open(os.path.join(HERE, "paths.json"), encoding="utf-8") as f:
        return json.load(f)


@dataclass
class History:
    """Monthly figures, the same months for every asset: a price asset's
    return as a fraction (dividends in, in Australian dollars), a rate
    asset's rate in force at the start of the month (per cent a year)."""

    months: list[str]
    values: dict[str, list[float]]
    notes: list[str] = field(default_factory=list)


def month_ends(dates: list[str], closes: list[float]) -> dict[str, float]:
    """The last close of each calendar month, leaving out the latest month,
    which may not be over yet."""
    out: dict[str, float] = {}
    for d, c in zip(dates, closes):
        out[d[:7]] = c
    if out:
        out.pop(max(out))
    return out


def rate_at_month_starts(
    dates: list[str], rates: list[float], months: list[str]
) -> list[float]:
    """The rate in force on the first day of each month, from a list of
    rate changes (oldest first)."""
    out: list[float] = []
    j, rate = 0, rates[0] if rates else 0.0
    for m in months:
        while j < len(dates) and dates[j] < m + "-01":
            rate = rates[j]
            j += 1
        out.append(rate)
    return out


def _next_month(m: str) -> str:
    y, mo = int(m[:4]), int(m[5:7])
    return f"{y + mo // 12}-{mo % 12 + 1:02d}"


def monthly_history(
    store: data.PriceStore, spec: dict, income: dict[str, float]
) -> History:
    """`income` holds each price symbol's dividend yield (per cent a year)."""
    hist = spec["history"]
    first = hist.get("first_month", "")
    levels: dict[str, dict[str, float]] = {}
    rate_rows: dict[str, tuple[list[str], list[float]]] = {}
    notes: list[str] = []
    for key, a in hist["assets"].items():
        series = _get(store, a["symbol"])
        if a.get("rate"):
            rate_rows[key] = (series.dates, series.close)
            continue
        series, cut = data.after_breaks(series, "index")
        notes += cut
        ends = month_ends(series.dates, series.close)
        if a.get("fx"):
            fx = _fx_month_ends(store, a["fx"])
            ends = {m: v / fx[m] for m, v in ends.items() if m in fx}
        levels[key] = ends
    common = sorted(set.intersection(*(set(v) for v in levels.values())))
    common = [m for m in common if m >= first] if first else common
    have = set(common)
    # A month's return needs the month before it in every series.
    months = [m for m in common if _next_month(m) in have]
    months = [_next_month(m) for m in months]
    if len(months) < 24:
        raise PlanError(
            "Fewer than two years of monthly prices: refresh prices and try again."
        )
    values: dict[str, list[float]] = {}
    for key, ends in levels.items():
        yearly = income.get(hist["assets"][key]["symbol"], 0.0)
        values[key] = [
            ends[m] / ends[_prev_month(m)] - 1 + yearly / 1200 for m in months
        ]
    for key, (dates, rates) in rate_rows.items():
        values[key] = rate_at_month_starts(dates, rates, months)
    return History(months, values, notes)


def _prev_month(m: str) -> str:
    y, mo = int(m[:4]), int(m[5:7])
    return f"{y - 1}-12" if mo == 1 else f"{y}-{mo - 1:02d}"


def _fx_month_ends(store: data.PriceStore, symbols: list[str]) -> dict[str, float]:
    """US dollars per Australian dollar at each month end: the first symbol,
    with the earlier months filled from the next ones."""
    out: dict[str, float] = {}
    for sym in symbols:
        try:
            series = store.get(sym)
        except data.PriceError:
            continue
        for m, v in month_ends(series.dates, series.close).items():
            out.setdefault(m, v)
    if not out:
        raise PlanError(f"No exchange rates from {', '.join(symbols)}.")
    return out


def _get(store: data.PriceStore, symbol: str):
    try:
        return store.get(symbol)
    except data.PriceError as exc:
        raise PlanError(f"No prices for {symbol}: {exc}") from exc


def futures(
    n_hist: int, months: int, block: int, runs: int, rng: random.Random
) -> list[list[int]]:
    """Index lists into the history: `block`-month runs of real months,
    picked at random and joined end to end. A run may wrap from the last
    month back to the first (a circular bootstrap), so the first and last
    months are drawn as often as the middle ones."""
    block = max(1, min(block, n_hist))
    out: list[list[int]] = []
    for _ in range(runs):
        seq: list[int] = []
        while len(seq) < months:
            a = rng.randrange(0, n_hist)
            seq.extend((a + j) % n_hist for j in range(block))
        out.append(seq[:months])
    return out


@dataclass
class Money:
    """What goes in each month: from take-home pay and into the account."""

    start: float
    monthly_cost: float  # take-home pay given up each month
    monthly_in: float  # what lands in the account each month
    notes: list[str]


def money_for(
    path: dict, start: float, weekly: float, tax: dict, salary: float = 0.0
) -> Money:
    """salary (before tax) sets the room under the concessional cap; 0 means
    not given, and then the cap is only mentioned."""
    monthly = weekly * 52 / 12
    if not path.get("pre_tax"):
        return Money(start, monthly, monthly, [])
    marginal, contrib = tax["marginal"], tax["super_contributions"]
    pre_tax = weekly * 52 / (1 - marginal)
    notes = []
    room = tax["concessional_cap"] - tax["super_guarantee"] * salary
    if salary <= 0:
        notes.append(
            f"The ${tax['concessional_cap']:,.0f} concessional cap also counts "
            "your employer's super, so it is not checked here: add your salary "
            "to check it."
        )
    elif pre_tax > room:
        pre_tax = max(0.0, room)
        fits = pre_tax * (1 - marginal) / 52
        notes.append(
            f"Only about ${fits:,.0f} a week of take-home pay fits under the "
            "concessional cap, so that is all this path puts in."
        )
    cost = pre_tax * (1 - marginal) / 12
    return Money(start, cost, pre_tax * (1 - contrib) / 12, notes)


def growth_factors(
    path: dict, spec: dict, hist: History, cautious: bool
) -> list[float]:
    """1 + the path's return in each history month, after fees and the
    yearly tax on income."""
    assets = spec["history"]["assets"]
    n = len(hist.months)
    if path["kind"] == "cash":
        rates = hist.values[path.get("rate", "cash")]
        keep = 1 - path.get("income_tax", 0.0)
        return [1 + (r + path.get("margin_pct", 0.0)) / 1200 * keep for r in rates]
    mix = path["mix"]
    shares = sum(w for k, w in mix.items() if not assets[k].get("rate"))
    cut = path.get("fee_pct", 0.0) + _income_tax_pct(path, assets)
    if cautious:
        cut += spec.get("cautious_cut_pct", 0.0) * shares
    out = []
    for i in range(n):
        r = 0.0
        for k, w in mix.items():
            v = hist.values[k][i]
            r += w * (v / 1200 if assets[k].get("rate") else v)
        out.append(1 + r - cut / 1200)
    return out


def _income_tax_pct(path: dict, assets: dict) -> float:
    """Yearly tax on the path's income, per cent of the balance."""
    if "drag_pct" in path:
        return path["drag_pct"]
    return sum(w * assets[k].get("income_tax_pct", 0.0) for k, w in path["mix"].items())


def dividends_kept(path: dict, spec: dict, income: dict[str, float]) -> float:
    """Share of the balance paid out as dividends each month and kept in the
    fund after their yearly tax. `income` holds each symbol's dividend yield
    (per cent a year)."""
    if path["kind"] != "fund":
        return 0.0
    assets = spec["history"]["assets"]
    paid = sum(
        w * income.get(assets[k]["symbol"], 0.0)
        for k, w in path["mix"].items()
        if not assets[k].get("rate")
    )
    return max(0.0, paid - _income_tax_pct(path, assets)) / 1200


@dataclass
class Sim:
    """Every future of one path."""

    rows: list[list[float]] = field(default_factory=list)  # balance each year end
    falls: list[float] = field(default_factory=list)  # worst fall of the growth of $1
    bases: list[float] = field(default_factory=list)  # cost base at the end
    recent: list[float] = field(default_factory=list)  # gain on the last year's buys


def simulate(
    g: list[float],
    seqs: list[list[int]],
    money: Money,
    brokerage: float = 0.0,
    reinvest: float = 0.0,
) -> Sim:
    """Balance at each year end in every future and each future's worst fall
    (on the growth of $1, so deposits do not hide it). For the tax on
    selling: the cost base (money paid in plus the dividends kept in, the
    `reinvest` share of the balance each month, already taxed as income) and
    the gain on the last 12 months' buys, which gets no discount."""
    sim = Sim()
    for seq in seqs:
        bal, twr, peak, worst = 0.0, 1.0, 1.0, 0.0
        base, new_value, new_cost = 0.0, 0.0, 0.0
        last_year = len(seq) - 12
        row: list[float] = []
        for m, i in enumerate(seq):
            buy = money.monthly_in + (money.start if m == 0 else 0.0)
            if buy > 0:
                put = max(0.0, buy - brokerage)
                bal += put
                base += buy
                if m >= last_year:
                    new_value += put
                    new_cost += buy
            base += bal * reinvest
            bal *= g[i]
            new_value *= g[i]
            twr *= g[i]
            if twr > peak:
                peak = twr
            elif 1 - twr / peak > worst:
                worst = 1 - twr / peak
            if (m + 1) % 12 == 0:
                row.append(bal)
        sim.rows.append(row)
        sim.falls.append(worst)
        sim.bases.append(base)
        sim.recent.append(new_value - new_cost)
    return sim


def after_tax(
    path: dict, end: float, base: float, recent: float = 0.0, full: float = 0.0
) -> float:
    """What is left after selling everything. `base` is the cost base. A gain
    held at least a year is taxed at the path's gain_tax (half of it at the
    marginal rate); `recent`, the gain on buys held under a year, is taxed at
    `full`, the marginal rate, when that is higher."""
    rate = path.get("gain_tax", 0.0)
    gain = end - base
    if gain <= 0 or not rate:
        return end
    short = min(max(recent, 0.0), gain)
    return end - short * max(rate, full) - (gain - short) * rate


def goal_reach(
    by_year: list[list[float]], goal: float, today: bool = False, infl: float = 0.0
) -> dict:
    """How often the futures reach `goal`. by_year[y] holds every future's
    balance at the end of year y + 1. Gives the share at or above the goal
    each year and at the end, and the first year at least half of them are
    there (None when that never happens). A goal in today's dollars
    (`today`) grows with inflation (`infl`, % a year) so it keeps its
    buying power."""
    shares = []
    for y, vals in enumerate(by_year, start=1):
        bar = goal * ((1 + infl / 100) ** y if today else 1.0)
        shares.append(
            round(sum(v >= bar for v in vals) / len(vals), 3) if vals else 0.0
        )
    half = next((y for y, s in enumerate(shares, start=1) if s >= 0.5), None)
    return {
        "amount": goal,
        "today": today,
        "share": shares[-1] if shares else 0.0,
        "by_year": shares,
        "half_year": half,
    }


def comfort_word(fall_p50: float, fall_p90: float, comfort: float) -> str:
    if fall_p90 <= comfort:
        return "ok"
    if fall_p50 <= comfort:
        return "tight"
    return "over"


def plan(
    store: data.PriceStore,
    lab: Lab | None = None,
    start: float = 100.0,
    weekly: float = 300.0,
    years: int = 10,
    comfort: float = 0.3,
    cautious: bool = False,
    runs: int = 1000,
    seed: int = 1,
    kinds: list[str] | None = None,
    spec: dict | None = None,
    salary: float = 0.0,
    goal: float = 0.0,
    goal_today: bool = False,
) -> dict:
    """The Plan tab. With a `goal` (dollars, 0 for none) every path also says
    how often it gets there (goal_reach), in today's dollars when
    `goal_today`."""
    if not 1 <= years <= MAX_YEARS:
        raise PlanError(f"Pick between 1 and {MAX_YEARS} years.")
    if not (0 <= weekly <= MAX_WEEKLY and 0 <= start <= MAX_START):
        raise PlanError(f"Weekly money must be $0 to ${MAX_WEEKLY:,.0f}.")
    if start + weekly <= 0:
        raise PlanError("Put something in: a starting amount or a weekly amount.")
    if not 0 < comfort < 1:
        raise PlanError("The fall you can sit through must be between 0% and 100%.")
    if not 0 <= goal <= MAX_GOAL:
        raise PlanError(f"A goal must be $0 to ${MAX_GOAL:,.0f}.")
    spec = spec or load_paths()
    infl = spec.get("inflation_pct", 0.0)
    lab = lab or Lab(store)
    runs = max(100, min(4000, runs))
    wanted = [p for p in spec["paths"] if not kinds or p["kind"] in kinds]
    out_paths: list[dict] = []
    notes: list[str] = []
    history = None
    if any(p["kind"] in FUND_KINDS for p in wanted):
        income = {s: i.dividend_yield_pct for s, i in lab.instruments.items()}
        hist = monthly_history(store, spec, income)
        notes += hist.notes
        seqs = futures(
            len(hist.months),
            years * 12,
            spec["history"].get("block_months", 12),
            runs,
            random.Random(seed),
        )
        finals: dict[str, list[float]] = {}
        for p in wanted:
            if p["kind"] not in FUND_KINDS:
                continue
            money = money_for(p, start, weekly, spec["tax"], salary)
            g = growth_factors(p, spec, hist, cautious)
            kept = dividends_kept(p, spec, income)
            sim = simulate(g, seqs, money, p.get("brokerage", 0.0), kept)
            full = spec["tax"]["marginal"]
            finals[p["id"]] = [
                after_tax(p, r[-1], b, n, full)
                for r, b, n in zip(sim.rows, sim.bases, sim.recent)
            ]
            row = _fund_result(p, sim, finals[p["id"]], money, years, comfort)
            if goal > 0:
                by_year = [[r[y] for r in sim.rows] for y in range(years)]
                row["goal"] = goal_reach(by_year, goal, goal_today, infl)
            out_paths.append(row)
        base = finals.get("savings")
        for row in out_paths:
            # locked money is not compared with money he can spend
            if base and row["id"] != "savings" and not row.get("locked"):
                mine = finals[row["id"]]
                row["beats_savings"] = round(
                    sum(a > b for a, b in zip(mine, base)) / len(base), 3
                )
        history = {
            "first": hist.months[0],
            "last": hist.months[-1],
            "months": len(hist.months),
            "assets": _asset_facts(spec, hist),
        }
    for p in wanted:
        if p["kind"] == "zero_skill":
            row = _zero_skill(lab, p, start, weekly, years, comfort, seed)
            if goal > 0:
                row["goal"] = goal_reach(row.pop("_marks"), goal, goal_today, infl)
            else:
                row.pop("_marks")
            out_paths.append(row)
    order = {p["id"]: i for i, p in enumerate(spec["paths"])}
    out_paths.sort(key=lambda r: order.get(r["id"], 99))
    return {
        "start": start,
        "weekly": weekly,
        "years": years,
        "comfort": comfort,
        "cautious": cautious,
        "goal": goal,
        "goal_today": goal_today,
        "runs": runs,
        "history": history,
        "inflation_pct": infl,
        "today_factor": round((1 + infl / 100) ** -years, 4),
        "paths": out_paths,
        "info": spec.get("info", []),
        "comfort_levels": spec.get("comfort", []),
        "tax_note": spec["tax"].get("note", ""),
        "notes": notes,
    }


def _fund_result(
    p: dict,
    sim: Sim,
    taxed: list[float],
    money: Money,
    years: int,
    comfort: float,
) -> dict:
    fan = []
    for y in range(years):
        paid = money.start + money.monthly_cost * 12 * (y + 1)
        fan.append(
            {
                "year": y + 1,
                **stats.spread([r[y] for r in sim.rows]),
                "money_in": round(paid, 2),
            }
        )
    money_in = fan[-1]["money_in"]
    ends = [r[-1] for r in sim.rows]
    fall = stats.spread(sim.falls)
    row = _describe(p)
    row.update(
        {
            "years": years,
            "fan": fan,
            "end": stats.spread(ends),
            "money_in": money_in,
            "below_money_in": round(sum(e < money_in for e in ends) / len(ends), 3),
            "after_tax_p50": stats.spread(taxed)["p50"],
            "fall_p50": fall["p50"],
            "fall_p90": fall["p90"],
            "comfort": comfort_word(fall["p50"], fall["p90"], comfort),
            "notes": list(money.notes),
        }
    )
    row["words"] = _words(row)
    return row


_CACHE: dict[tuple, dict] = {}


def _zero_skill(
    lab: Lab,
    p: dict,
    start: float,
    weekly: float,
    years: int,
    comfort: float,
    seed: int,
) -> dict:
    yrs = min(years, p.get("max_years", 10))
    span = round(yrs * 252)
    runs = max(60, min(300, 600_000 // span))
    cfg = RunConfig(start_cash=start, deposit=weekly, leverage=p.get("leverage", 1.0))
    last = lab.store.facts(p["symbol"]).get("last", "")
    key = (
        p["symbol"],
        start,
        weekly,
        yrs,
        cfg.leverage,
        p.get("trades_per_year"),
        seed,
        last,
    )
    z = _CACHE.get(key)
    if z is None:
        try:
            z = lab.zero_skill(
                p["symbol"],
                cfg,
                years=yrs,
                runs=runs,
                trades_per_year=p.get("trades_per_year", 25),
                hold_days=p.get("hold_days", 5),
                seed=seed,
                venue_id=p.get("venue", "cfd"),
                keep_marks=True,
            )
        except LabError as exc:
            raise PlanError(str(exc)) from exc
        if len(_CACHE) > 64:
            _CACHE.clear()
        _CACHE[key] = z
    money_in = z["fan"][-1]["money_in"] if z["fan"] else z["money_in_median"]
    row = _describe(p)
    row.update(
        {
            "years": yrs,
            "fan": z["fan"],
            "end": {"p10": z["p10"], "p50": z["p50"], "p90": z["p90"]},
            "money_in": money_in,
            "below_money_in": z["lost_share"],
            "after_tax_p50": round(after_tax(p, z["p50"], z["money_in_median"]), 2),
            "fall_p50": z["fall_p50"],
            "fall_p90": z["fall_p90"],
            "comfort": comfort_word(z["fall_p50"], z["fall_p90"], comfort),
            "closeout_share": z["closeout_share"],
            "median_costs": z["median_costs"],
            "runs": z["runs"],
            "window": {"first": z["first"], "last": z["last"]},
            "notes": list(z["notes"]),
            # every trader's balance at each year end, for goal_reach; plan()
            # takes it off before answering
            "_marks": z["marks"],
        }
    )
    if yrs < years:
        unit = "year" if yrs == 1 else "years"
        row["notes"].append(f"Shown for {yrs} {unit}, the most this path runs.")
    row["words"] = _words(row)
    return row


def _asset_facts(spec: dict, hist: History) -> dict:
    """What each asset did over the history: a year's return and its worst
    month, or a rate's average."""
    out = {}
    years = len(hist.months) / 12
    for key, a in spec["history"]["assets"].items():
        v = hist.values[key]
        if a.get("rate"):
            out[key] = {"label": a["label"], "average_rate": round(sum(v) / len(v), 2)}
            continue
        growth = 1.0
        for x in v:
            growth *= 1 + x
        out[key] = {
            "label": a["label"],
            "a_year": round(growth ** (1 / years) - 1, 4),
            "worst_month": round(min(v), 4),
        }
    return out


def _describe(p: dict) -> dict:
    keep = (
        "id",
        "kind",
        "short",
        "label",
        "colour",
        "summary",
        "locked",
        "sources",
        "assumptions",
    )
    return {k: p[k] for k in keep if k in p}


def _words(row: dict) -> str:
    e = row["end"]
    yrs = row["years"]
    text = (
        f"Put in ${row['money_in']:,.0f} over {yrs} year{'s' if yrs != 1 else ''}. "
        f"Middle future: ${e['p50']:,.0f}. One in ten ended below ${e['p10']:,.0f}, "
        f"one in ten above ${e['p90']:,.0f}. "
    )
    below = row["below_money_in"]
    if below >= 0.005:
        text += f"{below * 100:.0f}% of futures ended with less than was put in. "
    else:
        text += "No future ended with less than was put in. "
    text += (
        f"Worst fall on the way: {row['fall_p50'] * 100:.0f}% in a typical future, "
        f"{row['fall_p90'] * 100:.0f}% in a bad one."
    )
    return text
