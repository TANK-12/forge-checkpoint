/* 3D gravity for the puzzle modes: bodies on rails, a probe that falls freely.
 *
 * Bodies (stars, planets, moons, black holes) follow fixed Kepler orbits
 * around a parent, so where each one is depends only on the time. That is the
 * "on rails" model Kerbal Space Program uses too, and it is what makes a level
 * repeatable: the same launch always meets the planets in the same places, so
 * a stored reference solution keeps working and a path preview is exact.
 *
 * The probe is massless. It feels every body's pull and pulls on nothing, and
 * it is stepped with kick-drift-kick leapfrog, the same integrator as the 2D
 * sandbox (core/nbody.js). With bodies fixed in place its energy is conserved
 * to integrator accuracy; with bodies moving, energy is not conserved at all,
 * and that is the physics a gravity assist runs on.
 *
 * Axes: x and y span a level's main plane, z is "up" out of it. The view turns
 * this into Three.js's y-up axes, the same way the map does.
 *
 * No DOM and no Three.js here, so node --test can import it.
 */

import { solveKepler } from "./ephemeris.js";

const DEG = Math.PI / 180;

/* A body's orbit around its parent at time t, as position and velocity
 * relative to the parent. Angles in the spec are degrees; M0 is the mean
 * anomaly at t = 0 and direction -1 runs the orbit backwards. */
export function railState(orbit, mu, t) {
  const a = orbit.a;
  const e = orbit.e ?? 0;
  const dir = orbit.direction ?? 1;
  const n = Math.sqrt(mu / (a * a * a));
  const E = solveKepler((orbit.M0 ?? 0) * DEG + dir * n * t, e);
  const cosE = Math.cos(E);
  const sinE = Math.sin(E);
  const b = a * Math.sqrt(1 - e * e);
  const xp = a * (cosE - e);
  const yp = b * sinE;
  const Edot = (dir * n) / (1 - e * cosE);
  const vxp = -a * sinE * Edot;
  const vyp = b * cosE * Edot;

  const cw = Math.cos((orbit.peri ?? 0) * DEG);
  const sw = Math.sin((orbit.peri ?? 0) * DEG);
  const cO = Math.cos((orbit.node ?? 0) * DEG);
  const sO = Math.sin((orbit.node ?? 0) * DEG);
  const cI = Math.cos((orbit.i ?? 0) * DEG);
  const sI = Math.sin((orbit.i ?? 0) * DEG);
  const r11 = cw * cO - sw * sO * cI;
  const r12 = -sw * cO - cw * sO * cI;
  const r21 = cw * sO + sw * cO * cI;
  const r22 = -sw * sO + cw * cO * cI;
  const r31 = sw * sI;
  const r32 = cw * sI;
  return [
    r11 * xp + r12 * yp,
    r21 * xp + r22 * yp,
    r31 * xp + r32 * yp,
    r11 * vxp + r12 * vyp,
    r21 * vxp + r22 * vyp,
    r31 * vxp + r32 * vyp,
  ];
}

export class RailSystem {
  /* bodies: [{ id, name, kind, m, r, color, pos?: [x, y, z],
   *            orbit?: { parent, a, e, i, node, peri, M0, direction } }]
   * A body with no orbit sits still at `pos` (default the origin). */
  constructor({ G = 1, softening = 0, bodies = [] } = {}) {
    this.G = G;
    this.softening = softening;
    this.bodies = orderByParent(bodies).map((spec) => ({
      id: spec.id,
      name: spec.name ?? spec.id,
      kind: spec.kind ?? "planet",
      m: spec.m ?? 0,
      r: spec.r ?? 1,
      color: spec.color ?? "#ffffff",
      pos: spec.pos ?? [0, 0, 0],
      orbit: spec.orbit ?? null,
    }));
    this.index = new Map(this.bodies.map((b, i) => [b.id, i]));
    for (const b of this.bodies) {
      b.parentIndex = b.orbit ? this.index.get(b.orbit.parent) : -1;
      b.mu = b.orbit ? G * (this.bodies[b.parentIndex].m + b.m) : 0;
    }
    const n = this.bodies.length;
    this.px = new Float64Array(n);
    this.py = new Float64Array(n);
    this.pz = new Float64Array(n);
    this.vx = new Float64Array(n);
    this.vy = new Float64Array(n);
    this.vz = new Float64Array(n);
    this._t = NaN;
  }

  /* Fill the position and velocity arrays for time t. Parents come before
   * their children in this.bodies, so one pass is enough. */
  at(t) {
    if (t === this._t) return this;
    const B = this.bodies;
    for (let i = 0; i < B.length; i++) {
      const b = B[i];
      if (!b.orbit) {
        this.px[i] = b.pos[0];
        this.py[i] = b.pos[1];
        this.pz[i] = b.pos[2];
        this.vx[i] = this.vy[i] = this.vz[i] = 0;
        continue;
      }
      const p = b.parentIndex;
      const s = railState(b.orbit, b.mu, t);
      this.px[i] = this.px[p] + s[0];
      this.py[i] = this.py[p] + s[1];
      this.pz[i] = this.pz[p] + s[2];
      this.vx[i] = this.vx[p] + s[3];
      this.vy[i] = this.vy[p] + s[4];
      this.vz[i] = this.vz[p] + s[5];
    }
    this._t = t;
    return this;
  }

  position(id, t) {
    const i = this.index.get(id);
    this.at(t);
    return [this.px[i], this.py[i], this.pz[i]];
  }

  velocity(id, t) {
    const i = this.index.get(id);
    this.at(t);
    return [this.vx[i], this.vy[i], this.vz[i]];
  }

  body(id) {
    const i = this.index.get(id);
    return i === undefined ? null : this.bodies[i];
  }

  /* Orbital period of a body on rails, or Infinity for one that sits still. */
  period(id) {
    const b = this.body(id);
    if (!b?.orbit) return Infinity;
    return 2 * Math.PI * Math.sqrt(b.orbit.a ** 3 / b.mu);
  }

  /* Gravitational acceleration at a point, written into out. */
  accel(x, y, z, t, out) {
    this.at(t);
    const eps2 = this.softening * this.softening;
    let ax = 0;
    let ay = 0;
    let az = 0;
    for (let i = 0; i < this.bodies.length; i++) {
      const m = this.bodies[i].m;
      if (m === 0) continue;
      const dx = this.px[i] - x;
      const dy = this.py[i] - y;
      const dz = this.pz[i] - z;
      const r2 = dx * dx + dy * dy + dz * dz + eps2;
      const k = (this.G * m) / (r2 * Math.sqrt(r2));
      ax += k * dx;
      ay += k * dy;
      az += k * dz;
    }
    out[0] = ax;
    out[1] = ay;
    out[2] = az;
    return out;
  }

  potential(x, y, z, t) {
    this.at(t);
    const eps2 = this.softening * this.softening;
    let u = 0;
    for (let i = 0; i < this.bodies.length; i++) {
      const dx = this.px[i] - x;
      const dy = this.py[i] - y;
      const dz = this.pz[i] - z;
      u -= (this.G * this.bodies[i].m) / Math.sqrt(dx * dx + dy * dy + dz * dz + eps2);
    }
    return u;
  }

  /* Index of the body whose surface contains the point, or -1. */
  hit(x, y, z, t) {
    this.at(t);
    for (let i = 0; i < this.bodies.length; i++) {
      const r = this.bodies[i].r;
      const dx = this.px[i] - x;
      const dy = this.py[i] - y;
      const dz = this.pz[i] - z;
      if (dx * dx + dy * dy + dz * dz < r * r) return i;
    }
    return -1;
  }

  /* Index of the body pulling hardest at a point. */
  dominant(x, y, z, t) {
    this.at(t);
    let best = -1;
    let bestPull = 0;
    for (let i = 0; i < this.bodies.length; i++) {
      const d2 = (this.px[i] - x) ** 2 + (this.py[i] - y) ** 2 + (this.pz[i] - z) ** 2;
      const pull = this.bodies[i].m / Math.max(d2, 1e-12);
      if (pull > bestPull) {
        bestPull = pull;
        best = i;
      }
    }
    return best;
  }
}

function orderByParent(specs) {
  const byId = new Map(specs.map((s) => [s.id, s]));
  const out = [];
  const state = new Map();
  const visit = (s) => {
    if (state.get(s.id) === "done") return;
    if (state.get(s.id) === "busy") throw new Error(`Body "${s.id}" orbits itself through its parents.`);
    state.set(s.id, "busy");
    if (s.orbit) {
      const parent = byId.get(s.orbit.parent);
      if (!parent) throw new Error(`Body "${s.id}" orbits "${s.orbit.parent}", which does not exist.`);
      visit(parent);
    }
    state.set(s.id, "done");
    out.push(s);
  };
  for (const s of specs) visit(s);
  return out;
}

/* A probe's state: position, velocity, time, and the acceleration last
 * worked out for that position and time. */
export function makeProbe(p, v, t = 0) {
  return { x: p[0], y: p[1], z: p[2], vx: v[0], vy: v[1], vz: v[2], t, a: [0, 0, 0], aT: NaN };
}

/* One kick-drift-kick leapfrog step. The acceleration at the end of a step is
 * kept, so the next step's first kick costs nothing. */
export function stepProbe(sys, s, dt) {
  const h = 0.5 * dt;
  if (s.aT !== s.t) {
    sys.accel(s.x, s.y, s.z, s.t, s.a);
    s.aT = s.t;
  }
  s.vx += h * s.a[0];
  s.vy += h * s.a[1];
  s.vz += h * s.a[2];
  s.x += dt * s.vx;
  s.y += dt * s.vy;
  s.z += dt * s.vz;
  s.t += dt;
  sys.accel(s.x, s.y, s.z, s.t, s.a);
  s.aT = s.t;
  s.vx += h * s.a[0];
  s.vy += h * s.a[1];
  s.vz += h * s.a[2];
  return s;
}

/* Kinetic plus potential energy per unit mass. */
export function specificEnergy(sys, s) {
  return 0.5 * (s.vx * s.vx + s.vy * s.vy + s.vz * s.vz) + sys.potential(s.x, s.y, s.z, s.t);
}

/* Where a probe would go, without changing it. Returns the path as flat xyz
 * triples, the body it would hit (index, or -1), and the time it stopped. */
export function predict(sys, probe, { duration = 10, dt = 0.01, every = 4, bounds = Infinity } = {}) {
  const s = makeProbe([probe.x, probe.y, probe.z], [probe.vx, probe.vy, probe.vz], probe.t);
  const steps = Math.max(1, Math.ceil(duration / dt));
  const points = new Float64Array((Math.ceil(steps / every) + 2) * 3);
  let n = 0;
  const push = () => {
    points[n++] = s.x;
    points[n++] = s.y;
    points[n++] = s.z;
  };
  push();
  let hit = -1;
  for (let k = 1; k <= steps; k++) {
    stepProbe(sys, s, dt);
    hit = sys.hit(s.x, s.y, s.z, s.t);
    const out = s.x * s.x + s.y * s.y + s.z * s.z > bounds * bounds;
    if (hit >= 0 || out || k % every === 0 || k === steps) push();
    if (hit >= 0 || out) break;
  }
  return { points: points.subarray(0, n), hit, t: s.t };
}
