/* play.py swarm's runner: one JSON job in (the first argument), one JSON
 * answer out on stdout. server.py builds the job; lab.js does the work.
 *
 *   {"do": "run", "rules": {...}, "seconds": 10, "every": 1, "mirror": false}
 *   {"do": "hunt", "tries": 8, "seconds": 8, "colours": 5, "seed": 1, "mirror": false}
 */

import { hunt, measure, points } from "./lab.js";
import { COLOURS } from "./render.js";

function answer(job) {
  if (job.do === "run") {
    const m = measure(job.rules, { seconds: job.seconds, every: job.every, mirror: !!job.mirror });
    const { sw, ...rest } = m;
    return { ...rest, points: points(sw), colours: COLOURS };
  }
  if (job.do === "hunt") {
    const rows = hunt(job);
    return {
      rows: rows.map(({ sw, ...row }) => row),
      best: rows.length ? points(rows[0].sw) : null,
      colours: COLOURS,
    };
  }
  throw new Error(`unknown job ${JSON.stringify(job.do)}`);
}

try {
  process.stdout.write(JSON.stringify(answer(JSON.parse(process.argv[2] || "{}"))));
} catch (e) {
  process.stderr.write(`${e.message}\n`);
  process.exitCode = 1;
}
