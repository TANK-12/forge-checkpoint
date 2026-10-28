"""Pick for my machine: read the hardware and pick a visual level and a power
choice to suit it, for Forge and for Forge Desktop (Relay task 323,
2026-10-24).

The levels, the choices, the settings each one sets and the GPU and CPU
classes live in shared/machine_profiles.json; this module only reads the
machine and walks the rules written there:

    detect()                  -> what the machine is (CPU, GPU, RAM, battery,
                                 the CPU's power limits), None where unknown
    pick(machine)             -> {"visual", "power", "why": [plain lines]}
    changes(visual, power, targets)
                              -> {setting: value} for forge_theme.save()

Linux reads /proc and /sys (and lspci for the GPU's name when it is there);
Windows and macOS read what they can without extra packages (Forge Desktop
ships there). Nothing here changes a setting: the callers save, so the
Business lock and the backups stay theirs.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

PROFILES = Path(__file__).resolve().parent / "machine_profiles.json"
TARGETS = ("forge", "desktop")
# PCI vendor ids of graphics chips, for when lspci is missing
VENDORS = {"0x8086": "Intel", "0x1002": "AMD", "0x10de": "NVIDIA"}


def load_profiles(path: Path | None = None) -> dict:
    return json.loads((path or PROFILES).read_text(encoding="utf-8"))


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _run(cmd: list[str], timeout: float = 5) -> str:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout if out.returncode == 0 else ""


# --- parsers (pure, tested on captured text) ----------------------------------


def parse_cpuinfo(text: str) -> tuple[str | None, int | None]:
    """The CPU's name and how many threads /proc/cpuinfo lists."""
    names = re.findall(r"^model name\s*:\s*(.+)$", text, re.M)
    threads = len(re.findall(r"^processor\s*:", text, re.M))
    return (names[0].strip() if names else None), (threads or None)


def parse_meminfo(text: str) -> float | None:
    """Total memory in GiB, one decimal."""
    m = re.search(r"^MemTotal:\s*(\d+)\s*kB", text, re.M)
    return round(int(m.group(1)) / 1024**2, 1) if m else None


def parse_lspci(text: str) -> list[str]:
    """Graphics chips from `lspci -mm`: "vendor device" per chip."""
    out = []
    for line in text.splitlines():
        parts = re.findall(r'"([^"]*)"', line)
        if len(parts) >= 3 and re.search(r"vga|3d|display", parts[0], re.I):
            out.append(f"{parts[1]} {parts[2]}".strip())
    return out


def parse_pmset(text: str) -> tuple[bool | None, bool | None]:
    """(has a battery, on battery now) from macOS `pmset -g batt`."""
    if not text:
        return None, None
    has = "InternalBattery" in text
    on = "'Battery Power'" in text if has else False
    return has, on


# --- readers per system -------------------------------------------------------


def _linux(root: Path, lspci) -> dict:
    cpu, threads = parse_cpuinfo(_read(root / "proc/cpuinfo"))
    ram = parse_meminfo(_read(root / "proc/meminfo"))
    gpus = parse_lspci(lspci() if lspci else "")
    if not gpus:
        for card in sorted((root / "sys/class/drm").glob("card[0-9]")):
            vendor = _read(card / "device/vendor")
            if vendor:
                gpus.append(f"{VENDORS.get(vendor, vendor)} graphics")
    has_battery, on_battery = None, None
    folder = root / "sys/class/power_supply"
    supplies = sorted(folder.glob("*"))
    if supplies:
        kinds = {s: _read(s / "type") for s in supplies}
        batteries = [
            s
            for s, k in kinds.items()
            if k == "Battery" and _read(s / "scope") != "Device"
        ]
        has_battery = bool(batteries)
        # a USB-C charger shows as type USB, not Mains
        mains = [_read(s / "online") for s, k in kinds.items() if k in ("Mains", "USB")]
        if not has_battery or "1" in mains:
            on_battery = False
        elif mains:
            on_battery = True
        else:  # no charger listed: ask the battery
            states = [_read(s / "status") for s in batteries]
            on_battery = "Discharging" in states if any(states) else None
    elif folder.is_dir():
        has_battery, on_battery = False, False  # a desktop: no supplies at all
    watts = {}
    rapl = root / "sys/class/powercap/intel-rapl:0"
    for name, file in (("sustained", "constraint_0"), ("burst", "constraint_1")):
        raw = _read(rapl / f"{file}_power_limit_uw")
        if raw.isdigit() and int(raw):
            watts[name] = round(int(raw) / 1e6)
    return {
        "cpu": cpu,
        "threads": threads or os.cpu_count(),
        "ram_gb": ram,
        "gpus": gpus,
        "has_battery": has_battery,
        "on_battery": on_battery,
        "watts": watts,
    }


def _windows() -> dict:  # pragma: no cover - read on Windows only
    import ctypes

    cpu = None
    try:
        import importlib

        winreg = importlib.import_module("winreg")  # Windows only
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        )
        cpu = str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except OSError:
        cpu = platform.processor() or None

    class Memory(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    class Power(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", ctypes.c_byte),
            ("BatteryFlag", ctypes.c_byte),
            ("BatteryLifePercent", ctypes.c_byte),
            ("SystemStatusFlag", ctypes.c_byte),
            ("BatteryLifeTime", ctypes.c_ulong),
            ("BatteryFullLifeTime", ctypes.c_ulong),
        ]

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    memory = Memory()
    memory.dwLength = ctypes.sizeof(Memory)
    ram = None
    if kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        ram = round(memory.ullTotalPhys / 1024**3, 1)
    has_battery = on_battery = None
    power = Power()
    if kernel32.GetSystemPowerStatus(ctypes.byref(power)):
        flag = power.BatteryFlag & 0xFF
        has_battery = None if flag == 255 else not flag & 128
        if has_battery is False:
            on_battery = False
        elif power.ACLineStatus in (0, 1):
            on_battery = power.ACLineStatus == 0
    names = _run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "(Get-CimInstance Win32_VideoController).Name",
        ]
    )
    return {
        "cpu": cpu,
        "threads": os.cpu_count(),
        "ram_gb": ram,
        "gpus": [n.strip() for n in names.splitlines() if n.strip()],
        "has_battery": has_battery,
        "on_battery": on_battery,
        "watts": {},
    }


def _macos() -> dict:  # pragma: no cover - read on macOS only
    cpu = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or None
    raw = _run(["sysctl", "-n", "hw.memsize"]).strip()
    has_battery, on_battery = parse_pmset(_run(["pmset", "-g", "batt"]))
    # Apple's chips carry the GPU; an Intel Mac names it in system_profiler
    gpus = [cpu] if cpu and cpu.startswith("Apple") else []
    if not gpus:
        found = re.findall(
            r"Chipset Model:\s*(.+)",
            _run(["system_profiler", "SPDisplaysDataType"], timeout=10),
        )
        gpus = [g.strip() for g in found]
    return {
        "cpu": cpu,
        "threads": os.cpu_count(),
        "ram_gb": round(int(raw) / 1024**3, 1) if raw.isdigit() else None,
        "gpus": gpus,
        "has_battery": has_battery,
        "on_battery": on_battery,
        "watts": {},
    }


def detect(root: Path = Path("/"), lspci=None) -> dict:
    """What this machine is. `root` and `lspci` (a function returning
    `lspci -mm` text) are for tests; unknown parts are None or empty."""
    if sys.platform.startswith("win"):
        return _windows()
    if sys.platform == "darwin":
        return _macos()
    if lspci is None:
        lspci = lambda: _run(["lspci", "-mm"])  # noqa: E731
    return _linux(root, lspci)


# --- the pick -----------------------------------------------------------------


def _match(classes: list[dict], text: str) -> dict | None:
    for c in classes:
        if re.search(c["match"], text, re.I):
            return c
    return None


def gpu_class(machine: dict, profiles: dict) -> dict | None:
    """The strongest class among the machine's GPUs (a laptop with a
    graphics card besides its built-in one counts as the card)."""
    order = [c["id"] for c in profiles["gpu_classes"]]
    found = [_match(profiles["gpu_classes"], g) for g in machine.get("gpus") or []]
    found = [c for c in found if c]
    if not found and machine.get("cpu"):
        # an AMD chip names its built-in GPU: "Ryzen 7 7840HS w/ Radeon 780M"
        found = [c for c in [_match(profiles["gpu_classes"], machine["cpu"])] if c]
    return min(found, key=lambda c: order.index(c["id"])) if found else None


def _step(ids: list[str], at: str, by: int) -> str:
    return ids[max(0, min(len(ids) - 1, ids.index(at) + by))]


def pick(machine: dict, profiles: dict | None = None) -> dict:
    """The visual level and power choice for `machine`, with the reasons."""
    profiles = profiles or load_profiles()
    rules = profiles["rules"]
    levels = [v["id"] for v in profiles["visual"]]
    powers = [p["id"] for p in profiles["power"]]
    why: list[str] = []

    gpu = gpu_class(machine, profiles)
    cpu = _match(profiles["cpu_classes"], machine.get("cpu") or "")
    if gpu:
        visual = gpu["visual"]
        why.append(
            f"Graphics: {gpu['label']}, so {_label(profiles, 'visual', visual)}."
        )
    else:
        visual = profiles["gpu_unknown_visual"]
        why.append(
            f"Graphics: not recognised, so {_label(profiles, 'visual', visual)}."
        )
    if gpu and gpu["id"] == "modern" and cpu and cpu["id"] == "high":
        visual = _step(levels, visual, 1)
        why.append(
            f"CPU: {cpu['label']} gives the built-in GPU more power: one level up."
        )
    ram, threads = machine.get("ram_gb"), machine.get("threads")
    if (ram is not None and ram < rules["min_ram_gb"]) or (
        threads is not None and threads < rules["min_threads"]
    ):
        visual = _step(levels, visual, -1)
        why.append("Little memory or few CPU threads: one level down.")

    if machine.get("has_battery") is False:
        power = powers[-1]
        why.append(f"No battery: {_label(profiles, 'power', power)} power use.")
    else:
        power = "balanced" if "balanced" in powers else powers[len(powers) // 2]
        what = "A laptop" if machine.get("has_battery") else "Battery not readable"
        why.append(f"{what}: {_label(profiles, 'power', power)} power use.")
        sustained = (machine.get("watts") or {}).get("sustained")
        if machine.get("on_battery"):
            power = _step(powers, power, -1)
            why.append("On battery now: one step lighter.")
        elif sustained is not None and sustained <= rules["low_watts"]:
            power = _step(powers, power, -1)
            why.append(f"The CPU is held to {sustained} W: one step lighter.")
        elif cpu and cpu["id"] == "low":
            why.append(
                f"CPU: {cpu['label']}; the charger's full rate is kept, battery use stays light."
            )
    return {"visual": visual, "power": power, "why": why}


def _label(profiles: dict, kind: str, ident: str) -> str:
    for entry in profiles[kind]:
        if entry["id"] == ident:
            return entry["label"]
    return ident


def changes(
    visual: str | None,
    power: str | None,
    targets: list[str] | tuple[str, ...] = TARGETS,
    profiles: dict | None = None,
) -> dict:
    """{setting: value} for a visual level and a power choice, for Forge,
    Forge Desktop or both. The power settings are shared by the two, so they
    come with either. ValueError on a name that is not in the registry."""
    profiles = profiles or load_profiles()
    out: dict = {}
    targets = [t for t in targets if t in TARGETS]
    if not targets:
        raise ValueError("pick Forge, Forge Desktop or both")
    if visual:
        level = next((v for v in profiles["visual"] if v["id"] == visual), None)
        if level is None:
            raise ValueError(f"no visual level called {visual!r}")
        for target in targets:
            out.update(level.get(target, {}))
    if power:
        choice = next((p for p in profiles["power"] if p["id"] == power), None)
        if choice is None:
            raise ValueError(f"no power choice called {power!r}")
        out.update(choice.get("both", {}))
    return out


def summary(profiles: dict | None = None) -> dict:
    """The levels and choices as the settings pages list them."""
    profiles = profiles or load_profiles()
    return {
        kind: [{k: e[k] for k in ("id", "label", "about")} for e in profiles[kind]]
        for kind in ("visual", "power")
    }
