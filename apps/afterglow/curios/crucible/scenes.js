/* Composed scenes for Crucible, built from code so they are reproducible:
 * the starter forge that greets you on mount, the shelf still, and the
 * seeds (tools/make_seeds.mjs writes those). No DOM.
 */

import { M, createWorld, fillRect, setCell, place, stepN, inside } from "./sim.js";
import { rng, hashString } from "../_kit/rng.js";

function floor(s, top) {
  const r = rng(hashString(`floor:${s.seed}`));
  for (let x = 0; x < s.w; x++) {
    const bump = r() < 0.18 ? 1 : 0;
    fillRect(s, x, top - bump, x, s.h - 1, M.STONE);
  }
}

/** A sprinkled heap: a triangle of m with ragged edges. */
function heap(s, cx, baseY, halfWidth, height, m, r, t) {
  for (let y = 0; y < height; y++) {
    const span = Math.round(halfWidth * (1 - y / height));
    for (let x = cx - span; x <= cx + span; x++) {
      if (Math.abs(x - cx) === span && r() < 0.5) continue;
      if (inside(s, x, baseY - y) && s.mat[(baseY - y) * s.w + x] === M.EMPTY) setCell(s, x, baseY - y, m, t);
    }
  }
}

/**
 * The starter: a stone crucible full of ore on a coal bed already catching,
 * a wooden bung in its spout, a chute and a water trough to catch the pour.
 */
export function starter(seed = hashString("crucible")) {
  const s = createWorld(seed);
  const r = rng(seed ^ 0x9e3779b9);
  floor(s, 126);
  // a tapered stone bowl: inside runs from L(y) to R(y), floor at y 96..97
  const L = (y) => 66 + Math.round((y - 64) / 5);
  const R = (y) => 100 - Math.round((y - 64) / 5);
  for (let y = 62; y <= 95; y++) {
    fillRect(s, L(y) - 3, y, L(y) - 1, y, M.STONE);
    fillRect(s, R(y) + 1, y, R(y) + 3, y, M.STONE);
  }
  fillRect(s, L(95) - 3, 96, R(95) + 3, 97, M.STONE);
  fillRect(s, L(62) - 4, 61, L(62) - 1, 62, M.STONE); // rims
  fillRect(s, R(62) + 1, 61, R(62) + 4, 62, M.STONE);
  // the spout: a slot low in the right wall, stopped with a wooden bung
  fillRect(s, R(88) + 1, 87, R(88) + 3, 89, M.WOOD);
  // two stone legs on the floor
  fillRect(s, 66, 98, 68, 125, M.STONE);
  fillRect(s, 98, 98, 100, 125, M.STONE);
  // ore in the bowl
  for (let y = 70; y <= 95; y++) {
    for (let x = L(y); x <= R(y); x++) if (y > 74 || r() < 0.5) setCell(s, x, y, M.ORE);
  }
  // the coal heap under it, already catching along its flanks
  heap(s, 83, 125, 34, 30, M.COAL, r);
  for (let i = 0; i < s.mat.length; i++) {
    if (s.mat[i] !== M.COAL) continue;
    const x = i % s.w;
    const y = (i / s.w) | 0;
    const open = s.mat[i - s.w] === M.EMPTY || s.mat[i - 1] === M.EMPTY || s.mat[i + 1] === M.EMPTY;
    if (open && y > 98 && x > 60 && x < 106 && r() < 0.85) place(s, i, M.EMBER);
  }
  // it has been firing a while: the bowl and its charge are already hot
  for (let y = 60; y <= 125; y++) {
    for (let x = 50; x <= 116; x++) {
      const i = y * s.w + x;
      const m = s.mat[i];
      const k = Math.max(0, Math.min(1, (y - 62) / 34));
      if (m === M.STONE && y <= 97) s.temp[i] = 350 + 650 * k;
      else if (m === M.ORE) s.temp[i] = 420 + 560 * k;
      else if (m === M.COAL) s.temp[i] = 300;
      else if (m === M.STONE) s.temp[i] = 700;
    }
  }
  // a chute from the spout over the lip of the trough
  for (let k = 0; k <= 40; k++) {
    const x = R(88) + 4 + k;
    const y = 90 + Math.floor(k * 0.3);
    fillRect(s, x, y, x, y + 1, M.STONE, 560 - k * 9);
  }
  // the trough
  fillRect(s, 134, 105, 136, 125, M.STONE);
  fillRect(s, 204, 105, 206, 125, M.STONE);
  fillRect(s, 137, 109, 203, 125, M.WATER);
  // a sand dune on the left and a small woodpile
  heap(s, 20, 125, 24, 17, M.SAND, r);
  for (let k = 0; k < 3; k++) fillRect(s, 34 + k * 2, 123 - k * 3, 48 - k * 2, 124 - k * 3, M.WOOD);
  // an ice block melting slowly at the far right
  fillRect(s, 214, 110, 228, 125, M.ICE);
  return s;
}

/** The shelf still: the starter, already pouring. Cheap: built, not simulated long. */
export function showcase() {
  const s = starter();
  // ore halfway molten, glowing bed, a fresh ingot hissing in the trough
  for (let y = 84; y <= 95; y++) for (let x = 65; x <= 101; x++) setCell(s, x, y, M.MOLTEN, 1380 + (95 - y) * 6);
  for (let y = 70; y <= 83; y++) for (let x = 65; x <= 101; x++) {
    const i = y * s.w + x;
    if (s.mat[i] === M.ORE) s.temp[i] = 700 + (y - 70) * 25;
  }
  for (let i = 0; i < s.mat.length; i++) if (s.mat[i] === M.COAL && ((i / s.w) | 0) < 116) {
    place(s, i, M.EMBER, 1250 + ((i * 7) % 230));
  }
  fillRect(s, 96, 96, 104, 97, M.STONE, 900);
  fillRect(s, 102, 88, 104, 91, M.EMPTY, 600);
  for (let k = 0; k <= 22; k++) {
    const x = 105 + k;
    const y = 91 + Math.floor(k * 0.45);
    setCell(s, x, y, M.MOLTEN, 1320 - k * 8);
  }
  fillRect(s, 140, 120, 150, 125, M.IRON, 820);
  fillRect(s, 152, 123, 158, 125, M.IRON, 560);
  const r = rng(7);
  for (let k = 0; k < 120; k++) {
    const x = 132 + ((r() * 34) | 0);
    const y = 60 + ((r() * 44) | 0);
    if (r() < 0.6 + (y - 60) / 120) setCell(s, x, y, M.STEAM, 110);
  }
  for (let k = 0; k < 70; k++) {
    const x = 70 + ((r() * 28) | 0);
    const y = 98 + ((r() * 5) | 0);
    setCell(s, x, y, M.FIRE, 950);
  }
  return s;
}

/* ---- seeds ---------------------------------------------------------------- */

/**
 * A tall bloomery stack: layers of coal and ore, lit at the foot, a tap slot
 * at the hearth with a short spout stone over a deep quench pit.
 *
 * The stack stands on a stone plinth so the pit can sit right under the
 * spout. A long runner does not work here: the first trickle of melt freezes
 * on the cold stone, and iron only melts again past 1150 C, so the tap stays
 * shut for good. A three-cell spout with the water straight below keeps the
 * path short enough that the pour runs for thousands of steps, and the iron
 * below the tap that never gets out stays in the stack as the bloom.
 */
export function bloomery(seed = hashString("bloomery")) {
  const s = createWorld(seed);
  const r = rng(seed);
  floor(s, 128);
  const top = 12; // the stack walls run from here down to the hearth
  const hearth = 110; // top of the stone plinth the stack stands on
  fillRect(s, 96, top, 98, hearth, M.STONE);
  fillRect(s, 140, top, 142, hearth, M.STONE);
  fillRect(s, 96, hearth, 142, 127, M.STONE);
  // alternating charges of coal and ore
  let y = hearth - 1;
  let layer = 0;
  while (y > top + 20) {
    const thick = layer % 2 === 0 ? 7 + ((r() * 3) | 0) : 4 + ((r() * 3) | 0);
    const m = layer % 2 === 0 ? M.COAL : M.ORE;
    fillRect(s, 99, y - thick + 1, 139, y, m);
    y -= thick;
    layer++;
  }
  // lit at the foot
  for (let y = hearth - 8; y < hearth; y++) for (let x = 99; x <= 139; x++) if (r() < 0.35) setCell(s, x, y, M.EMBER);
  // a tap slot at the hearth (one cell high, so grains cannot slip through it),
  // a short spout stone, and the quench pit dug in under it
  fillRect(s, 140, hearth - 1, 142, hearth - 1, M.EMPTY);
  fillRect(s, 143, hearth, 145, hearth + 1, M.STONE);
  fillRect(s, 226, 111, 228, s.h - 1, M.STONE);
  fillRect(s, 143, 114, 225, s.h - 2, M.WATER);
  // a woodpile and a sand drift on the left for the fire to find
  for (let k = 0; k < 4; k++) fillRect(s, 20 + k * 2, 124 - k * 4, 62 - k * 2, 125 - k * 4, M.WOOD);
  return s;
}

/** A beach of sand with lightning strikes buried in it: they fuse into glass. */
export function fulgurites(seed = hashString("fulgurites")) {
  const s = createWorld(seed);
  const r = rng(seed);
  floor(s, 130);
  // dunes
  for (let x = 0; x < 150; x++) {
    const top = 100 + Math.round(8 * Math.sin(x / 17) + 5 * Math.sin(x / 7.3 + 1));
    for (let y = top; y < 129; y++) setCell(s, x, y, M.SAND);
  }
  // the sea, held by a low reef so it stays still until you play with it
  fillRect(s, 150, 116, 152, 129, M.STONE);
  for (let x = 153; x < s.w; x++) for (let y = 104; y < 129; y++) setCell(s, x, y, M.WATER, 14);
  for (let x = 150; x < 162; x++) for (let y = 112 + (x - 150); y < 129; y++) setCell(s, x, y, M.SAND);
  // three strikes: forked white-hot channels down into the sand
  for (const sx of [34, 78, 118]) {
    let x = sx;
    for (let y = 90; y < 128; y++) {
      x += r() < 0.3 ? -1 : r() < 0.45 ? 1 : 0;
      for (const dx of [-1, 0, 1]) {
        const i = y * s.w + x + dx;
        if (s.mat[i] === M.SAND) s.temp[i] = dx === 0 ? 2350 : 1900;
      }
      if (r() < 0.1) {
        let bx = x;
        const dir = r() < 0.5 ? -1 : 1;
        for (let k = 0; k < 6; k++) {
          bx += dir;
          const j = (y + k) * s.w + bx;
          if (y + k < s.h && s.mat[j] === M.SAND) s.temp[j] = 2100;
        }
      }
    }
  }
  return s;
}

/** A frozen cave with a brazier: icicles drip, the drips refreeze on cold stone. */
export function thaw(seed = hashString("thaw")) {
  const s = createWorld(seed, undefined, undefined, -8);
  const r = rng(seed);
  // cave: ceiling and floor of cold stone
  for (let x = 0; x < s.w; x++) {
    const ceil = 14 + Math.round(6 * Math.sin(x / 13) + 3 * Math.sin(x / 5.1));
    fillRect(s, x, 0, x, ceil, M.STONE, -18);
    const floorTop = 118 + Math.round(4 * Math.sin(x / 19 + 2));
    fillRect(s, x, floorTop, x, s.h - 1, M.STONE, -22);
    // icicles
    if (r() < 0.3) {
      const len = 6 + ((r() * 22) | 0);
      for (let k = 1; k <= len; k++) {
        setCell(s, x, ceil + k, M.ICE, -20);
        if (k < len / 3 && x + 1 < s.w) setCell(s, x + 1, ceil + k, M.ICE, -20);
      }
    }
  }
  // the brazier: an iron bowl of live coal on a stone post
  fillRect(s, 112, 98, 114, 118, M.STONE, -5);
  fillRect(s, 100, 94, 126, 95, M.IRON, 300);
  fillRect(s, 100, 88, 101, 93, M.IRON, 300);
  fillRect(s, 125, 88, 126, 93, M.IRON, 300);
  for (let y = 86; y <= 93; y++) for (let x = 102; x <= 124; x++) if (y > 88 || r() < 0.6) setCell(s, x, y, M.EMBER);
  // a frozen pool
  fillRect(s, 150, 112, 210, 120, M.ICE, -20);
  return s;
}

/** Hot ingots under a leaking cistern: endless hiss. */
export function rainOnIron(seed = hashString("rain on iron")) {
  const s = createWorld(seed);
  floor(s, 124);
  // the cistern, leaking in a few places
  fillRect(s, 50, 8, 52, 30, M.STONE);
  fillRect(s, 188, 8, 190, 30, M.STONE);
  fillRect(s, 50, 30, 190, 31, M.STONE);
  fillRect(s, 53, 16, 187, 29, M.WATER);
  for (const x of [74, 113, 131, 158]) fillRect(s, x, 30, x, 31, M.EMPTY);
  // an anvil and a row of ingots glowing from the fire
  fillRect(s, 60, 104, 92, 109, M.IRON, 1100);
  fillRect(s, 68, 110, 84, 123, M.IRON, 900);
  for (let k = 0; k < 5; k++) {
    const x = 104 + k * 14;
    fillRect(s, x, 116 - (k % 2) * 2, x + 9, 123, M.IRON, 1120 - k * 50);
  }
  fillRect(s, 196, 112, 230, 123, M.COAL);
  for (let x = 196; x <= 230; x++) setCell(s, x, 111, M.EMBER);
  return s;
}

export const SEEDS = [
  {
    slug: "bloomery",
    name: "Bloomery",
    build: bloomery,
    note:
      "A stack furnace charged the old way, coal and ore in layers, lit at the foot. Watch the burn climb the stack while molten iron trickles down through the charge and pools on the hearth, then runs out of the tap slot, off the spout stone and hisses into the quench pit as iron shot. What cools before it reaches the tap stays in the stack as the bloom. The best part is how slowly it starts and how much it does once it gets going.",
  },
  {
    slug: "fulgurites",
    name: "Fulgurites",
    build: fulgurites,
    note:
      "Lightning struck the beach a moment ago and the sand is still white-hot along the strike paths. The heat fuses the grains into glass in branching veins, the way real fulgurites form. Take the eraser to the dune afterwards and dig the glass out, it stays put while the loose sand slides away from it.",
  },
  {
    slug: "thaw",
    name: "Thaw",
    build: thaw,
    note:
      "A freezing cave with an iron brazier in the middle. The icicles over the fire drip, and the drops land on stone cold enough to freeze them again, so the cave slowly redraws itself. The room is set below zero here, so open water freezes on its own; try the torch on the frozen pool.",
  },
  {
    slug: "rain-on-iron",
    name: "Rain on iron",
    build: rainOnIron,
    note:
      "A leaking cistern over an anvil and a row of ingots still glowing from the fire. Every drop that lands flashes to steam, and the steam climbs, cools and rains down again. The iron loses its glow one hiss at a time. I could watch the colour leave the metal for a long while.",
  },
];

/** Warm a scene a little so a still shows life (used by previews; cheap). */
export function settle(s, steps = 4) {
  stepN(s, steps);
  return s;
}
