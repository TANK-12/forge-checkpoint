// Scripted demo (game.html?demo=1): drives the same input the keyboard
// does and checks the moves against the derive JSON. The result goes to
// window.__exoDemo = { ok, checks: [...] } and onto the screen. Between
// checks the demo moves the soldier to the right spot and tops the energy
// bar up, so one check cannot starve the next; that is the only cheating.

import { G } from "./physics.js";

function near(got, want, tol) {
  return Math.abs(got - want) <= Math.abs(want) * tol;
}

export async function runDemo(game) {
  const { sim, input } = game;
  const st = sim.stats;
  const checks = [];
  const add = (name, ok, got, want, note = "") => {
    checks.push({ name, ok: !!ok, got, want, note });
    game.demoPanel(checks);
  };
  const p = () => sim.player;
  const clear = () => {
    input.wish = [0, 0];
    input.sprint = false;
    input.walk = false;
    input.actions.length = 0;
  };
  const place = (x, z, yaw = 0) => {
    const q = p();
    Object.assign(q, { x, y: 0, z, vx: 0, vy: 0, vz: 0, yaw, dashT: 0, sliding: false, h: 1.6, slamming: false });
    q.onGround = true;
    input.yaw = yaw;
    game.lookAt(yaw);
  };
  // Topping up counts as a drain, so the recharge delay starts again and the
  // next energy check reads only what the move cost.
  const refill = () => {
    p().energy = st.energy.bar_j;
    p().mode = null;
    p().lastDrain = sim.t;
  };
  const press = (type, extra = {}) => input.actions.push({ type, ...extra });
  // The page hands each frame's events to the view, so the demo keeps its
  // own copy through game.onEvent; without a page they stay in sim.events.
  const seen = [];
  game.onEvent = (e) => seen.push(e);
  const last = (type) => seen.concat(sim.events).filter((e) => e.type === type).pop();
  sim.sentriesOn = false;

  // Walk and sprint on the open ground west of the course.
  clear();
  place(-42, -30, 0);
  await game.run(0.4);
  input.wish = [0, 1];
  input.walk = true;
  await game.run(1.5);
  const walk = Math.hypot(p().vx, p().vz);
  add("walk speed", near(walk, st.move.walk_mps, 0.05), walk, st.move.walk_mps, "within 5%");
  input.walk = false;
  input.sprint = true;
  await game.run(1.6);
  const sprint = Math.hypot(p().vx, p().vz);
  add("sprint speed", near(sprint, st.move.sprint_mps, 0.05), sprint, st.move.sprint_mps, "within 5%");
  const e0 = p().energy;
  await game.run(1.0);
  add("sprint drains", near(e0 - p().energy, st.energy.drain_w.sprint, 0.05), e0 - p().energy, st.energy.drain_w.sprint, "J over 1 s");

  // Slide: sprint at the slide bar, which only a sliding soldier fits under.
  clear();
  refill();
  place(0, 31.5, 0);
  input.wish = [0, 1];
  input.sprint = true;
  await game.run(0.6);
  press("crouch");
  await game.run(0.25);
  const slid = p().sliding && p().h < 1.0;
  await game.run(1.4);
  add("slide under the 1.0 m bar", slid && p().z > 36.6, p().z, 36.6, "z after the slide");
  clear();
  await game.run(0.3);

  // Jump, then the boost jump fired at the top of the first jump.
  refill();
  place(-42, 0, 0);
  await game.run(0.3);
  press("jump");
  await game.run(1.0);
  add("jump height", near(p().lastApex, st.move.jump_m, 0.1), p().lastApex, st.move.jump_m, "apex within 10%");
  await game.run(0.4);
  refill();
  const eb = p().energy;
  press("jump");
  let fired = false;
  let ea = null;
  await game.run(2.0, () => {
    if (fired && ea === null) ea = p().energy;
    if (!fired && !p().onGround && p().vy <= 0) {
      press("jump");
      fired = true;
    }
  });
  add("boost jump height", near(p().lastApex, st.move.boost_jump_m, 0.1), p().lastApex, st.move.boost_jump_m, "apex within 10%");
  add("boost costs boost_j", ea !== null && near(eb - ea, st.energy.boost_j, 0.02), eb - (ea ?? eb), st.energy.boost_j, "J, read the step after it fires");

  // Boost dash.
  await game.run(0.5);
  refill();
  let dashV = 0;
  press("dash", { dir: [0, 1] });
  await game.run(0.2, () => (dashV = Math.max(dashV, Math.hypot(p().vx, p().vz))));
  add("dash speed", near(dashV, st.move.dash_mps, 0.05), dashV, st.move.dash_mps, "within 5%");
  await game.run(0.8);

  // Ground slam next to the concrete wall: jump, boost, slam.
  refill();
  const wall = sim.walls.find((w) => w.kind === "concrete");
  place(-16, wall.min[2] - 1.2, 0);
  await game.run(0.3);
  press("jump");
  let stage = 0;
  await game.run(2.5, () => {
    if (stage === 0 && !p().onGround && p().vy <= 0) {
      press("jump");
      stage = 1;
    } else if (stage === 1 && p().vy <= 0 && !p().onGround && p().y > 0.9) {
      press("crouch");
      stage = 2;
    }
  });
  const slam = last("slam");
  const vSlam = Math.sqrt(2 * G * st.move.boost_jump_m) + (st.move.dash_mps - st.move.sprint_mps);
  const ke = 0.5 * st.mass.total_kg * vSlam * vSlam;
  add("slam lands with slam_j", !!slam && near(slam.e, st.move.slam_j, 0.02) && near(ke, st.move.slam_j, 0.05), slam ? slam.e : 0, st.move.slam_j, `1/2 m v2 = ${Math.round(ke)} J`);
  const shouldBreak = st.move.slam_j >= wall.def.break_j;
  add(`slam vs concrete (${wall.def.break_j} J)`, wall.intact !== shouldBreak, wall.intact ? "holds" : "broken", shouldBreak ? "broken" : "holds");

  // Suit modes: each drains at its own watts.
  clear();
  place(-42, 10, 0);
  await game.run(0.2);
  for (const mode of ["armour", "strength", "speed", "cloak"]) {
    refill();
    press("mode", { mode });
    await game.run(0.05);
    const a = p().energy;
    await game.run(0.5);
    const used = (a - p().energy) / 0.5;
    add(`${mode} mode drain`, p().mode === mode && near(used, st.energy.drain_w[mode], 0.05), used, st.energy.drain_w[mode], "W");
    press("mode", { mode });
    await game.run(0.05);
  }

  // Crates: lift the lightest, throw it, then try the heavy ones.
  refill();
  const tryLift = async (kg) => {
    const c = sim.crates.find((x) => x.kg === kg);
    if (p().held) {
      press("use");
      await game.run(0.1);
    }
    place(c.x - c.hx - p().r - 0.25, c.z, Math.PI / 2);
    await game.run(0.35);
    press("use");
    await game.run(0.15);
    return { held: !!p().held, c };
  };
  const light = sim.crates.reduce((a, c) => (c.kg < a.kg ? c : a));
  const r1 = await tryLift(light.kg);
  add(`lift ${light.kg} kg (limit ${st.strength.lift_kg} kg)`, r1.held === light.kg <= st.strength.lift_kg, r1.held ? "lifted" : "refused", light.kg <= st.strength.lift_kg ? "lifted" : "refused");
  if (r1.held) {
    game.lookAt(Math.PI / 2);
    press("punch");
    // The crate's own speed the step after it leaves the hands.
    let thrownV = null;
    await game.run(0.05, () => {
      if (thrownV === null && !light.held && light.thrown) thrownV = Math.hypot(light.vx - p().vx, light.vy, light.vz - p().vz);
    });
    const want = Math.min(st.strength.throw_cap_mps, Math.sqrt((2 * st.strength.throw_j) / (light.kg + st.strength.arm_mass_kg)));
    add("throw speed", thrownV !== null && near(thrownV, want, 0.03), thrownV ?? 0, want, "m/s, sqrt(2E / (crate + arms)), measured on the crate");
    await game.run(1.0);
  }
  const over = sim.crates.filter((c) => c.kg > st.strength.lift_kg && c.kg <= st.strength.break_kg).sort((a, b) => a.kg - b.kg)[0];
  if (over) {
    const r2 = await tryLift(over.kg);
    const ref = last("refuse");
    const refused = !r2.held && !!ref && ref.crate === over.id;
    add(`crate over lift_kg refuses (${over.kg} kg)`, refused, refused ? "refused" : r2.held ? "lifted" : "no refusal", "refused");
  } else add("crate over lift_kg refuses", true, "skipped", "refused", `no crate between ${st.strength.lift_kg} and ${st.strength.break_kg} kg`);
  const broke = sim.crates.find((c) => c.kg > st.strength.break_kg);
  if (!broke) add("crate over break_kg breaks the arms", true, "skipped", "arms broken", `no crate over ${st.strength.break_kg} kg`);
  if (broke) {
    const r3 = await tryLift(broke.kg);
    const brk = last("break");
    const ok3 = !r3.held && p().armsBroken && !!brk && brk.crate === broke.id;
    add(`crate over break_kg breaks the arms (${broke.kg} kg)`, ok3, p().armsBroken ? "arms broken" : "intact", "arms broken");
    await game.run(0.8);
    press("repair");
    await game.run(0.1);
  }

  // Punch a target and the plaster wall.
  refill();
  const t = sim.targets[0];
  place(t.x, t.z - 1.0, 0);
  await game.run(0.3);
  press("punch");
  await game.run(0.4);
  add("punch knocks a target down", t.down, t.down ? "down" : "standing", "down");
  const plaster = sim.walls.find((w) => w.kind === "plaster" && w.min[0] < -10);
  place((plaster.min[0] + plaster.max[0]) / 2, plaster.min[2] - 0.75, 0);
  await game.run(0.6);
  press("punch");
  await game.run(0.8);
  const pBreak = st.strength.punch_j >= plaster.def.break_j;
  add(`punch vs plaster (${plaster.def.break_j} J)`, plaster.intact !== pBreak, plaster.intact ? "holds" : "broken", pBreak ? "broken" : "holds");

  // Finish on the course, looking down range.
  clear();
  refill();
  place(0, -3, 0);
  sim.sentriesOn = true;
  await game.run(0.5);
  const ok = checks.every((c) => c.ok);
  window.__exoDemo = { ok, checks, model: st.model, profile: st.profile, source: game.source };
  game.demoPanel(checks, ok);
  return window.__exoDemo;
}
