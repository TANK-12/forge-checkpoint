/* Turns a Crucible world into pixels: one RGBA pixel per cell, plus a small
 * soft glow buffer for the bloom. A finer world (s.detail k > 1) draws the
 * same picture with smaller grains: the glow buffer stays the same size on
 * screen (one texel per 4k by 4k cells), water darkens over the same depth
 * and the sky keeps the same number of stars. Hot cells are tinted along a blackbody
 * ramp (dark red, orange, yellow, white) over their own colour. No DOM: it
 * writes into plain Uint8ClampedArrays, so node can test it and preview()
 * and the live view share it.
 */

import { M, MATERIALS, MAT_COUNT } from "./sim.js";

// Blackbody-ish stops: temperature in C, then the colour of light at it.
const BODY = [
  [480, 70, 0, 0],
  [640, 150, 16, 4],
  [820, 225, 60, 8],
  [1000, 255, 120, 24],
  [1200, 255, 176, 70],
  [1450, 255, 224, 150],
  [1800, 255, 246, 220],
  [2400, 220, 236, 255],
];
export const GLOW_START = BODY[0][0];

/** Light colour and strength (0..1) of something at temperature t. */
export function blackbody(t, out = [0, 0, 0, 0]) {
  if (t <= BODY[0][0]) {
    out[0] = out[1] = out[2] = out[3] = 0;
    return out;
  }
  let k = 1;
  while (k < BODY.length - 1 && t > BODY[k][0]) k++;
  const a = BODY[k - 1];
  const b = BODY[k];
  const f = Math.min(1, (t - a[0]) / (b[0] - a[0]));
  out[0] = a[1] + (b[1] - a[1]) * f;
  out[1] = a[2] + (b[2] - a[2]) * f;
  out[2] = a[3] + (b[3] - a[3]) * f;
  out[3] = Math.min(1, (t - BODY[0][0]) / 560);
  return out;
}

// A heat-map ramp for the overlay: deep blue cold, through teal and green, to red and white.
const MAP = [
  [-60, 40, 40, 160],
  [0, 40, 120, 220],
  [20, 30, 60, 70],
  [100, 40, 170, 120],
  [300, 210, 210, 60],
  [700, 240, 120, 40],
  [1200, 230, 40, 40],
  [2000, 255, 240, 240],
];

export function heatColor(t, out = [0, 0, 0]) {
  if (t <= MAP[0][0]) {
    out[0] = MAP[0][1];
    out[1] = MAP[0][2];
    out[2] = MAP[0][3];
    return out;
  }
  let k = 1;
  while (k < MAP.length - 1 && t > MAP[k][0]) k++;
  const a = MAP[k - 1];
  const b = MAP[k];
  const f = Math.min(1, (t - a[0]) / (b[0] - a[0]));
  out[0] = a[1] + (b[1] - a[1]) * f;
  out[1] = a[2] + (b[2] - a[2]) * f;
  out[2] = a[3] + (b[3] - a[3]) * f;
  return out;
}

const BASE = MATERIALS.map((m) => m.color);
// How much a material's own shade byte varies its colour.
const GRAIN = new Float32Array(MAT_COUNT).fill(0.1);
GRAIN[M.SAND] = 0.16;
GRAIN[M.ORE] = 0.22;
GRAIN[M.COAL] = 0.35;
GRAIN[M.STONE] = 0.12;
GRAIN[M.WOOD] = 0.18;
GRAIN[M.WATER] = 0.05;
GRAIN[M.ICE] = 0.06;
GRAIN[M.SHOT] = 0.25;

/** Bloom buffer size for a world: one texel per 4 base cells in each direction. */
export function bloomSize(w, h, detail = 1) {
  const c = 4 * detail;
  return { bw: Math.ceil(w / c), bh: Math.ceil(h / c) };
}

/**
 * Device pixels for one cell of a grid at `detail`, when there is room for k
 * device pixels per base cell. The base grid gets whole pixels once a cell is
 * 4 or more, as it always has. A finer grid gets whole pixels too when that
 * makes the picture no smaller than the base grid's; otherwise it keeps the
 * base grid's size and its cells differ by a pixel at most (pixelated
 * scaling, so still no blur). So the picture never shrinks for being finer.
 */
export function cellPixels(k, detail = 1) {
  const base = k >= 4 ? Math.floor(k) : k;
  const whole = Math.floor(k / detail);
  return whole >= 2 && whole * detail >= base ? whole : base / detail;
}

// glow texel column of each cell column, per (width, detail)
const COLS = new Map();
function glowColumns(w, detail) {
  const key = w * 8 + detail;
  let cols = COLS.get(key);
  if (!cols) {
    cols = new Int32Array(w);
    for (let x = 0; x < w; x++) cols[x] = Math.floor(x / (4 * detail));
    COLS.set(key, cols);
  }
  return cols;
}

/**
 * Draw world s into rgba (w*h*4). glow (bw*bh*3 floats, optional) collects
 * light for the bloom. opts.heat draws the heat map over everything.
 */
export function render(s, rgba, glow, opts = {}) {
  const { w, h, mat, temp, shade, flash, life } = s;
  const det = s.detail || 1;
  const heat = !!opts.heat;
  const time = opts.time || 0;
  const body = [0, 0, 0, 0];
  const hc = [0, 0, 0];
  const { bw } = bloomSize(w, h, det);
  const cols = glowColumns(w, det);
  const deep = 6 * det; // water darkens over its top 6 base cells
  const fade = 0.06 / det;
  const starOdds = 997 * det * det;
  const wet = new Uint16Array(w); // water cells straight above, per column
  if (glow) glow.fill(0);
  for (let y = 0; y < h; y++) {
    // the night behind everything: violet at the top, warm near the floor
    const fy = y / h;
    const skyR = 10 + 12 * fy;
    const skyG = 9 + 5 * fy;
    const skyB = 22 - 4 * fy;
    const by = Math.floor(y / (4 * det));
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const m = mat[i];
      const t = temp[i];
      let r;
      let g;
      let b;
      let light = 0;
      if (m === M.EMPTY) {
        r = skyR;
        g = skyG;
        b = skyB;
        if (t > 60) {
          // hot air shimmers a little
          const k = Math.min(1, (t - 60) / 900) * (0.7 + 0.3 * (((shade[i] + time * 3) & 255) / 255));
          r += 60 * k;
          g += 16 * k;
          light = 0.06 * k;
        } else if (y < h * 0.55) {
          // a few stars, fixed to the sky, twinkling
          const hsh = (Math.imul(x, 73856093) ^ Math.imul(y, 19349663)) >>> 0;
          if (hsh % starOdds < 2) {
            const tw = 0.55 + 0.45 * Math.sin(time * 0.05 + (hsh & 63));
            const v = (60 + (hsh & 63)) * tw * (1 - fy);
            r += v;
            g += v;
            b += v * 1.1;
          }
        }
      } else if (m === M.FIRE) {
        const lf = Math.min(1, life[i] / 40);
        const flick = (shade[i] + time * 0.4) % 256 / 256;
        r = 255;
        g = 90 + 150 * lf * (0.6 + 0.4 * flick);
        b = 20 + 90 * lf * lf;
        light = 0.75 + 0.25 * lf;
      } else {
        const c = BASE[m];
        const v = 1 + GRAIN[m] * ((shade[i] - 128) / 128);
        r = c[0] * v;
        g = c[1] * v;
        b = c[2] * v;
        if (m === M.WATER) {
          // deeper water is darker: count the water above, a few cells
          const d = wet[x] < deep ? wet[x] : deep;
          const f = 1.1 - d * fade;
          r *= f;
          g *= f;
          b *= f;
          if (d === 0) {
            r += 30;
            g += 40;
            b += 30;
          }
          if (t > 40) {
            const k = Math.min(1, (t - 40) / 60);
            r += 50 * k;
            g += 30 * k;
          }
        } else if (m === M.STEAM) {
          const a = 0.5 + 0.35 * (shade[i] / 255);
          r = skyR + (r - skyR) * a;
          g = skyG + (g - skyG) * a;
          b = skyB + (b - skyB) * a;
          light = 0.12;
        } else if (m === M.GLASS) {
          const glint = shade[i] > 236 ? 60 : 0;
          r += glint;
          g += glint;
          b += glint;
        } else if ((m === M.IRON || m === M.SHOT) && shade[i] > 228) {
          r += 45;
          g += 48;
          b += 52;
        } else if (m === M.ICE && shade[i] > 240) {
          r += 40;
          g += 30;
          b += 15;
        }
        if (t > GLOW_START || m === M.MOLTEN) {
          // live coal and stone stay a warm orange; only metal and glass go white
          const shown = m === M.MOLTEN ? Math.max(t, 700) : m === M.EMBER || m === M.STONE ? Math.min(t, 1080) : t;
          blackbody(shown, body);
          const a = m === M.MOLTEN ? Math.max(0.85, body[3]) : body[3];
          r = r * (1 - a) + body[0] * a;
          g = g * (1 - a) + body[1] * a;
          b = b * (1 - a) + body[2] * a;
          light = a;
          if (m === M.EMBER) {
            // a bed of live coal breathes: each lump brightens and dims on its own
            const k = 0.62 + 0.38 * Math.sin(time * 0.06 + shade[i] * 0.4);
            r *= k;
            g *= k * k;
            b *= k * k;
            light *= k;
          }
        }
      }
      const fl = flash[i];
      if (fl > 0) {
        r += (255 - r) * fl;
        g += (250 - g) * fl;
        b += (240 - b) * fl;
        light = Math.max(light, fl);
      }
      if (heat) {
        heatColor(t, hc);
        r = r * 0.25 + hc[0] * 0.75;
        g = g * 0.25 + hc[1] * 0.75;
        b = b * 0.25 + hc[2] * 0.75;
      }
      wet[x] = m === M.WATER ? wet[x] + 1 : 0;
      const o = i * 4;
      rgba[o] = r;
      rgba[o + 1] = g;
      rgba[o + 2] = b;
      rgba[o + 3] = 255;
      if (glow && light > 0.02 && !heat) {
        const gi = (by * bw + cols[x]) * 3;
        glow[gi] += r * light;
        glow[gi + 1] += g * light;
        glow[gi + 2] += b * light;
      }
    }
  }
}

/** Blur the glow buffer and write it to rgba (bw*bh*4); strength scales it.
 *  detail is the world's: each texel gathers 16 * detail^2 cells. */
export function bloom(glow, bw, bh, rgba, strength = 1, detail = 1) {
  const tmp = new Float32Array(glow.length);
  // two passes of a 3-tap box blur in each direction
  for (let pass = 0; pass < 2; pass++) {
    for (let y = 0; y < bh; y++) {
      for (let x = 0; x < bw; x++) {
        for (let c = 0; c < 3; c++) {
          const l = glow[(y * bw + Math.max(0, x - 1)) * 3 + c];
          const m = glow[(y * bw + x) * 3 + c];
          const r = glow[(y * bw + Math.min(bw - 1, x + 1)) * 3 + c];
          tmp[(y * bw + x) * 3 + c] = (l + m * 2 + r) / 4;
        }
      }
    }
    for (let y = 0; y < bh; y++) {
      for (let x = 0; x < bw; x++) {
        for (let c = 0; c < 3; c++) {
          const u = tmp[(Math.max(0, y - 1) * bw + x) * 3 + c];
          const m = tmp[(y * bw + x) * 3 + c];
          const d = tmp[(Math.min(bh - 1, y + 1) * bw + x) * 3 + c];
          glow[(y * bw + x) * 3 + c] = (u + m * 2 + d) / 4;
        }
      }
    }
  }
  const k = strength / (16 * detail * detail); // the cells that feed each glow texel
  for (let i = 0, o = 0; i < glow.length; i += 3, o += 4) {
    rgba[o] = glow[i] * k;
    rgba[o + 1] = glow[i + 1] * k;
    rgba[o + 2] = glow[i + 2] * k;
    rgba[o + 3] = 255;
  }
}
