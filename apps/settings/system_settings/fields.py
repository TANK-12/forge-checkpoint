"""Checks for the fields an action's JSON body carries."""

from __future__ import annotations


def flag(body: dict, key: str) -> bool:
    value = body.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value


def number(body: dict, key: str, low: int, high: int) -> int:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    if not low <= value <= high:
        raise ValueError(f"{key} must be {low} to {high}")
    return int(round(value))


def text(body: dict, key: str, allowed=None) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value or value.startswith("-"):
        raise ValueError(f"{key} is missing")
    if allowed is not None and value not in allowed:
        raise ValueError(f"no {key} called {value!r}")
    return value
