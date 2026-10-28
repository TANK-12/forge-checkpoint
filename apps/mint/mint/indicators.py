"""Rolling numbers strategies use. Each value at t uses data up to t only."""

from __future__ import annotations


def sma(values: list[float], n: int) -> list[float | None]:
    """Simple moving average of the last n values, None until there are n."""
    out: list[float | None] = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def rsi(values: list[float], n: int) -> list[float | None]:
    """Wilder's relative strength index (0-100)."""
    out: list[float | None] = [None] * len(values)
    gain = loss = 0.0
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        g = change if change > 0 else 0.0
        lo = -change if change < 0 else 0.0
        if i <= n:
            gain += g
            loss += lo
            if i < n:
                continue
            gain /= n
            loss /= n
        else:
            gain = (gain * (n - 1) + g) / n
            loss = (loss * (n - 1) + lo) / n
        out[i] = 100.0 if loss == 0 else 100.0 - 100.0 / (1.0 + gain / loss)
    return out


def prior_high(values: list[float], n: int) -> list[float | None]:
    """Highest of the n values before t (t itself excluded)."""
    return [max(values[i - n : i]) if i >= n else None for i in range(len(values))]


def prior_low(values: list[float], n: int) -> list[float | None]:
    """Lowest of the n values before t (t itself excluded)."""
    return [min(values[i - n : i]) if i >= n else None for i in range(len(values))]
