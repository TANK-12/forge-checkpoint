"""Move a file or folder to the system's trash, on Linux, macOS and Windows.

    from forge_trash import trash, TrashError
    trash(path)          # raises TrashError with a plain reason when it cannot

Linux uses `gio trash` (GNOME, and most other desktops ship gio too). macOS
asks Foundation's NSFileManager (pyobjc, which pywebview brings in a release),
and without it asks the Finder through osascript. Windows uses the shell's
own recycle-bin move (SHFileOperationW with undo allowed), with no dialog
unless the recycle bin cannot take it, when Windows asks before deleting.

Nothing here ever deletes: when no trash is reachable, the path is left where
it is and TrashError says so, so the caller can tell the user.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class TrashError(OSError):
    """The path could not be moved to the trash (it is left in place)."""


def trash(path: str | os.PathLike[str]) -> None:
    """Move `path` (a file, a folder or a link) to the trash."""
    target = Path(os.path.abspath(path))
    if not os.path.lexists(target):
        raise TrashError(f"{target.name} is not there any more")
    if sys.platform == "win32":
        _windows(target)
    elif sys.platform == "darwin":
        _macos(target)
    else:
        _linux(target)
    if os.path.lexists(target):
        raise TrashError(f"{target.name} is still there after moving it to the trash")


def _linux(target: Path) -> None:
    gio = shutil.which("gio")
    if not gio:
        raise TrashError("no trash here: gio is not installed")
    done = subprocess.run(
        [gio, "trash", "--", str(target)], capture_output=True, text=True, timeout=60
    )
    if done.returncode != 0:
        raise TrashError(done.stderr.strip() or "gio trash failed")


def _macos(target: Path) -> None:
    try:
        import Foundation  # type: ignore[import-not-found]
    except ImportError:
        Foundation = None
    if Foundation is not None:
        NSFileManager, NSURL = Foundation.NSFileManager, Foundation.NSURL
        url = NSURL.fileURLWithPath_(str(target))
        (
            ok,
            _,
            error,
        ) = NSFileManager.defaultManager().trashItemAtURL_resultingItemURL_error_(
            url, None, None
        )
        if ok:
            return
        raise TrashError(str(error.localizedDescription()) if error else "trash failed")
    script = (
        "on run argv\n"
        'tell application "Finder" to delete (POSIX file (item 1 of argv) as alias)\n'
        "end run"
    )
    done = subprocess.run(
        ["osascript", "-e", script, str(target)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if done.returncode != 0:
        raise TrashError(done.stderr.strip() or "the Finder did not move it")


def _windows_drive_type(root: str) -> int:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32")  # type: ignore[attr-defined]
    return kernel32.GetDriveTypeW(root)


def _windows(target: Path) -> None:
    import ctypes
    from ctypes import wintypes

    # Only a fixed drive has a recycle bin. On a USB stick or a network share
    # Windows would delete for good, so refuse there before asking it.
    root = os.path.splitdrive(str(target))[0].rstrip("\\") + "\\"
    if _windows_drive_type(root) != 3:  # DRIVE_FIXED
        raise TrashError(
            f"{target.name} is on a drive with no recycle bin, so it was left there"
        )

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    fo_delete = 3
    # FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI, and
    # FOF_WANTNUKEWARNING: where the bin still cannot take it (too big, or
    # turned off for that drive) Windows asks first instead of deleting it.
    flags = 0x0004 | 0x0010 | 0x0040 | 0x0400 | 0x4000
    op = SHFILEOPSTRUCTW()
    op.wFunc = fo_delete
    op.pFrom = str(target) + "\0"  # the list ends with a second NUL
    op.fFlags = flags
    shell32 = ctypes.WinDLL("shell32")  # type: ignore[attr-defined]
    code = shell32.SHFileOperationW(ctypes.byref(op))
    if code != 0 or op.fAnyOperationsAborted:
        raise TrashError(f"the recycle bin refused it (code {code:#x})")
