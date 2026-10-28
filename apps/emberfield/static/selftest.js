/* An in-page check of the parts of Emberfield that live in the browser.

   The Python suite covers world generation, collision shapes and the content
   store. Farming, growth, combat and saving are all frontend code, and a
   screenshot proves only that something was drawn -- it cannot show that a
   watered turnip ripens on schedule or that an unwatered one does not. So this
   file drives the real game functions, in a real page, against the real content
   store, and reports what happened.

   Loaded only for ?selftest=1, so it costs a normal boot nothing. Run it with:

     ...:8434/?seed=777&selftest=1

   and read the results in the page, or from --dump-dom in headless Chrome.
*/
"use strict";

(function () {
  const results = [];
  let failures = 0;

  function check(name, fn) {
    try {
      const problem = fn();
      if (problem) { failures++; results.push(`FAIL ${name}: ${problem}`); }
      else results.push(`ok   ${name}`);
    } catch (e) {
      failures++;
      results.push(`FAIL ${name}: threw ${e && e.message}`);
    }
  }

  function eq(actual, expected, what) {
    if (actual !== expected) return `${what}: expected ${expected}, got ${actual}`;
    return null;
  }

  /* Every async check is raced against a timeout. A hung promise would
     otherwise leave the whole suite pending with nothing reported, which reads
     exactly like a suite that was never run. */
  function withTimeout(promise, ms, what) {
    return Promise.race([
      promise,
      new Promise((resolve) => setTimeout(() => resolve(`timed out after ${ms}ms (${what})`), ms)),
    ]);
  }

  async function checkAsync(name, fn) {
    try {
      const problem = await withTimeout(fn(), 8000, name);
      if (problem) { failures++; results.push(`FAIL ${name}: ${problem}`); }
      else results.push(`ok   ${name}`);
    } catch (e) {
      failures++;
      results.push(`FAIL ${name}: threw ${e && e.message}`);
    }
  }

  window.runSelfTest = async function () {
    const G = window.EmberTest;   // the game's own functions, not copies
    const plot = G.S.world.regions.farm.plot;
    const x = plot.x, y = plot.y;

    /* --- the day/night cycle ------------------------------------------- */
    check("a day is the length the setting says", () => {
      G.S.settings.day_seconds = 900;
      const perSecond = G.minutesPerSecond();
      const realSeconds = 1440 / perSecond;
      // The session 1 bug made this 12 seconds. It must be 900.
      return Math.abs(realSeconds - 900) < 0.001
        ? null : `a day takes ${realSeconds.toFixed(1)}s of real time, not 900`;
    });
    check("a shorter day setting is honoured", () => {
      G.S.settings.day_seconds = 60;
      const realSeconds = 1440 / G.minutesPerSecond();
      G.S.settings.day_seconds = 900;
      return Math.abs(realSeconds - 60) < 0.001 ? null : `got ${realSeconds}s`;
    });

    /* --- collision ------------------------------------------------------ */
    check("you can stand where a tree's canopy is", () => {
      const oak = G.S.world.objects.find((o) => o.sprite === "tree_oak");
      if (!oak) return "no oak in this valley";
      // One tile above the trunk is canopy. Session 1 blocked it.
      const canopyY = (oak.y - 1) * TILE + 8;
      const canopyX = (oak.x + 1) * TILE;
      if (!G.canStand(canopyX, canopyY)) return "the canopy still blocks you";
      // And the trunk itself must still stop you, or the fix went too far.
      if (G.canStand((oak.x + 1) * TILE, (oak.y + 1) * TILE - 3)) {
        return "the trunk no longer blocks you either";
      }
      return null;
    });

    /* --- farming -------------------------------------------------------- */
    G.S.crops = {};
    G.S.tileEdits = {};
    G.S.clock.season = "spring";
    G.startingKit();
    G.rebuildHotbar();

    const seedId = Object.keys(G.S.inv).find((id) => {
      const item = G.lookup("items", id);
      return item && item.kind === "seed";
    });
    const cropDef = G.all("crops").find((c) => c.seed_item === seedId);

    check("the starting seeds suit the starting season", () =>
      cropDef && cropDef.seasons.includes("spring")
        ? null : `${cropDef ? cropDef.id : "no crop"} cannot be sown in spring`);

    check("the hoe tills bare ground", () => {
      G.setTile(x, y, "grass_b");
      const problem = G.VERBS.till(x, y);
      if (problem) return problem;
      return eq(G.S.world.tiles[y][x], "tilled", "tile after tilling");
    });

    check("you cannot till what is not ground", () => {
      G.setTile(x + 1, y, "water");
      const problem = G.VERBS.till(x + 1, y);
      G.setTile(x + 1, y, "grass_b");
      return problem ? null : "tilling water was allowed";
    });

    check("planting costs a seed and puts a crop in the ground", () => {
      const before = G.S.inv[seedId];
      const problem = G.plant(seedId, x, y);
      if (problem) return problem;
      if (!G.S.crops[x + "," + y]) return "nothing was planted";
      return eq(G.S.inv[seedId], before - 1, "seeds left");
    });

    check("you cannot plant on untilled ground", () => {
      G.setTile(x + 2, y, "grass_b");
      return G.plant(seedId, x + 2, y) ? null : "planting on grass was allowed";
    });

    check("the watering can wets the soil and the crop", () => {
      const problem = G.VERBS.water(x, y);
      if (problem) return problem;
      if (G.S.world.tiles[y][x] !== "tilled_wet") return "the soil did not change";
      return G.S.crops[x + "," + y].watered ? null : "the crop is still dry";
    });

    /* --- growth --------------------------------------------------------- */
    check("a watered crop ripens on the schedule its file gives it", () => {
      const at = G.S.crops[x + "," + y];
      const wanted = cropDef.stages.slice(0, -1).reduce((a, b) => a + b, 0);
      for (let day = 0; day < wanted; day++) {
        at.watered = true;
        G.growOvernight();
      }
      return eq(at.stage, cropDef.stages.length - 1,
        `stage after ${wanted} watered nights`);
    });

    check("an unwatered crop does not grow", () => {
      G.S.crops["1,1"] = { id: cropDef.id, stage: 0, days: 0, watered: false };
      G.growOvernight();
      const problem = eq(G.S.crops["1,1"].stage, 0, "stage after a dry night");
      delete G.S.crops["1,1"];
      return problem;
    });

    check("a crop out of its season does not grow", () => {
      const wrong = G.all("crops").find((c) => !c.seasons.includes("spring"));
      if (!wrong) return null;   // nothing to test in this content set
      G.S.crops["2,2"] = { id: wrong.id, stage: 0, days: 0, watered: true };
      G.growOvernight();
      const problem = eq(G.S.crops["2,2"].stage, 0, "stage out of season");
      delete G.S.crops["2,2"];
      return problem;
    });

    /* --- harvest -------------------------------------------------------- */
    check("harvesting a ripe crop yields its produce", () => {
      const before = G.S.inv[cropDef.yield_item] || 0;
      const problem = G.harvest(x, y);
      if (problem) return problem;
      return eq(G.S.inv[cropDef.yield_item] || 0, before + cropDef.yield_qty,
        "produce in the pack");
    });

    check("harvesting an empty tile is refused, not silently allowed", () =>
      G.harvest(x + 5, y + 5) ? null : "harvesting nothing succeeded");

    check("a regrowing crop goes back a stage instead of dying", () => {
      const regrows = G.all("crops").find((c) => c.regrow > 0);
      if (!regrows) return null;
      const k = (x + 3) + "," + y;
      G.S.crops[k] = { id: regrows.id, stage: regrows.stages.length - 1, days: 0 };
      G.harvest(x + 3, y);
      if (!G.S.crops[k]) return "the crop was removed instead of regrowing";
      return G.S.crops[k].stage < regrows.stages.length - 1
        ? null : "the crop stayed ripe";
    });

    /* --- combat --------------------------------------------------------- */
    check("clicking fires a shot toward the cursor, not the facing", () => {
      const bow = G.all("weapons")[0];
      if (!bow) return "no weapon in the content store";
      G.S.inv[bow.id] = 1;
      G.rebuildHotbar();
      G.S.slot = G.S.hotbar.findIndex((h) => h.id === bow.id);
      G.S.shots = [];
      G.S.fireT = 0;
      G.S.view = { camX: 0, camY: 0, viewW: 320, viewH: 200, z: 3 };
      G.S.dpr = 1;
      // Cursor well to the left of the player: the shot must travel left even
      // though the player is facing down.
      G.S.player.x = 200; G.S.player.y = 200; G.S.player.dir = "down";
      G.S.mouse.x = 10; G.S.mouse.y = 200;
      G.fire(0);
      if (!G.S.shots.length) return "no shot was created";
      return G.S.shots[0].vx < 0 ? null : `shot went right (vx ${G.S.shots[0].vx})`;
    });

    check("a foe that reaches you costs a heart", () => {
      G.S.player.hp = 6; G.S.player.hurtT = 0;
      G.hurtPlayer(1);
      return eq(G.S.player.hp, 5, "hearts after a hit");
    });

    check("the brief invulnerability stops a slime killing you instantly", () =>
      G.S.player.hurtT > 0 ? null : "no invulnerability window after a hit");

    /* --- eating ---------------------------------------------------------- */
    const TURNIP = "emberfield-turnip", STEW = "emberfield-hearty-stew";
    const keptInv = Object.assign({}, G.S.inv), keptHp = G.S.player.hp;

    check("a material is not food, a turnip and a stew are", () => {
      if (G.foodHeals(G.lookup("items", "emberfield-slime-gel")) !== 0) return "slime gel heals";
      if (!(G.foodHeals(G.lookup("items", TURNIP)) >= 1)) return "a turnip heals nothing";
      return G.foodHeals(G.lookup("items", STEW)) > G.foodHeals(G.lookup("items", TURNIP))
        ? null : "the stew heals no more than a turnip";
    });

    check("eating heals and costs exactly one food", () => {
      G.S.inv = { [TURNIP]: 2 };
      G.S.player.maxHp = 6; G.S.player.hp = 3;
      if (!G.eat()) return "eat() refused with food and missing hearts";
      const want = Math.min(6, 3 + G.foodHeals(G.lookup("items", TURNIP)));
      return eq(G.S.player.hp, want, "hearts after eating") ||
        eq(G.S.inv[TURNIP], 1, "turnips left");
    });

    check("a scratch costs the smallest meal that fills it", () => {
      G.S.inv = { [TURNIP]: 1, [STEW]: 1 };
      G.S.player.hp = 5;
      const small = G.bestFood();
      G.S.player.hp = 6 - G.foodHeals(G.lookup("items", STEW));
      const big = G.bestFood();
      return eq(small && small.id, TURNIP, "food for one missing heart") ||
        eq(big && big.id, STEW, "food for a deep wound");
    });

    check("eating at full health is refused and costs nothing", () => {
      G.S.inv = { [STEW]: 1 }; G.S.player.hp = 6;
      if (G.eat()) return "ate at full health";
      return eq(G.S.inv[STEW], 1, "stews left");
    });

    check("with nothing to eat, nothing happens", () => {
      G.S.inv = {}; G.S.player.hp = 2;
      if (G.eat()) return "ate from an empty bag";
      return eq(G.S.player.hp, 2, "hearts");
    });
    G.S.inv = keptInv; G.S.player.hp = keptHp; G.rebuildHotbar();

    /* --- the day turning over ------------------------------------------ */
    check("the season turns on day 29 however the day ended", () => {
      const kept = Object.assign({}, G.S.clock);
      G.S.clock.day = 28; G.S.clock.season = "spring";
      const changed = G.turnDay();
      const out = eq(changed, true, "turnDay reported a season change") ||
        eq(G.S.clock.day, 29, "day") || eq(G.S.clock.season, "summer", "season");
      G.S.clock = kept; G.S.ground.clear(); applyPalette();
      return out;
    });

    check("a new day dries watered soil", () => {
      const kept = Object.assign({}, G.S.clock);
      G.setTile(x + 1, y + 1, "tilled_wet");
      G.turnDay();
      const out = eq(G.S.world.tiles[y + 1][x + 1], "tilled", "tile after a day");
      G.S.clock = kept;
      return out;
    });

    check("a new valley starts on the first morning", () => {
      const c = G.freshClock();
      return eq(c.day, 1, "day") || eq(c.minutes, 360, "minutes");
    });

    check("your farm stays safe after dark", () => {
      const farm = G.S.world.regions.farm;
      return G.inSafeRegion(farm.x + 2, farm.y + 2)
        ? null : "the farm is not treated as safe ground";
    });

    check("foes spawn near you rather than across the whole valley", () => {
      G.S.foes = [];
      G.S.clock.minutes = 22 * 60;
      // Somewhere open and outside the farm.
      const town = G.S.world.regions.town;
      G.S.player.x = (town.x - 8) * TILE; G.S.player.y = (town.y + 4) * TILE;
      if (G.inSafeRegion(town.x - 8, town.y + 4)) return null;  // unlucky map
      G.topUpFoes();
      if (!G.S.foes.length) return "nothing spawned at night";
      const far = G.S.foes.filter(
        (f) => Math.hypot(f.x - G.S.player.x, f.y - G.S.player.y) > 260);
      return far.length ? `${far.length} foe(s) spawned out of reach` : null;
    });

    /* --- the shop ------------------------------------------------------- */
    check("the stall stocks exactly what carries a buy price", () => {
      const stocked = G.stock().map((i) => i.id).sort();
      const priced = G.all("items").filter((i) => i.buy > 0).map((i) => i.id).sort();
      if (JSON.stringify(stocked) !== JSON.stringify(priced)) {
        return "stock does not match the items with a buy price";
      }
      return stocked.length ? null : "nothing is for sale at all";
    });

    check("buying costs gold and hands over the goods", () => {
      const item = G.stock()[0];
      G.S.gold = item.buy + 5;
      const had = G.S.inv[item.id] || 0;
      G.buyItem(item.id);
      if ((G.S.inv[item.id] || 0) !== had + 1) return "you did not get the item";
      return eq(G.S.gold, 5, "gold left");
    });

    check("you cannot buy what you cannot afford", () => {
      const item = G.stock()[0];
      G.S.gold = item.buy - 1;
      const had = G.S.inv[item.id] || 0;
      G.buyItem(item.id);
      if ((G.S.inv[item.id] || 0) !== had) return "you got it without paying";
      return eq(G.S.gold, item.buy - 1, "gold after a refused purchase");
    });

    check("selling pays out and takes the item", () => {
      const item = G.all("items").find((i) => i.sell > 0);
      G.S.inv[item.id] = 2;
      G.S.gold = 0;
      G.rebuildHotbar();
      G.sellItem(item.id);
      if ((G.S.inv[item.id] || 0) !== 1) return "the item was not taken";
      return eq(G.S.gold, item.sell, "gold after selling");
    });

    check("produce is worth more than the seed it came from", () => {
      /* The whole point of the loop. If a crop sells for less than its seed
         costs, farming is a way to lose money and nobody would notice until
         they had played a week. */
      const broken = [];
      for (const crop of G.all("crops")) {
        const seed = G.lookup("items", crop.seed_item);
        const produce = G.lookup("items", crop.yield_item);
        if (!seed || !produce) continue;
        if (produce.sell * crop.yield_qty <= seed.buy) {
          broken.push(`${crop.id} (seed ${seed.buy}g, yields ${produce.sell * crop.yield_qty}g)`);
        }
      }
      return broken.length ? `not worth growing: ${broken.join("; ")}` : null;
    });

    /* --- loot ----------------------------------------------------------- */
    check("a loot table can always be drawn", () =>
      G.rollLoot() ? null : "no loot table matched the current day");

    check("a chest pays out once and only once", () => {
      const chest = { use: "chest", x: 1, y: 1 };
      const before = G.S.gold;
      G.openChest(chest);
      if (!chest.opened) return "the chest did not open";
      if (G.S.gold <= before) return "it paid nothing";
      const after = G.S.gold;
      G.openChest(chest);
      return eq(G.S.gold, after, "gold after opening it a second time");
    });

    check("every loot table names items that exist", () => {
      const missing = [];
      for (const table of G.all("loot")) {
        for (const id of table.items) {
          if (!G.lookup("items", id)) missing.push(`${table.id} -> ${id}`);
        }
        if (table.gold_max < table.gold_min) missing.push(`${table.id} gold range inverted`);
      }
      return missing.length ? missing.join(", ") : null;
    });

    /* --- shadows and knockback ------------------------------------------ */
    check("shadows fall west in the morning and east in the evening", () => {
      /* A shadow falls away from the sun. The first version negated the
         direction and had every shadow pointing at it, so mornings and evenings
         were exactly reversed -- which looks fine in a single screenshot and
         wrong the moment you watch a day pass. */
      G.S.clock.minutes = 7 * 60;
      const morning = G.sunLight();
      G.S.clock.minutes = 18 * 60;
      const evening = G.sunLight();
      if (morning.dir >= 0) return "the morning sun is not in the east";
      if (evening.dir <= 0) return "the evening sun is not in the west";
      G.S.clock.minutes = 12 * 60;
      const noon = G.sunLight();
      if (!(noon.stretch < morning.stretch && noon.stretch < evening.stretch)) {
        return "shadows are not shortest at midday";
      }
      return null;
    });

    check("a hit shoves a foe away from the shot", () => {
      /* Two things this test has to set up, both of which look like the foe
         dying if you get them wrong: foes further than 700px from the player
         are culled every frame, and in the valley by daylight every foe is
         cleared outright, because daylight is when the valley is safe. */
      G.S.clock.minutes = 22 * 60;
      G.S.player.x = 300; G.S.player.y = 340;
      G.S.foes = [{
        id: "test", sprite: "foe_slime", x: 300, y: 300, hp: 5,
        speed: 0, damage: 1, touch: 6, drops: [], hurtT: 0,
      }];
      G.S.shots = [{
        x: 296, y: 300, vx: 100, vy: 0, angle: 0, damage: 1,
        sprite: "arrow", life: 1,
      }];
      G.stepCombat(0.016, 0);
      const foe = G.S.foes[0];
      if (!foe) return "the foe died instead of being knocked back";
      return foe.kx > 0 ? null : `knockback was ${foe.kx}, expected a push east`;
    });

    /* --- the wilds ------------------------------------------------------ */
    await checkAsync("going down swaps the map but keeps what you carry", async () => {
      const valleySeed = G.S.world.seed;
      const carried = JSON.stringify(G.S.inv);
      const cropsBefore = Object.keys(G.S.crops).length;
      await G.enterWilds();
      if (!G.S.inWilds) return "still in the valley";
      if (G.S.world.seed === valleySeed) return "the cavern has the valley's seed";
      if (JSON.stringify(G.S.inv) !== carried) return "your pack changed on the way down";
      if (Object.keys(G.S.crops).length !== cropsBefore) return "your crops changed";
      if (!G.S.world.regions.entrance) return "the cavern has no way out";
      return null;
    });

    check("a save made underground still describes the valley", () => {
      if (!G.S.inWilds) return "not in the wilds, so this proves nothing";
      const payload = G.savePayload();
      return payload.world.seed === G.S.valley.world.seed
        ? null : "the save recorded the cavern's seed, not the valley's";
    });

    check("there is no safe ground underground except the way out", () => {
      const way = G.S.world.regions.entrance;
      if (!G.inSafeRegion(way[0], way[1])) return "even the exit is not safe";
      // Somewhere well away from it must not be.
      const deep = G.S.world.regions.deep;
      if (Math.hypot(deep[0] - way[0], deep[1] - way[1]) < 8) return null;
      return G.inSafeRegion(deep[0], deep[1])
        ? "the deep end counts as safe ground" : null;
    });

    check("the cavern asks for more foes than the valley does", () => {
      const danger = G.S.world.regions.danger;
      return danger && danger > 4 ? null : `cavern danger is ${danger}`;
    });

    check("coming back up restores the valley you left", () => {
      const cavernSeed = G.S.world.seed;
      G.leaveWilds();
      if (G.S.inWilds) return "still underground";
      if (G.S.world.seed === cavernSeed) return "the valley was not restored";
      if (!G.S.world.regions.farm) return "the restored map has no farm";
      return null;
    });

    /* --- houses and interiors (session 5) ----------------------------- */
    check("the valley has houses with doors and interior ids", () => {
      const b = G.S.world.regions.buildings || [];
      if (b.length < 5) return `only ${b.length} buildings`;
      const player = b.find((h) => h.id === "emberfield-house-player");
      if (!player || !player.door) return "no player house with a door";
      return b.every((h) => h.door && h.id) ? null : "a building is missing a door or id";
    });

    await checkAsync("walking through a door swaps to a room and keeps your pack", async () => {
      const carried = JSON.stringify(G.S.inv);
      const cropsBefore = Object.keys(G.S.crops).length;
      const house = G.S.world.objects.find((o) => o.use === "door");
      await G.enterBuilding(house);
      if (!G.S.inInterior) return "still outside";
      if (!G.S.world.is_interior) return "the swapped map is not an interior";
      if (JSON.stringify(G.S.inv) !== carried) return "your pack changed on the way in";
      if (Object.keys(G.S.crops).length !== cropsBefore) return "your crops changed";
      if (G.S.world.regions.exit == null) return "the room has no way out";
      return null;
    });

    check("a save made indoors still describes the valley", () => {
      if (!G.S.inInterior) return "not indoors, so this proves nothing";
      const payload = G.savePayload();
      return payload.world.seed === G.S.parked.world.seed
        ? null : "the save recorded the room, not the valley";
    });

    check("stepping back out puts you outside the door", () => {
      const door = G.S.parked && G.S.parked.door.slice();
      G.leaveBuilding();
      if (G.S.inInterior) return "still indoors";
      if (!G.S.world.regions.farm) return "the valley was not restored";
      const px = Math.floor(G.S.player.x / TILE), py = Math.floor(G.S.player.y / TILE);
      if (door && Math.hypot(px - door[0], py - door[1]) > 3) return "you came out far from the door";
      return null;
    });

    /* --- the people (session 5) -------------------------------------- */
    check("the valley is populated and everyone has a home", () => {
      if (!G.S.npcs.length) return "nobody lives here";
      const homeless = G.S.npcs.filter((n) => !n.home);
      return homeless.length ? `${homeless.length} npc(s) with no home` : null;
    });

    check("every npc can walk a path from home to every scheduled stop", () => {
      const fails = [];
      for (const npc of G.S.npcs) {
        for (const entry of (npc.def.schedule || [])) {
          const goal = G.resolvePlace(entry[1], npc);
          if (!G.bfsPath(npc.home.door, goal)) {
            fails.push(`${npc.id} -> ${JSON.stringify(entry[1])}`);
          }
        }
      }
      return fails.length ? fails.join("; ") : null;
    });

    check("talking to a villager returns a line", () => {
      const villager = G.S.npcs.find((n) => !n.def.shop);
      if (!villager) return "no plain villager to talk to";
      G.S.player.x = villager.x; G.S.player.y = villager.y;
      const line = G.talkTo(villager);
      return typeof line === "string" && line.length ? null : "no line came back";
    });

    check("talking to the shopkeeper opens the stall", () => {
      const keeper = G.S.npcs.find((n) => n.def.shop);
      if (!keeper) return "no shopkeeper in the content set";
      G.S.running = true;
      G.talkTo(keeper);
      return G.S.running === false ? null : "the stall did not open";
    });

    check("nobody sleeps somewhere the night would spawn a foe", () => {
      const exposed = G.S.npcs.filter((n) => {
        const d = n.home.door;
        return !G.inSafeRegion(d[0], d[1]);
      });
      return exposed.length
        ? `${exposed.map((n) => n.id).join(", ")} live on unsafe ground` : null;
    });

    /* --- crafting and storage (session 6) --------------------------- */
    check("crafting a recipe spends its inputs and yields its output", () => {
      const recipe = G.all("recipes")[0];
      if (!recipe) return "no recipes in the content store";
      for (const [id, qty] of Object.entries(recipe.inputs)) G.S.inv[id] = qty + 1;
      G.rebuildHotbar();
      const outBefore = G.S.inv[recipe.output] || 0;
      G.craftRecipe(recipe.id);
      for (const [id, qty] of Object.entries(recipe.inputs)) {
        if ((G.S.inv[id] || 0) !== 1) return `${id} was not spent to 1`;
      }
      return (G.S.inv[recipe.output] || 0) === outBefore + (recipe.output_qty || 1)
        ? null : "the output did not arrive";
    });

    check("you cannot craft what you cannot afford", () => {
      const recipe = G.all("recipes").find((r) => Object.keys(r.inputs).length);
      for (const id of Object.keys(recipe.inputs)) delete G.S.inv[id];
      G.rebuildHotbar();
      const before = G.S.inv[recipe.output] || 0;
      G.craftRecipe(recipe.id);
      return (G.S.inv[recipe.output] || 0) === before ? null : "it crafted from nothing";
    });

    check("a recipe shows only at its own station", () => {
      const bench = G.craftable("workbench").map((r) => r.id);
      const hearth = G.craftable("cook").map((r) => r.id);
      const both = bench.filter((id) => hearth.includes(id));
      if (both.length) return `${both.join(", ")} shows at both stations`;
      return bench.length && hearth.length ? null : "a station has no recipes at all";
    });

    check("the chest takes an item out of your pack and gives it back", () => {
      G.S.inv["emberfield-ash"] = 3;
      G.S.storage = {};
      G.deposit("emberfield-ash", 2);
      if ((G.S.inv["emberfield-ash"] || 0) !== 1) return "the pack was not drawn down";
      if ((G.S.storage["emberfield-ash"] || 0) !== 2) return "the chest did not fill";
      G.withdraw("emberfield-ash", 2);
      if (G.S.storage["emberfield-ash"]) return "the chest did not empty";
      return (G.S.inv["emberfield-ash"] || 0) === 3 ? null : "the pack did not refill";
    });

    check("the chest is written into the save", () => {
      G.S.storage = { "emberfield-charcoal": 4 };
      const payload = G.savePayload();
      return payload.storage && payload.storage["emberfield-charcoal"] === 4
        ? null : "storage is missing from the save";
    });

    check("crafting a tool upgrade raises the tool's tier, not your pack", () => {
      const up = G.all("recipes").find((r) => r.upgrades);
      if (!up) return "no upgrade recipe in the content set";
      G.S.toolTier = {};
      for (const [id, qty] of Object.entries(up.inputs)) G.S.inv[id] = qty + 1;
      G.rebuildHotbar();
      const packBefore = JSON.stringify(G.S.inv);
      G.craftRecipe(up.id);
      if ((G.S.toolTier[up.upgrades] || 0) !== up.tier) return "the tier did not rise";
      // The inputs are gone but no item was added.
      const diff = Object.keys(JSON.parse(packBefore)).length - Object.keys(G.S.inv).length;
      return diff >= 0 ? null : "an item landed in your pack from an upgrade";
    });

    check("an upgraded hoe tills a 3x3", () => {
      const plot2 = G.S.world.regions.farm.plot;
      const bx = plot2.x, by = plot2.y;
      for (let yy = by; yy < by + 3; yy++)
        for (let xx = bx; xx < bx + 3; xx++) G.setTile(xx, yy, "grass_b");
      G.S.crops = {};
      G.S.toolTier["emberfield-hoe"] = 1;
      const problem = G.applyToolArea(G.VERBS.till, bx + 1, by + 1, G.toolRadius("emberfield-hoe"));
      if (problem) return problem;
      let tilled = 0;
      for (let yy = by; yy < by + 3; yy++)
        for (let xx = bx; xx < bx + 3; xx++)
          if (G.S.world.tiles[yy][xx] === "tilled") tilled++;
      return tilled === 9 ? null : `only ${tilled}/9 tiles were tilled`;
    });

    check("a finished upgrade drops off the workbench list", () => {
      G.S.toolTier["emberfield-hoe"] = 1;
      const stillOffered = G.craftable("workbench").some(
        (r) => r.upgrades === "emberfield-hoe" && r.tier === 1);
      return stillOffered ? "the done upgrade is still listed" : null;
    });

    check("a dodge roll moves you and grants a mercy window", () => {
      const p = G.S.player;
      p.rollT = 0; p.rollCool = 0; p.hurtT = 0;
      const before = { x: p.x, y: p.y };
      if (!G.startRoll(1, 0)) return "the roll refused to start";
      if (!(p.hurtT > 0)) return "rolling gave no invulnerability";
      for (let i = 0; i < 8; i++) G.step(0.03, 0);
      const moved = Math.hypot(p.x - before.x, p.y - before.y);
      if (moved < 8) return `the roll barely moved you (${moved.toFixed(1)}px)`;
      return null;
    });

    check("you cannot chain rolls -- the cooldown holds", () => {
      const p = G.S.player;
      p.rollT = 0; p.rollCool = 0; p.hurtT = 0;
      G.startRoll(0, 1);
      p.rollT = 0;                       // the roll itself is over...
      if (G.startRoll(0, 1)) return "a second roll started during the cooldown";
      p.rollCool = 0;
      if (!G.startRoll(0, 1)) return "the roll never came back";
      p.rollT = 0; p.rollCool = 0;
      return null;
    });

    check("a roll cannot carry you through a wall", () => {
      const p = G.S.player;
      p.rollT = 0; p.rollCool = 0;
      /* Roll hard into every direction from where we stand; wherever we end
         up must still be somewhere the player is allowed to be. */
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        G.startRoll(dx, dy);
        for (let i = 0; i < 12; i++) G.step(0.03, 0);
        if (!G.canStand(p.x, p.y)) return `rolling ${dx},${dy} ended inside something solid`;
        p.rollT = 0; p.rollCool = 0;
      }
      return null;
    });

    check("the tool tier is written into the save", () => {
      G.S.toolTier = { "emberfield-watering-can": 1 };
      const payload = G.savePayload();
      return payload.toolTier
        && payload.toolTier["emberfield-watering-can"] === 1
        ? null : "toolTier is missing from the save";
    });

    await checkAsync("the player's house has a workbench, a hearth and a chest inside", async () => {
      if (G.S.inInterior || G.S.inWilds) return "not standing in the valley";
      const door = G.S.world.objects.find(
        (o) => o.use === "door" && o.building === "emberfield-house-player");
      if (!door) return "no player house";
      await G.enterBuilding(door);
      if (!G.S.inInterior) return "did not get inside";
      const uses = new Set(G.S.world.objects.map((o) => o.use).filter(Boolean));
      const missing = ["craft", "cook", "storage"].filter((u) => !uses.has(u));
      G.leaveBuilding();
      return missing.length ? `missing ${missing.join(", ")} indoors` : null;
    });

    /* --- sleeping in your house (the only way to sleep since session 5) --- */
    await checkAsync("a save made indoors is written to the valley's slot", async () => {
      const door = G.S.world.objects.find(
        (o) => o.use === "door" && o.building === "emberfield-house-player");
      if (!door) return "no player house";
      const valleySlot = G.saveSlot();
      await G.enterBuilding(door);
      if (!G.S.inInterior) return "did not get inside";
      const indoorSlot = G.saveSlot();
      G.leaveBuilding();
      return indoorSlot === valleySlot
        ? null : `indoors the save slot became ${indoorSlot}, not ${valleySlot}`;
    });

    await checkAsync("sleeping in your house ends the day and the game keeps running", async () => {
      const door = G.S.world.objects.find(
        (o) => o.use === "door" && o.building === "emberfield-house-player");
      if (!door) return "no player house";
      // Worked ground with water on it -- this is what dryTheField walks, and
      // its keys are valley coordinates.
      const plotA = G.S.world.regions.farm.plot;
      G.setTile(plotA.x, plotA.y, "tilled_wet");
      await G.enterBuilding(door);
      if (!G.S.inInterior) return "did not get inside";
      const dayBefore = G.S.clock.day;
      G.S.running = true;
      G.sleep();
      await new Promise((r) => setTimeout(r, 1400));
      const problems = [];
      if (!G.S.running) problems.push("the game did not resume after the fade");
      if (G.S.clock.day !== dayBefore + 1) problems.push("the day did not advance");
      if (G.S.tileEdits[plotA.x + "," + plotA.y] !== "tilled") {
        problems.push("the field did not dry");
      }
      if (G.S.inInterior) G.leaveBuilding();
      return problems.length ? problems.join("; ") : null;
    });

    /* --- sound ---------------------------------------------------------- */
    /* A headless browser will not play audio, so these render each sound into
       an OfflineAudioContext and measure the waveform. That distinction matters:
       a wrong envelope, or a low-pass cutoff below the fundamental, produces a
       perfectly valid graph that throws nothing and is completely silent. Only
       measuring the samples catches it. */

    check("every game event the code plays has a sound file", () => {
      const wired = Sound.events();
      const wanted = [
        "till", "water", "plant", "harvest", "shoot", "hit", "foe_dies",
        "hurt", "die", "sleep", "wake", "step", "select", "refuse",
      ];
      const missing = wanted.filter((e) => !wired.includes(e));
      return missing.length ? `no sound for: ${missing.join(", ")}` : null;
    });

    await checkAsync("every sound actually makes a noise when rendered", async () => {
      const silent = [];
      for (const event of Sound.events()) {
        const out = await Sound.renderOffline(event);
        // 0.01 is well below anything audible but far above a numerically
        // silent buffer, so this catches "graph built, nothing came out".
        if (out.peak < 0.01) silent.push(`${event} (peak ${out.peak.toFixed(5)})`);
      }
      return silent.length ? `silent: ${silent.join(", ")}` : null;
    });

    await checkAsync("no sound is loud enough to clip", async () => {
      const loud = [];
      for (const event of Sound.events()) {
        const out = await Sound.renderOffline(event);
        if (out.peak > 1.0) loud.push(`${event} (peak ${out.peak.toFixed(2)})`);
      }
      return loud.length ? `clipping: ${loud.join(", ")}` : null;
    });

    await checkAsync("a sound lasts as long as its file says", async () => {
      const def = Sound.def("harvest");
      const out = await Sound.renderOffline("harvest");
      const seconds = out.frames / 44100;
      return Math.abs(seconds - (def.duration + 0.05)) < 0.02
        ? null : `rendered ${seconds.toFixed(3)}s for a ${def.duration}s sound`;
    });

    /* --- saving --------------------------------------------------------- */
    check("a save carries the seed, not the map", () => {
      const payload = G.savePayload();
      if (payload.world.seed !== G.S.world.seed) return "the seed is missing";
      if (payload.world.tiles) return "the whole map is being stored";
      if (!payload.crops || !payload.tileEdits) return "worked ground is not saved";
      return null;
    });

    return { failures, results };
  };

  /* Run once the game is up, and put the result where a DOM dump can see it. */
  const wait = setInterval(() => {
    if (!window.EmberTest || !window.EmberTest.S.world) return;
    clearInterval(wait);
    window.runSelfTest().then(finish);
  }, 200);

  function finish(out) {
    const box = document.createElement("pre");
    box.id = "selftest";
    box.style.cssText =
      "position:fixed;inset:0;z-index:99;background:#12100e;color:#efe6d8;" +
      "font:12px/1.6 monospace;padding:20px;overflow:auto;margin:0";
    box.textContent =
      `SELFTEST ${out.failures === 0 ? "PASS" : "FAIL"} — ` +
      `${out.results.length - out.failures}/${out.results.length}\n\n` +
      out.results.join("\n");
    document.body.appendChild(box);
    document.title = out.failures === 0 ? "SELFTEST PASS" : "SELFTEST FAIL";
    /* Reported to the backend as well as to the page, so an automated run can
       read the result even if the browser is killed before it can be scraped. */
    fetch("/api/selftest", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: out.failures === 0 ? "PASS" : "FAIL",
        passed: out.results.length - out.failures,
        total: out.results.length,
        results: out.results,
      }),
    }).catch(() => {});
  }
})();
