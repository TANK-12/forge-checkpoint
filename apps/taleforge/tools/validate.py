"""Check a campaign folder: broken references, unknown keys, bad dice.

.venv/bin/python tools/validate.py campaigns/hollow-crown
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from taleforge.world import World, validate  # noqa: E402


def main(argv: list[str]) -> int:
    folders = argv or [str(p.parent) for p in Path("campaigns").glob("*/campaign.json")]
    worst = 0
    for folder in folders:
        world = World(Path(folder))
        problems = validate(world)
        counts = ", ".join(f"{n} {k}" for k, n in world.counts().items() if n)
        print(f"{world.id}: {counts}")
        for p in problems:
            print("  " + p)
        print(f"  {len(problems)} problem(s)")
        worst = max(worst, 1 if problems else 0)
    return worst


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
