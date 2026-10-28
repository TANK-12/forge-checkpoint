"""Mean reversion: buy short, sharp dips, sell the bounce."""

from ..indicators import rsi, sma

META = {
    "id": "rsi_reversion",
    "name": "Buy the dip (RSI)",
    "summary": "Buy after a sharp short-term fall (low RSI, a 0-100 gauge of "
    "recent ups versus downs) and sell when it bounces. Many small trades, so "
    "costs bite hard.",
    "long_only": True,
    "params": [
        {
            "key": "period",
            "label": "RSI length (days)",
            "min": 2,
            "max": 30,
            "step": 1,
            "default": 3,
            "help": "Short lengths react fastest.",
        },
        {
            "key": "buy_below",
            "label": "Buy below",
            "min": 5,
            "max": 45,
            "step": 1,
            "default": 20,
            "help": "RSI level that counts as a dip.",
        },
        {
            "key": "sell_above",
            "label": "Sell above",
            "min": 50,
            "max": 95,
            "step": 1,
            "default": 60,
            "help": "RSI level that counts as the bounce.",
        },
        {
            "key": "trend",
            "label": "Only above 200-day average",
            "min": 0,
            "max": 1,
            "step": 1,
            "default": 1,
            "help": "1 = only buy dips in an uptrend.",
        },
    ],
}


def targets(series, params):
    r = rsi(series.close, int(params["period"]))
    avg = sma(series.close, 200)
    lo, hi = params["buy_below"], params["sell_above"]
    pos = 0.0
    out = []
    for t, v in enumerate(r):
        if v is not None:
            uptrend = not params.get("trend") or (
                avg[t] is not None and series.close[t] > avg[t]
            )
            if pos == 0.0 and v < lo and uptrend:
                pos = 1.0
            elif pos > 0 and v > hi:
                pos = 0.0
        out.append(pos)
    return out
