"""Cost models for where a trade happens, read from venues.json and
symbols.json. Adding a venue or a market is one entry in a JSON file."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class Venue:
    id: str
    label: str
    kind: str  # "cfd" (leveraged contracts) or "cash" (you own the shares)
    summary: str = ""
    allow_short: bool = False
    leverage_caps: dict[str, float] = field(default_factory=dict)
    spread_pct: dict[str, float] = field(default_factory=dict)
    funding_markup_pct: float = 0.0
    benchmark_rate_pct: dict[str, float] = field(default_factory=dict)
    benchmark_history: dict[str, str] = field(
        default_factory=dict
    )  # currency -> series
    fx_fee_pct: float = 0.0
    brokerage_flat: float = 0.0
    brokerage_pct: float = 0.0
    min_trade: float = 0.0
    cash_interest_pct: float = 0.0
    cash_interest_follows: str = ""  # a currency: idle cash earns its benchmark rate
    margin_closeout: float = 0.5
    negative_balance_protection: bool = True
    whole_units: bool = False
    tradeable: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)

    def spread(self, cls: str) -> float:
        """Full bid-ask spread as a fraction of the price."""
        pct = self.spread_pct.get(cls, self.spread_pct.get("default", 0.0))
        return pct / 100.0

    def spread_for(self, inst: "Instrument") -> float:
        """The market's own spread on this venue when symbols.json gives one,
        else the venue's figure for its class."""
        pct = inst.spread_pct.get(self.id)
        return self.spread(inst.cls) if pct is None else pct / 100.0

    def cap(self, cls: str) -> float:
        """Most leverage a retail client may use on this class."""
        if self.kind != "cfd":
            return 1.0
        return float(self.leverage_caps.get(cls, self.leverage_caps.get("default", 1)))

    def bench_pct(self, currency: str) -> float:
        return self.benchmark_rate_pct.get(
            currency, self.benchmark_rate_pct.get("default", 0.0)
        )

    def funding_rate(
        self,
        currency: str,
        direction: int,
        bench: float | None = None,
        base: str = "",
        base_bench: float | None = None,
    ) -> float:
        """Yearly overnight cost on the position's value, as a fraction.
        Long pays the benchmark rate plus the markup; short pays the markup
        minus the benchmark rate (a negative number is money received). A
        currency pair (`base` set, AUD in AUD/USD) pays on the gap between
        its two rates instead: a long holds the base currency and owes the
        quote one, so it pays the markup plus the quote rate minus the base
        rate, and a short the other way round. `bench` and `base_bench` are
        the day's rates from history; the fixed figures otherwise."""
        if self.kind != "cfd" or direction == 0:
            return 0.0
        bench = self.bench_pct(currency) if bench is None else bench
        markup = self.funding_markup_pct
        if base:
            base_bench = self.bench_pct(base) if base_bench is None else base_bench
            gap = bench - base_bench
            pct = markup + gap if direction > 0 else markup - gap
        else:
            pct = bench + markup if direction > 0 else markup - bench
        return pct / 100.0

    def brokerage(self, value: float) -> float:
        if self.kind != "cash" or value <= 0:
            return 0.0
        return max(self.brokerage_flat, value * self.brokerage_pct / 100.0)

    def can_trade(self, kind: str) -> bool:
        return not self.tradeable or kind in self.tradeable


@dataclass
class Instrument:
    symbol: str
    name: str
    cls: str  # cost and leverage class, e.g. "index_major"
    kind: str  # "index", "etf", "share", "fx", "commodity", "crypto"
    currency: str = "AUD"
    benchmark: str = ""
    blurb: str = ""
    spread_pct: dict[str, float] = field(default_factory=dict)  # by venue id
    fee_pct: float = 0.0  # fund fee a year, already inside an ETF's price
    dividend_yield_pct: float = 0.0  # price index: what a CFD long is credited a year
    warning: str = ""
    base: str = ""  # currency pairs only: the currency a long holds (AUD in AUD/USD)


def _load(name: str) -> dict:
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return json.load(f)


def load_venues() -> dict[str, Venue]:
    data = _load("venues.json")
    out: dict[str, Venue] = {}
    for vid, v in data["venues"].items():
        known = {k: v[k] for k in v if k in Venue.__dataclass_fields__}
        out[vid] = Venue(id=vid, **known)
    return out


def load_instruments() -> dict[str, Instrument]:
    data = _load("symbols.json")
    out: dict[str, Instrument] = {}
    for s in data["symbols"]:
        known = {k: s[k] for k in s if k in Instrument.__dataclass_fields__}
        out[s["symbol"]] = Instrument(**known)
    return out


def exchange_suffixes() -> list[str]:
    """Exchanges (Yahoo's suffix: AX, L, TO) a share or fund missing from the
    registry may come from; a ticker with no suffix is a US listing."""
    return [str(x) for x in _load("symbols.json").get("exchange_suffixes", [])]


def instrument_for(symbol: str, instruments: dict[str, Instrument]) -> Instrument:
    """The registry entry, or a plain guess for an imported symbol."""
    if symbol in instruments:
        return instruments[symbol]
    if symbol.endswith(".AX"):
        return Instrument(symbol, symbol, "share", "share", "AUD", "VAS.AX")
    return Instrument(symbol, symbol, "share", "share", "AUD", "")
