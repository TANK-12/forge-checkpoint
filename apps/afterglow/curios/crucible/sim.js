/* Crucible's world: a falling-sand grid with a temperature field.
 *
 * One cell holds a material (mat), a temperature in degrees C (temp), a
 * counter for things that burn out (life) and a shade byte so grains keep
 * their own tint as they move. Everything lives in typed arrays, and every
 * random choice comes from the kit's seeded rng, so the same seed and the
 * same strokes always give the same world. No DOM: node tests import this.
 *
 * One step: move (powders fall, liquids flow and level, gases rise), then
 * heat (pairwise exchange between neighbours, so a closed box keeps its
 * energy), then react (melting, freezing, burning, quenching).
 *
 * Detail: a world can be built finer than the 240 by 135 base grid, with
 * detail k cells for every base cell in each direction. A grain moves one
 * cell a step whatever the detail, so the caller runs k steps for every base
 * step, and the world rescales whatever is counted per step so a finer world
 * plays at about the same pace on screen: heat flows faster per step
 * (diffusion over a screen distance needs k*k as many steps), anything that
 * decays or burns out per step decays k times slower, and fire and live coal
 * live k times as many steps. Detail 1 is the old world. ratesFor() has the
 * numbers; HEAT_GROWTH below says how close the pace comes, and where not.
 */

import { rng, hashString } from "../_kit/rng.js";

export const W = 240;
export const H = 135;
/** The finest detail offered: 3 means 720 by 405 cells. */
export const MAX_DETAIL = 3;
export const AMBIENT = 20;
export const T_MIN = -60;
export const T_MAX = 2400;

export const M = {
  EMPTY: 0,
  STONE: 1,
  SAND: 2,
  WATER: 3,
  ORE: 4,
  MOLTEN: 5,
  IRON: 6,
  COAL: 7,
  EMBER: 8,
  FIRE: 9,
  STEAM: 10,
  ICE: 11,
  WOOD: 12,
  GLASS: 13,
  SHOT: 14,
};
export const MAT_COUNT = 15;

export const KIND = { AIR: 0, SOLID: 1, POWDER: 2, LIQUID: 3, GAS: 4 };

/** Where each change of state happens, in degrees C. */
export const POINTS = {
  oreMelt: 980,
  ironMelt: 1150,
  ironFreeze: 640,
  superheat: 1320,
  boil: 100,
  condense: 92,
  freeze: -3,
  thaw: 1,
  coalIgnite: 340,
  woodIgnite: 280,
  sandFuse: 1450,
  emberHeat: 1700,
};

// id, label, kind, density, conductivity, heat capacity, colour, start temp, tip
const TABLE = [
  [M.EMPTY, "air", KIND.AIR, 0, 0.025, 0.6, [12, 10, 20], AMBIENT, "Empty air"],
  [M.STONE, "stone", KIND.SOLID, 0, 0.05, 1.2, [96, 90, 100], AMBIENT, "Stone: a fixed wall that warms up slowly"],
  [M.SAND, "sand", KIND.POWDER, 15, 0.04, 1.0, [214, 180, 118], AMBIENT, "Sand: falls and piles; fuses to glass if you get it hot enough"],
  [M.WATER, "water", KIND.LIQUID, 10, 0.08, 4.0, [48, 108, 206], AMBIENT, "Water: flows and levels out, soaks up heat, boils to steam"],
  [M.ORE, "ore", KIND.POWDER, 30, 0.1, 1.0, [128, 70, 56], AMBIENT, "Iron ore: heavy grains that melt into molten iron past 1100 C"],
  [M.MOLTEN, "molten iron", KIND.LIQUID, 70, 0.1, 3.0, [255, 120, 30], 1500, "Molten iron: a glowing heavy liquid; touch it to water for a hiss"],
  [M.IRON, "iron", KIND.SOLID, 0, 0.22, 1.0, [150, 162, 184], AMBIENT, "Iron: a solid ingot that conducts heat well and melts again past 1150 C"],
  [M.COAL, "coal", KIND.POWDER, 13, 0.05, 1.0, [36, 33, 38], AMBIENT, "Coal: catches past 340 C when it can breathe, then burns long and hot"],
  [M.EMBER, "live coal", KIND.POWDER, 13, 0.08, 1.0, [70, 30, 22], 1300, "Live coal: already burning"],
  [M.FIRE, "fire", KIND.GAS, -2, 0.15, 1.0, [255, 140, 40], 1150, "Fire: rises, flickers and dies, heating what it touches"],
  [M.STEAM, "steam", KIND.GAS, -1, 0.04, 1.5, [196, 206, 222], 115, "Steam: rises, cools and condenses back to water"],
  [M.ICE, "ice", KIND.SOLID, 0, 0.12, 2.0, [168, 214, 240], -30, "Ice: a cold solid that melts into water"],
  [M.WOOD, "wood", KIND.SOLID, 0, 0.03, 1.2, [124, 84, 50], AMBIENT, "Wood: a fixed beam that chars into fire and live coal"],
  [M.GLASS, "glass", KIND.SOLID, 0, 0.04, 1.0, [118, 196, 186], AMBIENT, "Glass: what sand becomes in a fierce heat"],
  [M.SHOT, "iron shot", KIND.POWDER, 60, 0.18, 1.0, [116, 124, 140], AMBIENT, "Iron shot: the beads molten iron makes when it drips into water; they sink and melt again past 1150 C"],
];

export const MATERIALS = TABLE.map(([id, label, kind, density, cond, cap, color, start, tip]) => ({
  id,
  label,
  kind,
  density,
  cond,
  cap,
  color,
  start,
  tip,
}));

const KINDS = new Uint8Array(MAT_COUNT);
const DENS = new Int8Array(MAT_COUNT);
const INV_CAP = new Float32Array(MAT_COUNT);
const PAIR = new Float32Array(MAT_COUNT * MAT_COUNT); // conductance between two materials
for (const m of MATERIALS) {
  KINDS[m.id] = m.kind;
  DENS[m.id] = m.density;
  INV_CAP[m.id] = 1 / m.cap;
}
for (const a of MATERIALS) {
  for (const b of MATERIALS) {
    PAIR[a.id * MAT_COUNT + b.id] = (2 * a.cond * b.cond) / (a.cond + b.cond);
  }
}
// The most a cell may hand to one neighbour in one step, as a share of the
// difference. Four neighbours at this stay under 1, so the explicit update
// is a blend of the old temperatures and can never overshoot or ring. At
// detail 1 nothing comes near it (iron to iron is 0.22).
const HEAT_LIMIT = 0.245;
// How much faster heat flows per step at detail k: k ** HEAT_GROWTH. Exactly 1
// would match heat creeping through stone over a screen distance; 0.75 is
// what the first detail build settled on from a single run of the starter.
// Measured since (2026-10-19, five seeds each, base steps, detail 2 against 1),
// the finer world does not play exactly like the old one, and this number
// barely moves that: ore melts sooner (starter mostly melted by about 150
// against about 240; bloomery's first melt about 410 against 505), fewer drips
// quench into shot (about 40% as many in the starter, 65% in the bloomery),
// stone five cells from a hot face warms about 20% less in the same time, and
// a molten slab in open air takes about 30% longer to set. 1.0 gives the same melt and quench numbers
// within the noise, heat creep matching detail 1, and slower setting still.
// The cause is the grid itself: a finer grid resolves thinner hot and cold
// layers at every edge, and melting, quenching and setting happen per cell.
const HEAT_GROWTH = 0.75;

const RATES = new Map();
/**
 * What a world of detail k counts per step: the conductance table (scaled by
 * k ** HEAT_GROWTH, capped at HEAT_LIMIT, symmetric so heat is still
 * conserved), and the
 * per-step chances and decay rates divided by k so they keep their pace in
 * wall-clock time. At k = 1 every number is the original constant.
 */
export function ratesFor(k) {
  let r = RATES.get(k);
  if (r) return r;
  // index (a << 4) | b: the share of (t_b - t_a) that a gains (gainA) and b
  // loses (loseB) in one step; both come from one symmetric conductance, so
  // the heat (temperature times capacity) a gains is exactly what b loses
  const gainA = new Float64Array(256);
  const loseB = new Float64Array(256);
  for (const a of MATERIALS) {
    for (const b of MATERIALS) {
      const lim = HEAT_LIMIT / Math.max(INV_CAP[a.id], INV_CAP[b.id]);
      const c = Math.min(PAIR[a.id * MAT_COUNT + b.id] * Math.pow(k, HEAT_GROWTH), lim);
      gainA[(a.id << 4) | b.id] = c * INV_CAP[a.id];
      loseB[(a.id << 4) | b.id] = c * INV_CAP[b.id];
    }
  }
  // how fast open air and steam drift back to room temperature
  const relax = new Float64Array(16);
  relax[M.EMPTY] = 0.006 / k;
  relax[M.STEAM] = 0.004 / k;
  r = {
    k,
    gainA,
    loseB,
    relax,
    condense: 0.02 / k,
    ironSet: 0.03 / k,
    woodCatch: 0.02 / k,
    emberBreathe: 0.07 / k,
    emberSmoulder: 0.03 / k,
    flashKeep: Math.pow(0.9, 1 / k),
  };
  RATES.set(k, r);
  return r;
}

/** The detail of a w by h grid: k when it is k times the base grid, else 1. */
export function detailOf(w, h) {
  const k = w / W;
  return Number.isInteger(k) && k >= 1 && k <= MAX_DETAIL && h === H * k ? k : 1;
}
// How readily a powder slides off a pile: sand runs, ore is lumpy.
const SLIDE = new Float32Array(MAT_COUNT);
SLIDE[M.SAND] = 1;
SLIDE[M.ORE] = 0.45;
SLIDE[M.COAL] = 0.7;
SLIDE[M.EMBER] = 0.7;
SLIDE[M.SHOT] = 0.9;
// How far a liquid looks sideways in one step.
const SPREAD = new Uint8Array(MAT_COUNT);
SPREAD[M.WATER] = 5;
SPREAD[M.MOLTEN] = 3;

export const kindOf = (m) => KINDS[m];

/**
 * A fresh, empty world at room temperature. detail (1..MAX_DETAIL) says how
 * many cells stand for one base cell; w and h are the real grid size.
 */
export function createWorld(seed = 1, w = W, h = H, ambient = AMBIENT, detail = 1) {
  const n = w * h;
  const k = Math.max(1, Math.min(MAX_DETAIL, Math.round(detail) || 1));
  const s = {
    w,
    h,
    seed: seed >>> 0,
    tick: 0,
    ambient,
    detail: k,
    rates: ratesFor(k),
    mat: new Uint8Array(n),
    temp: new Float32Array(n).fill(ambient),
    life: new Uint16Array(n),
    shade: new Uint8Array(n),
    flash: new Float32Array(n),
    moved: new Uint8Array(n),
    down: new Float64Array(w),
    rand: rng(seed >>> 0),
    events: { melted: 0, quenched: 0, glassed: 0, lit: 0, boiled: 0 },
  };
  const r = rng(hashString(`shade:${s.seed}`));
  for (let i = 0; i < n; i++) s.shade[i] = (r() * 256) | 0;
  return s;
}

/** Restart the random stream as a function of seed and tick (used after loading). */
export function reseed(s) {
  s.rand = rng(hashString(`${s.seed}:${s.tick}`));
}

/**
 * The same world at another detail, as a new world (s is left alone).
 * Going finer, each new cell copies the cell under its centre; going coarser,
 * each new cell takes the most common material of the block it covers (a tie
 * goes to the material rather than to air, so a one-cell wall survives), at
 * the mean temperature of those cells. Burn counters are rescaled, since they
 * count steps. Seed, step count, room temperature and events carry over.
 */
export function resample(s, detail) {
  const k = Math.max(1, Math.min(MAX_DETAIL, Math.round(detail) || 1));
  const from = s.detail || 1;
  if (k === from) return s;
  const baseW = Math.round(s.w / from);
  const baseH = Math.round(s.h / from);
  const out = createWorld(s.seed, baseW * k, baseH * k, s.ambient, k);
  out.tick = s.tick;
  out.events = { ...s.events };
  const f = k / from; // new cells per old cell, along each side
  const { w, h } = out;
  const ages = (m, life) => (m === M.FIRE || m === M.EMBER ? Math.min(65535, Math.round(life * f)) : life);
  if (f > 1) {
    const sx = new Int32Array(w);
    for (let x = 0; x < w; x++) sx[x] = Math.min(s.w - 1, Math.floor((x + 0.5) / f));
    for (let y = 0; y < h; y++) {
      const row = Math.min(s.h - 1, Math.floor((y + 0.5) / f)) * s.w;
      for (let x = 0; x < w; x++) {
        const i = y * w + x;
        const j = row + sx[x];
        const m = s.mat[j];
        out.mat[i] = m;
        out.temp[i] = s.temp[j];
        out.life[i] = ages(m, s.life[j]);
        out.flash[i] = s.flash[j];
      }
    }
  } else {
    const count = new Int32Array(MAT_COUNT);
    const heat = new Float64Array(MAT_COUNT);
    const life = new Int32Array(MAT_COUNT);
    // the old cells each new cell covers, worked out once per column and per row
    const spans = (len, n) => {
      const lo = new Int32Array(len);
      const hi = new Int32Array(len);
      for (let a = 0; a < len; a++) {
        lo[a] = Math.floor(a / f);
        hi[a] = Math.min(n, Math.max(lo[a] + 1, Math.floor((a + 1) / f)));
      }
      return [lo, hi];
    };
    const [xs0, xs1] = spans(w, s.w);
    const [ys0, ys1] = spans(h, s.h);
    for (let y = 0; y < h; y++) {
      const y0 = ys0[y];
      const y1 = ys1[y];
      for (let x = 0; x < w; x++) {
        const x0 = xs0[x];
        const x1 = xs1[x];
        count.fill(0);
        heat.fill(0);
        life.fill(0);
        let glow = 0;
        for (let yy = y0; yy < y1; yy++) {
          for (let xx = x0; xx < x1; xx++) {
            const j = yy * s.w + xx;
            const m = s.mat[j];
            count[m]++;
            heat[m] += s.temp[j];
            if (s.life[j] > life[m]) life[m] = s.life[j];
            if (s.flash[j] > glow) glow = s.flash[j];
          }
        }
        let best = M.EMPTY;
        for (let m = 1; m < MAT_COUNT; m++) if (count[m] > count[best] || (best === M.EMPTY && count[m] === count[best])) best = m;
        if (count[best] === 0) best = M.EMPTY;
        const i = y * w + x;
        out.mat[i] = best;
        out.temp[i] = heat[best] / count[best];
        out.life[i] = ages(best, life[best]);
        out.flash[i] = glow;
      }
    }
  }
  reseed(out);
  return out;
}

// burn counters are in steps, so a finer world gives them k times as many
function lifeFor(m, r, k = 1) {
  if (m === M.FIRE) return (18 + ((r() * 34) | 0)) * k;
  if (m === M.EMBER) return (1400 + ((r() * 900) | 0)) * k;
  return 0;
}

/** Put material m into cell i, at temperature t (default: the material's own). */
export function place(s, i, m, t) {
  s.mat[i] = m;
  s.temp[i] = t === undefined ? (MATERIALS[m].start === AMBIENT ? s.ambient : MATERIALS[m].start) : t;
  s.life[i] = lifeFor(m, s.rand, s.detail);
  s.shade[i] = (s.rand() * 256) | 0;
}

export function inside(s, x, y) {
  return x >= 0 && y >= 0 && x < s.w && y < s.h;
}

function swap(s, i, j) {
  const { mat, temp, life, shade, moved } = s;
  let t = mat[i];
  mat[i] = mat[j];
  mat[j] = t;
  const tt = temp[i];
  temp[i] = temp[j];
  temp[j] = tt;
  t = life[i];
  life[i] = life[j];
  life[j] = t;
  t = shade[i];
  shade[i] = shade[j];
  shade[j] = t;
  moved[i] = 1;
  moved[j] = 1;
}

/** Can a falling m move into a cell holding t (and should it, this step)? */
function sinksInto(m, t, r) {
  const k = KINDS[t];
  if (k === KIND.AIR || k === KIND.GAS) return true;
  if (k === KIND.LIQUID && DENS[t] < DENS[m]) return r() < 0.5;
  // a heavy liquid trickles down through lighter grains (molten iron through coal)
  if (k === KIND.POWDER && KINDS[m] === KIND.LIQUID && DENS[t] < DENS[m]) return r() < 0.3;
  return false;
}

/** sinksInto without the dice: could m ever sink into t? */
function couldSink(m, t) {
  const k = KINDS[t];
  if (k === KIND.AIR || k === KIND.GAS) return true;
  if (k === KIND.LIQUID) return DENS[t] < DENS[m];
  return k === KIND.POWDER && KINDS[m] === KIND.LIQUID && DENS[t] < DENS[m];
}

/** A diagonal slide one cell down and dx across; true when it moved. */
function slide(s, x, i, below, dx, m, r) {
  const nx = x + dx;
  if (nx < 0 || nx >= s.w) return false;
  if (KINDS[s.mat[i + dx]] === KIND.SOLID) return false; // no squeezing through a wall's corner
  if (!sinksInto(m, s.mat[below + dx], r)) return false;
  swap(s, i, below + dx);
  return true;
}

/** Flow sideways towards dx to the furthest free cell within reach; true when it moved. */
function flow(s, x, y, i, dx, m, reach) {
  const { w, h, mat } = s;
  let free = 0;
  for (let k = 1; k <= reach; k++) {
    const nx = x + dx * k;
    if (nx < 0 || nx >= w) break;
    const tk = KINDS[mat[i + dx * k]];
    if (tk === KIND.AIR || tk === KIND.GAS) free = k;
    else break;
    if (y + 1 < h && couldSink(m, mat[i + dx * k + w])) break; // found a drop: stop at its edge
  }
  if (!free) return false;
  swap(s, i, i + dx * free);
  return true;
}

function fall(s, x, y, i, m) {
  const { w, h, mat } = s;
  const r = s.rand;
  if (y + 1 >= h) return;
  const below = i + w;
  if (sinksInto(m, mat[below], r)) {
    swap(s, i, below);
    return;
  }
  const kind = KINDS[m];
  if (kind === KIND.POWDER && r() >= SLIDE[m]) return;
  const d = r() < 0.5 ? -1 : 1;
  if (slide(s, x, i, below, d, m, r) || slide(s, x, i, below, -d, m, r)) return;
  if (kind !== KIND.LIQUID) return;
  // Flow sideways to the furthest free cell within reach, so pools level out.
  if (m === M.MOLTEN && r() < 0.25) return;
  const reach = SPREAD[m];
  if (!flow(s, x, y, i, d, m, reach)) flow(s, x, y, i, -d, m, reach);
}

function rise(s, x, y, i, m) {
  const { w, mat } = s;
  const r = s.rand;
  if (m === M.FIRE && r() < 0.25) return; // flames hang and flicker a little
  const up = i - w;
  if (y > 0) {
    const t = mat[up];
    if (t === M.EMPTY || (m === M.STEAM && KINDS[t] === KIND.LIQUID && r() < 0.6)) {
      swap(s, i, up);
      return;
    }
  }
  const d = r() < 0.5 ? -1 : 1;
  for (let side = 0; side < 2; side++) {
    const dx = side === 0 ? d : -d;
    const nx = x + dx;
    if (nx < 0 || nx >= w) continue;
    if (y > 0 && mat[up + dx] === M.EMPTY && KINDS[mat[i + dx]] !== KIND.SOLID) {
      swap(s, i, up + dx);
      return;
    }
  }
  const nx = x + d;
  if (nx >= 0 && nx < w && mat[i + d] === M.EMPTY && r() < 0.5) swap(s, i, i + d);
}

function move(s) {
  const { w, h, mat, moved } = s;
  moved.fill(0);
  for (let y = h - 1; y >= 0; y--) {
    const ltr = ((y + s.tick) & 1) === 0;
    const row = y * w;
    for (let n = 0; n < w; n++) {
      const x = ltr ? n : w - 1 - n;
      const i = row + x;
      const k = KINDS[mat[i]];
      if (k === KIND.AIR || k === KIND.SOLID || moved[i]) continue;
      if (k === KIND.GAS) rise(s, x, y, i, mat[i]);
      else fall(s, x, y, i, mat[i]);
    }
  }
}

/**
 * Heat flows between every pair of neighbours; the borders are insulated.
 * One pass, in place: each pair's exchange is worked out once from the old
 * temperatures (the right-hand share carried along the row, the downward
 * share carried to the next row in s.down), and a cell is written only after
 * both of its pairs with earlier cells have been counted.
 */
export function diffuse(s) {
  const { w, h, mat, temp } = s;
  const { gainA, loseB, relax } = s.rates;
  let down = s.down;
  if (!down || down.length !== w) down = s.down = new Float64Array(w);
  down.fill(0);
  const amb = s.ambient;
  const last = w - 1;
  // every row but the last: each cell has a right-hand and a lower neighbour
  // (the last column only a lower one); the hot loop has no edge tests in it
  for (let y = 0; y + 1 < h; y++) {
    const row = y * w;
    let side = 0;
    for (let x = 0; x < last; x++) {
      const i = row + x;
      const a = mat[i];
      const ta = temp[i];
      const pa = a << 4;
      const pr = pa | mat[i + 1];
      const dr = temp[i + 1] - ta;
      const pd = pa | mat[i + w];
      const dd = temp[i + w] - ta;
      let t = ta + (down[x] + side + gainA[pr] * dr + gainA[pd] * dd);
      side = -loseB[pr] * dr;
      down[x] = -loseB[pd] * dd;
      t += (amb - t) * relax[a]; // open air carries heat away
      temp[i] = t < T_MIN ? T_MIN : t > T_MAX ? T_MAX : t;
    }
    const i = row + last;
    const a = mat[i];
    const ta = temp[i];
    const pd = (a << 4) | mat[i + w];
    const dd = temp[i + w] - ta;
    let t = ta + (down[last] + side + gainA[pd] * dd);
    down[last] = -loseB[pd] * dd;
    t += (amb - t) * relax[a];
    temp[i] = t < T_MIN ? T_MIN : t > T_MAX ? T_MAX : t;
  }
  // the last row: right-hand neighbours only
  const row = (h - 1) * w;
  let side = 0;
  for (let x = 0; x < w; x++) {
    const i = row + x;
    const a = mat[i];
    const ta = temp[i];
    let d = down[x] + side;
    if (x < last) {
      const pr = (a << 4) | mat[i + 1];
      const dr = temp[i + 1] - ta;
      d += gainA[pr] * dr;
      side = -loseB[pr] * dr;
    }
    let t = ta + d;
    t += (amb - t) * relax[a];
    temp[i] = t < T_MIN ? T_MIN : t > T_MAX ? T_MAX : t;
  }
}

function hasNeighbour(s, i, x, y, want) {
  const { w, h, mat } = s;
  return (
    (x > 0 && mat[i - 1] === want) ||
    (x + 1 < w && mat[i + 1] === want) ||
    (y > 0 && mat[i - w] === want) ||
    (y + 1 < h && mat[i + w] === want)
  );
}

/** The first of the four neighbours (left, right, up, down) holding a or b, or -1. */
function neighbourOf(s, i, x, y, a, b) {
  const { w, h, mat } = s;
  if (x > 0 && (mat[i - 1] === a || mat[i - 1] === b)) return i - 1;
  if (x + 1 < w && (mat[i + 1] === a || mat[i + 1] === b)) return i + 1;
  if (y > 0 && (mat[i - w] === a || mat[i - w] === b)) return i - w;
  if (y + 1 < h && (mat[i + w] === a || mat[i + w] === b)) return i + w;
  return -1;
}

function quench(s, i, j) {
  // j is water or ice touching molten iron at i
  s.mat[j] = M.STEAM;
  s.temp[j] = 130;
  s.life[j] = 0;
  s.flash[j] = 1;
  s.flash[i] = 1;
  s.temp[i] = Math.max(T_MIN, s.temp[i] - 260); // never colder than the coldest the world allows
  if (s.mat[i] === M.MOLTEN) {
    // a drip that meets water bursts into beads of iron shot
    s.mat[i] = M.SHOT;
    s.events.quenched++;
  }
}

function react(s) {
  const { w, h, mat, temp, life, flash } = s;
  const r = s.rand;
  const P = POINTS;
  const R = s.rates;
  const k = R.k;
  const keep = R.flashKeep;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const fl = flash[i];
      if (fl !== 0) flash[i] = fl > 0.01 ? fl * keep : 0;
      const m = mat[i];
      if (m === M.EMPTY || m === M.STONE) continue;
      const t = temp[i];
      switch (m) {
        case M.WATER:
          if (t > P.boil) {
            mat[i] = M.STEAM;
            s.events.boiled++;
          } else if (t < P.freeze) mat[i] = M.ICE;
          break;
        case M.ICE:
          // melting takes heat: a warm face gives way a grain at a time
          if (t > P.thaw && r() < 0.0006 * (t - P.thaw)) {
            mat[i] = M.WATER;
            temp[i] = 0.5;
          }
          break;
        case M.STEAM:
          if (t < P.condense && r() < R.condense) mat[i] = M.WATER;
          break;
        case M.ORE:
          if (t > P.oreMelt) {
            // a melt runs hot: that is what lets a pour reach the trough
            mat[i] = M.MOLTEN;
            temp[i] = Math.max(t, P.superheat);
            s.events.melted++;
          }
          break;
        case M.IRON:
        case M.SHOT:
          if (t > P.ironMelt) mat[i] = M.MOLTEN;
          break;
        case M.SAND:
          if (t > P.sandFuse) {
            mat[i] = M.GLASS;
            flash[i] = 0.6;
            s.events.glassed++;
          }
          break;
        case M.MOLTEN: {
          const j = neighbourOf(s, i, x, y, M.WATER, M.ICE);
          if (j >= 0) quench(s, i, j);
          if (mat[i] === M.MOLTEN && temp[i] < P.ironFreeze && r() < R.ironSet) mat[i] = M.IRON;
          break;
        }
        case M.COAL:
          // coal catches when hot and breathing, or creeps alight from a live neighbour
          if (
            t > P.coalIgnite &&
            (hasNeighbour(s, i, x, y, M.EMPTY) ||
              hasNeighbour(s, i, x, y, M.FIRE) ||
              (r() < 0.004 && hasNeighbour(s, i, x, y, M.EMBER)))
          ) {
            mat[i] = M.EMBER;
            life[i] = lifeFor(M.EMBER, r, k);
            s.events.lit++;
          }
          break;
        case M.WOOD:
          if (t > P.woodIgnite && r() < R.woodCatch) {
            if (r() < 0.45) {
              mat[i] = M.FIRE;
              life[i] = (40 + ((r() * 60) | 0)) * k;
              temp[i] = Math.max(t, 900);
            } else {
              mat[i] = M.EMBER;
              life[i] = (300 + ((r() * 300) | 0)) * k;
            }
          }
          break;
        case M.EMBER:
          ember(s, i, x, y, r);
          break;
        case M.FIRE:
          if (hasNeighbour(s, i, x, y, M.WATER)) {
            mat[i] = M.EMPTY;
            break;
          }
          temp[i] = Math.max(t, 1050 + r() * 350);
          if (life[i] <= 1) mat[i] = M.EMPTY;
          else life[i]--;
          break;
      }
    }
  }
}

function ember(s, i, x, y, r) {
  const { w, mat, temp, life } = s;
  const R = s.rates;
  const j = neighbourOf(s, i, x, y, M.WATER, M.WATER);
  if (j >= 0) {
    mat[j] = M.STEAM;
    temp[j] = 120;
    mat[i] = M.COAL;
    temp[i] = Math.min(temp[i], 180);
    s.flash[j] = 0.5;
    return;
  }
  const breathes = hasNeighbour(s, i, x, y, M.EMPTY) || hasNeighbour(s, i, x, y, M.FIRE);
  if (breathes) {
    temp[i] += (POINTS.emberHeat - temp[i]) * R.emberBreathe;
    if (y > 0 && mat[i - w] === M.EMPTY && r() < 0.07) {
      place(s, i - w, M.FIRE);
    }
    life[i] = life[i] > 0 ? life[i] - 1 : 0;
  } else {
    // smothered: it smoulders, cooler and slower
    temp[i] += (POINTS.emberHeat * 0.75 - temp[i]) * R.emberSmoulder;
    if (r() < 0.25) life[i] = life[i] > 0 ? life[i] - 1 : 0;
  }
  if (life[i] === 0) {
    mat[i] = r() < 0.5 ? M.EMPTY : M.FIRE;
    life[i] = mat[i] === M.FIRE ? 10 * R.k : 0;
  }
}

/** One deterministic step of the world. */
export function step(s) {
  move(s);
  diffuse(s);
  react(s);
  s.tick++;
}

export function stepN(s, n) {
  for (let k = 0; k < n; k++) step(s);
}

/** Tools besides the materials: they act on heat or clear cells. */
export const TOOLS = { TORCH: "torch", FROST: "frost", ERASE: "erase" };

/**
 * Paint a disc of radius r at (cx, cy). tool is a material id or one of TOOLS.
 * Materials only fill air, fire and steam (so a stroke never deletes what is
 * there); powders and liquids are sprinkled, not poured solid. Returns the
 * number of cells changed.
 */
export function paint(s, cx, cy, radius, tool) {
  const { w, h, mat, temp } = s;
  const rr = radius * radius + radius * 0.6;
  let changed = 0;
  const x0 = Math.max(0, Math.floor(cx - radius));
  const x1 = Math.min(w - 1, Math.ceil(cx + radius));
  const y0 = Math.max(0, Math.floor(cy - radius));
  const y1 = Math.min(h - 1, Math.ceil(cy + radius));
  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      const dx = x - cx;
      const dy = y - cy;
      const d2 = dx * dx + dy * dy;
      if (d2 > rr) continue;
      const i = y * w + x;
      if (tool === TOOLS.TORCH) {
        const fall = 1 - Math.sqrt(d2) / (radius + 1);
        temp[i] = Math.min(T_MAX, temp[i] + 60 * fall + 6);
        changed++;
      } else if (tool === TOOLS.FROST) {
        const fall = 1 - Math.sqrt(d2) / (radius + 1);
        temp[i] = Math.max(T_MIN, temp[i] - 30 * fall - 3);
        changed++;
      } else if (tool === TOOLS.ERASE) {
        if (mat[i] !== M.EMPTY) {
          place(s, i, M.EMPTY, s.ambient);
          changed++;
        }
      } else if (typeof tool === "number" && tool > 0 && tool < MAT_COUNT) {
        const here = KINDS[mat[i]];
        if (here !== KIND.AIR && here !== KIND.GAS) continue;
        const k = KINDS[tool];
        if ((k === KIND.POWDER || k === KIND.LIQUID || k === KIND.GAS) && s.rand() > 0.5) continue;
        place(s, i, tool);
        changed++;
      }
    }
  }
  return changed;
}

/**
 * Paint along the segment from (x0, y0) to (x1, y1), the start excluded (the
 * previous dab already covered it). Dabs sit at most half a brush apart, so
 * a fast stroke between two pointer events leaves no gaps.
 */
export function stroke(s, x0, y0, x1, y1, radius, tool) {
  const len = Math.hypot(x1 - x0, y1 - y0);
  const gap = Math.max(0.5, radius * 0.5);
  const n = Math.max(1, Math.ceil(len / gap));
  let changed = 0;
  for (let k = 1; k <= n; k++) {
    const f = k / n;
    changed += paint(s, x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, radius, tool);
  }
  return changed;
}

/** Fill every cell of a rectangle (inclusive) with m; used by scene builders. */
export function fillRect(s, x0, y0, x1, y1, m, t) {
  for (let y = Math.max(0, y0); y <= Math.min(s.h - 1, y1); y++) {
    for (let x = Math.max(0, x0); x <= Math.min(s.w - 1, x1); x++) place(s, y * s.w + x, m, t);
  }
}

export function setCell(s, x, y, m, t) {
  if (inside(s, x, y)) place(s, y * s.w + x, m, t);
}

/** How many cells hold each material. */
export function census(s) {
  const out = new Array(MAT_COUNT).fill(0);
  for (let i = 0; i < s.mat.length; i++) out[s.mat[i]]++;
  return out;
}

/** Total heat (temperature times heat capacity) over the grid. */
export function energy(s) {
  let e = 0;
  for (let i = 0; i < s.mat.length; i++) e += s.temp[i] * MATERIALS[s.mat[i]].cap;
  return e;
}
