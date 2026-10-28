/* Emberfield — the renderer: one depth-sorted pass over a blitted ground bake.
 *
 * Split out of index.html in session 5. Everything here is per-frame drawing
 * and nothing here changes game state. The ground is a single drawImage out of
 * the offscreen bake world.js made; objects, crops, foes and the player share
 * one y-sorted pass so the player walks behind a canopy and in front of a
 * trunk; then the time-of-day wash, the aim outline, and (underground) the
 * torch pool go over the top.
 *
 * Loaded as a classic script after world.js. `S`, `TILE` and `ForgeArt` are in
 * scope; it calls into play.js (`facingTile`) only at frame time.
 */
"use strict";

function resize() {
  const c = $("#stage");
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  c.width = Math.floor(window.innerWidth * dpr);
  c.height = Math.floor(window.innerHeight * dpr);
  S.dpr = dpr;
}

/* Shadows that move with the sun.

   A soft ellipse on the ground under anything that stands on it -- pixel art at
   this scale has no lighting model, so without one every sprite looks pasted
   onto the grass rather than standing in it.

   The first version put the ellipse straight underneath and only varied its
   darkness by the hour, which is fine at noon and wrong at every other time of
   day. Now the sun actually crosses the sky: shadows fall long to the west at
   dawn, shorten and swing under their objects towards midday, then stretch out
   east through the afternoon until they are longer than the things casting
   them. It costs one cosine per frame and it is the single cheapest thing in
   the renderer that makes an hour of the day legible without reading the clock.

   Underground there is no sun, so shadows point away from your torch instead --
   which means they swing around an object as you walk past it. */
function sunLight() {
  const h = S.clock.minutes / 60;
  const DAWN = 5.5, DUSK = 20;
  const t = Math.max(0, Math.min(1, (h - DAWN) / (DUSK - DAWN)));
  // 1 with the sun overhead, 0 at the horizon.
  const height = Math.max(0.001, Math.sin(t * Math.PI));
  return {
    // -1 with the sun in the east (shadow west), +1 with it in the west.
    dir: (t - 0.5) * 2,
    height,
    // Long at the ends of the day, short in the middle. Capped so a dawn
    // shadow is dramatic rather than absurd.
    stretch: Math.min(3.4, 0.42 / Math.max(0.13, height)),
  };
}

function shadow(ctx, cx, cy, rx, ry, alpha, sourceX, sourceY) {
  let offX, offY, stretch;
  if (S.inWilds) {
    /* Cast away from the player's torch. Falls back to straight down when you
       are standing exactly on top of something. */
    const dx = cx - (sourceX != null ? sourceX : cx);
    const dy = cy - (sourceY != null ? sourceY : cy) + 0.001;
    const dist = Math.hypot(dx, dy) || 1;
    const reach = Math.min(2.0, 0.25 + dist / 60);
    offX = (dx / dist) * rx * reach;
    offY = (dy / dist) * ry * reach * 0.6;
    stretch = 1 + reach * 0.5;
  } else {
    const sun = sunLight();
    stretch = sun.stretch;
    /* Not negated. sun.dir is -1 with the sun in the east, and a shadow falls
       *away* from the sun -- so at dawn it must go west, which is negative x.
       The first version negated this and had every shadow pointing at the sun
       instead of away from it: mornings and evenings were exactly reversed. */
    offX = sun.dir * rx * stretch * 1.5;
    offY = ry * 0.25;
  }
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.fillStyle = "#000";
  ctx.beginPath();
  /* Rotated to lie along the direction it is cast, so a long shadow reads as a
     shadow rather than as a smear beside the object. */
  const angle = Math.atan2(offY, offX);
  ctx.ellipse(cx + offX, cy + offY, rx * stretch, ry, angle, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

/* Shadows fade with the sun as well as moving with it -- weak at dawn, hardest
   at midday, gone by night, with a trace of moonlight after dark. */
function shadowStrength() {
  if (!S.settings.shadows) return 0;
  if (S.inInterior) return 0;              // no cast light indoors worth a shadow
  if (S.inWilds) return 0.34;              // torchlight is a hard little light
  const h = S.clock.minutes / 60;
  if (h < 5 || h >= 21) return 0.09;
  const sun = sunLight();
  return 0.09 + 0.22 * sun.height;
}

function render(t) {
  const c = $("#stage");
  const ctx = ForgeArt.crisp(c.getContext("2d"));
  const z = S.zoom * S.dpr;
  const viewW = c.width / z, viewH = c.height / z;

  /* The camera is clamped to the map and rounded to whole pixels. Without the
     rounding, pixel art crawls and shears as you walk. A house interior is
     smaller than the viewport, so on that axis the map is centred rather than
     clamped to a corner. */
  const spanX = S.world.width * TILE - viewW;
  const spanY = S.world.height * TILE - viewH;
  S.cam.x = spanX < 0 ? spanX / 2 : Math.max(0, Math.min(spanX, S.player.x - viewW / 2));
  S.cam.y = spanY < 0 ? spanY / 2 : Math.max(0, Math.min(spanY, S.player.y - viewH / 2));
  const camX = Math.round(S.cam.x), camY = Math.round(S.cam.y);
  S.view = { camX, camY, viewW, viewH, z };

  ctx.setTransform(z, 0, 0, z, 0, 0);
  ctx.fillStyle = "#0d0b09";
  ctx.fillRect(0, 0, viewW, viewH);

  const ground = S.ground.get(S.palette);
  ctx.drawImage(ground, camX, camY, Math.ceil(viewW), Math.ceil(viewH),
                0, 0, Math.ceil(viewW), Math.ceil(viewH));

  /* Objects, crops, foes and the player share one depth-sorted pass, so the
     player walks behind a tree's canopy and in front of its trunk. */
  const drawables = [];
  const x0 = Math.floor(camX / TILE) - 2, x1 = Math.ceil((camX + viewW) / TILE) + 2;
  const y0 = Math.floor(camY / TILE) - 4, y1 = Math.ceil((camY + viewH) / TILE) + 4;
  for (const o of S.world.objects) {
    if (o.x < x0 || o.x > x1 || o.y < y0 || o.y > y1) continue;
    drawables.push({ sort: o.y, o });
  }
  for (const [k, crop] of Object.entries(S.crops)) {
    const [cx, cy] = k.split(",").map(Number);
    if (cx < x0 || cx > x1 || cy < y0 || cy > y1) continue;
    drawables.push({ sort: cy, crop, cx, cy });
  }
  for (const f of S.foes) drawables.push({ sort: Math.floor(f.y / TILE), foe: f });
  if (!S.inWilds && !S.inInterior) {
    for (const n of S.npcs) {
      if (n.hidden) continue;
      if (n.x / TILE < x0 || n.x / TILE > x1 || n.y / TILE < y0 || n.y / TILE > y1) continue;
      drawables.push({ sort: Math.floor(n.y / TILE), npc: n });
    }
  }
  drawables.push({ sort: Math.floor(S.player.y / TILE), player: true });
  drawables.sort((a, b) => a.sort - b.sort);

  const sh = shadowStrength();

  for (const d of drawables) {
    if (d.player) {
      const sprite = "player_" + S.player.dir;
      const s = S.atlas.get(sprite);
      // The player stands at the torch, so their own shadow has no direction
      // to be cast in -- it stays underneath them.
      if (sh) shadow(ctx, S.player.x - camX, S.player.y - camY + 2, 5, 2.2, sh,
                     S.player.x - camX, S.player.y - camY + 2 - 0.01);
      const time = S.player.moving ? t : 0;
      /* A hit flashes the sprite out for a few frames. Cheap, and it is the
         only feedback that reliably reads during a fight. */
      ctx.save();
      if (S.player.hurtT > 0 && Math.floor(t / 60) % 2 === 0) ctx.globalAlpha = 0.35;
      S.atlas.draw(ctx, sprite,
        S.player.x - camX - s.w / 2,
        S.player.y - camY - s.h + 4, time, 1);
      ctx.restore();
    } else if (d.foe) {
      const f = d.foe;
      const s = S.atlas.get(f.sprite);
      if (!s) continue;
      if (sh) shadow(ctx, f.x - camX, f.y - camY + 2, 5, 2.2, sh,
                     S.player.x - camX, S.player.y - camY);
      ctx.save();
      if (f.hurtT > 0) ctx.globalAlpha = 0.5;
      S.atlas.draw(ctx, f.sprite, f.x - camX - s.w / 2, f.y - camY - s.h + 4, t, 1);
      ctx.restore();
    } else if (d.npc) {
      const n = d.npc;
      const s = S.atlas.get(n.sprite + "_" + n.dir);
      if (!s) continue;
      if (sh) shadow(ctx, n.x - camX, n.y - camY + 2, 5, 2.2, sh,
                     S.player.x - camX, S.player.y - camY);
      S.atlas.draw(ctx, n.sprite + "_" + n.dir,
        n.x - camX - s.w / 2, n.y - camY - s.h + 4, n.moving ? t : 0, 1);
    } else if (d.crop) {
      const def = lookup("crops", d.crop.id);
      if (!def) continue;
      const stage = Math.min(d.crop.stage, def.stages.length - 1);
      const name = def.sprite + "_" + stage;
      const s = S.atlas.get(name);
      if (!s) continue;
      S.atlas.draw(ctx, name, d.cx * TILE - camX, (d.cy + 1) * TILE - camY - s.h, t, 1);
    } else {
      const o = d.o, s = S.atlas.get(o.sprite);
      if (!s) continue;
      /* An opened chest is dimmed rather than removed, so you can tell at a
         glance where you have already been -- the only navigational aid a
         cavern that regenerates every day is ever going to get. */
      if (o.opened) ctx.globalAlpha = 0.42;
      if (sh && o.solid && o.hit) {
        /* Sized from the sprite's footprint, not from the hit box. They are
           different things on purpose: the hit box is a narrow trunk you walk
           around, while the shadow is what the whole canopy casts. Drawing the
           shadow at trunk width made a full-grown oak look like it was
           floating over a pebble. */
        const rx = Math.max(3.5, (o.w || 1) * TILE * 0.38);
        shadow(ctx, (o.x + (o.w || 1) / 2) * TILE - camX,
               (o.y + 1) * TILE - camY - 1.5, rx, rx * 0.34, sh,
               S.player.x - camX, S.player.y - camY);
      }
      S.atlas.draw(ctx, o.sprite,
        o.x * TILE - camX + (o.w * TILE - s.w) / 2,
        (o.y + 1) * TILE - camY - s.h, t, 1);
      ctx.globalAlpha = 1;
    }
  }

  /* Shots last, above everything: an arrow passing behind a bush is a shot you
     think you missed. */
  for (const shot of S.shots) {
    const s = S.atlas.get(shot.sprite);
    if (!s) continue;
    ctx.save();
    ctx.translate(shot.x - camX, shot.y - camY);
    ctx.rotate(shot.angle);
    S.atlas.draw(ctx, shot.sprite, -s.w / 2, -s.h / 2, 0, 1);
    ctx.restore();
  }

  paintLight(ctx, viewW, viewH);
  drawAimed(ctx, camX, camY);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
}

/* A thin outline on the tile you would act on. Farming needs to be unambiguous
   about which square the hoe lands on -- without it you till the wrong tile and
   cannot tell why. */
function drawAimed(ctx, camX, camY) {
  const [tx, ty] = facingTile();
  if (tx < 0 || ty < 0 || tx >= S.world.width || ty >= S.world.height) return;
  const kind = tileKind(tileAt(tx, ty));
  if (!["grass", "soil", "farm"].includes(kind) && !S.crops[key(tx, ty)]) return;
  // An upgraded hoe or can works a square; show the whole square so the reach
  // is legible.
  const item = held();
  const r = item && item.kind === "tools" ? toolRadius(item.id) : 0;
  ctx.save();
  ctx.globalAlpha = 0.5;
  ctx.strokeStyle = "#e08a3c";
  ctx.lineWidth = 1;
  if (r > 0) {
    ctx.strokeRect((tx - r) * TILE - camX + 0.5, (ty - r) * TILE - camY + 0.5,
      (2 * r + 1) * TILE - 1, (2 * r + 1) * TILE - 1);
  } else {
    ctx.strokeRect(tx * TILE - camX + 0.5, ty * TILE - camY + 0.5, TILE - 1, TILE - 1);
  }
  ctx.restore();
}

/* Time of day as a colour wash over the finished frame. The palette swap
   handles the big change between day and night; this handles the gradual part,
   so dusk arrives as a slow warm fade rather than a single jarring switch. */
function paintLight(ctx, w, h) {
  if (S.inInterior) {
    /* A lit room. Just a soft corner vignette so the walls do not read as the
       edge of the world -- no time-of-day wash, no torch. */
    const g = ctx.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.25,
                                       w / 2, h / 2, Math.max(w, h) * 0.62);
    g.addColorStop(0, "rgba(20,14,8,0)");
    g.addColorStop(1, "rgba(12,9,6,0.42)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
    return;
  }
  if (S.inWilds) {
    /* Torchlight rather than a flat wash: a warm pool around you falling off to
       near-black at the edges of the screen. The flat version was readable but
       made a cavern feel like a dim field -- what makes a cave feel like a cave
       is not being able to see the far wall.

       Drawn as one radial gradient over the finished frame, which costs a
       single fill and needs no light map, no shadow casting and no second
       render pass. */
    const cx = S.player.x - S.view.camX, cy = S.player.y - S.view.camY - 6;
    /* Wide enough to fight in. A first pass used 74 world pixels, which at zoom
       3 is a spotlight barely wider than the player -- atmospheric, but foes
       aggro from 190 away, so they arrived out of pitch black with no warning
       at all. This sees roughly half as far as they can, which leaves the dark
       threatening without making it unfair. */
    const reach = 118 + Math.sin(performance.now() / 420) * 4;   // a faint flicker
    const light = ctx.createRadialGradient(cx, cy, reach * 0.16, cx, cy, reach);
    light.addColorStop(0, "rgba(10,15,28,0)");
    light.addColorStop(0.45, "rgba(9,13,26,0.22)");
    light.addColorStop(0.78, "rgba(7,11,22,0.58)");
    light.addColorStop(1, "rgba(6,9,18,0.88)");
    ctx.fillStyle = light;
    ctx.fillRect(0, 0, w, h);
    /* Beyond the gradient's radius the fill above stops, so the far corners get
       their own flat cover or they stay conspicuously bright. */
    ctx.globalAlpha = 0.88;
    ctx.fillStyle = "#06090f";
    ctx.beginPath();
    ctx.rect(0, 0, w, h);
    ctx.arc(cx, cy, reach, 0, Math.PI * 2, true);
    ctx.fill("evenodd");
    ctx.globalAlpha = 1;
    return;
  }
  const hour = S.clock.minutes / 60;
  let tint = null;
  if (hour < 5) tint = ["#0a1430", 0.52];
  else if (hour < 7) tint = ["#4a3050", 0.34 * (7 - hour) / 2];
  else if (hour < 16.5) tint = null;
  else if (hour < 19) tint = ["#a8541e", 0.22 * (hour - 16.5) / 2.5];
  else if (hour < 21) tint = ["#2a2450", 0.30 * (hour - 19) / 2];
  else tint = ["#0a1430", 0.52];
  if (!tint) return;
  ctx.globalAlpha = tint[1];
  ctx.fillStyle = tint[0];
  ctx.fillRect(0, 0, w, h);
  ctx.globalAlpha = 1;
}
