// The heads-up display: energy and armour bars, suit mode, speed, lap timer,
// messages, and the derived stats in a corner so tester edits show up here.

import { MODES, liftLimit, lapTime, nearestCrate } from "./sim.js";

const $ = (sel) => document.querySelector(sel);
const fmt = (v, d = 1) => (v == null ? "-" : Number(v).toFixed(d));
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);
// Keyboard names for the HUD; with a pad in use setLabels() swaps in the
// pad's from controls.json (pad.js labelsFor). A sim message names a key as
// {action} ("press {repair} to repair"), filled in from these.
const KEYB = {
  use: "E",
  punch: "click",
  repair: "R",
  "mode:armour": "1",
  "mode:strength": "2",
  "mode:speed": "3",
  "mode:cloak": "4",
};

export class Hud {
  constructor(stats, source) {
    this.labels = { ...KEYB };
    this.modes = $("#modes");
    this.modes.innerHTML = MODES.map(
      (m) =>
        `<div class="mode" data-mode="${m}"><b>${this.labels[`mode:${m}`]}</b>${m}<i>${Math.round(stats.energy.drain_w[m])} W</i></div>`,
    ).join("");
    this.energy = $("#energy i");
    this.energyText = $("#energy span");
    this.hp = $("#hp i");
    this.hpText = $("#hp span");
    this.speed = $("#speed");
    this.timer = $("#timer");
    this.msgs = $("#msgs");
    this.prompt = $("#prompt");
    this.banner = $("#banner");
    this.statsBox = $("#stats");
    this.renderStats(stats, source);
    this.lastMsg = null;
  }

  setLabels(map) {
    this.labels = { ...KEYB, ...(map || {}) };
    this.lastMsg = null; // so the messages are shown again with these names
    for (const el of this.modes.children) el.querySelector("b").textContent = this.labels[`mode:${el.dataset.mode}`];
    this.banner.textContent = `Arms broken: the frame took more than it was built for. Press ${this.labels.repair} to repair.`;
  }

  renderStats(st, source) {
    const m = st.move;
    const s = st.strength;
    const e = st.energy;
    const rows = [
      ["Suit", `${st.name || st.model}`],
      ["Profile", `${st.profile}${source === "stub" ? " (offline stub)" : ""}`],
      ["Mass", `${fmt(st.mass.total_kg)} kg (body ${fmt(st.mass.body_kg)}, suit ${fmt(st.mass.suit_kg)}, kit ${fmt(st.mass.kit_kg)})`],
      ["Sprint", `${fmt(m.sprint_mps, 2)} m/s, Speed mode ${fmt(m.speed_mode_mps, 2)}`],
      ["Jump", `${fmt(m.jump_m, 2)} m, boost ${fmt(m.boost_jump_m, 2)} m`],
      ["Dash", `${fmt(m.dash_mps, 2)} m/s for ${fmt(m.dash_s, 2)} s`],
      ["Slam", `${fmt(m.slam_j, 0)} J, ${fmt(m.slam_radius_m, 2)} m`],
      ["Lift", `${fmt(s.lift_kg)} kg, Strength ${fmt(s.strength_lift_kg)} kg`],
      ["Breaks at", `${fmt(s.break_kg)} kg`],
      ["Punch", `${fmt(s.punch_j, 0)} J, Strength ${fmt(s.strength_punch_j, 0)} J`],
      ["Throw", `${fmt(s.throw_j, 0)} J, Strength ${fmt(s.strength_throw_j, 0)} J`],
      ["Armour", `${fmt(st.armour.hp, 0)} hp, Armour mode x${fmt(st.armour.armour_mode_damage_mult, 2)}`],
      ["Energy", `${fmt(e.bar_j, 0)} J, +${fmt(e.recharge_w, 0)} W after ${fmt(e.recharge_delay_s)} s, boost ${fmt(e.boost_j, 0)} J`],
    ];
    this.statsBox.innerHTML =
      `<h3>Derived stats</h3>` + rows.map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join("");
  }

  update(sim) {
    const p = sim.player;
    const st = sim.stats;
    for (const el of this.modes.children) el.classList.toggle("on", el.dataset.mode === p.mode);
    const ef = p.energy / st.energy.bar_j;
    this.energy.style.width = `${(ef * 100).toFixed(1)}%`;
    this.energy.classList.toggle("low", p.energy < st.energy.boost_j);
    this.energyText.textContent = `${Math.round(p.energy)} J${p.drainW ? `  -${Math.round(p.drainW)} W` : ""}`;
    const hf = Math.max(0, p.hp) / st.armour.hp;
    this.hp.style.width = `${(hf * 100).toFixed(1)}%`;
    this.hpText.textContent = `${Math.round(p.hp)} hp`;
    const v = Math.hypot(p.vx, p.vz);
    this.speed.innerHTML = `<b>${v.toFixed(1)}</b> m/s <small>${(v * 3.6).toFixed(0)} km/h</small>`;
    const lt = lapTime(sim);
    const lap = sim.lap;
    const cps = sim.level.checkpoints.length;
    this.timer.innerHTML =
      `<b>${lt == null ? "--.--" : lt.toFixed(2)}</b> s` +
      `<small>${lap.running ? `checkpoint ${lap.next}/${cps}` : "cross the start line"}` +
      `${lap.best != null ? ` · best ${lap.best.toFixed(2)}` : ""}</small>`;
    const last = sim.messages[sim.messages.length - 1];
    if (last !== this.lastMsg) {
      this.lastMsg = last;
      this.msgs.innerHTML = sim.messages
        .slice(-4)
        .map((m) => `<div class="${m.kind}">${this.fill(m.text)}</div>`)
        .join("");
    }
    for (const el of this.msgs.children) el.style.opacity = "1";
    if (last && sim.t - last.t > 5) this.msgs.style.opacity = "0.35";
    else this.msgs.style.opacity = "1";
    this.prompt.textContent = this.promptFor(sim);
    this.banner.hidden = !p.armsBroken;
  }

  // "{repair}" in a message becomes the key or button that repairs.
  fill(text) {
    return String(text).replace(/\{([\w:]+)\}/g, (all, k) => (k in this.labels ? esc(this.labels[k]) : all));
  }

  promptFor(sim) {
    const p = sim.player;
    const L = this.labels;
    if (p.held) return `Holding ${p.held.kg} kg: ${L.punch} to throw, ${L.use} to put down`;
    const best = nearestCrate(sim);
    if (best) return `${L.use}: lift ${best.kg} kg (your limit ${liftLimit(sim)} kg)`;
    return "";
  }
}
