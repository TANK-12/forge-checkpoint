/* Words for the garden: plant name suggestions, a crossed child's name, and
 * plain-language ages. Pure, so node tests it. */

import { rng, pick } from "../_kit/rng.js";

const FIRST = [
  "Ember", "Moss", "Dusk", "Lantern", "Copper", "Velvet", "Hollow", "Quiet",
  "Spark", "Tinder", "Amber", "Cinder", "Willow", "Thistle", "Comet", "Pewter",
  "Saffron", "Lumen", "Bramble", "Marrow", "Fennel", "Cobalt", "Juniper", "Wick",
];
const SECOND = [
  "fern", "bell", "wort", "spire", "curl", "frond", "sprig", "creeper",
  "lily", "briar", "plume", "thorn", "whisk", "tuft", "vine", "sedge",
];

/** A name for a new seed, fixed by the seed number. */
export function suggestName(seed) {
  const r = rng(seed >>> 0);
  return `${pick(r, FIRST)} ${pick(r, SECOND)}`;
}

export const MAX_NAME = 40; // server.py MAX_PLANT_NAME

/** A child's name from its parents: the front of one and the back of the other,
 *  never longer than a plant name may be. */
export function crossName(a, b) {
  const chars = Array.from(joinNames(a, b)); // code points, as Python counts
  return chars.length <= MAX_NAME ? chars.join("") : chars.slice(0, MAX_NAME).join("").trimEnd();
}

function joinNames(a, b) {
  const wa = String(a || "").trim().split(/\s+/).filter(Boolean);
  const wb = String(b || "").trim().split(/\s+/).filter(Boolean);
  if (!wa.length && !wb.length) return "Seedling";
  if (!wa.length) return wb.join(" ");
  if (!wb.length) return wa.join(" ");
  if (wa.length > 1 && wb.length > 1) return `${wa[0]} ${wb[wb.length - 1]}`;
  const x = wa[0];
  const y = wb[wb.length - 1];
  if (x.toLowerCase() === y.toLowerCase()) return `${x} the younger`;
  const xs = Array.from(x); // halve by code points so an emoji is never split
  const ys = Array.from(y);
  const left = xs.slice(0, Math.ceil(xs.length / 2)).join("");
  const right = ys.slice(Math.floor(ys.length / 2)).join("");
  const joined = left + right.toLowerCase();
  return joined.charAt(0).toUpperCase() + joined.slice(1);
}

/** "3 days 4 hours", "5 hours", "12 minutes", "just now"; a plant from the future says so. */
export function ageText(hours) {
  const n = Number(hours);
  if (Number.isFinite(n) && n < -1 / 60) return "not yet, the clock moved back";
  const h = Number.isFinite(n) ? Math.max(0, n) : 0;
  if (h < 1 / 60) return "just now";
  if (h < 1) {
    const m = Math.round(h * 60);
    return m < 60 ? `${m} minute${m === 1 ? "" : "s"}` : "1 hour";
  }
  const days = Math.floor(h / 24);
  const rest = Math.floor(h - days * 24);
  const d = days ? `${days} day${days === 1 ? "" : "s"}` : "";
  const r = rest ? `${rest} hour${rest === 1 ? "" : "s"}` : "";
  return [d, r].filter(Boolean).join(" ") || "1 day";
}

/** When the next generation is due, in words, or null when full grown. */
export function nextGrowthText(stage, maxGen, hoursPerGen) {
  if (stage >= maxGen) return null;
  const left = (Math.floor(stage) + 1 - stage) * hoursPerGen;
  return left < 1 / 60 ? "next generation any minute now" : `next generation in ${ageText(left)}`;
}

/** True when a string uses only L-system symbols with paired brackets. */
export function genomeOk(text) {
  if (!/^[A-Z+\-[\]]+$/.test(text)) return false;
  let depth = 0;
  for (const c of text) {
    depth += c === "[" ? 1 : c === "]" ? -1 : 0;
    if (depth < 0) return false;
  }
  return depth === 0;
}

/** "X = F[+X]FX | F[-X]FX" lines into rules, or an error string. */
export function parseRules(text) {
  const rules = {};
  for (const raw of String(text).split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const m = line.match(/^([A-Z])\s*=\s*(.+)$/);
    if (!m) return `"${line}" should look like X = F[+X]FX`;
    const variants = m[2].split("|").map((v) => v.replace(/\s+/g, "")).filter(Boolean);
    if (!variants.length || variants.length > 3) return `rule ${m[1]} needs 1 to 3 versions`;
    for (const v of variants) if (v.length > 60 || !genomeOk(v)) return `rule ${m[1]}: only F, capitals, + - [ ] with paired brackets`;
    rules[m[1]] = variants;
  }
  const n = Object.keys(rules).length;
  if (n < 1 || n > 3) return "write 1 to 3 rules";
  return rules;
}

export function rulesText(rules) {
  return Object.entries(rules)
    .map(([k, v]) => `${k} = ${v.join(" | ")}`)
    .join("\n");
}
