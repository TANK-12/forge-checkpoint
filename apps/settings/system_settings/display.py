"""Display: screen brightness (brightnessctl) and night light (GNOME)."""

from __future__ import annotations

import re

from . import fields
from .runner import Run, must

COLOR = "org.gnome.settings-daemon.plugins.color"
KELVIN = (1700, 4700)  # what GNOME Settings' slider allows


def parse_brightness(raw: str) -> dict | None:
    """brightnessctl -m -> {device, percent, raw, max} for the backlight."""
    for line in raw.splitlines():
        parts = line.strip().split(",")
        if len(parts) == 5 and parts[1] == "backlight":
            now, top = int(parts[2]), int(parts[4])
            return {
                "device": parts[0],
                "percent": round(now * 100 / top) if top else 0,
                "raw": now,
                "max": top,
            }
    return None


def gvalue(raw: str):
    """One gsettings value: true/false, numbers (with or without a type
    word like 'uint32 3537') and quoted strings."""
    raw = raw.strip()
    if raw in ("true", "false"):
        return raw == "true"
    found = re.fullmatch(r"(?:u?int\d+|double)?\s*(-?\d+(?:\.\d+)?)", raw)
    if found:
        number = float(found.group(1))
        return int(number) if number.is_integer() else number
    return raw.strip("'")


def _get(run: Run, key: str):
    result = run(["gsettings", "get", COLOR, key], timeout=5)
    return gvalue(result.out) if result.ok else None


def status(run: Run) -> dict:
    shown = run(["brightnessctl", "-m", "-c", "backlight"], timeout=5)
    light = parse_brightness(shown.out) if shown.ok else None
    night = {
        key.removeprefix("night-light-").replace("-", "_"): _get(run, key)
        for key in (
            "night-light-enabled",
            "night-light-temperature",
            "night-light-schedule-automatic",
            "night-light-schedule-from",
            "night-light-schedule-to",
        )
    }
    return {
        "available": light is not None or night["enabled"] is not None,
        "brightness": light,
        "night_light": night if night["enabled"] is not None else None,
        "kelvin_range": list(KELVIN),
    }


def brightness(body: dict, run: Run) -> dict:
    level = fields.number(body, "percent", 1, 100)  # 0 would black the screen
    shown = parse_brightness(run(["brightnessctl", "-m", "-c", "backlight"]).out)
    if shown is None:
        raise ValueError("no backlight found")
    must(
        run(["brightnessctl", "-m", "-d", shown["device"], "set", f"{level}%"]),
        "could not set brightness",
    )
    return {"percent": level}


def _set(run: Run, key: str, value: str) -> None:
    must(run(["gsettings", "set", COLOR, key, value], timeout=5), "could not change it")


def night_light(body: dict, run: Run) -> dict:
    on = fields.flag(body, "enabled")
    _set(run, "night-light-enabled", "true" if on else "false")
    return {"enabled": on}


def night_temperature(body: dict, run: Run) -> dict:
    kelvin = fields.number(body, "kelvin", *KELVIN)
    _set(run, "night-light-temperature", f"uint32 {kelvin}")
    return {"kelvin": kelvin}


def night_schedule(body: dict, run: Run) -> dict:
    """Sunset to sunrise, or the hours in from/to (0 to 24, may be halves)."""
    automatic = fields.flag(body, "automatic")
    hours = {}
    for key in ("from", "to"):
        if key in body:
            hour = body[key]
            if isinstance(hour, bool) or not isinstance(hour, (int, float)):
                raise ValueError(f"{key} must be an hour, 0 to 24")
            if not 0 <= hour < 24:
                raise ValueError(f"{key} must be an hour, 0 to 24")
            hours[key] = float(hour)
    _set(run, "night-light-schedule-automatic", "true" if automatic else "false")
    for key, hour in hours.items():
        _set(run, f"night-light-schedule-{key}", str(hour))
    return {"automatic": automatic}


def defaults(body: dict, run: Run) -> dict:
    """Night light back to GNOME's defaults (off, sunset to sunrise, its
    warmth). The brightness is left where it is."""
    for key in (
        "night-light-enabled",
        "night-light-temperature",
        "night-light-schedule-automatic",
        "night-light-schedule-from",
        "night-light-schedule-to",
    ):
        must(run(["gsettings", "reset", COLOR, key], timeout=5), "could not reset it")
    return {"reset": "night light"}


ACTIONS = {
    "defaults": defaults,
    "brightness": brightness,
    "night_light": night_light,
    "night_temperature": night_temperature,
    "night_schedule": night_schedule,
}
