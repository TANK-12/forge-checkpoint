/* Every setting, in one list. The Settings panel is built from it (simple
   ones always, advanced ones behind the toggle), numbers get a slider paired
   with a number field, and the game reads values by key. Adding a setting is
   one entry here. */

import { WEATHER } from "./weather.js";

export const SETTINGS = [
  { key: "volume", label: "Sound volume", kind: "range", min: 0, max: 100, step: 5, def: 60, unit: "%" },
  { key: "music", label: "Music volume", kind: "range", min: 0, max: 100, step: 5, def: 45, unit: "%" },
  { key: "weather", label: "Weather", kind: "choice", def: "changing",
    choices: { changing: "Changes as you ride", ...Object.fromEntries(Object.entries(WEATHER).map(([k, w]) => [k, w.label])) } },
  { key: "time", label: "Time of day", kind: "choice", def: "cycle",
    choices: { cycle: "Day and night cycle", dawn: "Always dawn", day: "Always day", dusk: "Always dusk", night: "Always night" } },
  { key: "day_minutes", label: "Length of a day", kind: "range", min: 1, max: 20, step: 1, def: 5, unit: "min" },
  { key: "strength", label: "Forge colour in the world", kind: "range", min: 0, max: 100, step: 5, def: 35, unit: "%" },
  { key: "quality", label: "Detail", kind: "choice", def: "high", choices: { high: "Full", low: "Lighter (fewer trees and effects)" } },
  { key: "aurora", label: "Northern lights at night", kind: "bool", def: true },
  { key: "forgiveness", label: "Landing forgiveness", kind: "range", min: 15, max: 85, step: 5, def: 45, unit: "°", advanced: true },
  { key: "flip_speed", label: "Flip speed", kind: "range", min: 3, max: 14, step: 0.5, def: 7.5, unit: "rad/s", advanced: true },
  { key: "jump", label: "Jump strength", kind: "range", min: 300, max: 1100, step: 20, def: 620, advanced: true },
  { key: "gravity", label: "Gravity", kind: "range", min: 700, max: 2600, step: 50, def: 1500, advanced: true },
  { key: "min_speed", label: "Slowest speed", kind: "range", min: 120, max: 600, step: 10, def: 280, advanced: true },
  { key: "max_speed", label: "Top speed", kind: "range", min: 600, max: 2000, step: 50, def: 1150, advanced: true },
  { key: "density", label: "Weather amount", kind: "range", min: 0, max: 200, step: 10, def: 100, unit: "%", advanced: true },
  { key: "zoom", label: "Camera zoom", kind: "range", min: 60, max: 160, step: 5, def: 100, unit: "%", advanced: true },
  { key: "shake", label: "Screen shake", kind: "bool", def: true, advanced: true },
  { key: "fps", label: "Show frame rate", kind: "bool", def: false },
  { key: "best_flag", label: "Flag at your best distance", kind: "bool", def: true },
  { key: "seed", label: "Mountain seed (0 for a new one each run)", kind: "range", min: 0, max: 99999, step: 1, def: 0, advanced: true },
];

export function defaults() {
  return Object.fromEntries(SETTINGS.map((s) => [s.key, s.def]));
}

export function clean(saved) {
  const out = defaults();
  for (const s of SETTINGS) {
    const v = saved && saved[s.key];
    if (v === undefined) continue;
    if (s.kind === "range" && Number.isFinite(Number(v))) out[s.key] = Math.min(s.max, Math.max(s.min, Number(v)));
    else if (s.kind === "choice" && v in s.choices) out[s.key] = v;
    else if (s.kind === "bool") out[s.key] = !!v;
  }
  return out;
}

// Build the form into `root`; onChange(key, value) fires on every edit.
export function buildForm(root, values, advanced, onChange) {
  root.textContent = "";
  for (const s of SETTINGS) {
    if (s.advanced && !advanced) continue;
    const row = document.createElement("label");
    row.className = "set-row";
    const name = document.createElement("span");
    name.textContent = s.label;
    row.appendChild(name);
    if (s.kind === "range") {
      const box = document.createElement("span");
      box.className = "pair";
      const slider = Object.assign(document.createElement("input"), { type: "range", min: s.min, max: s.max, step: s.step, value: values[s.key] });
      const num = Object.assign(document.createElement("input"), { type: "number", min: s.min, max: s.max, step: s.step, value: values[s.key] });
      const unit = document.createElement("em");
      unit.textContent = s.unit || "";
      slider.addEventListener("input", () => { num.value = slider.value; onChange(s.key, Number(slider.value)); });
      num.addEventListener("change", () => {
        const v = Math.min(s.max, Math.max(s.min, Number(num.value) || s.min));
        num.value = slider.value = String(v);
        onChange(s.key, v);
      });
      box.append(slider, num, unit);
      row.appendChild(box);
    } else if (s.kind === "choice") {
      const sel = document.createElement("select");
      for (const [k, label] of Object.entries(s.choices)) sel.appendChild(new Option(label, k, false, values[s.key] === k));
      sel.addEventListener("change", () => onChange(s.key, sel.value));
      row.appendChild(sel);
    } else {
      const box = Object.assign(document.createElement("input"), { type: "checkbox", checked: !!values[s.key] });
      box.addEventListener("change", () => onChange(s.key, box.checked));
      row.appendChild(box);
    }
    root.appendChild(row);
  }
}
