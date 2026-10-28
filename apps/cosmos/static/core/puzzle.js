/* The rules of the orbit puzzles: launching, goals, hazards, burns, stars.
 *
 * The physics is core/nbody3d.js. This file decides what a flight means: did
 * the probe reach the target, settle into an orbit, pass the rings in order,
 * touch down gently, or crash. A level is one JSON file (see README.md and
 * ~/ForgeGameData/cosmos/levels/); nothing here lists levels.
 *
 * Aim is three numbers: speed, heading (degrees round the level's plane from
 * +x) and elevation (degrees up out of the plane). A probe launched from a
 * body starts just above its surface in the aimed direction and keeps the
 * body's own orbital velocity, the way a real launch does.
 *
 * Fuel is measured as delta-v, the total change of speed the probe can make.
 * Par counts the launch speed plus every burn, so a cheaper route scores
 * better whether the saving came from aiming or from flying.
 *
 * No DOM here, so node --test can import it.
 */

import { mulberry32 } from "./nbody.js";
import { RailSystem, makeProbe, stepProbe } from "./nbody3d.js";

export const GOAL_TYPES = ["reach", "orbit", "waypoints", "land", "explore"];
export const BONUS_TYPES = ["no_burns", "time_under", "close_pass"];
export const BURN_DIRECTIONS = ["prograde", "retrograde", "radial", "antiradial", "normal", "antinormal"];
const BODY_KINDS = ["star", "planet", "moon", "blackhole"];
const DEG = Math.PI / 180;
const TRAIL_LIMIT = 24000; // numbers (8,000 points) before the trail is thinned

const finite = (v) => typeof v === "number" && Number.isFinite(v);
const isVec3 = (v) => Array.isArray(v) && v.length === 3 && v.every(finite);
const isRange = (v) => Array.isArray(v) && v.length === 2 && v.every(finite) && v[0] <= v[1];

/* Every reason a level cannot be played, as plain sentences. Empty means fine. */
export function checkLevel(level) {
  const problems = [];
  if (!level || typeof level !== "object") return ["A level must be a JSON object."];
  if (typeof level.name !== "string" || !level.name.trim()) problems.push("The level needs a name.");
  const bodies = Array.isArray(level.bodies) ? level.bodies : null;
  if (!bodies || !bodies.length) problems.push("The level needs at least one body.");
  const ids = new Set();
  for (const [i, b] of (bodies || []).entries()) {
    const label = `Body ${i + 1}${b?.id ? ` (${b.id})` : ""}`;
    if (!b || typeof b !== "object") {
      problems.push(`${label} is not an object.`);
      continue;
    }
    if (typeof b.id !== "string" || !b.id) problems.push(`${label} needs an id.`);
    else if (ids.has(b.id)) problems.push(`${label}: the id is used twice.`);
    else ids.add(b.id);
    if (!(finite(b.m) && b.m >= 0)) problems.push(`${label}: m must be a number of zero or more.`);
    if (!(finite(b.r) && b.r > 0)) problems.push(`${label}: r must be a positive number.`);
    if (b.kind !== undefined && !BODY_KINDS.includes(b.kind)) problems.push(`${label}: unknown kind "${b.kind}".`);
    if (b.pos !== undefined && !isVec3(b.pos)) problems.push(`${label}: pos must be [x, y, z].`);
    if (b.orbit) {
      if (!(finite(b.orbit.a) && b.orbit.a > 0)) problems.push(`${label}: the orbit needs a positive a.`);
      if (b.orbit.e !== undefined && !(finite(b.orbit.e) && b.orbit.e >= 0 && b.orbit.e < 1)) {
        problems.push(`${label}: the orbit's e must be at least 0 and below 1.`);
      }
    }
  }
  if (bodies && !problems.length) {
    try {
      new RailSystem({ bodies });
    } catch (err) {
      problems.push(err.message);
    }
  }

  const launch = level.launch;
  if (!launch || typeof launch !== "object") problems.push("The level needs a launch.");
  else {
    if (launch.from !== undefined && !ids.has(launch.from)) problems.push(`The launch body "${launch.from}" does not exist.`);
    if (launch.from === undefined && !isVec3(launch.pos)) problems.push("The launch needs a body to launch from or a pos.");
    if (!isRange(launch.speed) || launch.speed[0] < 0) problems.push("launch.speed must be [lowest, highest], zero or more.");
    for (const key of ["heading", "elevation"]) {
      if (launch[key] !== undefined && !isRange(launch[key])) problems.push(`launch.${key} must be [lowest, highest].`);
    }
  }

  const goal = level.goal;
  if (!goal || !GOAL_TYPES.includes(goal.type)) {
    problems.push(`The goal type must be one of: ${GOAL_TYPES.join(", ")}.`);
  } else {
    if (["reach", "orbit", "land"].includes(goal.type) && !ids.has(goal.target)) {
      problems.push(`The goal's target "${goal.target}" does not exist.`);
    }
    if (goal.type === "waypoints") {
      const pts = Array.isArray(goal.points) ? goal.points : [];
      if (!pts.length) problems.push("A waypoints goal needs at least one point.");
      for (const [i, w] of pts.entries()) {
        if (!isVec3(w.pos)) problems.push(`Waypoint ${i + 1} needs a pos of [x, y, z].`);
        if (!(finite(w.radius) && w.radius > 0)) problems.push(`Waypoint ${i + 1} needs a positive radius.`);
        if (w.body !== undefined && !ids.has(w.body)) problems.push(`Waypoint ${i + 1} rides on "${w.body}", which does not exist.`);
      }
    }
  }

  for (const key of ["fuel", "burn_rate", "dt", "bounds", "par", "preview", "preview_time", "time_limit", "time_scale", "preview_dt", "discover_radius", "G", "softening"]) {
    if (level[key] !== undefined && level[key] !== null && !(finite(level[key]) && level[key] >= 0)) {
      problems.push(`${key} must be a number of zero or more.`);
    }
  }
  if (level.dt !== undefined && !(level.dt > 0)) problems.push("dt must be above zero.");
  for (const [i, f] of (level.fields || []).entries()) {
    if (f.type !== "belt") problems.push(`Field ${i + 1}: the only field type is "belt".`);
    if (!ids.has(f.around)) problems.push(`Field ${i + 1} circles "${f.around}", which does not exist.`);
    if (!(finite(f.r_min) && finite(f.r_max) && f.r_min > 0 && f.r_min < f.r_max)) {
      problems.push(`Field ${i + 1} needs 0 < r_min < r_max.`);
    }
    if (!(Number.isInteger(f.count) && f.count > 0 && f.count <= 3000)) problems.push(`Field ${i + 1} needs a count from 1 to 3000.`);
  }
  if (level.bonus && !BONUS_TYPES.includes(level.bonus.type)) {
    problems.push(`The bonus type must be one of: ${BONUS_TYPES.join(", ")}.`);
  }
  if (level.bonus?.type === "close_pass" && !ids.has(level.bonus.body)) {
    problems.push(`The bonus body "${level.bonus.body}" does not exist.`);
  }
  return problems;
}

/* How far out the level's things reach from the origin. */
function extentOf(level) {
  const byId = new Map(level.bodies.map((b) => [b.id, b]));
  const memo = new Map();
  const reach = (b) => {
    if (memo.has(b.id)) return memo.get(b.id);
    const r = b.orbit ? reach(byId.get(b.orbit.parent)) + b.orbit.a * (1 + (b.orbit.e ?? 0)) : Math.hypot(...(b.pos || [0, 0, 0]));
    memo.set(b.id, r);
    return r;
  };
  let extent = Math.max(...level.bodies.map(reach));
  if (level.launch?.pos) extent = Math.max(extent, Math.hypot(...level.launch.pos));
  for (const w of level.goal?.points || []) extent = Math.max(extent, Math.hypot(...w.pos));
  return extent;
}

/* A copy of the level with every default filled in. */
export function prepareLevel(level) {
  const L = structuredClone(level);
  L.G ??= 1;
  L.softening ??= 0;
  L.dt ??= 0.01;
  // A huge level can preview with coarser steps than it flies, so aiming stays quick.
  L.preview_dt ??= L.dt;
  L.discover_radius ??= 30;
  L.fuel ??= 0;
  L.burn_rate ??= 1;
  L.preview ??= 1;
  L.preview_time ??= 40;
  L.time_limit ??= null;
  L.fields ??= [];
  L.caption ??= "";
  // Space is big and long shots are part of the fun, so the edge is far away.
  L.bounds ??= Math.max(50, extentOf(L) * 50);
  L.launch.heading ??= [0, 360];
  L.launch.elevation ??= [0, 0];
  L.launch.altitude ??= 0.5;
  const g = L.goal;
  if (g.type === "reach") g.radius ??= 1;
  if (g.type === "orbit") {
    g.hold ??= 4;
    const target = L.bodies.find((b) => b.id === g.target);
    g.min_altitude ??= target.r * 0.25;
    g.max_apoapsis ??= target.r * 12;
  }
  if (g.type === "land") g.max_speed ??= 1;
  return L;
}

/* A ring of asteroids on circular rails around one body. Massless: they only
 * matter if the probe runs into one. */
export class Field {
  constructor(spec, sys) {
    this.spec = spec;
    this.parent = sys.index.get(spec.around);
    const n = spec.count;
    const rng = mulberry32(spec.seed ?? 7);
    const mu = sys.G * sys.bodies[this.parent].m;
    this.size = spec.size ?? 0.2;
    this.a = new Float64Array(n);
    this.n = new Float64Array(n);
    this.M0 = new Float64Array(n);
    this.ci = new Float64Array(n);
    this.si = new Float64Array(n);
    this.cO = new Float64Array(n);
    this.sO = new Float64Array(n);
    const tilt = (spec.thickness_deg ?? 2) * DEG;
    for (let k = 0; k < n; k++) {
      const a = spec.r_min + (spec.r_max - spec.r_min) * rng();
      const inc = (rng() - 0.5) * 2 * tilt;
      const node = rng() * 2 * Math.PI;
      this.a[k] = a;
      this.n[k] = Math.sqrt(mu / (a * a * a)) * (spec.direction ?? 1);
      this.M0[k] = rng() * 2 * Math.PI;
      this.ci[k] = Math.cos(inc);
      this.si[k] = Math.sin(inc);
      this.cO[k] = Math.cos(node);
      this.sO[k] = Math.sin(node);
    }
    this.count = n;
    this.reachIn = spec.r_min - this.size - spec.r_max * Math.sin(tilt) - 1e-9;
    this.reachOut = spec.r_max + this.size;
    // Seen from above, asteroid k sits at angle node + M0 + n*t (exactly for a
    // flat ring, to within (1 - cos tilt) for a tilted one). Comparing that
    // angle with the probe's rules out almost every rock without any trig.
    this.angle0 = new Float64Array(n);
    for (let k = 0; k < n; k++) this.angle0[k] = Math.atan2(this.sO[k], this.cO[k]) + this.M0[k];
    this.angleSlack = this.size / Math.max(spec.r_min * 0.5, 1e-6) + (1 - Math.cos(tilt)) * Math.PI + 0.01;
  }

  /* Asteroid k's position relative to the body it circles. */
  offset(k, t, out) {
    const th = this.M0[k] + this.n[k] * t;
    const c = Math.cos(th) * this.a[k];
    const s = Math.sin(th) * this.a[k];
    out[0] = this.cO[k] * c - this.sO[k] * s * this.ci[k];
    out[1] = this.sO[k] * c + this.cO[k] * s * this.ci[k];
    out[2] = s * this.si[k];
    return out;
  }

  /* All positions, as flat xyz, for drawing. */
  positions(sys, t, out = new Float32Array(this.count * 3)) {
    sys.at(t);
    const px = sys.px[this.parent];
    const py = sys.py[this.parent];
    const pz = sys.pz[this.parent];
    const o = [0, 0, 0];
    for (let k = 0; k < this.count; k++) {
      this.offset(k, t, o);
      out[k * 3] = px + o[0];
      out[k * 3 + 1] = py + o[1];
      out[k * 3 + 2] = pz + o[2];
    }
    return out;
  }

  hit(sys, x, y, z, t) {
    sys.at(t);
    const dx = x - sys.px[this.parent];
    const dy = y - sys.py[this.parent];
    const dz = z - sys.pz[this.parent];
    const d = Math.hypot(dx, dy, dz);
    if (d < this.reachIn || d > this.reachOut) return false;
    const o = [0, 0, 0];
    const s2 = this.size * this.size;
    const phi = Math.atan2(dy, dx);
    const TWO_PI = 2 * Math.PI;
    for (let k = 0; k < this.count; k++) {
      let gap = this.angle0[k] + this.n[k] * t - phi;
      gap -= TWO_PI * Math.round(gap / TWO_PI);
      if (gap > this.angleSlack || gap < -this.angleSlack) continue;
      this.offset(k, t, o);
      if ((o[0] - dx) ** 2 + (o[1] - dy) ** 2 + (o[2] - dz) ** 2 < s2) return true;
    }
    return false;
  }
}

export function clampAim(level, aim) {
  const L = level.launch;
  const clamp = (v, [lo, hi]) => Math.min(hi, Math.max(lo, v));
  let heading = ((aim.heading % 360) + 360) % 360;
  if (!(L.heading[0] <= 0 && L.heading[1] >= 360)) heading = clamp(aim.heading, L.heading);
  return { speed: clamp(aim.speed, L.speed), heading, elevation: clamp(aim.elevation ?? 0, L.elevation) };
}

export function aimDirection({ heading, elevation = 0 }) {
  const h = heading * DEG;
  const e = elevation * DEG;
  return [Math.cos(e) * Math.cos(h), Math.cos(e) * Math.sin(h), Math.sin(e)];
}

/* Where the probe starts and how fast, for an aim. */
export function launchState(level, sys, aim) {
  const a = clampAim(level, aim);
  const d = aimDirection(a);
  const L = level.launch;
  let p;
  let v;
  if (L.from !== undefined) {
    const body = sys.body(L.from);
    const bp = sys.position(L.from, 0);
    const bv = sys.velocity(L.from, 0);
    const lift = body.r + L.altitude;
    p = [bp[0] + d[0] * lift, bp[1] + d[1] * lift, bp[2] + d[2] * lift];
    v = [bv[0] + d[0] * a.speed, bv[1] + d[1] * a.speed, bv[2] + d[2] * a.speed];
  } else {
    const base = L.velocity || [0, 0, 0];
    p = [...L.pos];
    v = [base[0] + d[0] * a.speed, base[1] + d[1] * a.speed, base[2] + d[2] * a.speed];
  }
  return { p, v, aim: a };
}

/* Orbit of a probe around one body, from its relative position and velocity. */
export function orbitAround(sys, index, s) {
  sys.at(s.t);
  const rx = s.x - sys.px[index];
  const ry = s.y - sys.py[index];
  const rz = s.z - sys.pz[index];
  const vx = s.vx - sys.vx[index];
  const vy = s.vy - sys.vy[index];
  const vz = s.vz - sys.vz[index];
  const r = Math.hypot(rx, ry, rz);
  const v2 = vx * vx + vy * vy + vz * vz;
  const mu = sys.G * sys.bodies[index].m;
  const energy = v2 / 2 - mu / r;
  const hx = ry * vz - rz * vy;
  const hy = rz * vx - rx * vz;
  const hz = rx * vy - ry * vx;
  const h2 = hx * hx + hy * hy + hz * hz;
  const e = Math.sqrt(Math.max(0, 1 + (2 * energy * h2) / (mu * mu)));
  if (energy >= 0) return { bound: false, r, speed: Math.sqrt(v2), e };
  const a = -mu / (2 * energy);
  return { bound: true, r, speed: Math.sqrt(v2), e, a, periapsis: a * (1 - e), apoapsis: a * (1 + e) };
}

/* One flight: a probe launched with an aim, stepped until it wins or is lost. */
export class Run {
  constructor(level, aim, { sys = null } = {}) {
    this.level = level;
    this.sys = sys || new RailSystem({ G: level.G, softening: level.softening, bodies: level.bodies });
    this.fields = level.fields.map((f) => new Field(f, this.sys));
    const start = launchState(level, this.sys, aim);
    this.aim = start.aim;
    this.probe = makeProbe(start.p, start.v, 0);
    this.launchSpeed = start.aim.speed;
    this.dvUsed = 0;
    this.fuelLeft = level.fuel;
    this.status = "flying";
    this.reason = "";
    this.waypoint = 0;
    this.holdTime = 0;
    this.events = [];
    this.trail = [start.p[0], start.p[1], start.p[2]];
    this.trailEvery = 4;
    this._stepCount = 0;
    this._carry = 0;
    this.minDistance = new Map();
    this.goalIndex = level.goal.target !== undefined ? this.sys.index.get(level.goal.target) : -1;
    this.bonusIndex = level.bonus?.body !== undefined ? this.sys.index.get(level.bonus.body) : -1;
    this.orbitInfo = null;
    // In an explore level, flying close to a star or black hole discovers it.
    this.discovered = new Set();
    this.discoverables = level.goal.type === "explore" ? discoverableIndices(this.sys) : [];
    this.farthest = 0;
  }

  get time() {
    return this.probe.t;
  }

  _end(status, reason) {
    this.status = status;
    this.reason = reason;
    this.events.push({ type: status, reason, t: this.probe.t });
    this._record(true);
  }

  _record(force = false) {
    const s = this.probe;
    if (!force && ++this._stepCount % this.trailEvery !== 0) return;
    this.trail.push(s.x, s.y, s.z);
    if (this.trail.length > TRAIL_LIMIT) {
      // Keep every other point; the path is still smooth and memory stays flat.
      const thin = [];
      for (let i = 0; i < this.trail.length; i += 6) thin.push(this.trail[i], this.trail[i + 1], this.trail[i + 2]);
      this.trail = thin;
      this.trailEvery *= 2;
    }
  }

  /* Fire a burn of up to dv in a direction measured against whatever pulls
   * hardest. Returns the delta-v actually spent. */
  burn(direction, dv) {
    if (this.status !== "flying" || dv <= 0) return 0;
    const spend = Math.min(dv, this.fuelLeft);
    if (spend <= 0) return 0;
    const s = this.probe;
    const sys = this.sys.at(s.t);
    const i = sys.dominant(s.x, s.y, s.z, s.t);
    const rel = i >= 0 ? [s.x - sys.px[i], s.y - sys.py[i], s.z - sys.pz[i]] : [s.x, s.y, s.z];
    const vel = i >= 0 ? [s.vx - sys.vx[i], s.vy - sys.vy[i], s.vz - sys.vz[i]] : [s.vx, s.vy, s.vz];
    const unit = (v) => {
      const l = Math.hypot(...v) || 1;
      return v.map((c) => c / l);
    };
    const prograde = unit(vel);
    const normal = unit([rel[1] * vel[2] - rel[2] * vel[1], rel[2] * vel[0] - rel[0] * vel[2], rel[0] * vel[1] - rel[1] * vel[0]]);
    const radial = unit([
      normal[1] * prograde[2] - normal[2] * prograde[1],
      normal[2] * prograde[0] - normal[0] * prograde[2],
      normal[0] * prograde[1] - normal[1] * prograde[0],
    ]);
    const dirs = {
      prograde,
      retrograde: prograde.map((c) => -c),
      normal,
      antinormal: normal.map((c) => -c),
      radial: radial.map((c) => -c),
      antiradial: radial,
    };
    const d = dirs[direction];
    if (!d) throw new Error(`Unknown burn direction "${direction}"`);
    s.vx += d[0] * spend;
    s.vy += d[1] * spend;
    s.vz += d[2] * spend;
    this.fuelLeft -= spend;
    this.dvUsed += spend;
    this.events.push({ type: "burn", direction, dv: spend, t: s.t });
    return spend;
  }

  step() {
    if (this.status !== "flying") return;
    const L = this.level;
    const s = this.probe;
    const sys = this.sys;
    stepProbe(sys, s, L.dt);
    sys.at(s.t);
    this._record();

    if (this.discoverables.length && this._stepCount % 4 === 0) {
      for (const i of this.discoverables) {
        const b = sys.bodies[i];
        if (this.discovered.has(b.id)) continue;
        if (Math.hypot(s.x - sys.px[i], s.y - sys.py[i], s.z - sys.pz[i]) < b.r + L.discover_radius) {
          this.discovered.add(b.id);
          this.events.push({ type: "discover", id: b.id, name: b.name, t: s.t });
        }
      }
      this.farthest = Math.max(this.farthest, Math.hypot(s.x, s.y, s.z));
    }

    if (this.bonusIndex >= 0) {
      const i = this.bonusIndex;
      const d = Math.hypot(s.x - sys.px[i], s.y - sys.py[i], s.z - sys.pz[i]) - sys.bodies[i].r;
      if (d < (this.minDistance.get(i) ?? Infinity)) this.minDistance.set(i, d);
    }

    const g = L.goal;
    if (g.type === "reach") {
      const i = this.goalIndex;
      const d = Math.hypot(s.x - sys.px[i], s.y - sys.py[i], s.z - sys.pz[i]);
      if (d < sys.bodies[i].r + g.radius) return this._end("won", `Reached ${sys.bodies[i].name}.`);
    } else if (g.type === "waypoints") {
      const w = g.points[this.waypoint];
      const c = waypointPosition(sys, w, s.t);
      if (Math.hypot(s.x - c[0], s.y - c[1], s.z - c[2]) < w.radius) {
        this.waypoint++;
        this.events.push({ type: "waypoint", index: this.waypoint - 1, t: s.t });
        if (this.waypoint === g.points.length) return this._end("won", "Passed every ring in order.");
      }
    } else if (g.type === "orbit") {
      const i = this.goalIndex;
      const o = orbitAround(sys, i, s);
      this.orbitInfo = o;
      const ok = o.bound && o.periapsis > sys.bodies[i].r + g.min_altitude && o.apoapsis < g.max_apoapsis;
      this.holdTime = ok ? this.holdTime + L.dt : 0;
      if (this.holdTime >= g.hold) return this._end("won", `In orbit around ${sys.bodies[i].name}.`);
    }

    const hit = sys.hit(s.x, s.y, s.z, s.t);
    if (hit >= 0) {
      const b = sys.bodies[hit];
      if (g.type === "land" && hit === this.goalIndex) {
        const speed = Math.hypot(s.vx - sys.vx[hit], s.vy - sys.vy[hit], s.vz - sys.vz[hit]);
        this.touchdownSpeed = speed;
        if (speed <= g.max_speed) return this._end("won", `Touched down on ${b.name} at ${speed.toFixed(2)}.`);
        return this._end("lost", `Hit ${b.name} at ${speed.toFixed(2)}; a landing has to be ${g.max_speed} or slower.`);
      }
      if (b.kind === "blackhole") return this._end("lost", `Fell into ${b.name}.`);
      return this._end("lost", `Crashed into ${b.name}.`);
    }
    for (const f of this.fields) {
      if (f.hit(sys, s.x, s.y, s.z, s.t)) return this._end("lost", "Hit an asteroid.");
    }
    if (s.x * s.x + s.y * s.y + s.z * s.z > L.bounds * L.bounds) return this._end("lost", "Drifted out of bounds.");
    if (L.time_limit && s.t >= L.time_limit) return this._end("lost", "Out of time.");
  }

  /* Step through a stretch of simulated time, stopping early if the flight
   * ends or the real-time budget runs out. Returns the steps taken. */
  advance(simTime, { maxMs = Infinity } = {}) {
    this._carry += simTime;
    const t0 = maxMs < Infinity ? performance.now() : 0;
    let steps = 0;
    while (this._carry >= this.level.dt && this.status === "flying") {
      this.step();
      this._carry -= this.level.dt;
      steps++;
      if (maxMs < Infinity && steps % 64 === 0 && performance.now() - t0 > maxMs) {
        this._carry = 0;
        break;
      }
    }
    return steps;
  }
}

function discoverableIndices(sys) {
  return sys.bodies.map((b, i) => (b.kind === "star" || b.kind === "blackhole" ? i : -1)).filter((i) => i >= 0);
}

/* The ids of every star and black hole in a level: what an explore level counts. */
export function discoverableIds(level) {
  return level.bodies.filter((b) => b.kind === "star" || b.kind === "blackhole").map((b) => b.id);
}

export function waypointPosition(sys, w, t) {
  if (w.body === undefined) return w.pos;
  const b = sys.position(w.body, t);
  return [b[0] + w.pos[0], b[1] + w.pos[1], b[2] + w.pos[2]];
}

/* Stars for a finished run: one for finishing, one for par, one for the bonus. */
export function score(level, run) {
  const won = run.status === "won";
  if (level.goal.type === "explore") return { won: false, stars: 0, finish: false, par: false, bonus: false, cost: run.launchSpeed + run.dvUsed };
  const cost = run.launchSpeed + run.dvUsed;
  const par = won && finite(level.par) && cost <= level.par + 1e-9;
  let bonus = false;
  const B = level.bonus;
  if (won && B) {
    if (B.type === "no_burns") bonus = run.dvUsed === 0;
    if (B.type === "time_under") bonus = run.time <= B.value;
    if (B.type === "close_pass") bonus = (run.minDistance.get(run.bonusIndex) ?? Infinity) <= B.within;
  }
  return { won, finish: won, par, bonus, stars: (won ? 1 : 0) + (par ? 1 : 0) + (bonus ? 1 : 0), cost };
}

/* Fly a level's stored reference solution (aim plus timed burns) to the end. */
export function playReference(level, reference = level.reference, { maxTime = null } = {}) {
  const run = new Run(level, reference);
  const burns = [...(reference.burns || [])].sort((a, b) => a.t - b.t);
  const limit = maxTime ?? level.time_limit ?? 2000;
  let next = 0;
  while (run.status === "flying" && run.time < limit) {
    while (next < burns.length && run.time >= burns[next].t) {
      run.burn(burns[next].dir, burns[next].dv);
      next++;
    }
    run.step();
  }
  return run;
}
