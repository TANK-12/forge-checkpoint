"""Paths, settings, and the three stacked modes.

Emberfield is built so the base game is complete on its own. Voice and the LLM
director are additive layers on top of it, each independently switchable, and
neither is ever required for the game to be playable:

    base   text and sound effects only, entirely deterministic
    voice  + pre-generated narrator and main-NPC lines, played from cache
    llm    + the director model shaping events, quests, wilds and economy

Settings live outside the app directory, in ~/EmberfieldData, following the
convention the other Forge apps use (~/NovelMakerData, ~/MediaForgeData).
"""

import json
import os

# $EMBERFIELD_DATA moves it (a Forge release keeps it in its own data folder).
DATA_ROOT = os.environ.get("EMBERFIELD_DATA") or os.path.join(
    os.path.expanduser("~"), "EmberfieldData"
)
SAVES_DIR = os.path.join(DATA_ROOT, "saves")
VOICE_CACHE = os.path.join(DATA_ROOT, "voice_cache")
SETTINGS_PATH = os.path.join(DATA_ROOT, "settings.json")

# Voice models already live in NovelForge's data directory; Emberfield reuses
# them rather than downloading a second 453 MB copy.
TTS_VOICES_DIR = os.path.join(os.path.expanduser("~"), "NovelMakerData", "tts_voices")

DEFAULTS = {
    # --- experiment toggles ---
    "llm_mode": "off",  # off | npcs | director | full
    "voice_mode": "off",  # off | narrator | narrator_and_main
    # --- model choices, matched to what is on disk ---
    "director_model": "",  # blank means "whatever Jan currently has loaded"
    "npc_model": "",
    "jan_base": "http://127.0.0.1:1337/v1",
    # --- resource budget ---
    # This laptop has 10 physical cores (2 performance, 8 efficiency) and an
    # iGPU that shares the same memory bus as the CPU. See resources.py.
    "heavy_cores": 6,
    "serialise_heavy_work": True,
    "voice_bake_budget_mb": 200,
    # --- time ---
    # Real seconds for one full in-game day. Minecraft's day is 20 minutes;
    # this sits a little under that. It was 12 *seconds* by accident in session
    # 1 -- MINUTES_PER_SECOND was multiplied by 60 a second time in the step
    # loop -- which made a day pass faster than you could cross the valley.
    # Exposed as a setting because it is the single most useful dial to move
    # while testing anything that depends on days passing.
    "day_seconds": 900,
    # --- sound ---
    # Every effect is synthesised from a recipe in the content store; there are
    # no audio files anywhere in the project. See static/audio.js.
    "volume": 70,
    "muted": False,
    # --- presentation ---
    "palette": "emberfield-spring",
    "zoom": 3,
    "show_grid": False,
    "shadows": True,
    "advanced_mode": False,
}


def ensure_dirs():
    for path in (DATA_ROOT, SAVES_DIR, VOICE_CACHE):
        os.makedirs(path, exist_ok=True)
    return DATA_ROOT


# Numbers the game divides by or pins cores with, held to a sane range so a
# stray value cannot stall a day or ask for zero cores.
RANGES = {
    "heavy_cores": (1, 64),
    # The same as the Settings sliders, so a value the page cannot show is
    # never stored behind its back.
    "day_seconds": (60, 1800),
    "volume": (0, 100),
    "zoom": (2, 5),
    "voice_bake_budget_mb": (0, 100000),
}


def clean_settings(values):
    """Check a settings patch against the types in DEFAULTS.

    Returns (clean, problems). A key must be one of DEFAULTS and keep its
    default's type (a whole number for a number, true/false for a switch, text
    of up to 500 characters for text); numbers are clamped into RANGES. An
    unknown key is refused: the page only sends known ones, and anything else
    would sit in settings.json forever. One wrong value used to be stored as sent, and
    a string in heavy_cores then broke /api/capabilities -- and with it the
    game's boot -- until the file was edited by hand.
    """
    clean, problems = {}, []
    for key, value in values.items():
        default = DEFAULTS.get(key)
        if key not in DEFAULTS:
            problems.append(f"{str(key)[:40]}: not a setting")
        elif isinstance(default, bool):
            if isinstance(value, bool):
                clean[key] = value
            else:
                problems.append(f"{key}: must be true or false")
        elif isinstance(default, int):
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            if isinstance(value, int) and not isinstance(value, bool):
                low, high = RANGES.get(key, (value, value))
                clean[key] = max(low, min(high, value))
            else:
                problems.append(f"{key}: must be a whole number")
        elif isinstance(value, str) and len(value) <= 500:
            clean[key] = value
        else:
            problems.append(f"{key}: must be text")
    return clean, problems


def load_settings():
    data = dict(DEFAULTS)
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            if isinstance(stored, dict):
                # A bad value already on disk falls back to its default
                # instead of breaking every page load after it.
                data.update(clean_settings(stored)[0])
        except (OSError, ValueError):
            pass  # a corrupt settings file must never stop the game booting
    return data


def save_settings(settings):
    ensure_dirs()
    tmp = SETTINGS_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=2)
        os.replace(tmp, SETTINGS_PATH)
    except OSError:
        return False
    return True
