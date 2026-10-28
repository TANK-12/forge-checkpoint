#!/usr/bin/env python3
"""Forge portable -- the launcher a Forge release runs on Windows, macOS and Linux.

WHAT THIS IS
    forge.py is Forge on the Linux desktop it grew up on: a GTK window whose
    WebKit view loads hub/index.html over file:// and talks to the page through
    WebKit's message channel. None of that exists on Windows or macOS. This
    launcher keeps everything else -- the same apps/, groups/, sections/, hub/
    and shared/, the same manifests, apps found by scanning -- and replaces
    only the window and the channel to it:

    * the hub is served over http://127.0.0.1:<hub_port> by a small standard
      library server in this file; status.js and theme.js are made per request
      instead of being written into hub/;
    * the page's `window.webkit.messageHandlers.forge` calls become POSTs to
      /forge/bridge (hub/portable.js), and what forge.py pushed into the page
      with run_javascript arrives on an event stream, /forge/events;
    * the window is whatever this system has, tried in the order the release
      registry gives (release/release.json, window_order.<os>): "native" (a
      GTK WebKit window through the system Python on Linux, pywebview on
      macOS), "app" (Edge, Chrome, Chromium or Brave in app mode: a window
      with no tabs or address bar), "browser" (a tab), or "none".

    The apps themselves run exactly as under forge.py (forge_core.py): one
    `python -m uvicorn` backend each, started when first opened, all stopped
    when Forge closes. In a release they share the Python in runtime/.

WHAT A SYSTEM CANNOT DO
    The registry lists, per system, every hub feature that is native, replaced,
    has a fallback, or is cut. The controls of a feature that is not native
    are hidden (its "hide" selectors) and its settings are left out of the
    Settings app (FORGE_CUT_SETTINGS, read by forge_theme.describe), as are
    whole Settings pages and their Reset groups (FORGE_CUT_PAGES and
    FORGE_CUT_RESETS, read by the Settings app) and help naming something cut
    is reworded (FORGE_SETTING_WORDS, and a Reset group's description in
    FORGE_RESET_WORDS), so no button is left that does
    nothing; home widgets it cannot feed ("widgets")
    are taken out of the widget menu. Apps cut on a system are not started.
    The top bar's and the widgets' system numbers (shared/forge_sysinfo.py)
    go out every 3 s as a "stats" event where the registry keeps them.
    An app's registry entry may also name variables for its backend ("env"),
    mostly where it keeps its data; see expand().

WHERE THINGS GO
    What a user makes (settings, saves, every app's data) lives in one folder
    they choose, "Forge data", with config/ and data/ inside. The first start
    asks where (hub/welcome.html: on this computer, or on a drive or folder
    they pick); a small pointer file outside that folder remembers it
    (local_dirs: ~/.config/forge-release/where.json on Linux,
    %APPDATA%\\Forge\\where.json on Windows). Caches, logs and window state
    stay on this computer. The release never uses forge.py's ~/.config/forge.
    Until a place is chosen, and whenever the chosen one cannot be used (a
    drive not plugged in, read-only, full, or holding other Forge data), no
    app is found, seeded or started: the server shows only that page. The
    place is checked at every start and every few seconds while Forge runs;
    hub/data.html shows it and moves it (a verified copy, the old one kept).
    Nothing is written into the release folder by the launcher.

SAFETY
    The server listens on 127.0.0.1 only. Every request must name this machine
    in its Host header (no DNS rebinding); the bridge, the event stream and the
    file routes also need the per-launch token the hub page is given, and the
    bridge refuses another page's Origin. Files are served only from the
    theme's cache, the wallpaper folder, the music folder and the wallpaper in
    use.

RUN
    python3 forge_portable.py                    open Forge
    python3 forge_portable.py --window browser   in a browser tab
    python3 forge_portable.py --smoke            start every app, check each
                                                 answers, stop, exit 0 or 1
    python3 forge_portable.py --data FOLDER      keep your things in FOLDER for
                                                 this run only
    python3 forge_portable.py --as-system macos  (checks) the hub as another
                                                 system's release shows it
"""

from __future__ import annotations

import argparse
import errno
import importlib
import json
import os
import posixpath
import queue
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import forge_core
from forge_serve import FRAME_RULE

ROOT = forge_core.ROOT
APPS_DIR = os.path.join(ROOT, "apps")
GROUPS_DIR = os.path.join(ROOT, "groups")
SECTIONS_DIR = os.path.join(ROOT, "sections")
HUB_DIR = os.path.join(ROOT, "hub")
SHARED_DIR = os.path.join(ROOT, "shared")
REGISTRY = os.path.join(ROOT, "release", "release.json")
TITLE = "Forge"
# Windows: the setup program's AppId and AppMutex and its shortcuts'
# AppUserModelID (release/launch/forge.iss); Linux: the menu entry's name.
APP_ID = "local.forge.Forge"
STATES = ("native", "replaced", "fallback", "cut")
# {data}, {config}, {cache}, {state}, {logs} or {port:<app>} in a registry
# "env" value.
PLACEHOLDER = re.compile(r"\{([a-z]+)(?::([A-Za-z0-9_.-]+))?\}")
# What the hub page calls forge.py through, and what it calls here instead.
WEBKIT_BRIDGE = "window.webkit.messageHandlers.forge"
PORTABLE_BRIDGE = "window.forgeBridge"
# The scripts made per request: theme.js carries the file token in its links
# and status.js the apps. Any web page may load a script from another site and
# read what it sets, so these two are handed out only with the bridge's token,
# which hub_page writes into their script tags.
TOKEN_SCRIPTS = ("/hub/status.js", "/hub/theme.js")
# the welcome, problem and data pages (where the user's things are kept)
PLACE_PAGES = ("/hub/welcome.html", "/hub/data.html")
# What forge.py writes into hub/ for its own window: made per request here,
# never handed out from the folder.
GENERATED = ("status.js", "theme.js", "status.json")
# An event stream with no page on it for this long ends Forge: the window was
# closed. A reload reconnects well inside it.
IDLE_GRACE = 20.0
PING_SECONDS = 5.0
STATS_SECONDS = 3.0  # as forge.py's StatsPump
WINDOW_SIZE = (1400, 900)
# A wallpaper may be a short video as well as a picture.
WALLPAPER_VIDEO = {".mp4", ".webm"}
# What a page loads from its own server, for the smoke check.
PAGE_REF = re.compile(
    r"""<(?:script|link|img)\b[^>]*?\s(?:src|href)\s*=\s*["']([^"'#]+)""", re.I
)
IMPORT_MAP = re.compile(
    r"<script\s+type=[\"']importmap[\"']>(.*?)</script>", re.S | re.I
)
# Pages of this machine (the apps, each on its own port) may read Forge's
# files for canvas and Web Audio; another site's page may not.
LOCAL_ORIGIN = re.compile(r"http://(127\.0\.0\.1|localhost|\[::1\]):\d+")
GTK_CHECK = (
    "import gi; gi.require_version('Gtk', '3.0'); "
    "gi.require_version('WebKit2', '4.1'); "
    "from gi.repository import Gtk, WebKit2"
)
# Served types by suffix. Not the mimetypes module: on Windows it reads the
# registry, where .js is sometimes text/plain and a browser then refuses it.
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".wasm": "application/wasm",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


# ----------------------------------------------------------------------------
# the release registry, for one system


def load_registry(path: str = REGISTRY) -> dict:
    """release/release.json, or {} when there is none (then every app is in)."""
    try:
        return forge_core.read_json(path)
    except (OSError, ValueError):
        return {}


def entry_state(text) -> str:
    """'native', 'replaced', 'fallback' or 'cut': the first word of a registry
    entry such as "cut: needs a Unix pseudo-terminal". A missing entry is
    native; an unknown word counts as cut, so a typo hides a feature rather
    than leaving a button that does nothing."""
    if text is None:
        return "native"
    word = str(text).split(":", 1)[0].strip().lower()
    return word if word in STATES else "cut"


class Profile:
    """What the release registry says about one system: the apps that run on
    it, and what the hub must hide, leave out of Settings or set."""

    def __init__(self, registry: dict, system: str):
        self.system = system
        self.version = str(registry.get("version") or "dev")
        self.hub_port = int(registry.get("hub_port") or 8400)
        order = (registry.get("window_order") or {}).get(system)
        self.windows = list(order or ["app", "browser"])
        apps = registry.get("apps")
        self.all_apps = not isinstance(apps, dict)
        self.apps: set[str] = set()
        self.cut_apps: dict[str, str] = {}
        self.env: dict[str, str] = dict(registry.get("env") or {})
        self.app_env: dict[str, dict[str, str]] = {}
        for name, entry in (apps or {}).items():
            if not isinstance(entry, dict) or entry.get("include") is not True:
                continue
            self.app_env[name] = dict(entry.get("env") or {})
            if entry_state(entry.get(system)) == "cut":
                self.cut_apps[name] = str(entry.get(system))
            else:
                self.apps.add(name)
        self.sections: dict[str, dict] = {
            name: {k: v for k, v in words.items() if k in ("label", "blurb")}
            for name, words in (registry.get("sections") or {}).items()
            if isinstance(words, dict)
        }
        self.group_words: dict[str, dict] = {
            name: {k: v for k, v in words.items() if k in ("label", "tagline")}
            for name, words in (registry.get("group_words") or {}).items()
            if isinstance(words, dict)
        }
        self.features: dict[str, str] = {}
        self.hide: list[str] = []
        self.cut_widgets: list[str] = []
        self.theme: dict = {}
        self.cut_settings: set[str] = set()
        self.cut_groups: set[str] = set()
        self.cut_pages: list[str] = []
        self.cut_resets: list[str] = []
        self.setting_words: dict[str, str] = {}
        self.reset_words: dict[str, str] = {}
        # Forge's own keys caught by the pages themselves (a "page_keys"
        # feature that is a fallback here), less the actions with no key
        self.page_keys = False
        self.cut_key_actions: set[str] = set()
        for name, feature in (registry.get("features") or {}).items():
            if not isinstance(feature, dict):
                continue
            state = entry_state(feature.get(system, "native"))
            self.features[name] = state
            if state in ("native", "replaced"):
                continue
            self.hide.extend(feature.get("hide") or [])
            self.cut_widgets.extend(
                kind
                for kind in feature.get("widgets") or []
                if kind not in self.cut_widgets
            )
            self.theme.update(feature.get("theme") or {})
            self.cut_settings.update(feature.get("settings") or [])
            self.cut_groups.update(feature.get("settings_groups") or [])
            for names, into in (
                (feature.get("settings_pages"), self.cut_pages),
                (feature.get("reset_groups"), self.cut_resets),
            ):
                into.extend(n for n in names or [] if n not in into)
            self.setting_words.update(feature.get("words") or {})
            self.reset_words.update(feature.get("reset_words") or {})
            self.cut_key_actions.update(feature.get("key_actions") or [])
            if state == "fallback" and feature.get("page_keys"):
                self.page_keys = True

    def includes(self, app_name: str) -> bool:
        return self.all_apps or app_name in self.apps

    def settings_to_cut(self, settings: dict) -> list[str]:
        """The setting keys Settings should not show here: those a feature this
        system lacks names, and every one in a group it lacks. `settings` is
        forge_theme.SETTINGS."""
        keys = set(self.cut_settings)
        keys.update(
            key
            for key, spec in settings.items()
            if isinstance(spec, dict) and spec.get("group") in self.cut_groups
        )
        return sorted(keys)


# The release's folders are its own and never forge.py's (~/.config/forge is
# the daily Forge on the laptop it grew up on): on Linux each is named
# LINUX_NAME. What a user makes lives in one chosen folder, PLACE_NAME, with
# config/ and data/ inside; the pointer naming it lives outside it, so moving
# that folder never moves the pointer.
LINUX_NAME = "forge-release"
PLACE_NAME = "Forge data"
PICKER_SHOWN = 2.0  # seconds: a picker that failed to start ends sooner
POINTER = "where.json"
# beside the window state: the look last seen on a place in use, for the
# problem screen, which cannot read a place that is not there
LOOK_FILE = "look.json"
MARKER = "forge-data.json"


def local_dirs(system: str, env=None, home: str | None = None) -> dict[str, str]:
    """This computer's own folders of a Forge release, which never move:
    "pointer" (the file naming where the user's things are kept), "computer"
    (the folder that holds PLACE_NAME when they stay on this computer), and
    the cache, logs and window state."""
    env = os.environ if env is None else env
    home = home or os.path.expanduser("~")
    if system == "windows":
        roaming = env.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        local = env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return {
            "pointer": os.path.join(roaming, "Forge", POINTER),
            "computer": os.path.join(roaming, "Forge"),
            "cache": os.path.join(local, "Forge", "Cache"),
            "logs": os.path.join(local, "Forge", "Logs"),
            "state": os.path.join(local, "Forge"),
        }
    if system == "macos":
        support = os.path.join(home, "Library", "Application Support", "Forge")
        return {
            "pointer": os.path.join(support, POINTER),
            "computer": support,
            "cache": os.path.join(home, "Library", "Caches", "Forge"),
            "logs": os.path.join(home, "Library", "Logs", "Forge"),
            "state": support,
        }
    config = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    data = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    cache = env.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    state = env.get("XDG_STATE_HOME") or os.path.join(home, ".local", "state")
    return {
        "pointer": os.path.join(config, LINUX_NAME, POINTER),
        "computer": os.path.join(data, LINUX_NAME),
        "cache": os.path.join(cache, LINUX_NAME),
        "logs": os.path.join(state, LINUX_NAME, "logs"),
        "state": os.path.join(state, LINUX_NAME),
    }


def place_dirs(local: dict[str, str], root: str) -> dict[str, str]:
    """The folders apps are given while the user's things are kept in `root`
    (a PLACE_NAME folder): config and data inside it, the rest from
    local_dirs, on this computer."""
    return {
        "root": root,
        "config": os.path.join(root, "config"),
        "data": os.path.join(root, "data"),
        "cache": local["cache"],
        "logs": local["logs"],
        "state": local["state"],
    }


def data_dirs(
    system: str, env=None, home: str | None = None, root: str | None = None
) -> dict[str, str]:
    """Where settings, caches, logs, window state and the apps' own data go:
    settings (config) and the apps' data inside the place `root` (this
    computer's when None), the rest on this computer."""
    local = local_dirs(system, env, home)
    return place_dirs(local, root or os.path.join(local["computer"], PLACE_NAME))


def expand(value: str, dirs: dict[str, str], ports: dict[str, int]) -> str | None:
    """A registry "env" value with its placeholders filled in: {data},
    {config}, {cache}, {state} and {logs} are this system's folders (see
    data_dirs) and {port:<app>} is that app's port, so a variable follows
    --port-offset. None when a placeholder names nothing known here (the
    variable is then left unset and the app's own default holds). A value
    that starts with a folder gets this system's path separators."""
    missing = []

    def one(match: re.Match) -> str:
        kind, arg = match.group(1), match.group(2)
        if kind == "port" and arg in ports:
            return str(ports[arg])
        if arg is None and kind in dirs:
            return dirs[kind]
        missing.append(match.group(0))
        return ""

    out = PLACEHOLDER.sub(one, str(value))
    if missing:
        return None
    first = PLACEHOLDER.match(str(value))
    if first and first.group(1) in dirs and first.group(2) is None:
        out = os.path.normpath(out)
    return out


def expand_all(
    wanted: dict[str, str],
    dirs: dict[str, str],
    ports: dict[str, int],
    log: Callable[[str], None] = print,
) -> dict[str, str]:
    out = {}
    for key, value in wanted.items():
        done = expand(value, dirs, ports)
        if done is None:
            log(f"[forge] {key} left unset: {value!r} names something not here")
        else:
            out[key] = done
    return out


def theme_environment(dirs: dict[str, str], env=None) -> dict[str, str]:
    """Where shared/forge_theme.py, forge_themes.py and forge_lock.py keep
    settings and caches, as the variables they read at import. The cache's
    may be set already (that value is kept); what belongs in the place is
    always the place's, so a release started from a shell of the daily
    Forge never writes into ~/.config/forge. FORGE_HUB_OUT takes the
    theme.js that Settings writes, so nothing is written into a release
    folder that may be read-only."""
    env = os.environ if env is None else env
    local = {
        "FORGE_CACHE": dirs["cache"],
        "FORGE_HUB_OUT": os.path.join(dirs["cache"], "hub"),
        "FORGE_AUTOSTART": os.path.join(dirs["state"], "autostart-unused.desktop"),
        "FORGE_THEME_DESKTOP": os.path.join(dirs["cache"], "desktop-theme"),
    }
    out = {key: env.get(key) or value for key, value in local.items()}
    out.update(
        {
            "FORGE_CONFIG": os.path.join(dirs["config"], "settings.json"),
            "FORGE_LOCK_FILE": os.path.join(dirs["config"], "look-lock.json"),
            "FORGE_LOCK_STATE": os.path.join(dirs["state"], "look-unlock.json"),
            "FORGE_USER_THEMES": os.path.join(dirs["data"], "themes"),
            "FORGE_LOGOS": os.path.join(dirs["data"], "logos"),
        }
    )
    return out


# ----------------------------------------------------------------------------
# small helpers


def inside(root: str, relative: str) -> str | None:
    """The file `relative` names under `root`, or None when it is not a file
    there (a path that climbs out with .. or a link is refused)."""
    try:
        base = os.path.realpath(root)
        target = os.path.realpath(os.path.join(base, relative.lstrip("/\\")))
        if os.path.commonpath([base, target]) != base or target == base:
            return None
    except ValueError:  # another drive on Windows, or a NUL in the name
        return None
    return target if os.path.isfile(target) else None


def clean_path(path: str) -> str:
    """A request path with its . and .. steps, doubled and trailing slashes
    and backslashes resolved: '/hub//status.js/' -> '/hub/status.js'."""
    return "/" + posixpath.normpath("/" + path.replace("\\", "/")).lstrip("/")


def under(path: Path, roots: list[Path]) -> bool:
    """True when `path` is one of `roots` or lies inside one of them."""
    for root in roots:
        if path == root or root in path.parents:
            return True
    return False


def content_type(path: str) -> str:
    return TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def http_get(
    url: str,
    timeout: float = 10.0,
    headers: dict | None = None,
    data: bytes | None = None,
):
    """(status, body bytes) of a GET (a POST of `data` when given); status 0
    when nothing answered."""
    request = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (OSError, ValueError):
        return 0, b""


def http_headers(url: str, timeout: float = 10.0) -> dict[str, str]:
    """The headers of a GET's answer, names in lower case (a header sent more
    than once joined with ", "); {} when nothing answered."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            got = response.headers
    except urllib.error.HTTPError as e:
        got = e.headers
    except (OSError, ValueError):
        return {}
    return {name.lower(): ", ".join(got.get_all(name) or []) for name in got}


def page_refs(html: str, base: str, origin: str) -> list[str]:
    """The addresses under `origin` that a page at `base` loads: script, link
    and img sources and its import map's entries (folder entries skipped)."""
    refs = PAGE_REF.findall(html)
    for block in IMPORT_MAP.findall(html):
        try:
            refs += [str(v) for v in (json.loads(block).get("imports") or {}).values()]
        except (ValueError, AttributeError):
            continue
    out: list[str] = []
    for ref in refs:
        url = urljoin(base, ref.strip())
        if url.startswith(origin) and not url.endswith("/") and url not in out:
            out.append(url)
    return out


def http_post(url: str, body: bytes, headers: dict, timeout: float = 10.0) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as e:
        return e.code
    except (OSError, ValueError):
        return 0


def other_forge(port: int) -> bool:
    """True when a Forge launcher already answers on the port."""
    status, body = http_get(f"http://127.0.0.1:{port}/forge/ping", timeout=2.0)
    try:
        return status == 200 and json.loads(body).get("forge") is True
    except ValueError:
        return False


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


# ----------------------------------------------------------------------------
# where your things are kept: the place, its pointer, its checks and a move
#
# The welcome flow (hub/welcome.html) asks where the user's things are kept
# and the data page (hub/data.html) moves them. The choice is a folder named
# PLACE_NAME with a marker file in it (MARKER: an id and the day it was made);
# the pointer file (local_dirs()["pointer"]) names that folder, its id and
# the drive it is on. At every start the folder must be there, carry the same
# id and take a test write; otherwise Forge starts no app and shows why
# (place_problem), and it never makes an empty folder in the place of a
# missing one.

WATCH_SECONDS = 4.0  # how often the place in use is looked at
MIN_FREE = 10**9  # a new place needs at least this much room
FULL_FREE = 50 * 10**6  # less than this left at start: the drive is full
NETWORK_FS = {
    "nfs",
    "nfs4",
    "cifs",
    "smb3",
    "smbfs",
    "sshfs",
    "fuse.sshfs",
    "fuse.rclone",
    "davfs",
    "fuse.davfs",
    "9p",
    "afs",
    "ceph",
    "glusterfs",
    "fuse.glusterfs",
}
FAT_FS = {"vfat", "msdos", "fat", "fat16", "fat32"}
# Drives that keep no Unix modes: a move there compares names, sizes and
# checksums, not modes (forge_external's modes=False).
NO_MODES_FS = FAT_FS | {"exfat", "ntfs", "ntfs3", "fuseblk"}
REMOVABLE_MOUNTS = ("/run/media/", "/media/", "/mnt/", "/Volumes/")
PICK_TITLE = "Choose where Forge keeps your things"
# the welcome's two looks: Forge's own dark one, and its light theme
LOOK_THEMES = {"dark": "forge", "light": "forge-light"}
# the shared modules that settle their folders at import (theme_environment)
THEME_MODULES = ("forge_lock", "forge_themes", "forge_theme")


def read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_json(path: str, data: dict) -> None:
    """Write through a temporary file beside it, so a crash never leaves half
    a file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_marker(folder: str) -> dict | None:
    """The marker of a Forge data folder, or None when folder is not one."""
    marker = read_json(os.path.join(folder, MARKER))
    if (
        marker
        and marker.get("what") == PLACE_NAME
        and isinstance(marker.get("id"), str)
    ):
        return marker
    return None


def today() -> str:
    return time.strftime("%Y-%m-%d")


def make_place(folder: str, version: str) -> dict:
    """Make folder a Forge data folder (its parent must exist), or take up the
    one already there; returns its marker."""
    if not os.path.isdir(folder):
        os.mkdir(folder)
    for sub in ("config", "data"):
        os.makedirs(os.path.join(folder, sub), exist_ok=True)
    marker = read_marker(folder)
    if marker is None:
        marker = {
            "what": PLACE_NAME,
            "id": secrets.token_hex(8),
            "made": today(),
            "by": f"Forge {version}",
        }
        write_json(os.path.join(folder, MARKER), marker)
    elif marker.pop("old_copy", None) is not None:
        write_json(os.path.join(folder, MARKER), marker)  # in use again
    return marker


def write_test(folder: str) -> str:
    """ "" when a small file can be written into folder and removed again,
    else why not: "full" or "read-only"."""
    path = os.path.join(folder, f".forge-write-test-{os.getpid()}")
    try:
        with open(path, "wb") as f:
            f.write(b"forge")
            f.flush()
            os.fsync(f.fileno())
        os.remove(path)
        return ""
    except OSError as e:
        try:
            os.remove(path)
        except OSError:
            pass
        full = (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC))
        return "full" if e.errno in full else "read-only"


def existing(path: str) -> str:
    """path, or its nearest folder above it that exists."""
    path = os.path.abspath(path)
    while not os.path.exists(path):
        up = os.path.dirname(path)
        if up == path:
            break
        path = up
    return path


def empty_folder(path: str) -> bool:
    try:
        return os.path.isdir(path) and not os.path.islink(path) and not os.listdir(path)
    except OSError:
        return False


def free_space(path: str) -> int | None:
    try:
        return shutil.disk_usage(existing(path)).free
    except OSError:
        return None


def size_text(n: int | None) -> str:
    if n is None:
        return "unknown"
    if n >= 10**9:
        return f"{n / 1e9:.1f} GB"
    if n >= 10**6:
        return f"{n / 1e6:.0f} MB"
    return f"{max(n, 0) / 1e3:.0f} KB"


def same_or_inside(path: str, folder: str) -> bool:
    """path is folder or somewhere under it (both made absolute, links
    followed, case folded where the system ignores case)."""
    a = os.path.normcase(os.path.realpath(path))
    b = os.path.normcase(os.path.realpath(folder))
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def unescape_mount(path: str) -> str:
    """/proc/mounts writes a space as \\040, a tab as \\011, a backslash as \\134."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), path)


def linux_mounts(text: str) -> list[tuple[str, str, str]]:
    """(device, mount point, filesystem) for every line of /proc/mounts."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            out.append((unescape_mount(parts[0]), unescape_mount(parts[1]), parts[2]))
    return out


def disk_ids(device: str, base: str = "/dev/disk") -> tuple[str, str]:
    """(label, uuid) of a Linux block device, from /dev/disk/by-label and
    by-uuid; empty when it has none."""
    found = {"by-label": "", "by-uuid": ""}
    try:
        real = os.path.realpath(device)
    except OSError:
        return "", ""
    for kind in found:
        folder = os.path.join(base, kind)
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            if os.path.realpath(os.path.join(folder, name)) == real:
                found[kind] = unescape_mount(name.replace("\\x20", " "))
                break
    return found["by-label"], found["by-uuid"]


def drive_of(path: str, system: str, mounts_file: str = "/proc/mounts") -> dict:
    """The drive a folder is on: mount, fs (filesystem), name (the drive's
    label or short name), uuid (Linux) or serial (Windows), removable and
    network."""
    where = existing(path)
    if system == "windows":
        return windows_drive(where)
    real = os.path.realpath(where)
    rows: list[tuple[str, str, str]] = []
    if system == "linux":
        try:
            with open(mounts_file, encoding="utf-8", errors="surrogateescape") as f:
                rows = linux_mounts(f.read())
        except OSError:
            rows = []
    elif system == "macos":
        rows = mac_mounts()
    best = ("", "/", "")
    for device, mount, fs in rows:
        if same_or_inside(real, mount) and len(mount) >= len(best[1]):
            best = (device, mount, fs)
    device, mount, fs = best
    label, uuid = (
        disk_ids(device)
        if system == "linux" and device.startswith("/dev/")
        else ("", "")
    )
    removable = mount.startswith(REMOVABLE_MOUNTS)
    name = label or (os.path.basename(mount.rstrip("/")) if removable else "")
    return {
        "mount": mount,
        "fs": fs,
        "name": name or "this computer",
        "uuid": uuid,
        "removable": removable,
        "network": fs in NETWORK_FS or fs.startswith("fuse.sshfs"),
    }


def mac_mounts() -> list[tuple[str, str, str]]:
    """(device, mount point, filesystem) from macOS's mount command."""
    try:
        out = subprocess.run(
            ["/sbin/mount"], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows = []
    for line in out.splitlines():
        m = re.match(r"(.+?) on (.+) \(([^,)]+)", line)
        if m:
            rows.append((m.group(1), m.group(2), m.group(3)))
    return rows


def windows_drive(path: str) -> dict:
    """drive_of on Windows, from the volume's own information."""
    out = {
        "mount": os.path.splitdrive(path)[0] + "\\",
        "fs": "",
        "name": "",
        "uuid": "",
        "removable": False,
        "network": path.startswith(("\\\\", "//")),
    }
    if sys.platform != "win32":
        return out
    import ctypes

    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_unicode_buffer(1024)
    if kernel32.GetVolumePathNameW(path, buf, 1024):
        out["mount"] = buf.value
    label = ctypes.create_unicode_buffer(261)
    fs = ctypes.create_unicode_buffer(261)
    serial = ctypes.c_ulong(0)
    if kernel32.GetVolumeInformationW(
        out["mount"], label, 261, ctypes.byref(serial), None, None, fs, 261
    ):
        out["name"], out["fs"] = label.value, fs.value.lower()
        out["uuid"] = f"{serial.value:08X}"
    kind = kernel32.GetDriveTypeW(out["mount"])
    out["removable"] = kind == 2 or (
        kind == 3
        and out["mount"][:2].upper() != os.environ.get("SystemDrive", "C:").upper()
    )
    out["network"] = out["network"] or kind == 4
    if not out["name"]:
        out["name"] = out["mount"].rstrip("\\") if out["removable"] else "this computer"
    return out


def drives(system: str, home: str | None = None) -> list[dict]:
    """The drives a user may keep Forge's data on besides this computer's own
    folder: mounted, not network, not the one home is on (that is "this
    computer"), with free space and a suggested folder."""
    if SHARED_DIR not in sys.path:
        sys.path.insert(0, SHARED_DIR)
    import forge_sysinfo

    home = home or os.path.expanduser("~")
    try:
        rows = forge_sysinfo.disks()
    except Exception:
        rows = []
    out = []
    for row in rows:
        mount = row.get("mount") or ""
        if not mount or row.get("system") or same_or_inside(home, mount):
            continue
        drive = drive_of(mount, system)
        if drive["network"]:
            continue
        free = free_space(mount)
        out.append(
            {
                "mount": mount,
                "name": drive["name"] if drive["name"] != "this computer" else mount,
                "fs": drive["fs"],
                "removable": drive["removable"],
                "free": free,
                "free_text": size_text(free),
                "folder": os.path.join(mount, PLACE_NAME),
            }
        )
    return out


def pointer_for(folder: str, marker: dict, system: str) -> dict:
    """What the pointer file says about a place."""
    drive = drive_of(folder, system)
    try:
        rel = os.path.relpath(folder, drive["mount"])
    except ValueError:
        rel = ""
    return {
        "root": folder,
        "id": marker["id"],
        "chosen": today(),
        "drive": {
            "name": drive["name"],
            "uuid": drive["uuid"],
            "mount": drive["mount"],
            "rel": rel,
            "removable": drive["removable"],
        },
    }


def mount_points(system: str) -> list[str]:
    """Every place a drive is mounted now (where a moved drive may be)."""
    if system == "windows":
        return [f"{chr(65 + n)}:\\" for n in range(26)]
    if system == "macos":
        return [m for _, m, _ in mac_mounts()]
    try:
        with open("/proc/mounts", encoding="utf-8", errors="surrogateescape") as f:
            return [m for _, m, _ in linux_mounts(f.read())]
    except OSError:
        return []


def find_moved(
    pointer: dict,
    system: str,
    mounts: list[str] | None = None,
    uuid_of=None,
) -> str | None:
    """Where the pointer's place is now when its drive came back under
    another name (another drive letter, or /run/media/<user>/<label>1): the
    same folder carrying the same id on the same drive (its uuid or volume
    serial). A backup of the folder on another drive, an old copy left by a
    Move, or a place whose drive has no known uuid is never taken by itself:
    the problem screen asks instead."""
    drive = pointer.get("drive") or {}
    rel, uuid = str(drive.get("rel") or ""), str(drive.get("uuid") or "")
    if not rel or rel.startswith("..") or not uuid:
        return None
    uuid_of = uuid_of or (lambda path: drive_of(path, system)["uuid"])
    for mount in mounts if mounts is not None else mount_points(system):
        candidate = os.path.join(mount, rel)
        if candidate == pointer.get("root"):
            continue
        marker = read_marker(candidate)
        if not marker or marker["id"] != pointer.get("id"):
            continue
        if marker.get("old_copy") or uuid_of(candidate) != uuid:
            continue
        return candidate
    return None


def place_problem(root: str, want_id: str, drive: dict | None = None) -> dict | None:
    """None when root is the Forge data folder with id want_id and takes a
    test write; otherwise why not, for the problem screen: "missing" (not
    there: a drive not plugged in, or a folder moved away), "empty" (the
    folder is there but holds no Forge data: an empty mount folder left
    behind), "other" (it holds other Forge data), "read-only" or "full"."""
    drive = drive or {}
    name = drive.get("name") or ""
    base = {"root": root, "drive": name, "removable": bool(drive.get("removable"))}
    usable = bool(root) and os.path.isabs(root)
    marker = read_marker(root) if usable else None
    if marker is None:
        why = "empty" if usable and os.path.isdir(root) else "missing"
        return {**base, "why": why}
    if marker["id"] != want_id:
        return {**base, "why": "other", "made": marker.get("made", "")}
    failed = write_test(root)
    free = free_space(root)
    if failed == "full" or (free is not None and free < FULL_FREE):
        return {**base, "why": "full", "free": free, "free_text": size_text(free)}
    if failed:
        return {**base, "why": "read-only"}
    return None


def check_place(
    path: str,
    system: str,
    current: str | None = None,
    move_size: int = 0,
    program: str = ROOT,
) -> dict:
    """Whether a folder the user chose or typed can hold Forge's data:
    {"ok", "folder" (the Forge data folder that would be used), "adopt" (its
    marker when Forge data is already there), "problem" (why not, in plain
    words), "notes", "free", "drive"}. With `current` (a move) the place must
    be new, outside the current one, and have room for move_size more."""
    out: dict = {"ok": False, "folder": "", "adopt": None, "problem": "", "notes": []}
    raw = os.path.expanduser(path or "")
    if not os.path.lexists(raw):  # pasted with spaces or quotes around it
        raw = os.path.expanduser((path or "").strip().strip('"').strip())
    if not raw:
        out["problem"] = "Type a folder's path, or choose one."
        return out
    if not os.path.isabs(raw):
        example = "D:\\" if system == "windows" else "/"
        out["problem"] = f"Type the whole path, starting with {example}"
        return out
    chosen = os.path.normpath(raw)
    try:
        chosen.encode(sys.getfilesystemencoding())
    except UnicodeEncodeError:
        out["problem"] = "Forge cannot use that folder's name on this system."
        return out
    if read_marker(chosen) or os.path.basename(chosen) == PLACE_NAME:
        folder = chosen
    else:
        folder = os.path.join(chosen, PLACE_NAME)
    out["folder"] = folder
    parent = os.path.dirname(folder)
    if not os.path.isdir(parent):
        out["problem"] = f"{parent} does not exist. Choose a folder that does."
        return out
    if same_or_inside(folder, program) or same_or_inside(program, folder):
        out["problem"] = (
            "That is inside the Forge program folder, which a new version"
            " replaces. Choose a place outside it."
        )
        return out
    drive = drive_of(parent, system)
    out["drive"] = drive
    if drive["network"]:
        out["problem"] = (
            "That is a network folder. Forge keeps your things on this"
            " computer or on a drive plugged into it."
        )
        return out
    marker = read_marker(folder)
    if current:
        if same_or_inside(folder, current) and same_or_inside(current, folder):
            out["problem"] = "Your things are kept there now."
            return out
        if same_or_inside(folder, current) or same_or_inside(current, folder):
            out["problem"] = (
                "That is inside the folder your things are in now. Choose a"
                " place outside it."
            )
            return out
        if marker:
            out["problem"] = (
                "That folder already holds Forge data. Choose an empty place"
                " to move to."
            )
            return out
        if os.path.lexists(folder) and not empty_folder(folder):
            out["problem"] = (
                f'There is already a folder named "{PLACE_NAME}" there. Choose'
                " another place, or rename that folder."
            )
            return out
    elif marker:
        out["adopt"] = marker
        out["size"], out["look"] = place_look(folder)
        # a theme the welcome does not offer (Sakura, say): it presses neither
        # look (critic round F1, Relay task 405: it showed Dark)
        kept = read_json(os.path.join(folder, "config", "settings.json")) or {}
        out["own_look"] = (kept.get("theme") or "forge") != LOOK_THEMES[out["look"]]
    elif os.path.isdir(folder) and os.listdir(folder):
        out["problem"] = (
            f'There is already a folder named "{PLACE_NAME}" there that Forge'
            " did not make. Choose another place, or rename that folder."
        )
        return out
    elif os.path.lexists(folder) and not os.path.isdir(folder):
        out["problem"] = f'There is a file named "{PLACE_NAME}" there.'
        return out
    failed = write_test(folder if os.path.isdir(folder) else parent)
    if failed == "read-only":
        out["problem"] = "Forge cannot write there: the drive or folder is read-only."
        return out
    free = free_space(parent)
    out["free"] = free
    need = FULL_FREE if marker else MIN_FREE + move_size
    if failed == "full" or (free is not None and free < need):
        out["problem"] = (
            f"Only {size_text(free)} is free there; Forge needs at least"
            f" {size_text(need)}."
        )
        return out
    if marker:
        made = marker.get("made") or "an earlier day"
        out["notes"].append(
            f"Forge data from {made} is already there. Forge will use it as it is."
        )
        old = marker.get("old_copy")
        if isinstance(old, dict):
            out["notes"].append(
                f"It is an old copy Forge kept after a move on {old.get('date', '?')};"
                f" the newer copy went to {old.get('moved_to', 'another place')}."
            )
    if drive["fs"] in FAT_FS:
        out["notes"].append(
            "This drive uses FAT32, which cannot hold a file bigger than 4 GB."
            " Most things fit; a big video or model will not."
        )
    if drive["removable"]:
        out["notes"].append(
            f"Forge will open only while {drive['name']} is plugged in."
        )
    out["ok"] = True
    return out


def repoint(config: str, old: str, new: str) -> list[str]:
    """After a move: every JSON file under config whose text names a path in
    the old place (an app that saved where its own folder is, such as
    Dossier's location.json) names the same path in the new place. Returns
    the files changed."""
    old_n = os.path.normpath(old)
    changed = []

    def fix(value):
        if isinstance(value, str):
            if value == old_n or value.startswith(old_n + os.sep):
                return new + value[len(old_n) :]
            return value
        if isinstance(value, list):
            return [fix(v) for v in value]
        if isinstance(value, dict):
            return {k: fix(v) for k, v in value.items()}
        return value

    for dirpath, _dirs, files in os.walk(config):
        for name in files:
            path = os.path.join(dirpath, name)
            if not name.endswith(".json") or os.path.getsize(path) > 4_000_000:
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            fixed = fix(data)
            if fixed != data:
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(fixed, f, indent=1, ensure_ascii=False)
                os.replace(tmp, path)
                changed.append(path)
    return changed


def place_size(root: str) -> tuple[int, int]:
    """(bytes, files) in a place, links not followed."""
    if SHARED_DIR not in sys.path:
        sys.path.insert(0, SHARED_DIR)
    import forge_external as fx

    return fx.tree_size(Path(root))


def old_copy_name(src: str) -> str:
    """Where the old place goes after a move: beside it, named as an old copy
    with the day, never over anything already there."""
    base = f"{os.path.basename(os.path.normpath(src))} (old copy, {today()})"
    target = os.path.join(os.path.dirname(os.path.normpath(src)), base)
    n = 2
    while os.path.lexists(target):
        target = os.path.join(os.path.dirname(os.path.normpath(src)), f"{base} {n}")
        n += 1
    return target


def copy_place(
    src: str,
    dst: str,
    fs: str = "",
    progress: Callable[[str], None] = lambda _: None,
) -> None:
    """Copy the Forge data folder src to dst (which must not exist): through
    a scratch folder beside dst, every file's sha256 taken while copying and
    read back from the drive (shared/forge_external.py's verified copy), the
    scratch folder renamed to dst only once all of it matches. A failure
    removes the scratch copy and leaves src as it was."""
    if SHARED_DIR not in sys.path:
        sys.path.insert(0, SHARED_DIR)
    import forge_external as fx

    if empty_folder(dst):
        os.rmdir(dst)  # an empty folder the user made for it
    if os.path.lexists(dst):
        raise fx.ExternalError(f"{dst} is already there")
    modes = fs not in NO_MODES_FS and sys.platform != "win32"
    scratch = Path(f"{dst}.partial-{int(time.time())}")
    source = Path(src)
    try:
        entries = fx._entries(source, modes)
        times = file_times(source)
        progress("copying 0%")
        hashes = fx.copy_tree(
            source, scratch, lambda line: progress(line.split(": ", 1)[-1]), "", modes
        )
        if fx._entries(source, modes) != entries or file_times(source) != times:
            raise fx.ExternalError(
                "something changed your things while they were copied"
            )
        progress("checking every file")
        fx.verify_tree(entries, hashes, scratch, modes)
        os.rename(scratch, dst)
    except BaseException:
        if os.path.lexists(scratch):
            fx._remove_scratch(scratch)
        raise


def theme_presets(path: str = os.path.join(SHARED_DIR, "forge_theme.py")) -> list[dict]:
    """forge_theme.SIZE_PRESETS without importing forge_theme (it settles its
    folders at import, which must wait until the place is known)."""
    import ast

    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SIZE_PRESETS" for t in node.targets
        ):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return []
            return [p for p in value if isinstance(p, dict) and p.get("name")]
    return []


def place_look(folder: str) -> tuple[str, str]:
    """The text size preset ("" when none matches) and the look ("dark" or
    "light") a Forge data folder already holds, read from its settings file
    without the theme modules, so the welcome shows what the place has and
    leaves it as it is unless the user picks another."""
    settings = read_json(os.path.join(folder, "config", "settings.json")) or {}
    presets = theme_presets()
    plain = next((p for p in presets if p["name"] == "Default"), {})
    size = ""
    for preset in presets:
        keys = [k for k in preset if k != "name"]
        if all(settings.get(k, plain.get(k)) == preset[k] for k in keys):
            size = preset["name"]
            break
    tid = settings.get("theme")
    theme = None
    if isinstance(tid, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]*", tid):
        theme = read_json(os.path.join(SHARED_DIR, "themes", f"{tid}.json"))
    # as the hub draws it: light panels only with the theme's own colours
    light = (
        theme is not None
        and theme.get("mode") == "light"
        and settings.get("look", theme.get("look")) == theme.get("look")
        and settings.get("theme_source") == "theme"
    )
    return size, "light" if light else "dark"


# -- the system's own folder picker ---------------------------------------------


def picker_commands(system: str, start: str, env=None) -> list[list[str]]:
    """Command lines that show this system's folder picker and print the
    chosen folder, best first (none: the page's typed path is the way)."""
    env = os.environ if env is None else env
    found: list[list[str]] = []
    if system == "windows":
        shell = shutil.which("powershell") or os.path.join(
            env.get("SystemRoot", r"C:\Windows"),
            "System32",
            "WindowsPowerShell",
            "v1.0",
            "powershell.exe",
        )
        if os.path.isfile(shell):
            script = (
                "[Console]::OutputEncoding = [Text.Encoding]::UTF8;"
                " Add-Type -AssemblyName System.Windows.Forms;"
                " $o = New-Object System.Windows.Forms.Form -Property @{TopMost = $true};"
                " $d = New-Object System.Windows.Forms.FolderBrowserDialog;"
                " $d.Description = $env:FORGE_PICK_TITLE;"
                " $d.ShowNewFolderButton = $true;"
                " $d.SelectedPath = $env:FORGE_PICK_START;"
                " if ($d.ShowDialog($o) -eq 'OK') { Write-Output $d.SelectedPath; exit 0 };"
                " exit 1"
            )
            found.append(
                [shell, "-NoProfile", "-NonInteractive", "-STA", "-Command", script]
            )
        return found
    if system == "macos":
        script = 'POSIX path of (choose folder with prompt (system attribute "FORGE_PICK_TITLE"))'
        if os.path.isfile("/usr/bin/osascript"):
            found.append(["/usr/bin/osascript", "-e", script])
        return found
    zenity = shutil.which("zenity")
    kdialog = shutil.which("kdialog")
    lead = start.rstrip("/") + "/"
    commands = []
    if zenity:
        commands.append(
            [
                zenity,
                "--file-selection",
                "--directory",
                f"--title={PICK_TITLE}",
                f"--filename={lead}",
            ]
        )
    if kdialog:
        commands.append(
            [kdialog, "--getexistingdirectory", start, "--title", PICK_TITLE]
        )
    if "kde" in env.get("XDG_CURRENT_DESKTOP", "").lower():
        commands.reverse()
    found.extend(commands)
    python = gtk_python()
    if python:
        found.append([python, os.path.abspath(__file__), "--pick-folder", start])
    return found


def file_times(top: Path) -> dict[str, int]:
    """rel path -> modification time (ns) of every file under top: an app
    still writing during a Move changes one even at the same size."""
    out: dict[str, int] = {}
    for dirpath, _dirs, files in os.walk(top):
        for name in files:
            path = os.path.join(dirpath, name)
            try:
                out[os.path.relpath(path, top)] = os.lstat(path).st_mtime_ns
            except OSError:
                out[os.path.relpath(path, top)] = -1
    return out


def pick_folder(system: str, start: str, run=subprocess.run) -> dict:
    """Show the system's folder picker: {"path": ...}, {"cancelled": True} or
    {"none": True} when this system has none (or it failed)."""
    env = dict(os.environ, FORGE_PICK_TITLE=PICK_TITLE, FORGE_PICK_START=start)
    flags: dict = {}
    if system == "windows":
        flags["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for command in picker_commands(system, start):
        opened = time.monotonic()
        try:
            done = run(
                command,
                capture_output=True,
                timeout=900,
                env=env,
                encoding="utf-8",
                errors="surrogateescape",
                **flags,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        path = (done.stdout or "").strip().splitlines()
        if done.returncode == 0 and path and path[-1].strip():
            return {"path": path[-1].strip()}
        err = (done.stderr or "").strip()
        shown = time.monotonic() - opened > PICKER_SHOWN
        if done.returncode == 1 and (not err or "(-128)" in err or shown):
            return {"cancelled": True}  # closed or Cancel pressed (macOS: -128)
        # anything else: this picker cannot run here; try the next
    return {"none": True}


def gtk_pick_folder(start: str) -> int:
    """--pick-folder: GTK's folder picker (the desktop's own through its
    portal), run by the system Python. Prints the folder; 1 when cancelled."""
    import gi  # type: ignore[import-not-found]

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk  # type: ignore[import-not-found]

    dialog = Gtk.FileChooserNative.new(
        PICK_TITLE, None, Gtk.FileChooserAction.SELECT_FOLDER, "Choose", "Cancel"
    )
    if start and os.path.isdir(start):
        dialog.set_current_folder(start)
    if dialog.run() == Gtk.ResponseType.ACCEPT and dialog.get_filename():
        print(dialog.get_filename(), flush=True)
        return 0
    return 1


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second server bind a port that is in use.
    allow_reuse_address = not forge_core.WINDOWS


# ----------------------------------------------------------------------------
# the launcher: the hub's server, its bridge, and the apps


def key_signature(combo: str) -> str:
    """ "Alt+Shift+M" as hub/portable.js and shared/forge_chrome.js name a key
    press (keySig there): its modifiers in a fixed order, then the key."""
    *mods, key = [part.strip().lower() for part in combo.split("+")]
    key = {
        "left": "arrowleft",
        "right": "arrowright",
        "up": "arrowup",
        "down": "arrowdown",
    }.get(key, key)
    return "+".join([m for m in ("ctrl", "alt", "shift", "meta") if m in mods] + [key])


# forge.py's workspace_shortcut: Ctrl+0 to 9 and Ctrl+Tab, which its window
# catches before the page (Ctrl+R stays the page's own there too)
WORKSPACE_KEYS = {
    "ctrl+0": "home",
    **{f"ctrl+{n}": str(n) for n in range(1, 10)},
    "ctrl+tab": "next",
    "ctrl+shift+tab": "prev",
}


def page_keys(defaults: dict, overrides: dict, skip: frozenset) -> dict[str, str]:
    """Forge's own keys for the pages to catch, {signature: action}: forge.py's
    window catches them before the page, a release's window does not. F1 and
    F11 are left to the page's help and the browser's own full screen."""
    out = dict(WORKSPACE_KEYS)  # critic round G, Relay task 405
    for action, keys in defaults.items():
        if action in skip or action == "help":
            continue
        for combo in str((overrides or {}).get(action) or keys).split(","):
            if combo.strip() and combo.strip().upper() != "F11":
                out[key_signature(combo)] = action
    return out


def cut_actions(status: dict, pages: list[str]) -> None:
    """Take out of the Settings app's search actions ("Wi-Fi", "Sound and
    volume") the ones that open a Settings page this release leaves out,
    so Home search offers no dead end. An action's page is its "page" when
    the hash is an alias the page itself reads (#wallpapers opens the
    Wallpaper page with its browser), else the hash up to the first /."""
    if not pages:
        return
    for info in status.values():
        if info.get("role") == "settings" and info.get("actions"):
            info["actions"] = [
                a
                for a in info["actions"]
                if (a.get("page") or str(a.get("hash", "")).split("/")[0]) not in pages
            ]


class Launcher:
    """The hub's server, its bridge, and the apps. It starts with no apps:
    begin() settles where the user's things are kept (the welcome asks the
    first time; a place that cannot be used shows why), and load() then
    builds the apps on that place. Until then the server answers only the
    welcome and problem pages and what they need."""

    def __init__(
        self,
        profile: Profile,
        local: dict[str, str],
        port: int,
        port_offset: int = 0,
        only: set[str] | None = None,
        log: Callable[[str], None] | None = None,
        system: str | None = None,
    ):
        self.profile = profile
        # the system Forge really runs on (profile.system may be --as-system's)
        self.system = system or forge_core.platform_name()
        self.local = local
        self.dirs = {"root": "", "config": "", "data": ""}
        self.dirs.update({k: local[k] for k in ("cache", "logs", "state")})
        self.port_offset = port_offset
        self.only = only
        self.port = port
        self.origin = f"http://127.0.0.1:{port}"
        self.token = secrets.token_urlsafe(24)
        # File links (wallpapers, music) carry a token of their own: the app
        # backends are handed those links, never the bridge's token.
        self.file_token = secrets.token_urlsafe(24)
        self.done = threading.Event()
        self.ended = False
        self.clients: list[queue.Queue] = []
        self.clients_lock = threading.Lock()
        self.theme_lock = threading.Lock()  # one switcher pick at a time
        self.had_client = False
        self.last_client = time.monotonic()
        self.on_quit: list[Callable[[], None]] = []
        self.window_kind = ""  # "pywebview" once open_native has made one
        self.httpd: Server | None = None
        self._log_file = None
        self.log = log or self._log
        # Where the user's things are kept: "welcome" until a place is
        # chosen, "problem" while the chosen one cannot be used, "moving"
        # during a move, then "ready". `place` is the one in use (root, id,
        # drive); with --data it is this run's only and never remembered.
        self.mode = "welcome"
        self.problem: dict | None = None
        self.place: dict = {}
        self.remember = True
        self.autostart = True
        self.move_state: dict = {}
        saved = read_json(os.path.join(local["state"], LOOK_FILE)) or {}
        self.last_look = "light" if saved.get("look") == "light" else "dark"
        self.look_lock = threading.Lock()  # load and the watch both note it
        self.size_cache: tuple[str, int, int] | None = None
        self.place_lock = threading.RLock()
        self.outer = dict(os.environ)  # before any place's variables are set
        self.theme_module: Any = None
        os.makedirs(local["logs"], exist_ok=True)
        os.environ["FORGE_FILE_BASE"] = (
            f"{self.origin}/forge/file?t={self.file_token}&p="
        )
        os.environ["FORGE_PORTABLE"] = "1"
        os.environ["FORGE_RELEASE"] = profile.version
        if SHARED_DIR not in sys.path:
            sys.path.insert(0, SHARED_DIR)
        self.manager = forge_core.AppManager(
            [], ROOT, log_dir=local["logs"], log=self.log, guard=True
        )

    # -- where the user's things are kept --------------------------------------

    def build(self, dirs: dict[str, str]) -> forge_core.AppManager:
        """The apps, each told where its data goes in the place `dirs`."""
        apps = forge_core.discover_apps(APPS_DIR, self.port_offset, self.log)
        ports = {a.name: a.port for a in apps}
        apps = [
            a
            for a in apps
            if self.profile.includes(a.name)
            and (self.only is None or a.name in self.only)
        ]
        for app in apps:
            app.env = expand_all(
                self.profile.app_env.get(app.name, {}), dirs, ports, self.log
            )
        return forge_core.AppManager(
            apps,
            ROOT,
            log_dir=dirs["logs"],
            env=expand_all(self.profile.env, dirs, ports, self.log),
            on_change=self.status_changed,
            log=self.log,
            guard=True,
            seed_dir=os.path.join(dirs["data"], "seeded"),
        )

    def load(self, root: str, look: tuple | None = None) -> None:
        """Run Forge on the place `root` (a Forge data folder): its settings,
        the apps' data and the seed notes are there. Whatever ran on a place
        before is stopped first. `look` (size, look) is the welcome's choice,
        saved before the place says it is ready: the welcome page goes to the
        hub on that news, and the hub must find the look already there."""
        marker = read_marker(root)
        if marker is None:
            raise OSError(f"{root} holds no Forge data")
        with self.place_lock:
            self.manager.stop_all()
            dirs = place_dirs(self.local, root)
            for key in ("config", "data"):
                os.makedirs(dirs[key], exist_ok=True)
            # before the theme modules are read: they settle folders at import
            os.environ.update(theme_environment(dirs, self.outer))
            # Read them again when anything imported them before this place
            # was set (a second place, or send_file's forge_music in the
            # welcome): else they keep ~/.config/forge and ~/.cache/forge.
            stale = any(sys.modules.get(n) for n in THEME_MODULES)
            import forge_lock
            import forge_theme
            import forge_themes

            if stale:
                for module in (forge_lock, forge_themes, forge_theme):
                    importlib.reload(module)
            self.theme_module = forge_theme
            os.environ["FORGE_CUT_SETTINGS"] = ",".join(
                self.profile.settings_to_cut(forge_theme.SETTINGS)
            )
            os.environ["FORGE_CUT_PAGES"] = ",".join(self.profile.cut_pages)
            os.environ["FORGE_CUT_RESETS"] = ",".join(self.profile.cut_resets)
            os.environ["FORGE_SETTING_WORDS"] = json.dumps(self.profile.setting_words)
            os.environ["FORGE_RESET_WORDS"] = json.dumps(self.profile.reset_words)
            self.manager = self.build(dirs)
            self.dirs = dirs
            drive = drive_of(root, self.system)
            self.place = {"root": root, "id": marker["id"], "drive": drive}
            self.problem = None
            self.size_cache = None
            self.mode = "ready"
            if look is not None:
                self.save_look(*look)
            self.keep_look(self.look_now()[1])
        self.log(f"[forge] your things are kept in {root}")
        if self.autostart:
            self.start_launch_apps()
        self.status_changed()
        self.push("place", self.place_state())

    def begin(self, data: str | None = None, smoke: bool = False) -> None:
        """Settle the place at start: `data` (--data) for this run only; else
        the one the pointer file names, checked; else, for --smoke, this
        computer's for this run; else the welcome asks (mode "welcome")."""
        self.autostart = not smoke
        computer = os.path.join(self.local["computer"], PLACE_NAME)
        if data or (smoke and not os.path.isfile(self.local["pointer"])):
            self.remember = False
            folder = os.path.abspath(os.path.expanduser(data or computer))
            os.makedirs(os.path.dirname(folder), exist_ok=True)
            make_place(folder, self.profile.version)
            self.load(folder)
            return
        if os.path.isfile(self.local["pointer"]):
            self.recheck()
            return
        self.mode = "welcome"
        self.log("[forge] first start: the welcome asks where your things go")

    def recheck(self, allow_full: bool = False) -> dict | None:
        """Check the remembered place (or this run's) and use it, or show why
        it cannot be used. A drive that came back under another name (another
        letter, another mount folder) is found by its folder and id."""
        with self.place_lock:
            if self.remember:
                pointer = read_json(self.local["pointer"]) or {}
            else:
                pointer = dict(self.place)
            root = str(pointer.get("root") or "")
            want = str(pointer.get("id") or "")
            if not root or not want:
                self.manager.stop_all()
                self.problem, self.mode = None, "welcome"
                self.log("[forge] where.json is damaged: the welcome asks again")
                self.push("place", self.place_state())
                return None
            drive = (
                pointer.get("drive") if isinstance(pointer.get("drive"), dict) else {}
            )
            problem = place_problem(root, want, drive)
            if problem and problem["why"] in ("missing", "empty"):
                moved = find_moved(pointer, self.system)
                marker = read_marker(moved) if moved else None
                if moved and marker:
                    self.log(f"[forge] your things turned up at {moved}")
                    pointer = pointer_for(moved, marker, self.system)
                    if self.remember:
                        write_json(self.local["pointer"], pointer)
                    root = moved
                    problem = place_problem(moved, want, pointer["drive"])
            if problem and problem["why"] == "full" and allow_full:
                problem = None
            if problem is None:
                self.load(root)
                return None
            self.manager.stop_all()
            self.problem, self.mode = problem, "problem"
            self.place = {"root": root, "id": want, "drive": drive}
        self.log(f"[forge] your things cannot be used now: {problem['why']} ({root})")
        self.push("place", self.place_state())
        return problem

    def watch_place(self) -> None:
        """Every few seconds: a place in use that went away (a drive pulled
        out) stops every app and shows why; one that came back is used
        again."""
        while not self.done.wait(WATCH_SECONDS):
            try:
                self.watch_once()
            except Exception as e:
                self.log(f"[forge] the place was not checked ({e})")

    def watch_once(self) -> None:
        if self.mode == "ready" and self.place.get("root"):
            # read before the marker: a place pulled out between the two
            # reads the default look, which the marker check then drops
            look = self.look_now()[1]
            marker = read_marker(self.place["root"])
            if marker is not None and marker["id"] == self.place.get("id"):
                # a Move that began meanwhile made look_now say "dark"
                if self.mode == "ready":
                    self.keep_look(look)  # a look changed in Settings
                return
            with self.place_lock:
                if self.mode != "ready":
                    return
                self.manager.stop_all()
                drive = self.place.get("drive") or {}
                self.problem = {
                    "root": self.place["root"],
                    "why": "gone",
                    "drive": drive.get("name") or "",
                    "removable": bool(drive.get("removable")),
                }
                self.mode = "problem"
            self.log(
                f"[forge] {self.place['root']} went away while Forge ran:"
                " every app stopped"
            )
            self.status_changed()
            self.push("place", self.place_state())
        elif self.mode == "problem" and (self.problem or {}).get("why") in (
            "missing",
            "empty",
            "gone",
        ):
            self.recheck()

    def place_state(self) -> dict:
        """What the welcome, problem and data pages show."""
        computer = os.path.join(self.local["computer"], PLACE_NAME)
        try:  # Forge's own folder: the "On this computer" choice needs it
            os.makedirs(self.local["computer"], exist_ok=True)
        except OSError:
            pass  # check_place then says why that place cannot be used
        free = free_space(computer)
        out: dict = {
            "mode": self.mode,
            "system": self.system,
            "version": self.profile.version,
            "remember": self.remember,
            "problem": self.problem,
            "computer": computer,
            "computer_free": size_text(free),
            "home": os.path.expanduser("~"),
            "sep": os.sep,
            "name": PLACE_NAME,
            "move": dict(self.move_state),
            "place": None,
            "presets": theme_presets(),
        }
        out["size"], out["look"] = self.look_now()
        if self.mode == "problem":
            out["look"] = self.last_look
        root = self.place.get("root") or ""
        if root and self.mode in ("ready", "moving"):
            drive = self.place.get("drive") or {}
            free = free_space(root)
            out["place"] = {
                "root": root,
                "drive": drive.get("name") or "this computer",
                "removable": bool(drive.get("removable")),
                "fs": drive.get("fs") or "",
                "free": free,
                "free_text": size_text(free),
                "on_computer": same_or_inside(root, self.local["computer"]),
            }
        return out

    def size_now(self) -> tuple[int, int]:
        root = self.dirs["root"]
        if not self.size_cache or self.size_cache[0] != root:
            size, files = place_size(root)
            self.size_cache = (root, size, files)
        return self.size_cache[1], self.size_cache[2]

    def look_now(self) -> tuple[str, str]:
        """The text size preset ("" when none matches) and the look ("dark"
        or "light") of the place in use, for the welcome again."""
        if self.theme_module is None or self.mode != "ready":
            return "Default", "dark"
        try:
            import forge_themes

            settings = self.theme_module.load()
            theme = forge_themes.active_theme(settings)
        except Exception:
            return "Default", "dark"
        look = "light" if theme and theme.get("mode") == "light" else "dark"
        for preset in getattr(self.theme_module, "SIZE_PRESETS", []):
            keys = [k for k in preset if k != "name"]
            if all(settings.get(k) == preset[k] for k in keys):
                return preset["name"], look
        return "", look

    def keep_look(self, look: str) -> None:
        """Note the look of the place in use, so the problem screen draws in
        it when that place is gone (task 405 left those screens dark after
        Light). Remembered on this computer unless the run has --data."""
        with self.look_lock:
            if look == self.last_look:
                return
            self.last_look = look
            if not self.remember:
                return
            try:
                write_json(os.path.join(self.local["state"], LOOK_FILE), {"look": look})
            except OSError as e:
                self.log(f"[forge] the look was not noted ({e})")

    def save_look(self, size, look) -> None:
        """The text size preset and the look the welcome's last step chose.
        Light puts on Forge's light theme; dark puts Forge's own back only
        when the light one was on, so a first start keeps the plain look."""
        if self.theme_module is None:
            return
        for preset in getattr(self.theme_module, "SIZE_PRESETS", []):
            if isinstance(size, str) and preset.get("name") == size:
                values = {k: v for k, v in preset.items() if k != "name"}
                forge_core.save_hub_settings(values, self.theme_module)
        if look not in LOOK_THEMES or self.look_now()[1] == look:
            return
        try:
            import forge_themes

            theme = forge_themes.get_theme(LOOK_THEMES[look])
            if theme is not None:
                changes = forge_themes.theme_changes(theme, self.theme_module.SETTINGS)
                self.theme_module.save(changes)
        except Exception as e:  # a locked look (Business), a folder not written
            self.log(f"[forge] the {look} look was not saved ({e})")

    def place_action(self, req: dict) -> dict:
        """One request from the welcome, problem or data page (POST
        /forge/place): {"do": what, ...}."""
        do = req.get("do")
        given = req.get("path")
        path = given if isinstance(given, str) else ""
        busy = {"ok": False, "problem": "Forge is moving your things now."}
        if do == "state":
            return self.place_state()
        if do == "drives":
            return {"drives": drives(self.system)}
        if do == "check":
            if req.get("move"):
                if self.mode != "ready":
                    return busy
                size = self.size_now()[0]
                return check_place(path, self.system, self.dirs["root"], size)
            return check_place(path, self.system)
        if do == "pick":
            start = path if os.path.isdir(path) else os.path.expanduser("~")
            return pick_folder(self.system, start)
        if do == "use":
            with self.place_lock:
                if self.mode in ("ready", "moving"):
                    return {
                        "ok": False,
                        "problem": "Forge has a place already. Move changes it.",
                    }
                result = check_place(path, self.system)
                if not result["ok"]:
                    return result
                folder = result["folder"]
                try:
                    marker = make_place(folder, self.profile.version)
                    write_json(
                        self.local["pointer"],
                        pointer_for(folder, marker, self.system),
                    )
                except OSError as e:
                    result.update(
                        ok=False, problem=f"Forge could not write there ({e})."
                    )
                    return result
                self.remember = True
                self.load(folder, (req.get("size"), req.get("look")))
            return {"ok": True, "go": "/hub/index.html"}
        if do == "done":  # the welcome run again, with a place in use
            if self.mode != "ready":
                return busy
            self.save_look(req.get("size"), req.get("look"))
            return {"ok": True, "go": "/hub/index.html"}
        if do in ("retry", "anyway"):
            if self.mode != "problem":
                return {"ok": self.mode == "ready", "mode": self.mode}
            problem = self.recheck(allow_full=do == "anyway")
            return {"ok": problem is None, "problem": problem}
        if do == "adopt":  # the folder holds other Forge data: use that
            with self.place_lock:
                problem = self.problem or {}
                if self.mode != "problem" or problem.get("why") != "other":
                    return {"ok": False, "mode": self.mode}
                root = problem["root"]
                marker = read_marker(root)
                if marker is None:
                    return {"ok": False, "problem": f"{root} holds no Forge data now."}
                pointer = pointer_for(root, marker, self.system)
                if self.remember:
                    write_json(self.local["pointer"], pointer)
                else:
                    self.place = pointer
            problem = self.recheck()
            return {"ok": problem is None, "problem": problem}
        if do == "size":
            if self.mode != "ready":
                return {"ok": False}
            size, files = self.size_now()
            return {"ok": True, "bytes": size, "files": files, "text": size_text(size)}
        if do == "move":
            return self.start_move(path)
        if do == "quit":
            threading.Thread(target=self.quit, daemon=True).start()
            return {"ok": True}
        return {"ok": False, "problem": "unknown request"}

    def start_move(self, path: str) -> dict:
        with self.place_lock:
            if self.mode != "ready":
                return {
                    "ok": False,
                    "problem": "Forge is not ready to move your things.",
                }
            if not self.remember:
                return {
                    "ok": False,
                    "problem": "This Forge was started with --data, for this run only.",
                }
            size = self.size_now()[0]
            result = check_place(path, self.system, self.dirs["root"], size)
            if not result["ok"]:
                return result
            self.mode = "moving"
            self.move_state = {
                "phase": "stopping",
                "text": "Stopping every app",
                "from": self.dirs["root"],
                "to": result["folder"],
                "bytes": size,
            }
        fs = (result.get("drive") or {}).get("fs") or ""
        threading.Thread(
            target=self.move, args=(result["folder"], fs), daemon=True, name="move"
        ).start()
        self.push("place", self.place_state())
        return {"ok": True, "started": True}

    def move(self, dst: str, fs: str) -> None:
        """Move the place in use to dst: stop every app, copy and check every
        file, repoint the paths apps saved, switch the pointer, and keep the
        old folder as "<name> (old copy, <date>)". On any failure the copy
        is removed and Forge goes on where it was."""
        src = self.dirs["root"]
        state = self.move_state

        def progress(text: str) -> None:
            state["text"] = text

        try:
            self.manager.stop_all()
            state.update(phase="copying", text="Copying")
            copy_place(src, dst, fs, progress)
            state.update(phase="switching", text="Switching over")
            repoint(os.path.join(dst, "config"), src, dst)
            marker = read_marker(dst)
            if marker is None:
                raise OSError(f"{dst} holds no Forge data after the copy")
            write_json(self.local["pointer"], pointer_for(dst, marker, self.system))
        except Exception as e:
            self.log(f"[forge] moving your things to {dst} failed: {e}")
            text = f"The move failed: {e}"
            if os.path.isdir(dst) and read_marker(dst) is not None:
                # the pointer was not switched: the copy is not the one in use
                shutil.rmtree(dst, ignore_errors=True)
                if os.path.lexists(dst):
                    self.mark_old(dst, src)
                    text += f". A copy is left at {dst}: delete it yourself"
            state.update(phase="failed", text=text, error=str(e))
            self.mode = "problem"  # reload() makes it ready again
            self.reload(src)
            return
        old = old_copy_name(src)
        try:
            os.rename(src, old)
        except OSError as e:
            self.log(f"[forge] the old copy keeps its name ({e})")
            old = src
        self.mark_old(old, dst)
        state.update(phase="done", text="Done", old=old)
        self.log(f"[forge] your things moved to {dst}; the old copy is {old}")
        self.reload(dst)

    def reload(self, root: str) -> None:
        """Carry on from root after a Move; when that fails (a drive pulled
        just then) the remembered place is checked as at a start, so the
        problem screen says why and Forge carries on when it is back."""
        try:
            self.load(root)
        except Exception as e:
            self.log(f"[forge] {root} cannot be used now ({e})")
            if not self.remember:  # a --data run: check the new root
                self.place = dict(self.place, root=root)
            self.recheck()

    def mark_old(self, folder: str, moved_to: str) -> None:
        """Note in a copy's marker that it is not the one in use."""
        marker = read_marker(folder)
        if marker is None:
            return
        marker["old_copy"] = {"date": today(), "moved_to": moved_to}
        try:
            write_json(os.path.join(folder, MARKER), marker)
        except OSError as e:
            self.log(f"[forge] {folder} not marked as an old copy ({e})")

    # -- logging ---------------------------------------------------------------

    def _log(self, line: str) -> None:
        try:
            print(line, flush=True)
        except (OSError, ValueError):
            pass  # no console (pythonw on Windows)
        try:
            if self._log_file is None:
                path = os.path.join(self.dirs["logs"], "forge.log")
                self._log_file = open(path, "a", encoding="utf-8")
            self._log_file.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
            self._log_file.flush()
        except OSError:
            pass

    # -- the server ------------------------------------------------------------

    def url(self, path: str = "/hub/index.html") -> str:
        return self.origin + path

    def serve(self) -> None:
        self.httpd = Server(("127.0.0.1", self.port), make_handler(self))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        threading.Thread(target=self.watch_place, daemon=True, name="place").start()
        if self.profile.features.get("stats") in ("native", "replaced"):
            threading.Thread(target=self.stats_loop, daemon=True, name="stats").start()
        self.log(f"[forge] Forge {self.profile.version} on {self.url()}")

    def start_launch_apps(self) -> None:
        """Apps whose manifest says start_at_launch; the rest start when opened."""
        for app in self.manager.apps.values():
            if app.start_at_launch:
                self.manager.start_async(app.name)

    def close(self) -> None:
        """Stop every app and the server. Safe to call more than once."""
        self.quit()
        self.manager.stop_all()
        if self.httpd is not None:
            httpd, self.httpd = self.httpd, None
            httpd.shutdown()
            httpd.server_close()
        self.log("[forge] stopped")

    def quit(self) -> None:
        """End Forge: tell the pages, close the windows, let main() finish."""
        with self.clients_lock:
            if self.ended:
                return
            self.ended = True
        self.push("quit", {})
        time.sleep(0.2)  # the event reaches the pages before they are cut off
        self.done.set()
        if "forge_ask" in sys.modules:  # the smart search's Jan model, if loaded
            try:
                sys.modules["forge_ask"].shutdown()
            except Exception as e:  # noqa: BLE001 -- quitting goes on
                self.log(f"[forge] releasing the ask model failed ({e})")
        for close in list(self.on_quit):
            try:
                close()
            except Exception as e:
                self.log(f"[forge] closing a window failed ({e})")

    def host_ok(self, handler: BaseHTTPRequestHandler) -> bool:
        host = (handler.headers.get("Host") or "").strip().lower()
        return host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    def token_ok(self, given: str, files: bool = False) -> bool:
        want = self.file_token if files else self.token
        return secrets.compare_digest(given.encode(), want.encode())

    def get(self, h: BaseHTTPRequestHandler, body: bool = True) -> None:
        if not self.host_ok(h):
            return send(h, 403, b"Forge answers only to this machine.", body=body)
        parts = urlsplit(h.path)
        path = clean_path(unquote(parts.path))
        query = parse_qs(parts.query)
        token = (query.get("t") or [""])[0]
        if path in ("/", "/index.html", "/hub", "/hub/"):
            return redirect(h, "/hub/index.html")
        if path == "/hub/index.html":
            if self.mode != "ready":  # no place yet, or it cannot be used
                return redirect(h, "/hub/welcome.html")
            return send(h, 200, self.hub_page(), TYPES[".html"], body=body)
        if path in PLACE_PAGES:
            if path == "/hub/data.html" and self.mode not in ("ready", "moving"):
                return redirect(h, "/hub/welcome.html")
            return send(h, 200, self.place_page(path), TYPES[".html"], body=body)
        if path in TOKEN_SCRIPTS and not self.token_ok(token):
            return send(h, 403, b"Wrong or missing token.", body=body)
        if path == "/hub/status.js":
            return send(h, 200, self.status_js().encode(), TYPES[".js"], body=body)
        if path == "/hub/theme.js":
            return send(h, 200, self.theme_js().encode(), TYPES[".js"], body=body)
        if path == "/forge/ping":
            data = {"forge": True, "version": self.profile.version}
            return send(h, 200, json.dumps(data).encode(), TYPES[".json"], body=body)
        files = path in ("/forge/file", "/forge/track")
        if path.startswith("/forge/") and not self.token_ok(token, files):
            return send(h, 403, b"Wrong or missing token.", body=body)
        if path == "/forge/events":
            return self.events(h)
        if path == "/forge/place":
            data = json.dumps(self.place_state()).encode()
            return send(h, 200, data, TYPES[".json"], body=body)
        if path == "/forge/file":
            return self.send_allowed(h, (query.get("p") or [""])[0], body)
        if path == "/forge/track":
            return self.send_track(h, (query.get("u") or [""])[0], body)
        if path == "/favicon.ico":  # what a browser asks for by itself
            icon = os.path.join(ROOT, "assets", "icon.png")
            if os.path.isfile(icon):
                return send_file(h, icon, body=body)
        for prefix, root in (("/hub/", HUB_DIR), ("/shared/", SHARED_DIR)):
            if path.startswith(prefix):
                found = inside(root, path[len(prefix) :])
                name = os.path.basename(found or "").lower()
                if found and not (root == HUB_DIR and name in GENERATED):
                    return send_file(h, found, body=body)
        return send(h, 404, b"Not found.", body=body)

    def post(self, h: BaseHTTPRequestHandler) -> None:
        if not self.host_ok(h):
            return send(h, 403, b"Forge answers only to this machine.")
        route = urlsplit(h.path).path
        if route not in ("/forge/bridge", "/forge/place"):
            return send(h, 404, b"Not found.")
        origin = h.headers.get("Origin")
        if origin is not None and origin not in (
            self.origin,
            f"http://localhost:{self.port}",
        ):
            return send(h, 403, b"Another page may not use Forge's bridge.")
        if not self.token_ok(h.headers.get("X-Forge") or ""):
            return send(h, 403, b"Wrong or missing token.")
        try:
            length = int(h.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= 1_000_000:
            return send(h, 413, b"Too large.")
        try:
            request = json.loads(h.rfile.read(length) or b"null")
        except ValueError:
            return send(h, 400, b"Not JSON.")
        if route == "/forge/place":
            answer = self.place_action(request if isinstance(request, dict) else {})
            return send(h, 200, json.dumps(answer).encode(), TYPES[".json"])
        what = self.handle(request)
        send(h, 200, json.dumps({"done": what}).encode(), TYPES[".json"])

    # -- what the hub is given -------------------------------------------------

    def hub_page(self) -> bytes:
        """hub/index.html as forge.py's window shows it, with the bridge swapped
        for hub/portable.js and that script's settings put in front of it."""
        with open(os.path.join(HUB_DIR, "index.html"), encoding="utf-8") as f:
            text = f.read()
        text = text.replace(WEBKIT_BRIDGE, PORTABLE_BRIDGE)
        for path in TOKEN_SCRIPTS:
            name = path.rsplit("/", 1)[1]
            text = text.replace(f'src="{name}"', f'src="{name}?t={self.token}"')
        config = {
            "token": self.token,
            "system": self.profile.system,
            "version": self.profile.version,
            "hide": self.profile.hide,
            "widgets": self.profile.cut_widgets,
            "features": self.profile.features,
            # pywebview windows refuse window.open: the launcher pops apps out
            "popout": "launcher" if self.window_kind == "pywebview" else "page",
        }
        data = json.dumps(config).replace("</", "<\\/")
        inject = (
            f"<script>window.FORGE_PORTABLE = {data};</script>\n"
            '<script src="portable.js"></script>\n'
        )
        at = text.find("<script")
        text = text[:at] + inject + text[at:] if at >= 0 else text + inject
        return text.encode("utf-8")

    def place_page(self, path: str) -> bytes:
        """hub/welcome.html or hub/data.html, with the token and system their
        scripts need put in front of them."""
        with open(os.path.join(HUB_DIR, path.rsplit("/", 1)[1]), encoding="utf-8") as f:
            text = f.read()
        config = {
            "token": self.token,
            "system": self.system,
            "version": self.profile.version,
        }
        data = json.dumps(config).replace("</", "<\\/")
        inject = f"<script>window.FORGE_PLACE = {data};</script>\n"
        at = text.find("<script")
        text = text[:at] + inject + text[at:] if at >= 0 else text + inject
        return text.encode("utf-8")

    def groups(self) -> dict:
        """The groups that have members, in this release's words."""
        groups = forge_core.attach_groups(
            list(self.manager.apps.values()),
            forge_core.discover_groups(GROUPS_DIR, self.log),
        )
        for name, words in self.profile.group_words.items():
            if name in groups:
                groups[name].update(words)
        return groups

    def status(self, groups: dict | None = None) -> dict:
        """The apps' status as the hub gets it, the same in status.js and in
        the event stream (critic round E2, Relay task 405: the stream sent the
        uncut snapshot, so Home search offered Wi-Fi again)."""
        status = self.manager.snapshot()
        cut_actions(status, self.profile.cut_pages)
        # the hub reads an app's group from its status, which must say the
        # group that took it in, whether by its own line or the group's list
        for gid, g in (self.groups() if groups is None else groups).items():
            for name in g["members"]:
                if name in status:
                    status[name]["group"] = gid
        return status

    def status_js(self) -> str:
        """What forge.py writes to hub/status.js: the apps, the groups that have
        members, and the home screen's sections."""
        groups = self.groups()
        sections = forge_core.discover_sections(SECTIONS_DIR, self.log)
        for name, words in self.profile.sections.items():
            if name in sections:
                sections[name].update(words)
        status = self.status(groups)
        return (
            f"window.FORGE_STATUS = {json.dumps(status)};\n"
            f"window.FORGE_GROUPS = {json.dumps(groups)};\n"
            f"window.FORGE_SECTIONS = {json.dumps(sections)};\n"
        )

    def theme_data(self) -> dict:
        try:
            data = self.theme_module.theme() if self.theme_module else {}
        except Exception as e:
            self.log(f"[forge] theme not made, using the plain look ({e})")
            data = {}
        data.update(self.profile.theme)
        if self.theme_module and "hub_keys" in data:
            skip = frozenset(self.profile.cut_key_actions)
            data["hub_key_list"] = self.theme_module.hub_key_list(
                data["hub_keys"], skip
            )
            if self.profile.page_keys:
                data["page_keys"] = page_keys(
                    self.theme_module.HUB_KEYS, data["hub_keys"], skip
                )
        return data

    def theme_js(self) -> str:
        return f"window.FORGE_THEME = {json.dumps(self.theme_data())};\n"

    # -- the bridge: what forge.py's on_page_message does ---------------------

    def ask(self, req: dict) -> None:
        import forge_ask

        try:
            answer = forge_ask.answer(req)
        except Exception as e:  # noqa: BLE001 -- the hub waits on an answer
            answer = {"id": req.get("id"), "kind": "error", "text": f"search: {e}"}
        self.push("ask", answer)

    def handle(self, request) -> str:
        """Carry out one message from the page; returns what was done (for the
        log and the tests). Messages for a feature this launcher does not have
        (snapshots, key tables, power, web views, the PS5 pad, zoom) are
        ignored, as forge.py ignores what it does not know."""
        if not isinstance(request, dict):
            return "ignored"
        if self.mode != "ready" and request.get("forge") != "quit":
            return "not ready"  # no place yet, a problem shown, or a move
        if isinstance(request.get("settings"), dict):
            saved = forge_core.save_hub_settings(request["settings"], self.theme_module)
            return "settings" if saved else "ignored"
        if isinstance(request.get("music"), dict):
            return self.music(request["music"])
        if any(
            k in request
            for k in (
                "theme_pick",
                "layout_pick",
                "forge_layout_pick",
                "theme_next",
                "theme_undo",
            )
        ):
            # Alt+T's switcher, as forge.py's theme_request; the wallpaper's
            # colours take a moment, so off this thread, then back to the hub
            # (critic round G, Relay task 405: a release ignored these)
            threading.Thread(
                target=self.theme_pick, args=(request,), daemon=True
            ).start()
            return "theme"
        if isinstance(request.get("ask"), dict):
            # The smart search (shared/forge_ask.py): rules, web or a model,
            # off this thread as forge.py does; the answer goes back as "ask".
            threading.Thread(
                target=self.ask, args=(request["ask"],), daemon=True
            ).start()
            return "ask"
        if isinstance(request.get("media"), dict):
            # Other players on the desktop (MPRIS) are Linux D-Bus: none here.
            self.push("media", [])
            return "media"
        if request.get("forge") == "quit":
            threading.Thread(target=self.quit, daemon=True).start()
            return "quit"
        popped = request.get("popout")
        if isinstance(popped, str):
            if popped not in self.manager.apps:
                return "unknown"
            if self.window_kind != "pywebview":
                return "ignored"  # the page opens its own windows
            self.manager.start_async(popped)
            threading.Thread(target=self.popout, args=(popped,), daemon=True).start()
            return "popout"
        name, closing = request.get("start"), request.get("stop")
        if isinstance(name, str):
            if name not in self.manager.apps:
                return "unknown"
            return "start" if self.manager.start_async(name) else "running"
        if isinstance(closing, str):
            if closing not in self.manager.apps:
                return "unknown"
            threading.Thread(
                target=self.manager.stop, args=(closing,), daemon=True
            ).start()
            return "stop"
        return "ignored"

    def theme_pick(self, request: dict) -> dict:
        """Pick a theme or home layout, step to the next theme, or undo the
        last pick, saved in the place through shared/forge_themes.py (so the
        Business lock still guards it); pushes {"theme": the hub's theme data}
        or {"error": text} as "theme_picked" and returns it."""
        import forge_lock
        import forge_themes

        with self.theme_lock:
            try:
                if request.get("theme_undo"):
                    forge_themes.undo()
                elif "layout_pick" in request:
                    forge_themes.pick_layout(str(request["layout_pick"]))
                elif "forge_layout_pick" in request:
                    forge_themes.pick_forge_layout(str(request["forge_layout_pick"]))
                elif request.get("theme_next"):
                    now = forge_themes._ft().load()
                    forge_themes.pick(forge_themes.next_theme(now))
                else:
                    forge_themes.pick(str(request.get("theme_pick")))
                answer: dict = {"theme": self.theme_data()}
            except KeyError:
                answer = {"error": "That theme or layout is not there any more."}
            except forge_lock.Locked as error:
                answer = {"error": str(error) or "The look is locked."}
        self.push("theme_picked", answer)
        return answer

    def popout(self, name: str) -> None:
        """An app in a pywebview window of its own, once its backend is up."""
        import webview  # type: ignore[import-not-found]  # pywebview

        def create(title: str, url: str):
            return webview.create_window(
                title,
                url,
                width=WINDOW_SIZE[0],
                height=WINDOW_SIZE[1],
                min_size=(640, 480),
            )

        window = open_when_up(self.manager.apps[name], create, self.done)
        if window is not None:
            self.on_quit.append(window.destroy)

    def music_folder(self) -> Path:
        if self.theme_module is None:
            return Path(os.path.expanduser("~/Music"))
        folder = self.theme_module.load()["music_folder"]
        return Path(os.path.expanduser(folder or "~/Music"))

    def music(self, req: dict) -> str:
        """The hub's music panel: its track list, its folder, and where Web
        Audio can read the tracks from. Adding a YouTube link (yt-dlp) and the
        system sound levels (cava) are cut in a release."""
        op = req.get("op")
        if op == "serve":
            base = f"{self.origin}/forge/track?t={self.file_token}&u="
            self.push("music", {"type": "serve", "base": base})
            return "serve"
        if op == "tracks":
            folder = str(self.music_folder())
            self.push(
                "music",
                {
                    "type": "tracks",
                    "tracks": self.theme_module.music_tracks(folder),
                    "note": self.theme_module.music_note(folder),
                },
            )
            return "tracks"
        if op == "folder":
            folder = self.music_folder()
            folder.mkdir(parents=True, exist_ok=True)
            self.push("music", {"type": "folder", "path": str(folder)})
            return "folder"
        if op == "levels" and req.get("on"):
            self.push("music", {"type": "levels-off", "reason": "not in a release"})
        return "cut"

    # -- files: wallpapers, their cached copies, music -------------------------

    def file_roots(self) -> list[tuple[Path, set[str] | None]]:
        """Where pages may read files from, each with the kinds of file it
        gives out (None: any): Forge's own cache, then pictures only from the
        wallpaper folder and the chosen wallpaper, and music only from the
        music folder (a folder setting cannot open up a whole home folder)."""
        ft = self.theme_module
        if ft is None:
            return []
        pictures = set(ft.IMAGE_TYPES) | WALLPAPER_VIDEO
        music = set(getattr(ft, "MUSIC_TYPES", set()))
        roots: list[tuple[Path, set[str] | None]] = [
            (Path(ft.CACHE), None),
            (Path(ft.WALLPAPER_DIR), pictures),
            (self.music_folder(), music),
        ]
        try:
            wallpaper = ft.chosen_wallpaper(ft.load())
        except Exception:
            wallpaper = None
        if wallpaper is not None:
            roots.append((Path(wallpaper), pictures))
        out = []
        for root, kinds in roots:
            try:
                out.append((root.expanduser().resolve(), kinds))
            except OSError:
                continue
        return out

    def allowed_file(self, raw: str) -> Path | None:
        # Network shares are never contacted (Windows would send its login).
        if not raw or raw.replace("\\", "/").startswith("//"):
            return None
        try:
            path = Path(raw).expanduser().resolve()
        except (OSError, ValueError):
            return None
        for root, kinds in self.file_roots():
            if not under(path, [root]):
                continue
            if kinds is None or path.suffix.lower() in kinds:
                return path if path.is_file() else None
        return None

    def send_allowed(self, h: BaseHTTPRequestHandler, raw: str, body: bool) -> None:
        path = self.allowed_file(raw)
        if path is None:
            return send(h, 404, b"Not found.", body=body)
        send_file(h, str(path), body=body, cors=True)

    def send_track(self, h: BaseHTTPRequestHandler, link: str, body: bool) -> None:
        """A music track for the hub's Web Audio: `link` is the track's own
        address as the theme gave it (/forge/file?...&p=<path>) or a file://
        link; only a playable file inside the music folder is sent."""
        parts = urlsplit(link)
        if parts.scheme == "file" and parts.netloc not in ("", "localhost"):
            return send(h, 404, b"Not found.", body=body)
        if parts.scheme == "file":
            raw = unquote(parts.path)
            if forge_core.WINDOWS and raw[:1] == "/" and raw[2:3] == ":":
                raw = raw[1:]  # /C:/Users/... -> C:/Users/...
        elif parts.path == "/forge/file":
            raw = (parse_qs(parts.query).get("p") or [""])[0]
        else:
            return send(h, 404, b"Not found.", body=body)
        path = self.allowed_file(raw)
        types = getattr(self.theme_module, "MUSIC_TYPES", set())
        try:
            folder = self.music_folder().resolve()
        except OSError:
            folder = None
        if (
            path is None
            or folder is None
            or folder not in path.parents
            or path.suffix.lower() not in types
        ):
            return send(h, 404, b"Not found.", body=body)
        send_file(h, str(path), body=body, cors=True)

    # -- the system numbers for the top bar and the home widgets ----------------

    def read_stats(self, state: dict) -> dict:
        """What forge.py's StatsPump sends (shared/forge_sysinfo.py): CPU,
        memory and battery each time, the network speed where the registry
        keeps the Network widget, and every 30 s the drives (and on Linux Jan
        and the temperatures). `state` carries the samples between calls."""
        import forge_sysinfo

        top, state["sample"] = forge_sysinfo.system_stats(state.get("sample"))
        stats: dict = dict(top)
        if self.profile.features.get("net_and_jan") in ("native", "replaced"):
            if "net" not in state:
                state["net"] = forge_sysinfo.NetMeter()
            stats["net"] = state["net"].read()
        if time.monotonic() - state.get("slow_at", -1e9) > 30:
            state["slow_at"] = time.monotonic()
            slow: dict = {"disks": forge_sysinfo.disks()}
            if self.profile.system == "linux":
                slow["jan"] = forge_sysinfo.jan_status()
                slow["temps"] = forge_sysinfo.temperatures()
            state["slow"] = slow
        stats.update(state["slow"])
        return stats

    def stats_loop(self) -> None:
        """While a page is open, the numbers go out every STATS_SECONDS as a
        "stats" event, which hub/portable.js hands to window.forgeSetStats as
        forge.py does. A failing read is logged once and tried again."""
        state: dict = {}
        failed = False
        while not self.done.wait(STATS_SECONDS):
            with self.clients_lock:
                listening = bool(self.clients)
            if not listening and "sample" in state:
                continue
            try:
                stats = self.read_stats(state)  # the first read primes the CPU
                if listening:
                    self.push("stats", stats)
                failed = False
            except Exception as e:
                if not failed:
                    self.log(f"[forge] system numbers not read ({e})")
                failed = True

    # -- events to the pages ---------------------------------------------------

    def push(self, name: str, data) -> None:
        with self.clients_lock:
            for q in self.clients:
                try:
                    q.put_nowait((name, data))
                except queue.Full:
                    pass  # a page that stopped reading misses events

    def status_changed(self) -> None:
        self.push("status", self.status())

    def events(self, h: BaseHTTPRequestHandler) -> None:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self.clients_lock:
            self.clients.append(q)
            self.had_client = True
        try:
            h.send_response(200)
            h.send_header("Content-Type", "text/event-stream; charset=utf-8")
            h.send_header("Cache-Control", "no-store")
            h.end_headers()
            write_event(h, "status", self.status())
            while True:
                try:
                    name, data = q.get(timeout=PING_SECONDS)
                except queue.Empty:
                    if self.done.is_set():
                        break
                    h.wfile.write(b": ping\n\n")
                    h.wfile.flush()
                    continue
                write_event(h, name, data)
                if name == "quit":
                    break
        except OSError:
            pass  # the page went away
        finally:
            with self.clients_lock:
                self.clients.remove(q)
                self.last_client = time.monotonic()

    def pages(self) -> int:
        with self.clients_lock:
            return len(self.clients)

    def wait_for_pages(self) -> None:
        """Until Forge quits, or no page has been open for IDLE_GRACE seconds
        after one was: how a window this launcher does not own is followed."""
        while not self.done.wait(1.0):
            idle = time.monotonic() - self.last_client
            if self.had_client and self.pages() == 0 and idle > IDLE_GRACE:
                self.log("[forge] the Forge window was closed")
                return

    # -- the smoke check -------------------------------------------------------

    @staticmethod
    def missing(html: str, base: str, origin: str = "") -> tuple[bool, str]:
        """(all there, what is not) for the files a page loads from its server."""
        gone = []
        for url in page_refs(html, base, origin or base):
            status = http_get(url, timeout=30.0)[0]
            if status != 200:
                gone.append(f"{url[len(origin or base):]} (HTTP {status})")
        return not gone, ", ".join(gone[:4]) + (" ..." if len(gone) > 4 else "")

    def smoke(self, report: str | None = None, timeout: float = 240.0) -> int:
        """Check the hub's routes and the bridge's guard, start every app, check
        each one's page answers, stop them all. Exit status 0 when all passed."""
        results: list[dict] = []

        def check(name: str, ok: bool, detail: str = "") -> None:
            results.append({"check": name, "ok": bool(ok), "detail": detail})
            self.log(f"[smoke] {'PASS' if ok else 'FAIL'} {name} {detail}".rstrip())

        status, page = http_get(self.url())
        text = page.decode("utf-8", "replace")
        check(
            "hub page",
            status == 200
            and PORTABLE_BRIDGE in text
            and WEBKIT_BRIDGE not in text
            and self.token in text,
            f"HTTP {status}",
        )
        hub = f"{self.origin}/hub/index.html"
        check("hub page files", *self.missing(text, hub, self.origin + "/"))
        rule = http_headers(self.url()).get("content-security-policy", "")
        check("hub refuses other sites' frames", rule == FRAME_RULE, rule)
        for path, marker in (
            ("/hub/status.js", b"window.FORGE_STATUS"),
            ("/hub/theme.js", b"window.FORGE_THEME"),
            ("/hub/portable.js", b"forgeBridge"),
            ("/shared/forge_icons.js", b""),
        ):
            given = f"?t={self.token}" if path in TOKEN_SCRIPTS else ""
            status, data = http_get(self.url(path + given))
            check(path, status == 200 and marker in data, f"HTTP {status}")
        refused = [http_get(self.url(path))[0] for path in TOKEN_SCRIPTS]
        check(
            "hub scripts refuse a page without the token",
            refused == [403] * len(TOKEN_SCRIPTS),
            f"HTTP {refused}",
        )
        status, _ = http_get(self.url("/hub/../forge_core.py"))
        check("no files outside hub/ and shared/", status == 404, f"HTTP {status}")
        bridge = self.url("/forge/bridge")
        status = http_post(bridge, b"{}", {"Content-Type": "application/json"})
        check("bridge refuses a page without the token", status == 403, f"{status}")
        headers = {"X-Forge": self.token, "Content-Type": "application/json"}
        status = http_post(bridge, b'{"nothing": 1}', headers)
        check("bridge answers the hub", status == 200, f"HTTP {status}")
        root = self.dirs["root"]
        check(
            "your things' place is in use and takes a write",
            self.mode == "ready" and bool(root) and write_test(root) == "",
            root,
        )
        for page in PLACE_PAGES:
            status, data = http_get(self.url(page))
            text = data.decode("utf-8", "replace")
            check(page, status == 200 and self.token in text, f"HTTP {status}")
            check(f"{page} files", *self.missing(text, self.origin + page, hub))
        status, _ = http_get(self.url("/forge/place"))
        check("place refuses a page without the token", status == 403, f"HTTP {status}")
        status, data = http_get(self.url(f"/forge/place?t={self.token}"))
        try:
            mode = json.loads(data).get("mode") if status == 200 else None
        except ValueError:
            mode = None
        check("place answers the hub", mode == "ready", f"HTTP {status}, {mode}")

        names = sorted(self.manager.apps)
        started = time.monotonic()
        threads = [
            threading.Thread(target=self.manager.start_and_wait, args=(n,))
            for n in names
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(max(1.0, timeout - (time.monotonic() - started)))
        for name in names:
            app = self.manager.apps[name]
            status, page = http_get(app.url + "/", timeout=30.0)
            check(
                f"app {name}",
                app.state == "up" and status == 200 and len(page) > 0,
                f"{app.state}, HTTP {status}, {len(page)} bytes",
            )
            if status != 200:
                continue
            text = page.decode("utf-8", "replace")
            check(f"app {name} page files", *self.missing(text, app.url + "/"))
            status, _ = http_get(app.url + "/", headers={"Host": "evil.example"})
            check(
                f"app {name} answers only to this machine",
                status == 403,
                f"HTTP {status}",
            )
            rule = http_headers(app.url + "/").get("content-security-policy", "")
            check(f"app {name} refuses other sites' frames", FRAME_RULE in rule, rule)
            status, _ = http_get(
                app.url + "/",
                headers={"Origin": "https://evil.example"},
                data=b"{}",
            )
            check(
                f"app {name} takes no changes from another site",
                status == 403,
                f"HTTP {status}",
            )
        failed = [r for r in results if not r["ok"]]
        self.log(
            f"[smoke] {len(results) - len(failed)} passed, {len(failed)} failed"
            f" ({self.profile.system}, {len(names)} apps)"
        )
        if report:
            with open(report, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "system": self.profile.system,
                        "version": self.profile.version,
                        "python": sys.version.split()[0],
                        "results": results,
                    },
                    f,
                    indent=2,
                )
        return 1 if failed else 0


def send(
    h: BaseHTTPRequestHandler,
    status: int,
    data: bytes,
    kind: str = "text/plain; charset=utf-8",
    body: bool = True,
) -> None:
    try:
        h.send_response(status)
        h.send_header("Content-Type", kind)
        h.send_header("Content-Length", str(len(data)))
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        if body:
            h.wfile.write(data)
    except OSError:
        pass


def redirect(h: BaseHTTPRequestHandler, where: str) -> None:
    try:
        h.send_response(302)
        h.send_header("Location", where)
        h.send_header("Content-Length", "0")
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
    except OSError:
        pass


def send_file(
    h: BaseHTTPRequestHandler, path: str, body: bool = True, cors: bool = False
) -> None:
    """A file, with byte ranges (audio and video seek with them)."""
    from forge_music import byte_range

    try:
        size = os.path.getsize(path)
        asked = h.headers.get("Range")
        span = byte_range(asked, size) if asked else None
        if asked and span is None:
            h.send_response(416)
            h.send_header("Content-Range", f"bytes */{size}")
            h.send_header("Content-Length", "0")
            h.end_headers()
            return
        first, last = span or (0, size - 1)
        h.send_response(206 if span else 200)
        h.send_header("Content-Type", content_type(path))
        h.send_header("Content-Length", str(max(0, last - first + 1)))
        h.send_header("Accept-Ranges", "bytes")
        h.send_header("Cache-Control", "no-cache")
        if span:
            h.send_header("Content-Range", f"bytes {first}-{last}/{size}")
        origin = h.headers.get("Origin") or ""
        if cors and LOCAL_ORIGIN.fullmatch(origin):
            # The apps (other ports of this machine) may read it, for canvas
            # and Web Audio; another site's page may not.
            h.send_header("Access-Control-Allow-Origin", origin)
            h.send_header("Vary", "Origin")
        h.end_headers()
        if not body or size == 0:
            return
        with open(path, "rb") as f:
            f.seek(first)
            left = last - first + 1
            while left > 0:
                chunk = f.read(min(65536, left))
                if not chunk:
                    break
                h.wfile.write(chunk)
                left -= len(chunk)
    except OSError:
        pass  # the page stopped reading (a seek, a track change)


def write_event(h: BaseHTTPRequestHandler, name: str, data) -> None:
    h.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode("utf-8"))
    h.wfile.flush()


def make_handler(launcher: Launcher):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Forge"
        protocol_version = "HTTP/1.0"

        def log_message(self, format: str, *args) -> None:
            pass

        def end_headers(self) -> None:
            # On every answer: no other site's page may frame the hub.
            self.send_header("Content-Security-Policy", FRAME_RULE)
            super().end_headers()

        def do_GET(self) -> None:
            launcher.get(self)

        def do_HEAD(self) -> None:
            launcher.get(self, body=False)

        def do_POST(self) -> None:
            launcher.post(self)

    return Handler


# ----------------------------------------------------------------------------
# windows: each kind opens the hub and returns once it has gone; False means
# this system does not have that kind and the next one is tried


def gtk_python() -> str | None:
    """A Python with GTK 3 and WebKit2 4.1 bindings (Linux): the system's,
    since a release's runtime has none."""
    seen = []
    for candidate in (
        os.environ.get("FORGE_GTK_PYTHON"),
        "/usr/bin/python3",
        shutil.which("python3"),
    ):
        if not candidate or candidate in seen or not os.path.isfile(candidate):
            continue
        seen.append(candidate)
        try:
            ok = subprocess.run(
                [candidate, "-c", GTK_CHECK], capture_output=True, timeout=20
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if ok.returncode == 0:
            return candidate
    return None


def open_when_up(app, create, done: threading.Event, seconds: float = 120.0):
    """create(app.label, app.url) once the app's backend is up; None when it
    fails, Forge quits or `seconds` pass first."""
    deadline = time.monotonic() + seconds
    while app.state != "up":
        if app.state == "failed" or time.monotonic() > deadline or done.wait(0.25):
            return None
    return create(app.label, app.url)


def watch_process(launcher: Launcher, proc: subprocess.Popen) -> None:
    """Until the process ends or Forge quits (which then ends the process)."""
    launcher.on_quit.append(lambda: forge_core.end_process(proc))
    while proc.poll() is None and not launcher.done.wait(0.5):
        pass


def open_native(launcher: Launcher, url: str, fullscreen: bool) -> bool:
    if launcher.profile.system == "linux":
        python = gtk_python()
        if python is None:
            return False
        command = [python, os.path.abspath(__file__), "--gtk-window", url]
        if fullscreen:
            command.append("--fullscreen")
        log = open(os.path.join(launcher.dirs["logs"], "window.log"), "ab")
        proc = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        log.close()
        launcher.log(f"[forge] window: GTK WebKit ({python})")
        watch_process(launcher, proc)
        return proc.returncode != 3  # 3: the window could not be made
    if not webview2_present():
        # pywebview would draw Forge with Internet Explorer's engine, which
        # shows a blank page: the next opener takes over
        launcher.log(
            "[forge] Microsoft Edge WebView2 is missing: trying a browser window"
        )
        return False
    try:
        import webview  # type: ignore[import-not-found]  # pywebview
    except Exception:
        return False
    launcher.log("[forge] window: pywebview")
    launcher.window_kind = "pywebview"
    window = None
    try:
        window = webview.create_window(
            TITLE,
            url,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            fullscreen=fullscreen,
            min_size=(640, 480),
        )
        if window is not None:
            launcher.on_quit.append(window.destroy)
        webview.start(
            private_mode=False,
            storage_path=os.path.join(launcher.dirs["state"], "webview"),
        )
    except Exception as e:
        # pywebview raises when it has no way to draw a window (Wine has no
        # .NET for it): the next opener takes over, unless a window showed
        # and was used, which then counts as closed
        launcher.log(f"[forge] the window stopped with an error ({e})")
        shown = window is not None and window_was_shown(launcher, window)
        failed = True
    else:
        shown = window_was_shown(launcher, window)
        failed = False
    if failed or not shown:
        # nothing of this window is left for quitting to wait on (pywebview's
        # destroy waits 20 s for a window that never showed)
        if window is not None and window.destroy in launcher.on_quit:
            launcher.on_quit.remove(window.destroy)
    if not shown:
        # the next opener's window is not a pywebview one: pop-outs and
        # closing must not go to pywebview
        launcher.window_kind = ""
    return shown


def webview2_present(reg: Any = None) -> bool:
    """False on a Windows without Microsoft Edge WebView2 (or without .NET
    4.6.2), where pywebview falls back to Internet Explorer's engine; the
    same registry keys pywebview reads. True on other systems."""
    if reg is None:
        try:
            reg = importlib.import_module("winreg")  # Windows only
        except ImportError:
            return True

    def value(root, path: str, name: str):
        try:
            with reg.OpenKey(root, path) as key:
                return reg.QueryValueEx(key, name)[0]
        except Exception:
            return None

    net = value(
        reg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
        "Release",
    )
    if not isinstance(net, int) or net < 394802:
        return False
    for client in (
        "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",  # the runtime
        "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",  # beta
        "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}",  # dev
        "{65C35B14-6C1D-4122-AC46-7148CC9D6497}",  # canary
    ):
        for root, path in (
            (reg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients"),
            (reg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients"),
            (
                reg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients",
            ),
        ):
            build = str(value(root, path + "\\" + client, "pv") or "0")
            major = build.split(".")[0]
            if major.isdigit() and int(major) >= 86:  # WebView2 86.0.622.0
                return True
    return False


def window_was_shown(launcher: Launcher, window) -> bool:
    """After pywebview's loop ends: True when its window ever showed. On a
    Windows without Edge WebView2 (or under Wine) it never does, and the
    next opener (Edge's app mode, then the browser) takes over."""
    shown = getattr(getattr(window, "events", None), "shown", None)
    if shown is None or not hasattr(shown, "is_set") or shown.is_set():
        return True
    launcher.log(
        "[forge] the window did not show (Microsoft Edge WebView2 may be"
        " missing): trying a browser window"
    )
    return False


def app_browsers(system: str, env=None) -> list[list[str]]:
    """Chrome-family browsers that have an app mode, best first, as the start
    of a command line."""
    env = os.environ if env is None else env
    found: list[list[str]] = []
    if system == "windows":
        bases = [
            env.get("PROGRAMFILES(X86)"),
            env.get("PROGRAMFILES"),
            env.get("LOCALAPPDATA"),
        ]
        tails = [
            ("Microsoft", "Edge", "Application", "msedge.exe"),
            ("Google", "Chrome", "Application", "chrome.exe"),
            ("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
            ("Chromium", "Application", "chrome.exe"),
        ]
        for tail in tails:
            for base in bases:
                if base and os.path.isfile(os.path.join(base, *tail)):
                    found.append([os.path.join(base, *tail)])
                    break
        return found
    if system == "macos":
        for name, exe in (
            ("Google Chrome", "Google Chrome"),
            ("Microsoft Edge", "Microsoft Edge"),
            ("Chromium", "Chromium"),
            ("Brave Browser", "Brave Browser"),
        ):
            for base in ("/Applications", os.path.expanduser("~/Applications")):
                path = os.path.join(base, f"{name}.app", "Contents", "MacOS", exe)
                if os.path.isfile(path):
                    found.append([path])
                    break
        return found
    for name in (
        "google-chrome-stable",
        "google-chrome",
        "chromium",
        "chromium-browser",
        "microsoft-edge-stable",
        "microsoft-edge",
        "brave-browser",
        "brave",
        "vivaldi-stable",
    ):
        path = shutil.which(name)
        if path and [path] not in found:
            found.append([path])
    flatpak = shutil.which("flatpak")
    if flatpak:
        for app_id in (
            "com.google.Chrome",
            "org.chromium.Chromium",
            "com.brave.Browser",
        ):
            try:
                there = subprocess.run(
                    [flatpak, "info", app_id], capture_output=True, timeout=10
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if there.returncode == 0:
                found.append([flatpak, "run", app_id])
    return found


def open_app(launcher: Launcher, url: str, fullscreen: bool) -> bool:
    browsers = app_browsers(launcher.profile.system)
    if not browsers:
        return False
    command = browsers[0]
    # A profile of Forge's own makes the browser process ours: it ends when
    # the window is closed. A Flatpak browser cannot see that folder, so it
    # runs on its own profile and the page decides instead.
    own = not command[0].endswith("flatpak")
    args = command + [
        f"--app={url}",
        "--no-first-run",
        "--no-default-browser-check",
        "--autoplay-policy=no-user-gesture-required",
        f"--window-size={WINDOW_SIZE[0]},{WINDOW_SIZE[1]}",
    ]
    if own:
        args.append(f"--user-data-dir={os.path.join(launcher.dirs['state'], 'app')}")
    if fullscreen:
        args.append("--start-fullscreen")
    log = open(os.path.join(launcher.dirs["logs"], "window.log"), "ab")
    flags: dict = {"stdout": log, "stderr": subprocess.STDOUT}
    if not forge_core.WINDOWS:
        flags["start_new_session"] = True
    try:
        proc = subprocess.Popen(args, **flags)
    except OSError as e:
        log.close()
        launcher.log(f"[forge] {command[-1]} did not start ({e})")
        return False
    log.close()
    launcher.log(f"[forge] window: {' '.join(command)} in app mode")
    began = time.monotonic()
    watch_process(launcher, proc)
    if not launcher.done.is_set() and (not own or time.monotonic() - began < 5):
        # The browser handed the window to one already running and left.
        launcher.wait_for_pages()
    return True


def open_browser(launcher: Launcher, url: str, fullscreen: bool) -> bool:
    try:
        opened = webbrowser.open(url)
    except Exception:
        opened = False
    if not opened:
        return False
    launcher.log("[forge] window: a browser tab")
    launcher.wait_for_pages()
    return True


def open_none(launcher: Launcher, url: str, fullscreen: bool) -> bool:
    launcher.log(f"[forge] no window: open {url} (Ctrl+C ends Forge)")
    while not launcher.done.wait(1.0):
        pass
    return True


OPENERS: dict[str, Callable[[Launcher, str, bool], bool]] = {
    "native": open_native,
    "app": open_app,
    "browser": open_browser,
    "none": open_none,
}


def show(launcher: Launcher, order: list[str], fullscreen: bool) -> None:
    url = launcher.url()
    for kind in order:
        opener = OPENERS.get(kind)
        if opener is None:
            launcher.log(f"[forge] unknown window kind {kind!r}, skipped")
            continue
        if opener(launcher, url, fullscreen):
            return
    launcher.log(f"[forge] no window could be opened: open {url} in a browser")
    launcher.wait_for_pages()


# ----------------------------------------------------------------------------
# the GTK window (Linux), run by the system Python as a child process


def gtk_window(url: str, fullscreen: bool = False) -> int:
    try:
        import gi  # pyright: ignore[reportMissingImports]  (system Python only)

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("WebKit2", "4.1")
        from gi.repository import (  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
            Gdk,
            GLib,
            Gtk,
            WebKit2,
        )
    except (ImportError, ValueError):
        return 3
    windows: list = []

    def on_key(win, event, view) -> bool:
        key = Gdk.keyval_name(event.keyval) or ""
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if key == "F11":
            state = win.get_window().get_state() if win.get_window() else 0
            if state & Gdk.WindowState.FULLSCREEN:
                win.unfullscreen()
            else:
                win.fullscreen()
            return True
        if ctrl and key in ("plus", "equal", "KP_Add"):
            view.set_zoom_level(min(3.0, view.get_zoom_level() * 1.1))
            return True
        if ctrl and key in ("minus", "KP_Subtract"):
            view.set_zoom_level(max(0.3, view.get_zoom_level() / 1.1))
            return True
        if ctrl and key in ("0", "KP_0"):
            view.set_zoom_level(1.0)
            return True
        return False

    def holder(view, title: str):
        win = Gtk.Window(title=title)
        win.set_default_size(*WINDOW_SIZE)
        win.add(view)
        win.connect("key-press-event", on_key, view)

        def gone(w) -> None:
            windows.remove(w)
            if not windows:
                Gtk.main_quit()

        win.connect("destroy", gone)
        view.connect("close", lambda _v: win.destroy())
        windows.append(win)
        return win

    def make_view(related=None):
        view = (
            WebKit2.WebView.new_with_related_view(related)
            if related is not None
            else WebKit2.WebView()
        )
        settings = view.get_settings()
        settings.set_enable_fullscreen(True)
        settings.set_media_playback_requires_user_gesture(False)
        settings.set_javascript_can_open_windows_automatically(True)
        view.connect("create", on_create)
        return view

    def on_create(view, _action):
        # window.open (an app popped out): a window of the same kind
        child = make_view(view)
        win = holder(child, TITLE)
        child.connect("ready-to-show", lambda _v: win.show_all())
        return child

    view = make_view()
    win = holder(view, TITLE)
    view.load_uri(url)
    win.show_all()
    if fullscreen:
        win.fullscreen()
    for number in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, number, Gtk.main_quit)
    Gtk.main()
    return 0


# ----------------------------------------------------------------------------


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Forge, for Windows, macOS and Linux")
    parser.add_argument(
        "--window",
        choices=sorted(OPENERS),
        help="how to show Forge (default: the release registry's order)",
    )
    parser.add_argument("--port", type=int, help="the hub's port (default 8400)")
    parser.add_argument(
        "--port-offset",
        type=int,
        default=0,
        help="add this to every port (to run beside another Forge)",
    )
    parser.add_argument("--apps", help="only these apps, comma separated")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument(
        "--smoke", action="store_true", help="check the hub and every app, then stop"
    )
    parser.add_argument("--report", help="with --smoke: write the results here")
    parser.add_argument(
        "--data",
        metavar="FOLDER",
        help="keep your things in FOLDER for this run only (made if missing),"
        " without asking or remembering it",
    )
    parser.add_argument("--pick-folder", metavar="START", help=argparse.SUPPRESS)
    parser.add_argument("--gtk-window", metavar="URL", help=argparse.SUPPRESS)
    # for checks: what the hub hides and which apps run are another system's
    parser.add_argument(
        "--as-system", choices=["linux", "windows", "macos"], help=argparse.SUPPRESS
    )
    return parser.parse_args(argv)


def windows_identity(system: str) -> object | None:
    """Windows only: take APP_ID as this process's AppUserModelID (a
    pywebview window then groups with the setup's Start menu shortcut and
    shows Forge's icon; Edge's app-mode window is Edge's own process and
    keeps Edge's) and hold a mutex of that name while Forge runs; the
    setup program and its uninstaller (AppMutex) see it and ask the user to
    close Forge first. The handle is returned so it stays open; Windows
    closes it when Forge ends."""
    if system != "windows":
        return None
    try:
        import ctypes

        # private handles: setting restype on ctypes.windll's shared ones
        # would change them for every other user in this process
        dll = getattr(ctypes, "WinDLL")  # noqa: B009  (Windows-only name)
        shell32, kernel32 = dll("shell32"), dll("kernel32")
    except Exception:
        return None
    try:
        shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass  # an older Windows or Wine: only the taskbar icon is lost
    try:
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        return kernel32.CreateMutexW(None, False, APP_ID)
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.gtk_window:
        return gtk_window(args.gtk_window, args.fullscreen)
    if args.pick_folder is not None:
        return gtk_pick_folder(args.pick_folder)
    # no bytecode files in the program folder from the apps Forge starts
    # (the launchers pass -B or set this already; a shortcut may not)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    system = forge_core.platform_name()
    identity = windows_identity(system)  # noqa: F841  (held while Forge runs)
    profile = Profile(load_registry(), args.as_system or system)
    local = local_dirs(system)
    wanted = args.port if args.port else profile.hub_port + args.port_offset
    port = wanted
    if forge_core.port_open(wanted):
        if other_forge(wanted) and not args.smoke:
            print(f"[forge] Forge is already running: opening {wanted}", flush=True)
            webbrowser.open(f"http://127.0.0.1:{wanted}/hub/index.html")
            return 0
        port = free_port()
    only = {a.strip() for a in args.apps.split(",") if a.strip()} if args.apps else None
    launcher = Launcher(profile, local, port, args.port_offset, only, system=system)
    launcher.serve()
    for number in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if number is not None:
            signal.signal(number, lambda *_: launcher.done.set())
    try:
        launcher.begin(args.data, args.smoke)
        if args.smoke:
            return launcher.smoke(args.report)
        settings = launcher.theme_module.load() if launcher.theme_module else {}
        fullscreen = args.fullscreen or settings.get("start_fullscreen") is True
        order = [args.window] if args.window else profile.windows
        show(launcher, order, fullscreen)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        launcher.close()


if __name__ == "__main__":
    sys.exit(main())
