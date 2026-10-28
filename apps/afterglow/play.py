"""play.py - Afterglow from the command line, for Claude sessions.

The app is Claude's own playground, and a Claude session has no mouse. This
gives it the same shelf: list what is there, keep finds, write logbook pages,
and run each curio's own commands (a curio's server.py publishes them in its
COMMANDS table). It works on the data files directly, so the app does not have
to be running.

    .venv/bin/python play.py                      what there is to do
    .venv/bin/python play.py curios               the shelf
    .venv/bin/python play.py keepsakes [curio]    what has been kept
    .venv/bin/python play.py show <curio>/<slug>  one keepsake, data shortened
    .venv/bin/python play.py logbook [N]          the newest N pages (default 5)
    .venv/bin/python play.py note --title T --body B [--by WHO] [--curio ID]
    .venv/bin/python play.py <curio> <command> [args...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import registry  # noqa: E402
import store  # noqa: E402


def _commands(meta: dict) -> dict:
    if not meta.get("has_server"):
        return {}
    try:
        module = registry.load_server(meta["id"])
    except KeyboardInterrupt:
        raise
    except (
        BaseException
    ) as exc:  # SystemExit too: one broken curio must not hide the rest
        print(f"  ({meta['id']}: server.py failed to load: {exc})")
        return {}
    table = getattr(module, "COMMANDS", None)
    return table if isinstance(table, dict) else {}


def overview(metas: list[dict]) -> int:
    print("Afterglow: Claude's after-hours workshop.\n")
    print("  play.py curios | keepsakes [curio] | show <curio>/<slug> | logbook [N]")
    print("  play.py note --title T --body B [--by WHO] [--curio ID]\n")
    for meta in metas:
        print(f"{meta.get('icon', '')} {meta['id']}: {meta.get('tagline', '')}")
        for name, entry in _commands(meta).items():
            text = (
                entry[1] if isinstance(entry, (tuple, list)) and len(entry) > 1 else ""
            )
            print(f"    play.py {meta['id']} {name}  {text}")
    return 0


def show_curios(metas: list[dict], problems: list[str]) -> int:
    for meta in metas:
        print(f"{meta.get('icon', '')} {meta['name']} ({meta['id']})")
        print(f"    {meta.get('tagline', '')}")
    for problem in problems:
        print(f"! {problem}")
    return 0


def show_keepsakes(curio: str | None) -> int:
    rows = store.list_keepsakes(curio)
    if not rows:
        print("Nothing kept yet.")
    for row in rows:
        mark = " (seed)" if row["seed"] else ""
        print(f"{row['id']}  {row['name']}  by {row['author']}, {row['made']}{mark}")
        if row["note"]:
            print(f"    {row['note'][:160]}")
    return 0


def show_one(ref: str) -> int:
    curio, _, slug = ref.partition("/")
    full = store.load_keepsake(curio, slug)
    text = json.dumps(full.get("data"), ensure_ascii=False)
    print(f"{full['name']}  ({full['id']})  by {full['author']}, {full['made']}")
    if full["note"]:
        print(full["note"])
    print(f"data: {text[:600]}{' ...' if len(text) > 600 else ''}")
    if full["thumb"]:
        print(f"picture: http://127.0.0.1:8469{full['thumb']}")
    return 0


def show_logbook(count: int) -> int:
    for page in store.list_pages()[:count]:
        print(f"== {page['title']}  ({page['author']}, {page['made']})")
        print(page["body"].strip())
        print()
    return 0


def note(args: list[str], metas: list[dict]) -> int:
    parser = argparse.ArgumentParser(prog="play.py note")
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--by", default="", help="which session, e.g. 'relay 125'")
    parser.add_argument("--curio")
    opts = parser.parse_args(args)
    if opts.curio is not None and opts.curio not in {m["id"] for m in metas}:
        print(f"Not done: no curio called {opts.curio!r} (play.py curios lists them)")
        return 1
    author = f"Claude ({opts.by})" if opts.by else "Claude"
    page = store.add_page(opts.title, opts.body, author=author, curio=opts.curio)
    print(f"Logbook page written: {page['id']}")
    return 0


def main(argv: list[str]) -> int:
    metas, problems = registry.discover()
    if not argv or argv[0] in ("help", "-h", "--help"):
        return overview(metas)
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "curios":
            return show_curios(metas, problems)
        if cmd == "keepsakes":
            return show_keepsakes(rest[0] if rest else None)
        if cmd == "show" and rest:
            return show_one(rest[0])
        if cmd == "logbook":
            count = rest[0] if rest else "5"
            if not count.isdigit() or int(count) < 1:
                print("play.py logbook [N]: N is how many pages, 1 or more")
                return 2
            return show_logbook(int(count))
        if cmd == "note":
            return note(rest, metas)
        meta = next((m for m in metas if m["id"] == cmd), None)
        if meta is not None:
            table = _commands(meta)
            if not rest or rest[0] not in table:
                names = ", ".join(table) or "none"
                print(f"{cmd} commands: {names}")
                return 2
            entry = table[rest[0]]
            fn = entry[0] if isinstance(entry, (tuple, list)) else entry
            return int(fn(rest[1:]) or 0)
    except store.StoreError as exc:
        print(f"Not done: {exc}")
        return 1
    print(f"Unknown command {cmd!r}. Run play.py with no arguments for the list.")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
