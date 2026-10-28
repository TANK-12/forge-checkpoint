# Prompts

A library for the prompts you write for other tools: Suno songs, AI Studio
pictures, Claude and Jan chats. Port 8493, section Create. Forge-built
(Relay task 241, app 34 of the fifty-apps plan,
`~/Forge/docs/library/plans/2026-10-20-fifty-apps-and-store.md`).

## Using it

- **New prompt**, pick its target, give it a title and tags, fill the boxes
  (Suno has Style and Lyrics; AI Studio has Prompt and Negative prompt;
  Claude and Jan have System prompt and Prompt; Other has one box).
  **Save** (or Ctrl+S) keeps it as v1.
- Every later save that changes the text makes a new version; the note box
  says what changed. Saving the same text again keeps the version number.
- **Versions** on the right lists them newest first. Opening one shows the
  lines removed and added against the version before; **Load into the
  editor** puts an old version back in the boxes (Save makes it the newest).
- Write `{{city}}` or `{{mood}}` in the text and a box appears for each.
  **Copy** beside a box copies its text with the values filled in.
- **What came out**: a note of the result, the version it came from, a
  rating out of five and a link or file path. Remove hides a result (it
  stays in the export).
- Search matches every word against the title, tags and the newest text.
  The chips show one target. **Archive** hides a prompt from the library;
  tick Archived to see those. Nothing is deleted.
- **Export all** downloads every prompt, version and result (hidden ones
  too) as `prompts.json`.

## Files

| File | What it is |
|---|---|
| `targets.json` | the registry of targets and their boxes; a new target is one entry here |
| `prompts_core.py` | storage (SQLite) and every check |
| `web_app.py` | the FastAPI routes, behind `shared/forge_guard.py` |
| `static/` | the page; `prompts-logic.js` (variables, fill, tags, line diff) has no DOM and is tested with `node --test` |
| `tests/` | `test_prompts.py` (pytest), `logic.test.mjs`, `check_ui.py` (headless Chrome) |

Data: `~/.local/share/forge/prompts/prompts.sqlite3` (`PROMPTS_DATA_DIR`
overrides it). Changing a prompt's target is allowed only when its newest
text fits the new target's boxes.

## Checks

```
.venv/bin/python -m pytest -q tests
node --test tests/
~/Forge/apps/clipboard/.venv/bin/python tests/check_ui.py [SHOTS_DIR]
```
