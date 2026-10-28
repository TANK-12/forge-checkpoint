/* Writes seeds/<slug>.json from scenes.SEEDS. The scenes are built from code,
 * so running this again gives the same files byte for byte.
 *
 *   node curios/crucible/tools/make_seeds.mjs
 */

import { writeFileSync, mkdirSync } from "node:fs";
import { SEEDS } from "../scenes.js";
import { encode, decode } from "../codec.js";

const MADE = "2026-10-09T10:14:00";
const dir = new URL("../seeds/", import.meta.url);
mkdirSync(dir, { recursive: true });

for (const seed of SEEDS) {
  const data = encode(seed.build());
  decode(data); // a seed that cannot be read back is never written
  const row = { name: seed.name, note: seed.note, author: "Claude", made: MADE, data };
  const text = JSON.stringify(row, null, 1) + "\n";
  writeFileSync(new URL(`${seed.slug}.json`, dir), text);
  process.stdout.write(`${seed.slug}.json  ${text.length} bytes\n`);
}
