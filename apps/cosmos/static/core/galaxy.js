/* A drawn model of the Milky Way, placed around the real Sun.
 *
 * Nobody has a picture of our galaxy from outside; we are inside its disc.
 * What is known well is the frame -- where the galactic centre and the
 * galactic pole are on the sky, and that the Sun is about 8.2 kpc from the
 * centre and a little above the plane -- and that frame is used exactly here.
 * The shape inside it is a model and the map labels it as one:
 *
 *   a bar about 4.5 kpc long at 27 degrees to the Sun-centre line,
 *   a bulge, an exponential disc,
 *   four logarithmic spiral arms with a 12-degree pitch, placed so that at
 *   the Sun's side of the galaxy they cross at about the radii measured for
 *   the Scutum-Centaurus (4.9 kpc), Sagittarius-Carina (6.8), Perseus (9.5)
 *   and Outer (13.3) arms,
 *   and the short Orion Spur the Sun sits in.
 *
 * Galactocentric model coordinates (u, v, w) in parsecs share their axes with
 * heliocentric galactic coordinates: u points from the Sun toward the centre,
 * v toward galactic longitude 90 degrees (the way the Sun is travelling), w
 * toward the north galactic pole. The Sun is at u = -8200, w = +20. The galaxy
 * turns clockwise seen from the north pole, so the arms trail
 * counter-clockwise.
 */

import { mulberry32 } from "./nbody.js";
import { equatorialToEcliptic } from "./vec.js";

export const SUN_TO_CENTER_PC = 8200;
export const SUN_ABOVE_PLANE_PC = 20;

// Rows are the galactic x, y, z axes written in J2000 equatorial coordinates
// (Hipparcos introduction, vol. 1, section 1.5.3).
const GALACTIC_AXES_EQ = [
  [-0.0548755604, -0.8734370902, -0.4838350155],
  [0.4941094279, -0.44482963, 0.7469822445],
  [-0.867666149, -0.1980763734, 0.4559837762],
];

/* Heliocentric galactic cartesian -> heliocentric J2000 ecliptic. */
export function galacticToEcliptic(v) {
  const A = GALACTIC_AXES_EQ;
  return equatorialToEcliptic([
    A[0][0] * v[0] + A[1][0] * v[1] + A[2][0] * v[2],
    A[0][1] * v[0] + A[1][1] * v[1] + A[2][1] * v[2],
    A[0][2] * v[0] + A[1][2] * v[1] + A[2][2] * v[2],
  ]);
}

/* Model coordinates (u, v, w, parsecs) -> heliocentric ecliptic parsecs. */
export function modelToEcliptic(u, v, w) {
  return galacticToEcliptic([u + SUN_TO_CENTER_PC, v, w - SUN_ABOVE_PLANE_PC]);
}

export function galacticCenterEcliptic() {
  return modelToEcliptic(0, 0, 0);
}

const PITCH = (12 * Math.PI) / 180;
const K = Math.tan(PITCH);
const SUN_AZIMUTH = Math.PI; // the Sun sits on the -u axis

// Scutum-Centaurus and Perseus carry most of the old stars and are drawn
// denser; the other two are weaker, mostly gas and young stars.
export const ARMS = [
  { name: "Scutum-Centaurus Arm", radius_at_sun_pc: 4900, weight: 1.5 },
  { name: "Sagittarius-Carina Arm", radius_at_sun_pc: 6800, weight: 0.8 },
  { name: "Perseus Arm", radius_at_sun_pc: 9500, weight: 1.4 },
  { name: "Outer Arm", radius_at_sun_pc: 13300, weight: 0.5 },
];
const ARM_WEIGHT_TOTAL = ARMS.reduce((sum, a) => sum + a.weight, 0);

function pickArm(r) {
  let x = r * ARM_WEIGHT_TOTAL;
  for (const arm of ARMS) {
    x -= arm.weight;
    if (x <= 0) return arm;
  }
  return ARMS[ARMS.length - 1];
}

/* Azimuth (radians, counter-clockwise from +u) of an arm at radius R. */
export function armAzimuth(arm, R) {
  return SUN_AZIMUTH + Math.log(R / arm.radius_at_sun_pc) / K;
}

function gauss(rng) {
  let u = 0;
  while (u === 0) u = rng();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rng());
}

/* Points for the model. Returns ecliptic positions (pc), RGB colours, the
 * same points' (u, v) for drawing a face-on glow, and label anchors. */
export function buildGalaxyModel({ count = 60000, seed = 2 } = {}) {
  const rng = mulberry32(seed);
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const plane = new Float32Array(count * 2);
  const barAngle = (27 * Math.PI) / 180;

  const WARM = [1.0, 0.86, 0.66];
  const DISC = [0.78, 0.82, 1.0];
  const ARM = [0.68, 0.78, 1.0];
  const NEBULA = [1.0, 0.56, 0.7];

  for (let i = 0; i < count; i++) {
    const pick = rng();
    let u;
    let v;
    let w;
    let col;
    if (pick < 0.1) {
      // Bar: long axis tipped 27 degrees toward positive v (the near end is
      // at positive galactic longitude).
      const a = gauss(rng) * 1500;
      const b = gauss(rng) * 480;
      u = a * Math.cos(barAngle) - b * Math.sin(barAngle);
      v = a * Math.sin(barAngle) + b * Math.cos(barAngle);
      w = gauss(rng) * 300;
      col = WARM;
    } else if (pick < 0.18) {
      const r = Math.abs(gauss(rng)) * 750;
      const t = rng() * 2 * Math.PI;
      const z = rng() * 2 - 1;
      u = r * Math.sqrt(1 - z * z) * Math.cos(t);
      v = r * Math.sqrt(1 - z * z) * Math.sin(t);
      w = r * z * 0.7;
      col = WARM;
    } else if (pick < 0.5) {
      const R = -3000 * Math.log(1 - rng() * 0.995);
      const t = rng() * 2 * Math.PI;
      u = R * Math.cos(t);
      v = R * Math.sin(t);
      w = gauss(rng) * 160;
      col = DISC;
    } else if (pick < 0.985) {
      const arm = pickArm(rng());
      const R = 3200 + (16000 - 3200) * Math.pow(rng(), 1.3);
      const t = armAzimuth(arm, R);
      const spread = gauss(rng) * (420 + 0.055 * R);
      u = R * Math.cos(t) + spread * Math.cos(t + Math.PI / 2 - PITCH);
      v = R * Math.sin(t) + spread * Math.sin(t + Math.PI / 2 - PITCH);
      w = gauss(rng) * 110;
      col = rng() < 0.08 ? NEBULA : ARM;
    } else {
      // Orion Spur: a short arm segment running through the Sun's position.
      const t = SUN_AZIMUTH + (rng() - 0.55) * 0.55;
      const R = 8300 * Math.exp(K * (t - SUN_AZIMUTH)) + gauss(rng) * 380;
      u = R * Math.cos(t);
      v = R * Math.sin(t);
      w = gauss(rng) * 90;
      col = rng() < 0.08 ? NEBULA : ARM;
    }
    const e = modelToEcliptic(u, v, w);
    positions.set(e, i * 3);
    const shade = 0.75 + rng() * 0.25;
    colors[i * 3] = col[0] * shade;
    colors[i * 3 + 1] = col[1] * shade;
    colors[i * 3 + 2] = col[2] * shade;
    plane[i * 2] = u;
    plane[i * 2 + 1] = v;
  }

  const labels = [
    { name: "Galactic centre (Sagittarius A*)", position: galacticCenterEcliptic() },
    ...ARMS.map((arm) => {
      const R = arm.radius_at_sun_pc * 1.35;
      const t = armAzimuth(arm, R);
      return { name: arm.name, position: modelToEcliptic(R * Math.cos(t), R * Math.sin(t), 0) };
    }),
  ];
  return { positions, colors, plane, labels, extent_pc: 18000 };
}
