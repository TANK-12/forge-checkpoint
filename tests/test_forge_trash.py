"""shared/forge_trash.py: a file or folder goes to this system's trash.

The real-trash test runs on whatever system runs it (the release's native
runners run it on macOS and Windows too); the file it trashes is a small
scratch file made for the test in a folder under the home folder, because
gio has no trash for /tmp.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))

import forge_trash  # noqa: E402


def _scratch() -> Path:
    base = Path.home() / ".cache" / "forge-trash-test"
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="t-", dir=base))


def _can_trash_here() -> bool:
    if sys.platform in ("win32", "darwin"):
        return True
    return shutil.which("gio") is not None


@pytest.mark.skipif(not _can_trash_here(), reason="no trash on this system")
@pytest.mark.parametrize("kind", ["file", "folder"])
def test_moves_a_file_or_folder_to_the_trash(kind):
    folder = _scratch()
    try:
        target = folder / f"forge-trash-test-{uuid.uuid4().hex[:8]}"
        if kind == "folder":
            target.mkdir()
            (target / "inside.txt").write_text("x")
        else:
            target.write_text("x")
        forge_trash.trash(target)
        assert not target.exists()
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_a_missing_path_is_an_error(tmp_path):
    with pytest.raises(forge_trash.TrashError, match="not there"):
        forge_trash.trash(tmp_path / "nothing")


def test_an_error_is_an_oserror():
    assert issubclass(forge_trash.TrashError, OSError)


@pytest.mark.skipif(sys.platform in ("win32", "darwin"), reason="the Linux path")
def test_linux_without_gio_leaves_the_file(tmp_path, monkeypatch):
    target = tmp_path / "keep.txt"
    target.write_text("x")
    monkeypatch.setattr(forge_trash.shutil, "which", lambda name: None)
    with pytest.raises(forge_trash.TrashError, match="gio is not installed"):
        forge_trash.trash(target)
    assert target.read_text() == "x"


@pytest.mark.skipif(sys.platform in ("win32", "darwin"), reason="the Linux path")
def test_linux_gio_refusing_leaves_the_file(tmp_path, monkeypatch):
    target = tmp_path / "keep.txt"
    target.write_text("x")

    class Done:
        returncode = 1
        stderr = "Unable to find or create trash directory"

    monkeypatch.setattr(forge_trash.subprocess, "run", lambda *a, **k: Done())
    with pytest.raises(forge_trash.TrashError, match="trash directory"):
        forge_trash.trash(target)
    assert target.read_text() == "x"


@pytest.mark.skipif(sys.platform in ("win32", "darwin"), reason="the Linux path")
def test_a_trash_that_says_yes_but_keeps_the_file_is_an_error(tmp_path, monkeypatch):
    target = tmp_path / "keep.txt"
    target.write_text("x")

    class Done:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(forge_trash.subprocess, "run", lambda *a, **k: Done())
    with pytest.raises(forge_trash.TrashError, match="still there"):
        forge_trash.trash(target)


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows path")
@pytest.mark.parametrize("kind", [2, 4, 0])  # removable, network, unknown
def test_windows_drive_without_a_bin_leaves_the_file(tmp_path, monkeypatch, kind):
    target = tmp_path / "keep.txt"
    target.write_text("kept")
    monkeypatch.setattr(forge_trash, "_windows_drive_type", lambda root: kind)
    with pytest.raises(forge_trash.TrashError, match="no recycle bin"):
        forge_trash.trash(target)
    assert target.read_text() == "kept"


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows path")
def test_windows_asks_about_the_drive_root(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(
        forge_trash, "_windows_drive_type", lambda r: seen.append(r) or 2
    )
    with pytest.raises(forge_trash.TrashError):
        forge_trash.trash(tmp_path)
    assert seen == [str(tmp_path)[:2] + "\\"]
