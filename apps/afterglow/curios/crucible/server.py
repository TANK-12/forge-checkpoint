"""Crucible from the command line: run a scene headless and look at it.

The world lives in JavaScript (sim.js), so these commands run it through
node (tools/play.mjs) rather than keep a second copy of the physics here.
No routes: the browser side needs none. Nothing happens at import; the only
file written is a keepsake, through store, under store.data_dir().

    play.py crucible run [scene] [--steps N] [--cols C]
    play.py crucible keep [scene] --name NAME [--steps N] [--note TEXT]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import store

HERE = Path(__file__).resolve().parent
CURIO = "crucible"
SCENES = ["starter", "showcase", "bloomery", "fulgurites", "thaw", "rain-on-iron"]
KEY = (
    "  # stone  . sand  ~ water  o ore  @ molten iron  I iron  i iron shot\n"
    "  : coal  * live coal  ^ fire  ' steam  = ice  | wood  g glass"
)


class NodeMissing(RuntimeError):
    pass


def run_scene(scene: str, steps: int, cols: int = 80) -> dict[str, Any]:
    """Run a scene for `steps` steps in node and return what play.mjs reports."""
    node = shutil.which("node")
    if node is None:
        raise NodeMissing("node is not on PATH, and the world runs in node")
    proc = subprocess.run(
        [node, str(HERE / "tools" / "play.mjs"), scene, str(steps), str(cols)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    if not line:
        raise RuntimeError(proc.stderr.strip() or "node printed nothing")
    out = json.loads(line)
    if "error" in out:
        raise ValueError(f"{out['error']}; scenes: {', '.join(out.get('scenes', []))}")
    return out


def report(out: dict[str, Any], picture: bool = True) -> None:
    print(
        f"{out['scene']} after {out['steps']} steps "
        f"({out['ms_per_step']:.2f} ms a step), hottest {out['hottest']} C"
    )
    if picture:
        print("\n".join(out["picture"]))
        print(KEY)
    after = ", ".join(f"{k} {v}" for k, v in out["after"].items())
    print(f"now: {after}")
    ev = out["events"]
    print(
        f"so far: {ev['melted']} melted, {ev['quenched']} quenched, "
        f"{ev['glassed']} fused to glass, {ev['lit']} caught fire, {ev['boiled']} boiled"
    )


def _parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("scene", nargs="?", default="starter", choices=SCENES)
    parser.add_argument("--steps", type=int, default=600, help="steps to run (0-20000)")
    return parser


def cli_run(args: list[str]) -> int:
    parser = _parser("play.py crucible run")
    parser.add_argument("--cols", type=int, default=80, help="picture width (20-240)")
    opts = parser.parse_args(args)
    try:
        out = run_scene(opts.scene, opts.steps, opts.cols)
    except (NodeMissing, RuntimeError, ValueError) as exc:
        print(f"Could not run it: {exc}")
        return 1
    report(out)
    return 0


def cli_keep(args: list[str]) -> int:
    parser = _parser("play.py crucible keep")
    parser.add_argument("--name", required=True)
    parser.add_argument("--note", default="")
    opts = parser.parse_args(args)
    try:
        out = run_scene(opts.scene, opts.steps)
    except (NodeMissing, RuntimeError, ValueError) as exc:
        print(f"Could not run it: {exc}")
        return 1
    report(out, picture=False)
    row = store.save_keepsake(
        CURIO, name=opts.name, note=opts.note, data=out["data"], author="Claude"
    )
    print(f"Kept as {row['id']}")
    return 0


COMMANDS = {
    "run": (cli_run, "run a scene headless and print a text picture and a census"),
    "keep": (cli_keep, "run a scene and keep the result as a keepsake"),
}
