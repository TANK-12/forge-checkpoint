// The first level, a test range, as plain data: boxes, crates, walls,
// targets, sentries and the lap course. Distances in metres, +Z is "down
// range" from the spawn. The course heights are fixed on purpose: whether a
// suit clears them depends on the stats derived from the owner's tester edits.

// Breakable walls need this much energy in one hit (game rules, not physics):
// plaster gives to any punch, breeze block needs a Strength-mode punch from a
// strong suit, reinforced concrete needs a ground slam.
export const WALL_KINDS = {
  plaster: { name: "Plaster", break_j: 75, color: 0xd8d2c4, tex: "plaster" },
  breeze: { name: "Breeze block", break_j: 180, color: 0xa9a49a, tex: "brick" },
  concrete: { name: "Reinforced concrete", break_j: 2500, color: 0x8a8a86, tex: "concrete" },
};

export const CRATE_KG = [5, 10, 25, 50, 100, 200, 400];

// Crate edge length grows with the log of the mass: 0.35 m at 5 kg to 1.2 m.
export function crateSize(kg) {
  const t = Math.log(kg / 5) / Math.log(400 / 5);
  return 0.35 + Math.max(0, Math.min(1, t)) * 0.85;
}

function b(x0, y0, z0, x1, y1, z1, extra = {}) {
  return { min: [x0, y0, z0], max: [x1, y1, z1], ...extra };
}

export function testRange() {
  const statics = [
    b(-80, -1, -80, 80, 0, 80, { kind: "ground" }),
    // Course: step, jump block, two boost ledges with a dash gap, slide bar.
    b(-3, 0, 4, 3, 0.25, 7, { kind: "course", label: "Step 0.25 m" }),
    b(-3, 0, 9, 3, 0.34, 10, { kind: "course", label: "Jump 0.34 m" }),
    b(-3, 0, 14, 3, 1.2, 20, { kind: "course", label: "Boost ledge 1.2 m" }),
    b(-3, 0, 25, 3, 1.2, 30, { kind: "course", label: "Dash gap 5 m" }),
    b(-3.3, 0, 36, -3, 1.3, 36.3, { kind: "post" }),
    b(3, 0, 36, 3.3, 1.3, 36.3, { kind: "post" }),
    b(-3, 1.0, 36, 3, 1.3, 36.3, { kind: "bar", label: "Slide under 1.0 m" }),
    // Finish gate: side walls and a lintel; the doorway is a plaster panel.
    b(-14, 0, 44, -1, 3, 44.4, { kind: "gate" }),
    b(1, 0, 44, 14, 3, 44.4, { kind: "gate" }),
    b(-1, 2.6, 44, 1, 3, 44.4, { kind: "gate" }),
    // Range edges.
    b(-32.4, 0, -12, -31.6, 0.8, 54, { kind: "barrier" }),
    b(31.6, 0, -12, 32.4, 0.8, 54, { kind: "barrier" }),
    b(-32.4, 0, 54, 32.4, 0.8, 54.8, { kind: "barrier" }),
    b(-32.4, 0, -12.8, 32.4, 0.8, -12, { kind: "barrier" }),
  ];
  const walls = [
    { kind: "plaster", ...b(-1, 0, 44, 1, 2.6, 44.4), label: "Plaster 75 J" },
    { kind: "plaster", ...b(-18, 0, 6, -14, 2.4, 6.3), label: "Plaster 75 J" },
    { kind: "breeze", ...b(-18, 0, 12, -14, 2.4, 12.3), label: "Breeze block 180 J" },
    { kind: "concrete", ...b(-18, 0, 18, -14, 2.4, 18.4), label: "Concrete 2500 J" },
  ];
  const crates = CRATE_KG.map((kg, i) => ({ kg, x: 12, z: 2 + i * 2.2 }));
  const targets = [
    [18, 2],
    [18, 6],
    [18, 10],
    [18, 14],
    [14, 22],
    [20, 22],
  ].map(([x, z]) => ({ x, y: 1.4, z }));
  const sentries = [
    { x: 24, z: 40 },
    { x: -24, z: 34 },
  ];
  const trig = (x0, y0, z0, x1, y1, z1) => b(x0, y0, z0, x1, y1, z1);
  return {
    name: "Test range",
    spawn: { x: 0, y: 0, z: -3, yaw: 0 },
    statics,
    walls,
    crates,
    targets,
    sentries,
    start: trig(-3, 0, 0, 3, 3, 1),
    checkpoints: [
      trig(-3, 1.1, 14, 3, 4, 20),
      trig(-3, 1.1, 25, 3, 4, 30),
      trig(-3, 0, 35.5, 3, 4, 36.8),
    ],
    finish: trig(-1, 0, 44.6, 1, 3, 46),
    props: [
      { asset: "Barrel_01", x: 9, z: -1 },
      { asset: "Barrel_01", x: 9.8, z: -1.4 },
      { asset: "Barrel_01", x: 22, z: 17 },
      { asset: "Barrel_01", x: -12, z: 22 },
    ],
    signs: [
      { text: "Start", x: 0, y: 3.2, z: 0.5 },
      { text: "Crate yard", x: 12, y: 3.2, z: -0.5 },
      { text: "Walls", x: -16, y: 3.6, z: 3 },
      { text: "Finish", x: 0, y: 3.5, z: 44.2 },
    ],
  };
}
