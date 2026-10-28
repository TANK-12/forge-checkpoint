"""Time Jan models on Taleforge's own prompts. Plays a few turns in-process
(no server, no save), takes the narration and dialogue jobs those turns make,
and sends each to every model named, printing tokens/sec, seconds and what
survives the guard. Usage:

    .venv/bin/python tools/model_bench.py MODEL [MODEL ...] [--url URL]

MODEL is a Jan model id, or `id@http://127.0.0.1:PORT/v1` to time a model on
its own llama-server (one Jan's router has not listed yet)."""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path
import os

os.environ.setdefault("TALEFORGE_DATA", tempfile.mkdtemp(prefix="taleforge-bench-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taleforge import narrator  # noqa: E402
from taleforge.core import GameError  # noqa: E402
from taleforge.game import start_game  # noqa: E402
from taleforge.world import CAMPAIGNS, World  # noqa: E402

forge_jan = narrator.forge_jan
TURNS = ["look around", "talk to {who}", "say to {who} what brings you here?", "look"]


def jobs(campaign: str, per_role: int) -> list[tuple[str, list[dict]]]:
    world = World(CAMPAIGNS / campaign)
    cls = next(iter(world.rules["_classes"]))
    background = next(iter(world.rules["_backgrounds"]))
    spec = {
        "name": "Aren",
        "pronouns": "they/them",
        "class": cls,
        "background": background,
        "method": "array",
        "scores": dict(zip(world.rules["_abilities"], [15, 13, 14, 10, 12, 8])),
        "skills": [],
    }
    taken = world.rules["_backgrounds"][background].get("skills", [])
    spec["skills"] = [
        s for s in world.rules["_classes"][cls]["skill_options"] if s not in taken
    ][: world.rules["_classes"][cls]["skill_count"]]
    game = start_game(world, spec, seed=3)
    entries = list(game.s.get("log", []))
    for ex in game.location().get("exits", []):
        if game.people_here():
            break
        try:  # walk on until someone is here to talk to
            entries += game.act({"do": "go", "to": ex["to"]})
        except GameError:
            pass
    here = game.people_here()
    who = game.person_name(here[0]).split()[0].lower() if here else "nobody"
    for turn in TURNS:
        try:
            entries += game.act({"do": "text", "text": turn.format(who=who)})
        except GameError:
            pass
    out: list[tuple[str, list[dict]]] = []
    for e in entries:
        job = e.get("jan")
        if job and sum(r == job["role"] for r, _ in out) < per_role:
            out.append((job["role"], narrator.messages_for(game, e)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--url", default=forge_jan.BASE_URL)
    ap.add_argument("--campaign", default="hollow-crown")
    ap.add_argument("--per-role", type=int, default=3)
    args = ap.parse_args()
    work = jobs(args.campaign, args.per_role)
    for spec in args.models:
        model, _, url = spec.partition("@")
        tps, secs, kept = [], [], 0
        print(f"\n=== {model}")
        for role, msgs in work:
            stats: dict = {}
            start = time.monotonic()
            try:
                raw = forge_jan.chat_messages(
                    model,
                    msgs,
                    temperature=narrator.TEMPERATURE[role],
                    max_tokens=narrator.MAX_TOKENS[role],
                    timeout=narrator.TIMEOUT,
                    base_url=url or args.url,
                    stats=stats,
                )
            except forge_jan.JanError as exc:
                print(f"[{role}] failed: {exc}")
                continue
            took = time.monotonic() - start
            shown = narrator.clean(raw, role)
            kept += shown is not None
            secs.append(took)
            if stats.get("gen_tps"):
                tps.append(stats["gen_tps"])
            print(
                f"[{role}] {took:.1f} s, {stats.get('gen_tps') or 0:.1f} tok/s, "
                f"prompt {stats.get('prompt_tokens')} tok at {stats.get('prompt_tps') or 0:.0f} tok/s"
            )
            print("   " + (shown or f"(guard dropped it) {raw[:200]!r}"))
        if secs:
            print(
                f"--- {model}: mean {sum(secs) / len(secs):.1f} s per line, "
                f"{(sum(tps) / len(tps)) if tps else 0:.1f} tok/s, {kept}/{len(work)} kept"
            )


if __name__ == "__main__":
    main()
