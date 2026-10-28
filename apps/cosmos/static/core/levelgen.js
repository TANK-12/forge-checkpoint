/* Endless puzzle levels, and a solver that finds a way through any level.
 *
 * Generated levels are solvable by construction, then checked by flying them.
 * The generator builds a system (a star, the home planet, and at higher
 * difficulty extra planets, a belt, a black hole), picks a random launch, and
 * flies it with no goal. Then it puts the goal where the probe actually went:
 * a target planet on a circular orbit timed to be at that spot at that
 * moment, or rings along the path. Finally the finished level is flown with
 * the stored launch, and it is only handed out if that flight wins. A seed
 * that cannot make a good level moves on to the next attempt, and after 40
 * attempts a plain one-planet level is built, which is also checked.
 *
 * Par for a generated level is 15% above the constructed launch speed, so a
 * player can beat it by finding a cheaper route than the one used to build it.
 *
 * solveLevel() searches a hand-made level for a launch (and for orbit and
 * landing goals, one braking burn) that wins. tools/solve_level.mjs runs it on
 * a level file, which is how reference solutions and pars get written.
 *
 * No DOM here, so node --test can import it.
 */

import { mulberry32 } from "./nbody.js";
import { Run, orbitAround, playReference, prepareLevel } from "./puzzle.js";

const STAR_COLORS = ["#ffd27a", "#ffe9b8", "#ffb36b", "#bcd4ff", "#ff9a6b"];
const PLANET_COLORS = ["#5aa0e0", "#d9b27c", "#7ad0b0", "#c9643b", "#b99cff", "#e8c98b", "#8fd0ff"];
const round = (v, digits = 3) => Math.round(v * 10 ** digits) / 10 ** digits;
// A burn time is stored rounded down, so a replay fires on the same step and
// not one step late, which is the difference between a landing and a crash.
const floorTime = (t) => Math.floor(t * 1e4) / 1e4;

const CAPTIONS = {
  reach: [
    "The target is moving. Aim for where it will be, not where it is.",
    "A slower launch takes a longer, curving route; a faster one flies straighter.",
    "Planets you pass pull your path toward them. Use them or avoid them.",
  ],
  waypoints: [
    "Rings stay put while everything else moves. Pass them in order.",
    "Your path bends toward the star, so a ring behind it needs a curving shot.",
    "Out-of-plane rings need elevation: tilt the launch up or down.",
  ],
};

function pick(rng, list) {
  return list[Math.floor(rng() * list.length)];
}

function buildSystem(rng, difficulty) {
  const hole = difficulty >= 7 && rng() < 0.5;
  const bodies = [
    hole
      ? { id: "core", name: "Black hole", kind: "blackhole", m: 1400, r: 2.2, color: "#ff9c4a", pos: [0, 0, 0] }
      : { id: "core", name: "Star", kind: "star", m: 1000, r: 3, color: pick(rng, STAR_COLORS), pos: [0, 0, 0] },
  ];
  const homeA = 40 + rng() * 20;
  bodies.push({
    id: "home",
    name: "Home",
    kind: "planet",
    m: 1,
    r: 1.2,
    color: "#5aa0e0",
    orbit: { parent: "core", a: round(homeA), M0: round(rng() * 360) },
  });
  const fields = [];
  const extra = difficulty >= 3 ? 1 + Math.floor((difficulty - 3) / 3) : 0;
  const used = [homeA];
  for (let k = 0; k < extra; k++) {
    let a = 0;
    for (let tries = 0; tries < 20; tries++) {
      a = 70 + rng() * 100;
      if (used.every((u) => Math.abs(u - a) > 18)) break;
    }
    used.push(a);
    bodies.push({
      id: `world-${k + 1}`,
      name: ["Ferrum", "Vesper", "Oriel", "Talon"][k % 4],
      kind: "planet",
      m: round(3 + rng() * 6, 2),
      r: round(1.6 + rng() * 1.2, 2),
      color: pick(rng, PLANET_COLORS),
      orbit: { parent: "core", a: round(a), M0: round(rng() * 360), direction: 1 },
    });
  }
  if (difficulty >= 4) {
    let r0 = homeA + 8;
    for (let tries = 0; tries < 20 && used.some((u) => u > r0 - 6 && u < r0 + 16); tries++) r0 += 7;
    fields.push({
      type: "belt",
      around: "core",
      r_min: round(r0),
      r_max: round(r0 + 8),
      count: Math.min(1200, 250 + difficulty * 60),
      size: 0.35,
      thickness_deg: 3,
      seed: Math.floor(rng() * 1e6),
    });
  }
  return { bodies, fields, homeA };
}

/* Fly a draft level with no goal and keep samples of where the probe was. */
function scout(draft, aim, until) {
  const run = new Run(prepareLevel({ ...draft, goal: { type: "explore" } }), aim);
  const samples = [];
  const every = Math.max(1, Math.round(0.25 / run.level.dt));
  let k = 0;
  while (run.status === "flying" && run.time < until) {
    run.step();
    if (++k % every === 0) {
      const s = run.probe;
      samples.push({ t: s.t, p: [s.x, s.y, s.z] });
    }
  }
  return samples;
}

function clearOfBodies(draft, sys, sample, gap) {
  sys.at(sample.t);
  for (let i = 0; i < sys.bodies.length; i++) {
    const d = Math.hypot(sample.p[0] - sys.px[i], sample.p[1] - sys.py[i], sample.p[2] - sys.pz[i]);
    if (d < sys.bodies[i].r + gap) return false;
  }
  return true;
}

function attempt(rng, difficulty, simple) {
  const { bodies, fields, homeA } = simple ? buildSystem(() => 0.5, 1) : buildSystem(rng, difficulty);
  const offPlane = !simple && difficulty >= 5;
  const goalType = !simple && difficulty % 3 === 2 ? "waypoints" : "reach";
  const aim = {
    speed: round(1.5 + rng() * 2.5, 2),
    heading: round(rng() * 360, 1),
    elevation: goalType === "waypoints" && offPlane ? round((rng() - 0.5) * 30, 1) : 0,
  };
  const draft = {
    name: `Endless ${difficulty}`,
    G: 1,
    dt: 0.02,
    bodies,
    fields: simple ? [] : fields,
    launch: { from: "home", speed: [0, 6], elevation: offPlane ? [-30, 30] : [0, 0], altitude: 0.6 },
  };
  const probeRun = new Run(prepareLevel({ ...draft, goal: { type: "explore" } }), aim);
  const samples = scout(draft, aim, 160);
  const sys = probeRun.sys;
  const usable = samples.filter((s) => s.t > 8 && Math.hypot(...s.p) > homeA + 12 && Math.hypot(...s.p) < 175 && clearOfBodies(draft, sys, s, 8));
  if (!usable.length) return null;

  let goal;
  let arrival;
  if (goalType === "reach") {
    const s = usable[Math.floor(rng() * usable.length)];
    const a = Math.hypot(s.p[0], s.p[1]);
    const mu = draft.G * (bodies[0].m + 0.3);
    const n = Math.sqrt(mu / a ** 3);
    const theta = Math.atan2(s.p[1], s.p[0]);
    bodies.push({
      id: "target",
      name: "Beacon",
      kind: "planet",
      m: 0.3,
      r: 1.5,
      color: "#ffcf6b",
      orbit: { parent: "core", a: round(a, 6), M0: round(((theta - n * s.t) * 180) / Math.PI, 6) },
    });
    goal = { type: "reach", target: "target", radius: 1.8 };
    arrival = s.t;
  } else {
    const count = Math.min(3, 1 + Math.floor(difficulty / 3));
    const picks = [];
    let last = -Infinity;
    for (const s of usable) {
      if (s.t - last >= 5 && picks.length < count && rng() < 0.35) {
        picks.push(s);
        last = s.t;
      }
    }
    if (!picks.length) return null;
    goal = { type: "waypoints", points: picks.map((s) => ({ pos: s.p.map((c) => round(c, 3)), radius: 2.4 })) };
    arrival = picks[picks.length - 1].t;
  }

  const level = prepareLevel({
    ...draft,
    goal,
    preview: round(Math.max(0.25, 1 - 0.08 * (difficulty - 1)), 2),
    preview_time: round(arrival * 1.25, 1),
    par: round(aim.speed * 1.15, 2),
    bonus: { type: "time_under", value: Math.ceil(arrival * 1.3), text: "Arrive quickly" },
    caption: pick(rng, CAPTIONS[goalType]),
    reference: aim,
    generated: true,
  });
  const check = playReference(level, aim, { maxTime: arrival * 1.5 + 10 });
  return check.status === "won" ? level : null;
}

/* A solvable level for a seed and difficulty. Same inputs, same level. */
export function generateLevel(seed, difficulty = 1) {
  const rng = mulberry32((seed * 2654435761) ^ (difficulty * 40503));
  for (let k = 0; k < 40; k++) {
    const level = attempt(rng, difficulty, false);
    if (level) return { ...level, id: `endless-${seed}-${difficulty}`, seed, difficulty };
  }
  for (let k = 0; k < 40; k++) {
    const level = attempt(rng, 1, true);
    if (level) return { ...level, id: `endless-${seed}-${difficulty}`, seed, difficulty, fallback: true };
  }
  throw new Error("Could not build a level even from the simple fallback.");
}

/* --- solving hand-made levels ----------------------------------------------- */

/* Fly an aim, braking automatically for orbit and landing goals. Returns the
 * run, the burns used and how close it came, so a search can climb toward a
 * win even from misses. */
export function flyWithAutopilot(level, aim, { landingMargin = 0.6, maxTime = null } = {}) {
  const run = new Run(level, aim);
  const g = level.goal;
  const sys = run.sys;
  const burns = [];
  const limit = maxTime ?? level.time_limit ?? level.preview_time * 3;
  let closest = Infinity;
  let lastRadial = null;
  let braked = false;
  while (run.status === "flying" && run.time < limit) {
    const s = run.probe;
    if (g.type === "reach" || g.type === "orbit" || g.type === "land") {
      sys.at(s.t);
      const i = run.goalIndex;
      const rx = s.x - sys.px[i];
      const ry = s.y - sys.py[i];
      const rz = s.z - sys.pz[i];
      const d = Math.hypot(rx, ry, rz);
      closest = Math.min(closest, d - sys.bodies[i].r);
      const vx = s.vx - sys.vx[i];
      const vy = s.vy - sys.vy[i];
      const vz = s.vz - sys.vz[i];
      const radial = rx * vx + ry * vy + rz * vz;
      const mu = sys.G * sys.bodies[i].m;
      const speed = Math.hypot(vx, vy, vz);
      if (!braked && level.fuel > 0 && g.type === "orbit" && lastRadial !== null && lastRadial < 0 && radial >= 0) {
        const o = orbitAround(sys, i, s);
        if (d > sys.bodies[i].r + g.min_altitude && d < g.max_apoapsis * 0.8 && (!o.bound || o.apoapsis >= g.max_apoapsis * 0.9)) {
          const dv = speed - Math.sqrt(mu / d);
          if (dv > 0 && dv <= run.fuelLeft) {
            burns.push({ t: floorTime(s.t), dir: "retrograde", dv: round(dv, 6) });
            run.burn("retrograde", round(dv, 6));
            braked = true;
          }
        }
      }
      // One braking burn can only land gently if it fires low enough that the
      // rest of the fall adds less speed than the landing limit allows.
      const want = g.max_speed * landingMargin;
      const r0 = sys.bodies[i].r;
      const lowEnough = 1 / r0 - (want * want) / (2 * mu) <= 0 || d <= 1 / (1 / r0 - (want * want) / (2 * mu));
      if (!braked && level.fuel > 0 && g.type === "land" && lowEnough && radial < 0) {
        const fall = 2 * mu * (1 / r0 - 1 / d);
        const vt = Math.sqrt(Math.max(0, want * want - fall));
        const dv = speed - vt;
        if (dv > 0 && dv <= run.fuelLeft) {
          burns.push({ t: floorTime(s.t), dir: "retrograde", dv: round(dv, 6) });
          run.burn("retrograde", round(dv, 6));
        }
        braked = true;
      }
      lastRadial = radial;
    } else if (g.type === "waypoints") {
      const w = g.points[run.waypoint];
      if (w) {
        const d = Math.hypot(s.x - w.pos[0], s.y - w.pos[1], s.z - w.pos[2]);
        closest = Math.min(closest, (g.points.length - run.waypoint) * 1000 + d);
      }
    }
    run.step();
  }
  return { run, burns, closest: run.status === "won" ? -1 : closest };
}

/* Search for the cheapest winning aim. Coarse grid first, then random
 * refinement around the best few. Deterministic for a given seed. */
export function solveLevel(rawLevel, { seed = 1, coarse = 48, speeds = 14, refine = 400, margins = [0.8, 0.6, 0.4] } = {}) {
  const level = prepareLevel(rawLevel);
  const L = level.launch;
  const rng = mulberry32(seed);
  const elevations = L.elevation[0] === L.elevation[1] ? [L.elevation[0]] : [0, 0.25, 0.5, 0.75, 1].map((f) => L.elevation[0] + f * (L.elevation[1] - L.elevation[0]));
  const headingSpan = L.heading[1] - L.heading[0];
  const candidates = [];
  const tryAim = (aim) => {
    let best = null;
    for (const m of level.goal.type === "land" ? margins : [0.6]) {
      const r = flyWithAutopilot(level, aim, { landingMargin: m });
      const cost = aim.speed + r.run.dvUsed;
      const entry = { aim: { ...r.run.aim }, burns: r.burns, closest: r.closest, cost, won: r.run.status === "won", time: r.run.time };
      if (!best || (entry.won && (!best.won || entry.cost < best.cost)) || (!best.won && !entry.won && entry.closest < best.closest)) best = entry;
    }
    candidates.push(best);
    return best;
  };
  for (let h = 0; h < coarse; h++) {
    for (let s = 0; s < speeds; s++) {
      for (const elevation of elevations) {
        tryAim({
          heading: L.heading[0] + (headingSpan * (h + 0.5)) / coarse,
          speed: L.speed[0] + ((L.speed[1] - L.speed[0]) * (s + 0.5)) / speeds,
          elevation,
        });
      }
    }
  }
  const rank = (a, b) => (a.won !== b.won ? (a.won ? -1 : 1) : a.won ? a.cost - b.cost : a.closest - b.closest);
  for (let k = 0; k < refine; k++) {
    candidates.sort(rank);
    const base = candidates[Math.floor(rng() * Math.min(5, candidates.length))].aim;
    const spread = 1 - k / refine;
    tryAim({
      heading: base.heading + (rng() - 0.5) * (headingSpan / coarse) * 2 * spread,
      speed: base.speed + (rng() - 0.5) * ((L.speed[1] - L.speed[0]) / speeds) * 2 * spread,
      elevation: base.elevation + (rng() - 0.5) * (L.elevation[1] - L.elevation[0]) * 0.2 * spread,
    });
  }
  candidates.sort(rank);
  // A win only counts once the stored, rounded solution replays to a win.
  let tried = 0;
  for (const c of candidates) {
    if (!c.won || tried++ >= 50) break;
    const reference = { speed: round(c.aim.speed, 6), heading: round(c.aim.heading, 6), elevation: round(c.aim.elevation, 6), burns: c.burns };
    if (playReference(level, reference).status !== "won") continue;
    return { solved: true, reference, cost: round(c.cost, 4), time: round(c.time, 2) };
  }
  return { solved: false, closest: candidates[0].closest, aim: candidates[0].aim };
}
