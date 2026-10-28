"""Reading and setting up Jan, without anyone having to remember how.

Jan is the user's, not this app's: models get swapped, settings get changed in
its interface, and it rewrites its own `router.preset.ini` on every start. So
rather than assume a configuration, this reads what is actually there and can
push it back to what Dossier needs, on demand, from a button.

Two rules are encoded here rather than left to memory:

* **Exactly one model on the iGPU.** Putting two on it made the larger one emit
  garbage tokens mid-sentence inside otherwise valid JSON - the kind of failure
  that silently poisons extracted facts. The Iris Xe has no dedicated memory and
  Vulkan returned wrong results rather than failing. Everything else runs on the
  CPU, which is also what keeps both processors busy at once.
* **A bounded context.** llama.cpp preallocates the whole KV cache at
  `ctx-size`, so a 50,000-token context cost about 14 GB for two models on a
  machine with no swap.

Nothing here hardcodes a model name. Whatever Jan has is what it works with.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import store

try:  # shared/, on the path when Dossier runs under Forge
    import forge_slim  # pyright: ignore[reportMissingImports]
except ImportError:
    forge_slim = None

JAN_APP_ID = "ai.jan.Jan"
JAN_DATA = Path(
    os.environ.get(
        "JAN_DATA_DIR",
        str(Path.home() / ".var/app/ai.jan.Jan/data/Jan/data/llamacpp"),
    )
)
SETTINGS_FILE = "jan-policy.json"

DEFAULT_POLICY = {
    "ctx_size": 20000,
    # Empty means "let the app pick by its own preference order".
    "tiers": {"triage": "", "reason": "", "deep": ""},
    # Which tier's model gets the iGPU. Everything else runs on the CPU.
    "gpu_tier": "reason",
    "gpu_layers": 99,
}


@dataclass
class ModelInfo:
    name: str
    path: Path
    size_bytes: int = 0
    ctx_size: int | None = None
    gpu_layers: int | None = None
    cpu_moe: bool | None = None
    settings: dict = field(default_factory=dict)

    @property
    def on_gpu(self) -> bool:
        return bool(self.gpu_layers)

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / 1e9, 2)


def _model_dirs() -> list[Path]:
    base = JAN_DATA / "models"
    if not base.is_dir():
        return []
    return sorted(
        d for d in base.iterdir() if d.is_dir() and (d / "model.yml").is_file()
    )


def _read_yaml(path: Path) -> dict:
    """Jan's model.yml is flat `key: value`; a parser is not worth a dependency."""
    out: dict = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
                continue
            key, _, raw = line.partition(":")
            value = raw.strip()
            if value in ("true", "false"):
                parsed: object = value == "true"
            elif re.fullmatch(r"-?\d+", value):
                parsed = int(value)
            else:
                parsed = value
            out[key.strip()] = parsed
    except Exception:
        return {}
    return out


def _write_yaml_keys(path: Path, updates: dict, remove: tuple[str, ...] = ()) -> None:
    """Set or remove individual keys, leaving every other line untouched.

    Jan owns this file; rewriting it wholesale would discard settings the user
    chose in its interface.
    """
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    seen = set()
    out = []
    for line in lines:
        key = line.partition(":")[0].strip()
        if key in remove:
            continue
        if key in updates:
            value = updates[key]
            rendered = "true" if value is True else "false" if value is False else value
            out.append(f"{key}: {rendered}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            rendered = "true" if value is True else "false" if value is False else value
            out.append(f"{key}: {rendered}")
    path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")


def models() -> list[ModelInfo]:
    """Every model Jan has on disk, with the settings it will start it under."""
    found = []
    for directory in _model_dirs():
        settings = _read_yaml(directory / "model.yml")
        gguf = directory / "model.gguf"
        found.append(
            ModelInfo(
                name=directory.name,
                path=directory,
                size_bytes=gguf.stat().st_size if gguf.is_file() else 0,
                ctx_size=settings.get("ctx_size"),
                gpu_layers=settings.get("n_gpu_layers"),
                cpu_moe=settings.get("cpu_moe"),
                settings=settings,
            )
        )
    return found


def policy(root: Path | None = None) -> dict:
    stored = store.read_json((root or store.data_root().path) / SETTINGS_FILE, None)
    merged = {**DEFAULT_POLICY, **(stored or {})}
    merged["tiers"] = {**DEFAULT_POLICY["tiers"], **(merged.get("tiers") or {})}
    return merged


def set_policy(updates: dict, root: Path | None = None) -> dict:
    current = policy(root)
    if "tiers" in updates:
        current["tiers"] = {**current["tiers"], **(updates.pop("tiers") or {})}
    current.update(updates)
    store.write_json((root or store.data_root().path) / SETTINGS_FILE, current)
    return current


def plan(root: Path | None = None) -> list[dict]:
    """What `apply()` would change, without changing it."""
    settings = policy(root)
    gpu_model = (settings["tiers"] or {}).get(settings.get("gpu_tier", "reason"), "")
    steps = []
    for model in models():
        wants_gpu = bool(gpu_model) and model.name == gpu_model
        if not gpu_model:
            # No explicit choice: keep whichever model already had the GPU, so
            # pressing the button does not quietly move it.
            wants_gpu = model.on_gpu
        changes = {}
        if model.ctx_size != settings["ctx_size"]:
            changes["ctx_size"] = f"{model.ctx_size} -> {settings['ctx_size']}"
        if wants_gpu and model.gpu_layers != settings["gpu_layers"]:
            changes["n_gpu_layers"] = f"{model.gpu_layers} -> {settings['gpu_layers']}"
        if not wants_gpu and model.gpu_layers:
            changes["n_gpu_layers"] = f"{model.gpu_layers} -> removed (CPU)"
        if wants_gpu and model.cpu_moe:
            changes["cpu_moe"] = "true -> false"
        steps.append(
            {
                "model": model.name,
                "size_gb": model.size_gb,
                "target": "iGPU" if wants_gpu else "CPU",
                "changes": changes,
            }
        )
    return steps


def apply(root: Path | None = None) -> list[dict]:
    """Write the policy into Jan's per-model settings.

    Only `model.yml` is touched: Jan regenerates `router.preset.ini` from it on
    every start, so writing the preset directly would be undone.
    """
    settings = policy(root)
    applied = plan(root)
    for model, step in zip(models(), applied):
        if step["target"] == "iGPU":
            _write_yaml_keys(
                model.path / "model.yml",
                {
                    "ctx_size": settings["ctx_size"],
                    "n_gpu_layers": settings["gpu_layers"],
                    "cpu_moe": False,
                },
            )
        else:
            _write_yaml_keys(
                model.path / "model.yml",
                {"ctx_size": settings["ctx_size"]},
                remove=("n_gpu_layers",),
            )
    return applied


def running() -> bool:
    try:
        return bool(
            subprocess.run(
                ["pgrep", "-x", "Jan"], capture_output=True, text=True
            ).stdout.strip()
        )
    except Exception:
        return False


def stop(timeout: float = 20.0) -> bool:
    for signal in ("-TERM", "-KILL"):
        for name in ("Jan", "llama-server"):
            subprocess.run(["pkill", signal, "-x", name], capture_output=True)
        deadline = time.time() + timeout / 2
        while time.time() < deadline:
            if not running():
                break
            time.sleep(0.5)
        if not running():
            break
    return not running()


def start(wait: float = 180.0) -> bool:
    """Launch Jan and wait until its API lists at least one model."""
    if not shutil.which("flatpak"):
        return False
    cmd = ["flatpak", "run", JAN_APP_ID]
    subprocess.Popen(
        # Jan's CPU inference keeps the huge pages Forge turns off for itself
        forge_slim.huge_pages(cmd) if forge_slim else cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    import llm

    deadline = time.time() + wait
    while time.time() < deadline:
        try:
            if llm.available_models(refresh=True):
                return True
        except Exception:
            pass
        time.sleep(3.0)
    return False


def reset(root: Path | None = None) -> dict:
    """Stop Jan, push the settings Dossier needs, start it again."""
    was_running = running()
    stopped = stop()
    applied = apply(root)
    started = start()
    return {
        "was_running": was_running,
        "stopped": stopped,
        "applied": applied,
        "started": started,
        "policy": policy(root),
    }
