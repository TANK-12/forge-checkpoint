/* Colour: the time of day, the colour roles shapes are painted with, and how
   the Forge accent is folded into the world.

   A shape never names a colour, only a role ("snow", "rock", "accent"). Each
   frame the roles are resolved once: the base colour, pulled toward the sky's
   tint and darkened by how little light there is, with the Forge accent mixed
   into the shadows by the "Forge colour" setting. So a pine is green at noon,
   blue-violet at dusk and a silhouette at night without a second drawing. */

export function hexToRgb(hex) {
  let h = String(hex || "#000").replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const n = parseInt(h.slice(0, 6), 16) || 0;
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function rgbToHex([r, g, b]) {
  const c = (v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0");
  return `#${c(r)}${c(g)}${c(b)}`;
}

export function mix(a, b, t) {
  const x = hexToRgb(a), y = hexToRgb(b);
  return rgbToHex([0, 1, 2].map((i) => x[i] + (y[i] - x[i]) * t));
}

// k > 0 lightens toward white, k < 0 darkens toward black
export function shade(hex, k) {
  return k >= 0 ? mix(hex, "#ffffff", k) : mix(hex, "#000000", -k);
}

export function rgba(hex, a) {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r},${g},${b},${a})`;
}

/* The day, as keyframes over t in [0, 1): 0 is midnight, 0.5 noon.
   light is how lit the world is; sun is the colour of its light. */
const SKY = [
  { t: 0.0, top: "#070b24", bottom: "#1f2752", light: 0.28, haze: "#2a3363" },
  { t: 0.2, top: "#1a1f52", bottom: "#6a4a7a", light: 0.45, haze: "#5a4a78" },
  { t: 0.26, top: "#3c4f9a", bottom: "#f4a47c", light: 0.78, haze: "#e8a88e" },
  { t: 0.33, top: "#5b95da", bottom: "#dcebf7", light: 1.0, haze: "#cfe0f0" },
  { t: 0.66, top: "#4d87d0", bottom: "#e6eff7", light: 1.0, haze: "#d6e4f1" },
  { t: 0.74, top: "#39408a", bottom: "#ff9468", light: 0.8, haze: "#f09a7c" },
  { t: 0.81, top: "#1d2156", bottom: "#7a4470", light: 0.5, haze: "#6c4a72" },
  { t: 1.0, top: "#070b24", bottom: "#1f2752", light: 0.28, haze: "#2a3363" },
];

export const TIMES = { dawn: 0.27, day: 0.45, dusk: 0.745, night: 0.02 };

export function skyAt(t) {
  t = ((t % 1) + 1) % 1;
  let i = 0;
  while (i < SKY.length - 2 && SKY[i + 1].t <= t) i++;
  const a = SKY[i], b = SKY[i + 1];
  const k = (t - a.t) / (b.t - a.t || 1);
  return {
    top: mix(a.top, b.top, k),
    bottom: mix(a.bottom, b.bottom, k),
    haze: mix(a.haze, b.haze, k),
    light: a.light + (b.light - a.light) * k,
  };
}

// How dark it is, 0 at full day to 1 at deep night: lanterns and stars use it.
export function nightness(sky) {
  return Math.max(0, Math.min(1, (0.85 - sky.light) / 0.57));
}

export const BASE = {
  snow: "#f4f7fb",
  snowShade: "#c6d3e6",
  rock: "#6f7686",
  rockShade: "#4b5263",
  wood: "#8a5a3c",
  woodDark: "#5a3a28",
  leaf: "#2f6b52",
  leafShade: "#1f4c3b",
  roof: "#7c3d3d",
  roofShade: "#592b30",
  stone: "#b9ad9b",
  stoneShade: "#8e8373",
  fur: "#efe6da",
  furShade: "#c7b9a6",
  skin: "#f0c8a0",
  cloth: "#3f5f8f",
  clothShade: "#2e4670",
  cloth2: "#2b3550",
  board: "#ece5d6",
  gold: "#f2c14e",
  goldShade: "#c8962e",
  dark: "#2b2b33",
  light: "#ffffff",
  glow: "#ffd98a",
};

// Roles that shine rather than reflect: night never darkens them.
const EMISSIVE = new Set(["glow", "gold", "goldShade"]);

export function resolveRoles(sky, accent, accent2, strength, overcast = 0) {
  const light = Math.max(0.2, sky.light - overcast * 0.35);
  const dark = (1 - light) * 0.62;
  const tintK = (1 - light) * 0.45 + 0.08;
  const roles = {};
  for (const [role, base] of Object.entries(BASE)) {
    if (EMISSIVE.has(role)) { roles[role] = role === "glow" ? base : shade(base, -dark * 0.4); continue; }
    let c = mix(base, sky.haze, tintK);
    if (role.endsWith("Shade")) c = mix(c, accent, strength * 0.3);
    roles[role] = shade(c, -dark);
  }
  roles.accent = shade(accent, -dark * 0.7);
  roles.accent2 = shade(accent2, -dark * 0.7);
  return roles;
}

// The Forge's second accent when the hub did not send one: the accent turned
// a third of the way round the colour wheel.
export function companion(hex) {
  const [r, g, b] = hexToRgb(hex).map((v) => v / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
  let h = 0, s = 0;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    h /= 6;
  }
  h = (h + 0.33) % 1;
  const f = (n) => {
    const k = (n + h * 12) % 12, a = s * Math.min(l, 1 - l);
    return l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
  };
  return rgbToHex([f(0) * 255, f(8) * 255, f(4) * 255]);
}
