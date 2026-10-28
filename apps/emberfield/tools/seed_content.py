"""Write Emberfield's starting content into the shared content store.

A seeder, not a pipeline -- the same contract as seed_art.py. Running it writes
the defaults for anything missing; it will not overwrite a file you have edited
unless you pass --force. So this is safe to re-run to recover a deleted crop,
and safe to ignore once you have started tuning your own.

    python tools/seed_content.py            # fill in what is missing
    python tools/seed_content.py --force    # restore defaults, losing your edits
    python tools/seed_content.py --list     # show what is in the store now

Everything written here is namespaced emberfield-* because the store is shared.
"""

import argparse
import os
import sys

sys.path.insert(
    0,
    os.environ.get("FORGE_SHARED_DIR")
    or os.path.abspath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "shared"
        )
    ),
)

import forge_content  # noqa: E402

# --- items -----------------------------------------------------------------
# Seeds and produce. A crop points at these by id, which is the whole coupling
# between the two -- adding a crop and its two items is three files.

# (id, label, kind, sprite, sell, buy). A buy price above zero is what puts
# something on the stall's shelf -- there is no list of stocked items anywhere.
# Seeds are stocked and produce is not, so the loop is: buy seeds, grow them,
# sell what grew for more than the seeds cost.
ITEMS = [
    ("emberfield-turnip-seed", "Turnip seeds", "seed", "seed_bag", 12, 20),
    ("emberfield-turnip", "Turnip", "food", "crop_turnip_3", 35, 0),
    ("emberfield-barley-seed", "Barley seeds", "seed", "seed_bag", 18, 30),
    ("emberfield-barley", "Barley", "material", "crop_barley_3", 52, 0),
    ("emberfield-emberbloom-seed", "Emberbloom seeds", "seed", "seed_bag", 40, 90),
    ("emberfield-emberbloom", "Emberbloom", "material", "crop_emberbloom_3", 120, 0),
    ("emberfield-slime-gel", "Slime gel", "material", "", 8, 0),
    ("emberfield-ash", "Ash", "material", "", 5, 0),
    ("emberfield-ember-shard", "Ember shard", "material", "", 65, 0),
    # --- crafted goods (session 6) -------------------------------------
    # Raw drops are worth little; turning them into these at the workbench
    # or the hearth is the first thing to spend materials on that is not the
    # shop. sell prices sit well above the sum of the inputs' sell prices.
    ("emberfield-glue", "Pot of glue", "material", "", 34, 0),
    ("emberfield-charcoal", "Charcoal", "material", "", 16, 0),
    ("emberfield-ember-glass", "Ember glass", "material", "", 160, 0),
    ("emberfield-hearty-stew", "Hearty stew", "food", "", 90, 0),
    ("emberfield-field-ration", "Field ration", "food", "", 55, 0),
]


# Hearts a food gives back when eaten (e in the game). A food without a
# "heals" field heals one heart per 30 gold of its sell price, at least one;
# these say it outright so the numbers are there to tune.
HEALS = {
    "emberfield-turnip": 1,
    "emberfield-field-ration": 2,
    "emberfield-hearty-stew": 3,
}


def items():
    out = []
    for item_id, label, kind, sprite, sell, buy in ITEMS:
        entry = {
            "id": item_id,
            "label": label,
            "kind": kind,
            "sprite": sprite,
            "sell": sell,
            "buy": buy,
            "stack": 99,
        }
        if item_id in HEALS:
            entry["heals"] = HEALS[item_id]
        out.append(entry)
    return out


# --- loot ------------------------------------------------------------------
# What a chest at the deep end of a cavern can hold. Drawn by weight, so making
# something rare is a smaller number rather than a branch in the code, and
# gated by day and by darkness so the wilds pay better the further in you are
# willing to go.

LOOT = [
    {
        "id": "emberfield-common-cache",
        "label": "A dropped satchel",
        "items": ["emberfield-slime-gel", "emberfield-ash"],
        "gold_min": 15,
        "gold_max": 40,
        "weight": 20,
    },
    {
        "id": "emberfield-seed-cache",
        "label": "Someone's seed store",
        "items": ["emberfield-turnip-seed", "emberfield-barley-seed"],
        "gold_min": 5,
        "gold_max": 20,
        "weight": 14,
    },
    {
        "id": "emberfield-deep-cache",
        "label": "A miner's strongbox",
        "items": ["emberfield-ember-shard", "emberfield-emberbloom-seed"],
        "gold_min": 60,
        "gold_max": 140,
        "weight": 7,
        "night_only": True,
    },
    {
        "id": "emberfield-old-cache",
        "label": "Something older",
        "items": ["emberfield-ember-shard", "emberfield-ember-shard"],
        "gold_min": 120,
        "gold_max": 260,
        "weight": 4,
        "min_day": 6,
    },
]


# --- tools -----------------------------------------------------------------
# "verb" names the handler the game dispatches to. Two tools sharing a verb need
# no new code, which is the point of storing it as a string.

TOOLS = [
    {
        "id": "emberfield-hoe",
        "label": "Hoe",
        "verb": "till",
        "sprite": "tool_hoe",
        "range": 1,
        "power": 1,
    },
    {
        "id": "emberfield-watering-can",
        "label": "Watering can",
        "verb": "water",
        "sprite": "tool_can",
        "range": 1,
        "power": 1,
    },
]


# --- crops -----------------------------------------------------------------
# stages is days per growth stage, so len(stages) sprites are needed:
# crop_turnip_0 .. crop_turnip_3. Adding a crop is this dict and its two items.

CROPS = [
    {
        "id": "emberfield-turnip",
        "label": "Turnip",
        "sprite": "crop_turnip",
        "stages": [1, 1, 2, 2],
        "seasons": ["spring", "autumn"],
        "seed_item": "emberfield-turnip-seed",
        "yield_item": "emberfield-turnip",
        "yield_qty": 1,
        "regrow": 0,
    },
    {
        "id": "emberfield-barley",
        "label": "Barley",
        "sprite": "crop_barley",
        "stages": [2, 2, 2, 3],
        "seasons": ["summer", "autumn"],
        "seed_item": "emberfield-barley-seed",
        "yield_item": "emberfield-barley",
        "yield_qty": 2,
        "regrow": 0,
    },
    {
        "id": "emberfield-emberbloom",
        "label": "Emberbloom",
        "sprite": "crop_emberbloom",
        "stages": [2, 3, 3, 4],
        "seasons": ["summer"],
        "seed_item": "emberfield-emberbloom-seed",
        "yield_item": "emberfield-emberbloom",
        "yield_qty": 1,
        # Bears again four days after each harvest instead of dying, which is
        # what makes it worth its price.
        "regrow": 4,
    },
]


# --- weapons and foes ------------------------------------------------------

WEAPONS = [
    {
        "id": "emberfield-short-bow",
        "label": "Short bow",
        "sprite": "tool_bow",
        "damage": 1,
        "shot_speed": 190,
        "cooldown": 0.30,
        "shot_sprite": "arrow",
        "range": 190,
    },
]

FOES = [
    {
        "id": "emberfield-slime",
        "label": "Slime",
        "sprite": "foe_slime",
        "hp": 3,
        "speed": 17,
        "damage": 1,
        "touch": 7,
        "night_only": True,
        "weight": 14,
        "drops": ["emberfield-slime-gel"],
    },
    {
        "id": "emberfield-wisp",
        "label": "Ember wisp",
        "sprite": "foe_wisp",
        "hp": 2,
        "speed": 38,
        "damage": 1,
        "touch": 6,
        "night_only": True,
        "weight": 7,
        "drops": ["emberfield-ash"],
    },
]


# --- sounds ----------------------------------------------------------------
# Synthesised, not sampled. Each of these is a recipe for a small Web Audio
# graph, so the whole soundtrack costs about four kilobytes of JSON instead of
# megabytes of wav -- which matters on a laptop that is short on disk -- and
# every one of them can be retuned by editing a number rather than by opening
# an audio editor. "event" is what the game plays it on; adding a sound for a
# new event is one more file here and nothing else.

SOUNDS = [
    {
        "id": "emberfield-till",
        "label": "Hoe stroke",
        "event": "till",
        "wave": "noise",
        "duration": 0.22,
        "attack": 0.004,
        "gain": 0.34,
        "filter": 1400,
        "filter_to": 240,
    },
    {
        "id": "emberfield-water",
        "label": "Watering can",
        "event": "water",
        "wave": "noise",
        "duration": 0.45,
        "attack": 0.05,
        "gain": 0.22,
        "filter": 900,
        "filter_to": 2600,
    },
    {
        "id": "emberfield-plant",
        "label": "Seed sown",
        "event": "plant",
        "wave": "triangle",
        "freq": 520,
        "freq_to": 760,
        "duration": 0.14,
        "gain": 0.22,
    },
    {
        "id": "emberfield-harvest",
        "label": "Harvest",
        "event": "harvest",
        "wave": "triangle",
        "freq": 620,
        "freq_to": 980,
        "duration": 0.20,
        "gain": 0.30,
        "detune": 700,
    },
    {
        # Eating (e). A short soft bite of filtered noise rather than a tone,
        # so it never reads as a pickup or a harvest.
        "id": "emberfield-eat",
        "label": "Eat",
        "event": "eat",
        "wave": "noise",
        "duration": 0.16,
        "attack": 0.006,
        "gain": 0.3,
        "filter": 900,
        "filter_to": 320,
    },
    {
        "id": "emberfield-shoot",
        "label": "Bowstring",
        "event": "shoot",
        "wave": "noise",
        "duration": 0.13,
        "attack": 0.002,
        "gain": 0.26,
        "filter": 3000,
        "filter_to": 600,
    },
    {
        "id": "emberfield-hit",
        "label": "Arrow lands",
        "event": "hit",
        "wave": "square",
        "freq": 300,
        "freq_to": 120,
        "duration": 0.10,
        "gain": 0.24,
        "filter": 1800,
    },
    {
        "id": "emberfield-foe-dies",
        "label": "Foe dies",
        "event": "foe_dies",
        "wave": "sawtooth",
        "freq": 260,
        "freq_to": 60,
        "duration": 0.30,
        "gain": 0.26,
        "filter": 1600,
        "filter_to": 300,
    },
    {
        "id": "emberfield-hurt",
        "label": "You are hit",
        "event": "hurt",
        "wave": "square",
        "freq": 190,
        "freq_to": 90,
        "duration": 0.26,
        "gain": 0.34,
        "detune": -900,
        "filter": 1200,
    },
    {
        "id": "emberfield-die",
        "label": "You fall",
        "event": "die",
        "wave": "sawtooth",
        "freq": 220,
        "freq_to": 40,
        "duration": 1.30,
        "gain": 0.32,
        "filter": 1400,
        "filter_to": 180,
    },
    {
        "id": "emberfield-sleep",
        "label": "Sleep",
        "event": "sleep",
        "wave": "sine",
        "freq": 300,
        "freq_to": 140,
        "duration": 0.90,
        "attack": 0.10,
        "gain": 0.22,
        "detune": 400,
    },
    {
        "id": "emberfield-wake",
        "label": "Morning",
        "event": "wake",
        "wave": "sine",
        "freq": 420,
        "freq_to": 700,
        "duration": 0.70,
        "attack": 0.12,
        "gain": 0.20,
        "detune": 700,
    },
    {
        "id": "emberfield-step",
        "label": "Footstep",
        "event": "step",
        "wave": "noise",
        "duration": 0.07,
        "attack": 0.002,
        "gain": 0.10,
        "filter": 700,
        "filter_to": 200,
    },
    {
        "id": "emberfield-roll",
        "label": "Dodge roll",
        "event": "roll",
        "wave": "noise",
        "duration": 0.26,
        "attack": 0.01,
        "gain": 0.16,
        "filter": 2200,
        "filter_to": 300,
    },
    {
        "id": "emberfield-select",
        "label": "Hotbar",
        "event": "select",
        "wave": "square",
        "freq": 880,
        "duration": 0.045,
        "gain": 0.10,
        "filter": 2400,
    },
    {
        "id": "emberfield-refuse",
        "label": "That will not work",
        "event": "refuse",
        "wave": "square",
        "freq": 200,
        "freq_to": 150,
        "duration": 0.11,
        "gain": 0.16,
        "filter": 900,
    },
    {
        "id": "emberfield-buy",
        "label": "Coins",
        "event": "buy",
        "wave": "triangle",
        "freq": 1100,
        "duration": 0.06,
        "gain": 0.16,
        "repeat": 3,
        "repeat_gap": 0.055,
        "detune": 1200,
    },
    {
        "id": "emberfield-portal",
        "label": "Into the wilds",
        "event": "portal",
        "wave": "sine",
        "freq": 140,
        "freq_to": 520,
        "duration": 0.80,
        "attack": 0.06,
        "gain": 0.26,
        "detune": -1200,
        "filter": 2000,
    },
    {
        "id": "emberfield-chest",
        "label": "A chest opens",
        "event": "chest",
        "wave": "triangle",
        "freq": 380,
        "freq_to": 900,
        "duration": 0.55,
        "attack": 0.02,
        "gain": 0.30,
        "detune": 700,
        "filter": 3000,
    },
    {
        "id": "emberfield-sell",
        "label": "Sold",
        "event": "sell",
        "wave": "triangle",
        "freq": 700,
        "freq_to": 1050,
        "duration": 0.11,
        "gain": 0.18,
        "detune": 500,
    },
    # Ambience. Two beds that fade in and out with the clock rather than
    # starting and stopping, so dusk arrives instead of switching.
    {
        "id": "emberfield-night-air",
        "label": "Night air",
        "event": "ambience_night",
        "wave": "noise",
        "duration": 2.0,
        "attack": 1.2,
        "gain": 0.045,
        "filter": 380,
        "loop": True,
    },
    {
        "id": "emberfield-wilds-air",
        "label": "The wilds",
        "event": "ambience_wilds",
        "wave": "noise",
        "duration": 2.0,
        "attack": 1.2,
        "gain": 0.075,
        "filter": 240,
        "loop": True,
    },
]

# --- people --------------------------------------------------------------
# The valley's residents. `home` names a building the world generator places
# (world.regions["buildings"]); `schedule` is [[hour, place], ...] walked on a
# real path; `lines` are canned for now and become model-driven in session 8
# without the field changing. The shopkeeper carries shop:true so talking to
# them opens the stall.
#
# Buildings the layout guarantees: emberfield-house-player, -town-1..5,
# -village-1..2, -farmstead-north, -farmstead-east.

NPCS = [
    {
        "id": "emberfield-npc-brannoc",
        "label": "Brannoc",
        "sprite": "villager_c",
        "home": "emberfield-house-town-1",
        "shop": True,
        "schedule": [
            [7, "emberfield-house-town-1"],
            [9, "stall"],
            [18, "well"],
            [20, "emberfield-house-town-1"],
        ],
        "lines": [
            "Seeds in, coin out. Set a buy price on a thing and it lands on my shelf.",
            "Everything here came off a farm or out of the cave. Same as you.",
            "Sell me what the wilds cough up. I don't ask where it's been.",
        ],
    },
    {
        "id": "emberfield-npc-maren",
        "label": "Maren",
        "sprite": "villager_a",
        "home": "emberfield-house-town-2",
        "schedule": [
            [7, "emberfield-house-town-2"],
            [10, "town_centre"],
            [14, "well"],
            [19, "emberfield-house-town-2"],
        ],
        "lines": [
            "The town well's the old meeting spot. Habit outlives the reason.",
            "You're the one who took the south plot. Brave, this close to the cliffs.",
            "Rain's coming. My knee says so and my knee is never wrong.",
        ],
    },
    {
        "id": "emberfield-npc-odd",
        "label": "Odd",
        "sprite": "villager_b",
        "home": "emberfield-house-town-3",
        "schedule": [
            [8, "emberfield-house-town-3"],
            [11, "stall"],
            [15, "town_centre"],
            [20, "emberfield-house-town-3"],
        ],
        "lines": [
            "Went down the cave once. Once was the right number of times.",
            "Brannoc overcharges for barley seed. You didn't hear it from me.",
            "Quiet valley. We'd like to keep it that way.",
        ],
    },
    {
        "id": "emberfield-npc-sena",
        "label": "Sena",
        "sprite": "villager_a",
        "home": "emberfield-house-village-1",
        "schedule": [
            [7, "emberfield-house-village-1"],
            [9, "village_centre"],
            [13, "town_centre"],
            [18, "emberfield-house-village-1"],
        ],
        "lines": [
            "The village is smaller than the town and prouder of it.",
            "Walk the north road in daylight. Only in daylight.",
            "You can grow emberbloom down your end. It won't take up here — too cold.",
        ],
    },
    {
        "id": "emberfield-npc-fell",
        "label": "Fell",
        "sprite": "villager_c",
        "home": "emberfield-house-village-2",
        "schedule": [
            [8, "emberfield-house-village-2"],
            [10, "village_centre"],
            [16, "well"],
            [19, "emberfield-house-village-2"],
        ],
        "lines": [
            "Every house here has a hearth going by dusk. You'll want yours lit too.",
            "The wilds change every night. The village hasn't changed in forty years.",
            "Knock before dark. Nobody opens a door after dark.",
        ],
    },
    {
        "id": "emberfield-npc-tamsin",
        "label": "Tamsin",
        "sprite": "villager_b",
        "home": "emberfield-house-farmstead-north",
        "schedule": [
            [6, "emberfield-house-farmstead-north"],
            [8, "farmstead-north_centre"],
            [17, "emberfield-house-farmstead-north"],
        ],
        "lines": [
            "Just me and the north field. Suits me fine.",
            "You farm the south, I farm the north. We'll not be short of turnips.",
            "Foxes in the barley. If you see one, it isn't a fox.",
        ],
    },
    {
        "id": "emberfield-npc-corin",
        "label": "Corin",
        "sprite": "villager_a",
        "home": "emberfield-house-farmstead-east",
        "schedule": [
            [6, "emberfield-house-farmstead-east"],
            [9, "farmstead-east_centre"],
            [12, "town_centre"],
            [18, "emberfield-house-farmstead-east"],
        ],
        "lines": [
            "East farmstead. Closest to the cave, for my sins.",
            "I hear it at night. Best you're indoors by then.",
            "Trade you barley for turnip seed, if you're ever passing.",
        ],
    },
]


# --- recipes -------------------------------------------------------------
# Made at the workbench or the hearth in the player's house. inputs is
# {item: qty}; output is one item id. A recipe appears only at its station.
# The whole point: turn what the wilds and the farm give you into something
# worth more, so materials stop having exactly one use.

RECIPES = [
    {
        "id": "emberfield-glue",
        "label": "Boil slime into glue",
        "station": "workbench",
        "inputs": {"emberfield-slime-gel": 3},
        "output": "emberfield-glue",
        "output_qty": 1,
    },
    {
        "id": "emberfield-charcoal",
        "label": "Char ash to charcoal",
        "station": "workbench",
        "inputs": {"emberfield-ash": 2},
        "output": "emberfield-charcoal",
        "output_qty": 1,
    },
    {
        "id": "emberfield-ember-glass",
        "label": "Fuse ember glass",
        "station": "workbench",
        "inputs": {"emberfield-ember-shard": 1, "emberfield-ash": 3},
        "output": "emberfield-ember-glass",
        "output_qty": 1,
    },
    {
        "id": "emberfield-field-ration",
        "label": "Pack a field ration",
        "station": "cook",
        "inputs": {"emberfield-turnip": 3},
        "output": "emberfield-field-ration",
        "output_qty": 1,
    },
    {
        "id": "emberfield-hearty-stew",
        "label": "Cook a hearty stew",
        "station": "cook",
        "inputs": {"emberfield-turnip": 2, "emberfield-barley": 1},
        "output": "emberfield-hearty-stew",
        "output_qty": 1,
    },
    # --- tool upgrades ---------------------------------------------------
    # These do not yield an item -- they raise a tool's tier, which the till
    # and water verbs read to work a 3x3 instead of a single tile. `output`
    # points at the tool's own id to satisfy the schema.
    {
        "id": "emberfield-reinforce-hoe",
        "label": "Reinforce the hoe (tills 3×3)",
        "station": "workbench",
        "inputs": {"emberfield-charcoal": 2, "emberfield-glue": 1},
        "output": "emberfield-hoe",
        "upgrades": "emberfield-hoe",
        "tier": 1,
    },
    {
        "id": "emberfield-widen-can",
        "label": "Widen the watering can (waters 3×3)",
        "station": "workbench",
        "inputs": {"emberfield-ember-glass": 1, "emberfield-glue": 1},
        "output": "emberfield-watering-can",
        "upgrades": "emberfield-watering-can",
        "tier": 1,
    },
]


CONTENT = {
    "items": items,
    "sounds": lambda: SOUNDS,
    "tools": lambda: TOOLS,
    "crops": lambda: CROPS,
    "loot": lambda: LOOT,
    "weapons": lambda: WEAPONS,
    "foes": lambda: FOES,
    "npcs": lambda: NPCS,
    "recipes": lambda: RECIPES,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite entries that already exist, losing any edits",
    )
    parser.add_argument(
        "--list", action="store_true", help="show what the store holds and exit"
    )
    args = parser.parse_args()

    root = forge_content.ensure_root()

    if args.list:
        store = forge_content.store()
        print(f"content store: {root}")
        for type_name, entries in store["types"].items():
            print(f"  {type_name:9s} {len(entries)}")
            for entry_id, entry in entries.items():
                print(f"    {entry_id:32s} {entry.get('label', '')}")
        for problem in store["problems"]:
            print(f"  problem: {problem}")
        return 0

    written, kept = 0, 0
    for type_name, builder in CONTENT.items():
        for entry in builder():
            path = forge_content.entry_path(type_name, entry["id"])
            if os.path.exists(path) and not args.force:
                kept += 1
                continue
            forge_content.save(type_name, entry)
            written += 1

    print(f"content store: {root}")
    print(f"  wrote {written} entries, left {kept} existing ones alone")
    if kept and not args.force:
        print("  (pass --force to overwrite those, losing your edits)")
    problems = forge_content.store()["problems"]
    for problem in problems:
        print(f"  problem: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
