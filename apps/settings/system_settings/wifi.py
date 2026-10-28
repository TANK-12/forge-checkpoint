"""Wi-Fi: networks in range, saved networks and the radio (nmcli)."""

from __future__ import annotations

import re

from . import fields
from .runner import CommandFailed, Run, must


def split_terse(line: str) -> list[str]:
    """One nmcli -t line into its fields: ':' separates, '\\:' and '\\\\'
    are a literal colon and backslash (BSSIDs and some names have them)."""
    out, cur, i = [], [], 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def parse_networks(raw: str) -> list[dict]:
    """nmcli -t -f IN-USE,SSID,BSSID,SIGNAL,SECURITY,CHAN device wifi list
    -> one entry per name (the strongest access point), hidden ones left out."""
    best: dict[str, dict] = {}
    for line in raw.splitlines():
        parts = split_terse(line)
        if len(parts) < 6 or not parts[1]:
            continue
        in_use, ssid, bssid, signal, security, chan = parts[:6]
        entry = {
            "ssid": ssid,
            "signal": int(signal) if signal.isdigit() else 0,
            "secure": bool(security.strip()) and security.strip() != "--",
            "security": security.strip(),
            "band": "5 GHz" if chan.isdigit() and int(chan) > 14 else "2.4 GHz",
            "active": in_use.strip() == "*",
            "bssid": bssid,
        }
        old = best.get(ssid)
        if (
            old is None
            or entry["active"]
            or (not old["active"] and entry["signal"] > old["signal"])
        ):
            best[ssid] = entry
    return sorted(best.values(), key=lambda n: (not n["active"], -n["signal"]))


def parse_saved(raw: str) -> list[dict]:
    """nmcli -t -f NAME,UUID,TYPE,ACTIVE connection show -> Wi-Fi ones."""
    out = []
    for line in raw.splitlines():
        parts = split_terse(line)
        if len(parts) >= 4 and parts[2] == "802-11-wireless":
            out.append(
                {"name": parts[0], "uuid": parts[1], "active": parts[3] == "yes"}
            )
    return out


def parse_devices(raw: str) -> list[dict]:
    """nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device -> the Wi-Fi devices."""
    out = []
    for line in raw.splitlines():
        parts = split_terse(line)
        if len(parts) >= 4 and parts[1] == "wifi":
            out.append({"device": parts[0], "state": parts[2], "connection": parts[3]})
    return out


def status(run: Run) -> dict:
    radio = run(["nmcli", "radio", "wifi"], timeout=5)
    if not radio.ok:
        return {"available": False, "why": radio.text() or "nmcli failed"}
    devices = parse_devices(
        run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"]).out
    )
    networks = parse_networks(
        run(
            [
                "nmcli",
                "-t",
                "-f",
                "IN-USE,SSID,BSSID,SIGNAL,SECURITY,CHAN",
                "device",
                "wifi",
                "list",
                "--rescan",
                "no",
            ]
        ).out
    )
    saved = parse_saved(
        run(["nmcli", "-t", "-f", "NAME,UUID,TYPE,ACTIVE", "connection", "show"]).out
    )
    names = {s["name"] for s in saved}
    for net in networks:
        net["saved"] = net["ssid"] in names
    return {
        "available": bool(devices),
        "why": "" if devices else "no Wi-Fi device",
        "radio": radio.out.strip() == "enabled",
        "devices": devices,
        "networks": networks,
        "saved": saved,
    }


def rescan(body: dict, run: Run) -> dict:
    run(["nmcli", "device", "wifi", "rescan"], timeout=15)  # refused if too soon
    return {"rescanned": True}


def connect(body: dict, run: Run) -> dict:
    """A saved network comes up with its stored password; a new one needs
    the password in the body (open networks need none)."""
    ssid = fields.text(body, "ssid")
    saved = parse_saved(
        run(["nmcli", "-t", "-f", "NAME,UUID,TYPE,ACTIVE", "connection", "show"]).out
    )
    known = next((s for s in saved if s["name"] == ssid), None)
    if known:
        cmd = ["nmcli", "connection", "up", "uuid", known["uuid"]]
    else:
        cmd = ["nmcli", "device", "wifi", "connect", ssid]
        password = body.get("password")
        if password:
            if not isinstance(password, str) or not (
                8 <= len(password) <= 63 or re.fullmatch(r"[0-9A-Fa-f]{64}", password)
            ):
                raise ValueError(
                    "a Wi-Fi password is 8 to 63 characters (or a 64-digit hex key)"
                )
            cmd += ["password", password]
    must(run(cmd, timeout=45), f"could not join {ssid}")
    return {"connected": ssid}


def forget(body: dict, run: Run) -> dict:
    saved = parse_saved(
        run(["nmcli", "-t", "-f", "NAME,UUID,TYPE,ACTIVE", "connection", "show"]).out
    )
    uuid = fields.text(body, "uuid", {s["uuid"] for s in saved})
    must(
        run(["nmcli", "connection", "delete", "uuid", uuid], timeout=15),
        "could not forget it",
    )
    return {"forgotten": uuid}


def forget_all(body: dict, run: Run) -> dict:
    """Forget every saved Wi-Fi network; with keep_current (the default) the
    one in use stays, so the laptop is not cut off by its own reset."""
    keep = fields.flag(body, "keep_current") if "keep_current" in body else True
    saved = parse_saved(
        run(["nmcli", "-t", "-f", "NAME,UUID,TYPE,ACTIVE", "connection", "show"]).out
    )
    gone, kept, failed = [], [], []
    for net in saved:
        if keep and net["active"]:
            kept.append(net["name"])
            continue
        done = run(["nmcli", "connection", "delete", "uuid", net["uuid"]], timeout=15)
        (gone if done.ok else failed).append(net["name"])
    if failed:
        raise CommandFailed(f"could not forget {', '.join(failed)}")
    return {"forgotten": gone, "kept": kept}


def radio(body: dict, run: Run) -> dict:
    on = fields.flag(body, "on")
    must(
        run(["nmcli", "radio", "wifi", "on" if on else "off"]), "could not switch Wi-Fi"
    )
    return {"radio": on}


ACTIONS = {
    "rescan": rescan,
    "connect": connect,
    "forget": forget,
    "forget_all": forget_all,
    "radio": radio,
}
