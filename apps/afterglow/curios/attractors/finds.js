/* The curio's bookkeeping, kept free of the DOM so node can test it: the
 * strip of recent finds, what a keepsake stores and how it is read back, the
 * slow drift of one coefficient, and hunting a slice at a time. */

import { decode, encode, isCode, onGrid, analyse, dimension } from "./sprott.js";
import { PALETTES } from "./render.js";

export const DEFAULTS = { palette: "ember", exposure: 1.25, gamma: 1.25 };
export const LIMITS = { exposure: [0.3, 3], gamma: [0.5, 3], coeff: [-1.2, 1.2] };

const clamp = (v, [lo, hi]) => Math.min(hi, Math.max(lo, v));

/** A stable key for a set of coefficients (same map, same key). */
export function keyOf(coeffs) {
  return coeffs.map((v) => Number(v).toFixed(4)).join(",");
}

/** The code to show: the exact code when every value is on a letter,
 *  otherwise the nearest code with a leading "≈". */
export function codeLabel(coeffs) {
  return onGrid(coeffs) ? encode(coeffs) : `≈${encode(coeffs)}`;
}

/** Newest first, no repeats, at most cap. Returns a new list. */
export function addRecent(list, find, cap = 8) {
  const key = keyOf(find.coeffs);
  return [find, ...list.filter((f) => keyOf(f.coeffs) !== key)].slice(0, cap);
}

/** The neighbour of the current find in the recent list (dir -1 or +1),
 *  wrapping round. null when the list is empty. */
export function neighbour(list, coeffs, dir) {
  if (!list.length) return null;
  const at = list.findIndex((f) => keyOf(f.coeffs) === keyOf(coeffs));
  if (at < 0) return list[0];
  return list[(at + dir + list.length) % list.length];
}

/** What a keepsake stores. */
export function keepData(s) {
  return {
    code: encode(s.coeffs),
    coeffs: s.coeffs.map((v) => Number(Number(v).toFixed(6))),
    palette: s.palette,
    exposure: s.exposure,
    gamma: s.gamma,
    lyapunov: s.lyapunov ?? null,
    dimension: s.dimension ?? null,
  };
}

/** What to keep for the attractor on screen, measured afresh: a drift moves
 *  the coefficients on without a full measurement. Returns {data, measured}. */
export function keepNow(s) {
  const measured = measure(s.coeffs);
  const data = keepData({ ...s, lyapunov: measured.info.lyapunov, dimension: measured.dimension });
  return { data, measured };
}

/** Copy the code of coeffs with clipboard.writeText; when there is no
 *  clipboard or it refuses, select(code) so Ctrl+C can do it. Resolves to the
 *  words for a toast. */
export async function copyCode(coeffs, clipboard, select) {
  const code = encode(coeffs);
  const what = onGrid(coeffs) ? code : `the nearest code, ${code}`;
  try {
    if (!clipboard || typeof clipboard.writeText !== "function") throw new Error("no clipboard");
    await clipboard.writeText(code);
    return `Copied ${what}.`;
  } catch {
    select(code);
    return `Selected ${what}: press Ctrl+C to copy it.`;
  }
}

/** Read a keepsake's data back into settings, filling gaps with defaults.
 *  Throws when there is neither a usable coeffs list nor a code. */
export function settingsFrom(data) {
  const d = data && typeof data === "object" ? data : {};
  let coeffs = null;
  if (Array.isArray(d.coeffs) && d.coeffs.length === 12 && d.coeffs.every((v) => Number.isFinite(v))) {
    coeffs = d.coeffs.map((v) => clamp(v, LIMITS.coeff));
  } else if (isCode(d.code)) {
    coeffs = decode(d.code);
  } else {
    throw new Error("this keepsake has no code or coefficients");
  }
  const num = (v, fallback, lim) => (Number.isFinite(v) ? clamp(v, lim) : fallback);
  return {
    coeffs,
    palette: Object.hasOwn(PALETTES, d.palette) ? d.palette : DEFAULTS.palette,
    exposure: num(d.exposure, DEFAULTS.exposure, LIMITS.exposure),
    gamma: num(d.gamma, DEFAULTS.gamma, LIMITS.gamma),
  };
}

/** Measure a set of coefficients: the analysis plus the dimension when chaotic. */
export function measure(coeffs, opts) {
  const info = analyse(coeffs, opts);
  const dim = info.status === "chaotic" ? dimension(info.sample, info.bounds) : null;
  return { info, dimension: dim };
}

/** A fresh drift: coefficient k wanders around its current value. */
export function startDrift(coeffs, k = 0) {
  return { k, base: coeffs[k], phase: 0, dir: 1, amp: 0.08, bounces: 0 };
}

/** Move the drift on by dt seconds at speed (radians per second). The new
 *  value is only taken while isChaotic(newCoeffs) says yes; otherwise the
 *  drift turns round, and after 3 bounces in a row it hands over to another
 *  coefficient. Returns {coeffs, drift, moved}. */
export function driftStep(drift, coeffs, dt, speed, isChaotic) {
  const phase = drift.phase + dt * speed * drift.dir;
  const value = clamp(drift.base + drift.amp * Math.sin(phase), LIMITS.coeff);
  const next = coeffs.slice();
  next[drift.k] = value;
  if (isChaotic(next)) {
    return { coeffs: next, drift: { ...drift, phase, bounces: 0 }, moved: true };
  }
  const bounces = drift.bounces + 1;
  if (bounces >= 3) {
    const k = (drift.k + 5) % 12;
    return { coeffs, drift: { ...startDrift(coeffs, k) }, moved: false };
  }
  return { coeffs, drift: { ...drift, dir: -drift.dir, bounces }, moved: false };
}

/** An empty tally of what the hunt has seen. */
export function newTally() {
  return { tried: 0, escapes: 0, fixed: 0, cycle: 0, loop: 0, chaotic: 0 };
}

/** Try codes from a hunter until one is accepted, maxCodes are tried, or
 *  budgetMs has passed (now() is the clock). Updates tally in place.
 *  Returns {found, last}: found is the accepted try or null, last the last
 *  try (for the flickering code while hunting). */
export function huntSlice(h, tally, { maxCodes = 4, budgetMs = 3, now = () => performance.now() } = {}) {
  const t0 = now();
  let last = null;
  for (let n = 0; n < maxCodes; n++) {
    last = h.next();
    tally.tried += 1;
    tally[last.result.status] += 1;
    if (last.accepted) return { found: last, last };
    if (now() - t0 > budgetMs) break;
  }
  return { found: null, last };
}

/** The tally in plain words. */
export function tallyText(t) {
  if (!t.tried) return "";
  const parts = [];
  if (t.escapes) parts.push(`${t.escapes} flew off`);
  if (t.fixed) parts.push(`${t.fixed} settled`);
  if (t.cycle + t.loop) parts.push(`${t.cycle + t.loop} went round in circles`);
  if (t.chaotic) parts.push(`${t.chaotic} chaotic`);
  const codes = t.tried === 1 ? "1 code" : `${t.tried.toLocaleString("en")} codes`;
  return `Tried ${codes}: ${parts.join(", ")}.`;
}
