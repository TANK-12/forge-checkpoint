"""Coin flip: random trades. What zero skill looks like after costs."""

import random

META = {
    "id": "coin_flip",
    "name": "Coin flip (zero skill)",
    "summary": "Opens trades at random and closes them at random. Whatever it "
    "earns or loses is luck plus costs: the honest baseline for any trading idea.",
    "long_only": False,
    "params": [
        {
            "key": "trades_per_year",
            "label": "Trades a year",
            "min": 1,
            "max": 150,
            "step": 1,
            "default": 25,
            "help": "How often it opens a trade.",
        },
        {
            "key": "hold_days",
            "label": "Average hold (days)",
            "min": 1,
            "max": 60,
            "step": 1,
            "default": 5,
            "help": "How long a trade stays open on average.",
        },
        {
            "key": "shorts",
            "label": "Shorts too",
            "min": 0,
            "max": 1,
            "step": 1,
            "default": 1,
            "help": "1 = half its bets are on falls (CFD only).",
        },
        {
            "key": "seed",
            "label": "Coin (seed)",
            "min": 1,
            "max": 9999,
            "step": 1,
            "default": 1,
            "help": "Different numbers flip a different coin.",
        },
    ],
}


def targets(series, params):
    rng = random.Random(int(params["seed"]))
    hold = max(1.0, float(params["hold_days"]))
    per_year = float(params["trades_per_year"])
    in_market = min(0.95, per_year * hold / 252)
    p_enter = min(1.0, per_year / 252 / max(0.05, 1 - in_market))
    shorts = bool(params.get("shorts"))
    pos = 0.0
    out = []
    for _ in range(len(series)):
        u, v = rng.random(), rng.random()
        if pos == 0.0:
            if u < p_enter:
                pos = -1.0 if shorts and v < 0.5 else 1.0
        elif u < 1 / hold:
            pos = 0.0
        out.append(pos)
    return out
