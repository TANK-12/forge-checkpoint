"""Forge core -- app discovery and backend processes, with no window toolkit.

forge_portable.py (the launcher for Windows, macOS and Linux) and the release
builder (release/build.py) share this module. It reads the same files as
forge.py -- apps/<name>/forge_app.json, groups/<id>.json, sections/<id>.json
-- and runs a backend the way forge.py does: `python -m uvicorn <module>` on
127.0.0.1:<port>, from the app's source folder, with FORGE_SHARED_DIR set
(through forge_serve.py's guard for a release: AppManager(guard=True)).
What differs is only what has to: where Python lives on each system, how a
process group is made and ended, and where logs go.

WHICH PYTHON RUNS AN APP
    The app's own .venv when it has one (a checkout used for development);
    otherwise the Python a release bundles in runtime/ beside this file;
    otherwise the Python running this module.

forge.py keeps its own copy of the discovery code for now: it is the GTK
window on the Linux desktop this grew up on and is restarted rarely, so it
moves over to this module in a change of its own (see release/README.md).
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Callable

ROOT = os.path.dirname(os.path.abspath(__file__))
WINDOWS = os.name == "nt"
MACOS = sys.platform == "darwin"


def platform_name() -> str:
    """'linux', 'windows' or 'macos': the names the release registry uses."""
    if WINDOWS:
        return "windows"
    if MACOS:
        return "macos"
    return "linux"


def port_open(port: int, timeout: float = 0.2) -> bool:
    """True once something accepts a TCP connection on the port. Uvicorn binds
    its socket only after the app's startup has run, so a connect is the same
    readiness signal as a GET of the index page."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def venv_python(venv: str) -> str:
    """Where a virtualenv keeps its interpreter on this system."""
    if WINDOWS:
        return os.path.join(venv, "Scripts", "python.exe")
    return os.path.join(venv, "bin", "python")


def runtime_python(root: str = ROOT) -> str | None:
    """The Python a release bundles in runtime/, or None in a checkout."""
    if WINDOWS:
        path = os.path.join(root, "runtime", "python.exe")
    else:
        path = os.path.join(root, "runtime", "bin", "python3")
    return path if os.path.isfile(path) else None


def read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def help_text(manifest: dict) -> dict:
    """What the F1 help sheet says about an app: the manifest's "help"
    (a line or a list of lines, and optional "keys": [[keys, what], ...]
    and "features": [name, ...]), else its manifest summary, plus the names
    of its features (the help's own list when it gives one)."""
    raw = manifest.get("help", "")
    keys = []
    own_features = None
    if isinstance(raw, dict):
        keys = [k for k in raw.get("keys", []) if isinstance(k, list) and len(k) == 2]
        if isinstance(raw.get("features"), list):
            own_features = [f for f in raw["features"] if isinstance(f, str) and f]
        raw = raw.get("about", "")
    lines = [raw] if isinstance(raw, str) else [x for x in raw if isinstance(x, str)]
    lines = [x for x in lines if x.strip()]
    inner = manifest.get("manifest")
    if not isinstance(inner, dict):
        inner = {}
    if not lines and isinstance(inner.get("summary"), str):
        lines = [inner["summary"]]
    features = (
        own_features
        if own_features is not None
        else [
            f.get("name", "")
            for f in inner.get("features", [])
            if isinstance(f, dict) and f.get("name")
        ]
    )[:12]
    return {"about": lines, "keys": keys, "features": features}


def own_keys(manifest: dict) -> list:
    """The manifest's "own_keys": plain keys such as "F1" that the app uses
    itself, so Forge's keys leave them to it while it is in front."""
    raw = manifest.get("own_keys", [])
    return [k for k in raw if isinstance(k, str)] if isinstance(raw, list) else []


def actions(manifest: dict) -> list:
    """The manifest's "actions": jobs the home screen's search offers by name
    ("Free up memory"), each opening the app at its own `hash`. Only well
    formed ones are kept: a label, an optional hash and search words."""
    raw = manifest.get("actions", [])
    out = []
    for a in raw if isinstance(raw, list) else []:
        if not isinstance(a, dict) or not isinstance(a.get("label"), str):
            continue
        label = a["label"].strip()
        if not label:
            continue
        hash_ = a.get("hash", "")
        words = a.get("words", "")
        out.append(
            {
                "label": label[:80],
                "hash": hash_.lstrip("#")[:400] if isinstance(hash_, str) else "",
                "words": words[:200] if isinstance(words, str) else "",
            }
        )
    return out[:12]


def frame(manifest: dict):
    """The manifest's "frame" (experience plan B4): the app sits under the
    hub's one app frame, the strip over its window with its name, its tabs,
    Simple/Advanced and a More menu. `true`, or {"tabs": [{"id", "label",
    "adv"}], "settings": "<tab id>", "mode": true}: a tab's id is the hash it
    opens, "adv" shows it in Advanced only, "settings" is the tab the menu's
    "<App> settings" opens, "mode" draws Simple/Advanced from the start (else
    it shows once the page says it has one). Anything else is None: the app
    keeps its own header."""
    raw = manifest.get("frame")
    if raw is True:
        return {"tabs": [], "settings": "", "mode": False}
    if not isinstance(raw, dict):
        return None
    tabs, given = [], raw.get("tabs")
    for t in given if isinstance(given, list) else []:
        if not isinstance(t, dict):
            continue
        id_, label = t.get("id"), t.get("label")
        if not isinstance(id_, str) or not isinstance(label, str):
            continue
        id_, label = id_.strip().lstrip("#")[:80], label.strip()[:40]
        if id_ and label and all(x["id"] != id_ for x in tabs):
            tabs.append({"id": id_, "label": label, "adv": t.get("adv") is True})
    settings = raw.get("settings", "")
    settings = settings.strip().lstrip("#")[:80] if isinstance(settings, str) else ""
    return {"tabs": tabs[:12], "settings": settings, "mode": raw.get("mode") is True}


def inside(manifest: dict):
    """The manifest's "inside": the app lives inside another app's page, so it
    has no tile, dock icon or search entry of its own and opening it opens
    that page instead. {"role": "settings", "hash": "wallpapers"} (Relay task
    423: the Wallpapers app folded into Settings > Wallpaper). Anything else
    is None."""
    raw = manifest.get("inside")
    if not isinstance(raw, dict) or not isinstance(raw.get("role"), str):
        return None
    role = raw["role"].strip()[:40]
    hash_ = raw.get("hash", "")
    hash_ = hash_.strip().lstrip("#")[:400] if isinstance(hash_, str) else ""
    return {"role": role, "hash": hash_} if role else None


SEED_TIMEOUT = 120.0  # seconds one starting-data script may take

_SEED_ITEM = re.compile(
    r"^(?:([a-z0-9][a-z0-9-]*):)?([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.py)$"
)


def seed_scripts(manifest: dict) -> list[tuple[str, str]]:
    """The manifest's "seed": scripts that write an app's starting data (its
    first art, content or worlds) into its data folders, as (owner, path).
    A plain path is the app's own ("tools/seed_art.py"); "<app>:<path>" is
    another app's script ("emberfield:tools/seed_art.py"), run only when that
    app is here too. Paths stay inside their app; anything else is dropped."""
    found: list[tuple[str, str]] = []
    for item in manifest.get("seed") or []:
        match = _SEED_ITEM.match(item) if isinstance(item, str) else None
        if match is None or ".." in match.group(2).split("/"):
            continue
        found.append((match.group(1) or "", match.group(2)))
    return found


class App:
    """One app: its manifest fields, and its backend process once started."""

    def __init__(self, manifest: dict, root: str, port_offset: int = 0):
        self.root = root
        self.name = manifest["name"]
        self.label = manifest.get("label", self.name)
        self.tagline = manifest.get("tagline", "")
        self.port = int(manifest["port"]) + port_offset
        self.module = manifest["module"]
        self.src_dir = manifest.get("src_dir", ".")
        self.order = manifest.get("order", 99)
        self.ready_timeout = manifest.get("ready_timeout", 180)
        self.start_at_launch = manifest.get("start_at_launch") is True
        self.accent = manifest.get("accent", "")
        self.icon = manifest.get("icon", "")
        self.role = manifest.get("role", "")
        self.fullscreen = manifest.get("fullscreen", "")
        self.group = manifest.get("group", "")
        # a developer's tool, hidden unless Settings shows developer apps
        self.dev = bool(manifest.get("dev", False))
        self.help = help_text(manifest)
        self.own_keys = own_keys(manifest)
        self.actions = actions(manifest)
        self.frame = frame(manifest)
        self.inside = inside(manifest)
        self.section = manifest.get("section", "")
        self.seed = seed_scripts(manifest)
        self.url = f"http://127.0.0.1:{self.port}"
        # Variables this app's backend gets on top of the launcher's (a
        # release sets where each app keeps its data this way).
        self.env: dict[str, str] = {}
        self.proc: subprocess.Popen | None = None
        self.state = "pending"  # pending | idle | starting | up | failed | missing
        # Why the last start failed, for the hub's card: "port_busy" (another
        # program holds the port), "exited" (it stopped while starting),
        # "slow" (no answer in time) or "".
        self.reason = ""

    @property
    def source(self) -> str:
        return os.path.join(self.root, self.src_dir)

    def python(self, forge_root: str = ROOT) -> str:
        own = venv_python(os.path.join(self.root, ".venv"))
        if os.path.isfile(own):
            return own
        return runtime_python(forge_root) or sys.executable

    def command(self, python: str, serve: str = "") -> list[str]:
        if serve:
            # The release's guarded uvicorn (forge_serve.py).
            return [python, serve, self.module, "--port", str(self.port)]
        # `python -m uvicorn`, never a uvicorn script: a venv made with
        # --system-site-packages has no script of its own, and a release
        # runtime has none either.
        return [
            python,
            "-m",
            "uvicorn",
            self.module,
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
        ]

    def environment(self, forge_root: str = ROOT, extra: dict | None = None) -> dict:
        env = os.environ.copy()
        env["FORGE_SHARED_DIR"] = os.path.join(forge_root, "shared")
        # Files are UTF-8 everywhere in Forge; Windows would otherwise open
        # them in the local code page and fail on the first accent.
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        bin_dir = os.path.join(self.root, "bin")
        if os.path.isdir(bin_dir):
            # Native helpers an app ships next to its source (AI Studio's
            # sd-server) find their libraries here.
            var = (
                "PATH"
                if WINDOWS
                else "DYLD_LIBRARY_PATH" if MACOS else "LD_LIBRARY_PATH"
            )
            env[var] = bin_dir + os.pathsep + env.get(var, "")
        env.update(extra or {})
        return env

    def snapshot(self) -> dict:
        """What the hub's FORGE_STATUS holds for this app (as forge.py)."""
        return {
            "available": self.state == "up",
            "state": self.state,
            "reason": self.reason,
            "label": self.label,
            "tagline": self.tagline,
            "url": self.url,
            "accent": self.accent,
            "icon": self.icon,
            "role": self.role,
            "fullscreen": self.fullscreen,
            "order": self.order,
            "group": self.group,
            "own_group": self.group,
            "section": self.section,
            "dev": self.dev,
            "help": self.help,
            "own_keys": self.own_keys,
            "actions": self.actions,
            "frame": self.frame,
            "inside": self.inside,
        }


def discover_apps(
    apps_dir: str, port_offset: int = 0, log: Callable[[str], None] = print
) -> list[App]:
    """Every apps/<dir>/forge_app.json becomes an app, ordered by the
    manifest's "order". A manifest's "root" points at a codebase kept
    elsewhere; one that does not exist leaves the app out."""
    found = []
    if not os.path.isdir(apps_dir):
        return found
    for entry in sorted(os.listdir(apps_dir)):
        folder = os.path.join(apps_dir, entry)
        manifest_path = os.path.join(folder, "forge_app.json")
        if not os.path.isfile(manifest_path):
            continue
        try:
            manifest = read_json(manifest_path)
            manifest.setdefault("name", entry)
            root = (
                os.path.expanduser(manifest["root"]) if manifest.get("root") else folder
            )
            found.append(App(manifest, root, port_offset))
        except Exception as e:
            log(f"[forge] {entry}: bad forge_app.json, skipping ({e})")
    found.sort(key=lambda a: (a.order, a.name))
    return found


def group_fields(group_id: str, data: dict) -> dict:
    """One groups/<id>.json as the hub reads it (forge.py shares this).

    A group is a chooser by default. "tabs": true makes it a place: its tile
    opens straight into the member used last, with the members as tabs along
    the top. "merged": true says the members were folded into one new place,
    so the hub shows the place's name over the tab's. "members" lists apps
    by name in tab order (an app's own "group" line joins it too), and
    "tab_labels" names a member's tab ({"ipod": "Other devices"}). "off": true
    undoes the fold: the group is skipped and every member keeps its own tile.
    "glyph" names its icon in shared/forge_icons.js when the group's id is
    already an app's (groups/devices.json and apps/devices).
    """
    members = data.get("members", [])
    labels = data.get("tab_labels", {})
    return {
        "id": group_id,
        "label": data.get("label", group_id),
        "tagline": data.get("tagline", ""),
        "icon": data.get("icon", ""),
        "accent": data.get("accent", ""),
        "order": data.get("order", 99),
        "section": data.get("section", ""),
        "tabs": bool(data.get("tabs", False)),
        "merged": bool(data.get("merged", False)),
        "listed": (
            [m for m in members if isinstance(m, str)]
            if isinstance(members, list)
            else []
        ),
        "tab_labels": (
            {k: v for k, v in labels.items() if isinstance(v, str)}
            if isinstance(labels, dict)
            else {}
        ),
        "help": data.get("help", ""),
        "glyph": data["glyph"] if isinstance(data.get("glyph"), str) else "",
    }


def discover_groups(groups_dir: str, log: Callable[[str], None] = print) -> dict:
    """Every groups/<id>.json: one tile standing for the apps that join it.
    A file saying "off": true is left out, which gives its apps their own
    tiles back."""
    found = {}
    for path in sorted(glob.glob(os.path.join(groups_dir, "*.json"))):
        group_id = os.path.splitext(os.path.basename(path))[0]
        try:
            data = read_json(path)
            if not isinstance(data, dict):
                raise ValueError("not a JSON object")
        except Exception as e:
            log(f"[forge] group {group_id}: bad file, skipping ({e})")
            continue
        if data.get("off"):
            continue
        found[group_id] = group_fields(group_id, data)
    return found


def resolve_groups(apps: list, groups: dict) -> dict:
    """{app name: group id} for every app that sits behind a group tile.

    `apps` is (name, own group) pairs in app order. An app's own "group" line
    wins when that group exists; otherwise the first group (by id) that lists
    it in "members". An app no existing group claims keeps its tile."""
    out = {}
    for name, own in apps:
        if own and own in groups:
            out[name] = own
            continue
        for gid in sorted(groups):
            if name in groups[gid].get("listed", []):
                out[name] = gid
                break
    return out


def attach_members(apps: list, groups: dict) -> dict:
    """The groups that have members. A group's "members" order comes first
    (the tab order), then apps that joined by their own line, in app order."""
    where = resolve_groups(apps, groups)
    attached: dict = {}
    names = [name for name, _ in apps]
    for gid, g in groups.items():
        mine = [n for n in names if where.get(n) == gid]
        if not mine:
            continue
        listed = [n for n in g.get("listed", []) if n in mine]
        rest = [n for n in mine if n not in listed]
        attached[gid] = dict(g, members=listed + rest)
    return attached


def discover_sections(sections_dir: str, log: Callable[[str], None] = print) -> dict:
    """Every sections/<id>.json: a heading on the home screen, in "order"."""
    found = []
    for path in sorted(glob.glob(os.path.join(sections_dir, "*.json"))):
        section_id = os.path.splitext(os.path.basename(path))[0]
        try:
            data = read_json(path)
        except Exception as e:
            log(f"[forge] section {section_id}: bad file, skipping ({e})")
            continue
        found.append(
            {
                "id": section_id,
                "label": data.get("label", section_id),
                "icon": data.get("icon", ""),
                "blurb": data.get("blurb", ""),
                "order": data.get("order", 99),
            }
        )
    found.sort(key=lambda s: (s["order"], s["id"]))
    return {s["id"]: s for s in found}


def attach_groups(apps: list[App], groups: dict) -> dict:
    """The groups that have members, each listing its apps in tab order."""
    return attach_members([(a.name, a.group) for a in apps], groups)


# What the hub page itself may save: its Aa panel's sizes and size presets, a
# tile's menu (hidden and archived apps), folders made by dragging one app onto
# another, Now playing's volume, and the Alt+A animations switch. The effect
# keys (Alt+E, Alt+P, Alt+M) and the visuals popup save forge_theme's
# VISUALS_POPUP rows as well. Every other setting belongs to Settings.
HUB_SETTING_KEYS = (
    "size_presets",
    "hidden_apps",
    "archived_apps",
    "app_folders",
    "music_volume",
    # the owner (2026-10-23): Alt+A off was forgotten when Forge restarted
    "animations",
)


def save_hub_settings(changes: dict, theme_module, path=None) -> dict | None:
    """Save the keys of `changes` the hub may change (forge_theme's SIZE_KEYS
    and VISUALS_POPUP, and HUB_SETTING_KEYS) through `theme_module`
    (shared/forge_theme.py) and return them; anything else in `changes` is
    dropped. None when a locked look (Business) refused the save."""
    allowed = (
        set(theme_module.SIZE_KEYS)
        | set(theme_module.VISUALS_POPUP)
        | set(HUB_SETTING_KEYS)
    )
    picked = {k: v for k, v in changes.items() if k in allowed}
    if picked:
        try:
            theme_module.save(picked, path)
        except theme_module.forge_lock.Locked:
            return None  # Business is locked
    return picked


def end_process(proc: subprocess.Popen) -> None:
    """Ask a backend's process group to stop (Windows: end its tree)."""
    if proc.poll() is not None:
        return
    if WINDOWS:
        # No signals to send a console-less process: taskkill ends the tree,
        # so a backend's own helpers (ffmpeg and the like) go with it.
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except OSError:
        pass


def kill_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if WINDOWS:
        proc.kill()
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass


class AppManager:
    """Starts apps when first opened and stops them all at the end.

    `on_change` is called (from a worker thread) whenever an app's state
    changes, so the caller can push the new status to the hub.

    With `guard` (the release launcher) each backend runs through
    forge_serve.py: it answers only to this machine's own names (no DNS
    rebinding), it ends when this process ends, and a port some other
    program holds is never taken for the app.

    With `seed_dir`, an app's "seed" scripts run before its first start, each
    once per data folder and again only when the script itself changes (a
    newer release adds what is new; the scripts never overwrite edits)."""

    def __init__(
        self,
        apps: list[App],
        forge_root: str = ROOT,
        log_dir: str | None = None,
        env: dict | None = None,
        on_change: Callable[[], None] = lambda: None,
        log: Callable[[str], None] = print,
        guard: bool = False,
        seed_dir: str | None = None,
    ):
        self.apps = {a.name: a for a in apps}
        self.guard = guard
        # Where "this starting-data script has run" is noted, beside the data
        # it wrote; None runs no seed scripts (forge.py's own data is there).
        self.seed_dir = seed_dir
        self._seed_lock = threading.Lock()
        self.forge_root = forge_root
        self.log_dir = log_dir or os.path.join(forge_root, "outputs")
        self.env = env or {}
        self.on_change = on_change
        self.log = log
        self._lock = threading.Lock()
        for a in apps:
            a.state = "idle"

    def snapshot(self) -> dict:
        status = {}
        for name, a in self.apps.items():
            status[name] = a.snapshot()
            # the hub's "didn't start" card points here (critic round F1,
            # Relay task 405: it named forge.py's outputs/ folder)
            status[name]["log"] = os.path.join(self.log_dir, f"{name}.log")
        return status

    def start_async(self, name: str) -> bool:
        """Start one app on a worker thread; False when there is nothing to do."""
        app = self.apps.get(name)
        if app is None:
            return False
        with self._lock:
            if app.state in ("starting", "up"):
                return False
            app.state = "starting"
        threading.Thread(target=self._start, args=(app,), daemon=True).start()
        self.on_change()
        return True

    def start_and_wait(self, name: str) -> bool:
        app = self.apps[name]
        with self._lock:
            if app.state == "up":
                return True
            app.state = "starting"
        return self._start(app)

    def _start(self, app: App) -> bool:
        ok = self._run(app)
        self.on_change()
        return ok

    def _run(self, app: App) -> bool:
        app.reason = ""
        if not os.path.isdir(app.source):
            self.log(f"[forge] {app.name}: no source folder ({app.source})")
            app.state = "missing"
            return False
        if port_open(app.port) and self.guard:
            # A guarded backend ends with its launcher, so this is another
            # program (or one still shutting down): never show it as the app.
            deadline = time.time() + 3.0
            while port_open(app.port) and time.time() < deadline:
                time.sleep(0.2)
            if port_open(app.port):
                line = (
                    f"[forge] {app.name}: port {app.port} is in use by another"
                    " program; start Forge with --port-offset to move every port"
                )
                self.log(line)
                # the failed card names this app's own log (critic round G,
                # Relay task 405: it was never written when the app never ran)
                os.makedirs(self.log_dir, exist_ok=True)
                with open(
                    os.path.join(self.log_dir, f"{app.name}.log"),
                    "a",
                    encoding="utf-8",
                ) as f:
                    f.write(line + "\n")
                app.reason = "port_busy"
                app.state = "failed"
                return False
        if port_open(app.port):
            # Something already answers there: an earlier launcher's backend
            # left behind, or a service of the app's own. Use it.
            self.log(f"[forge] {app.name}: already running on {app.url}, using it")
            app.state = "up"
            return True
        os.makedirs(self.log_dir, exist_ok=True)
        log_file = open(os.path.join(self.log_dir, f"{app.name}.log"), "ab")
        flags: dict = {}
        if WINDOWS:
            # Read with getattr: the names exist only on Windows, and the
            # type checker runs on Linux.
            flags["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            ) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            flags["start_new_session"] = True
        self._seed(app, log_file, flags)
        try:
            serve = (
                os.path.join(self.forge_root, "forge_serve.py") if self.guard else ""
            )
            extra = {**self.env, **app.env}
            if self.guard:
                extra["FORGE_PARENT_PID"] = str(os.getpid())
            proc = subprocess.Popen(
                app.command(app.python(self.forge_root), serve),
                cwd=app.source,
                env=app.environment(self.forge_root, extra),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                **flags,
            )
        except OSError as e:
            log_file.close()
            self.log(f"[forge] {app.name}: could not start ({e})")
            app.state = "failed"
            return False
        log_file.close()
        app.proc = proc
        self.log(f"[forge] {app.name}: starting on {app.url} (pid {proc.pid})")
        deadline = time.time() + float(app.ready_timeout)
        while time.time() < deadline:
            if app.proc is not proc:
                return False  # stopped while it started
            if port_open(app.port):
                app.state = "up"
                self.log(f"[forge] {app.name}: ready")
                return True
            if proc.poll() is not None:
                app.reason = "exited"
                app.state = "failed"
                self.log(
                    f"[forge] {app.name}: exited early (code {proc.returncode})"
                    f" -- see {os.path.join(self.log_dir, app.name + '.log')}"
                )
                return False
            time.sleep(0.1)
        app.reason = "slow"
        app.state = "failed"
        self.log(f"[forge] {app.name}: not ready within {app.ready_timeout}s")
        return False

    def _seed(self, app: App, log_file, flags: dict) -> None:
        """Run the app's starting-data scripts that have not run on this data
        folder yet. A script that fails is logged and tried at the next
        start; the app starts either way."""
        if not self.seed_dir:
            return
        for owner_name, rel in app.seed:
            owner = self.apps.get(owner_name or app.name)
            if owner is None:
                continue  # that app is not in this Forge
            script = os.path.join(owner.root, *rel.split("/"))
            try:
                with open(script, "rb") as f:
                    digest = hashlib.sha256(f.read()).hexdigest()
            except OSError:
                self.log(f"[forge] {app.name}: no starting-data script {rel}")
                continue
            marker = os.path.join(
                self.seed_dir, owner.name, rel.replace("/", "__") + ".done"
            )
            with self._seed_lock:
                try:
                    with open(marker, encoding="utf-8") as f:
                        if f.read().strip() == digest:
                            continue
                except OSError:
                    pass
                log_file.write(f"[forge] writing starting data: {rel}\n".encode())
                log_file.flush()
                extra = {**self.env, **owner.env}
                done: int | str
                try:
                    done = subprocess.run(
                        [owner.python(self.forge_root), script],
                        cwd=owner.root,
                        env=owner.environment(self.forge_root, extra),
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        timeout=SEED_TIMEOUT,
                        creationflags=flags.get("creationflags", 0),
                    ).returncode
                except (OSError, subprocess.TimeoutExpired) as e:
                    done = f"{type(e).__name__}"
                if done != 0:
                    self.log(
                        f"[forge] {app.name}: starting data not written ({rel}:"
                        f" {done}) -- see {os.path.join(self.log_dir, app.name + '.log')}"
                    )
                    continue
                os.makedirs(os.path.dirname(marker), exist_ok=True)
                with open(marker, "w", encoding="utf-8") as f:
                    f.write(digest + "\n")
                self.log(
                    f"[forge] {app.name}: wrote starting data ({owner.name}: {rel})"
                )

    def stop(self, name: str, timeout: float = 3.0) -> bool:
        app = self.apps.get(name)
        if app is None or app.proc is None:
            return False
        proc, app.proc = app.proc, None
        end_process(proc)
        try:
            proc.wait(timeout)
        except subprocess.TimeoutExpired:
            kill_process(proc)
        app.state = "idle"
        self.on_change()
        return True

    def stop_all(self, timeout: float = 3.0) -> None:
        """Every backend is asked to stop at once, then waited for together:
        stopping them one after another took seconds."""
        running = [(a, a.proc) for a in self.apps.values() if a.proc is not None]
        for a, proc in running:
            a.proc = None
            end_process(proc)
        deadline = time.time() + timeout
        for a, proc in running:
            try:
                proc.wait(max(0.0, deadline - time.time()))
            except subprocess.TimeoutExpired:
                kill_process(proc)
            a.state = "idle"
