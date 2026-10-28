"""The password lock for a locked look (Business, hub/looks/business.json).

A look whose sidecar says "locked": true keeps Forge's settings shut while it
is the chosen look: forge_theme.save() asks `check()` before it writes, so
the Settings app, the Wallpapers app, the Power app and the hub (through
forge.py) are all refused the same way, and so is leaving the look.
Entering the password opens a short window (UNLOCK_SECONDS) in which saves go
through; "Lock now" or the clock shuts it again.

Only a salted PBKDF2 hash of the password is kept, in a 0600 file beside the
settings (PASSWORD_FILE); the password itself is never written, logged or
sent back. With no password set nothing is locked, so a fresh Forge can
never shut itself out. The unlock window and the count of wrong tries live
in STATE_FILE: five wrong tries in a row make the next try wait WAIT_SECONDS.
Every read-check-write of that file holds a thread lock and a file lock
(_guard), so guesses sent all at once are still counted one by one.

This guards the settings against someone using the screen, not against
someone with a shell on the laptop: any local program can write these files.

Set or change the password from the command line without it showing:
    python3 shared/forge_lock.py set        (reads it from stdin, no echo)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows: the thread lock alone
    fcntl = None

HOME = Path.home()
PASSWORD_FILE = Path(
    os.environ.get("FORGE_LOCK_FILE", HOME / ".config/forge/look-lock.json")
)
STATE_FILE = Path(
    os.environ.get("FORGE_LOCK_STATE", HOME / ".local/state/forge/look-unlock.json")
)
UNLOCK_SECONDS = 600
MAX_TRIES = 5
WAIT_SECONDS = 30
ITERATIONS = 200_000
MIN_LENGTH = 4
_THREADS = threading.Lock()


class Locked(Exception):
    """A change was asked for while the chosen look is locked."""

    def __init__(
        self, message: str = "Business mode is locked. Unlock it in Settings first."
    ):
        super().__init__(message)


class BadPassword(Exception):
    """The password given does not match, or a wait is still running."""

    def __init__(self, message: str, wait: int = 0):
        super().__init__(message)
        self.wait = wait


def _write_private(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)  # 0600
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(data, out)
    os.replace(tmp, path)


@contextmanager
def _guard():
    """One password check or window change at a time, across threads and
    processes (Settings and the command line)."""
    with _THREADS:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE.with_name(STATE_FILE.name + ".lock"), "a") as held:
            if fcntl:
                fcntl.flock(held, fcntl.LOCK_EX)
            yield


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _digest(password: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    ).hex()


def has_password() -> bool:
    stored = _read(PASSWORD_FILE)
    return bool(stored.get("hash") and stored.get("salt"))


def set_password(new: str, current: str | None = None) -> None:
    """Store `new` (hashed). When a password is already set, `current` must
    match it; a wrong one counts as a wrong try."""
    if len(new or "") < MIN_LENGTH:
        raise ValueError(f"The password needs at least {MIN_LENGTH} characters.")
    with _guard():
        if has_password():
            _verify(current or "")
        salt = secrets.token_bytes(16)
        _write_private(
            PASSWORD_FILE,
            {
                "scheme": "pbkdf2_sha256",
                "iterations": ITERATIONS,
                "salt": salt.hex(),
                "hash": _digest(new, salt, ITERATIONS),
            },
        )


def _verify(password: str, now: float | None = None) -> None:
    """Raise BadPassword unless `password` matches; count wrong tries.
    Called inside _guard()."""
    now = time.time() if now is None else now
    state = _read(STATE_FILE)
    wait = int(float(state.get("wait_until", 0)) - now)
    if wait > 0:
        raise BadPassword(f"Too many wrong tries. Try again in {wait} s.", wait)
    stored = _read(PASSWORD_FILE)
    try:
        salt = bytes.fromhex(stored["salt"])
        iterations = int(stored.get("iterations", ITERATIONS))
        good = hmac.compare_digest(
            _digest(password or "", salt, iterations), stored["hash"]
        )
    except (KeyError, ValueError, TypeError):
        good = False
    if good:
        state.update(fails=0, wait_until=0)
        _write_private(STATE_FILE, state)
        return
    fails = int(state.get("fails", 0)) + 1
    if fails >= MAX_TRIES:
        state.update(fails=0, wait_until=now + WAIT_SECONDS)
        _write_private(STATE_FILE, state)
        raise BadPassword(
            f"Wrong password. Too many tries: wait {WAIT_SECONDS} s.", WAIT_SECONDS
        )
    state["fails"] = fails
    _write_private(STATE_FILE, state)
    raise BadPassword("Wrong password.")


def unlock(password: str, now: float | None = None) -> float:
    """Open the window if `password` matches; returns when it shuts."""
    now = time.time() if now is None else now
    with _guard():
        _verify(password, now)
        until = now + UNLOCK_SECONDS
        state = _read(STATE_FILE)
        state["until"] = until
        _write_private(STATE_FILE, state)
    return until


def relock() -> None:
    with _guard():
        state = _read(STATE_FILE)
        if state.get("until"):
            state["until"] = 0
            _write_private(STATE_FILE, state)


def open_until(now: float | None = None) -> float:
    """When the unlock window shuts, or 0 when it is shut."""
    now = time.time() if now is None else now
    until = float(_read(STATE_FILE).get("until", 0) or 0)
    return until if until > now else 0.0


def is_locked(look_locks: bool, now: float | None = None) -> bool:
    """Locked: the chosen look locks, a password is set and the window is shut."""
    return bool(look_locks) and has_password() and not open_until(now)


def check(look_locks: bool) -> None:
    if is_locked(look_locks):
        raise Locked()


def status(look_locks: bool) -> dict:
    """What a settings page may show: never the password or its hash."""
    return {
        "look_locks": bool(look_locks),
        "has_password": has_password(),
        "locked": is_locked(look_locks),
        "open_until": open_until(),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import getpass
    import sys

    parser = argparse.ArgumentParser(description="Set the Business look password.")
    parser.add_argument("action", choices=["set", "status"])
    args = parser.parse_args(argv)
    if args.action == "status":
        print(json.dumps({"has_password": has_password(), "open_until": open_until()}))
        return 0
    read = getpass.getpass if sys.stdin.isatty() else (lambda _prompt="": input())
    # taken as typed, spaces and all, the same as the Settings page
    current = read("Current password: ") if has_password() else None
    new = read("New password: ")
    try:
        set_password(new, current)
    except (ValueError, BadPassword) as error:
        print(error, file=sys.stderr)
        return 1
    print("Password saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
