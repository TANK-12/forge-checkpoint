"""Sound: output and input devices with volume and mute (pactl, PipeWire)."""

from __future__ import annotations

import json

from . import fields
from .runner import Run, must

KINDS = {"output": "sink", "input": "source"}


def _volume(entry: dict) -> int:
    levels = [
        int(str(ch.get("value_percent", "0")).rstrip("%") or 0)
        for ch in (entry.get("volume") or {}).values()
        if isinstance(ch, dict)
    ]
    return round(sum(levels) / len(levels)) if levels else 0


def parse_devices(raw: str, default: str, inputs: bool = False) -> list[dict]:
    """pactl -f json list sinks|sources -> [{name, label, volume, mute, default}].
    Monitor sources (what an output plays, seen as an input) are left out."""
    try:
        data = json.loads(raw or "[]")
    except ValueError:
        return []
    out = []
    for entry in data if isinstance(data, list) else []:
        props = entry.get("properties") or {}
        if inputs and (
            props.get("device.class") == "monitor"
            or str(entry.get("name", "")).endswith(".monitor")
        ):
            continue
        out.append(
            {
                "name": entry.get("name", ""),
                "label": entry.get("description") or entry.get("name", ""),
                "volume": _volume(entry),
                "mute": bool(entry.get("mute")),
                "default": entry.get("name") == default,
                "port": entry.get("active_port") or "",
            }
        )
    return out


def status(run: Run) -> dict:
    out: dict = {}
    for kind, pa in KINDS.items():
        listed = run(["pactl", "-f", "json", "list", pa + "s"])
        if not listed.ok:
            return {"available": False, "why": listed.text() or "pactl failed"}
        default = run(["pactl", f"get-default-{pa}"]).out.strip()
        out[kind + "s"] = parse_devices(listed.out, default, inputs=kind == "input")
    out["available"] = True
    return out


def _device(body: dict, run: Run) -> tuple[str, str]:
    kind = fields.text(body, "kind", KINDS)
    names = [d["name"] for d in status(run).get(kind + "s", [])]
    return KINDS[kind], fields.text(body, "name", names)


def set_default(body: dict, run: Run) -> dict:
    pa, name = _device(body, run)
    must(run(["pactl", f"set-default-{pa}", name]), "could not switch device")
    return {"default": name}


def set_volume(body: dict, run: Run) -> dict:
    pa, name = _device(body, run)
    level = fields.number(body, "percent", 0, 150)
    must(run(["pactl", f"set-{pa}-volume", name, f"{level}%"]), "could not set volume")
    return {"volume": level}


def set_mute(body: dict, run: Run) -> dict:
    pa, name = _device(body, run)
    mute = fields.flag(body, "mute")
    must(run(["pactl", f"set-{pa}-mute", name, "1" if mute else "0"]), "could not mute")
    return {"mute": mute}


ACTIONS = {"default": set_default, "volume": set_volume, "mute": set_mute}
