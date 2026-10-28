"""A support report: the newest lines of Forge's logs, scrubbed, in one zip.

    python3 shared/forge_diag.py make                # new zip in ~/Downloads
    python3 shared/forge_diag.py make --dest /tmp/x  # or in another folder

`make(dest_dir=None) -> Path` does the same for a caller (the Settings About
card's "Make a support report" button). What goes in, and every scrub pattern,
is the registry `shared/forge_diag.json`; the home-folder and drive rules come
from the release registry (`release/release.json`, `scrub`), read only, so
the report and the release build hide the same things.

Logs live in `outputs/` beside forge.py when Forge runs from source and in
the system's log folder in a portable release (forge_portable.data_dirs:
~/.local/state/forge/logs, %LOCALAPPDATA%\\Forge\\Logs, ~/Library/Logs/Forge).
Both are read when they exist. Only the last `tail_lines` of each log go in,
read from the end of the file, so a large log costs little.

The zip gets a new name every time (forge-report-YYYY-MM-DD-HHMM.zip, then
-2, -3 ...) and is opened with mode "x", so nothing is ever overwritten. Each
log is scrubbed in this order: the account's home folder (plain and
URL-encoded), extra_scrub (keys,
tokens, emails, other systems' home folders), the release rules, the user
name as a whole word (also between URL-encoded slashes), and last anything a release `forbid` or a `must_not`
pattern still matches becomes <hidden>. `make` then checks every member
again and writes no zip at all if any `must_not` or `forbid` pattern, or the
home folder, is left.
"""

from __future__ import annotations

import argparse
import fnmatch
import getpass
import json
import os
import platform
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import quote

SHARED = Path(__file__).resolve().parent
FORGE = SHARED.parent
REGISTRY = SHARED / "forge_diag.json"


class DiagError(RuntimeError):
    pass


def load_registry(path: Path = REGISTRY) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def release_rules(forge: Path, registry: dict) -> dict[str, list]:
    """The release registry's scrub replace and forbid lists, plus the
    private ones its scrub.private file adds (as release/build.py reads
    them). Missing registry: no rules, extra_scrub still applies."""
    path = forge / registry.get("release_registry", "release/release.json")
    try:
        rules = json.loads(path.read_text(encoding="utf-8")).get("scrub") or {}
    except (OSError, ValueError):
        return {"replace": [], "forbid": []}
    replace = list(rules.get("replace") or [])
    forbid = list(rules.get("forbid") or [])
    private = rules.get("private")
    if private:
        extra_path = Path(os.path.expanduser(private))
        try:
            extra = json.loads(extra_path.read_text(encoding="utf-8"))
            replace = list(extra.get("replace") or []) + replace
            forbid += list(extra.get("forbid") or [])
        except (OSError, ValueError):
            pass
    return {"replace": replace, "forbid": forbid}


class Scrubber:
    """Every scrub step for one account, compiled once."""

    def __init__(
        self,
        registry: dict,
        rules: dict[str, list],
        home: str | None = None,
        user: str | None = None,
    ):
        self.home = home if home is not None else str(Path.home())
        if user is None:
            try:
                user = getpass.getuser()
            except Exception:
                user = os.path.basename(self.home)
        self.user = user
        # Request lines in the logs carry paths URL-encoded (path=%2Fhome%2F...),
        # sometimes twice (%252F), so the home folder is also matched in
        # those forms, either hex case.
        coded = quote(self.home, safe="")
        twice = quote(coded, safe="")
        self.homes = [self.home, coded, coded.replace("%2F", "%2f"), twice]
        self.homes.append(twice.replace("%252F", "%252f"))
        if len(self.home) <= 1:
            self.homes = []

        def pattern(text: str) -> re.Pattern[str]:
            return re.compile(text.replace("{home}", re.escape(self.home)))

        self.extra = [(re.compile(a), b) for a, b in registry.get("extra_scrub", [])]
        self.release = [(pattern(a), b) for a, b in rules["replace"]]
        self.last = [pattern(p) for p in rules["forbid"]] + [
            re.compile(p) for p in registry.get("must_not", [])
        ]

    def __call__(self, text: str) -> str:
        for home in self.homes:
            text = text.replace(home, "~")
        for pat, new in self.extra:
            text = pat.sub(new, text)
        for pat, new in self.release:
            text = pat.sub(lambda _m, new=new: new, text)
        if len(self.user) >= 2:
            name = re.escape(self.user)
            text = re.sub(rf"(?:\b|(?<=%2[Ff])|(?<=%252[Ff])){name}\b", "<user>", text)
        for pat in self.last:
            text = pat.sub("<hidden>", text)
        return text

    def leaks(self, text: str) -> list[str]:
        """The patterns that still match: empty for a clean text."""
        found = [p.pattern for p in self.last if p.search(text)]
        if any(home in text for home in self.homes):
            found.append("home folder")
        return found


def log_dirs(registry: dict, forge: Path = FORGE) -> list[tuple[str, Path]]:
    """(id, folder) for every registry log folder that exists."""
    release_logs = ""
    try:
        sys.path.insert(0, str(forge))
        import forge_core
        import forge_portable

        release_logs = forge_portable.data_dirs(forge_core.platform_name())["logs"]
    except Exception:
        pass
    finally:
        if sys.path and sys.path[0] == str(forge):
            sys.path.pop(0)
    found: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for entry in registry.get("logs", []):
        raw = entry["dir"]
        if "{logs}" in raw and not release_logs:
            continue
        folder = Path(
            raw.replace("{forge}", str(forge)).replace("{logs}", release_logs)
        ).expanduser()
        if folder.is_dir() and folder.resolve() not in seen:
            seen.add(folder.resolve())
            found.append((entry["id"], folder))
    return found


def tail(path: Path, lines: int, max_bytes: int) -> str:
    """The last `lines` lines of a file, reading at most `max_bytes` from its end."""
    size = path.stat().st_size
    with path.open("rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
        data = f.read(max_bytes)
    text = data.decode("utf-8", errors="replace")
    if size > max_bytes and "\n" in text:
        text = text.split("\n", 1)[1]
    return "\n".join(text.splitlines()[-lines:]) + "\n"


def facts(forge: Path = FORGE) -> dict:
    """What the report says about this Forge: no host name, no paths."""
    out: dict = {
        "made": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }
    try:
        rel = json.loads((forge / "release/release.json").read_text(encoding="utf-8"))
        out["forge_version"] = rel.get("version")
    except (OSError, ValueError):
        out["forge_version"] = None
    if (forge / ".git").exists():
        try:
            run = subprocess.run(
                ["git", "-C", str(forge), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            out["git"] = run.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            out["git"] = None
    apps = []
    for manifest in sorted((forge / "apps").glob("*/forge_app.json")):
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            apps.append({"name": manifest.parent.name, "error": "unreadable manifest"})
            continue
        apps.append(
            {"name": m.get("name"), "port": m.get("port"), "version": m.get("version")}
        )
    out["apps"] = apps
    return out


def new_name(dest: Path, stamp: str) -> Path:
    path = dest / f"forge-report-{stamp}.zip"
    n = 2
    while path.exists():
        path = dest / f"forge-report-{stamp}-{n}.zip"
        n += 1
    return path


def make(
    dest_dir: str | os.PathLike | None = None,
    forge: Path = FORGE,
    registry: dict | None = None,
    home: str | None = None,
    user: str | None = None,
    dirs: list[tuple[str, Path]] | None = None,
) -> Path:
    """Write a new scrubbed support report and return its path."""
    registry = registry if registry is not None else load_registry()
    scrub = Scrubber(registry, release_rules(forge, registry), home, user)
    dest = (
        Path(dest_dir).expanduser() if dest_dir else Path.home() / "Downloads"
    ).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    dirs = dirs if dirs is not None else log_dirs(registry, forge)
    lines = int(registry.get("tail_lines", 400))
    max_bytes = int(registry.get("max_bytes_per_file", 200000))
    max_files = int(registry.get("max_files", 200))
    members: dict[str, str] = {}
    skipped = 0
    globs = {e["id"]: e.get("glob", "*.log") for e in registry.get("logs", [])}
    for log_id, folder in dirs:
        pattern = globs.get(log_id, "*.log")
        for path in sorted(folder.iterdir()):
            if not path.is_file() or not fnmatch.fnmatch(path.name, pattern):
                continue
            if len(members) >= max_files:
                skipped += 1
                continue
            try:
                text = tail(path, lines, max_bytes)
            except OSError as e:
                text = f"(could not read: {e.strerror})\n"
            members[f"logs/{log_id}/{scrub(path.name)}"] = scrub(text)
    info = facts(forge)
    info["logs"] = {
        "folders": [log_id for log_id, _ in dirs],
        "files": len(members),
        "left_out_over_limit": skipped,
        "tail_lines": lines,
    }
    members["facts.json"] = scrub(json.dumps(info, indent=2)) + "\n"
    members["README.txt"] = (
        "A Forge support report. It holds the newest lines of each Forge log "
        "and a few facts about this Forge (system, Python, versions, app "
        "ports). Home folders, the user name, emails, keys and tokens were "
        "replaced before the zip was written. Open the files to see exactly "
        "what would be sent.\n"
    )
    for name, text in members.items():
        problems = scrub.leaks(text) + scrub.leaks(name)
        if problems:
            raise DiagError(f"{name} still matches {problems[0]} after the scrub")
    stamp = time.strftime("%Y-%m-%d-%H%M")
    path = new_name(dest, stamp)
    try:
        with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as z:
            for name, text in members.items():
                z.writestr(name, text)
    except FileExistsError:
        path = new_name(dest, stamp + f"-{os.getpid()}")
        with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as z:
            for name, text in members.items():
                z.writestr(name, text)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").strip().split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make", help="write a new support report zip")
    mk.add_argument("--dest", help="folder for the zip (default ~/Downloads)")
    args = parser.parse_args(argv)
    if args.cmd == "make":
        try:
            path = make(args.dest)
        except DiagError as e:
            print(f"no report made: {e}", file=sys.stderr)
            return 1
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
        logs = sum(1 for n in names if n.startswith("logs/"))
        print(f"{path} ({logs} logs, {path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
