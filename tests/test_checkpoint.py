"""Check the preview install helpers without opening a desktop window."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def mac_case(tmp_path: Path, arch: str = "arm64") -> tuple[Path, dict[str, str]]:
    """A tiny archive and stand-ins for macOS commands on a Linux test host."""
    home = tmp_path / "home with spaces"
    home.mkdir()
    tools = tmp_path / "tools"
    tools.mkdir()
    for name, script in {
        "uname": f'#!/bin/sh\ncase "$1" in -s) echo Darwin;; -m) echo {arch};; esac\n',
        "ditto": '#!/bin/sh\ncp -R "$1" "$2"\n',
        "sysctl": "#!/bin/sh\necho 0\n",
    }.items():
        path = tools / name
        path.write_text(script)
        path.chmod(0o755)
    downloads = tmp_path / "downloads with spaces"
    downloads.mkdir()
    archive = (
        downloads / f"forge-0.2.0-macos-{arch if arch == 'arm64' else 'x64'}.tar.gz"
    )
    with tarfile.open(archive, "w:gz") as bundle:
        for name, data, mode in (
            ("Contents/MacOS/Forge", b"#!/bin/sh\nexit 0\n", 0o755),
            ("Contents/Info.plist", b"fixture", 0o644),
        ):
            entry = tarfile.TarInfo("Forge/Forge.app/" + name)
            entry.size = len(data)
            entry.mode = mode
            bundle.addfile(entry, io.BytesIO(data))
    write_checksum(archive)
    env = dict(
        os.environ, HOME=str(home), PATH=str(tools) + os.pathsep + os.environ["PATH"]
    )
    return archive, env


def write_checksum(archive: Path) -> None:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (archive.parent / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n")


def install_mac(
    archive: Path, env: dict[str, str], *extra: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(ROOT / "scripts/install-macos.sh"), str(archive), *extra],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX installer fixture")
@pytest.mark.parametrize("arch", ["arm64", "x86_64"])
def test_mac_installs_matching_archive_with_spaces(tmp_path: Path, arch: str) -> None:
    archive, env = mac_case(tmp_path, arch)
    done = install_mac(archive, env)
    assert done.returncode == 0, done.stderr
    installed = Path(env["HOME"]) / "Applications/Forge.app/Contents/MacOS/Forge"
    assert installed.is_file() and os.access(installed, os.X_OK)
    assert "Installed:" in done.stdout


@pytest.mark.skipif(os.name == "nt", reason="POSIX installer fixture")
def test_mac_detects_apple_silicon_in_rosetta_terminal(tmp_path: Path) -> None:
    archive, env = mac_case(tmp_path)
    (tmp_path / "tools/uname").write_text(
        '#!/bin/sh\ncase "$1" in -s) echo Darwin;; -m) echo x86_64;; esac\n'
    )
    sysctl = tmp_path / "tools/sysctl"
    sysctl.write_text("#!/bin/sh\necho 1\n")
    sysctl.chmod(0o755)
    done = install_mac(archive, env)
    assert done.returncode == 0, done.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX installer fixture")
def test_mac_keeps_existing_destination(tmp_path: Path) -> None:
    archive, env = mac_case(tmp_path)
    destination = tmp_path / "existing.app"
    destination.mkdir()
    marker = destination / "my save"
    marker.write_text("keep")
    done = install_mac(archive, env, str(destination))
    assert done.returncode != 0
    assert "already exists" in done.stderr
    assert marker.read_text() == "keep"


@pytest.mark.skipif(os.name == "nt", reason="POSIX installer fixture")
@pytest.mark.parametrize(
    "failure",
    ["missing checksum", "wrong checksum", "wrong architecture", "incomplete archive"],
)
def test_mac_refuses_bad_download(tmp_path: Path, failure: str) -> None:
    archive, env = mac_case(tmp_path)
    if failure == "missing checksum":
        (archive.parent / "SHA256SUMS").unlink()
    elif failure == "wrong checksum":
        archive.write_bytes(archive.read_bytes() + b"changed")
    elif failure == "wrong architecture":
        other = archive.with_name("forge-0.2.0-macos-x64.tar.gz")
        archive.rename(other)
        archive = other
    else:
        with tarfile.open(archive, "w:gz"):
            pass
        write_checksum(archive)
    done = install_mac(archive, env)
    assert done.returncode != 0, done.stdout
    assert not (Path(env["HOME"]) / "Applications/Forge.app").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX installer fixture")
def test_mac_rejects_non_mac_host(tmp_path: Path) -> None:
    archive, env = mac_case(tmp_path)
    (tmp_path / "tools/uname").write_text("#!/bin/sh\necho Linux\n")
    done = install_mac(archive, env)
    assert done.returncode != 0
    assert "Run this installer on macOS" in done.stderr


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows PowerShell")
@pytest.mark.parametrize("trailing_separator", [False, True])
def test_windows_installs_and_refuses_overwrite(
    tmp_path: Path, trailing_separator: bool
) -> None:
    shell = shutil.which("powershell")
    assert shell, "Windows PowerShell is required for the helper"
    archive = tmp_path / "forge-0.2.0-windows-x64.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("Forge/Forge.cmd", "@echo off\r\n")
    write_checksum(archive)
    destination = tmp_path / "program with spaces"
    command = [
        shell,
        "-NoProfile",
        "-File",
        str(ROOT / "scripts/install-windows.ps1"),
        "-Archive",
        str(archive),
        "-Destination",
        str(destination) + (os.sep if trailing_separator else ""),
    ]
    # A pwsh parent gives Python module paths Windows PowerShell cannot load.
    # Let the child construct its own standard module search path.
    env = {
        key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"
    }
    done = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert (destination / "Forge.cmd").is_file()
    again = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
    assert again.returncode != 0
    assert (destination / "Forge.cmd").is_file()
