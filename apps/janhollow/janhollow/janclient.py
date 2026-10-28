"""Talking to Jan, carefully.

Three rules are baked in here rather than left to callers, because each one
came from something that actually went wrong on this laptop:

* **Thinking off.** Qwen3.5 reasons by default. Measured on 2026-09-16: a plain
  request for one line of crew dialogue spent all 160 tokens in
  `reasoning_content` and returned empty content in 5.7 s. The same request with
  `enable_thinking: false` came back in 0.9 s with the line. Every request here
  sends that flag.
* **One request at a time.** Two concurrent Jan requests once froze the laptop.
  There is a single lane through this module, so the chatter and the narrator
  take turns no matter how many threads want one.
* **Jan is shared and is never restarted.** This module only ever posts to it.
  Loading and releasing models is `shared/forge_jan.py`'s job, which is why the
  caller passes the guard it gets from `forge_jan.mount`.

Measured latencies, same day: the 0.8B chatter model answers in 0.6-0.9 s; the
4B narrator took 21.4 s for 74 tokens. That gap is the whole reason the narrator
runs rarely and never on the path of anything a person is waiting for.
"""

from __future__ import annotations

import os
import sys
import time

SHARED_DIR = os.environ.get("FORGE_SHARED_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "shared"
)
sys.path.insert(0, os.path.abspath(SHARED_DIR))

import forge_jan  # noqa: E402

BASE_URL = forge_jan.BASE_URL

# The request itself, the single lane and the thinking-off flag all live in
# shared/forge_jan.py now, so every Forge app that talks to Jan gets them.
# What stays here is what is particular to a station full of people talking:
# the app's model preferences, the stats the Voices panel shows, and a short
# lane wait -- the chatter would rather skip a conversation than queue behind
# a twenty-second narrator call.
JanError = forge_jan.JanError
LANE = forge_jan.LANE
LANE_WAIT = 3.0


class Client:
    """One app's way in. `guard` is the AppJan from forge_jan.mount, which is
    what marks a model as this app's so the idle release can hand it back."""

    def __init__(
        self, guard=None, base_url: str = BASE_URL, log=print, preferences=None
    ):
        self.guard = guard
        self.base_url = base_url
        self.log = log
        # The app's preferred model per role. It is only ever a fallback: a
        # model chosen in the settings panel always wins. See janhollow/roles.py
        # for why this exists at all.
        self.preferences = dict(preferences or {})
        self.stats = {
            "calls": 0,
            "failures": 0,
            "skipped_busy": 0,
            "seconds": 0.0,
            "last_error": "",
        }

    def model_for(self, role: str, fallback: str = "") -> str:
        preferred = fallback or self.preferences.get(role, "")
        if self.guard is not None:
            return self.guard.model_for(role, preferred)
        return preferred

    def chat(
        self,
        role: str,
        system: str,
        user: str,
        *,
        fallback_model: str = "",
        temperature: float = 0.9,
        max_tokens: int = 90,
        timeout: float = 120.0,
        seed: int | None = None,
        wait: float = LANE_WAIT,
    ) -> str:
        """One completion, or a JanError. Returns the message content.

        Blocks for at most `wait` seconds on the lane: a caller that cannot get
        in returns a JanError rather than piling up behind a slow model.
        """
        model = self.model_for(role, fallback_model)
        if not model:
            raise JanError(f"no model chosen for {role!r} and Jan offered none")
        started = time.monotonic()
        try:
            using = self.guard.using(model) if self.guard is not None else _NullGuard()
            with using:
                content = forge_jan.chat(
                    model,
                    system,
                    user,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    seed=seed,
                    base_url=self.base_url,
                    wait=wait,
                )
            self.stats["calls"] += 1
            return content
        except JanError as exc:
            if "busy" in str(exc):
                self.stats["skipped_busy"] += 1
            self.stats["failures"] += 1
            self.stats["last_error"] = str(exc)[:200]
            raise
        finally:
            self.stats["seconds"] += time.monotonic() - started

    def online(self, timeout: float = 2.0) -> bool:
        return forge_jan.router_url() is not None or bool(forge_jan.models())


class _NullGuard:
    """Stands in for forge_jan's guard when there isn't one, so tests and a
    standalone run need no Jan settings at all."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
