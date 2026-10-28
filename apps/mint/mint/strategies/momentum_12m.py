"""Time-series momentum: hold while the last year's return is positive."""

META = {
    "id": "momentum_12m",
    "name": "Momentum (last 12 months)",
    "summary": "Invested while the market is up over the last year (skipping "
    "the latest month), out or short while it is down.",
    "long_only": False,
    "params": [
        {
            "key": "lookback",
            "label": "Look back (days)",
            "min": 40,
            "max": 400,
            "step": 5,
            "default": 252,
            "help": "252 trading days is about a year.",
        },
        {
            "key": "skip",
            "label": "Skip latest (days)",
            "min": 0,
            "max": 40,
            "step": 1,
            "default": 21,
            "help": "Ignore the newest days (short-term noise).",
        },
        {
            "key": "shorts",
            "label": "Go short when down",
            "min": 0,
            "max": 1,
            "step": 1,
            "default": 0,
            "help": "1 = bet on falls too (CFD only).",
        },
    ],
}


def targets(series, params):
    look = int(params["lookback"])
    skip = int(params["skip"])
    down = -1.0 if params.get("shorts") else 0.0
    c = series.close
    out = []
    for t in range(len(c)):
        if t < look or skip >= look:
            out.append(0.0)
            continue
        ret = c[t - skip] / c[t - look] - 1
        out.append(1.0 if ret > 0 else down)
    return out
