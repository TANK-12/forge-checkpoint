"""Trend filter: invested while the price is above its long average."""

from ..indicators import sma

META = {
    "id": "trend_200",
    "name": "Trend filter (200-day average)",
    "summary": "Hold the market while its price is above the average of the "
    "last 200 days; sit in cash below it. Aims to dodge long crashes, pays for "
    "it with false alarms.",
    "long_only": True,
    "params": [
        {
            "key": "days",
            "label": "Average over (days)",
            "min": 20,
            "max": 400,
            "step": 10,
            "default": 200,
            "help": "How many past days the average covers.",
        }
    ],
}


def targets(series, params):
    avg = sma(series.close, int(params["days"]))
    return [
        0.0 if a is None else (1.0 if c > a else 0.0) for c, a in zip(series.close, avg)
    ]
