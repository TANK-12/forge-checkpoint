/* Glyphs: Compose, a small seeded grammar that writes formulas which tend to
 * look good. Each recipe is a known-good shape (ripples, spirals, weaves,
 * bands, clouds, stencils, lace, rain) with its knobs drawn from short lists
 * of numbers that read well, plus a generated title. No DOM.
 *
 * server.py has a line-for-line copy (same mulberry32, same draws in the same
 * order), so compose(seed) gives the same piece in the browser and in a
 * terminal; the agreement sweep in tests/test_glyphs.py checks hundreds.
 */

import { rng } from "../_kit/rng.js";

const pick = (r, list) => list[Math.floor(r() * list.length)];

const SPEEDS = ["0.6", "1", "1.5", "2", "3"];
const MOODS = {
  slow: ["Slow", "Patient", "Sleepy", "Quiet"],
  mid: ["Steady", "Easy", "Warm", "Little"],
  fast: ["Quick", "Restless", "Bright", "Giddy"],
};
const NUMBER_WORDS = ["", "One", "Two", "Three", "Four", "Five"];
const BANDS = [
  ["x", "current"],
  ["y", "staircase"],
  ["x + y", "slope"],
  ["x - y", "drift"],
  ["abs(u) + abs(v)", "diamond"],
  ["max(abs(u), abs(v))", "frame"],
  ["u*v/4", "saddle"],
];
const GATES = [
  "sin(r*0.8 - t*S)",
  "sin(a*3 + r*0.5 - t*S)",
  "sin(x*0.6 + t*S) * cos(y*0.6 - t*S)",
  "noise(x/4, y/4, t*S/2)",
];
const LACES = ["x & y", "x & (y + floor(t*S))", "(x + floor(t*S)) & y", "(x + y) & (x - y + n)"];

function mood(r, s) {
  const k = Number(s);
  return pick(r, k < 1 ? MOODS.slow : k < 2 ? MOODS.mid : MOODS.fast);
}

const RECIPES = {
  ripple(r, s) {
    const k = pick(r, ["0.6", "0.8", "1", "1.3"]);
    const dir = pick(r, ["-", "+"]);
    let body = `sin(r*${k} ${dir} t*${s})`;
    if (r() < 0.5) body += ` * (1 - r/${pick(r, ["8", "10", "12"])})`;
    return [body, `${mood(r, s)} ${pick(r, ["ripple", "pond", "tide", "echo"])}`];
  },
  spiral(r, s) {
    const arms = pick(r, ["1", "2", "3", "4", "5"]);
    const k = pick(r, ["0.4", "0.6", "0.9"]);
    const turn = pick(r, ["+", "-"]);
    const body = `sin(a*${arms} ${turn} r*${k} - t*${s})`;
    const noun = pick(r, ["pinwheel", "whorl", "spiral", "galaxy"]);
    if (arms === "1") return [body, `${mood(r, s)} ${noun}`];
    return [body, `${NUMBER_WORDS[Number(arms)]}-arm ${noun}`];
  },
  weave(r, s) {
    const k1 = pick(r, ["0.5", "0.7", "0.9", "1.2"]);
    const k2 = pick(r, ["0.5", "0.7", "0.9", "1.2"]);
    const s2 = pick(r, SPEEDS);
    const body = `sin(x*${k1} + t*${s}) * cos(y*${k2} - t*${s2})`;
    return [body, `${mood(r, s)} ${pick(r, ["weave", "plaid", "lattice", "quilt"])}`];
  },
  bands(r, s) {
    const [dir, noun] = pick(r, BANDS);
    const k = pick(r, ["0.5", "0.8", "1.2"]);
    return [`sin((${dir})*${k} - t*${s})`, `${mood(r, s)} ${noun}`];
  },
  clouds(r, s) {
    const k = pick(r, ["3", "4", "6"]);
    const gain = pick(r, ["2", "2.5", "3"]);
    const body = `noise(x/${k}, y/${k}, t*${s}/2) * ${gain}`;
    return [body, `${mood(r, s)} ${pick(r, ["weather", "smoke", "clouds", "fog"])}`];
  },
  gate(r, s) {
    const inner = pick(r, GATES).replaceAll("S", s);
    const th = pick(r, ["0", "0.3", "0.5"]);
    const low = pick(r, ["0", "-0.4", "-1"]);
    const body = `${inner} > ${th} ? 1 : ${low}`;
    return [body, `${mood(r, s)} ${pick(r, ["signal", "stencil", "switchboard", "code"])}`];
  },
  lace(r, s) {
    const cond = pick(r, LACES).replaceAll("S", s);
    const k = pick(r, ["0.3", "0.5", "0.8"]);
    const low = pick(r, ["0", "-0.2"]);
    const body = `(${cond}) == 0 ? sin(t*${s} - r*${k}) : ${low}`;
    return [body, `${mood(r, s)} ${pick(r, ["lace", "crumbs", "triangles", "frost"])}`];
  },
  rain(r) {
    const s = pick(r, ["4", "6", "9"]);
    const gap = pick(r, ["4", "8", "12"]);
    const len = pick(r, ["3", "4", "6"]);
    const body = `max(0, 1 - mod(t*${s}*(1 + rand(x)) + rand(x + 50)*n - y, n + ${gap})/${len})`;
    return [body, `${mood(r, s)} ${pick(r, ["rain", "drizzle", "downpour", "monsoon"])}`];
  },
};

export const RECIPE_NAMES = Object.keys(RECIPES);

/** A new piece from a seed: {formula, title, seed, recipe}. */
export function compose(seed) {
  seed = seed >>> 0;
  const r = rng(seed);
  const recipe = pick(r, RECIPE_NAMES);
  const s = pick(r, SPEEDS);
  const [formula, title] = RECIPES[recipe](r, s);
  return { formula, title, seed, recipe };
}
