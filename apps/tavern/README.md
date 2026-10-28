# Tavern

Tabletop role-playing campaigns with Jan as the game master. Forge-built
(port 8496, section Play).

## What it does

- **Campaigns**: New campaign asks for a name, a world and the party (up to
  eight characters, each with a name and a role). Every campaign is kept
  and listed on the left; the last one open comes back on the next visit.
- **The story**: pick who acts, write what they do, and press Act (or
  Enter; Shift+Enter starts a new line). The action goes in the story and
  Jan answers as the game master. **GM, go on** asks Jan to continue without
  an action (on an empty story it opens the campaign with the world's
  opening scene). **Ask again** takes back the game master's last reply,
  including any HP it changed, and asks again. **Note** adds an
  out-of-character line that Jan reads but does not answer. **Story so
  far** shows the running summary (see below), bringing it up to date first.
- **Rolls**: when an outcome is uncertain, Jan asks for a roll with a tag
  (`[roll 1d20+2 Kai Charm]`). The tag is taken out of the text and shows
  as a button, "🎲 1d20+2 for Kai (Charm)"; pressing it rolls, puts the
  result in the story, and marks the button rolled (each ask can be
  rolled once). Jan reads the roll on its next turn. Dice are always
  rolled by the app, never by Jan.
- **HP**: Jan can hurt or heal the party with `[hp Juno -3]` / `[hp Juno
  +2]`, several at once as `[hp Juno -3, Kai -1]`; the change shows as a
  chip under the reply and moves the HP bar. HP stays between minus max HP
  and max HP. A name may be the full name or any part of it that fits only
  one character ("Vale" for Aria Vale). A tag naming nobody in the party,
  or two people at once, or a roll that cannot be rolled, is left in the
  text as written so the table can sort it out.
- **Party tab**: one card per character with an HP bar and −5 / −1 / +1 /
  +5 buttons, Edit and Remove (asks first). The form adds or edits a
  character: name, role, HP, max HP and notes (gear, quirks, goals). Jan is
  told every character's role, HP and notes on every turn.
- **Map tab**: grid maps (24 by 16 squares by default, up to 64 by 64).
  Pick a ground (floor, wall, grass, trees, water, road, door, fire) and
  click or drag to paint; pick Move to drag tokens. Each character starts
  with a token; Add makes another (a monster, a shopkeeper), and a picked
  token can be removed. A campaign can have several maps; the one shown is
  the one Jan is told about, in words ("Kai at column 13, row 6 (floor)").
- **Dice tab**: d4 to d100 and 2d6 buttons, plus any expression:
  `1d20+3`, `2d6 - 1`, `4d6kh3` (keep the three highest), `2d20kl1` (keep
  the lowest, for disadvantage). The last twelve rolls are listed.
- **Save the story** downloads the whole campaign as Markdown. **Move to
  trash** (asks first) puts the campaign file in the desktop trash with
  `gio trash`; nothing is deleted outright.
- **Jan models** (left, at the bottom): which Jan model writes the game
  master's replies and which writes the recaps. Empty means the first chat
  model Jan has. Models load when Tavern asks and are released after the
  idle time set there (`shared/forge_jan.py`).

## Keeping Jan's context small

Jan sees a system prompt (setting, tone, party, the map in words, the story
so far) and every entry not yet in that summary as a real back-and-forth
(players, rolls and notes as the user, the game master as the assistant).
Once more than 40 entries are not yet summarised, everything but the last
24 is folded into the story-so-far by one recap request before the next
reply, so Jan reads 24 to 40 entries word for word. A failed recap is
skipped and the game goes on with the older summary; if recaps keep
failing, Jan is shown at most the last 80 entries. The numbers are in
`tavern.json` (`story.recent`, `story.fold_at`).

## Worlds

`worlds/*.json`, one file each: `id` (the file name), `label`, `order`,
`blurb` (the setting Jan is given), `tone`, `roles` (suggested in the
forms), `hp` (a new character's max HP) and `opening` (what Jan is asked to
do on GM, go on with an empty story). Adding a world is one more file;
nothing else changes. There are four: sword and sorcery, starship crew,
city noir and gothic horror.

## Data

`~/.local/share/forge/tavern/campaigns/<id>.json`, one file per campaign,
written whole through a temporary file. `TAVERN_DATA_DIR` moves it.
Jan settings are in `~/.config/forge/jan/tavern.json` (shared Forge
place).

## API

| Method | Path | |
|---|---|---|
| GET | /api/state | worlds, terrain, map defaults, campaigns |
| POST | /api/campaigns | `{name, world, party: [{name, role}]}` |
| GET / DELETE | /api/campaigns/{id} | one campaign / move it to the trash |
| POST | /api/campaigns/{id}/turn | `{who, text}`; empty text: GM, go on |
| POST | /api/campaigns/{id}/retry | Ask again |
| POST | /api/campaigns/{id}/recap | bring the summary up to date |
| POST | /api/campaigns/{id}/say | `{who, text, kind: say or note}`, no Jan |
| POST | /api/campaigns/{id}/roll | `{expr, who, why, ask: "<n>.<i>"}` |
| POST | /api/campaigns/{id}/party | add or (with `id`) edit a character |
| DELETE | /api/campaigns/{id}/party/{pid} | remove a character |
| POST | /api/campaigns/{id}/party/{pid}/hp | `{delta}` |
| POST | /api/campaigns/{id}/maps | `{name, w, h}` |
| PUT | /api/campaigns/{id}/maps/{mid} | `{name?, cells?, tokens?}`; shows it |
| GET | /api/campaigns/{id}/export | Markdown |

Errors are `{detail}`: 400 for bad input, 409 while the game master is
still writing (a turn, Ask again, the recap and Move to trash all wait for
it), 503 when Jan cannot answer. Ask again keeps the old reply until the
new one is in hand, so a failure changes nothing. Only Forge's own pages can call
it (`shared/forge_guard.py`).

## Checks

    .venv/bin/python -m pytest -q tests           # rules, with a fake Jan
    .venv/bin/python tests/check_ui.py [SHOTS]    # headless Chrome, fake Jan

check_ui runs a small local server that speaks Jan's API, so no model is
loaded. Its campaigns live in `~/.cache/forge-checks/tavern-data`, because
`gio trash` cannot trash inside `/tmp`; the Move to trash check leaves one
small file in the desktop trash per run.
