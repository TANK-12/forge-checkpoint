/* Drawing: the sky, three layers of low-poly mountains, the slope, its
   props, the rider. Everything is flat-shaded polygons, painted from colour
   roles (palette.js), so the whole picture follows the time of day, the
   weather and the Forge accent.

   Camera: world (wx, wy) lands on screen at ((wx - cam.x) * z, (wy - cam.y) *
   z + H / 2). The background layers only move sideways, at a fraction of
   the camera's speed, the way Alto's mountains do. */

import { hash, DX, ropeY } from "./world.js";
import { mix, shade, rgba } from "./palette.js";

// --- shapes ---------------------------------------------------------------

export function drawShape(ctx, shape, roles, x, y, scale = 1, angle = 0, flip = false, mono = null) {
  if (!shape) return;
  ctx.save();
  ctx.translate(x, y);
  if (angle) ctx.rotate(angle);
  ctx.scale(flip ? -scale : scale, scale);
  for (const part of shape.parts) {
    const pts = part.points;
    ctx.fillStyle = mono || roles[part.role] || "#ff00ff";
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.closePath();
    ctx.fill();
  }
  ctx.restore();
}

// The centre of a shape's glowing parts, cached: lanterns and windows.
const glowCache = new WeakMap();
export function glowPoints(shape) {
  if (!shape) return [];
  if (glowCache.has(shape)) return glowCache.get(shape);
  const pts = shape.parts.filter((p) => p.role === "glow").map((p) => {
    const n = p.points.length;
    return [p.points.reduce((s, q) => s + q[0], 0) / n, p.points.reduce((s, q) => s + q[1], 0) / n];
  });
  glowCache.set(shape, pts);
  return pts;
}

let glowSprite = null;
function glow(ctx, x, y, r, color, a) {
  if (!glowSprite) {
    glowSprite = document.createElement("canvas");
    glowSprite.width = glowSprite.height = 64;
    const g = glowSprite.getContext("2d");
    const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0, "rgba(255,255,255,1)");
    grad.addColorStop(0.3, "rgba(255,255,255,.35)");
    grad.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grad;
    g.fillRect(0, 0, 64, 64);
  }
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  ctx.globalAlpha = a;
  ctx.filter = "none";
  ctx.drawImage(tinted(color), x - r, y - r, r * 2, r * 2);
  ctx.restore();
}
const tints = {};
function tinted(color) {
  if (tints[color]) return tints[color];
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  g.drawImage(glowSprite, 0, 0);
  g.globalCompositeOperation = "source-in";
  g.fillStyle = color;
  g.fillRect(0, 0, 64, 64);
  return (tints[color] = c);
}

// --- sky ------------------------------------------------------------------

const STARS = Array.from({ length: 140 }, (_, i) => [hash(i, 1), hash(i, 2) * 0.6, hash(i, 3)]);

export function drawSky(ctx, W, H, s) {
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, s.sky.top);
  g.addColorStop(0.75, s.sky.bottom);
  g.addColorStop(1, s.sky.bottom);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);

  const night = s.night;
  if (night > 0.05) {
    ctx.fillStyle = "#ffffff";
    for (const [x, y, b] of STARS) {
      ctx.globalAlpha = night * (0.3 + 0.7 * b) * (0.7 + 0.3 * Math.sin(s.time * 2 + b * 40)) * (1 - s.weather.overcast);
      ctx.fillRect(((x * W - s.cam.x * 0.01) % W + W) % W, y * H, 1.6, 1.6);
    }
    ctx.globalAlpha = 1;
    if (s.aurora && s.weather.overcast < 0.3) drawAurora(ctx, W, H, s, night);
  }

  // the sun and the moon ride one arc across the day
  const a = s.dayT * Math.PI * 2 - Math.PI / 2;
  const cx = W * 0.5 + Math.cos(a) * W * 0.42, cy = H * 0.62 + Math.sin(a) * H * 0.5;
  const mx = W * 0.5 - Math.cos(a) * W * 0.42, my = H * 0.62 - Math.sin(a) * H * 0.5;
  const clear = 1 - s.weather.overcast;
  if (cy < H * 0.7) {
    glow(ctx, cx, cy, 160, mix("#fff1c9", s.accent, 0.15), 0.5 * clear);
    ctx.fillStyle = rgba("#fff6dc", clear);
    polyCircle(ctx, cx, cy, 26, 10);
  }
  if (my < H * 0.7 && night > 0.1) {
    glow(ctx, mx, my, 90, "#b8c8ff", 0.35 * clear * night);
    ctx.fillStyle = rgba("#eef2ff", clear * night);
    polyCircle(ctx, mx, my, 18, 9);
    ctx.fillStyle = rgba(s.sky.top, clear * night);
    polyCircle(ctx, mx + 7, my - 4, 15, 9);
  }

  // low-poly clouds, drifting a little faster than the far range
  const cloud = mix(s.sky.bottom, "#ffffff", 0.55 - night * 0.4);
  ctx.fillStyle = rgba(cloud, 0.55 + s.weather.overcast * 0.4);
  const n = 5 + Math.round(s.weather.overcast * 8);
  for (let i = 0; i < n; i++) {
    const span = W + 600;
    const x = (((hash(i, 7) * span - s.cam.x * 0.04 - s.time * (8 + hash(i, 8) * 10)) % span) + span) % span - 300;
    const y = H * (0.08 + hash(i, 9) * 0.3);
    const w = 90 + hash(i, 10) * 160;
    ctx.beginPath();
    ctx.moveTo(x - w / 2, y);
    ctx.lineTo(x - w * 0.3, y - w * 0.12);
    ctx.lineTo(x - w * 0.05, y - w * 0.2);
    ctx.lineTo(x + w * 0.2, y - w * 0.14);
    ctx.lineTo(x + w / 2, y);
    ctx.closePath();
    ctx.fill();
  }
}

function polyCircle(ctx, x, y, r, n) {
  ctx.beginPath();
  for (let k = 0; k < n; k++) {
    const a = (k / n) * Math.PI * 2;
    ctx.lineTo(x + Math.cos(a) * r, y + Math.sin(a) * r);
  }
  ctx.fill();
}

function drawAurora(ctx, W, H, s, night) {
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  const cols = [s.accent, s.accent2, "#62f2b0"];
  for (let b = 0; b < 3; b++) {
    const g = ctx.createLinearGradient(0, H * 0.05, 0, H * 0.45);
    g.addColorStop(0, rgba(cols[b], 0));
    g.addColorStop(0.5, rgba(cols[b], 0.16 * night));
    g.addColorStop(1, rgba(cols[b], 0));
    ctx.fillStyle = g;
    ctx.beginPath();
    for (let x = 0; x <= W; x += 40) {
      const y = H * 0.18 + Math.sin(x / 230 + s.time * 0.25 + b * 2) * 40 + Math.sin(x / 90 + s.time * 0.5 + b) * 12;
      ctx.lineTo(x, y);
    }
    for (let x = W; x >= 0; x -= 40) {
      const y = H * 0.34 + Math.sin(x / 200 + s.time * 0.2 + b * 3) * 30;
      ctx.lineTo(x, y);
    }
    ctx.fill();
  }
  ctx.restore();
}

// --- mountain ranges ------------------------------------------------------

/* A range is value noise on a lattice, joined by straight lines: that is what
   makes it low-poly. Each lattice step is two triangles down to a lower row,
   each shaded by which way it faces the sun, with a little per-facet jitter,
   and the tallest peaks get snow caps. */
export const RANGES = [
  { parallax: 0.06, base: 0.62, height: 0.4, step: 150, salt: 11, haze: 0.62, snow: true, trees: false },
  { parallax: 0.16, base: 0.72, height: 0.3, step: 110, salt: 23, haze: 0.42, snow: true, trees: true },
  { parallax: 0.32, base: 0.84, height: 0.2, step: 80, salt: 37, haze: 0.22, snow: false, trees: true },
];

function ridge(range, i, H) {
  const a = hash(i, range.salt), b = hash(i >> 2, range.salt + 1);
  return H * range.base - H * range.height * (0.25 + 0.45 * a * a + 0.35 * b);
}

export function drawRanges(ctx, W, H, s, shapes, quality) {
  const sunLeft = Math.cos(s.dayT * Math.PI * 2 - Math.PI / 2) < 0;
  RANGES.forEach((range, li) => {
    const off = s.cam.x * range.parallax;
    const i0 = Math.floor(off / range.step) - 1, i1 = i0 + Math.ceil(W / range.step) + 3;
    const base = mix(mix("#5d6b8a", s.sky.haze, range.haze), s.accent, s.strength * 0.18 * (1 - range.haze));
    const body = shade(base, -(1 - s.sky.light) * 0.55 - li * 0.06);
    const snow = shade(mix("#f2f5fb", s.sky.haze, range.haze * 0.8), -(1 - s.sky.light) * 0.5);
    const floorY = H;
    for (let i = i0; i < i1; i++) {
      const xa = i * range.step - off, xb = xa + range.step;
      const ya = ridge(range, i, H), yb = ridge(range, i + 1, H);
      const mxv = (xa + xb) / 2 + (hash(i, range.salt + 5) - 0.5) * range.step * 0.4;
      const mya = Math.max(ya, yb) + (floorY - Math.max(ya, yb)) * (0.35 + hash(i, range.salt + 6) * 0.3);
      const facing = (yb - ya) / range.step; // >0: face toward the right
      const lit = (sunLeft ? -facing : facing) * 0.25;
      const j = (hash(i, range.salt + 7) - 0.5) * 0.08;
      tri(ctx, xa, ya, xb, yb, mxv, mya, shade(body, clamp(lit + j, -0.3, 0.3)));
      tri(ctx, xa, ya, mxv, mya, xa, floorY, shade(body, clamp(-lit * 0.6 + j - 0.05, -0.3, 0.3)));
      tri(ctx, xb, yb, mxv, mya, xb, floorY, shade(body, clamp(lit * 0.4 - j - 0.08, -0.3, 0.3)));
      tri(ctx, mxv, mya, xa, floorY, xb, floorY, shade(body, -0.1 + j));
      if (range.snow && ya < H * range.base - H * range.height * 0.72) {
        const k = 0.28;
        ctx.fillStyle = shade(snow, sunLeft ? 0.02 : -0.08);
        ctx.beginPath();
        ctx.moveTo(xa, ya);
        ctx.lineTo(xa + (xb - xa) * k, ya + (yb - ya) * k + 6);
        ctx.lineTo(xa + (mxv - xa) * k * 0.7, ya + (mya - ya) * k * 0.7);
        ctx.lineTo(xa - range.step * k * 0.8, ya + (ridge(range, i - 1, H) - ya) * k + 4);
        ctx.fill();
      }
      if (range.trees && quality !== "low" && shapes.pine) {
        const n = li === 2 ? 3 : 2;
        for (let t = 0; t < n; t++) {
          const h = hash(i * 7 + t, range.salt + 9);
          if (h < 0.45) continue;
          const tx = xa + (t + 0.3 + h * 0.4) * (range.step / n);
          const ty = mya + (floorY - mya) * 0.15 + h * 20;
          drawShape(ctx, shapes.pine, null, tx, ty, 0.35 + li * 0.18 + h * 0.2, 0, false, shade(body, -0.12));
        }
      }
    }
    // atmospheric haze at the foot of each range
    const hz = ctx.createLinearGradient(0, H * range.base - H * 0.15, 0, H);
    hz.addColorStop(0, rgba(s.sky.haze, 0));
    hz.addColorStop(1, rgba(s.sky.haze, 0.35 + range.haze * 0.3));
    ctx.fillStyle = hz;
    ctx.fillRect(0, H * range.base - H * 0.15, W, H);
  });
}

function tri(ctx, ax, ay, bx, by, cx, cy, color) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(ax, ay);
  ctx.lineTo(bx, by);
  ctx.lineTo(cx, cy);
  ctx.closePath();
  ctx.fill();
  // a hair of the same colour hides the seams between facets
  ctx.strokeStyle = color;
  ctx.lineWidth = 0.6;
  ctx.stroke();
}

function clamp(v, a, b) {
  return Math.max(a, Math.min(b, v));
}

// --- the slope ------------------------------------------------------------

export function drawGround(ctx, W, H, s, world) {
  const z = s.zoom, cam = s.cam;
  const sx = (x) => (x - cam.x) * z, sy = (y) => (y - cam.y) * z + H / 2;
  const i0 = Math.max(0, Math.floor((cam.x - world.x0) / DX) - 1);
  const i1 = Math.min(world.ys.length - 1, i0 + Math.ceil(W / z / DX) + 3);
  const roles = s.roles;
  let i = i0;
  while (i <= i1) {
    while (i <= i1 && world.gaps[i]) i++;
    if (i > i1) break;
    const start = i;
    while (i <= i1 && !world.gaps[i]) i++;
    const end = i - 1;
    if (end <= start) continue;
    const X = (k) => sx(world.x0 + k * DX), Y = (k) => sy(world.ys[k]);
    // the body of the snow, darkening into the depth
    const top = Math.min(...[start, end].map(Y));
    const g = ctx.createLinearGradient(0, top, 0, H);
    g.addColorStop(0, roles.snow);
    g.addColorStop(0.35, roles.snowShade);
    g.addColorStop(1, shade(roles.snowShade, -0.35));
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.moveTo(X(start), H + 10);
    for (let k = start; k <= end; k++) ctx.lineTo(X(k), Y(k));
    ctx.lineTo(X(end), H + 10);
    ctx.closePath();
    ctx.fill();
    // facets just under the surface, so the snow reads as low-poly too: a
    // strip of triangles between the rim and a jittered row below it
    const salt = Math.floor(world.x0 / DX);
    const sub = (k) => [X(k) + (hash(k + salt, 53) - 0.5) * 20 * z, Y(k) + (38 + hash(k + salt, 51) * 34) * z];
    const phase = (((start + salt) % 3) + 3) % 3; // facets stay put as the view scrolls
    for (let k = start + ((3 - phase) % 3); k + 3 <= end; k += 3) {
      const [ax, ay] = sub(k), [bx, by] = sub(k + 3);
      const j = hash(k + salt, 52) * 0.18;
      tri(ctx, X(k), Y(k), X(k + 3), Y(k + 3), ax, ay, mix(roles.snow, roles.snowShade, 0.12 + j));
      tri(ctx, X(k + 3), Y(k + 3), bx, by, ax, ay, mix(roles.snow, roles.snowShade, 0.3 + j));
    }
    // a chasm's cliff faces are bare rock
    for (const [k, dir] of [[start, -1], [end, 1]]) {
      if (k === start && start === 0) continue;
      if (k === end && end >= world.ys.length - 1) continue;
      ctx.fillStyle = roles.rockShade;
      ctx.beginPath();
      ctx.moveTo(X(k), Y(k));
      ctx.lineTo(X(k) - dir * 22 * z, Y(k) + 60 * z);
      ctx.lineTo(X(k) - dir * 8 * z, H + 10);
      ctx.lineTo(X(k), H + 10);
      ctx.fill();
    }
    // the bright rim of the snow
    ctx.strokeStyle = shade(roles.snow, 0.3);
    ctx.lineWidth = 2 * z;
    ctx.beginPath();
    for (let k = start; k <= end; k++) ctx.lineTo(X(k), Y(k));
    ctx.stroke();
  }
}

// The groove the board leaves behind.
export function drawTrail(ctx, H, s, trail) {
  if (trail.length < 2) return;
  const z = s.zoom, cam = s.cam;
  ctx.strokeStyle = s.roles.snowShade;
  ctx.lineWidth = 3 * z;
  ctx.lineCap = "round";
  ctx.beginPath();
  let pen = false;
  for (const p of trail) {
    if (!p) { pen = false; continue; }
    const x = (p[0] - cam.x) * z, y = (p[1] + 1.5 - cam.y) * z + H / 2;
    if (pen) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    pen = true;
  }
  ctx.stroke();
}

export function drawRopes(ctx, H, s, world) {
  const z = s.zoom, cam = s.cam;
  const flags = [s.roles.accent, s.roles.accent2, s.roles.gold, s.roles.snow];
  for (const r of world.ropes) {
    const sx = (x) => (x - cam.x) * z, sy = (y) => (y - cam.y) * z + H / 2;
    ctx.strokeStyle = s.roles.woodDark;
    ctx.lineWidth = 1.6 * z;
    ctx.beginPath();
    for (let x = r.x1; x <= r.x2; x += 12) ctx.lineTo(sx(x), sy(ropeY(r, x)));
    ctx.lineTo(sx(r.x2), sy(r.y2));
    ctx.stroke();
    let n = 0;
    for (let x = r.x1 + 18; x < r.x2 - 10; x += 24, n++) {
      const y = ropeY(r, x);
      const flap = Math.sin(s.time * 6 + x * 0.05) * 2 * z;
      ctx.fillStyle = flags[n % flags.length];
      ctx.beginPath();
      ctx.moveTo(sx(x - 7), sy(y));
      ctx.lineTo(sx(x + 7), sy(ropeY(r, x + 7)));
      ctx.lineTo(sx(x) + flap, sy(y + 13));
      ctx.fill();
    }
  }
}

// The flag where your best run ended: a pole and a pennant in the Forge
// accent with the distance beside it, planted on the first snow at or after
// x (a best that ended over a chasm stands on its far side).
export function drawFlag(ctx, H, s, world, x, label) {
  if (!x) return;
  const z = s.zoom, cam = s.cam, W = ctx.canvas.width;
  if ((x - cam.x) * z < -120 || (x - cam.x) * z > W + 120) return;
  let gx = x, g = world.groundAt(gx);
  for (let k = 0; g === null && k < 40; k++) g = world.groundAt((gx += DX));
  if (g === null) return;
  const px = (gx - cam.x) * z, py = (g - cam.y) * z + H / 2, h = 74 * z;
  const flap = Math.sin(s.time * 5) * 3 * z;
  ctx.strokeStyle = s.roles.woodDark;
  ctx.lineWidth = 2.2 * z;
  ctx.beginPath();
  ctx.moveTo(px, py + 3 * z);
  ctx.lineTo(px, py - h);
  ctx.stroke();
  ctx.fillStyle = s.roles.accent;
  ctx.beginPath();
  ctx.moveTo(px, py - h);
  ctx.lineTo(px + 34 * z + flap, py - h + 10 * z);
  ctx.lineTo(px, py - h + 20 * z);
  ctx.fill();
  if (!label) return;
  ctx.font = `600 ${Math.round(13 * z)}px Rubik, Inter, system-ui, sans-serif`;
  ctx.textBaseline = "middle";
  ctx.lineWidth = 3 * z;
  ctx.strokeStyle = "rgba(10, 14, 32, 0.55)";
  ctx.strokeText(label, px + 6 * z, py - h + 32 * z);
  ctx.fillStyle = "#ffffff";
  ctx.fillText(label, px + 6 * z, py - h + 32 * z);
}

export function drawItems(ctx, H, s, world, shapes, layer) {
  const z = s.zoom, cam = s.cam, W = ctx.canvas.width;
  for (const it of world.items) {
    if (it.layer !== layer || it.taken) continue;
    const x = (it.x - cam.x) * z, y = (it.y - cam.y) * z + H / 2;
    if (x < -200 || x > W + 200) continue;
    const shape = shapes[it.id];
    if (it.type === "coin") {
      const bob = Math.sin(s.time * 4 + it.x) * 2 * z;
      const spin = Math.abs(Math.cos(s.time * 3 + it.x * 0.01));
      ctx.save();
      ctx.translate(x, y + bob);
      ctx.scale(0.35 + 0.65 * spin, 1);
      drawShape(ctx, shape, s.roles, 0, 0, z * 1.2);
      ctx.restore();
      if (s.night > 0.3) glow(ctx, x, y, 16 * z, s.roles.gold, 0.35 * s.night);
      continue;
    }
    drawShape(ctx, shape, s.roles, x, y, z * (it.scale || 1), 0, it.flip);
    if (s.night > 0.2 && shape && shape.place && shape.place.night_glow) {
      for (const [gx, gy] of glowPoints(shape)) {
        const px = x + gx * z * (it.scale || 1) * (it.flip ? -1 : 1), py = y + gy * z * (it.scale || 1);
        glow(ctx, px, py, 60 * z, "#ffc774", 0.6 * s.night);
      }
    }
  }
}

export function drawAnimals(ctx, H, s, world, shapes) {
  const z = s.zoom, cam = s.cam;
  for (const a of world.animals) {
    const x = (a.x - cam.x) * z, y = (a.y - cam.y) * z + H / 2;
    const tilt = a.hop > 0 ? -0.15 : Math.sin(s.time * 14 + a.x) * 0.04;
    drawShape(ctx, shapes[a.id], s.roles, x, y, z, tilt, false);
  }
}

export function drawRider(ctx, H, s, rider, scarf, shapes) {
  const z = s.zoom, cam = s.cam, shape = shapes.rider;
  if (!shape) return;
  const x = (rider.x - cam.x) * z, y = (rider.y - cam.y) * z + H / 2;
  // the scarf streams behind, a chain of points each chasing the last
  if (scarf.length) {
    ctx.strokeStyle = s.roles.accent;
    ctx.lineWidth = 3.5 * z;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.beginPath();
    for (const p of scarf) ctx.lineTo((p[0] - cam.x) * z, (p[1] - cam.y) * z + H / 2);
    ctx.stroke();
  }
  if (rider.boost > 0) glow(ctx, x, y - 18 * z, 70 * z, s.accent, Math.min(1, rider.boost) * 0.6);
  drawShape(ctx, shape, s.roles, x, y, z, rider.angle);
}

// The scarf's anchor in world space: the shape's `scarf` point, turned.
export function scarfAnchor(rider, shape) {
  const [ax, ay] = (shape && shape.scarf) || [-5, -29];
  const c = Math.cos(rider.angle), sn = Math.sin(rider.angle);
  return [rider.x + ax * c - ay * sn, rider.y + ax * sn + ay * c];
}

export function drawSpray(ctx, H, s, spray) {
  const z = s.zoom, cam = s.cam;
  ctx.fillStyle = s.roles.snow;
  for (const p of spray) {
    ctx.globalAlpha = Math.max(0, p.life);
    const x = (p.x - cam.x) * z, y = (p.y - cam.y) * z + H / 2;
    ctx.fillRect(x, y, 3 * z, 3 * z);
  }
  ctx.globalAlpha = 1;
}
