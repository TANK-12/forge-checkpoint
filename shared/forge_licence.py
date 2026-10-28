"""Forge's licence file: read it, check its signature, install and remove it.

A licence file is JSON holding a licence and its Ed25519 signature:

    {"licence": {"v": 1, "id": "FL-2026-0001", "edition": "business",
                 "licensee": "Example Pty Ltd", "seats": 5,
                 "issued": "2026-11-01", "updates_until": "2028-11-01",
                 "expires": null, "key": "k1"},
     "sig": "base64 signature over canonical(licence)"}

canonical() is the licence as JSON with sorted keys and no spaces. The
signature is checked offline with shared/forge_ed25519.py against the public
key named by "key" in shared/forge_licence_keys.json. Nothing is ever sent
anywhere. Licences are signed on the owner's laptop with
tools/forge_licence_sign.py.

Decisions:
    - No real signing key exists yet. forge_licence_keys.json ships with an
      empty key set, so every licence is "invalid" and Forge stays free until
      the owner runs the tool's keygen and pastes the public key in.
    - FORGE_LICENCE_KEYS names another keys file and FORGE_LICENCE_FILE
      another licence path (tests use both with a scratch key).
    - The licence lives in Forge's config folder, beside settings.json:
      FORGE_CONFIG's folder when that is set (the portable launcher sets it to
      forge_portable.data_dirs()["config"]/settings.json, so on Windows it is
      %APPDATA%/Forge, on macOS ~/Library/Application Support/Forge), else
      ~/.config/forge/licence.json, the source tree's own config folder.

States (state() and check() return {"state", "reason", "licence"}):
    free          no licence file
    valid         signature good, not expired, covers this build
    invalid       unreadable, malformed, unknown key or edition, bad signature
    expired       signature good but "expires" has passed
    past_updates  signature good but this build was released after
                  "updates_until" (the licence still covers older builds)

None of these ever keeps anyone from their data: shared/forge_edition.py
turns a state into features, and a feature that is off is only hidden or
read-only.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path

import forge_ed25519

HERE = Path(__file__).resolve().parent
KEYS_FILE = HERE / "forge_licence_keys.json"
EDITIONS_FILE = HERE / "forge_editions.json"
FIELDS = {"v", "id", "edition", "licensee", "seats", "issued", "updates_until"}
FIELDS |= {"expires", "key"}


def licence_path() -> Path:
    """Where this Forge keeps its licence file."""
    override = os.environ.get("FORGE_LICENCE_FILE")
    if override:
        return Path(override)
    config = os.environ.get("FORGE_CONFIG")
    if config:
        return Path(config).parent / "licence.json"
    return Path.home() / ".config" / "forge" / "licence.json"


def canonical(licence: dict) -> bytes:
    """The exact bytes a licence's signature covers."""
    return json.dumps(
        licence, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def load_keys() -> dict[str, bytes]:
    """Key id to 32-byte public key; malformed entries are left out."""
    path = Path(os.environ.get("FORGE_LICENCE_KEYS") or KEYS_FILE)
    try:
        raw = json.loads(path.read_text(encoding="utf-8")).get("keys") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    keys = {}
    for kid, value in raw.items() if isinstance(raw, dict) else []:
        try:
            key = bytes.fromhex(value)
        except (TypeError, ValueError):
            continue
        if len(key) == 32:
            keys[str(kid)] = key
    return keys


def known_editions() -> set[str]:
    try:
        return set(json.loads(EDITIONS_FILE.read_text(encoding="utf-8"))["editions"])
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def _date(value) -> dt.date | None:
    """None, or a YYYY-MM-DD date (fromisoformat alone would also take
    20261101 and 2026-W44-1)."""
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("a date is not YYYY-MM-DD text")
    return dt.date.fromisoformat(value)


def _result(state: str, reason: str = "", licence: dict | None = None) -> dict:
    return {"state": state, "reason": reason, "licence": licence}


def _fields_problem(lic: dict) -> str:
    """Empty when the licence's fields are well formed, else why not."""
    if set(lic) != FIELDS:
        missing = sorted(FIELDS - set(lic))
        extra = sorted(set(lic) - FIELDS)
        return f"fields wrong (missing {missing}, unexpected {extra})"
    if type(lic["v"]) is not int or lic["v"] != 1:
        return "unknown licence format version"
    for name in ("id", "edition", "licensee", "key"):
        if not isinstance(lic[name], str) or not lic[name].strip():
            return f"{name} is empty"
    seats = lic["seats"]
    if seats is not None and (
        not isinstance(seats, int) or isinstance(seats, bool) or seats < 1
    ):
        return "seats is not a whole number of one or more"
    try:
        if _date(lic["issued"]) is None:
            return "issued is missing"
        _date(lic["updates_until"])
        _date(lic["expires"])
    except ValueError:
        return "a date is not YYYY-MM-DD"
    try:
        canonical(lic)
    except UnicodeEncodeError:  # "\ud800" written as an escape in the file
        return "a field is not plain text"
    return ""


def check(
    text: str | bytes,
    today: dt.date | None = None,
    released: dt.date | None = None,
    keys: dict[str, bytes] | None = None,
    editions: set[str] | None = None,
) -> dict:
    """The state of one licence file's text. released is this build's
    release date (None: unknown, so never past_updates)."""
    today = today or dt.date.today()
    keys = load_keys() if keys is None else keys
    editions = known_editions() if editions is None else editions
    if isinstance(text, str):
        text = text.removeprefix("\ufeff")  # Windows editors add a BOM
    try:
        doc = json.loads(text)
    except (ValueError, TypeError):
        return _result("invalid", "not a licence file (not JSON)")
    if not isinstance(doc, dict) or not isinstance(doc.get("licence"), dict):
        return _result("invalid", "not a licence file")
    lic = doc["licence"]
    problem = _fields_problem(lic)
    if problem:
        return _result("invalid", problem)
    if lic["key"] not in keys:
        return _result("invalid", f"signed with an unknown key ({lic['key']})")
    try:
        sig = base64.b64decode(str(doc.get("sig", "")), validate=True)
    except (binascii.Error, ValueError):
        return _result("invalid", "signature is not base64")
    if not forge_ed25519.verify(keys[lic["key"]], canonical(lic), sig):
        return _result("invalid", "signature does not match")
    if lic["edition"] not in editions:
        return _result("invalid", f"unknown edition ({lic['edition']})")
    expires = _date(lic["expires"])
    if expires is not None and today > expires:
        return _result("expired", f"ended on {expires.isoformat()}", lic)
    until = _date(lic["updates_until"])
    if until is not None and released is not None and released > until:
        return _result(
            "past_updates", f"covers builds released up to {until.isoformat()}", lic
        )
    return _result("valid", "", lic)


def state(today: dt.date | None = None, released: dt.date | None = None) -> dict:
    """The state of this Forge's licence file (free when there is none)."""
    path = licence_path()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return _result("free")
    except (OSError, UnicodeDecodeError) as err:
        return _result(
            "invalid", f"cannot read the licence file ({err.__class__.__name__})"
        )
    return check(text, today=today, released=released)


def _aside(path: Path) -> Path:
    """Rename path to a timestamped name beside it (never deleted)."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.removed-{stamp}")
    n = 1
    while target.exists():
        n += 1
        target = path.with_name(f"{path.name}.removed-{stamp}-{n}")
    path.rename(target)
    return target


def install(text: str, today: dt.date | None = None) -> dict:
    """Check a licence and, when its signature is good, make it this Forge's
    licence (atomic write, 0600). An invalid one is refused and nothing is
    written. A licence already there is moved aside, not deleted."""
    text = text.removeprefix("\ufeff")
    result = check(text, today=today)
    if result["state"] == "invalid":
        return result
    path = licence_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".licence-", dir=path.parent)
    try:
        if hasattr(os, "fchmod"):  # mkstemp already makes it 0600
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")
        if path.exists():
            _aside(path)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return result


def remove() -> Path | None:
    """Move this Forge's licence file aside (timestamped); None when there
    was none. Forge is then the free edition."""
    path = licence_path()
    if not path.exists():
        return None
    return _aside(path)
