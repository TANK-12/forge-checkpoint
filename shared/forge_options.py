"""Per-app options: one `options.json` beside an app's `forge_app.json`.

An app that wants its own options shown in Settings > Apps declares them in
`apps/NAME/options.json`; the file being there is all it takes (found, not
listed anywhere). Each option uses the same keys as a setting in
`forge_theme.SETTINGS`, so the Settings page draws it with the same rows:

    {
      "_about": "...",
      "file": "~/.local/share/forge/calendar/settings.json",
      "dir_env": "FORGE_CALENDAR_DATA",
      "live": "reread",
      "options": {
        "keep_days": {"kind": "int", "default": 365, "min": 0, "max": 3650,
                      "label": "Keep activity for", "help": "...",
                      "group": "Privacy", "scope": "user"},
        "enabled.claude": {"kind": "bool", "default": true, "label": "..."}
      }
    }

- `file`: where the app itself keeps these values (home-relative, must stay
  under home). Default `~/.config/forge/apps/NAME.json`. `dir_env` names an
  environment variable the app reads its data folder from; when it is set,
  the file is that folder plus the file's own name, so Settings writes where
  the app reads.
- `live`: "reread" (the app reads the file again on its own, so a change
  applies without a restart) or "restart" (it applies when the app restarts).
- Kinds: bool, int, number (`min`, `max`, optional `step`, `unit`), choice
  (`choices`, optional `labels`) and text (optional `max_len`, default 200).
- A key with one dot, "enabled.claude", is the entry "claude" inside the
  stored object "enabled".
- `scope`: "user" or "admin" (who should change it; today both are shut
  alike while the Business look is locked).

`save()` checks every value, refuses unknown keys, and writes only the keys
whose value really changes (compared with the raw stored value, so a
hand-edited "yes" is not taken for true). When something changes it asks the
Business lock first (shared/forge_lock.py, as forge_theme.save does; the
app's own panel should ask too, through `look_locks()`) and rewrites those
keys through a temp file and a rename, so keys it does not know stay exactly
as stored. When nothing changes it writes nothing. App options never touch Forge's own settings.json or
the hub's theme.

    python3 shared/forge_options.py check     # checks every options.json
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import threading
from pathlib import Path
from typing import TypeGuard

SHARED = Path(__file__).resolve().parent
APPS_DIR = Path(os.environ.get("FORGE_APPS_DIR", SHARED.parent / "apps"))
FILE_NAME = "options.json"
KINDS = ("bool", "int", "number", "choice", "text")
SCOPES = ("user", "admin")
LIVE = ("reread", "restart")
KEY = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)?$")
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
TEXT_MAX = 200
_WRITE = threading.Lock()


class OptionError(ValueError):
    """An options.json, an app name or a value that cannot be used."""


# --- the registry -------------------------------------------------------------


def _number(value) -> TypeGuard[int | float]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # an int too big for a float
        return False


def spec_problems(spec: dict) -> list[str]:
    """What is wrong with one option's spec (empty when it is fine)."""
    problems = []
    kind = spec.get("kind")
    if kind not in KINDS:
        return [f"kind must be one of {', '.join(KINDS)}"]
    if not isinstance(spec.get("label"), str) or not spec["label"].strip():
        problems.append("label is missing")
    if spec.get("scope", "user") not in SCOPES:
        problems.append("scope must be user or admin")
    if kind in ("int", "number"):
        low, high = spec.get("min"), spec.get("max")
        if not (_number(low) and _number(high) and low <= high):
            problems.append("min and max must be numbers, min not above max")
    if kind == "choice":
        choices = spec.get("choices")
        if not isinstance(choices, list) or not choices:
            problems.append("choices must be a list")
        elif not all(isinstance(c, str) for c in choices):
            problems.append("choices must be text")
    if "default" not in spec:
        problems.append("default is missing")
    elif not problems:
        try:
            clean(spec, spec["default"])
        except OptionError as error:
            problems.append(f"the default is refused by its own rules: {error}")
    return problems


def read_spec(app_dir: Path) -> dict | None:
    """An app's options.json, checked; None when it has none. Raises
    OptionError naming the first problem in a file that is there."""
    path = Path(app_dir) / FILE_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise OptionError(f"{path}: not readable JSON ({error})") from error
    if not isinstance(data, dict) or not isinstance(data.get("options"), dict):
        raise OptionError(f'{path}: needs an "options" object')
    if not data["options"]:
        raise OptionError(f"{path}: lists no options")
    if data.get("live", "reread") not in LIVE:
        raise OptionError(f"{path}: live must be reread or restart")
    for key, spec in data["options"].items():
        if not KEY.fullmatch(key):
            raise OptionError(f"{path}: {key!r} is not a usable key")
        if not isinstance(spec, dict):
            raise OptionError(f"{path}: {key} must be an object")
        problems = spec_problems(spec)
        if problems:
            raise OptionError(f"{path}: {key}: {problems[0]}")
    _ = file_for(data, Path(app_dir).name)  # a file outside home is refused
    return data


def file_for(data: dict, name: str) -> Path:
    """Where the app keeps its option values."""
    raw = data.get("file") or f"~/.config/forge/apps/{name}.json"
    if not isinstance(raw, str) or not raw.startswith("~/"):
        raise OptionError(f"{name}: file must start with ~/")
    home = Path.home()
    rest = raw[2:]
    path = home / rest
    if (
        rest.startswith("/")
        or ".." in Path(rest).parts
        or not path.is_relative_to(home)
    ):
        raise OptionError(f"{name}: file must stay under the home folder")
    env = data.get("dir_env")
    if isinstance(env, str) and os.environ.get(env):
        return Path(os.environ[env]).expanduser() / path.name
    return path


def app_dir(name: str, apps_dir: Path | None = None) -> Path:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise OptionError("not an app name")
    return Path(apps_dir or APPS_DIR) / name


def spec_for(name: str, apps_dir: Path | None = None) -> dict:
    data = read_spec(app_dir(name, apps_dir))
    if data is None:
        raise OptionError(f"{name} has no {FILE_NAME}")
    return data


# --- values -------------------------------------------------------------------


def clean(spec: dict, value):
    """The value as stored, or OptionError saying why it is refused."""
    kind = spec["kind"]
    if kind == "bool":
        if not isinstance(value, bool):
            raise OptionError("must be on or off")
        return value
    if kind in ("int", "number"):
        if not _number(value):
            raise OptionError("must be a number")
        if kind == "int":
            if value != int(value):
                raise OptionError("must be a whole number")
            value = int(value)
        if not spec["min"] <= value <= spec["max"]:
            raise OptionError(f"must be from {spec['min']} to {spec['max']}")
        return value
    if kind == "choice":
        if value not in spec["choices"]:
            raise OptionError(f"must be one of {', '.join(spec['choices'])}")
        return value
    if not isinstance(value, str):
        raise OptionError("must be text")
    value = value.strip()
    if len(value) > int(spec.get("max_len", TEXT_MAX)):
        raise OptionError("is too long")
    return value


def _stored(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _get(stored: dict, key: str):
    """(found, value) for a plain or one-dot key."""
    if "." in key:
        outer, inner = key.split(".", 1)
        box = stored.get(outer)
        if isinstance(box, dict) and inner in box:
            return True, box[inner]
        return False, None
    return (key in stored), stored.get(key)


def _changes(stored: dict, key: str, value, spec: dict) -> bool:
    """Whether storing `value` changes what the app reads: compared with the
    raw stored value (a hand-edited "yes" is not True), or with the default
    when the key is not stored."""
    found, raw = _get(stored, key)
    if not found:
        return value != spec["default"]
    if _number(raw) and _number(value) and spec["kind"] in ("int", "number"):
        return raw != value
    return type(raw) is not type(value) or raw != value


def values(data: dict, path: Path) -> dict:
    """Every option's value: the stored one when it is usable, else the
    default. A stored number outside today's range is brought inside it."""
    stored = _stored(path)
    out = {}
    for key, spec in data["options"].items():
        found, value = _get(stored, key)
        if found and spec["kind"] in ("int", "number") and _number(value):
            value = min(max(value, spec["min"]), spec["max"])
        try:
            out[key] = clean(spec, value) if found else spec["default"]
        except OptionError:
            out[key] = spec["default"]
    return out


def load(name: str, apps_dir: Path | None = None) -> dict:
    data = spec_for(name, apps_dir)
    return values(data, file_for(data, name))


def look_locks() -> bool:
    """Whether Forge's chosen look locks its settings (Business)."""
    if str(SHARED) not in sys.path:
        sys.path.insert(0, str(SHARED))
    import forge_theme  # here, not at the top: it is large and only saves need it

    return bool(forge_theme.look_rules(forge_theme.load()["look"])["locked"])


def save(name: str, changes: dict, apps_dir: Path | None = None) -> dict:
    """Check and store `changes` ({key: value}) in the app's own file and
    return every value. Unknown keys and bad values raise OptionError; a
    real change while the Business look is locked raises forge_lock.Locked."""
    data = spec_for(name, apps_dir)
    if not isinstance(changes, dict):
        raise OptionError("send an object of option: value")
    specs = data["options"]
    cleaned = {}
    for key, value in changes.items():
        if key not in specs:
            raise OptionError(f"{name} has no option {key}")
        try:
            cleaned[key] = clean(specs[key], value)
        except OptionError as error:
            raise OptionError(f"{specs[key]['label']} {error}") from error
    path = file_for(data, name)
    with _WRITE:
        stored = _stored(path)
        changed = {k: v for k, v in cleaned.items() if _changes(stored, k, v, specs[k])}
        if not changed:
            return values(data, path)  # nothing to write, so nothing to lock
        import forge_lock

        forge_lock.check(look_locks())
        for key, value in changed.items():
            if "." in key:
                outer, inner = key.split(".", 1)
                box = stored.get(outer)
                stored[outer] = {**(box if isinstance(box, dict) else {}), inner: value}
            else:
                stored[key] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(stored, indent=1), encoding="utf-8")
        tmp.replace(path)
    return values(data, path)


# --- for Settings -------------------------------------------------------------


def _manifest(folder: Path) -> dict:
    try:
        data = json.loads((folder / "forge_app.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def describe_all(apps_dir: Path | None = None) -> dict:
    """Every app with options (specs and values), every app without, and
    any options.json that could not be used, for Settings > Apps."""
    apps, without, broken = [], [], []
    folders = sorted(
        p.parent for p in Path(apps_dir or APPS_DIR).glob("*/forge_app.json")
    )
    for folder in folders:
        manifest = _manifest(folder)
        name = str(manifest.get("name") or folder.name)
        label = str(manifest.get("label") or name)
        try:
            data = read_spec(folder)
        except OptionError as error:
            broken.append({"name": folder.name, "label": label, "error": str(error)})
            continue
        if data is None:
            without.append({"name": folder.name, "label": label})
            continue
        path = file_for(data, folder.name)
        apps.append(
            {
                "name": folder.name,
                "label": label,
                "icon": str(manifest.get("icon") or ""),
                "about": str(data.get("about") or ""),
                "live": data.get("live", "reread"),
                "file": str(path),
                "options": data["options"],
                "values": values(data, path),
            }
        )
    return {"apps": apps, "without": without, "broken": broken}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] != ["check"]:
        print("usage: forge_options.py check [apps folder]")
        return 2
    found = describe_all(Path(argv[1]) if len(argv) > 1 else None)
    for app in found["apps"]:
        print(f"ok      {app['name']}: {len(app['options'])} options in {app['file']}")
    for app in found["broken"]:
        print(f"broken  {app['error']}")
    print(f"{len(found['without'])} apps have no {FILE_NAME} yet")
    return 1 if found["broken"] else 0


if __name__ == "__main__":
    sys.exit(main())
