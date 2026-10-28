"""Swarm, the Python half: play.py commands that run the simulation headless.

The simulation is sim.js, run in node through cli.mjs, so a rule table behaves
exactly as it does in the browser and nothing is ported twice. Python reads
the answer, prints what happened, draws the last moment to a PNG a session can
open, and keeps what is worth keeping.

    play.py swarm run [SLUG] [--seconds S] [--mirror] [--keep NAME] [--note T]
    play.py swarm hunt [--tries N] [--seconds S] [--colours K] [--seed N]
                       [--mirror] [--keep NAME] [--note T]

`run` plays one table (a keepsake's, Cell weather by default) and prints how
gathered and how fast it is each second. `hunt` rolls random tables and ranks
them: chases first, then settled shapes, then mist. Nothing happens at import;
files are only written under store.data_dir().
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
from pathlib import Path
from typing import Any

import kit
import store

HERE = Path(__file__).resolve().parent
CURIO = "swarm"
DEFAULT_SLUG = "cell-weather"
BG = (15, 17, 21)
NODE_TIMEOUT = 900


class SwarmError(Exception):
    """The node runner is missing or did not answer."""


def node_path() -> str | None:
    return shutil.which("node")


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    """One job through cli.mjs; the answer as a dict."""
    node = node_path()
    if not node:
        raise SwarmError(
            "node is not installed, and the swarm runs in node (sim.js). "
            "Install it, or open Swarm in the app instead."
        )
    try:
        done = subprocess.run(
            [node, str(HERE / "cli.mjs"), json.dumps(job)],
            capture_output=True,
            text=True,
            timeout=NODE_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SwarmError(
            f"the swarm ran past {NODE_TIMEOUT} s and was stopped"
        ) from exc
    if done.returncode != 0:
        raise SwarmError(done.stderr.strip() or f"node exited with {done.returncode}")
    try:
        return json.loads(done.stdout)
    except ValueError as exc:
        raise SwarmError(f"node's answer did not read as JSON ({exc})") from exc


def _hex(colour: str) -> tuple[int, int, int]:
    c = colour.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def picture_rgb(
    points: dict[str, Any], colours: list[str], width: int = 800, dot: int = 2
) -> tuple[int, int, bytearray]:
    """The swarm's last moment as RGB rows: dots added onto the dark background."""
    w_world = float(points["W"])
    h_world = float(points["H"])
    width = max(16, int(width))
    height = max(16, round(width * h_world / w_world))
    rgb = bytearray(bytes(BG) * (width * height))
    palette = [_hex(c) for c in colours] or [(255, 180, 84)]
    k = max(1, int(points["k"]))
    sx = width / w_world
    sy = height / h_world
    for i, (x, y) in enumerate(zip(points["x"], points["y"])):
        r, g, b = palette[(i % k) % len(palette)]
        px = int(x * sx) - dot // 2
        py = int(y * sy) - dot // 2
        for yy in range(py, py + dot):
            row = (yy % height) * width
            for xx in range(px, px + dot):
                at = (row + (xx % width)) * 3
                rgb[at] = min(255, rgb[at] + r * 85 // 100)
                rgb[at + 1] = min(255, rgb[at + 1] + g * 85 // 100)
                rgb[at + 2] = min(255, rgb[at + 2] + b * 85 // 100)
    return width, height, rgb


def write_picture(name: str, points: dict[str, Any], colours: list[str]) -> Path:
    w, h, rgb = picture_rgb(points, colours)
    target = store.data_dir() / CURIO / f"{store.slugify(name, 'swarm')}.png"
    return kit.write_png(target, w, h, rgb)


def thumb_url(points: dict[str, Any], colours: list[str]) -> str:
    """A small PNG data URL for a keepsake card, under the 200 KB limit."""
    for width in (320, 240, 160):
        w, h, rgb = picture_rgb(points, colours, width, dot=2)
        url = kit.png_data_url(w, h, rgb)
        if len(url) <= store.MAX_THUMB:
            return url
    return url


def keep(rules: dict[str, Any], name: str, note: str, thumb: str) -> dict[str, Any]:
    return store.save_keepsake(
        CURIO, name=name, note=note, data=rules, author="Claude", thumb=thumb
    )


def _rules_for(slug: str) -> dict[str, Any]:
    return store.load_keepsake(CURIO, slug)["data"]


def _keep_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mirror", action="store_true", help="make the rules mutual first"
    )
    parser.add_argument("--keep", metavar="NAME", default=None)
    parser.add_argument("--note", default="")


def _seconds(text: str) -> float:
    value = float(text)
    if not 0.1 <= value <= 120:
        raise argparse.ArgumentTypeError("seconds go from 0.1 to 120")
    return value


def cli_run(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="play.py swarm run")
    parser.add_argument("slug", nargs="?", default=DEFAULT_SLUG)
    parser.add_argument("--seconds", type=_seconds, default=10.0)
    _keep_args(parser)
    opts = parser.parse_args(args)
    try:
        rules = _rules_for(opts.slug)
        out = run_job(
            {
                "do": "run",
                "rules": rules,
                "seconds": opts.seconds,
                "every": 1,
                "mirror": opts.mirror,
            }
        )
    except (store.StoreError, SwarmError) as exc:
        print(f"Did not run: {exc}")
        return 1
    print(
        f"{opts.slug}{' (mirrored)' if opts.mirror else ''}, {out['rules']['count']} particles:"
    )
    for frame in out["frames"]:
        print(
            f"  {frame['t']:>6.2f} s  gathered {frame['gathered']:>5.2f}x  speed {frame['speed']:.4f}"
        )
    print(f"After {out['frames'][-1]['t']:g} s it is {out['words']}.")
    path = write_picture(
        f"{opts.slug}{'-mirrored' if opts.mirror else ''}",
        out["points"],
        out["colours"],
    )
    print(f"Picture: {path}")
    if opts.keep:
        row = keep(
            out["rules"], opts.keep, opts.note, thumb_url(out["points"], out["colours"])
        )
        print(f"Kept as {row['id']}")
    return 0


def cli_hunt(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="play.py swarm hunt")
    parser.add_argument("--tries", type=int, default=8)
    parser.add_argument("--seconds", type=_seconds, default=8.0)
    parser.add_argument("--colours", type=int, default=5)
    parser.add_argument("--seed", type=int, default=None)
    _keep_args(parser)
    opts = parser.parse_args(args)
    if not 1 <= opts.tries <= 200:
        parser.error("--tries goes from 1 to 200")
    if not 2 <= opts.colours <= 8:
        parser.error("--colours goes from 2 to 8")
    seed = opts.seed if opts.seed is not None else random.getrandbits(31)
    job = {
        "do": "hunt",
        "tries": opts.tries,
        "seconds": opts.seconds,
        "colours": opts.colours,
        "seed": seed,
        "mirror": opts.mirror,
    }
    try:
        out = run_job(job)
    except SwarmError as exc:
        print(f"Did not hunt: {exc}")
        return 1
    rows = out["rows"]
    print(
        f"{len(rows)} tables from seed {seed}, {opts.seconds:g} s each{', mirrored' if opts.mirror else ''}:"
    )
    for row in rows:
        print(
            f"  seed {row['seed']:>10}  gathered {row['gathered']:>5.2f}x  speed {row['speed']:.4f}  {row['kind']}"
        )
    best = rows[0]
    print(f"Best: seed {best['seed']}, {best['words']}.")
    path = write_picture(f"hunt-{best['seed']}", out["best"], out["colours"])
    print(f"Picture: {path}")
    if opts.keep:
        kept = keep(
            best["rules"], opts.keep, opts.note, thumb_url(out["best"], out["colours"])
        )
        print(f"Kept as {kept['id']}")
    return 0


COMMANDS = {
    "run": (
        cli_run,
        "[SLUG] [--seconds S] [--mirror] [--keep NAME]  play a kept swarm headless, write a PNG",
    ),
    "hunt": (
        cli_hunt,
        "[--tries N] [--seconds S] [--colours K] [--seed N] [--mirror] [--keep NAME]  rank random rule tables",
    ),
}
