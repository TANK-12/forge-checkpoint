"""Install Forge on Linux, or take it out again.

    ./Forge/forge --install          copy Forge to your home folder, add it to
                                     the apps menu and start it
    ./Forge/forge --install --no-start
    forge --uninstall                take the program and its menu entry out;
                                     your things stay
    forge --uninstall --remove-data  also remove Forge's own folders on this
                                     computer (it names them and asks first)

The launcher script beside this file (`forge`) hands --install and
--uninstall here. The program goes to ~/.local/share/forge-release/app (the
release's own folder, never ~/.local/share/forge, which a Forge built from
source uses), its menu entry is local.forge.Forge.desktop (a name no other
launcher uses, so an existing forge.desktop is never replaced), and the
icon is the installed copy's assets/icon.png. Where the user's things are
kept is forge_portable's business (local_dirs and the pointer file): this
file only reads it, to say where they are and to leave a chosen drive or
folder alone.

A newer version installs over an older one: the new copy is made beside the
old one and the two swap places, so a failed copy leaves the old Forge
working. A program folder is only replaced or removed when it holds the
marker file this installer writes (MARKER), never a folder it did not make.
Only the files the download lists (FILE_LIST, written by release/build.py)
are copied, so a download unpacked over an older Forge's folder installs
this version alone.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
APP_ID = "local.forge.Forge"  # the menu entry's name (reverse DNS, unique)
PROGRAM = "app"  # the program's folder inside the release's data folder
MARKER = ".forge-install.json"  # in a program folder this installer made
WEBVIEW = "forge_portable.py"  # the folders WebKitGTK names after the program
NEEDS = ("forge", "forge_portable.py", "runtime/bin/python3")  # a whole Forge
FILE_LIST = "release/files.txt"  # every file of the download, one per line
ROOM = 1.2  # the copy needs this times the folder's size free


def portable():
    """forge_portable beside this file (the bundle's top folder): its folder
    names are the ones Forge itself uses."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import forge_portable  # type: ignore[import-not-found]

    return forge_portable


def places(env=None, home: str | None = None) -> dict:
    """Where the program, its menu entry and the release's own folders are.
    A relative XDG_* folder is ignored, as the base directory spec says."""
    env = os.environ if env is None else env
    env = {k: v for k, v in env.items() if not k.startswith("XDG_") or os.path.isabs(v)}
    home = home or env.get("HOME") or os.path.expanduser("~")
    fp = portable()
    local = fp.local_dirs("linux", env, home)
    share = Path(env.get("XDG_DATA_HOME") or Path(home) / ".local" / "share")
    return {
        "program": Path(local["computer"]) / PROGRAM,
        "menu": share / "applications" / f"{APP_ID}.desktop",
        "local": local,
        "name": fp.LINUX_NAME,
        "place": Path(local["computer"]) / fp.PLACE_NAME,
    }


def version_of(folder: Path) -> str:
    """The version a Forge folder carries (its release/release.json)."""
    try:
        data = json.loads((folder / "release" / "release.json").read_text("utf-8"))
        return str(data.get("version") or "")
    except (OSError, ValueError):
        return ""


def is_whole(folder: Path) -> bool:
    return all((folder / need).exists() for need in NEEDS)


def is_ours(folder: Path) -> bool:
    """A program folder this installer made (it holds MARKER)."""
    return (folder / MARKER).is_file()


def running_from(folder: Path) -> list[int]:
    """Processes started from inside the folder (a Forge running from it),
    other than this one. The launcher names the folder as the shell sees it,
    so a path through a symlink counts as well as the real one."""
    me = os.getpid()
    prefixes = {
        str(folder).rstrip("/").encode() + b"/",
        str(folder.resolve()).encode() + b"/",
    }
    found = []
    for proc in Path("/proc").glob("[0-9]*"):
        pid = int(proc.name)
        if pid == me:
            continue
        try:
            words = (proc / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if any(
            w.endswith(b"forge_portable.py") and w.startswith(tuple(prefixes))
            for w in words
        ):
            found.append(pid)
    return sorted(found)


def listed_files(src: Path) -> list[str] | None:
    """The files the download holds (FILE_LIST; folders end in "/"), or None
    for a Forge folder without the list (one run from the source tree)."""
    try:
        text = (src / FILE_LIST).read_text("utf-8")
    except OSError:
        return None
    out = [line for line in text.splitlines() if line and not line.startswith("#")]
    for rel in out:
        part = Path(rel)
        if part.is_absolute() or ".." in part.parts:
            raise Problem(f"{FILE_LIST} names {rel}: unpack the download again")
    return out


def extra_files(src: Path, listed: list[str]) -> int:
    """Files in the unpacked folder that the download does not hold (an
    older Forge unpacked into the same folder leaves its own behind)."""
    known = set(listed) | {FILE_LIST}
    count = 0
    for top, _dirs, files in os.walk(src):
        for name in files:
            if os.path.relpath(os.path.join(top, name), src) not in known:
                count += 1
    return count


def copy_listed(src: Path, dest: Path, listed: list[str] | None) -> None:
    """Copy the download's files to dest (a new folder): only those listed,
    or the whole folder when there is no list."""
    if listed is None:
        shutil.copytree(src, dest, symlinks=True)
        return
    dest.mkdir()
    for rel in listed:
        source, target = src / rel, dest / rel
        if rel.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            os.symlink(os.readlink(source), target)
        else:
            shutil.copy2(source, target)
    shutil.copy2(src / FILE_LIST, dest / FILE_LIST)


def sweep(program: Path) -> None:
    """Leftovers of an install or uninstall that was stopped half way (the
    process that made them is gone): an old program folder whose swap was
    cut short goes back in place, the rest is removed."""
    left = []
    for spot in program.parent.glob(f".{PROGRAM}-*-*"):
        kind, _, pid = spot.name[len(PROGRAM) + 2 :].rpartition("-")
        if kind not in ("new", "old", "removing") or not pid.isdigit():
            continue
        if Path(f"/proc/{pid}").exists() or spot.is_symlink() or not spot.is_dir():
            continue
        left.append((kind, spot))
    for kind, spot in sorted(left):
        if kind == "old" and not program.exists() and is_ours(spot):
            spot.rename(program)
        else:
            shutil.rmtree(spot, ignore_errors=True)


def folder_bytes(folder: Path) -> int:
    total = 0
    for top, _dirs, files in os.walk(folder):
        for name in files:
            try:
                total += os.lstat(os.path.join(top, name)).st_size
            except OSError:
                pass
    return total


def free_bytes(path: Path) -> int:
    """Free room on the drive that holds `path` (or its nearest parent)."""
    while not path.exists() and path != path.parent:
        path = path.parent
    return shutil.disk_usage(path).free


def exec_quoted(path: Path) -> str:
    """A path as one argument of a menu entry's Exec line: quoted, with the
    characters the desktop entry spec reserves escaped (and the backslash
    escaped once more, as every string value needs)."""
    text = str(path)
    for ch in ("\\", '"', "`", "$"):
        text = text.replace(ch, "\\" + ch)
    return '"' + text.replace("\\", "\\\\").replace("%", "%%") + '"'


def plain_value(text: str) -> str:
    """A desktop entry string value: backslashes, new lines and tabs escaped."""
    return (
        text.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )


def menu_entry(program: Path, version: str) -> str:
    """The menu entry for an installed Forge."""
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.5",
        "Name=Forge",
        "GenericName=App hub",
        "Comment=Many small local apps in one window: games, creative tools,"
        " readers and research helpers",
        f"Exec={exec_quoted(program / 'forge')}",
        f"TryExec={plain_value(str(program / 'forge'))}",
        f"Icon={plain_value(str(program / 'assets' / 'icon.png'))}",
        f"Path={plain_value(str(program))}",
        "Terminal=false",
        "Categories=Utility;",
        "Keywords=forge;apps;games;tools;",
        "StartupNotify=true",
        # the GTK window's name until the launcher names it APP_ID itself
        "StartupWMClass=forge_portable.py",
        f"X-Forge-Version={plain_value(version)}",
        "X-Forge-Install=true",
    ]
    return "\n".join(lines) + "\n"


def is_our_entry(path: Path) -> bool:
    try:
        return "\nX-Forge-Install=true\n" in path.read_text("utf-8", "replace")
    except OSError:
        return False


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


class Problem(Exception):
    """Something the user has to sort out; the text says what to do."""


def install(
    src: Path = HERE,
    env=None,
    home: str | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    """Copy the Forge folder `src` to the install place and add the menu
    entry. Returns {"program", "menu", "version", "copied"}; raises Problem
    with a plain sentence when it cannot."""
    where = places(env, home)
    program, menu = where["program"], where["menu"]
    src = src.resolve()
    if not is_whole(src):
        raise Problem(
            f"{src} is not a whole Forge folder (it needs {', '.join(NEEDS)}):"
            " unpack the download again and run its forge --install"
        )
    version = version_of(src)
    if program.parent.is_dir():
        sweep(program)
    if menu.exists() and not is_our_entry(menu):
        raise Problem(
            f"{menu} is already there and was not written by Forge's installer:"
            " move it somewhere else, then run this again"
        )
    copied = src != program.resolve()
    if copied:
        if program.exists() and not is_ours(program):
            raise Problem(
                f"{program} is already there and was not made by Forge's"
                " installer: move it somewhere else, then run this again"
            )
        busy = running_from(program) if program.exists() else []
        if busy:
            raise Problem(
                "Forge is running from where it is installed: close Forge"
                f" (process {', '.join(map(str, busy))}), then run this again"
            )
        listed = listed_files(src)
        if listed is not None:
            lost = [r for r in listed if not os.path.lexists(src / r.rstrip("/"))]
            if lost:
                raise Problem(
                    f"the unpacked folder is missing {len(lost)} of Forge's files"
                    f" ({lost[0]} and more): unpack the download again"
                )
            extra = extra_files(src, listed)
            if extra:
                log(
                    f"Leaving out {extra} files in {src} that are not part of"
                    f" Forge {version} (an older Forge unpacked into the same"
                    " folder?)"
                )
        size = (
            folder_bytes(src)
            if listed is None
            else sum(os.lstat(src / r).st_size for r in listed if not r.endswith("/"))
        )
        need = int(size * ROOM)
        free = free_bytes(program.parent)
        if free < need:
            raise Problem(
                f"not enough room: installing needs {need / 1e6:.0f} MB and the"
                f" drive holding {program.parent} has {free / 1e6:.0f} MB free"
            )
        old = version_of(program) if program.exists() else ""
        log(
            f"Installing Forge {version} in {program}"
            + (f" (replacing {old or 'an older Forge'})" if program.exists() else "")
        )
        program.parent.mkdir(parents=True, exist_ok=True)
        fresh = program.with_name(f".{PROGRAM}-new-{os.getpid()}")
        stale = program.with_name(f".{PROGRAM}-old-{os.getpid()}")
        try:
            copy_listed(src, fresh, listed)
            write_marker(fresh, version, src)
            if program.exists():
                program.rename(stale)
            fresh.rename(program)
        except BaseException as e:  # Ctrl-C too: never leave a half copy
            if not program.exists() and stale.exists():
                stale.rename(program)  # the old Forge stays as it was
            shutil.rmtree(fresh, ignore_errors=True)
            if isinstance(e, OSError):
                raise Problem(f"the copy failed ({e}); nothing was changed")
            raise
        shutil.rmtree(stale, ignore_errors=True)
    else:
        log(f"Forge {version} is already installed in {program}")
        write_marker(program, version, src, keep=True)
    write_atomic(menu, menu_entry(program, version))
    log(f"Added Forge to your apps menu ({menu.name})")
    return {"program": program, "menu": menu, "version": version, "copied": copied}


def write_marker(folder: Path, version: str, src: Path, keep: bool = False) -> None:
    path = folder / MARKER
    if keep and path.is_file():
        return
    path.write_text(
        json.dumps(
            {
                "version": version,
                "installed": dt.datetime.now().isoformat(timespec="seconds"),
                "from": str(src),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def kept_place(where: dict) -> Path:
    """The folder that holds the user's things: the pointer's choice, else
    this computer's default place."""
    fp = portable()
    pointer = fp.read_json(where["local"]["pointer"]) or {}
    root = pointer.get("root") if isinstance(pointer, dict) else None
    return Path(root) if root else where["place"]


def own_folders(where: dict) -> list[Path]:
    """The release's own folders on this computer that exist: each is named
    after the release (forge-release), or is the window's web storage and
    cache (WEBVIEW, the name WebKitGTK gives them), so nothing else can be
    among them."""
    local = where["local"]
    spots = [
        Path(local["pointer"]).parent,
        Path(local["computer"]),
        Path(local["cache"]),
        Path(local["state"]),
        Path(local["computer"]).parent / WEBVIEW,
        Path(local["cache"]).parent / WEBVIEW,
    ]
    out = []
    for spot in spots:
        named = spot.name in (where["name"], WEBVIEW)
        if named and spot.is_dir() and not spot.is_symlink() and spot not in out:
            out.append(spot)
    return out


def inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def remove(path: Path) -> str:
    """Move a folder to the Trash when the desktop has one, else delete it.
    Says which."""
    gio = shutil.which("gio")
    if gio:
        done = subprocess.run(
            [gio, "trash", str(path)], capture_output=True, text=True, check=False
        )
        if done.returncode == 0 and not path.exists():
            return "moved to the Trash"
    shutil.rmtree(path)
    return "deleted"


def uninstall(
    remove_data: bool = False,
    yes: bool = False,
    env=None,
    home: str | None = None,
    ask: Callable[[str], str] = input,
    log: Callable[[str], None] = print,
) -> dict:
    """Take the program and its menu entry out; with remove_data, also the
    release's own folders on this computer, after naming them (ask() must
    answer "yes" or "y" unless yes=True; another answer removes only the
    program, and no terminal to ask in removes nothing). A place the user
    chose elsewhere (a drive or another folder) is never touched."""
    where = places(env, home)
    program, menu = where["program"], where["menu"]
    done: dict = {"program": False, "menu": False, "data": []}
    if program.exists():
        if not is_ours(program):
            raise Problem(
                f"{program} was not made by Forge's installer, so it is left"
                " alone; nothing was removed"
            )
        busy = running_from(program)
        if busy:
            raise Problem(
                f"Forge is running (process {', '.join(map(str, busy))}): close"
                " it, then run this again; nothing was removed"
            )
    place = kept_place(where)
    folders = own_folders(where) if remove_data else []
    if place.resolve() != where["place"].resolve():
        # a place the user chose stays, even inside one of Forge's folders
        for folder in [f for f in folders if inside(place, f)]:
            log(f"Keeping {folder}: the place you chose for your things is in it")
            folders.remove(folder)
    if folders:
        # asked before anything goes: the program may be this very Python
        log("These folders and everything in them will be removed:")
        for folder in folders:
            log(f"  {folder}")
        if not yes:
            try:
                answer = ask("Type yes to remove them, anything else to keep them: ")
            except (EOFError, OSError, RuntimeError):  # no terminal to ask in
                log("Kept everything; nothing was removed")
                done["declined"] = True
                return done
            if answer.strip().lower() not in ("y", "yes"):
                # the program still goes: that was asked for (critic round F1,
                # Relay task 405: a "y" kept Forge installed)
                log("Keeping those folders; removing only the program")
                done["declined"] = True
                folders, remove_data = [], False
    if menu.exists():
        if is_our_entry(menu):
            menu.unlink()
            done["menu"] = True
            log(f"Took Forge out of your apps menu ({menu.name})")
        else:
            log(f"Left {menu} alone: Forge's installer did not write it")
    if program.exists():
        gone = program.with_name(f".{PROGRAM}-removing-{os.getpid()}")
        program.rename(gone)
        shutil.rmtree(gone)
        done["program"] = True
        log(f"Removed the program ({program})")
        try:
            program.parent.rmdir()  # only when nothing else is in it
        except OSError:
            pass
    elif not done["menu"]:
        log(f"Forge is not installed in {program}")
    if not remove_data:
        if place.exists():
            log(f"Your things are kept in {place}")
        left = own_folders(where)
        if left:
            log(
                "Forge's own folders on this computer stay too ("
                + ", ".join(map(str, left))
                + "): delete them yourself if you no longer want them"
            )
        return done
    if not folders:
        log("Forge has no folders of its own left on this computer")
    for folder in folders:
        if folder.exists():
            how = remove(folder)
            done["data"].append(str(folder))
            log(f"{folder}: {how}")
    if place.exists() and not any(inside(place, f) for f in folders):
        log(
            f"Your things in {place} were not touched (a place you chose);"
            " remove that folder yourself if you no longer want it"
        )
    return done


def start(program: Path, where: dict, extra: list[str] | None = None) -> None:
    """Start the installed Forge on its own (closing the terminal leaves it
    running), with `extra` options (forge --install --port-offset 1000 hands
    them on); its output goes to forge-start.log in the logs folder."""
    logs = Path(where["local"]["logs"])
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / "forge-start.log", "ab") as out:
        subprocess.Popen(
            [str(program / "forge"), *(extra or [])],
            cwd=str(Path.home()),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def parse_args(argv: list[str] | None) -> tuple[argparse.Namespace, list[str]]:
    """The installer's own options, and the rest: options for the Forge that
    --install starts (only --install takes any)."""
    parser = argparse.ArgumentParser(
        prog="forge", description="Install Forge on this computer, or take it out"
    )
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument(
        "--install",
        action="store_true",
        help="copy Forge to your home folder, add it to the apps menu, start it",
    )
    what.add_argument(
        "--uninstall",
        action="store_true",
        help="take the program and its menu entry out; your things stay",
    )
    parser.add_argument(
        "--no-start", action="store_true", help="with --install: do not start Forge"
    )
    parser.add_argument(
        "--remove-data",
        action="store_true",
        help="with --uninstall: also remove Forge's folders on this computer",
    )
    parser.add_argument(
        "--yes", action="store_true", help="with --remove-data: do not ask first"
    )
    args, rest = parser.parse_known_args(argv)
    if rest and not (args.install and not args.no_start):
        parser.error(f"unknown option: {' '.join(rest)}")
    return args, rest


def main(argv: list[str] | None = None) -> int:
    args, rest = parse_args(argv)
    if sys.platform != "linux":
        print("forge --install and --uninstall are for Linux; see README.txt")
        return 1
    if os.geteuid() == 0:
        print(
            "Run this as yourself, without sudo: Forge installs for one person"
            " and never needs administrator rights"
        )
        return 1
    try:
        if args.uninstall:
            uninstall(remove_data=args.remove_data, yes=args.yes)
            return 0
        busy = [] if args.no_start else running_from(HERE)
        if busy:
            raise Problem(
                f"Forge is running from {HERE} (process"
                f" {', '.join(map(str, busy))}): close it first, so that two"
                " Forges never use your things at once"
            )
        result = install()
    except Problem as e:
        print(f"Could not finish: {e}")
        return 1
    except KeyboardInterrupt:
        print("\nStopped before the end (an install leaves no half copy behind)")
        return 130
    print("Done. Next time, open Forge from your apps menu (search for Forge).")
    if result["copied"]:
        print("You can delete the download and the folder you unpacked.")
    print(f"To remove Forge later: {result['program'] / 'forge'} --uninstall")
    if not args.no_start:
        print("Starting Forge: its window opens in a few seconds.")
        start(result["program"], places(), rest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
