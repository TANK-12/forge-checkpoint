/* Garden's plant logic: L-system expansion, growth with real time, and turtle
 * geometry. No DOM, so node tests it as it is. server.py mirrors expand(),
 * effectiveMaxGen(), growthStage() and the genome checks in words.js;
 * tests/test_agree.py runs tests/agree.mjs to pin both sides to the same
 * answers.
 *
 * A genome:
 *   axiom        start string, e.g. "X"
 *   rules        {symbol: [variant, ...]}, 1-3 symbols, 1-3 variants each
 *                (more than one variant makes the rule stochastic)
 *   angle        branch angle in degrees
 *   len_decay    segment length multiplier per bracket depth
 *   width_decay  stem width multiplier per bracket depth
 *   jitter       random turn added to each + and -, in degrees
 *   hues         {stem, leaf, flower}, 0-360
 *   flower       "star" | "round" | "bell" | "spark"
 *   bloom        share of buds that flower (0-0.6)
 *   max_gen      how many generations it grows to
 *   hours_per_gen  real hours per generation
 *   seed         32-bit seed for stochastic rules and jitter
 *
 * Symbols: F draws forward, + and - turn, [ and ] push and pop, any other
 * capital letter is a bud (a leaf or a flower at the tip).
 */

import { rng, hashString } from "../_kit/rng.js";

export const MAX_LEN = 20000; // longest string a plant may expand to
export const MAX_SEGMENTS = 4000; // most F segments a plant may have
export const DEPTHS = 8; // stem width levels kept apart for batched drawing
export const BUD = 8; // numbers per bud in turtle().buds

/** Expand towards generation gen. fresh[i] is 1 for tokens new in the last
 *  step; of a rewritten symbol's own letter in its variant, the last occurrence
 *  inherits the parent's flag (so the apex carries on rather than popping).
 *  Growth stops at the last generation within MAX_LEN and MAX_SEGMENTS, and a
 *  step is abandoned as soon as it passes them, so no genome can blow up:
 *  the returned gen is the generation actually reached (at most gen). */
export function expand(genome, gen) {
  const r = rng(genome.seed >>> 0);
  let str = genome.axiom;
  let fresh = new Uint8Array(str.length).fill(1);
  let reached = 0;
  for (let g = 0; g < gen; g++) {
    const out = [];
    const flags = [];
    let segments = 0;
    let over = false;
    for (let i = 0; i < str.length && !over; i++) {
      const c = str[i];
      const variants = Object.hasOwn(genome.rules, c) ? genome.rules[c] : null;
      if (!variants || !variants.length) {
        out.push(c);
        flags.push(0);
        if (c === "F") segments++;
      } else {
        const v = variants.length === 1 ? variants[0] : variants[Math.floor(r() * variants.length)];
        const keep = v.lastIndexOf(c);
        for (let k = 0; k < v.length; k++) {
          out.push(v[k]);
          flags.push(k === keep ? 0 : 1);
          if (v[k] === "F") segments++;
        }
      }
      over = out.length > MAX_LEN || segments > MAX_SEGMENTS;
    }
    if (over) break;
    str = out.join("");
    fresh = Uint8Array.from(flags);
    reached = g + 1;
  }
  return { str, fresh, gen: reached };
}

export function countF(str) {
  let n = 0;
  for (let i = 0; i < str.length; i++) if (str.charCodeAt(i) === 70) n++;
  return n;
}

/** The highest generation, at most max_gen, whose string stays within the caps. */
export function effectiveMaxGen(genome) {
  return expand(genome, Math.max(0, Math.floor(genome.max_gen) || 0)).gen;
}

/** Hours a plant has been growing at nowMs (head start included). */
export function hoursGrown(plant, nowMs, aheadHours = 0) {
  const planted = Date.parse(plant.planted);
  const h = (nowMs - planted) / 3600000 + (plant.head_start_hours || 0) + aheadHours;
  return Number.isFinite(h) ? Math.max(0, h) : 0;
}

/** Growth stage: generations grown, a float in [0, maxGen]. */
export function growthStage(plant, nowMs, maxGen, aheadHours = 0) {
  const hpg = Math.max(0.1, plant.genome.hours_per_gen || 6);
  return Math.min(maxGen, hoursGrown(plant, nowMs, aheadHours) / hpg);
}

export function smooth(t) {
  const x = Math.min(1, Math.max(0, t));
  return x * x * (3 - 2 * x);
}

/** Which generation to draw and how far its new growth has come. */
export function stageParts(stage, maxGen) {
  const n = Math.floor(stage);
  const f = stage - n;
  if (n >= maxGen || f < 1e-6) return { gen: Math.min(n, maxGen), grow: 1 };
  return { gen: n + 1, grow: smooth(f) };
}

/** How open the flowers are: they bloom over the last part of growing. */
export function bloomOpen(stage, maxGen) {
  if (maxGen <= 0) return 0;
  return smooth((stage - maxGen * 0.55) / Math.max(0.6, maxGen * 0.35));
}

/** Turtle geometry for a string. Units: the first segment is 1 long; y is up.
 *  Returns segment lists per depth level ([x0, y0, x1, y1, steps] flat),
 *  buds [x, y, heading, size, depth, kind(0 leaf, 1 flower), hash, steps], bounds
 *  and the deepest step count. grow scales fresh segments and buds. */
export function turtle(genome, str, fresh, grow = 1) {
  const r = rng((genome.seed ^ 0x9e3779b9) >>> 0);
  const segs = Array.from({ length: DEPTHS }, () => []);
  const buds = [];
  const rad = Math.PI / 180;
  const ang = genome.angle;
  const jit = genome.jitter || 0;
  const bloom = genome.bloom || 0;
  let x = 0;
  let y = 0;
  let h = 90;
  let depth = 0;
  let steps = 0;
  const stack = [];
  let minX = 0;
  let maxX = 0;
  let maxY = 0;
  let maxSteps = 0;
  let budIndex = 0;
  for (let i = 0; i < str.length; i++) {
    const c = str[i];
    if (c === "F") {
      const len = Math.pow(genome.len_decay, depth) * (0.94 + r() * 0.12) * (fresh[i] ? grow : 1);
      const nx = x + Math.cos(h * rad) * len;
      const ny = y + Math.sin(h * rad) * len;
      if (len > 1e-4) {
        segs[Math.min(depth, DEPTHS - 1)].push(x, y, nx, ny, steps);
        steps += 1;
      }
      x = nx;
      y = ny;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
      if (steps > maxSteps) maxSteps = steps;
    } else if (c === "+") {
      h += ang + jit * (r() * 2 - 1);
    } else if (c === "-") {
      h -= ang + jit * (r() * 2 - 1);
    } else if (c === "[") {
      stack.push([x, y, h, depth, steps]);
      depth += 1;
    } else if (c === "]") {
      if (stack.length) [x, y, h, depth, steps] = stack.pop();
    } else if (c >= "A" && c <= "Z") {
      const hash = hashString(`${genome.seed}:${budIndex}`) / 4294967296;
      budIndex += 1;
      const size = fresh[i] ? grow : 1;
      if (size <= 0.01) continue;
      const kind = depth >= 1 && hash < bloom ? 1 : 0;
      buds.push(x, y, h, size, depth, kind, hash, steps);
    }
  }
  return { segs, buds, minX, maxX, maxY, maxSteps };
}

/** Geometry for a plant at a growth stage (cache the result). */
export function plantGeometry(genome, stage, maxGen) {
  const { gen, grow } = stageParts(stage, maxGen);
  const { str, fresh } = expand(genome, gen);
  const geo = turtle(genome, str, fresh, grow);
  geo.gen = gen;
  geo.grow = grow;
  geo.bloom = bloomOpen(stage, maxGen);
  return geo;
}

/** Bounds of the full-grown plant, used to fix its scale for its whole life. */
export function fullBounds(genome, maxGen) {
  const { str, fresh } = expand(genome, maxGen);
  const g = turtle(genome, str, fresh, 1);
  return { minX: g.minX, maxX: g.maxX, maxY: Math.max(g.maxY, 1) };
}
