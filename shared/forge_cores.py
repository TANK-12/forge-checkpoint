"""Which CPU cores a kind of work may use: shared/core_plan.json.

Relay task 249 (2026-10-21) measured pinning on this laptop's i5-1245U
(CPUs 0-3 are two hyperthreaded P-cores, 4-11 eight E-cores); the numbers are
in docs/library/performance/2026-10-21-core-pinning.md. The plan names slots
("relay-session", "heavy-job"), each with the cores its work may use, and is
off until `enabled` is true. Launchers ask for a slot's cores when they start
something; the pin is sched_setaffinity, which every child process and thread
inherits. systemd's AllowedCPUs= is no use here: the user manager has no
cpuset controller, so it is ignored without a word (checked 2026-10-21).

    python3 ~/Forge/shared/forge_cores.py show
    python3 ~/Forge/shared/forge_cores.py run --slot heavy-job -- CMD...

Stdlib only, so any venv (or plain python3) can import or run it. Anything
unreadable, unknown or empty means "no pin", never an error: a broken plan
must not stop a launch.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

# FORGE_CORE_PLAN points at another plan file (for a check with the plan on)
PLAN = Path(
    os.environ.get("FORGE_CORE_PLAN") or Path(__file__).with_name("core_plan.json")
)
SYSFS = Path("/sys/devices")
NAMED = {"p-cores": "cpu_core/cpus", "e-cores": "cpu_atom/cpus"}


def parse_cpus(text: str) -> set[int]:
    """A kernel CPU list such as "0,4-11" as a set; ValueError on anything else."""
    cpus: set[int] = set()
    for part in text.strip().split(","):
        part = part.strip()
        if not part:
            continue
        lo, dash, hi = part.partition("-")
        first, last = int(lo), int(hi) if dash else int(lo)
        if first < 0 or last < first:
            raise ValueError(f"bad CPU range {part!r}")
        cpus.update(range(first, last + 1))
    return cpus


def format_cpus(cpus: set[int]) -> str:
    """The set back as a kernel CPU list: {0, 1, 2, 5} -> "0-2,5"."""
    runs: list[list[int]] = []
    for cpu in sorted(cpus):
        if runs and runs[-1][1] == cpu - 1:
            runs[-1][1] = cpu
        else:
            runs.append([cpu, cpu])
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def load_plan(path: Path | str = PLAN) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def online_cpus(sysfs: Path = SYSFS) -> set[int]:
    try:
        return parse_cpus((sysfs / "system/cpu/online").read_text())
    except (OSError, ValueError):
        return set(range(os.cpu_count() or 1))


def resolve(spec: str, sysfs: Path = SYSFS) -> set[int]:
    """A slot's cpus value as online CPU numbers (OSError/ValueError if unreadable)."""
    online = online_cpus(sysfs)
    if spec == "all":
        return online
    if spec in NAMED:
        return parse_cpus((sysfs / NAMED[spec]).read_text()) & online
    return parse_cpus(spec) & online


def cpus_for(
    slot: str,
    plan: dict | None = None,
    sysfs: Path = SYSFS,
    allowed: set[int] | None = None,
) -> set[int] | None:
    """The cores a slot's work may use, or None for "do not pin": the plan is
    off, the slot is unknown, its cores cannot be read, or there is nothing to
    narrow. A pin only ever narrows: the slot's cores are kept within the cores
    the caller may already use (`allowed`, default this process's own), so a
    caller someone pinned on purpose is never widened, and a slot that leaves
    it no cores at all leaves it as it is."""
    plan = load_plan() if plan is None else plan
    if plan.get("enabled") is not True:
        return None
    entry = (plan.get("slots") or {}).get(slot)
    if not isinstance(entry, dict) or not isinstance(entry.get("cpus"), str):
        return None
    try:
        cpus = resolve(entry["cpus"], sysfs)
    except (OSError, ValueError):
        return None
    allowed = os.sched_getaffinity(0) if allowed is None else allowed
    cpus &= allowed
    if not cpus or cpus == allowed:
        return None
    return cpus


def taskset_prefix(
    slot: str, plan: dict | None = None, sysfs: Path = SYSFS
) -> list[str]:
    """["taskset", "-c", "4-11"] to put before a command, or [] for no pin."""
    cpus = cpus_for(slot, plan, sysfs)
    taskset = shutil.which("taskset")
    if cpus is None or not taskset:
        return []
    return [taskset, "-c", format_cpus(cpus)]


def pin_self(
    slot: str, plan: dict | None = None, sysfs: Path = SYSFS
) -> set[int] | None:
    """Pin this process (and so whatever it execs or starts next) to the slot."""
    cpus = cpus_for(slot, plan, sysfs)
    if cpus is not None:
        try:
            os.sched_setaffinity(0, cpus)
        except OSError:
            return None
    return cpus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="the plan and each slot's cores")
    run = sub.add_parser("run", help="run a command on a slot's cores")
    run.add_argument("--slot", required=True)
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    plan = load_plan()
    if args.cmd == "show":
        print(f"core plan {'on' if plan.get('enabled') is True else 'off'} ({PLAN})")
        for name, entry in (plan.get("slots") or {}).items():
            spec = entry.get("cpus") if isinstance(entry, dict) else None
            try:
                cpus = (
                    format_cpus(resolve(spec, SYSFS)) if isinstance(spec, str) else "?"
                )
            except (OSError, ValueError):
                cpus = "unreadable"
            print(f"  {name}: {spec} = CPUs {cpus}")
        return 0
    cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not cmd:
        parser.error("run needs a command after --")
    pin_self(args.slot, plan)
    sys.stdout.flush()
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    sys.exit(main())
