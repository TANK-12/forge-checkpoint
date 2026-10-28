/* When things happen in the sky, found from the ephemeris: the Moon's phase
 * and its next full and new moon, and when a planet next comes to opposition
 * (opposite the Sun in Earth's sky, which is when it is closest, brightest
 * and up all night). No DOM; tested in tests/js/events.test.mjs.
 *
 * Everything is measured the way almanacs do it: by ecliptic longitude seen
 * from Earth. A body's elongation here is how far east of the Sun it sits,
 * from -180 to 180 degrees: 0 at conjunction (a new moon), 180 at opposition
 * (a full moon).
 */

import { angleBetween, sub } from "./vec.js";

const DEG = 180 / Math.PI;
const wrap = (x) => ((((x + 180) % 360) + 360) % 360) - 180;

/* The Moon's phases by elongation, each centred on its own angle. */
export const MOON_PHASES = [
  { at: 0, name: "New moon" },
  { at: 45, name: "Waxing crescent" },
  { at: 90, name: "First quarter" },
  { at: 135, name: "Waxing gibbous" },
  { at: 180, name: "Full moon" },
  { at: 225, name: "Waning gibbous" },
  { at: 270, name: "Last quarter" },
  { at: 315, name: "Waning crescent" },
];

/* Ecliptic longitude of `id` seen from Earth, in degrees. */
export function geocentricLongitude(eph, id, jd) {
  const v = sub(eph.position(id, jd), eph.position("earth", jd));
  return Math.atan2(v[1], v[0]) * DEG;
}

/* How far east of the Sun `id` sits in Earth's sky, in degrees, -180 to 180. */
export function elongation(eph, id, jd) {
  return wrap(geocentricLongitude(eph, id, jd) - geocentricLongitude(eph, "sun", jd));
}

/* The first date after `jd` when the elongation of `id` passes `target`
 * degrees, in either direction. It is stepped `step` days at a time for up to
 * `within` days, then narrowed to well under a minute; null if it does not
 * happen in that window. The step must be short enough that the elongation
 * cannot pass the target and come back within one step. */
export function nextElongation(eph, id, target, jd, { step = 1, within = 800 } = {}) {
  const f = (t) => wrap(elongation(eph, id, t) - target);
  let a = jd;
  let fa = f(a);
  for (let b = jd + step; b <= jd + within + 1e-9; b += step) {
    const fb = f(b);
    // a sign change counts; the jump from +180 to -180 opposite the target does not
    if (((fa < 0 && fb >= 0) || (fa > 0 && fb <= 0)) && Math.abs(fb - fa) < 180) {
      let [lo, hi, flo] = [a, b, fa];
      for (let k = 0; k < 40; k++) {
        const mid = (lo + hi) / 2;
        const fm = f(mid);
        if (Math.sign(fm) === Math.sign(flo)) [lo, flo] = [mid, fm];
        else hi = mid;
      }
      return (lo + hi) / 2;
    }
    [a, fa] = [b, fb];
  }
  return null;
}

/* The Moon's phase on `jd`: its name, and how much of the disc is lit (0 to 1). */
export function moonPhase(eph, jd, moonId = "moon") {
  const e = (elongation(eph, moonId, jd) + 360) % 360;
  const name = MOON_PHASES[Math.round(e / 45) % MOON_PHASES.length].name;
  const earth = eph.position("earth", jd);
  // the Sun-Earth-Moon angle; the Moon is so close that the phase angle is 180 minus it
  const psi = angleBetween(sub(eph.position("sun", jd), earth), sub(eph.position(moonId, jd), earth));
  return { name, lit: (1 - Math.cos(psi / DEG)) / 2, elongation: e };
}
