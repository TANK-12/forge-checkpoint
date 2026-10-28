"""The release: its registry (release/release.json), the portable launcher
(forge_portable.py) and the bundle builder (release/build.py).

The launcher is also run for real, as a release runs it, in a subprocess
with its home folder moved and no apps, and probed over HTTP the way the hub
page and other pages would reach it.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

import forge_core  # noqa: E402
import forge_portable as fp  # noqa: E402
import forge_serve  # noqa: E402
import forge_theme  # noqa: E402
from release import build  # noqa: E402

REGISTRY = fp.load_registry()
SYSTEMS = ("linux", "windows", "macos")


# ---------------------------------------------------------------- the registry


def test_registry_names_every_app_folder():
    folders = {p.parent.name for p in (ROOT / "apps").glob("*/forge_app.json")}
    entries = REGISTRY["apps"]
    assert folders - set(entries) == set(), "apps with no release entry"
    assert set(entries) - folders == set(), "release entries with no app folder"
    for name, entry in entries.items():
        if entry.get("include") is True:
            continue
        assert entry.get("include") is False, name
        assert entry.get("why"), f"{name} is left out without a reason"


def test_every_feature_and_app_entry_uses_a_known_word():
    for name, feature in REGISTRY["features"].items():
        assert feature.get("what"), name
        for system in SYSTEMS:
            text = feature.get(system)
            assert text, f"{name} says nothing for {system}"
            word = str(text).split(":", 1)[0].strip()
            assert word in fp.STATES, f"{name}.{system}: {word!r}"
    for name, entry in REGISTRY["apps"].items():
        for system in SYSTEMS:
            if system in entry:
                word = str(entry[system]).split(":", 1)[0].strip()
                assert word in fp.STATES, f"{name}.{system}: {word!r}"
                assert ":" in entry[system], f"{name}.{system} gives no reason"


def test_window_order_names_known_windows():
    for system in SYSTEMS:
        order = REGISTRY["window_order"][system]
        assert order and set(order) <= set(fp.OPENERS), system


def test_cut_settings_are_real_settings():
    groups = {spec.get("group") for spec in forge_theme.SETTINGS.values()}
    for name, feature in REGISTRY["features"].items():
        for key in feature.get("settings") or []:
            assert key in forge_theme.SETTINGS, f"{name}: no setting {key!r}"
        for group in feature.get("settings_groups") or []:
            assert group in groups, f"{name}: no settings group {group!r}"


def test_group_words_cover_every_group_that_loses_members():
    """A group that ships only some of its apps says so in its own words:
    "Music videos, beats and Suno songs" over Loops alone was wrong."""
    shipped = {n for n, e in REGISTRY["apps"].items() if e.get("include")}
    joined: dict[str, set] = {}
    for manifest in (ROOT / "apps").glob("*/forge_app.json"):
        line = json.loads(manifest.read_text(encoding="utf-8")).get("group")
        if line:
            joined.setdefault(line, set()).add(manifest.parent.name)
    words = REGISTRY["group_words"]
    for path in (ROOT / "groups").glob("*.json"):
        gid = path.stem
        members = set(json.loads(path.read_text(encoding="utf-8")).get("members", []))
        members |= joined.get(gid, set())
        if members & shipped and members - shipped:
            assert gid in words, f"{gid}: ships {sorted(members & shipped)} only"
    for gid, entry in words.items():
        assert (ROOT / "groups" / f"{gid}.json").is_file(), gid
        assert entry and set(entry) <= {"label", "tagline"}, gid
    p = fp.Profile(REGISTRY, "linux")
    assert p.group_words["make-music"]["tagline"] == "Beats and loops on a step grid"


def test_settings_actions_to_a_cut_page_leave_the_search():
    """Critic round C: Home search offered Wi-Fi, Bluetooth, Sound and
    Screen brightness, which opened Settings on a page the release cut.
    Every Settings action names a real Settings page; a release drops the
    ones whose page it cut, and keeps the rest."""
    manifest = json.loads(
        (ROOT / "apps/settings/forge_app.json").read_text(encoding="utf-8")
    )
    html = (ROOT / "apps/settings/static/index.html").read_text(encoding="utf-8")
    sections = set(re.findall(r'data-section="([^"]+)"', html))
    for action in manifest["actions"]:
        assert action["hash"].split("/")[0] in sections, action
    status = {
        "settings": {"role": "settings", "actions": manifest["actions"]},
        "arcade": {"role": "", "actions": [{"label": "Play", "hash": "system"}]},
    }
    p = fp.Profile(REGISTRY, "linux")
    fp.cut_actions(status, p.cut_pages)
    left = {a["label"] for a in status["settings"]["actions"]}
    assert left == {"Change the wallpaper", "Pick a theme"}, left
    assert status["arcade"]["actions"] == [{"label": "Play", "hash": "system"}]


def test_the_event_stream_sends_the_same_cut_status_as_status_js(tmp_path):
    """Critic round E2: Home search offered Wi-Fi and Bluetooth again on the
    installed build. status.js cut them, but the event stream (on connect and
    on every app start or stop) sent the uncut snapshot, and the hub replaced
    its status with it. Every way the hub gets the status gives the same."""
    local = {k: str(tmp_path / k) for k in ("cache", "logs", "state")}
    for d in local.values():
        os.makedirs(d)
    launcher = fp.Launcher(fp.Profile(REGISTRY, "linux"), local, port=1)
    dirs = dict(local, root=str(tmp_path), config=str(tmp_path / "c"))
    dirs["data"] = str(tmp_path / "d")
    launcher.manager = launcher.build(dirs)
    js = launcher.status_js()
    from_js = json.loads(js.split("window.FORGE_STATUS = ", 1)[1].split(";\n", 1)[0])
    q: queue.Queue = queue.Queue()
    launcher.clients.append(q)
    launcher.status_changed()
    name, pushed = q.get_nowait()
    assert name == "status"
    hashes = {a["hash"].split("/")[0] for a in pushed["settings"]["actions"]}
    assert not hashes & set(launcher.profile.cut_pages), hashes
    assert pushed == from_js


def test_seeded_art_names_no_app_the_release_leaves_out():
    """Critic round C: PixelForge opened on "Crew Room — characters", a pack
    named after an app the testers do not have. A shipped art pack or
    palette may not carry the name of a left-out app."""
    left_out = set()
    for name, entry in REGISTRY["apps"].items():
        manifest = ROOT / "apps" / name / "forge_app.json"
        if not entry.get("include") and manifest.is_file():
            label = json.loads(manifest.read_text(encoding="utf-8")).get("label")
            if label:
                left_out.add(label)
    seeds = sorted((ROOT / "shared/art_seed").glob("*/*.json"))
    assert seeds
    for path in seeds:
        label = json.loads(path.read_text(encoding="utf-8")).get("label", "")
        for app in left_out:
            assert app not in label, f"{path.name}: {label!r} names {app}"


def test_help_sheets_speak_to_testers():
    """Critic round E1: the Help sheet (F1, or the frame's ... > Help) fell
    back to each manifest's developer summary and feature names: play.py,
    ~/Music/Loops, MediaForge, "the owner's money". Every shipped app now
    says what it is in its own "help", features included."""
    left_out = set()
    for name, entry in REGISTRY["apps"].items():
        manifest = ROOT / "apps" / name / "forge_app.json"
        if not entry.get("include") and manifest.is_file():
            label = json.loads(manifest.read_text(encoding="utf-8")).get("label")
            if label:
                left_out.add(label)
    # Left-out apps named with an ordinary word (Afterglow has a Shelf of its
    # own; its toys are made by Claude the AI, not the left-out Claude app)
    left_out -= set(
        "Arena Atlas Backup Bible Board Browser Calendar Claude Clipboard Code"
        " Disk Enjoy Focus Gauge Keymap Logins Logs Media Office Papers Phone"
        " Power Prompts Recall Reps Setups Shelf Snap Store Switchboard Tutor"
        " Typing Vault Voice Wallpapers Workers".split()
    )
    banned = re.compile(
        r"\.py\b|~/|/home/|\brelay\b|\blaptop\b|\bowner\b|the owner|registry"
        r"|sha256|\.json\b|static/|shared/",
        re.I,
    )
    for name, entry in REGISTRY["apps"].items():
        if not entry.get("include"):
            continue
        manifest = json.loads(
            (ROOT / "apps" / name / "forge_app.json").read_text(encoding="utf-8")
        )
        help_ = manifest.get("help")
        assert isinstance(help_, dict) and help_.get("about"), f"{name}: no help"
        assert "features" in help_, f"{name}: help names no features"
        sheet = forge_core.help_text(manifest)
        assert sheet["features"] == help_["features"], name
        words = " ".join(sheet["about"] + sheet["features"])
        words += " " + " ".join(" ".join(k) for k in sheet["keys"])
        assert not banned.search(words), f"{name}: {banned.search(words)!r}"
        for app in left_out:
            assert not re.search(rf"\b{re.escape(app)}\b", words), f"{name}: {app}"


def test_shipped_logbook_and_mint_sources_read_for_testers():
    """Critic round E2: Afterglow's logbook signed posts "Claude"
    and named play.py and "this laptop"; Mint's Learn intro named
    docs/library files and its sources carried "" tags. The
    release copy (after the scrub) says none of it."""
    paths = sorted((ROOT / "apps/afterglow/logbook").glob("*.json"))
    paths += [ROOT / "apps/mint/learn.json", ROOT / "apps/mint/paths.json"]
    files = [
        build.File(p.relative_to(ROOT).as_posix(), p.read_bytes(), 0o644) for p in paths
    ]
    build.scrub(files, REGISTRY)
    bad = re.compile(
        r"relay \d+|Forge sweep|play\.py|this laptop|Claude session"
        r"|research [AB]\b|docs/library"
        # critic round F1: the same kind of working note
        r"|verified on page|snippet only|Low confidence"
    )
    for f in files:
        data = json.loads(f.data.decode("utf-8"))
        if f.rel.endswith("paths.json"):
            data.pop("about", None)  # the file's note for whoever edits it, not shown
        found = bad.search(json.dumps(data))
        assert not found, f"{f.rel}: {found.group(0)!r}"


def test_afterglow_shelf_reads_for_testers():
    """Critic round F1: the last card on Afterglow's shelf told a later
    Claude session to add a folder under curios/."""
    page = ROOT / "apps/afterglow/static/app.js"
    files = [build.File(page.relative_to(ROOT).as_posix(), page.read_bytes(), 0o644)]
    build.scrub(files, REGISTRY)
    text = files[0].data.decode("utf-8")
    found = re.search(r"Claude session|curios/, nothing", text)
    assert not found, found and found.group(0)


def test_section_words_name_real_sections():
    for name, words in REGISTRY.get("sections", {}).items():
        assert (ROOT / "sections" / f"{name}.json").is_file(), name
        assert words and set(words) <= {"label", "blurb"}, name
        assert all(isinstance(v, str) and v.strip() for v in words.values()), name


def test_hide_selectors_name_real_controls():
    """A selector that matches nothing would leave the control it was meant
    to hide on screen."""
    html = (ROOT / "hub" / "index.html").read_text(encoding="utf-8")
    for name, feature in REGISTRY["features"].items():
        for selector in feature.get("hide") or []:
            for ident in re.findall(r"#([\w-]+)", selector):
                made = (
                    ident.startswith("sz-")
                    and ident[3:] in forge_theme.SIZE_KEYS
                    and "`sz-${k}`" in html
                )
                assert f'id="{ident}"' in html or made, f"{name}: #{ident}"
            for cls in re.findall(r"\.([\w-]+)", selector):
                assert re.search(rf'class="[^"]*\b{cls}\b', html), f"{name}: .{cls}"


def test_env_values_name_known_folders_and_apps():
    included = set(build.included_apps(REGISTRY))
    values = list(REGISTRY["env"].values())
    for name in included:
        values += list((REGISTRY["apps"][name].get("env") or {}).values())
    for value in values:
        for kind, arg in fp.PLACEHOLDER.findall(value):
            if kind == "port":
                assert arg in included, value
            else:
                assert kind in fp.data_dirs("linux") and not arg, value


def test_included_apps_have_their_module():
    for name in build.included_apps(REGISTRY):
        manifest = json.loads((ROOT / "apps" / name / "forge_app.json").read_text())
        source = ROOT / "apps" / name / manifest.get("src_dir", ".")
        module = manifest["module"].split(":")[0]
        assert (source / (module.replace(".", "/") + ".py")).is_file(), name


# ---------------------------------------------------------------- what a system gets


@pytest.mark.parametrize(
    "text, state",
    [
        (None, "native"),
        ("native", "native"),
        ("cut: needs a pty", "cut"),
        ("Fallback: the window's own", "fallback"),
        ("replaced: HTTP", "replaced"),
        ("nonsense: typo", "cut"),
    ],
)
def test_entry_state(text, state):
    assert fp.entry_state(text) == state


def test_profile_cuts_terminal_on_windows_only():
    windows = fp.Profile(REGISTRY, "windows")
    linux = fp.Profile(REGISTRY, "linux")
    assert "terminal" in windows.cut_apps and not windows.includes("terminal")
    assert linux.includes("terminal") and not linux.cut_apps
    assert not linux.includes("relay"), "a left-out app must not start"


def test_profile_hides_and_sets_what_a_system_lacks():
    p = fp.Profile(REGISTRY, "macos")
    assert "#music-add" in p.hide
    assert p.theme.get("show_stats") is False
    assert p.features["bridge"] == "replaced" and p.features["music"] == "native"
    cut = p.settings_to_cut(forge_theme.SETTINGS)
    assert "close_action" in cut and "ui_scale" in cut and "music_folder" not in cut
    in_group = [
        k for k, s in forge_theme.SETTINGS.items() if s.get("group") == "On the desktop"
    ]
    assert in_group and set(in_group) <= set(cut)


def test_desktop_theme_files_are_cut_everywhere():
    """The switch writes Hyprland and terminal colour files, which a release
    puts in its cache where no config reads them, and its note names the
    laptop's own ~/.config/forge/theme/: no system shows it."""
    for system in SYSTEMS:
        cut = fp.Profile(REGISTRY, system).settings_to_cut(forge_theme.SETTINGS)
        assert "theme_desktop" in cut, system
    js = (ROOT / "apps" / "settings" / "static" / "themes.js").read_text()
    assert '"theme_desktop" in (state.fields' in js, "Settings hides it when cut"


def test_settings_leaves_out_the_laptop_pages_and_their_resets():
    """Settings' System page drives the laptop's own Wi-Fi, Bluetooth and
    sound (nmcli, bluetoothctl, pactl), names its RAM guard service and
    desktop extension, and its Reset groups forget Wi-Fi networks; Pick for
    my machine names the Power app; App options lists no app. A release cuts
    those pages and groups on every system (critic round B, 2026-10-28)."""
    html = (ROOT / "apps" / "settings" / "static" / "index.html").read_text()
    sections = set(re.findall(r'data-section="([^"]+)"', html))
    groups = {
        g["id"]
        for g in json.loads(
            (ROOT / "apps" / "settings" / "reset_groups.json").read_text()
        )["groups"]
    }
    for system in SYSTEMS:
        p = fp.Profile(REGISTRY, system)
        assert {"system", "machine", "app-options"} <= set(p.cut_pages), system
        assert set(p.cut_pages) <= sections, "each names a real page"
        laptop = {g for g in groups if g in ("network", "wifi", "bluetooth")}
        assert laptop | {"autoclose"} <= set(p.cut_resets), system
        assert set(p.cut_resets) <= groups, "each names a real reset group"
        assert set(p.setting_words) <= set(forge_theme.SETTINGS)


def test_shown_settings_name_nothing_the_release_leaves_out(monkeypatch):
    """The help under every setting a release shows, with its words in
    place, names no app or tool it does not ship (critic round B found
    "Also in the Power app", "in the Browser app", "Media saves downloads",
    the desktop extension and developer apps)."""
    banned = [
        "Power app",
        "Browser",
        "desktop extension",
        "particles extension",
        "YouTube",
        "Media saves",
        "developer apps",
        "Arena",
        "codec",
    ]
    for system in SYSTEMS:
        p = fp.Profile(REGISTRY, system)
        monkeypatch.setenv(
            "FORGE_CUT_SETTINGS", ",".join(p.settings_to_cut(forge_theme.SETTINGS))
        )
        monkeypatch.setenv("FORGE_SETTING_WORDS", json.dumps(p.setting_words))
        for key, spec in forge_theme.describe().items():
            text = f"{spec.get('label', '')} {spec.get('help', '')}"
            said = [w for w in banned if w in text]
            assert not said, f"{system}: {key} says {said}"
        widgets = forge_theme.describe()["widgets"]["help"]
        assert ("Jan" in widgets) == (p.features["net_and_jan"] == "native"), system


def test_profile_takes_out_the_widgets_a_system_cannot_feed():
    linux, windows, macos = (fp.Profile(REGISTRY, s) for s in SYSTEMS)
    assert linux.features["stats"] == "native" and linux.cut_widgets == []
    assert windows.features["stats"] == "replaced"
    assert set(windows.cut_widgets) == {"network", "jan"}
    assert windows.theme.get("show_stats") is None, "Windows keeps the top bar's"
    assert set(macos.cut_widgets) == {
        "system",
        "disk",
        "battery",
        "activity",
        "network",
        "jan",
    }
    assert macos.theme.get("show_stats") is False


def test_widget_cuts_name_real_widgets():
    text = (ROOT / "shared" / "forge_widgets.js").read_text(encoding="utf-8")
    kinds = set(re.findall(r'define\("([a-z0-9_]+)"', text))
    named = {
        kind
        for feature in REGISTRY["features"].values()
        for kind in feature.get("widgets") or []
    }
    assert named and named <= kinds, named - kinds


def test_profile_without_a_registry_runs_every_app():
    p = fp.Profile({}, "linux")
    assert p.includes("anything") and p.hide == [] and p.windows == ["app", "browser"]


def test_data_dirs_per_system():
    # settings and data in the place ("Forge data", this computer's by
    # default), the rest local; never forge.py's ~/.config/forge
    env = {"APPDATA": r"C:\Users\a\AppData\Roaming", "LOCALAPPDATA": r"C:\L"}
    win = fp.data_dirs("windows", env, home="/h")
    place = os.path.join(env["APPDATA"], "Forge", "Forge data")
    assert win["config"] == os.path.join(place, "config")
    assert win["cache"] == os.path.join(r"C:\L", "Forge", "Cache")
    mac = fp.data_dirs("macos", {}, home="/Users/a")
    support = "/Users/a/Library/Application Support/Forge"
    assert mac["data"] == support + "/Forge data/data"
    assert mac["logs"] == "/Users/a/Library/Logs/Forge"
    lin = fp.data_dirs("linux", {"XDG_CONFIG_HOME": "/x/conf"}, home="/h")
    assert lin["config"] == "/h/.local/share/forge-release/Forge data/config"
    assert lin["data"] == "/h/.local/share/forge-release/Forge data/data"
    assert lin["logs"] == "/h/.local/state/forge-release/logs"
    on_drive = fp.data_dirs("linux", {}, home="/h", root="/mnt/d/Forge data")
    assert on_drive["config"] == "/mnt/d/Forge data/config"
    assert on_drive["cache"] == "/h/.cache/forge-release"


def test_expand_fills_folders_and_ports():
    dirs = {"data": "/d", "config": "/c"}
    ports = {"dossier": 9437}
    assert fp.expand("{data}/A//b", dirs, ports) == os.path.normpath("/d/A/b")
    assert fp.expand("http://127.0.0.1:{port:dossier}", dirs, ports) == (
        "http://127.0.0.1:9437"
    )
    assert fp.expand("plain", dirs, ports) == "plain"
    assert fp.expand("{nothing}/x", dirs, ports) is None
    assert fp.expand("{port:gone}", dirs, ports) is None
    logged = []
    out = fp.expand_all(
        {"A": "{data}/a", "B": "{port:gone}"}, dirs, ports, logged.append
    )
    assert out == {"A": os.path.normpath("/d/a")} and len(logged) == 1


def test_theme_environment_keeps_values_already_set():
    dirs = fp.data_dirs("linux", {}, home="/h")
    env = fp.theme_environment(dirs, {"FORGE_CACHE": "/mine"})
    assert env["FORGE_CACHE"] == "/mine"
    place = "/h/.local/share/forge-release/Forge data"
    assert env["FORGE_CONFIG"] == place + "/config/settings.json"
    assert env["FORGE_HUB_OUT"].startswith("/h/.cache/forge-release")


def test_inside_refuses_paths_out_of_its_folder(tmp_path):
    root = tmp_path / "hub"
    root.mkdir()
    (root / "a.js").write_text("x")
    (tmp_path / "secret.txt").write_text("s")
    (root / "link.txt").symlink_to(tmp_path / "secret.txt")
    assert fp.inside(str(root), "a.js") == str((root / "a.js").resolve())
    assert fp.inside(str(root), "/a.js") == str((root / "a.js").resolve())
    assert fp.inside(str(root), "../secret.txt") is None
    assert fp.inside(str(root), "link.txt") is None
    assert fp.inside(str(root), "") is None
    assert fp.inside(str(root), "missing.js") is None
    assert fp.inside(str(root), "a\x00.js") is None


@pytest.mark.parametrize(
    "asked, path",
    [
        ("/hub/index.html", "/hub/index.html"),
        ("/hub//status.js", "/hub/status.js"),
        ("/hub/./theme.js/", "/hub/theme.js"),
        ("/hub/x/../status.js", "/hub/status.js"),
        ("/hub/..\\forge_core.py", "/forge_core.py"),
        ("//hub/status.js", "/hub/status.js"),
        ("/hub/", "/hub"),
        ("/", "/"),
        ("", "/"),
    ],
)
def test_request_paths_are_cleaned_before_any_check(asked, path):
    assert fp.clean_path(asked) == path


# ---------------------------------------------------------------- the launcher, running


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Running:
    def __init__(self, proc: subprocess.Popen, port: int, home: Path):
        self.proc, self.port, self.home = proc, port, home
        self.token = ""
        self.headers: dict[str, str] = {}

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            self.headers = dict(response.getheaders())
            return response.status, response.read()
        finally:
            conn.close()

    def bridge(self, message, headers=None):
        sent = {"Content-Type": "application/json", "X-Forge": self.token}
        sent.update(headers or {})
        status, data = self.request("POST", "/forge/bridge", json.dumps(message), sent)
        return status, (json.loads(data) if status == 200 else data)


@pytest.fixture(scope="module")
def launcher(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("FORGE_", "XDG_")) and k not in ("APPDATA", "LOCALAPPDATA")
    }
    env["HOME"] = str(home)
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "forge_portable.py")]
        + ["--window", "none", "--port", str(port), "--apps", "no-such-app"]
        + ["--data", str(home / "Forge data")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    running = Running(proc, port, home)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            status, _ = running.request("GET", "/forge/ping")
            if status == 200:
                break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.fail(
            "the launcher did not answer: "
            + (proc.stdout.read() if proc.stdout else "")
        )
    status, page = running.request("GET", "/hub/index.html")
    found = re.search(rb'"token": "([^"]+)"', page)
    assert status == 200 and found
    running.token = found.group(1).decode()
    yield running
    if proc.poll() is None:
        proc.kill()
        proc.wait(10)


def test_hub_page_has_the_portable_bridge(launcher):
    status, page = launcher.request("GET", "/hub/index.html")
    text = page.decode()
    assert status == 200
    assert fp.WEBKIT_BRIDGE not in text and fp.PORTABLE_BRIDGE in text
    assert text.find('src="portable.js"') < text.find(
        "<script", text.find("portable.js")
    )
    assert '"system": "linux"' in text
    assert '"popout": "page"' in text, "no pywebview window: the page pops apps out"


def test_system_numbers_reach_the_page(launcher):
    """Every few seconds, as forge.py's StatsPump: a "stats" event with the
    top bar's and the widgets' numbers (Linux: nothing is cut)."""
    _, page = launcher.request("GET", "/hub/index.html")
    assert '"widgets": []' in page.decode()
    conn = http.client.HTTPConnection("127.0.0.1", launcher.port, timeout=15)
    try:
        conn.request("GET", f"/forge/events?t={launcher.token}")
        response = conn.getresponse()
        assert response.status == 200
        stats = None
        deadline = time.monotonic() + 12
        while stats is None and time.monotonic() < deadline:
            line = response.fp.readline().decode()
            if line.startswith("event: stats"):
                data = response.fp.readline().decode()
                stats = json.loads(data.split("data: ", 1)[1])
    finally:
        conn.close()
    assert stats is not None, "no stats event within 12 s"
    assert {"cpu", "mem", "battery", "plugged", "net", "disks", "jan"} <= set(stats)
    assert isinstance(stats["mem"], int) and any(
        d["mount"] == "/" for d in stats["disks"]
    )


def test_generated_hub_files(launcher):
    for path, marker in (
        ("/hub/status.js", b"window.FORGE_STATUS = {}"),
        ("/hub/status.js", b'"blurb": "Draw, animate and check 3D prints"'),
        ("/hub/theme.js", b'"wall_3d": false'),
        ("/hub/portable.js", b"forgeBridge"),
    ):
        given = f"?t={launcher.token}" if path in fp.TOKEN_SCRIPTS else ""
        status, data = launcher.request("GET", path + given)
        assert status == 200 and marker in data, path


def test_hub_scripts_need_the_token(launcher):
    """Another site's page may load a script from Forge and read what it sets
    (theme.js holds the file token), so the hub's own scripts need the token."""
    for path in fp.TOKEN_SCRIPTS:
        assert launcher.request("GET", path)[0] == 403, path
        assert launcher.request("GET", path + "?t=wrong")[0] == 403, path
    status, page = launcher.request("GET", "/hub/index.html")
    assert status == 200
    for name in ("status.js", "theme.js"):
        assert f'src="{name}?t={launcher.token}"'.encode() in page, name
        assert f'src="{name}"'.encode() not in page, name


@pytest.mark.parametrize(
    "path",
    [
        "/hub//status.js",
        "/hub/./theme.js",
        "/hub/status.js/",
        "/hub/x/../theme.js",
        "/hub/%2e/status.js",
        "/hub/status.json",
        "/hub/STATUS.JSON",
    ],
)
def test_generated_hub_files_never_come_from_the_folder(launcher, path):
    """forge.py writes status.js, theme.js and status.json into hub/ for its
    own window (the owner's apps and file links); the launcher makes its own
    per request and hands out neither those files nor its own without the
    token, however the path is written."""
    status, data = launcher.request("GET", path)
    assert status in (403, 404), path
    assert b"FORGE_STATUS" not in data and b"FORGE_THEME" not in data


def test_every_answer_says_no_other_site_may_frame_it(launcher):
    for path, headers, want in (
        ("/hub/index.html", {}, 200),
        ("/hub/portable.js", {}, 200),
        ("/nowhere", {}, 404),
        ("/hub/status.js", {}, 403),
        ("/hub/index.html", {"Host": "evil.example"}, 403),
    ):
        status, _ = launcher.request("GET", path, headers=headers)
        assert status == want, path
        assert launcher.headers.get("Content-Security-Policy") == fp.FRAME_RULE, path
    assert "frame-ancestors 'self' http://127.0.0.1:*" in fp.FRAME_RULE


def test_the_hub_listens_only_to_forges_own_pages():
    """Another site's page that opens or frames the hub (or sits in a frame
    inside an app) may not post {forge: "open", app: "terminal"} to it."""
    hub = (ROOT / "hub" / "index.html").read_text(encoding="utf-8")
    found = re.search(r"const LOCAL_PAGE = /(.+)/;", hub)
    assert found
    local = re.compile(found.group(1).replace("\\/", "/"))
    for origin, ok in (
        ("http://127.0.0.1:8441", True),
        ("http://localhost", True),
        ("http://[::1]:9000", True),
        ("https://127.0.0.1:8441", False),
        ("https://evil.example", False),
        ("null", False),
        ("file://", False),
        ("http://127.0.0.1.evil.example", False),
        ("http://localhost.evil.example:80", False),
        ("http://evil.example/http://127.0.0.1:1", False),
    ):
        assert bool(local.fullmatch(origin)) is ok, origin
    start = hub.index('addEventListener("message", (event) => {\n  const msg')
    assert "|| !fromForge(event)) return;" in hub[start : start + 200]
    assert "return !!frameOwner(event.source) || LOCAL_PAGE.test(event.origin);" in hub


def test_only_this_machine_may_ask(launcher):
    status, _ = launcher.request(
        "GET", "/hub/index.html", headers={"Host": "evil.example"}
    )
    assert status == 403
    status, _ = launcher.request(
        "GET", "/hub/index.html", headers={"Host": f"evil.example:{launcher.port}"}
    )
    assert status == 403


@pytest.mark.parametrize(
    "path",
    [
        "/hub/../forge_core.py",
        "/hub/%2e%2e/forge_core.py",
        "/shared/..%2fforge_portable.py",
        "/hub/..%5cforge_core.py",
        "/release/release.json",
        "/apps/settings/web_app.py",
    ],
)
def test_no_files_outside_hub_and_shared(launcher, path):
    status, _ = launcher.request("GET", path)
    assert status == 404


def test_bridge_needs_the_token_and_the_hub_origin(launcher):
    status, _ = launcher.bridge({"nothing": 1}, {"X-Forge": "wrong"})
    assert status == 403
    status, _ = launcher.bridge({"nothing": 1}, {"Origin": "http://evil.example"})
    assert status == 403
    status, _ = launcher.bridge(
        {"nothing": 1}, {"Origin": f"http://127.0.0.1:{launcher.port}"}
    )
    assert status == 200
    status, answer = launcher.bridge({"start": "relay"})
    assert status == 200 and answer == {
        "done": "unknown"
    }, "a left-out app must not start"
    status, answer = launcher.bridge({"popout": "relay"})
    assert status == 200 and answer == {"done": "unknown"}
    status, _ = launcher.request("GET", "/forge/events")
    assert status == 403
    status, _ = launcher.request("GET", "/forge/file?p=/etc/hostname")
    assert status == 403


def test_bridge_saves_only_the_hub_settings(launcher):
    status, answer = launcher.bridge(
        {"settings": {"music_volume": 60, "music_folder": "/"}}
    )
    assert status == 200 and answer == {"done": "settings"}
    saved = json.loads(
        (launcher.home / "Forge data" / "config" / "settings.json").read_text()
    )
    assert saved["music_volume"] == 60 and "music_folder" not in saved
    status, answer = launcher.bridge({"settings": {"music_folder": "/"}})
    assert answer == {"done": "ignored"}


def picked_theme(launcher, message) -> dict:
    """Send one theme switcher message and read the answer the launcher
    pushes back to the hub ("theme_picked", as forge.py calls
    forgeThemePicked)."""
    conn = http.client.HTTPConnection("127.0.0.1", launcher.port, timeout=15)
    try:
        conn.request("GET", f"/forge/events?t={launcher.token}")
        response = conn.getresponse()
        assert response.status == 200
        assert launcher.bridge(message) == (200, {"done": "theme"})
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            line = response.fp.readline().decode()
            if line.startswith("event: theme_picked"):
                data = response.fp.readline().decode()
                return json.loads(data.split("data: ", 1)[1])
    finally:
        conn.close()
    raise AssertionError("no theme_picked event within 12 s")


def test_the_theme_switcher_picks_in_a_release(launcher):
    """Alt+T's switcher and Alt+Shift+T changed nothing in a release: the
    launcher ignored theme_pick, layout_pick, theme_next and theme_undo
    (critic round G, Relay task 405). It now saves them in the place and
    answers with the hub's own theme data (page keys and all)."""
    settings = launcher.home / "Forge data" / "config" / "settings.json"
    answer = picked_theme(launcher, {"theme_pick": "sakura"})
    assert answer["theme"]["theme"] == "sakura" and "page_keys" in answer["theme"]
    assert json.loads(settings.read_text())["theme"] == "sakura"
    answer = picked_theme(launcher, {"theme_undo": True})
    assert answer["theme"]["theme"] != "sakura"
    answer = picked_theme(launcher, {"theme_next": True})
    assert answer["theme"]["theme"]
    answer = picked_theme(launcher, {"layout_pick": "no-such-layout"})
    assert answer == {"error": "That theme or layout is not there any more."}
    assert not (launcher.home / ".config" / "forge").exists()
    portable = (ROOT / "hub" / "portable.js").read_text(encoding="utf-8")
    assert '"theme_picked"' in portable and "forgeThemePicked" in portable


def file_token(launcher) -> str:
    """The token file links carry, got as the hub gets it: the music panel's
    "serve" event."""
    conn = http.client.HTTPConnection("127.0.0.1", launcher.port, timeout=15)
    try:
        conn.request("GET", f"/forge/events?t={launcher.token}")
        response = conn.getresponse()
        assert response.status == 200
        assert launcher.bridge({"music": {"op": "serve"}})[0] == 200
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            line = response.fp.readline().decode()
            if line.startswith("event: music"):
                data = json.loads(response.fp.readline().decode().split("data: ", 1)[1])
                if data.get("type") == "serve":
                    return parse_qs(urlsplit(data["base"]).query)["t"][0]
    finally:
        conn.close()
    pytest.fail("no music serve event within 10 s")


def test_files_only_from_the_allowed_folders(launcher):
    cache = launcher.home / ".cache" / "forge-release"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "w.jpg").write_bytes(b"\xff\xd8 picture")
    (launcher.home / "private.txt").write_text("not for pages")
    music = launcher.home / "Music"
    music.mkdir(exist_ok=True)
    (music / "song.mp3").write_bytes(b"ID3 song")
    (music / "notes.txt").write_text("not music")
    t = file_token(launcher)
    assert t != launcher.token

    def get(raw, token=t):
        return launcher.request("GET", f"/forge/file?t={token}&p={quote(str(raw))}")

    assert (
        get(cache / "w.jpg", launcher.token)[0] == 403
    ), "the bridge token opens no file"
    assert get(cache / "w.jpg") == (200, b"\xff\xd8 picture")
    assert get(music / "song.mp3") == (200, b"ID3 song")
    for raw in (
        launcher.home / "private.txt",
        cache / ".." / ".." / "private.txt",
        "/etc/hostname",
        music / "notes.txt",  # the music folder gives out music only
        "//fileserver/share/w.jpg",  # a network share is never contacted
        "\\\\fileserver\\share\\w.jpg",
    ):
        assert get(raw)[0] == 404, raw
    track = quote("file://fileserver/share/song.mp3")
    assert launcher.request("GET", f"/forge/track?t={t}&u={track}")[0] == 404
    track = quote(f"file://{music / 'song.mp3'}")
    assert launcher.request("GET", f"/forge/track?t={t}&u={track}") == (
        200,
        b"ID3 song",
    )


def test_file_links_are_readable_by_this_machines_pages_only(launcher):
    cache = launcher.home / ".cache" / "forge-release"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "c.jpg").write_bytes(b"\xff\xd8 c")
    path = f"/forge/file?t={file_token(launcher)}&p={quote(str(cache / 'c.jpg'))}"
    for origin, allowed in (
        ("http://127.0.0.1:8441", True),
        ("http://localhost:9", True),
        ("http://evil.example", False),
        ("http://127.0.0.1.evil.example:80", False),
        ("null", False),
    ):
        status, _ = launcher.request("GET", path, headers={"Origin": origin})
        assert status == 200
        given = launcher.headers.get("Access-Control-Allow-Origin")
        assert given == (origin if allowed else None), origin


def test_quit_from_the_page_ends_the_launcher(launcher):
    status, answer = launcher.bridge({"forge": "quit"})
    assert status == 200 and answer == {"done": "quit"}
    assert launcher.proc.wait(15) == 0


# ---------------------------------------------------------------- guarded backends


def guard(scope: dict) -> tuple[list, list]:
    """(scope types the app saw, messages sent) for one request through
    forge_serve.HostGuard."""
    seen: list = []
    sent: list = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        sent.append(message)

    asyncio.run(forge_serve.HostGuard(app)(scope, receive, send))
    return seen, sent


@pytest.mark.parametrize(
    "host, ok",
    [
        ("127.0.0.1:8441", True),
        ("localhost:8441", True),
        ("LOCALHOST", True),
        ("[::1]:8441", True),
        ("evil.example", False),
        ("evil.example:8441", False),
        ("localhost.evil.example:8441", False),
        ("127.0.0.1.evil.example", False),
        ("", False),
    ],
)
def test_backends_answer_only_to_this_machine(host, ok):
    for kind in ("http", "websocket"):
        headers = [(b"host", host.encode())] if host else []
        seen, sent = guard({"type": kind, "headers": headers})
        assert (seen == [kind]) is ok, (kind, host)
        if not ok and kind == "http":
            assert sent[0]["status"] == 403
        if not ok and kind == "websocket":
            assert sent == [{"type": "websocket.close", "code": 1008}]
    assert guard({"type": "lifespan"})[0] == ["lifespan"]


def test_backend_answers_say_no_other_site_may_frame_them():
    sent: list = []

    async def app(scope, receive, send):
        start = {"type": "http.response.start", "status": 200}
        await send({**start, "headers": [(b"content-type", b"text/html")]})
        await send({"type": "http.response.body", "body": b"hi"})

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        sent.append(message)

    page = {"type": "http", "headers": [(b"host", b"127.0.0.1:8441")]}
    asyncio.run(forge_serve.HostGuard(app)(page, receive, send))
    rule = (b"content-security-policy", forge_serve.FRAME_RULE.encode())
    assert sent[0]["headers"] == [(b"content-type", b"text/html"), rule]
    assert sent[1] == {"type": "http.response.body", "body": b"hi"}
    refused = guard({"type": "http", "headers": [(b"host", b"evil.example")]})[1]
    assert refused[0]["status"] == 403 and rule in refused[0]["headers"]
    closed = guard({"type": "websocket", "headers": [(b"host", b"evil.example")]})[1]
    assert closed == [{"type": "websocket.close", "code": 1008}]


@pytest.mark.parametrize(
    "kind, method, origin, fetch_site, ok",
    [
        ("http", "POST", "http://127.0.0.1:9000", None, True),
        ("http", "POST", "http://localhost:8441", "same-site", True),
        ("http", "PUT", "http://[::1]:8441", None, True),
        ("http", "POST", None, None, True),  # the launcher, curl
        ("http", "POST", None, "same-origin", True),
        ("http", "GET", "https://evil.example", "cross-site", True),
        ("http", "OPTIONS", "https://evil.example", "cross-site", True),
        ("http", "POST", "https://evil.example", "cross-site", False),
        ("http", "DELETE", "http://evil.example:8441", None, False),
        ("http", "POST", "null", None, False),  # a sandboxed frame or file page
        ("http", "POST", "http://127.0.0.1.evil.example", None, False),
        ("http", "POST", "http://localhost.evil.example:8441", None, False),
        ("http", "POST", "https://127.0.0.1:8441", None, False),
        ("http", "PATCH", None, "cross-site", False),
        ("websocket", None, "http://127.0.0.1:8441", None, True),
        ("websocket", None, None, None, True),
        ("websocket", None, "https://evil.example", None, False),
    ],
)
def test_backends_take_changes_only_from_their_own_pages(
    kind, method, origin, fetch_site, ok
):
    headers = [(b"host", b"127.0.0.1:8441")]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if fetch_site is not None:
        headers.append((b"sec-fetch-site", fetch_site.encode()))
    scope = {"type": kind, "headers": headers}
    if method:
        scope["method"] = method
    seen, sent = guard(scope)
    assert (seen == [kind]) is ok
    if not ok and kind == "http":
        assert sent[0]["status"] == 403
        assert sent[1]["body"] == forge_serve.CROSS_SITE
    if not ok and kind == "websocket":
        assert sent == [{"type": "websocket.close", "code": 1008}]


TINY_APP = """
async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"tiny"})
"""

# Starts forge_serve.py as AppManager(guard=True) does, prints its pid, waits.
FAKE_LAUNCHER = """
import os, subprocess, sys, time
child = subprocess.Popen(
    [sys.executable, sys.argv[1], "tiny:app", "--port", sys.argv[2]],
    env=dict(os.environ, FORGE_PARENT_PID=str(os.getpid())),
    start_new_session=True,
)
print(child.pid, flush=True)
time.sleep(120)
"""


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.skipif(os.name == "nt", reason="POSIX signals")
def test_a_backend_refuses_other_names_and_ends_with_its_launcher(tmp_path):
    (tmp_path / "tiny.py").write_text(TINY_APP)
    port = free_port()
    launcher = subprocess.Popen(
        [sys.executable, "-c", FAKE_LAUNCHER, str(ROOT / "forge_serve.py"), str(port)],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert launcher.stdout is not None
    child = int(launcher.stdout.readline())
    try:
        deadline = time.monotonic() + 20
        while not forge_core.port_open(port) and time.monotonic() < deadline:
            time.sleep(0.1)
        backend = Running(launcher, port, tmp_path)
        assert backend.request("GET", "/") == (200, b"tiny")
        status, _ = backend.request("GET", "/", headers={"Host": "evil.example"})
        assert status == 403, "DNS rebinding: another name gets nothing"
        status, _ = backend.request(
            "POST", "/", body=b"{}", headers={"Origin": "https://evil.example"}
        )
        assert status == 403, "another site's page changes nothing"
        own = {"Origin": f"http://127.0.0.1:{port}"}
        assert backend.request("POST", "/", body=b"{}", headers=own) == (200, b"tiny")
        launcher.send_signal(signal.SIGKILL)
        launcher.wait(5)
        deadline = time.monotonic() + 15
        while alive(child) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert not alive(child), "the backend outlived its killed launcher"
        assert not forge_core.port_open(port)
    finally:
        if alive(child):
            os.kill(child, signal.SIGKILL)
        if launcher.poll() is None:
            launcher.kill()


def test_a_guarded_manager_never_takes_a_busy_port(tmp_path):
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = held.getsockname()[1]
        app = forge_core.App(
            {"name": "busy", "port": port, "module": "tiny:app"}, str(tmp_path)
        )
        said: list[str] = []
        manager = forge_core.AppManager(
            [app], log_dir=str(tmp_path), log=said.append, guard=True
        )
        assert manager.start_and_wait("busy") is False
        assert app.state == "failed" and app.proc is None
        assert any("in use by another program" in line for line in said)


def test_a_failed_card_learns_why_and_where_the_log_is(tmp_path):
    """The hub's "didn't start" card named forge.py's outputs/<app>.log and
    said "no response" when the port was taken (critic round F1, Relay task
    405): the status now carries the reason and the launcher's log path."""
    logs = tmp_path / "logs"
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = held.getsockname()[1]
        app = forge_core.App(
            {"name": "busy", "port": port, "module": "tiny:app"}, str(tmp_path)
        )
        manager = forge_core.AppManager(
            [app], log_dir=str(logs), log=lambda line: None, guard=True
        )
        manager.start_and_wait("busy")
    entry = manager.snapshot()["busy"]
    assert entry["state"] == "failed" and entry["reason"] == "port_busy"
    assert entry["log"] == str(logs / "busy.log")
    # the card sends the tester to that file, so it holds the reason even
    # when the app never ran (critic round G, Relay task 405)
    assert f"port {port} is in use" in (logs / "busy.log").read_text()
    hub = (ROOT / "hub" / "index.html").read_text(encoding="utf-8")
    assert "info.reason" in hub and "info.log ||" in hub


def test_open_when_up_waits_for_the_backend():
    made = []

    def create(title, url):
        made.append((title, url))
        return "window"

    app = types.SimpleNamespace(
        state="starting", label="Mint", url="http://127.0.0.1:1/"
    )
    threading.Timer(0.3, lambda: setattr(app, "state", "up")).start()
    assert fp.open_when_up(app, create, threading.Event(), seconds=10) == "window"
    assert made == [("Mint", "http://127.0.0.1:1/")]
    app.state = "failed"
    assert fp.open_when_up(app, create, threading.Event()) is None
    app.state = "starting"
    quitting = threading.Event()
    quitting.set()
    assert fp.open_when_up(app, create, quitting) is None
    assert fp.open_when_up(app, create, threading.Event(), seconds=0.3) is None
    assert len(made) == 1, "no window for an app that never came up"


# ---------------------------------------------------------------- the builder


def files(**texts) -> list[build.File]:
    return [
        build.File(rel, data if isinstance(data, bytes) else data.encode(), 0o644)
        for rel, data in texts.items()
    ]


SCRUB = {
    "scrub": {
        "replace": [
            ["/home/[a-z_][a-z0-9_-]*/", "~/"],
            ["/run/media/[a-z_][a-z0-9_-]*/", "/run/media/<user>/"],
        ],
        "forbid": ["/home/[a-z_][a-z0-9_-]*", "/run/media/[a-z_][a-z0-9_-]*", "{home}"],
    }
}


# Joined at run time: written out whole, the builder's own scrub would
# rewrite these examples in the source tree it makes from this file.
HOMES = "/home"
DRIVES = "/run/media"


def test_scrub_swaps_home_folders_and_drives_in_text_only():
    fs = files(
        a=f"cd {HOMES}/alice/Forge && ls {DRIVES}/bob/Store/x",
        b='p = f"/home/{user}/x"; q = "/home/"; r = "/run/media/"',
        c=b"\0binary " + f"{HOMES}/alice/x".encode(),
    )
    done = build.scrub(fs, SCRUB)
    assert fs[0].data == b"cd ~/Forge && ls /run/media/<user>/Store/x"
    assert fs[1].data == b'p = f"/home/{user}/x"; q = "/home/"; r = "/run/media/"'
    assert done == {"a": 2}
    problems = build.forbidden(fs, SCRUB)
    assert problems == [
        "c: a forbidden text (home folder, drive or private name) is left after"
        " the scrub"
    ]


def test_the_source_trees_own_files_pass_the_forbid_list():
    # Only the source tree ships the builder, its templates and these tests:
    # build 13 stopped on a builder comment that named a CI runner's home.
    fs = []
    for root in build.source_roots(REGISTRY):
        top = ROOT / root
        paths = sorted(top.rglob("*")) if root.endswith("/") else [top]
        fs += [
            build.File(p.relative_to(ROOT).as_posix(), p.read_bytes(), 0o644)
            for p in paths
            if p.is_file() and "__pycache__" not in p.parts
        ]
    assert len(fs) > 5
    build.scrub(fs, REGISTRY)
    assert build.forbidden(fs, REGISTRY) == []


def test_forbid_catches_paths_and_the_builders_own_home():
    fs = files(**{f"apps/x{HOMES}/alice/notes.txt": "fine"})
    fs += [build.File("apps/x/ok.txt", str(Path.home() / "y").encode(), 0o644)]
    rules = {"scrub": {"forbid": ["/home/[a-z_][a-z0-9_-]*/", "{home}"]}}
    assert len(build.forbidden(fs, rules)) == 2
    assert (
        build.scrub_pattern("{home}/x", home="/Users/a b+c").pattern
        == rb"/Users/a\ b\+c/x"
    )


TINY = {
    "ship": ["hub/", "forge_core.py"],
    "leave_out": ["*/tests/*", "shared/assets/*"],
    "packages": {"base": ["fastapi==1"], "window": {"windows": ["pywebview==6"]}},
    "apps": {
        "a": {"include": True, "packages": ["numpy==2"]},
        "b": {
            "include": True,
            "windows": "cut: Unix only",
            "packages": ["pty-thing==1"],
            "assets": ["shared/assets/b/"],
        },
        "c": {"include": False, "why": "personal"},
    },
}


def test_what_ships_and_what_is_left_out():
    assert build.in_ship("hub/index.html", TINY)
    assert build.in_ship("forge_core.py", TINY) and not build.in_ship("forge.py", TINY)
    assert build.in_ship("apps/a/web_app.py", TINY)
    assert not build.in_ship("apps/c/web_app.py", TINY)
    assert build.in_ship("shared/assets/b/tree.glb", TINY)
    assert not build.in_ship("shared/assets/other/tree.glb", TINY)
    assert build.left_out("apps/a/tests/test_x.py", TINY) == "*/tests/*"
    assert (
        build.left_out("shared/assets/b/tree.glb", TINY) is None
    ), "an app's assets ship"
    cut = build.cut_apps(TINY, "windows")
    assert cut == {"b"}
    assert build.dropped("apps/b/web_app.py", TINY, cut)
    assert build.dropped("shared/assets/b/tree.glb", TINY, cut)
    assert not build.dropped("hub/index.html", TINY, cut)


def test_requirements_per_system():
    assert build.requirements(TINY, "linux") == [
        "fastapi==1",
        "numpy==2",
        "pty-thing==1",
    ]
    assert build.requirements(TINY, "windows") == [
        "fastapi==1",
        "numpy==2",
        "pywebview==6",
    ]
    clash = json.loads(json.dumps(TINY))
    clash["apps"]["b"]["packages"] = ["numpy==3"]
    with pytest.raises(build.BuildError):
        build.requirements(clash, "linux")
    loose = json.loads(json.dumps(TINY))
    loose["apps"]["a"]["packages"] = ["numpy"]
    with pytest.raises(build.BuildError, match="pin one version"):
        build.requirements(loose, "linux")


def test_requirements_text_marks_what_only_some_systems_need():
    tiny = {
        **TINY,
        "version": "9",
        "targets": {"l": {"system": "linux"}, "w": {"system": "windows"}},
    }
    lines = build.requirements_text(tiny).splitlines()
    assert [line for line in lines if not line.startswith("#")] == [
        "fastapi==1",
        "numpy==2",
        'pty-thing==1; sys_platform == "linux"',
        'pywebview==6; sys_platform == "win32"',
    ]


def test_public_registry_keeps_only_the_shipped_apps():
    assert set(build.public_registry(TINY)["apps"]) == {"a", "b"}
    assert set(TINY["apps"]) == {"a", "b", "c"}, "the registry itself is left alone"


def test_oldest_system_from_wheel_tags():
    dists = [
        {"tags": ["cp314-cp314-manylinux_2_27_x86_64.manylinux_2_28_x86_64"]},
        {"tags": ["cp314-cp314-manylinux2014_x86_64"]},
        {"tags": ["cp314-cp314-macosx_11_0_arm64", "py3-none-any"]},
    ]
    assert build.oldest_system(dists) == {"glibc": "2.28", "macos": "11.0"}


def test_import_scan_follows_shipped_files():
    fs = files(
        **{
            "apps/a/web_app.py": "import os\nimport helper\nimport fastapi\nimport gone_hard\n"
            "try:\n    import gone_soft\nexcept ImportError:\n    pass\n"
            "def f():\n    import gone_late\n",
            "apps/a/helper.py": "from . import nothing_here\nimport forge_shared_thing\n",
            "shared/forge_shared_thing.py": "import json\n",
        }
    )
    scan = build.ImportScan(fs, {"fastapi"})
    scan.visit("apps/a/web_app.py", ["apps/a", "shared"], "apps/a")
    assert scan.seen == {
        "apps/a/web_app.py",
        "apps/a/helper.py",
        "shared/forge_shared_thing.py",
    }
    assert [e.split(": ", 1)[1] for e in scan.errors] == [
        "gone_hard is not shipped or installed"
    ]
    assert len(scan.warnings) == 2


def test_import_scan_knows_each_systems_standard_library():
    fs = files(
        **{
            "apps/a/web_app.py": "import fcntl\nimport json\n"
            "try:\n    import msvcrt\nexcept ImportError:\n    msvcrt = None\n"
            "if False:\n    import winreg\n"
        }
    )
    found = {}
    for system in ("linux", "windows"):
        scan = build.ImportScan(fs, set(), system)
        scan.visit("apps/a/web_app.py", ["apps/a"], "apps/a")
        found[system] = [e.split(": ", 1)[1] for e in scan.errors + scan.warnings]
    assert found["windows"] == ["fcntl is not in Python on windows"]
    assert found["linux"] == [], "the other system's branch under try or if is fine"


def test_third_party_check_skips_only_the_named_patterns():
    if build.clean_module() is None:
        pytest.skip("the clean checker (apps/backup/clean.py) is not in this tree")
    # Joined at run time so this file does not trip the checker itself.
    link = ("https://" + "someone:hunter22" + "@example.com/x").encode()
    key = ("-----BEGIN " + "RSA PRIVATE KEY-----").encode()
    strict = build.third_party_checker({})
    loose = build.third_party_checker({"third_party": {"skip": ["password in a link"]}})
    assert strict is not None and loose is not None
    assert "password in a link" in strict.scan_bytes(link)
    assert loose.scan_bytes(link) == []
    assert loose.scan_bytes(key) == ["private key"]


def test_readme_per_target_is_filled_in():
    names = {"terminal": "Terminal"}
    for name, target in REGISTRY["targets"].items():
        text = build.readme_text(REGISTRY, target, names)
        assert not re.search(r"@[A-Z_]+@", text), name
        assert REGISTRY["version"] in text and target["label"] in text
        notes = "\n".join(build.system_notes(REGISTRY, target["system"], names))
        assert ("Terminal" in notes) == (target["system"] == "windows"), name
        assert "Real web pages inside Forge" not in notes, "readme: false is kept out"
        assert "@end@" not in text and "@windows@" not in text, name
        assert ("Forge.cmd" in text) == (target["system"] == "windows"), name
        assert ("xattr -dr" in text) == (target["system"] == "macos"), name
        assert ("tar xzf" in text) == (target["system"] == "linux"), name


def test_app_data_in_a_tests_folder_ships():
    """Exolab's bench tests are data its tester runs; "*/tests/*" left them
    out and the tester opened on "no tests item named 'shoulder_rom'"."""
    for name in ("shoulder_rom", "shoulder_hold", "lift_cycle"):
        rel = f"apps/exolab/data/tests/{name}.json"
        assert (ROOT / rel).is_file(), rel
        assert build.in_ship(rel, REGISTRY) and build.left_out(rel, REGISTRY) is None
    assert build.left_out("apps/exolab/tests/test_api.py", REGISTRY) == "*/tests/*"
    for rel in REGISTRY["leave_out_keep"]:
        assert (ROOT / rel).exists(), rel


def test_readme_names_left_out_apps_by_their_label():
    """build_target names apps from every shipped manifest, so the Windows
    notes say "Convert", not the folder name of an app its bundle lacks."""
    files = [
        build.File(
            f"apps/{app}/forge_app.json",
            (ROOT / "apps" / app / "forge_app.json").read_bytes(),
            0o644,
        )
        for app in build.cut_apps(REGISTRY, "windows")
    ]
    names = build.labels(files)
    notes = "\n".join(build.system_notes(REGISTRY, "windows", names))
    for app in build.cut_apps(REGISTRY, "windows"):
        assert f"  {names[app]}: " in notes, app
    assert "  convert: " not in notes and "  Convert: " in notes
    readme = "\n".join(build.system_notes(REGISTRY, "windows", names, True))
    assert "Apps not in this build: Convert, " in readme and "convert" not in readme
    src = (ROOT / "release" / "build.py").read_text(encoding="utf-8")
    assert "readme_text(registry, target, labels(files)" in src


def test_third_party_credits_name_the_vendored_code():
    text = build.third_party_text(REGISTRY, [])
    for credit in ("three.js 0.186.0", "three-vrm 3.5.5", "xterm.js 6.0"):
        assert credit in text
    for folder in ("shared/vendor/three", "shared/vendor/three-vrm"):
        assert (ROOT / folder / "LICENSE").is_file() or (
            ROOT / folder / "THREE-LICENSE"
        ).is_file(), folder


def test_prune_takes_out_package_tests_and_debug_symbols(tmp_path):
    site = tmp_path / "site-packages"
    for rel in (
        "PyObjCTest/test_a.py",
        "PyObjCTest/x.so.dSYM/Contents/Info.plist",
        "objc/_objc.so",
        "objc/_objc.so.dSYM/Contents/Resources/DWARF/_objc.so",
    ):
        (site / rel).parent.mkdir(parents=True, exist_ok=True)
        (site / rel).write_text("x")
    (site / "empty_namespace").mkdir()
    assert build.prune(site, ["PyObjCTest/*", "*.dSYM/*"]) == 3
    assert not (site / "PyObjCTest").exists()
    assert not (site / "objc" / "_objc.so.dSYM").exists()
    assert (site / "objc" / "_objc.so").is_file()
    assert (site / "empty_namespace").is_dir(), "only what a pattern names goes"


def test_the_registry_prunes_command_scripts_naming_the_build_machine(tmp_path):
    site = tmp_path / "site-packages"
    for rel in ("bin/fastapi", "bin/bottle.py", "bottle.py", "fastapi/__init__.py"):
        (site / rel).parent.mkdir(parents=True, exist_ok=True)
        (site / rel).write_text("#!/somewhere/bin/python3\n")
    assert build.prune(site, REGISTRY["packages"]["leave_out"]) == 2
    assert not (site / "bin").exists()
    assert (site / "bottle.py").is_file() and (
        site / "fastapi" / "__init__.py"
    ).is_file()


def test_build_traces_find_the_builds_own_folders_in_a_bundle(tmp_path):
    cache = Path(HOMES, "builder", ".cache", "forge-release")
    bundle = tmp_path / "Forge"
    (bundle / "runtime" / "bin").mkdir(parents=True)
    (bundle / "runtime" / "bin" / "tool").write_text(f"#!{cache}/host/bin/python3")
    # A wheel built on a CI runner names that runner's home: not ours.
    (bundle / "sbom.json").write_text('{"path": "' + HOMES + '/runner/work/x"}')
    assert build.build_traces(bundle, [cache]) == ["runtime/bin/tool"]
    runner = Path(HOMES, "runner", ".cache", "forge-release")
    assert build.build_traces(bundle, [runner, tmp_path / ".build-x"]) == []
    assert build.build_traces(bundle, [Path("/"), Path("/x")]) == [], "never all"
    home = Path(HOMES, "builder")
    assert build.build_traces(bundle, [home]) == [], "never a bare home folder"


def test_scrub_drops_notes_about_the_owners_own_setup():
    # Joined, so the source tree's own scrub leaves this test as it is.
    fs = files(
        a="a free hand (Relay" + " task 125, 2026-10-09): this app",
        b="built in Blender, by Relay" + " task 104; see",
        c="asked for it (see ~/" + ".claude/self/X.md).",
        d='return title || "Relay task";',
    )
    build.scrub(fs, {"scrub": {"replace": REGISTRY["scrub"]["replace"]}})
    assert [f.data for f in fs] == [
        b"a free hand: this app",
        b"built in Blender; see",
        b"asked for it.",
        b'return title || "Relay task";',
    ]


def test_scrub_notes_stay_on_their_own_line():
    # Joined, as above.
    two_lines = "kept (Relay" + " task 7, which started\nover two lines) here"
    fs = files(
        a=two_lines,
        b="as Relay" + "'s chat does",
        c="text\n(see ~/" + ".claude/x.md) next",
    )
    build.scrub(fs, {"scrub": {"replace": REGISTRY["scrub"]["replace"]}})
    assert [f.data for f in fs] == [
        two_lines.encode(),
        b"as the chat does",
        b"text\n next",
    ]


def test_the_release_drops_the_voice_script_with_the_voice_app():
    """The Voice app is not shipped, so its script is left out and the tag
    that loads it goes: Afterglow then shows no Read aloud or mic button."""
    tag = '<script src="/shared/forge_' + 'voice.js"></script>'
    page = (
        f'  <script src="/shared/forge.js"></script>\n  {tag}\n  <script src="app.js">'
    )
    fs = files(a=page)
    build.scrub(fs, {"scrub": {"replace": REGISTRY["scrub"]["replace"]}})
    assert (
        fs[0].data
        == b'  <script src="/shared/forge.js"></script>\n  <script src="app.js">'
    )
    assert "shared/forge_voice.js" in REGISTRY["leave_out"]
    afterglow = (ROOT / "apps/afterglow/static/index.html").read_text(encoding="utf-8")
    # The owner's own tree keeps the tag for his Forge; the public source
    # tree has neither the script nor the tag.
    assert (tag in afterglow) == (ROOT / "shared/forge_voice.js").is_file()


def test_private_scrub_rules_come_from_a_file_outside_the_repo(tmp_path):
    name = "Ali" + "ce"  # joined: the build's own scrub must not see a name
    private = tmp_path / "release-scrub.json"
    private.write_text(
        json.dumps({"replace": [[rf"\b{name}\b", "the owner"]], "forbid": [name]})
    )
    rules = {"scrub": {**SCRUB["scrub"], "private": str(private)}}
    fs = files(a=f"{name} asked for this", b=f"{name}Bot keeps the name")
    assert build.scrub(fs, rules) == {"a": 1}
    assert fs[0].data == b"the owner asked for this"
    assert [p.split(":")[0] for p in build.forbidden(fs, rules)] == ["b"]
    # A named private file that is missing stops the build (the owner's own
    # words would otherwise ship unswapped); a registry naming none, as the
    # public source tree's does, uses its own lists.
    absent = {"scrub": {**SCRUB["scrub"], "private": str(tmp_path / "none.json")}}
    with pytest.raises(build.BuildError, match="private scrub list"):
        build.scrub_rules(absent)
    assert build.scrub_rules(SCRUB) == {
        "replace": SCRUB["scrub"]["replace"],
        "forbid": SCRUB["scrub"]["forbid"],
    }


def test_source_readme_is_filled_in():
    template = (ROOT / "release" / "source" / "README.md").read_text()
    fs = [
        build.File(
            f"apps/{name}/forge_app.json",
            (ROOT / "apps" / name / "forge_app.json").read_bytes(),
            0o644,
        )
        for name in build.included_apps(REGISTRY)
    ]
    text = build.source_readme(REGISTRY, template, fs)
    assert not re.search(r"@[A-Z_]+@", text) and not text.startswith("<!--")
    assert f"Version {REGISTRY['version']}." in text
    assert "inside Forge (not on Windows)" in text, "Terminal is cut on Windows"
    with pytest.raises(build.BuildError, match="unknown fields"):
        build.source_readme(REGISTRY, template + "@NOPE@", fs)


def test_launch_scripts_are_valid():
    for name in ("forge", "mac-launcher"):
        done = subprocess.run(["sh", "-n", str(ROOT / "release" / "launch" / name)])
        assert done.returncode == 0, name
    for target in REGISTRY["targets"].values():
        for source in (target.get("launch") or {}).values():
            assert (ROOT / "release" / "launch" / source).is_file()
    plist = (ROOT / "release" / "launch" / "Info.plist").read_text()
    filled = plist.format(version="1", bundle_id="x.y", min_macos="11.0")
    assert "<string>11.0</string>" in filled


# Folder variables an included app reads that the release leaves unset on
# purpose (each one's own default is right for a tester).
FOLDER_VARS_LEFT_UNSET = {
    "FORGE_SHARED_DIR": "the launcher sets it for every app",
    "XDG_CACHE_HOME": "the launcher's own folders",
    "XDG_CONFIG_HOME": "the launcher's own folders",
    "XDG_DATA_HOME": "the launcher's own folders",
    "JAN_DATA_DIR": "Jan's own folder, not Forge's",
    "DOSSIER_DIR": "where Dossier's code is, beside Foresight in the bundle",
    "COSMOS_DRIVE_ROOT": "only the catalog build tool reads it",
    "CONVERT_OUT_DIR": "converted copies of the tester's own files go to Downloads",
}


def test_what_included_apps_make_goes_in_the_place():
    """The welcome says everything made in Forge's apps is kept in the place
    picked; Loops' WAVs went to ~/Music/Loops and Typeset's documents to
    ~/Documents/Typeset instead (critic round C on the 0.2.0 candidate).
    Every folder variable an included app reads is given in its release env
    or is left unset on purpose."""
    read = re.compile(
        r'environ(?:\.get)?\(?\[?\s*"([A-Z0-9_]+_(?:DIR|DIRS|HOME|PATH|ROOT|OUT))"'
    )
    for name, app in REGISTRY["apps"].items():
        if not app.get("include"):
            continue
        given = set((app.get("env") or {}).keys())
        for path in (ROOT / "apps" / name).rglob("*.py"):
            if {".venv", "tests", "__pycache__"} & set(path.parts):
                continue
            for var in read.findall(path.read_text(errors="ignore")):
                assert var in given or var in FOLDER_VARS_LEFT_UNSET, (name, var)
    for name, var in (("loops", "LOOPS_OUT_DIR"), ("typeset", "TYPESET_DOCS_DIR")):
        assert REGISTRY["apps"][name]["env"][var].startswith("{data}/"), var


def test_shipped_pages_name_no_home_folder():
    """Emberfield and Drift Peaks told testers their files were in
    ~/ForgeGameData, a folder a release keeps inside the place instead
    (critic round D on the 0.2.0 candidate). A page an included app ships
    names no ~/ path outside its code comments."""
    comments = re.compile(r"/\*.*?\*/|<!--.*?-->|^\s*//.*?$", re.S | re.M)
    home = re.compile(r"~/[A-Za-z]")
    for name, app in REGISTRY["apps"].items():
        if not app.get("include"):
            continue
        for path in (ROOT / "apps" / name / "static").rglob("*"):
            if path.suffix not in (".html", ".js") or "node_modules" in path.parts:
                continue
            text = comments.sub("", path.read_text(errors="ignore"))
            # File-picker examples are input hints, not a claimed save location.
            text = re.sub(r'placeholder="[^"]*"', "", text)
            hits = [line.strip() for line in text.splitlines() if home.search(line)]
            assert not hits, (str(path.relative_to(ROOT)), hits)


def test_settings_words_on_a_release_name_nothing_it_cut(monkeypatch):
    """Critic round E: on the installed build the Reset page described
    "the 3D wallpaper", "the desktop's particles and visualiser", "the
    battery versions" and "the desktop's widgets", offered to reset Forge's
    own keys (cut everywhere), the help said "on the desktop" and "each
    app's own manifest", and the look list said "a waybar-style bar"."""
    sys.path.insert(0, str(ROOT / "apps" / "settings"))
    import resets  # pyright: ignore[reportMissingImports]  (apps/settings, put on the path above)

    groups = {g["id"] for g in resets.load_groups()}
    banned = re.compile(
        r"3D wallpaper|the desktop's (?:particles|widgets)|on the desktop|battery versions"
        r"|low battery saver"
        r"|GPU is busy|Forge's own keys|manifest|laptop|Hyprland|waybar"
    )

    for system in SYSTEMS:
        p = fp.Profile(REGISTRY, system)
        assert set(p.reset_words) <= groups, "each names a real reset group"
        monkeypatch.setenv("FORGE_CUT_RESETS", ",".join(p.cut_resets))
        monkeypatch.setenv("FORGE_RESET_WORDS", json.dumps(p.reset_words))
        monkeypatch.setenv(
            "FORGE_CUT_SETTINGS", ",".join(p.settings_to_cut(forge_theme.SETTINGS))
        )
        monkeypatch.setenv("FORGE_SETTING_WORDS", json.dumps(p.setting_words))
        for g in resets.load_groups():
            found = banned.search(f"{g['label']} {g.get('about', '')}")
            assert not found, f"{system}: reset group {g['id']}: {found.group(0)!r}"
        for key, spec in forge_theme.describe().items():
            text = f"{spec.get('label', '')} {spec.get('help', '')}"
            if key == "look":
                # Read from hub/looks/*.css, whose release copies the scrub
                # rewords: checked on the scrubbed file below.
                text = re.sub(r"Hyprland: [^;]*;", "", text)
            found = banned.search(text)
            assert not found, f"{system}: {key}: {found.group(0)!r}"
    look = ROOT / "hub" / "looks" / "hyprland.css"
    files = [build.File(look.relative_to(ROOT).as_posix(), look.read_bytes(), 0o644)]
    build.scrub(files, REGISTRY)
    first = files[0].data.decode("utf-8").splitlines()[0]
    assert first.startswith("/* look: ") and not banned.search(first), first


def test_shown_words_skip_what_every_bundle_cuts():
    """Critic round F: Settings > Business said "the 3D wallpaper ... stay
    off" and Home's Now playing card said "Play something in any app or
    player", but every bundle cuts the 3D wallpaper and other players. The
    release copy says neither, and the README names the Now playing cut."""
    pages = {
        "apps/settings/static/index.html": "3D wallpaper and animations",
        "shared/forge_widgets.js": "any app or player",
    }
    for rel, phrase in pages.items():
        page = ROOT / rel
        files = [build.File(rel, page.read_bytes(), 0o644)]
        build.scrub(files, REGISTRY)
        assert phrase not in files[0].data.decode("utf-8"), rel
    for system in ("linux", "windows", "macos"):
        assert REGISTRY["features"]["wall_3d"][system].startswith("cut")
        assert REGISTRY["features"]["desktop_players"][system].startswith("cut")
    for name, target in REGISTRY["targets"].items():
        text = build.readme_text(REGISTRY, target, {})
        assert "Now playing" in text, name


def test_bundle_readme_notes_are_for_testers():
    """Critic round E2: the Windows README's "What works differently" copied
    the registry's developer reasons ("Linux D-Bus only", "read from Linux's
    /proc", "needs a Unix pseudo-terminal (pty)", "needs yt-dlp and the GTK
    launcher") and listed things a tester never meets (the PS5 pad, the 2.5D
    wallpaper). A bundle's README now says only each feature's "tester"
    line; the source README keeps the reasons."""
    internals = re.compile(
        r"D-Bus|/proc|pty|yt-dlp|GTK launcher|PipeWire|gio\b|xdg-open|onnxruntime"
        r"|WebKit's message|MPRIS|PS5|2\.5D|input devices|Hyprland|laptop"
    )
    for name, target in REGISTRY["targets"].items():
        text = build.readme_text(REGISTRY, target, {})
        notes = text.split("What works differently on this system", 1)[1]
        notes = notes.split("If something goes wrong", 1)[0]
        found = internals.search(notes)
        assert not found, f"{name}: {found.group(0)!r}"
        if target["system"] != "linux":
            assert "Linux" not in notes, name
    for feature in REGISTRY["features"].values():
        words = feature.get("tester")
        for text in words.values() if isinstance(words, dict) else [words or ""]:
            assert not text or text.endswith("."), text
    source = "\n".join(build.system_notes(REGISTRY, "windows", {}))
    assert "Linux D-Bus only" in source, "the developer notes keep their reasons"


def test_f1_on_home_shows_forges_keys():
    """F1 on Home did nothing in a release (a browser opens its own help
    page instead), though the help table and the bar say F1 is help
    (critic round G, Relay task 405). Home now gets a sheet of Forge's own
    keys, from the key press and from the launcher's "help" action."""
    hub = (ROOT / "hub" / "index.html").read_text(encoding="utf-8")
    f1 = hub.split('if (e.key !== "F1"', 1)[1].split("});", 1)[0]
    assert "current === null ||" not in f1.split("\n", 1)[0]
    assert "Help.home()" in f1
    home = hub.split("  home() {", 1)[1].split("\n  },", 1)[0]
    assert "theme.hub_key_list" in home and "Forge keys" in home
    action = hub.split('if (action === "help")', 1)[1].split("\n", 1)[0]
    assert "Help.home()" in action


def test_the_theme_switcher_says_what_was_picked():
    """A layout picked in Alt+T's switcher toasted the theme's name
    ("Midnight is on"), and after the first pick the focus stayed on the old
    index, now the newly kept "My look before themes" card, so Enter put the
    old look back (critic round H, Relay task 405)."""
    hub = (ROOT / "hub" / "index.html").read_text(encoding="utf-8")
    pick = hub.split("  pick(request) {", 1)[1].split("\n  },", 1)[0]
    assert "this.last = request" in pick
    answer = hub.split("window.forgeThemePicked = (answer) => {", 1)[1].split(
        "\n};", 1
    )[0]
    assert "asked.layout_pick" in answer and "layout.label" in answer
    assert "asked.theme_undo" in answer
    assert 'classList.contains("ftc-current")' in answer
    assert "ThemePicker.move(focus)" not in answer


def test_release_pages_catch_forge_keys(tmp_path):
    """Critic round F (F-alt-keys): a release's window does not catch Forge's
    keys before the page as forge.py's does, so Alt+H, Alt+S and the rest did
    nothing while F1 listed them. The pages catch them now (hub/portable.js on
    the hub, shared/forge_chrome.js in each app), with no Quit or Restart key."""

    class Theme:  # forge_theme without the user's settings file
        HUB_KEYS = forge_theme.HUB_KEYS
        hub_key_list = staticmethod(forge_theme.hub_key_list)

        @staticmethod
        def theme():
            return {"hub_keys": {}}

    local = {k: str(tmp_path / k) for k in ("cache", "logs", "state")}
    for system in ("linux", "windows", "macos"):
        launcher = fp.Launcher(fp.Profile(REGISTRY, system), local, port=1)
        launcher.theme_module = Theme
        data = launcher.theme_data()
        labels = {label for _keys, label in data["hub_key_list"]}
        assert "Quit Forge" not in labels and "Restart Forge" not in labels, system
        if system == "macos":
            assert "page_keys" not in data
            continue
        keys = data["page_keys"]
        for sig, action in {
            "alt+h": "home",
            "alt+s": "settings",
            "alt+f": "fullscreen",
            "alt+shift+m": "visuals",
            "alt+arrowleft": "prev-app",
            "alt+space": "overview",
            "alt+3": "app-3",
            # forge.py's window also catches these while an app has the focus
            # (critic round G, Relay task 405)
            "ctrl+0": "home",
            "ctrl+4": "4",
            "ctrl+tab": "next",
            "ctrl+shift+tab": "prev",
        }.items():
            assert keys.get(sig) == action, (system, sig)
        assert "ctrl+r" not in keys, "Ctrl+R stays the app's own, as in forge.py"
        assert not {"quit", "restart", "help"} & set(keys.values()), system
        assert "f11" not in keys and "f1" not in keys, system

    # the two copies of keySig are the same and name a key press as
    # key_signature names a combo
    twins = [
        re.search(
            r"const keySig = \(e\) => \{.*?\n  \};",
            (ROOT / rel).read_text(encoding="utf-8"),
            re.S,
        )
        for rel in ("hub/portable.js", "shared/forge_chrome.js")
    ]
    assert all(twins) and twins[0].group(0) == twins[1].group(0)  # type: ignore[union-attr]
    node = shutil.which("node")
    if not node:
        return
    presses = [
        ({"key": "h", "code": "KeyH", "altKey": True}, "Alt+H"),
        ({"key": "M", "code": "KeyM", "altKey": True, "shiftKey": True}, "Alt+Shift+M"),
        ({"key": "ArrowLeft", "code": "ArrowLeft", "altKey": True}, "Alt+Left"),
        ({"key": " ", "code": "Space", "altKey": True}, "Alt+Space"),
        ({"key": "&", "code": "Digit1", "altKey": True}, "Alt+1"),
        ({"key": "0", "code": "Digit0", "ctrlKey": True}, "Ctrl+0"),
        (
            {"key": "Tab", "code": "Tab", "ctrlKey": True, "shiftKey": True},
            "Ctrl+Shift+Tab",
        ),
        (
            {"key": "Q", "code": "KeyQ", "ctrlKey": True, "shiftKey": True},
            "Ctrl+Shift+Q",
        ),
    ]
    script = twins[0].group(0) + f"\nconsole.log(JSON.stringify({json.dumps([p for p, _ in presses])}.map(keySig)));"  # type: ignore[union-attr]
    out = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [fp.key_signature(c) for _, c in presses]
