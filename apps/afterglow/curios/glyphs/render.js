/* Glyphs: drawing the dot field, and the small rules around a piece. No DOM:
 * drawField takes any 2D context and a path factory (Path2D in the browser,
 * a recorder in the node tests), so the whole look is testable.
 *
 * A frame is at most 2 + 2 + 8 fills however big the grid: dots are sorted
 * into paths by sign and by one of four brightness steps, so a 64 x 64 field
 * still draws in a couple of milliseconds.
 */

export const GRID_MIN = 4;
export const GRID_MAX = 64;
export const SPEED_MAX = 4;
export const SHAPES = ["circle", "square", "diamond"];

/** pos/neg: four steps from small-and-dim to large-and-bright. */
export const PALETTES = {
  ember: {
    label: "Ember",
    title: "Gold for positive, twilight violet for negative",
    bg: "#0b0911",
    wash: "rgba(255, 130, 60, 0.07)",
    rest: "rgba(255, 236, 210, 0.09)",
    pos: ["#8a4220", "#cf6a2c", "#ffa046", "#ffd894"],
    neg: ["#3e3170", "#6650bd", "#a58bff", "#d8ccff"],
    halo: ["rgba(255, 150, 70, 0.16)", "rgba(165, 139, 255, 0.16)"],
  },
  tixy: {
    label: "Tixy",
    title: "White and red on black, after tixy.land",
    bg: "#000000",
    wash: "rgba(255, 255, 255, 0.025)",
    rest: "rgba(255, 255, 255, 0.07)",
    pos: ["#6a6a6a", "#a8a8a8", "#e2e2e2", "#ffffff"],
    neg: ["#6e1420", "#a81f30", "#e2303f", "#ff4b55"],
    halo: null,
  },
  sea: {
    label: "Sea",
    title: "Aqua for positive, coral for negative",
    bg: "#05121a",
    wash: "rgba(80, 210, 220, 0.07)",
    rest: "rgba(200, 255, 250, 0.08)",
    pos: ["#1c5a66", "#2c95a0", "#5cd6cf", "#c6fff6"],
    neg: ["#5a2633", "#a8445a", "#ff7a8a", "#ffc4ca"],
    halo: ["rgba(92, 214, 207, 0.15)", "rgba(255, 122, 138, 0.14)"],
  },
  paper: {
    label: "Paper",
    title: "Ink and vermilion on warm paper",
    bg: "#f0e6d2",
    wash: "rgba(255, 252, 240, 0.55)",
    rest: "rgba(60, 40, 20, 0.12)",
    pos: ["#a49c90", "#6a645e", "#34302f", "#151318"],
    neg: ["#ecb5a0", "#e27c5c", "#d0482a", "#a52a12"],
    halo: null,
  },
};

const TAU = Math.PI * 2;

function addShape(p, shape, cx, cy, rad) {
  if (shape === "square") {
    const s = rad * 0.9;
    p.rect(cx - s, cy - s, 2 * s, 2 * s);
  } else if (shape === "diamond") {
    const d = rad * 1.08;
    p.moveTo(cx, cy - d);
    p.lineTo(cx + d, cy);
    p.lineTo(cx, cy + d);
    p.lineTo(cx - d, cy);
    p.closePath();
  } else {
    p.moveTo(cx + rad, cy);
    p.arc(cx, cy, rad, 0, TAU);
  }
}

const newPath2D = () => new Path2D();

/** Paint the background and the field of dots.
 *  opts: {w, h, box: {x, y, size}, n, values, palette, shape, glow, makePath} */
export function drawField(g, opts) {
  const { w, h, box, n, values } = opts;
  const pal = PALETTES[opts.palette] || PALETTES.ember;
  const shape = opts.shape || "circle";
  const makePath = opts.makePath || newPath2D;
  g.globalCompositeOperation = "source-over";
  g.fillStyle = pal.bg;
  g.fillRect(0, 0, w, h);
  const mx = box.x + box.size / 2;
  const my = box.y + box.size / 2;
  const wash = g.createRadialGradient(mx, my, 0, mx, my, Math.max(w, h) * 0.6);
  wash.addColorStop(0, pal.wash);
  wash.addColorStop(1, "rgba(0, 0, 0, 0)");
  g.fillStyle = wash;
  g.fillRect(0, 0, w, h);

  const cell = box.size / n;
  const maxR = cell * 0.46;
  const restR = Math.max(0.7, cell * 0.055);
  const glow = opts.glow !== false && !!pal.halo;
  const rest = makePath();
  const halos = [makePath(), makePath()];
  const dots = [0, 1].map(() => [makePath(), makePath(), makePath(), makePath()]);
  let k = 0;
  for (let y = 0; y < n; y++) {
    const cy = box.y + (y + 0.5) * cell;
    for (let x = 0; x < n; x++, k++) {
      const v = values[k];
      const m = Math.min(1, Math.abs(v));
      const cx = box.x + (x + 0.5) * cell;
      if (m < 0.12) {
        rest.moveTo(cx + restR, cy);
        rest.arc(cx, cy, restR, 0, TAU);
      }
      if (m < 0.04) continue;
      const side = v > 0 ? 0 : 1;
      addShape(dots[side][Math.min(3, (m * 4) | 0)], shape, cx, cy, maxR * m);
      if (glow && m > 0.55) {
        halos[side].moveTo(cx + maxR * 1.9 * m, cy);
        halos[side].arc(cx, cy, maxR * 1.9 * m, 0, TAU);
      }
    }
  }
  g.fillStyle = pal.rest;
  g.fill(rest);
  if (glow) {
    g.globalCompositeOperation = "lighter";
    g.fillStyle = pal.halo[0];
    g.fill(halos[0]);
    g.fillStyle = pal.halo[1];
    g.fill(halos[1]);
    g.globalCompositeOperation = "source-over";
  }
  for (let side = 0; side < 2; side++) {
    const ramp = side === 0 ? pal.pos : pal.neg;
    for (let level = 0; level < 4; level++) {
      g.fillStyle = ramp[level];
      g.fill(dots[side][level]);
    }
  }
}

/** Move shown values toward target, frame-rate independent. Returns the
 *  biggest change left, so a paused field can stop redrawing once settled. */
export function ease(shown, target, dt, rate = 14) {
  const k = 1 - Math.exp(-Math.max(0, dt) * rate);
  let left = 0;
  for (let i = 0; i < target.length; i++) {
    const d = target[i] - shown[i];
    shown[i] += d * k;
    const rem = Math.abs(d * (1 - k));
    if (rem > left) left = rem;
  }
  return left;
}

/** The biggest square that fits the free area (between floating panels), or
 *  the whole canvas when the free area is too thin to be worth it. */
export function fieldBox(w, h, free = {}) {
  let left = free.left ?? 0;
  let right = free.right ?? w;
  let top = free.top ?? 0;
  let bottom = free.bottom ?? h;
  if (right - left < Math.min(280, w * 0.45)) {
    left = 0;
    right = w;
  }
  if (bottom - top < Math.min(240, h * 0.45)) {
    top = 0;
    bottom = h;
  }
  const size = Math.max(16, Math.floor(Math.min(right - left, bottom - top) * 0.94));
  return { x: Math.round(left + (right - left - size) / 2), y: Math.round(top + (bottom - top - size) / 2), size };
}

/** The dot under a point, or -1. */
export function dotAt(box, n, px, py) {
  const x = Math.floor(((px - box.x) / box.size) * n);
  const y = Math.floor(((py - box.y) / box.size) * n);
  if (!(x >= 0 && x < n && y >= 0 && y < n)) return -1;
  return y * n + x;
}

function clampNum(v, lo, hi, dflt) {
  const k = Number(v);
  return Number.isFinite(k) ? Math.min(hi, Math.max(lo, k)) : dflt;
}

/** Any keepsake's data -> a piece that is safe to play. */
export function cleanPiece(data) {
  const d = data && typeof data === "object" ? data : {};
  return {
    formula: typeof d.formula === "string" ? d.formula.slice(0, 400) : "sin(t - r)",
    grid: Math.round(clampNum(d.grid, GRID_MIN, GRID_MAX, 16)),
    speed: clampNum(d.speed, 0, SPEED_MAX, 1),
    palette: Object.hasOwn(PALETTES, d.palette) ? d.palette : "ember",
    shape: SHAPES.includes(d.shape) ? d.shape : "circle",
  };
}
