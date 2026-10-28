/* Garden drawing: sky, soil, plants with wind, fireflies, and the pressed
 * herbarium sheet. Every function takes a 2D context and plain data; nothing
 * here touches the page at import, and layoutGarden() is pure (node tests it). */

import { rng, hashString } from "../_kit/rng.js";
import { DEPTHS, BUD } from "./lsys.js";
import { rgb } from "./sky.js";

const TAU = Math.PI * 2;
const RAD = Math.PI / 180;

/** Where each plant stands. Slots are at least minSlot wide; when they do not
 *  fit, the row is wider than the view and pans (width is the row width). */
export function layoutGarden(plants, w, h, minSlot = 150) {
  const ground = Math.round(h - Math.max(54, h * 0.13));
  const n = Math.max(1, plants.length);
  const slot = Math.max(minSlot, w / n);
  const rowWidth = slot * plants.length;
  const offset = rowWidth < w ? (w - rowWidth) / 2 : 0;
  const tall = Math.max(60, ground - h * 0.1);
  const spots = plants.map((p, i) => {
    const b = p.bounds;
    const spanX = Math.max(1e-3, b.maxX - b.minX);
    const stature = 0.8 + 0.2 * ((hashString(String(p.genome.seed)) % 1000) / 1000);
    const scale = Math.min((slot * 0.88) / spanX, (tall * stature) / b.maxY);
    return { x0: offset + slot * i, x1: offset + slot * (i + 1), mid: offset + slot * (i + 0.5), scale, stature, height: b.maxY * scale };
  });
  return { ground, slot, tall, rowWidth: Math.max(rowWidth, w), spots };
}

export function hsl(h, s, l, a = 1) {
  const L = Math.max(0, Math.min(100, l));
  return a >= 1 ? `hsl(${h % 360} ${s}% ${L}%)` : `hsl(${h % 360} ${s}% ${L}% / ${a})`;
}

// --- background (cached by the caller) -----------------------------------------

export function drawBackground(g, w, h, sky, ground) {
  const grad = g.createLinearGradient(0, 0, 0, ground);
  grad.addColorStop(0, rgb(sky.top));
  grad.addColorStop(0.55, rgb(sky.mid));
  grad.addColorStop(1, rgb(sky.low));
  g.fillStyle = grad;
  g.fillRect(0, 0, w, ground + 2);
  // sun or moon
  const body = sky.sun.up ? sky.sun : sky.moon.up ? sky.moon : null;
  if (body) {
    const x = body.x * w;
    const y = ground - body.y * (ground * 0.78) - 10;
    const isSun = body === sky.sun;
    const r = Math.max(8, Math.min(w, h) * (isSun ? 0.03 : 0.022));
    const halo = g.createRadialGradient(x, y, r * 0.5, x, y, r * (isSun ? 7 : 4));
    halo.addColorStop(0, isSun ? "rgba(255,226,170,0.55)" : "rgba(220,226,255,0.22)");
    halo.addColorStop(1, "rgba(255,220,170,0)");
    g.fillStyle = halo;
    g.fillRect(x - r * 7, y - r * 7, r * 14, r * 14);
    g.fillStyle = isSun ? "#fff1cf" : "#e8ecff";
    g.beginPath();
    g.arc(x, y, r, 0, TAU);
    g.fill();
    if (!isSun) {
      g.fillStyle = rgb(sky.top, 0.9);
      g.beginPath();
      g.arc(x + r * 0.45, y - r * 0.2, r * 0.85, 0, TAU);
      g.fill();
    }
  }
  // the afterglow: a warm band low on the horizon
  if (sky.glow > 0.01) {
    const band = g.createLinearGradient(0, ground - h * 0.35, 0, ground);
    band.addColorStop(0, "rgba(255,120,60,0)");
    band.addColorStop(1, `rgba(255,128,64,${0.32 * sky.glow})`);
    g.fillStyle = band;
    g.fillRect(0, ground - h * 0.35, w, h * 0.35);
  }
  // two rows of far hills
  const hills = [
    [0.18, 0.55, 3],
    [0.09, 0.3, 11],
  ];
  for (const [rise, dark, seed] of hills) {
    const r = rng(seed);
    const a = [r() * 6, r() * 6, r() * 6];
    const c = sky.low.map((v, i) => Math.round(v * (1 - dark) * 0.55 + sky.top[i] * dark * 0.6));
    g.fillStyle = rgb(c);
    g.beginPath();
    g.moveTo(0, ground + 2);
    for (let x = 0; x <= w + 8; x += 8) {
      const u = x / w;
      const y =
        ground -
        h * rise * (0.55 + 0.25 * Math.sin(u * 5.1 + a[0]) + 0.14 * Math.sin(u * 11.3 + a[1]) + 0.06 * Math.sin(u * 23 + a[2]));
      g.lineTo(x, y);
    }
    g.lineTo(w, ground + 2);
    g.closePath();
    g.fill();
  }
  // soil
  const soil = g.createLinearGradient(0, ground - 6, 0, h);
  const L = sky.light;
  soil.addColorStop(0, `rgb(${Math.round(70 * L)},${Math.round(50 * L)},${Math.round(40 * L)})`);
  soil.addColorStop(0.2, `rgb(${Math.round(44 * L)},${Math.round(30 * L)},${Math.round(26 * L)})`);
  soil.addColorStop(1, "rgb(14,10,12)");
  g.fillStyle = soil;
  g.beginPath();
  g.moveTo(0, h);
  for (let x = 0; x <= w + 6; x += 6) g.lineTo(x, ground + Math.sin(x * 0.013) * 2.2 + Math.sin(x * 0.051) * 1.1);
  g.lineTo(w, h);
  g.closePath();
  g.fill();
  // grass tufts and pebbles
  const r = rng(7);
  g.lineWidth = Math.max(1, h / 700);
  g.strokeStyle = hsl(96, 32, 26 * L + 6);
  g.beginPath();
  const tufts = Math.round(w / 14);
  for (let i = 0; i < tufts; i++) {
    const x = r() * w;
    const y = ground + Math.sin(x * 0.013) * 2.2 + 1;
    const n = 2 + Math.floor(r() * 3);
    for (let k = 0; k < n; k++) {
      const len = 4 + r() * 8;
      const lean = (r() - 0.5) * 6;
      g.moveTo(x + k * 1.6, y);
      g.quadraticCurveTo(x + k * 1.6 + lean * 0.3, y - len * 0.6, x + k * 1.6 + lean, y - len);
    }
  }
  g.stroke();
  g.fillStyle = `rgba(150,130,120,${0.18 * L + 0.05})`;
  for (let i = 0; i < w / 30; i++) {
    g.beginPath();
    g.ellipse(r() * w, ground + 10 + r() * (h - ground - 14), 1.5 + r() * 2.5, 1 + r() * 1.2, 0, 0, TAU);
    g.fill();
  }
}

/** A fixed field of stars, in 0..1 coordinates. */
export function makeStars(count = 140) {
  const r = rng(125);
  return Array.from({ length: count }, () => [r(), Math.pow(r(), 1.6), 0.4 + r() * 0.9, r() * TAU]);
}

export function drawStars(g, w, ground, stars, amount, t) {
  if (amount < 0.02) return;
  for (const [x, y, size, phase] of stars) {
    const twinkle = 0.65 + 0.35 * Math.sin(t * 1.3 + phase * 3);
    g.fillStyle = `rgba(235,238,255,${(amount * twinkle * 0.85).toFixed(3)})`;
    g.fillRect(x * w, y * ground * 0.82, size * 1.4, size * 1.4);
  }
}

// --- plants --------------------------------------------------------------------

/** Colours for a plant under a light level (pressed: the faded herbarium look). */
export function plantColours(genome, light, pressed = false) {
  const { stem, leaf, flower } = genome.hues;
  const L = light;
  if (pressed) {
    return {
      stems: Array.from({ length: DEPTHS }, (_, d) => hsl(stem * 0.6 + 20, 26, 26 + d * 3)),
      leaves: [hsl(leaf * 0.7 + 30, 30, 36), hsl(leaf * 0.7 + 38, 26, 44)],
      flower: hsl(flower, 46, 55),
      heart: hsl(flower + 30, 50, 72),
    };
  }
  return {
    stems: Array.from({ length: DEPTHS }, (_, d) => hsl(stem, 30 + d * 3, (20 + d * 4.5) * L + 4)),
    leaves: [hsl(leaf, 52, 34 * L + 6), hsl(leaf + 14, 58, 44 * L + 6)],
    flower: hsl(flower, 72, 62 * Math.max(L, 0.75)),
    heart: hsl(flower + 35, 95, 82),
  };
}

/** Draw one plant. place: {cx, ground, scale, trunk, leafPx, maxY};
 *  sway: {t, amp, phase} or null for a still. */
export function drawPlant(g, geo, genome, place, colours, sway, glowSprite) {
  const { cx, ground, scale, trunk, leafPx, maxY } = place;
  const amp = sway ? sway.amp : 0;
  const steps = Math.max(1, geo.maxSteps + 1);
  const table = new Float32Array(steps + 1);
  let base = 0;
  if (amp) {
    const t = sway.t;
    const p = sway.phase;
    base = (Math.sin(t * 0.8 + p) + 0.45 * Math.sin(t * 2.07 + p * 1.7)) * amp * 0.05 * maxY * scale;
    for (let s = 0; s <= steps; s++) table[s] = Math.sin(t * 1.9 + p + s * 0.22) * amp * Math.min(s, 60) * 0.018 * scale;
  }
  const H = Math.max(1e-6, maxY);
  const dx = (y, s) => {
    if (!amp) return 0;
    const yn = Math.max(0, y / H);
    return base * Math.pow(yn, 1.6) + table[Math.min(s, steps)] * yn;
  };
  g.lineCap = "round";
  g.lineJoin = "round";
  for (let d = 0; d < DEPTHS; d++) {
    const list = geo.segs[d];
    if (!list.length) continue;
    g.lineWidth = Math.max(0.7, trunk * Math.pow(genome.width_decay, d));
    g.strokeStyle = colours.stems[d];
    g.beginPath();
    for (let i = 0; i < list.length; i += 5) {
      const s = list[i + 4];
      g.moveTo(cx + list[i] * scale + dx(list[i + 1], s), ground - list[i + 1] * scale);
      g.lineTo(cx + list[i + 2] * scale + dx(list[i + 3], s + 1), ground - list[i + 3] * scale);
    }
    g.stroke();
  }
  // leaves in two shades, then flowers
  const b = geo.buds;
  const flowers = [];
  for (let shade = 0; shade < 2; shade++) {
    g.fillStyle = colours.leaves[shade];
    g.beginPath();
    for (let i = 0; i < b.length; i += BUD) {
      if (b[i + 5] === 1) {
        if (shade === 0) flowers.push(i);
        continue;
      }
      const hash = b[i + 6];
      if ((hash * 1000) % 2 >= 1 !== (shade === 1)) continue;
      const size = b[i + 3] * leafPx * (0.75 + hash * 0.5);
      const flutter = sway ? Math.sin(sway.t * 3 + hash * 40) * 0.18 * sway.amp : 0;
      const turn = ((hash * 7919) % 1 > 0.5 ? 1 : -1) * 38;
      const rot = -(b[i + 2] + turn) * RAD + flutter;
      const x = cx + b[i] * scale + dx(b[i + 1], b[i + 7]);
      const y = ground - b[i + 1] * scale;
      const lx = x + Math.cos(rot) * size;
      const ly = y + Math.sin(rot) * size;
      g.moveTo(lx + Math.cos(rot) * size, ly + Math.sin(rot) * size);
      g.ellipse(lx, ly, size, size * 0.42, rot, 0, TAU);
    }
    g.fill();
  }
  if (!flowers.length || geo.bloom <= 0.02) return;
  const open = geo.bloom;
  if (glowSprite) {
    const prev = g.globalCompositeOperation;
    g.globalCompositeOperation = "lighter";
    g.globalAlpha = glowSprite.alpha;
    for (const i of flowers) {
      const s = leafPx * 4 * open * b[i + 3];
      const x = cx + b[i] * scale + dx(b[i + 1], b[i + 7]);
      const y = ground - b[i + 1] * scale;
      g.drawImage(glowSprite.canvas, x - s, y - s, s * 2, s * 2);
    }
    g.globalAlpha = 1;
    g.globalCompositeOperation = prev;
  }
  g.fillStyle = colours.flower;
  g.strokeStyle = colours.flower;
  g.lineWidth = Math.max(1, leafPx * 0.22);
  g.beginPath();
  for (const i of flowers) {
    const r = leafPx * 1.05 * open * b[i + 3];
    const x = cx + b[i] * scale + dx(b[i + 1], b[i + 7]);
    const y = ground - b[i + 1] * scale;
    flowerPath(g, genome.flower, x, y, r, b[i + 6] * TAU);
  }
  if (genome.flower === "spark") g.stroke();
  else g.fill();
  g.fillStyle = colours.heart;
  g.beginPath();
  for (const i of flowers) {
    const r = leafPx * 0.32 * open * b[i + 3];
    const x = cx + b[i] * scale + dx(b[i + 1], b[i + 7]);
    const y = ground - b[i + 1] * scale + (genome.flower === "bell" ? leafPx * 0.9 * open : 0);
    g.moveTo(x + r, y);
    g.arc(x, y, r, 0, TAU);
  }
  g.fill();
}

function flowerPath(g, shape, x, y, r, spin) {
  if (r < 0.3) return;
  if (shape === "round") {
    for (let k = 0; k < 5; k++) {
      const a = spin + (k * TAU) / 5;
      const px = x + Math.cos(a) * r * 0.62;
      const py = y + Math.sin(a) * r * 0.62;
      g.moveTo(px + r * 0.48, py);
      g.arc(px, py, r * 0.48, 0, TAU);
    }
  } else if (shape === "star") {
    for (let k = 0; k <= 10; k++) {
      const a = spin + (k * Math.PI) / 5;
      const rr = k % 2 ? r * 0.42 : r * 1.15;
      if (k === 0) g.moveTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr);
      else g.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr);
    }
    g.closePath();
  } else if (shape === "bell") {
    g.moveTo(x - r * 0.15, y);
    g.quadraticCurveTo(x - r * 0.95, y + r * 0.6, x - r * 0.8, y + r * 1.5);
    g.lineTo(x + r * 0.8, y + r * 1.5);
    g.quadraticCurveTo(x + r * 0.95, y + r * 0.6, x + r * 0.15, y);
    g.closePath();
  } else {
    for (let k = 0; k < 7; k++) {
      const a = spin + (k * TAU) / 7;
      g.moveTo(x + Math.cos(a) * r * 0.3, y + Math.sin(a) * r * 0.3);
      g.lineTo(x + Math.cos(a) * r * 1.25, y + Math.sin(a) * r * 1.25);
    }
  }
}

/** A seed in the soil with a tiny sprout, for plants that have not come up yet. */
export function drawSeedling(g, x, ground, px, light, stage) {
  g.fillStyle = `rgb(${Math.round(92 * light + 20)},${Math.round(66 * light + 14)},${Math.round(46 * light + 10)})`;
  g.beginPath();
  g.ellipse(x, ground + px * 0.4, px * 1.1, px * 0.55, -0.3, 0, TAU);
  g.fill();
  const up = Math.min(1, stage) * px * 2.4;
  if (up > 0.5) {
    g.strokeStyle = hsl(100, 50, 40 * light + 10);
    g.lineWidth = Math.max(1, px * 0.3);
    g.beginPath();
    g.moveTo(x, ground);
    g.quadraticCurveTo(x - px * 0.3, ground - up * 0.6, x + px * 0.2, ground - up);
    g.stroke();
  }
}

/** Little lights drifting over the garden at night. */
export function drawFireflies(g, w, ground, h, amount, t, sprite, count = 26) {
  if (amount < 0.05 || !sprite) return;
  const prev = g.globalCompositeOperation;
  g.globalCompositeOperation = "lighter";
  for (let i = 0; i < count; i++) {
    const a = i * 12.9898;
    const x = (((Math.sin(a) * 0.5 + 0.5) * w + Math.sin(t * 0.21 + a) * w * 0.06 + Math.sin(t * 0.53 + a * 2) * 24) % w + w) % w;
    const y = ground - (0.08 + (Math.cos(a * 1.7) * 0.5 + 0.5) * 0.5) * (ground * 0.8) + Math.sin(t * 0.7 + a * 3) * 18;
    const pulse = Math.max(0, Math.sin(t * (0.9 + (i % 5) * 0.17) + a));
    g.globalAlpha = amount * (0.15 + 0.85 * pulse * pulse);
    const s = 9 + (i % 3) * 3;
    g.drawImage(sprite, x - s, y - s, s * 2, s * 2);
  }
  g.globalAlpha = 1;
  g.globalCompositeOperation = prev;
}

/** A soft round glow on its own small canvas (made once, drawn many times). */
export function makeGlow(canvas, inner, outer) {
  canvas.width = canvas.height = 64;
  const g = canvas.getContext("2d");
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, inner);
  grad.addColorStop(0.25, outer);
  grad.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  return canvas;
}

// --- the pressed sheet ---------------------------------------------------------

/** A herbarium sheet: the plant flat on paper, with its label.
 *  info: {name, by, stage, maxGen, pressed, parents}. Returns the paper rect. */
export function drawPressed(g, w, h, geo, genome, info, bounds) {
  g.fillStyle = "#130f16";
  g.fillRect(0, 0, w, h);
  const pad = Math.min(w, h) * 0.06;
  let ph = h - pad * 2;
  let pw = ph * 0.74;
  if (pw > w - pad * 2) {
    pw = w - pad * 2;
    ph = pw / 0.74;
  }
  const px = (w - pw) / 2;
  const py = (h - ph) / 2;
  g.fillStyle = "rgba(0,0,0,0.45)";
  g.fillRect(px + pw * 0.015, py + pw * 0.02, pw, ph);
  const paper = g.createLinearGradient(px, py, px + pw, py + ph);
  paper.addColorStop(0, "#f2e9d4");
  paper.addColorStop(1, "#e2d4b6");
  g.fillStyle = paper;
  g.fillRect(px, py, pw, ph);
  // fibres
  const r = rng(genome.seed ^ 0x51ed);
  g.strokeStyle = "rgba(120,96,60,0.10)";
  g.lineWidth = 1;
  g.beginPath();
  for (let i = 0; i < 60; i++) {
    const x = px + r() * pw;
    const y = py + r() * ph;
    const a = r() * TAU;
    const l = 3 + r() * pw * 0.03;
    g.moveTo(x, y);
    g.lineTo(x + Math.cos(a) * l, y + Math.sin(a) * l);
  }
  g.stroke();
  // the plant, fitted into the upper part of the sheet
  const showLabel = pw > 150;
  const areaH = ph * (showLabel ? 0.7 : 0.82);
  const spanX = Math.max(1e-3, bounds.maxX - bounds.minX);
  const scale = Math.min((pw * 0.82) / spanX, areaH / bounds.maxY);
  const ground = py + ph * 0.08 + areaH;
  const cx = px + pw / 2 - ((bounds.maxX + bounds.minX) / 2) * scale;
  const height = bounds.maxY * scale;
  const place = {
    cx,
    ground,
    scale,
    trunk: Math.min(6, Math.max(1, height * 0.02)),
    leafPx: Math.min(7, Math.max(1.4, height * 0.014)),
    maxY: bounds.maxY,
  };
  if (geo.segs.some((s) => s.length)) {
    drawPlant(g, geo, genome, place, plantColours(genome, 1, true), null, null);
  } else {
    drawSeedling(g, px + pw / 2, ground, Math.max(3, pw * 0.02), 1, info.stage);
  }
  // two strips of tape over the stem
  g.fillStyle = "rgba(250,244,220,0.6)";
  for (const [ox, rot] of [
    [-0.05, -0.2],
    [0.05, 0.25],
  ]) {
    g.save();
    g.translate(px + pw / 2 + ox * pw, ground - ph * 0.02);
    g.rotate(rot);
    g.fillRect(-pw * 0.07, -pw * 0.018, pw * 0.14, pw * 0.036);
    g.restore();
  }
  if (showLabel) {
    const lw = pw * 0.52;
    const lh = ph * 0.15;
    const lx = px + pw - lw - pw * 0.06;
    const ly = py + ph - lh - ph * 0.04;
    g.fillStyle = "#fbf6e8";
    g.fillRect(lx, ly, lw, lh);
    g.strokeStyle = "rgba(90,70,40,0.45)";
    g.lineWidth = 1;
    g.strokeRect(lx + 0.5, ly + 0.5, lw - 1, lh - 1);
    const big = Math.max(10, Math.min(26, lh * 0.26));
    const small = Math.max(8, big * 0.52);
    g.fillStyle = "#3a2c1c";
    g.textBaseline = "top";
    g.font = `italic ${big}px Georgia, "Noto Serif", serif`;
    g.fillText(fit(g, info.name, lw - big), lx + big * 0.5, ly + lh * 0.12);
    g.font = `${small}px Georgia, "Noto Serif", serif`;
    g.fillStyle = "#5d4a33";
    const lines = [
      `planted by ${info.by}`,
      `generation ${Math.floor(info.stage)} of ${info.maxGen}${info.parents ? ` · ${info.parents}` : ""}`,
      info.pressed ? `pressed ${info.pressed}` : "",
    ].filter(Boolean);
    lines.forEach((text, k) => g.fillText(fit(g, text, lw - big), lx + big * 0.5, ly + lh * 0.12 + big * 1.35 + k * small * 1.3));
  }
  return { x: px, y: py, w: pw, h: ph };
}

function fit(g, text, width) {
  let t = String(text);
  if (g.measureText(t).width <= width) return t;
  while (t.length > 1 && g.measureText(t + "…").width > width) t = t.slice(0, -1);
  return t + "…";
}
