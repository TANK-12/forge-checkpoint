"""One account's money: cash, positions and every cost, in Australian dollars.

Backtests and paper accounts both move money through this class, so a cost
rule is written once. Prices are in the instrument's own currency; `fx` is
how many units of that currency one Australian dollar buys (AUDUSD for US
assets), so a US price divided by fx is in AUD.

Two kinds of venue:
- "cash": you own the shares. The whole value moves with the exchange rate.
- "cfd": a contract for difference. Only the profit or loss is money; it is
  settled into cash each time the price is marked, and only that profit or
  loss is exposed to the exchange rate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .venues import Instrument, Venue

COST_KINDS = ("spread", "funding", "brokerage", "fx")


@dataclass
class Position:
    symbol: str
    units: float = 0.0
    mark: float = 0.0  # price the profit or loss was last settled at
    mark_value: float = 0.0  # cash venue: AUD value at the last mark
    avg_entry: float = 0.0
    opened: str = ""
    stop: float = 0.0
    take: float = 0.0
    note: str = ""
    pnl: float = 0.0  # market profit or loss (AUD) of the open trade, costs excluded
    costs: float = 0.0  # costs (AUD) charged to the open trade
    realized: float = 0.0  # profit or loss after costs already taken off this trade


@dataclass
class Account:
    venue: Venue
    cash: float = 0.0
    base: str = "AUD"
    positions: dict[str, Position] = field(default_factory=dict)
    instruments: dict[str, Instrument] = field(default_factory=dict)
    costs: dict[str, float] = field(
        default_factory=lambda: {k: 0.0 for k in COST_KINDS}
    )
    interest: float = 0.0
    dividends: float = 0.0  # CFD dividend adjustments on a price index (shorts pay)
    deposited: float = 0.0
    trades: list[dict] = field(default_factory=list)
    round_trips: list[dict] = field(default_factory=list)
    closeouts: int = 0
    stops_hit: int = 0
    protected: float = 0.0  # losses written off by negative balance protection
    rates: dict[str, float] = field(
        default_factory=dict
    )  # today's benchmark %, by currency
    entries: int = 0

    # ---- reading ---------------------------------------------------------

    def value_of(self, sym: str, price: float, fx: float) -> float:
        """What the position adds to equity at `price`."""
        p = self.positions.get(sym)
        if not p or not p.units:
            return 0.0
        if self.venue.kind == "cfd":
            return p.units * (price - p.mark) / fx
        return p.units * price / fx

    def equity(self, prices: dict[str, float], fxs: dict[str, float]) -> float:
        total = self.cash
        for sym in self.positions:
            total += self.value_of(sym, prices[sym], fxs.get(sym, 1.0))
        return total

    def notional(self, sym: str, price: float, fx: float) -> float:
        p = self.positions.get(sym)
        return (p.units * price / fx) if p else 0.0

    def margin_needed(self, prices: dict[str, float], fxs: dict[str, float]) -> float:
        """Initial margin of all open CFD positions (value / leverage cap)."""
        if self.venue.kind != "cfd":
            return 0.0
        total = 0.0
        for sym, p in self.positions.items():
            cap = self.venue.cap(self.instruments[sym].cls)
            total += abs(p.units) * prices[sym] / fxs.get(sym, 1.0) / cap
        return total

    # ---- money in and over time -----------------------------------------

    def deposit(self, amount: float) -> None:
        self.cash += amount
        self.deposited += amount

    def accrue(
        self, days: int, prices: dict[str, float], fxs: dict[str, float]
    ) -> None:
        """Overnight funding on CFD positions, their dividend adjustment on a
        price index, and interest on idle cash, for `days` calendar nights
        (a weekend is three)."""
        if days <= 0:
            return
        for sym, p in self.positions.items():
            if not p.units:
                continue
            inst = self.instruments[sym]
            value = abs(p.units) * prices[sym] / fxs.get(sym, 1.0)
            rate = self.venue.funding_rate(
                inst.currency,
                1 if p.units > 0 else -1,
                self.rates.get(inst.currency),
                inst.base,
                self.rates.get(inst.base),
            )
            if rate:
                cost = value * rate * days / 365
                self.cash -= cost
                self.costs["funding"] += cost
                p.costs += cost
            if self.venue.kind == "cfd" and inst.dividend_yield_pct:
                paid = value * inst.dividend_yield_pct / 100 * days / 365
                paid = paid if p.units > 0 else -paid
                self.cash += paid
                self.dividends += paid
                p.pnl += paid
        pct = self.venue.cash_interest_pct
        follows = self.venue.cash_interest_follows
        if follows and follows in self.rates:
            pct = self.rates[follows]
        if self.cash > 0 and pct:
            earned = self.cash * pct / 100 * days / 365
            self.cash += earned
            self.interest += earned

    def settle(self, sym: str, price: float, fx: float) -> None:
        """Bring the position's profit or loss up to `price`."""
        p = self.positions.get(sym)
        if not p:
            return
        if self.venue.kind == "cfd":
            move = p.units * (price - p.mark) / fx
            self.cash += move
            p.pnl += move
        else:
            value = p.units * price / fx
            p.pnl += value - p.mark_value
            p.mark_value = value
        p.mark = price

    # ---- trading ---------------------------------------------------------

    def trade(
        self,
        date: str,
        sym: str,
        units: float,
        mid: float,
        fx: float,
        reason: str = "signal",
        exact_fill: float | None = None,
    ) -> dict | None:
        """Buy (units > 0) or sell (units < 0) at `mid` plus half the spread,
        or at `exact_fill` (a stop or close-out level, spread on top)."""
        if not units or mid <= 0:
            return None
        inst = self.instruments[sym]
        half = self.venue.spread_for(inst) / 2
        ref = exact_fill if exact_fill is not None else mid
        fill = ref * (1 + half) if units > 0 else ref * (1 - half)
        p = self.positions.get(sym)
        if p is None:
            p = Position(sym, mark=ref)
            p.mark_value = 0.0
            self.positions[sym] = p
        self.settle(sym, ref, fx)
        old = p.units
        spread_cost = abs(units) * ref * half / fx
        brokerage = fx_fee = 0.0
        foreign = inst.currency != self.base
        if self.venue.kind == "cfd":
            self.cash -= spread_cost
        else:
            brokerage = self.venue.brokerage(abs(units) * ref / fx)
            fx_fee = (
                abs(units) * ref / fx * self.venue.fx_fee_pct / 100 if foreign else 0.0
            )
            self.cash -= units * fill / fx + brokerage + fx_fee
            p.mark_value += units * ref / fx
        self.costs["spread"] += spread_cost
        self.costs["brokerage"] += brokerage
        self.costs["fx"] += fx_fee
        p.costs += spread_cost + brokerage + fx_fee
        trade_cost = spread_cost + brokerage + fx_fee

        new = old + units
        closing = 0.0
        if old and (old > 0) != (units > 0):
            closing = min(abs(units), abs(old))
        if closing:
            share = closing / abs(old)
            gained = p.pnl * share
            charged = p.costs * share
            if self.venue.kind == "cfd" and foreign and self.venue.fx_fee_pct:
                fee = abs(gained) * self.venue.fx_fee_pct / 100
                self.cash -= fee
                self.costs["fx"] += fee
                charged += fee
                trade_cost += fee
            p.realized += gained - charged
            p.pnl -= gained
            p.costs -= p.costs * share
        if abs(new) < 1e-12 or (old and new and (old > 0) != (new > 0)):
            self._finish_trip(date, p)
        if abs(new) < 1e-12:
            del self.positions[sym]
        else:
            if not old or (old > 0) != (new > 0):
                self.entries += 1
                p.opened = date
                p.avg_entry = ref
                p.pnl = p.costs = p.realized = 0.0
                if self.venue.kind == "cash":
                    p.mark_value = new * ref / fx
                p.costs += 0.0 if closing else trade_cost
            elif not closing:
                p.avg_entry = (p.avg_entry * abs(old) + ref * abs(units)) / abs(new)
            p.units = new
        rec = {
            "date": date,
            "symbol": sym,
            "side": "buy" if units > 0 else "sell",
            "units": round(units, 6),
            "price": round(fill, 6),
            "value": round(abs(units) * fill / fx, 2),
            "cost": round(trade_cost, 2),
            "reason": reason,
        }
        self.trades.append(rec)
        return rec

    def _finish_trip(self, date: str, p: Position) -> None:
        self.round_trips.append(
            {
                "symbol": p.symbol,
                "opened": p.opened,
                "closed": date,
                "result": round(p.realized, 2),
                "side": "long" if p.units > 0 else "short",
            }
        )
        p.realized = 0.0

    def close(
        self,
        date: str,
        sym: str,
        price: float,
        fx: float,
        reason: str,
        exact: bool = False,
    ) -> dict | None:
        p = self.positions.get(sym)
        if not p:
            return None
        return self.trade(
            date, sym, -p.units, price, fx, reason, exact_fill=price if exact else None
        )

    # ---- protection rules --------------------------------------------------

    def check_stops(
        self, date: str, sym: str, open_: float, low: float, high: float, fx: float
    ) -> bool:
        """Stop-loss and take-profit on the day's range. A gap through the
        level fills at the open, which is worse, as in real markets."""
        p = self.positions.get(sym)
        if not p or not (p.stop or p.take):
            return False
        long = p.units > 0
        level = 0.0
        reason = ""
        if p.stop and ((long and low <= p.stop) or (not long and high >= p.stop)):
            co = self.closeout_price(sym, fx)
            if co is not None and (
                (long and p.stop < co and low <= co)
                or (not long and p.stop > co and high >= co)
            ):
                return False  # the margin close-out bites first on the way
            gapped = (long and open_ <= p.stop) or (not long and open_ >= p.stop)
            level = open_ if gapped else p.stop
            reason = "stop"
        elif p.take and ((long and high >= p.take) or (not long and low <= p.take)):
            gapped = (long and open_ >= p.take) or (not long and open_ <= p.take)
            level = open_ if gapped else p.take
            reason = "take profit"
        if not level:
            return False
        self.close(date, sym, level, fx, reason, exact=True)
        self.stops_hit += 1
        return True

    def closeout_price(self, sym: str, fx: float) -> float | None:
        """With one CFD position, the price where the margin close-out
        bites (equity = the venue's share of the initial margin); None for
        a share account, several positions or no such price."""
        if self.venue.kind != "cfd" or list(self.positions) != [sym]:
            return None
        p = self.positions[sym]
        c = self.venue.margin_closeout
        cap = self.venue.cap(self.instruments[sym].cls)
        u = p.units
        base = self.cash * fx + (-u * p.mark)
        k = (1 - c / cap) if u > 0 else (1 + c / cap)
        if not u * k:
            return None
        level = -base / (u * k)
        return level if math.isfinite(level) else None

    def check_closeout(
        self,
        date: str,
        bars: dict[str, tuple[float, float, float]],
        fxs: dict[str, float],
    ) -> bool:
        """The ASIC margin close-out: when equity falls below the venue's
        share (50%) of the initial margin, positions are closed. `bars` holds
        (open, low, high) per symbol. With one position the close happens at
        the exact price where the rule bites; with several, every position is
        closed at its worst price of the day (cautious)."""
        if self.venue.kind != "cfd" or not self.positions:
            return False
        c = self.venue.margin_closeout
        worst = {}
        for sym, p in self.positions.items():
            o, lo, hi = bars[sym]
            worst[sym] = lo if p.units > 0 else hi
        eq = self.equity(worst, fxs)
        need = self.margin_needed(worst, fxs)
        if not need or eq >= c * need:
            return False
        self.closeouts += 1
        if len(self.positions) == 1:
            sym, p = next(iter(self.positions.items()))
            o, lo, hi = bars[sym]
            fx = fxs.get(sym, 1.0)
            cap = self.venue.cap(self.instruments[sym].cls)
            level = self.closeout_price(sym, fx)
            if level is None:
                level = o
            eq_open = self.equity({sym: o}, fxs)
            need_open = self.margin_needed({sym: o}, fxs)
            if eq_open < c * need_open or not math.isfinite(level):
                level = o
            level = min(max(level, lo), hi)
            self.close(date, sym, level, fx, "margin close-out", exact=True)
        else:
            for sym in list(self.positions):
                self.close(
                    date,
                    sym,
                    worst[sym],
                    fxs.get(sym, 1.0),
                    "margin close-out",
                    exact=True,
                )
        self.protect()
        return True

    def protect(self) -> None:
        """Negative balance protection: with no positions left, a debt is
        written off rather than owed."""
        if (
            self.venue.negative_balance_protection
            and not self.positions
            and self.cash < 0
        ):
            self.protected += -self.cash
            self.cash = 0.0
