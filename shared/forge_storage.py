"""Linux file access pinned to a folder and its filesystem, for NAS shares.

All traversal is descriptor-relative and refuses symlinks. A USB mount removed
or replaced at the same path is unavailable, never a fallback destination.
No array, filesystem or existing user file is changed by this module.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import secrets
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

DIRECTORY = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
READ = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
CHUNK = 1 << 20
MAX_FILE = 2 << 30
FREE_FLOOR = 256 << 20


class StorageError(Exception):
    """A storage boundary or availability refusal the caller may display."""

    def __init__(self, message: str = "", status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def parts(raw: str, allow_hidden: bool = False) -> list[str]:
    if (
        not isinstance(raw, str)
        or len(raw) > 1024
        or raw.startswith("/")
        or "\\" in raw
        or "\0" in raw
    ):
        raise StorageError("Choose a path inside the shared folder")
    found = raw.split("/") if raw else []
    if any(
        not name
        or name in (".", "..")
        or (name.startswith(".") and not allow_hidden)
        or len(os.fsencode(name)) > 240
        for name in found
    ):
        raise StorageError("Hidden files and parent paths cannot be shared")
    return found


@contextmanager
def directory(path: str) -> Iterator[int]:
    """Open an absolute directory without following any symlink component."""
    if not sys.platform.startswith("linux"):
        raise StorageError("These protected filesystem tools currently require Linux")
    source = Path(path)
    if not source.is_absolute() or ".." in source.parts:
        raise StorageError("Choose an absolute folder path")
    descriptor = os.open("/", DIRECTORY)
    try:
        for name in source.parts[1:]:
            next_descriptor = os.open(name, DIRECTORY, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        yield descriptor
    finally:
        os.close(descriptor)


def pin(path: str) -> dict:
    real = Path(path).expanduser()
    with directory(str(real)) as descriptor:
        reading = os.fstat(descriptor)
    uuid = ""
    by_uuid = Path("/dev/disk/by-uuid")
    if by_uuid.is_dir():
        for candidate in by_uuid.iterdir():
            try:
                if candidate.stat().st_rdev == reading.st_dev:
                    uuid = candidate.name
                    break
            except OSError:
                continue
    return {
        "path": str(real),
        "device": reading.st_dev,
        "inode": reading.st_ino,
        "uuid": uuid,
    }


def expected_device(pinned: dict) -> int:
    uuid = pinned.get("uuid", "")
    if uuid:
        if "/" in uuid or uuid.startswith("."):
            raise StorageError("Invalid filesystem identity")
        try:
            reading = (Path("/dev/disk/by-uuid") / uuid).stat()
        except OSError:
            raise StorageError(
                "The drive is unavailable; check its cable and mount"
            ) from None
        if not stat.S_ISBLK(reading.st_mode):
            raise StorageError("The saved filesystem identity is not a drive")
        return reading.st_rdev
    return int(pinned["device"])


def verify(pinned: dict, descriptor: int) -> None:
    reading = os.fstat(descriptor)
    current = os.stat(pinned["path"], follow_symlinks=False)
    device = expected_device(pinned)
    if (
        reading.st_dev != device
        or reading.st_ino != pinned["inode"]
        or (current.st_dev, current.st_ino) != (reading.st_dev, reading.st_ino)
    ):
        raise StorageError("The folder or drive changed; reconnect the original drive")


@contextmanager
def folder(
    pinned: dict, relative: str = "", allow_hidden: bool = False
) -> Iterator[int]:
    with directory(pinned["path"]) as root:
        verify(pinned, root)
        descriptor = os.dup(root)
        try:
            for name in parts(relative, allow_hidden):
                next_descriptor = os.open(name, DIRECTORY, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
                if os.fstat(descriptor).st_dev != os.fstat(root).st_dev:
                    raise StorageError("A nested filesystem needs its own share")
            verify(pinned, root)
            yield descriptor
        finally:
            os.close(descriptor)


def entries(pinned: dict, relative: str = "", limit: int = 5000) -> dict:
    found = []
    truncated = False
    with folder(pinned, relative) as descriptor:
        with os.scandir(descriptor) as children:
            for child in children:
                if child.name.startswith("."):
                    continue
                if len(found) >= limit:
                    truncated = True
                    break
                try:
                    reading = child.stat(follow_symlinks=False)
                    if stat.S_ISLNK(
                        reading.st_mode
                    ) or reading.st_dev != expected_device(pinned):
                        continue
                    if not (
                        stat.S_ISDIR(reading.st_mode) or stat.S_ISREG(reading.st_mode)
                    ):
                        continue
                    found.append(
                        {
                            "name": child.name,
                            "directory": stat.S_ISDIR(reading.st_mode),
                            "bytes": reading.st_size,
                            "modified": reading.st_mtime,
                        }
                    )
                except FileNotFoundError:
                    continue
    return {
        "entries": sorted(
            found, key=lambda item: (not item["directory"], item["name"].casefold())
        ),
        "truncated": truncated,
    }


@contextmanager
def read_file(pinned: dict, relative: str) -> Iterator[BinaryIO]:
    names = parts(relative)
    if not names:
        raise StorageError("Choose a file")
    with folder(pinned, "/".join(names[:-1])) as parent:
        descriptor = os.open(names[-1], READ, dir_fd=parent)
        try:
            reading = os.fstat(descriptor)
            if stat.S_ISDIR(reading.st_mode):
                raise StorageError("That is a folder, not a file", 400)
            if not stat.S_ISREG(reading.st_mode) or reading.st_dev != expected_device(
                pinned
            ):
                raise StorageError("Choose a regular file on this drive")
            stream = os.fdopen(descriptor, "rb")
        except BaseException:
            os.close(descriptor)
            raise
        with stream:
            yield stream


def rename_new(source: str, target: str, parent: int) -> None:
    """Publish without a check/rename race, including on FAT/exFAT.

    Unsupported kernels/filesystems fail safely, keeping the staging file.
    """
    try:
        rename = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError:
        raise StorageError(
            "This system cannot safely publish without replacing files"
        ) from None
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    if rename(parent, os.fsencode(source), parent, os.fsencode(target), 1):
        number = ctypes.get_errno()
        if number == errno.EEXIST:
            raise FileExistsError(number, os.strerror(number), target)
        raise OSError(number, os.strerror(number), target)


class Incoming:
    """A bounded upload that keeps its destination directory open throughout."""

    def __init__(self, pinned: dict, relative: str, max_bytes: int = MAX_FILE) -> None:
        names = parts(relative)
        if not names:
            raise StorageError("Choose a file name")
        self.pinned = pinned
        self.relative_parent = "/".join(names[:-1])
        self.name = names[-1]
        self.max_bytes = max_bytes
        self.context = folder(pinned, "/".join(names[:-1]))
        self.parent = self.context.__enter__()
        self.temporary = ".nas-" + secrets.token_hex(12) + ".part"
        try:
            descriptor = os.open(
                self.temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=self.parent,
            )
        except BaseException:
            self.context.__exit__(None, None, None)
            raise
        self.stream = os.fdopen(descriptor, "wb")
        self.digest = hashlib.sha256()
        self.count = 0
        self.closed = False

    def check(self) -> None:
        with folder(self.pinned, self.relative_parent) as current:
            reading = os.fstat(current)
            held = os.fstat(self.parent)
            if (reading.st_dev, reading.st_ino) != (held.st_dev, held.st_ino):
                raise StorageError("The upload folder moved; transfer stopped")

    def write(self, block: bytes) -> None:
        self.count += len(block)
        if self.count > self.max_bytes:
            raise StorageError("This transfer exceeds the file size limit")
        self.check()
        space = os.fstatvfs(self.parent)
        if space.f_bavail * space.f_frsize < len(block) + FREE_FLOOR:
            raise StorageError("Not enough free space; transfer stopped", 507)
        self.stream.write(block)
        self.digest.update(block)

    def finish(self) -> dict:
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.stream.close()
        self.check()
        for number in range(1, 10001):
            candidate = (
                self.name
                if number == 1
                else f"{Path(self.name).stem} ({number}){Path(self.name).suffix}"
            )
            try:
                rename_new(self.temporary, candidate, self.parent)
                os.fsync(self.parent)
                return {
                    "name": candidate,
                    "bytes": self.count,
                    "sha256": self.digest.hexdigest(),
                }
            except FileExistsError:
                continue
        raise StorageError("Too many files already use that name")

    def close(self) -> None:
        if not self.closed:
            self.stream.close()
            self.context.__exit__(None, None, None)
            self.closed = True


def store(
    pinned: dict, relative: str, blocks: Iterator[bytes], max_bytes: int = MAX_FILE
) -> dict:
    incoming = Incoming(pinned, relative, max_bytes)
    try:
        for block in blocks:
            incoming.write(block)
        return incoming.finish()
    finally:
        incoming.close()


def mkdir(pinned: dict, relative: str) -> None:
    names = parts(relative)
    if not names:
        raise StorageError("Choose a new folder name")
    with folder(pinned, "/".join(names[:-1])) as parent:
        os.mkdir(names[-1], mode=0o700, dir_fd=parent)
        os.fsync(parent)
