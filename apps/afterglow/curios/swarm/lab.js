/* Swarm without a screen: run a rule table for a while and measure it, or roll
 * many tables and rank them. play.py's swarm commands reach this through
 * cli.mjs; node --test imports it directly. No DOM.
 *
 * Two measures, the same ones the logbook page used:
 *   gathered  neighbours within half a reach, over an even scatter (clumping)
 *   speed     mean speed in screen heights a second (meanSpeed)
 * A swarm counts as gathered above GATHERED and as moving above MOVING. The
 * logbook's settled swarms measured about 0.002 and its chases about 0.09,
 * so MOVING sits well clear of both.
 */

import { DEFAULTS, cleanRules, clumping, createSwarm, meanSpeed, mirrorRules, randomRules, step } from "./sim.js";
import { rng } from "../_kit/rng.js";

export const GATHERED = 2;
export const MOVING = 0.01;
export const DT = 1 / 60;
const MAX_SECONDS = 120;
const MAX_TRIES = 200;

/** What a pair of measures means, in words. Order is the hunt's ranking. */
export const KINDS = [
  { id: "chase", words: "a chase: gathered into shapes and still moving" },
  { id: "settled", words: "settled: gathered into shapes that have stopped" },
  { id: "mist", words: "a drifting mist: moving, but not gathered" },
  { id: "haze", words: "a still haze: neither gathered nor moving" },
];

export function kindOf(gathered, speed) {
  const g = gathered >= GATHERED;
  const m = speed >= MOVING;
  return KINDS[g && m ? 0 : g ? 1 : m ? 2 : 3];
}

const round = (v, places) => Number(v.toFixed(places));
const clampNum = (v, lo, hi, fallback) => {
  const n = Number(v);
  return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : fallback;
};

/** Run one rule table for `seconds` of its own time at 60 steps a second,
 *  measuring every `every` seconds. Returns the cleaned rules, the timeline,
 *  the last measures and the world itself (for a picture). */
export function measure(data, { seconds = 10, every = 1, aspect = 16 / 9, mirror = false } = {}) {
  const rules = cleanRules(data);
  if (mirror) rules.matrix = mirrorRules(rules.matrix, rules.colours);
  const secs = clampNum(seconds, DT, MAX_SECONDS, 10);
  const steps = Math.max(1, Math.round(secs / DT));
  const per = Math.max(1, Math.round(clampNum(every, DT, MAX_SECONDS, 1) / DT));
  const sw = createSwarm(rules, aspect);
  const frames = [];
  for (let s = 1; s <= steps; s++) {
    step(sw, rules, DT);
    if (s % per === 0 || s === steps) {
      frames.push({ t: round(s * DT, 2), gathered: round(clumping(sw, rules.reach), 2), speed: round(meanSpeed(sw), 4) });
    }
  }
  const last = frames[frames.length - 1];
  const kind = kindOf(last.gathered, last.speed);
  return { rules, frames, gathered: last.gathered, speed: last.speed, kind: kind.id, words: kind.words, sw };
}

/** Roll `tries` random tables (seeds seed, seed + 1, ...), run each and rank
 *  them: chases first, then settled shapes, mist, haze; more gathered first
 *  within a kind. The same arguments always give the same answer. */
export function hunt({ tries = 8, seconds = 8, colours = DEFAULTS.colours, count = DEFAULTS.count, seed = 1, mirror = false, aspect = 16 / 9 } = {}) {
  const n = Math.round(clampNum(tries, 1, MAX_TRIES, 8));
  const base = Math.abs(Math.floor(clampNum(seed, 0, 4294967295, 1)));
  const rows = [];
  for (let i = 0; i < n; i++) {
    const s = (base + i) % 4294967296;
    const k = cleanRules({ colours }).colours;
    const data = { ...DEFAULTS, colours: k, count, matrix: randomRules(rng(s), k), seed: s };
    const m = measure(data, { seconds, every: seconds, aspect, mirror });
    rows.push({ seed: s, rules: m.rules, gathered: m.gathered, speed: m.speed, kind: m.kind, words: m.words, sw: m.sw });
  }
  const rank = (r) => KINDS.findIndex((k) => k.id === r.kind);
  rows.sort((a, b) => rank(a) - rank(b) || b.gathered - a.gathered || a.seed - b.seed);
  return rows;
}

/** A world's particles as plain numbers, for a picture drawn elsewhere. */
export function points(sw, places = 4) {
  return {
    W: round(sw.W, 6),
    H: round(sw.H, 6),
    k: sw.k,
    x: Array.from(sw.x.subarray(0, sw.n), (v) => round(v, places)),
    y: Array.from(sw.y.subarray(0, sw.n), (v) => round(v, places)),
  };
}
