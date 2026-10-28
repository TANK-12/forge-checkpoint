"""On-demand inspection and bounded scans for Files' Advanced view."""

from __future__ import annotations

import hashlib
import os
import stat
import sys
import time
from pathlib import Path

import fsops

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
import forge_storage as storage  # noqa: E402

try:
    import pwd
    import grp
except ImportError:  # Windows has no Unix owner database.
    pwd = grp = None

SCAN_SECONDS = 3.0
SCAN_ENTRIES = 20000
HASH_BYTES = 1 << 30


def inspect(path: str) -> dict:
    expanded = Path(path).expanduser()
    source = (
        fsops.resolve(path) if expanded in fsops.allowed_roots() else fsops._src(path)
    )
    with storage.directory(str(source.parent)) as parent:
        reading = os.stat(source.name, dir_fd=parent, follow_symlinks=False)
        link = (
            os.readlink(source.name, dir_fd=parent)
            if stat.S_ISLNK(reading.st_mode)
            else None
        )
    try:
        owner = pwd.getpwuid(reading.st_uid).pw_name if pwd else str(reading.st_uid)
    except KeyError:
        owner = str(reading.st_uid)
    try:
        group = grp.getgrgid(reading.st_gid).gr_name if grp else str(reading.st_gid)
    except KeyError:
        group = str(reading.st_gid)
    return {
        "path": str(source),
        "bytes": reading.st_size,
        "allocated": getattr(reading, "st_blocks", 0) * 512,
        "permissions": stat.filemode(reading.st_mode),
        "mode": f"{stat.S_IMODE(reading.st_mode):04o}",
        "owner": owner,
        "group": group,
        "uid": reading.st_uid,
        "gid": reading.st_gid,
        "modified": reading.st_mtime,
        "changed": reading.st_ctime,
        "inode": reading.st_ino,
        "device": reading.st_dev,
        "links": reading.st_nlink,
        "link": link,
    }


def checksum(path: str) -> dict:
    source = fsops.resolve(path)
    with storage.directory(str(source.parent)) as parent:
        descriptor = os.open(
            source.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent
        )
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise fsops.FsError("Choose a regular file to hash")
        if before.st_size > HASH_BYTES:
            raise fsops.FsError("Hashing here is limited to files up to 1 GiB")
        digest = hashlib.sha256()
        deadline = time.monotonic() + SCAN_SECONDS
        count = 0
        while block := stream.read(1 << 20):
            count += len(block)
            if count > HASH_BYTES or time.monotonic() > deadline:
                raise fsops.FsError("Hashing took too long; no partial hash was kept")
            digest.update(block)
        after = os.fstat(stream.fileno())
    current = source.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ) or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino):
        raise fsops.FsError("The file changed while hashing; try again")
    return {"sha256": digest.hexdigest(), "bytes": count}


def usage(path: str) -> dict:
    """Count unique file inodes without following links or crossing filesystems."""
    root = fsops.resolve(path)
    if not root.is_dir():
        raise fsops.FsError("Choose a folder to measure")
    pinned = storage.pin(str(root))
    device = storage.expected_device(pinned)
    pending = [""]
    seen: set[tuple[int, int]] = set()
    total = allocated = entries = skipped = 0
    partial = False
    deadline = time.monotonic() + SCAN_SECONDS
    while pending and not partial:
        folder = pending.pop()
        try:
            with storage.folder(
                pinned, folder, allow_hidden=True
            ) as descriptor, os.scandir(descriptor) as children:
                for child in children:
                    if entries >= SCAN_ENTRIES or time.monotonic() > deadline:
                        partial = True
                        break
                    entries += 1
                    try:
                        reading = child.stat(follow_symlinks=False)
                        identity = (reading.st_dev, reading.st_ino)
                        if child.is_symlink() or reading.st_dev != device:
                            skipped += 1
                        elif child.is_dir(follow_symlinks=False):
                            pending.append((folder + "/" + child.name).lstrip("/"))
                        elif stat.S_ISREG(reading.st_mode) and identity not in seen:
                            seen.add(identity)
                            total += reading.st_size
                            allocated += getattr(reading, "st_blocks", 0) * 512
                    except OSError:
                        skipped += 1
        except (OSError, storage.StorageError):
            skipped += 1
    return {
        "bytes": total,
        "allocated": allocated,
        "files": len(seen),
        "entries": entries,
        "skipped": skipped,
        "partial": partial,
    }


def rename_plan(paths: list[str], find: str, replace: str, prefix: str) -> list[dict]:
    if not paths or len(paths) > 200 or len(set(paths)) != len(paths):
        raise fsops.FsError("Choose between 1 and 200 different files")
    result = []
    targets: set[Path] = set()
    for raw in paths:
        source = fsops._src(raw)
        fsops._guard_not_root(source)
        name = prefix + (source.name.replace(find, replace) if find else source.name)
        if fsops.valid_name(name) != name:
            raise fsops.FsError("A new name has leading or trailing spaces")
        target = source.with_name(name)
        if target in targets or (target != source and os.path.lexists(target)):
            raise fsops.FsError(f"{name} already exists or repeats in this batch")
        targets.add(target)
        reading = source.lstat()
        result.append(
            {
                "path": str(source),
                "name": name,
                "identity": [
                    str(reading.st_dev),
                    str(reading.st_ino),
                    str(reading.st_mtime_ns),
                ],
            }
        )
    return result


def rename_batch(plan: list[dict]) -> dict:
    """Revalidate a preview, then rename without replacing any existing name.

    A late failure returns each completed rename so partial work is visible.
    """
    if not plan or len(plan) > 200:
        raise fsops.FsError("Choose between 1 and 200 files")
    targets: set[Path] = set()
    sources: set[Path] = set()
    checked = []
    for item in plan:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("name"), str)
        ):
            raise fsops.FsError("Invalid rename preview")
        source = fsops._src(item["path"])
        fsops._guard_not_root(source)
        target = source.with_name(fsops.valid_name(item["name"]))
        reading = source.lstat()
        if item.get("identity") != [
            str(reading.st_dev),
            str(reading.st_ino),
            str(reading.st_mtime_ns),
        ]:
            raise fsops.FsError("An item changed after the preview; preview again")
        if (
            source in sources
            or target in targets
            or (source != target and os.path.lexists(target))
        ):
            raise fsops.FsError("Names clash; preview again")
        sources.add(source)
        targets.add(target)
        checked.append((source, target))
    renamed = []
    for source, target in checked:
        try:
            if source != target:
                with storage.directory(str(source.parent)) as parent:
                    reading = os.stat(source.name, dir_fd=parent, follow_symlinks=False)
                    original = next(
                        item for item in plan if item["path"] == str(source)
                    )
                    if original["identity"] != [
                        str(reading.st_dev),
                        str(reading.st_ino),
                        str(reading.st_mtime_ns),
                    ]:
                        raise fsops.FsError(
                            "An item changed after validation; preview again"
                        )
                    storage.rename_new(source.name, target.name, parent)
            renamed.append({"from": str(source), "to": str(target)})
        except (OSError, fsops.FsError, storage.StorageError) as error:
            return {"renamed": renamed, "error": str(error)}
    return {"renamed": renamed, "error": None}
