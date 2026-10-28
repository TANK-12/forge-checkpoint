"""Runs the system tools the panels read and change. Every panel takes a
`run` argument so the tests can hand in canned output instead."""

from __future__ import annotations

import re
import subprocess
from typing import Callable

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x01|\x02")

Run = Callable[..., "Result"]


class Result:
    def __init__(self, code: int, out: str, err: str = "") -> None:
        self.code, self.out, self.err = code, out, err

    @property
    def ok(self) -> bool:
        return self.code == 0

    def text(self) -> str:
        return (self.err or self.out).strip()


class CommandFailed(Exception):
    """A tool ran but said no; the message is what it said."""


def run(cmd: list[str], timeout: float = 10, input: str | None = None) -> Result:
    try:
        done = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, input=input
        )
    except FileNotFoundError:
        return Result(127, "", f"{cmd[0]} is not installed")
    except subprocess.TimeoutExpired:
        return Result(124, "", f"{cmd[0]} took longer than {timeout:.0f} s")
    return Result(done.returncode, ANSI.sub("", done.stdout), ANSI.sub("", done.stderr))


def must(result: Result, what: str) -> Result:
    if not result.ok:
        raise CommandFailed(f"{what}: {result.text() or 'failed'}")
    return result
