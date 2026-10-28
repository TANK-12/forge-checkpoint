"""The compute budget: how much of this machine the experiments may take.

The constraint is specific and worth stating plainly, because it drives the
design rather than merely decorating it. The host is a 12th Gen i5-1245U: ten
physical cores, twelve logical -- two performance cores at 4.4 GHz (logical
CPUs 0-3) and eight efficiency cores at 3.3 GHz (logical CPUs 4-11) -- with an
Intel Iris Xe iGPU and 31 GiB of shared RAM and no swap.

Two things follow.

First, core count is not the only contended resource. Text generation runs on
the iGPU through Vulkan, while Piper, Kokoro and faster-whisper all run on the
CPU through onnxruntime -- and the iGPU and the CPU share one memory bus. A
model generating tokens starves CPU-side speech work of bandwidth even when
cores sit idle. Pinning cores alone does not fix that; running one heavy job at
a time does. Hence `serialise_heavy_work`, on by default.

Second, these libraries grab every core they can find unless told otherwise, so
the thread counts have to be set explicitly at the point of use. Reserving the
performance cores for the game loop and confining background work to six of the
efficiency cores keeps the game at frame rate and the desktop responsive while
a bake runs.

Nothing here is speculative about the hardware: the topology is read from the
running machine, and the split degrades sensibly on anything else.
"""

import os
import threading

# Logical CPUs whose core is a performance core, on this topology. Detected at
# runtime rather than hardcoded, so this stays correct on other machines.
_PERFORMANCE_MAX_MHZ_MARGIN = 1.15


def _cpu_max_mhz(cpu):
    path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/cpuinfo_max_freq"
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return int(handle.read().strip()) / 1000.0
    except (OSError, ValueError):
        return 0.0


def topology():
    """Split logical CPUs into fast and slow groups.

    Where the kernel exposes per-CPU maximum frequency (Intel hybrid parts do),
    anything meaningfully below the fastest is treated as an efficiency core.
    On a uniform CPU everything lands in `fast` and the split is a no-op.
    """
    try:
        cpus = sorted(os.sched_getaffinity(0))
    except AttributeError:  # not Linux
        cpus = list(range(os.cpu_count() or 1))
    freqs = {cpu: _cpu_max_mhz(cpu) for cpu in cpus}
    peak = max(freqs.values()) if freqs else 0.0
    if peak <= 0:
        return {"all": cpus, "fast": cpus, "slow": []}
    fast = [c for c in cpus if freqs[c] * _PERFORMANCE_MAX_MHZ_MARGIN >= peak]
    slow = [c for c in cpus if c not in fast]
    return {"all": cpus, "fast": fast, "slow": slow}


def background_cpus(budget=6):
    """The logical CPUs background AI work is allowed to touch.

    Prefers efficiency cores, keeping the performance cores free for the game
    and the compositor. Falls back to leaving a couple of cores free on a
    uniform CPU, and never returns an empty set.
    """
    topo = topology()
    pool = topo["slow"] or topo["all"]
    if not topo["slow"]:
        # Uniform CPU: leave at least two logical CPUs for everything else.
        pool = topo["all"][: max(1, len(topo["all"]) - 2)]
    chosen = pool[: max(1, int(budget))]
    return chosen or topo["all"][:1]


def apply_to_current_thread(budget=6):
    """Confine the calling process to the background pool.

    Intended for a worker *process*; sched_setaffinity is per-process on Linux,
    so callers that must not restrict the whole app should use `taskset_prefix`
    for a subprocess instead.
    """
    cpus = background_cpus(budget)
    try:
        os.sched_setaffinity(0, set(cpus))
    except (AttributeError, OSError):
        return []
    return cpus


def taskset_prefix(budget=6):
    """Command prefix that pins a subprocess, e.g. a Piper or ffmpeg call."""
    cpus = background_cpus(budget)
    if not cpus:
        return []
    return ["taskset", "-c", ",".join(str(c) for c in cpus)]


def thread_env(budget=6):
    """Environment that stops onnxruntime, OpenMP and friends from helping
    themselves to every core. Merge into a subprocess env, or set before
    importing the library in-process."""
    count = str(max(1, len(background_cpus(budget))))
    return {
        "OMP_NUM_THREADS": count,
        "OPENBLAS_NUM_THREADS": count,
        "MKL_NUM_THREADS": count,
        "NUMEXPR_NUM_THREADS": count,
        "ORT_NUM_THREADS": count,
    }


class HeavyLane:
    """One heavy job at a time, across every kind of heavy job.

    Text generation, speech synthesis and transcription all queue here together
    rather than each keeping its own pool, because they contend for the same
    memory bandwidth and the same thermal headroom. `busy()` and `depth()` are
    what the UI reads to show why the game just got quieter.
    """

    def __init__(self, enabled=True):
        self._lock = threading.RLock()
        self._enabled = enabled
        self._depth = 0
        self._label = ""
        self._depth_lock = threading.Lock()

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)

    def busy(self):
        return bool(self._label)

    def label(self):
        return self._label

    def depth(self):
        return self._depth

    def run(self, label, fn, *args, **kwargs):
        with self._depth_lock:
            self._depth += 1
        try:
            if not self._enabled:
                self._label = label
                return fn(*args, **kwargs)
            with self._lock:
                self._label = label
                try:
                    return fn(*args, **kwargs)
                finally:
                    self._label = ""
        finally:
            with self._depth_lock:
                self._depth -= 1
            if not self._enabled:
                self._label = ""


LANE = HeavyLane()


def describe(budget=6):
    """A snapshot for the settings page, so the budget is visible rather than
    an invisible policy the player has to take on trust."""
    topo = topology()
    cpus = background_cpus(budget)
    return {
        "logical_cpus": len(topo["all"]),
        "performance_cpus": topo["fast"],
        "efficiency_cpus": topo["slow"],
        "background_cpus": cpus,
        "background_count": len(cpus),
        "serialised": LANE._enabled,
        "busy_with": LANE.label(),
        "queue_depth": LANE.depth(),
    }
