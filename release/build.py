#!/usr/bin/env python3
"""Forge release builder: one folder and one archive per system, made on Linux
from the release registry (release/release.json).

    python3 release/build.py                         every target
    python3 release/build.py --target linux-x64      one (repeatable)
    python3 release/build.py --check-only            pick and check the files only
    python3 release/build.py --from worktree         uncommitted files too
    python3 release/build.py --source-tree           the release as a source tree

WHAT GOES IN
    The paths the registry's "ship" list names, plus apps/<name>/ for every app
    it includes (an app cut on a system stays out of that system's bundle),
    minus whatever "leave_out" matches: tests, handoff docs, the owner's own
    tools and data. Files come from git HEAD by default, so only what is
    committed ships; --from worktree takes the working tree's git view.
    Each bundle also gets a relocatable CPython (python-build-standalone,
    checked against the digest the registry pins), the packages its apps
    need, the launch scripts in release/launch/ and README.txt.

CHECKS (a failing one stops the build before anything is archived)
    1. scrub: the registry's "scrub" swaps run on every shipped text file (the
       owner's home folder in comments and examples), then no "forbid" string
       may be left in any file, text or not.
    2. clean: Forge Backup's clean-copy checker (apps/backup/clean.py, the one
       that guards the public GitHub copy) reads every shipped file for
       secrets, personal data, this laptop's real tokens and passwords, and
       lines of private notes. The bundled Python and packages are read for
       secrets and those real values too. A tree without apps/backup (the
       public source tree, which was checked when it was made) skips this
       check and says so.
    3. packages: uv installs each target's packages from wheels made for that
       platform (uv pip install --python-platform), with each package's own
       per-system dependencies; pip cannot do that from another system. Every
       package is pinned to one version, so each build gets the same.
    4. imports: from each entry point (the launcher, every app's module) every
       import is followed through the shipped files; an import at module level
       must resolve to the standard library of the target system, a shipped
       file or an installed package. Imports inside functions, try blocks or
       ifs only warn.

THE SOURCE TREE (--source-tree)
    What a public git repository of the release holds: the files every bundle
    draws from (all systems' apps), this builder, its launch scripts and
    tests, a README.md, .gitignore and GitHub workflow made from the
    templates in release/source/ (registry "source"), and a requirements.txt
    for running from source. It gets the same checks; the registry it carries
    lists only the apps it holds.

WHAT COMES OUT  (outputs/release/<version>/ unless --out says otherwise)
    forge-<version>-<target>.tar.gz or .zip, SHA256SUMS, report.json, and
    the unpacked bundles in build/<target>/ for a smoke run; with
    --source-tree, the folder forge-<version>-source/. An output folder that
    already holds a target is never overwritten: pick another --out.

NEEDS
    git, uv, and network access the first time (the runtimes and wheels are
    cached in ~/.cache/forge-release and uv's own cache).
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import fnmatch
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REGISTRY = HERE / "release.json"
LAUNCH = HERE / "launch"
CLEAN_DIR = ROOT / "apps" / "backup"
# The builder's downloads (runtimes, wheels). Not ~/.cache/forge-release: that
# is the installed release's own cache folder (forge_portable.data_dirs).
CACHE = Path(
    os.environ.get("FORGE_RELEASE_CACHE") or Path.home() / ".cache" / "forge-build"
)
# Inno Setup 6 lives in a Wine prefix of its own, kept apart from any other
# Wine use (installed there once with its /VERYSILENT /CURRENTUSER setup).
INNO_PREFIX = Path(
    os.environ.get("FORGE_INNO_PREFIX")
    or Path.home() / ".local" / "share" / "forge-build" / "wine-inno"
)
TOP = "Forge"  # the folder every archive unpacks to
SNIFF = 8192  # a NUL byte in this many first bytes marks a binary file
MANYLINUX_OLD = {
    "manylinux1": (2, 5),
    "manylinux2010": (2, 12),
    "manylinux2014": (2, 17),
}

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import forge_portable  # noqa: E402  (entry_state: what a system cuts)


class BuildError(Exception):
    """A check failed or a step could not run: nothing is archived."""


@dataclass
class File:
    rel: str  # path from the Forge folder, with /
    data: bytes
    mode: int  # 0o755 or 0o644


NOT_CHECKED = (
    "[build] Careful: there is no apps/backup/clean.py here, so no file was"
    " checked for secrets or personal data (only the registry's scrub and"
    " forbid lists ran). Read the output yourself before you publish it."
)


def clean_module():
    """apps/backup/clean.py, the checker that keeps secrets out of copies, or
    None in a tree that has no apps/backup (the public source tree)."""
    if not (CLEAN_DIR / "clean.py").is_file():
        return None
    if str(CLEAN_DIR) not in sys.path:
        sys.path.insert(0, str(CLEAN_DIR))
    try:
        import clean  # type: ignore[import-not-found]
    except ImportError as e:
        raise BuildError(
            f"apps/backup/clean.py is needed: it is the check that keeps secrets "
            f"and personal data out of a release ({e})"
        )
    return clean


# ---------------------------------------------------------------- git


def git(*args: str, data: bytes | None = None) -> bytes:
    done = subprocess.run(
        ["git", "-C", str(ROOT), *args], input=data, capture_output=True
    )
    if done.returncode != 0:
        why = done.stderr.decode(errors="replace").strip()
        raise BuildError(f"git {args[0]} failed: {why}")
    return done.stdout


def head_files() -> dict[str, tuple[str, str]]:
    """{path: (mode, blob id)} of every file in the last commit."""
    rows = {}
    out = git("ls-tree", "-r", "-z", "--full-tree", "HEAD")
    for record in out.decode(errors="surrogateescape").split("\0"):
        if record:
            meta, path = record.split("\t", 1)
            mode, kind, sha = meta.split()
            if kind == "blob":
                rows[path] = (mode, sha)
    return rows


def read_blobs(shas: list[str]) -> dict[str, bytes]:
    """{blob id: content}, from one git process."""
    if not shas:
        return {}
    out = git("cat-file", "--batch", data=("\n".join(shas) + "\n").encode())
    blobs: dict[str, bytes] = {}
    pos = 0
    for _ in shas:
        end = out.index(b"\n", pos)
        sha, _kind, size = out[pos:end].split()
        start = end + 1
        blobs[sha.decode()] = out[start : start + int(size)]
        pos = start + int(size) + 1
    return blobs


def worktree_files() -> list[str]:
    """The working tree as git sees it: tracked files plus new ones not
    ignored. Outside a git checkout, every file but caches."""
    if (ROOT / ".git").exists():
        out = git("ls-files", "-z", "-co", "--exclude-standard")
        rows = out.decode(errors="surrogateescape").split("\0")
    else:
        rows = [
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*")
            if not {".git", "__pycache__"} & set(path.relative_to(ROOT).parts)
        ]
    return sorted(rel for rel in rows if rel and os.path.lexists(ROOT / rel))


# ---------------------------------------------------------------- registry


def load_registry(path: Path = REGISTRY) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def included_apps(registry: dict) -> list[str]:
    return sorted(
        name
        for name, entry in (registry.get("apps") or {}).items()
        if isinstance(entry, dict) and entry.get("include") is True
    )


def cut_apps(registry: dict, system: str) -> set[str]:
    """Included apps a system cannot run: left out of its bundle."""
    return {
        name
        for name in included_apps(registry)
        if forge_portable.entry_state(registry["apps"][name].get(system)) == "cut"
    }


def under_root(rel: str, root: str) -> bool:
    """True when a path is the root itself or, for a root ending in /, inside it."""
    return rel == root or (root.endswith("/") and rel.startswith(root))


def asset_roots(registry: dict) -> dict[str, list[str]]:
    """{folder or file: the included apps that name it}: parts of shared/
    only those apps use (their "assets" folders and "downloads" files),
    shipped with them."""
    out: dict[str, list[str]] = {}
    for name in included_apps(registry):
        entry = registry["apps"][name]
        paths = list(entry.get("assets") or [])
        paths += [d["path"] for d in entry.get("downloads") or []]
        for root in paths:
            out.setdefault(root, []).append(name)
    return out


def download_list(registry: dict) -> list[dict]:
    """Every included app's "downloads": files kept out of git (large
    third-party assets) that the build fetches and checks by SHA-256."""
    return [
        d
        for name in included_apps(registry)
        for d in registry["apps"][name].get("downloads") or []
    ]


def owners(rel: str, registry: dict) -> set[str]:
    """The included apps a shipped path belongs to (none: the hub's own)."""
    parts = rel.split("/")
    if parts[0] == "apps" and len(parts) > 2:
        return {parts[1]}
    found: set[str] = set()
    for root, names in asset_roots(registry).items():
        if under_root(rel, root):
            found.update(names)
    return found


def dropped(rel: str, registry: dict, cut: set[str]) -> bool:
    """True when every app a shipped path belongs to is cut on a system."""
    found = owners(rel, registry)
    return bool(found) and found <= cut


def source_roots(registry: dict) -> list[str]:
    """What the source tree holds besides what ships: the builder, its
    templates and tests (registry "source", "add")."""
    return list((registry.get("source") or {}).get("add") or [])


def in_ship(rel: str, registry: dict, extra: list[str] | None = None) -> bool:
    roots = list(registry.get("ship") or [])
    roots += [f"apps/{name}/" for name in included_apps(registry)]
    roots += list(asset_roots(registry))
    roots += extra or []
    return any(under_root(rel, root) for root in roots)


def left_out(rel: str, registry: dict, extra: list[str] | None = None) -> str | None:
    """The leave_out pattern a shipped path matches, if any. An app's asset
    folders ship whole: leave_out keeps the packs they sit in out, not them.
    So do the source tree's extra roots (its tests among them), and the
    registry's leave_out_keep (app data in a folder named like tests)."""
    keep = list(asset_roots(registry)) + (extra or [])
    keep += list(registry.get("leave_out_keep") or [])
    if any(under_root(rel, root) for root in keep):
        return None
    for pattern in registry.get("leave_out") or []:
        if fnmatch.fnmatchcase(rel, pattern):
            return pattern
    return None


def project(requirement: str) -> str:
    """The normalised project name of a requirement such as "numpy==2.5.3"."""
    name = re.split(r"[=<>!~;\[ @]", requirement.strip(), maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def requirements(registry: dict, system: str) -> list[str]:
    """The packages one system's bundle installs: the base set, its window
    packages, and those of every app it runs. The same project pinned two
    ways is an error."""
    packages = registry.get("packages") or {}
    wanted = list(packages.get("base") or [])
    wanted += list((packages.get("window") or {}).get(system) or [])
    cut = cut_apps(registry, system)
    for name in included_apps(registry):
        if name not in cut:
            wanted += list(registry["apps"][name].get("packages") or [])
    out: dict[str, str] = {}
    for req in wanted:
        key = project(req)
        if not re.fullmatch(r"[A-Za-z0-9._\-\[\], ]+==[A-Za-z0-9.+!\-]+", req.strip()):
            raise BuildError(
                f"{req!r}: pin one version (name==version), or a build may"
                " quietly get an old one that has wheels"
            )
        if key in out and out[key] != req.strip():
            raise BuildError(f"{key} is asked for as {out[key]!r} and {req!r}")
        out[key] = req.strip()
    return [out[k] for k in sorted(out)]


# ---------------------------------------------------------------- files


def source_files(
    registry: dict, source: str, extra: list[str] | None = None
) -> tuple[list[File], dict[str, str]]:
    """Every file the bundles may ship (and the extra roots), from git HEAD
    or the working tree, and what was left out (path: why)."""
    left: dict[str, str] = {}
    files: list[File] = []
    # A pinned download always comes from its download, never a copy here.
    fetched = {d["path"] for d in download_list(registry)}
    if source == "head":
        picked: dict[str, tuple[str, str]] = {}
        for rel, (mode, sha) in head_files().items():
            if rel in fetched or not in_ship(rel, registry, extra):
                continue
            why = left_out(rel, registry, extra)
            if why:
                left[rel] = f"leave_out {why}"
            elif mode == "120000":
                left[rel] = "a link"
            else:
                picked[rel] = (mode, sha)
        blobs = read_blobs(sorted({s for _, s in picked.values()}))
        for rel in sorted(picked):
            mode, sha = picked[rel]
            files.append(File(rel, blobs[sha], 0o755 if mode == "100755" else 0o644))
    elif source == "worktree":
        for rel in worktree_files():
            if rel in fetched or not in_ship(rel, registry, extra):
                continue
            path = ROOT / rel
            why = left_out(rel, registry, extra)
            if why:
                left[rel] = f"leave_out {why}"
            elif path.is_symlink():
                left[rel] = "a link"
            elif path.is_file():
                mode = 0o755 if os.access(path, os.X_OK) else 0o644
                files.append(File(rel, path.read_bytes(), mode))
    else:
        raise BuildError(f"unknown source {source!r} (head or worktree)")
    have = {f.rel.split("/")[1] for f in files if f.rel.startswith("apps/")}
    missing = [name for name in included_apps(registry) if name not in have]
    if missing:
        raise BuildError(f"included apps with no files in {source}: {missing}")
    empty = [
        root
        for root in asset_roots(registry)
        if root not in fetched and not any(under_root(f.rel, root) for f in files)
    ]
    if empty:
        raise BuildError(f"asset folders with no files in {source}: {empty}")
    return files, left


def is_text(data: bytes) -> bool:
    return b"\0" not in data[:SNIFF]


def scrub_pattern(text: str, home: str | None = None) -> re.Pattern[bytes]:
    """A scrub rule as a pattern; {home} is the building account's home
    folder, matched as it is."""
    home = str(Path.home()) if home is None else home
    return re.compile(text.replace("{home}", re.escape(home)).encode())


def scrub_rules(registry: dict) -> dict[str, list]:
    """The registry's replace and forbid lists, plus the private ones from
    the file scrub.private names (outside the repo: rules that would name
    the owner if they were written in the registry). A registry that names
    a private file which is missing stops the build."""
    rules = registry.get("scrub") or {}
    replace = list(rules.get("replace") or [])
    forbid = list(rules.get("forbid") or [])
    if rules.get("private"):
        private = Path(os.path.expanduser(rules["private"]))
        if not private.is_file():
            # Without it the owner's own words would ship unswapped.
            raise BuildError(
                f"the private scrub list {rules['private']} that release.json"
                " names is missing: put it back (a build is never made without"
                " it), or build from the public source tree, whose registry"
                " names none"
            )
        extra = json.loads(private.read_text(encoding="utf-8"))
        replace = list(extra.get("replace") or []) + replace
        forbid += list(extra.get("forbid") or [])
    return {"replace": replace, "forbid": forbid}


def scrub(files: list[File], registry: dict) -> dict[str, int]:
    """Apply the scrub swaps to every text file; {path: swaps made}."""
    pairs = [
        (scrub_pattern(old), new.encode())
        for old, new in scrub_rules(registry)["replace"]
    ]
    done: dict[str, int] = {}
    for f in files:
        if not is_text(f.data):
            continue
        count = 0
        for pattern, new in pairs:
            f.data, n = pattern.subn(lambda _m, new=new: new, f.data)
            count += n
        if count:
            done[f.rel] = count
    return done


def forbidden(files: list[File], registry: dict) -> list[str]:
    """Shipped files or paths a forbid pattern still matches after the scrub."""
    patterns = [scrub_pattern(p) for p in scrub_rules(registry)["forbid"]]
    problems = []
    for f in files:
        for pattern in patterns:
            if pattern.search(f.data) or pattern.search(f.rel.encode()):
                problems.append(
                    f"{f.rel}: a forbidden text (home folder, drive or private"
                    " name) is left after the scrub"
                )
                break
    return problems


SHARED_REF = re.compile(
    rb"(?<![\w.])/shared/([\w./-]+\.(?:js|mjs|css|json|png|svg|jpe?g|webp|gif"
    rb"|woff2?|ttf|html|glb|gltf|vrm|wasm|mp3|ogg|wav))\b"
)


def missing_shared(files: list[File], registry: dict) -> list[str]:
    """Shipped text files that name a /shared/ file the release does not ship
    (shared/ ships by allowlist: a new script tag needs its file listed)."""
    have = {f.rel for f in files} | {d["path"] for d in download_list(registry)}
    problems = []
    for f in files:
        if not is_text(f.data):
            continue
        for m in SHARED_REF.finditer(f.data):
            rel = "shared/" + m.group(1).decode(errors="replace")
            if rel not in have:
                problems.append(
                    f"{f.rel}: names /{rel}, which is not shipped (add it to"
                    " release.json's ship list, or take the reference out)"
                )
    return sorted(set(problems))


def clean_problems(files: list[File]) -> list[str]:
    """What the clean-copy checker finds in the shipped files (never values)."""
    clean = clean_module()
    if clean is None:
        return []
    checker = clean.Checker(clean.load_rules())
    problems = []
    for f in files:
        why = checker.file(f.rel, len(f.data), f.data)
        if why:
            problems.append(f"{f.rel}: {why}")
    return problems


def licence_module():
    """release/licence_check.py: sorts licences by release/licence_policy.json."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import licence_check  # type: ignore[import-not-found]

    return licence_check


def licence_problems(site: Path, dists: list[dict]) -> dict[str, list[str]]:
    """{"errors": [...], "warnings": [...]} for the packages a bundle really
    holds: a licence the policy denies (with no exception there) stops the
    build. An empty short licence is read again in full, as licence_check.py's
    own command does."""
    check = licence_module()
    full = []
    for d in dists:
        if str(d.get("licence") or "").strip().lower() in check.UNKNOWN_TEXTS:
            d = {**d, "licence": check.full_licence(site, d["name"]) or d["licence"]}
        full.append(d)
    return check.problems(full)


def third_party_checker(registry: dict):
    """The clean checker for third-party files (the runtime, packages and
    downloaded assets): secrets and this laptop's real values only. Their
    authors' addresses are not personal data here, names such as secrets.py
    are the standard library's, and the secret patterns the registry's
    third_party.skip names match examples in library docs."""
    clean = clean_module()
    if clean is None:
        return None
    rules = clean.load_rules()
    skip = set((registry.get("third_party") or {}).get("skip") or [])
    patterns = [p for p in rules.get("secret_patterns", []) if p["name"] not in skip]
    return clean.Checker(
        {
            **rules,
            "secret_patterns": patterns,
            "personal_patterns": [],
            "private_texts": [],
        }
    )


def third_party_problems(folder: Path, registry: dict) -> list[str]:
    """What the third-party check finds in the runtime and packages."""
    checker = third_party_checker(registry)
    if checker is None:
        return []
    problems = []
    for path in sorted(folder.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        hits = checker.scan_bytes(path.read_bytes())
        if hits:
            problems.append(f"{path.relative_to(folder)}: {', '.join(hits)}")
    return problems


def build_traces(folder: Path, places: list[Path]) -> list[str]:
    """Files under `folder` that name one of the build's own `places` (the
    download cache holding the Python that installs the packages, the
    staging folder): pip writes that Python's path into the first line of
    every command script it installs, and a release must not say where, or
    by whom, it was built. Not the bare home folder: a wheel built on a CI
    runner names that runner's home folder, which is a CI build's home too."""
    needles = {
        str(place).rstrip("/\\").encode()
        for place in places
        if len(Path(place).parts) > 3  # never /, /home or a bare home folder
    }
    return [
        path.relative_to(folder).as_posix()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and any(needle in path.read_bytes() for needle in needles)
    ]


# ---------------------------------------------------------------- imports


def imports(tree: ast.AST):
    """(import node, hard) for every import in a module. Hard: run when the
    module loads (module level, outside functions, try blocks, ifs and withs),
    so a missing module there stops the app."""

    def walk(node: ast.AST, hard: bool):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                yield child, hard
            elif isinstance(child, ast.If) and "TYPE_CHECKING" in ast.unparse(
                child.test
            ):
                continue
            elif isinstance(
                child,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.Lambda,
                    ast.Try,
                    ast.TryStar,
                    ast.If,
                    ast.With,
                ),
            ):
                yield from walk(child, False)
            else:
                yield from walk(child, hard)

    yield from walk(tree, True)


def installed_names(site: Path) -> set[str]:
    """Top-level module names a site-packages folder provides."""
    names = set()
    for entry in site.iterdir():
        name = entry.name
        if name.endswith((".dist-info", ".data", ".egg-info", ".pth")):
            continue
        if name == "__pycache__":
            continue
        if entry.is_dir():
            names.add(name)
        elif name.endswith((".py", ".pyd", ".so")):
            names.add(name.split(".")[0])
    return names


# Standard library modules one kind of system lacks. The build runs on Linux,
# where all of the Unix ones import, so an app's `import fcntl` would pass the
# scan and then stop the app on Windows.
UNIX_ONLY = {
    "_curses",
    "_posixshmem",
    "_posixsubprocess",
    "curses",
    "fcntl",
    "grp",
    "posix",
    "pty",
    "pwd",
    "readline",
    "resource",
    "syslog",
    "termios",
    "tty",
}
WINDOWS_ONLY = {"_overlapped", "_winapi", "_wmi", "msvcrt", "nt", "winreg", "winsound"}


def normal_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned_by_app(files: list[File]) -> dict[str, set[str]]:
    """{app folder: distributions its shipped venv.lock.json pins}."""
    pinned = {}
    for f in files:
        parts = f.rel.split("/")
        if len(parts) == 3 and parts[0] == "apps" and parts[2] == "venv.lock.json":
            try:
                pins = json.loads(f.data).get("packages") or []
            except (ValueError, AttributeError):
                continue
            pinned[f"apps/{parts[1]}"] = {
                normal_dist(str(p).split("==")[0]) for p in pins if isinstance(p, str)
            }
    return pinned


class ImportScan:
    """Follows imports from entry files through the shipped files."""

    def __init__(
        self,
        files: list[File],
        installed: set[str],
        system: str = "linux",
        import_names: dict[str, str] | None = None,
    ):
        self.py = {f.rel: f for f in files if f.rel.endswith(".py")}
        self.pinned = pinned_by_app(files)
        self.import_names = import_names or {}
        self.dirs = {posixpath.dirname(rel) for rel in self.py}
        self.installed = installed
        self.system = system
        self.absent = UNIX_ONLY if system == "windows" else WINDOWS_ONLY
        self.stdlib = set(sys.stdlib_module_names) - self.absent
        self.stdlib |= {"__future__", "__main__"}
        self.seen: set[str] = set()
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def find(self, dotted: str, path: list[str]) -> str | None:
        """The shipped file `import dotted` loads from these folders (a
        package's __init__.py, or the folder of a namespace package)."""
        parts = dotted.split(".")
        for base in path:
            stem = posixpath.join(base, *parts) if base else posixpath.join(*parts)
            for candidate in (stem + ".py", stem + "/__init__.py"):
                if candidate in self.py:
                    return candidate
            if stem in self.dirs:
                return stem + "/"
        return None

    def elsewhere(self, top: str, app_dir: str) -> str | None:
        """A module of this name anywhere in the app: some apps put their own
        subfolders on sys.path at run time."""
        for rel in sorted(self.py):
            if rel.startswith(app_dir + "/") and posixpath.basename(rel) == top + ".py":
                return rel
        return None

    def visit(self, rel: str, path: list[str], app_dir: str) -> None:
        if rel in self.seen or rel not in self.py:
            return
        self.seen.add(rel)
        try:
            tree = ast.parse(self.py[rel].data, rel)
        except SyntaxError as e:
            self.errors.append(f"{rel}: does not parse ({e.msg}, line {e.lineno})")
            return
        here = posixpath.dirname(rel)
        for node, hard in imports(tree):
            for dotted, local_base in self.targets(node, here):
                self.resolve(dotted, local_base, path, app_dir, rel, node.lineno, hard)

    def targets(self, node, here: str) -> list[tuple[str, str | None]]:
        """(dotted name, folder for a relative import or None) per name the
        node imports; `from a import b` may mean the module a.b."""
        if isinstance(node, ast.Import):
            return [(alias.name, None) for alias in node.names]
        base = None
        if node.level:
            base = here
            for _ in range(node.level - 1):
                base = posixpath.dirname(base)
        module = node.module or ""
        out = [(f"{module}.{a.name}" if module else a.name, base) for a in node.names]
        if module:
            out.append((module, base))
        return out

    def resolve(
        self,
        dotted: str,
        base: str | None,
        path: list[str],
        app_dir: str,
        rel: str,
        line: int,
        hard: bool,
    ) -> None:
        search = [base] if base is not None else path
        parts = dotted.split(".")
        for n in range(len(parts), 0, -1):
            found = self.find(".".join(parts[:n]), search)
            if found:
                if found.endswith(".py"):
                    self.visit(found, path, app_dir)
                return
        if base is not None:
            # `from . import name` where name is not a module: an attribute
            # of the package, which visiting the package covers.
            return
        top = parts[0]
        if top in self.absent:
            # Under an if or a try it is the other system's branch: fine.
            if hard:
                self.errors.append(
                    f"{rel}:{line}: {top} is not in Python on {self.system}"
                )
            return
        if top in self.stdlib or top in self.installed:
            return
        found = self.elsewhere(top, app_dir) if app_dir else None
        if found:
            self.visit(found, path, app_dir)
            return
        if len(parts) > 1 and self.find(parts[0], search):
            return  # `from pkg import name`: a name inside a shipped package
        message = f"{rel}:{line}: {top} is not shipped or installed"
        dist = normal_dist(self.import_names.get(top, top))
        if dist in self.pinned.get(app_dir, set()):
            # The app's own lock pins it, so it is a real dependency, not
            # an optional extra: a function that imports it would fail.
            hard = True
            message += f" (its {app_dir}/venv.lock.json pins it)"
        found_in = self.errors if hard else self.warnings
        if message not in found_in:
            found_in.append(message)


def app_entries(files: list[File], registry: dict, skip: set[str]):
    """(entry file, module search folders, app folder) for each shipped app,
    read from its forge_app.json the way forge_core starts it."""
    by_rel = {f.rel: f for f in files}
    for name in included_apps(registry):
        if name in skip:
            continue
        manifest = json.loads(by_rel[f"apps/{name}/forge_app.json"].data)
        source = posixpath.normpath(
            posixpath.join(f"apps/{name}", manifest.get("src_dir", "."))
        )
        module = manifest["module"].split(":")[0]
        entry = posixpath.join(source, *module.split(".")) + ".py"
        yield entry, [source, "shared"], f"apps/{name}"


def scan_imports(
    files: list[File],
    registry: dict,
    installed: set[str],
    skip: set[str],
    system: str = "linux",
) -> ImportScan:
    scan = ImportScan(files, installed, system, registry.get("imports"))
    scan.visit("forge_portable.py", ["", "shared"], "")
    for entry, path, app_dir in app_entries(files, registry, skip):
        if entry not in scan.py:
            scan.errors.append(f"{app_dir}: its module {entry} is not shipped")
            continue
        scan.visit(entry, path, app_dir)
    return scan


# ---------------------------------------------------------------- runtime and packages


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_url(registry: dict, target: dict) -> str:
    rt = registry["runtime"]
    return rt["url"].format(
        tag=rt["tag"],
        version=rt["version"],
        triple=target["triple"],
        flavour=rt["flavour"],
    )


def fetch(url: str, want_sha: str) -> Path:
    """A download, cached and checked against its pinned SHA-256."""
    dest = CACHE / "downloads" / f"{want_sha[:12]}-{url.rsplit('/', 1)[1]}"
    if dest.is_file() and sha256(dest) == want_sha:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    print(f"[build] downloading {url}", flush=True)
    with urllib.request.urlopen(url, timeout=120) as response, open(part, "wb") as out:
        shutil.copyfileobj(response, out, 1 << 20)
    got = sha256(part)
    if got != want_sha:
        part.unlink()
        raise BuildError(f"{dest.name}: SHA-256 {got} is not the pinned {want_sha}")
    os.replace(part, dest)
    return dest


def unpack_runtime(archive: Path, dest: Path, leave: list[str]) -> list[str]:
    """python-build-standalone's python/ folder into dest, minus the paths
    `leave` matches (from inside python/); returns what was left out."""
    skipped = []
    with tarfile.open(archive) as tar:
        members = []
        for m in tar.getmembers():
            if not m.name.startswith("python/"):
                continue
            m.name = m.name[len("python/") :]
            if m.islnk() and m.linkname.startswith("python/"):
                m.linkname = m.linkname[len("python/") :]
            if not m.name:
                continue
            if any(fnmatch.fnmatchcase(m.name, p) for p in leave):
                skipped.append(m.name)
                continue
            members.append(m)
        dest.mkdir(parents=True, exist_ok=True)
        tar.extractall(dest, members=members, filter="data")
    return skipped


def prune(site: Path, patterns: list[str]) -> int:
    """Takes the installed files `patterns` match (from inside site-packages)
    out of this build's own copy again; returns how many went."""
    gone = 0
    for path in sorted(site.rglob("*"), reverse=True):
        rel = path.relative_to(site).as_posix()
        if path.is_file() and any(fnmatch.fnmatchcase(rel, p) for p in patterns):
            path.unlink()
            gone += 1
        elif (
            path.is_dir()
            and not any(path.iterdir())
            and any(fnmatch.fnmatchcase(rel + "/x", p) for p in patterns)
        ):
            path.rmdir()
    return gone


def runtime_python(runtime: Path, system: str) -> Path:
    if system == "windows":
        return runtime / "python.exe"
    return runtime / "bin" / "python3"


def site_packages(runtime: Path, system: str, version: str) -> Path:
    if system == "windows":
        return runtime / "Lib" / "site-packages"
    major_minor = ".".join(version.split(".")[:2])
    return runtime / "lib" / f"python{major_minor}" / "site-packages"


def host_python(registry: dict) -> Path:
    """A Linux runtime of the release's Python, unpacked in the cache: it runs
    pip to build the source-only wheels and tells uv which Python to resolve
    for."""
    target = next(
        t
        for t in registry["targets"].values()
        if t["triple"] == "x86_64-unknown-linux-gnu"
    )
    folder = CACHE / "host" / registry["runtime"]["version"]
    python = runtime_python(folder, "linux")
    if not python.is_file():
        archive = fetch(runtime_url(registry, target), target["runtime_sha256"])
        unpack_runtime(archive, folder, [])
    return python


def wheelhouse(registry: dict, python: Path) -> Path:
    """Wheels built here for pure-Python packages published only as source."""
    folder = CACHE / "wheelhouse"
    folder.mkdir(parents=True, exist_ok=True)
    for req in (registry.get("packages") or {}).get("source_only") or []:
        stem = project(req).replace("-", "_")
        version = req.split("==", 1)[1] if "==" in req else ""
        if any(folder.glob(f"{stem}-{version}*.whl")):
            continue
        run(
            [str(python), "-m", "pip", "wheel", "--no-deps", "--no-binary", ":all:"]
            + ["--disable-pip-version-check", "-w", str(folder), req]
        )
    return folder


def run(command: list[str], env: dict | None = None) -> str:
    done = subprocess.run(command, capture_output=True, text=True, env=env)
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()[-25:]
        raise BuildError(f"{' '.join(command[:4])} ... failed:\n" + "\n".join(tail))
    return done.stdout


def install_packages(
    registry: dict, target: dict, site: Path, python: Path, wheels: Path
) -> list[str]:
    reqs = requirements(registry, target["system"])
    version = ".".join(registry["runtime"]["version"].split(".")[:2])
    env = dict(os.environ)
    if target.get("macos_min"):
        env["MACOSX_DEPLOYMENT_TARGET"] = target["macos_min"]
    run(
        ["uv", "pip", "install", "--no-config", "--quiet", "--target", str(site)]
        + ["--python", str(python), "--python-version", version]
        + ["--python-platform", target["uv_platform"], "--only-binary", ":all:"]
        + ["--find-links", str(wheels), "--link-mode", "copy", *reqs],
        env=env,
    )
    return reqs


def distributions(site: Path) -> list[dict]:
    """Name, version, licence and wheel tags of every installed package."""
    out = []
    for meta in sorted(site.glob("*.dist-info/METADATA")):
        fields: dict[str, list[str]] = {}
        for line in (
            meta.read_text(encoding="utf-8", errors="replace")
            .split("\n\n")[0]
            .splitlines()
        ):
            if ": " in line and not line.startswith(" "):
                key, value = line.split(": ", 1)
                fields.setdefault(key, []).append(value.strip())
        licence = (fields.get("License-Expression") or [""])[0]
        if not licence:
            short = (fields.get("License") or [""])[0]
            licence = short if 0 < len(short) <= 60 else ""
        if not licence:
            classes = [
                c.split(" :: ")[-1]
                for c in fields.get("Classifier", [])
                if c.startswith("License ::")
            ]
            licence = ", ".join(classes)
        wheel = meta.with_name("WHEEL")
        tags = []
        if wheel.is_file():
            tags = [
                line.split(":", 1)[1].strip()
                for line in wheel.read_text(errors="replace").splitlines()
                if line.startswith("Tag:")
            ]
        out.append(
            {
                "name": (fields.get("Name") or [meta.parent.name])[0],
                "version": (fields.get("Version") or ["?"])[0],
                "licence": licence or "see its own files",
                "tags": tags,
            }
        )
    return out


def oldest_system(dists: list[dict]) -> dict[str, str]:
    """The newest macOS and glibc any installed wheel asks for: the oldest
    system the bundle can run on, as far as its packages go."""
    mac = (0, 0)
    glibc = (0, 0)
    for dist in dists:
        for tag in dist["tags"]:
            platform = tag.split("-")[-1]
            for part in platform.split("."):
                if m := re.match(r"macosx_(\d+)_(\d+)_", part):
                    mac = max(mac, (int(m.group(1)), int(m.group(2))))
                elif m := re.match(r"manylinux_(\d+)_(\d+)_", part):
                    glibc = max(glibc, (int(m.group(1)), int(m.group(2))))
                else:
                    for old, version in MANYLINUX_OLD.items():
                        if part.startswith(old + "_"):
                            glibc = max(glibc, version)
    out = {}
    if mac > (0, 0):
        out["macos"] = f"{mac[0]}.{mac[1]}"
    if glibc > (0, 0):
        out["glibc"] = f"{glibc[0]}.{glibc[1]}"
    return out


def third_party_text(registry: dict, dists: list[dict]) -> str:
    rt = registry["runtime"]
    lines = [
        "Forge bundles these, each under its own licence (see its folder in runtime/).",
        "",
        f"Python {rt['version']} (PSF License), built by python-build-standalone {rt['tag']}",
    ]
    lines += [f"{d['name']} {d['version']}: {d['licence']}" for d in dists]
    included = (registry.get("third_party") or {}).get("included") or []
    if included:
        lines += [
            "",
            "Code shipped inside Forge's own folders (its licence beside it):",
        ]
        lines += included
    credits = list(
        dict.fromkeys(d["credit"] for d in download_list(registry) if d.get("credit"))
    )
    if credits:
        lines += [
            "",
            "Assets downloaded for the apps (source and digest in release.json):",
        ]
        lines += credits
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- what a system lacks

KINDS = (
    ("replaced", "Done another way"),
    ("fallback", "Falls back to something simpler"),
    ("cut", "Not in this version"),
)


def labels(files: list[File]) -> dict[str, str]:
    """{app: the name the home screen shows} from the shipped manifests."""
    out = {}
    for f in files:
        parts = f.rel.split("/")
        if len(parts) == 3 and parts[0] == "apps" and parts[2] == "forge_app.json":
            out[parts[1]] = json.loads(f.data).get("label") or parts[1]
    return out


def tester_words(feature: dict, system: str) -> str:
    """A feature's plain line for a bundle's README ("tester": one text or
    one per system); "" when it has none."""
    words = feature.get("tester") or ""
    if isinstance(words, dict):
        words = words.get(system) or ""
    return str(words)


def system_notes(
    registry: dict, system: str, names: dict[str, str], tester: bool = False
) -> list[str]:
    """What works differently on one system, from the registry's features
    and apps: replaced, falling back, cut, and the apps left out. tester:
    for a bundle's README, only the features with a "tester" line, in its
    words, and the left-out apps in one line (critic round E2: the Windows
    README explained cuts in Linux internals, D-Bus, /proc, pty, yt-dlp)."""
    lines: list[str] = []
    for kind, title in KINDS:
        rows = []
        for feature in (registry.get("features") or {}).values():
            if feature.get("readme") is False:
                continue
            text = str(feature.get(system) or "native")
            if forge_portable.entry_state(text) != kind:
                continue
            if tester:
                if tester_words(feature, system):
                    rows.append(f"  {tester_words(feature, system)}")
                continue
            why = text.split(":", 1)[1].strip() if ":" in text else ""
            rows.append(f"  {feature['what']}" + (f": {why}" if why else ""))
        if rows:
            lines += [f"{title}:", *rows, ""]
    if tester:
        left = sorted(names.get(name, name) for name in cut_apps(registry, system))
        if left:
            listed = (
                ", ".join(left[:-1]) + " and " + left[-1] if len(left) > 1 else left[0]
            )
            lines += [f"Apps not in this build: {listed}.", ""]
        return lines[:-1] if lines and not lines[-1] else lines
    apps = [
        f"  {names.get(name, name)}: {registry['apps'][name][system].split(':', 1)[-1].strip()}"
        for name in sorted(cut_apps(registry, system))
    ]
    if apps:
        lines += ["Apps left out on this system:", *apps, ""]
    return lines[:-1] if lines and not lines[-1] else lines


def readme_text(
    registry: dict, target: dict, names: dict[str, str], setup: bool = False
) -> str:
    """release/README.txt for one bundle: version, system and its notes.
    setup: a setup program is made beside this bundle (Windows)."""
    system = target["system"]
    cut = cut_apps(registry, system)
    needs = [
        f"  {names.get(name, name)}: {registry['apps'][name]['needs']}"
        for name in included_apps(registry)
        if registry["apps"][name].get("needs") and name not in cut
    ]
    text = (HERE / "README.txt").read_text(encoding="utf-8")
    # A block between "@<system>@" and "@end@" lines is kept only in that
    # system's README; "@<system>-setup@" only when a setup program is made.
    text = re.sub(
        r"^@(windows|macos|linux)(-setup)?@\n(.*?)^@end@\n",
        lambda m: (
            m.group(3) if m.group(1) == system and (setup or not m.group(2)) else ""
        ),
        text,
        flags=re.S | re.M,
    )
    title = f"Forge {registry['version']} for {target['label']}"
    for key, value in (
        ("@TITLE@", title + "\n" + "=" * len(title)),
        ("@VERSION@", registry["version"]),
        ("@NEEDS@", "\n".join(needs) or "  None."),
        ("@SYSTEM_NOTES@", "\n".join(system_notes(registry, system, names, True))),
    ):
        text = text.replace(key, value)
    # blocks left out leave their blank lines: two blank lines at most
    return re.sub(r"\n{4,}", "\n\n\n", text)


# ---------------------------------------------------------------- bundles and archives


def write_files(files: list[File], dest: Path) -> None:
    for f in files:
        path = dest / f.rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f.data)
        path.chmod(f.mode)


def add_launchers(target: dict, top: Path, registry: dict, mins: dict) -> None:
    """Launch scripts at the top of a bundle, or Forge.app around it (macOS)."""
    for name, source in (target.get("launch") or {}).items():
        shutil.copyfile(LAUNCH / source, top / name)
        (top / name).chmod(0o755 if os.access(LAUNCH / source, os.X_OK) else 0o644)
    if target.get("app_bundle"):
        contents = top / "Forge.app" / "Contents"
        (contents / "MacOS").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(LAUNCH / "mac-launcher", contents / "MacOS" / "Forge")
        (contents / "MacOS" / "Forge").chmod(0o755)
        wanted = [target.get("macos_min") or "11.0", mins.get("macos", "0.0")]
        oldest = max(wanted, key=lambda v: tuple(int(x) for x in v.split(".")))
        plist = (LAUNCH / "Info.plist").read_text(encoding="utf-8")
        plist = plist.format(
            version=registry["version"],
            bundle_id=registry.get("mac_bundle_id") or "local.forge.hub",
            min_macos=oldest,
        )
        (contents / "Info.plist").write_text(plist, encoding="utf-8")


def archive(folder: Path, out: Path, kind: str) -> None:
    """The folder as TOP/... in a .tar.gz (modes and links kept) or a .zip."""
    if kind == "zip":
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for path in sorted(folder.rglob("*")):
                if path.is_symlink() or not path.is_file():
                    continue
                name = f"{TOP}/{path.relative_to(folder).as_posix()}"
                info = zipfile.ZipInfo.from_file(path, name)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
                with open(path, "rb") as f:
                    z.writestr(info, f.read(), compresslevel=6)
        return

    def owner(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        return info

    with tarfile.open(out, "w:gz", compresslevel=6) as tar:
        tar.add(folder, arcname=TOP, filter=owner)


def folder_size(folder: Path) -> tuple[int, int]:
    count = size = 0
    for path in folder.rglob("*"):
        if path.is_file() and not path.is_symlink():
            count += 1
            size += path.stat().st_size
    return count, size


def git_state(source: str, registry: dict) -> dict:
    commit = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    roots = list(registry.get("ship") or []) + [
        f"apps/{name}/" for name in included_apps(registry)
    ]
    changed = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", *roots],
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return {"from": source, "commit": commit, "differs_in_worktree": len(changed)}


def build_target(
    name: str,
    registry: dict,
    files: list[File],
    out: Path,
    stage: Path,
    python: Path,
    wheels: Path,
) -> dict:
    target = registry["targets"][name]
    system = target["system"]
    cut = cut_apps(registry, system)
    mine = [f for f in files if not dropped(f.rel, registry, cut)]
    top = stage / name / TOP
    forge = (
        top / "Forge.app" / "Contents" / "Resources" / "forge"
        if target.get("app_bundle")
        else top
    )
    print(f"[build] {name}: {len(mine)} files, runtime and packages", flush=True)
    write_files(mine, forge)
    makes_setup = bool(target.get("setup")) and inno_compiler() is not None
    # every included app's name: the left-out ones are named in the notes too
    readme = readme_text(registry, target, labels(files), makes_setup)
    for spot in {top, forge}:
        (spot / "README.txt").write_text(readme, encoding="utf-8")
    runtime = forge / "runtime"
    archive_path = fetch(runtime_url(registry, target), target["runtime_sha256"])
    skipped = unpack_runtime(
        archive_path, runtime, registry["runtime"].get("leave_out") or []
    )
    site = site_packages(runtime, system, registry["runtime"]["version"])
    reqs = install_packages(registry, target, site, python, wheels)
    pruned = prune(site, registry["packages"].get("leave_out") or [])
    dists = distributions(site)
    licences = licence_problems(site, dists)
    if licences["errors"]:
        raise BuildError(
            f"{name}: packages whose licence release/licence_policy.json does"
            " not allow:\n  " + "\n  ".join(licences["errors"])
        )
    mins = oldest_system(dists)
    scan = scan_imports(mine, registry, installed_names(site), cut, system)
    if scan.errors:
        raise BuildError(
            f"{name}: imports that would fail:\n  " + "\n  ".join(scan.errors)
        )
    secrets = third_party_problems(runtime, registry)
    if secrets:
        raise BuildError(
            f"{name}: the runtime or a package holds:\n  " + "\n  ".join(secrets)
        )
    (top / "THIRD-PARTY.txt").write_text(
        third_party_text(registry, dists), encoding="utf-8"
    )
    add_launchers(target, top, registry, mins)
    traces = build_traces(top, [CACHE, stage, ROOT])
    if traces:
        raise BuildError(
            f"{name}: files that name the build's own folders:\n  "
            + "\n  ".join(traces)
        )
    if system == "linux":
        write_file_list(forge)
    kind = target.get("archive", "tar.gz")
    package = out / f"forge-{registry['version']}-{name}.{kind}"
    if package.exists():
        raise BuildError(f"{package} already exists: pick another --out")
    if target.get("setup") and setup_path(registry, out).exists():
        raise BuildError(
            f"{setup_path(registry, out)} already exists: pick another --out"
        )
    if target.get("setup"):
        # before packing, so a failed build leaves no download in --out
        problems = setup_folder_problems(top, LAUNCH / target["setup"])
        if problems:
            raise BuildError(
                "the setup script misses bundle folders:\n  " + "\n  ".join(problems)
            )
    print(f"[build] {name}: packing {package.name}", flush=True)
    archive(top, package, kind)
    count, size = folder_size(top)
    setup = windows_setup(registry, target, top, out) if target.get("setup") else {}
    return {
        "label": target["label"],
        "archive": package.name,
        "archive_bytes": package.stat().st_size,
        "sha256": sha256(package),
        "files": count,
        "bytes": size,
        "apps_cut": sorted(cut),
        "runtime": runtime_url(registry, target),
        "runtime_left_out": len(skipped),
        "packages_left_out": pruned,
        "requirements": reqs,
        "packages": [f"{d['name']}=={d['version']}" for d in dists],
        "oldest_system": mins,
        "imports_followed": len(scan.seen),
        "import_warnings": scan.warnings,
        "licence_warnings": licences["warnings"],
        **setup,
    }


FILE_LIST = "release/files.txt"  # forge_installer.py's FILE_LIST


def write_file_list(forge: Path) -> None:
    """release/files.txt in the bundle: every file and symlink (and empty
    folder, ending in "/"), so forge --install copies only this version's
    files even from a folder an older Forge was unpacked into as well."""
    lines = []
    for top, dirs, files in os.walk(forge):
        here = Path(top).relative_to(forge)
        links = [d for d in dirs if (Path(top) / d).is_symlink()]
        for name in files + links:
            rel = (here / name).as_posix()
            if rel != FILE_LIST:
                lines.append(rel)
        if not files and not dirs and here != Path("."):
            lines.append(here.as_posix() + "/")
    path = forge / FILE_LIST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Every file of this Forge download (release/build.py): forge --install"
        " copies only these.\n" + "\n".join(sorted(lines)) + "\n",
        encoding="utf-8",
    )


SETUP_FILES = re.compile(
    r"^(?:SetupIconFile|WizardImageFile|WizardSmallImageFile)=(.+)$"
    r'|^Source: "([^"{]+)"',
    re.M,
)


def launch_problems(registry: dict) -> list[str]:
    """Launch files and setup scripts the targets name that are not in
    release/launch/, and the icon and pictures a setup script names, so a
    missing file fails the build even where Inno Setup is not installed."""
    problems = []
    for name, target in registry["targets"].items():
        wanted = list((target.get("launch") or {}).values())
        if target.get("setup"):
            wanted.append(target["setup"])
            script = LAUNCH / target["setup"]
            if script.is_file():
                for found in SETUP_FILES.finditer(script.read_text("utf-8")):
                    listed = found.group(1) or found.group(2)
                    wanted += [part.strip() for part in listed.split(",")]
        problems += [
            f"{name}: release/launch/{rel} is missing"
            for rel in dict.fromkeys(wanted)
            if not (LAUNCH / rel).is_file()
        ]
    return problems


def inno_compiler() -> tuple[list[str], Path | None] | None:
    """Inno Setup 6's compiler run through Wine, and the Wine prefix it runs
    in. FORGE_ISCC names ISCC.exe; else it is looked for in the build's own
    prefix (INNO_PREFIX), then in WINEPREFIX (else ~/.wine). It runs in the
    prefix it was found in. None when there is no Wine or no Inno Setup."""
    wine = shutil.which("wine")
    if not wine:
        if os.environ.get("FORGE_ISCC"):
            raise BuildError("FORGE_ISCC is set, but Wine (which runs it) is not")
        return None
    if os.environ.get("FORGE_ISCC"):
        spots = [Path(os.environ["FORGE_ISCC"])]
        if not spots[0].is_file():
            raise BuildError(f"FORGE_ISCC names {spots[0]}, which is not there")
    else:
        spots = []
        for prefix in (
            INNO_PREFIX,
            Path(os.environ.get("WINEPREFIX") or Path.home() / ".wine"),
        ):
            drive = prefix / "drive_c"
            spots += [
                drive / folder / "Inno Setup 6" / "ISCC.exe"
                for folder in ("Program Files (x86)", "Program Files")
            ]
            spots += sorted(
                drive.glob("users/*/AppData/Local/Programs/Inno Setup 6/ISCC.exe")
            )
    found = next((spot for spot in spots if spot.is_file()), None)
    if found is None:
        return None
    prefix = next(
        (folder.parent for folder in found.parents if folder.name == "drive_c"), None
    )
    return [wine, str(found)], prefix


def wine_path(path: Path) -> str:
    """A Linux path as Wine's programs see it (Z: is the root folder)."""
    return "Z:" + str(path.resolve()).replace("/", "\\")


def setup_path(registry: dict, out: Path) -> Path:
    return out / f"Forge-Setup-{registry['version']}.exe"


def numeric_version(version: str) -> str:
    """The version as Windows' file version wants it: numbers and dots
    only (0.2.0-rc1 -> 0.2.0)."""
    match = re.match(r"\d+(\.\d+){0,3}", version)
    return match.group(0) if match else "0.0.0"


def setup_folder_problems(top: Path, script: Path) -> list[str]:
    """Every folder at the top of the bundle must be named in the setup
    script's [InstallDelete] (an upgrade clears it first) and
    [UninstallDelete] (the uninstaller takes what Forge wrote there)."""
    sections: dict[str, set[str]] = {}
    section = ""
    for line in script.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        found = re.match(r'Type: filesandordirs; Name: "\{app\}\\([^"\\]+)"', line)
        if found:
            sections.setdefault(section, set()).add(found.group(1).lower())
    problems = []
    for folder in sorted(p.name for p in top.iterdir() if p.is_dir()):
        for section in ("InstallDelete", "UninstallDelete"):
            if folder.lower() not in sections.get(section, set()):
                problems.append(f"{script.name} [{section}] does not name {folder}")
    return problems


def wine_value(wine: str, env: dict, key: str, name: str) -> str | None:
    """A Wine registry value ("" when it is set but empty), or None when it
    is not set."""
    try:
        text = run([wine, "reg", "query", key, "/v", name], env=env)
    except BuildError:
        return None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == name and parts[1].startswith("REG_"):
            return " ".join(parts[2:])
    return None


def windows_setup(registry: dict, target: dict, top: Path, out: Path) -> dict:
    """Forge-Setup-<version>.exe from the bundle folder, made by Inno Setup
    under Wine from the target's "setup" script in release/launch/. Without
    Inno Setup the zip is the whole download, and the report says why."""
    found = inno_compiler()
    if found is None:
        print(
            "[build] no Inno Setup under Wine: the Windows download is the zip"
            " alone (release/README.md says how to add the setup program)",
            flush=True,
        )
        return {"setup": None, "setup_why": "Inno Setup was not found under Wine"}
    dest = setup_path(registry, out)
    stem = dest.stem
    if dest.exists():
        raise BuildError(f"{dest} already exists: pick another --out")
    print(f"[build] {target['label']}: making {dest.name} with Inno Setup", flush=True)
    compiler, prefix = found
    # no window on the screen: no display, no Mono or Gecko install prompt,
    # and nothing added to the Linux menus
    env = dict(
        os.environ,
        WINEDEBUG="-all",
        WINEDLLOVERRIDES="mscoree,mshtml=;winemenubuilder.exe=d",
    )
    for key in ("DISPLAY", "WAYLAND_DISPLAY"):
        env.pop(key, None)
    if prefix is not None:
        env["WINEPREFIX"] = str(prefix)
    # Wine marks a file whose name starts with a dot as hidden, and Inno
    # Setup leaves hidden files out: show them while it runs, so the setup
    # program installs every file the zip holds, then put the prefix's own
    # value back.
    wine, key = compiler[0], r"HKCU\Software\Wine"
    before = wine_value(wine, env, key, "ShowDotFiles")
    try:
        run([wine, "reg", "add", key, "/v", "ShowDotFiles", "/d", "Y", "/f"], env=env)
        run(
            compiler
            + [
                "/Q",
                f"/DAppVersion={registry['version']}",
                f"/DNumericVersion={numeric_version(registry['version'])}",
                f"/DBundle={wine_path(top)}",
                f"/DOutputDir={wine_path(out)}",
                f"/DOutputName={stem}",
                wine_path(LAUNCH / target["setup"]),
            ],
            env=env,
        )
    except BuildError as e:
        raise BuildError(f"Inno Setup could not make {dest.name}: {e}")
    finally:
        if before is None:
            restore = [wine, "reg", "delete", key, "/v", "ShowDotFiles", "/f"]
        else:
            restore = [wine, "reg", "add", key, "/v", "ShowDotFiles"]
            restore += ["/d", before, "/f"]
        try:
            run(restore, env=env)
        except BuildError:
            pass  # the setup program is made; a shown dot-file is harmless
    if not dest.is_file():
        raise BuildError(f"Inno Setup ran but {dest.name} is not in {out}")
    return {
        "setup": dest.name,
        "setup_bytes": dest.stat().st_size,
        "setup_sha256": sha256(dest),
    }


def downloaded_files(registry: dict) -> list[File]:
    """The registry's downloads as shipped files. They are third-party data,
    so, like the runtime, they get the third-party check (a glTF's numbers
    look like phone numbers to the personal patterns)."""
    checker = third_party_checker(registry)
    out = []
    for d in download_list(registry):
        data = fetch(d["url"], d["sha256"]).read_bytes()
        hits = checker.scan_bytes(data) if checker else []
        if hits:
            raise BuildError(f"{d['path']} (downloaded): {', '.join(hits)}")
        out.append(File(d["path"], data, 0o644))
    return out


def public_registry(registry: dict) -> dict:
    """The registry as a bundle or the source tree carries it: only the apps
    it holds. The rest are the owner's and mean nothing there."""
    out = dict(registry)
    out["apps"] = {
        name: entry
        for name, entry in registry["apps"].items()
        if isinstance(entry, dict) and entry.get("include") is True
    }
    if "scrub" in out:  # the owner's private list means nothing elsewhere
        out["scrub"] = {
            k: v
            for k, v in out["scrub"].items()
            if k not in ("private", "private_about")
        }
    return out


def check_files(
    registry: dict, source: str, for_tree: bool = False
) -> tuple[list[File], dict, dict]:
    """Pick, scrub and check the shipped files (checks 1 and 2), then add
    the pinned downloads (the source tree leaves those to the build)."""
    extra = source_roots(registry) if for_tree else None
    files, left = source_files(registry, source, extra)
    for f in files:
        if f.rel == "release/release.json":
            text = json.dumps(public_registry(registry), indent=2, ensure_ascii=False)
            f.data = (text + "\n").encode()
    scrubbed = scrub(files, registry)
    problems = forbidden(files, registry) + missing_shared(files, registry)
    problems += clean_problems(files) + launch_problems(registry)
    if problems:
        raise BuildError("shipped files fail the checks:\n  " + "\n  ".join(problems))
    if not for_tree:
        have = {f.rel for f in files}
        files += [f for f in downloaded_files(registry) if f.rel not in have]
    return files, left, scrubbed


# ---------------------------------------------------------------- the source tree

SYSTEM_NAMES = {"linux": "Linux", "windows": "Windows", "macos": "macOS"}
MARKERS = {
    "linux": 'sys_platform == "linux"',
    "windows": 'sys_platform == "win32"',
    "macos": 'sys_platform == "darwin"',
}


def systems(registry: dict) -> list[str]:
    """The systems the targets cover, in the order the registry names them."""
    return list(dict.fromkeys(t["system"] for t in registry["targets"].values()))


def requirements_text(registry: dict) -> str:
    """requirements.txt for running the source tree: every system's packages,
    with a marker on those only some systems need."""
    each = {system: set(requirements(registry, system)) for system in systems(registry)}
    everywhere = set.intersection(*each.values())
    lines = [
        f"# What Forge {registry['version']} needs to run from source"
        " (python3 forge_portable.py).",
        "# Made by release/build.py from release/release.json; downloads bring"
        " their own.",
    ]
    lines += sorted(everywhere, key=project)
    for req in sorted(set.union(*each.values()) - everywhere, key=project):
        where = " or ".join(MARKERS[system] for system in each if req in each[system])
        lines.append(f"{req}; {where}")
    return "\n".join(lines) + "\n"


def apps_text(registry: dict, files: list[File]) -> str:
    """The README's list of apps: name, tagline and the systems it skips."""
    by_rel = {f.rel: f for f in files}
    rows = []
    for name in included_apps(registry):
        manifest = json.loads(by_rel[f"apps/{name}/forge_app.json"].data)
        label = manifest.get("label") or name
        line = f"- **{label}**"
        if manifest.get("tagline"):
            line += f": {manifest['tagline']}"
        skips = [
            SYSTEM_NAMES[system]
            for system in systems(registry)
            if name in cut_apps(registry, system)
        ]
        if skips:
            line += f" (not on {', '.join(skips)})"
        rows.append((label.lower(), line))
    return "\n".join(line for _, line in sorted(rows))


def source_readme(registry: dict, template: str, files: list[File]) -> str:
    """release/source/README.md filled in: version, apps, needs, per-system
    notes and licence."""
    names = labels(files)
    needs = [
        f"- **{names.get(name, name)}**: {registry['apps'][name]['needs']}"
        for name in included_apps(registry)
        if registry["apps"][name].get("needs")
    ]
    notes = []
    for system in systems(registry):
        lines = system_notes(registry, system, names)
        notes += [f"### {SYSTEM_NAMES[system]}", "", "```", *lines, "```", ""]
    licence = registry.get("licence") or ""
    licence_text = (
        f"Forge is released under the {licence} licence: see LICENSE."
        if licence
        else "No licence has been chosen yet, so all rights are reserved for now."
    )
    text = template
    for key, value in (
        ("@VERSION@", registry["version"]),
        ("@SUMMARY@", registry.get("summary", "")),
        ("@APPS@", apps_text(registry, files)),
        ("@NEEDS@", "\n".join(needs) or "None."),
        ("@SYSTEM_NOTES@", "\n".join(notes).rstrip()),
        ("@LICENCE@", licence_text),
    ):
        text = text.replace(key, value)
    text = re.sub(r"\A<!--.*?-->\n+", "", text, flags=re.S)
    left = sorted(set(re.findall(r"@[A-Z_]+@", text)))
    if left:
        raise BuildError(f"release/source/README.md: unknown fields {left}")
    return text


def source_tree(registry: dict, files: list[File], out: Path) -> tuple[Path, int]:
    """The checked files as a source tree, with the top files the registry's
    source.top maps from release/source/ (README.md filled in) and a
    requirements.txt. The made files get checks 1 and 2 as well."""
    top = out / f"forge-{registry['version']}-source"
    if top.exists():
        raise BuildError(f"{top} already exists: pick another --out")
    by_rel = {f.rel: f for f in files}
    made: list[File] = []
    for rel, dest in ((registry.get("source") or {}).get("top") or {}).items():
        if rel not in by_rel:
            raise BuildError(f"{rel} (named in source.top) is not in the tree")
        data = by_rel[rel].data
        if dest == "README.md":
            data = source_readme(registry, data.decode("utf-8"), files).encode()
        made.append(File(dest, data, by_rel[rel].mode))
    made.append(File("requirements.txt", requirements_text(registry).encode(), 0o644))
    problems = forbidden(made, registry) + clean_problems(made)
    if problems:
        raise BuildError("made files fail the checks:\n  " + "\n  ".join(problems))
    tree = files + made
    write_files(tree, top)
    return top, len(tree)


def main(argv: list[str] | None = None) -> int:
    registry = load_registry()
    parser = argparse.ArgumentParser(description="Build Forge release bundles.")
    parser.add_argument(
        "--target", action="append", choices=sorted(registry["targets"])
    )
    parser.add_argument(
        "--from", dest="origin", default="head", choices=["head", "worktree"]
    )
    parser.add_argument(
        "--out", help="output folder (default outputs/release/<version>)"
    )
    parser.add_argument(
        "--check-only", action="store_true", help="files and checks only"
    )
    parser.add_argument(
        "--source-tree",
        action="store_true",
        help="write the release as a source tree for a git repository",
    )
    args = parser.parse_args(argv)
    out = Path(args.out or ROOT / "outputs" / "release" / registry["version"]).resolve()
    names = args.target or sorted(registry["targets"])
    try:
        if clean_module() is None:
            print(NOT_CHECKED, flush=True)
        files, left, scrubbed = check_files(registry, args.origin, args.source_tree)
        print(
            f"[build] {len(files)} files pass the scrub and clean checks"
            f" ({len(left)} left out, {len(scrubbed)} scrubbed)",
            flush=True,
        )
        if args.check_only:
            # No bundle is made, so the licence check reads the apps' own
            # venvs (a full build checks the packages it really ships).
            if licence_module().main(["--deny"]) != 0:
                raise BuildError(
                    "a package's licence is not allowed (release/licence_policy.json)"
                )
            return 0
        out.mkdir(parents=True, exist_ok=True)
        if args.source_tree:
            top, count = source_tree(registry, files, out)
            print(f"[build] source tree: {top} ({count} files)", flush=True)
            return 0
        python = host_python(registry)
        wheels = wheelhouse(registry, python)
        report = {
            "name": registry.get("name", "Forge"),
            "version": registry["version"],
            "built": dt.datetime.now().isoformat(timespec="seconds"),
            "source": git_state(args.origin, registry),
            "clean_check": "apps/backup/clean.py" if clean_module() else "skipped",
            "targets": {},
            "left_out": left,
            "scrubbed": scrubbed,
        }
        # Each bundle is laid out in a folder of its own under --out (on
        # disk: /tmp is often memory) that goes away once it is packed.
        with tempfile.TemporaryDirectory(dir=out, prefix=".build-") as stage:
            for name in names:
                report["targets"][name] = build_target(
                    name, registry, files, out, Path(stage), python, wheels
                )
    except BuildError as e:
        print(f"[build] stopped: {e}", file=sys.stderr, flush=True)
        return 1
    sums = out / "SHA256SUMS"
    lines = {
        line.split("  ", 1)[1]: line
        for line in (sums.read_text().splitlines() if sums.is_file() else [])
        if "  " in line
    }
    for result in report["targets"].values():
        lines[result["archive"]] = f"{result['sha256']}  {result['archive']}"
        if result.get("setup"):
            lines[result["setup"]] = f"{result['setup_sha256']}  {result['setup']}"
    sums.write_text("".join(lines[k] + "\n" for k in sorted(lines)))
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out / f"report-{stamp}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for name, result in report["targets"].items():
        print(
            f"[build] {name}: {result['archive']} {result['archive_bytes'] / 1e6:.0f} MB,"
            f" {result['files']} files, {len(result['import_warnings'])} import warnings,"
            f" {len(result['licence_warnings'])} licence warnings",
            flush=True,
        )
        if result.get("setup"):
            print(
                f"[build] {name}: {result['setup']}"
                f" {result['setup_bytes'] / 1e6:.0f} MB",
                flush=True,
            )
    print(f"[build] report: {path}", flush=True)
    if clean_module() is None:
        print(NOT_CHECKED, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
