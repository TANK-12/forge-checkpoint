"""Talking to Jan, at three speeds — and the one place thinking is wanted.

Dossier forces `enable_thinking: false` on every call, for a good measured
reason: Qwen3.5 is a hybrid reasoning model and, left alone, spends its whole
token budget narrating and returns an empty `content` field (16.8 s and no
answer, against 0.4 s and "Yes" with it off). Foresight keeps that rule for its
fast tiers and **deliberately breaks it for one**:

    chat     the study companion. Small, instant, thinking off.
    analyse  triage, sentiment on the ambiguous band, summaries. Thinking off.
    think    scenarios and plans. Thinking ON, a long budget, minutes allowed.

The `think` tier is the whole point of this app. The user asked for something
"as smart as a human" that "will think on this dedicated task for ages", so
here a long chain of thought is the product rather than waste, and the timeout
is generous enough to let it finish.

That is also why the preference order wants a **mixture-of-experts** model
first. An MoE activates a fraction of its parameters per token, so a long
reasoning chain is affordable on a CPU; a dense model of the same nominal size
would produce the same thinking at a fraction of the speed.

**One model resident at a time.** Dossier's WIP records that putting a second
model on the Iris Xe silently corrupted the first one's output — well-formed
JSON with garbage tokens inside strings. Nothing here loads models; it uses
whatever Jan has, and the interface warns when a tier falls back.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

import httpx

JAN_BASE = os.environ.get("JAN_BASE_URL", "http://127.0.0.1:1337/v1")

# Preference order per tier; the first one Jan actually has is used, so
# swapping models never breaks the app - it only makes a tier sharper or
# blunter, and `status()` reports which model each tier actually landed on.
TIER_PREFERENCE = {
    "chat": ["Qwen3_5-2B", "qwen35-0_8b", "Qwen3_5-4B"],
    "analyse": ["Qwen3_5-4B", "Qwen3_5-2B", "Qwen3_5-9B"],
    "think": [
        "Qwen3.6-35B-A3B",  # the recommended download: MoE, cheap per token
        "Qwen3-30B-A3B",
        "Ternary-Bonsai-27B",
        "Qwen3_5-9B",  # already on disk - the working fallback
        "VibeThinker",
        "Qwen3_5-4B",
    ],
}

# Thinking is off everywhere except the tier that exists to think.
TIER_THINKS = {"chat": False, "analyse": False, "think": True}

# A thinking tier needs room to actually think. These are budgets, not targets.
TIER_BUDGET = {"chat": 800, "analyse": 1200, "think": 8000}
TIER_TIMEOUT = {"chat": 120.0, "analyse": 300.0, "think": 1800.0}

# The desktop shares one iGPU with the model. Two concurrent calls once froze
# this machine, and there is no swap, so concurrency stays small and bounded.
LLM_CONCURRENCY = int(os.environ.get("FORESIGHT_LLM_CONCURRENCY", "1"))
_lock = threading.Semaphore(LLM_CONCURRENCY)

_cache: dict = {"models": [], "checked": 0.0}
CACHE_TTL = 60.0


class JanUnavailable(RuntimeError):
    """Jan is off or has no model. Callers degrade; they never fabricate."""


class NotEnoughMemory(RuntimeError):
    """Refusing to start a big call while the machine is close to the edge."""


# This laptop has 31 GB and **no swap**, so running out of memory does not
# degrade - it locks the machine up. The think tier's model is the largest
# thing that will ever be resident, and llama.cpp grows its KV cache as a
# conversation lengthens, so the dangerous moment is starting a long call when
# memory is already tight rather than loading the model itself.
#
# Refusing here costs an answer. Not refusing costs the session.
MIN_FREE_MB_FOR_THINKING = 3000


def available_mb() -> int:
    """Memory actually available, as the kernel reckons it.

    MemAvailable rather than MemFree: free memory excludes reclaimable page
    cache and reads as alarmingly low on a perfectly healthy machine.
    """
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return -1


def available_models(refresh: bool = False) -> list[str]:
    now = time.time()
    if _cache["models"] and not refresh and now - _cache["checked"] < CACHE_TTL:
        return _cache["models"]
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{JAN_BASE}/models")
            r.raise_for_status()
            ids = [m["id"] for m in (r.json().get("data") or [])]
    except Exception as e:
        raise JanUnavailable(f"Jan unreachable at {JAN_BASE} ({type(e).__name__}: {e})")
    if not ids:
        raise JanUnavailable("Jan is running but has no model available")
    _cache.update(models=ids, checked=now)
    return ids


def overrides() -> dict:
    """The user's own tier-to-model choices, read from disk each time.

    On disk rather than imported so choosing a model in the interface takes
    effect without a restart, and so this module does not depend on whatever
    writes it.
    """
    try:
        import store

        stored = store.read_json(store.data_root().path / "jan-policy.json", None)
        return {k: v for k, v in ((stored or {}).get("tiers") or {}).items() if v}
    except Exception:
        return {}


def resolve(tier: str) -> str:
    """Which model id serves this tier right now."""
    ids = available_models()
    wanted = overrides().get(tier)
    if wanted:
        for have in ids:
            if wanted.lower() == have.lower() or wanted.lower() in have.lower():
                return have
    # Embedding models answer /models too and must never be asked to chat.
    usable = [i for i in ids if "sentence-transformer" not in i.lower()]
    for want in TIER_PREFERENCE.get(tier, []):
        for have in usable:
            if want.lower() in have.lower():
                return have
    if not usable:
        raise JanUnavailable("Jan has only embedding models available")
    return usable[0]


def status() -> dict:
    """What Jan has, and what each tier actually landed on.

    `ideal` is reported beside the resolved model so the interface can say "the
    think tier is running on the 9B fallback" rather than quietly pretending
    the recommended model is there.
    """
    out: dict = {"jan": False, "models": [], "tiers": {}, "detail": ""}
    try:
        out["models"] = available_models()
        out["jan"] = True
    except JanUnavailable as e:
        out["detail"] = str(e)
        out["tiers"] = {t: None for t in TIER_PREFERENCE}
        return out
    for tier, preference in TIER_PREFERENCE.items():
        try:
            got = resolve(tier)
        except JanUnavailable:
            got = None
        out["tiers"][tier] = {
            "model": got,
            "ideal": preference[0],
            "is_ideal": bool(got and preference[0].lower() in got.lower()),
            "thinks": TIER_THINKS.get(tier, False),
        }
    return out


def chat(
    tier: str,
    messages: list[dict],
    max_tokens: int | None = None,
    temperature: float = 0.3,
    thinking: bool | None = None,
    timeout: float | None = None,
) -> dict:
    """One completion. Returns the text and, when it thought, its reasoning.

    The reasoning is handed back rather than thrown away because on the `think`
    tier it is most of the value — the user asked for something that thinks a
    problem through, and being able to read the thinking is how they judge
    whether to trust the conclusion.
    """
    model = resolve(tier)
    thinks = TIER_THINKS.get(tier, False) if thinking is None else bool(thinking)
    if thinks:
        free = available_mb()
        if 0 <= free < MIN_FREE_MB_FOR_THINKING:
            raise NotEnoughMemory(
                f"Only {free} MB of memory is available and there is no swap on "
                f"this machine, so a long thinking call could lock it up. Close "
                f"something, or use the rules tier - it needs no model at all."
            )
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens or TIER_BUDGET.get(tier, 1200),
        "temperature": temperature,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": thinks},
        # Every prompt here is a different situation pack, so a cached prompt
        # can never be reused. Left on, llama.cpp's prompt cache grew a model
        # from 1.4 GB to 7.2 GB over one long run, on a machine with no swap.
        "cache_prompt": False,
    }
    started = time.time()
    with _lock:
        try:
            with httpx.Client(
                timeout=timeout or TIER_TIMEOUT.get(tier, 300.0)
            ) as client:
                r = client.post(f"{JAN_BASE}/chat/completions", json=body)
        except Exception as e:
            raise JanUnavailable(f"Jan call failed ({type(e).__name__}: {e})")
    if r.status_code >= 400:
        raise JanUnavailable(f"Jan returned {r.status_code}: {r.text[:300]}")
    message = r.json()["choices"][0]["message"]
    text = (message.get("content") or "").strip()
    reasoning = (message.get("reasoning_content") or "").strip()
    if not text and reasoning and not thinks:
        # Thinking leaked despite the flag being off. Never pass reasoning off
        # as an answer - say so, so the caller can raise the budget instead.
        raise JanUnavailable(
            f"{model} returned only reasoning; raise max_tokens or check its chat template"
        )
    return {
        "text": text,
        "reasoning": reasoning,
        "model": model,
        "seconds": round(time.time() - started, 1),
        "thought": bool(reasoning),
    }


_FENCED = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def chat_json(tier: str, messages: list[dict], default, **kw):
    """A completion that must parse as JSON.

    Small models fence their output or put a sentence in front of it; both are
    tolerated. Anything else returns the default — a malformed answer must not
    become a finding.
    """
    raw = chat(tier, messages, **kw)["text"]
    candidates = [raw, *(m.group(1) for m in _FENCED.finditer(raw))]
    for candidate in candidates:
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
        if start < 0:
            continue
        for end in range(len(candidate), start, -1):
            if candidate[end - 1] not in "}]":
                continue
            try:
                return json.loads(candidate[start:end])
            except Exception:
                continue
    return default
