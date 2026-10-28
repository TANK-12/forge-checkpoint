#!/usr/bin/env node
// Refit each moon's mean anomaly and its rate to JPL Horizons positions.
//
//   node tools/fit_moons.mjs            # print how far each moon is off, before and after
//   node tools/fit_moons.mjs --write    # store the fitted values in data/bodies/<id>.json
//
// JPL's published mean elements for the moons are dated J2000 or earlier and
// their periods are rounded, so by 2026 many moons sat tens of degrees, some
// half an orbit, from where they really were. This keeps every element JPL
// gives (size, shape, tilt, precession) and fits only the two numbers that
// say where along its orbit the moon is: the mean anomaly at the new epoch
// and how fast it runs (M_rate_deg_day). The node and periapsis are carried
// forward to that epoch with their own precession rates.
//
// The reference is tests/js/horizons-moons-2026-10-19.json: each moon's
// offset from its planet, from the Horizons API, on 16 dates from 2000 to
// 2045. Four of them (2008, 2020, 2035, 2045) are held out of the fit, so the
// printout shows how well the fit predicts dates it never saw.
// tests/js/moons.test.mjs checks the stored result against the same file.

import { readFileSync, readdirSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { Ephemeris } from "../static/core/ephemeris.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const BODIES = join(ROOT, "data/bodies");
const REF = join(ROOT, "tests/js/horizons-moons-2026-10-19.json");
const write = process.argv.includes("--write");

const DEG = Math.PI / 180;
const mod360 = (x) => ((x % 360) + 360) % 360;
const angle = (a, b) => {
  const dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  return Math.acos(Math.max(-1, Math.min(1, dot / Math.hypot(...a) / Math.hypot(...b)))) / DEG;
};

const files = readdirSync(BODIES).filter((f) => f.endsWith(".json"));
const bodies = files.map((f) => JSON.parse(readFileSync(join(BODIES, f), "utf8")));
const ref = JSON.parse(readFileSync(REF, "utf8"));
const E = ref.epoch_jd;
// nearest dates first, so the rate is pinned down on short baselines before
// long ones can alias it by a whole number of turns
const fitOrder = ref.fit_dates
  .map((jd) => ref.jd.indexOf(jd))
  .sort((a, b) => Math.abs(ref.jd[a] - E) - Math.abs(ref.jd[b] - E));
const heldOut = ref.jd.map((_, k) => k).filter((k) => !ref.fit_dates.includes(ref.jd[k]));

function errorsFor(eph, id, parent, ks) {
  return ks.map((k) => {
    const p = eph.position(id, ref.jd[k]);
    const q = eph.position(parent, ref.jd[k]);
    return angle([p[0] - q[0], p[1] - q[1], p[2] - q[2]], ref.offsets_au[id][k]);
  });
}

function fitMoon(body) {
  const base = body.elements;
  const others = bodies.filter((b) => b.id !== body.id);
  const backwards = Math.cos(base.i_deg * DEG) < 0;
  const periRate = base.peri_period_yr ? 360 / (base.peri_period_yr * 365.25) : 0;
  const nodeRate = base.node_period_yr ? ((backwards ? 1 : -1) * 360) / (base.node_period_yr * 365.25) : 0;
  const dE = E - base.epoch_jd;
  const node = mod360(base.node_deg + nodeRate * dE);
  const peri = mod360(base.peri_deg + periRate * dE);
  const elementsWith = (M, rate) => ({
    ...base,
    epoch_jd: E,
    node_deg: node,
    peri_deg: peri,
    M_deg: M,
    M_rate_deg_day: rate,
  });
  const ephWith = (M, rate) => new Ephemeris([...others, { ...body, elements: elementsWith(M, rate) }]);
  const cost = (M, rate, ks) => errorsFor(ephWith(M, rate), body.id, body.parent, ks).reduce((s, e) => s + e * e, 0);

  const n = base.n_deg_day ?? 360 / base.period_days;
  let rate = base.M_rate_deg_day ?? n - periRate - (backwards ? -1 : 1) * nodeRate;
  let M = 0;
  let best = Infinity;
  for (let m = 0; m < 360; m += 0.5) {
    const c = cost(m, rate, [fitOrder[0]]);
    if (c < best) [best, M] = [c, m];
  }
  for (let i = 1; i < fitOrder.length; i++) {
    const ks = fitOrder.slice(0, i + 1);
    const dt = Math.max(Math.abs(ref.jd[fitOrder[i]] - E), 1e-3);
    let b = { c: cost(M, rate, ks), M, rate };
    // the rate can only be as far off as the shorter baselines allow
    const span = Math.min(2, 120 / dt);
    for (let k = -60; k <= 60; k++) {
      const r = rate + (span * k) / 60;
      const c = cost(M, r, ks);
      if (c < b.c) b = { c, M, rate: r };
    }
    for (let s = span / 60; s > 1e-10; s /= 2) {
      for (const [dm, dr] of [
        [0, s],
        [0, -s],
        [s * dt, 0],
        [-s * dt, 0],
      ]) {
        const c = cost(b.M + dm, b.rate + dr, ks);
        if (c < b.c) b = { c, M: b.M + dm, rate: b.rate + dr };
      }
    }
    ({ M, rate } = b);
  }
  return {
    ...elementsWith(+mod360(M).toFixed(4), +rate.toFixed(10)),
    node_deg: +node.toFixed(4),
    peri_deg: +peri.toFixed(4),
  };
}

const fmt = (xs) => xs.map((x) => x.toFixed(2).padStart(6)).join(" ");
console.log(`moon       before (max deg)  after: fitted dates (max)  held-out ${heldOut.map((k) => ref.jd[k]).join(" ")}`);
const old = new Ephemeris(bodies);
for (const id of Object.keys(ref.offsets_au)) {
  const body = bodies.find((b) => b.id === id);
  const all = ref.jd.map((_, k) => k);
  const before = Math.max(...errorsFor(old, id, body.parent, all));
  const fitted = fitMoon(body);
  const eph = new Ephemeris([...bodies.filter((b) => b.id !== id), { ...body, elements: fitted }]);
  const fitMax = Math.max(...errorsFor(eph, id, body.parent, fitOrder));
  console.log(
    `${id.padEnd(10)} ${before.toFixed(2).padStart(8)}          ${fitMax.toFixed(2).padStart(8)}              ${fmt(errorsFor(eph, id, body.parent, heldOut))}`,
  );
  if (!write) continue;
  const path = join(BODIES, `${id}.json`);
  const raw = JSON.parse(readFileSync(path, "utf8"));
  const el = {};
  for (const [k, v] of Object.entries(raw.elements)) {
    el[k] = k in fitted ? fitted[k] : v;
    if (k === "period_days") el.M_rate_deg_day = fitted.M_rate_deg_day;
  }
  el.M_rate_deg_day ??= fitted.M_rate_deg_day;
  el.source = "JPL planetary satellite mean elements; mean anomaly and its rate refitted to JPL Horizons positions (2000-2045) on 2026-10-19 by tools/fit_moons.mjs";
  raw.elements = el;
  writeFileSync(`${path}.tmp`, `${JSON.stringify(raw, null, 2)}\n`);
  renameSync(`${path}.tmp`, path);
}
if (write) console.log("Written to data/bodies/.");
