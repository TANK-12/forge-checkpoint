/* The gravity engine for the Cosmos game modes (2D).
 *
 * Two kinds of thing move here:
 *
 *   bodies     stars, planets, moons and black holes. Every body pulls on
 *              every other body. There are rarely more than a few dozen.
 *   particles  massless test particles -- asteroid belts, galaxy discs,
 *              debris. They feel the bodies but pull on nothing, which is
 *              what lets a galaxy collision have thousands of stars at the
 *              cost of a handful of bodies.
 *
 * Integration is kick-drift-kick leapfrog. It is second order and
 * symplectic: energy wobbles but does not creep, so an orbit left running for
 * an hour is still the same orbit. Gravity is softened by `softening` (a
 * length) so a close pass cannot produce an infinite kick; the energy the
 * integrator conserves is the softened one, and `energy()` reports that.
 *
 * Bodies that touch merge, conserving mass and momentum. The survivor keeps
 * the name of the heavier one and the "strongest" kind (a black hole that eats
 * a star is still a black hole). Particles that fall into a body are removed.
 *
 * A scenario is plain JSON (see ~/ForgeGameData/cosmos/scenarios/): world
 * settings, a list of bodies, and generators that scatter particles. Adding a
 * scenario never touches this file.
 *
 * The 3D flight sim planned for later needs orbital mechanics of a different
 * kind (patched conics, spheres of influence) and gets its own engine rather
 * than stretching this one.
 */

const KIND_RANK = { moon: 1, planet: 2, star: 3, blackhole: 4 };

/* Small, seedable random numbers, so a generator gives the same disc every
 * time a scenario is loaded. */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

class ParticleSet {
  constructor(capacity = 256) {
    this.count = 0;
    this.palette = [];
    this._alloc(capacity);
  }

  _alloc(capacity) {
    const grow = (Old, old) => {
      const next = new Old(capacity);
      if (old) next.set(old.subarray(0, this.count));
      return next;
    };
    this.x = grow(Float64Array, this.x);
    this.y = grow(Float64Array, this.y);
    this.vx = grow(Float64Array, this.vx);
    this.vy = grow(Float64Array, this.vy);
    this.color = grow(Uint16Array, this.color);
    this.capacity = capacity;
  }

  colorIndex(color) {
    let i = this.palette.indexOf(color);
    if (i < 0) {
      this.palette.push(color);
      i = this.palette.length - 1;
    }
    return i;
  }

  add(x, y, vx, vy, color = "#cfd8ff") {
    if (this.count === this.capacity) this._alloc(this.capacity * 2);
    const i = this.count++;
    this.x[i] = x;
    this.y[i] = y;
    this.vx[i] = vx;
    this.vy[i] = vy;
    this.color[i] = this.colorIndex(color);
    return i;
  }

  remove(i) {
    const last = --this.count;
    this.x[i] = this.x[last];
    this.y[i] = this.y[last];
    this.vx[i] = this.vx[last];
    this.vy[i] = this.vy[last];
    this.color[i] = this.color[last];
  }

  clear() {
    this.count = 0;
    this.palette = [];
  }
}

let nextId = 1;

export class World {
  constructor({ G = 1, softening = 0.01, merge = true } = {}) {
    this.G = G;
    this.softening = softening;
    this.merge = merge;
    this.time = 0;
    this.bodies = [];
    this.particles = new ParticleSet();
    this.events = [];
    this._accValid = false;
  }

  addBody(spec = {}) {
    const b = {
      id: spec.id ?? `body-${nextId++}`,
      name: spec.name ?? "",
      kind: spec.kind ?? "planet",
      m: spec.m ?? 1,
      r: spec.r ?? 1,
      color: spec.color ?? "#ffffff",
      x: spec.x ?? 0,
      y: spec.y ?? 0,
      vx: spec.vx ?? 0,
      vy: spec.vy ?? 0,
      fixed: !!spec.fixed,
      ax: 0,
      ay: 0,
    };
    this.bodies.push(b);
    this._accValid = false;
    return b;
  }

  bodyById(id) {
    return this.bodies.find((b) => b.id === id) || null;
  }

  removeBody(id) {
    this.bodies = this.bodies.filter((b) => b.id !== id);
    this._accValid = false;
  }

  addParticle(x, y, vx, vy, color) {
    return this.particles.add(x, y, vx, vy, color);
  }

  /* Call after moving or changing bodies by hand. */
  touch() {
    this._accValid = false;
  }

  _computeBodyAcc() {
    const B = this.bodies;
    const eps2 = this.softening * this.softening;
    for (const b of B) {
      b.ax = 0;
      b.ay = 0;
    }
    for (let i = 0; i < B.length; i++) {
      const a = B[i];
      for (let j = i + 1; j < B.length; j++) {
        const b = B[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const r2 = dx * dx + dy * dy + eps2;
        const inv = this.G / (r2 * Math.sqrt(r2));
        a.ax += inv * b.m * dx;
        a.ay += inv * b.m * dy;
        b.ax -= inv * a.m * dx;
        b.ay -= inv * a.m * dy;
      }
    }
    this._accValid = true;
  }

  _kickParticles(h) {
    const P = this.particles;
    const B = this.bodies;
    const eps2 = this.softening * this.softening;
    for (let i = 0; i < P.count; i++) {
      let ax = 0;
      let ay = 0;
      const px = P.x[i];
      const py = P.y[i];
      for (let k = 0; k < B.length; k++) {
        const b = B[k];
        const dx = b.x - px;
        const dy = b.y - py;
        const r2 = dx * dx + dy * dy + eps2;
        const inv = (this.G * b.m) / (r2 * Math.sqrt(r2));
        ax += inv * dx;
        ay += inv * dy;
      }
      P.vx[i] += h * ax;
      P.vy[i] += h * ay;
    }
  }

  step(dt) {
    const B = this.bodies;
    const P = this.particles;
    const h = 0.5 * dt;
    if (!this._accValid) this._computeBodyAcc();

    // Particles are kicked against the bodies' positions at the start of the
    // step, so everything shares one kick-drift-kick sequence.
    this._kickParticles(h);
    for (let i = 0; i < P.count; i++) {
      P.x[i] += dt * P.vx[i];
      P.y[i] += dt * P.vy[i];
    }
    for (const b of B) {
      if (b.fixed) continue;
      b.vx += h * b.ax;
      b.vy += h * b.ay;
      b.x += dt * b.vx;
      b.y += dt * b.vy;
    }

    if (this.merge) this._collide();
    this._computeBodyAcc();

    for (const b of this.bodies) {
      if (b.fixed) continue;
      b.vx += h * b.ax;
      b.vy += h * b.ay;
    }
    this._kickParticles(h);
    this._absorbParticles();
    this.time += dt;
  }

  _collide() {
    const B = this.bodies;
    let merged = false;
    for (let i = 0; i < B.length; i++) {
      for (let j = i + 1; j < B.length; j++) {
        const a = B[i];
        const b = B[j];
        if (a.dead) break;
        if (b.dead) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const reach = a.r + b.r;
        if (dx * dx + dy * dy >= reach * reach) continue;
        const [big, small] = a.m >= b.m ? [a, b] : [b, a];
        const m = a.m + b.m;
        if (big.fixed || small.fixed) {
          // An anchored body stays where it was put and soaks up the impact.
          if (small.fixed) {
            big.x = small.x;
            big.y = small.y;
          }
          big.fixed = true;
          big.vx = 0;
          big.vy = 0;
        } else {
          big.x = (a.m * a.x + b.m * b.x) / m;
          big.y = (a.m * a.y + b.m * b.y) / m;
          big.vx = (a.m * a.vx + b.m * b.vx) / m;
          big.vy = (a.m * a.vy + b.m * b.vy) / m;
        }
        // A black hole's size follows its mass (the heavier hole, scaled up);
        // anything else keeps its combined volume.
        const holes = [a, b].filter((x) => x.kind === "blackhole");
        if (holes.length) {
          const hole = holes.reduce((p, q) => (q.m > p.m ? q : p));
          big.r = hole.r * (m / hole.m);
        } else {
          big.r = Math.cbrt(big.r ** 3 + small.r ** 3);
        }
        if ((KIND_RANK[small.kind] || 0) > (KIND_RANK[big.kind] || 0)) {
          big.kind = small.kind;
          big.color = small.color;
        }
        big.m = m;
        small.dead = true;
        merged = true;
        this.events.push({ type: "merge", x: big.x, y: big.y, m, kind: big.kind, into: big.id });
      }
    }
    if (merged) this.bodies = B.filter((b) => !b.dead);
  }

  _absorbParticles() {
    const P = this.particles;
    const B = this.bodies;
    for (let i = P.count - 1; i >= 0; i--) {
      for (let k = 0; k < B.length; k++) {
        const b = B[k];
        const dx = b.x - P.x[i];
        const dy = b.y - P.y[i];
        if (dx * dx + dy * dy < b.r * b.r) {
          P.remove(i);
          break;
        }
      }
    }
  }

  /* Total kinetic + softened potential energy of the bodies. Particles are
   * massless and carry none. */
  energy() {
    const B = this.bodies;
    const eps2 = this.softening * this.softening;
    let ke = 0;
    let pe = 0;
    for (let i = 0; i < B.length; i++) {
      const a = B[i];
      ke += 0.5 * a.m * (a.vx * a.vx + a.vy * a.vy);
      for (let j = i + 1; j < B.length; j++) {
        const b = B[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        pe -= (this.G * a.m * b.m) / Math.sqrt(dx * dx + dy * dy + eps2);
      }
    }
    return ke + pe;
  }

  momentum() {
    let px = 0;
    let py = 0;
    for (const b of this.bodies) {
      px += b.m * b.vx;
      py += b.m * b.vy;
    }
    return [px, py];
  }

  /* The body whose pull is strongest at (x, y), or null in empty space. */
  dominantAttractor(x, y, exclude = null) {
    let best = null;
    let bestPull = 0;
    for (const b of this.bodies) {
      if (b === exclude) continue;
      const d2 = (b.x - x) ** 2 + (b.y - y) ** 2;
      const pull = b.m / Math.max(d2, 1e-12);
      if (pull > bestPull) {
        bestPull = pull;
        best = b;
      }
    }
    return best;
  }

  /* Speed for a circular orbit at radius r around mass m, allowing for the
   * softening so the orbit really is circular in this engine. */
  circularSpeed(m, r) {
    const eps2 = this.softening * this.softening;
    return Math.sqrt((this.G * m * r * r) / Math.pow(r * r + eps2, 1.5));
  }

  /* Velocity for a circular orbit at (x, y) around the dominant attractor,
   * counter-clockwise when direction is 1. */
  circularVelocity(x, y, direction = 1, exclude = null) {
    const att = this.dominantAttractor(x, y, exclude);
    if (!att) return { vx: 0, vy: 0, attractor: null };
    const dx = x - att.x;
    const dy = y - att.y;
    const r = Math.hypot(dx, dy);
    if (r === 0) return { vx: att.vx, vy: att.vy, attractor: att };
    const v = this.circularSpeed(att.m, r) * direction;
    return { vx: att.vx - (v * dy) / r, vy: att.vy + (v * dx) / r, attractor: att };
  }

  /* Where a massless probe launched from (x, y) at (vx, vy) would go, with
   * the bodies moving too. Returns the path as a flat Float32Array of xy
   * pairs and the id of the body it would hit, if any. Nothing in the world
   * changes. */
  predict(x, y, vx, vy, { steps = 600, dt = 0.02, every = 2 } = {}) {
    const B = this.bodies.map((b) => ({ ...b }));
    const eps2 = this.softening * this.softening;
    const G = this.G;
    const out = new Float32Array(Math.ceil(steps / every) * 2 + 2);
    let n = 0;
    let hit = null;
    const accOn = (px, py, skip) => {
      let ax = 0;
      let ay = 0;
      for (const b of B) {
        if (b === skip) continue;
        const dx = b.x - px;
        const dy = b.y - py;
        const r2 = dx * dx + dy * dy + eps2;
        const inv = (G * b.m) / (r2 * Math.sqrt(r2));
        ax += inv * dx;
        ay += inv * dy;
      }
      return [ax, ay];
    };
    const h = 0.5 * dt;
    out[n++] = x;
    out[n++] = y;
    for (let s = 0; s < steps; s++) {
      let [ax, ay] = accOn(x, y, null);
      vx += h * ax;
      vy += h * ay;
      x += dt * vx;
      y += dt * vy;
      for (const b of B) {
        if (b.fixed) continue;
        const [bx, by] = accOn(b.x, b.y, b);
        b.vx += h * bx;
        b.vy += h * by;
      }
      for (const b of B) {
        if (b.fixed) continue;
        b.x += dt * b.vx;
        b.y += dt * b.vy;
      }
      for (const b of B) {
        if (b.fixed) continue;
        const [bx, by] = accOn(b.x, b.y, b);
        b.vx += h * bx;
        b.vy += h * by;
      }
      [ax, ay] = accOn(x, y, null);
      vx += h * ax;
      vy += h * ay;
      if ((s + 1) % every === 0 && n < out.length - 1) {
        out[n++] = x;
        out[n++] = y;
      }
      const struck = B.find((b) => (b.x - x) ** 2 + (b.y - y) ** 2 < b.r * b.r);
      if (struck) {
        hit = struck.id;
        break;
      }
    }
    return { points: out.subarray(0, n), hit };
  }

  /* --- scenarios ----------------------------------------------------- */

  static fromScenario(s) {
    const w = new World({ G: s.G ?? 1, softening: s.softening ?? 0.01, merge: s.merge ?? true });
    for (const spec of s.bodies || []) w.addBody(spec);
    for (const gen of s.generators || []) applyGenerator(w, gen);
    const colors = s.particle_colors || [];
    for (const p of s.particles || []) w.addParticle(p[0], p[1], p[2], p[3], colors[p[4]] ?? "#cfd8ff");
    return w;
  }

  /* The current state as a scenario, so a running world can be saved. */
  toScenario(meta = {}) {
    const r4 = (v) => Math.round(v * 1e4) / 1e4;
    const P = this.particles;
    const particles = [];
    for (let i = 0; i < P.count; i++) {
      particles.push([r4(P.x[i]), r4(P.y[i]), r4(P.vx[i]), r4(P.vy[i]), P.color[i]]);
    }
    return {
      version: 1,
      ...meta,
      G: this.G,
      softening: this.softening,
      merge: this.merge,
      bodies: this.bodies.map((b) => ({
        id: b.id,
        name: b.name,
        kind: b.kind,
        m: b.m,
        r: b.r,
        color: b.color,
        x: r4(b.x),
        y: r4(b.y),
        vx: r4(b.vx),
        vy: r4(b.vy),
        ...(b.fixed ? { fixed: true } : {}),
      })),
      particle_colors: [...P.palette],
      particles,
    };
  }
}

/* Scatter particles on circular orbits.
 *
 *   { "type": "disc", "around": "<body id>", "count": 800,
 *     "r_min": 30, "r_max": 160, "seed": 1, "direction": 1,
 *     "jitter": 0.02, "colors": ["#9cc3ff", "#ffe2b0"] }
 *
 * Without "around", give "x", "y", "vx", "vy" and "mass" for an invisible
 * centre. Particles are spread evenly by area. */
export function applyGenerator(world, gen) {
  if (gen.type !== "disc") throw new Error(`Unknown generator "${gen.type}"`);
  const rng = mulberry32(gen.seed ?? 1);
  const c = gen.around ? world.bodyById(gen.around) : null;
  if (gen.around && !c) throw new Error(`Generator refers to missing body "${gen.around}"`);
  const cx = c ? c.x : gen.x ?? 0;
  const cy = c ? c.y : gen.y ?? 0;
  const cvx = c ? c.vx : gen.vx ?? 0;
  const cvy = c ? c.vy : gen.vy ?? 0;
  const M = c ? c.m : gen.mass ?? 0;
  const dir = gen.direction ?? 1;
  const colors = gen.colors?.length ? gen.colors : ["#cfd8ff"];
  const rMin = gen.r_min ?? 10;
  const rMax = gen.r_max ?? 100;
  for (let k = 0; k < (gen.count ?? 100); k++) {
    const r = Math.sqrt(rMin * rMin + (rMax * rMax - rMin * rMin) * rng());
    const t = rng() * 2 * Math.PI;
    const v = world.circularSpeed(M, r) * (1 + (rng() - 0.5) * 2 * (gen.jitter ?? 0)) * dir;
    world.addParticle(
      cx + r * Math.cos(t),
      cy + r * Math.sin(t),
      cvx - v * Math.sin(t),
      cvy + v * Math.cos(t),
      colors[Math.floor(rng() * colors.length)],
    );
  }
}
