"""Keeping a long unattended run from freezing the machine.

This laptop has no swap, so running out of memory does not degrade - it locks
up. And llama.cpp's prompt cache cannot be bounded from Jan's configuration
(Jan regenerates the preset that would carry `cache-ram` on every start), so a
model server grows over a long run: the 2B was measured going from 1.4 GB to
7.2 GB during one.

So the queue watches how much memory is actually left and pauses itself before
that becomes a problem, resuming when there is room again. Pausing lets the
in-flight subjects finish and starts nothing new; nothing is lost either way,
because the queue is on disk.

The hold this puts on the queue is deliberately its own flag (`by_guard=True`),
separate from the pause the user sets. Sharing one flag would mean the guard
lifting its hold also cleared a pause the user meant to stick - and that pause
now survives a restart, so it would be a lasting surprise rather than a
momentary one.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

# Pause below this, resume above the higher mark. The gap stops it flapping
# between the two states every time a model allocates.
PAUSE_BELOW_MB = 2200
RESUME_ABOVE_MB = 4000
CHECK_EVERY = 45.0


def available_mb() -> int:
    """Memory actually available, as the kernel reckons it.

    MemAvailable rather than MemFree: free memory excludes reclaimable page
    cache and would read as alarmingly low on a perfectly healthy machine.
    """
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except Exception:
        pass
    return -1


def decide(available: int, paused_by_us: bool) -> str:
    """'pause', 'resume' or 'hold', given the memory left and our own state."""
    if available < 0:
        return "hold"
    if not paused_by_us and available < PAUSE_BELOW_MB:
        return "pause"
    if paused_by_us and available >= RESUME_ABOVE_MB:
        return "resume"
    return "hold"


def watch(queue, log=print, check_every: float = CHECK_EVERY) -> threading.Thread:
    """Run the guard in the background against a queue."""
    state = {"paused_by_us": False}

    def loop():
        while True:
            time.sleep(check_every)
            try:
                mb = available_mb()
                action = decide(mb, state["paused_by_us"])
                if action == "pause":
                    queue.pause(by_guard=True)
                    state["paused_by_us"] = True
                    log(
                        f"[dossier] only {mb} MB free - pausing research to keep "
                        "the machine responsive (no swap on this system)"
                    )
                elif action == "resume":
                    state["paused_by_us"] = False
                    queue.resume(by_guard=True)
                    log(f"[dossier] {mb} MB free again - resuming research")
            except Exception as e:
                log(f"[dossier] memory guard: {type(e).__name__}: {e}")

    thread = threading.Thread(target=loop, daemon=True, name="memory-guard")
    thread.start()
    return thread
