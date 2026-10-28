"""Talking to Jan, at two speeds.

Jan is OpenAI-compatible on 127.0.0.1:1337 and its llama.cpp router keeps more
than one model resident, so a request picks its own tier by model id. Cheap
judgement (is this article even about the right person?) goes to the small
model hundreds of times; expensive judgement (what does it claim, does it
contradict the others, write it up) goes to the larger one a few times.

Two things here are not optional:

* `enable_thinking: false`. Qwen3.5 is a hybrid reasoning model and will spend
  its entire token budget narrating a chain of thought, returning an EMPTY
  content field. Measured on this machine: 16.8s and no answer with thinking
  on, 0.4s and "Yes" with it off. Every call sets it.
* One request at a time. The model shares an iGPU with the desktop; running
  calls in parallel makes the whole machine stutter for no throughput gain.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import time

import httpx

JAN_BASE = os.environ.get("JAN_BASE_URL", "http://127.0.0.1:1337/v1")

# Preference order per tier; the first one Jan actually has is used.
TIER_PREFERENCE = {
    "triage": ["Qwen3_5-2B", "qwen35-0_8b", "Qwen3_5-4B", "VibeThinker"],
    "reason": ["Qwen3_5-4B", "Qwen3_5-9B", "Qwen3_5-2B"],
    "deep": ["Qwen3_5-9B", "Qwen3_5-4B"],
}

# llama.cpp is configured with continuous batching and two parallel slots, so
# a second request shares a forward pass rather than queueing behind the first.
# This is a semaphore rather than a mutex for that reason - but it stays small
# and bounded, because two concurrent requests once out-of-memory-froze this
# machine and unbounded concurrency would invite that back.
LLM_CONCURRENCY = int(os.environ.get("DOSSIER_LLM_CONCURRENCY", "2"))
_lock = threading.Semaphore(LLM_CONCURRENCY)

# Bulk research will happily consume every slot for hours, and it starved the
# thing the user actually reads: the daily brief's summary call sat behind four
# research workers and timed out after 300 seconds. Foreground work - briefs,
# questions, a single subject asked for by hand - goes first, and background
# work waits while any is pending.
_gate = threading.Condition()
_foreground_waiting = 0


@contextlib.contextmanager
def _slot(priority: str):
    """Take an LLM slot, yielding to foreground work if this is background."""
    global _foreground_waiting
    if priority == "high":
        with _gate:
            _foreground_waiting += 1
        try:
            with _lock:
                yield
        finally:
            with _gate:
                _foreground_waiting -= 1
                _gate.notify_all()
    else:
        with _gate:
            while _foreground_waiting:
                _gate.wait(timeout=0.5)
        with _lock:
            yield


_cache: dict = {"models": [], "checked": 0.0}
_policy_cache: dict = {"tiers": {}, "checked": 0.0}
CACHE_TTL = 60.0


class JanUnavailable(RuntimeError):
    """Jan is off or has no model. Callers degrade; they never fabricate."""


def available_models(
    client: httpx.Client | None = None, refresh: bool = False
) -> list[str]:
    """What Jan currently offers. `refresh` skips the cache, which matters
    right after Jan has been restarted and the old list is stale."""
    now = time.time()
    if _cache["models"] and not refresh and now - _cache["checked"] < CACHE_TTL:
        return _cache["models"]
    own = client is None
    client = client or httpx.Client(timeout=5.0)
    try:
        r = client.get(f"{JAN_BASE}/models")
        r.raise_for_status()
        ids = [m["id"] for m in (r.json().get("data") or [])]
        if not ids:
            raise JanUnavailable("Jan is running but has no model available")
        _cache.update(models=ids, checked=now)
        return ids
    except JanUnavailable:
        raise
    except Exception as e:
        raise JanUnavailable(f"Jan unreachable at {JAN_BASE} ({type(e).__name__}: {e})")
    finally:
        if own:
            client.close()


def tier_overrides() -> dict:
    """The user's own tier-to-model choices, if they have made any.

    Read from disk rather than imported, so swapping a model in the interface
    takes effect without a restart and without this module depending on the
    thing that writes it.
    """
    now = time.time()
    if now - _policy_cache["checked"] < 10.0:
        return _policy_cache["tiers"]
    tiers = {}
    try:
        import store

        stored = store.read_json(store.data_root().path / "jan-policy.json", None)
        tiers = {k: v for k, v in ((stored or {}).get("tiers") or {}).items() if v}
    except Exception:
        tiers = {}
    _policy_cache.update(tiers=tiers, checked=now)
    return tiers


def resolve(tier: str) -> str:
    """Which model id serves this tier right now.

    An explicit choice wins; otherwise the preference order below picks the
    best of whatever Jan happens to have, so changing models does not break
    anything.
    """
    ids = available_models()
    wanted = tier_overrides().get(tier)
    if wanted:
        for have in ids:
            if wanted.lower() == have.lower() or wanted.lower() in have.lower():
                return have
    embedding = [i for i in ids if "sentence-transformer" in i.lower()]
    usable = [i for i in ids if i not in embedding]
    for want in TIER_PREFERENCE.get(tier, []):
        for have in usable:
            if want.lower() in have.lower():
                return have
    if not usable:
        raise JanUnavailable("Jan has only embedding models available")
    return usable[0]


def status() -> dict:
    out = {"jan": False, "models": [], "tiers": {}, "detail": ""}
    try:
        out["models"] = available_models()
        out["jan"] = True
        for tier in TIER_PREFERENCE:
            try:
                out["tiers"][tier] = resolve(tier)
            except JanUnavailable:
                out["tiers"][tier] = None
    except JanUnavailable as e:
        out["detail"] = str(e)
    return out


class JanRequestFailed(JanUnavailable):
    """Jan answered, but this one request failed.

    A subclass so every existing handler still catches it, while the claim
    reader can skip one article instead of treating Jan as switched off.
    """


# Seconds before retrying a request the server failed. Real failures seen here
# (a reply in the wrong format, a Vulkan device reset) often pass on a retry.
RETRY_PAUSE = 5.0


def chat(
    tier: str,
    messages: list[dict],
    max_tokens: int = 512,
    temperature: float = 0.2,
    thinking: bool = False,
    timeout: float = 300.0,
    priority: str = "low",
) -> str:
    """One completion. Thinking off, content only, bounded concurrency."""
    model = resolve(tier)
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": bool(thinking)},
        # Every prompt here is unique - a different article or subject each
        # time - so a cached prompt can never be reused. Left on, llama.cpp's
        # prompt cache grew the 2B from 1.4 GB to 6.5 GB during a bulk run,
        # which matters on a machine with no swap. It is not a speed fix:
        # measured 5.86s against 6.30s under load, where the real constraint is
        # the shared iGPU.
        "cache_prompt": False,
    }
    r = _post(body, timeout, priority)
    if r.status_code >= 500:
        time.sleep(RETRY_PAUSE)
        r = _post(body, timeout, priority)
    if r.status_code >= 400:
        raise JanRequestFailed(f"Jan returned {r.status_code}: {r.text[:300]}")
    data = r.json()
    msg = data["choices"][0]["message"]
    text = (msg.get("content") or "").strip()
    if not text and msg.get("reasoning_content"):
        # Thinking leaked despite the flag - salvage the tail rather than
        # returning nothing, but never silently pass off reasoning as an answer.
        raise JanRequestFailed(
            f"{model} returned only reasoning; raise max_tokens or check the chat template"
        )
    return text


_in_flight = 0
_in_flight_lock = threading.Lock()


def in_flight() -> int:
    """Requests sent to Jan, or waiting for a slot, that have not returned."""
    return _in_flight


def _post(body: dict, timeout: float, priority: str) -> httpx.Response:
    global _in_flight
    with _in_flight_lock:
        _in_flight += 1
    try:
        with _slot(priority):
            try:
                with httpx.Client(timeout=timeout) as client:
                    return client.post(f"{JAN_BASE}/chat/completions", json=body)
            except httpx.TimeoutException as e:
                raise JanRequestFailed(f"Jan call timed out ({type(e).__name__}: {e})")
            except Exception as e:
                raise JanUnavailable(f"Jan call failed ({type(e).__name__}: {e})")
    finally:
        with _in_flight_lock:
            _in_flight -= 1


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def chat_json(tier: str, messages: list[dict], default, **kw):
    """A completion that must parse as JSON. Small models fence their output
    or add a sentence in front of it; both are tolerated. On anything else the
    default is returned - a malformed answer must not become a fact."""
    raw = chat(tier, messages, **kw)
    for candidate in (raw, *(m.group(1) for m in _JSON_BLOCK.finditer(raw))):
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except Exception:
            pass
        start = min(
            (i for i in (candidate.find("{"), candidate.find("[")) if i >= 0),
            default=-1,
        )
        if start >= 0:
            for end in range(len(candidate), start, -1):
                chunk = candidate[start:end]
                if chunk[-1] not in "}]":
                    continue
                try:
                    return json.loads(chunk)
                except Exception:
                    continue
        repaired = _repair_array(candidate)
        if repaired is not None:
            return repaired
    return default


def _repair_array(text: str):
    """Salvage a list that was cut off when the token budget ran out.

    A truncated answer is the normal failure mode for a small model given a
    generous list to produce, and the complete objects before the cut are
    perfectly good. Everything after the last complete one is discarded.
    """
    start = text.find("[")
    if start < 0:
        return None
    depth = 0
    last_complete = -1
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_complete = i
    if last_complete < 0:
        return None
    try:
        return json.loads(text[start : last_complete + 1] + "]")
    except Exception:
        return None
