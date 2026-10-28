// The game rules: the exo soldier's moves, suit modes and energy, crates,
// walls, targets, sentries and the lap timer. Pure data and maths with no
// three.js, stepped at a fixed rate, so the scripted demo and a Node check
// see exactly what the player sees. Every move number comes from the derive
// JSON (GET /api/derive/<model>); FEEL holds the few game-feel rules that
// have no physics behind them.

import {
  G,
  canStand,
  circleRect,
  crateBox,
  moveCapsule,
  rayBoxes,
  rectDistance,
  stepCrate,
} from "./physics.js";
import { WALL_KINDS, crateSize } from "./level.js";

export const STEP = 1 / 120;
export const MODES = ["armour", "strength", "speed", "cloak"];

export const FEEL = {
  run_frac: 0.6, // running without Shift, as a share of the sprint speed
  ground_accel: 30, // m/s2 towards the wanted speed on the ground
  air_accel: 5, // m/s2 of air control
  stand_h: 1.6,
  slide_h: 0.9,
  radius: 0.32,
  slide_decel: 3.0, // m/s2 lost while sliding
  slide_min_s: 0.45,
  slide_max_s: 1.1,
  punch_cooldown_s: 0.45,
  punch_reach_m: 1.0,
  lift_reach_m: 1.0,
  sentry_range_m: 32,
  sentry_period_s: 1.2,
  sentry_damage: 12,
  sentry_offline_s: 15,
  hp_regen: 8, // hp per second after hp_regen_delay_s without a hit
  hp_regen_delay_s: 4,
  target_reset_s: 6,
  crate_punch_cap_mps: 12,
  sprint_restart_frac: 0.25, // share of the bar needed to start sprinting again once it ran dry
  slam_min_h: 0.2, // m above the ground to start a ground slam
  hold_h: 0.9, // m, held crate centre above the feet
  hold_gap: 0, // m between the capsule (0.32 m, wider than the chest) and a held crate
};

const fwd = (yaw) => [Math.sin(yaw), Math.cos(yaw)];

export function createSim(stats, level) {
  const s = {
    t: 0,
    stats,
    level,
    events: [],
    messages: [],
    sentriesOn: true,
    lap: { running: false, t0: 0, next: 0, last: null, best: null },
  };
  reset(s);
  return s;
}

export function reset(s) {
  const L = s.level;
  s.statics = L.statics.slice();
  s.walls = L.walls.map((w, i) => ({ ...w, id: i, intact: true, def: WALL_KINDS[w.kind] }));
  s.crates = L.crates.map((c, i) => {
    const h = crateSize(c.kg) / 2;
    return { id: i, kg: c.kg, x: c.x, y: h, z: c.z, hx: h, hy: h, hz: h, vx: 0, vy: 0, vz: 0 };
  });
  s.targets = L.targets.map((t, i) => ({ ...t, id: i, down: false, downT: 0 }));
  s.sentries = L.sentries.map((t, i) => ({ ...t, id: i, y: 0, yaw: 0, cool: 1, seen: false, offT: 0 }));
  s.lap.running = false;
  s.lap.next = 0;
  respawn(s);
}

export function respawn(s) {
  const st = s.stats;
  const sp = s.level.spawn;
  const old = s.player;
  if (old && old.held) old.held.held = false;
  if (s.lap) s.lap.running = false;
  s.player = {
    x: sp.x,
    y: sp.y,
    z: sp.z,
    vx: 0,
    vy: 0,
    vz: 0,
    r: FEEL.radius,
    h: FEEL.stand_h,
    onGround: true,
    yaw: sp.yaw,
    mode: null,
    energy: st.energy.bar_j,
    lastDrain: -1e9,
    drainW: 0,
    hp: st.armour.hp,
    lastHit: -1e9,
    airBoost: false,
    airDash: false,
    dashT: 0,
    dashDir: [0, 1],
    sliding: false,
    slideT: 0,
    slamming: false,
    punchT: 0,
    punched: -1e9,
    held: null,
    armsBroken: false,
    sprinting: false,
    takeoffY: sp.y,
    maxY: sp.y,
    lastApex: 0,
    landedAt: -1e9,
  };
}

function say(s, text, kind = "info") {
  s.messages.push({ t: s.t, text, kind });
  if (s.messages.length > 6) s.messages.shift();
}

function emit(s, type, data = {}) {
  s.events.push({ type, t: s.t, ...data });
}

// The kick a boost gives: impulse / total mass, which the derive JSON carries
// as dash speed minus sprint speed.
export function boostDv(st) {
  const dv = st.move.dash_mps - st.move.sprint_mps;
  if (dv > 0) return dv;
  return Math.sqrt(Math.max(0, 2 * G * (st.move.boost_jump_m - st.move.jump_m)));
}

export function liftLimit(s) {
  const st = s.stats.strength;
  return s.player.mode === "strength" ? st.strength_lift_kg : st.lift_kg;
}

function spend(s, j, what) {
  const p = s.player;
  if (p.energy < j) {
    say(s, `Not enough energy for ${what}: needs ${Math.round(j)} J`, "warn");
    return false;
  }
  p.energy -= j;
  p.lastDrain = s.t;
  return true;
}

function solids(s) {
  const out = s.statics.slice();
  for (const w of s.walls) if (w.intact) out.push(w);
  for (const c of s.crates) if (!c.held) out.push(crateBox(c));
  return out;
}

function setMode(s, mode) {
  const p = s.player;
  if (p.mode === mode) {
    p.mode = null;
    say(s, `${cap(mode)} mode off`);
    return;
  }
  if (p.energy <= 1) {
    say(s, "No energy for a suit mode", "warn");
    return;
  }
  p.mode = mode;
  emit(s, "mode", { mode });
  say(s, `${cap(mode)} mode: ${Math.round(s.stats.energy.drain_w[mode])} W`);
}

const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);

// --- actions -------------------------------------------------------------

function doJump(s) {
  const p = s.player;
  const st = s.stats;
  if (p.onGround) {
    if (p.sliding && !endSlide(s)) return;
    p.vy = Math.sqrt(2 * G * st.move.jump_m);
    p.onGround = false;
    p.takeoffY = p.y;
    p.maxY = p.y;
    emit(s, "jump");
    return;
  }
  if (p.airBoost || p.slamming) return;
  if (!spend(s, st.energy.boost_j, "a boost jump")) return;
  p.vy = Math.max(p.vy, 0) + boostDv(st);
  p.airBoost = true;
  emit(s, "boost", { kind: "jump" });
}

function doDash(s, dir) {
  const p = s.player;
  const st = s.stats;
  if (p.dashT > 0 || p.slamming) return;
  if (!p.onGround && p.airDash) return;
  if (!spend(s, st.energy.boost_j, "a boost dash")) return;
  let d = dir;
  if (!d || Math.hypot(d[0], d[1]) < 0.1) d = fwd(p.yaw);
  const n = Math.hypot(d[0], d[1]);
  p.dashDir = [d[0] / n, d[1] / n];
  p.dashT = st.move.dash_s;
  if (p.sliding) endSlide(s, true);
  if (!p.onGround) p.airDash = true;
  emit(s, "boost", { kind: "dash" });
}

function doCrouch(s) {
  const p = s.player;
  const st = s.stats;
  if (!p.onGround) {
    if (p.slamming) return;
    const below = groundBelow(s);
    const h = p.y - (Number.isFinite(below) ? below : 0);
    if (h < FEEL.slam_min_h) {
      say(s, `Too low to slam: needs ${FEEL.slam_min_h} m of height`);
      return;
    }
    if (!spend(s, st.energy.boost_j, "a ground slam")) return;
    // The jets drive the soldier down: the fall from here plus the boost,
    // the same sum the derive's slam_j takes from the boost jump apex.
    p.slamV = Math.sqrt(2 * G * h) + boostDv(st);
    p.slamming = true;
    p.dashT = 0;
    emit(s, "boost", { kind: "slam" });
    return;
  }
  const speed = Math.hypot(p.vx, p.vz);
  if (!p.sliding && p.sprinting && speed > 0.7 * st.move.sprint_mps) {
    p.sliding = true;
    p.slideT = 0;
    p.h = FEEL.slide_h;
    emit(s, "slide");
  }
}

function endSlide(s, force = false) {
  const p = s.player;
  if (!force && !canStand(p, solids(s), FEEL.stand_h)) return false;
  p.sliding = false;
  p.h = FEEL.stand_h;
  return true;
}

function groundBelow(s) {
  const p = s.player;
  let top = -Infinity;
  for (const o of solids(s)) {
    if (o.max[1] > p.y + 1e-3) continue;
    if (circleRect(p.x, p.z, p.r * 0.9, o)) top = Math.max(top, o.max[1]);
  }
  return top;
}

export function nearestCrate(s, reach = FEEL.lift_reach_m) {
  const p = s.player;
  const [fx, fz] = fwd(p.yaw);
  let best = null;
  let bestD = Infinity;
  for (const c of s.crates) {
    if (c.held) continue;
    const dx = c.x - p.x;
    const dz = c.z - p.z;
    const along = dx * fx + dz * fz;
    const d = rectDistance(p.x, p.z, crateBox(c)) - p.r;
    // Not one too high, and not the one underfoot.
    if (along <= 0 || d > reach || c.y - c.hy > p.y + 1.2 || c.y + c.hy <= p.y + 0.05) continue;
    if (d < bestD) {
      best = c;
      bestD = d;
    }
  }
  return best;
}

function doUse(s) {
  const p = s.player;
  const st = s.stats.strength;
  if (p.held) {
    const c = p.held;
    c.held = false;
    c.sleeping = false;
    c.vx = p.vx;
    c.vz = p.vz;
    c.vy = 0;
    p.held = null;
    emit(s, "drop", { crate: c.id });
    return;
  }
  if (p.armsBroken) {
    say(s, "Arms broken: press {repair} to repair", "warn");
    return;
  }
  const c = nearestCrate(s, FEEL.lift_reach_m);
  if (!c) {
    say(s, "Nothing to lift in reach");
    return;
  }
  const limit = liftLimit(s);
  if (c.kg > st.break_kg) {
    p.armsBroken = true;
    say(s, `Arms broken: ${c.kg} kg is over the frame's ${st.break_kg} kg break load. {repair} repairs`, "bad");
    emit(s, "break", { crate: c.id, kg: c.kg });
    return;
  }
  if (c.kg > limit) {
    const hint =
      p.mode !== "strength" && st.strength_lift_kg > st.lift_kg
        ? ` (Strength mode: ${st.strength_lift_kg} kg)`
        : "";
    say(s, `Too heavy: ${c.kg} kg, your lift is ${limit} kg${hint}`, "warn");
    emit(s, "refuse", { crate: c.id, kg: c.kg, limit });
    return;
  }
  c.held = true;
  c.sleeping = false;
  p.held = c;
  emit(s, "lift", { crate: c.id, kg: c.kg });
}

function doPunch(s, pitch) {
  const p = s.player;
  const st = s.stats.strength;
  if (p.held) return doThrow(s, pitch);
  if (p.armsBroken) {
    say(s, "Arms broken: press {repair} to repair", "warn");
    return;
  }
  if (p.punchT > 0) return;
  p.punchT = FEEL.punch_cooldown_s;
  p.punched = s.t;
  const e = p.mode === "strength" ? st.strength_punch_j : st.punch_j;
  if (p.mode === "cloak") {
    p.mode = null;
    say(s, "Cloak dropped by the punch");
  }
  const [fx, fz] = fwd(p.yaw);
  const hx = p.x + fx * (p.r + FEEL.punch_reach_m * 0.6);
  const hz = p.z + fz * (p.r + FEEL.punch_reach_m * 0.6);
  const hy = p.y + Math.min(p.h, 1.2);
  const hit = { e, what: null };
  for (const t of s.targets) {
    if (t.down) continue;
    if (Math.hypot(t.x - hx, t.z - hz) < 0.75 && Math.abs(t.y - hy) < 0.9) {
      knockTarget(s, t);
      hit.what = "target";
    }
  }
  for (const w of s.walls) {
    if (!w.intact || hit.what) continue;
    if (rectDistance(hx, hz, w) > 0.45 || hy < w.min[1] || hy > w.max[1] + 0.3) continue;
    if (e >= w.def.break_j) {
      breakWall(s, w, "punch", e);
    } else {
      say(s, `${w.def.name} holds: needs ${w.def.break_j} J, your punch is ${Math.round(e)} J`, "warn");
    }
    hit.what = "wall";
  }
  for (const sn of s.sentries) {
    if (hit.what || sn.offT > 0) continue;
    if (Math.hypot(sn.x - hx, sn.z - hz) < 0.9) {
      sn.offT = FEEL.sentry_offline_s;
      say(s, "Sentry knocked offline");
      hit.what = "sentry";
    }
  }
  if (!hit.what) {
    const c = nearestCrate(s, FEEL.punch_reach_m);
    if (c) {
      const v = Math.min(FEEL.crate_punch_cap_mps, Math.sqrt((2 * e) / c.kg));
      c.sleeping = false;
      c.vx += fx * v * 0.95;
      c.vz += fz * v * 0.95;
      c.vy += v * 0.3;
      hit.what = "crate";
    }
  }
  emit(s, "punch", { e, hit: hit.what });
}

function doThrow(s, pitch = 0) {
  const p = s.player;
  const st = s.stats.strength;
  const c = p.held;
  const e = p.mode === "strength" ? st.strength_throw_j : st.throw_j;
  const v = Math.min(st.throw_cap_mps, Math.sqrt((2 * e) / (c.kg + st.arm_mass_kg)));
  const a = Math.max(-0.3, Math.min(1.0, pitch + 0.2));
  const [fx, fz] = fwd(p.yaw);
  c.held = false;
  c.sleeping = false;
  c.vx = p.vx + fx * v * Math.cos(a);
  c.vz = p.vz + fz * v * Math.cos(a);
  c.vy = v * Math.sin(a);
  c.thrown = true;
  p.held = null;
  p.punched = s.t;
  if (p.mode === "cloak") {
    p.mode = null;
    say(s, "Cloak broken by the throw", "warn");
  }
  emit(s, "throw", { crate: c.id, v, e });
}

function knockTarget(s, t) {
  t.down = true;
  t.downT = FEEL.target_reset_s;
  emit(s, "target", { id: t.id });
}

function breakWall(s, w, by, e) {
  w.intact = false;
  emit(s, "wall", { id: w.id, by, e });
  say(s, `${w.def.name} broken by ${by} (${Math.round(e)} J >= ${w.def.break_j} J)`, "good");
}

function slamImpact(s) {
  const p = s.player;
  const st = s.stats.move;
  const R = st.slam_radius_m;
  const E = 0.5 * s.stats.mass.total_kg * p.slamV * p.slamV;
  p.slamming = false;
  for (const w of s.walls) {
    if (!w.intact || rectDistance(p.x, p.z, w) > R) continue;
    if (E >= w.def.break_j) breakWall(s, w, "slam", E);
    else say(s, `${w.def.name} holds: needs ${w.def.break_j} J, slam is ${Math.round(E)} J`, "warn");
  }
  for (const t of s.targets) {
    if (!t.down && Math.hypot(t.x - p.x, t.z - p.z) <= R) knockTarget(s, t);
  }
  for (const c of s.crates) {
    if (c.held) continue;
    const dx = c.x - p.x;
    const dz = c.z - p.z;
    const d = Math.hypot(dx, dz);
    if (d > R) continue;
    const share = 0.05 * (1 - d / R);
    const v = Math.min(10, Math.sqrt((2 * E * share) / c.kg));
    const n = Math.max(d, 0.01);
    c.sleeping = false;
    c.vx += (dx / n) * v;
    c.vz += (dz / n) * v;
    c.vy += v * 0.6;
  }
  emit(s, "slam", { e: E, r: R, x: p.x, y: p.y, z: p.z });
}

export function damage(s, hp) {
  const p = s.player;
  const mult = p.mode === "armour" ? s.stats.armour.armour_mode_damage_mult : 1;
  p.hp -= hp * mult;
  p.lastHit = s.t;
  emit(s, "hurt", { hp: hp * mult });
  if (p.hp <= 0) {
    say(s, "Suit down: back to the start", "bad");
    emit(s, "down");
    respawn(s);
  }
}

// --- the step ------------------------------------------------------------

// input: { wish: [x, z] world direction (length 0..1), yaw, pitch, sprint,
// walk, actions: [{ type, dir?, mode? }] } -- actions are used up here.
export function step(s, input, dt = STEP) {
  const p = s.player;
  const st = s.stats;
  s.t += dt;
  for (const a of input.actions.splice(0)) {
    if (a.type === "jump") doJump(s);
    else if (a.type === "dash") doDash(s, a.dir || input.wish);
    else if (a.type === "crouch") doCrouch(s);
    else if (a.type === "punch") doPunch(s, input.pitch || 0);
    else if (a.type === "use") doUse(s);
    else if (a.type === "mode") setMode(s, a.mode);
    else if (a.type === "repair") {
      if (p.armsBroken) say(s, "Arms repaired");
      p.armsBroken = false;
    } else if (a.type === "respawn") respawn(s);
    else if (a.type === "restart") {
      // The pause menu's Restart: walls, crates, targets and sentries come
      // back and the soldier starts again; the best lap is kept.
      reset(s);
      say(s, "Range reset: back to the start");
    }
  }
  const q = s.player;
  const wish = input.wish || [0, 0];
  const wl = Math.min(1, Math.hypot(wish[0], wish[1]));
  const speedNow = Math.hypot(q.vx, q.vz);

  // Energy: the mode drains, sprinting drains the legs, a boost spends at
  // once; the bar recharges after a quiet spell.
  q.sprinting =
    !!input.sprint &&
    wl > 0.1 &&
    q.energy > 0 &&
    !q.sprintLock &&
    !q.held &&
    !q.sliding &&
    (q.onGround || q.sprinting);
  let w = q.mode ? st.energy.drain_w[q.mode] : 0;
  if (q.sprinting && q.mode !== "speed") w += st.energy.drain_w.sprint;
  q.drainW = w;
  if (w > 0) {
    q.energy -= w * dt;
    q.lastDrain = s.t;
  } else if (s.t - q.lastDrain >= st.energy.recharge_delay_s) {
    q.energy = Math.min(st.energy.bar_j, q.energy + st.energy.recharge_w * dt);
  }
  if (q.energy >= FEEL.sprint_restart_frac * st.energy.bar_j) q.sprintLock = false;
  if (q.energy <= 0) {
    q.energy = 0;
    q.sprintLock = true;
    if (q.mode) say(s, `Energy empty: ${q.mode} mode off`, "warn");
    q.mode = null;
    q.sprinting = false;
  }
  if (q.held && q.held.kg > liftLimit(s)) {
    const c = q.held;
    c.held = false;
    c.sleeping = false;
    c.vx = q.vx;
    c.vz = q.vz;
    c.vy = 0;
    q.held = null;
    say(s, `Dropped ${c.kg} kg: over your ${liftLimit(s)} kg lift without Strength mode`, "warn");
    emit(s, "drop", { crate: c.id });
  }

  // Horizontal velocity.
  const top = q.mode === "speed" ? st.move.speed_mode_mps : st.move.sprint_mps;
  let want = input.walk ? st.move.walk_mps : q.sprinting ? top : FEEL.run_frac * top;
  if (q.held) want = Math.min(want, FEEL.run_frac * st.move.sprint_mps);
  if (q.dashT > 0) {
    q.vx = q.dashDir[0] * st.move.dash_mps;
    q.vz = q.dashDir[1] * st.move.dash_mps;
    q.dashT -= dt;
  } else if (q.sliding) {
    q.slideT += dt;
    const k = Math.max(0, speedNow - FEEL.slide_decel * dt) / Math.max(speedNow, 1e-6);
    q.vx *= k;
    q.vz *= k;
    const slow = Math.hypot(q.vx, q.vz) < st.move.walk_mps;
    if (q.slideT > FEEL.slide_max_s || (slow && q.slideT > FEEL.slide_min_s)) {
      if (!endSlide(s)) {
        const n = Math.max(Math.hypot(q.vx, q.vz), 1e-6);
        const keep = Math.max(n, st.move.walk_mps) / n;
        q.vx *= keep;
        q.vz *= keep;
      }
    }
  } else if (q.slamming) {
    q.vx *= Math.max(0, 1 - 6 * dt);
    q.vz *= Math.max(0, 1 - 6 * dt);
  } else {
    const tx = wl > 0.01 ? (wish[0] / Math.max(wl, 1e-6)) * want * wl : 0;
    const tz = wl > 0.01 ? (wish[1] / Math.max(wl, 1e-6)) * want * wl : 0;
    const acc = (q.onGround ? FEEL.ground_accel : FEEL.air_accel) * dt;
    const dx = tx - q.vx;
    const dz = tz - q.vz;
    const dl = Math.hypot(dx, dz);
    if (q.onGround || wl > 0.01) {
      const k = dl > acc ? acc / dl : 1;
      q.vx += dx * k;
      q.vz += dz * k;
    }
  }

  // Vertical velocity.
  if (q.slamming) {
    q.vy = -q.slamV;
  } else if (q.dashT > 0 && !q.onGround) {
    q.vy = Math.max(q.vy, 0);
  }
  // Gravity in two half steps around the move (exact apex for a jump).
  const falling = !q.onGround && !q.slamming && !(q.dashT > 0);
  if (falling) q.vy -= (G * dt) / 2;

  const wasGround = q.onGround;
  const fallV = q.vy;
  moveCapsule(q, solids(s), dt);
  if (falling && !q.onGround) q.vy -= (G * dt) / 2;
  if (!q.onGround) q.maxY = Math.max(q.maxY, q.y);
  if (wasGround && !q.onGround) {
    q.takeoffY = q.y;
    q.maxY = q.y;
  }
  if (q.onGround && !wasGround) {
    q.lastApex = q.maxY - q.takeoffY;
    q.landedAt = s.t;
    q.airBoost = false;
    q.airDash = false;
    emit(s, "land", { v: -fallV, apex: q.lastApex });
    if (q.slamming) slamImpact(s);
  }
  if (q.onGround) q.slamming = false;

  // Facing: follow the camera while holding or punching, else the motion.
  if (q.held || s.t - q.punched < 0.4 || q.armsBroken) {
    q.yaw = input.yaw ?? q.yaw;
  } else if (Math.hypot(q.vx, q.vz) > 0.3) {
    const target = Math.atan2(q.vx, q.vz);
    let d = target - q.yaw;
    d = Math.atan2(Math.sin(d), Math.cos(d));
    q.yaw += d * Math.min(1, dt * 14);
  }
  q.punchT = Math.max(0, q.punchT - dt);

  // Hit points regenerate after a quiet spell.
  if (s.t - q.lastHit > FEEL.hp_regen_delay_s) q.hp = Math.min(st.armour.hp, q.hp + FEEL.hp_regen * dt);

  // Crates.
  const statics = s.statics.concat(s.walls.filter((w2) => w2.intact));
  if (q.held) {
    const c = q.held;
    const [fx, fz] = fwd(q.yaw);
    const hy = q.y + FEEL.hold_h;
    const hit = rayBoxes([q.x, hy, q.z], [fx, 0, fz], statics, 3);
    const d = Math.max(0, Math.min(q.r + c.hz + FEEL.hold_gap, hit - c.hz - 0.02));
    c.x = q.x + fx * d;
    c.z = q.z + fz * d;
    c.y = hy;
    c.vx = c.vy = c.vz = 0;
  }
  for (const c of s.crates) {
    const sp = Math.hypot(c.vx, c.vy, c.vz);
    stepCrate(c, statics, s.crates, dt);
    if (c.held || sp < 2) continue;
    const ke = 0.5 * c.kg * sp * sp;
    const cb = crateBox(c);
    for (const t of s.targets) {
      if (t.down) continue;
      if (Math.abs(t.x - c.x) < c.hx + 0.45 && Math.abs(t.z - c.z) < c.hz + 0.45 && Math.abs(t.y - c.y) < c.hy + 0.5) {
        knockTarget(s, t);
      }
    }
    for (const w2 of s.walls) {
      if (!w2.intact) continue;
      const hit = [0, 1, 2].every((i) => cb.max[i] + 0.03 > w2.min[i] && cb.min[i] - 0.03 < w2.max[i]);
      if (hit && ke >= w2.def.break_j) breakWall(s, w2, `a ${c.kg} kg crate`, ke);
    }
  }

  // Targets pop back up.
  for (const t of s.targets) {
    if (!t.down) continue;
    t.downT -= dt;
    if (t.downT <= 0) t.down = false;
  }

  // Sentries shoot what they can see; Cloak hides you.
  const losBoxes = s.statics.filter((o) => o.kind !== "ground").concat(s.walls.filter((w2) => w2.intact));
  for (const sn of s.sentries) {
    if (sn.offT > 0) {
      sn.offT -= dt;
      sn.seen = false;
      continue;
    }
    const eye = [sn.x, 1.3, sn.z];
    const aim = [q.x, q.y + 1.2, q.z];
    const d = [aim[0] - eye[0], aim[1] - eye[1], aim[2] - eye[2]];
    const dist = Math.hypot(...d);
    let sees = s.sentriesOn && q.mode !== "cloak" && dist < FEEL.sentry_range_m;
    if (sees) {
      const u = d.map((v) => v / dist);
      sees = rayBoxes(eye, u, losBoxes, dist) >= dist - 0.4;
    }
    if (sees) {
      const target = Math.atan2(d[0], d[2]);
      let dy = target - sn.yaw;
      dy = Math.atan2(Math.sin(dy), Math.cos(dy));
      sn.yaw += dy * Math.min(1, dt * 6);
      if (!sn.seen) sn.cool = FEEL.sentry_period_s;
      sn.cool -= dt;
      if (sn.cool <= 0) {
        sn.cool = FEEL.sentry_period_s;
        emit(s, "shot", { from: eye, to: aim, id: sn.id });
        damage(s, FEEL.sentry_damage);
      }
    }
    sn.seen = sees;
  }

  // Lap timer: start line, checkpoints in order, finish.
  const inside = (b) =>
    q.x >= b.min[0] && q.x <= b.max[0] && q.y >= b.min[1] && q.y <= b.max[1] && q.z >= b.min[2] && q.z <= b.max[2];
  const lap = s.lap;
  const L = s.level;
  if (inside(L.start)) {
    if (!lap.running) for (const w of s.walls) w.intact = true;
    lap.running = true;
    lap.t0 = s.t;
    lap.next = 0;
  }
  if (lap.running && lap.next < L.checkpoints.length && inside(L.checkpoints[lap.next])) {
    lap.next += 1;
    emit(s, "checkpoint", { n: lap.next });
  }
  if (lap.running && inside(L.finish)) {
    if (lap.next >= L.checkpoints.length) {
      lap.last = s.t - lap.t0;
      // lap.best may come from an earlier visit (game/records.js).
      const beat = lap.best != null && lap.last < lap.best;
      lap.best = lap.best == null ? lap.last : Math.min(lap.best, lap.last);
      lap.running = false;
      emit(s, "lap", { time: lap.last, best: beat });
      say(s, `Lap ${lap.last.toFixed(2)} s${beat ? ", a new best" : ""}`, "good");
    }
  }
}

export function lapTime(s) {
  const lap = s.lap;
  if (lap.running) return s.t - lap.t0;
  return lap.last;
}
