"""Backtest: one strategy, one market, fake money, one day at a time.

The strategy decides at the close of day t from prices up to t; the engine
trades at the open of day t+1. Order of events on each day:
overnight costs, deposits, the open (gap), the strategy's trade, stops and
the margin close-out on the day's range, then the close.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

from .account import Account
from .series import Series, days_between
from .venues import Instrument, Venue

TWR_FLOOR = 1e-9  # growth of $1 never quite reaches zero; see run()


@dataclass
class RunConfig:
    start_cash: float = 100.0
    deposit: float = 300.0
    deposit_every_days: int = 7
    leverage: float = 1.0  # position value / equity when the strategy is all in
    band: float = 0.2  # CFD: re-size only when this far (fraction) off target
    stop_pct: float = 0.0  # stop-loss this many % past the entry price, 0 = none
    min_trade: float | None = None  # share account: smallest buy, None = the venue's


@dataclass
class RunResult:
    dates: list[str]
    equity: list[float]
    flows: list[float]  # money deposited on each day (day 0 holds the start)
    exposure: list[float]  # position value / equity at each close, signed
    twr: list[float]  # time-weighted growth of $1, deposits taken out
    account: Account
    leverage_used: float
    bars_in_market: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def deposited(self) -> float:
        return sum(self.flows)


def run(
    series: Series,
    targets: list[float],
    venue: Venue,
    inst: Instrument,
    cfg: RunConfig,
    fx: list[float] | None = None,
    rates: dict[str, list[float]] | None = None,
) -> RunResult:
    """`rates` holds each currency's benchmark rate (per cent) on each day;
    a currency left out uses the venue's fixed figure."""
    n = len(series)
    rates = rates or {}
    fx = fx or [1.0] * n
    sym = series.symbol
    acct = Account(venue)
    acct.instruments[sym] = inst
    notes: list[str] = []
    if venue.kind == "cfd":
        cap = venue.cap(inst.cls)
        lev = min(cfg.leverage, cap)
        if cfg.leverage > cap:
            notes.append(f"Leverage cut to {cap:g}x, the retail limit for this market.")
    else:
        lev = 1.0
        if cfg.leverage > 1:
            notes.append("A share account has no leverage, so 1x was used.")

    flows = [0.0] * n
    equity = [0.0] * n
    exposure = [0.0] * n
    twr = [1.0] * n
    if n == 0:
        return RunResult([], [], [], [], [], acct, lev, 0, notes)
    acct.deposit(cfg.start_cash)
    flows[0] = cfg.start_cash
    equity[0] = cfg.start_cash
    step = dt.timedelta(days=max(1, cfg.deposit_every_days))
    next_dep = dt.date.fromisoformat(series.dates[0]) + step
    in_market = waited = 0
    o_, h_, l_, c_ = series.open, series.high, series.low, series.close

    for t in range(1, n):
        d = series.dates[t]
        o, hi, lo, c, f = o_[t], h_[t], l_[t], c_[t], fx[t]
        acct.rates = {cur: r[t - 1] for cur, r in rates.items()}
        acct.accrue(
            days_between(series.dates[t - 1], d), {sym: c_[t - 1]}, {sym: fx[t - 1]}
        )
        # the old balance at today's open, before any deposit lands
        v_open = acct.equity({sym: o}, {sym: f})
        if cfg.deposit > 0:
            today = dt.date.fromisoformat(d)
            while next_dep <= today:
                acct.deposit(cfg.deposit)
                flows[t] += cfg.deposit
                next_dep += step
        if sym in acct.positions:
            acct.settle(sym, o, f)
            acct.check_closeout(d, {sym: (o, o, o)}, {sym: f})
        _rebalance(acct, d, sym, inst, venue, targets[t - 1], lev, o, f, cfg)
        if venue.kind == "cash" and targets[t - 1] > 0 and sym not in acct.positions:
            waited += 1
        if sym in acct.positions:
            acct.check_stops(d, sym, o, lo, hi, f)
        if sym in acct.positions:
            acct.check_closeout(d, {sym: (o, lo, hi)}, {sym: f})
        if sym in acct.positions:
            acct.settle(sym, c, f)
            in_market += 1
        acct.protect()
        e = acct.equity({sym: c}, {sym: f})
        equity[t] = e
        exposure[t] = acct.notional(sym, c, f) / e if e > 0 else 0.0
        # Deposits land at the open: the old balance owns the night's move,
        # old and new money share the day's. A wipe-out leaves a tiny floor
        # rather than zero, so money deposited after it is still measured.
        prev = equity[t - 1]
        night = v_open / prev if prev > 0.01 else 1.0
        base = v_open + flows[t]
        day = e / base if base > 0.01 else 1.0
        twr[t] = twr[t - 1] * max(TWR_FLOOR, night * day)
    if waited:
        least = venue.min_trade if cfg.min_trade is None else cfg.min_trade
        notes.append(
            f"Buys waited on {waited} trading days: less than ${least:,.0f} was "
            "free to spend, the smallest buy this account makes."
        )
    return RunResult(
        series.dates, equity, flows, exposure, twr, acct, lev, in_market, notes
    )


def _rebalance(
    acct: Account,
    d: str,
    sym: str,
    inst: Instrument,
    venue: Venue,
    target: float,
    lev: float,
    o: float,
    f: float,
    cfg: RunConfig,
) -> None:
    if venue.kind == "cash" or not venue.allow_short:
        target = min(max(target, 0.0), 1.0)
    else:
        target = min(max(target, -1.0), 1.0)
    p = acct.positions.get(sym)
    if abs(target) < 1e-9:
        if p:
            acct.close(d, sym, o, f, "signal")
        return
    if p and (p.units > 0) != (target > 0):
        acct.close(d, sym, o, f, "signal")
    eq = acct.equity({sym: o}, {sym: f})
    if eq <= 0:
        return
    want = target * lev * eq
    have = acct.notional(sym, o, f)
    gap = want - have
    opening = sym not in acct.positions
    if venue.kind == "cash":
        foreign = inst.currency != acct.base
        least = venue.min_trade if cfg.min_trade is None else cfg.min_trade
        if gap > 0 and gap >= least:
            spend = min(gap, acct.cash)
            spend -= venue.brokerage(spend)
            fill = o * (1 + venue.spread_for(inst) / 2) / f
            per_unit = fill * (1 + (venue.fx_fee_pct / 100 if foreign else 0.0))
            units = spend / per_unit if per_unit > 0 else 0.0
            if venue.whole_units:
                units = math.floor(units)
            if units > 0:
                acct.trade(d, sym, units, o, f, "signal")
        elif gap < 0 and have and -gap > cfg.band * abs(have):
            units = gap * f / o
            if venue.whole_units:
                units = -math.floor(-units) if units > 0 else math.ceil(units)
            if units:
                acct.trade(d, sym, units, o, f, "signal")
    elif opening or abs(gap) > cfg.band * abs(want):
        acct.trade(d, sym, gap * f / o, o, f, "signal")
    p = acct.positions.get(sym)
    if p and opening and cfg.stop_pct > 0:
        k = cfg.stop_pct / 100
        p.stop = p.avg_entry * (1 - k) if p.units > 0 else p.avg_entry * (1 + k)
