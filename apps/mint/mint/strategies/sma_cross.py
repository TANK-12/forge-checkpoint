"""Moving-average crossover: long when the fast average is above the slow."""

from ..indicators import sma

META = {
    "id": "sma_cross",
    "name": "Moving-average crossover",
    "summary": "Buy when the short-term average climbs above the long-term "
    "one, get out (or go short) when it drops below. The classic trend rule.",
    "long_only": False,
    "order": [["fast", "slow"]],
    "params": [
        {
            "key": "fast",
            "label": "Fast average (days)",
            "min": 3,
            "max": 100,
            "step": 1,
            "default": 20,
            "help": "The short-term average.",
        },
        {
            "key": "slow",
            "label": "Slow average (days)",
            "min": 10,
            "max": 300,
            "step": 5,
            "default": 100,
            "help": "The long-term average.",
        },
        {
            "key": "shorts",
            "label": "Go short when below",
            "min": 0,
            "max": 1,
            "step": 1,
            "default": 0,
            "help": "1 = bet on falls too (CFD only).",
        },
    ],
}


def targets(series, params):
    fast = sma(series.close, int(params["fast"]))
    slow = sma(series.close, int(params["slow"]))
    down = -1.0 if params.get("shorts") else 0.0
    out = []
    for f, s in zip(fast, slow):
        if f is None or s is None:
            out.append(0.0)
        else:
            out.append(1.0 if f > s else down)
    return out
