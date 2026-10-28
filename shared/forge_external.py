"""Apps kept on an external drive.

An app's heavy parts that can be fetched or rebuilt again (its .venv,
node_modules, downloaded models: the manifest's "movable" list) may live on
an external drive from shared/forge_drives.json instead of the laptop, so the
app only opens while that drive is plugged in. The app's code, settings and
everything the user made stay on the laptop.

Moving never loses a file: each part is copied to
<drive>/<folder>/<app>/<path under home>.partial with a sha256 taken while
copying, flushed to the drive and dropped from the page cache, read back and
checked file by file (type, size, mode, link target, sha256), renamed to its
final name, and only then is the laptop copy swapped for a link and removed.
Bringing an app back is the same in reverse.

The link points into STATE_DIR/mounts/<drive>, itself a link that refresh()
points at wherever the partition is mounted now (udisks puts it under
/run/media/<user>/<label>; the backup mounts it under /mnt/forge-drive), so
the app does not care which. A drive that is plugged in but not mounted is
mounted with udisksctl. Where every app is kept is STATE_DIR/placements.json.

forge.py asks check(app) before starting an app: None means it may start,
otherwise the dict names the drive to plug in. The Store moves apps with
move() and back(); `python3 forge_external.py` prints where each is.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import socket
import stat
import subprocess
import time
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
DRIVES_FILE = HERE / "forge_drives.json"
STORES_FILE = HERE / "forge_stores.json"
FORGE_DIR = HERE.parent
APPS_DIR = Path(os.environ.get("FORGE_APPS_DIR") or FORGE_DIR / "apps")
STATE_DIR = Path(
    os.environ.get("FORGE_EXTERNAL_DIR")
    or Path.home() / ".local" / "share" / "forge" / "external"
)
LABEL_DIR = Path("/dev/disk/by-label")
# Parts every app may move without naming them in its manifest.
DEFAULT_MOVABLE = (".venv", "node_modules")
CHUNK = 1 << 20
# Binary file handles on Windows (the Forge release moves its data with these
# functions there too); 0 everywhere else.
BINARY = getattr(os, "O_BINARY", 0)
# Left free on the laptop beyond what is brought back.
LAPTOP_SPARE = 2 * 10**9
# Filesystems that keep what program folders need (permissions, links).
LINUX_FS = ("ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", "jfs", "nilfs2")
# Left free on a drive found plugged in that has no registry entry.
FOUND_KEEP_FREE_GB = 10
FOUND_TTL = 3.0

Log = Callable[[str], None]


class ExternalError(Exception):
    """A move or bring-back that was refused or stopped; nothing was lost."""


# ---------------------------------------------------------------- drives


def registered() -> dict[str, dict]:
    """The drives named in shared/forge_drives.json."""
    try:
        data = json.loads(DRIVES_FILE.read_text())
    except (OSError, ValueError):
        return {}
    found = data.get("drives") if isinstance(data, dict) else None
    return found if isinstance(found, dict) else {}


def _remembered_file() -> Path:
    return STATE_DIR / "drives.json"


def remembered() -> dict[str, dict]:
    """Drives found plugged in (not in the registry) that something was kept
    on, so it is still named while the drive is away."""
    try:
        data = json.loads(_remembered_file().read_text())
    except (OSError, ValueError):
        return {}
    found = data.get("drives") if isinstance(data, dict) else None
    return found if isinstance(found, dict) else {}


def _remember(drive_id: str, d: dict) -> None:
    known = remembered()
    if drive_id in registered() or known.get(drive_id) == d:
        return
    known[drive_id] = {k: v for k, v in d.items() if k != "found"}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = _remembered_file()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"drives": known}, indent=2) + "\n")
    os.replace(tmp, path)


def drive_id_for(label: str) -> str:
    return "drive-" + ("".join(c if c.isalnum() else "-" for c in label.lower()))


_found_cache: dict = {"at": -1e9, "drives": {}}


def found() -> dict[str, dict]:
    """External partitions plugged in now (hot-plug disks such as USB drives,
    with a label), as drive entries keyed by drive_id_for(label). Read with
    lsblk at most every few seconds."""
    now = time.monotonic()
    if now - _found_cache["at"] < FOUND_TTL:
        return _found_cache["drives"]
    try:
        out = subprocess.run(
            ["lsblk", "-J", "-o", "LABEL,FSTYPE,HOTPLUG,TYPE"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
        todo = list(json.loads(out).get("blockdevices") or [])
    except (OSError, ValueError, subprocess.SubprocessError):
        todo = []
    out_drives: dict[str, dict] = {}
    while todo:
        dev = todo.pop(0)
        todo.extend(dev.get("children") or [])
        label, fstype = dev.get("label"), dev.get("fstype")
        hot = dev.get("hotplug") in (True, 1, "1", "true")
        if not (label and fstype and hot) or fstype in ("swap", "crypto_LUKS"):
            continue
        if dev.get("type") not in ("part", "disk"):
            continue
        drive_id = drive_id_for(label)
        n = 2
        while drive_id in out_drives and out_drives[drive_id]["label"] != label:
            drive_id, n = f"{drive_id_for(label)}-{n}", n + 1
        out_drives[drive_id] = {
            "label": label,
            "name": f"the {label} drive",
            "folder": "forge-apps",
            "keep_free_gb": FOUND_KEEP_FREE_GB,
            "fstype": fstype,
            "found": True,
        }
    _found_cache.update(at=now, drives=out_drives)
    return out_drives


def drives() -> dict[str, dict]:
    """Every drive something may be kept on: the registry first, then drives
    remembered from earlier, then any other external drive plugged in now.
    A registered drive that is plugged in carries its filesystem type."""
    here = found()
    by_label = {d["label"]: d for d in here.values()}
    out: dict[str, dict] = {}
    for drive_id, d in list(registered().items()) + list(remembered().items()):
        if drive_id in out or not isinstance(d, dict):
            continue
        seen = by_label.get(d.get("label", ""))
        out[drive_id] = dict(d, fstype=seen["fstype"]) if seen else dict(d)
    labels = {d.get("label") for d in out.values()}
    for drive_id, d in here.items():
        if d["label"] not in labels and drive_id not in out:
            out[drive_id] = d
    return out


def drive(drive_id: str) -> dict:
    d = drives().get(drive_id)
    if not d:
        raise ExternalError(f"no drive called {drive_id!r} is known or plugged in")
    return d


def drive_name(drive_id: str) -> str:
    return (drives().get(drive_id) or {}).get("name") or drive_id


def unusable(d: dict) -> str:
    """Why this drive cannot hold program files, or "" when it can. Folders
    of programs need Linux permissions and links, which FAT, exFAT and NTFS
    drives do not keep."""
    fstype = d.get("fstype") or ""
    if fstype and fstype not in LINUX_FS:
        return (
            f"it is formatted as {fstype}, which cannot keep the permissions and"
            " links programs need; only a Linux format such as ext4 can"
        )
    return ""


def status(drive_id: str) -> dict:
    """For a page: whether the drive is here and ready, why not, and its
    free and total space."""
    d = drive(drive_id)
    out = {
        "id": drive_id,
        "name": d.get("name", drive_id),
        "label": d.get("label", ""),
        "fstype": d.get("fstype", ""),
        "registered": drive_id in registered(),
        "here": plugged_in(d.get("label", "")),
        "mounted": False,
        "ready": False,
        "why": "",
        "free": None,
        "total": None,
        "keep_free": int(float(d.get("keep_free_gb", 0)) * 1e9),
        "room": None,
    }
    mp = find_mount(d.get("label", ""))
    if mp is not None:
        out["mounted"] = True
        try:
            use = shutil.disk_usage(mp)
            out["free"], out["total"] = use.free, use.total
            out["room"] = max(0, use.free - out["keep_free"])
        except OSError:
            pass
    folder = mp / d.get("folder", "forge-apps") if mp is not None else None
    if unusable(d):
        out["why"] = unusable(d)
    elif mp is None:
        out["why"] = (
            "plugged in but not opened (ejected?); open it in Files first"
            if out["here"]
            else "not plugged in"
        )
    elif folder is not None and folder.is_dir() and os.access(folder, os.W_OK):
        out["ready"] = True
    elif os.access(mp, os.W_OK):
        out["ready"] = True  # the folder is made on the first move
    else:
        out["why"] = (
            f"its top folder belongs to the system, so it needs a {d.get('folder', 'forge-apps')}"
            f" folder you own first (once, in a terminal: sudo install -d -o $USER"
            f" {shlex.quote(str(folder))})"
        )
    return out


def find_mount(label: str) -> Path | None:
    """Where the partition with this label is mounted now, or None. Never
    mounts anything."""
    dev = label_dev(label)
    if not label or not dev.exists():
        return None
    out = subprocess.run(
        ["findmnt", "-rno", "TARGET", str(dev.resolve())],
        capture_output=True,
        text=True,
    ).stdout.split("\n")
    for line in out:
        # findmnt escapes spaces as \x20 in raw output
        target = line.strip().replace("\\x20", " ")
        if target and os.path.isdir(target):
            return Path(target)
    return None


def label_dev(label: str) -> Path:
    """The /dev/disk/by-label entry for a label: udev writes a space and any
    other character outside [A-Za-z0-9#+-.:=@_] as \\xNN ("My\\x20Passport")."""
    keep = set("#+-.:=@_")
    out = "".join(
        (
            c
            if (c.isascii() and c.isalnum()) or c in keep or ord(c) > 127
            else f"\\x{ord(c):02x}"
        )
        for c in label
    )
    return LABEL_DIR / out


def plugged_in(label: str) -> bool:
    return bool(label) and label_dev(label).exists()


def _ejected_mark(label: str) -> Path:
    return STATE_DIR / "ejected" / label


def note_ejected(label: str) -> None:
    """The user ejected this partition (the backup app's Eject): it is not
    mounted again behind their back while it stays plugged in."""
    mark = _ejected_mark(label)
    mark.parent.mkdir(parents=True, exist_ok=True)
    mark.touch()


def mount(label: str) -> Path | None:
    """Mount a plugged-in partition the way the file manager would
    (udisksctl, no password for a removable drive), then find it. Not one
    the user ejected, until it is unplugged or mounted again by hand."""
    mark = _ejected_mark(label)
    if not plugged_in(label):
        mark.unlink(missing_ok=True)
        return None
    if mark.exists():
        return None
    subprocess.run(
        [
            "udisksctl",
            "mount",
            "--no-user-interaction",
            "-b",
            str(label_dev(label).resolve()),
        ],
        capture_output=True,
        timeout=30,
    )
    return find_mount(label)


def store_root(drive_id: str, mount_now: bool = True) -> Path | None:
    """The apps folder on the drive, or None while the drive is away."""
    d = drive(drive_id)
    mp = find_mount(d["label"])
    if mp is None and mount_now:
        mp = mount(d["label"])
    if mp is None:
        return None
    _ejected_mark(d["label"]).unlink(missing_ok=True)  # mounted again
    return mp / d.get("folder", "forge-apps")


def link_root(drive_id: str) -> Path:
    """The stable path every moved part links through."""
    return STATE_DIR / "mounts" / drive_id


def refresh(drive_id: str, mount_now: bool = True) -> Path | None:
    """Point mounts/<drive> at the drive's apps folder where it is mounted
    now; returns that folder, or None while the drive is away (the link is
    then left as it was: dangling, which is what an app should see)."""
    root = store_root(drive_id, mount_now)
    if root is None or not root.is_dir():
        return None
    link = link_root(drive_id)
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.path.islink(link) and os.readlink(link) == str(root):
        return root
    tmp = link.with_name(link.name + ".new")
    if os.path.lexists(tmp):
        os.unlink(tmp)
    os.symlink(str(root), tmp)
    os.replace(tmp, link)
    return root


# ---------------------------------------------------------------- placements


def _placements_file() -> Path:
    return STATE_DIR / "placements.json"


def placements() -> dict[str, dict]:
    try:
        data = json.loads(_placements_file().read_text())
    except (OSError, ValueError):
        return {}
    apps = data.get("apps") if isinstance(data, dict) else None
    return apps if isinstance(apps, dict) else {}


def placement(app: str) -> dict | None:
    p = placements().get(app)
    return p if isinstance(p, dict) and p.get("items") else None


def _save(apps: dict[str, dict]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = _placements_file()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"apps": apps}, indent=2) + "\n")
    os.replace(tmp, path)


def _record(app: str, entry: dict | None) -> None:
    apps = placements()
    if entry:
        apps[app] = entry
    else:
        apps.pop(app, None)
    _save(apps)


def sharer(app: str, root: str | Path) -> str | None:
    """Another app whose kept parts sit under this app's root: two Forge apps
    can share one root (Codec Lab and Codec Player), so moving one moves the
    other's .venv too."""
    top = os.path.normpath(os.path.expanduser(str(root)))
    for other, p in placements().items():
        if other == app or p.get("store"):
            continue  # a store waits through _waiting_on_store, if needed
        for item in p.get("items", []):
            if str(item.get("path", "")).startswith(top + "/"):
                return other
    return None


def _moving_file() -> Path:
    return STATE_DIR / "moving.json"


def _note_moving(app: str, root: str | Path | None, drive_id: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _moving_file().write_text(
        json.dumps(
            {
                "app": app,
                "root": os.path.normpath(os.path.expanduser(str(root or ""))),
                "drive": drive_id,
                "pid": os.getpid(),
            }
        )
    )


def moving(app: str, root: str | Path | None = None) -> str | None:
    """The drive id when this app (or one sharing its root) is being copied
    to or from a drive right now, else None."""
    try:
        m = json.loads(_moving_file().read_text())
        os.kill(int(m["pid"]), 0)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    same_root = root is not None and m.get("root") == os.path.normpath(
        os.path.expanduser(str(root))
    )
    return str(m.get("drive", "")) if m.get("app") == app or same_root else None


def check(app: str, root: str | Path | None = None) -> dict | None:
    """None when the app may start (kept on the laptop, or its drive is
    here); otherwise {"drive", "name", "label"} of the drive to plug in,
    with "moving" while it is being copied. With its root, an app that
    shares a root with a kept app waits too, and so does an app whose needed
    store (stores()) is on a drive that is away, with "what" naming it."""
    return _check_own(app, root) or _waiting_on_store(app)


def _waiting_on_store(app: str) -> dict | None:
    for key, p in sorted(placements().items()):
        if not p.get("store") or app not in (p.get("used_by") or []):
            continue
        if not p.get("needed"):
            try:  # the link follows the drive to where it is mounted now
                refresh(p.get("drive", ""), mount_now=False)
            except (ExternalError, OSError, subprocess.SubprocessError):
                pass
            continue
        away = _check_own(key)
        if away:
            return dict(away, what=p.get("label") or key)
    return None


def _check_own(app: str, root: str | Path | None = None) -> dict | None:
    busy = moving(app, root)
    if busy is not None:
        return {
            "drive": busy,
            "name": drive_name(busy),
            "label": (drives().get(busy) or {}).get("label", ""),
            "moving": True,
        }
    p = placement(app)
    if not p and root is not None:
        other = sharer(app, root)
        return _check_own(other) if other else None
    if not p:
        return None
    drive_id = p.get("drive", "")
    missing = {
        "drive": drive_id,
        "name": drive_name(drive_id),
        "label": (drives().get(drive_id) or {}).get("label", ""),
    }
    if p.get("pending"):
        # A swap that a crash cut short is finished or undone, but never
        # while a move is running (it holds the lock and is mid-swap).
        try:
            lock = _lock()
        except ExternalError:
            return dict(missing, moving=True)
        try:
            recover(app)
        except OSError:
            return missing
        finally:
            lock.close()
    try:
        root = refresh(drive_id)
    except (ExternalError, OSError, subprocess.SubprocessError):
        return missing
    if root is None:
        return missing
    for item in p["items"]:
        if not os.path.lexists(root / item["stored"]):
            return missing
    return None


def where(app: str) -> dict:
    """For a page: {"drive": id or "", "name": friendly, "here": bool}."""
    p = placement(app)
    if not p:
        return {"drive": "", "name": "", "here": True}
    drive_id = p.get("drive", "")
    d = drives().get(drive_id) or {}
    return {
        "drive": drive_id,
        "name": drive_name(drive_id),
        "here": bool(d) and find_mount(d.get("label", "")) is not None,
        "bytes": sum(int(i.get("bytes", 0)) for i in p["items"]),
    }


# ---------------------------------------------------------------- stores


def stores() -> list[dict]:
    """Folders of downloaded things (models, assets) that may live on a drive
    on their own, apart from any app: shared/forge_stores.json for folders
    several apps share, and each app's manifest "stores" list for its own.
    An entry is {id, label, kind ("model" or "asset"), paths (a list, or
    one "path"; relative to the Forge folder or the app's root, or starting
    with ~; moved and brought back together), used_by (apps
    that read it; an app's own store defaults to that app), needed (true:
    those apps wait with the plug-in card while it is away; false: they
    open, and code reading it asks require() for a plain message)}. Its
    placement key is <owner>.<id>, owner "shared" for the hub-wide ones."""
    home = Path.home()
    rows: list[dict] = []

    def add(owner: str, root: Path, e: object, used_by: list[str]) -> None:
        if not isinstance(e, dict) or not e.get("id"):
            return
        given = e.get("paths") or ([e["path"]] if e.get("path") else [])
        if not isinstance(given, list) or not given:
            return
        paths = []
        for one in given:
            path = Path(os.path.expanduser(str(one)))
            path = Path(os.path.normpath(path if path.is_absolute() else root / path))
            if home not in path.parents:
                return  # the whole entry, not a part of it
            paths.append(str(path))
        rows.append(
            {
                "key": f"{owner}.{e['id']}",
                "owner": owner,
                "label": str(e.get("label") or e["id"]),
                "kind": str(e.get("kind") or "model"),
                "path": paths[0],
                "paths": paths,
                "used_by": [str(a) for a in (e.get("used_by") or used_by)],
                "needed": bool(e.get("needed")),
            }
        )

    try:
        data = json.loads(STORES_FILE.read_text())
    except (OSError, ValueError):
        data = {}
    for e in (data.get("stores") if isinstance(data, dict) else None) or []:
        add("shared", FORGE_DIR, e, [])
    for mf in sorted(APPS_DIR.glob("*/forge_app.json")):
        try:
            m = json.loads(mf.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict):
            continue
        root = Path(os.path.expanduser(str(m.get("root") or mf.parent)))
        for e in m.get("stores") or []:
            add(mf.parent.name, root, e, [mf.parent.name])
    return rows


def store(key: str) -> dict | None:
    return next((r for r in stores() if r["key"] == key), None)


def store_manifest(row: dict) -> dict:
    """What move() and back() take for a store: its folders, nothing else."""
    return {"movable": list(row["paths"]), "only_listed": True, "port": None}


def store_extra(row: dict) -> dict:
    """What a store's placement keeps, so check() and the hub need nothing else."""
    return {
        "store": True,
        "kind": row["kind"],
        "label": row["label"],
        "used_by": row["used_by"],
        "needed": row["needed"],
    }


def away(path: str | Path) -> dict | None:
    """When this path is (or is inside) something kept on a drive that is not
    here now: {"drive", "name", "label", "what"}; else None."""
    target = os.path.normpath(os.path.abspath(os.path.expanduser(str(path))))
    for key, p in sorted(placements().items()):
        for item in p.get("items", []):
            top = str(item.get("path", ""))
            if not top or not (target == top or target.startswith(top + "/")):
                continue
            if os.path.exists(top):
                return None
            try:  # never mounts: this runs on every read of a store
                if refresh(p.get("drive", ""), mount_now=False) is not None:
                    if os.path.exists(top):
                        return None
            except (ExternalError, OSError, subprocess.SubprocessError):
                pass
            drive_id = p.get("drive", "")
            label = (drives().get(drive_id) or {}).get("label", "")
            return {
                "drive": drive_id,
                "name": drive_name(drive_id),
                "label": label,
                "what": p.get("label") or key,
                "here": plugged_in(label),
            }
    return None


def require(path: str | Path) -> None:
    """Raise ExternalError with a plain message when path is kept on a drive
    that is away, for code that reads a store an app opens without."""
    a = away(path)
    if a and a.get("here"):
        raise ExternalError(
            f"{a['what']}: kept on {a['name']}, which is plugged in but not"
            " opened (ejected?). Open it in Files and try again."
        )
    if a:
        raise ExternalError(
            f"{a['what']}: kept on {a['name']}, which is not plugged in."
            " Plug it in and try again."
        )


def away_for(app: str, placed: dict[str, dict] | None = None) -> list[dict]:
    """The stores this app reads that are on a drive that is away (the hub
    says so when it opens). Cheap: no mounting; `placed` saves a reread."""
    out = []
    for key, p in sorted((placements() if placed is None else placed).items()):
        if not isinstance(p, dict):
            continue
        if not p.get("store") or app not in (p.get("used_by") or []):
            continue
        items = [str(i.get("path", "")) for i in p.get("items", [])]
        if items and all(os.path.exists(i) for i in items):
            continue
        drive_id = p.get("drive", "")
        out.append(
            {"key": key, "what": p.get("label") or key, "name": drive_name(drive_id)}
        )
    return out


# ---------------------------------------------------------------- what moves


def movable(manifest: dict, root: str | Path) -> list[Path]:
    """The app's parts that may live on a drive and exist here now: .venv,
    node_modules and the manifest's "movable" list (relative to the app's
    root, or starting with ~). Each must be under the home folder and not
    the root itself."""
    root = Path(root).expanduser()
    home = Path.home()
    names = ([] if manifest.get("only_listed") else list(DEFAULT_MOVABLE)) + [
        str(n) for n in (manifest.get("movable") or []) if isinstance(n, str)
    ]
    out: list[Path] = []
    for name in names:
        p = Path(os.path.expanduser(name))
        p = p if p.is_absolute() else root / p
        p = Path(os.path.normpath(p))
        if p == root or home not in p.parents:
            continue
        if os.path.islink(p):  # a link holds nothing here (or is kept already)
            continue
        if any(os.path.islink(q) for q in p.parents if home in q.parents):
            continue  # inside a folder that is itself kept on a drive
        if not os.path.lexists(p) or p in out:
            continue
        out.append(p)
    # A part inside another listed part moves with it (a Store app's .venv
    # sits inside its versions folder).
    return [p for p in out if not any(q in p.parents for q in out)]


def stored_name(app: str, path: Path) -> str:
    return f"{app}/{path.relative_to(Path.home())}"


def tree_size(path: Path) -> tuple[int, int]:
    """(bytes, files) under path, links not followed."""
    if path.is_symlink() or path.is_file():
        st = path.lstat()
        return (st.st_size if stat.S_ISREG(st.st_mode) else 0), 1
    total = files = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for name in filenames + [
            d for d in dirnames if os.path.islink(os.path.join(dirpath, d))
        ]:
            st = os.lstat(os.path.join(dirpath, name))
            files += 1
            if stat.S_ISREG(st.st_mode):
                total += st.st_size
    return total, files


def plan(app: str, manifest: dict, root: str | Path) -> dict:
    """What moving this app would move, with sizes; what is already a link
    (already on a drive, or made by hand) is listed apart."""
    items, linked = [], []
    for p in movable(manifest, root):
        if p.is_symlink():
            linked.append(str(p))
            continue
        size, files = tree_size(p)
        items.append({"path": str(p), "bytes": size, "files": files})
    return {
        "app": app,
        "items": items,
        "linked": linked,
        "bytes": sum(i["bytes"] for i in items),
    }


def tracked_in_git(paths: list[str]) -> str:
    """The first file under these paths that a git repository keeps, or "".
    Such a folder must not turn into a link: git would see its files as
    deleted, and the next broad commit would delete them."""
    for p in paths:
        try:
            out = subprocess.run(
                ["git", "-C", os.path.dirname(p), "ls-files", "-z", "--", p],
                capture_output=True,
                text=True,
                timeout=20,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        first = out.split("\0")[0]
        if first:
            return os.path.join(os.path.dirname(p), first)
    return ""


def users_of(paths: list[Path]) -> list[int]:
    """Processes of this user running from, working in, or holding a file
    open under any of these paths (their program, folder, open files and
    mapped libraries), read from /proc. A port check alone misses a test run
    or a helper started by the app."""
    roots = [os.path.realpath(p) for p in paths]

    def under(target: str) -> bool:
        return any(target == r or target.startswith(r + "/") for r in roots)

    me, uid, found = os.getpid(), os.getuid(), []
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        base = f"/proc/{entry.name}"
        try:
            if os.stat(base).st_uid != uid:
                continue
            links = [os.readlink(f"{base}/exe"), os.readlink(f"{base}/cwd")]
            for fd in os.listdir(f"{base}/fd"):
                try:
                    links.append(os.readlink(f"{base}/fd/{fd}"))
                except OSError:
                    pass
            with open(f"{base}/maps") as f:
                links += [line.split(None, 5)[-1].strip() for line in f if "/" in line]
        except OSError:
            continue
        if any(under(t) for t in links):
            found.append(int(entry.name))
    return found


def open_on_drive(label: str) -> list[str]:
    """Apps kept on the drive with this partition label that are open now
    (their port answers, or a process uses their files on it). The backup's
    Eject names them instead of pulling the drive from under them."""
    out = []
    for app, p in sorted(placements().items()):
        if (drives().get(p.get("drive", "")) or {}).get("label") != label:
            continue
        root = link_root(p["drive"])
        stored = [root / i["stored"] for i in p.get("items", []) if i.get("stored")]
        ports = [p.get("port")] + _sharing_ports(app, p)
        if any(port and port_open(int(port)) for port in ports) or (
            stored and users_of(stored)
        ):
            out.append(app)
    return out


def _sharing_ports(app: str, p: dict) -> list:
    """Ports of the other Forge apps (apps/*/forge_app.json) whose root holds
    this app's kept parts: Codec Player runs from Codec Lab's .venv."""
    ports = []
    for path in sorted((HERE.parent / "apps").glob("*/forge_app.json")):
        try:
            m = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if path.parent.name == app or not isinstance(m, dict):
            continue
        top = os.path.normpath(os.path.expanduser(str(m.get("root") or path.parent)))
        if any(str(i.get("path", "")).startswith(top + "/") for i in p["items"]):
            ports.append(m.get("port"))
    return ports


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.3):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------- copy + check


def _drop_cache(fd: int) -> None:
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    except (AttributeError, OSError):
        pass


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | BINARY)
    try:
        _drop_cache(fd)  # read what is on the disk, not what was just written
        with os.fdopen(fd, "rb", closefd=False) as f:
            for block in iter(lambda: f.read(CHUNK), b""):
                h.update(block)
        _drop_cache(fd)
    finally:
        os.close(fd)
    return h.hexdigest()


def _copy_file(src: Path, dst: Path, modes: bool = True) -> str:
    h = hashlib.sha256()
    with open(src, "rb") as fin:
        fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | BINARY, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=False) as fout:
                for block in iter(lambda: fin.read(CHUNK), b""):
                    h.update(block)
                    fout.write(block)
                fout.flush()
                os.fsync(fd)
            _drop_cache(fd)
        finally:
            os.close(fd)
    _copy_stat(src, dst, modes)
    return h.hexdigest()


def _copy_stat(src: Path, dst: Path, modes: bool) -> None:
    """Modes and times as src has them. Without `modes` (a FAT, exFAT or NTFS
    drive, which keeps no Unix modes and may refuse chmod) only the times."""
    try:
        shutil.copystat(src, dst, follow_symlinks=False)
    except OSError:
        if modes:
            raise
        st = src.lstat()
        try:
            os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))
        except OSError:
            pass


def _entries(top: Path, modes: bool = True) -> dict[str, tuple]:
    """rel path -> (kind, size, mode, link target) for everything under top
    (top itself is "."). Links are listed, never followed. Without `modes`
    every mode reads 0 (a drive that keeps none)."""
    out: dict[str, tuple] = {}

    def one(p: Path, rel: str) -> None:
        st = p.lstat()
        mode = stat.S_IMODE(st.st_mode) if modes else 0
        if stat.S_ISLNK(st.st_mode):
            out[rel] = ("link", 0, 0, os.readlink(p))
        elif stat.S_ISDIR(st.st_mode):
            out[rel] = ("dir", 0, mode, "")
        elif stat.S_ISREG(st.st_mode):
            out[rel] = ("file", st.st_size, mode, "")
        else:
            out[rel] = ("other", 0, mode, "")

    one(top, ".")
    if top.is_dir() and not top.is_symlink():
        for dirpath, dirnames, filenames in os.walk(top):
            base = Path(dirpath)
            for name in dirnames + filenames:
                p = base / name
                one(p, str(p.relative_to(top)))
    return out


def copy_tree(
    src: Path, dst: Path, log: Log, label: str, modes: bool = True
) -> dict[str, str]:
    """Copy src (a folder, file or link) to dst, which must not exist.
    Returns rel path -> sha256 of every file as read from src. Without
    `modes` the copy keeps only times (see _copy_stat)."""
    entries = _entries(src, modes)
    odd = [r for r, e in entries.items() if e[0] == "other"]
    if odd:
        raise ExternalError(
            f"{src} holds something that is not a file, folder or link ({odd[0]}); left as it is"
        )
    total = sum(e[1] for e in entries.values()) or 1
    done = 0
    last = time.monotonic()
    hashes: dict[str, str] = {}
    dirs: list[tuple[Path, Path]] = []
    for rel in sorted(entries, key=lambda r: (r != ".", r)):
        kind = entries[rel][0]
        s = src if rel == "." else src / rel
        d = dst if rel == "." else dst / rel
        if kind == "dir":
            d.mkdir(mode=0o700)
            dirs.append((s, d))
        elif kind == "link":
            os.symlink(os.readlink(s), d)
        else:
            hashes[rel] = _copy_file(s, d, modes)
            done += entries[rel][1]
            if time.monotonic() - last > 2:
                last = time.monotonic()
                log(f"{label}: copied {done * 100 // total}%")
    # Folder modes and times last, deepest first, so writing into them
    # earlier did not change their times.
    for s, d in reversed(dirs):
        _copy_stat(s, d, modes)
    return hashes


def verify_tree(
    src_entries: dict[str, tuple],
    hashes: dict[str, str],
    dst: Path,
    modes: bool = True,
) -> None:
    """dst must hold exactly what src held, every file's sha256 read back
    from the disk matching the one taken while copying. src_entries must have
    been read with the same `modes`."""
    got = _entries(dst, modes)
    if set(got) != set(src_entries):
        extra = sorted(set(got) ^ set(src_entries))[:3]
        raise ExternalError(
            f"the copy does not hold the same names ({', '.join(extra)})"
        )
    for rel, want in src_entries.items():
        have = got[rel]
        if have != want:
            raise ExternalError(f"{rel} differs in the copy ({have[0]} vs {want[0]})")
        if (
            want[0] == "file"
            and _hash_file(dst if rel == "." else dst / rel) != hashes[rel]
        ):
            raise ExternalError(f"{rel} reads back differently from the drive")


def _remove_scratch(path: Path) -> None:
    """Remove a half-made copy this module created (never an original)."""
    if os.path.islink(path) or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _remove_original(path: Path) -> None:
    """The laptop's or drive's old copy, once the new one is checked."""
    _remove_scratch(path)


def _lock():
    import fcntl  # Linux only: the release imports this module on Windows too

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    f = open(STATE_DIR / ".lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        raise ExternalError(
            "another move to or from a drive is running; try again after it"
        )
    return f


def _snapshot(path: Path) -> tuple:
    st = path.lstat()
    return (st.st_mtime_ns, st.st_size, st.st_ino)


# ---------------------------------------------------------------- move / back


def _refuse_if_running(
    app: str, manifest: dict, paths: list[Path], running: Callable[[], bool] | None
) -> None:
    port = manifest.get("port")
    if running is not None:
        busy = running()
    else:
        busy = bool(port) and port_open(int(port))
    if busy:
        raise ExternalError(f"{app} is running; close it first")
    pids = users_of(paths)
    if pids:
        raise ExternalError(
            f"{app}'s files are in use (process {', '.join(map(str, pids[:5]))}); close what uses them first"
        )


def _pending(app: str, step: dict | None) -> None:
    """Note the swap about to happen (or clear it), so recover() can finish
    or undo it after a crash."""
    apps = placements()
    entry = apps.get(app) or {}
    if step:
        entry["pending"] = step
    else:
        entry.pop("pending", None)
    if entry:
        apps[app] = entry
    else:
        apps.pop(app, None)
    _save(apps)


def recover(app: str) -> str:
    """Finish or undo a swap a crash cut short. Moving: if the link stands,
    the drive copy was checked, so the old laptop copy goes, but only once
    that copy is seen on the drive (until then the step waits); if the swap
    never began, the drive copy is a spare and goes; otherwise the laptop
    copy is put back. Bringing back: if the checked laptop copy is in place
    the drive copy goes; otherwise the link is put back. Returns what it did
    ("" for nothing)."""
    entry = placements().get(app) or {}
    step = entry.get("pending")
    if not isinstance(step, dict):
        return ""
    path = Path(step["path"])
    aside = Path(step["aside"])
    # the drive copy: where it was written, or through the drive's link
    stored = [i["stored"] for i in entry.get("items", []) if i.get("path") == str(path)]
    copies = [Path(step["final"])] if step.get("final") else []
    copies += [link_root(entry.get("drive", "")) / n for n in stored[:1]]

    def drop_item() -> None:
        items = [i for i in entry.get("items", []) if i.get("path") != str(path)]
        entry.pop("pending", None)
        _record(app, dict(entry, items=items) if items else None)

    if step.get("kind") == "move":
        if os.path.islink(path):
            if os.path.lexists(aside):
                # the laptop copy goes only once the drive copy is seen
                if not any(os.path.isdir(c) for c in copies):
                    return ""
                os.sync()
                _remove_original(aside)
            _pending(app, None)
            return "finished"
        if not os.path.lexists(path) and os.path.lexists(aside):
            os.rename(aside, path)
            drop_item()
            return "undone"
        if os.path.isdir(path) and not os.path.lexists(aside):
            # cut short before the swap began: the drive copy is a spare
            for c in copies[:1]:
                if os.path.lexists(c):
                    _remove_scratch(c)
            drop_item()
            return "undone"
    elif step.get("kind") == "back":
        if os.path.lexists(path) and not os.path.islink(path):
            drop_item()
            if os.path.lexists(aside):
                os.sync()
                _remove_original(aside)
            return "finished"
        if not os.path.lexists(path):
            os.symlink(step["link"], path)
            _pending(app, None)
            return "undone"
    _pending(app, None)
    return ""


def move(
    app: str,
    manifest: dict,
    root: str | Path,
    drive_id: str,
    log: Log = print,
    running: Callable[[], bool] | None = None,
    extra: dict | None = None,
) -> dict:
    """Keep this app's movable parts on the drive. Refuses (and changes
    nothing) while the app runs, when the drive is away, too full or of a
    kind that cannot hold program files. `extra` is kept in the placement
    (a store's kind, label and used_by)."""
    lock = _lock()
    try:
        d = drive(drive_id)
        if unusable(d):
            raise ExternalError(f"{d['name']} cannot hold apps: {unusable(d)}")
        _note_moving(app, root, drive_id)
        recover(app)
        already = placement(app)
        if already:
            raise ExternalError(
                f"{app} is already kept on {drive_name(already['drive'])}"
            )
        todo = plan(app, manifest, root)
        _refuse_if_running(
            app, manifest, [Path(i["path"]) for i in todo["items"]], running
        )
        if not todo["items"]:
            raise ExternalError(f"{app} has nothing here that could move")
        kept = tracked_in_git([i["path"] for i in todo["items"]])
        if kept:
            raise ExternalError(
                f"{kept} is kept in git, so its folder stays on the laptop"
            )
        store_parent = store_root(drive_id)
        if store_parent is None:
            raise ExternalError(f"plug in {d['name']} first")
        if not store_parent.exists() and os.access(store_parent.parent, os.W_OK):
            store_parent.mkdir()  # a drive found plugged in: its folder, once
        store = refresh(drive_id)
        if store is None:
            raise ExternalError(
                f"{d['name']} has no {d.get('folder', 'forge-apps')} folder this user can write to yet"
            )
        if not os.access(store, os.W_OK):
            raise ExternalError(f"cannot write to {store}")
        free = shutil.disk_usage(store).free
        need = todo["bytes"] + int(float(d.get("keep_free_gb", 0)) * 1e9)
        if free < need:
            raise ExternalError(
                f"{d['name']} has {free / 1e9:.1f} GB free; {app} needs {todo['bytes'] / 1e9:.1f} GB"
                f" and {d.get('keep_free_gb', 0)} GB stays free"
            )
        if d.get("found"):
            _remember(drive_id, d)  # still named while it is away
        link = link_root(drive_id)
        moved: list[dict] = []
        base = dict(extra or {}, drive=drive_id, port=manifest.get("port"))
        for item in todo["items"]:
            src = Path(item["path"])
            name = stored_name(app, src)
            final = store / name
            partial = final.with_name(final.name + ".partial")
            if os.path.lexists(final):
                raise ExternalError(f"{final} is already on the drive; left as it is")
            if os.path.lexists(partial):
                _remove_scratch(partial)
            final.parent.mkdir(parents=True, exist_ok=True)
            before = _snapshot(src)
            src_entries = _entries(src)
            log(f"{src.name}: copying {item['bytes'] / 1e6:.0f} MB to {d['name']}")
            try:
                hashes = copy_tree(src, partial, log, src.name)
                log(f"{src.name}: checking the copy")
                verify_tree(src_entries, hashes, partial)
                if _snapshot(src) != before or _entries(src) != src_entries:
                    raise ExternalError(f"{src} changed while it was copied")
            except BaseException:
                _remove_scratch(partial)
                raise
            os.rename(partial, final)
            os.sync()  # the drive copy's folders and names are on the drive
            pids = users_of([src])
            if pids:
                _remove_scratch(final)
                raise ExternalError(
                    f"{src} was opened while it was copied (process {pids[0]}); left on the laptop"
                )
            # Swap: the original is renamed aside first, so a link never
            # stands where files were until the drive copy is in place.
            aside = src.with_name(src.name + ".forge-moving")
            _record(
                app,
                dict(
                    base,
                    moved=time.strftime("%Y-%m-%d %H:%M"),
                    items=moved
                    + [{"path": str(src), "stored": name, "bytes": item["bytes"]}],
                    pending={
                        "kind": "move",
                        "path": str(src),
                        "aside": str(aside),
                        "final": str(final),
                    },
                ),
            )
            os.rename(src, aside)
            os.symlink(str(link / name), src)
            if not src.exists():
                os.unlink(src)
                os.rename(aside, src)
                _record(
                    app,
                    dict(base, items=moved) if moved else None,
                )
                raise ExternalError(
                    f"the link for {src} did not reach the drive; put back"
                )
            moved.append({"path": str(src), "stored": name, "bytes": item["bytes"]})
            _remove_original(aside)
            _pending(app, None)
            log(f"{src.name}: on {d['name']} now")
        return {"app": app, "drive": drive_id, "items": moved, "bytes": todo["bytes"]}
    finally:
        _moving_file().unlink(missing_ok=True)
        lock.close()


def back(
    app: str,
    manifest: dict,
    log: Log = print,
    running: Callable[[], bool] | None = None,
) -> dict:
    """Bring an app's parts back onto the laptop: copy, check, swap the link
    for the folder, then remove the drive copy."""
    lock = _lock()
    try:
        recover(app)
        p = placement(app)
        if not p:
            raise ExternalError(f"{app} is kept on the laptop already")
        drive_id = p["drive"]
        _note_moving(app, None, drive_id)
        store = refresh(drive_id)
        if store is None:
            raise ExternalError(f"plug in {drive_name(drive_id)} first")
        need = sum(int(i.get("bytes", 0)) for i in p["items"]) + LAPTOP_SPARE
        free = shutil.disk_usage(Path.home()).free
        if free < need:
            raise ExternalError(
                f"the laptop has {free / 1e9:.1f} GB free; bringing {app} back needs {need / 1e9:.1f} GB"
            )
        _refuse_if_running(
            app, manifest, [store / i["stored"] for i in p["items"]], running
        )
        left = list(p["items"])
        for item in list(left):
            dest = Path(item["path"])
            stored = store / item["stored"]
            if not os.path.islink(dest):
                raise ExternalError(
                    f"{dest} is not a link to the drive any more; left as it is"
                )
            back_tmp = dest.with_name(dest.name + ".forge-returning")
            if os.path.lexists(back_tmp):
                _remove_scratch(back_tmp)
            src_entries = _entries(stored)
            log(f"{dest.name}: copying back from {drive_name(drive_id)}")
            try:
                hashes = copy_tree(stored, back_tmp, log, dest.name)
                log(f"{dest.name}: checking the copy")
                verify_tree(src_entries, hashes, back_tmp)
            except BaseException:
                _remove_scratch(back_tmp)
                raise
            pids = users_of([stored])
            if pids:
                _remove_scratch(back_tmp)
                raise ExternalError(
                    f"{stored} was opened while it was copied (process {pids[0]}); left on the drive"
                )
            link_text = os.readlink(dest)
            _pending(
                app,
                {
                    "kind": "back",
                    "path": str(dest),
                    "aside": str(stored),
                    "link": link_text,
                },
            )
            os.unlink(dest)
            os.rename(back_tmp, dest)
            os.sync()  # the laptop copy is on disk before the drive's goes
            left.remove(item)
            _record(app, dict(p, items=left) if left else None)
            _remove_original(stored)
            log(f"{dest.name}: on the laptop again")
        prune_empty(store / app, store)
        return {"app": app, "back": [i["path"] for i in p["items"]]}
    finally:
        _moving_file().unlink(missing_ok=True)
        lock.close()


def forget(app: str, store: Path) -> list[Path]:
    """Stop keeping an app on its drive without bringing it back (the Store
    removing the app): its laptop links and drive copies, for the caller to
    send to the trash and then drop() the placement."""
    p = placement(app)
    if not p:
        return []
    out = []
    for item in p["items"]:
        link = Path(item["path"])
        if os.path.islink(link):
            out.append(link)
        out.append(store / item["stored"])
    return out


def drop(app: str) -> None:
    """Forget an app's placement (after forget()'s paths are in the trash)."""
    _record(app, None)


def prune_empty(path: Path, stop: Path) -> None:
    """Remove now-empty folders this module made on the drive."""
    for dirpath in sorted((t[0] for t in os.walk(path)), key=len, reverse=True):
        p = Path(dirpath)
        if p != stop and not any(p.iterdir()):
            p.rmdir()


def main() -> None:
    argparse.ArgumentParser(
        description="List the apps kept on an external drive and whether each is ready."
    ).parse_args()
    for app, p in sorted(placements().items()):
        c = check(app)
        state = "ready" if c is None else f"waiting for {c['name']}"
        size = sum(int(i.get("bytes", 0)) for i in p.get("items", [])) / 1e9
        print(f"{app}: on {drive_name(p.get('drive', ''))}, {size:.1f} GB, {state}")
        for i in p.get("items", []):
            print(f"  {i['path']}")
    if not placements():
        print("every app is kept on the laptop")


if __name__ == "__main__":
    main()
