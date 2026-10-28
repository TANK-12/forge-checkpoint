/* The mountain: the slope the rider is on, and everything on it.

   The ground is a list of heights every DX pixels, grown ahead of the rider
   and trimmed behind it. It is built from FEATURES, a registry of stretches
   of mountain (a plain run, a kicker, a chasm, a rope line, a village...):
   each is picked by weight, and the weights shift with distance so the
   mountain gets harder the further you go. Adding a new kind of stretch is
   one entry in FEATURES.

   Props come from the shape files. A shape's `place.kind` says what it is to
   the world: decor is scattered, obstacle is a rock, pole holds up a rope,
   chase is an animal, coin is a coin. Which decor appears, and how often, is
   the shape files' `place.weight`, so new decor is a new shape file only.

   Canvas y grows downward, so going downhill is y increasing. */

export const DX = 16;
export const PX_PER_M = 20;

export function rng(seed) {
  let a = seed >>> 0 || 1;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// A repeatable value in [0, 1) for an integer lattice point: the far
// mountains and the facet shading use it so they never shimmer.
export function hash(i, salt = 0) {
  let h = Math.imul((i | 0) ^ Math.imul(salt | 0, 0x9e3779b1), 0x85ebca6b);
  h ^= h >>> 13;
  h = Math.imul(h, 0xc2b2ae35);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
}

function pickWeighted(r, list, weightOf) {
  const total = list.reduce((s, e) => s + Math.max(0, weightOf(e)), 0);
  let x = r() * total;
  for (const e of list) {
    x -= Math.max(0, weightOf(e));
    if (x <= 0) return e;
  }
  return list[list.length - 1];
}

/* Stretches of mountain. build(g) appends ground through the builder's
   helpers and places things; weight(m) is how likely it is at m metres. */
export const FEATURES = [
  {
    id: "run",
    weight: () => 5,
    build(g) {
      const n = g.int(30, 60);
      const start = g.x;
      g.run(n, g.range(0.22, 0.42));
      g.scatter(start, g.x);
      if (g.r() < 0.5) g.coinLine(start + 120, g.int(5, 9), 28);
    },
  },
  {
    id: "kicker",
    weight: (m) => (m < 80 ? 1 : 4),
    build(g) {
      g.run(8, 0.3);
      const start = g.x;
      const n = g.int(26, 40);
      g.bump(n, g.range(40, 95));
      g.run(10, 0.36);
      g.scatter(start - 80, start);
      if (g.r() < 0.7) g.coinArc(start + n * DX * 0.7, g.int(6, 10), 180, 110);
    },
  },
  {
    id: "chasm",
    weight: (m) => (m < 400 ? 0 : 2 + Math.min(3, m / 1500)),
    build(g) {
      g.run(12, 0.32);
      const ropeFrom = g.x - 6 * DX;
      g.run(5, -0.22); // the lip that throws you across
      const width = g.int(9, 16 + Math.min(8, Math.floor(g.metres / 800)));
      const from = g.x;
      g.gap(width, g.range(30, 120));
      g.run(3, 0.1);
      g.chasms.push({ x1: from, x2: g.x - 3 * DX });
      g.run(18, 0.34);
      if (g.r() < 0.4) g.rope(ropeFrom, g.x - 4 * DX);
      else g.coinArc(from + (width * DX) / 2, g.int(5, 8), width * DX * 0.8, 90);
    },
  },
  {
    id: "rocks",
    weight: (m) => (m < 150 ? 0 : 2.5 + Math.min(2, m / 2000)),
    build(g) {
      const start = g.x;
      g.run(g.int(34, 50), g.range(0.25, 0.38));
      g.obstacle(start + g.range(0.35, 0.5) * (g.x - start));
      if (g.metres > 1200 && g.r() < 0.4) g.obstacle(start + 0.85 * (g.x - start));
      g.scatter(start, start + 200);
    },
  },
  {
    id: "ropes",
    weight: (m) => (m < 60 ? 0 : 2.5),
    build(g) {
      const start = g.x;
      g.run(g.int(40, 60), g.range(0.25, 0.36));
      g.rope(start + 4 * DX, g.x - 6 * DX);
      g.scatter(start, g.x, 0.5);
    },
  },
  {
    id: "goat",
    weight: (m) => (m < 200 ? 0 : 1.2),
    build(g) {
      const start = g.x;
      g.run(g.int(50, 70), g.range(0.26, 0.36));
      g.animal(start + 60);
      g.scatter(start, g.x, 0.6);
    },
  },
  {
    id: "village",
    weight: (m) => (m < 300 ? 0 : 0.8),
    build(g) {
      const start = g.x;
      g.run(g.int(55, 70), g.range(0.18, 0.26));
      g.decor("hut", start + 120, "back");
      g.decor("lantern", start + 60, "back");
      g.decor("lantern", start + 260, "back");
      g.rope(start + 330, g.x - 5 * DX);
      g.coinLine(start + 40, 6, 30);
    },
  },
];

export class World {
  constructor(seed, shapes) {
    this.seed = seed;
    this.r = rng(seed);
    this.shapes = shapes || {};
    this.x0 = -2400; // world x of ys[0]: the mountain starts well off screen
    this.ys = [];
    this.gaps = [];
    this.items = []; // decor, obstacles, coins, poles
    this.ropes = [];
    this.animals = [];
    this.chasms = [];
    this.grade = 0.3;
    this.decorKinds = Object.values(this.shapes).filter((s) => s.place && s.place.kind === "decor");
    // a gentle start: a long even run so the first seconds are just riding
    this.ys.push(0);
    this.gaps.push(false);
    this.run(220, 0.3);
    this.scatter(this.x0 + 200, this.x);
  }

  get x() { return this.x0 + (this.ys.length - 1) * DX; }
  get y() { return this.ys[this.ys.length - 1]; }
  get metres() { return this.x / PX_PER_M; }
  int(a, b) { return a + Math.floor(this.r() * (b - a + 1)); }
  range(a, b) { return a + this.r() * (b - a); }

  // --- ground builders -----------------------------------------------------
  run(n, grade) {
    for (let i = 0; i < n; i++) {
      this.grade += (grade - this.grade) * 0.12;
      const wobble = (this.r() - 0.5) * 1.2;
      this.push(this.y + this.grade * DX + wobble, false);
    }
  }
  bump(n, height) {
    const base = this.y;
    for (let i = 1; i <= n; i++) {
      const k = i / n;
      // rises to a crest two thirds of the way, then drops away steeply
      const up = k < 0.66 ? Math.sin((k / 0.66) * Math.PI / 2) : Math.cos(((k - 0.66) / 0.34) * Math.PI / 2);
      this.push(base + this.grade * DX * i - up * height, false);
    }
  }
  gap(n, drop) {
    for (let i = 1; i <= n; i++) this.push(this.y + this.grade * DX + drop / n, true);
  }
  push(y, isGap) {
    this.ys.push(y);
    this.gaps.push(isGap);
  }

  // --- placing things ------------------------------------------------------
  scatter(from, to, density = 1) {
    if (!this.decorKinds.length) return;
    let x = from + this.range(40, 160);
    while (x < to) {
      const s = pickWeighted(this.r, this.decorKinds, (e) => e.place.weight || 1);
      this.decor(s.id, x, this.r() < 0.8 ? "back" : "front");
      x += this.range(90, 260) / density;
    }
  }
  decor(id, x, layer) {
    const s = this.shapes[id];
    const g = this.groundAt(x);
    if (!s || g === null) return;
    const [lo, hi] = (s.place && s.place.scale) || [1, 1];
    this.items.push({ type: "decor", id, x, y: g + 3, scale: this.range(lo, hi), flip: this.r() < 0.5, layer });
  }
  obstacle(x) {
    const g = this.groundAt(x);
    if (g === null) return;
    const s = this.shapes.rock;
    const scale = this.range(...((s && s.place && s.place.scale) || [1, 1]));
    const radius = ((s && s.place && s.place.radius) || 14) * scale;
    this.items.push({ type: "rock", id: "rock", x, y: g + 2, scale, radius, flip: this.r() < 0.5, layer: "mid" });
  }
  coinLine(x, n, step) {
    for (let i = 0; i < n; i++) {
      const cx = x + i * step, g = this.groundAt(cx);
      if (g !== null) this.items.push({ type: "coin", id: "coin", x: cx, y: g - 26, layer: "mid" });
    }
  }
  coinArc(cx, n, width, height) {
    const g0 = this.groundAt(cx - width / 2) ?? this.y;
    const g1 = this.groundAt(cx + width / 2) ?? this.y;
    for (let i = 0; i < n; i++) {
      const k = n === 1 ? 0.5 : i / (n - 1);
      const x = cx - width / 2 + k * width;
      const base = g0 + (g1 - g0) * k;
      this.items.push({ type: "coin", id: "coin", x, y: base - 40 - Math.sin(k * Math.PI) * height, layer: "mid" });
    }
  }
  rope(x1, x2) {
    const pole = this.shapes.pole;
    const top = (pole && pole.place && pole.place.top) || -63;
    const g1 = this.groundAt(x1), g2 = this.groundAt(x2);
    if (g1 === null || g2 === null || x2 - x1 < 160) return;
    const rope = { x1, y1: g1 + top, x2, y2: g2 + top, sag: Math.min(40, (x2 - x1) * 0.05) };
    this.ropes.push(rope);
    this.items.push({ type: "pole", id: "pole", x: x1, y: g1 + 2, layer: "mid" });
    this.items.push({ type: "pole", id: "pole", x: x2, y: g2 + 2, layer: "mid" });
    const n = Math.floor((x2 - x1) / 70);
    for (let i = 1; i < n; i++) {
      const x = x1 + ((x2 - x1) * i) / n;
      this.items.push({ type: "coin", id: "coin", x, y: ropeY(rope, x) - 24, layer: "mid" });
    }
  }
  animal(x) {
    const g = this.groundAt(x);
    if (g === null || !this.shapes.goat) return;
    this.animals.push({ id: "goat", x, y: g, vy: 0, speed: this.range(300, 380), hop: 0, caught: false, flee: 0 });
  }

  // --- growing and trimming ------------------------------------------------
  ensure(xAhead) {
    while (this.x < xAhead) {
      const m = this.metres;
      const f = pickWeighted(this.r, FEATURES, (e) => e.weight(m));
      f.build(this);
    }
  }
  trim(xBehind) {
    const drop = Math.floor((xBehind - this.x0) / DX) - 2;
    if (drop > 64) {
      this.ys.splice(0, drop);
      this.gaps.splice(0, drop);
      this.x0 += drop * DX;
    }
    const keep = (o) => (o.x2 ?? o.x) > xBehind;
    this.items = this.items.filter(keep);
    this.ropes = this.ropes.filter(keep);
    this.chasms = this.chasms.filter(keep);
    this.animals = this.animals.filter((a) => a.x > xBehind && !a.gone);
  }

  // --- queries -------------------------------------------------------------
  // The ground's y at x, or null over a chasm or off the known mountain.
  groundAt(x) {
    const f = (x - this.x0) / DX;
    const i = Math.floor(f);
    if (i < 0 || i + 1 >= this.ys.length) return null;
    if (this.gaps[i] || this.gaps[i + 1]) return null;
    return this.ys[i] + (this.ys[i + 1] - this.ys[i]) * (f - i);
  }
  // The slope's angle at x (radians; positive is downhill to the right).
  slopeAt(x) {
    const a = this.groundAt(x - DX), b = this.groundAt(x + DX);
    if (a === null || b === null) {
      const c = this.groundAt(x);
      const d = this.groundAt(x + (a === null ? DX : -DX));
      if (c === null || d === null) return Math.atan(this.grade);
      return a === null ? Math.atan2(d - c, DX) : Math.atan2(c - d, DX);
    }
    return Math.atan2(b - a, 2 * DX);
  }
  // The lowest nearby ground, so the rider knows when a fall is a fall.
  floorNear(x) {
    const i = Math.max(0, Math.floor((x - this.x0) / DX));
    let y = -Infinity;
    for (let k = Math.max(0, i - 30); k < Math.min(this.ys.length, i + 30); k++) y = Math.max(y, this.ys[k]);
    return y;
  }
}

export function ropeY(rope, x) {
  const k = (x - rope.x1) / (rope.x2 - rope.x1);
  return rope.y1 + (rope.y2 - rope.y1) * k + Math.sin(k * Math.PI) * rope.sag;
}
