"""Spaced repetition for Forge apps: one small wrapper over py-fsrs.

Kotoba uses it now and Recall will use the same one, so both apps schedule
cards the same way. A card is stored as the plain dict py-fsrs gives back
(`Card.to_dict()`), which goes straight into JSON or a SQLite text column.

    import forge_fsrs
    card = forge_fsrs.new_card()
    card, log = forge_fsrs.review(card, forge_fsrs.GOOD)
    forge_fsrs.due_at(card)  # -> aware datetime

The app's venv needs `fsrs` (PyPI, github.com/open-spaced-repetition/py-fsrs,
MIT). Ratings are the four FSRS answers, 1 to 4.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from fsrs import Card, Rating, Scheduler

AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
RATING_NAMES = {AGAIN: "Again", HARD: "Hard", GOOD: "Good", EASY: "Easy"}
STATE_NAMES = {1: "learning", 2: "review", 3: "relearning"}

_scheduler = Scheduler(enable_fuzzing=False)


def _load(card: dict[str, Any]) -> Card:
    return Card.from_dict(cast(Any, card))


def _dump(card: Card) -> dict[str, Any]:
    return dict(card.to_dict())


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_card(when: datetime | None = None) -> dict[str, Any]:
    """A fresh card, due straight away."""
    card = Card()
    card.due = when or now()
    return _dump(card)


def review(
    card: dict[str, Any], rating: int, when: datetime | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Answer a card; returns the updated card and the review log entry."""
    if rating not in RATING_NAMES:
        raise ValueError(f"rating must be 1 to 4, got {rating!r}")
    updated, log = _scheduler.review_card(
        _load(card), Rating(rating), review_datetime=when or now()
    )
    return _dump(updated), dict(log.to_dict())


def due_at(card: dict[str, Any]) -> datetime:
    return _load(card).due


def next_intervals(
    card: dict[str, Any], when: datetime | None = None
) -> dict[int, float]:
    """Seconds until the card would be due again for each answer, for the
    labels on the answer buttons."""
    at = when or now()
    out = {}
    for rating in RATING_NAMES:
        updated, _ = _scheduler.review_card(
            _load(card), Rating(rating), review_datetime=at
        )
        out[rating] = max(0.0, (updated.due - at).total_seconds())
    return out


def recall_chance(card: dict[str, Any], when: datetime | None = None) -> float:
    """How likely the card is remembered right now, 0 to 1."""
    return float(_scheduler.get_card_retrievability(_load(card), when or now()))


def state_name(card: dict[str, Any]) -> str:
    return STATE_NAMES.get(int(card.get("state", 1)), "learning")
