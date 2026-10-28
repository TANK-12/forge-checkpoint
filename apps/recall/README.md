# Recall

Flashcards that come back when they are due. Each answer (Again, Hard, Good,
Easy) goes to FSRS, the scheduler in `shared/forge_fsrs.py` (the same one
Kotoba uses), which sets when the card is shown next. The rating buttons
show that time before you pick.

## Using it

- **Review**: the deck list on the left shows how many cards are due (blue)
  and how many new ones are left today (+N). Space or Enter shows the
  answer, and 1 to 4 rate it.
- **Cards**: write a card into any deck (a new name makes a new deck), edit
  one, search the fronts and backs, or remove one. Remove asks a second
  time. Removed cards are hidden, not deleted: their reviews are kept, and
  importing again does not bring them back.
- **Import**: brings in cards from the sources in `recall.json`. Importing
  again adds what is new and updates words that changed; the schedule of
  a card that was already answered is kept.

New cards: at most `new_per_day` (20) a day across all decks, counted from
local midnight. Cards already learned that are due always come first.

## Sources (`recall.json`)

Recall only reads the folders below; it never writes to them.

- `study` (kind `study_bank`): every question in Study Companion's
  `data/<course>/questions/*.jsonl`. The question goes on the front; the
  answer and its worked steps go on the back. One deck per course.
- `study-notes` (kind `note_lines`): any line in a course's notes
  (`*.txt`, `*.md`) written as `front :: back`. A leading `-` is dropped.

To add a source, add one entry to `recall.json`. To add a new kind of
source, write one function in `recall_core.IMPORTERS` that yields `Found`
cards with a stable key.

## Files

- `recall_core.py`: the SQLite store (`<data>/recall.db`), the queue,
  answers, stats and the importers
- `web_app.py`: the FastAPI routes, behind `shared/forge_guard.LocalOnly`
- `static/`: the page
- Data goes in `~/.local/share/forge/recall`, or `RECALL_DATA_DIR` if set.
  `RECALL_CONFIG` points at another `recall.json`.

## Checks

    .venv/bin/python -m pytest -q tests        # backend, importers, API, guard
    .venv/bin/python tests/check_ui.py [SHOTS]  # headless Chrome, a temp data folder
