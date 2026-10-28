"""Ready for real money? A checklist, not a button.

Every check has to pass before Mint writes a plan, and the plan is only
words for the owner to carry out himself if he decides to: Mint never opens,
funds or trades a real account. A bot's past years (tuning, then test) are
a minimum only: settings can be tried in the Lab again and again until the
past looks good, so passing them proves little. The luck check runs on the
paper days from the day an account was made to FORWARD_DAYS later, with the
orders made by then, for a bot and a person's own trades alike: nobody could
have tuned on those days, and one look fixed in advance stops a lucky
stretch from passing on its best day. Every paper account made is one more
idea tried: try twenty skill-free ideas against a 95% bar and one clears it
by luck about two times in three. So each idea's bar is fixed by its place
in the order the accounts were made, 5% / (rank x (rank + 1)) of luck
allowed, which adds up to 5% for all of them together however many follow
and whenever each is acted on. The coin-flip copies grow with the rank too:
with 200 copies, beating every one still happens by luck one time in 201.
"""

from __future__ import annotations

import datetime as dt
import math

from .data import LIVE_SOURCES

FORWARD_DAYS = 90
FORWARD_TRADES = 20
LUCK_ALPHA = 0.05  # all ideas together pass the luck check by luck at most this often
MAX_RUNS = 20000


def luck_day(created: str) -> str:
    """The one day an account's luck is judged: FORWARD_DAYS after it was
    made. Looked at every day instead, a coin-flipper's lucky stretch would
    pass on its best day far more often than one time in twenty."""
    day = dt.date.fromisoformat(created) + dt.timedelta(days=FORWARD_DAYS)
    return day.isoformat()


def _check(cid: str, label: str, state: str, detail: str) -> dict:
    return {"id": cid, "label": label, "state": state, "detail": detail}


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def luck_alpha(rank: int) -> float:
    """The chance of passing by luck allowed to the idea made `rank`-th:
    2.5% for the first, 0.83% for the second, 0.42% for the third. These add
    up to 5% however many ideas follow (a Bonferroni-style split fixed in
    advance), so acting on each pass as it comes stays honest."""
    r = max(1, rank)
    return LUCK_ALPHA / (r * (r + 1))


def luck_bar(rank: int) -> float:
    """The share of coin-flip copies to beat: 97.5% for the first idea,
    higher for each later one."""
    return 100.0 * (1 - luck_alpha(rank))


def luck_runs(rank: int) -> int:
    """Coin-flip copies for a luck check. The account counts as one more, so
    the best odds it can show are 1 in runs + 1, and those must sit inside
    the bar: 200 copies for the first idea, more for later ones, up to
    MAX_RUNS."""
    r = max(1, rank)
    return min(MAX_RUNS, max(200, 40 * r * (r + 1)))


def can_pass(rank: int) -> bool:
    """Whether any result can pass at this place in line: from idea 32 on,
    even beating all MAX_RUNS copies is not rare enough."""
    return luck_alpha(rank) * (luck_runs(rank) + 1) >= 1


def judge_now(state: dict, look: str) -> bool:
    """Whether luck can be judged yet: the prices reach the look day and the
    account ran until then. One archived before its look day is never
    judged, so stopping on a good day cannot pass."""
    archived = state.get("archived") or ""
    reach = state.get("prices_to") or ""
    return reach >= look and (not archived or archived >= look)


def _odds(x: float) -> str:
    """A chance as a percentage, never in e-notation."""
    v = x * 100
    text = f"{v:.0f}" if v >= 10 else f"{v:.1f}" if v >= 1 else f"{v:.3f}"
    return (text.rstrip("0").rstrip(".") if "." in text else text) + "%"


def _bar_text(bar: float) -> str:
    """The bar rounded up, so beating the words means beating the bar, with
    as many places as it takes to stay under 100."""
    places = 2
    up = math.ceil(bar * 100 - 1e-6) / 100
    while up >= 100 > bar and places < 6:
        places += 1
        up = math.ceil(bar * 10**places - 1e-6) / 10**places
    return f"{up:.{places}f}".rstrip("0").rstrip(".")


def evaluate(
    paper: dict,
    backtest: dict | None,
    luck: dict | None,
    comfort: float,
    rank: int = 1,
    start: float = 100.0,
) -> dict:
    """`paper` is Paper.replay's result; `backtest` the Lab's backtest of a
    bot up to the day it was made (None for a manual account); `luck` the
    luck check on the paper days up to luck_day, for both kinds (None until
    then); `rank` the account's place in the order paper accounts were made
    (Paper.rank, archived ones too); `start` the amount from the settings."""
    checks: list[dict] = [_prices_check(paper)]
    falls = [paper["stats"].get("max_drawdown") or 0.0]
    if backtest:
        t, bt = backtest["tuning"], backtest["bench"]["tuning"]
        s, bs = backtest["test"], backtest["bench"]["test"]
        checks.append(
            _check(
                "tuning",
                "Beat the plain fund after costs on the tuning years",
                "pass" if (t.get("cagr") or -1) > (bt.get("cagr") or -1) else "fail",
                f"{_pct(t.get('cagr'))} a year against {_pct(bt.get('cagr'))} "
                f"({t.get('start', '?')} to {t.get('end', '?')}). A minimum only: "
                "settings can be tried in the Lab until the past looks good, so "
                "this proves little on its own.",
            )
        )
        checks.append(
            _check(
                "test",
                "Beat it on the later years too",
                "pass" if (s.get("cagr") or -1) > (bs.get("cagr") or -1) else "fail",
                f"{_pct(s.get('cagr'))} a year against {_pct(bs.get('cagr'))} "
                f"({s.get('start', '?')} to {s.get('end', '?')}). A minimum too: "
                "these years can be seen in the Lab, so they are not a clean test.",
            )
        )
        falls.append(backtest["whole"].get("max_drawdown") or 0.0)
    else:
        checks.append(
            _check(
                "past",
                "Tested on past years",
                "n/a",
                "A person's own trades cannot be replayed on the past, so only "
                "the paper record counts.",
            )
        )
    created = paper.get("created")
    look = luck_day(created) if isinstance(created, str) and created else ""
    luck_check = _luck_check(luck, rank, look)
    checks.append(luck_check)
    checks.append(_forward_check(paper))
    days = paper.get("calendar_days", 0)
    # positions opened or closed; top-ups of an open position are not decisions
    moves = paper["trades"].get("entries", 0) + paper["trades"].get("round_trips", 0)
    checks.append(
        _check(
            "time",
            f"At least {FORWARD_DAYS} days and {FORWARD_TRADES} trades on paper",
            "pass" if days >= FORWARD_DAYS and moves >= FORWARD_TRADES else "wait",
            f"{days} days so far ({FORWARD_DAYS} needed); {moves} of {FORWARD_TRADES} "
            "trades in or out (topping up a position does not count). "
            "A rule that trades rarely needs years of record before it can be "
            "told apart from luck.",
        )
    )
    worst = max(falls)
    checks.append(
        _check(
            "fall",
            "Worst fall inside your comfort",
            "pass" if worst <= comfort else "fail",
            f"Worst fall {worst * 100:.0f}% against the {comfort * 100:.0f}% you "
            "said you can sit through.",
        )
    )
    passed = all(c["state"] in ("pass", "n/a") for c in checks)
    return {
        "checks": checks,
        "passed": passed,
        "open": sum(c["state"] not in ("pass", "n/a") for c in checks),
        "plan": _plan(paper, comfort, start) if passed else [],
        "meanwhile": (
            [] if passed else _meanwhile(paper, settled=luck_check["state"] == "fail")
        ),
    }


def _prices_check(paper: dict) -> dict:
    label = "Real prices only"
    sources = paper.get("sources") or {}
    if not sources:
        return _check(
            "prices", label, "fail", "Mint cannot tell where these prices came from."
        )
    bad = sorted(sym for sym, src in sources.items() if src not in LIVE_SOURCES)
    if bad:
        return _check(
            "prices",
            label,
            "fail",
            f"{', '.join(bad)} came from a file or from made-up prices, which "
            "could say anything. Only prices Mint fetched itself count.",
        )
    return _check(
        "prices",
        label,
        "pass",
        "Every price came from Yahoo Finance or the RBA, fetched by Mint itself.",
    )


def _luck_check(luck: dict | None, rank: int = 1, look: str = "") -> dict:
    bar, alpha = luck_bar(rank), luck_alpha(rank)
    label = f"Beat at least {_bar_text(bar)}% of coin-flip copies of the same days"
    which = "the first idea" if rank <= 1 else f"idea number {rank}"
    why = (
        f" This is {which} tried on paper (every account counts, archived ones "
        "too, in the order they were made). Each later idea gets a stricter "
        "bar, so all of them together pass by luck at most 5% of the time."
    )
    if not can_pass(rank):
        return _check(
            "luck",
            label,
            "fail",
            "So far down the line, no result can pass: even beating all "
            f"{luck_runs(rank):,} coin-flip copies of its days happens by luck "
            f"more often than the {_odds(alpha)} allowed." + why,
        )
    when = f"on {look}" if look else f"{FORWARD_DAYS} days after the account was made"
    if not luck:
        return _check(
            "luck",
            label,
            "wait",
            f"Judged {when}, on the paper days and the orders made up to then: "
            "those days came after the account was made, so nobody could have "
            "tuned on them, and one look fixed in advance stops a lucky stretch "
            "from passing on its best day. The coin-flip copies keep its own "
            "trades and sizes and turn each day's move round at random." + why,
        )
    judged = f" Judged on the paper days and orders up to {look}." if look else ""
    if luck.get("skipped"):
        return _check("luck", label, "fail", luck.get("verdict", "") + judged + why)
    p = luck.get("p")
    if not (isinstance(p, (int, float)) and not isinstance(p, bool) and 0 < p <= 1):
        odds = " Mint could not tell how often luck does this well, so it cannot pass."
        ok = False
    else:
        odds = (
            " Counting the account as one more copy, luck alone does this well "
            f"{_odds(p)} of the time; passing needs {_odds(alpha)} or less."
        )
        ok = p <= alpha
    return _check(
        "luck",
        label,
        "pass" if ok else "fail",
        luck.get("verdict", "") + judged + odds + why,
    )


def _forward_check(paper: dict) -> dict:
    label = "Beat the plain fund since the paper account opened"
    bench = paper.get("bench")
    if not bench or paper.get("days", 0) < 2:
        return _check("forward", label, "wait", "No days to compare yet.")
    me, them = paper["equity"], bench["final"]
    return _check(
        "forward",
        label,
        "pass" if me > them else "fail",
        f"${me:,.2f} against ${them:,.2f} in {bench['symbol']} with the same deposits.",
    )


def _plan(paper: dict, comfort: float, start: float) -> list[str]:
    who = paper.get("strategy_name") or "your own calls"
    first = (
        f"Start with ${start:,.0f} at most: money you are fine to lose, not your "
        "savings."
        if start > 0
        else "Start small, with money you are fine to lose, not your savings."
    )
    lines = [
        "Mint never touches a real account. Every check passing is not a "
        "promise: if you decide to go ahead, that is your call, and this is a "
        "plan for you to carry out yourself.",
        first,
    ]
    if paper["venue"] == "cfd":
        lines.append(
            f"Use a CFD account on {paper['market']} at 1x to 2x leverage at first, "
            "whatever the test used. ASIC found 68% of Australian retail CFD clients "
            "lost money in FY24."
        )
    else:
        lines.append(
            f"Open a share account with a low-cost broker (about $3 a trade) and "
            f"follow {who} on {paper['market']}. Mint shows the call for the next "
            "open every day."
        )
    bench = (paper.get("bench") or {}).get("symbol", "the plain fund")
    lines += [
        "Keep this paper account running beside the real one.",
        f"Stop if the real one trails {bench} for three months in a row, or falls "
        f"more than {comfort * 100:.0f}%.",
        "Keep a record of every trade for tax: profits are taxed at your marginal "
        "rate.",
    ]
    return lines


def _meanwhile(paper: dict, settled: bool = False) -> list[str]:
    """`settled`: the luck check was judged and failed, which is final."""
    bench = (paper.get("bench") or {}).get("symbol", "VAS.AX")
    return [
        f"Not ready. Until every check passes, the plan is the plain fund: {bench}, "
        "bought once a month and left alone.",
        (
            "Its luck check did not pass, so this account can never pass. Another "
            "idea needs a new paper account, against a higher bar."
            if settled
            else "Keep the paper account running; the checks update with every new "
            "day of prices."
        ),
    ]
