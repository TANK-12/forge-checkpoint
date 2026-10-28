/* Where every body in the solar system is on a given date.
 *
 * Nothing here is hardcoded per planet. Each body is one JSON file in
 * data/bodies/ carrying its orbit in one of two models, and this module only
 * knows the models:
 *
 *   "standish"  JPL's approximate Keplerian elements for the planets
 *               (E.M. Standish, valid 1800-2050): each element is a value at
 *               J2000 plus a rate per Julian century. Heliocentric, ecliptic
 *               J2000. Good to well under a degree across that window.
 *
 *   "kepler"    Osculating or mean elements at an epoch: a, e, i, node,
 *               argument of periapsis, mean anomaly, plus a mean motion (or a
 *               period), and optional precession periods for the node and the
 *               periapsis. Used for dwarf planets (JPL SBDB) and moons (JPL's
 *               planetary satellite mean elements). A moon's `period_days`
 *               is its published sidereal period; `M_rate_deg_day`, when
 *               present, is how fast its mean anomaly runs, fitted to JPL
 *               Horizons by tools/fit_moons.mjs (the published elements'
 *               epochs and rates drifted tens of degrees by 2026).
 *
 * A "kepler" orbit's `frame` says what its angles are measured against:
 * "ecliptic", or "parent_equator" -- the parent planet's equator, whose
 * orientation comes from the parent's IAU pole (`pole.ra_deg/dec_deg`), with
 * the node counted from where that equator crosses Earth's equator. JPL gives
 * most moons against each satellite's local Laplace plane; for the inner
 * moons that plane sits on the planet's equator, and for far ones like
 * Iapetus it is tipped part-way toward the planet's orbit, so treating it as
 * the equator is an approximation. It is what makes Uranus's moons circle
 * on their side, which is the part you can see.
 *
 * Every position comes back heliocentric, in AU, in J2000 ecliptic axes.
 */

import { AU_KM, DAYS_PER_CENTURY, J2000 } from "./units.js";
import { add, cross, equatorialToEcliptic, scale, sub } from "./vec.js";

const DEG = Math.PI / 180;
const TWO_PI = 2 * Math.PI;

/* Eccentric anomaly E from mean anomaly M (radians) for an ellipse. */
export function solveKepler(M, e) {
  const m = ((M % TWO_PI) + TWO_PI) % TWO_PI;
  // Newton from M converges for ordinary orbits; for very eccentric ones it
  // can overshoot near periapsis, and starting from pi does not.
  let E = e < 0.8 ? m : Math.PI;
  for (let k = 0; k < 60; k++) {
    const d = (E - e * Math.sin(E) - m) / (1 - e * Math.cos(E));
    E -= d;
    if (Math.abs(d) < 1e-13) break;
  }
  return E;
}

/* A body's orbital elements at a Julian date, in one common shape:
 * a (AU), e, i/node/peri/M (degrees), n (degrees per day), frame. */
export function elementsAt(body, jd) {
  const el = body.elements;
  if (!el) return null;
  if (el.model === "standish") {
    const T = (jd - J2000) / DAYS_PER_CENTURY;
    const at = (k) => el[k][0] + el[k][1] * T;
    const L = at("L");
    const varpi = at("varpi");
    const node = at("node");
    return {
      a: at("a"),
      e: at("e"),
      i: at("i"),
      node,
      peri: varpi - node,
      M: L - varpi,
      n: el.L[1] / DAYS_PER_CENTURY,
      frame: "ecliptic",
    };
  }
  if (el.model === "kepler") {
    const d = jd - el.epoch_jd;
    const n = el.n_deg_day ?? 360 / el.period_days;
    // Nodes of these orbits regress and periapses advance; the published
    // periods are unsigned, so the direction is supplied here. An orbit run
    // backwards (inclination over 90 degrees, like Triton's) sees its node
    // move the other way.
    const backwards = Math.cos(el.i_deg * DEG) < 0;
    const nodeRate = el.node_period_yr ? ((backwards ? 1 : -1) * 360) / (el.node_period_yr * 365.25) : 0;
    const periRate = el.peri_period_yr ? 360 / (el.peri_period_yr * 365.25) : 0;
    return {
      a: el.a_au ?? el.a_km / AU_KM,
      e: el.e,
      i: el.i_deg,
      node: el.node_deg + nodeRate * d,
      peri: el.peri_deg + periRate * d,
      M: el.M_deg + (el.M_rate_deg_day ?? n) * d,
      n,
      frame: el.frame || "ecliptic",
    };
  }
  throw new Error(`Unknown orbit model "${el.model}" on ${body.id}`);
}

/* Position on the orbit at eccentric anomaly E, in the orbit's own frame. */
export function positionInFrame(el, E) {
  const xp = el.a * (Math.cos(E) - el.e);
  const yp = el.a * Math.sqrt(1 - el.e * el.e) * Math.sin(E);
  const cw = Math.cos(el.peri * DEG);
  const sw = Math.sin(el.peri * DEG);
  const cO = Math.cos(el.node * DEG);
  const sO = Math.sin(el.node * DEG);
  const cI = Math.cos(el.i * DEG);
  const sI = Math.sin(el.i * DEG);
  return [
    (cw * cO - sw * sO * cI) * xp + (-sw * cO - cw * sO * cI) * yp,
    (cw * sO + sw * cO * cI) * xp + (-sw * sO + cw * cO * cI) * yp,
    sw * sI * xp + cw * sI * yp,
  ];
}

/* The axes of a planet's equatorial frame, expressed in ecliptic coordinates:
 * x toward the equator's ascending node on Earth's equator, z along the pole. */
export function poleFrame(pole) {
  const a = pole.ra_deg * DEG;
  const d = pole.dec_deg * DEG;
  const z = [Math.cos(d) * Math.cos(a), Math.cos(d) * Math.sin(a), Math.sin(d)];
  const x = [-Math.sin(a), Math.cos(a), 0];
  const y = cross(z, x);
  return [x, y, z].map(equatorialToEcliptic);
}

export class Ephemeris {
  constructor(bodies) {
    this.bodies = new Map(bodies.map((b) => [b.id, b]));
    this._frames = new Map();
    this._cacheJd = NaN;
    this._cache = new Map();
  }

  get(id) {
    return this.bodies.get(id);
  }

  list() {
    return [...this.bodies.values()];
  }

  children(id) {
    return this.list().filter((b) => b.parent === id);
  }

  _frameAxes(body, frame) {
    if (frame === "ecliptic") return null;
    if (frame !== "parent_equator") throw new Error(`Unknown frame "${frame}" on ${body.id}`);
    const parent = this.bodies.get(body.parent);
    if (!parent?.pole) throw new Error(`${body.id} needs a pole on its parent ${body.parent}`);
    if (!this._frames.has(parent.id)) this._frames.set(parent.id, poleFrame(parent.pole));
    return this._frames.get(parent.id);
  }

  _toEcliptic(body, frame, v) {
    const axes = this._frameAxes(body, frame);
    if (!axes) return v;
    const [X, Y, Z] = axes;
    return add(add(scale(X, v[0]), scale(Y, v[1])), scale(Z, v[2]));
  }

  /* Position of the body relative to the body it orbits, ignoring any
   * barycentre correction. */
  orbitalOffset(id, jd) {
    const body = this.bodies.get(id);
    const el = elementsAt(body, jd);
    if (!el) return [0, 0, 0];
    const E = solveKepler(el.M * DEG, el.e);
    return this._toEcliptic(body, el.frame, positionInFrame(el, E));
  }

  /* Heliocentric ecliptic position in AU. */
  position(id, jd) {
    if (jd !== this._cacheJd) {
      this._cache.clear();
      this._cacheJd = jd;
    }
    const hit = this._cache.get(id);
    if (hit) return hit;
    const body = this.bodies.get(id);
    if (!body) throw new Error(`No body "${id}"`);
    let p = [0, 0, 0];
    if (body.elements) {
      p = this.orbitalOffset(id, jd);
      // Standish's "Earth" is really the Earth-Moon barycentre; Earth sits a
      // little (about 4,700 km) on the far side of it from the Moon.
      const partner = body.elements.barycenter_partner;
      if (partner && this.bodies.has(partner)) {
        p = sub(p, scale(this.orbitalOffset(partner, jd), body.elements.barycenter_ratio));
      }
      if (body.parent) p = add(this.position(body.parent, jd), p);
    }
    this._cache.set(id, p);
    return p;
  }

  /* Orbital period in days, or null for the Sun. */
  periodDays(id, jd) {
    const el = elementsAt(this.bodies.get(id), jd);
    return el ? 360 / el.n : null;
  }

  /* Points around the whole orbit, relative to the parent, as a flat
   * Float32Array of (segments + 1) xyz triples. The loop is closed. */
  orbitPath(id, jd, segments = 256) {
    const body = this.bodies.get(id);
    const el = elementsAt(body, jd);
    const out = new Float32Array((segments + 1) * 3);
    if (!el) return out;
    for (let k = 0; k <= segments; k++) {
      const v = this._toEcliptic(body, el.frame, positionInFrame(el, (k / segments) * TWO_PI));
      out.set(v, k * 3);
    }
    return out;
  }
}
