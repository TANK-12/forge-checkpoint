"""Which Forge edition this is, and whether a feature is on in it.

The editions and their features are declared in shared/forge_editions.json
(one registry; adding a paid feature is one entry there plus one enabled()
call where it lives). The edition comes from the licence file
(shared/forge_licence.py): none or an invalid one means the registry's
default edition.

    import forge_edition
    forge_edition.enabled("beta_channel")   # True or False
    forge_edition.status("business_lock")   # "on", "hidden" or "read_only"
    forge_edition.describe()                # everything an About card shows

Decisions:
    - Declared, not yet enforced. No existing code path calls enabled() until
      the owner picks the editions: his own laptop has no licence, so it is the
      free edition, and gating business_lock today would take his Business
      look lock away. The Settings About card only shows describe().
    - A feature that is off is only hidden or read-only (its when_off), never
      anything that keeps a user from their own data.
    - expired and past_updates licences keep their edition's name on the
      About card, but its paid features fall back to their when_off until it
      is renewed.

The Forge version: FORGE_RELEASE when set (the portable launcher sets it from
release/release.json's "version", which every bundle ships), else that
registry file read directly, else "dev". A build's release date comes from
the registry's "released" field when it has one (not there yet: until then
no licence is ever past_updates).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import forge_licence

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "forge_editions.json"
RELEASE = HERE.parent / "release" / "release.json"
WHEN_OFF = ("hidden", "read_only")

LINES = {
    "free": "No licence file: this is {label}, free for personal use.",
    "valid": "Licensed to {licensee}: {label}{seats_text}.",
    "invalid": (
        "The licence file is not valid ({reason}), so this is {label}, "
        "free for personal use. Nothing of yours is touched."
    ),
    "expired": (
        "The {licensed_label} licence for {licensee} {reason}. Its features "
        "are paused until it is renewed; all your data stays as it is."
    ),
    "past_updates": (
        "The {licensed_label} licence for {licensee} {reason}, and this build "
        "is newer. Its features are paused; an older build still has them, "
        "and all your data stays as it is."
    ),
}


def load(path: Path | None = None) -> dict:
    return json.loads((path or REGISTRY).read_text(encoding="utf-8"))


def chain(edition: str, registry: dict | None = None) -> list[str]:
    """This edition and every edition it inherits, nearest first."""
    registry = registry or load()
    editions = registry["editions"]
    out: list[str] = []
    current: str | None = edition
    while current is not None:
        if current not in editions:
            raise ValueError(f"unknown edition {current!r}")
        if current in out:
            raise ValueError(f"editions inherit in a loop: {out + [current]}")
        out.append(current)
        current = editions[current].get("inherits")
    return out


def _release() -> tuple[str, str, dt.date | None]:
    """(version, where it came from, release date or None)."""
    released = None
    try:
        data = json.loads(RELEASE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    try:
        released = dt.date.fromisoformat(str(data.get("released")))
    except ValueError:
        released = None
    env = os.environ.get("FORGE_RELEASE")
    if env:
        return env, "FORGE_RELEASE (set by the portable launcher)", released
    if data.get("version"):
        return str(data["version"]), "release/release.json", released
    return "dev", "none found", released


def current(registry: dict | None = None, licence_state: dict | None = None) -> dict:
    """The edition in force, with the licence behind it."""
    registry = registry or load()
    if licence_state is None:
        licence_state = forge_licence.state(released=_release()[2])
    lic = licence_state.get("licence") or {}
    state = licence_state["state"]
    default = registry["default"]
    licensed = lic.get("edition") if state != "invalid" else None
    edition = licensed if state == "valid" and licensed else default
    editions = registry["editions"]
    label = editions[edition]["label"]
    licensed_label = editions[licensed]["label"] if licensed in editions else ""
    seats = lic.get("seats")
    line = LINES[state].format(
        label=label,
        licensed_label=licensed_label,
        licensee=lic.get("licensee", ""),
        reason=licence_state.get("reason", ""),
        seats_text=f", {seats} seats" if seats else "",
    )
    return {
        "edition": edition,
        "label": label,
        "licensed_edition": licensed,
        "licensed_label": licensed_label or None,
        "state": state,
        "line": line,
        "licensee": lic.get("licensee"),
        "seats": seats,
        "updates_until": lic.get("updates_until"),
        "expires": lic.get("expires"),
        "licence_id": lic.get("id"),
    }


def status(
    feature: str, registry: dict | None = None, edition: str | None = None
) -> str:
    """on, or the feature's when_off. An unknown feature raises KeyError."""
    registry = registry or load()
    spec = registry["features"][feature]
    edition = edition or current(registry)["edition"]
    if spec["edition"] in chain(edition, registry):
        return "on"
    return spec["when_off"]


def enabled(
    feature: str, registry: dict | None = None, edition: str | None = None
) -> bool:
    """True when this edition has the feature."""
    return status(feature, registry, edition) == "on"


def describe(registry: dict | None = None, licence_state: dict | None = None) -> dict:
    """Everything an About card needs, in one dict."""
    registry = registry or load()
    out = current(registry, licence_state)
    version, source, released = _release()
    out["version"] = version
    out["version_source"] = source
    out["released"] = released.isoformat() if released else None
    out["enforced"] = False
    out["features"] = [
        {
            "id": fid,
            "what": spec["what"],
            "edition": spec["edition"],
            "edition_label": registry["editions"][spec["edition"]]["label"],
            "owner": spec["owner"],
            "status": status(fid, registry, out["edition"]),
        }
        for fid, spec in registry["features"].items()
    ]
    return out
