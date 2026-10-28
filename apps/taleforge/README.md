# Taleforge

A data-driven text RPG engine for the Forge hub. The engine owns every rule and
number (d20 checks, HP, gold, inventory, affection, quest state); Jan, the local
LLM, only retells what the engine already decided. With Jan off or slow the game
plays the same, using the hand-written text.

Port 8502, section "play" in the hub. Saves live in
`~/.local/share/forge/taleforge/saves/` (set `TALEFORGE_DATA` to use another
folder, as the tests do). Deleted saves go to a `trash/` folder beside them.

## Layout

| path | what |
|---|---|
| `web_app.py` | FastAPI app: campaigns, character creation, saves, `act`, Jan entries, settings |
| `taleforge/world.py` | loads a campaign folder plus its ruleset; `validate()` finds broken references |
| `taleforge/core.py` | game state, the condition language (`when`) and effect language (`effects`), quests, scenes |
| `taleforge/game.py` | `Game.act()`: every player action, then reactions, quest updates, romance arc triggers |
| `taleforge/combat.py` | turn-based combat, abilities, companions in fights, defeat |
| `taleforge/rules.py`, `dice.py` | character building, levels, modifiers, dice expressions, d20 with advantage |
| `taleforge/parser.py` | free text to an action ("talk to hollis", "go to the docks", `"Hello"`, "flirt with lyra") |
| `taleforge/generator.py` | job-board quests built from `templates/` so the world never runs dry |
| `taleforge/narrator.py` | Jan worker: prompts, the guard (`clean`), on-disk model check, fallback |
| `taleforge/view.py` | what the page sees of a game |
| `static/` | the page: home, character creation, play (log + side panel) |
| `rulesets/` | `d20-fantasy.json`, `d20-neon.json`: abilities, skills, classes, backgrounds, DCs, levels, words for tones |
| `campaigns/` | `hollow-crown/` (fantasy romance, the big one), `neon-debt/` (small cyberpunk proof that the engine is genre-free) |
| `tools/validate.py` | `.venv/bin/python tools/validate.py campaigns/hollow-crown` |
| `tools/model_bench.py` | times Jan models on Taleforge's own prompts: tok/s, seconds a line, what the guard keeps |
| `tools/playthrough.py` | plays turns against a running server and prints the fallback next to Jan's text |
| `docs/CONTENT.md` | the content format (authoritative) |
| `docs/STORY.md` | Hollow Crown story bible: acts, regions, flags that cross regions, planned companions |

## Adding content

A new campaign or genre is files only: a folder under `campaigns/` with a
`campaign.json` naming its ruleset, plus `regions/ locations/ npcs/ companions/
quests/ scenes/ items/ monsters/ factions/ templates/`. A new rule set is one
JSON file in `rulesets/`. Run `tools/validate.py` until it reports 0 problems;
`tests/test_content.py` fails on any problem in any campaign.

## Jan

Two roles, each its own per-app setting in the Jan panel on the home screen
(stored in `~/.config/forge/jan/taleforge.json`, never in Jan's own settings):
`dialogue` (characters) and `narration` (places, fights, freeform actions).
Both roles use LFM2.5 1.2B Instruct (`LFM2_5-1_2B-Instruct-Q5_K_M`, CPU) since
2026-10-24: about 4 s a line against 19 s for the 4B (bench in
`~/Forge/docs/library/models/2026-10-24-taleforge-small-model.md`). The narrator
only uses a model whose file is on disk *and* that Jan's router lists; the router
reads its list once at start, so a newly added model is used after the router
next starts, with the 4B until then (the home screen says so).
Models load through `shared/forge_jan.py` on demand and unload when idle.
Requests carry their own temperature and token limits. Jan's text arrives after
the turn; the hand-written line shows first and is replaced when Jan answers.
`clean()` drops sentences with numbers, rule words or "what do you do?", so Jan
cannot state a different HP or roll than the engine.

## Running checks

    .venv/bin/python -m pytest -q tests          # 74 tests, no Jan needed
                                                 # (test_logic_js runs tests/logic.test.js
                                                 # under node: static/logic.js, the skill picker)
    .venv/bin/python tools/validate.py           # every campaign
    TALEFORGE_DATA=/tmp/tf .venv/bin/python -m uvicorn web_app:app --port 8502
    .venv/bin/python tools/playthrough.py "talk to hollis" "go to the docks" "1" "attack"

Pages: `/`, `/?new=hollow-crown` (character creation), `/?save=<id>`.
