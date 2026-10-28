"""Prices: Yahoo Finance's public chart feed (no key), cached on disk, plus
CSV import for anything else. The feed is unofficial and delayed; a
fetch failure falls back to the cache."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
import os
import tempfile
import time
import urllib.parse
import urllib.request
import zoneinfo

from .series import Series, align

YAHOO = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
    "?period1={p1}&period2={p2}&interval=1d&events=div%2Csplits"
    "&includeAdjustedClose=true"
)
AGENT = "Mozilla/5.0 (X11; Linux x86_64) Forge-Mint/1.0"
RBA_A2 = "https://www.rba.gov.au/statistics/tables/csv/a2-data.csv"
# A one-day move bigger than this (as a log return) is read as broken data,
# such as a split the feed never adjusted for, unless the market really moves
# like that. IVV.AX on Yahoo falls 93% on 2011-01-04, which never happened.
BREAK_LOG = {"crypto": 0.7, "default": 0.4}


# Where Mint fetches prices itself. "csv" (a file) and "made-up" are not
# real prices, so nothing that can pass the Ready? checklist may use them.
LIVE_SOURCES = ("yahoo", "rba")


class PriceError(RuntimeError):
    pass


def parse_yahoo(payload: dict, now: float | None = None) -> tuple[Series, dict]:
    """A chart API answer -> adjusted daily Series plus facts about it.
    Dates are the exchange's own calendar days. A bar for a day still
    trading is dropped, so nothing acts on a price that is not final."""
    chart = payload.get("chart") or {}
    if chart.get("error") or not chart.get("result"):
        raise PriceError(str(chart.get("error") or "no data in the answer"))
    r = chart["result"][0]
    meta = r.get("meta", {})
    zone = _zone(meta.get("exchangeTimezoneName", ""), int(meta.get("gmtoffset", 0)))
    stamps = r.get("timestamp") or []
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    adj = ((r.get("indicators", {}).get("adjclose") or [{}])[0]).get("adjclose")
    dates: list[str] = []
    o: list[float] = []
    h: list[float] = []
    lo: list[float] = []
    c: list[float] = []
    for i, ts in enumerate(stamps):
        vals = [
            q.get(k, [None] * len(stamps))[i] for k in ("open", "high", "low", "close")
        ]
        if any(v is None or v <= 0 for v in vals):
            continue
        open_, high, low, close = (float(v) for v in vals)
        factor = 1.0
        if adj and i < len(adj) and adj[i]:
            factor = float(adj[i]) / close
        day = dt.datetime.fromtimestamp(ts, zone).date().isoformat()
        if dates and dates[-1] == day:
            for col in (dates, o, h, lo, c):
                col.pop()
        dates.append(day)
        o.append(open_ * factor)
        h.append(max(high, open_, close) * factor)
        lo.append(min(low, open_, close) * factor)
        c.append(close * factor)
    now = time.time() if now is None else now
    period = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    end = period.get("end")
    today = dt.datetime.fromtimestamp(now, zone).date().isoformat()
    partial = bool(dates) and dates[-1] == today and end is not None and now < end
    if partial:
        for col in (dates, o, h, lo, c):
            col.pop()
    sym = meta.get("symbol", "")
    series = Series(
        sym,
        dates,
        o,
        h,
        lo,
        c,
        currency=meta.get("currency") or "AUD",
        source="yahoo",
        adjusted=bool(adj),
        name=meta.get("longName") or meta.get("shortName") or sym,
    )
    facts = {
        "symbol": sym,
        "name": series.name,
        "currency": series.currency,
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName", ""),
        "timezone": meta.get("exchangeTimezoneName", ""),
        "last_price": meta.get("regularMarketPrice"),
        "last_price_time": meta.get("regularMarketTime"),
        "dropped_unfinished_day": partial,
        "adjusted": bool(adj),
    }
    return series, facts


def _zone(name: str, offset: int) -> dt.tzinfo:
    """The exchange's own time zone, so each bar gets its local trading day
    with the daylight-saving rule of that date; the feed's current offset
    only when the zone is unknown."""
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return dt.timezone(dt.timedelta(seconds=offset))


def fetch_yahoo(symbol: str, timeout: float = 25.0) -> tuple[Series, dict]:
    url = YAHOO.format(
        sym=urllib.parse.quote(symbol, safe=""), p1=0, p2=int(time.time()) + 86400
    )
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except Exception as exc:  # network, HTTP or JSON trouble: the caller falls back
        raise PriceError(f"could not fetch {symbol}: {exc}") from exc
    return parse_yahoo(payload)


def parse_rba_a2(text: str) -> Series:
    """RBA table A2 (every cash rate target change) as a step series of the
    rate in per cent. Early rows give a range ("17.00 to 17.50"): the middle
    is used."""
    points: dict[str, float] = {}
    for row in csv.reader(io.StringIO(text.lstrip("\ufeff"))):
        if len(row) < 3:
            continue
        try:
            day = dt.datetime.strptime(row[0].strip(), "%d-%b-%Y").date().isoformat()
            parts = [float(x) for x in row[2].replace("to", " ").split()]
        except ValueError:
            continue
        if parts:
            points[day] = sum(parts) / len(parts)
    days = sorted(points)
    if not days:
        raise PriceError("no cash rate rows in the RBA table")
    rates = [points[d] for d in days]
    return Series(
        "rba-cash",
        days,
        rates,
        rates,
        rates,
        rates,
        currency="AUD",
        source="rba",
        adjusted=False,
        name="RBA cash rate target (per cent)",
    )


def fetch_rba_cash(timeout: float = 25.0) -> tuple[Series, dict]:
    req = urllib.request.Request(RBA_A2, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
    except Exception as exc:  # network trouble: the caller falls back
        raise PriceError(f"could not fetch the RBA cash rate: {exc}") from exc
    series = parse_rba_a2(text)
    return series, {"exchange": "RBA table A2", "url": RBA_A2}


def breaks(series: Series, kind: str = "") -> list[tuple[str, float]]:
    """Days whose close moved more than a market of this kind plausibly can
    in one day: (date, move as a fraction)."""
    limit = BREAK_LOG.get(kind, BREAK_LOG["default"])
    c = series.close
    return [
        (series.dates[i], c[i] / c[i - 1] - 1)
        for i in range(1, len(c))
        if c[i - 1] > 0 and c[i] > 0 and abs(math.log(c[i] / c[i - 1])) > limit
    ]


def after_breaks(series: Series, kind: str = "") -> tuple[Series, list[str]]:
    """The prices after the last broken day, with a note saying what was
    left out and why."""
    found = breaks(series, kind)
    if not found:
        return series, []
    day, move = found[-1]
    cut = series.index_on_or_after(day)
    note = (
        f"{series.symbol}: prices before {day} were left out. The feed shows a "
        f"one-day move of {move * 100:+.0f}% there, which looks like broken "
        "data (often a split it never adjusted for)."
    )
    return series.slice(cut, len(series)), [note]


def parse_csv(symbol: str, text: str, currency: str = "AUD", name: str = "") -> Series:
    """Date, Open, High, Low, Close and optional Adj Close columns, any
    order and case. Dates as YYYY-MM-DD or DD/MM/YYYY."""
    rows = list(csv.reader(io.StringIO(text.strip())))
    if len(rows) < 3:
        raise PriceError("the file needs a header row and at least two days")
    head = [x.strip().lower().replace("_", " ") for x in rows[0]]

    def col(*names: str) -> int | None:
        for n in names:
            if n in head:
                return head.index(n)
        return None

    i_date, i_close = col("date"), col("close", "price")
    if i_date is None or i_close is None:
        raise PriceError("the file needs at least Date and Close columns")
    i_open, i_high, i_low = col("open"), col("high"), col("low")
    i_adj = col("adj close", "adjusted close", "adjclose")
    bars: dict[str, tuple[float, float, float, float]] = {}
    for row in rows[1:]:
        try:
            day = _date(row[i_date])
            close = float(row[i_close])
            open_ = float(row[i_open]) if i_open is not None else close
            high = float(row[i_high]) if i_high is not None else max(open_, close)
            low = float(row[i_low]) if i_low is not None else min(open_, close)
            factor = float(row[i_adj]) / close if i_adj is not None else 1.0
        except (ValueError, IndexError, ZeroDivisionError):
            continue
        if close <= 0 or open_ <= 0:
            continue
        bars[day] = (
            open_ * factor,
            max(high, open_, close) * factor,
            min(low, open_, close) * factor,
            close * factor,
        )
    days = sorted(bars)
    if len(days) < 2:
        raise PriceError("fewer than two readable days in the file")
    return Series(
        symbol,
        days,
        [bars[d][0] for d in days],
        [bars[d][1] for d in days],
        [bars[d][2] for d in days],
        [bars[d][3] for d in days],
        currency=currency,
        source="csv",
        adjusted=i_adj is not None,
        name=name or symbol,
    )


def _date(text: str) -> str:
    text = text.strip()
    if "/" in text:
        d, m, y = text.split("/")
        return dt.date(int(y), int(m), int(d)).isoformat()
    return dt.date.fromisoformat(text[:10]).isoformat()


def default_root() -> str:
    """Where Mint keeps its prices and paper accounts."""
    return os.environ.get("MINT_DATA_DIR") or os.path.expanduser(
        "~/.local/share/forge/mint"
    )


class PriceStore:
    """On-disk cache: prices/<symbol>.csv plus prices/<symbol>.json."""

    def __init__(self, root: str, fetcher=fetch_yahoo):
        self.dir = os.path.join(root, "prices")
        os.makedirs(self.dir, exist_ok=True)
        self.fetcher = fetcher
        # Series that do not come from Yahoo, by the name venues.json uses.
        self.fetchers = {"rba-cash": fetch_rba_cash}

    def _base(self, symbol: str) -> str:
        return os.path.join(self.dir, urllib.parse.quote(symbol, safe=""))

    def symbols(self) -> list[str]:
        """Every symbol with saved facts, as it was saved."""
        return sorted(
            urllib.parse.unquote(f[:-5])
            for f in os.listdir(self.dir)
            if f.endswith(".json")
        )

    def facts(self, symbol: str) -> dict:
        try:
            with open(self._base(symbol) + ".json", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def cached(self, symbol: str) -> Series | None:
        facts = self.facts(symbol)
        try:
            with open(self._base(symbol) + ".csv", encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
        except OSError:
            return None
        # blank rows: a cache Windows wrote with doubled line ends (\r\r\n)
        rows = [r for r in rows[1:] if len(r) >= 5]
        if not rows:
            return None
        return Series(
            symbol,
            [r[0] for r in rows],
            [float(r[1]) for r in rows],
            [float(r[2]) for r in rows],
            [float(r[3]) for r in rows],
            [float(r[4]) for r in rows],
            currency=facts.get("currency", "AUD"),
            source=facts.get("source", "yahoo"),
            adjusted=facts.get("adjusted", True),
            name=facts.get("name", symbol),
        )

    def save(self, series: Series, facts: dict) -> None:
        base = self._base(series.symbol)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "open", "high", "low", "close"])
        for i, d in enumerate(series.dates):
            w.writerow(
                [d]
                + [
                    f"{x[i]:.6f}"
                    for x in (series.open, series.high, series.low, series.close)
                ]
            )
        _write(base + ".csv", buf.getvalue())
        info = dict(facts)
        info.update(
            {
                "symbol": series.symbol,
                "name": series.name,
                "currency": series.currency,
                "source": series.source,
                "adjusted": series.adjusted,
                "first": series.dates[0] if series.dates else "",
                "last": series.dates[-1] if series.dates else "",
                "bars": len(series),
                "fetched_at": time.time(),
            }
        )
        _write(base + ".json", json.dumps(info, indent=1))

    def get(
        self, symbol: str, refresh: bool = False, max_age_hours: float = 6
    ) -> Series:
        """Cached prices, fetched again when older than max_age_hours (or on
        refresh). A failed fetch keeps the cache and notes why."""
        series = self.cached(symbol)
        facts = self.facts(symbol)
        fresh = time.time() - facts.get("fetched_at", 0) < max_age_hours * 3600
        if series is not None and (
            fresh and not refresh or facts.get("source") == "csv"
        ):
            return series
        try:
            fetch = self.fetchers.get(symbol)
            new, new_facts = fetch() if fetch else self.fetcher(symbol)
        except PriceError as exc:
            if series is None:
                raise
            series.notes.append(f"Using saved prices: {exc}")
            return series
        if len(new) < 2:
            if series is None:
                raise PriceError(f"no daily prices for {symbol}")
            return series
        self.save(new, new_facts)
        return new

    def import_csv(
        self,
        symbol: str,
        text: str,
        currency: str = "AUD",
        name: str = "",
        today: str | None = None,
    ) -> Series:
        """Prices from a file. Days after today are dropped: a file must
        never hand a paper account days that have not happened."""
        series = parse_csv(symbol, text, currency, name)
        series = series.window("", today or dt.date.today().isoformat())
        if len(series) < 2:
            raise PriceError("fewer than two days up to today in the file")
        self.save(series, {"imported": True})
        return series

    def fx_for(
        self, series: Series, base: str = "AUD"
    ) -> tuple[list[float], list[str]]:
        """Units of the series' currency one AUD buys, on each of its days."""
        if series.currency == base:
            return [1.0] * len(series), []
        pair = f"{base}{series.currency}=X"
        try:
            other = self.get(pair)
        except PriceError:
            return [1.0] * len(series), [
                f"No {pair} exchange rates, so {series.currency} amounts were not converted."
            ]
        return align(series, other), []

    def rates_for(
        self, series: Series, sources: dict[str, str], currencies: list[str]
    ) -> tuple[dict[str, list[float]], list[str]]:
        """The benchmark rate (per cent) of each currency on each of the
        series' days, from the history named in venues.json. A currency with
        no history is left out, so the venue's fixed figure is used."""
        out: dict[str, list[float]] = {}
        notes: list[str] = []
        for cur in dict.fromkeys(currencies):
            src = sources.get(cur)
            if not src:
                continue
            try:
                hist = self.get(src)
            except PriceError:
                notes.append(f"No {cur} rate history, so a fixed rate was used.")
                continue
            out[cur] = align(series, hist)
        return out, notes


def _write(path: str, text: str) -> None:
    """Write whole or not at all: a temp file of its own in the same folder,
    then one rename, so two writers never share a half-written file."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".part")
    try:
        # newline="": the text as given, so csv's \r\n stays one line end
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)  # only ever the temp file made just above
        raise
