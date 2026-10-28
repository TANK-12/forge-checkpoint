/* Emberfield — play: the simulation loop and every verb the world answers to.
 *
 * Split out of index.html in session 5. This file is what happens each frame
 * that is not drawing: moving the player and the clock, farming (till, water,
 * plant, harvest), the shop's arithmetic, chest loot, going down into the wilds
 * and back, and the small nightly combat. The render lives in render.js and the
 * screens in ui.js; this file calls into both but owns neither.
 *
 * Loaded as a classic script after render.js. `S`, `TILE`, the utilities,
 * `Sound` and everything in world.js are already in scope.
 */
"use strict";

/* ------------------------------------------------------------ simulation */
function facingTile() {
  const tx = Math.floor(S.player.x / TILE), ty = Math.floor(S.player.y / TILE);
  if (S.player.dir === "left") return [tx - 1, ty];
  if (S.player.dir === "right") return [tx + 1, ty];
  if (S.player.dir === "up") return [tx, ty - 1];
  return [tx, ty + 1];
}

/* The dodge roll.

   A short, fast dart in the direction you are already holding, with the same
   brief invulnerability a hit gives you, on a cooldown. It exists because the
   wilds otherwise have exactly one answer to a slime closing in -- walk
   backwards and shoot -- and because you can get pinned against a wall with no
   way out at all.

   Deliberately not a stamina bar. One cooldown you can feel is easier to read
   mid-fight than a draining meter, and a bar would want a UI, a regen rate and
   a food that refills it. The roll resolves against walls exactly like walking
   does, so it cannot be used to clip through a fence. */
const ROLL = { speed: 460, time: 0.24, cooldown: 0.85, mercy: 0.5 };

function startRoll(dx, dy) {
  const p = S.player;
  if (p.rollT > 0 || p.rollCool > 0 || S.paused) return false;
  /* Rolling on the spot would be a free invulnerability window, so a direction
     is required: whatever you are holding, or failing that, where you face. */
  if (!dx && !dy) {
    if (p.dir === "left") dx = -1;
    else if (p.dir === "right") dx = 1;
    else if (p.dir === "up") dy = -1;
    else dy = 1;
  }
  const len = Math.hypot(dx, dy) || 1;
  p.rollX = dx / len;
  p.rollY = dy / len;
  p.rollT = ROLL.time;
  p.rollCool = ROLL.cooldown;
  p.hurtT = Math.max(p.hurtT || 0, ROLL.mercy);
  p.rolls = (p.rolls || 0) + 1;
  Sound.play("roll");
  return true;
}

function step(dt, t) {
  const p = S.player;
  let dx = 0, dy = 0;
  if (S.keys.has("a") || S.keys.has("arrowleft")) dx -= 1;
  if (S.keys.has("d") || S.keys.has("arrowright")) dx += 1;
  if (S.keys.has("w") || S.keys.has("arrowup")) dy -= 1;
  if (S.keys.has("s") || S.keys.has("arrowdown")) dy += 1;

  if (p.rollCool > 0) p.rollCool -= dt;
  if (p.rollT > 0) {
    /* Mid-roll you have no steering: the whole point is that you commit. */
    p.rollT -= dt;
    const dist = ROLL.speed * dt;
    if (canStand(p.x + p.rollX * dist, p.y)) p.x += p.rollX * dist;
    if (canStand(p.x, p.y + p.rollY * dist)) p.y += p.rollY * dist;
    p.moving = true;
    if (p.hurtT > 0) p.hurtT -= dt;
    S.clock.minutes += dt * minutesPerSecond();
    stepCombat(dt, t);
    if (!S.inWilds && !S.inInterior) stepNpcs(dt, t);
    steerAmbience();
    return;
  }

  p.moving = !!(dx || dy);
  const beforeX = p.x, beforeY = p.y;
  if (p.moving) {
    if (dx < 0) p.dir = "left"; else if (dx > 0) p.dir = "right";
    else if (dy < 0) p.dir = "up"; else p.dir = "down";
    const len = Math.hypot(dx, dy) || 1;
    const speed = p.speed * (S.keys.has("shift") ? 1.75 : 1) * dt;
    /* Axes resolved separately so a blocked diagonal slides along the wall
       instead of stopping dead, which is what makes tight gaps feel fair. */
    const nx = p.x + (dx / len) * speed;
    if (canStand(nx, p.y)) p.x = nx;
    const ny = p.y + (dy / len) * speed;
    if (canStand(p.x, ny)) p.y = ny;
    S.player.moved = (S.player.moved || 0) + 1;

    /* Footsteps are spaced by distance walked, not by time, so running gives
       you a faster stride rather than the same stride played faster -- and so
       walking into a wall makes no sound at all. */
    S.stride = (S.stride || 0) + Math.hypot(p.x - beforeX, p.y - beforeY);
    if (S.stride > 13) {
      S.stride = 0;
      Sound.play("step", { pitch: 0.9 + Math.random() * 0.25 });
    }
  }
  if (p.hurtT > 0) p.hurtT -= dt;
  if (p.kx || p.ky) {
    if (canStand(p.x + p.kx * dt, p.y)) p.x += p.kx * dt;
    if (canStand(p.x, p.y + p.ky * dt)) p.y += p.ky * dt;
    p.kx *= 0.80; p.ky *= 0.80;
    if (Math.abs(p.kx) < 2) p.kx = 0;
    if (Math.abs(p.ky) < 2) p.ky = 0;
  }

  const before = isNight();
  S.clock.minutes += dt * minutesPerSecond();
  if (S.clock.minutes >= 1440) { S.clock.minutes -= 1440; newDay(); }
  if (isNight() !== before && !S.inInterior) applyPalette();

  stepCombat(dt, t);
  if (!S.inWilds && !S.inInterior) stepNpcs(dt, t);
  steerAmbience();
}

/* The ambient bed is steered every frame rather than started and stopped, so
   the night arrives instead of switching on. Level rises through dusk and falls
   through dawn, following the same hours the colour wash uses. */
function steerAmbience() {
  const h = S.clock.minutes / 60;
  let night = 0;
  if (h >= 19 && h < 21) night = (h - 19) / 2;
  else if (h >= 21 || h < 5) night = 1;
  else if (h >= 5 && h < 7) night = 1 - (h - 5) / 2;
  Sound.ambience("ambience_night", S.inWilds ? 0 : night);
  Sound.ambience("ambience_wilds", S.inWilds ? 1 : 0);
}

/* Rolling past midnight without sleeping. You still get a new day -- crops
   just do not grow, because growth is what sleeping is *for*. */
function newDay() {
  if (turnDay()) applyPalette();
}

/* The one place a day turns over: the date moves on, a season ends every 28
   days, and wet soil dries. Midnight, a night's sleep and waking after a fall
   all come through here. Waking after a fall used to add a day by hand and
   skip the rest, so a fall on day 28 stretched spring to 56 days and left
   yesterday's watering on the field. Returns true when the season changed
   (the caller repaints). */
function turnDay() {
  S.clock.day += 1;
  let seasonChanged = false;
  if ((S.clock.day - 1) % 28 === 0) {
    S.clock.season = SEASONS[(SEASONS.indexOf(S.clock.season) + 1) % 4];
    S.ground.clear();
    seasonChanged = true;
  }
  for (const crop of Object.values(S.crops)) crop.watered = false;
  dryTheField();
  return seasonChanged;
}

/* A quiet save every couple of minutes of play, so a crash or a power cut
   loses little. */
let saveEveryMs = 120000;

function loop(t) {
  S.loopId = 0;
  if (!S.running) return;
  const dt = Math.min(0.05, (t - S.lastT) / 1000 || 0);
  S.lastT = t;
  step(dt, t);
  if (!S.world) return;   // a full permadeath inside this step closed the valley
  if (!S.savedT) S.savedT = t;
  else if (t - S.savedT > saveEveryMs && !S.dead) {
    S.savedT = t;
    autosave(true);
  }
  render(t);
  hud();
  kickLoop();
}

/* ------------------------------------------------------------- farming */
/* Tilling, watering, planting and harvesting. Each is a "verb" a tool names in
   its content file, so a second hoe with a bigger radius is a JSON file and
   nothing else. */

/* A verb works one tile and stays silent. The stroke's sound is played once by
   interact(), because an upgraded tool runs the verb nine times and nine
   overlapping hoe strokes is a noise, not a sound effect. */
const VERBS = {
  till(tx, ty) {
    const kind = tileKind(tileAt(tx, ty));
    if (kind === "farm") return "already tilled";
    if (kind !== "grass" && kind !== "soil") return "you cannot till that";
    if (S.crops[key(tx, ty)]) return "something is growing there";
    setTile(tx, ty, "tilled");
    return null;
  },
  water(tx, ty) {
    if (tileAt(tx, ty) === "tilled_wet") return "already watered";
    if (tileKind(tileAt(tx, ty)) !== "farm") return "there is nothing to water";
    setTile(tx, ty, "tilled_wet");
    const crop = S.crops[key(tx, ty)];
    if (crop) crop.watered = true;
    return null;
  },
};

function plant(seedId, tx, ty) {
  const crop = all("crops").find((entry) => entry.seed_item === seedId);
  if (!crop) return "those seeds grow nothing";
  if (tileKind(tileAt(tx, ty)) !== "farm") return "till the ground first";
  if (S.crops[key(tx, ty)]) return "something is already growing there";
  if (!crop.seasons.includes(S.clock.season)) {
    return `${crop.label} will not grow in ${S.clock.season}`;
  }
  S.crops[key(tx, ty)] = {
    id: crop.id, stage: 0, days: 0,
    watered: tileAt(tx, ty) === "tilled_wet",
  };
  take(seedId, 1);
  Sound.play("plant");
  return null;
}

function harvest(tx, ty) {
  const at = S.crops[key(tx, ty)];
  if (!at) return "there is nothing to harvest";
  const def = lookup("crops", at.id);
  if (!def || at.stage < def.stages.length - 1) return `${def ? def.label : "it"} is not ready`;
  give(def.yield_item, def.yield_qty);
  if (def.regrow > 0) {
    /* A regrowing crop drops back a stage rather than dying, which is the
       whole reason it costs more at the seed stall. */
    at.stage = Math.max(0, def.stages.length - 2);
    at.days = -def.regrow;
  } else {
    delete S.crops[key(tx, ty)];
  }
  Sound.play("harvest");
  toast(`harvested ${def.yield_qty} ${lookup("items", def.yield_item)?.label || def.label}`);
  return null;
}

function give(itemId, qty) {
  if (!itemId) return;
  S.inv[itemId] = (S.inv[itemId] || 0) + qty;
  rebuildHotbar();
}

function take(itemId, qty) {
  S.inv[itemId] = (S.inv[itemId] || 0) - qty;
  if (S.inv[itemId] <= 0) delete S.inv[itemId];
  rebuildHotbar();
}

/* --------------------------------------------------------------- eating */
/* e eats. Food is what an item file calls kind "food"; its "heals" field says
   how many hearts it gives back. A food file without that field heals one
   heart per 30 gold of its sell price, at least one, so the cooked dishes are
   worth carrying (a turnip 1, a field ration 2, a hearty stew 3) before
   anyone has tuned them by hand. A new food is still one JSON file. */
function foodHeals(item) {
  if (!item || item.kind !== "food") return 0;
  if (item.heals > 0) return Math.floor(item.heals);
  return Math.max(1, Math.round((item.sell || 0) / 30));
}

function carriedFood() {
  return all("items")
    .filter((item) => foodHeals(item) > 0 && (S.inv[item.id] || 0) > 0)
    .sort((a, b) => foodHeals(a) - foodHeals(b) || (a.sell || 0) - (b.sell || 0));
}

/* The smallest meal that fills every missing heart, or failing that the
   biggest you carry -- so a scratch costs a turnip, not the stew you were
   saving for the deep end of the cavern. */
function bestFood() {
  const missing = S.player.maxHp - S.player.hp;
  const foods = carriedFood();
  if (!foods.length) return null;
  return foods.find((item) => foodHeals(item) >= missing) || foods[foods.length - 1];
}

function eat() {
  if (S.player.hp >= S.player.maxHp) { refuse("you are not hungry"); return false; }
  const food = bestFood();
  if (!food) { refuse("you have nothing to eat"); return false; }
  const before = S.player.hp;
  S.player.hp = Math.min(S.player.maxHp, S.player.hp + foodHeals(food));
  take(food.id, 1);
  // "eat" is a sound recipe like any other; a store seeded before it existed
  // falls back to the harvest chime rather than staying silent.
  Sound.play(Sound.def("eat") ? "eat" : "harvest");
  toast(`ate the ${food.label.toLowerCase()} · +${S.player.hp - before} ♥`);
  return true;
}

/* Space: interact. The bed sleeps, a ripe crop harvests, and otherwise the
   held tool's verb runs on the tile you are facing. One key, resolved by what
   is in front of you and what is in your hand. */
function nearbyUse(px, py) {
  for (const obj of S.world.objects) {
    if (!obj.use) continue;
    if (Math.abs(px - obj.x) <= 2 && Math.abs(py - obj.y) <= 2) return obj;
  }
  return null;
}

function interact() {
  const [tx, ty] = facingTile();
  /* The cave mouth in the valley, and the way out of the wilds. Both are
     entered with the same key as everything else, so there is one verb to
     learn rather than a special case per doorway. */
  const px = Math.floor(S.player.x / TILE), py = Math.floor(S.player.y / TILE);
  if (S.inWilds) {
    const way = S.world.regions.entrance;
    if (way && Math.abs(px - way[0]) <= 2 && Math.abs(py - way[1]) <= 2) {
      leaveWilds(); return;
    }
  } else {
    const mouth = S.world.regions.cave_mouth;
    if (mouth && Math.abs(px - mouth[0]) <= 3 && Math.abs(py - mouth[1]) <= 3) {
      enterWilds(); return;
    }
  }

  /* Someone to talk to takes priority over whatever you are facing -- a
     villager standing at their own door should answer, not be walked through. */
  const npc = nearestNpc(px, py, 1.8);
  if (npc) { talkTo(npc); return; }

  /* Objects can carry a "use" in their world data -- the bed sleeps, the stall
     opens the shop, the chest opens, a door leads inside. Dispatching on that
     rather than on the sprite name means a second stall, or a house anywhere
     else, needs no code at all. */
  const near = nearbyUse(px, py);
  if (near) {
    if (near.use === "shop") { shopScreen(); return; }
    if (near.use === "chest") { openChest(near); return; }
    if (near.use === "sleep") { sleep(); return; }
    if (near.use === "door") { enterBuilding(near); return; }
    if (near.use === "exit") { leaveBuilding(); return; }
    if (near.use === "craft" || near.use === "cook") {
      craftScreen(near.station || "workbench"); return;
    }
    if (near.use === "storage") { storageScreen(); return; }
  }

  const there = S.crops[key(tx, ty)];
  if (there) {
    const def = lookup("crops", there.id);
    if (def && there.stage >= def.stages.length - 1) { harvest(tx, ty); return; }
  }

  const item = held();
  if (!item) { refuse("your hands are empty"); return; }

  if (item.kind === "tools") {
    const tool = lookup("tools", item.id);
    const verb = VERBS[tool.verb];
    if (!verb) { toast(`${tool.label} does nothing yet`); return; }
    const problem = applyToolArea(verb, tx, ty, toolRadius(item.id));
    if (problem) refuse(problem);
    // A tool's verb name is also its sound event ("till", "water"), so the
    // wiring stays in the content store rather than in a lookup here.
    else Sound.play(tool.verb);
    return;
  }
  if (item.kind === "items" && lookup("items", item.id).kind === "seed") {
    const problem = plant(item.id, tx, ty);
    if (problem) refuse(problem);
    return;
  }
  if (item.kind === "weapons") { refuse("click to shoot"); return; }
}

/* Sleeping is how a day ends and the only way crops grow. It happens at the
   bed rather than at a keypress so the farm has somewhere that is home. */
function sleep() {
  if (!S.running) return;
  S.running = false;
  S.sleeping = true;
  Sound.play("sleep");
  Sound.silenceAmbience();
  $("#fade").classList.add("on");
  setTimeout(() => {
    const grown = growOvernight();
    turnDay();
    S.clock.minutes = 6 * 60;
    S.player.hp = S.player.maxHp;
    S.foes = []; S.shots = [];
    applyPalette();
    autosave();
    $("#fade").classList.remove("on");
    S.sleeping = false;
    toast(grown ? `day ${S.clock.day} — ${grown} grew overnight` : `day ${S.clock.day}`);
    // Switched away during the fade: wake to the pause screen, not to a game
    // running for nobody behind another app.
    if (offScreen()) { pauseScreen(); return; }
    Sound.play("wake");
    S.running = true; S.lastT = performance.now();
    kickLoop();
  }, 620);
}

/* Growth is resolved once, on sleep, rather than every frame. Watered crops
   advance; dry ones sit; out-of-season crops sit too. */
function growOvernight() {
  let grown = 0;
  for (const crop of Object.values(S.crops)) {
    const def = lookup("crops", crop.id);
    if (!def) continue;
    if (crop.stage >= def.stages.length - 1 && def.regrow <= 0) continue;
    if (!crop.watered) continue;
    if (!def.seasons.includes(S.clock.season)) continue;
    crop.days += 1;
    grown += 1;
    const needed = def.stages[Math.min(crop.stage, def.stages.length - 1)];
    if (crop.days >= needed && crop.stage < def.stages.length - 1) {
      crop.stage += 1;
      crop.days = 0;
    }
    crop.watered = false;
  }
  return grown;
}

/* Watered soil dries out overnight. Without this you water once and never
   again, and the watering can stops being a decision. */
function dryTheField() {
  /* Always the valley, never the room you are standing in. tileEdits holds
     valley coordinates, and you sleep indoors -- writing them into a 15x11
     interior threw and left the sleep fade stuck on black. */
  const valley = valleyWorld();
  const showing = valley === S.world;
  let dried = 0;
  for (const [k, name] of Object.entries(S.tileEdits)) {
    if (name !== "tilled_wet") continue;
    const [x, y] = k.split(",").map(Number);
    if (!valley.tiles[y] || valley.tiles[y][x] === undefined) continue;
    valley.tiles[y][x] = "tilled";
    S.tileEdits[k] = "tilled";
    dried += 1;
    if (showing) repaintTile(x, y);
  }
  /* Repainting only works on the bake that is currently live. If the field
     dried while you were indoors, drop the parked bake so stepping outside
     rebuilds it rather than showing yesterday's wet soil. */
  if (dried && !showing) valleyGround().clear();
}

/* ----------------------------------------------------------------- shop */
/* The stall in the town square. Its stock is not a list anywhere -- it sells
   every item in the content store with a buy price above zero, and buys back
   anything you are carrying that has a sell price. So putting something on the
   shelf is setting a number on an item file. */
function stock() {
  return all("items").filter((item) => item.buy > 0);
}

function sellable() {
  return all("items").filter((item) => (S.inv[item.id] || 0) > 0 && item.sell > 0);
}

function buyItem(id) {
  const item = lookup("items", id);
  if (!item || item.buy <= 0) return;
  if (S.gold < item.buy) { refuse("you cannot afford that"); return; }
  S.gold -= item.buy;
  give(id, 1);
  Sound.play("buy");
  shopScreen();
}

function sellItem(id) {
  const item = lookup("items", id);
  if (!item || item.sell <= 0 || !(S.inv[id] > 0)) return;
  S.gold += item.sell;
  take(id, 1);
  Sound.play("sell");
  shopScreen();
}

/* ---------------------------------------------------------------- chest */
/* One at the deep end of every cavern. Which table it draws from is decided
   here, from the content store, weighted -- so a rarer reward is a smaller
   number in a JSON file rather than a branch. */
function rollLoot() {
  const tables = all("loot").filter((table) => {
    if (table.night_only && !(S.world.regions || {}).night) return false;
    return S.clock.day >= (table.min_day || 1);
  });
  if (!tables.length) return null;
  const weights = tables.map((t) => t.weight || 10);
  const total = weights.reduce((a, b) => a + b, 0);
  let roll = Math.random() * total;
  for (let i = 0; i < tables.length; i++) {
    roll -= weights[i];
    if (roll <= 0) return tables[i];
  }
  return tables[0];
}

function openChest(chest) {
  if (chest.opened) { refuse("you have already emptied that"); return; }
  const table = rollLoot();
  if (!table) { refuse("it is empty"); return; }
  chest.opened = true;
  Sound.play("chest");

  const gold = table.gold_min +
    Math.floor(Math.random() * Math.max(1, table.gold_max - table.gold_min + 1));
  S.gold += gold;
  const won = [];
  for (const id of table.items) {
    give(id, 1);
    won.push(lookup("items", id)?.label || id);
  }
  /* Emptied chests are drawn differently rather than removed, so you can see
     where you have already been -- which is the only navigational aid a cavern
     that regenerates every day is ever going to get. */
  toast(`${table.label}: ${gold}g${won.length ? " and " + won.join(", ") : ""}`, 3200);
}

/* ---------------------------------------------------------------- wilds */
/* The valley is the place that becomes familiar; the wilds are the place that
   never does. A fresh cavern is generated for every day/night cycle from the
   valley's seed plus the day and whether it is dark, so it is different each
   time and identical when a save is reloaded. Nothing about a run down there is
   stored -- walk out and that cavern is gone for good.

   Entering parks the valley rather than discarding it: your crops, your worked
   ground and where you were standing all come back untouched. */
async function enterWilds() {
  /* S.travelling: a second press while the cavern is still on its way would
     park the first cavern as if it were the valley, and the valley -- crops,
     worked ground and all -- would be gone for the session. */
  if (S.inWilds || S.inInterior || S.travelling) return;
  S.travelling = true;
  Sound.play("portal");
  let data;
  try {
    data = await api("/api/wilds", {
      json: { seed: S.world.seed, day: S.clock.day, night: isNight() },
    });
  } catch (e) { toast("the way down is blocked: " + e.message); return; }
  finally { S.travelling = false; }

  S.valley = {
    world: S.world, tilesMeta: S.tilesMeta, objIndex: S.objIndex,
    ground: S.ground, palette: S.palette,
    player: { x: S.player.x, y: S.player.y },
  };
  S.inWilds = true;
  S.ground = new Map();
  swapWorld(data);
  toast(isNight() ? "the wilds, after dark" : "the wilds");
}

function leaveWilds({ save = true } = {}) {
  if (!S.inWilds || !S.valley) return;
  Sound.play("portal");
  S.inWilds = false;
  S.world = S.valley.world;
  S.tilesMeta = S.valley.tilesMeta;
  S.objIndex = S.valley.objIndex;
  S.ground = S.valley.ground;
  /* Back at the cave mouth rather than where you went in, because the mouth is
     where the door is. Standing one tile south of it so you are not immediately
     re-entering. */
  const mouth = S.world.regions.cave_mouth;
  S.player.x = mouth[0] * TILE + TILE / 2;
  S.player.y = (mouth[1] + 2) * TILE + TILE / 2;
  S.valley = null;
  S.foes = []; S.shots = [];
  applyPalette();
  if (save) autosave(true);
  toast("back in the valley");
}

/* --------------------------------------------------------------- combat */
/* Deliberately small: foes come out in the valley after dark, away from your
   farm and the town, and clear at dawn. The nightly wilds are their own map and
   their own generator, and are not this. */

function stepCombat(dt, t) {
  /* Nothing hunts you in your own kitchen. */
  if (S.inInterior) { S.foes = []; S.shots = []; return; }
  const night = isNight();
  /* Underground it is always dangerous; in the valley only after dark. */
  if (S.inWilds || night) topUpFoes();
  else if (S.foes.length) S.foes = [];

  if (S.mouse.down) fire(t);
  S.fireT -= dt;

  for (const shot of S.shots) {
    shot.x += shot.vx * dt;
    shot.y += shot.vy * dt;
    shot.life -= dt;
    if (blockedAtPixel(shot.x, shot.y)) shot.life = 0;
    for (const foe of S.foes) {
      if (foe.hp <= 0) continue;
      if (Math.hypot(foe.x - shot.x, foe.y - shot.y) < 8) {
        foe.hp -= shot.damage;
        foe.hurtT = 0.12;
        /* Shoved back along the arrow's line. Without this a fight reads as two
           sprites overlapping -- knockback is the cheapest thing that makes a
           hit look like it landed, and it also stops a fast foe pinning you
           against a wall with no way to break contact. */
        const push = Math.hypot(shot.vx, shot.vy) || 1;
        foe.kx = (shot.vx / push) * 62;
        foe.ky = (shot.vy / push) * 62;
        shot.life = 0;
        Sound.play("hit");
        if (foe.hp <= 0) killFoe(foe);
        break;
      }
    }
  }
  S.shots = S.shots.filter((s) => s.life > 0);

  for (const foe of S.foes) {
    if (foe.hurtT > 0) foe.hurtT -= dt;
    /* Knockback decays fast and is resolved against walls like ordinary
       movement, so nothing gets shoved through solid rock. */
    if (foe.kx || foe.ky) {
      if (!blockedAtPixel(foe.x + foe.kx * dt, foe.y)) foe.x += foe.kx * dt;
      if (!blockedAtPixel(foe.x, foe.y + foe.ky * dt)) foe.y += foe.ky * dt;
      foe.kx *= 0.82; foe.ky *= 0.82;
      if (Math.abs(foe.kx) < 2) foe.kx = 0;
      if (Math.abs(foe.ky) < 2) foe.ky = 0;
    }
    const dx = S.player.x - foe.x, dy = S.player.y - foe.y;
    const dist = Math.hypot(dx, dy) || 1;
    if (dist < 190) {
      const nx = foe.x + (dx / dist) * foe.speed * dt;
      const ny = foe.y + (dy / dist) * foe.speed * dt;
      if (!blockedAtPixel(nx, foe.y)) foe.x = nx;
      if (!blockedAtPixel(foe.x, ny)) foe.y = ny;
    }
    if (dist < foe.touch && S.player.hurtT <= 0) {
      hurtPlayer(foe.damage);
      /* You get shoved too, away from whatever hit you. Combined with the
         invulnerability window this is what lets you break out of a crowd
         instead of being ground down in place. */
      S.player.kx = (-dx / dist) * 90;
      S.player.ky = (-dy / dist) * 90;
    }
  }
  /* Anything killed, or left far enough behind that it will never catch up, is
     dropped. Without the distance cull the valley slowly fills with slimes
     following you from three screens away. */
  S.foes = S.foes.filter(
    (f) => f.hp > 0 && Math.hypot(f.x - S.player.x, f.y - S.player.y) < 700
  );
}

/* Foes are kept topped up in a ring around you rather than sprinkled once over
   the whole valley at dusk.

   Scattering them across 96x72 tiles put roughly one foe every seven hundred
   tiles: statistically you could cross the valley at midnight and meet nothing,
   which is not a night that feels dangerous. Spawning in a ring means the dark
   is populated wherever you actually are, and the far cull keeps the count
   honest instead of accumulating. */
function topUpFoes() {
  const kinds = all("foes").filter((f) => f.night_only !== false);
  if (!kinds.length) return;
  const px = Math.floor(S.player.x / TILE), py = Math.floor(S.player.y / TILE);
  if (inSafeRegion(px, py)) return;   // your farm and the town stay clear

  const target = 4 + Math.min(8, S.clock.day);
  if (S.foes.length >= target) return;

  const weights = kinds.map((f) => f.weight || 10);
  const total = weights.reduce((a, b) => a + b, 0);

  for (let attempt = 0; attempt < 60 && S.foes.length < target; attempt++) {
    const angle = Math.random() * Math.PI * 2;
    /* World pixels, not screen pixels: 16 to a tile, so this is five to
       thirteen tiles out. Sized against the *view* rather than picked to feel
       right on paper -- a first pass used 150-370, which at zoom 4 is beyond
       the edge of the screen in every direction, so the night stayed empty no
       matter how many spawned. */
    const radius = 80 + Math.random() * 130;
    const wx = S.player.x + Math.cos(angle) * radius;
    const wy = S.player.y + Math.sin(angle) * radius;
    const tx = Math.floor(wx / TILE), ty = Math.floor(wy / TILE);
    if (tx < 1 || ty < 1 || tx >= S.world.width - 1 || ty >= S.world.height - 1) continue;
    if (inSafeRegion(tx, ty)) continue;
    if (blockedAtPixel(wx, wy)) continue;

    let roll = Math.random() * total, pick = kinds[0];
    for (let i = 0; i < kinds.length; i++) {
      roll -= weights[i];
      if (roll <= 0) { pick = kinds[i]; break; }
    }
    S.foes.push({
      id: pick.id, sprite: pick.sprite, x: wx, y: wy,
      hp: pick.hp, speed: pick.speed, damage: pick.damage,
      touch: pick.touch, drops: pick.drops || [], hurtT: 0,
    });
  }
}

function fire(t) {
  const item = held();
  const weapon = item && item.kind === "weapons" ? lookup("weapons", item.id) : null;
  if (!weapon) return;
  if (S.fireT > 0) return;
  S.fireT = weapon.cooldown;

  /* Aimed at the cursor, not at the four directions you can face -- the whole
     reason combat is on the mouse. */
  const v = S.view;
  const worldX = v.camX + (S.mouse.x * S.dpr) / v.z;
  const worldY = v.camY + (S.mouse.y * S.dpr) / v.z;
  const angle = Math.atan2(worldY - S.player.y, worldX - S.player.x);
  Sound.play("shoot");
  S.shots.push({
    x: S.player.x, y: S.player.y - 6,
    vx: Math.cos(angle) * weapon.shot_speed,
    vy: Math.sin(angle) * weapon.shot_speed,
    angle, damage: weapon.damage, sprite: weapon.shot_sprite,
    life: weapon.range / weapon.shot_speed,
  });
  /* Shooting turns you to face the shot, so the sprite never fires over its
     own shoulder. */
  if (Math.abs(Math.cos(angle)) > Math.abs(Math.sin(angle))) {
    S.player.dir = Math.cos(angle) > 0 ? "right" : "left";
  } else {
    S.player.dir = Math.sin(angle) > 0 ? "down" : "up";
  }
}

/* Your farm and the town stay safe. Night should make the valley feel
   dangerous to cross, not make your own fence a place you get killed in. */
function inSafeRegion(tx, ty) {
  /* There is no safe ground in the wilds -- except the few tiles by the way
     out, so you can catch your breath before deciding to go back in. */
  if (S.inWilds) {
    const way = S.world.regions.entrance;
    return !!(way && Math.abs(tx - way[0]) <= 3 && Math.abs(ty - way[1]) <= 3);
  }
  /* Every settlement and every farmstead is safe ground -- night should make
     the open valley dangerous to cross, not get a villager killed on their own
     doorstep. The cave is the one laid region that is not a refuge. */
  for (const [name, r] of Object.entries(S.world.regions)) {
    if (name === "cave" || !r || typeof r !== "object" || !("w" in r)) continue;
    if (tx >= r.x - 3 && tx < r.x + r.w + 3 && ty >= r.y - 3 && ty < r.y + r.h + 3) return true;
  }
  return false;
}

function killFoe(foe) {
  Sound.play("foe_dies");
  for (const drop of foe.drops) give(drop, 1);
  S.gold += 2;
}

function hurtPlayer(amount) {
  S.player.hp -= amount;
  Sound.play(S.player.hp <= 0 ? "die" : "hurt");
  S.player.hurtT = 0.9;   // brief invulnerability, or a slime kills you instantly
  if (S.player.hp <= 0) die();
}

/* The death rule chosen on the title screen finally does something. */
function die() {
  S.running = false;
  S.dead = true;
  S.foes = []; S.shots = [];
  /* However the rule resolves, you come back out. Waking underground in a
     cavern that is about to be regenerated -- or inside somebody's front room
     -- is not a place to wake up. */
  /* ...without the autosave a normal exit makes. Under full permadeath that
     save raced the DELETE below and could land after it, bringing the valley
     back; under the other rules the wake-up (or closing the page) saves the
     state after the fall anyway. */
  if (S.inWilds) leaveWilds({ save: false });
  if (S.inInterior) leaveBuilding({ save: false });
  if (S.deathRule === "full") {
    fetch(`/api/saves/${saveSlot()}`, { method: "DELETE" }).catch(() => {});
    // Gone for good: no later save, not even the one on closing the page,
    // may write this valley back.
    S.world = null;
    showVeil(`
      <h1>The valley closes</h1>
      <p class="sub">Full permadeath. Day ${S.clock.day} was the last one, and the
      save is gone.</p>
      <div class="row"><button class="btn" id="again">A new valley</button></div>`);
    $("#again").addEventListener("click", () => { S.dead = false; titleScreen(); });
    return;
  }
  const lost = S.deathRule === "soft" ? Math.floor(S.gold / 2) : S.gold;
  S.gold -= lost;
  const kept = S.deathRule === "soft"
    ? "You wake at the farm. Nothing is gone but the coin."
    : "The adventurer is gone. The farm, the valley and what you stored remain.";
  if (S.deathRule === "character") { S.inv = {}; startingKit(); rebuildHotbar(); }
  showVeil(`
    <h2>You fell</h2>
    <p class="sub">${kept}${lost ? ` Lost ${lost} gold.` : ""}</p>
    <div class="row"><button class="btn" id="wake">Wake up</button></div>`);
  $("#wake").addEventListener("click", () => {
    S.dead = false;
    S.player.hp = S.player.maxHp;
    S.player.x = S.world.spawn[0] * TILE + TILE / 2;
    S.player.y = S.world.spawn[1] * TILE + TILE / 2;
    S.clock.minutes = 6 * 60;
    if (turnDay()) applyPalette();
    autosave();
    resume();
  });
}

/* -------------------------------------------------------------- interiors */
/* A house you walk into is a small map swapped in exactly the way the wilds
   are: the valley is parked, not discarded, so your crops and where you were
   standing come back untouched. The room regenerates from its building id, so
   nothing about it is saved -- a save made indoors describes the valley and the
   tile just outside the door. */

async function enterBuilding(obj) {
  if (S.inInterior || S.inWilds || S.travelling || !obj || !obj.building) return;
  S.travelling = true;
  Sound.play("portal");
  let data;
  try {
    data = await api("/api/interior", {
      json: { building: obj.building, seed: S.world.seed },
    });
  } catch (e) { toast("the door will not open: " + e.message); return; }
  finally { S.travelling = false; }

  S.parked = {
    world: S.world, tilesMeta: S.tilesMeta, objIndex: S.objIndex,
    ground: S.ground, palette: S.palette,
    door: (obj.door || [Math.floor(S.player.x / TILE), Math.floor(S.player.y / TILE)]).slice(),
    player: { x: S.player.x, y: S.player.y },
  };
  S.inInterior = true;
  S.ground = new Map();
  swapWorld(data);
  toast("inside");
}

function leaveBuilding({ save = true } = {}) {
  if (!S.inInterior || !S.parked) return;
  Sound.play("portal");
  S.inInterior = false;
  S.world = S.parked.world;
  S.tilesMeta = S.parked.tilesMeta;
  S.objIndex = S.parked.objIndex;
  S.ground = S.parked.ground;
  /* Step out onto the tile just south of the door, facing away from the house,
     so pressing space again does not walk you straight back in. */
  const d = S.parked.door;
  S.player.x = (d[0] + 0.5) * TILE;
  S.player.y = (d[1] + 1.5) * TILE;
  S.player.dir = "down";
  S.parked = null;
  S.foes = []; S.shots = [];
  applyPalette();
  if (save) autosave(true);
  toast("back outside");
}

/* ------------------------------------------------------------------ NPCs */
/* The valley's residents. Built once when the valley loads, they walk a daily
   schedule of stops on a real path (a greedy walk wedges them behind the first
   tree), speak canned lines, and -- for the shopkeeper -- open the stall. They
   exist only in the valley: `stepNpcs` and the renderer both stand down in the
   wilds and indoors, and `S.npcs` is left intact so they are simply where you
   left them when you come back. */

function buildNpcs() {
  S.npcs = [];
  if (!S.world || !S.world.regions) return;
  const buildings = S.world.regions.buildings || [];
  for (const def of all("npcs")) {
    const home = buildings.find((b) => b.id === def.home);
    if (!home) continue;
    const wells = S.world.objects.filter((o) => o.sprite === "well");
    let nearestWell = null, best = Infinity;
    for (const w of wells) {
      const d = Math.hypot(w.x - home.door[0], w.y - home.door[1]);
      if (d < best) { best = d; nearestWell = [w.x, w.y]; }
    }
    S.npcs.push({
      id: def.id, def, sprite: def.sprite,
      x: (home.door[0] + 0.5) * TILE, y: (home.door[1] + 0.5) * TILE,
      dir: "down", moving: false,
      targetKey: null, path: [], pathI: 0, lineI: 0,
      home, well: nearestWell, hidden: false,
    });
  }
}

/* The schedule is [[hour, place], ...]. The current stop is the last entry
   whose hour has arrived; before the first, the last entry of the day still
   applies (they were somewhere overnight). */
function scheduleStop(npc, hour) {
  const sched = npc.def.schedule || [];
  if (!sched.length) return npc.def.home;
  let stop = sched[sched.length - 1][1];
  for (const [h, place] of sched) {
    if (hour >= h) stop = place;
  }
  return stop;
}

/* The nearest walkable tile to one that might be solid -- the stall and the
   well are objects you stand *next* to, not on. Mirrors worldgen._walkable_near. */
function walkableNear(t) {
  if (!tileBlocked(t[0], t[1])) return t;
  for (let r = 1; r <= 4; r++) {
    for (let dy = -r; dy <= r; dy++) {
      for (let dx = -r; dx <= r; dx++) {
        if (Math.max(Math.abs(dx), Math.abs(dy)) !== r) continue;
        if (!tileBlocked(t[0] + dx, t[1] + dy)) return [t[0] + dx, t[1] + dy];
      }
    }
  }
  return t;
}

/* A place name resolves to a walkable tile: an explicit [x, y], a building's
   door, a region's centre, or one of the named landmarks. */
function resolvePlace(place, npc) {
  const r = S.world.regions;
  let t;
  if (Array.isArray(place)) t = place.slice();
  else {
    const building = (r.buildings || []).find((b) => b.id === place);
    if (building) t = building.door.slice();
    else if (place === "well" && npc && npc.well) t = npc.well.slice();
    else if (place === "stall" && r.stall) t = r.stall.slice();
    else if (place === "cave_mouth" && r.cave_mouth) t = r.cave_mouth.slice();
    else if (r[place + "_centre"]) t = r[place + "_centre"].slice();
    else if (Array.isArray(r[place])) t = r[place].slice();
    else if (r[place] && "w" in r[place]) {
      t = [r[place].x + (r[place].w >> 1), r[place].y + (r[place].h >> 1)];
    } else t = [Math.floor(npc.x / TILE), Math.floor(npc.y / TILE)];
  }
  return walkableNear(t);
}

function npcTarget(npc) {
  return scheduleStop(npc, S.clock.minutes / 60);
}

function stepNpcs(dt) {
  if (!S.npcs.length) return;
  const speed = S.player.speed * 0.5 * dt;
  for (const npc of S.npcs) {
    const stop = npcTarget(npc);
    const stopKey = JSON.stringify(stop);
    if (stopKey !== npc.targetKey) {
      npc.targetKey = stopKey;
      const from = [Math.floor(npc.x / TILE), Math.floor(npc.y / TILE)];
      const goal = resolvePlace(stop, npc);
      npc.path = bfsPath(from, goal) || [];
      npc.pathI = 0;
      npc.goalTile = goal;
    }

    npc.moving = false;
    if (npc.pathI < npc.path.length) {
      const [tx, ty] = npc.path[npc.pathI];
      const gx = (tx + 0.5) * TILE, gy = (ty + 0.5) * TILE;
      const dx = gx - npc.x, dy = gy - npc.y;
      const dist = Math.hypot(dx, dy) || 1;
      if (dist <= speed) { npc.x = gx; npc.y = gy; npc.pathI += 1; }
      else {
        npc.x += (dx / dist) * speed;
        npc.y += (dy / dist) * speed;
        npc.moving = true;
        npc.dir = Math.abs(dx) > Math.abs(dy)
          ? (dx > 0 ? "right" : "left")
          : (dy > 0 ? "down" : "up");
      }
    }

    /* Home and arrived: they have gone inside. Shown at the door the rest of
       the day. NPC interiors are not walked -- this is the whole of "they went
       home". */
    const arrived = npc.pathI >= npc.path.length;
    npc.hidden = arrived && stop === npc.def.home;
  }
}

function nearestNpc(px, py, range) {
  if (S.inWilds || S.inInterior) return null;
  let found = null, best = range;
  for (const npc of S.npcs) {
    if (npc.hidden) continue;
    const d = Math.hypot(px - npc.x / TILE, py - npc.y / TILE);
    if (d <= best) { best = d; found = npc; }
  }
  return found;
}

function talkTo(npc) {
  /* Face the player. */
  const dx = S.player.x - npc.x, dy = S.player.y - npc.y;
  npc.dir = Math.abs(dx) > Math.abs(dy)
    ? (dx > 0 ? "right" : "left")
    : (dy > 0 ? "down" : "up");
  if (npc.def.shop) { Sound.play("select"); shopScreen(); return null; }
  const lines = npc.def.lines || [];
  const line = lines.length ? lines[npc.lineI % lines.length] : "…";
  npc.lineI += 1;
  Sound.play("select");
  toast(`${npc.def.label}: “${line}”`, 3800);
  return line;
}

/* A shortest tile path over walkable ground, or null. The engine-side twin of
   worldgen.bfs_path -- NPCs recompute it only when their schedule stop
   changes, a few times an in-game day, so a plain breadth-first walk is
   plenty. */
function tileBlocked(tx, ty) {
  if (tx < 0 || ty < 0 || tx >= S.world.width || ty >= S.world.height) return true;
  /* The same pixel test the player's collision uses, sampled at the tile
     centre. Testing "is a solid object bucketed on this tile" instead was too
     coarse -- a house's index bucket spills onto its own doorstep even though
     the ellipse does not, so every route to a door read as blocked. */
  return blockedAtPixel((tx + 0.5) * TILE, (ty + 0.5) * TILE);
}

/* ---------------------------------------------------------- crafting */
/* Recipes are content, made at the workbench or the hearth in your house.
   inputs is {item: qty}; output is one item. A recipe shows only at its
   station. This is the first thing to spend materials on that is not the shop
   -- raw drops are worth little, the goods you make from them are worth more. */

function craftable(station) {
  return all("recipes").filter((r) => {
    if ((r.station || "workbench") !== station) return false;
    // A tool-upgrade recipe shows only while the tool is exactly one tier
    // below what it grants -- so you climb the ladder a rung at a time and a
    // done upgrade drops off the list.
    if (r.upgrades) return (S.toolTier[r.upgrades] || 0) === (r.tier || 1) - 1;
    return true;
  });
}

function canCraft(recipe) {
  return Object.entries(recipe.inputs || {}).every(
    ([id, qty]) => (S.inv[id] || 0) >= qty
  );
}

function craftRecipe(id) {
  const recipe = lookup("recipes", id);
  if (!recipe || !canCraft(recipe)) { refuse("you are missing something"); return null; }
  if (recipe.upgrades && (S.toolTier[recipe.upgrades] || 0) !== (recipe.tier || 1) - 1) {
    refuse("that tool is not ready for this"); return null;
  }
  for (const [item, qty] of Object.entries(recipe.inputs || {})) take(item, qty);
  Sound.play("buy");
  if (recipe.upgrades) {
    S.toolTier[recipe.upgrades] = recipe.tier || 1;
    const tool = lookup("tools", recipe.upgrades);
    toast(`${tool ? tool.label : recipe.upgrades} upgraded`);
    return recipe.upgrades;
  }
  give(recipe.output, recipe.output_qty || 1);
  const made = lookup("items", recipe.output);
  toast(`made ${recipe.output_qty || 1} ${made ? made.label : recipe.output}`);
  return recipe.output;
}

/* How far a tool reaches, in tiles out from the tile you are facing. Base 0
   (a single tile); each crafted tier adds one, so tier 1 is a 3x3. */
function toolRadius(toolId) {
  return S.toolTier[toolId] || 0;
}

/* Run a farming verb over the square the tool covers. A problem is reported
   only if the centre tile failed -- an upgraded hoe near a fence should not
   nag about the edge tiles it could not reach. */
function applyToolArea(verb, cx, cy, radius) {
  let worked = false;
  let centre = null;
  for (let dy = -radius; dy <= radius; dy++) {
    for (let dx = -radius; dx <= radius; dx++) {
      const problem = verb(cx + dx, cy + dy);
      if (dx === 0 && dy === 0) centre = problem;
      if (!problem) worked = true;
    }
  }
  return worked ? null : centre;
}

/* --------------------------------------------------------- the chest */
/* The storage chest in your house. The first interior state a save carries --
   the room itself is regenerated, but what is in the chest is written to the
   save like your pack and your gold. */

function deposit(id, qty) {
  const have = S.inv[id] || 0;
  const n = Math.min(qty || 1, have);
  if (n <= 0) return;
  take(id, n);
  S.storage[id] = (S.storage[id] || 0) + n;
}

function withdraw(id, qty) {
  const have = S.storage[id] || 0;
  const n = Math.min(qty || 1, have);
  if (n <= 0) return;
  S.storage[id] -= n;
  if (S.storage[id] <= 0) delete S.storage[id];
  give(id, n);
}

function bfsPath(start, goal) {
  const sx = start[0], sy = start[1], gx = goal[0], gy = goal[1];
  if (tileBlocked(sx, sy) || tileBlocked(gx, gy)) return null;
  const startKey = sx + "," + sy, goalKey = gx + "," + gy;
  const prev = new Map([[startKey, null]]);
  const queue = [[sx, sy]];
  let head = 0, guard = 0;
  while (head < queue.length && guard++ < 40000) {
    const [x, y] = queue[head++];
    if (x === gx && y === gy) {
      const path = [];
      let k = goalKey;
      while (k !== null) {
        const [px, py] = k.split(",").map(Number);
        path.push([px, py]);
        k = prev.get(k);
      }
      return path.reverse();
    }
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const nx = x + dx, ny = y + dy, nk = nx + "," + ny;
      if (!prev.has(nk) && !tileBlocked(nx, ny)) {
        prev.set(nk, x + "," + y);
        queue.push([nx, ny]);
      }
    }
  }
  return null;
}
