#!/usr/bin/env python3
"""Sort software licences into allow, deny and unknown (release/licence_policy.json).

    python3 release/licence_check.py          every included app's venv
    python3 release/licence_check.py --deny   only what is not allowed
    python3 release/licence_check.py --strict an unknown licence fails too

classify() reads one licence text. Options joined by "or" (and the ", "
build.py uses to join licence classifiers) pass when any option is allowed;
parts joined by "and" pass only when every part is. Within one option the
policy's review patterns are tried first (unknown: a person decides), then
deny, then allow; anything else, and an empty or "see its own files" text, is
unknown.

problems() turns the packages build.py's distributions() lists into errors
(deny with no exception) and warnings (unknown, or a deny the policy
excepts).

The CLI reads, without changing anything, the package metadata in the venv
of every app release/release.json includes, through build.py's own
distributions(), and prints one line per package; where build.py's short
licence text is empty it reads the whole License field itself. Note that a dev venv
holds more than a bundle ships (pytest and the like). Exit status 1 when a
package is denied with no exception (with --strict, also when one is
unknown).

Decision: not wired into build.py or
release.json, which task 356 owns; wiring it is one call after
distributions() and one registry key.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
POLICY = HERE / "licence_policy.json"
UNKNOWN_TEXTS = {"", "see its own files", "unknown", "license.txt", "license"}


def load_policy(path: Path = POLICY) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _matches(text: str, patterns: list[str]) -> bool:
    low = text.lower()
    return any(fnmatch.fnmatchcase(low, p.lower()) for p in patterns)


def _one(option: str, policy: dict) -> str:
    option = option.strip().strip("()").strip()
    if option.lower() in UNKNOWN_TEXTS:
        return "unknown"
    if _matches(option, policy.get("review", [])):
        return "unknown"
    if _matches(option, policy.get("deny", [])):
        return "deny"
    if _matches(option, policy.get("allow", [])):
        return "allow"
    return "unknown"


OPS = {"and", "or", ",", "/", "(", ")"}
SPLIT = re.compile(r"((?:^|\s+)(?:and/or|and|or)(?=\s|$)|,|/|\(|\))", re.I)


def _tokens(text: str) -> list[str]:
    """Licence names and the operators in OPS. "and/or" reads as "or". A
    bracket straight after a name belongs to that name, as in "Mozilla Public
    License 2.0 (MPL 2.0)"; anywhere else it groups."""
    out: list[str] = []
    in_name = 0  # open brackets inside the current name
    for raw in SPLIT.split(text):
        tok = raw.strip()
        if not tok:
            continue
        if in_name or (tok == "(" and out and out[-1] not in OPS):
            out[-1] += (" " if tok == "(" and not in_name else "") + raw
            in_name += {"(": 1, ")": -1}.get(tok, 0)
            continue
        low = tok.lower()
        out.append("or" if low == "and/or" else low if low in OPS else tok)
    if in_name:
        raise ValueError("a bracket in a name is not closed")
    return [" ".join(t.split()) for t in out]


def classify(text: str, policy: dict | None = None) -> str:
    """allow, deny or unknown for one package's licence text.

    "or" and "/" join options: allow when any option is allowed, else deny
    when any is denied. "and" and the ", " build.py joins classifiers with
    join parts that all apply: deny when any part is denied, allow only when
    every part is. "and" binds tighter than "or" and brackets group, so
    "AGPL-3.0 AND (MIT OR BSD)" is denied. A text that does not parse is
    denied when a deny pattern matches it whole, else unknown."""
    policy = policy or load_policy()
    text = (text or "").strip()
    if text.lower() in UNKNOWN_TEXTS:
        return "unknown"
    # "Apache License, Version 2.0" is one name, not two parts
    text = re.sub(r",\s*(?=version\b)", " ", text, flags=re.I)
    tokens: list[str] = []
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def either(verdicts: list[str]) -> str:
        if "allow" in verdicts:
            return "allow"
        return "deny" if "deny" in verdicts else "unknown"

    def both(verdicts: list[str]) -> str:
        if "deny" in verdicts:
            return "deny"
        return "allow" if all(v == "allow" for v in verdicts) else "unknown"

    def expr() -> str:
        nonlocal pos
        verdicts = [term()]
        while peek() in ("or", "/"):
            pos += 1
            verdicts.append(term())
        return either(verdicts)

    def term() -> str:
        nonlocal pos
        verdicts = [clause()]
        while peek() in ("and", ","):
            pos += 1
            verdicts.append(clause())
        return both(verdicts)

    def clause() -> str:
        nonlocal pos
        tok = peek()
        if tok == "(":
            pos += 1
            verdict = expr()
            if peek() != ")":
                raise ValueError("unbalanced bracket")
            pos += 1
            return verdict
        if tok is None or tok in OPS:
            raise ValueError("a licence name is missing")
        pos += 1
        return _one(tok, policy)

    try:
        tokens = _tokens(text)
        verdict = expr()
        if pos != len(tokens):
            raise ValueError("text left over")
    except ValueError:
        return "deny" if _one(text, policy) == "deny" else "unknown"
    return verdict


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def problems(dists: list[dict], policy: dict | None = None) -> dict[str, list[str]]:
    """{"errors": [...], "warnings": [...]} for build.py's distributions()."""
    policy = policy or load_policy()
    excepted = {_norm(k): v for k, v in policy.get("exceptions", {}).items()}
    errors, warnings = [], []
    for d in dists:
        verdict = classify(d.get("licence", ""), policy)
        label = f"{d['name']} {d.get('version', '?')}: {d.get('licence', '')}"
        if verdict == "deny":
            reason = excepted.get(_norm(d["name"]))
            if reason:
                warnings.append(f"{label} (denied, excepted: {reason})")
            else:
                errors.append(f"{label} (denied)")
        elif verdict == "unknown":
            warnings.append(f"{label} (unknown, needs a look)")
    return {"errors": errors, "warnings": warnings}


def full_licence(site: Path, name: str) -> str:
    """A package's whole licence text from its METADATA, for when build.py's
    short one is empty: build.py drops a License field over 60 characters,
    which hid PyMuPDF's "GNU AFFERO GPL 3.0 or Artifex Commercial License"."""
    for meta in site.glob("*.dist-info/METADATA"):
        if _norm(meta.parent.name.split("-")[0]) != _norm(name):
            continue
        head = meta.read_text(encoding="utf-8", errors="replace").split("\n\n")[0]
        fields: dict[str, list[str]] = {}
        for line in head.splitlines():
            if ": " in line and not line.startswith(" "):
                key, value = line.split(": ", 1)
                fields.setdefault(key, []).append(value.strip())
        for key in ("License-Expression", "License"):
            if (fields.get(key) or [""])[0]:
                return fields[key][0]
        classes = [
            c for c in fields.get("Classifier", []) if c.startswith("License ::")
        ]
        if classes:
            return ", ".join(c.split(" :: ")[-1] for c in classes)
        return licence_file_title(meta.parent, fields.get("License-File", []))
    return ""


def licence_file_title(info: Path, names: list[str]) -> str:
    """The first line of a package's own licence file ("MIT License") when its
    METADATA names none, as clr_loader's does. A line that names no licence
    (a copyright line) stays unknown under the policy's patterns."""
    for name in names:
        for path in (info / "licenses" / name, info / name):
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip():
                    title = line.strip()
                    return title if len(title) <= 80 else ""
    return ""


def included_sites(registry: dict) -> dict[str, list[Path]]:
    out = {}
    for app, entry in registry.get("apps", {}).items():
        if entry.get("include"):
            venv = ROOT / "apps" / app / ".venv"
            out[app] = sorted(venv.glob("lib/python3*/site-packages"))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--deny", action="store_true", help="only deny and unknown")
    parser.add_argument(
        "--strict", action="store_true", help="an unknown licence fails as well"
    )
    args = parser.parse_args(argv)
    sys.path[:0] = [str(HERE), str(ROOT)]
    import build  # read-only use of distributions()

    policy = load_policy()
    registry = json.loads((HERE / "release.json").read_text(encoding="utf-8"))
    excepted = {_norm(k) for k in policy.get("exceptions", {})}
    seen: dict[str, dict] = {}
    for app, sites in included_sites(registry).items():
        if not sites:
            print(f"# {app}: no venv found")
        for site in sites:
            for d in build.distributions(site):
                if d["licence"].strip().lower() in UNKNOWN_TEXTS:
                    d = {**d, "licence": full_licence(site, d["name"]) or d["licence"]}
                key = _norm(d["name"])
                entry = seen.setdefault(key, {**d, "apps": []})
                entry["apps"].append(app)
    errors = 0
    counts = {"allow": 0, "deny": 0, "unknown": 0}
    for key in sorted(seen):
        d = seen[key]
        verdict = classify(d["licence"], policy)
        counts[verdict] += 1
        note = ""
        if verdict == "unknown" and args.strict:
            errors += 1
        if verdict == "deny":
            if key in excepted:
                note = " (excepted in the policy)"
            else:
                errors += 1
        if args.deny and verdict == "allow":
            continue
        apps = ",".join(d["apps"]) if len(d["apps"]) < 4 else f"{len(d['apps'])} apps"
        print(f"{verdict:8} {d['name']} {d['version']}: {d['licence']} [{apps}]{note}")
    print(
        f"# {len(seen)} packages: {counts['allow']} allow, {counts['deny']} deny,"
        f" {counts['unknown']} unknown; {errors} failing"
    )
    for item in registry.get("third_party", {}).get("included", []):
        found = re.search(r"\(([^,)]+)", item)
        verdict = classify(found.group(1) if found else "", policy)
        print(f"{verdict:8} vendored: {item.split(':')[0]}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
