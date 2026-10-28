"""Is there room for one more heavy thing: RAM, CPU, GPU, disk and battery?

One registry, shared/ram_guard.json, holds every load number used on this
laptop: the Power app's guard (warn and stop levels, the process groups in
the order they are shut down, the battery steps) and the headroom rules here,
which the boss and any Claude session use before starting something
heavy. Stdlib only, so any venv (or plain python3) can import or run it.

    python3 ~/Forge/shared/forge_ram.py status [--json]
    python3 ~/Forge/shared/forge_ram.py check [--purpose heavy_job] [--need-mb N]
            [--gpu]
    python3 ~/Forge/shared/forge_ram.py run [--purpose heavy_job] [--need-mb N]
            [--gpu] [--wait SECONDS] [--mem-max 50%] [--swap-max 1G]
            [--name NAME] [--cores SLOT] -- CMD...

`check` exits 0 when there is room and 3 (with the reason) when there is
not. `run` waits for room (queues instead of piling on), then runs CMD in a
systemd --user scope with MemoryMax, so a runaway job is killed inside its
own box before the desktop runs out of memory. When the core plan
(shared/core_plan.json, forge_cores.py) is on, `run` also pins CMD to the
cores of its slot (--cores, default heavy-job); while it is off, nothing is
pinned.

Room means (each only when the purpose's rule in "headroom" sets it): RAM
and swap under their limits, enough MB available, min_free_gb on the home
disk, the 1-minute load per CPU and the CPU and disk pressure (PSI, the share
of time work waited) under their limits, and no battery step holding that
purpose. --gpu (or "gpu": true in the rule) also waits for the shared GPU
lock (gpu.lock, /run/user/1000/forge-igpu.lock: one GPU job at a time) and
holds it for the whole job.

Battery steps ("battery" in the registry) apply while the battery is
draining, plugged in or not, and stay on while it charges until it is
resume_margin points above the step's line. A step can cap the parallel
sessions (max_relay_sessions), give jobs started here a nice level and a
CPUQuota (heavy_nice, heavy_cpu_quota), hold purposes (hold) and pause
running process groups (pause_groups, done by the forge-ram-guard service).
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

REGISTRY = Path(__file__).with_name("ram_guard.json")
TIGHT_EXIT = 3


def load_registry(path: Path | str = REGISTRY) -> dict:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: the registry must be a JSON object")
    return data


def meminfo(path: Path | str = "/proc/meminfo") -> dict[str, int]:
    """Fields of /proc/meminfo in kB."""
    out: dict[str, int] = {}
    for line in Path(path).read_text().splitlines():
        name, _, rest = line.partition(":")
        words = rest.split()
        if words and words[0].isdigit():
            out[name.strip()] = int(words[0])
    return out


def usage(info: dict[str, int] | None = None) -> dict:
    """RAM and swap in use, as the desktop feels it.

    RAM in use is total minus MemAvailable (what the kernel could hand out
    without swapping), so page cache does not count but tmpfs files do.
    """
    info = meminfo() if info is None else info
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    return {
        "ram_percent": round(100 * (total - avail) / total, 1) if total else 0.0,
        "swap_percent": (
            round(100 * (swap_total - swap_free) / swap_total, 1) if swap_total else 0.0
        ),
        "total_mb": total // 1024,
        "available_mb": avail // 1024,
        "swap_free_mb": swap_free // 1024,
    }


def headroom(
    purpose: str,
    need_mb: int = 0,
    info: dict[str, int] | None = None,
    registry: dict | None = None,
) -> str:
    """Why `purpose` should not start now; "" when there is room.

    The limits come from registry["headroom"][purpose]; an unknown purpose
    falls back to "heavy_job". need_mb is what the job expects to use: it
    must fit in MemAvailable on top of the rule's min_available_mb.
    """
    registry = load_registry() if registry is None else registry
    rules = registry.get("headroom", {})
    rule = rules[purpose] if purpose in rules else rules.get("heavy_job") or {}
    now = usage(info)
    max_ram = rule.get("max_ram_percent")
    if max_ram is not None and now["ram_percent"] >= max_ram:
        return f"RAM is {now['ram_percent']:.0f}% used (limit {max_ram}%)"
    max_swap = rule.get("max_swap_percent")
    # a limit of 100 means full swap is fine (zram), so it never refuses
    if max_swap is not None and max_swap < 100 and now["swap_percent"] >= max_swap:
        return f"swap is {now['swap_percent']:.0f}% used (limit {max_swap}%)"
    want = need_mb + int(rule.get("min_available_mb", 0))
    if want and now["available_mb"] < want:
        return f"only {now['available_mb']} MB free, {want} MB wanted"
    return ""


# ------------------------------------------------------ CPU, disk, GPU, battery


def load_per_cpu(path: Path | str = "/proc/loadavg", cpus: int | None = None) -> float:
    """The 1-minute load average divided by the number of CPUs."""
    try:
        first = float(Path(path).read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0
    return round(first / (cpus or os.cpu_count() or 1), 2)


def pressure(kind: str, root: Path | str = "/proc/pressure") -> float | None:
    """PSI "some avg10" for cpu, io or memory: the % of the last 10 s in
    which at least one task waited for it. None without PSI."""
    try:
        text = (Path(root) / kind).read_text()
    except OSError:
        return None
    found = re.search(r"^some avg10=([0-9.]+)", text, re.M)
    return float(found.group(1)) if found else None


def disk_free_gb(path: str = "~") -> float | None:
    try:
        return round(shutil.disk_usage(os.path.expanduser(path)).free / 1e9, 1)
    except OSError:
        return None


def gpu_lock_path(registry: dict) -> Path:
    raw = (registry.get("gpu") or {}).get("lock") or "/run/user/{uid}/forge-igpu.lock"
    return Path(os.path.expanduser(raw.format(uid=os.getuid())))


def gpu_holder(
    lock: Path, locks: Path | str = "/proc/locks", proc: Path | str = "/proc"
) -> dict | None:
    """Who holds the shared GPU lock, read from /proc/locks without taking
    it: {"pid", "name"} (name is the command line, short), or None."""
    try:
        st = os.stat(lock)
        table = Path(locks).read_text()
    except OSError:
        return None
    for line in table.splitlines():
        words = line.split()
        if len(words) < 6 or words[1] != "FLOCK":
            continue  # a waiter's line reads "N: -> FLOCK ..."
        try:
            pid = int(words[4])
            major, minor, inode = words[5].split(":")
            dev = (int(major, 16), int(minor, 16))
        except ValueError:
            continue
        if int(inode) != st.st_ino or dev != (os.major(st.st_dev), os.minor(st.st_dev)):
            continue
        try:
            args = (Path(proc) / str(pid) / "cmdline").read_bytes()
            name = args.replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except OSError:
            name = ""
        return {"pid": pid, "name": name[:80] or f"pid {pid}"}
    return None


def gpu_wanted_dir(lock: Path) -> Path:
    """Where a job polling for the GPU lock leaves a file named by its pid,
    so a holder that can give the lock back (Forge Models unloads an idle
    model) knows someone waits. Blocked flock waiters show in /proc/locks."""
    return lock.with_name(lock.name + ".wanted")


def gpu_wanted(lock: Path, proc: Path | str = "/proc") -> int:
    """How many live processes are polling for the GPU lock."""
    try:
        names = [f.name for f in gpu_wanted_dir(lock).iterdir()]
    except OSError:
        return 0
    return sum(1 for n in names if n.isdigit() and Path(proc, n).exists())


def take_gpu(lock: Path) -> int | None:
    """The shared GPU lock, taken without waiting: an inheritable fd that
    holds it until the job (which inherits it through exec) ends, or None
    while someone else has it."""
    try:
        fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o666)
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    os.set_inheritable(fd, True)
    return fd


def battery(root: Path | str = "/sys/class/power_supply") -> dict | None:
    """The first battery: {"percent", "status", "draining", "plugged"}, or
    None without one. draining is true whenever the charge goes down, also
    while plugged in when the laptop uses more than the charger gives."""
    found: dict | None = None
    plugged = None
    for supply in sorted(Path(root).glob("*")):
        try:
            kind = (supply / "type").read_text().strip()
            if kind == "Battery" and found is None:
                status = (supply / "status").read_text().strip()
                found = {
                    "percent": int((supply / "capacity").read_text().strip()),
                    "status": status,
                    "draining": status == "Discharging",
                }
            elif kind == "Mains" and plugged is None:
                plugged = (supply / "online").read_text().strip() == "1"
        except (OSError, ValueError):
            continue
    if found is not None:
        found["plugged"] = plugged
    return found


def last_step(registry: dict) -> str:
    """The step the RAM guard last applied (its state file), "" for none."""
    path = (registry.get("battery") or {}).get("paused_file")
    try:
        data = json.loads(Path(os.path.expanduser(path)).read_text()) if path else {}
        return str(data.get("step") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def battery_step(
    registry: dict, batt: dict | None, previous: str | None = None
) -> dict:
    """The battery step that applies now (lowest line first), with a "why";
    {} when none does.

    A step comes on only while the battery drains below its below_percent.
    One that is already on (`previous`, or one stricter than it) stays on
    until the battery is resume_margin points above its line, draining or
    not, so plugging in never makes a step stricter and a render does not
    flap on and off around a line. `previous` defaults to the step in the
    RAM guard's state file. A battery that cannot be read for a moment
    keeps the step that is on (a lifted and re-applied shutdown step would
    stop everything and send its note twice, Relay task 274)."""
    cfg = registry.get("battery") or {}
    if cfg.get("enabled") is False:
        return {}
    steps = sorted(cfg.get("steps", []), key=lambda s: s.get("below_percent", 0))
    if not batt or batt.get("percent") is None:
        if previous is None:
            previous = last_step(registry)
        kept = [s for s in steps if previous and s.get("name") == previous]
        return (
            dict(kept[0], why=f"battery not readable, keeping {previous}")
            if kept
            else {}
        )
    pct = batt["percent"]
    draining = bool(batt.get("draining"))
    margin = cfg.get("resume_margin", 5)
    if previous is None:
        previous = last_step(registry)
    names = [s.get("name") for s in steps]
    held = names.index(previous) if previous in names else -1
    for rank, step in enumerate(steps):
        line = step.get("below_percent", 0)
        on = draining and pct < line
        kept = 0 <= held <= rank and pct < line + margin
        if on or kept:
            how = "draining" if draining else "charging back up"
            return dict(
                step,
                why=f"battery {pct}% and {how} ({step.get('name', 'a battery step')})",
            )
    return {}


def measure(registry: dict) -> dict:
    """Every cheap load reading (no GPU sample), for room() and status."""
    disk = (registry.get("disk") or {}).get("path", "~")
    lock = gpu_lock_path(registry)
    batt = battery(
        (registry.get("battery") or {}).get("power_supply", "/sys/class/power_supply")
    )
    return {
        "load_per_cpu": load_per_cpu(),
        "cpus": os.cpu_count() or 1,
        "cpu_pressure": pressure("cpu"),
        "io_pressure": pressure("io"),
        "disk_path": disk,
        "disk_free_gb": disk_free_gb(disk),
        "gpu_lock": str(lock),
        "gpu_holder": gpu_holder(lock),
        "battery": batt,
        "step": battery_step(registry, batt),
    }


def room(
    purpose: str,
    need_mb: int = 0,
    info: dict[str, int] | None = None,
    registry: dict | None = None,
    facts: dict | None = None,
    gpu: bool = False,
) -> str:
    """Why `purpose` should not start now, over every resource; "" when
    there is room. RAM first (headroom), then each limit the purpose's rule
    sets, then a battery step that holds it, then the GPU lock when gpu (or
    the rule's "gpu") asks for it. facts: a measure() reading (tests)."""
    registry = load_registry() if registry is None else registry
    why = headroom(purpose, need_mb, info, registry)
    if why:
        return why
    rules = registry.get("headroom", {})
    rule = rules[purpose] if purpose in rules else rules.get("heavy_job") or {}
    facts = measure(registry) if facts is None else facts
    free = facts.get("disk_free_gb")
    want = rule.get("min_free_gb")
    if want is not None and free is not None and free < want:
        return f"only {free:.1f} GB disk free, {want} GB wanted"
    most = rule.get("max_load_per_cpu")
    load = facts.get("load_per_cpu")
    if most is not None and load is not None and load > most:
        return f"CPU load is {load:.2f} per CPU (limit {most})"
    for kind in ("cpu", "io"):
        most = rule.get(f"max_{kind}_pressure")
        now = facts.get(f"{kind}_pressure")
        if most is not None and now is not None and now > most:
            what = "CPU" if kind == "cpu" else "disk"
            return f"{what} pressure is {now:.0f}% (limit {most}%)"
    step = facts.get("step") or {}
    if purpose in step.get("hold", []):
        return f"{step['why']}: {purpose} waits"
    if gpu or rule.get("gpu"):
        holder = facts.get("gpu_holder")
        if holder:
            return f"the GPU is taken by {holder['name']} (pid {holder['pid']})"
    return ""


def wait_for_turn(
    purpose: str,
    need_mb: int = 0,
    timeout: float = 0,
    poll: float = 10,
    say=print,
    gpu: bool = False,
) -> tuple[str, int | None]:
    """Wait up to `timeout` s for room() and, with gpu, the GPU lock.
    ("", fd or None) once there is room, else (why not, None)."""
    registry = load_registry()
    gpu = gpu or bool(
        (registry.get("headroom", {}).get(purpose) or {}).get("gpu", False)
    )
    deadline = time.monotonic() + timeout
    told = ""
    marker: Path | None = None
    try:
        while True:
            why = room(purpose, need_mb, registry=registry, gpu=gpu)
            fd = None
            if not why and gpu:
                fd = take_gpu(gpu_lock_path(registry))
                if fd is None:
                    why = "the GPU lock is taken"
                    if marker is None and timeout > 0:
                        marker = gpu_wanted_dir(gpu_lock_path(registry)) / str(
                            os.getpid()
                        )
                        try:
                            marker.parent.mkdir(parents=True, exist_ok=True)
                            marker.touch()
                        except OSError:
                            marker = None
            if not why:
                return "", fd
            if time.monotonic() >= deadline:
                return why, None
            if why != told:
                say(f"waiting for room: {why}")
                told = why
            time.sleep(min(poll, max(0.1, deadline - time.monotonic())))
            registry = load_registry()
    finally:
        if marker is not None:
            marker.unlink(missing_ok=True)


def scope_command(
    cmd: list[str],
    mem_max: str,
    swap_max: str,
    name: str = "",
    nice: int | None = None,
    cpu_quota: str = "",
) -> list[str]:
    """systemd-run line that runs cmd in a memory-capped user scope, with a
    nice level and a CPUQuota when a battery step (or the rule) sets them."""
    line = ["systemd-run", "--user", "--scope", "--quiet", "--collect"]
    # the forge-heavy- unit name is what puts the job in the guard's renders group
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", name or Path(cmd[0]).name)[:40]
    line.append(f"--unit=forge-heavy-{name or 'job'}-{os.getpid()}")
    if mem_max:
        line += ["-p", f"MemoryMax={mem_max}"]
    if swap_max:
        line += ["-p", f"MemorySwapMax={swap_max}"]
    if cpu_quota:
        line += ["-p", f"CPUQuota={cpu_quota}"]
    if nice is not None:
        line.append(f"--nice={int(nice)}")
    return line + ["--", *cmd]


def tmpfs_use(paths: list[str]) -> list[tuple[str, int]]:
    """(path, MB used) for each tmpfs path that exists; tmpfs files live in RAM."""
    out = []
    for path in paths:
        try:
            du = shutil.disk_usage(path)
        except OSError:
            continue
        out.append((path, du.used // (1024 * 1024)))
    return out


def pin_cores(slot: str) -> None:
    """Pin this process to a core plan slot; CMD inherits it through the exec.
    Imported here so that importing forge_ram changes nothing for its users."""
    shared = str(Path(__file__).resolve().parent)
    if shared not in sys.path:
        sys.path.append(shared)
    import forge_cores

    plan = forge_cores.load_plan()
    if plan.get("enabled") is True and slot not in (plan.get("slots") or {}):
        print(
            f"the core plan has no slot {slot!r}, so the job is not pinned",
            file=sys.stderr,
        )
    forge_cores.pin_self(slot, plan)


def describe(now: dict, facts: dict, gpu_share: list | None = None) -> list[str]:
    """Status lines for people: RAM, CPU, disk, GPU, battery, step."""
    lines = [
        f"RAM {now['ram_percent']}% used ({now['available_mb']} MB free of "
        f"{now['total_mb']}), swap {now['swap_percent']}% used"
    ]
    cpu = f"CPU load {facts['load_per_cpu']} per CPU ({facts['cpus']} CPUs)"
    if facts.get("cpu_pressure") is not None:
        cpu += f", tasks waited for CPU {facts['cpu_pressure']:.0f}% of the last 10 s"
    lines.append(cpu)
    disk = f"disk {facts['disk_free_gb']} GB free on {facts['disk_path']}"
    if facts.get("io_pressure") is not None:
        disk += f", waited on disk {facts['io_pressure']:.0f}% of the last 10 s"
    lines.append(disk)
    holder = facts.get("gpu_holder")
    gpu = (
        f"GPU lock taken by {holder['name']} (pid {holder['pid']})"
        if holder
        else "GPU lock free"
    )
    if gpu_share:
        busy = ", ".join(
            f"{g['name'] or g['comm']} {100 * g['share']:.0f}%" for g in gpu_share
        )
        gpu += f"; GPU busy: {busy}"
    lines.append(gpu)
    batt = facts.get("battery")
    if batt:
        plug = {True: ", plugged in", False: ", on battery"}.get(
            batt.get("plugged"), ""
        )
        lines.append(f"battery {batt['percent']}% ({batt['status'].lower()}{plug})")
    step = facts.get("step") or {}
    if step:
        parts = []
        if "max_relay_sessions" in step:
            parts.append(f"Relay runs at most {step['max_relay_sessions']} sessions")
        if step.get("hold"):
            parts.append(f"{', '.join(step['hold'])} wait")
        if step.get("pause_groups"):
            parts.append(f"{', '.join(step['pause_groups'])} paused")
        if step.get("heavy_cpu_quota"):
            parts.append(f"jobs capped at {step['heavy_cpu_quota']} CPU")
        lines.append(f"{step['why']}: {'; '.join(parts) or 'no limits set'}")
    else:
        lines.append("no battery step applies")
    return lines


def gpu_busy(seconds: float = 0.5) -> list[dict]:
    """The busiest GPU users over `seconds` (forge_gpuload), [] if unreadable."""
    shared = str(Path(__file__).resolve().parent)
    if shared not in sys.path:
        sys.path.append(shared)
    try:
        import forge_gpuload

        return [
            g
            for g in forge_gpuload.top_gpu(count=3, seconds=seconds)
            if g["share"] >= 0.01
        ]
    except Exception:  # a strange /proc never breaks a status line
        return []


def snapshot(registry: dict | None = None, gpu_seconds: float = 0.5) -> dict:
    """Everything status shows, as one dict (the Power app's guard card)."""
    registry = load_registry() if registry is None else registry
    facts = measure(registry)
    snap = {
        "ram": usage(),
        **facts,
        "gpu_busy": gpu_busy(gpu_seconds) if gpu_seconds > 0 else [],
    }
    snap["lines"] = describe(snap["ram"], snap, snap["gpu_busy"])
    return snap


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status", help="RAM, CPU, disk, GPU and battery")
    st.add_argument("--json", action="store_true")
    for name in ("check", "run"):
        p = sub.add_parser(name)
        p.add_argument("--purpose", default="heavy_job")
        p.add_argument("--need-mb", type=int, default=0)
        p.add_argument("--gpu", action="store_true", help="needs the shared GPU lock")
        if name == "run":
            p.add_argument("--wait", type=float, default=1800)
            p.add_argument("--mem-max", default=None)
            p.add_argument("--swap-max", default=None)
            p.add_argument("--name", default="")
            p.add_argument("--cores", default="heavy-job", help="core plan slot")
            p.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    registry = load_registry()

    if args.cmd == "status":
        snap = snapshot(registry)
        snap["lines"] += [
            f"{path} (in RAM) holds {mb} MB"
            for path, mb in tmpfs_use(registry.get("tmpfs_paths", []))
        ]
        if args.json:
            print(json.dumps(snap, indent=1))
        else:
            print("\n".join(snap["lines"]))
        return 0

    if args.cmd == "check":
        why = room(args.purpose, args.need_mb, registry=registry, gpu=args.gpu)
        print(why or "room to start")
        return TIGHT_EXIT if why else 0

    cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not cmd:
        parser.error("run needs a command after --")
    why, _gpu_fd = wait_for_turn(args.purpose, args.need_mb, args.wait, gpu=args.gpu)
    if why:
        print(f"not started, still no room after {args.wait:.0f} s: {why}")
        return TIGHT_EXIT
    registry = load_registry()
    rule = registry.get("headroom", {}).get(args.purpose, {})
    step = battery_step(registry, battery())
    mem_max = args.mem_max if args.mem_max is not None else rule.get("mem_max", "")
    swap_max = args.swap_max if args.swap_max is not None else rule.get("swap_max", "")
    nice = step.get("heavy_nice", rule.get("nice"))
    quota = step.get("heavy_cpu_quota") or rule.get("cpu_quota", "")
    if step:
        print(f"{step['why']}: nice {nice}, CPU quota {quota or 'none'}")
    line = scope_command(cmd, mem_max, swap_max, args.name, nice, quota)
    pin_cores(args.cores)
    sys.stdout.flush()
    # the GPU lock's fd is inheritable, so CMD holds it until it ends
    if _gpu_fd is not None:
        # scripts that take the lock themselves (render.sh, quickcheck,
        # core_bench) skip it, or they would wait on the lock held for them
        os.environ["FORGE_GPU_LOCK_HELD"] = "1"
    os.execvp(line[0], line)


if __name__ == "__main__":
    sys.exit(main())
