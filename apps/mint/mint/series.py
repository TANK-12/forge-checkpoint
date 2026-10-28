"""Daily price series: the one shape every part of Mint reads."""

from __future__ import annotations

import bisect
import datetime as dt
import math
import random
from dataclasses import dataclass, field


@dataclass
class Series:
    """Daily bars, oldest first. Prices are adjusted for dividends and splits
    when `adjusted` is true, so buy-and-hold on the close is a total return."""

    symbol: str
    dates: list[str]
    open: list[float]
    high: list[float]
    low: list[float]
    close: list[float]
    currency: str = "AUD"
    source: str = "yahoo"
    adjusted: bool = True
    name: str = ""
    notes: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.dates)

    def slice(self, a: int, b: int) -> "Series":
        """Bars a..b-1, like a list slice."""
        return Series(
            self.symbol,
            self.dates[a:b],
            self.open[a:b],
            self.high[a:b],
            self.low[a:b],
            self.close[a:b],
            self.currency,
            self.source,
            self.adjusted,
            self.name,
            list(self.notes),
        )

    def index_on_or_after(self, date: str) -> int:
        """First bar on or after `date` (len(self) when there is none)."""
        return bisect.bisect_left(self.dates, date)

    def window(self, start: str = "", end: str = "") -> "Series":
        a = self.index_on_or_after(start) if start else 0
        b = bisect.bisect_right(self.dates, end) if end else len(self)
        return self.slice(a, b)


def days_between(a: str, b: str) -> int:
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def align(series: Series, other: Series | None) -> list[float]:
    """`other`'s close on each of `series`' dates, carried forward over gaps
    (and back-filled before its first bar). All ones when there is no other."""
    if other is None or not len(other):
        return [1.0] * len(series)
    out: list[float] = []
    j = 0
    last = other.close[0]
    for d in series.dates:
        while j < len(other) and other.dates[j] <= d:
            last = other.close[j]
            j += 1
        out.append(last)
    return out


def made_up(
    symbol: str = "MADE-UP",
    n: int = 2520,
    start: str = "2016-01-04",
    drift: float = 0.07,
    vol: float = 0.16,
    seed: int = 7,
    price: float = 100.0,
) -> Series:
    """A seeded random walk on weekdays, for tests and the offline demo.
    Always labelled as made up wherever it is shown."""
    rng = random.Random(seed)
    day = dt.date.fromisoformat(start)
    mu = (drift - vol * vol / 2) / 252
    sd = vol / math.sqrt(252)
    dates: list[str] = []
    o: list[float] = []
    h: list[float] = []
    lo: list[float] = []
    c: list[float] = []
    prev = price
    while len(dates) < n:
        if day.weekday() < 5:
            gap = rng.gauss(0, sd * 0.3)
            open_ = prev * math.exp(gap)
            close = prev * math.exp(mu + rng.gauss(0, sd))
            span = abs(rng.gauss(0, sd * 0.6))
            dates.append(day.isoformat())
            o.append(open_)
            c.append(close)
            h.append(max(open_, close) * math.exp(span))
            lo.append(min(open_, close) * math.exp(-span))
            prev = close
        day += dt.timedelta(days=1)
    return Series(
        symbol,
        dates,
        o,
        h,
        lo,
        c,
        source="made-up",
        name="Made-up prices (random walk)",
        notes=["Made-up prices from a random walk, not a real market."],
    )
