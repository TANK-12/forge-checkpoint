"""The release's Linux install and uninstall (release/launch/forge_installer.py,
started by release/launch/forge) and the build checks part C of the 0.2
plan added to release/build.py.

Every install here goes into a home folder under tmp_path (HOME and the XDG
folders moved), with a small stand-in bundle: the real launcher, installer,
forge_portable.py and registry, and a runtime/bin/python3 that is this
Python (or, for the launcher checks, a script that prints what it got).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "release" / "launch"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(LAUNCH))

import forge_installer as fi  # noqa: E402  # pyright: ignore[reportMissingImports]
from release import build  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux install")


def make_bundle(where: Path, python: str | None = None) -> Path:
    """A stand-in for an unpacked download: Forge/ with what the installer
    and the launcher need."""
    top = where / "Forge"
    (top / "runtime" / "bin").mkdir(parents=True)
    (top / "release").mkdir()
    (top / "assets").mkdir()
    for name in ("forge_portable.py", "forge_core.py", "forge_serve.py"):
        shutil.copy(ROOT / name, top / name)
    shutil.copy(ROOT / "release" / "release.json", top / "release" / "release.json")
    shutil.copy(ROOT / "assets" / "icon.png", top / "assets" / "icon.png")
    shutil.copy(LAUNCH / "forge", top / "forge")
    shutil.copy(LAUNCH / "forge_installer.py", top / "forge_installer.py")
    (top / "forge").chmod(0o755)
    py = top / "runtime" / "bin" / "python3"
    if python:
        py.write_text(python)
        py.chmod(0o755)
    else:
        py.symlink_to(sys.executable)
    return top


def env_for(home: Path) -> dict:
    return {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
    }


@pytest.fixture
def home(tmp_path):
    # a space and a letter outside ASCII, as a real home folder may have
    folder = tmp_path / "home of Zoë"
    folder.mkdir()
    return folder


def quiet(*_a, **_k):
    pass


# ---------------------------------------------------------------- install


def test_install_copies_marks_and_adds_a_menu_entry(tmp_path, home):
    src = make_bundle(tmp_path / "Downloads")
    env = env_for(home)
    done = fi.install(src, env=env, home=str(home), log=quiet)
    program = home / ".local" / "share" / "forge-release" / "app"
    assert done["program"] == program and done["copied"]
    assert (program / "forge_portable.py").is_file()
    assert os.access(program / "forge", os.X_OK)
    marker = json.loads((program / fi.MARKER).read_text())
    assert marker["version"] == fi.version_of(src) and marker["version"]
    menu = home / ".local" / "share" / "applications" / "local.forge.Forge.desktop"
    assert done["menu"] == menu
    text = menu.read_text()
    assert f'Exec="{program}/forge"' in text
    assert f"Icon={program}/assets/icon.png" in text
    assert (program / "assets" / "icon.png").is_file()
    assert "X-Forge-Install=true" in text
    assert not list(program.parent.glob(".app-*")), "no half-made copies left"
    # the download stays as it was
    assert (src / "forge_portable.py").is_file()


@pytest.mark.skipif(not shutil.which("desktop-file-validate"), reason="no validator")
def test_menu_entry_passes_the_desktop_entry_validator(tmp_path):
    odd = tmp_path / 'a "b" $c `d` 100% \\e'
    path = tmp_path / "local.forge.Forge.desktop"
    path.write_text(fi.menu_entry(odd, "0.2.0"))
    done = subprocess.run(
        ["desktop-file-validate", str(path)], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_exec_line_quotes_what_the_spec_reserves():
    # quoting rules first (\ " ` $), then the string escape doubles every \
    assert fi.exec_quoted(Path("/a b/forge")) == '"/a b/forge"'
    assert fi.exec_quoted(Path('/x"y/forge')) == '"/x\\\\"y/forge"'
    assert fi.exec_quoted(Path("/x$y/forge")) == '"/x\\\\$y/forge"'
    assert fi.exec_quoted(Path("/x\\y/forge")) == '"/x\\\\\\\\y/forge"'
    assert fi.exec_quoted(Path("/100%/forge")) == '"/100%%/forge"'


def test_an_existing_forge_desktop_is_never_touched(tmp_path, home):
    apps = home / ".local" / "share" / "applications"
    apps.mkdir(parents=True)
    theirs = apps / "forge.desktop"
    theirs.write_text("[Desktop Entry]\nName=Someone else's Forge\n")
    src = make_bundle(tmp_path / "Downloads")
    fi.install(src, env=env_for(home), home=str(home), log=quiet)
    fi.uninstall(env=env_for(home), home=str(home), log=quiet)
    assert theirs.read_text() == "[Desktop Entry]\nName=Someone else's Forge\n"


def test_a_newer_version_replaces_the_program_only(tmp_path, home):
    env = env_for(home)
    first = make_bundle(tmp_path / "one")
    (first / "only-in-old.txt").write_text("old")
    fi.install(first, env=env, home=str(home), log=quiet)
    place = home / ".local" / "share" / "forge-release" / "Forge data"
    (place / "data").mkdir(parents=True)
    (place / "data" / "save.json").write_text("{}")
    second = make_bundle(tmp_path / "two")
    (second / "only-in-new.txt").write_text("new")
    lines = []
    done = fi.install(second, env=env, home=str(home), log=lines.append)
    program = done["program"]
    assert (program / "only-in-new.txt").is_file()
    assert not (program / "only-in-old.txt").exists()
    assert (place / "data" / "save.json").read_text() == "{}"
    assert "replacing" in lines[0]
    assert not list(program.parent.glob(".app-*"))


def test_install_from_the_installed_copy_only_repairs_the_entry(tmp_path, home):
    env = env_for(home)
    src = make_bundle(tmp_path / "Downloads")
    program = fi.install(src, env=env, home=str(home), log=quiet)["program"]
    menu = fi.places(env, str(home))["menu"]
    menu.unlink()
    done = fi.install(program, env=env, home=str(home), log=quiet)
    assert not done["copied"] and menu.is_file()


def test_install_refuses_a_folder_it_did_not_make(tmp_path, home):
    env = env_for(home)
    program = fi.places(env, str(home))["program"]
    program.mkdir(parents=True)
    (program / "mine.txt").write_text("keep me")
    src = make_bundle(tmp_path / "Downloads")
    with pytest.raises(fi.Problem, match="not made by Forge's installer"):
        fi.install(src, env=env, home=str(home), log=quiet)
    assert (program / "mine.txt").read_text() == "keep me"
    with pytest.raises(fi.Problem, match="left alone"):
        fi.uninstall(env=env, home=str(home), log=quiet)
    assert (program / "mine.txt").read_text() == "keep me"


def test_install_refuses_a_partial_folder(tmp_path, home):
    src = make_bundle(tmp_path / "Downloads")
    (src / "forge_portable.py").unlink()
    with pytest.raises(fi.Problem, match="not a whole Forge folder"):
        fi.install(src, env=env_for(home), home=str(home), log=quiet)


def test_a_failed_copy_leaves_the_old_forge_working(tmp_path, home, monkeypatch):
    env = env_for(home)
    fi.install(make_bundle(tmp_path / "one"), env=env, home=str(home), log=quiet)
    program = fi.places(env, str(home))["program"]

    def broken(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(fi.shutil, "copytree", broken)
    with pytest.raises(fi.Problem, match="nothing was changed"):
        fi.install(make_bundle(tmp_path / "two"), env=env, home=str(home), log=quiet)
    assert (program / "forge_portable.py").is_file() and fi.is_ours(program)
    assert not list(program.parent.glob(".app-*"))


def test_install_says_when_there_is_no_room(tmp_path, home, monkeypatch):
    monkeypatch.setattr(fi, "free_bytes", lambda _p: 1000)
    with pytest.raises(fi.Problem, match="not enough room"):
        fi.install(
            make_bundle(tmp_path / "d"), env=env_for(home), home=str(home), log=quiet
        )
    assert not fi.places(env_for(home), str(home))["program"].exists()


def test_a_running_forge_stops_install_and_uninstall(tmp_path, home):
    env = env_for(home)
    program = fi.install(
        make_bundle(tmp_path / "d"), env=env, home=str(home), log=quiet
    )["program"]
    # a process whose command line runs the installed forge_portable.py
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
            str(program / "forge_portable.py"),
        ]
    )
    try:
        assert fi.running_from(program) == [proc.pid]
        with pytest.raises(fi.Problem, match="running"):
            fi.install(make_bundle(tmp_path / "e"), env=env, home=str(home), log=quiet)
        with pytest.raises(fi.Problem, match="running"):
            fi.uninstall(env=env, home=str(home), log=quiet)
        assert fi.is_ours(program)
    finally:
        proc.kill()
        proc.wait()


# ---------------------------------------------------------------- uninstall


def seed_data(home: Path) -> dict:
    """The release's folders with something in each, plus a neighbour."""
    share = home / ".local" / "share"
    made = {
        "place": share / "forge-release" / "Forge data" / "data" / "save.json",
        "pointer_dir": home / ".config" / "forge-release" / "x.json",
        "cache": home / ".cache" / "forge-release" / "c.bin",
        "logs": home / ".local" / "state" / "forge-release" / "logs" / "forge.log",
        "neighbour": share / "forge" / "data" / "daily.json",
    }
    for path in made.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    return made


def test_uninstall_keeps_the_users_things(tmp_path, home):
    env = env_for(home)
    fi.install(make_bundle(tmp_path / "d"), env=env, home=str(home), log=quiet)
    made = seed_data(home)
    lines = []
    done = fi.uninstall(env=env, home=str(home), log=lines.append)
    where = fi.places(env, str(home))
    assert done["program"] and done["menu"] and done["data"] == []
    assert not where["program"].exists() and not where["menu"].exists()
    assert all(p.is_file() for p in made.values())
    said = "\n".join(lines)
    assert "Your things are kept in" in said and "delete them yourself" in said


def test_remove_data_asks_and_a_no_keeps_the_folders(tmp_path, home):
    env = env_for(home)
    fi.install(make_bundle(tmp_path / "d"), env=env, home=str(home), log=quiet)
    made = seed_data(home)

    def closed(_q):
        raise EOFError

    done = fi.uninstall(
        remove_data=True, env=env, home=str(home), ask=closed, log=quiet
    )
    assert done.get("declined") and all(p.is_file() for p in made.values())
    assert fi.places(env, str(home))["program"].is_dir()
    # a typed "no" still takes the program out: the uninstall was asked for
    # (critic round F1, Relay task 405)
    lines = []
    done = fi.uninstall(
        remove_data=True, env=env, home=str(home), ask=lambda _q: "no", log=lines.append
    )
    assert done.get("declined") and done["program"] and done["data"] == []
    assert not fi.places(env, str(home))["program"].exists()
    assert all(p.is_file() for p in made.values())
    said = "\n".join(lines)
    assert str(home / ".local" / "share" / "forge-release") in said
    assert "Your things are kept in" in said


def test_remove_data_takes_a_y_as_yes(tmp_path, home, monkeypatch):
    monkeypatch.setattr(fi.shutil, "which", lambda _n: None)
    env = env_for(home)
    fi.install(make_bundle(tmp_path / "d"), env=env, home=str(home), log=quiet)
    made = seed_data(home)
    done = fi.uninstall(
        remove_data=True, env=env, home=str(home), ask=lambda _q: " Y ", log=quiet
    )
    assert done["program"] and not done.get("declined") and len(done["data"]) == 4
    assert not made["place"].exists()


def test_remove_data_removes_only_the_releases_own_folders(tmp_path, home, monkeypatch):
    monkeypatch.setattr(fi.shutil, "which", lambda _n: None)  # delete, no Trash
    env = env_for(home)
    fi.install(make_bundle(tmp_path / "d"), env=env, home=str(home), log=quiet)
    made = seed_data(home)
    done = fi.uninstall(
        remove_data=True, env=env, home=str(home), ask=lambda _q: "yes", log=quiet
    )
    assert done["program"] and len(done["data"]) == 4
    for key in ("place", "pointer_dir", "cache", "logs"):
        assert not made[key].exists(), key
    assert made["neighbour"].read_text() == "x", "forge.py's own folder stays"
    assert all(Path(p).name == "forge-release" for p in done["data"])


def test_remove_data_never_touches_a_chosen_place(tmp_path, home, monkeypatch):
    monkeypatch.setattr(fi.shutil, "which", lambda _n: None)
    env = env_for(home)
    fi.install(make_bundle(tmp_path / "d"), env=env, home=str(home), log=quiet)
    seed_data(home)
    drive = tmp_path / "drive" / "Forge data"
    (drive / "data").mkdir(parents=True)
    (drive / "data" / "save.json").write_text("mine")
    pointer = home / ".config" / "forge-release" / "where.json"
    pointer.write_text(json.dumps({"root": str(drive), "id": "x"}))
    lines = []
    fi.uninstall(remove_data=True, yes=True, env=env, home=str(home), log=lines.append)
    assert (drive / "data" / "save.json").read_text() == "mine"
    assert not pointer.exists()
    assert any(str(drive) in line and "not touched" in line for line in lines)


def test_uninstall_with_nothing_installed_says_so(home):
    lines = []
    done = fi.uninstall(env=env_for(home), home=str(home), log=lines.append)
    assert done == {"program": False, "menu": False, "data": []}
    assert any("not installed" in line for line in lines)


# ---------------------------------------------------------------- the launcher

ECHO = """#!/bin/sh
echo "dont_write=${PYTHONDONTWRITEBYTECODE:-unset}"
for a in "$@"; do echo "arg=$a"; done
"""


def run_launcher(top: Path, *args: str) -> list[str]:
    done = subprocess.run(
        [str(top / "forge"), *args], capture_output=True, text=True, timeout=30
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines()


def test_launcher_hands_install_and_uninstall_to_the_installer(tmp_path):
    top = make_bundle(tmp_path / "with space", python=ECHO)
    out = run_launcher(top, "--install", "--no-start")
    assert out[0] == "dont_write=1"
    assert out[1] == f"arg={top / 'forge_installer.py'}"
    assert out[2:] == ["arg=--install", "arg=--no-start"]
    out = run_launcher(top, "--uninstall")
    assert out[1] == f"arg={top / 'forge_installer.py'}"


def test_launcher_starts_forge_portable_otherwise(tmp_path):
    top = make_bundle(tmp_path / "d", python=ECHO)
    out = run_launcher(top, "--window", "none")
    assert out == [
        "dont_write=1",
        f"arg={top / 'forge_portable.py'}",
        "arg=--window",
        "arg=none",
    ]
    help_text = "\n".join(run_launcher(top, "--help"))
    assert "--install" in help_text and "--remove-data" in help_text


def test_launcher_install_end_to_end(tmp_path, home):
    src = make_bundle(tmp_path / "Downloads")
    env = {**os.environ, **env_for(home)}
    done = subprocess.run(
        [str(src / "forge"), "--install", "--no-start"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Done." in done.stdout and "--uninstall" in done.stdout
    program = home / ".local" / "share" / "forge-release" / "app"
    assert fi.is_ours(program)
    assert not list(src.rglob("__pycache__")), "the launcher writes no bytecode"
    done = subprocess.run(
        [str(program / "forge"), "--uninstall"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert not program.exists()


def test_windows_launchers_turn_off_bytecode():
    for name in ("Forge.cmd", "forge-console.cmd"):
        text = (LAUNCH / name).read_text()
        assert "set PYTHONDONTWRITEBYTECODE=1" in text, name
        assert text.index("PYTHONDONTWRITEBYTECODE") < text.index("forge_portable.py")


# ---------------------------------------------------------------- build checks


def test_build_stops_when_the_private_scrub_list_is_missing(tmp_path):
    registry = {"scrub": {"private": str(tmp_path / "gone.json")}}
    with pytest.raises(build.BuildError, match="private scrub list"):
        build.scrub_rules(registry)
    (tmp_path / "gone.json").write_text(json.dumps({"forbid": ["secretword"]}))
    assert "secretword" in build.scrub_rules(registry)["forbid"]


def test_public_registry_names_no_private_list():
    registry = json.loads((ROOT / "release" / "release.json").read_text())
    public = build.public_registry(registry)
    assert "private" not in public["scrub"] and "private_about" not in public["scrub"]
    # the public tree's own build then runs without the owner's file
    assert build.scrub_rules(public)["forbid"]


def test_forbid_list_catches_the_owners_names():
    registry = json.loads((ROOT / "release" / "release.json").read_text())
    registry["scrub"].pop("private", None)
    bad = [
        build.File("a.txt", b"made for " + b"Emer" + b"son", 0o644),
        build.File("b.txt", b"user " + b"ej" + b"b here", 0o644),
        build.File("c.txt", b"the " + b"AN" + b"3 drive", 0o644),
        build.File("d.txt", b"plain words only", 0o644),
    ]
    problems = build.forbidden(bad, registry)
    named = {p.split(":")[0] for p in problems}
    assert named == {"a.txt", "b.txt", "c.txt"}


def test_a_shipped_page_naming_an_unshipped_shared_file_stops_the_build():
    registry = {"ship": [], "apps": {}}
    files = [
        build.File("shared/forge.js", b"x", 0o644),
        build.File(
            "apps/x/static/index.html",
            b'<script src="/shared/forge.js"></script>'
            # joined: the source tree ships this test, and its own check
            # would stop on a whole unshipped name here
            + b'<script src="/shared/forge_secret' + b'_tool.js"></script>',
            0o644,
        ),
    ]
    problems = build.missing_shared(files, registry)
    assert len(problems) == 1 and "shared/forge_secret_tool.js" in problems[0]


def test_licence_check_stops_a_denied_package(tmp_path):
    ok = [{"name": "fine", "version": "1", "licence": "MIT"}]
    assert build.licence_problems(tmp_path, ok)["errors"] == []
    bad = ok + [{"name": "sticky", "version": "2", "licence": "GNU Affero GPL v3"}]
    assert build.licence_problems(tmp_path, bad)["errors"]


def test_the_linux_bundle_ships_the_installer_and_the_icon():
    registry = json.loads((ROOT / "release" / "release.json").read_text())
    launch = registry["targets"]["linux-x64"]["launch"]
    assert launch.get("forge_installer.py") == "forge_installer.py"
    assert "assets/icon.png" in registry["ship"]
    for name, target in registry["targets"].items():
        for source in (target.get("launch") or {}).values():
            assert (LAUNCH / source).is_file(), (name, source)


# ---------------------------------------------------------------- Windows setup and README


def test_every_launch_and_setup_file_is_there():
    assert build.launch_problems(build.load_registry()) == []


def test_a_missing_setup_picture_stops_the_build(tmp_path, monkeypatch):
    (tmp_path / "Forge.cmd").write_text("@echo off\r\n")
    (tmp_path / "forge.iss").write_text(
        "[Setup]\nSetupIconFile=forge.ico\n"
        "WizardImageFile=wizard-202.bmp,wizard-404.bmp\n"
        '[Files]\nSource: "{#Bundle}\\*"; DestDir: "{app}"\n'
        'Source: "forge.ico"; DestDir: "{app}"\n'
    )
    (tmp_path / "forge.ico").write_bytes(b"ico")
    (tmp_path / "wizard-202.bmp").write_bytes(b"bmp")
    monkeypatch.setattr(build, "LAUNCH", tmp_path)
    registry = {
        "targets": {
            "windows-x64": {"launch": {"Forge.cmd": "Forge.cmd"}, "setup": "forge.iss"}
        }
    }
    assert build.launch_problems(registry) == [
        "windows-x64: release/launch/wizard-404.bmp is missing"
    ]
    registry["targets"]["windows-x64"]["setup"] = "gone.iss"
    assert build.launch_problems(registry) == [
        "windows-x64: release/launch/gone.iss is missing"
    ]


def test_setup_script_installs_for_the_user_and_keeps_data_unless_asked():
    iss = (LAUNCH / "forge.iss").read_text()
    for line in (
        "AppId=local.forge.Forge",
        "PrivilegesRequired=lowest",
        "DefaultDirName={autopf}\\Forge",
        "DisableDirPage=yes",
    ):
        assert line in iss, line
    # the data question defaults to No and is never asked in a silent uninstall
    assert "MB_YESNO or MB_DEFBUTTON2" in iss
    assert "(CurUninstallStep <> usPostUninstall) or UninstallSilent" in iss
    # old program files are cleared only from a folder that holds Forge
    for line in iss.splitlines():
        if line.startswith("Type: filesandordirs") and "[InstallDelete]" in iss:
            if "{app}\\__pycache__" not in line:
                assert "Check: IsForgeFolder" in line, line
    # shortcuts start Forge.cmd, which turns bytecode files off
    assert iss.count('Filename: "{app}\\Forge.cmd"') == 3


def readmes():
    registry = build.load_registry()
    for name, target in registry["targets"].items():
        for setup in (False, True):
            yield name, target, setup, build.readme_text(registry, target, {}, setup)


def test_readmes_have_no_markers_left():
    import re

    for name, _target, setup, text in readmes():
        assert not re.findall(r"^@[\w-]+@$", text, re.M), (name, setup)
        assert "\n\n\n\n" not in text, (name, setup)


def test_readme_install_steps_per_system():
    for name, target, setup, text in readmes():
        system = target["system"]
        assert ("./Forge/forge --install" in text) == (system == "linux"), name
        assert ("forge --uninstall" in text) == (system == "linux"), name
        made = setup and system == "windows"
        assert ("Forge-Setup-0.2.0.exe" in text) == made, (name, setup)
        if system == "windows":
            assert '"More info", then "Run anyway"' in text
            assert "Forge.cmd" in text
        if system == "linux":
            # the terminal line is the first thing the Install section says
            install = text.split("Install\n-------\n", 1)[1]
            first = next(line for line in install.splitlines() if line.strip())
            assert "terminal" in first
            assert "~/.config/forge\n" not in text and "~/.config/forge," not in text


def test_install_hands_other_options_to_the_forge_it_starts(monkeypatch, tmp_path):
    args, rest = fi.parse_args(["--install", "--port-offset", "1000"])
    assert args.install and rest == ["--port-offset", "1000"]
    for wrong in (
        ["--uninstall", "--port-offset", "1"],
        ["--install", "--no-start", "-x"],
    ):
        with pytest.raises(SystemExit):
            fi.parse_args(wrong)
    seen = {}

    def popen(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw

    monkeypatch.setattr(fi.subprocess, "Popen", popen)
    where = {"local": {"logs": str(tmp_path / "logs")}}
    fi.start(tmp_path / "app", where, rest)
    assert seen["cmd"] == [str(tmp_path / "app" / "forge"), "--port-offset", "1000"]
    assert seen["kw"]["start_new_session"] is True


def test_remove_data_takes_the_window_web_storage_too(tmp_path, home, monkeypatch):
    monkeypatch.setattr(fi.shutil, "which", lambda _n: None)
    env = env_for(home)
    fi.install(make_bundle(tmp_path / "d"), env=env, home=str(home), log=quiet)
    web = [home / ".local" / "share" / fi.WEBVIEW, home / ".cache" / fi.WEBVIEW]
    for folder in web:
        (folder / "WebKitCache").mkdir(parents=True)
    other = home / ".local" / "share" / "forge.py"
    other.mkdir()
    done = fi.uninstall(remove_data=True, yes=True, env=env, home=str(home), log=quiet)
    assert set(map(str, web)) <= set(done["data"])
    assert not any(folder.exists() for folder in web) and other.is_dir()


def test_plain_uninstall_never_points_at_the_removed_program(tmp_path, home):
    env = env_for(home)
    fi.install(make_bundle(tmp_path / "d"), env=env, home=str(home), log=quiet)
    seed_data(home)
    lines = []
    fi.uninstall(env=env, home=str(home), log=lines.append)
    said = "\n".join(lines)
    assert "--remove-data" not in said and "delete them yourself" in said


# ---------------------------------------------------------------- critic round 3


def test_install_copies_only_the_downloads_own_files(tmp_path, home):
    top = make_bundle(tmp_path / "d")
    (top / "apps" / "empty").mkdir(parents=True)
    build.write_file_list(top)
    listed = (top / fi.FILE_LIST).read_text()
    assert "forge_portable.py\n" in listed and "apps/empty/\n" in listed
    # an older Forge unpacked into the same folder left an app behind
    (top / "apps" / "oldapp").mkdir()
    (top / "apps" / "oldapp" / "web_app.py").write_text("old")
    lines = []
    program = fi.install(top, env=env_for(home), home=str(home), log=lines.append)[
        "program"
    ]
    assert (program / "forge_portable.py").is_file()
    assert (program / "apps" / "empty").is_dir()
    assert (program / "runtime" / "bin" / "python3").is_symlink()
    assert not (program / "apps" / "oldapp").exists()
    assert any("Leaving out 1 files" in line for line in lines)


def test_install_refuses_a_download_with_files_missing(tmp_path, home):
    top = make_bundle(tmp_path / "d")
    build.write_file_list(top)
    (top / "forge_serve.py").unlink()
    with pytest.raises(fi.Problem, match="missing 1 of Forge's files"):
        fi.install(top, env=env_for(home), home=str(home), log=quiet)


def test_a_stopped_install_leaves_no_half_copy(tmp_path, home, monkeypatch):
    env = env_for(home)
    fi.install(make_bundle(tmp_path / "one"), env=env, home=str(home), log=quiet)
    program = fi.places(env, str(home))["program"]

    def stopped(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(fi, "copy_listed", stopped)
    with pytest.raises(KeyboardInterrupt):
        fi.install(make_bundle(tmp_path / "two"), env=env, home=str(home), log=quiet)
    assert fi.is_ours(program)
    assert not list(program.parent.glob(".app-*"))


def test_leftovers_of_a_killed_install_are_swept(tmp_path, home):
    env = env_for(home)
    program = fi.install(
        make_bundle(tmp_path / "one"), env=env, home=str(home), log=quiet
    )["program"]
    dead = 2**22 + 12345  # above the kernel's pid limit: never a live process
    half = program.parent / f".app-new-{dead}"
    (half / "apps").mkdir(parents=True)
    # killed between the two renames: the old program is only under its swap name
    program.rename(program.parent / f".app-old-{dead}")
    fi.install(make_bundle(tmp_path / "two"), env=env, home=str(home), log=quiet)
    assert fi.is_ours(program) and not half.exists()
    assert not list(program.parent.glob(".app-*"))


def test_a_running_forge_is_seen_through_a_symlinked_folder(tmp_path, home):
    real = tmp_path / "real"
    (real / "app").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
            str(link / "app" / "forge_portable.py"),
        ]
    )
    try:
        assert fi.running_from(link / "app") == [proc.pid]
        assert fi.running_from(real / "app") == []  # named only through the link
    finally:
        proc.kill()
        proc.wait()


def test_a_relative_xdg_folder_is_ignored(home):
    env = {**env_for(home), "XDG_DATA_HOME": "rel/share"}
    where = fi.places(env, str(home))
    assert where["program"].is_absolute()
    assert where["menu"] == home / ".local/share/applications/local.forge.Forge.desktop"


def test_remove_data_with_no_terminal_to_ask_keeps_everything(tmp_path, home):
    env = env_for(home)
    fi.install(make_bundle(tmp_path / "d"), env=env, home=str(home), log=quiet)
    seed_data(home)

    def no_stdin(_prompt):
        raise RuntimeError("lost sys.stdin")

    done = fi.uninstall(
        remove_data=True, env=env, home=str(home), ask=no_stdin, log=quiet
    )
    assert done.get("declined") and fi.places(env, str(home))["program"].exists()


def test_a_chosen_place_inside_forges_own_folder_is_kept(tmp_path, home, monkeypatch):
    monkeypatch.setattr(fi.shutil, "which", lambda _n: None)
    env = env_for(home)
    fi.install(make_bundle(tmp_path / "d"), env=env, home=str(home), log=quiet)
    seed_data(home)
    config = home / ".config" / "forge-release"
    chosen = config / "mine" / "Forge data"
    chosen.mkdir(parents=True)
    (chosen / "save.json").write_text("mine")
    (config / "where.json").write_text(json.dumps({"root": str(chosen), "id": "x"}))
    lines = []
    fi.uninstall(remove_data=True, yes=True, env=env, home=str(home), log=lines.append)
    assert (chosen / "save.json").read_text() == "mine"
    assert any(line.startswith(f"Keeping {config}") for line in lines)


def test_a_menu_entry_forge_did_not_write_is_never_replaced(tmp_path, home):
    env = env_for(home)
    menu = fi.places(env, str(home))["menu"]
    menu.parent.mkdir(parents=True)
    menu.write_text("[Desktop Entry]\nName=Someone else's\n")
    with pytest.raises(fi.Problem, match="not written by Forge"):
        fi.install(make_bundle(tmp_path / "d"), env=env, home=str(home), log=quiet)
    assert "Someone else's" in menu.read_text()


def test_root_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(fi.os, "geteuid", lambda: 0)
    assert fi.main(["--install"]) == 1
    assert "without sudo" in capsys.readouterr().out


def test_a_trial_forge_still_running_stops_install_and_start(monkeypatch, capsys):
    monkeypatch.setattr(fi, "running_from", lambda _f: [4242])
    called = []
    monkeypatch.setattr(fi, "install", lambda *a, **k: called.append(1))
    assert fi.main(["--install"]) == 1
    assert "close it first" in capsys.readouterr().out and not called


def test_plain_uninstall_takes_an_empty_release_folder_too(tmp_path, home):
    env = env_for(home)
    program = fi.install(
        make_bundle(tmp_path / "d"), env=env, home=str(home), log=quiet
    )["program"]
    fi.uninstall(env=env, home=str(home), log=quiet)
    assert not program.parent.exists()


def test_launcher_finds_install_anywhere_on_the_line(tmp_path):
    top = make_bundle(tmp_path / "d", python=ECHO)
    out = run_launcher(top, "--no-start", "--install")
    assert out[1] == f"arg={top / 'forge_installer.py'}"
    assert out[2:] == ["arg=--no-start", "arg=--install"]
