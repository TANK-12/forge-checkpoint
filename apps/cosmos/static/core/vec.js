/* Small 3-vector helpers on plain [x, y, z] arrays. */

import { OBLIQUITY_RAD } from "./units.js";

export const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const scale = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
export const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const length = (a) => Math.hypot(a[0], a[1], a[2]);
export const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

export function cross(a, b) {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

export function normalize(a) {
  const l = length(a);
  return l > 0 ? scale(a, 1 / l) : [0, 0, 0];
}

/* Angle between two vectors, in degrees. */
export function angleBetween(a, b) {
  const c = dot(a, b) / (length(a) * length(b));
  return (Math.acos(Math.min(1, Math.max(-1, c))) * 180) / Math.PI;
}

/* J2000 equatorial -> J2000 ecliptic: a rotation about the shared x axis
 * (the March equinox direction) by the obliquity of the ecliptic. */
export function equatorialToEcliptic(v) {
  const c = Math.cos(OBLIQUITY_RAD);
  const s = Math.sin(OBLIQUITY_RAD);
  return [v[0], v[1] * c + v[2] * s, -v[1] * s + v[2] * c];
}

/* A unit vector for a direction on the sky given as RA/Dec in degrees,
 * returned in ecliptic coordinates. */
export function raDecToEclipticUnit(raDeg, decDeg) {
  const a = (raDeg * Math.PI) / 180;
  const d = (decDeg * Math.PI) / 180;
  return equatorialToEcliptic([Math.cos(d) * Math.cos(a), Math.cos(d) * Math.sin(a), Math.sin(d)]);
}
