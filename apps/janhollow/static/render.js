/* Janhollow — drawing a deck at 32 pixels a tile.
 *
 * Everything here is per-frame drawing and nothing here changes state. The
 * backend owns the simulation; this turns one snapshot of it into pixels.
 *
 * Three things make the deck read as a place rather than a grid:
 *
 * 1. **Autotiled walls.** A wall picks one of sixteen variants from which of
 *    its four sides have another wall beside them, so a corner is drawn as a
 *    corner and an edge facing a room gets a lit lip. No file says where a
 *    corner is; it falls out of the map.
 * 2. **Two atlases.** Tiles are baked against the janhollow palette and the
 *    crew against the crewroom one, so the deck can be re-skinned -- night
 *    shift, red alert -- without touching a character. Sprites are asked for by
 *    their qualified "pack/name", because the 32px packs deliberately reuse the
 *    16px names.
 * 3. **Light pools.** The deck is dark, and lamps, consoles, viewports, doors
 *    and the lift cut holes in that darkness. It is one composited canvas per
 *    deck, rebuilt only when the view changes.
 *
 * `ForgeArt` and `S` are in scope; game.js loads this first.
 */
"use strict";

/* What the backend's one-character-per-tile rows mean. */
const HULL = " ", FLOOR = ".", WALL = "#", DOOR = "+", LIFT = "L";

/* Props that give off light, and how far it reaches in tiles. Adding a lamp to
   a room is a data edit, and it lights the room without any further wiring. */
/* The colour a light adds back. Cold for screens and space, warm for lamps --
   a station lit entirely in one colour looks like a menu. */
const WARM = {
  lamp: "rgba(90,62,22,0.55)",
  coffee_machine: "rgba(80,56,20,0.42)",
  reactor: "rgba(20,70,64,0.5)",
  console: "rgba(18,52,66,0.42)",
  bridge_display: "rgba(20,58,74,0.46)",
  server_rack: "rgba(16,46,60,0.36)",
  star_window: "rgba(26,44,70,0.4)",
  aquarium: "rgba(18,54,70,0.44)",
  window_city: "rgba(28,46,72,0.4)",
  window_night: "rgba(20,40,66,0.36)",
};

const LIGHTS = {
  lamp: 3.6,
  console: 2.6,
  bridge_display: 3.4,
  server_rack: 2.2,
  reactor: 5.0,
  coffee_machine: 2.0,
  star_window: 3.8,
  aquarium: 2.8,
  window_city: 3.4,
  window_night: 3.0,
};

function tileSize() {
  const pack = (S.library && S.library.packs || {})["janhollow-deck"];
  return (pack && pack.tile) || 32;
}

/* Stars behind the hull, deterministic per deck so a deck keeps its own sky. */
function starfield(deckId, w, h) {
  let seed = 0;
  for (let i = 0; i < deckId.length; i++) seed = (seed * 31 + deckId.charCodeAt(i)) >>> 0;
  const stars = [];
  for (let i = 0; i < 140; i++) {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    const x = seed % w;
    seed = (seed * 1664525 + 1013904223) >>> 0;
    const y = seed % h;
    seed = (seed * 1664525 + 1013904223) >>> 0;
    stars.push({ x, y, r: (seed % 3) * 0.5 + 0.5, a: ((seed >> 4) % 60) / 100 + 0.2 });
  }
  return stars;
}

/* Which of the four sides of a wall have another wall next to them. Hull counts
   as wall: the outside of the station should not get an indoor lit lip. */
function wallMask(deck, x, y) {
  const solid = (tx, ty) => {
    const row = deck.rows[ty];
    if (row === undefined) return true;
    const ch = row[tx];
    return ch === undefined || ch === WALL || ch === HULL;
  };
  return (
    (solid(x, y - 1) ? 1 : 0) |
    (solid(x + 1, y) ? 2 : 0) |
    (solid(x, y + 1) ? 4 : 0) |
    (solid(x - 1, y) ? 8 : 0)
  );
}

function tileSprite(deck, ch, x, y) {
  if (ch === WALL) return "janhollow-deck/wall_" + wallMask(deck, x, y);
  if (ch === DOOR) return "janhollow-deck/door";
  if (ch === LIFT) return "janhollow-deck/lift";
  if (ch !== FLOOR) return null;
  const room = S.roomAt(deck.id, x, y);
  if (room) {
    const floor = room.floor || deck.floor || "floor_plate";
    /* One plate repeated across a room reads as wallpaper. Every seventh tile,
       picked from its own coordinates so it never changes between frames, gets
       the worn variant instead. */
    if (floor === "floor_plate" && (x * 7 + y * 13) % 7 === 0) {
      return "janhollow-deck/floor_plate_worn";
    }
    return "janhollow-deck/" + floor;
  }
  /* Corridors get a lit strip down the middle of the run and grating either
     side of it, which is what makes a corridor look like a corridor. */
  const centre = deck.rows[y][x - 1] === FLOOR && deck.rows[y][x + 1] === FLOOR;
  const above = (deck.rows[y - 1] || "")[x];
  const below = (deck.rows[y + 1] || "")[x];
  const horizontal = centre && above !== FLOOR && below === FLOOR;
  return "janhollow-deck/" + (horizontal ? "floor_strip" : "floor_grate");
}

function view(deck, canvas) {
  const tile = S.tile;
  const fit = Math.max(
    0.5,
    Math.min(canvas.width / (deck.width * tile), canvas.height / (deck.height * tile))
  );
  const player = S.player;
  const zoom = S.zoom || 1;
  /* Watching, you see the whole deck. Playing, the camera comes in and follows
     you -- the owner chose "zoom in and follow you" over keeping the wide view.
     The two are the same function so that stepping in and stepping out is a
     change of numbers rather than a change of code path. `S.zoom` scales both,
     from the wheel or the plus and minus keys. */
  if (!player || !player.aboard || player.deck !== deck.id) {
    const scale = fit * zoom;
    const wide = deck.width * tile * scale;
    const tall = deck.height * tile * scale;
    /* Zoomed past fit, centre on the middle of the deck and clamp to its edges
       rather than letting it drift off screen. */
    const unit = tile * scale;
    const ox = JanView.axis({ size: wide, view: canvas.width, cam: S.cameraX, unit });
    /* While finding someone, centre below the play bar so they are not under
       it (S.findPad, set in game.js); zero otherwise. */
    const oy = JanView.axis({ size: tall, view: canvas.height, cam: S.cameraY, unit, pad: S.findPad || 0 });
    return { scale, ox: Math.round(ox), oy: Math.round(oy) };
  }
  const scale = Math.max(fit, Math.min(4.5, fit * 2.4 * zoom));
  const wide = deck.width * tile * scale;
  const tall = deck.height * tile * scale;
  /* Centre on you, then stop at the edges so the camera never shows the void
     past the hull. A deck smaller than the window is centred instead. */
  const unit = tile * scale;
  const ox = JanView.axis({ size: wide, view: canvas.width, cam: S.cameraX, unit });
  const oy = JanView.axis({ size: tall, view: canvas.height, cam: S.cameraY, unit, pad: S.findPad || 0 });
  return { scale, ox: Math.round(ox), oy: Math.round(oy) };
}

/* --- light ---------------------------------------------------------------- */

/* One dark overlay per deck with the lights punched out of it. Rebuilt only
   when the deck or the view changes: it is a few hundred gradient fills, which
   is far too much to do sixty times a second and nothing at all once.
   It covers the bake window `win` (JanView.bakeWindow, in deck pixels) rather
   than the screen, so a moving camera reuses it until it leaves the window
. The caller draws it at (v.ox + win.x, v.oy + win.y). The
   key holds the props, because the camera no longer rebakes it every frame. */
function lightLayer(deck, canvas, v, win) {
  let propsKey = "";
  for (const prop of deck.props) propsKey += `${prop.x},${prop.y},${prop.sprite};`;
  const key =
    `${deck.id}:${canvas.width}x${canvas.height}:` +
    `${v.scale}:${win.x}:${win.y}:${win.w}x${win.h}:${propsKey}`;
  if (S.lightKey === key && S.lightCanvas) return S.lightCanvas;

  /* Reuse the last canvas when the size matches: a fresh full-size canvas per
     rebake was garbage the collector had to chase. */
  let layer = S.lightCanvas;
  if (!layer || layer.width !== win.w || layer.height !== win.h) {
    layer = document.createElement("canvas");
    layer.width = win.w;
    layer.height = win.h;
  }
  const ctx = layer.getContext("2d");
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = "source-over";
  ctx.clearRect(0, 0, layer.width, layer.height);
  const tile = S.tile * v.scale;
  /* Where the deck's corner sits inside the layer. */
  const bx = -win.x, by = -win.y;

  /* Tuned by eye against a screenshot: at 0.62 the deck was so dark that the
     new 32px texture was invisible, which defeated the point of drawing it. */
  /* Lifted from 0.38: with the atmosphere module laying contact shadow at every
     wall base, depth no longer has to come from darkness, and its author's
     honest critique was that everything outside a light pool sat at near-black
     where Sheepy keeps readable mid-tones. */
  ctx.fillStyle = "rgba(6,10,20,0.26)";
  ctx.fillRect(0, 0, layer.width, layer.height);
  ctx.globalCompositeOperation = "destination-out";

  const pool = (tx, ty, tiles, strength) => {
    const cx = bx + (tx + 0.5) * tile;
    const cy = by + (ty + 0.5) * tile;
    const r = tiles * tile;
    const gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
    gradient.addColorStop(0, `rgba(0,0,0,${strength})`);
    gradient.addColorStop(0.55, `rgba(0,0,0,${strength * 0.45})`);
    gradient.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = gradient;
    ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
  };

  for (const prop of deck.props) {
    const reach = LIGHTS[prop.sprite];
    if (reach) pool(prop.x, prop.y, reach, 0.95);
  }
  for (let y = 0; y < deck.height; y++) {
    for (let x = 0; x < deck.width; x++) {
      const ch = deck.rows[y][x];
      if (ch === DOOR) pool(x, y, 1.8, 0.75);
      else if (ch === LIFT) pool(x, y, 2.6, 0.85);
    }
  }
  /* A little ambient over every walkable tile, so an unlit corner is dim
     rather than black. */
  ctx.fillStyle = "rgba(0,0,0,0.34)";
  for (let y = 0; y < deck.height; y++) {
    for (let x = 0; x < deck.width; x++) {
      if (deck.rows[y][x] === HULL) continue;
      ctx.fillRect(bx + x * tile, by + y * tile, tile + 1, tile + 1);
    }
  }

  /* Then a warm glow added back on top of the lamps themselves. Taking darkness
     away makes a room visible; adding light back is what makes a lamp look lit
     rather than look like a hole in the shadow. */
  ctx.globalCompositeOperation = "lighter";
  const glow = (tx, ty, tiles, colour) => {
    const cx = bx + (tx + 0.5) * tile;
    const cy = by + (ty + 0.5) * tile;
    const r = tiles * tile;
    const gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
    gradient.addColorStop(0, colour);
    gradient.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = gradient;
    ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
  };
  for (const prop of deck.props) {
    const reach = LIGHTS[prop.sprite];
    if (reach) glow(prop.x, prop.y, reach * 0.8, WARM[prop.sprite] || "rgba(70,52,20,0.5)");
  }
  for (let y = 0; y < deck.height; y++) {
    for (let x = 0; x < deck.width; x++) {
      const ch = deck.rows[y][x];
      if (ch === LIFT) glow(x, y, 1.1, "rgba(14,48,46,0.3)");
      else if (ch === DOOR) glow(x, y, 1.0, "rgba(12,44,42,0.32)");
    }
  }
  ctx.globalCompositeOperation = "source-over";

  S.lightKey = key;
  S.lightCanvas = layer;
  return layer;
}

/* --- the frame ------------------------------------------------------------ */

function drawDeck(ctx, deck, canvas, now) {
  const v = view(deck, canvas);
  const tile = S.tile;
  const k = v.scale;
  const px = (x) => v.ox + x * tile * k;
  const py = (y) => v.oy + y * tile * k;
  /* One bake window per frame, shared by lightLayer and the atmosphere bakes. */
  const win = (S.bakeWin = JanView.bakeWindow(S.bakeWin, {
    scope: `${deck.id}:${canvas.width}x${canvas.height}:${k}`,
    ox: v.ox, oy: v.oy, w: canvas.width, h: canvas.height, unit: tile * k,
  }));

  ctx.fillStyle = "#04060b";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (!S.stars[deck.id]) S.stars[deck.id] = starfield(deck.id, canvas.width, canvas.height);
  for (const star of S.stars[deck.id]) {
    ctx.globalAlpha = star.a;
    ctx.fillStyle = "#cfe6ff";
    ctx.fillRect(star.x, star.y, star.r, star.r);
  }
  ctx.globalAlpha = 1;

  for (let y = 0; y < deck.height; y++) {
    const row = deck.rows[y] || "";
    for (let x = 0; x < deck.width; x++) {
      const id = tileSprite(deck, row[x], x, y);
      if (id) S.tiles.draw(ctx, id, px(x), py(y), now, k);
    }
  }

  /* Props and crew share one pass sorted by their feet, so someone standing
     behind a console is drawn behind it. */
  const drawables = [];
  for (const prop of deck.props) {
    drawables.push({ y: prop.y + (prop.h || 1) - 1, kind: "prop", it: prop });
  }
  /* Things lying on the floor. Sorted a hair above their tile so anyone
     standing on the same row is drawn in front of them. */
  for (const thing of S.items || []) {
    if (thing.deck !== deck.id) continue;
    drawables.push({ y: thing.y - 0.05, kind: "item", it: thing });
  }
  for (const member of S.crew) {
    if (member.deck !== deck.id) continue;
    drawables.push({ y: member.drawY, kind: "crew", it: member });
  }
  if (S.player && S.player.aboard && S.player.deck === deck.id) {
    drawables.push({ y: S.player.drawY, kind: "crew", it: S.player });
  }
  drawables.sort((a, b) => a.y - b.y);

  /* Contact shadow goes down before anyone is drawn, so the crew stand IN it
     rather than on top of it. The module's author flagged the ordering; the
     first wiring had it over their heads. */
  if (window.Atmosphere) {
    try {
      Atmosphere.groundShadowPass(ctx, atmosphereScene(deck, v, now, win));
    } catch (err) {
      window.Atmosphere = null;
    }
  }

  const talking = [];
  for (const d of drawables) {
    if (d.kind === "prop") {
      /* Furniture stands ON its tile rather than hanging down from it. A
         bookshelf is two tiles tall and a star window is seven wide; drawing
         them from the top-left corner of one tile is what pushed them through
         walls and through each other. */
      const id = "janhollow-crew/" + d.it.sprite;
      const sprite = S.crewArt.get(id);
      const tall = sprite ? sprite.h : S.tile;
      S.crewArt.draw(ctx, id, px(d.it.x), py(d.it.y + (d.it.h || 1)) - tall * k, now, k);
      continue;
    }
    if (d.kind === "item") {
      const id = d.it.pack + "/" + d.it.sprite;
      const sprite = S.tiles.get(id);
      if (sprite) S.tiles.draw(ctx, id, px(d.it.x), py(d.it.y + 1) - sprite.h * k, now, k);
      continue;
    }
    drawCrew(ctx, d.it, px, py, k, now);
    if (d.it.saying) talking.push(d.it);
  }

  ctx.drawImage(lightLayer(deck, canvas, v, win), v.ox + win.x, v.oy + win.y);

  /* The atmosphere module (static/atmosphere.js) adds the parts that make the
     deck feel like a place rather than a plan: contact shadow at the foot of
     every wall, bloom around the lights, dust in the light, and a screen pass
     over the lot. Guarded because the page must still draw if that file is not
     there. */
  if (window.Atmosphere) {
    const scene = atmosphereScene(deck, v, now, win);
    try {
      Atmosphere.lightPass(ctx, scene);
      Atmosphere.dustPass(ctx, scene, Math.min(0.1, (now - (S.lastAtmos || now)) / 1000));
      Atmosphere.screenPass(ctx, scene);
    } catch (err) {
      /* One bad frame of weather must never take the station down. */
      window.Atmosphere = null;
      console.warn("atmosphere off:", err);
    }
    S.lastAtmos = now;
  }

  /* Labels, outlines and bubbles go over the light, because they are interface
     rather than scenery and must stay readable in a dark corridor. */
  drawLabels(ctx, deck, px, py, k);
  drawGlints(ctx, deck, px, py, k, now);
  const onDeck = S.crew.filter((m) => m.deck === deck.id);
  if (S.player && S.player.aboard && S.player.deck === deck.id) onDeck.push(S.player);
  for (const member of onDeck) {
    if (!member.saying && (S.showNames || S.selected === member.id)) {
      const at = anchor(member, px, py, k);
      label(ctx, member.label, at.cx, at.top - 2 * k, k);
    }
  }
  for (const member of talking) {
    const at = anchor(member, px, py, k);
    bubble(ctx, member.saying, at.cx, at.top - 2 * k, k);
  }
}

/* Two naming schemes live in the library: the crew have _walk_down/_up/_left/
   _right, while the helper set the player wears has a single _walk plus a
   _walk_up. Rather than teach one to look like the other, ask for the best
   name and fall back through the ones that might exist. */
/* What the atmosphere module needs to know about the deck on screen. Built
   fresh each frame because the camera moves; everything expensive inside the
   module is cached on the geometry, not rebuilt from this. */
function atmosphereScene(deck, v, now, win) {
  const lights = [];
  for (const prop of deck.props) {
    const reach = LIGHTS[prop.sprite];
    if (reach) {
      lights.push({
        x: prop.x, y: prop.y, reach,
        colour: WARM[prop.sprite] || "rgba(90,62,22,0.55)",
        flicker: prop.sprite === "reactor" ? 0.35 : 0.08,
      });
    }
  }
  for (let y = 0; y < deck.height; y++) {
    for (let x = 0; x < deck.width; x++) {
      const ch = deck.rows[y][x];
      if (ch === DOOR) lights.push({ x, y, reach: 1.4, colour: "rgba(14,50,48,0.5)", flicker: 0 });
      else if (ch === LIFT) lights.push({ x, y, reach: 2.0, colour: "rgba(16,60,56,0.5)", flicker: 0.12 });
    }
  }
  const actors = [];
  for (const member of S.crew) {
    if (member.deck === deck.id) actors.push({ x: member.drawX, y: member.drawY, h: 48 });
  }
  if (S.player && S.player.aboard && S.player.deck === deck.id) {
    actors.push({ x: S.player.drawX, y: S.player.drawY, h: 48 });
  }
  return {
    tile: S.tile, scale: v.scale, ox: v.ox, oy: v.oy,
    bake: win ? { x: win.x, y: win.y, w: win.w, h: win.h } : null,
    width: deck.width, height: deck.height, rows: deck.rows,
    lights, props: deck.props, actors,
    timeOfDay: S.minuteOfDay == null ? 0.5 : S.minuteOfDay / 1440,
    now,
  };
}

function crewSpriteId(member) {
  const base = "janhollow-crew/" + (member.sprite || "person1");
  const facing = member.facing || "down";
  const wanted = [];
  if (member.riding) wanted.push(base + "_back");
  if (member.moving) {
    wanted.push(base + "_walk_" + facing);
    if (facing === "up") wanted.push(base + "_walk_up");
    wanted.push(base + "_walk");
  }
  if (member.sitting) wanted.push(base + "_relax", base + "_type");
  if (member.saying) wanted.push(base + "_talk");
  wanted.push(base + "_idle", base + "_walk", "janhollow-crew/person1_idle");
  for (const id of wanted) {
    if (S.crewArt.has(id)) return id;
  }
  return base + "_idle";
}

function anchor(member, px, py, k) {
  const sprite =
    S.crewArt.get(crewSpriteId(member)) ||
    S.crewArt.get("janhollow-crew/" + (member.sprite || "person1") + "_idle");
  const h = sprite ? sprite.h : S.tile * 1.5;
  return {
    cx: px(member.drawX) + S.tile * k * 0.5,
    top: py(member.drawY) - (h - S.tile) * k,
  };
}

function drawCrew(ctx, member, px, py, k, now) {
  const id = crewSpriteId(member);
  const sprite = S.crewArt.get(id) || S.crewArt.get("janhollow-crew/person1_idle");
  const you = S.player && member.id === S.player.id;
  if (!sprite) return;
  const at = anchor(member, px, py, k);
  const x = px(member.drawX);

  ctx.globalAlpha = 0.3;
  ctx.fillStyle = "#000";
  ctx.beginPath();
  ctx.ellipse(
    x + S.tile * k * 0.5,
    py(member.drawY) + S.tile * k * 0.86,
    S.tile * k * 0.3,
    S.tile * k * 0.12,
    0, 0, Math.PI * 2
  );
  ctx.fill();
  ctx.globalAlpha = 1;

  /* What you have in your hands, at half size. Walking away from the camera
     your body hides it, so it is drawn first. */
  const inHands = you ? heldItem(member) : null;
  const handsAt = () => drawHeld(ctx, inHands, x, py(member.drawY), k, now);
  if (inHands && member.facing === "up") handsAt();
  S.crewArt.draw(ctx, S.crewArt.has(id) ? id : "janhollow-crew/person1_idle", x, at.top, now, k);
  if (inHands && member.facing !== "up") handsAt();

  if (you) {
    /* A soft ring under you. In a dark corridor full of crew it is the only
       quick way to find yourself. */
    ctx.globalAlpha = 0.5;
    ctx.strokeStyle = "#5bd6c4";
    ctx.lineWidth = Math.max(1, k * 0.9);
    ctx.beginPath();
    ctx.ellipse(
      x + S.tile * k * 0.5, py(member.drawY) + S.tile * k * 0.86,
      S.tile * k * 0.36, S.tile * k * 0.15, 0, 0, Math.PI * 2
    );
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
  if (S.selected === member.id) {
    ctx.strokeStyle = "#5bd6c4";
    ctx.lineWidth = Math.max(1, k);
    ctx.strokeRect(Math.round(x) - 1, Math.round(at.top) - 1, sprite.w * k + 2, sprite.h * k + 2);
  }
}

/* Things on the floor sit in the dark with everything else and are easy to
   walk past, so each gets a slow glint drawn over the light: a soft ring at
   its base and a small four-point sparkle, the way pickups read in any pixel
   game. It is interface, like the labels, not a light source. */
function drawGlints(ctx, deck, px, py, k, now) {
  for (const thing of S.items || []) {
    if (thing.deck !== deck.id) continue;
    const phase = (now / 900 + (thing.x * 7 + thing.y * 3) * 0.37) % (Math.PI * 2);
    const pulse = 0.5 + 0.5 * Math.sin(phase);
    const cx = px(thing.x) + S.tile * k * 0.5;
    const base = py(thing.y) + S.tile * k * 0.88;
    ctx.globalAlpha = 0.18 + 0.22 * pulse;
    ctx.strokeStyle = "#ffd98a";
    ctx.lineWidth = Math.max(1, k * 0.8);
    ctx.beginPath();
    ctx.ellipse(cx, base, S.tile * k * 0.34, S.tile * k * 0.12, 0, 0, Math.PI * 2);
    ctx.stroke();
    const sx = Math.round(px(thing.x) + S.tile * k * 0.8);
    const sy = Math.round(py(thing.y) + S.tile * k * 0.15);
    const arm = Math.max(2, Math.round(k * (2 + 2 * pulse)));
    const dot = Math.max(1, Math.round(k));
    ctx.globalAlpha = 0.35 + 0.6 * pulse;
    ctx.fillStyle = "#fff4d6";
    ctx.fillRect(sx - arm, sy, arm * 2 + dot, dot);
    ctx.fillRect(sx, sy - arm, dot, arm * 2 + dot);
  }
  ctx.globalAlpha = 1;
}

function heldItem(player) {
  const carrying = player.carrying || [];
  return carrying[player.held] || null;
}

function drawHeld(ctx, thing, x, footY, k, now) {
  const id = thing.pack + "/" + thing.sprite;
  const sprite = S.tiles.get(id);
  if (!sprite) return;
  const half = k * 0.5;
  S.tiles.draw(
    ctx, id,
    x + (S.tile * k - sprite.w * half) / 2,
    footY + S.tile * k * 0.62 - sprite.h * half,
    now, half
  );
}

function label(ctx, text, cx, cy, k) {
  /* Names and room labels are interface rather than scenery, so they stop
     growing once the camera comes in close. At the play zoom the old
     behaviour put a name across a third of the deck. */
  const size = Math.round(11 * Math.min(k, 1.3));
  ctx.font = `${size}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  const w = ctx.measureText(text).width + 10 * k;
  ctx.fillStyle = "rgba(6,12,20,0.8)";
  roundRect(ctx, cx - w / 2, cy - size * 1.35, w, size * 1.4, 4 * k);
  ctx.fill();
  ctx.fillStyle = "#e8f6ff";
  ctx.fillText(text, cx, cy - size * 0.32);
  ctx.textAlign = "left";
}

function bubble(ctx, text, cx, bottom, k) {
  const size = Math.round(11 * Math.min(k, 1.4));
  ctx.font = `${size}px system-ui, sans-serif`;
  const maxWidth = Math.min(230 * k, ctx.canvas.width * 0.4);
  const words = String(text).split(/\s+/);
  const lines = [];
  let line = "";
  for (const word of words) {
    const next = line ? line + " " + word : word;
    if (ctx.measureText(next).width > maxWidth && line) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);

  const pad = 6 * k;
  const lineHeight = size * 1.25;
  const width = Math.max(...lines.map((l) => ctx.measureText(l).width)) + pad * 2;
  const height = lines.length * lineHeight + pad * 2;
  let left = cx - width / 2;
  left = Math.max(4, Math.min(ctx.canvas.width - width - 4, left));
  const top = Math.max(4, bottom - height);

  ctx.fillStyle = "rgba(8,16,26,0.93)";
  ctx.strokeStyle = "rgba(91,214,196,0.6)";
  ctx.lineWidth = Math.max(1, k * 0.7);
  roundRect(ctx, left, top, width, height, 7 * k);
  ctx.fill();
  ctx.stroke();

  ctx.beginPath();
  ctx.moveTo(cx - 5 * k, top + height);
  ctx.lineTo(cx + 5 * k, top + height);
  ctx.lineTo(cx, top + height + 6 * k);
  ctx.closePath();
  ctx.fill();

  ctx.fillStyle = "#e9f7ff";
  ctx.textAlign = "left";
  lines.forEach((l, i) => ctx.fillText(l, left + pad, top + pad + lineHeight * (i + 0.8)));
}

function roundRect(ctx, x, y, w, h, r) {
  const radius = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + w, y, x + w, y + h, radius);
  ctx.arcTo(x + w, y + h, x, y + h, radius);
  ctx.arcTo(x, y + h, x, y, radius);
  ctx.arcTo(x, y, x + w, y, radius);
  ctx.closePath();
}

function drawLabels(ctx, deck, px, py, k) {
  const size = Math.round(9 * Math.min(k, 1.4));
  ctx.font = `${size}px system-ui, sans-serif`;
  for (const id in S.locations) {
    const loc = S.locations[id];
    if (loc.deck !== deck.id) continue;
    const x = px(loc.rect[0]) + 4 * k;
    const y = py(loc.rect[1]) + size * 1.6;
    const w = ctx.measureText(loc.label).width + 7 * k;
    ctx.fillStyle = "rgba(6,12,20,0.66)";
    ctx.fillRect(x - 3 * k, y - size * 1.15, w, size * 1.45);
    ctx.fillStyle = "rgba(150,225,240,0.92)";
    ctx.fillText(loc.label, x, y);
  }
}
