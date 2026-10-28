/* The rider: one button, and the physics behind it.

   On the ground the rider slides along the slope, pulled by gravity and held
   between a minimum and a maximum speed. Tapping jumps; holding in the air
   turns a backflip. Coming down, the board must meet the ground within the
   landing forgiveness, or it is a crash. A rope caught from above is a grind.

   step() is pure over (rider, world, input, params, dt) and reports what
   happened as events, so the game decides what a crash means (the end of a
   run, or a stumble in zen) and the tests can drive it without a screen. */

import { ropeY } from "./world.js";

export const DEFAULTS = {
  gravity: 1500,
  jump: 620,
  flip_speed: 7.5,
  min_speed: 280,
  max_speed: 1150,
  forgiveness: 45, // degrees either side of the slope
  friction: 0.18,
};

const TAU = Math.PI * 2;

export function wrapAngle(a) {
  return Math.atan2(Math.sin(a), Math.cos(a));
}

// Whole backflips in a turn of `rot` radians; a flip lands a little short.
export function countFlips(rot) {
  return Math.floor((Math.abs(rot) + 1.0) / TAU);
}

export function newRider(world) {
  const x = 200;
  return {
    x, y: world.groundAt(x) ?? 0, vx: DEFAULTS.min_speed, vy: 0, speed: DEFAULTS.min_speed,
    angle: world.slopeAt(x), rot: 0, state: "ground", rope: null,
    airTime: 0, takeoffX: x, boost: 0, crashT: 0, jumpFlips: 0,
  };
}

function airborne(rider) {
  rider.state = "air";
  rider.rot = 0;
  rider.airTime = 0;
  rider.takeoffX = rider.x;
}

export function step(rider, world, input, p, dt, events = []) {
  const g = p.gravity;
  if (rider.state === "crashed") {
    rider.crashT += dt;
    rider.vy += g * dt;
    rider.vx *= Math.pow(0.4, dt);
    rider.x += rider.vx * dt;
    rider.y += rider.vy * dt;
    rider.angle += 9 * dt * Math.max(0.1, rider.vx / 600);
    const gy = world.groundAt(rider.x);
    if (gy !== null && rider.y > gy) { rider.y = gy; rider.vy *= -0.25; }
    return events;
  }

  const minSpeed = p.min_speed + (rider.boost > 0 ? 220 : 0);
  rider.boost = Math.max(0, rider.boost - dt);

  if (rider.state === "rope") {
    const r = rider.rope;
    const slope = Math.atan2(ropeY(r, rider.x + 4) - ropeY(r, rider.x - 4), 8);
    rider.speed = Math.min(p.max_speed, Math.max(minSpeed, rider.speed + g * Math.sin(slope) * 0.5 * dt));
    const dx = rider.speed * Math.cos(slope) * dt;
    rider.x += dx;
    rider.angle = slope;
    events.push({ type: "grinding", px: Math.hypot(dx, dx * Math.tan(slope)) });
    if (input.pressed) {
      rider.y = ropeY(r, rider.x);
      rider.vx = rider.speed * Math.cos(slope);
      rider.vy = rider.speed * Math.sin(slope) - p.jump * 0.9;
      rider.rope = null;
      airborne(rider);
      events.push({ type: "jump", from: "rope" });
    } else if (rider.x >= r.x2) {
      rider.vx = rider.speed * Math.cos(slope);
      rider.vy = rider.speed * Math.sin(slope);
      rider.rope = null;
      airborne(rider);
      events.push({ type: "rope-end" });
    } else {
      rider.y = ropeY(r, rider.x);
    }
    return events;
  }

  if (rider.state === "ground") {
    const gy = world.groundAt(rider.x);
    if (gy === null) { airborne(rider); return events; }
    const th = world.slopeAt(rider.x);
    rider.speed += (g * Math.sin(th) - p.friction * rider.speed) * dt;
    rider.speed = Math.min(p.max_speed, Math.max(minSpeed, rider.speed));
    rider.vx = rider.speed * Math.cos(th);
    rider.vy = rider.speed * Math.sin(th);
    rider.angle += wrapAngle(th - rider.angle) * Math.min(1, dt * 14);
    if (input.pressed) {
      rider.vy -= p.jump;
      rider.vx += Math.sin(th) * p.jump * 0.15;
      rider.y = gy;
      airborne(rider);
      events.push({ type: "jump", from: "ground" });
      return events;
    }
    const nx = rider.x + rider.vx * dt;
    const ny = world.groundAt(nx);
    const flying = rider.y + rider.vy * dt;
    rider.x = nx;
    if (ny === null || ny > flying + 3) {
      // the ground falls away faster than we do: off a crest or a lip
      rider.y = flying;
      airborne(rider);
      events.push({ type: "launch" });
    } else {
      rider.y = ny;
    }
    return events;
  }

  // --- in the air
  rider.airTime += dt;
  rider.vy += g * dt;
  rider.vx = Math.max(p.min_speed * 0.6, rider.vx * (1 - 0.05 * dt));
  const prevY = rider.y, prevX = rider.x;
  rider.x += rider.vx * dt;
  rider.y += rider.vy * dt;
  if (input.held) {
    const turn = p.flip_speed * dt;
    rider.angle -= turn;
    rider.rot += turn;
  }

  // a rope caught from above
  if (rider.vy > 0) {
    for (const r of world.ropes) {
      if (rider.x < r.x1 || rider.x > r.x2 - 20) continue;
      const ry = ropeY(r, rider.x), pry = ropeY(r, prevX);
      if (prevY <= pry + 2 && rider.y >= ry) {
        const slope = Math.atan2(r.y2 - r.y1, r.x2 - r.x1);
        if (!landable(rider, slope, p)) return crash(rider, events, "rope");
        const flips = countFlips(rider.rot);
        rider.state = "rope";
        rider.rope = r;
        rider.y = ry;
        rider.speed = Math.min(p.max_speed, Math.max(minSpeed, Math.hypot(rider.vx, rider.vy) * 0.9));
        events.push({ type: "land", on: "rope", flips, airTime: rider.airTime, takeoffX: rider.takeoffX });
        return events;
      }
    }
  }

  const gy = world.groundAt(rider.x);
  if (gy !== null && rider.y >= gy) {
    const th = world.slopeAt(rider.x);
    if (!landable(rider, th, p)) return crash(rider, events, "landing");
    const flips = countFlips(rider.rot);
    // keep the part of the fall that runs along the slope
    const along = rider.vx * Math.cos(th) + rider.vy * Math.sin(th);
    rider.speed = Math.min(p.max_speed, Math.max(minSpeed, along));
    rider.y = gy;
    rider.state = "ground";
    rider.angle = th + wrapAngle(rider.angle - th) * 0.5;
    events.push({ type: "land", on: "ground", flips, airTime: rider.airTime, takeoffX: rider.takeoffX });
    return events;
  }
  if (rider.y > world.floorNear(rider.x) + 500) return crash(rider, events, "chasm");
  return events;
}

export function landable(rider, slope, p) {
  return Math.abs(wrapAngle(rider.angle - slope)) <= (p.forgiveness * Math.PI) / 180;
}

export function crash(rider, events, cause) {
  rider.state = "crashed";
  rider.crashT = 0;
  events.push({ type: "crash", cause });
  return events;
}

// A rock bounce: the rider landed on a rock top from the air. The game calls
// this when it sees the overlap, so rocks stay the game's business.
export function bounce(rider, p) {
  rider.vy = -p.jump * 0.85;
  rider.state = "air";
  rider.rot = rider.rot % TAU;
}

// Zen mode: pick the rider up where it fell and set it going again.
export function recover(rider, world) {
  let x = rider.x;
  for (let i = 0; i < 400 && world.groundAt(x) === null; i++) x += 16;
  rider.x = x;
  rider.y = world.groundAt(x) ?? rider.y;
  rider.angle = world.slopeAt(x);
  rider.state = "ground";
  rider.speed = DEFAULTS.min_speed;
  rider.rot = 0;
}
