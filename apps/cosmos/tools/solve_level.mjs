#!/usr/bin/env node
// Find a winning launch for a puzzle level file and print it.
//
//   node tools/solve_level.mjs ~/ForgeGameData/cosmos/levels/05-slingshot.json
//   node tools/solve_level.mjs LEVEL.json --write      # store reference and par in the file
//
// --write sets "reference" to the solution and "par" to 15% above its cost.
// Everything else in the file is left exactly as it was.

import { readFileSync, renameSync, writeFileSync } from "node:fs";

import { solveLevel } from "../static/core/levelgen.js";
import { checkLevel, playReference, prepareLevel, score } from "../static/core/puzzle.js";

const args = process.argv.slice(2);
const file = args.find((a) => !a.startsWith("--"));
if (!file) {
  console.error("Usage: node tools/solve_level.mjs LEVEL.json [--write]");
  process.exit(2);
}
const level = JSON.parse(readFileSync(file, "utf8"));
const problems = checkLevel(level);
if (problems.length) {
  console.error(`${file} is not a playable level:\n  ${problems.join("\n  ")}`);
  process.exit(1);
}
if (level.goal.type === "explore") {
  console.log("An explore level has no goal to solve.");
  process.exit(0);
}

const started = Date.now();
const found = solveLevel(level);
if (!found.solved) {
  console.error(`No winning launch found. Closest approach: ${found.closest.toFixed(3)}. Try widening launch.speed, adding fuel, or moving the target.`);
  process.exit(1);
}
const check = playReference(prepareLevel(level), found.reference);
const result = {
  reference: found.reference,
  cost: found.cost,
  suggested_par: Math.round(found.cost * 1.15 * 100) / 100,
  flight_time: found.time,
  replay: check.status,
  seconds_searching: (Date.now() - started) / 1000,
};
console.log(JSON.stringify(result, null, 2));

if (args.includes("--write")) {
  level.reference = found.reference;
  level.par = result.suggested_par;
  const prepared = prepareLevel(level);
  const stars = score(prepared, playReference(prepared, found.reference));
  if (!stars.finish) {
    console.error("The replay did not win; the file was not changed.");
    process.exit(1);
  }
  const tmp = `${file}.part`;
  writeFileSync(tmp, `${JSON.stringify(level, null, 2)}\n`);
  renameSync(tmp, file);
  console.log(`Wrote reference and par ${level.par} to ${file}.`);
}
