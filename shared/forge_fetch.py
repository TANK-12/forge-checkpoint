"""Pinned programs, fetched on first use.

An app that needs a program Forge does not ship (Atlas: go-pmtiles, Convert:
pandoc) names one release archive in its own json, with the sha256 of that
archive and the path of the program inside it:

    {"version": "3.12.1",
     "url": "https://github.com/jgm/pandoc/releases/download/3.12.1/pandoc-3.12.1-linux-amd64.tar.gz",
     "sha256": "d0c9...",
     "member": "pandoc-3.12.1/bin/pandoc"}

pinned_tool() fetches it once, refuses it when the sha256 differs, and keeps
the program in the app's bin folder with a version stamp beside it, so a new
version in the json fetches again. One fetch runs at a time; the program is
written under its own temporary name and moved into place whole.
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
import tarfile
import threading
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Callable

LOCK = threading.Lock()


class FetchError(Exception):
    """Said to the person as it is."""


def fetch(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Forge"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _member(body: bytes, member: str) -> bytes:
    """The one file `member` out of a .tar(.gz) or .zip archive."""
    if body[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            try:
                return z.read(member)
            except KeyError:
                raise FetchError(f"the archive has no {member}") from None
    try:
        with tarfile.open(fileobj=io.BytesIO(body)) as tar:
            f = tar.extractfile(member)
            if f is None:
                raise FetchError(f"the archive has no {member}")
            return f.read()
    except KeyError:
        raise FetchError(f"the archive has no {member}") from None
    except tarfile.TarError as e:
        raise FetchError(f"the archive could not be read ({e})") from None


def is_ready(spec: dict, bin_dir: Path) -> bool:
    """Whether this version is already fetched (nothing is fetched to ask)."""
    name = spec.get("name") or Path(spec["member"]).name
    exe, stamp = bin_dir / name, bin_dir / f"{name}.version"
    return (
        exe.is_file()
        and stamp.is_file()
        and stamp.read_text().strip() == spec["version"]
    )


def pinned_tool(
    spec: dict,
    bin_dir: Path,
    get: Callable[[str], bytes] | None = None,
    say: Callable[[str], None] | None = None,
) -> Path:
    """The program `spec` names, fetched and checked the first time."""
    get = get or fetch
    name = spec.get("name") or Path(spec["member"]).name
    exe, stamp = bin_dir / name, bin_dir / f"{name}.version"
    with LOCK:
        if is_ready(spec, bin_dir):
            return exe
        if say:
            say(f"Fetching {name} {spec['version']} once (checked against its sha256)")
        try:
            body = get(spec["url"])
        except OSError as e:
            # The reason goes to the app's log; the person gets plain words.
            print(f"forge_fetch: {name} from {spec['url']}: {e}", file=sys.stderr)
            if isinstance(e, urllib.error.HTTPError):
                why = f"the download site answered {e.code}. Try again later."
            else:
                why = "the internet could not be reached. Check the connection and try again."
            raise FetchError(f"could not fetch {name}: {why}") from None
        if hashlib.sha256(body).hexdigest() != spec["sha256"]:
            raise FetchError(f"{name} did not match its pinned sha256; not used")
        data = _member(body, spec["member"])
        bin_dir.mkdir(parents=True, exist_ok=True)
        tmp = bin_dir / f"{name}.{uuid.uuid4().hex[:8]}.part"
        try:
            tmp.write_bytes(data)
            tmp.chmod(0o755)
            os.replace(tmp, exe)
        finally:
            tmp.unlink(missing_ok=True)
        stamp.write_text(spec["version"])
        return exe
