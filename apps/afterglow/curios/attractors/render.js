/* Density rendering: millions of iterates binned into a histogram, then a
 * log tone map through a palette. No DOM: works on typed arrays so node can
 * test it; curio.js puts the pixels on a canvas.
 *
 * Tone map (server.py does the same):
 *   v = log(1 + count) / log(1 + max)
 *   v = min(1, v * exposure * fade) ** (1 / gamma)
 *   colour = palette ramp at v (256 steps), count 0 is the background.
 */

export const PALETTES = {
  ember: {
    label: "Ember",
    title: "Ember gold on night",
    stops: [[8, 6, 14], [74, 20, 40], [190, 64, 36], [255, 150, 60], [255, 236, 190]],
  },
  dusk: {
    label: "Dusk",
    title: "Violet dusk",
    stops: [[10, 8, 22], [46, 24, 88], [118, 70, 196], [196, 146, 255], [255, 228, 246]],
  },
  ice: {
    label: "Ice",
    title: "Ice blue on deep water",
    stops: [[3, 9, 18], [10, 44, 78], [36, 118, 168], [128, 208, 236], [240, 252, 255]],
  },
  ink: {
    label: "Ink",
    title: "Ink on paper",
    stops: [[240, 232, 216], [200, 184, 160], [124, 106, 98], [52, 42, 54], [14, 12, 22]],
  },
};

export function paletteOf(name) {
  return PALETTES[name] || PALETTES.ember;
}

/** The colour at t (0..1) along evenly spaced stops, as [r, g, b]. */
export function ramp(stops, t) {
  const u = Math.min(1, Math.max(0, t)) * (stops.length - 1);
  const i = Math.min(Math.floor(u), stops.length - 2);
  const f = u - i;
  const a = stops[i];
  const b = stops[i + 1];
  return [0, 1, 2].map((k) => Math.round(a[k] + (b[k] - a[k]) * f));
}

/** 256 colours packed for a little-endian Uint32 view of ImageData. */
export function paletteLut(name) {
  const stops = paletteOf(name).stops;
  const lut = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    const [r, g, b] = ramp(stops, i / 255);
    lut[i] = (255 << 24) | (b << 16) | (g << 8) | r;
  }
  return lut;
}

/** CSS colour of a palette's background (count 0). */
export function background(name) {
  const [r, g, b] = paletteOf(name).stops[0];
  return `rgb(${r}, ${g}, ${b})`;
}

/** Scale and offset putting bounds [xmin, xmax, ymin, ymax] inside the
 *  rectangle {x, y, w, h} (pixels) with a margin, same scale on both axes,
 *  y pointing up. Returns {s, ox, oy}: px = ox + x * s, py = oy - y * s. */
export function fitView(bounds, rect, margin = 0.07) {
  const [x0, x1, y0, y1] = bounds;
  const bw = Math.max(x1 - x0, 1e-3);
  const bh = Math.max(y1 - y0, 1e-3);
  const s = Math.min((rect.w * (1 - 2 * margin)) / bw, (rect.h * (1 - 2 * margin)) / bh);
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  return { s, ox: rect.x + rect.w / 2 - cx * s, oy: rect.y + rect.h / 2 + cy * s };
}

/** A histogram of where the orbit lands. */
export class Density {
  constructor(w, h) {
    this.w = Math.max(1, w | 0);
    this.h = Math.max(1, h | 0);
    this.hist = new Uint32Array(this.w * this.h);
    this.a = new Float64Array(12);
    this.view = { s: 1, ox: 0, oy: 0 };
    this.x = 0.05;
    this.y = 0.05;
    this.max = 0;
    this.total = 0;
    this.lost = false;
  }

  /** New coefficients and a starting point on the attractor. */
  setMap(a, start = [0.05, 0.05]) {
    for (let i = 0; i < 12; i++) this.a[i] = a[i];
    this.x = start[0];
    this.y = start[1];
    this.lost = false;
  }

  setView(view) {
    this.view = { ...view };
  }

  clear() {
    this.hist.fill(0);
    this.max = 0;
    this.total = 0;
  }

  /** Fade what is there: every count loses 1/2^shift of itself. */
  decay(shift = 2) {
    const hist = this.hist;
    let max = 0;
    for (let i = 0; i < hist.length; i++) {
      const c = hist[i];
      if (c) {
        const n = c - (c >>> shift) - (c < 1 << shift ? 1 : 0);
        hist[i] = n;
        if (n > max) max = n;
      }
    }
    this.max = max;
    this.total = Math.floor(this.total / 2);
  }

  /** Iterate n more points. Stops early (lost = true) if the orbit escapes. */
  accumulate(n) {
    const a = this.a;
    const a0 = a[0], a1 = a[1], a2 = a[2], a3 = a[3], a4 = a[4], a5 = a[5];
    const a6 = a[6], a7 = a[7], a8 = a[8], a9 = a[9], a10 = a[10], a11 = a[11];
    const { w, h, hist } = this;
    const { s, ox, oy } = this.view;
    let x = this.x;
    let y = this.y;
    let max = this.max;
    let i = 0;
    for (; i < n; i++) {
      const xn = a0 + a1 * x + a2 * x * x + a3 * x * y + a4 * y + a5 * y * y;
      y = a6 + a7 * x + a8 * x * x + a9 * x * y + a10 * y + a11 * y * y;
      x = xn;
      const fx = ox + x * s;
      const fy = oy - y * s;
      if (fx >= 0 && fx < w && fy >= 0 && fy < h) {
        const k = (fy | 0) * w + (fx | 0);
        const c = hist[k] + 1;
        hist[k] = c;
        if (c > max) max = c;
      } else if (!(Math.abs(x) + Math.abs(y) < 1e6)) {
        this.lost = true;
        x = 0.05;
        y = 0.05;
        break;
      }
    }
    this.x = x;
    this.y = y;
    this.max = max;
    this.total += i;
    return i;
  }
}

/** The palette index (0..255) for a count, given the tone settings. */
export function toneIndex(count, max, { exposure = 1.25, gamma = 1.25, fade = 1 } = {}) {
  if (count <= 0 || max <= 0) return 0;
  const v = Math.min(1, (Math.log1p(count) / Math.log1p(max)) * exposure * fade);
  return Math.round(Math.pow(v, 1 / gamma) * 255);
}

/** Write the tone-mapped density into out (a Uint32Array over ImageData). */
export function toneMap(density, lut, out, opts = {}) {
  const { hist, max } = density;
  const size = Math.min(max, 65535) + 1;
  const table = new Uint32Array(size);
  for (let c = 0; c < size; c++) table[c] = lut[toneIndex(c, max, opts)];
  const bg = lut[0];
  for (let i = 0; i < hist.length; i++) {
    const c = hist[i];
    out[i] = c === 0 ? bg : c < size ? table[c] : lut[toneIndex(c, max, opts)];
  }
}

/** Render a still into a fresh RGBA byte array (w*h*4): used for previews,
 *  the recent-finds strip and thumbnails. Returns the pixels and the count. */
export function still(coeffs, bounds, start, w, h, { points = 300000, palette = "ember", ...tone } = {}) {
  const d = new Density(w, h);
  d.setMap(coeffs, start);
  d.setView(fitView(bounds, { x: 0, y: 0, w: d.w, h: d.h }));
  d.accumulate(points);
  const px = new Uint8ClampedArray(d.w * d.h * 4);
  toneMap(d, paletteLut(palette), new Uint32Array(px.buffer), tone);
  return { pixels: px, w: d.w, h: d.h, density: d };
}
