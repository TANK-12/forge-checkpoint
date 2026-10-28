"""Auto-close rules: which apps the RAM guard may close, and when.

The RAM guard (apps/power/ram_guard.py) already shuts groups of processes
down in a fixed order when RAM passes kill_percent. Auto-close adds the owner's
own rules on top, one per app:

- a RAM level: close this app once RAM is at least this full (his rule
  replaces the guard's emergency line for that app, so it can be earlier or
  later than 90%);
- an idle time: close it after this many minutes without being used.

What counts as an app is declared, not coded: every group in
shared/ram_guard.json is a target, the "auto_close" block there adds labels,
idle signals and defaults (and may split a group, e.g. Firefox tabs and
Whatsie out of browser-tabs-and-chat), and every Forge app found under apps/
becomes a target of its own. His choices live in rules_file
(~/.config/forge/auto_close.json), written by the Settings app's System
section; the guard writes what it sees and what it closed to status_file.
Stdlib only: the guard's venv and the Settings app's both import it.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

SHARED = Path(__file__).resolve().parent
# FORGE_RAM_REGISTRY: a copy for UI checks, so they never touch his rules
REGISTRY = Path(os.environ.get("FORGE_RAM_REGISTRY") or SHARED / "ram_guard.json")
APPS_DIR = SHARED.parent / "apps"
SIGNALS = ("requests", "cpu", "focus")


def _path(text: str) -> Path:
    return Path(os.path.expanduser(text))


def settings(registry: dict) -> dict:
    """The registry's auto_close block (empty when the registry has none)."""
    block = registry.get("auto_close")
    return block if isinstance(block, dict) else {}


def rules_path(registry: dict) -> Path:
    return _path(
        settings(registry).get("rules_file", "~/.config/forge/auto_close.json")
    )


def status_path(registry: dict) -> Path:
    return _path(
        settings(registry).get(
            "status_file", "~/.local/state/forge-power/auto_close.json"
        )
    )


def load_registry(path: Path | str = REGISTRY) -> dict:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: the registry must be a JSON object")
    return data


# ------------------------------------------------------------ rule matching


def rule_hits(rule: dict, p: dict) -> bool:
    """True when every key of the rule holds for process p (see _groups in
    the registry). An unknown key never matches, so a typo stops nothing."""
    if not rule:
        return False
    for key, want in rule.items():
        if key.startswith("_"):
            continue
        if key == "port":
            if want not in p.get("ports", []):
                return False
        elif key == "comm":
            if not re.fullmatch(want, p.get("comm", "")):
                return False
        elif key in ("args", "cwd", "cgroup"):
            if not re.search(want, p.get(key, "")):
                return False
        else:
            return False
    return True


def any_hit(rules: list[dict] | None, p: dict) -> bool:
    return any(rule_hits(r, p) for r in rules or [])


def owning_group(registry: dict, p: dict) -> str | None:
    """The group a process like p would belong to: the last one that matches."""
    owner = None
    for group in registry.get("groups", []):
        if any_hit(group.get("match", []), p) and not any_hit(group.get("exclude"), p):
            owner = group["name"]
    return owner


# ------------------------------------------------------------------ targets


def forge_apps(apps_dir: Path = APPS_DIR) -> list[dict]:
    """Every Forge app with its own backend under apps/: name, label, icon,
    port and the manifest's optional "auto_close" block. Apps whose code lives
    elsewhere ("root") are left out: the guard's Forge-app group matches by
    the apps/<name> working folder, so it never sees them."""
    out = []
    for manifest in sorted(apps_dir.glob("*/forge_app.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("root"):
            continue
        port = data.get("port")
        if not isinstance(port, int):
            continue
        extra = data.get("auto_close")
        out.append(
            {
                "name": manifest.parent.name,
                "dir": str(manifest.parent),
                "module": str(data.get("module") or "web_app:app"),
                "label": str(data.get("label") or manifest.parent.name),
                "icon": str(data.get("icon") or ""),
                "port": port,
                "auto_close": extra if isinstance(extra, (dict, bool)) else {},
            }
        )
    return out


def _target(entry: dict, group: dict, kind: str) -> dict:
    idle_allowed = entry.get("idle", True) is not False
    low = entry.get("ram_min")
    signals = [s for s in entry.get("signals", []) if s in SIGNALS]
    if not signals:
        idle_allowed = False
    return {
        "name": entry["name"],
        "label": entry.get("label") or group.get("label", entry["name"]),
        "icon": entry.get("icon", ""),
        "kind": kind,
        "group": group["name"],
        "group_label": group.get("label", group["name"]),
        "match": list(entry.get("match", [])),
        "signals": signals,
        "idle_allowed": idle_allowed,
        "idle_why": entry.get("why", ""),
        "note": entry.get("note", ""),
        "save": entry.get("save"),
        "busy": entry.get("busy"),
        "port": entry.get("port"),
        "ram_min": low if isinstance(low, (int, float)) else None,
        "idle_min_mb": entry.get("idle_min_mb"),
        "min_percent": group.get("min_percent", 0),
        "default": {
            "enabled": bool(entry.get("enabled", False)),
            "ram_percent": entry.get("ram_percent"),
            "idle_minutes": int(entry.get("idle_minutes", 0)) if idle_allowed else 0,
        },
    }


def targets(registry: dict, apps_dir: Path = APPS_DIR) -> list[dict]:
    """Every auto-close target, in the guard's stop order.

    Per group: the registry's targets that narrow it ("match") first, then the
    group itself as the catch-all for the rest of its processes. The Forge-app
    group is split into one target per app found under apps/ (only apps whose
    backend would really fall in that group: the Claude app and AI Studio have
    groups of their own). An app target is matched by its manifest port, so a
    test server of the same app on another port stays with the group. A group with no
    entry in the block still appears, with idle closing off ("no idle signal
    declared"), so a new group is never idle-closed by accident.
    """
    block = settings(registry)
    declared = [t for t in block.get("targets", []) if isinstance(t, dict)]
    by_group: dict[str, list[dict]] = {}
    for entry in declared:
        if entry.get("name") and entry.get("group"):
            by_group.setdefault(entry["group"], []).append(entry)
    apps = block.get("forge_apps") or {}
    out: list[dict] = []
    for group in registry.get("groups", []):
        mine = by_group.get(group["name"], [])
        narrow = [e for e in mine if e.get("match")]
        base = next((e for e in mine if not e.get("match")), None)
        if apps.get("group") == group["name"]:
            for app in forge_apps(apps_dir):
                like = {
                    "comm": "python",
                    "args": f"python -m uvicorn {app['module']} --port {app['port']}",
                    "cwd": app["dir"],
                    "cgroup": "",
                    "ports": [app["port"]],
                }
                if owning_group(registry, like) != group["name"]:
                    continue
                extra = app["auto_close"]
                if extra is False:
                    continue
                extra = extra if isinstance(extra, dict) else {}
                entry = {
                    "name": f"app:{app['name']}",
                    "label": app["label"],
                    "icon": app["icon"],
                    "match": [{"port": app["port"]}],
                    "port": app["port"],
                    "signals": apps.get("signals", ["requests", "cpu"]),
                    "enabled": extra.get("enabled", apps.get("enabled", False)),
                    "idle_minutes": extra.get(
                        "idle_minutes", apps.get("idle_minutes", 60)
                    ),
                    "idle": extra.get("idle", True),
                    "why": extra.get("why", ""),
                    "save": extra.get("save"),
                    "busy": extra.get("busy"),
                }
                out.append(_target(entry, group, "app"))
        for entry in narrow:
            out.append(_target(entry, group, "group"))
        if base is None:
            base = {"name": group["name"], "why": "no idle signal declared"}
        out.append(_target(base, group, "group"))
    # the RAM levels a rule may pick: never below the target's floor, and
    # never later than the emergency order would close it anyway
    low, high = block.get("ram_range", [50, 99])
    kill = registry.get("kill_percent", 90)
    for t in out:
        t["ram_low"] = max(low, t["ram_min"] or 0)
        t["ram_high"] = min(high, max(kill, t["min_percent"]))
    return out


# -------------------------------------------------------------------- rules


def load_rules(registry: dict) -> dict:
    """{target name: {enabled, ram_percent, idle_minutes}} as he set them."""
    try:
        data = json.loads(rules_path(registry).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rules = data.get("targets") if isinstance(data, dict) else None
    return rules if isinstance(rules, dict) else {}


def effective(target: dict, rules: dict) -> dict:
    """The rule in force for one target: his choice, else the default.

    Off means none of his rules apply: no idle closing, and the guard's own
    emergency order at kill_percent is all that can close it.
    Values that are not valid now (a hand edit, a floor raised since) fall
    back to the default, so a bad rules file can never break the guard.
    """
    mine = rules.get(target["name"])
    mine = mine if isinstance(mine, dict) else {}
    out = dict(target["default"])
    if problem(target, "ram_percent", out["ram_percent"]):
        out["ram_percent"] = None
    for key in ("enabled", "ram_percent", "idle_minutes"):
        if key in mine and not problem(target, key, mine[key]):
            out[key] = mine[key]
    if out["ram_percent"] is not None:
        out["ram_percent"] = int(out["ram_percent"])
    if not target["idle_allowed"]:
        out["idle_minutes"] = 0
    # what comes back on when he turns it on again (the page shows it greyed)
    out["chosen"] = {
        "ram_percent": out["ram_percent"],
        "idle_minutes": out["idle_minutes"],
    }
    if not out["enabled"]:
        out["ram_percent"], out["idle_minutes"] = None, 0
    # Changed only when it acts differently from the default (a saved rule
    # equal to the default is not), so the page shows reset only then.
    out["custom"] = bool(mine) and _shape(out) != _shape(effective(target, {}))
    return out


def _shape(rule: dict) -> tuple:
    """What a rule does: on or off, and what comes back when it is on."""
    return (
        rule["enabled"],
        rule["chosen"]["ram_percent"],
        rule["chosen"]["idle_minutes"],
    )


def problem(target: dict, key: str, value) -> str | None:
    """What is wrong with one rule value for this target, or None."""
    if key == "enabled":
        return None if isinstance(value, bool) else "enabled must be true or false"
    if key == "ram_percent":
        low, high = target["ram_low"], target["ram_high"]
        if value is None:
            return None
        if low > high:
            return f"{target['label']} has no RAM level of its own, only the emergency order"
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not low <= value <= high
        ):
            return f"RAM level must be {low} to {high}%, or empty"
        return None
    if key == "idle_minutes":
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 24 * 60
        ):
            return "idle minutes must be 0 (never) to 1440"
        if value and not target["idle_allowed"]:
            return f"{target['label']} is never closed for being idle" + (
                f": {target['idle_why']}" if target["idle_why"] else ""
            )
        return None
    return f"unknown rule field: {key}"


def check_change(registry: dict, target: dict, change: dict) -> dict:
    """A cleaned rule change, or ValueError saying what is wrong with it."""
    out: dict = {}
    for key, value in change.items():
        wrong = problem(target, key, value)
        if wrong:
            raise ValueError(wrong)
        if key == "ram_percent" and value is not None:
            value = int(value)
        out[key] = value
    return out


def save_rule(registry: dict, name: str, change: dict | None) -> dict:
    """Change (or with None, reset to the default) one target's rule. Returns
    the whole rules map as stored. Written atomically."""
    known = {t["name"]: t for t in targets(registry)}
    if name not in known:
        raise ValueError(f"no auto-close target called {name!r}")
    rules = load_rules(registry)
    if change is None:
        rules.pop(name, None)
    else:
        target = known[name]
        clean = check_change(registry, target, change)
        merged = dict(rules.get(name) or {}, **clean)
        # A value set back to the default is no longer his choice: dropped,
        # and with nothing left the rule goes, as a reset would leave it.
        base = effective(target, {})
        default = {"enabled": base["enabled"], **base["chosen"]}
        merged = {
            k: v for k, v in merged.items() if k not in default or v != default[k]
        }
        if merged:
            rules[name] = merged
        else:
            rules.pop(name, None)
    _write_json(rules_path(registry), {"targets": rules})
    return rules


def changed(registry: dict) -> list[str]:
    """The labels of the targets whose rule differs from the default."""
    rules = load_rules(registry)
    return [t["label"] for t in targets(registry) if effective(t, rules)["custom"]]


def restore_rules(registry: dict, rules: dict) -> None:
    """Put back a rules map that reset_all() (or a backup) returned."""
    if not isinstance(rules, dict):
        raise ValueError("rules must be a map of target names")
    _write_json(rules_path(registry), {"targets": rules})


def reset_all(registry: dict) -> dict:
    """Every target back to its default rule. Returns the rules it had."""
    before = load_rules(registry)
    _write_json(rules_path(registry), {"targets": {}})
    return before


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ------------------------------------------------------------------- status


def write_status(registry: dict, data: dict) -> None:
    _write_json(status_path(registry), data)


def load_status(registry: dict) -> dict:
    try:
        data = json.loads(status_path(registry).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def describe(registry: dict, now: float | None = None) -> dict:
    """Everything the System page shows: each target with its default, his
    rule, what is in force and what the guard last saw."""
    now = time.time() if now is None else now
    block = settings(registry)
    rules = load_rules(registry)
    status = load_status(registry)
    seen = status.get("targets")
    if not isinstance(seen, dict):
        seen = {}
    updated = status.get("updated")
    # the guard writes it every idle_check_seconds while an idle rule is on,
    # else every status_every_seconds: allow two missed writes
    every = max(
        block.get("status_every_seconds", 300), block.get("idle_check_seconds", 40)
    )
    fresh = isinstance(updated, (int, float)) and now - updated < 2 * every + 60
    listed = []
    for target in targets(registry):
        listed.append(
            dict(
                target,
                rule=effective(target, rules),
                seen=seen.get(target["name"]) if fresh else None,
            )
        )
    return {
        "targets": listed,
        "kill_percent": registry.get("kill_percent", 90),
        "warn_percent": registry.get("warn_percent", 85),
        "ram_range": block.get("ram_range", [50, 99]),
        "idle_choices": block.get("idle_choices", [0, 15, 30, 60, 120, 240]),
        "idle_min_mb": block.get("idle_min_mb", 200),
        "guard_running": fresh,
        "focus": status.get("focus", "unknown") if fresh else "unknown",
        "ram_percent": status.get("ram_percent") if fresh else None,
        "closed": status.get("closed", [])[-30:],
        "rules_file": str(rules_path(registry)),
    }
