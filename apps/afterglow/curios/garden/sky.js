/* The garden's sky follows the real local time of day: night with stars,
 * dawn, day, and the dusk afterglow the app is named after. Pure: an hour
 * (0-24, fractions allowed) in, colours and amounts out. */

// Keyframes around the clock; skyAt() blends between neighbours.
const KEYS = [
  { h: 0, top: [6, 7, 20], mid: [14, 14, 36], low: [24, 20, 44], stars: 1, light: 0.42, glow: 0 },
  { h: 4.5, top: [8, 9, 26], mid: [18, 18, 44], low: [30, 24, 52], stars: 1, light: 0.42, glow: 0 },
  { h: 5.8, top: [28, 30, 72], mid: [92, 70, 120], low: [236, 140, 120], stars: 0.35, light: 0.6, glow: 0.6 },
  { h: 7, top: [70, 120, 190], mid: [170, 190, 220], low: [255, 214, 170], stars: 0, light: 0.86, glow: 0.3 },
  { h: 9, top: [62, 132, 214], mid: [140, 192, 236], low: [214, 232, 246], stars: 0, light: 1, glow: 0 },
  { h: 16, top: [58, 124, 206], mid: [134, 184, 230], low: [220, 228, 236], stars: 0, light: 1, glow: 0 },
  { h: 18.2, top: [70, 86, 160], mid: [214, 150, 140], low: [255, 186, 110], stars: 0, light: 0.86, glow: 0.55 },
  { h: 19.4, top: [42, 36, 96], mid: [176, 86, 120], low: [255, 140, 70], stars: 0.15, light: 0.7, glow: 1 },
  { h: 20.6, top: [16, 14, 44], mid: [70, 36, 80], low: [196, 82, 60], stars: 0.6, light: 0.52, glow: 0.7 },
  { h: 22, top: [7, 8, 22], mid: [16, 15, 38], low: [30, 22, 48], stars: 1, light: 0.42, glow: 0.05 },
  { h: 24, top: [6, 7, 20], mid: [14, 14, 36], low: [24, 20, 44], stars: 1, light: 0.42, glow: 0 },
];

const mix = (a, b, t) => a + (b - a) * t;
const mixRgb = (a, b, t) => a.map((v, i) => Math.round(mix(v, b[i], t)));

export function wrapHour(hour) {
  const h = Number(hour);
  if (!Number.isFinite(h)) return 0;
  return ((h % 24) + 24) % 24;
}

/** Sky colours and amounts at a local hour. */
export function skyAt(hour) {
  const h = wrapHour(hour);
  let i = 0;
  while (i < KEYS.length - 2 && KEYS[i + 1].h <= h) i++;
  const a = KEYS[i];
  const b = KEYS[i + 1];
  const t = (h - a.h) / (b.h - a.h);
  const s = t * t * (3 - 2 * t);
  return {
    hour: h,
    top: mixRgb(a.top, b.top, s),
    mid: mixRgb(a.mid, b.mid, s),
    low: mixRgb(a.low, b.low, s),
    stars: mix(a.stars, b.stars, s),
    light: mix(a.light, b.light, s),
    glow: mix(a.glow, b.glow, s),
    night: h < 5.2 || h >= 21.2,
    sun: sunAt(h),
    moon: sunAt(h + 12),
    phase: phaseName(h),
  };
}

/** Where the sun (or, with hour + 12, the moon) sits: x 0..1 across the sky,
 *  y 0 at the horizon to 1 high; up false when it is below the horizon. */
export function sunAt(hour) {
  const h = wrapHour(hour);
  const t = (h - 6) / 13.5; // 6:00 rise, 19:30 set
  const up = t >= 0 && t <= 1;
  return { x: 0.08 + t * 0.84, y: up ? Math.sin(t * Math.PI) : 0, up };
}

export function phaseName(hour) {
  const h = wrapHour(hour);
  if (h < 5.2) return "Night, the garden asleep";
  if (h < 7) return "Dawn";
  if (h < 11.5) return "Morning";
  if (h < 16.5) return "Afternoon";
  if (h < 18.6) return "Evening";
  if (h < 21.2) return "Dusk, the afterglow hour";
  return "Night, fireflies out";
}

export function rgb(c, alpha = 1) {
  return alpha >= 1 ? `rgb(${c[0]},${c[1]},${c[2]})` : `rgba(${c[0]},${c[1]},${c[2]},${alpha})`;
}
