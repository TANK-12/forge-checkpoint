"""Giving Jan's memory back when nothing is using it.

Two idle models held about 9.8 GB on a laptop with no swap while research was
paused. Jan runs a llama.cpp router that loads a model again on the next
request naming it, so an idle model can be unloaded at the cost of a reload
later - measured at 1.9 seconds for the 2B.

A model counts as idle only when its own process has used no CPU for the whole
wait, which is true only when nothing at all is talking to it: not Dossier, not
the Arcade, not another session. Nothing is released while Dossier has a
request waiting on Jan.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Iterator

import httpx

import llm

IDLE_SECONDS = float(os.environ.get("DOSSIER_JAN_IDLE_SECONDS", "300"))
CHECK_EVERY = 30.0
SERVER = "llama-server"
# Linux's process table; Windows and macOS have none, and then no Jan model
# is seen or released here.
PROC = Path("/proc")


def _flag(cmd: list[str], name: str) -> str | None:
    try:
        return cmd[cmd.index(name) + 1]
    except (ValueError, IndexError):
        return None


def _is_server(cmd: list[str]) -> bool:
    return bool(cmd) and Path(cmd[0]).name == SERVER


def parse_router(cmd: list[str], environ: dict[str, str]) -> tuple[str, str] | None:
    """The router's base URL and API key, from its command line and environment."""
    if not _is_server(cmd) or "--models-preset" not in cmd:
        return None
    port = _flag(cmd, "--port")
    if not port:
        return None
    host = _flag(cmd, "--host") or "127.0.0.1"
    return f"http://{host}:{port}", environ.get("LLAMA_API_KEY", "")


def parse_model(cmd: list[str]) -> str | None:
    """The model a llama-server process is serving, or None for the router."""
    if not _is_server(cmd) or "--models-preset" in cmd:
        return None
    return _flag(cmd, "--alias")


def _servers() -> Iterator[tuple[int, list[str]]]:
    if not PROC.is_dir():
        return
    for entry in PROC.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        argv = [a.decode(errors="replace") for a in raw.split(b"\0") if a]
        if _is_server(argv):
            yield int(entry.name), argv


def _cpu_ticks(pid: int) -> int | None:
    try:
        fields = (PROC / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[11]) + int(fields[12])
    except (OSError, IndexError, ValueError):
        return None


def model_ticks() -> dict[str, int]:
    """CPU time used so far by each loaded model, keyed by model name."""
    out: dict[str, int] = {}
    for pid, argv in _servers():
        name = parse_model(argv)
        ticks = _cpu_ticks(pid)
        if name and ticks is not None:
            out[name] = ticks
    return out


def model_ports() -> dict[str, int]:
    """The port each loaded model's own llama-server listens on."""
    out: dict[str, int] = {}
    for _pid, argv in _servers():
        name = parse_model(argv)
        port = _flag(argv, "--port")
        if name and port and port.isdigit():
            out[name] = int(port)
    return out


def slots_busy(port: int) -> bool:
    """True while any slot of that model server is working on a request.

    The CPU-tick test above sees a model that sat idle for the whole wait,
    but a request that has just arrived (PanelForge reading a page after
    minutes of detection, say) is not on the ticks yet: on 2026-09-19 the
    4B was unloaded fourteen times under another app's requests that way.
    The server's own /slots answer is the last word before an unload;
    when it cannot be asked, the model is treated as busy.
    """
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/slots", timeout=3.0)
        r.raise_for_status()
        return any(bool(slot.get("is_processing")) for slot in r.json())
    except (httpx.HTTPError, ValueError, AttributeError):
        return True


def router() -> tuple[str, str] | None:
    for pid, argv in _servers():
        if "--models-preset" not in argv:
            continue
        try:
            raw = (PROC / str(pid) / "environ").read_bytes()
        except OSError:
            continue
        env = dict(
            item.split("=", 1)
            for item in raw.decode(errors="replace").split("\0")
            if "=" in item
        )
        found = parse_router(argv, env)
        if found:
            return found
    return None


def release(model: str) -> bool:
    """Ask Jan's router to unload one model. The next request reloads it."""
    found = router()
    if not found:
        return False
    base, key = found
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        r = httpx.post(
            f"{base}/models/unload",
            json={"model": model},
            headers=headers,
            timeout=30.0,
        )
    except httpx.HTTPError:
        return False
    return r.status_code == 200


class IdleTracker:
    """Which loaded models have gone the whole wait without doing any work."""

    def __init__(self, idle_seconds: float):
        self.idle_seconds = idle_seconds
        self._seen: dict[str, tuple[int, float]] = {}

    def observe(self, now: float, ticks: dict[str, int], busy: bool) -> list[str]:
        for model in list(self._seen):
            if model not in ticks:
                del self._seen[model]
        idle = []
        for model, used in ticks.items():
            previous = self._seen.get(model)
            if busy or previous is None or previous[0] != used:
                self._seen[model] = (used, now)
            elif now - previous[1] >= self.idle_seconds:
                idle.append(model)
        return idle


def watch(
    idle_seconds: float = IDLE_SECONDS,
    check_every: float = CHECK_EVERY,
    log=print,
) -> threading.Thread | None:
    """Release idle models in the background. `idle_seconds <= 0` turns it off,
    and so does a system with no process table to watch."""
    if idle_seconds <= 0 or not PROC.is_dir():
        return None
    tracker = IdleTracker(idle_seconds)

    def loop():
        while True:
            time.sleep(check_every)
            try:
                busy = llm.in_flight() > 0
                ports = model_ports()
                for model in tracker.observe(time.monotonic(), model_ticks(), busy):
                    port = ports.get(model)
                    if port is not None and slots_busy(port):
                        continue  # a request is on it right now
                    if llm.in_flight() == 0 and release(model):
                        log(
                            f"[dossier] released idle Jan model {model} to free "
                            "memory; it loads again on the next request"
                        )
            except Exception as e:
                log(f"[dossier] Jan idle release: {type(e).__name__}: {e}")

    thread = threading.Thread(target=loop, daemon=True, name="jan-idle")
    thread.start()
    return thread
