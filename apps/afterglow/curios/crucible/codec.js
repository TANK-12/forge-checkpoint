/* Crucible's keepsake format, version 1: a compact, exact copy of a world.
 *
 *   { v: 1, w, h, seed, tick, ambient,
 *     mat:  base64 of run-length pairs (count 1..255, material byte),
 *     heat: base64 of run-length triples (count, lo, hi) of round(temp) + 100,
 *     life: base64 of run-length triples of the burn counters }
 *
 * Temperatures are kept to the nearest degree. Shades are not stored: they
 * come back from the seed. The detail is not stored either: it follows from
 * the size (480 by 270 is detail 2, 720 by 405 detail 3, see sim.detailOf). No DOM: node tests import this.
 */

import { createWorld, reseed, detailOf, MAT_COUNT, T_MIN, T_MAX } from "./sim.js";

export const VERSION = 1;
const HEAT_OFFSET = 100;

/** What decode throws: always this, with a plain message, whatever the junk. */
export class SceneError extends Error {
  constructor(message) {
    super(message);
    this.name = "SceneError";
  }
}

function toBase64(bytes) {
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

function fromBase64(text) {
  if (typeof text !== "string") throw new SceneError("a scene field is missing");
  const bin = atob(text);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** Run-length code a list of values, each stored in `width` bytes (1 or 2). */
export function rle(values, width) {
  const out = [];
  let i = 0;
  while (i < values.length) {
    const v = values[i];
    let run = 1;
    while (run < 255 && i + run < values.length && values[i + run] === v) run++;
    out.push(run, v & 0xff);
    if (width === 2) out.push((v >> 8) & 0xff);
    i += run;
  }
  return Uint8Array.from(out);
}

export function unrle(bytes, width, count) {
  const out = new Uint16Array(count);
  let at = 0;
  const step = width + 1;
  if (bytes.length % step) throw new SceneError("a scene field is cut short");
  for (let i = 0; i < bytes.length; i += step) {
    const run = bytes[i];
    const v = width === 2 ? bytes[i + 1] | (bytes[i + 2] << 8) : bytes[i + 1];
    if (run === 0 || at + run > count) throw new SceneError("a scene field has the wrong length");
    out.fill(v, at, at + run);
    at += run;
  }
  if (at !== count) throw new SceneError("a scene field has the wrong length");
  return out;
}

export function encode(s) {
  const n = s.w * s.h;
  const heat = new Uint16Array(n);
  for (let i = 0; i < n; i++) heat[i] = Math.round(s.temp[i]) + HEAT_OFFSET;
  return {
    v: VERSION,
    w: s.w,
    h: s.h,
    seed: s.seed,
    tick: s.tick,
    ambient: s.ambient,
    mat: toBase64(rle(s.mat, 1)),
    heat: toBase64(rle(heat, 2)),
    life: toBase64(rle(s.life, 2)),
  };
}

/**
 * A world from encoded data. Bad data of any shape (wrong types, broken
 * base64, short or long runs, unknown materials) throws a SceneError with a
 * plain message, never a TypeError or a DOMException.
 */
export function decode(data) {
  try {
    return decodeOrThrow(data);
  } catch (e) {
    if (e instanceof SceneError) throw e;
    throw new SceneError("this scene is damaged and cannot be read");
  }
}

function decodeOrThrow(data) {
  if (!data || typeof data !== "object") throw new SceneError("this keepsake holds no scene");
  if (data.v !== VERSION) {
    const v = Number.isInteger(data.v) ? `version ${data.v}` : "in an unknown format";
    throw new SceneError(`this scene is ${v}, Crucible reads version ${VERSION}`);
  }
  const { w, h } = data;
  if (!Number.isInteger(w) || !Number.isInteger(h) || w < 8 || h < 8 || w * h > 400000) {
    throw new SceneError("this scene has an odd size");
  }
  const ambient = Number.isFinite(data.ambient) ? Math.min(T_MAX, Math.max(T_MIN, data.ambient)) : 20;
  // a 480 by 270 scene was kept at detail 2, and so on; any other size plays at detail 1
  const s = createWorld(Number(data.seed) >>> 0, w, h, ambient, detailOf(w, h));
  const n = w * h;
  const mat = unrle(fromBase64(data.mat), 1, n);
  const heat = unrle(fromBase64(data.heat), 2, n);
  const life = unrle(fromBase64(data.life), 2, n);
  for (let i = 0; i < n; i++) {
    if (mat[i] >= MAT_COUNT) throw new SceneError("this scene holds a material Crucible does not know");
    s.mat[i] = mat[i];
    s.temp[i] = Math.min(T_MAX, Math.max(T_MIN, heat[i] - HEAT_OFFSET));
    s.life[i] = life[i];
  }
  s.tick = Number.isInteger(data.tick) && data.tick >= 0 ? data.tick : 0;
  reseed(s);
  return s;
}
