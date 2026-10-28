/* The map, the hunt and the measurements, after J. C. Sprott's "Strange
 * Attractors: Creating Patterns in Chaos". No DOM: node tests this file, and
 * server.py does the same sums in the same order so both sides agree.
 *
 * A 2D quadratic map:
 *   x' = a1 + a2 x + a3 x^2 + a4 x y + a5 y + a6 y^2
 *   y' = a7 + a8 x + a9 x^2 + a10 x y + a11 y + a12 y^2
 * Each coefficient is a letter A..Y standing for -1.2..1.2 in steps of 0.1,
 * so a whole attractor is a 12-letter code such as FIRCDERRPVLD.
 *
 * The Lyapunov exponent is in bits per iteration (log base 2 of the average
 * stretch of a tiny separation, renormalised every step; a step where the
 * separation is exactly zero gives no sample and a fresh direction).
 */

import { rng } from "../_kit/rng.js";

export const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXY";
export const ESCAPE = 1e6;
export const FIXED = 1e-10;
export const SEPARATION = 1e-6;
export const CHAOS = 0.005; // bits per iteration; below this it is not chaotic
export const ITERATIONS = 12000;
export const TRANSIENT = 1000;
export const SAMPLE = 800;
export const MIN_DIMENSION = 1.1;

/** The value a letter stands for, or NaN for anything else. */
export function letterValue(ch) {
  const i = LETTERS.indexOf(String(ch).toUpperCase());
  return i < 0 || String(ch).length !== 1 ? NaN : (i - 12) / 10;
}

/** True for a 12-letter code made only of A..Y (either case). */
export function isCode(text) {
  return typeof text === "string" && /^[A-Ya-y]{12}$/.test(text.trim());
}

/** The 12 coefficients of a code. Throws on anything that is not a code. */
export function decode(code) {
  if (!isCode(code)) throw new Error("a code is 12 letters from A to Y");
  return [...code.trim().toUpperCase()].map(letterValue);
}

/** The nearest code for any 12 numbers (values are clamped to -1.2..1.2). */
export function encode(coeffs) {
  return coeffs
    .map((v) => {
      const i = Math.round(Math.min(1.2, Math.max(-1.2, Number(v) || 0)) * 10) + 12;
      return LETTERS[i];
    })
    .join("");
}

/** True when every coefficient sits exactly on a letter. */
export function onGrid(coeffs) {
  return coeffs.every((v) => Math.abs(v * 10 - Math.round(v * 10)) < 1e-9 && Math.abs(v) <= 1.2 + 1e-9);
}

/** One step of the map. Returns [x', y']. */
export function step(a, x, y) {
  return [
    a[0] + a[1] * x + a[2] * x * x + a[3] * x * y + a[4] * y + a[5] * y * y,
    a[6] + a[7] * x + a[8] * x * x + a[9] * x * y + a[10] * y + a[11] * y * y,
  ];
}

/** Iterate from (0.05, 0.05) and classify. Returns
 *  {status, lyapunov, bounds, sample, at}: status is "chaotic", "loop"
 *  (quasi-periodic, exponent about 0), "cycle" (exponent below 0), "fixed"
 *  (settles on a point) or "escapes" (|x|+|y| beyond 1e6). bounds and sample
 *  only cover the iterations after the transient. */
export function analyse(a, { iterations = ITERATIONS, transient = TRANSIENT, sample = SAMPLE } = {}) {
  let x = 0.05;
  let y = 0.05;
  let xe = x + SEPARATION;
  let ye = y;
  let lsum = 0;
  let n = 0;
  let xmin = Infinity;
  let xmax = -Infinity;
  let ymin = Infinity;
  let ymax = -Infinity;
  const stride = Math.max(1, Math.floor((iterations - transient) / Math.max(1, sample)));
  const pts = [];
  for (let i = 1; i <= iterations; i++) {
    const xn = a[0] + a[1] * x + a[2] * x * x + a[3] * x * y + a[4] * y + a[5] * y * y;
    const yn = a[6] + a[7] * x + a[8] * x * x + a[9] * x * y + a[10] * y + a[11] * y * y;
    if (!(Math.abs(xn) + Math.abs(yn) <= ESCAPE)) {
      return { status: "escapes", lyapunov: null, bounds: null, sample: [], at: i };
    }
    if (Math.abs(xn - x) + Math.abs(yn - y) < FIXED) {
      return { status: "fixed", lyapunov: null, bounds: [xn, xn, yn, yn], sample: [[xn, yn]], at: i };
    }
    const xs = a[0] + a[1] * xe + a[2] * xe * xe + a[3] * xe * ye + a[4] * ye + a[5] * ye * ye;
    const ys = a[6] + a[7] * xe + a[8] * xe * xe + a[9] * xe * ye + a[10] * ye + a[11] * ye * ye;
    let dx = xs - xn;
    let dy = ys - yn;
    let d = Math.sqrt(dx * dx + dy * dy);
    // the neighbour landed exactly on the orbit: there is no stretch to
    // measure this step, so skip the sample and restart the neighbour a
    // quarter turn from where it was
    const met = d === 0;
    if (met) {
      dx = -(ye - y);
      dy = xe - x;
      d = Math.sqrt(dx * dx + dy * dy);
      if (d === 0) {
        dx = SEPARATION;
        dy = 0;
        d = SEPARATION;
      }
    }
    if (i > transient) {
      if (!met) {
        lsum += Math.log(d / SEPARATION);
        n += 1;
      }
      if (xn < xmin) xmin = xn;
      if (xn > xmax) xmax = xn;
      if (yn < ymin) ymin = yn;
      if (yn > ymax) ymax = yn;
      if ((i - transient) % stride === 0 && pts.length < sample) pts.push([xn, yn]);
    }
    xe = xn + (SEPARATION * dx) / Math.max(d, 1e-300);
    ye = yn + (SEPARATION * dy) / Math.max(d, 1e-300);
    x = xn;
    y = yn;
  }
  const lyapunov = n ? lsum / n / Math.LN2 : 0;
  let status = "chaotic";
  if (lyapunov < -CHAOS) status = "cycle";
  else if (lyapunov <= CHAOS) status = "loop";
  return { status, lyapunov, bounds: [xmin, xmax, ymin, ymax], sample: pts, at: iterations };
}

/** Correlation dimension (Grassberger-Procaccia) from two radii, 2% and 20%
 *  of the larger side of the bounds. null when there is too little to say. */
export function dimension(sample, bounds) {
  if (!bounds || sample.length < 50) return null;
  const size = Math.max(bounds[1] - bounds[0], bounds[3] - bounds[2]);
  if (!(size > 0)) return null;
  const r1 = 0.02 * size;
  const r2 = 0.2 * size;
  const q1 = r1 * r1;
  const q2 = r2 * r2;
  let c1 = 0;
  let c2 = 0;
  for (let i = 0; i < sample.length; i++) {
    const [xi, yi] = sample[i];
    for (let j = i + 1; j < sample.length; j++) {
      const dx = sample[j][0] - xi;
      const dy = sample[j][1] - yi;
      const q = dx * dx + dy * dy;
      if (q < q2) {
        c2 += 1;
        if (q < q1) c1 += 1;
      }
    }
  }
  if (c1 < 10) return null;
  return Math.log(c2 / c1) / Math.log(r2 / r1);
}

/** A random code from a seeded stream: 12 draws, one per letter. */
export function randomCode(r) {
  let code = "";
  for (let i = 0; i < 12; i++) code += LETTERS[Math.floor(r() * 25)];
  return code;
}

/** Try one candidate. accepted when chaotic and at least minDimension. */
export function tryCode(code, { minDimension = MIN_DIMENSION } = {}) {
  const coeffs = decode(code);
  const result = analyse(coeffs);
  let dim = null;
  if (result.status === "chaotic") dim = dimension(result.sample, result.bounds);
  const accepted = result.status === "chaotic" && dim !== null && dim >= minDimension;
  return { code, coeffs, result, dimension: dim, accepted };
}

/** A hunt that can be run a slice at a time: next() tries one code. */
export function hunter(seed, opts = {}) {
  const r = rng(seed);
  let tried = 0;
  return {
    get tried() {
      return tried;
    },
    next() {
      tried += 1;
      return tryCode(randomCode(r), opts);
    },
  };
}

/** The first accepted find from a seed (what `play.py attractors hunt
 *  --seed N` prints too). null if none within maxTries. */
export function hunt(seed, { maxTries = 20000, ...opts } = {}) {
  const h = hunter(seed, opts);
  while (h.tried < maxTries) {
    const found = h.next();
    if (found.accepted) return { ...found, tried: h.tried };
  }
  return null;
}

/** Two plain lines about a find. Python's describe() says the same. */
export function describe(lyapunov, dim) {
  const l = lyapunov === null || lyapunov === undefined ? "?" : lyapunov.toFixed(3);
  const d = dim === null || dim === undefined ? "unknown" : `about ${dim.toFixed(2)}`;
  const first = `Lyapunov exponent ${l} bits per iteration, correlation dimension ${d}.`;
  let shape = "a dusting of points";
  if (dim !== null && dim !== undefined) {
    if (dim < 1.15) shape = "fine threads, nearly a curve";
    else if (dim < 1.4) shape = "folded ribbons";
    else if (dim < 1.7) shape = "a smoky cloud of folds";
    else shape = "a dense veil that almost fills its patch";
  }
  let pace = "and drifts apart slowly";
  if (lyapunov !== null && lyapunov !== undefined) {
    if (lyapunov >= 0.4) pace = "and scrambles neighbours fast";
    else if (lyapunov >= 0.15) pace = "and stirs at a steady pace";
  }
  return [first, `It looks like ${shape}, ${pace}.`];
}

/** The status in plain words, for the badge. */
export const STATUS_WORDS = {
  chaotic: "chaotic",
  loop: "a closed loop, not chaotic",
  cycle: "a cycle of points, not chaotic",
  fixed: "settles to one point",
  escapes: "flies off to infinity",
};
