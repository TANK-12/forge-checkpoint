# Reps

A log for workouts and habits with streaks and simple charts. Forge-built
(port 8498, section Life).

## What it does

- **Today**: one card per tracker. Type the numbers (reps and weight,
  minutes and distance, an amount) and press Log or Enter; a plain habit
  has one Done button. Each entry shows as a chip under the card, and the
  × on a chip removes it, with Undo in the message that follows. The card
  shows the streak (🔥), the week as seven dots and how far along the week
  goal is. **Logging for** picks another day, to fill in something
  forgotten (never a day ahead): the cards then show and log that day's
  entries, while the streak, the week and the headline still count from
  today. Undo brings back the very entry removed (its time too), even on an
  archived tracker.
- **History**: pick a tracker for the current and best streak, this week,
  days logged, a bar chart of the last eight weeks (the charted field added
  up per day, or the number of times for a habit) and the entries, newest
  first, each with a × to remove it.
- **Trackers**: add one (name, kind, goal in days a week; the kind sets a
  sensible goal), rename it, change its goal, archive it, or bring it back.
  Trackers are never deleted, so their history stays.

## Streaks

With a goal of every day, the streak is days in a row. With a smaller goal
(say 3 days a week) it is weeks in a row that met the goal; weeks start on
Monday. Today not logged yet, or this week not met yet, does not break a
streak; the day or week before does.

## Kinds

`kinds.json` is the registry: each kind has a label, an icon, a default
goal, its fields (`id`, `label`, optional `unit`, `min`, `max`, `step`,
`required`), and what the chart adds up (`chart.sum`, a
field id, or none to count entries). Adding a kind is one more entry there;
nothing else changes. A tracker whose kind is removed from the file still
shows and keeps its history, but takes no new entries.

## Data

`~/.local/share/forge/reps/reps.json` (`REPS_DATA_DIR` moves it), written
whole through a temporary file. A file that cannot be read as JSON is kept
aside as `reps.broken-<time>.json` and never thrown away; so is a file of
the wrong shape, and a file with rows missing what they need is copied
aside before those rows are dropped. Nothing leaves the laptop.

## Checks

    .venv/bin/python -m pytest -q tests
    .venv/bin/python tests/check_ui.py [SHOTS_DIR]

`check_ui.py` drives headless Chrome (Flatpak) through
`~/Forge/tests/cdp_driver.py` with real clicks and typing, on a scratch
data folder.
