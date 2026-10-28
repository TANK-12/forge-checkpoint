"""File operations for the Files app, kept free of the web layer so they test cleanly.

Two rules hold for everything here:

- **No path escapes.** Every path from the page goes through `resolve()`, which
  expands `~`, resolves symlinks and `..`, and refuses anything outside the
  allowed roots (home and the removable-drive mount points).
- **Nothing is ever hard-deleted.** Removal is `gio trash` only. If the trash
  refuses (a tmpfs, a read-only drive), the error goes back to the page and
  the file stays where it is. This module has no unlink or rmtree on purpose;
  `tests/test_fsops.py` checks that by reading the source.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import mimetypes
import os
import re
import shutil
import stat
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote

HOME = Path.home()
USER = os.environ.get("USER") or HOME.name

# Where removable drives appear. Only the ones that exist count as roots.
DRIVE_PARENTS = [Path("/run/media") / USER, Path("/media") / USER, Path("/mnt")]

TEXT_EXTS = {
    ".txt",
    ".md",
    ".py",
    ".js",
    ".ts",
    ".json",
    ".css",
    ".html",
    ".htm",
    ".sh",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".yaml",
    ".yml",
    ".xml",
    ".csv",
    ".log",
    ".c",
    ".h",
    ".cpp",
    ".rs",
    ".go",
    ".java",
    ".lua",
    ".gd",
    ".srt",
    ".ass",
    ".rst",
    ".tex",
    ".sql",
    ".desktop",
    ".service",
    ".env",
    ".gitignore",
}
ARCHIVE_EXTS = {".zip", ".tar", ".gz", ".xz", ".bz2", ".7z", ".rar", ".zst"}


class FsError(Exception):
    """A refusal the page should show as-is (bad path, name clash, trash failed)."""


def allowed_roots() -> list[Path]:
    """Home plus any drive mount parent that exists. `FILES_ROOTS` overrides (tests)."""
    env = os.environ.get("FILES_ROOTS")
    if env:
        return [Path(p).resolve() for p in env.split(os.pathsep) if p]
    roots = [HOME.resolve()]
    roots += [p.resolve() for p in DRIVE_PARENTS if p.is_dir()]
    return roots


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def resolve(raw: str) -> Path:
    """Turn a path from the page into a real path inside an allowed root, or refuse."""
    if not raw or "\x00" in raw:
        raise FsError("No path given")
    p = Path(os.path.expanduser(raw))
    if not p.is_absolute():
        raise FsError("Paths must be absolute")
    p = p.resolve()
    if not any(_inside(p, r) for r in allowed_roots()):
        raise FsError(f"{p} is outside the folders Files may touch")
    return p


def _guard_not_root(p: Path) -> None:
    if any(p == r for r in allowed_roots()):
        raise FsError(f"{p} is a top-level folder and can't be changed")


def valid_name(name: str) -> str:
    name = name.strip()
    if not name or name in (".", "..") or "/" in name or "\x00" in name:
        raise FsError("That name isn't allowed")
    if len(name.encode()) > 255:
        raise FsError("That name is too long")
    return name


def kind_of(p: Path, is_dir: bool) -> str:
    if is_dir:
        return "folder"
    ext = p.suffix.lower()
    mime = mimetypes.guess_type(p.name)[0] or ""
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/") or ext in (".mkv", ".webm"):
        return "video"
    if mime.startswith("audio/") or ext in (".flac", ".opus", ".m4a"):
        return "audio"
    if ext == ".pdf":
        return "pdf"
    if ext in ARCHIVE_EXTS:
        return "archive"
    if ext in TEXT_EXTS or mime.startswith("text/") or not ext:
        return "text"
    return "file"


def entry(p: Path) -> dict:
    try:
        st = p.stat()
        is_dir = stat.S_ISDIR(st.st_mode)
        size, mtime = (0 if is_dir else st.st_size), st.st_mtime
    except OSError:
        # A dangling symlink: show it, but as a plain broken file.
        is_dir, size, mtime = False, 0, 0.0
    return {
        "name": p.name,
        "path": str(p),
        "dir": is_dir,
        "size": size,
        "mtime": mtime,
        "kind": kind_of(p, is_dir),
        "hidden": p.name.startswith("."),
        "link": p.is_symlink(),
    }


def list_dir(path: str, hidden: bool = False) -> dict:
    p = resolve(path)
    if not p.is_dir():
        raise FsError(f"{p} is not a folder")
    stamp = p.stat().st_mtime_ns
    items = []
    try:
        with os.scandir(p) as it:
            for de in it:
                if not hidden and de.name.startswith("."):
                    continue
                items.append(entry(Path(de.path)))
    except PermissionError:
        raise FsError(f"No permission to open {p}")
    parent = (
        str(p.parent)
        if any(_inside(p.parent, r) for r in allowed_roots()) and p.parent != p
        else None
    )
    return {"path": str(p), "parent": parent, "items": items, "stamp": stamp}


def folder_stamp(path: str) -> int:
    """The folder's change time in ns: it moves whenever an entry is added,
    removed or renamed inside, so the page can redraw only then."""
    p = resolve(path)
    if not p.is_dir():
        raise FsError(f"{p} is not a folder")
    return p.stat().st_mtime_ns


# ---------------------------------------------------------------- places

_USER_DIRS = re.compile(r'^XDG_([A-Z]+)_DIR="(.*)"$')

# Which XDG folders make the sidebar, in order. Templates/Public stay out.
PLACE_ORDER = [
    "DESKTOP",
    "DOWNLOAD",
    "DOCUMENTS",
    "MUSIC",
    "PICTURES",
    "VIDEOS",
    "PROJECTS",
]
PLACE_ICONS = {
    "DESKTOP": "🖥️",
    "DOWNLOAD": "⬇️",
    "DOCUMENTS": "📄",
    "MUSIC": "🎵",
    "PICTURES": "🖼️",
    "VIDEOS": "🎬",
    "PROJECTS": "🧪",
}


def xdg_dirs() -> dict[str, Path]:
    cfg = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "user-dirs.dirs"
    found: dict[str, Path] = {}
    try:
        for line in cfg.read_text().splitlines():
            m = _USER_DIRS.match(line.strip())
            if m:
                found[m.group(1)] = Path(m.group(2).replace("$HOME", str(HOME)))
    except OSError:
        pass
    return found


def places() -> dict:
    """Sidebar entries, discovered from user-dirs.dirs, ~/Forge and mounted drives."""
    out = [{"label": "Home", "path": str(HOME), "icon": "🏠"}]
    dirs = xdg_dirs()
    for key in PLACE_ORDER:
        p = dirs.get(key)
        if p and p.is_dir() and p != HOME:
            out.append(
                {"label": p.name, "path": str(p), "icon": PLACE_ICONS.get(key, "📁")}
            )
    forge = HOME / "Forge"
    if forge.is_dir():
        out.append({"label": "Forge", "path": str(forge), "icon": "🔥"})
    drives = []
    for parent in DRIVE_PARENTS:
        if not parent.is_dir():
            continue
        try:
            for d in sorted(parent.iterdir()):
                if d.is_dir() and os.path.ismount(d):
                    drives.append({"label": d.name, "path": str(d), "icon": "💾"})
        except OSError:
            continue
    trash = _trash_dir() / "files"
    return {
        "places": out,
        "drives": drives,
        "trash": str(trash) if trash.is_dir() else None,
    }


# ---------------------------------------------------------------- changes


def unique_dest(folder: Path, name: str) -> Path:
    """`name` in `folder`, or `stem (copy).ext`, `stem (copy 2).ext` ... if taken."""
    target = folder / name
    if not os.path.lexists(target):
        return target
    p = Path(name)
    stem, ext = (
        (p.stem, p.suffix)
        if not name.startswith(".") or p.suffix != name
        else (name, "")
    )
    n = 1
    while True:
        label = " (copy)" if n == 1 else f" (copy {n})"
        target = folder / f"{stem}{label}{ext}"
        if not os.path.lexists(target):
            return target
        n += 1


def make_folder(parent: str, name: str) -> str:
    folder = resolve(parent)
    target = folder / valid_name(name)
    if os.path.lexists(target):
        raise FsError(f"{target.name} already exists")
    target.mkdir()
    return str(target)


def rename(path: str, new_name: str) -> str:
    src = _src(path)
    _guard_not_root(src)
    target = src.parent / valid_name(new_name)
    if target == src:
        return str(src)
    if os.path.lexists(target):
        raise FsError(f"{target.name} already exists")
    src.rename(target)
    return str(target)


def _src(path: str) -> Path:
    """Like resolve(), but keeps a symlink itself rather than following it."""
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        raise FsError("Paths must be absolute")
    parent = resolve(str(p.parent))
    src = parent / p.name
    if not os.path.lexists(src):
        raise FsError(f"{src} doesn't exist")
    return src


def trash(paths: list[str]) -> dict:
    """Send each path to the desktop trash with `gio trash`. Never deletes."""
    done, failed = [], []
    for raw in paths:
        try:
            src = _src(raw)
            _guard_not_root(src)
        except FsError as e:
            failed.append({"path": raw, "error": str(e)})
            continue
        r = subprocess.run(
            ["gio", "trash", "--", str(src)], capture_output=True, text=True
        )
        if r.returncode == 0 and not os.path.lexists(src):
            done.append(str(src))
        else:
            msg = r.stderr.strip().split(": ", 1)[-1] or "The trash refused it"
            failed.append({"path": str(src), "error": msg})
    return {"trashed": done, "failed": failed}


def _trash_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share") / "Trash"


def _drop_trashinfo(info: Path) -> None:
    """The one removal in this file: a restored item's .trashinfo record, which
    the trash spec drops when the item leaves the trash. Only ever a
    *.trashinfo file directly inside the trash's info folder."""
    if info.suffix == ".trashinfo" and info.parent == _trash_dir() / "info":
        os.unlink(info)


def _original_path(info: Path) -> Path:
    for line in info.read_text(encoding="utf-8").splitlines():
        if line.startswith("Path="):
            p = Path(unquote(line[5:]))
            if p.is_absolute():
                return p
    raise FsError("The trash has no record of where this came from")


def restore(paths: list[str]) -> dict:
    """Put items from the home trash back where they were (the freedesktop
    trash spec: Trash/info/<name>.trashinfo holds the original path). A name
    that is taken again gets a "(copy)" name; a missing folder is made again.
    Both ends must be inside the folders Files may touch."""
    files_dir = _trash_dir() / "files"
    done, failed = [], []
    for raw in paths:
        try:
            item = Path(os.path.normpath(os.path.expanduser(raw)))
            if item.parent != files_dir or not os.path.lexists(item):
                raise FsError("Only items in the trash can be restored")
            info = _trash_dir() / "info" / f"{item.name}.trashinfo"
            original = _original_path(info)
            existing = original.parent
            while not existing.exists():
                existing = existing.parent
            resolve(str(existing))
            original.parent.mkdir(parents=True, exist_ok=True)
            target = unique_dest(resolve(str(original.parent)), original.name)
            shutil.move(str(item), str(target))
            _drop_trashinfo(info)
            done.append(str(target))
        except (FsError, OSError) as e:
            failed.append({"path": raw, "error": str(e)})
    return {"restored": done, "failed": failed}


def open_default(path: str) -> None:
    p = resolve(path)
    subprocess.Popen(
        ["xdg-open", str(p)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# ---------------------------------------------------------------- drops from outside

# Room an upload must leave free on the drive, so a big drop can't fill it.
UPLOAD_SPARE = 256 * 1024 * 1024

_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


def _load_renameat2():
    """glibc's renameat2, or None where the C library lacks it."""
    try:
        fn = ctypes.CDLL(None, use_errno=True).renameat2
    except (OSError, AttributeError):
        return None
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p]
    fn.argtypes += [ctypes.c_uint]
    fn.restype = ctypes.c_int
    return fn


_renameat2 = _load_renameat2()


def _rename_noreplace(src: Path, dst: Path) -> None:
    """Rename `src` to `dst`, raising FileExistsError if `dst` exists; it never
    replaces a file. One atomic renameat2(RENAME_NOREPLACE) where the kernel
    and filesystem support it. Elsewhere `dst` is first reserved with an
    exclusive create (which refuses an existing file) and `src` renamed over
    that empty reservation, so only a program that writes into the reserved
    name in the instant between the two steps could lose its write."""
    if _renameat2 is not None:
        rc = _renameat2(
            _AT_FDCWD, os.fsencode(src), _AT_FDCWD, os.fsencode(dst), _RENAME_NOREPLACE
        )
        if rc == 0:
            return
        err = ctypes.get_errno()
        if err not in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP):
            raise OSError(err, os.strerror(err), str(dst))
    os.close(os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644))
    os.rename(src, dst)


class Upload:
    """One file dropped in from outside Forge (a desktop drag), arriving over
    HTTP. It is written to a short hidden `.upload-<hex>.part` in the
    destination folder (short, so a 255-byte name still fits) and moved to a
    free name once complete, never over an existing file, even one another
    program made meanwhile. Free space is checked before every chunk, so a
    body without Content-Length can't fill the drive either. An aborted
    upload's partial goes to the trash like any removal here."""

    def __init__(self, dest: str, name: str, size: int | None) -> None:
        folder = resolve(dest)
        if not folder.is_dir():
            raise FsError(f"{folder} is not a folder")
        self.name = valid_name(name)
        if size is not None and size > shutil.disk_usage(folder).free - UPLOAD_SPARE:
            raise FsError(f"Not enough free space on that drive for {self.name}")
        self.folder = folder
        self.part = folder / f".upload-{uuid.uuid4().hex}.part"
        self.file = open(self.part, "xb")
        self.written = 0

    def write(self, chunk: bytes) -> None:
        # Flushed first so the drive's free count includes everything so far.
        self.file.flush()
        if shutil.disk_usage(self.folder).free - len(chunk) < UPLOAD_SPARE:
            # Give the space back now; abort() then trashes the empty stub
            # (trashing a full partial would keep the drive just as full).
            self.file.truncate(0)
            raise FsError(
                f"Not enough free space on that drive for {self.name}; "
                "the upload was stopped"
            )
        self.file.write(chunk)
        self.written += len(chunk)

    def finish(self) -> str:
        self.file.close()
        for _ in range(100):
            target = unique_dest(self.folder, self.name)
            try:
                _rename_noreplace(self.part, target)
            except FileExistsError:
                continue
            return str(target)
        raise FsError(f"Could not find a free name for {self.name}")

    def abort(self) -> None:
        self.file.close()
        if os.path.lexists(self.part):
            trash([str(self.part)])


# ---------------------------------------------------------------- copy / move jobs


@dataclass
class Job:
    op: str
    sources: list[str]
    dest: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    total: int = 0
    done: int = 0
    state: str = "running"
    error: str = ""
    results: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {
            "id": self.id,
            "op": self.op,
            "total": self.total,
            "done": self.done,
            "state": self.state,
            "error": self.error,
            "results": self.results,
            "count": len(self.sources),
            "dest": self.dest,
        }


JOBS: dict[str, Job] = {}


def _tree_size(p: Path) -> int:
    if p.is_symlink() or not p.is_dir():
        return p.lstat().st_size
    total = 0
    for dirpath, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def plan_transfer(op: str, sources: list[str], dest: str) -> tuple[list[Path], Path]:
    """Check a copy/move before it starts. Raises FsError for anything unsafe."""
    if op not in ("copy", "move"):
        raise FsError("Unknown operation")
    folder = resolve(dest)
    if not folder.is_dir():
        raise FsError(f"{folder} is not a folder")
    srcs = [_src(s) for s in sources]
    for s in srcs:
        if op == "move":
            _guard_not_root(s)
        if s.is_dir() and not s.is_symlink() and _inside(folder, s.resolve()):
            raise FsError(f"Can't put {s.name} inside itself")
    return srcs, folder


def run_transfer(job: Job, srcs: list[Path], folder: Path) -> None:
    def count(n: int) -> None:
        job.done += n

    def copy_file(a: str, b: str) -> str:
        out = shutil.copy2(a, b)
        count(os.lstat(a).st_size)
        return out

    try:
        job.total = sum(_tree_size(s) for s in srcs)
        for s in srcs:
            if job.op == "move" and s.parent == folder:
                job.results.append(str(s))  # dropped onto its own folder: nothing to do
                count(_tree_size(s))
                continue
            target = unique_dest(folder, s.name)
            if job.op == "move":
                before, size = job.done, _tree_size(s)
                # shutil.move renames on the same drive and copies then removes across
                # drives; the removal there is of the source it just copied, not a trash.
                shutil.move(str(s), str(target), copy_function=copy_file)
                job.done = before + size
            elif s.is_dir() and not s.is_symlink():
                shutil.copytree(s, target, symlinks=True, copy_function=copy_file)
            elif s.is_symlink():
                os.symlink(os.readlink(s), target)
            else:
                copy_file(str(s), str(target))
            job.results.append(str(target))
        job.state = "done"
    except Exception as e:  # noqa: BLE001 - every failure goes back to the page
        job.state = "error"
        job.error = str(e)


def start_transfer(op: str, sources: list[str], dest: str, wait: bool = False) -> Job:
    srcs, folder = plan_transfer(op, sources, dest)
    job = Job(op=op, sources=[str(s) for s in srcs], dest=str(folder))
    JOBS[job.id] = job
    if wait:
        run_transfer(job, srcs, folder)
    else:
        threading.Thread(
            target=run_transfer, args=(job, srcs, folder), daemon=True
        ).start()
    # Keep the table small: forget finished jobs older than ten minutes.
    cutoff = time.time() - 600
    for k in [
        k for k, j in JOBS.items() if j.state != "running" and j.started < cutoff
    ]:
        JOBS.pop(k, None)
    return job


# ---------------------------------------------------------------- archives

DOUBLE_EXTS = (".tar.gz", ".tar.xz", ".tar.bz2", ".tar.zst")


def _archive_stem(p: Path) -> str:
    low = p.name.lower()
    for ext in DOUBLE_EXTS:
        if low.endswith(ext):
            return p.name[: -len(ext)]
    return p.stem


def _entry_count(srcs: list[Path]) -> int:
    """How many entries a .zip of these items holds: each item and, inside a
    folder, every sub-folder, link and file (bsdtar -v reports each on a line)."""
    n = 0
    for s in srcs:
        n += 1
        if s.is_dir() and not s.is_symlink():
            for _dirpath, dirs, files in os.walk(s):
                n += len(dirs) + len(files)
    return n


def _run_counted(
    job: Job, cmd: list[str], mark: str, names: set[str] | None = None
) -> None:
    """Run a verbose bsdtar, counting its one line per entry (starting with
    `mark`) into job.done for the progress bar; other lines are the error.
    bsdtar reports a failed entry on that entry's own line ("x a.bin: ZIP bad
    CRC", "x big.bin: Write failed"), so an entry line that is not a known
    name and has ": " in it is kept as an error too. `names` (the listing)
    keeps a file that really has ": " in its name from looking like one."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    timer = threading.Timer(3600, proc.kill)
    timer.start()
    other: list[str] = []
    try:
        for line in proc.stderr or []:
            if line.startswith(mark):
                job.done = min(job.total, job.done + 1)
                entry = line[len(mark) :].rstrip("\n")
                if ": " in entry and (names is None or entry not in names):
                    other.append(entry.strip())
            elif line.strip():
                other.append(line.strip())
        code = proc.wait()
    finally:
        timer.cancel()
    if code != 0:
        # "Error exit delayed from previous errors" adds nothing to a reason
        said = [ln for ln in other if "exit delayed" not in ln] or other
        raise FsError("\n".join(said[-3:]) or f"bsdtar stopped ({code})")


def _tree_names(folder: Path, srcs: list[Path]) -> set[str]:
    """The entry names `bsdtar -cv -C folder ./item...` prints for these items."""
    names: set[str] = set()
    for s in srcs:
        names.add(f"./{s.name}")
        if s.is_dir() and not s.is_symlink():
            for dirpath, dirs, files in os.walk(s):
                rel = Path(dirpath).relative_to(folder)
                names.update(f"./{rel / n}" for n in dirs + files)
    return names


def run_archive(job: Job, srcs: list[Path], folder: Path) -> None:
    """Extract into a new folder named after the archive, or compress into a
    .zip beside the items, with bsdtar (libarchive: zip, tar, 7z, rar...).
    bsdtar refuses absolute paths and ".." inside an archive by default.
    Progress counts entries: the archive's listing, or the items' tree."""
    job.total = 1
    try:
        if job.op == "extract":
            src = srcs[0]
            check = subprocess.run(
                ["bsdtar", "-tf", str(src)], capture_output=True, text=True, timeout=600
            )
            if check.returncode != 0:
                raise FsError(check.stderr.strip() or "That archive can't be read")
            lines = [ln for ln in check.stdout.splitlines() if ln.strip()]
            listed = set(lines)
            job.total = max(1, len(lines))
            target = unique_dest(folder, _archive_stem(src) or "archive")
            target.mkdir()
            cmd = ["nice", "-n", "10", "bsdtar", "-xvf", str(src), "-C", str(target)]
            mark = "x "
            names = listed
        else:
            one = srcs[0]
            name = one.name if len(srcs) > 1 or one.is_dir() else one.stem
            target = unique_dest(
                folder, f"{folder.name if len(srcs) > 1 else name}.zip"
            )
            job.total = max(1, _entry_count(srcs))
            cmd = [
                "nice",
                "-n",
                "10",
                "bsdtar",
                "-a",
                "-cvf",
                str(target),
                "-C",
                str(folder),
            ]
            cmd += [f"./{s.name}" for s in srcs]
            mark = "a "
            names = _tree_names(folder, srcs)
        _run_counted(job, cmd, mark, names)
        job.results.append(str(target))
        job.done = job.total
        job.state = "done"
    except Exception as e:  # noqa: BLE001 - every failure goes back to the page
        job.state = "error"
        job.error = str(e)


def start_archive(op: str, sources: list[str], wait: bool = False) -> Job:
    if op not in ("extract", "compress") or not sources:
        raise FsError("Pick something to extract or compress")
    srcs = [_src(s) for s in sources]
    folder = srcs[0].parent
    if op == "extract" and len(srcs) != 1:
        raise FsError("Extract one archive at a time")
    if op == "compress" and any(s.parent != folder for s in srcs):
        raise FsError("Pick items from one folder to compress them together")
    job = Job(op=op, sources=[str(s) for s in srcs], dest=str(folder))
    JOBS[job.id] = job
    if wait:
        run_archive(job, srcs, folder)
    else:
        threading.Thread(
            target=run_archive, args=(job, srcs, folder), daemon=True
        ).start()
    return job


# ---------------------------------------------------------------- search and preview


def search(
    path: str, query: str, hidden: bool = False, limit: int = 400, seconds: float = 4.0
) -> dict:
    """Case-insensitive name search below `path`, bounded by count and time."""
    root = resolve(path)
    q = query.strip().lower()
    if not q:
        raise FsError("Type something to search for")
    found, deadline, truncated = [], time.monotonic() + seconds, False
    for dirpath, dirs, files in os.walk(root):
        if not hidden:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
        dirs[:] = [
            d
            for d in dirs
            if d not in (".venv", "node_modules", "__pycache__", "wineprefix")
        ]
        for name in dirs + files:
            if q in name.lower() and (hidden or not name.startswith(".")):
                found.append(entry(Path(dirpath) / name))
                if len(found) >= limit:
                    truncated = True
                    break
        if truncated or time.monotonic() > deadline:
            truncated = True
            break
    return {"path": str(root), "query": query, "items": found, "truncated": truncated}


def read_text(path: str, limit: int = 64 * 1024) -> dict:
    p = resolve(path)
    if not p.is_file():
        raise FsError("Not a file")
    with open(p, "rb") as f:
        data = f.read(limit + 1)
    if b"\x00" in data[:8192]:
        return {"binary": True, "text": "", "truncated": False}
    return {
        "binary": False,
        "text": data[:limit].decode("utf-8", errors="replace"),
        "truncated": len(data) > limit,
    }


def folder_info(path: str) -> dict:
    p = resolve(path)
    usage = shutil.disk_usage(p)
    return {"free": usage.free, "total": usage.total}


# ---------------------------------------------------------------- thumbnails

CACHE = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache"))
# Thumbnails this app makes itself; $FILES_THUMBS_DIR moves them (a release sets it).
OWN_THUMBS = Path(
    os.environ.get("FILES_THUMBS_DIR") or CACHE / "forge-files" / "thumbs"
)
_ffmpeg_slots = threading.Semaphore(2)


def _png_mtime(png: Path) -> str | None:
    """The Thumb::MTime text chunk of a freedesktop thumbnail, if any."""
    try:
        data = png.read_bytes()[:4096]
    except OSError:
        return None
    i = data.find(b"Thumb::MTime\x00")
    if i < 0:
        return None
    j = i + len(b"Thumb::MTime\x00")
    end = j
    while end < len(data) and data[end : end + 1].isdigit():
        end += 1
    return data[j:end].decode() or None


def thumbnail(path: str) -> Path | None:
    """A small JPEG or PNG for an image, video or PDF: the desktop's own cached one if
    it is current, otherwise one made by ffmpeg (pdftoppm for a PDF's first page)
    into ~/.cache/forge-files."""
    p = resolve(path)
    if not p.is_file():
        return None
    kind = kind_of(p, False)
    if kind not in ("image", "video", "pdf"):
        return None
    mtime = int(p.stat().st_mtime)
    uri = "file://" + quote(str(p))
    digest = hashlib.md5(uri.encode()).hexdigest()
    for size in ("large", "normal"):
        cached = CACHE / "thumbnails" / size / f"{digest}.png"
        if cached.is_file() and _png_mtime(cached) == str(mtime):
            return cached
    own = OWN_THUMBS / f"{digest}-{mtime}.jpg"
    if own.is_file():
        return own
    if kind == "image" and p.stat().st_size < 200_000 and p.suffix.lower() != ".svg":
        return p  # small already; the browser scales it
    OWN_THUMBS.mkdir(parents=True, exist_ok=True)
    if kind == "pdf":
        # -singlefile writes <base>.jpg, which is `own`
        pdf = ["nice", "-n", "15", "pdftoppm", "-jpeg", "-f", "1", "-l", "1"]
        pdf += ["-scale-to", "256", "-singlefile", str(p), str(own.with_suffix(""))]
        with _ffmpeg_slots:
            try:
                subprocess.run(pdf, capture_output=True, timeout=20)
            except (subprocess.TimeoutExpired, OSError):
                return None
        return own if own.is_file() else None
    cmd = ["nice", "-n", "15", "ffmpeg", "-v", "error", "-y"]
    if kind == "video":
        cmd += ["-ss", "3"]
    cmd += [
        "-i",
        str(p),
        "-frames:v",
        "1",
        "-vf",
        "scale=256:-2",
        "-q:v",
        "5",
        str(own),
    ]
    with _ffmpeg_slots:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=20)
            if r.returncode != 0 and kind == "video":
                # Shorter than 3 s: take the first frame.
                cmd.remove("-ss")
                cmd.remove("3")
                subprocess.run(cmd, capture_output=True, timeout=20)
        except (subprocess.TimeoutExpired, OSError):
            # no ffmpeg, or a file it chokes on: the page shows the icon
            return None
    return own if own.is_file() else None
