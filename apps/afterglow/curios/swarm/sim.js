/* Swarm: particle life. A few thousand particles in a handful of colours,
 * and one table of rules: how much each colour is pulled toward (positive) or
 * pushed from (negative) every other colour. Up close everything pushes
 * apart, so nothing collapses to a point. The world wraps at its edges.
 * No DOM: node imports this file as it is.
 */

import { rng } from "../_kit/rng.js";

export const LIMITS = {
  colours: { min: 2, max: 8, step: 1 },
  count: { min: 200, max: 2500, step: 100 },
  reach: { min: 0.04, max: 0.2, step: 0.01 },
  pull: { min: 1, max: 20, step: 0.5 },
  glide: { min: 0.01, max: 0.2, step: 0.005 },
};
export const DEFAULTS = { colours: 5, count: 1400, reach: 0.1, pull: 10, glide: 0.04 };
/** Inside this share of the reach, every pair pushes apart whatever the rule says. */
export const BETA = 0.3;
/** Every world has the area of a 16:9 frame one unit high, whatever the window's
 *  shape, so a tall window does not crowd the same particles into less room. */
export const AREA = 16 / 9;
const RULE_STEP = 0.05;

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

function num(value, { min, max, step }, fallback) {
  const v = Number(value);
  if (!Number.isFinite(v)) return fallback;
  const places = String(step).includes(".") ? String(step).split(".")[1].length : 0;
  return Number(clamp(Math.round(v / step) * step, min, max).toFixed(places));
}

/** A rule table for k colours, values in [-1, 1] on a 0.05 grid. */
export function randomRules(rand, k) {
  const out = new Array(k * k);
  for (let i = 0; i < out.length; i++) out[i] = Math.round((rand() * 2 - 1) / RULE_STEP) * RULE_STEP;
  return out.map((v) => Number(v.toFixed(2)) || 0);
}

/** Any keepsake's data made safe: every field present, in range, finite. */
export function cleanRules(data) {
  const d = data && typeof data === "object" ? data : {};
  const seedRaw = Number(d.seed);
  const seed = Number.isFinite(seedRaw) ? Math.abs(Math.floor(seedRaw)) % 4294967296 : 1;
  const colours = num(d.colours, LIMITS.colours, DEFAULTS.colours);
  let matrix = Array.isArray(d.matrix) && d.matrix.length === colours * colours ? d.matrix.map(Number) : null;
  if (!matrix || matrix.some((v) => !Number.isFinite(v))) matrix = randomRules(rng(seed), colours);
  return {
    colours,
    matrix: matrix.map((v) => Number(clamp(v, -1, 1).toFixed(2)) || 0),
    count: num(d.count, LIMITS.count, DEFAULTS.count),
    reach: num(d.reach, LIMITS.reach, DEFAULTS.reach),
    pull: num(d.pull, LIMITS.pull, DEFAULTS.pull),
    glide: num(d.glide, LIMITS.glide, DEFAULTS.glide),
    seed,
  };
}

/** The same table made mutual: every pair feels each other the way the upper
 *  right half says (the Mirror button). Mirrored swarms settle; lopsided ones chase. */
export function mirrorRules(matrix, k) {
  const out = matrix.slice();
  for (let i = 0; i < k; i++) for (let j = 0; j < i; j++) out[i * k + j] = out[j * k + i];
  return out;
}

/** A rule table resized to k colours: kept where both tables have a cell, new cells from rand. */
export function resizeRules(matrix, from, to, rand) {
  const out = randomRules(rand, to);
  for (let i = 0; i < Math.min(from, to); i++) {
    for (let j = 0; j < Math.min(from, to); j++) out[i * to + j] = matrix[i * from + j];
  }
  return out;
}

/** The force at distance r (as a share of the reach) under rule a. */
export function force(r, a) {
  if (r < BETA) return r / BETA - 1;
  if (r < 1) return a * (1 - Math.abs(2 * r - 1 - BETA) / (1 - BETA));
  return 0;
}

/** Width and height of a world with this aspect (width over height) and the fixed AREA. */
export function worldSize(aspect) {
  const a = clamp(Number(aspect) || 1, 0.2, 5);
  const H = Math.sqrt(AREA / a);
  return { W: a * H, H };
}

/** A new world shaped like the window. Particle i has colour i % k, so
 *  drawing one colour is a stride through the arrays. */
export function createSwarm(rules, aspect = 16 / 9, seed = rules.seed) {
  const n = rules.count;
  const { W, H } = worldSize(aspect);
  const rand = rng(seed);
  const sw = {
    n,
    k: rules.colours,
    W,
    H,
    x: new Float32Array(n),
    y: new Float32Array(n),
    vx: new Float32Array(n),
    vy: new Float32Array(n),
    cell: new Int32Array(n),
    items: new Int32Array(n),
    start: new Int32Array(1),
  };
  for (let i = 0; i < n; i++) {
    sw.x[i] = rand() * W;
    sw.y[i] = rand() * H;
  }
  return sw;
}

/** Stretch the world to a new aspect, keeping every particle where it was relative to the edges. */
export function reshape(sw, aspect) {
  const { W, H } = worldSize(aspect);
  if (Math.abs(W - sw.W) < 1e-6 && Math.abs(H - sw.H) < 1e-6) return sw;
  const sx = W / sw.W;
  const sy = H / sw.H;
  for (let i = 0; i < sw.n; i++) {
    sw.x[i] = Math.min(W - 1e-6, sw.x[i] * sx);
    sw.y[i] = Math.min(H - 1e-6, sw.y[i] * sy);
  }
  sw.W = W;
  sw.H = H;
  return sw;
}

/** The same world with n particles: the first ones kept, new ones scattered from rand. */
export function recount(sw, n, rand) {
  const out = { ...sw, n };
  for (const key of ["x", "y", "vx", "vy"]) {
    out[key] = new Float32Array(n);
    out[key].set(sw[key].subarray(0, Math.min(n, sw.n)));
  }
  for (let i = sw.n; i < n; i++) {
    out.x[i] = rand() * sw.W;
    out.y[i] = rand() * sw.H;
  }
  out.cell = new Int32Array(n);
  out.items = new Int32Array(n);
  return out;
}

function offsets(cells) {
  return cells >= 3 ? [-1, 0, 1] : cells === 2 ? [0, 1] : [0];
}

/** Advance the world by dt seconds. Neighbours are found through a grid of
 *  cells at least one reach wide, so a step costs about n x (neighbours). */
export function step(sw, rules, dt) {
  const { n, x, y, vx, vy, cell, W, H } = sw;
  const k = sw.k;
  const m = rules.matrix;
  const R = rules.reach;
  const R2 = R * R;
  const cols = Math.max(1, Math.floor(W / R));
  const rows = Math.max(1, Math.floor(H / R));
  const cw = W / cols;
  const ch = H / rows;
  const cells = cols * rows;
  if (sw.start.length !== cells + 1) sw.start = new Int32Array(cells + 1);
  if (!sw.fill || sw.fill.length !== cells) sw.fill = new Int32Array(cells);
  const start = sw.start;
  const fill = sw.fill;
  const items = sw.items;
  start.fill(0);
  for (let i = 0; i < n; i++) {
    const cx = Math.min(cols - 1, Math.floor(x[i] / cw));
    const cy = Math.min(rows - 1, Math.floor(y[i] / ch));
    cell[i] = cx + cy * cols;
    start[cell[i] + 1]++;
  }
  for (let c = 0; c < cells; c++) start[c + 1] += start[c];
  fill.set(start.subarray(0, cells));
  for (let i = 0; i < n; i++) items[fill[cell[i]]++] = i;

  const xs = offsets(cols);
  const ys = offsets(rows);
  const halfW = W / 2;
  const halfH = H / 2;
  const keep = Math.pow(0.5, dt / rules.glide);
  const scale = R * rules.pull;
  for (let i = 0; i < n; i++) {
    const xi = x[i];
    const yi = y[i];
    const row = (i % k) * k;
    const cx = cell[i] % cols;
    const cy = (cell[i] - cx) / cols;
    let ax = 0;
    let ay = 0;
    for (const oy of ys) {
      const ry = (cy + oy + rows) % rows;
      for (const ox of xs) {
        const c = ((cx + ox + cols) % cols) + ry * cols;
        for (let p = start[c]; p < start[c + 1]; p++) {
          const j = items[p];
          if (j === i) continue;
          let dx = x[j] - xi;
          let dy = y[j] - yi;
          if (dx > halfW) dx -= W;
          else if (dx < -halfW) dx += W;
          if (dy > halfH) dy -= H;
          else if (dy < -halfH) dy += H;
          const d2 = dx * dx + dy * dy;
          if (d2 >= R2 || d2 === 0) continue;
          const d = Math.sqrt(d2);
          const f = force(d / R, m[row + (j % k)]);
          ax += (dx / d) * f;
          ay += (dy / d) * f;
        }
      }
    }
    vx[i] = vx[i] * keep + ax * scale * dt;
    vy[i] = vy[i] * keep + ay * scale * dt;
  }
  for (let i = 0; i < n; i++) {
    let nx = x[i] + vx[i] * dt;
    let ny = y[i] + vy[i] * dt;
    nx -= Math.floor(nx / W) * W;
    ny -= Math.floor(ny / H) * H;
    x[i] = nx < W ? nx : 0; // float rounding can land exactly on the far edge
    y[i] = ny < H ? ny : 0;
  }
  return sw;
}

/** Push every particle within `radius` of (px, py) outward; returns how many moved. */
export function poke(sw, px, py, radius = 0.12, strength = 1.2) {
  let moved = 0;
  for (let i = 0; i < sw.n; i++) {
    let dx = sw.x[i] - px;
    let dy = sw.y[i] - py;
    if (dx > sw.W / 2) dx -= sw.W;
    else if (dx < -sw.W / 2) dx += sw.W;
    if (dy > sw.H / 2) dy -= sw.H;
    else if (dy < -sw.H / 2) dy += sw.H;
    const d = Math.hypot(dx, dy);
    if (d >= radius || d === 0) continue;
    const push = strength * (1 - d / radius);
    sw.vx[i] += (dx / d) * push;
    sw.vy[i] += (dy / d) * push;
    moved++;
  }
  return moved;
}

/** How clumped the world is: the mean number of neighbours within half a
 *  reach, over what an even scatter would have. About 1 is even; well above
 *  1 means the particles have gathered into shapes. */
export function clumping(sw, reach) {
  const r = reach / 2;
  const r2 = r * r;
  let found = 0;
  const sample = Math.min(sw.n, 400);
  const stride = sw.n / sample;
  for (let s = 0; s < sample; s++) {
    const i = Math.floor(s * stride);
    for (let j = 0; j < sw.n; j++) {
      if (j === i) continue;
      let dx = Math.abs(sw.x[j] - sw.x[i]);
      let dy = Math.abs(sw.y[j] - sw.y[i]);
      if (dx > sw.W / 2) dx = sw.W - dx;
      if (dy > sw.H / 2) dy = sw.H - dy;
      if (dx * dx + dy * dy < r2) found++;
    }
  }
  const expected = ((sw.n - 1) * Math.PI * r2) / (sw.W * sw.H);
  return found / sample / expected;
}

/** Mean speed, in world units per second (a 16:9 world is one unit high). */
export function meanSpeed(sw) {
  let total = 0;
  for (let i = 0; i < sw.n; i++) total += Math.hypot(sw.vx[i], sw.vy[i]);
  return sw.n ? total / sw.n : 0;
}
