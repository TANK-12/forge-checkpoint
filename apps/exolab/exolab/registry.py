"""The data registry and the owner's profiles.

Every sub-folder of ``data/`` is a kind (materials, actuators, mechanisms,
models, tests, motions, human, power, game) and every ``*.json`` in it is one
item, keyed by its ``id`` (the file stem when absent). Nothing lists them in
code: a new material or test is one new file.

A **profile** holds the owner's edits and never touches the baselines:

    knobs:     {kind: {item_id: {knob: multiplier}}}  the four relative knobs
               (stiffness, strength, weight, power), mapped to fields by
               data/knobs.json
    overrides: {kind: {item_id: {"dotted.path": absolute value}}}  advanced
               mode: any field, including nested ones ("joints.0.actuator")

Effective value = override if set, else baseline x knob. ``data/limits.json``
bounds what an override may be, so a typed 0 cannot divide a bench by zero,
and says which text fields may change at all (``text``): a pick from fixed
choices, another item's id, or words that only describe. Text that decides
how an item is built (a kind, a status, a section shape, a link role) is
fixed, so only its data file changes it.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROFILE_DIR = (
    Path(os.environ.get("EXOLAB_DATA", Path.home() / "ForgeGameData" / "exolab"))
    / "profiles"
)
# Whole-name match: no trailing space, dot or newline.
NAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9 _.-]{0,46}[A-Za-z0-9_-])?")
KNOB_NAMES = ("stiffness", "strength", "weight", "power")
KNOB_MIN, KNOB_MAX = 0.05, 20.0
SHARED_DIR = Path(os.environ.get("FORGE_SHARED_DIR") or ROOT.parent.parent / "shared")
CHAR_DIR = SHARED_DIR / "assets" / "characters"


class NotFound(KeyError):
    """An id, profile or motion that does not exist (HTTP 404). Any other
    KeyError is a setting the physics could not use (HTTP 400)."""


class Registry:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.items: dict[str, dict[str, dict]] = {}
        self.knobs: dict = {}
        self.limits: dict = {}
        self.reload()

    def reload(self) -> None:
        items: dict[str, dict[str, dict]] = {}
        for sub in sorted(p for p in self.data_dir.iterdir() if p.is_dir()):
            kind: dict[str, dict] = {}
            for f in sorted(sub.glob("*.json")):
                obj = json.loads(f.read_text())
                obj.setdefault("id", f.stem)
                kind[obj["id"]] = obj
            items[sub.name] = kind
        self.items = items
        self.knobs = json.loads((self.data_dir / "knobs.json").read_text())
        lim = self.data_dir / "limits.json"
        self.limits = json.loads(lim.read_text()) if lim.exists() else {}

    def kinds(self) -> list[str]:
        return list(self.items)

    def get(self, kind: str, item_id: str) -> dict:
        try:
            return copy.deepcopy(self.items[kind][item_id])
        except KeyError:
            raise NotFound(f"no {kind} item named {item_id!r}") from None

    def ids(self, kind: str) -> list[str]:
        return list(self.items.get(kind, {}))

    def summaries(self) -> dict[str, list[dict]]:
        keep = ("id", "name", "category", "kind", "note", "about", "colour", "group")
        return {
            kind: [{k: it[k] for k in keep if k in it} for it in items.values()]
            for kind, items in self.items.items()
        }

    def effective(self, kind: str, item_id: str, profile: dict | None) -> dict:
        """The item with the profile's knobs and overrides applied.

        Overrides are absolute values, so they go in first and a knob never
        scales an overridden field. Derived fields fill in after the
        overrides, so a derived limit follows an overridden source.
        """
        item = self.get(kind, item_id)
        prof = profile or {}
        knobs = prof.get("knobs", {}).get(kind, {}).get(item_id, {})
        overrides = prof.get("overrides", {}).get(kind, {}).get(item_id, {})
        for path, value in overrides.items():
            try:
                set_path(item, path, value)
            except (KeyError, IndexError, ValueError, TypeError):
                continue  # a stale path from an older data file
        derived = self.knobs.get("derived", {}).get(kind, {})
        for target, (source, factor) in derived.items():
            if target not in item and isinstance(item.get(source), (int, float)):
                item[target] = item[source] * factor
        motorless = kind == "actuators" and self.motorless(item)
        for knob, mult in knobs.items():
            if knob == "power" and motorless:
                continue  # no motor to make bigger; check_knobs says so
            for fname, exp in self.knob_fields(kind, knob).items():
                if fname in overrides:
                    continue
                if isinstance(item.get(fname), (int, float)):
                    item[fname] = item[fname] * clamp_knob(mult) ** exp
        return item

    def knob_fields(self, kind: str, knob: str) -> dict[str, float]:
        """The fields a knob scales on an item of this kind, each with the
        power the multiplier is raised to (data/knobs.json; a plain list
        there means 1 for each)."""
        got = self.knobs.get("fields", {}).get(kind, {}).get(knob) or []
        if isinstance(got, dict):
            return {str(f): float(e) for f, e in got.items()}
        return {str(f): 1.0 for f in got}

    def motorless(self, actuator: dict) -> bool:
        """An actuator with no motor (knobs.json "motorless" kinds), so the
        power knob has nothing to scale on it."""
        return actuator.get("kind") in self.knobs.get("motorless", [])

    def model_mechanism(self, model: dict, profile: dict | None) -> dict:
        """The shoulder mechanism a model uses, with the model's own defaults
        for it (shoulder.mechanism_overrides keyed by mechanism id, so a swap
        never fits drives chosen for another one) and then the profile's
        edits of it again, so the owner's choice wins."""
        sh = model.get("shoulder") or {}
        mech_id = sh.get("mechanism")
        if not isinstance(mech_id, str):
            raise KeyError("shoulder.mechanism")
        mech = self.effective("mechanisms", mech_id, profile)
        mine_by_model = (sh.get("mechanism_overrides") or {}).get(mech_id) or {}
        mine = (profile or {}).get("overrides", {}).get("mechanisms", {}).get(mech_id)
        for edits in (mine_by_model, mine or {}):
            for path, value in edits.items():
                try:
                    set_path(mech, path, value)
                except (KeyError, IndexError, ValueError, TypeError):
                    continue  # a stale path
        return mech

    def id_kind(self, value: str) -> str | None:
        """The kind that has an item with this id, among the kinds other
        items point at (limits.json text.refs), so a text field holding one
        is an id field."""
        for kind in self.limits.get("text", {}).get("refs") or list(self.items):
            if value in self.items.get(kind, {}):
                return kind
        return None

    def choices(self, field: str) -> list[str] | None:
        """The answers a text field may take: the character folders for a
        character, else limits.json text.choices; None when not listed."""
        if field == "character":
            return characters()
        got = self.limits.get("text", {}).get("choices", {}).get(field)
        return [str(c) for c in got] if isinstance(got, list) else None

    def part_kinds(self, model_id: str, profile: dict | None) -> dict[str, str]:
        """The parts a part knob ("<model>/<part>") may name, each with its
        kind in knobs.json part_knobs (which knobs it reads): the names
        parts.resolve() reads, so the shoulder drives J1.., the elbow and leg
        drives ("drive"; a drive with no motor is its actuator's kind, and a
        leg's is "passive", as the leg physics reads only powered drives),
        every link, cuff and shell, and the battery."""
        if model_id not in self.items.get("models", {}):
            return {}
        model = self.effective("models", model_id, profile)
        acts = self.items.get("actuators", {})

        def drive(spec: Any, leg: bool = False) -> str:
            act = (
                acts.get(str(spec.get("actuator"))) if isinstance(spec, dict) else None
            ) or {}
            if not self.motorless(act):
                return "drive"
            return "passive" if leg else str(act.get("kind"))

        kinds = {"battery": "battery"}
        if (model.get("shoulder") or {}).get("mechanism") in self.items.get(
            "mechanisms", {}
        ):
            mech = self.model_mechanism(model, profile)
            for i, spec in enumerate(mech.get("joints") or []):
                kinds[f"J{i + 1}"] = drive(spec)
        if (model.get("elbow") or {}).get("actuator"):
            kinds["elbow"] = drive(model["elbow"])
        for leg, spec in (model.get("legs") or {}).items():
            if isinstance(spec, dict) and "actuator" in spec:
                kinds[leg] = drive(spec, leg=True)
        for group, kind in (("links", "link"), ("cuffs", "cuff"), ("shells", "shell")):
            for spec in model.get(group) or []:
                if isinstance(spec, dict) and "id" in spec:
                    kinds[str(spec["id"])] = kind
        return kinds

    def knobs_of_parts(
        self, model_id: str, profile: dict | None
    ) -> dict[str, list[str]]:
        """Each part's knobs: its kind (part_kinds) through knobs.json
        part_knobs, all part knobs for a kind it does not list, and never
        power on a motorless kind (check_knobs refuses it)."""
        table = self.knobs.get("part_knobs", {})
        every = list(self.knobs.get("fields", {}).get("parts", {}))
        no_motor = self.knobs.get("motorless", [])
        return {
            part: [
                k
                for k in table.get(kind, every)
                if not (k == "power" and kind in no_motor)
            ]
            for part, kind in self.part_kinds(model_id, profile).items()
        }

    def part_ids(self, model_id: str, profile: dict | None) -> set[str]:
        """The part names a part knob may use (see part_kinds)."""
        return set(self.part_kinds(model_id, profile))

    def limit(self, kind: str, path: str, old: float) -> tuple[float, float]:
        """The range a typed number must stay in: data/limits.json when it
        names the field (``*`` matches any one step of the path), else the
        baseline's sign and at most 1000 times its size."""
        keys = path.split(".")
        for pattern, rng in self.limits.get(kind, {}).items():
            pat = pattern.split(".")
            if len(pat) == len(keys) and all(p in ("*", k) for p, k in zip(pat, keys)):
                return float(rng[0]), float(rng[1])
        span = 1000.0 * max(abs(old), 1.0)
        return (0.0 if old >= 0 else -span), span

    def check_knobs(
        self, knobs: Any, overrides: dict | None = None
    ) -> tuple[dict, list[str]]:
        """Keep the knobs that name a real item and a knob its kind has
        (clamped); say why each other one was dropped. Part knobs are keyed
        "<model>/<part>" and must name a part the model has once the clean
        overrides are in (a mechanism swap changes the shoulder drives),
        and a knob that kind of part reads (knobs.json part_knobs). Power
        needs a motor: a passive actuator or drive takes none, and a passive
        actuator type takes only the knobs its drive reads."""
        clean: dict = {}
        errors: list[str] = []
        if not isinstance(knobs, dict):
            return clean, ["knobs must be an object"] if knobs else []
        fields = self.knobs.get("fields", {})
        parts_of: dict[str, dict[str, str]] = {}
        part_knobs = self.knobs.get("part_knobs", {})
        no_motor = self.knobs.get("motorless", [])
        for kind, items in knobs.items():
            if kind not in fields or not isinstance(items, dict):
                errors.append(f"no knobs for {kind!r}")
                continue
            pool = self.items.get(kind, {})
            for item_id, ks in items.items():
                if kind == "parts":
                    owner, _, part = str(item_id).partition("/")
                    if owner not in parts_of:
                        parts_of[owner] = self.part_kinds(
                            owner, {"overrides": overrides or {}}
                        )
                    part_kind = parts_of[owner].get(part)
                    real = part_kind is not None
                else:
                    real = item_id in pool
                    act = pool[item_id] if kind == "actuators" and real else {}
                    part_kind = act.get("kind") if self.motorless(act) else None
                allowed = list(
                    part_knobs.get(part_kind, fields[kind])
                    if part_kind
                    else fields[kind]
                )
                motorless = part_kind in no_motor
                if not real or not isinstance(ks, dict):
                    errors.append(f"no {kind} item {item_id!r}")
                    continue
                for k, m in ks.items():
                    if k == "power" and motorless:
                        errors.append(
                            f"{kind}/{item_id}: no motor, so no power knob"
                            " (a passive drive has nothing to make bigger)"
                        )
                    elif k not in allowed and motorless:
                        errors.append(
                            f"{kind}/{item_id}: no {k!r} knob (nothing reads"
                            f" the {k} of a {part_kind} drive)"
                        )
                    elif k not in allowed:
                        errors.append(f"{kind}/{item_id}: no {k!r} knob")
                    elif _finite(m) is None:
                        errors.append(f"{kind}/{item_id} {k}: must be a number")
                    else:
                        clean.setdefault(kind, {}).setdefault(str(item_id), {})[k] = (
                            clamp_knob(m)
                        )
        return clean, errors

    def check_overrides(self, overrides: Any) -> tuple[dict, list[str]]:
        """Keep the overrides that name a real field with a value of the
        same type; say why each other one was dropped."""
        clean: dict = {}
        errors: list[str] = []
        if not isinstance(overrides, dict):
            return clean, ["overrides must be an object"] if overrides else []
        for kind, items in overrides.items():
            if kind not in self.items or not isinstance(items, dict):
                errors.append(f"no kind {kind!r}")
                continue
            for item_id, paths in items.items():
                if item_id not in self.items[kind] or not isinstance(paths, dict):
                    errors.append(f"no {kind} item {item_id!r}")
                    continue
                base = self.items[kind][item_id]
                derived = self.knobs.get("derived", {}).get(kind, {})
                for path, value in paths.items():
                    why = self._override_error(kind, base, str(path), value, derived)
                    if why:
                        errors.append(f"{kind}/{item_id} {path}: {why}")
                        continue
                    clean.setdefault(kind, {}).setdefault(item_id, {})[
                        str(path)
                    ] = value
        return clean, errors

    def _override_error(
        self, kind: str, base: dict, path: str, value: Any, derived: dict
    ) -> str:
        old = get_path(base, path, _MISSING)
        if old is _MISSING and path in derived:
            old = 0.0
        if old is _MISSING:
            return "no such field"
        if isinstance(old, (dict, list)):
            return "only single values can be overridden"
        if old is None:  # an "auto" field: nothing (auto) or a number
            if value is None:
                return ""
            old = 0.0
        if isinstance(old, bool):
            return "" if isinstance(value, bool) else "must be true or false"
        if isinstance(old, (int, float)):
            f = _finite(value)
            if f is None:
                return "must be a number"
            lo, hi = self.limit(kind, path, float(old))
            if not lo <= f <= hi:
                return f"must be between {lo:g} and {hi:g}"
            return ""
        if isinstance(old, str):
            return self._text_error(path, old, value)
        return "bad value"

    def _text_error(self, path: str, old: str, value: Any) -> str:
        """Text may be a pick from fixed choices, another item's id, or
        words that only describe; any other text builds the item."""
        if not isinstance(value, str):
            return "must be text"
        text = self.limits.get("text", {})
        cap = int(text.get("max_chars", 200))
        if len(value) > cap:
            return f"must be at most {cap} characters"
        field = path.split(".")[-1]
        choices = self.choices(field)
        if choices is not None:
            return "" if value in choices else f"must be one of {', '.join(choices)}"
        # A part's name is a key in the physics (the mass list), so only an
        # item's own name, and words that only describe, are free.
        free = field in text.get("free", []) and (field != "name" or path == "name")
        if free or field.endswith("_note"):
            return ""
        # text.fixed: fields that hold an id yet are no pick (an actuator's
        # kind builds it; nothing reads the girdle's joint).
        fixed = path == "id" or field in text.get("fixed", [])
        ref = None if fixed else self.id_kind(old)
        if ref:
            return "" if value in self.items[ref] else f"no {ref} item {value!r}"
        return "is fixed: it decides how the item is built, so only its data file changes it"


_MISSING = object()


def characters() -> list[str]:
    """The VRM characters in the shared asset library, one folder each."""
    if not CHAR_DIR.is_dir():
        return []
    return sorted(
        p.name for p in CHAR_DIR.iterdir() if p.is_dir() and any(p.glob("*.vrm"))
    )


def _finite(value: Any) -> float | None:
    """The value as a float when it is a real, finite number (not a bool,
    and not an integer too big for a float)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        f = float(value)
    except OverflowError:
        return None
    return f if math.isfinite(f) else None


def clamp_knob(x: Any) -> float:
    try:
        f = float(x)
    except (TypeError, ValueError, OverflowError):
        return 1.0
    if f != f:  # NaN
        return 1.0
    return min(KNOB_MAX, max(KNOB_MIN, f))


def _index(k: str) -> int:
    """A list position in a path: digits only, so "-1" is no position."""
    if not (k.isascii() and k.isdigit()):
        raise ValueError(f"{k!r} is not a list position")
    return int(k)


def set_path(obj: Any, path: str, value: Any) -> None:
    """Set a dotted path ("joints.0.actuator") inside nested dicts and lists."""
    keys = path.split(".")
    cur = obj
    for k in keys[:-1]:
        cur = cur[_index(k)] if isinstance(cur, list) else cur.setdefault(k, {})
    last = keys[-1]
    if isinstance(cur, list):
        cur[_index(last)] = value
    else:
        cur[last] = value


def get_path(obj: Any, path: str, default: Any = None) -> Any:
    cur = obj
    try:
        for k in path.split("."):
            cur = cur[_index(k)] if isinstance(cur, list) else cur[k]
    except (KeyError, IndexError, ValueError, TypeError):
        return default
    return cur


# ----- profiles (the owner's edits, stored outside the repo) -----


def empty_profile(name: str) -> dict:
    return {"name": name, "knobs": {}, "overrides": {}, "notes": ""}


def profile_path(name: str) -> Path:
    if not NAME_RE.fullmatch(name):
        raise ValueError(
            "profile names use letters, digits, space, dot, dash, underscore"
        )
    return PROFILE_DIR / f"{name}.json"


def list_profiles() -> list[str]:
    names = {"baseline"}
    if PROFILE_DIR.is_dir():
        names.update(p.stem for p in PROFILE_DIR.glob("*.json") if p.is_file())
    return sorted(names, key=lambda n: (n != "baseline", n.lower()))


def load_profile(name: str | None) -> dict:
    """The named profile; 'baseline' (or none) is the untouched data."""
    if not name or name == "baseline":
        return empty_profile("baseline")
    p = profile_path(name)
    if not p.exists():
        raise NotFound(f"no profile named {name!r}")
    if not p.is_file():
        raise ValueError(f"profile {name!r} is not a file")
    try:
        prof = json.loads(p.read_text())
    except ValueError as e:
        raise ValueError(f"profile {name!r} is not valid JSON: {e}") from None
    if not isinstance(prof, dict):
        raise ValueError(f"profile {name!r} is not a JSON object")
    prof.setdefault("knobs", {})
    prof.setdefault("overrides", {})
    prof["name"] = name
    return prof


def clean_profile(
    name: str, prof: dict, reg: Registry | None = None
) -> tuple[dict, list[str]]:
    """A profile reduced to known knobs (clamped) and, given the registry,
    knobs on real items and valid overrides; the second value lists what was
    dropped and why."""
    raw = prof.get("knobs") or {}
    errors: list[str] = []
    if reg is not None:
        overrides, more = reg.check_overrides(prof.get("overrides") or {})
        knobs, errors = reg.check_knobs(raw, overrides)
        errors += more
    else:
        knobs = {
            str(kind): {
                str(i): {
                    str(k): clamp_knob(m) for k, m in ks.items() if k in KNOB_NAMES
                }
                for i, ks in items.items()
                if isinstance(ks, dict)
            }
            for kind, items in (raw.items() if isinstance(raw, dict) else [])
            if isinstance(items, dict)
        }
        overrides = prof.get("overrides") or {}
    clean = {
        "name": name,
        "knobs": knobs,
        "overrides": overrides,
        "notes": str(prof.get("notes", ""))[:4000],
    }
    return clean, errors


def edits_of(prof: dict) -> str:
    """A profile's edits as one comparable string (1x knobs change nothing)."""
    knobs = {
        kind: {i: {k: m for k, m in ks.items() if m != 1.0} for i, ks in items.items()}
        for kind, items in (prof.get("knobs") or {}).items()
    }
    knobs = {kd: {i: ks for i, ks in its.items() if ks} for kd, its in knobs.items()}
    knobs = {kd: its for kd, its in knobs.items() if its}
    return json.dumps([knobs, prof.get("overrides") or {}], sort_keys=True)


_LOOKS = str.maketrans(
    {
        "i": "l",
        "1": "l",
        "7": "l",
        "0": "o",
        "4": "a",
        "8": "b",
        "6": "b",
        "5": "s",
        "3": "e",
    }
)


def reserved(name: str) -> bool:
    """True for "baseline" and names that read like it: any case, I, 1 or 7
    for l, 0 for o, 4 for a, 8 or 6 for b, 5 for s, 3 for e, spaces and
    marks left out. As I and l read the same, "basellne" is refused too."""
    skeleton = re.sub(r"[^a-z0-9]", "", name.lower()).translate(_LOOKS)
    return skeleton == "baseline".translate(_LOOKS)


def save_profile(
    name: str,
    prof: dict,
    reg: Registry | None = None,
    rules: Callable[[dict], list[str]] | None = None,
) -> dict:
    """Write a profile; with the registry, refuse one with bad overrides,
    and with ``rules`` one whose fields break a rule between them (the
    benches' cross_errors), so a profile that saves also runs."""
    if reserved(name):
        raise ValueError(
            f"{name!r} reads as the baseline, which is read-only; save under another name"
        )
    path = profile_path(name)
    clean, errors = clean_profile(name, prof, reg)
    if not errors and rules:
        errors = rules(clean)
    if errors:
        raise ValueError("; ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=2))
    try:
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)  # a folder in the way: leave nothing behind
        raise
    return clean
