/* Emberfield — the world: loading a map, baking its ground, collision, saves.
 *
 * Split out of index.html in session 5. This file owns everything about a map
 * as a place: the offscreen ground bake the render loop blits from, the ellipse
 * collision the player and foes both test against, turning a server payload into
 * a running world, and the save file that describes it. It holds no per-frame
 * logic — render.js draws, play.js simulates — and no screens.
 *
 * Loaded as a classic script after the core state block in index.html, so `S`,
 * `TILE`, the small utilities and `ForgeArt` are already in scope.
 */
"use strict";

/* ------------------------------------------------------------ collision

   An object's collision shape is NOT its footprint. The footprint says how much
   room the sprite needs; the hit box says what part of it your boots can walk
   into. An oak is two tiles wide and three tall, but only its trunk stops you --
   session 1 blocked the whole footprint, so you collided with leaves two tiles
   above the ground and could never walk behind a tree.

   The shape is read as an ellipse rather than a rectangle, which is what makes
   a trunk feel round: you slide around its shoulder instead of catching on a
   square corner you cannot see. */
function hitEllipse(o) {
  const hit = o.hit || [o.w || 1, 1];
  const cx = (o.x + (o.w || 1) / 2) * TILE;
  const cy = (o.y + 1) * TILE - (hit[1] * TILE) / 2;
  return { cx, cy, rx: (hit[0] * TILE) / 2, ry: (hit[1] * TILE) / 2 };
}

function insideEllipse(e, px, py) {
  const dx = (px - e.cx) / e.rx, dy = (py - e.cy) / e.ry;
  return dx * dx + dy * dy <= 1;
}

/* Objects are bucketed by tile at load so a collision check looks at the few
   objects near your feet rather than all fifteen hundred of them. */
function buildObjectIndex() {
  S.objIndex = new Map();
  for (const o of S.world.objects) {
    if (!o.solid) continue;
    const e = hitEllipse(o);
    const x0 = Math.floor((e.cx - e.rx) / TILE), x1 = Math.floor((e.cx + e.rx) / TILE);
    const y0 = Math.floor((e.cy - e.ry) / TILE), y1 = Math.floor((e.cy + e.ry) / TILE);
    for (let ty = y0; ty <= y1; ty++) {
      for (let tx = x0; tx <= x1; tx++) {
        const k = key(tx, ty);
        if (!S.objIndex.has(k)) S.objIndex.set(k, []);
        S.objIndex.get(k).push(o);
      }
    }
  }
}

function blockedAtPixel(px, py) {
  const tx = Math.floor(px / TILE), ty = Math.floor(py / TILE);
  if (tx < 0 || ty < 0 || tx >= S.world.width || ty >= S.world.height) return true;
  if ((S.tilesMeta[S.world.tiles[ty][tx]] || {}).solid) return true;
  const near = S.objIndex.get(key(tx, ty));
  if (!near) return false;
  for (const o of near) if (insideEllipse(hitEllipse(o), px, py)) return true;
  return false;
}

/* Tested against the player's feet, not their centre: a character in this
   register stands on the tile under their boots, and colliding with their
   head makes doorways and tree gaps feel a tile too small. */
function canStand(px, py) {
  const half = 4;
  for (const dx of [-half, half - 1]) {
    if (blockedAtPixel(px + dx, py)) return false;
  }
  return true;
}

/* ------------------------------------------------------- the ground bake
   Tiles and the procedural nature layer are drawn once into a single canvas
   the size of the whole valley (1536x1152 at 16px tiles). The frame loop then
   blits one rectangle out of it. Doing it per-frame instead would mean a few
   thousand tiny fills every frame for the grass alone; doing it once means the
   render loop is a single drawImage, and it also guarantees the scatter never
   shimmers as the camera moves. Re-baked only when the palette changes. */
function bakeGround(paletteId) {
  if (S.ground.has(paletteId)) return S.ground.get(paletteId);
  const w = S.world.width, h = S.world.height;
  const canvas = document.createElement("canvas");
  canvas.width = w * TILE; canvas.height = h * TILE;
  const ctx = ForgeArt.crisp(canvas.getContext("2d"));
  const atlas = new ForgeArt.Atlas(S.library, paletteId);

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      atlas.draw(ctx, S.world.tiles[y][x], x * TILE, y * TILE, 0, 1);
    }
  }
  paintNature(ctx, atlas, w, h);
  S.ground.set(paletteId, canvas);
  if (S.ground.size > 3) S.ground.delete(S.ground.keys().next().value);
  return canvas;
}

/* Repaint one tile into every baked palette we are holding.

   Tilling and watering change the ground, and re-baking a 1536x1152 canvas for
   a single hoe stroke would stall the frame. Painting the one tile into each
   cached bake keeps the single-blit render loop intact and costs nothing. */
function repaintTile(x, y) {
  for (const [paletteId, canvas] of S.ground) {
    const ctx = ForgeArt.crisp(canvas.getContext("2d"));
    const atlas = new ForgeArt.Atlas(S.library, paletteId);
    ctx.clearRect(x * TILE, y * TILE, TILE, TILE);
    atlas.draw(ctx, S.world.tiles[y][x], x * TILE, y * TILE, 0, 1);
    paintNatureTile(ctx, atlas, x, y);
  }
}

function setTile(x, y, name) {
  S.world.tiles[y][x] = name;
  S.tileEdits[key(x, y)] = name;
  repaintTile(x, y);
}

/* The procedural half of the art. Grass blades, leaf litter and shore foam are
   scattered here rather than drawn into the tiles, so that the hand-authored
   tiles stay clean and editable while the ground still breaks up into
   something organic. Colours come from the palette's semantic roles, which is
   what keeps the scatter in step with a season swap instead of hardcoding
   greens. */
function paintNature(ctx, atlas, w, h) {
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) paintNatureTile(ctx, atlas, x, y);
  }
}

function paintNatureTile(ctx, atlas, x, y) {
  const bladeDark = atlas.role("grass_dark", "#3f6b34");
  const bladeHi = atlas.role("grass_hi", "#74b258");
  const leaf = atlas.role("leaf_dark", "#2f5c2a");
  const foam = atlas.role("foam", "#cfe9f2");
  const sandDark = atlas.role("sand_dark", "#c2a674");

  const kind = tileKind(S.world.tiles[y][x]);
  const px = x * TILE, py = y * TILE;
  const r = hash2(x, y);

  if (kind === "grass") {
    const blades = 2 + Math.floor(r * 4);
    for (let i = 0; i < blades; i++) {
      const rx = hash2(x * 7 + i, y * 13);
      const ry = hash2(x * 3, y * 11 + i);
      const bx = px + Math.floor(rx * TILE);
      const by = py + Math.floor(ry * TILE);
      ctx.fillStyle = rx > 0.72 ? bladeHi : bladeDark;
      ctx.fillRect(bx, by, 1, 1 + (ry > 0.6 ? 1 : 0));
    }
    if (r > 0.955) {  // occasional leaf litter
      ctx.fillStyle = leaf;
      ctx.fillRect(px + 4 + Math.floor(r * 6), py + 6, 2, 1);
    }
  } else if (kind === "rock") {
    /* The same trick the grass gets: a per-tile scatter in palette colours, so
       a wall of forty tiles has grain rather than a repeating stamp. Stable
       against the position hash, because the ground is baked once. */
    const dark = atlas.role("tilled_dark", "#33241a");
    const light = atlas.role("stone_hi", "#b3b3bc");
    for (let i = 0; i < 5; i++) {
      const rx = hash2(x * 11 + i, y * 19);
      const ry = hash2(x * 5, y * 23 + i);
      ctx.fillStyle = rx > 0.82 ? light : dark;
      ctx.fillRect(px + Math.floor(rx * TILE), py + Math.floor(ry * TILE), 1, 1 + (ry > 0.7 ? 1 : 0));
    }
  } else if (kind === "sand") {
    for (let i = 0; i < 3; i++) {
      const rx = hash2(x * 5 + i, y * 17);
      ctx.fillStyle = sandDark;
      ctx.fillRect(px + Math.floor(rx * TILE), py + Math.floor(hash2(x, y + i) * TILE), 1, 1);
    }
  }

  /* Foam where water meets anything walkable: the single cheapest thing
     that makes a coastline read as a coastline. */
  if (kind === "water") {
    const up = y > 0 ? tileKind(S.world.tiles[y - 1][x]) : "water";
    if (up !== "water") {
      ctx.fillStyle = foam;
      for (let i = 0; i < TILE; i += 2) {
        if (hash2(x * TILE + i, y) > 0.35) ctx.fillRect(px + i, py, 2, 1);
      }
    }
  }
}

/* ------------------------------------------------------------ the world */
/* A new valley starts on the first morning, whatever the last one reached.
   The clock used to carry over: Save & leave on day 40 of an autumn, then
   Begin, and the new valley was already on day 40, in autumn, at that hour.
   The season is the one picked in Settings before Begin, otherwise spring. */
function freshClock() {
  return { day: 1, minutes: 6 * 60, season: S.startSeason || "spring" };
}

async function startWorld(data, restore) {
  S.world = data.world;
  S.world.tiles = S.world.tiles.map((row) => row.split("\t"));
  S.tilesMeta = data.tiles_meta;
  S.deathRule = data.death_rule;
  S.name = data.name;

  /* Ground you have worked is replayed onto the freshly generated valley. The
     world comes back from its seed; what you did to it comes back from here. */
  S.tileEdits = (restore && restore.tileEdits) || {};
  for (const [k, name] of Object.entries(S.tileEdits)) {
    const [x, y] = k.split(",").map(Number);
    if (x >= 0 && y >= 0 && x < S.world.width && y < S.world.height) S.world.tiles[y][x] = name;
  }

  buildObjectIndex();

  if (restore) {
    S.player.x = restore.player.x; S.player.y = restore.player.y;
    S.player.hp = restore.player.hp; S.player.maxHp = restore.player.maxHp;
    S.clock = restore.clock;
    S.crops = restore.crops || {};
    S.inv = restore.inv || {};
    S.storage = restore.storage || {};
    S.toolTier = restore.toolTier || {};
    S.hotbar = restore.hotbar || [];
    S.gold = restore.gold || 0;
    S.tutStep = restore.tutStep != null ? restore.tutStep : TUTORIAL.length;
  } else {
    S.player.x = S.world.spawn[0] * TILE + TILE / 2;
    S.player.y = S.world.spawn[1] * TILE + TILE / 2;
    S.player.hp = S.player.maxHp = 6;
    S.crops = {}; S.storage = {}; S.toolTier = {}; S.gold = 0; S.tutStep = 0;
    startingKit();
  }
  rebuildHotbar();

  S.foes = []; S.shots = [];
  S.inWilds = false; S.inInterior = false; S.valley = null; S.parked = null;
  buildNpcs();
  S.ground.clear();
  applyPalette();
  hideVeil();
  S.running = true;
  S.dead = false; S.sleeping = false;
  tutorial();
  kickLoop();
}

/* What you start with. Read from the content store rather than hardcoded, so
   the day a tool is renamed this does not silently hand you nothing. */
function startingKit() {
  S.inv = {};
  for (const tool of all("tools")) S.inv[tool.id] = 1;
  for (const weapon of all("weapons")) S.inv[weapon.id] = 1;
  /* Seeds you can actually plant today. Handing out a summer crop on the first
     morning of spring means the tutorial tells you to plant something the
     ground will refuse. */
  const sowable = all("crops")
    .filter((crop) => crop.seasons.includes(S.clock.season))
    .map((crop) => crop.seed_item)
    .filter(Boolean);
  const fallback = all("crops").map((crop) => crop.seed_item).filter(Boolean);
  const picks = sowable.length ? sowable : fallback;
  if (picks[0]) S.inv[picks[0]] = 12;
  if (picks[1]) S.inv[picks[1]] = 6;
}

/* The hotbar is derived, never stored as truth: tools and weapons you own,
   then seeds you are carrying. A new tool in the content store appears here
   without a line of code. */
function rebuildHotbar() {
  const bar = [];
  for (const tool of all("tools")) if (S.inv[tool.id]) bar.push({ kind: "tools", id: tool.id });
  for (const weapon of all("weapons")) if (S.inv[weapon.id]) bar.push({ kind: "weapons", id: weapon.id });
  for (const item of all("items")) {
    if (item.kind === "seed" && S.inv[item.id] > 0) bar.push({ kind: "items", id: item.id });
  }
  S.hotbar = bar.slice(0, 9);
  if (S.slot >= S.hotbar.length) S.slot = 0;
  drawHotbar();
}

function held() { return S.hotbar[S.slot] || null; }

function applyPalette() {
  const night = isNight();
  /* Indoors is always lit -- a house has a hearth and a lamp, so it stays on
     the season's day palette whatever the hour outside. Underground always uses
     the night palette: a cavern lit like a spring afternoon reads as a grey
     field, and the whole point of going down there is that it is somewhere
     else. */
  if (S.inInterior) {
    S.palette = SEASON_PALETTE[S.clock.season] || "emberfield-spring";
  } else if (night || S.inWilds) {
    S.palette = "emberfield-night";
  } else {
    S.palette = SEASON_PALETTE[S.clock.season] || "emberfield-spring";
  }
  if (!S.library.palettes[S.palette]) S.palette = "emberfield-spring";
  S.atlas = new ForgeArt.Atlas(S.library, S.palette);
  bakeGround(S.palette);
}

/* Swap in a different map without touching the player, the clock or anything
   you are carrying. Used for the wilds; startWorld() is for beginning a save. */
function swapWorld(data) {
  S.world = data.world;
  S.world.tiles = S.world.tiles.map((row) => row.split("\t"));
  S.tilesMeta = data.tiles_meta;
  buildObjectIndex();
  S.player.x = S.world.spawn[0] * TILE + TILE / 2;
  S.player.y = S.world.spawn[1] * TILE + TILE / 2;
  S.foes = []; S.shots = [];
  applyPalette();
}

/* The valley, wherever you happen to be standing.

   S.world is whatever map is on screen -- the valley, a cavern, or the room
   inside a house. Anything that means "the valley" specifically has to ask for
   it, because the valley is parked, not discarded, while you are elsewhere.

   Session 5 moved the bed indoors and two things quietly started answering with
   the wrong map: the save slot was named after the room's seed, and drying the
   field wrote valley tile coordinates into a fifteen-by-eleven room. The second
   threw inside sleep()'s timeout and left the screen black on a fade that never
   finished -- sleeping is the core loop, so this is the most important function
   in the file. */
function valleyWorld() {
  if (S.inWilds && S.valley) return S.valley.world;
  if (S.inInterior && S.parked) return S.parked.world;
  return S.world;
}

/* The baked ground canvases for the valley, likewise -- the live cache while
   you are outdoors, the parked one while you are not. */
function valleyGround() {
  if (S.inWilds && S.valley) return S.valley.ground;
  if (S.inInterior && S.parked) return S.parked.ground;
  return S.ground;
}

/* ------------------------------------------------------------ save/load */
/* One slot per valley, named for its seed, written when you sleep and when you
   leave through the menu. The world is not stored -- only its seed, which is
   why the generator being deterministic matters more than it looks. */
function saveSlot() { return "valley-" + valleyWorld().seed; }

function savePayload() {
  /* A save always describes the valley, never the cavern or the room you happen
     to be standing in. The wilds regenerate from the day and the hour and a
     house interior regenerates from its building id, so there is nothing about
     either worth storing -- and a save that dropped you back into a cavern that
     no longer exists, or a room with no way recorded out, would be worse than
     useless. */
  const parked = S.inWilds ? S.valley : (S.inInterior ? S.parked : null);
  const world = parked ? parked.world : S.world;
  const at = parked ? parked.player : S.player;
  return {
    name: S.name, seed: world.seed, day: S.clock.day,
    death_rule: S.deathRule,
    world: { seed: world.seed },
    player: { x: at.x, y: at.y, hp: S.player.hp, maxHp: S.player.maxHp },
    clock: S.clock, crops: S.crops, tileEdits: S.tileEdits,
    inv: S.inv, storage: S.storage, toolTier: S.toolTier,
    hotbar: S.hotbar, gold: S.gold, tutStep: S.tutStep,
  };
}

/* Resolves true once the save is on disk. A failure is always said out loud,
   even for a quiet save, because a save you believe happened and did not is
   the worst kind of loss. */
async function autosave(quiet) {
  if (!S.world) return false;
  try {
    await api(`/api/saves/${saveSlot()}`, { json: savePayload() });
    if (!quiet) toast("saved");
    return true;
  } catch (e) {
    toast("could not save: " + e.message, 4000);
    return false;
  }
}

async function continueSave(slot) {
  if (S.starting) return;   // a double click must not grow the valley twice
  S.starting = true;
  try {
    const save = await api(`/api/saves/${encodeURIComponent(slot)}`);
    if (!save || !save.world || save.world.seed == null) throw new Error("that save is damaged");
    const data = await api("/api/world/new", {
      json: { seed: save.world.seed, death_rule: save.death_rule, name: save.name },
    });
    await startWorld(data, save);
  } catch (e) {
    toast("could not open that valley: " + e.message, 4000);
  } finally { S.starting = false; }
}
