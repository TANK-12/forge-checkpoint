// Light kinematic physics for the Exo Lab game: a vertical capsule (drawn as a
// cylinder of radius r and height h, feet at y) against axis-aligned boxes,
// and loose crates as boxes. No three.js here, so the same file runs in the
// page and in a plain Node check. Units are SI, +Y up.

export const G = 9.81;

// Box shape used everywhere: { min: [x, y, z], max: [x, y, z], ...extra }.
export function box(min, max, extra = {}) {
  return { min, max, ...extra };
}

export function crateBox(c) {
  return {
    min: [c.x - c.hx, c.y - c.hy, c.z - c.hz],
    max: [c.x + c.hx, c.y + c.hy, c.z + c.hz],
    crate: c,
  };
}

// Overlap of a circle (x, z, r) with a box's XZ rectangle. Returns the push
// direction and depth that separates them, or null when apart.
export function circleRect(px, pz, r, b) {
  const cx = Math.min(Math.max(px, b.min[0]), b.max[0]);
  const cz = Math.min(Math.max(pz, b.min[2]), b.max[2]);
  const dx = px - cx;
  const dz = pz - cz;
  const d2 = dx * dx + dz * dz;
  if (d2 >= r * r) return null;
  if (d2 > 1e-12) {
    const d = Math.sqrt(d2);
    return { nx: dx / d, nz: dz / d, depth: r - d };
  }
  // Centre inside the rectangle: leave by the nearest side.
  const sides = [
    [px - b.min[0], -1, 0],
    [b.max[0] - px, 1, 0],
    [pz - b.min[2], 0, -1],
    [b.max[2] - pz, 0, 1],
  ];
  sides.sort((a, c) => a[0] - c[0]);
  const [d, nx, nz] = sides[0];
  return { nx, nz, depth: d + r };
}

// Distance from a point to a box's XZ rectangle (0 when inside).
export function rectDistance(px, pz, b) {
  const dx = Math.max(b.min[0] - px, 0, px - b.max[0]);
  const dz = Math.max(b.min[2] - pz, 0, pz - b.max[2]);
  return Math.hypot(dx, dz);
}

function headroom(b, boxes, y, h) {
  for (const o of boxes) {
    if (o.min[1] >= y + h || o.max[1] <= y + 1e-3) continue;
    if (circleRect(b.x, b.z, b.r * 0.95, o)) return false;
  }
  return true;
}

// Is there room for the capsule to stand at height h where it is?
export function canStand(b, boxes, h) {
  return headroom(b, boxes, b.y, h);
}

// Move the capsule one step: horizontal first (with step-up onto low boxes),
// then vertical (land on tops, bump heads on bottoms), then a ground probe.
export function moveCapsule(b, boxes, dt, step = 0.26) {
  const wasGround = b.onGround;
  b.onGround = false;
  b.hitWall = false;
  b.x += b.vx * dt;
  b.z += b.vz * dt;
  for (let pass = 0; pass < 2; pass++) {
    for (const o of boxes) {
      if (o.max[1] <= b.y + 1e-4 || o.min[1] >= b.y + b.h) continue;
      const hit = circleRect(b.x, b.z, b.r, o);
      if (!hit) continue;
      const rise = o.max[1] - b.y;
      if (wasGround && rise <= step && headroom(b, boxes, o.max[1], b.h)) {
        b.y = o.max[1];
        continue;
      }
      b.x += hit.nx * hit.depth;
      b.z += hit.nz * hit.depth;
      const vn = b.vx * hit.nx + b.vz * hit.nz;
      if (vn < 0) {
        b.vx -= vn * hit.nx;
        b.vz -= vn * hit.nz;
      }
      b.hitWall = true;
    }
  }
  const y0 = b.y;
  b.y += b.vy * dt;
  for (const o of boxes) {
    if (!circleRect(b.x, b.z, b.r * 0.9, o)) continue;
    if (b.vy <= 0 && y0 >= o.max[1] - 1e-3 && b.y < o.max[1]) {
      b.y = o.max[1];
      b.vy = 0;
      b.onGround = true;
      b.ground = o;
    } else if (b.vy > 0 && y0 + b.h <= o.min[1] + 1e-3 && b.y + b.h > o.min[1]) {
      b.y = o.min[1] - b.h;
      b.vy = 0;
    }
  }
  if (!b.onGround && b.vy <= 0) {
    for (const o of boxes) {
      if (Math.abs(b.y - o.max[1]) > 0.02) continue;
      if (!circleRect(b.x, b.z, b.r * 0.9, o)) continue;
      b.y = o.max[1];
      b.vy = 0;
      b.onGround = true;
      b.ground = o;
      break;
    }
  }
}

function overlap(a, b) {
  const d = [0, 0, 0];
  for (let i = 0; i < 3; i++) {
    const lo = Math.max(a.min[i], b.min[i]);
    const hi = Math.min(a.max[i], b.max[i]);
    if (hi <= lo) return null;
    d[i] = hi - lo;
  }
  return d;
}

// One step for a loose crate: gravity, then push out of the statics and the
// other crates along the axis of least overlap. Crates resting on something
// lose horizontal speed to friction and fall asleep when still.
export function stepCrate(c, statics, crates, dt) {
  if (c.held) return;
  if (c.sleeping) return;
  c.vy -= G * dt;
  c.x += c.vx * dt;
  c.y += c.vy * dt;
  c.z += c.vz * dt;
  c.onGround = false;
  const me = crateBox(c);
  const others = crates.filter((o) => o !== c && !o.held).map(crateBox);
  for (const o of [...statics, ...others]) {
    const d = overlap(me, o);
    if (!d) continue;
    let axis = 0;
    if (d[1] < d[axis]) axis = 1;
    if (d[2] < d[axis]) axis = 2;
    const mid = (o.min[axis] + o.max[axis]) / 2;
    const pos = [c.x, c.y, c.z][axis];
    const sign = pos >= mid ? 1 : -1;
    const push = d[axis] * sign;
    if (axis === 0) c.x += push;
    if (axis === 1) c.y += push;
    if (axis === 2) c.z += push;
    const v = ["vx", "vy", "vz"][axis];
    if (c[v] * sign < 0) c[v] = axis === 1 ? 0 : -c[v] * 0.2;
    if (axis === 1 && sign > 0) c.onGround = true;
    me.min = [c.x - c.hx, c.y - c.hy, c.z - c.hz];
    me.max = [c.x + c.hx, c.y + c.hy, c.z + c.hz];
    if (o.crate && o.crate.sleeping) o.crate.sleeping = false;
  }
  if (c.onGround) {
    const k = Math.max(0, 1 - 8 * dt);
    c.vx *= k;
    c.vz *= k;
    if (Math.hypot(c.vx, c.vy, c.vz) < 0.05) {
      c.vx = c.vy = c.vz = 0;
      c.sleeping = true;
    }
  }
}

// Ray against a box (slab test): distance along the unit direction d, or
// Infinity on a miss.
export function rayBox(o, d, b, maxT = Infinity) {
  let t0 = 0;
  let t1 = maxT;
  for (let i = 0; i < 3; i++) {
    if (Math.abs(d[i]) < 1e-9) {
      if (o[i] < b.min[i] || o[i] > b.max[i]) return Infinity;
      continue;
    }
    let ta = (b.min[i] - o[i]) / d[i];
    let tb = (b.max[i] - o[i]) / d[i];
    if (ta > tb) [ta, tb] = [tb, ta];
    t0 = Math.max(t0, ta);
    t1 = Math.min(t1, tb);
    if (t0 > t1) return Infinity;
  }
  return t0;
}

export function rayBoxes(o, d, boxes, maxT = Infinity) {
  let best = maxT;
  for (const b of boxes) best = Math.min(best, rayBox(o, d, b, best));
  return best;
}
