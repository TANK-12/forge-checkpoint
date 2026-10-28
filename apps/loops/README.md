# Loops

A beat and loop maker for Forge: a step sequencer in the page, with WAV export.

- One row per instrument (kick, snare, clap, hats, toms, bass, blip). Click a
  step for a loud hit, again for a soft one, again to clear it.
- Tempo (40 to 240 bpm), swing, 8 to 32 steps, and mute and volume per row.
  Space plays and stops.
- **Save pattern** keeps the grid as JSON in
  `~/.local/share/forge/loops/patterns/`. The cross beside a saved pattern
  moves it to the desktop trash.
- **Export WAV** renders 1, 2, 4 or 8 repeats offline, in the page, at
  44.1 kHz stereo. Hits that ring past the end are folded into the start, so
  the WAV loops without a gap. It is written to `~/Music/Loops`, and a name in
  use gets " (2)": an export never replaces a file.

The sound is made by Web Audio in the page, so the backend only stores
patterns and writes WAVs. Nothing is fetched and no samples ship.

## Adding sounds

- A new instrument is one entry in `instruments.json`: an id, a label, the
  voice that plays it and that voice's params.
- A new kind of sound is one function in `static/voices.js` `VOICES`. There
  are four now: kick (a falling sine), snare (tone plus noise), noise
  (filtered noise bursts: clap, hats) and tone (an oscillator with optional
  pitch bend and low-pass: toms, bass, blip).

## Files

- `loops_core.py`: folders, pattern checks, saving, trash and export.
- `web_app.py`: the FastAPI routes, behind `forge_guard.LocalOnly`.
- `static/loops-logic.js`: timing, swing, resize, hits, the WAV encoder and
  the tail fold. It has no DOM, so `node --test tests/` runs it.
- `static/voices.js`: the sound makers and the master bus (a gain into a
  compressor, so a full row does not clip).
- `static/app.js`: the grid, the look-ahead scheduler, save, open and export.

## Settings

| Variable | Default | What |
|---|---|---|
| `LOOPS_DATA_DIR` | `~/.local/share/forge/loops` | saved patterns |
| `LOOPS_OUT_DIR` | `~/Music/Loops` | exported WAVs |
| `LOOPS_TRASH_CMD` | `gio trash` | stand-in used by the browser check |

## Checks

    .venv/bin/python -m pytest -q tests        # backend, 34 tests
    node --test tests/                         # page logic, 9 tests
    ~/Forge/apps/clipboard/.venv/bin/python tests/check_ui.py [SHOTS]   # headless Chrome
