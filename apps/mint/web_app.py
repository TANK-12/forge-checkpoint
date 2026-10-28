"""Mint - a fake-money sandbox where a money idea has to earn real money.

Mint never connects to a broker, never logs in and never moves money. It
answers "where should the weekly money go" with fans of real-history
futures, backtests strategies on real prices with every real cost next to
the plain fund, runs paper accounts forward only, and keeps a checklist a
strategy must pass before Mint writes a plan for the owner to carry out
himself.

    /api/meta                    venues, markets, strategies, plan paths
    /api/settings                his numbers, goal and comfort (GET, POST)
    /api/plan                    the Plan tab, with how often each path
                                 reaches his goal (POST)
    /api/prices/<symbol>         a market's history, downsampled
    /api/prices/import           a CSV of daily prices (POST)
    /api/backtest, /api/sweep, /api/zero-skill    the Lab (POST)
    /api/paper                   paper accounts: list, make (POST)
    /api/paper/<id>              one account replayed; /order /archive
                                 /refresh (POST), /ready (GET)
    /api/learn                   the published figures, with sources

Every request under /api/ but /api/health must carry `X-Forge: 1` and a
local Host, so a web page open in Forge's Browser (which can reach
127.0.0.1) can neither write here nor set off a fetch or a backtest, and a
page that re-points its own name at 127.0.0.1 is refused.

Run standalone with:
    FORGE_SHARED_DIR=~/Forge/shared \\
    .venv/bin/python -m uvicorn web_app:app --host 127.0.0.1 --port 8470
"""

from __future__ import annotations

import json
import os
import urllib.parse
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from mint import data, planner, ready, strategies
from mint.engine import RunConfig
from mint.lab import Lab, LabError
from mint.paper import Paper, PaperError

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR", ROOT.parent.parent / "shared"))
MAX_BODY = 3_000_000
NO_STORE = {"Cache-Control": "no-store"}
# A page from elsewhere that re-points its own name at 127.0.0.1 (DNS
# rebinding) becomes same-origin and could send X-Forge; its Host header
# still carries its own name, so the API answers only to these.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
OPEN_PATHS = {"/api/health"}
DEFAULT_SETTINGS = {
    "start": 100.0,
    "weekly": 300.0,
    "years": 10,
    "comfort": 0.3,
    "mode": "simple",
    "salary": 0.0,
    "goal": 0.0,
}

app = FastAPI(title="Mint")


class State:
    """The price store, Lab and paper accounts, made on first use so the
    data folder can be pointed elsewhere (MINT_DATA_DIR) before that."""

    root = ""
    lab: Lab | None = None
    paper: Paper | None = None

    @classmethod
    def get(cls) -> tuple[Lab, Paper]:
        root = data.default_root()
        if cls.lab is None or cls.paper is None or root != cls.root:
            cls.root = root
            cls.lab = Lab(data.PriceStore(root))
            cls.paper = Paper(cls.lab, root)
        return cls.lab, cls.paper


def _local(host: str) -> bool:
    try:
        return urllib.parse.urlsplit("//" + host).hostname in LOCAL_HOSTS
    except ValueError:
        return False


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in OPEN_PATHS:
        if not _local(request.headers.get("host", "")):
            return JSONResponse(
                {"detail": "Mint answers only to 127.0.0.1 or localhost"},
                status_code=403,
            )
        # GETs too: a cross-site <img> must not set off a fetch or a backtest
        if request.headers.get("x-forge") != "1":
            return JSONResponse(
                {"detail": "Mint's API needs the X-Forge: 1 header"},
                status_code=403,
            )
    if path.startswith("/api/") and request.method not in ("GET", "HEAD"):
        if "chunked" in request.headers.get("transfer-encoding", "").lower():
            # no length up front means no size check: refuse rather than buffer
            return JSONResponse(
                {"detail": "send a Content-Length with the body"}, status_code=411
            )
        size = request.headers.get("content-length")
        if size and size.isdigit() and int(size) > MAX_BODY:
            return JSONResponse({"detail": "that is too big"}, status_code=413)
    response = await call_next(request)
    if not path.startswith("/api/"):
        # Forge's WebKit has run a stale app.js before; always revalidate.
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


@app.exception_handler(RequestValidationError)
async def bad_request(request: Request, exc: RequestValidationError):  # noqa: ARG001
    """FastAPI's own answer echoes the input back, and a NaN in it cannot be
    written as JSON (a 500); this one says what was wrong in words only."""
    problems = []
    for err in exc.errors()[:5]:
        where = ".".join(str(x) for x in err.get("loc", ()) if x != "body")
        msg = str(err.get("msg", "not valid"))
        problems.append(f"{where}: {msg}" if where else msg)
    return JSONResponse(
        {"detail": "; ".join(problems) or "That request is not valid."},
        status_code=422,
    )


@app.exception_handler(OverflowError)
async def too_big(request: Request, exc: OverflowError):  # noqa: ARG001
    """A number too big for a float (10**400) is a bad request, not a 500."""
    return JSONResponse({"detail": "A number in that was too big."}, status_code=400)


@app.exception_handler(LabError)
async def lab_error(request: Request, exc: LabError):  # noqa: ARG001
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(planner.PlanError)
async def plan_error(request: Request, exc: planner.PlanError):  # noqa: ARG001
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(PaperError)
async def paper_error(request: Request, exc: PaperError):  # noqa: ARG001
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@app.exception_handler(data.PriceError)
async def price_error(request: Request, exc: data.PriceError):  # noqa: ARG001
    return JSONResponse({"detail": f"Could not get prices: {exc}"}, status_code=502)


def _read_json(name: str) -> dict:
    with open(ROOT / name, encoding="utf-8") as f:
        return json.load(f)


# ---- meta and settings ----------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/meta")
def meta() -> JSONResponse:
    lab, _ = State.get()
    venues = _read_json("venues.json")["venues"]
    markets = _read_json("symbols.json")["symbols"]
    spec = planner.load_paths()
    return JSONResponse(
        {
            "venues": [
                {
                    "id": vid,
                    "label": v["label"],
                    "kind": v["kind"],
                    "summary": v.get("summary", ""),
                    "allow_short": v.get("allow_short", False),
                    "leverage_caps": v.get("leverage_caps", {}),
                    "tradeable": v.get("tradeable", []),
                    "min_trade": v.get("min_trade", 0),
                }
                for vid, v in venues.items()
            ],
            "markets": [
                {
                    k: m.get(k, "")
                    for k in (
                        "symbol",
                        "name",
                        "kind",
                        "cls",
                        "currency",
                        "blurb",
                        "warning",
                    )
                }
                for m in markets
            ],
            "strategies": [mod.META for mod in strategies.load().values()],
            "comfort": spec.get("comfort", []),
            "paths": [
                {k: p.get(k, "") for k in ("id", "short", "colour")}
                for p in spec["paths"]
            ],
            "made_up": "MADE-UP",
            "cached": sorted(_cached_symbols(lab)),
        },
        headers=NO_STORE,
    )


def _cached_symbols(lab: Lab) -> set[str]:
    folder = lab.store.dir
    out = set()
    for f in os.listdir(folder):
        if f.endswith(".json"):
            sym = lab.store.facts(urllib.parse.unquote(f[:-5])).get("symbol")
            if sym:
                out.add(sym)
    return out


def _settings_path() -> str:
    return os.path.join(data.default_root(), "settings.json")


def _load_settings() -> dict:
    try:
        with open(_settings_path(), encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    return {**DEFAULT_SETTINGS, **saved}


@app.get("/api/settings")
def get_settings() -> JSONResponse:
    return JSONResponse(_load_settings(), headers=NO_STORE)


class SettingsIn(BaseModel):
    start: float | None = Field(None, ge=0, le=planner.MAX_START)
    weekly: float | None = Field(None, ge=0, le=planner.MAX_WEEKLY)
    years: int | None = Field(None, ge=1, le=planner.MAX_YEARS)
    comfort: float | None = Field(None, gt=0, lt=1)
    mode: str | None = Field(None, pattern="^(simple|advanced)$")
    salary: float | None = Field(None, ge=0, le=planner.MAX_START)
    goal: float | None = Field(None, ge=0, le=planner.MAX_GOAL)


@app.post("/api/settings")
def set_settings(body: SettingsIn) -> JSONResponse:
    current = _load_settings()
    current.update({k: v for k, v in body.model_dump().items() if v is not None})
    os.makedirs(data.default_root(), exist_ok=True)
    data._write(_settings_path(), json.dumps(current, indent=1))
    return JSONResponse(current, headers=NO_STORE)


# ---- plan --------------------------------------------------------------------


class PlanIn(BaseModel):
    start: float = Field(100.0, ge=0, le=planner.MAX_START)
    weekly: float = Field(300.0, ge=0, le=planner.MAX_WEEKLY)
    years: int = Field(10, ge=1, le=planner.MAX_YEARS)
    comfort: float = Field(0.3, gt=0, lt=1)
    cautious: bool = False
    kinds: list[str] | None = None
    seed: int = 1
    salary: float = Field(0.0, ge=0, le=planner.MAX_START)
    # a target balance (0: none); in today's dollars when goal_today
    goal: float = Field(0.0, ge=0, le=planner.MAX_GOAL)
    goal_today: bool = False


@app.post("/api/plan")
def plan(body: PlanIn) -> dict:
    lab, _ = State.get()
    return planner.plan(
        lab.store,
        lab,
        start=body.start,
        weekly=body.weekly,
        years=body.years,
        comfort=body.comfort,
        cautious=body.cautious,
        kinds=body.kinds,
        seed=body.seed,
        salary=body.salary,
        goal=body.goal,
        goal_today=body.goal_today,
    )


# ---- prices -------------------------------------------------------------------


@app.get("/api/prices/{symbol}")
def prices(symbol: str, refresh: bool = False, points: int = 600) -> JSONResponse:
    lab, _ = State.get()
    symbol = lab.check(symbol)  # before any fetch: an unknown index never leaves
    if refresh and symbol != "MADE-UP":
        lab.store.get(symbol, refresh=True)
    series, inst, notes = lab.history(symbol)
    n = len(series)
    step = max(1, n // max(50, min(points, 3000)))
    idx = list(range(0, n, step))
    if idx and idx[-1] != n - 1:
        idx.append(n - 1)
    facts = lab.store.facts(symbol)
    return JSONResponse(
        {
            "symbol": symbol,
            "name": inst.name,
            "currency": series.currency,
            "first": series.dates[0] if n else "",
            "last": series.dates[-1] if n else "",
            "bars": n,
            "dates": [series.dates[i] for i in idx],
            "close": [round(series.close[i], 4) for i in idx],
            "source": series.source,
            "fetched_at": facts.get("fetched_at"),
            "notes": notes,
            "warning": inst.warning,
        },
        headers=NO_STORE,
    )


class ImportIn(BaseModel):
    symbol: str = Field(
        ..., min_length=1, max_length=24, pattern=r"^[A-Za-z0-9.^=_-]+$"
    )
    text: str = Field(..., min_length=10)
    currency: str = Field("AUD", pattern="^[A-Z]{3}$")
    name: str = Field("", max_length=80)


@app.post("/api/prices/import")
def import_prices(body: ImportIn) -> dict:
    lab, _ = State.get()
    s = lab.import_csv(body.symbol, body.text, body.currency, body.name)
    return {
        "symbol": s.symbol,
        "bars": len(s),
        "first": s.dates[0],
        "last": s.dates[-1],
    }


# ---- the lab ------------------------------------------------------------------


class ConfigIn(BaseModel):
    start_cash: float = Field(default=100.0, ge=0, le=1_000_000)
    deposit: float = Field(default=300.0, ge=0, le=5000)
    deposit_every_days: int = Field(default=7, ge=1, le=31)
    leverage: float = Field(default=1.0, ge=1, le=30)
    stop_pct: float = Field(default=0.0, ge=0, le=50)

    def run_config(self) -> RunConfig:
        return RunConfig(**self.model_dump())


class BacktestIn(BaseModel):
    symbol: str = "VAS.AX"
    venue: str = "cash"
    strategy: str = "buy_and_hold"
    params: dict[str, Any] | None = None
    config: ConfigIn = Field(default_factory=ConfigIn)
    start: str = ""
    end: str = ""
    split: float = Field(0.7, ge=0.3, le=0.9)
    luck_runs: int = Field(200, ge=0, le=500)
    steps: int = Field(6, ge=2, le=10)


@app.post("/api/backtest")
def backtest(body: BacktestIn) -> dict:
    lab, _ = State.get()
    return lab.backtest(
        body.symbol,
        body.venue,
        body.strategy,
        body.params,
        body.config.run_config(),
        body.start,
        body.end,
        body.split,
        body.luck_runs,
    )


@app.post("/api/sweep")
def sweep(body: BacktestIn) -> dict:
    lab, _ = State.get()
    return lab.sweep(
        body.symbol,
        body.venue,
        body.strategy,
        body.config.run_config(),
        body.start,
        body.end,
        body.split,
        body.steps,
    )


class ZeroIn(BaseModel):
    symbol: str = "^AXJO"
    venue: str = "cfd"
    config: ConfigIn = Field(default_factory=lambda: ConfigIn(leverage=5))
    years: float = Field(1.0, ge=0.25, le=20)
    runs: int = Field(200, ge=20, le=500)
    trades_per_year: int = Field(25, ge=1, le=500)
    hold_days: int = Field(5, ge=1, le=120)


@app.post("/api/zero-skill")
def zero_skill(body: ZeroIn) -> dict:
    lab, _ = State.get()
    return lab.zero_skill(
        body.symbol,
        body.config.run_config(),
        years=body.years,
        runs=body.runs,
        trades_per_year=body.trades_per_year,
        hold_days=body.hold_days,
        venue_id=body.venue,
    )


# ---- paper accounts -----------------------------------------------------------


@app.get("/api/paper")
def paper_list() -> JSONResponse:
    _, paper = State.get()
    return JSONResponse(paper.listing(), headers=NO_STORE)


class PaperIn(BaseModel):
    name: str = Field("", max_length=60)
    kind: str = Field("manual", pattern="^(manual|bot)$")
    symbol: str = "VAS.AX"
    venue: str = "cash"
    strategy: str = ""
    params: dict[str, Any] | None = None
    # None: the start and weekly amounts from the settings
    start_cash: float | None = None
    deposit: float | None = None
    deposit_every_days: int = 7
    leverage: float = 1.0
    stop_pct: float = 0.0


@app.post("/api/paper")
def paper_create(body: PaperIn) -> dict:
    _, paper = State.get()
    settings = _load_settings()
    fields = body.model_dump()
    if fields["start_cash"] is None:
        fields["start_cash"] = settings["start"]
    if fields["deposit"] is None:
        fields["deposit"] = settings["weekly"]
    acct = paper.create(fields)
    return paper.replay(acct)


@app.get("/api/paper/{pid}")
def paper_one(pid: str) -> JSONResponse:
    _, paper = State.get()
    return JSONResponse(paper.replay(paper.load(pid)), headers=NO_STORE)


class OrderIn(BaseModel):
    target: float = Field(..., ge=-1, le=1)


@app.post("/api/paper/{pid}/order")
def paper_order(pid: str, body: OrderIn) -> dict:
    _, paper = State.get()
    return paper.replay(paper.order(pid, body.target))


@app.post("/api/paper/{pid}/archive")
def paper_archive(pid: str) -> dict:
    _, paper = State.get()
    return paper.replay(paper.archive(pid))


@app.post("/api/paper/{pid}/refresh")
def paper_refresh(pid: str) -> dict:
    lab, paper = State.get()
    acct = paper.load(pid)
    lab.store.get(lab.check(acct["symbol"]), refresh=True)
    return paper.replay(acct)


@app.get("/api/paper/{pid}/ready")
def paper_ready(pid: str, comfort: float = 0.3) -> JSONResponse:
    lab, paper = State.get()
    if not 0 < comfort < 1:
        raise PaperError("comfort must be between 0 and 1.")
    acct = paper.load(pid)
    state = paper.replay(acct)
    test = None
    if acct["kind"] == "bot":
        test = lab.backtest(
            acct["symbol"],
            acct["venue"],
            acct["strategy"],
            acct["params"],
            RunConfig(**acct["config"]),
            end=acct["created"],
            luck_runs=0,
        )
    # the past can be retried in the Lab until it looks good and the paper days
    # cannot; their luck is judged on a day fixed when the account was made,
    # against a bar fixed by its place in the order accounts were made
    look = ready.luck_day(acct["created"])
    rank = paper.rank(acct)
    luck = (
        paper.forward_luck(acct, runs=ready.luck_runs(rank), until=look)
        if ready.judge_now(state, look) and ready.can_pass(rank)
        else None
    )
    start = _load_settings()["start"]
    out = ready.evaluate(
        state,
        test,
        luck,
        comfort,
        rank=rank,
        start=start if isinstance(start, (int, float)) else 100.0,
    )
    out["account"] = {k: state[k] for k in ("id", "name", "kind", "symbol", "market")}
    return JSONResponse(out, headers=NO_STORE)


# ---- learn --------------------------------------------------------------------


@app.get("/api/learn")
def learn() -> JSONResponse:
    return JSONResponse(_read_json("learn.json"), headers=NO_STORE)


if SHARED_DIR.is_dir():
    app.mount("/shared", StaticFiles(directory=str(SHARED_DIR)), name="shared")
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
