/* Seeded randomness for curios: the same seed always gives the same world,
 * so a keepsake can store a seed instead of a whole state, and tests can pin
 * an outcome. mulberry32 for the stream, FNV-1a to turn text into a seed.
 * No DOM: node imports this file as it is.
 */

/** A function returning floats in [0, 1), fixed by the seed. */
export function rng(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** A 32-bit seed from any text. */
export function hashString(text) {
  let h = 0x811c9dc5;
  for (const ch of String(text)) {
    h ^= ch.codePointAt(0);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

/** An integer in [lo, hi], both ends included. */
export function randInt(r, lo, hi) {
  return lo + Math.floor(r() * (hi - lo + 1));
}

export function pick(r, list) {
  return list[Math.floor(r() * list.length)];
}

/** A fresh seed for "surprise me" buttons. */
export function freshSeed() {
  return (Math.random() * 4294967296) >>> 0;
}
