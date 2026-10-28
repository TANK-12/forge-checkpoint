"""Write Janhollow's carryable items, and what each crew member likes.

Items are one file each in ~/ForgeGameData/janhollow/items/, drawn from sprites
that already exist in the janhollow-space pack. Likes are merged into the crew
files that are already there: a crew member who has a `likes` list keeps it
unless --force says otherwise, and nothing else in their file is touched.
Run it after seed_content.py, which writes the crew.

    .venv/bin/python tools/seed_items.py [--force]
"""

import json
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TOOLS))
sys.path.insert(0, TOOLS)

from janhollow import content  # noqa: E402
from seed_content import write  # noqa: E402

ITEMS = [
    {
        "id": "toolbox",
        "label": "toolbox",
        "sprite": "toolbox",
        "starts_in": ["workshop"],
        "tags": ["work"],
    },
    {
        "id": "sapling",
        "label": "sapling",
        "sprite": "sapling",
        "starts_in": ["hydroponics"],
        "tags": ["garden"],
    },
    {
        "id": "mail-sack",
        "label": "mail sack",
        "sprite": "mail_sack",
        "starts_in": ["comms"],
        "tags": ["post"],
    },
    {
        "id": "cake",
        "label": "cake",
        "sprite": "cake",
        "starts_in": ["galley"],
        "tags": ["food"],
    },
    {
        "id": "crate",
        "label": "crate of supplies",
        "sprite": "crate_stack",
        "starts_in": ["cargo_bay"],
        "tags": ["supplies"],
    },
]

# Crew id -> item ids they are glad to be given. Chosen from their jobs and
# personalities, so a gift says you noticed who they are.
LIKES = {
    "vessa-oduya": ["mail-sack"],
    "bo-ferreira": ["crate", "sapling"],
    "tamsin-reyes": ["toolbox"],
    "ilya-novak": ["sapling"],
    "mira-song": ["cake", "sapling"],
    "co-amari": ["mail-sack"],
    "dez-halloway": ["crate", "cake"],
    "juno-park": ["cake"],
}


def merge_likes(force):
    changed, kept = 0, 0
    for crew_id, likes in LIKES.items():
        path = content.STORE.entry_path("npcs", crew_id)
        if not os.path.exists(path):
            print(f"  no crew file for {crew_id}; run seed_content.py first")
            continue
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
        if record.get("likes") and not force:
            kept += 1
            continue
        record["likes"] = likes
        content.STORE.save("npcs", record)
        changed += 1
    print(f"likes: {changed} crew updated, {kept} left alone")


def main():
    force = "--force" in sys.argv
    content.STORE.ensure_root()
    write("items", ITEMS, force)
    merge_likes(force)
    result = content.store()
    for problem in result["problems"]:
        print("  problem:", problem)
    print({k: len(v) for k, v in result["types"].items()})


if __name__ == "__main__":
    if {"-h", "--help"} & set(sys.argv[1:]):  # usage only, no work
        print(__doc__)
        sys.exit(0)
    main()
