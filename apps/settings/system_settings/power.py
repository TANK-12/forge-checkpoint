"""Battery: charge, charger and power profile (upower, powerprofilesctl).
Read-only here: CPU caps and profiles are the Power app's, so the page links
to it instead of changing them behind its back."""

from __future__ import annotations

from .runner import Run


def parse_upower(raw: str) -> dict:
    """upower -i <device> -> its 'key: value' lines."""
    out = {}
    for line in raw.splitlines():
        key, sep, value = line.strip().partition(":")
        if sep and value.strip():
            out[key.strip()] = value.strip()
    return out


def _percent(text: str | None) -> float | None:
    try:
        return round(float((text or "").rstrip("%")), 1)
    except ValueError:
        return None


def status(run: Run) -> dict:
    listed = run(["upower", "-e"], timeout=5)
    if not listed.ok:
        return {"available": False, "why": listed.text() or "upower failed"}
    paths = listed.out.split()
    battery = next((p for p in paths if "/battery_" in p), None)
    chargers = [p for p in paths if "/line_power_" in p]
    out: dict = {"available": True, "battery": None, "on_power": None}
    if battery:
        info = parse_upower(run(["upower", "-i", battery], timeout=5).out)
        out["battery"] = {
            "percent": _percent(info.get("percentage")),
            "state": info.get("state", ""),
            "time_to_empty": info.get("time to empty"),
            "time_to_full": info.get("time to full"),
            "health": _percent(info.get("capacity")),
            "watts": info.get("energy-rate"),
        }
    for path in chargers:
        info = parse_upower(run(["upower", "-i", path], timeout=5).out)
        if info.get("online") == "yes":
            out["on_power"] = True
            break
        out["on_power"] = False
    profile = run(["powerprofilesctl", "get"], timeout=5)
    out["profile"] = profile.out.strip() if profile.ok else None
    return out


ACTIONS: dict = {}
