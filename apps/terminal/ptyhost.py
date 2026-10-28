"""Shells on pseudo-terminals, kept alive between page reloads.

A `Term` is one shell started with `pty.fork()`. Its output is read on the
asyncio loop and fanned out to whichever WebSocket is attached, and the last
`SCROLLBACK` bytes are kept so a reloaded page (or a reopened Forge tab) gets
its screen back. Closing a tab sends SIGHUP to the shell's process group, as a
real terminal does when its window closes; stopping the app does the same for
all of them.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios
import time
import uuid
from pathlib import Path
from typing import Callable

SCROLLBACK = 256 * 1024
# Typed or pasted input waiting for the shell to read it. A paste bigger than
# this (32 MB) is cut short rather than held in memory.
MAX_PENDING = 32 * 1024 * 1024
INTERRUPT = b"\x03"
# What a terminal wraps a paste in once the program asks for it (bracketed paste).
PASTE_START, PASTE_END = b"\x1b[200~", b"\x1b[201~"
HOME = Path.home()


def keep_tail(buf: bytearray, limit: int) -> None:
    """Trim `buf` in place to at most `limit` bytes, cut at a line start, so a
    replay never begins inside an escape sequence or a multi-byte character
    (that showed as stray "8;2;255m" or a "?" at the top of a reloaded tab)."""
    over = len(buf) - limit
    if over <= 0:
        return
    nl = buf.find(b"\n", over, over + 4096)
    del buf[: nl + 1 if nl >= 0 else over]


def paste_left_open(dropped: bytes) -> bool:
    """True if `dropped` (queued input being thrown away) still holds the end
    marker of a bracketed paste whose start already went in."""
    end = dropped.find(PASTE_END)
    if end < 0:
        return False
    start = dropped.find(PASTE_START)
    return start < 0 or end < start


def default_shell() -> str:
    shell = os.environ.get("SHELL", "")
    return shell if shell and os.access(shell, os.X_OK) else "/bin/bash"


class Term:
    def __init__(
        self,
        cwd: str | None = None,
        cols: int = 100,
        rows: int = 30,
        argv: list[str] | None = None,
    ):
        self.id = uuid.uuid4().hex[:8]
        self.created = time.time()
        self.buffer = bytearray()
        self.listeners: set[Callable[[bytes | None], None]] = set()
        self.exit_code: int | None = None
        self.pending = bytearray()  # input the shell has not taken yet
        start = Path(cwd).expanduser() if cwd else HOME
        if not start.is_dir():
            start = HOME
        shell = default_shell()
        argv = argv or [shell, "-l"]
        env = {
            **os.environ,
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "TERM_PROGRAM": "ForgeTerminal",
        }
        env.pop("VIRTUAL_ENV", None)  # the app's own venv must not leak into the shell
        env["PATH"] = os.pathsep.join(
            p
            for p in env.get("PATH", "").split(os.pathsep)
            if "/apps/terminal/.venv" not in p
        )
        # subprocess forks in C, which is safe in this multi-threaded server
        # (pty.fork() runs Python in the child and can deadlock). `setsid -c`
        # makes the pty the shell's controlling terminal, so Ctrl+C, job
        # control and SIGWINCH on resize all work.
        fd, slave = pty.openpty()
        self.proc = subprocess.Popen(
            ["setsid", "-c", *argv],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=start,
            env=env,
            close_fds=True,
        )
        self.tty = os.ttyname(slave)  # the shell's side, flushed by interrupt()
        os.close(slave)
        self.pid, self.fd = self.proc.pid, fd
        self.resize(cols, rows)
        os.set_blocking(fd, False)
        self.loop = asyncio.get_running_loop()
        self.loop.add_reader(fd, self._on_readable)

    # ------------------------------------------------------------ io

    def _on_readable(self) -> None:
        try:
            data = os.read(self.fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self._finish()
            return
        self.buffer += data
        keep_tail(self.buffer, SCROLLBACK)
        for fn in list(self.listeners):
            fn(data)

    def _finish(self) -> None:
        try:
            self.loop.remove_reader(self.fd)
            self.loop.remove_writer(self.fd)
        except (ValueError, OSError):
            pass
        self.pending.clear()
        try:
            code = self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            code = -1
        self.exit_code = code
        try:
            os.close(self.fd)
        except OSError:
            pass
        for fn in list(self.listeners):
            fn(None)

    @property
    def alive(self) -> bool:
        return self.exit_code is None

    def write(self, data: bytes) -> None:
        """Queue input for the shell without ever blocking the event loop.

        A big paste fills the tty's input queue; the rest waits here and goes
        in as the shell reads (`_on_writable`). Writing in a loop until it all
        went in used to hang every tab for good: the shell stops reading while
        its echo is not read, and the echo is read on this same loop.
        Ctrl+C while a paste is still going in drops the rest of the paste,
        so it can be stopped."""
        if not self.alive or not data:
            return
        if data == INTERRUPT and self.pending:
            dropped = bytes(self.pending)
            self.pending.clear()
            self.loop.remove_writer(self.fd)
            if self.interrupt():
                return
            # A program reading the key itself still gets the paste's end
            # marker, or it would stay in paste mode.
            if paste_left_open(dropped):
                data = PASTE_END + data
        if self.pending:
            room = MAX_PENDING - len(self.pending)
            self.pending += data[: max(room, 0)]
            return
        try:
            n = os.write(self.fd, data)
        except BlockingIOError:
            n = 0
        except OSError:
            return
        if n < len(data):
            self.pending += data[n : n + MAX_PENDING]
            self.loop.add_writer(self.fd, self._on_writable)

    def interrupt(self) -> bool:
        """Do what the tty does when it reads Ctrl+C, for a Ctrl+C stuck behind
        a full input queue: drop the queued input and send SIGINT to the
        program in front. Only when that program lets the tty handle Ctrl+C
        (ISIG on, as a shell running `sleep`); a raw-mode program such as an
        editor or Claude Code gets the key itself. False if not done.

        The settings and the program in front are read through the master
        side: asking the shell's side for its foreground group fails (ENOTTY)
        from a process that does not have it as its own terminal."""
        try:
            attrs = termios.tcgetattr(self.fd)
            if not attrs[3] & termios.ISIG or attrs[6][termios.VINTR] != INTERRUPT:
                return False
            front = os.tcgetpgrp(self.fd)
        except OSError:
            return False
        try:
            fd = os.open(self.tty, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            try:
                termios.tcflush(fd, termios.TCIFLUSH)
            finally:
                os.close(fd)
        except OSError:
            pass  # the signal below still stops the program
        try:
            os.killpg(front, signal.SIGINT)
        except OSError:
            return False
        return True

    def _on_writable(self) -> None:
        try:
            n = os.write(self.fd, self.pending)
        except BlockingIOError:
            return
        except OSError:
            n = len(self.pending)
        del self.pending[:n]
        if not self.pending:
            self.loop.remove_writer(self.fd)

    def resize(self, cols: int, rows: int) -> None:
        cols, rows = max(2, min(int(cols), 1000)), max(1, min(int(rows), 500))
        try:
            fcntl.ioctl(
                self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0)
            )
        except OSError:
            pass

    # ------------------------------------------------------------ what's running

    def foreground(self) -> str:
        """Name of the program in front (`vim`, `htop`), or the shell's."""
        try:
            pgid = os.tcgetpgrp(self.fd)
            return Path(f"/proc/{pgid}/comm").read_text().strip()
        except OSError:
            return ""

    def cwd(self) -> str:
        try:
            return os.readlink(f"/proc/{self.pid}/cwd")
        except OSError:
            return ""

    def public(self) -> dict:
        cwd = self.cwd()
        return {
            "id": self.id,
            "alive": self.alive,
            "exit_code": self.exit_code,
            "cwd": cwd,
            "program": self.foreground() if self.alive else "",
            "created": self.created,
        }

    def close(self) -> None:
        if self.alive:
            for sig in (signal.SIGHUP, signal.SIGCONT):
                self._signal_group(sig)
            self.loop.call_later(1.5, self._term_if_alive)

    def _term_if_alive(self) -> None:
        """A moment later: the hang-up again, as bash can drop one that lands
        while it is still starting (a tab closed right after it opened kept
        its shell), then a TERM for anything that ignores hang-ups."""
        if self.alive:
            for sig in (signal.SIGHUP, signal.SIGCONT, signal.SIGTERM):
                self._signal_group(sig)

    def _signal_group(self, sig: int) -> None:
        """Signal the shell's process group, which `setsid` numbers after the
        shell. Never `getpgid(pid)`: in the first moment after the start,
        before `setsid` has run, that is this server's own group, and closing
        a brand-new tab hung up the whole Terminal backend."""
        try:
            os.killpg(self.pid, sig)
        except ProcessLookupError:
            try:  # no group yet: only the starting process itself
                os.kill(self.pid, sig)
            except OSError:
                pass
        except OSError:
            pass


class Registry:
    def __init__(self) -> None:
        self.terms: dict[str, Term] = {}

    def create(self, cwd: str | None = None, cols: int = 100, rows: int = 30) -> Term:
        t = Term(cwd, cols, rows)
        self.terms[t.id] = t
        return t

    def get(self, tid: str) -> Term | None:
        return self.terms.get(tid)

    def remove(self, tid: str) -> bool:
        t = self.terms.pop(tid, None)
        if t is None:
            return False
        t.close()
        return True

    def list(self) -> list[dict]:
        # A shell that exited on its own (typed `exit`) is dropped once listed.
        out = [t.public() for t in self.terms.values()]
        for t in [t for t in self.terms.values() if not t.alive and not t.listeners]:
            self.terms.pop(t.id, None)
        return sorted(out, key=lambda d: d["created"])

    def close_all(self) -> None:
        for tid in list(self.terms):
            self.remove(tid)
