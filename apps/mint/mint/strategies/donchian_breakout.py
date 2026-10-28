"""Breakout: buy a new N-day high, leave on a new M-day low."""

from ..indicators import prior_high, prior_low

META = {
    "id": "donchian_breakout",
    "name": "Breakout (new highs)",
    "summary": "Buy when the price closes above its highest point of the last "
    "N days, sell when it closes below its lowest of the last M days. The "
    "'turtle' rule.",
    "long_only": False,
    "order": [["exit", "entry"]],
    "params": [
        {
            "key": "entry",
            "label": "Entry high (days)",
            "min": 5,
            "max": 150,
            "step": 5,
            "default": 55,
            "help": "Look-back for the breakout high.",
        },
        {
            "key": "exit",
            "label": "Exit low (days)",
            "min": 3,
            "max": 100,
            "step": 1,
            "default": 20,
            "help": "Look-back for the exit low.",
        },
        {
            "key": "shorts",
            "label": "Short new lows too",
            "min": 0,
            "max": 1,
            "step": 1,
            "default": 0,
            "help": "1 = mirror the rule for falls (CFD only).",
        },
    ],
}


def targets(series, params):
    c = series.close
    up = prior_high(series.high, int(params["entry"]))
    out_lo = prior_low(series.low, int(params["exit"]))
    dn = prior_low(series.low, int(params["entry"]))
    out_hi = prior_high(series.high, int(params["exit"]))
    shorts = bool(params.get("shorts"))
    pos = 0.0
    out = []
    for t in range(len(c)):
        if pos > 0 and out_lo[t] is not None and c[t] < out_lo[t]:
            pos = 0.0
        elif pos < 0 and out_hi[t] is not None and c[t] > out_hi[t]:
            pos = 0.0
        if pos == 0.0:
            if up[t] is not None and c[t] > up[t]:
                pos = 1.0
            elif shorts and dn[t] is not None and c[t] < dn[t]:
                pos = -1.0
        out.append(pos)
    return out
