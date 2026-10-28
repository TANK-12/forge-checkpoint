"""A dated markdown report of one bench run, for the Forge docs library.

The report lists what was tested, the profile's edits (so the numbers can be
reproduced), the verdict cards, the headline metrics and what the model
leaves out. It is written next to the other library documents and never
replaces an earlier one.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path

LIBRARY_DIR = Path(
    os.environ.get(
        "EXOLAB_REPORT_DIR", Path.home() / "Forge" / "docs" / "library" / "exolab"
    )
)
LEFT_OUT = (
    "Not modelled: soft tissue sliding in detail, muscle forces, heat, wear, "
    "control-loop stability and impacts. Material and motor numbers are "
    "typical handbook values, not certified ones."
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "run"


def _edits(profile: dict) -> list[str]:
    lines = []
    for kind, items in sorted((profile.get("knobs") or {}).items()):
        for item_id, ks in sorted(items.items()):
            for knob, mult in sorted(ks.items()):
                if abs(float(mult) - 1.0) > 1e-9:
                    lines.append(f"- {kind} / {item_id}: {knob} x{float(mult):.2f}")
    for kind, items in sorted((profile.get("overrides") or {}).items()):
        for item_id, paths in sorted(items.items()):
            for path, value in sorted(paths.items()):
                lines.append(f"- {kind} / {item_id}: {path} = {value}")
    return lines


def markdown(
    result: dict, model_name: str, test_name: str, profile: dict, day: dt.date
) -> str:
    out = [
        f"# Exo Lab report: {test_name} on {model_name}",
        "",
        f"date: {day.isoformat()} · for: the owner · made by Exo Lab (apps/exolab)",
        "",
        f"- Model: {model_name} (`{result.get('model', '')}`)",
        f"- Test: {test_name} (`{result.get('test', '')}`)",
        f"- Profile: {profile.get('name', 'baseline')}",
        f"- Verdict: **{result.get('verdict', '?')}**",
        "",
    ]
    if result.get("about"):
        out += [str(result["about"]), ""]
    edits = _edits(profile)
    out += ["## Edits in this profile", ""]
    out += edits or ["- none (baseline values)"]
    out += ["", "## Results", ""]
    for c in result.get("cards", []):
        out.append(
            f"- **{c.get('title', '')}** ({c.get('level', '')}): {c.get('value', '')}. {c.get('text', '')}"
        )
    metrics = result.get("metrics") or result.get("peaks") or {}
    if metrics:
        out += ["", "## Numbers", ""]
        for k, val in metrics.items():
            if isinstance(val, dict):
                val = ", ".join(f"{a} {b}" for a, b in val.items()) or "none"
            out.append(f"- {k}: {val}")
    if profile.get("notes"):
        out += ["", "## Notes", "", str(profile["notes"])]
    out += ["", "## What this leaves out", "", LEFT_OUT, ""]
    return "\n".join(out)


def save(
    result: dict,
    model_name: str,
    test_name: str,
    profile: dict,
    folder: Path | None = None,
    day: dt.date | None = None,
) -> Path:
    """Write the report as a new dated file; an earlier one is never touched."""
    day = day or dt.date.today()
    folder = folder or LIBRARY_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{day.isoformat()}-{_slug(str(result.get('model', '')))}-{_slug(str(result.get('test', '')))}"
    path = folder / f"{stem}.md"
    n = 2
    while path.exists():
        path = folder / f"{stem}-{n}.md"
        n += 1
    path.write_text(markdown(result, model_name, test_name, profile, day))
    return path
