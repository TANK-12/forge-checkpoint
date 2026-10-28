/* Units, constants and the clock shared by every Cosmos mode.
 *
 * Positions in the map are kept in astronomical units (AU) as plain doubles;
 * stars arrive in parsecs. Dates are Julian dates, because every published
 * set of orbital elements is written against one. The difference between UTC
 * and the TDB timescale JPL uses is about 69 seconds, which moves the Moon by
 * roughly 70 km -- well under anything the map can show, so it is ignored.
 */

export const AU_KM = 149597870.7;
export const LIGHT_YEAR_AU = 63241.07708;
export const PARSEC_AU = 206264.8062;
export const PARSEC_LY = 3.261563777;
export const J2000 = 2451545.0;
export const DAY_MS = 86400000;
export const DAYS_PER_CENTURY = 36525;
export const OBLIQUITY_RAD = (23.4392911 * Math.PI) / 180;

const UNIX_EPOCH_JD = 2440587.5;

export function jdFromMs(ms) {
  return ms / DAY_MS + UNIX_EPOCH_JD;
}

export function msFromJd(jd) {
  return (jd - UNIX_EPOCH_JD) * DAY_MS;
}

function group(n) {
  return Math.round(n).toLocaleString("en-US");
}

/* A distance given in AU, written in whichever unit a person would use. */
export function formatDistance(au) {
  const km = au * AU_KM;
  if (km < 2e6) return `${group(km)} km`;
  if (au < 2000) return `${au < 10 ? au.toPrecision(3) : group(au)} AU`;
  const ly = au / LIGHT_YEAR_AU;
  if (ly < 3000) return `${ly < 10 ? ly.toFixed(2) : group(ly)} light-years`;
  const kpc = ly / PARSEC_LY / 1000;
  return `${kpc.toFixed(2)} kpc (${group(ly)} light-years)`;
}

export function formatDuration(days) {
  const d = Math.abs(days);
  if (d < 2) return `${(d * 24).toFixed(1)} hours`;
  if (d < 730) return `${d.toFixed(d < 10 ? 2 : 1)} days`;
  return `${(d / 365.25).toFixed(d < 3650 ? 2 : 1)} years`;
}
