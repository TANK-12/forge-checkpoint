"""Whether anyone can see a Forge window, so its pages can rest when not.

B34 (2026-09-27): on GNOME Wayland GTK3 never hears that a window was
minimised or left on another workspace, so WebKit kept the page visible and
every animation ran at full rate. GNOME does send a fully-obscured
visibility event about four seconds after a window is hidden, and forge.py
unmaps the page while that holds, which WebKit reads as hidden.

Task 60 (2026-10-07): fully-obscured needs every pixel covered, so a window
that covers almost all of Forge (or a see-through terminal over it) never
counted and the hub kept drawing behind it. The Forge GNOME extension
(desktop/gnome-extension) sees every window, so it works out how much of
each Forge window still shows and writes it to UNDER_FILE as
{"<screen>": hidden, ..., "pids": {"<pid>": hidden}}; the screens are the
desktop's (desktop/particles.py), the pids Forge's own processes. A window
counts as hidden there when it is minimised, on another workspace, or less
than a tenth of it shows. `watch_shell` feeds this process's entry to Seen.

Tiers (2026-10-07): the file also carries how much shows, in twentieths,
{"shown": {"screens": {...}, "pids": {"<pid>": share}}}. Under a tenth is the
paused tier (the page unmapped, here); a mostly covered window is the reduced
tier, which shared/forge_power.js decides from the share `watch_shell` hands
to `on_share`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

UNDER_FILE = (
    Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "forge-desktop-under.json"
)


class Seen:
    """Whether anyone can see the window, from everything that says so.

    The compositor's fully-obscured event, the window's minimised state, its
    mapping and the GNOME extension's answer each can hide it. A window
    visible on another monitor is not hidden, and focus never counts, so it
    keeps running there. Each update returns whether `seen` changed.
    """

    def __init__(self):
        self.is_mapped = True
        self.iconified = False
        self.obscured = False
        self.shell_hidden = False

    @property
    def seen(self):
        return (
            self.is_mapped
            and not self.iconified
            and not self.obscured
            and not self.shell_hidden
        )

    def _set(self, name, value):
        before = self.seen
        setattr(self, name, bool(value))
        return self.seen != before

    def visibility(self, obscured):
        return self._set("obscured", obscured)

    def window_state(self, iconified):
        return self._set("iconified", iconified)

    def mapped(self, on):
        return self._set("is_mapped", on)

    def shell(self, hidden):
        """The GNOME extension's answer: covered, minimised or elsewhere."""
        return self._set("shell_hidden", hidden)

    def touched(self):
        """Focus, a click, a key or the pointer coming in: someone is looking,
        whatever the compositor or the shell last said."""
        before = self.seen
        self.obscured = self.iconified = self.shell_hidden = False
        return self.seen != before


def read_under(path: Path = UNDER_FILE) -> dict:
    """The extension's file as a dict; {} when absent or unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def pid_hidden(data: dict, pid: int) -> bool:
    """Whether the extension says every window of process `pid` is hidden.
    False when it says nothing about it (an older extension, no GNOME)."""
    pids = data.get("pids")
    return isinstance(pids, dict) and pids.get(str(pid)) is True


def pid_shown(data: dict, pid: int) -> float:
    """The share (0..1) of process `pid`'s most visible window that shows;
    1.0 when the extension says nothing about it."""
    shown = data.get("shown")
    pids = shown.get("pids") if isinstance(shown, dict) else None
    value = pids.get(str(pid)) if isinstance(pids, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 1.0
    return min(1.0, max(0.0, float(value)))


def watch_shell(
    seen: Seen,
    changed: Callable[[], object],
    path: Path = UNDER_FILE,
    pid: int | None = None,
    on_share: Callable[[float], object] | None = None,
):
    """Follow the extension's answer for this process: set seen.shell from
    the file now and on every rewrite, and call `changed` when that changes
    `seen`; `on_share` gets the shown share each time it changes. Returns
    the file monitor; keep a reference to it."""
    from gi.repository import Gio

    me = os.getpid() if pid is None else pid
    last: dict[str, float | None] = {"share": None}

    def update(*_args):
        data = read_under(path)
        if seen.shell(pid_hidden(data, me)):
            changed()
        share = pid_shown(data, me)
        if on_share is not None and share != last["share"]:
            last["share"] = share
            on_share(share)

    monitor = Gio.File.new_for_path(str(path)).monitor_file(
        Gio.FileMonitorFlags.NONE, None
    )
    monitor.set_rate_limit(50)
    monitor.connect("changed", update)
    update()
    return monitor
