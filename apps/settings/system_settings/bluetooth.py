"""Bluetooth: the adapter, known and nearby devices (bluetoothctl), and the
radio's rfkill block (rfkill): blocked, Dell's adapter vanishes and
bluetoothctl only says "No default controller available"."""

from __future__ import annotations

import json
import re
import time

from . import fields
from .runner import CommandFailed, Run, must

MAC = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
DEVICE = re.compile(r"^Device ([0-9A-F:]{17}) ?(.*)$")


def parse_show(raw: str) -> dict:
    """bluetoothctl show -> {address, name, powered, discovering}."""
    info: dict = {}
    head = re.search(r"Controller ([0-9A-F:]{17})", raw)
    if head:
        info["address"] = head.group(1)
    for line in raw.splitlines():
        key, _, value = line.strip().partition(": ")
        if key in ("Name", "Alias", "Powered", "Discovering", "Pairable"):
            info[key.lower()] = value.strip()
    return {
        "address": info.get("address", ""),
        "name": info.get("alias") or info.get("name", ""),
        "powered": info.get("powered") == "yes",
        "discovering": info.get("discovering") == "yes",
    }


def parse_devices(raw: str) -> dict[str, str]:
    """bluetoothctl devices [Paired|Connected] -> {mac: name}. Lines that
    are not a plain device line (scan chatter like [NEW]) are skipped."""
    out = {}
    for line in raw.splitlines():
        found = DEVICE.match(line.strip())
        if found:
            mac, name = found.groups()
            out[mac] = name.strip() or mac
    return out


def parse_info(raw: str) -> dict:
    """bluetoothctl info MAC -> {icon, battery} (what the list adds)."""
    out: dict = {}
    for line in raw.splitlines():
        key, _, value = line.strip().partition(": ")
        if key == "Icon":
            out["icon"] = value.strip()
        elif key == "Battery Percentage":
            found = re.search(r"\((\d+)\)", value)
            if found:
                out["battery"] = int(found.group(1))
    return out


def parse_rfkill(raw: str) -> str:
    """`rfkill -J -o TYPE,SOFT,HARD` -> "hard", "soft" or "" for Bluetooth.
    The list is under "rfkilldevices" (util-linux 2.42) or "" (older)."""
    try:
        data = json.loads(raw)
    except ValueError:
        return ""
    rows = next((v for v in data.values() if isinstance(v, list)), [])
    radios = [r for r in rows if isinstance(r, dict) and r.get("type") == "bluetooth"]
    if any(r.get("hard") == "blocked" for r in radios):
        return "hard"
    if any(r.get("soft") == "blocked" for r in radios):
        return "soft"
    return ""


def blocked(run: Run) -> str:
    """Whether the Bluetooth radio is blocked: "hard" (a switch or the BIOS),
    "soft" (airplane mode, the quick settings, `rfkill block`) or ""."""
    got = run(["rfkill", "-J", "-o", "TYPE,SOFT,HARD"], timeout=5)
    return parse_rfkill(got.out) if got.ok else ""


WHY_BLOCKED = {
    "soft": "Bluetooth is switched off (airplane mode or the Bluetooth switch "
    "in the quick settings)",
    "hard": "Bluetooth is switched off by the laptop's hardware switch or its "
    "BIOS, which Forge cannot turn on",
}


def status(run: Run) -> dict:
    shown = run(["bluetoothctl", "show"], timeout=5)
    if not shown.ok or "Controller" not in shown.out:
        block = blocked(run)
        why = WHY_BLOCKED.get(block) or shown.text() or "no Bluetooth adapter"
        return {"available": False, "blocked": block, "why": why}
    adapter = parse_show(shown.out)
    every = parse_devices(run(["bluetoothctl", "devices"], timeout=5).out)
    paired = parse_devices(run(["bluetoothctl", "devices", "Paired"], timeout=5).out)
    connected = parse_devices(
        run(["bluetoothctl", "devices", "Connected"], timeout=5).out
    )
    devices = []
    for mac, name in every.items():
        entry = {
            "mac": mac,
            "name": name,
            "paired": mac in paired,
            "connected": mac in connected,
        }
        if entry["connected"]:
            entry.update(parse_info(run(["bluetoothctl", "info", mac], timeout=5).out))
        devices.append(entry)
    devices.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
    return dict(adapter, available=True, devices=devices)


def _mac(body: dict) -> str:
    mac = str(body.get("mac", "")).upper()
    if not MAC.match(mac):
        raise ValueError("mac must look like AA:BB:CC:DD:EE:FF")
    return mac


def _said_ok(result, what: str) -> None:
    """bluetoothctl sometimes exits 0 after a failure; read what it said."""
    must(result, what)
    if re.search(r"Failed|not available|Error", result.out):
        last = [ln.strip() for ln in result.out.splitlines() if ln.strip()]
        raise CommandFailed(f"{what}: {last[-1] if last else 'failed'}")


def power(body: dict, run: Run) -> dict:
    on = fields.flag(body, "on")
    # A blocked radio refuses `power on` (org.bluez.Error.Blocked).
    if on and blocked(run) == "soft":
        must(run(["rfkill", "unblock", "bluetooth"], timeout=5), "could not switch")
    _said_ok(run(["bluetoothctl", "power", "on" if on else "off"]), "could not switch")
    return {"powered": on}


def _pause(seconds: float) -> None:
    time.sleep(seconds)


def unblock(body: dict, run: Run) -> dict:
    """Turn Bluetooth on from "switched off": lift the radio's soft block,
    wait (up to 6 s) for the adapter to come back, then power it on."""
    if blocked(run) == "hard":
        raise CommandFailed(WHY_BLOCKED["hard"])
    must(run(["rfkill", "unblock", "bluetooth"], timeout=5), "could not turn it on")
    for _ in range(12):
        shown = run(["bluetoothctl", "show"], timeout=5)
        if shown.ok and "Controller" in shown.out:
            break
        _pause(0.5)
    else:
        raise CommandFailed(
            "the radio is on, but no Bluetooth adapter appeared yet: "
            "read the panel again in a moment"
        )
    _said_ok(run(["bluetoothctl", "power", "on"]), "on, but could not power it")
    return {"unblocked": True}


def scan(body: dict, run: Run) -> dict:
    seconds = fields.number(body, "seconds", 3, 30) if "seconds" in body else 10
    run(["bluetoothctl", "--timeout", str(seconds), "scan", "on"], timeout=seconds + 10)
    return {"scanned": seconds}


def pair(body: dict, run: Run) -> dict:
    mac = _mac(body)
    _said_ok(
        run(
            [
                "bluetoothctl",
                "--agent",
                "NoInputNoOutput",
                "--timeout",
                "30",
                "pair",
                mac,
            ],
            timeout=45,
        ),
        "could not pair",
    )
    run(["bluetoothctl", "trust", mac], timeout=10)
    _said_ok(
        run(["bluetoothctl", "connect", mac], timeout=30),
        "paired, but could not connect",
    )
    return {"paired": mac}


def connect(body: dict, run: Run) -> dict:
    mac = _mac(body)
    _said_ok(run(["bluetoothctl", "connect", mac], timeout=30), "could not connect")
    return {"connected": mac}


def disconnect(body: dict, run: Run) -> dict:
    mac = _mac(body)
    _said_ok(
        run(["bluetoothctl", "disconnect", mac], timeout=15), "could not disconnect"
    )
    return {"disconnected": mac}


def remove(body: dict, run: Run) -> dict:
    mac = _mac(body)
    _said_ok(run(["bluetoothctl", "remove", mac], timeout=15), "could not forget it")
    return {"removed": mac}


def remove_all(body: dict, run: Run) -> dict:
    """Forget every paired device."""
    shown = run(["bluetoothctl", "show"], timeout=5)
    if not shown.ok or "Controller" not in shown.out:
        raise CommandFailed(
            "Bluetooth is off, so its devices cannot be forgotten now: turn it on first"
        )
    paired = parse_devices(run(["bluetoothctl", "devices", "Paired"], timeout=5).out)
    gone, failed = [], []
    for mac, name in paired.items():
        try:
            _said_ok(run(["bluetoothctl", "remove", mac], timeout=15), "no")
            gone.append(name)
        except CommandFailed:
            failed.append(name)
    if failed:
        raise CommandFailed(f"could not forget {', '.join(failed)}")
    return {"removed": gone}


ACTIONS = {
    "power": power,
    "unblock": unblock,
    "scan": scan,
    "pair": pair,
    "connect": connect,
    "disconnect": disconnect,
    "remove": remove,
    "remove_all": remove_all,
}
