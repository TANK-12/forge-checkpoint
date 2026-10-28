"""Paper accounts: fake money on real prices, forward only.

An account is its settings plus a list of orders, kept as JSON in
<data>/paper/<id>.json. Its state is never stored: every look replays the
engine from the account's first day on the prices known now, so a bot steps
on new bars by itself and nothing can drift. The rules that keep the record
honest:

- Day one is the last trading day on or before the day the account was made;
  the first trade can only fill at the open of a later day.
- A manual order made on a calendar day (the exchange's own) fills at the
  open of the first trading day after it, never on a day already seen.
- A bot's strategy and settings are frozen when it is made. To try other
  settings, archive it and start a new one.
- Nothing is deleted. Archived accounts stop on the day they were archived
  and stay listed, so the number of tries stays visible.
- No date in a file comes before the account was made or after tomorrow. An
  order or archive the clock puts before the account (a refresh that lost
  the market's time zone falls back to UTC) takes the account's own day.
"""

from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import os
import re
import secrets
import threading
import time
from collections.abc import Container
from zoneinfo import ZoneInfo

from . import data, luck, stats, strategies
from .engine import RunConfig, run
from .lab import DEFAULT_BENCHMARK, MADE_UP, Lab, LabError, curve

MAX_ACCOUNTS = 200
MAX_ORDERS = 2000
ID_RE = re.compile(r"[A-Za-z0-9-]{1,64}")
DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
CONFIG_KEYS = ("start_cash", "deposit", "deposit_every_days", "leverage", "stop_pct")
# Every change to an account reads its file, changes it and writes it back;
# one lock stops two at once (two clicks, two tabs) from losing either.
_LOCK = threading.RLock()


class PaperError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Paper:
    def __init__(self, lab: Lab, root: str | None = None):
        self.lab = lab
        self.dir = os.path.join(root or data.default_root(), "paper")
        os.makedirs(self.dir, exist_ok=True)

    # ---- files -----------------------------------------------------------------

    def _path(self, pid: str) -> str:
        if not isinstance(pid, str) or not ID_RE.fullmatch(pid):
            raise PaperError("No such paper account.", 404)
        return os.path.join(self.dir, pid + ".json")

    def load(self, pid: str) -> dict:
        path = self._path(pid)
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except FileNotFoundError:
            raise PaperError("No such paper account.", 404) from None
        except (OSError, ValueError, RecursionError) as exc:  # "[[[[..." recurses
            raise PaperError(f"That account's file is damaged: {exc}", 409) from exc
        try:
            problem = damaged(doc, pid, self.lab.venues)
        except Exception as exc:  # whatever a hand edit holds: a 409, never a 500
            problem = f"it could not be checked ({type(exc).__name__})"
        if problem:
            raise PaperError(f"That account's file is damaged: {problem}.", 409)
        return doc

    def save(self, acct: dict) -> None:
        data._write(self._path(acct["id"]), json.dumps(acct, indent=1))

    def ids(self) -> list[str]:
        return sorted(f[:-5] for f in os.listdir(self.dir) if f.endswith(".json"))

    def rank(self, acct: dict) -> int:
        """The account's place in the order paper accounts were made, archived
        ones too: 1 for the first. Its luck bar is fixed by it (ready.luck_alpha)
        and accounts made later never move it. A file that cannot be read
        counts as made earlier: it may have been any idea."""
        mine = (acct["created_at"], acct["id"])
        earlier = 0
        for pid in self.ids():
            if pid == acct["id"]:
                continue
            try:
                doc = self.load(pid)
            except PaperError:
                earlier += 1
                continue
            earlier += (doc["created_at"], doc["id"]) < mine
        return 1 + earlier

    # ---- changes ---------------------------------------------------------------

    def create(self, body: dict, today: str | None = None) -> dict:
        with _LOCK:
            return self._create(body, today)

    def _create(self, body: dict, today: str | None) -> dict:
        if len(self.ids()) >= MAX_ACCOUNTS:
            raise PaperError(f"{MAX_ACCOUNTS} paper accounts is the limit.")
        kind = body.get("kind", "manual")
        if kind not in ("manual", "bot"):
            raise PaperError("An account is manual or a bot.")
        symbol = str(body.get("symbol", "")).strip()
        if not symbol or symbol.upper() == MADE_UP:
            raise PaperError(
                "Pick a real market: paper accounts run on real prices only."
            )
        venue_id = body.get("venue", "cash")
        venue = self.lab.venues.get(venue_id)
        if venue is None:
            raise PaperError(f"No venue called {venue_id}.")
        try:
            full, inst, _ = self.lab.history(symbol)
        except LabError as exc:
            raise PaperError(str(exc)) from exc
        symbol = inst.symbol  # Mint's own spelling: vas.ax is saved as VAS.AX
        if full.source not in data.LIVE_SOURCES:
            raise PaperError(
                "Paper accounts run on prices Mint fetches itself: prices from "
                "a file could say anything."
            )
        if not venue.can_trade(inst.kind):
            raise PaperError(f"A {venue.label} cannot trade {inst.name}.")
        cfg = _config(body)
        acct = {
            "id": "",
            "name": str(body.get("name") or "").strip()[:60],
            "kind": kind,
            "symbol": symbol,
            "venue": venue_id,
            "config": cfg,
            "created": today or self.today(symbol),
            "created_at": time.time() if today is None else _midnight(today),
            "orders": [],
            "archived": "",
        }
        if kind == "bot":
            mods = strategies.load()
            sid = body.get("strategy", "")
            if sid not in mods:
                raise PaperError(f"No strategy called {sid}.")
            acct["strategy"] = sid
            acct["params"] = strategies.params_for(mods[sid].META, body.get("params"))
            problem = strategies.order_problem(mods[sid].META, acct["params"])
            if problem:
                raise PaperError(problem)
            acct["name"] = acct["name"] or f"{mods[sid].META['name']} on {symbol}"
        else:
            acct["name"] = acct["name"] or f"My trades on {symbol}"
        if full.dates and full.dates[0] > acct["created"]:
            raise PaperError("Prices for that market start after today.")
        acct["id"] = acct["created"].replace("-", "") + "-" + secrets.token_hex(3)
        self.save(acct)
        return acct

    def order(self, pid: str, target: float, today: str | None = None) -> dict:
        with _LOCK:
            return self._order(pid, target, today)

    def _order(self, pid: str, target: float, today: str | None) -> dict:
        acct = self.load(pid)
        if acct.get("archived"):
            raise PaperError("This account is archived.", 409)
        if acct["kind"] == "bot":
            raise PaperError(
                "A bot's settings are frozen so its record stays honest. Archive "
                "it and start a new one to try something else.",
                409,
            )
        venue = self.lab.venues[acct["venue"]]
        lo = -1.0 if venue.allow_short else 0.0
        try:
            target = float(target)
        except (TypeError, ValueError, OverflowError):
            raise PaperError("The order needs a number from -1 to 1.") from None
        if not lo <= target <= 1:
            raise PaperError(
                "Shorting is not allowed here: pick 0 to 1."
                if lo == 0
                else "Pick -1 to 1."
            )
        if len(acct["orders"]) >= MAX_ORDERS:
            raise PaperError(f"{MAX_ORDERS} orders is the limit for one account.")
        day = max(today or self.today(acct["symbol"]), acct["created"])
        acct["orders"].append(
            {
                "date": day,
                "target": round(target, 4),
                "at": time.time() if today is None else _midnight(day),
            }
        )
        self.save(acct)
        return acct

    def archive(self, pid: str, today: str | None = None) -> dict:
        with _LOCK:
            acct = self.load(pid)
            if not acct.get("archived"):
                day = today or self.today(acct["symbol"])
                acct["archived"] = max(day, acct["created"])
                self.save(acct)
            return acct

    def today(self, symbol: str) -> str:
        """Today's date where the market trades."""
        name = self.lab.store.facts(symbol).get("timezone") or "UTC"
        try:
            zone: dt.tzinfo = ZoneInfo(name)
        except (KeyError, ValueError):
            zone = dt.timezone.utc
        return dt.datetime.now(zone).date().isoformat()

    # ---- replay ----------------------------------------------------------------

    def replay(self, acct: dict, until: str | None = None) -> dict:
        """The account as it stands on the prices known now, or on `until`."""
        return self._replay(acct, until)[0]

    def forward_luck(
        self, acct: dict, runs: int = 200, until: str | None = None
    ) -> dict:
        """This account's own trades on coin-flip copies of its days, up to
        `until` (the day its luck is judged on, ready.luck_day)."""
        _, ctx = self._replay(acct, until)
        return luck.check(**ctx, runs=runs, seed=1)

    def _replay(self, acct: dict, until: str | None = None) -> tuple[dict, dict]:
        try:
            return self._run(acct, until)
        except (PaperError, LabError):
            raise
        except Exception as exc:  # a file edited by hand: say so, never a 500
            raise PaperError(f"That account could not be replayed: {exc}", 409) from exc

    def _run(self, acct: dict, until: str | None) -> tuple[dict, dict]:
        lab = self.lab
        venue = lab.venues[acct["venue"]]
        try:
            full, inst, notes = lab.history(acct["symbol"])
        except LabError as exc:
            raise PaperError(str(exc), 502) from exc
        if not venue.can_trade(inst.kind):
            raise PaperError(f"A {venue.label} cannot trade {inst.name}.", 409)
        if full.dates and full.dates[0] > acct["created"]:
            raise PaperError(
                f"Prices for {inst.name} start after this account was made, so it "
                "cannot be replayed.",
                409,
            )
        i0 = max(0, bisect.bisect_right(full.dates, acct["created"]) - 1)
        # never past today, whatever the price file holds
        today = self.today(acct["symbol"])
        stop = min(acct.get("archived") or today, today, until or today)
        series = full.window(full.dates[i0] if full.dates else "", stop)
        n = len(series)
        if n == 0:
            raise PaperError("No prices for this account's days.", 502)
        cfg = RunConfig(**acct["config"])
        params: dict = {}
        if acct["kind"] == "bot":
            mods = strategies.load()
            mod = mods.get(acct["strategy"])
            if mod is None:
                raise PaperError(f"The strategy {acct['strategy']} is gone.", 409)
            # a setting the idea gained after the bot was made takes its default
            params = strategies.params_for(mod.META, acct["params"])
            targets = mod.targets(full, params)[i0 : i0 + n]
        else:
            # an order placed after the last day looked at cannot change it: a
            # luck check judged on its look day would re-roll with each new one
            orders = [o for o in acct["orders"] if o["date"] <= stop]
            targets = manual_targets(series.dates, orders)
        fx, fx_notes = lab.store.fx_for(series)
        rates, rate_notes = lab.store.rates_for(
            series, venue.benchmark_history, [inst.currency, "AUD"]
        )
        res = run(series, targets, venue, inst, cfg, fx, rates)
        bench_sym = inst.benchmark or DEFAULT_BENCHMARK
        bench = bench_inst = None
        sources = {acct["symbol"]: full.source}
        try:
            bench_full, bench_inst, _ = lab.history(bench_sym)
            bench = lab.benchmark(bench_full, bench_inst, series, cfg)
            sources[bench_sym] = bench_full.source
        except LabError:
            pass
        aud = rates.get("AUD")
        rate = sum(aud) / len(aud) if aud else venue.bench_pct("AUD")
        whole = stats.segment(res, 0, n - 1, rate)
        out = dict(acct)
        out.update(
            {
                "name": acct["name"],
                "market": inst.name,
                "venue_label": venue.label,
                "since": series.dates[0],
                "last_date": series.dates[-1],
                # how far the market's prices reach, whatever the window
                "prices_to": min(full.dates[-1], today),
                "days": n,
                "calendar_days": (
                    dt.date.fromisoformat(series.dates[-1])
                    - dt.date.fromisoformat(series.dates[0])
                ).days,
                "equity": round(res.equity[-1], 2),
                "money_in": round(res.deposited, 2),
                "profit": round(res.equity[-1] - res.deposited, 2),
                "exposure": round(res.exposure[-1], 3),
                "wanted": round(targets[-1], 3) if targets else 0.0,
                "leverage_used": res.leverage_used,
                "stats": whole,
                "trades": stats.trade_stats(res),
                "trade_log": res.account.trades[-100:],
                "notes": res.notes + notes + fx_notes + rate_notes,
                "warning": inst.warning,
                "sources": sources,
            }
        )
        if acct["kind"] == "bot":
            out["strategy_name"] = strategies.load()[acct["strategy"]].META["name"]
            out["params"] = params
        if bench is not None and bench_inst is not None and bench.dates:
            out["bench"] = {
                "symbol": bench_sym,
                "name": bench_inst.name,
                "final": round(bench.equity[-1], 2),
                "stats": stats.segment(bench, 0, len(bench.dates) - 1, rate),
            }
        else:
            bench = None
        out["curve"] = curve(series, res, bench)
        luck_args = {
            "series": series,
            "targets": targets,
            "venue": venue,
            "inst": inst,
            "cfg": cfg,
            "res": res,
            "fx": fx,
            "rates": rates,
        }
        return out, luck_args

    def listing(self) -> dict:
        rows, problems = [], []
        for pid in self.ids():
            try:
                r = self.replay(self.load(pid))
            except Exception as exc:  # one bad file must not hide the others
                problems.append({"id": pid, "problem": str(exc)})
                continue
            r.pop("trade_log", None)
            r.pop("curve", None)
            rows.append(r)
        rows.sort(key=lambda r: (r["created"], r["id"]), reverse=True)
        live = [r for r in rows if not r.get("archived")]
        return {
            "accounts": live + [r for r in rows if r.get("archived")],
            "live": len(live),
            "archived": len(rows) - len(live),
            "bots_tried": sum(1 for r in rows if r["kind"] == "bot"),
            "problems": problems,
        }


def manual_targets(dates: list[str], orders: list[dict]) -> list[float]:
    """The exposure wanted at each close: the latest order made before the
    next trading day (so it fills at that day's open); the last day holds
    the latest order of all, waiting for the next open."""
    by_date = sorted(
        ((o["date"], i, float(o["target"])) for i, o in enumerate(orders)),
        key=lambda x: (x[0], x[1]),
    )
    keys = [d for d, _, _ in by_date]
    out: list[float] = []
    for t in range(len(dates)):
        if t + 1 < len(dates):
            k = bisect.bisect_left(keys, dates[t + 1])
        else:
            k = len(keys)
        out.append(by_date[k - 1][2] if k > 0 else 0.0)
    return out


def damaged(doc: object, pid: str, venue_ids: Container[str]) -> str:
    """Why an account file cannot be replayed, or "" when it can: a file
    edited by hand or cut short shows up as a problem, not a crash."""
    if not isinstance(doc, dict):
        return "it is not an account"
    for key, kind in (
        ("id", str),
        ("name", str),
        ("kind", str),
        ("symbol", str),
        ("venue", str),
        ("config", dict),
        ("created", str),
        ("orders", list),
        ("archived", str),
    ):
        if not isinstance(doc.get(key), kind):
            return f"its {key} is missing or the wrong kind of value"
    if doc["id"] != pid:
        return "its id does not match its file name"
    if doc["kind"] not in ("manual", "bot"):
        return "it is neither a manual account nor a bot"
    if doc["venue"] not in venue_ids:
        return f"there is no account type called {doc['venue']}"
    if not _is_day(doc["created"]) or (
        doc["archived"] and not _is_day(doc["archived"])
    ):
        return "its dates are not dates"
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    if max(doc["created"], doc["archived"]) > tomorrow:
        return "it is dated in the future"
    if not doc["id"].startswith(doc["created"].replace("-", "") + "-"):
        return "its id does not match the day it was made"
    if doc["archived"] and doc["archived"] < doc["created"]:
        return "it was archived before it was made"
    if not _made_on(doc.get("created_at"), doc["created"]):
        return "the day it was made and the time it was saved do not agree"
    cfg = doc["config"]
    if sorted(cfg) != sorted(CONFIG_KEYS) or not all(_is_num(v) for v in cfg.values()):
        return "its settings are not the ones Mint writes"
    try:
        if _config(cfg) != cfg:  # 7.5 days between deposits would run as 7
            return "its settings are not the ones Mint writes"
    except PaperError as exc:
        return str(exc).rstrip(".")
    for o in doc["orders"]:
        if not (
            isinstance(o, dict)
            and isinstance(o.get("date"), str)
            and _is_day(o["date"])
            and _is_num(o.get("target"))
            and -1 <= o["target"] <= 1
        ):
            return "one of its orders is not an order"
        if o["date"] < doc["created"] or not _made_on(o.get("at"), o["date"]):
            return (
                "one of its orders is dated before the account or saved on another day"
            )
        if o["date"] > tomorrow:
            return "one of its orders is dated in the future"
    if doc["kind"] == "bot":
        return _bot_problem(doc.get("strategy"), doc.get("params"))
    return ""


def _bot_problem(sid: object, params: object) -> str:
    """A bot runs only on settings Mint itself would write: a known idea,
    every setting inside its range and in the idea's order. A setting the
    idea gained since the bot was made takes its default; one the idea no
    longer has means the idea changed under the bot."""
    if not (isinstance(sid, str) and isinstance(params, dict)):
        return "its idea or the idea's settings are missing"
    mod = strategies.load().get(sid)
    if mod is None:
        return f"there is no idea called {sid}"
    keys = {p["key"] for p in mod.META.get("params", [])}
    gone = sorted(str(k) for k in params if k not in keys)
    if gone:
        return f"the idea changed: it no longer has the setting {', '.join(gone)}"
    full = strategies.params_for(mod.META, params)
    if any(params[k] != full[k] for k in params) or strategies.order_problem(
        mod.META, full
    ):
        return "its idea's settings are not ones Mint writes"
    return ""


def _made_on(stamp: object, day: str) -> bool:
    """Whether a saved time falls on (or a day either side of, for time
    zones) the day an account says it was made."""
    if not (_is_num(stamp) and isinstance(stamp, (int, float))):
        return False
    try:
        saved = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return False
    return abs((saved - dt.date.fromisoformat(day)).days) <= 1


def _midnight(day: str) -> float:
    """Midnight UTC at the start of `day`, as a saved time."""
    return dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp()


def _is_num(v: object) -> bool:
    """A finite number a float holds exactly: 10**400 is not one."""
    return (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and abs(v) <= 2**53
        and math.isfinite(v)
    )


def _is_day(s: str) -> bool:
    if not DAY_RE.fullmatch(s):
        return False
    try:
        dt.date.fromisoformat(s)
    except ValueError:
        return False
    return True


def _config(body: dict) -> dict:
    def num(key: str, default: float, lo: float, hi: float) -> float:
        try:
            v = float(body.get(key, default))
        except (TypeError, ValueError):
            raise PaperError(f"{key} must be a number.") from None
        if not lo <= v <= hi:
            raise PaperError(f"{key} must be between {lo:g} and {hi:g}.")
        return v

    cfg = RunConfig(
        start_cash=num("start_cash", 100.0, 0, 1_000_000),
        deposit=num("deposit", 0.0, 0, 5000),
        deposit_every_days=int(num("deposit_every_days", 7, 1, 31)),
        leverage=num("leverage", 1.0, 1, 30),
        stop_pct=num("stop_pct", 0.0, 0, 50),
    )
    if cfg.start_cash + cfg.deposit <= 0:
        raise PaperError("Start with some fake money, or a weekly deposit.")
    return {k: getattr(cfg, k) for k in CONFIG_KEYS}
