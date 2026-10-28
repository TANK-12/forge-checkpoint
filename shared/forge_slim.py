"""Keep a Forge process's resident memory close to what Python really holds.

Measured 2026-10-22: Mission's day-old backend sat at about
280 MB PSS while Python itself held under 2 MB of live objects and about
75 MB RSS in total after hours of polling. The rest was transparent huge
pages: the laptop runs THP "always" with khugepaged's max_ptes_none at 511,
so a 2 MB stretch of malloc heap with one page in use gets collapsed into a
whole resident huge page (225 MB of Mission's 280 MB). Every other Forge
Python process carried the same weight: forge.py 40 MB of 174, the Claude
backend 32 of 131, each small app backend about 26 of its 45, the particles
wallpaper 30 of 74.

slim() turns THP off for this process (prctl PR_SET_THP_DISABLE, which
khugepaged honours too) and caps glibc at two malloc arenas, so freed memory
stays reusable and is not pinned by huge pages. It uses the kernel's
"except advised" mode where there is one (memory a program asks huge pages
for with madvise still gets them) and plain "off" on older kernels. The THP
setting is inherited by every child and kept across exec, so forge.py
calling it once covers each app backend it starts (and wakes); the arena cap
is per process. Nothing an app does changes; elsewhere than Linux with glibc
it does nothing.

Model servers a backend launches (Jan from Dossier, jan-tune's scratch
llama-server, AI Studio's sd-server) would inherit it too, and their CPU
inference may want huge pages: they start through huge_pages(cmd), which
runs this file to switch THP back on and then execs the real command (same
pid and command line; no preexec_fn, which is unsafe in threaded servers).
"""

from __future__ import annotations

import ctypes
import os
import sys

PR_SET_THP_DISABLE = 41
PR_GET_THP_DISABLE = 42
EXCEPT_ADVISED = 1 << 1  # PR_THP_DISABLE_EXCEPT_ADVISED (Linux 6.18+)
M_ARENA_MAX = -8
ARENAS = 2


def _libc():
    if not sys.platform.startswith("linux"):
        return None
    try:
        return ctypes.CDLL(None, use_errno=True)
    except OSError:
        return None


def slim() -> dict[str, bool]:
    """Apply both settings; says which ones took."""
    libc = _libc()
    done = {"thp_off": False, "arenas": False}
    if libc is None:
        return done
    try:
        done["thp_off"] = (
            libc.prctl(PR_SET_THP_DISABLE, 1, EXCEPT_ADVISED, 0, 0) == 0
            or libc.prctl(PR_SET_THP_DISABLE, 1, 0, 0, 0) == 0
        )
    except AttributeError:
        pass
    try:
        done["arenas"] = libc.mallopt(M_ARENA_MAX, ARENAS) == 1
    except AttributeError:  # not glibc
        pass
    return done


def thp_off() -> bool:
    """True when huge pages are off for this process."""
    libc = _libc()
    if libc is None:
        return False
    try:
        # 1 when off, 3 when off except advised, -1 on error
        return libc.prctl(PR_GET_THP_DISABLE, 0, 0, 0, 0) > 0
    except AttributeError:
        return False


def huge_pages(cmd: list[str]) -> list[str]:
    """`cmd` with huge pages back on, for a model server started by a backend."""
    if not thp_off():
        return list(cmd)
    return [sys.executable, os.path.abspath(__file__), "--huge-pages", "--", *cmd]


def _exec_with_huge_pages(argv: list[str]) -> None:
    libc = _libc()
    if libc is not None:
        libc.prctl(PR_SET_THP_DISABLE, 0, 0, 0, 0)
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    if sys.argv[1:3] != ["--huge-pages", "--"] or len(sys.argv) < 4:
        sys.exit("usage: forge_slim.py --huge-pages -- CMD [ARG...]")
    _exec_with_huge_pages(sys.argv[3:])
