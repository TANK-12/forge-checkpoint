/* Colour helpers: star colour from the catalog's B-V index, and hex parsing. */

/* Surface temperature in kelvin from a B-V colour index (Ballesteros 2012). */
export function bvToTemperature(bv) {
  const b = Math.min(Math.max(bv, -0.4), 2.0);
  return 4600 * (1 / (0.92 * b + 1.7) + 1 / (0.92 * b + 0.62));
}

/* An approximate sRGB colour, 0..1 per channel, for a blackbody at a given
 * temperature (Tanner Helland's fit to the CIE data, 1,000-40,000 K). */
export function temperatureToRgb(kelvin) {
  const t = Math.min(Math.max(kelvin, 1000), 40000) / 100;
  let r;
  let g;
  let b;
  if (t <= 66) {
    r = 255;
    g = 99.4708025861 * Math.log(t) - 161.1195681661;
    b = t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307;
  } else {
    r = 329.698727446 * Math.pow(t - 60, -0.1332047592);
    g = 288.1221695283 * Math.pow(t - 60, -0.0755148492);
    b = 255;
  }
  const c = (v) => Math.min(255, Math.max(0, v)) / 255;
  return [c(r), c(g), c(b)];
}

export function hexToRgb(hex) {
  const n = parseInt(String(hex).replace("#", ""), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

export function rgbToCss([r, g, b], alpha = 1) {
  return `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${alpha})`;
}
