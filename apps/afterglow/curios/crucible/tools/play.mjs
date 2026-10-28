/* Runs a Crucible scene headless for server.py (play.py crucible ...).
 *
 *   node tools/play.mjs <scene> <steps> [cols]
 *
 * Prints one JSON object: the scene's census before and after, the events
 * (cells melted, quenched, fused, lit, boiled), a small text picture and the
 * encoded world, so the caller can keep it. No DOM, nothing written.
 */

import * as S from "../sim.js";
import * as SC from "../scenes.js";
import { encode } from "../codec.js";

const BUILDERS = {
  starter: () => SC.starter(),
  showcase: () => SC.showcase(),
  ...Object.fromEntries(SC.SEEDS.map((seed) => [seed.slug, seed.build])),
};

// one character per material, then hot cells drawn brighter
const GLYPH = {
  [S.M.EMPTY]: " ",
  [S.M.STONE]: "#",
  [S.M.SAND]: ".",
  [S.M.WATER]: "~",
  [S.M.ORE]: "o",
  [S.M.MOLTEN]: "@",
  [S.M.IRON]: "I",
  [S.M.COAL]: ":",
  [S.M.EMBER]: "*",
  [S.M.FIRE]: "^",
  [S.M.STEAM]: "'",
  [S.M.ICE]: "=",
  [S.M.WOOD]: "|",
  [S.M.GLASS]: "g",
  [S.M.SHOT]: "i",
};

/** A text picture: each character stands for a block, showing its most common non-air material. */
export function picture(s, cols = 80) {
  const bx = Math.max(1, Math.ceil(s.w / cols));
  const by = bx * 2; // terminal characters are about twice as tall as wide
  const lines = [];
  for (let y0 = 0; y0 < s.h; y0 += by) {
    let line = "";
    for (let x0 = 0; x0 < s.w; x0 += bx) {
      const count = new Array(S.MAT_COUNT).fill(0);
      for (let y = y0; y < Math.min(s.h, y0 + by); y++) {
        for (let x = x0; x < Math.min(s.w, x0 + bx); x++) count[s.mat[y * s.w + x]]++;
      }
      let best = 0;
      for (let m = 1; m < S.MAT_COUNT; m++) if (count[m] > count[best] || (best === 0 && count[m] * 3 >= bx * by)) best = m;
      line += GLYPH[best];
    }
    lines.push(line.replace(/\s+$/, ""));
  }
  return lines;
}

function named(census) {
  const out = {};
  census.forEach((n, m) => {
    if (n && m !== S.M.EMPTY) out[S.MATERIALS[m].label] = n;
  });
  return out;
}

function main(argv) {
  const [scene, stepsText, colsText] = argv;
  const build = BUILDERS[scene];
  if (!build) {
    process.stdout.write(JSON.stringify({ error: `no scene called ${scene}`, scenes: Object.keys(BUILDERS) }) + "\n");
    return 2;
  }
  const steps = Math.max(0, Math.min(20000, Number.parseInt(stepsText ?? "600", 10) || 0));
  const cols = Math.max(20, Math.min(240, Number.parseInt(colsText ?? "80", 10) || 80));
  const s = build();
  const before = named(S.census(s));
  const t0 = performance.now();
  S.stepN(s, steps);
  const ms = performance.now() - t0;
  let hottest = -Infinity;
  for (let i = 0; i < s.temp.length; i++) if (s.mat[i] !== S.M.EMPTY && s.temp[i] > hottest) hottest = s.temp[i];
  const out = {
    scene,
    steps,
    ms_per_step: steps ? ms / steps : 0,
    before,
    after: named(S.census(s)),
    events: s.events,
    hottest: Math.round(hottest),
    picture: picture(s, cols),
    data: encode(s),
  };
  process.stdout.write(JSON.stringify(out) + "\n");
  return 0;
}

if (import.meta.url === `file://${process.argv[1]}`) process.exitCode = main(process.argv.slice(2));
