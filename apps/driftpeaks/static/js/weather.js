/* Weather: a registry of kinds, and the particles that draw them.

   Each kind is data: which particle it throws (and how many), how much fog,
   how hard the wind blows, how much it darkens the day, and whether it
   carries lightning. Adding a weather is one entry here; the Settings list
   and the "changing" rotation both read WEATHER. */

import { rgba } from "./palette.js";

export const WEATHER = {
  clear: { label: "Clear", particle: null, count: 0, fog: 0, wind: 0, overcast: 0, weight: 4 },
  snow: { label: "Snowfall", particle: "flake", count: 170, fog: 0.12, wind: -30, overcast: 0.2, weight: 3 },
  blizzard: { label: "Blizzard", particle: "flake", count: 420, fog: 0.35, wind: -260, overcast: 0.4, weight: 1 },
  rain: { label: "Rain", particle: "streak", count: 240, fog: 0.15, wind: -60, overcast: 0.35, weight: 1.5 },
  fog: { label: "Fog", particle: "mote", count: 40, fog: 0.55, wind: -10, overcast: 0.25, weight: 1.5 },
  storm: { label: "Thunderstorm", particle: "streak", count: 360, fog: 0.28, wind: -140, overcast: 0.6, lightning: true, weight: 1 },
  gusts: { label: "Sand gusts", particle: "grain", count: 260, fog: 0.22, wind: -380, overcast: 0.15, tint: "#d9a86a", weight: 1 },
};

export const STORMY = new Set(["storm", "blizzard", "gusts"]);

export class Weather {
  constructor() {
    this.kind = "clear";
    this.from = "clear";
    this.blend = 1; // 0..1 from `from` to `kind`
    this.nextChange = 40;
    this.parts = [];
    this.flash = 0;
    this.thunder = 0;
  }

  // The live mix of the old and new weather's numbers.
  get mixed() {
    const a = WEATHER[this.from], b = WEATHER[this.kind], k = this.blend;
    const lerp = (p) => (a[p] || 0) + ((b[p] || 0) - (a[p] || 0)) * k;
    return { fog: lerp("fog"), wind: lerp("wind"), overcast: lerp("overcast"), tint: b.tint || a.tint, tintK: b.tint ? k : a.tint ? 1 - k : 0 };
  }

  set(kind) {
    if (!WEATHER[kind] || kind === this.kind) return;
    this.from = this.kind;
    this.kind = kind;
    this.blend = 0;
  }

  update(dt, mode, r, W, H, density, events) {
    this.blend = Math.min(1, this.blend + dt / 5);
    if (mode === "changing") {
      this.nextChange -= dt;
      if (this.nextChange <= 0) {
        const keys = Object.keys(WEATHER);
        let total = keys.reduce((s, k) => s + WEATHER[k].weight, 0), x = r() * total;
        let pick = keys[0];
        for (const k of keys) { x -= WEATHER[k].weight; if (x <= 0) { pick = k; break; } }
        this.set(pick);
        this.nextChange = 35 + r() * 50;
      }
    } else if (WEATHER[mode]) this.set(mode);

    const w = WEATHER[this.kind];
    const want = Math.round((w.count || 0) * density * this.blend);
    const wind = this.mixed.wind;
    while (this.parts.length < want) this.parts.push(this.spawn(w.particle, r, W, H, true));
    if (this.parts.length > want) this.parts.length = Math.max(want, this.parts.length - 8);
    for (const p of this.parts) {
      p.x += (wind * p.depth + p.vx) * dt;
      p.y += p.vy * p.depth * dt;
      p.x += Math.sin((p.y + p.seed) / 40) * p.sway * dt;
      if (p.y > H + 20 || p.x < -60 || p.x > W + 60) Object.assign(p, this.spawn(w.particle, r, W, H, false, wind));
    }

    this.flash = Math.max(0, this.flash - dt * 2.5);
    if (w.lightning && this.blend > 0.6 && r() < dt * 0.12) {
      this.flash = 1;
      this.thunder = 0.4 + r() * 1.2;
    }
    if (this.thunder > 0) {
      this.thunder -= dt;
      if (this.thunder <= 0) events.push("thunder");
    }
  }

  spawn(kind, r, W, H, anywhere, wind = 0) {
    const depth = 0.4 + r() * 0.9;
    const fromSide = !anywhere && wind < -100 && r() < 0.6;
    const p = {
      kind: kind || "flake", depth, seed: r() * 1000,
      x: fromSide ? W + 20 : r() * (W + 200) - 50,
      y: anywhere ? r() * H : fromSide ? r() * H : -20,
      vx: 0, vy: 60, sway: 0, size: 1,
    };
    if (p.kind === "flake") Object.assign(p, { vy: 70 + r() * 60, sway: 30, size: 1 + r() * 2.2 });
    else if (p.kind === "streak") Object.assign(p, { vy: 900 + r() * 400, size: 10 + r() * 14 });
    else if (p.kind === "grain") Object.assign(p, { vy: 30 + r() * 60, vx: -80, size: 0.8 + r() * 1.6 });
    else if (p.kind === "mote") Object.assign(p, { vy: 8 + r() * 10, sway: 12, size: 30 + r() * 60 });
    return p;
  }

  draw(ctx, W, H, roles, night) {
    const mixed = this.mixed;
    if (mixed.fog > 0.01) {
      const g = ctx.createLinearGradient(0, H * 0.25, 0, H);
      const fogC = night > 0.5 ? "#8390b0" : "#e9eef5";
      g.addColorStop(0, rgba(fogC, 0));
      g.addColorStop(1, rgba(fogC, Math.min(0.75, mixed.fog)));
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, W, H);
    }
    if (mixed.tint && mixed.tintK > 0) {
      ctx.fillStyle = rgba(mixed.tint, 0.22 * mixed.tintK);
      ctx.fillRect(0, 0, W, H);
    }
    const wind = mixed.wind;
    for (const p of this.parts) {
      if (p.kind === "flake") {
        ctx.fillStyle = rgba("#ffffff", 0.5 + p.depth * 0.4);
        const s = p.size * p.depth * 1.6;
        ctx.beginPath(); // a tiny hexagon: low-poly snow
        for (let k = 0; k < 6; k++) {
          const a = (k / 6) * Math.PI * 2 + p.seed;
          ctx.lineTo(p.x + Math.cos(a) * s, p.y + Math.sin(a) * s);
        }
        ctx.fill();
      } else if (p.kind === "streak") {
        ctx.strokeStyle = rgba("#cfe0ff", 0.25 + p.depth * 0.3);
        ctx.lineWidth = p.depth;
        const len = p.size * p.depth;
        const dx = (wind * p.depth) / (p.vy * p.depth) * len;
        ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x - dx, p.y - len); ctx.stroke();
      } else if (p.kind === "grain") {
        ctx.fillStyle = rgba("#f0cc94", 0.35 + p.depth * 0.3);
        ctx.fillRect(p.x, p.y, p.size * 4 * p.depth, p.size * p.depth);
      } else if (p.kind === "mote") {
        ctx.fillStyle = rgba(night > 0.5 ? "#9aa6c6" : "#ffffff", 0.05 * p.depth);
        ctx.beginPath(); ctx.arc(p.x, p.y, p.size * p.depth, 0, Math.PI * 2); ctx.fill();
      }
    }
    if (this.flash > 0) {
      ctx.fillStyle = rgba("#eef3ff", this.flash * 0.55);
      ctx.fillRect(0, 0, W, H);
    }
  }
}
