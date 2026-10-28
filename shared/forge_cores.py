"""Which CPU cores work runs on: the core plan, quick moves, and job presets.

Relay task 249 (2026-10-21) measured pinning on this laptop's i5-1245U
(CPUs 0-3 are two hyperthreaded P-cores, 4-11 eight E-cores); the numbers are
in docs/library/performance/2026-10-21-core-pinning.md. The plan
(shared/core_plan.json) names slots ("relay-session", "heavy-job"), each with
the cores its work may use, and is off until `enabled` is true. Launchers ask
for a slot's cores when they start something.

Relay task 422 (2026-10-28) added quick moves: move a running process (all its
threads and children) or a whole job to other cores, optionally for a time
after which it goes back, and presets per job name that apply by themselves to
new processes of that job. Jobs are named by shared/core_jobs.json (battle
bot, Relay task N, a forge_ram.py run --name); anything else is its command
name. Moves and presets live in ~/.local/state/forge/cores.json; Power's
priority watcher (forge-power-priority.service) calls tick() every 5 s, which
puts expired moves back and pins new processes of a preset's job.

P- and E-cores are read from the hardware (/sys/devices/cpu_core/cpus and
cpu_atom/cpus on Intel hybrids, cpu_capacity on big.LITTLE ARM; a CPU with
neither has only "P-cores"). A choice ("spec") is one of:

    all          every online CPU
    p-cores      the performance cores   (p-cores:N  the last N of them)
    e-cores      the efficiency cores    (e-cores:N  the last N of them)
    4-7,10       a kernel CPU list

N counts whole cores, so p-cores:1 is both threads of one P-core. The pin is
sched_setaffinity, which every child process and thread inherits. systemd's
AllowedCPUs= is no use here: the user manager has no cpuset controller, so it
is ignored without a word (checked 2026-10-21).

    python3 ~/Forge/shared/forge_cores.py list
    python3 ~/Forge/shared/forge_cores.py move "battle bot" --to e-cores:3 --for 8h
    python3 ~/Forge/shared/forge_cores.py move 12345 --to p-cores --until 19:40
    python3 ~/Forge/shared/forge_cores.py preset "battle bot" --to e-cores:3
    python3 ~/Forge/shared/forge_cores.py run --to e-cores:4 -- CMD...
    python3 ~/Forge/shared/forge_cores.py run --slot heavy-job -- CMD...

Stdlib only, so any venv (or plain python3) can import or run it. For the
plan, anything unreadable, unknown or empty means "no pin", never an error: a
broken plan must not stop a launch.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from collections.abc import Iterator

# FORGE_CORE_PLAN points at another plan file (for a check with the plan on)
PLAN = Path(
    os.environ.get("FORGE_CORE_PLAN") or Path(__file__).with_name("core_plan.json")
)
JOBS = Path(__file__).with_name("core_jobs.json")
STATE = Path(
    os.environ.get("FORGE_CORES_STATE") or Path.home() / ".local/state/forge/cores.json"
)
SYSFS = Path("/sys/devices")
PROC = Path("/proc")
NAMED = {"p-cores": "p", "e-cores": "e"}
SPEC_RE = re.compile(r"(p-cores|e-cores)(?::(\d+))?")
TICK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
MAX_CPUS = 8192  # the kernel's own NR_CPUS limit; a bigger list is a typo


def parse_cpus(text: str) -> set[int]:
    """A kernel CPU list such as "0,4-11" as a set; ValueError on anything else."""
    cpus: set[int] = set()
    for part in text.strip().split(","):
        part = part.strip()
        if not part:
            continue
        lo, dash, hi = part.partition("-")
        first, last = int(lo), int(hi) if dash else int(lo)
        if first < 0 or last < first or last >= MAX_CPUS:
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


# ------------------------------------------------------------------ hardware


def _cpu_list(path: Path) -> set[int] | None:
    try:
        return parse_cpus(path.read_text())
    except (OSError, ValueError):
        return None


def topology(sysfs: Path = SYSFS) -> dict[str, set[int]]:
    """{"p": performance CPUs, "e": efficiency CPUs, "all": online CPUs},
    read from the hardware. An Intel hybrid lists its cores in cpu_core and
    cpu_atom; an ARM big.LITTLE gives the little cores a lower cpu_capacity;
    a CPU with neither counts every core as a P-core and has no E-cores."""
    online = online_cpus(sysfs)
    p = _cpu_list(sysfs / "cpu_core/cpus")
    e = _cpu_list(sysfs / "cpu_atom/cpus")
    if p is None and e is None:
        caps: dict[int, int] = {}
        for cpu in online:
            try:
                path = sysfs / f"system/cpu/cpu{cpu}/cpu_capacity"
                caps[cpu] = int(path.read_text())
            except (OSError, ValueError):
                break
        if len(caps) == len(online) and len(set(caps.values())) > 1:
            top = max(caps.values())
            p = {c for c, cap in caps.items() if cap == top}
            e = online - p
    if p is None:
        p = online - (e or set())
    return {"p": p & online, "e": (e or set()) & online, "all": online}


def core_groups(cpus: set[int], sysfs: Path = SYSFS) -> list[list[int]]:
    """The CPUs as whole cores (hyperthread siblings together), lowest first."""
    groups: list[list[int]] = []
    seen: set[int] = set()
    for cpu in sorted(cpus):
        if cpu in seen:
            continue
        path = sysfs / f"system/cpu/cpu{cpu}/topology/thread_siblings_list"
        siblings = (_cpu_list(path) or {cpu}) & cpus | {cpu}
        seen |= siblings
        groups.append(sorted(siblings))
    return groups


def resolve(spec: str, sysfs: Path = SYSFS) -> set[int]:
    """A spec (see the module docstring) as online CPU numbers. ValueError
    when it names nothing on this machine (e-cores on a CPU without them, more
    cores than there are, CPUs that are all offline)."""
    spec = spec.strip().lower()
    topo = topology(sysfs)
    if spec == "all":
        return topo["all"]
    named = SPEC_RE.fullmatch(spec)
    if named:
        kind, count = named.groups()
        cpus = topo[NAMED[kind]]
        label = "P-cores" if kind == "p-cores" else "E-cores"
        if not cpus:
            raise ValueError(f"this CPU has no {label}")
        if count is None:
            return cpus
        groups = core_groups(cpus, sysfs)
        n = int(count)
        if not 1 <= n <= len(groups):
            raise ValueError(f"asked for {n} {label}, this CPU has {len(groups)}")
        return {cpu for group in groups[-n:] for cpu in group}
    if not is_spec(spec):
        raise ValueError(
            f"{spec!r} is not a core choice: use all, p-cores, e-cores,"
            " p-cores:N, e-cores:N or CPUs such as 4-7"
        )
    cpus = parse_cpus(spec) & topo["all"]
    if not cpus:
        raise ValueError(f"no online CPU in {spec!r}")
    return cpus


def is_spec(text: str) -> bool:
    """True when text has the shape of a spec (not whether this CPU has it)."""
    text = text.strip().lower()
    return (
        text == "all"
        or bool(SPEC_RE.fullmatch(text))
        or bool(re.fullmatch(r"\d+(-\d+)?(,\d+(-\d+)?)*", text))
    )


def describe(cpus: set[int], sysfs: Path = SYSFS) -> str:
    """Words for a set of CPUs: "all cores", "E-cores", "3 E-cores (9-11)"."""
    topo = topology(sysfs)
    if cpus >= topo["all"]:
        return "all cores"
    hybrid = bool(topo["e"])
    if hybrid and cpus == topo["p"]:
        return f"P-cores ({format_cpus(cpus)})"
    if hybrid and cpus == topo["e"]:
        return f"E-cores ({format_cpus(cpus)})"
    parts = []
    for kind, label in (("p", "P"), ("e", "E")):
        n = len(core_groups(cpus & topo[kind], sysfs)) if cpus & topo[kind] else 0
        if n:
            parts.append(f"{n} {label}-core{'s' if n > 1 else ''}")
    if not hybrid:
        n = len(core_groups(cpus, sysfs))
        parts = [f"{n} core{'s' if n > 1 else ''}"]
    return f"{' + '.join(parts) or 'no cores'} ({format_cpus(cpus)})"


def hardware(sysfs: Path = SYSFS) -> dict:
    """The CPU's layout for people and pages."""
    topo = topology(sysfs)
    return {
        "hybrid": bool(topo["e"]),
        "all": format_cpus(topo["all"]),
        "p": format_cpus(topo["p"]),
        "e": format_cpus(topo["e"]),
        "p_cores": len(core_groups(topo["p"], sysfs)),
        "e_cores": len(core_groups(topo["e"], sysfs)),
    }


# ------------------------------------------------------------------ the plan


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


# ------------------------------------------------------------------ processes


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def read_procs(proc: Path = PROC, uid: int | None = None) -> dict[int, dict]:
    """This user's processes: pid -> {pid, ppid, comm, args, cwd, cgroup,
    start, ticks, rss_mb, cpus}. Only our own, since moving anyone else's
    needs root. The keys comm/args/cwd/cgroup are the guard's rule language."""
    uid = os.getuid() if uid is None else uid
    out: dict[int, dict] = {}
    for entry in proc.iterdir() if proc.is_dir() else []:
        if not entry.name.isdigit():
            continue
        status = _read(entry / "status")
        stat = _read(entry / "stat")
        uids = re.search(r"^Uid:\s+(\d+)", status, re.M)
        if not stat or not uids or int(uids.group(1)) != uid:
            continue
        head, _, tail = stat.rpartition(")")
        cols = tail.split()
        if len(cols) < 22:
            continue
        cpus = re.search(r"^Cpus_allowed_list:\s+(\S+)", status, re.M)
        rss = re.search(r"^VmRSS:\s+(\d+)", status, re.M)
        try:
            cwd = os.readlink(entry / "cwd")
        except OSError:
            cwd = ""
        pid = int(entry.name)
        out[pid] = {
            "pid": pid,
            "ppid": int(cols[1]),
            "comm": head.partition("(")[2],
            "args": _read(entry / "cmdline").replace("\0", " ").strip(),
            "cwd": cwd,
            "cgroup": _read(entry / "cgroup").strip(),
            "start": int(cols[19]),
            "ticks": int(cols[11]) + int(cols[12]),
            "rss_mb": int(rss.group(1)) // 1024 if rss else 0,
            "cpus": format_cpus(parse_cpus(cpus.group(1))) if cpus else "",
        }
    return out


def key(p: dict) -> str:
    """pid:start, which a reused pid never repeats."""
    return f"{p['pid']}:{p['start']}"


def descendants(pid: int, procs: dict[int, dict]) -> list[int]:
    """pid and every process under it, parents before children."""
    children: dict[int, list[int]] = {}
    for p in procs.values():
        children.setdefault(p["ppid"], []).append(p["pid"])
    out, todo = [], [pid]
    while todo:
        cur = todo.pop(0)
        if cur in procs and cur not in out:
            out.append(cur)
            todo.extend(children.get(cur, []))
    return out


def ancestors(pid: int, procs: dict[int, dict]) -> Iterator[int]:
    """pid itself, then its parent, grandparent and so on."""
    seen: set[int] = set()
    while pid in procs and pid not in seen:
        seen.add(pid)
        yield pid
        pid = procs[pid]["ppid"]


def set_cpus(pid: int, cpus: set[int], proc: Path = PROC) -> None:
    """Every thread of pid onto cpus (a pid alone is only its main thread).
    The thread list is read again until it has nothing new, since a thread
    started by one not yet moved keeps the old cores. Raises OSError when no
    thread of the process could be moved (a zombie main thread alone is no
    reason to leave its live threads where they are)."""
    done: set[int] = set()
    moved = False
    error: OSError | None = None
    for _ in range(3):
        try:
            tids = {int(t) for t in os.listdir(proc / str(pid) / "task")}
        except OSError:
            tids = {pid}
        if not tids - done:
            break
        for tid in sorted(tids - done, key=lambda t: t != pid):
            try:
                os.sched_setaffinity(tid, cpus)
                moved = True
            except OSError as exc:
                error = error or exc
        done |= tids
    if not moved:
        raise error or ProcessLookupError(f"no thread of {pid} is left")


# ------------------------------------------------------------------ jobs


def load_jobs(path: Path | None = None) -> list[dict]:
    """shared/core_jobs.json's job rules; a broken file means no named jobs."""
    try:
        jobs = json.loads((path or JOBS).read_text(encoding="utf-8")).get("jobs", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [
        j
        for j in jobs
        if isinstance(j, dict)
        and isinstance(j.get("name"), str)
        and isinstance(j.get("match"), list)
    ]


def _rule_name(job: dict, p: dict) -> str | None:
    """The job's name for p when one of its rules holds, with {1}, {2} filled
    from the rule's regex groups; None when no rule holds. Same keys and
    meaning as the guard's rules (forge_autoclose.rule_hits)."""
    for rule in job["match"]:
        if not isinstance(rule, dict) or not rule:
            continue
        groups: list[str] = []
        fields = [f for f in rule if not f.startswith("_")]
        for field in fields or ["?"]:
            want = rule.get(field, "")
            if field not in ("comm", "args", "cwd", "cgroup"):
                break
            text = p.get(field, "")
            found = (
                re.fullmatch(want, text) if field == "comm" else re.search(want, text)
            )
            if not found:
                break
            groups += [g or "" for g in found.groups()]
        else:
            try:
                return job["name"].format("", *groups)
            except (IndexError, KeyError, ValueError):
                return job["name"]
    return None


def job_names(procs: dict[int, dict], jobs: list[dict] | None = None) -> dict:
    """pid -> job name. A process a job rule names belongs to that job (the
    first rule in the file wins); any other process belongs to the job of its
    nearest named ancestor, and failing that is a job of its own command
    name. So the battle bot's scripts under a Relay session are "battle bot",
    and the session's other tools are "Relay task N"."""
    jobs = load_jobs() if jobs is None else jobs
    direct: dict[int, str] = {}
    for pid, p in procs.items():
        for job in jobs:
            name = _rule_name(job, p)
            if name:
                direct[pid] = name
                break
    out: dict[int, str] = {}
    for pid, p in procs.items():
        out[pid] = next(
            (direct[a] for a in ancestors(pid, procs) if a in direct), p["comm"]
        )
    return out


def same(name: str) -> str:
    """A job or preset name as compared: case, spaces and symbols do not
    count, so "Battle Bot" is "battle-bot" (forge_ram.py turns a --name
    with spaces into a scope name with dashes). A name of symbols alone
    stays itself rather than matching every other such name."""
    return re.sub(r"\W+", "-", name.lower()).strip("-") or name.strip().lower()


def preset_for(state: dict, name: str, now: float | None = None) -> dict | None:
    """The live (not expired) preset saved for job `name`, or None."""
    now = time.time() if now is None else now
    for n, p in state["presets"].items():
        if same(n) == same(name) and (p.get("until") is None or p["until"] > now):
            return p
    return None


def named_jobs(procs: dict[int, dict], names: dict) -> set[str]:
    """Job names that come from a job rule rather than a bare command name."""
    return {names[pid] for pid in procs if names[pid] != procs[pid]["comm"]}


# ------------------------------------------------------------------ state


def _empty() -> dict:
    return {"presets": {}, "moves": {}, "applied": {}}


_TIME = (int, float, type(None))
_SHAPES = {  # each entry's needed fields and their types; others are dropped
    "presets": {"spec": str, "until": _TIME},
    "moves": {"pid": int, "cpus": str, "before": str, "until": _TIME},
    "applied": {"preset": str, "before": str, "cpus": str},
}


def _fits(entry, fields: dict) -> bool:
    return isinstance(entry, dict) and all(
        isinstance(entry.get(f), t) and not isinstance(entry.get(f), bool)
        for f, t in fields.items()
    )


def load_state(path: Path | None = None) -> dict:
    """The moves and presets; a broken file or entry is left out, never an
    error, so one bad line cannot stop timed moves going back."""
    try:
        data = json.loads((path or STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    state = _empty()
    for part, fields in _SHAPES.items():
        if isinstance(data.get(part), dict):
            state[part] = {k: v for k, v in data[part].items() if _fits(v, fields)}
    for m in state["moves"].values():
        tree = m.get("tree")
        if not (isinstance(tree, list) and all(isinstance(t, str) for t in tree)):
            m.pop("tree", None)
    return state


@contextlib.contextmanager
def editing(path: Path | None = None) -> Iterator[dict]:
    """The state under an exclusive lock, written back (atomically) after."""
    import fcntl

    path = path or STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load_state(path)
        before = json.dumps(state, sort_keys=True)
        yield state
        if json.dumps(state, sort_keys=True) != before:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
            os.replace(tmp, path)


def check_spec(spec: str, sysfs: Path = SYSFS) -> str:
    """spec tidied, or ValueError saying why it names no cores here."""
    spec = spec.strip().lower()
    resolve(spec, sysfs)
    return spec


def _go_back(
    pid: int,
    procs: dict,
    was: set[int],
    before: str,
    sysfs: Path,
    errors: list,
    skip: set[int] = frozenset(),  # type: ignore[assignment]
) -> None:
    """Put pid (and its children still on the cores we gave them) back on
    `before`. A process someone has moved since is left where it is, and so
    is one in `skip` (a preset's, which the tick puts back on its own)."""
    try:
        target = resolve(before, sysfs) if before else topology(sysfs)["all"]
    except ValueError:
        target = topology(sysfs)["all"]
    for child in descendants(pid, procs):
        cur = procs[child]["cpus"]
        if child in skip or (cur and parse_cpus(cur) != was):
            continue
        try:
            set_cpus(child, target)
        except OSError as exc:
            errors.append(f"{procs[child]['comm']} ({child}): {exc}")


def move(
    target: int,
    spec: str,
    until: float | None = None,
    children: bool = True,
    procs: dict | None = None,
    state: dict | None = None,
    sysfs: Path = SYSFS,
    only: set[int] | None = None,
    job: str | None = None,
) -> dict:
    """Move one process (all its threads, and its children unless told not
    to; with `only`, just the children in it) onto spec's cores. With
    `until`, tick() puts them back on the cores they had once that time has
    passed, even if the top process has ended by then. A move also keeps a
    preset off that process tree for as long as it lasts."""
    procs = read_procs() if procs is None else procs
    if target not in procs:
        raise LookupError(f"no process {target} of yours is running")
    cpus = resolve(spec, sysfs)
    tree = descendants(target, procs) if children else [target]
    if only is not None:  # through `only` alone, not past another job
        kept = {target}
        for pid in tree[1:]:
            if pid in only and procs[pid]["ppid"] in kept:
                kept.add(pid)
        tree = [pid for pid in tree if pid in kept]
    before = procs[target]["cpus"]
    errors: list[str] = []
    done: list[int] = []
    for pid in tree:
        try:
            set_cpus(pid, cpus)
            done.append(pid)
        except OSError as exc:
            errors.append(f"{procs[pid]['comm']} ({pid}): {exc}")
    moved = len(done)
    if not moved:
        raise PermissionError("; ".join(errors) or "nothing could be moved")
    root = procs[target]
    record = {
        "pid": target,
        "start": root["start"],
        "comm": root["comm"],
        "spec": spec.strip().lower(),
        "cpus": format_cpus(cpus),
        "before": before,
        "until": until,
        "set": time.time(),
        "tree": [key(procs[pid]) for pid in done],
    }
    if job is not None:  # later children count only if they are this job's
        record["job"] = job
    if state is not None:
        old = state["moves"].get(key(root))
        if old:  # moving again: going back still means the cores it had first
            record["before"] = old.get("before", record["before"])
        for pid in tree[1:]:
            state["moves"].pop(key(procs[pid]), None)
        state["moves"][key(root)] = record
    out = {k: v for k, v in record.items() if k != "tree"}
    return {"moved": moved, "processes": len(tree), "errors": errors, **out}


def move_job(
    name: str,
    spec: str,
    until: float | None = None,
    procs: dict | None = None,
    state: dict | None = None,
    sysfs: Path = SYSFS,
    jobs: list[dict] | None = None,
    root: int | None = None,
) -> dict:
    """Move every process of a job: each top process with those of its
    children that belong to the job (a Relay session started by a python
    script is its own job, not part of "python"). With root, only that one
    process of the job and the job's processes under it."""
    procs = read_procs() if procs is None else procs
    names = job_names(procs, jobs)
    want = same(name)
    members = {pid for pid, job in names.items() if same(job) == want}
    if not members:
        raise LookupError(f"no process of the job {name!r} is running")
    roots = [pid for pid in members if procs[pid]["ppid"] not in members]
    if root is not None:
        if root not in members:
            raise LookupError(f"process {root} is not part of the job {name!r}")
        roots = [root]
    out = {"moved": 0, "processes": 0, "errors": [], "roots": roots}
    for pid in sorted(roots):
        try:
            got = move(pid, spec, until, True, procs, state, sysfs, members, name)
        except (PermissionError, LookupError) as exc:
            out["errors"].append(str(exc))
            continue
        out["moved"] += got["moved"]
        out["processes"] += got["processes"]
        out["errors"] += got["errors"]
        out["cpus"] = got["cpus"]
    if not out["moved"]:
        raise PermissionError("; ".join(out["errors"]) or "nothing could be moved")
    return out


def set_preset(
    state: dict,
    name: str,
    spec: str,
    until: float | None = None,
    procs: dict | None = None,
    jobs: list[dict] | None = None,
) -> dict:
    """Save a job's cores; tick() then pins its running and new processes.
    Given the process table, the preset also takes over earlier moves of that
    job's processes (they would otherwise keep it off them); going back then
    still means the cores they had before the move."""
    name = name.strip()
    if not name:
        raise ValueError("a preset needs a job name")
    if until is not None and until <= time.time():
        raise ValueError("that time has already passed")
    entry = {"spec": check_spec(spec), "until": until, "set": time.time()}
    for other in [n for n in state["presets"] if same(n) == same(name)]:
        state["presets"].pop(other)
        for a in state["applied"].values():
            if a["preset"] == other:
                a["preset"] = name
    state["presets"][name] = entry
    # processes it pinned before follow the new cores on the next tick
    for a in state["applied"].values():
        if a["preset"] == name:
            a["stale"] = True
    if procs is not None:
        names = job_names(procs, jobs)
        for k, m in list(state["moves"].items()):
            pid = m.get("pid")
            if pid in procs and key(procs[pid]) == k:
                if same(names[pid]) == same(name):
                    state["moves"].pop(k)
                    state["applied"][k] = {
                        "preset": name,
                        "before": m.get("before", ""),
                        "cpus": m.get("cpus", ""),
                        "stale": True,
                    }
    return entry


def remove_preset(
    state: dict, name: str, procs: dict | None = None, sysfs: Path = SYSFS
) -> list[str]:
    """Drop a preset and put the processes it pinned back on their cores."""
    found = [n for n in state["presets"] if same(n) == same(name)]
    if not found:
        raise LookupError(f"no preset called {name!r}")
    procs = read_procs() if procs is None else procs
    errors: list[str] = []
    for preset in found:
        _release(state, preset, procs, sysfs, errors)
        state["presets"].pop(preset)
    return errors


def _release(state: dict, preset: str, procs: dict, sysfs: Path, errors: list):
    alive = {key(p): pid for pid, p in procs.items()}
    for k, entry in list(state["applied"].items()):
        if entry["preset"] != preset:
            continue
        state["applied"].pop(k)
        if k in alive:
            was = parse_cpus(entry.get("cpus") or "") or set()
            _go_back(alive[k], procs, was, entry.get("before", ""), sysfs, errors)


def tick(
    now: float | None = None,
    procs: dict | None = None,
    path: Path | None = None,
    sysfs: Path = SYSFS,
    jobs: list[dict] | None = None,
) -> set[int]:
    """One pass: put expired moves and presets back, pin new processes of a
    preset's job. Returns the pids it holds (moved trees and preset pins), so
    the priority watcher's saver squeeze leaves their cores alone."""
    now = time.time() if now is None else now
    path = path or STATE
    if not path.exists():
        return set()
    with editing(path) as state:
        if not (state["presets"] or state["moves"] or state["applied"]):
            return set()
        procs = read_procs() if procs is None else procs
        return _tick(state, now, procs, sysfs, jobs)


def _held(entry: dict, k: str, alive: dict, procs: dict, names: dict) -> set[int]:
    """The live processes a move holds: those it moved, and processes under
    them still on its cores (of its job, for a job move)."""
    tops = [alive[m] for m in entry.get("tree") or [k] if m in alive]
    was = parse_cpus(entry.get("cpus") or "") or set()
    job = entry.get("job")
    out = set(tops)
    for top in tops:
        for pid in descendants(top, procs)[1:]:
            cur = procs[pid]["cpus"]
            if cur and parse_cpus(cur) != was:
                continue
            if isinstance(job, str) and same(names.get(pid, "")) != same(job):
                continue
            out.add(pid)
    return out


def _tick(state: dict, now: float, procs: dict, sysfs: Path, jobs) -> set[int]:
    alive = {key(p): pid for pid, p in procs.items()}
    errors: list[str] = []
    names = job_names(procs, jobs) if state["moves"] or state["presets"] else {}
    for k, entry in list(state["moves"].items()):
        # a timed move outlives its top process while any process it holds
        # runs on, so a wrapper script that exits early strands nothing; the
        # tree is brought up to date every tick to include new children
        ours = _held(entry, k, alive, procs, names)
        if not ours or (k not in alive and entry.get("until") is None):
            state["moves"].pop(k)
        elif entry.get("until") is None or entry["until"] > now:
            entry["tree"] = sorted({key(procs[pid]) for pid in ours})
        else:
            state["moves"].pop(k)
            was = parse_cpus(entry.get("cpus") or "") or set()
            tops = [pid for pid in ours if procs[pid]["ppid"] not in ours]
            presets = {pid for pid in ours if key(procs[pid]) in state["applied"]}
            for pid in presets:  # back onto the preset's cores, below
                state["applied"][key(procs[pid])]["stale"] = True
            skip = presets | (set(procs) - ours)
            for top in tops:
                _go_back(top, procs, was, entry.get("before", ""), sysfs, errors, skip)
    for name, preset in list(state["presets"].items()):
        if preset.get("until") is not None and preset["until"] <= now:
            _release(state, name, procs, sysfs, errors)
            state["presets"].pop(name)
    for k in [k for k in state["applied"] if k not in alive]:
        state["applied"].pop(k)
    held: set[int] = set()
    for k, m in state["moves"].items():
        held |= _held(m, k, alive, procs, names)
    if not state["presets"]:
        return held
    wanted: dict[str, set[int]] = {}
    for name, preset in state["presets"].items():
        try:
            wanted[same(name)] = resolve(preset["spec"], sysfs)
        except ValueError:
            continue
    titles = {same(n): n for n in state["presets"]}
    for pid in sorted(procs, key=lambda p: procs[p]["start"]):
        job = same(names[pid])
        if job not in wanted or pid in held:
            continue
        p = procs[pid]
        cpus = wanted[job]
        entry = state["applied"].get(key(p))
        if entry and not entry.get("stale"):
            held.add(pid)
            continue
        current = parse_cpus(p["cpus"]) if p["cpus"] else set()
        before = entry["before"] if entry else _before(pid, procs, state, cpus)
        if current != cpus:
            try:
                set_cpus(pid, cpus)
            except OSError:
                continue
            p["cpus"] = format_cpus(cpus)
        state["applied"][key(p)] = {
            "preset": titles[job],
            "before": before,
            "cpus": format_cpus(cpus),
        }
        held.add(pid)
    return held


def _before(pid: int, procs: dict, state: dict, cpus: set[int]) -> str:
    """What a newly pinned process goes back to: what it had, unless it only
    had the preset's cores from its parent, then what that parent had."""
    for a in list(ancestors(pid, procs))[1:]:
        entry = state["applied"].get(key(procs[a]))
        if entry:
            return entry["before"]
    own = procs[pid]["cpus"]
    if own and parse_cpus(own) != cpus:
        return own
    return ""  # every online core


# ------------------------------------------------------------------ listing


def cpu_use(first: dict, second: dict, seconds: float) -> dict[int, float]:
    """pid -> percent of one CPU used between two read_procs() snapshots."""
    out = {}
    for pid, p in second.items():
        old = first.get(pid)
        if old and old["start"] == p["start"] and seconds > 0:
            out[pid] = max(0.0, (p["ticks"] - old["ticks"]) / TICK / seconds * 100)
    return out


def listing(
    procs: dict,
    use: dict[int, float],
    state: dict,
    sysfs: Path = SYSFS,
    jobs: list[dict] | None = None,
    min_cpu: float = 2.0,
    limit: int = 20,
) -> list[dict]:
    """One row per job worth showing: named jobs (battle bot, Relay tasks,
    forge_ram runs), any job with a preset or a move, and the busiest others
    (at least min_cpu percent), busiest first."""
    names = job_names(procs, jobs)
    named = named_jobs(procs, names)
    me = os.getpid()
    presets = {same(n): (n, p) for n, p in state["presets"].items()}
    moves_by_pid = {
        m["pid"]: m
        for k, m in state["moves"].items()
        if m["pid"] in procs and key(procs[m["pid"]]) == k
    }
    kids: dict[int, list[int]] = {}
    for p in procs.values():
        kids.setdefault(p["ppid"], []).append(p["pid"])
    rows: dict[str, dict] = {}
    for pid, p in procs.items():
        if pid == me:
            continue
        job = names[pid]
        row = rows.setdefault(
            same(job),
            {"job": job, "pids": [], "cpu": 0.0, "rss_mb": 0, "cpus": set()},
        )
        row["pids"].append(pid)
        row["cpu"] += use.get(pid, 0.0)
        row["rss_mb"] += p["rss_mb"]
        row["cpus"].add(p["cpus"])
    out = []
    for low, row in rows.items():
        moves = [moves_by_pid[pid] for pid in row["pids"] if pid in moves_by_pid]
        preset = presets.get(low)
        if not (row["job"] in named or preset or moves or row["cpu"] >= min_cpu):
            continue
        sets = sorted(row["cpus"] - {""})
        main = max(
            sets,
            key=lambda c: sum(procs[p]["cpus"] == c for p in row["pids"]),
            default="",
        )
        cores = parse_cpus(main) if main else topology(sysfs)["all"]
        untils = [m["until"] for m in moves if m.get("until")]
        top = min(row["pids"], key=lambda pid: procs[pid]["start"])
        members = set(row["pids"])
        firsts = {pid for pid in members if procs[pid]["ppid"] not in members}
        tops = []
        for pid in sorted(firsts):
            tree, todo = [], [pid]  # the job's processes under it, up to the
            while todo:  # next top process of the same job
                cur = todo.pop()
                tree.append(cur)
                todo += [c for c in kids.get(cur, []) if c in members - firsts]
            p = procs[pid]
            tops.append(
                {
                    "pid": pid,
                    "comm": p["comm"],
                    "args": p["args"][:120],
                    "processes": len(tree),
                    "cpu": round(sum(use.get(c, 0.0) for c in tree), 1),
                    "cpus": p["cpus"],
                }
            )
        tops.sort(key=lambda t: (-t["cpu"], t["pid"]))
        out.append(
            {
                "job": row["job"],
                "kind": "job" if row["job"] in named else "process",
                "pid": top,
                "processes": len(row["pids"]),
                "cpu": round(row["cpu"], 1),
                "rss_mb": row["rss_mb"],
                "cpus": main,
                "cores": describe(cores, sysfs),
                "mixed": len(sets) > 1,
                "tops": tops[:12],
                "until": min(untils) if untils else None,
                "moved": bool(moves),
                "preset": (
                    {"name": preset[0], **preset[1]} if preset is not None else None
                ),
            }
        )
    out.sort(key=lambda r: (-r["cpu"], r["job"].lower()))
    keep = [r for r in out if r["kind"] == "job" or r["preset"] or r["moved"]]
    rest = [r for r in out if r not in keep][: max(0, limit - len(keep))]
    return sorted(keep + rest, key=lambda r: (-r["cpu"], r["job"].lower()))


def snapshot(seconds: float = 0.5, previous: tuple | None = None) -> dict:
    """Everything the Power page and `list` show. previous is (time, procs)
    from an earlier call; without one it samples for `seconds`."""
    if previous is None:
        first, t0 = read_procs(), time.monotonic()
        time.sleep(seconds)
    else:
        t0, first = previous
    procs, t1 = read_procs(), time.monotonic()
    state = load_state()
    return {
        "hardware": hardware(),
        "rows": listing(procs, cpu_use(first, procs, t1 - t0), state),
        "presets": [
            {"name": n, **p, "cores": _spec_words(p["spec"])}
            for n, p in state["presets"].items()
        ],
        "sample": (t1, procs),
    }


def _spec_words(spec: str) -> str:
    try:
        return describe(resolve(spec))
    except ValueError as exc:
        return str(exc)


# ------------------------------------------------------------------ CLI


def parse_for(text: str) -> float:
    """ "8h", "90m", "1h30m", "2d" or a plain number of hours, in seconds."""
    text = text.strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text) * 3600
    parts = re.findall(r"(\d+(?:\.\d+)?)\s*([dhms])", text)
    if not parts or "".join(n + u for n, u in parts) != text.replace(" ", ""):
        raise ValueError(f"cannot read the time {text!r}; try 8h, 90m or 1h30m")
    unit = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    seconds = sum(float(n) * unit[u] for n, u in parts)
    if seconds <= 0:
        raise ValueError("the time must be more than nothing")
    return seconds


def parse_until(text: str, now: dt.datetime | None = None) -> float:
    """ "19:40" as the next time the clock shows it (today, else tomorrow)."""
    now = dt.datetime.now() if now is None else now
    found = re.fullmatch(r"(\d{1,2}):(\d{2})", text.strip())
    if not found or int(found.group(1)) > 23 or int(found.group(2)) > 59:
        raise ValueError(f"cannot read the clock time {text!r}; try 19:40")
    at = now.replace(
        hour=int(found.group(1)), minute=int(found.group(2)), second=0, microsecond=0
    )
    if at <= now:
        at += dt.timedelta(days=1)
    return at.timestamp()


def _clock(ts: float | None) -> str:
    if not ts:
        return ""
    at = dt.datetime.fromtimestamp(ts)
    same_day = at.date() == dt.date.today()
    return at.strftime("%H:%M" if same_day else "%a %H:%M")


def _until(args) -> float | None:
    if args.until:
        return parse_until(args.until)
    if args.for_:
        return time.time() + parse_for(args.for_)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="this CPU's cores, the plan and each slot's cores")
    lst = sub.add_parser("list", help="busy processes and jobs, and their cores")
    lst.add_argument("--json", action="store_true")
    mv = sub.add_parser("move", help="move a process or a job to other cores")
    mv.add_argument("target", help="a pid or a job name from list")
    mv.add_argument("--to", required=True, help="all, p-cores, e-cores, e-cores:3…")
    mv.add_argument("--only", action="store_true", help="the process, not children")
    pre = sub.add_parser("preset", help="save (or --remove) a job's cores")
    pre.add_argument("job")
    pre.add_argument("--to", help="all, p-cores, e-cores, e-cores:3…")
    pre.add_argument("--remove", action="store_true")
    for p in (mv, pre):
        p.add_argument("--for", dest="for_", help="then go back: 8h, 90m, 1h30m")
        p.add_argument("--until", help="then go back at this clock time: 19:40")
    sub.add_parser("presets", help="the saved presets")
    sub.add_parser("tick", help="one pass of the watcher (Power runs it every 5 s)")
    run = sub.add_parser("run", help="run a command on a slot's or a spec's cores")
    run.add_argument("--slot")
    run.add_argument("--to", help="all, p-cores, e-cores, e-cores:3…")
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    try:
        return _command(args, parser)
    except (ValueError, LookupError, PermissionError) as exc:
        print(f"forge_cores: {exc}", file=sys.stderr)
        return 1


def _command(args, parser) -> int:
    if args.cmd == "show":
        hw = hardware()
        print(f"P-cores {hw['p']} ({hw['p_cores']} cores)", end="")
        print(f", E-cores {hw['e']} ({hw['e_cores']})" if hw["hybrid"] else "")
        plan = load_plan()
        print(f"core plan {'on' if plan.get('enabled') is True else 'off'} ({PLAN})")
        for name, entry in (plan.get("slots") or {}).items():
            spec = entry.get("cpus") if isinstance(entry, dict) else None
            try:
                cpus = format_cpus(resolve(spec)) if isinstance(spec, str) else "?"
            except (OSError, ValueError):
                cpus = "unreadable"
            print(f"  {name}: {spec} = CPUs {cpus}")
        return 0
    if args.cmd == "list":
        snap = snapshot()
        snap.pop("sample")
        if args.json:
            print(json.dumps(snap, indent=1))
            return 0
        for row in snap["rows"]:
            extra = f" until {_clock(row['until'])}" if row["until"] else ""
            if row["preset"]:
                extra += " (preset)"
            print(
                f"{row['cpu']:5.1f}%  {row['job']}  [{row['processes']}, pid "
                f"{row['pid']}]  on {row['cores']}{' mixed' if row['mixed'] else ''}"
                f"{extra}"
            )
        return 0
    if args.cmd == "move":
        until = _until(args)
        with editing() as state:
            if args.target.isdigit():
                got = move(int(args.target), args.to, until, not args.only, state=state)
            else:
                got = move_job(args.target, args.to, until, state=state)
        back = f", back at {_clock(until)}" if until else ""
        print(f"moved {got['moved']} processes to CPUs {got['cpus']}{back}")
        for err in got["errors"]:
            print(f"  not moved: {err}", file=sys.stderr)
        return 0
    if args.cmd == "preset":
        with editing() as state:
            if args.remove:
                errors = remove_preset(state, args.job)
                print(f"removed the preset {args.job!r}")
                for err in errors:
                    print(f"  not put back: {err}", file=sys.stderr)
                return 0
            if not args.to:
                parser.error("preset needs --to (or --remove)")
            entry = set_preset(state, args.job, args.to, _until(args), read_procs())
        tick()
        back = f" until {_clock(entry['until'])}" if entry["until"] else ""
        print(f"preset {args.job!r}: {_spec_words(entry['spec'])}{back}")
        return 0
    if args.cmd == "presets":
        for name, entry in load_state()["presets"].items():
            back = f" until {_clock(entry['until'])}" if entry.get("until") else ""
            print(f"{name}: {entry['spec']} = {_spec_words(entry['spec'])}{back}")
        return 0
    if args.cmd == "tick":
        tick()
        return 0
    cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not cmd or bool(args.slot) == bool(args.to):
        parser.error("run needs --slot or --to, and a command after --")
    if args.to:
        os.sched_setaffinity(0, resolve(args.to))
    else:
        pin_self(args.slot, load_plan())
    sys.stdout.flush()
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    sys.exit(main())
