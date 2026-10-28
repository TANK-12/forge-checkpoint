/* Swarm: drawing. Pure canvas 2D; the shelf preview and the live view share it. */

import { createSwarm, step, cleanRules } from "./sim.js";

/** One colour per kind of particle, in the order the rule table lists them. */
export const COLOURS = ["#ffb454", "#ff6b5a", "#a58bff", "#5ad1ff", "#7dff9a", "#ffd36b", "#ff8ad8", "#e6e1d6"];
export const NAMES = ["Amber", "Coral", "Violet", "Sky", "Mint", "Gold", "Pink", "Bone"];
const BG = "15, 17, 21";

/** One frame. `trails` fades the last frame instead of clearing it, so
 *  movement leaves a short streak. Sizes are in canvas pixels. */
export function drawSwarm(g, sw, { w, h, trails = true, dot = 2 } = {}) {
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.globalCompositeOperation = "source-over";
  g.globalAlpha = 1;
  g.fillStyle = trails ? `rgba(${BG}, 0.26)` : `rgb(${BG})`;
  g.fillRect(0, 0, w, h);
  g.globalCompositeOperation = "lighter";
  g.globalAlpha = 0.85;
  const sx = w / sw.W;
  const sy = h / sw.H;
  const half = dot / 2;
  for (let c = 0; c < sw.k; c++) {
    g.fillStyle = COLOURS[c % COLOURS.length];
    g.beginPath();
    for (let i = c; i < sw.n; i += sw.k) g.rect(sw.x[i] * sx - half, sw.y[i] * sy - half, dot, dot);
    g.fill();
  }
  g.globalCompositeOperation = "source-over";
  g.globalAlpha = 1;
}

/** A small swarm grown for a moment, ready to draw: the shelf card and the
 *  keepsake pictures. It has only a few hundred particles, so the reach grows
 *  to keep the crowd as dense (in reaches) as the full swarm, or it would
 *  never meet itself. The growing stops early on a busy machine, so a
 *  preview stays within its 30 ms. */
export function growPreview(data, w, h, budgetMs = 18) {
  const rules = cleanRules(data);
  const count = Math.min(rules.count, 380);
  const aspect = w / Math.max(1, h);
  const grow = Math.sqrt(rules.count / count);
  const small = { ...rules, count, reach: Math.min(0.45, rules.reach * grow) };
  const sw = createSwarm(small, aspect);
  const until = performance.now() + budgetMs;
  for (let s = 0; s < 36 && performance.now() < until; s++) step(sw, small, 1 / 18);
  return { sw, rules: small };
}

export function stillSwarm(canvas, data, budgetMs = 18) {
  const w = canvas.width;
  const h = canvas.height;
  const { sw, rules } = growPreview(data, w, h, budgetMs);
  const g = canvas.getContext("2d");
  const dot = Math.max(1.5, Math.min(w, h) / 110);
  drawSwarm(g, sw, { w, h, trails: false, dot });
  for (let s = 0; s < 5; s++) {
    step(sw, rules, 1 / 30);
    drawSwarm(g, sw, { w, h, trails: true, dot });
  }
}

/** A picture too small for single dots (the gallery's 40 px squares). Drawn
 *  straight in, the dots pile up into white noise; drawn at three times the
 *  size and shrunk, the crowd keeps its colours and its clumps. */
export function smallSwarm(canvas, data, budgetMs = 12) {
  const big = canvas.ownerDocument.createElement("canvas");
  big.width = canvas.width * 3;
  big.height = canvas.height * 3;
  stillSwarm(big, data, budgetMs);
  const g = canvas.getContext("2d");
  g.imageSmoothingQuality = "high";
  g.drawImage(big, 0, 0, canvas.width, canvas.height);
}
