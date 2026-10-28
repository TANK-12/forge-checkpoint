/* Who steps the world: a Web Worker when the page can start one, else the page itself.
 *
 * At detail 2 a frame takes four steps of a 480 by 270 grid, about 10 to 15 ms
 * on the Latitude; done on the page's own thread that leaves no room for
 * drawing and the brush. So the worker (worker.js) holds the real world and
 * steps it, and the page keeps a copy (the mirror) that it draws, reads the
 * hover temperature from and saves as a keepsake. Brush strokes and room
 * changes go to the worker as a list of ops, applied before its next steps.
 * A brush held still is one held op, dabbed once for every frame's worth of
 * steps the worker takes, so it pours at the same rate per step however far
 * behind the worker runs.
 * Steps asked for while the worker is still busy are owed, not dropped (up to
 * two frames' worth), and go out the moment it answers, so a run that spills
 * past a frame costs no pace; only a world too big for the worker plays slower.
 * Arrays travel as transfers and come back for reuse, so a steady run makes
 * no garbage. Without a worker, the same calls step the world in place.
 */

import * as S from "./sim.js";

/** The arrays a picture, a hover readout and a keepsake need. */
const FIELDS = ["mat", "temp", "life", "shade", "flash"];

/**
 * Take n steps, dabbing the held op (if any) before the first step and then
 * before every `every` steps after it: one dab per frame's worth of steps.
 */
export function stepHeld(s, n, hold, every) {
  const per = Math.max(1, every | 0);
  for (let k = 0; k < n; k++) {
    if (hold && k % per === 0) applyOps(s, [hold]);
    S.step(s);
  }
}

/** Apply brush and room ops ([kind, ...args]) to a world, in order. */
export function applyOps(s, ops) {
  for (const op of ops) {
    if (op[0] === "paint") S.paint(s, op[1], op[2], op[3], op[4]);
    else if (op[0] === "stroke") S.stroke(s, op[1], op[2], op[3], op[4], op[5], op[6]);
    else if (op[0] === "ambient") s.ambient = op[1];
  }
}

/**
 * A world as a message. Its arrays are copied into `spare` arrays of the
 * right length when there are any (handed back by the other side), else into
 * new ones; the copies' buffers are listed for transfer.
 */
export function pack(s, spare = null) {
  const msg = {
    w: s.w,
    h: s.h,
    seed: s.seed,
    tick: s.tick,
    ambient: s.ambient,
    detail: s.detail,
    events: { ...s.events },
  };
  const transfer = [];
  for (const f of FIELDS) {
    const src = s[f];
    const reuse = spare && spare[f] && spare[f].length === src.length ? spare[f] : null;
    const a = reuse ? (reuse.set(src), reuse) : src.slice();
    msg[f] = a;
    transfer.push(a.buffer);
  }
  return { msg, transfer };
}

/** A full world from a packed message (its arrays are taken over, not copied). */
export function unpack(msg) {
  const s = S.createWorld(msg.seed, msg.w, msg.h, msg.ambient, msg.detail);
  adopt(s, msg);
  S.reseed(s);
  return s;
}

/** Point a world's arrays and counters at a packed message's; returns the arrays it let go. */
function adopt(s, msg) {
  const old = {};
  for (const f of FIELDS) {
    old[f] = s[f];
    s[f] = msg[f];
  }
  s.tick = msg.tick;
  s.ambient = msg.ambient;
  s.events = { ...msg.events };
  return old;
}

/**
 * The worker's side, as a plain function so node can test it: takes a
 * message, returns the reply ({msg, transfer}) or null.
 *   {type: "set", gen, world}            the world to step from now on
 *   {type: "run", gen, ops, steps, hold, every, spare}
 *                                        apply ops, take steps (dabbing hold
 *                                        every `every` steps), send a copy back
 */
export function host() {
  let s = null;
  let gen = -1;
  return (m) => {
    if (m.type === "set") {
      s = unpack(m.world);
      gen = m.gen;
      return null;
    }
    if (m.type !== "run" || !s || m.gen !== gen) return null;
    const t0 = performance.now();
    applyOps(s, m.ops);
    stepHeld(s, m.steps, m.hold || null, m.every || m.steps);
    const ms = performance.now() - t0;
    const { msg, transfer } = pack(s, m.spare);
    return { msg: { type: "frame", gen, ms, steps: m.steps, world: msg }, transfer };
  };
}

/**
 * The page's side. `world` is always a full world the page may read and draw;
 * with a worker it is the latest copy, without one it is the real thing.
 *   set(s)      start from world s (a new scene, a keepsake, another detail)
 *   queue(op)   a brush or room op
 *   hold(op)    a brush held still (or null): dabbed once per run(steps)'s worth of steps
 *   run(steps)  take steps now (or send them when the worker is free)
 *   ready       true when a run would go out at once
 *   stepMs      the worker's time per step, smoothed (0 without a worker)
 * opts: {worker: false} steps on the page; {Worker} a stand-in class (tests).
 */
export function stepper(first, opts = {}) {
  let world = first;
  let gen = 0;
  let worker = null;
  let busy = false;
  let ops = [];
  let extra = 0; // single steps asked for while the worker was busy
  let owed = 0; // frame steps asked for while the worker was busy
  let spare = null;
  let held = null; // the brush held still, or null
  let every = 1; // steps in one frame: the held brush dabs once per this many
  const self = {
    get world() {
      return world;
    },
    get ready() {
      return !worker || !busy;
    },
    get threaded() {
      return !!worker;
    },
    stepMs: 0,
    set(s) {
      world = s;
      gen++;
      ops = [];
      extra = 0;
      owed = 0;
      held = null; // its cells were in the old grid; the page holds it again next frame
      if (worker) {
        busy = false;
        const { msg, transfer } = pack(s);
        worker.postMessage({ type: "set", gen, world: msg }, transfer);
      }
    },
    queue(op) {
      if (worker) ops.push(op);
      else applyOps(world, [op]);
    },
    hold(op) {
      held = op || null;
    },
    run(steps) {
      if (steps > 0) every = steps;
      if (!worker) {
        stepHeld(world, steps, held, every);
        return true;
      }
      if (busy) {
        // paused (0 steps) forgives the debt; running owes at most two frames
        owed = Math.min(owed + steps, 2 * steps);
        return false;
      }
      return send(steps);
    },
    /** Steps that must not be dropped (the Step button): sent with the next run. */
    later(steps) {
      if (!worker) stepHeld(world, steps, null, 1);
      else extra += steps;
    },
    stop() {
      if (worker) worker.terminate();
      worker = null;
    },
  };
  function send(steps) {
    const n = steps + extra + owed;
    if (n === 0 && ops.length === 0) return false;
    const transfer = [];
    if (spare) for (const f of FIELDS) transfer.push(spare[f].buffer);
    worker.postMessage({ type: "run", gen, ops, steps: n, hold: held, every, spare }, transfer);
    ops = [];
    extra = 0;
    owed = 0;
    spare = null;
    busy = true;
    return true;
  }
  // the page's own thread steps it when there is no worker, or the worker fails
  const fallBack = () => {
    if (!worker) return;
    worker.terminate();
    worker = null;
    busy = false;
    S.reseed(world);
    applyOps(world, ops);
    ops = [];
    const behind = extra + owed;
    extra = 0;
    owed = 0;
    if (behind) stepHeld(world, behind, held, every);
    if (opts.onfallback) opts.onfallback();
  };
  if (opts.worker !== false && (opts.Worker || typeof Worker !== "undefined")) {
    try {
      worker = new (opts.Worker || Worker)(new URL("./worker.js", import.meta.url), { type: "module" });
      worker.onerror = (e) => {
        e.preventDefault();
        fallBack();
      };
      worker.onmessageerror = fallBack;
      worker.onmessage = (e) => {
        const m = e.data;
        if (m.type !== "frame") return;
        if (m.gen !== gen) {
          spare = null; // a run from before a set(): its arrays may be the wrong size, let them go
          return;
        }
        busy = false;
        if (m.steps > 0) {
          const per = m.ms / m.steps;
          self.stepMs = self.stepMs ? self.stepMs * 0.8 + per * 0.2 : per;
        }
        spare = adopt(world, m.world);
        if (owed > 0) send(0); // catch up now rather than at the next frame
      };
      const { msg, transfer } = pack(world);
      worker.postMessage({ type: "set", gen, world: msg }, transfer);
    } catch {
      worker = null;
    }
  }
  return self;
}
