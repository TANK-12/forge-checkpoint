// Exo Lab page state, a tiny event bus, the API call, and the DOM, number
// and profile helpers the tester, the editor and the 3D view share.

export const S = {
  reg: null, // GET /api/registry: every data item, the knob map, profiles
  modelId: "exo_full",
  testId: "shoulder_rom",
  compareTo: "baseline",
  profileName: "baseline",
  profile: { name: "baseline", knobs: {}, overrides: {}, notes: "" },
  saved: "", // stable JSON of the profile as last loaded or saved
  model: null, // POST /api/model with the working profile
  modelFor: "", // profileKey() of the profile that model answered
  result: null, // POST /api/run
  derive: null, // POST /api/derive
  base: null, // the comparison run, model and game stats
  sub: 0, // motion index (motions) or pose row (hold)
  frames: [],
  frame: 0,
  poseMode: false,
  pose: { plane: 90, elev: 60, axial: 0, elbow: 30, payload_kg: 0 },
  poseFrame: null,
  advanced: false,
  tab: "parts",
  chart: "torque",
};

// Plain names for the shoulder motors (the core calls them J1 to J3): the
// first lifts the arm, the second swings it round, the third twists it.
export const MOTOR = { J1: "lift", J2: "swing", J3: "twist", elbow: "elbow" };
export const motorName = (key) => MOTOR[key] || key;
/** Card and issue text from the core in plain words: "J2" -> "swing motor". */
export function plain(text) {
  return String(text ?? "")
    .replace(/\bJ3 arm twist\b/g, "twist motor")
    .replace(/\bJ([123])\b/g, (_, n) => `${MOTOR[`J${n}`]} motor`);
}

const subs = new Map();
export function on(name, fn) {
  if (!subs.has(name)) subs.set(name, []);
  subs.get(name).push(fn);
}
export function emit(name, data) {
  for (const fn of subs.get(name) || []) fn(data);
}

export async function api(path, body, method) {
  const opt = { method: method || (body === undefined ? "GET" : "POST") };
  if (body !== undefined) {
    opt.headers = { "Content-Type": "application/json" };
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  let data = null;
  try {
    data = await r.json();
  } catch {
    data = null;
  }
  if (!r.ok) {
    const d = data && data.detail;
    throw new Error(typeof d === "string" ? d : `${r.status} ${r.statusText}`);
  }
  return data;
}

export const $ = (id) => document.getElementById(id);

export function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
    else if (k === "value") e.value = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(3)) {
    if (kid == null || kid === false) continue;
    e.append(kid instanceof Node ? kid : String(kid));
  }
  return e;
}

/** A number with sensible digits for its size; a dash for nothing. */
export function fmt(x, digits) {
  if (x == null || typeof x !== "number" || Number.isNaN(x)) return "–";
  const a = Math.abs(x);
  const d = digits ?? (a >= 100 ? 0 : a >= 10 ? 1 : a >= 1 ? 2 : a === 0 ? 0 : 3);
  return x.toFixed(d);
}

/** A number held to a range input's min, max and step the way the slider
 *  itself shows it (a tie goes to the larger step), so a typed value and
 *  its slider never disagree. Anything not a number gives min. */
export function snapToStep(x, min, max, step) {
  const lo = Number(min);
  const hi = Number(max);
  const st = Number(step) > 0 ? Number(step) : 0;
  let v = Math.min(hi, Math.max(lo, Number(x)));
  if (!Number.isFinite(v)) return lo;
  if (!st) return v;
  const dp = (n) => (String(n).split(".")[1] || "").length;
  v = Number((lo + Math.round((v - lo) / st) * st).toFixed(Math.max(dp(st), dp(lo))));
  return v > hi ? Number((v - st).toFixed(Math.max(dp(st), dp(lo)))) : v;
}

export const LEVEL_CSS = {
  pass: "var(--good)",
  warn: "var(--warn)",
  fail: "var(--bad)",
  out: "var(--muted)",
};
export const LEVEL_WORD = { pass: "pass", warn: "warning", fail: "fail" };

// Units by field-name ending, longest first, for labels and readouts.
const UNITS = [
  ["_kg_m3", "kg/m³"],
  ["_nm_rad", "N·m/rad"],
  ["_wh_kg", "Wh/kg"],
  ["_rad_s", "rad/s"],
  ["_n_per_mm", "N/mm"],
  ["_kgm2", "kg·m²"],
  ["_gpa", "GPa"],
  ["_mpa", "MPa"],
  ["_kpa", "kPa"],
  ["_deg", "°"],
  ["_kg", "kg"],
  ["_nm", "N·m"],
  ["_mm", "mm"],
  ["_wh", "Wh"],
  ["_w", "W"],
  ["_m", "m"],
  ["_n", "N"],
  ["_s", "s"],
  ["_pct", "%"],
];

/** "torque_cont_nm" -> ["Torque cont", "N·m"]. */
export function label(key) {
  const k = String(key);
  for (const [end, unit] of UNITS) {
    if (k.endsWith(end) && k.length > end.length) return [nice(k.slice(0, -end.length)), unit];
  }
  return [nice(k), ""];
}
function nice(k) {
  const s = k.replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ----- data paths and the effective item (mirrors exolab/registry.py) -----

/** A list position in a path: digits only, so "-1" is no position (as in Python). */
const idx = (k) => (/^\d+$/.test(k) ? Number(k) : -1);
const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

export function getPath(obj, path, dflt) {
  let cur = obj;
  for (const k of String(path).split(".")) {
    if (cur == null || typeof cur !== "object") return dflt;
    cur = Array.isArray(cur) ? cur[idx(k)] : cur[k];
    if (cur === undefined) return dflt;
  }
  return cur;
}

/** Set a dotted path; a path through a plain value or past a list's end is
 * stale and skipped, as registry.set_path does. */
export function setPath(obj, path, value) {
  const keys = String(path).split(".");
  let cur = obj;
  for (const k of keys.slice(0, -1)) {
    if (Array.isArray(cur)) cur = cur[idx(k)];
    else if (!own(cur, k)) cur = cur[k] = {};
    else cur = cur[k];
    if (cur == null || typeof cur !== "object") return;
  }
  const last = keys[keys.length - 1];
  if (!Array.isArray(cur)) cur[last] = value;
  else if (idx(last) >= 0 && idx(last) < cur.length) cur[idx(last)] = value;
}

/** The range a typed number must stay in (mirrors Registry.limit). */
export function limitOf(kind, path, old = 0) {
  const keys = String(path).split(".");
  for (const [pattern, rng] of Object.entries(S.reg?.limits?.[kind] || {})) {
    const pat = pattern.split(".");
    if (pat.length === keys.length && pat.every((p, i) => p === "*" || p === keys[i])) return [rng[0], rng[1]];
  }
  const span = 1000 * Math.max(Math.abs(old), 1);
  return [old >= 0 ? 0 : -span, span];
}

const clampKnob = (m) => (Number.isNaN(Number(m)) ? 1 : Math.min(20, Math.max(0.05, Number(m))));

export function knobVal(kind, id, knob) {
  const v = S.profile.knobs?.[kind]?.[id]?.[knob];
  return typeof v === "number" ? v : 1;
}

export function overrideVal(kind, id, path) {
  return S.profile.overrides?.[kind]?.[id]?.[path];
}

/** The item with the working profile's overrides, derived fields and knobs. */
/** The fields a knob scales on an item of this kind, each with the power
 *  the multiplier is raised to (data/knobs.json; a plain list means 1), as
 *  Registry.knob_fields. */
export function knobFields(kind, knob) {
  const got = S.reg?.knobs?.fields?.[kind]?.[knob] || [];
  return Array.isArray(got) ? got.map((f) => [f, 1]) : Object.entries(got);
}

/** An actuator with no motor (knobs.json "motorless" kinds): power has
 *  nothing to scale on it, so it takes no power knob. */
export function motorless(actId) {
  const kind = S.reg?.items?.actuators?.[actId]?.kind;
  return kind !== undefined && (S.reg?.knobs?.motorless || []).includes(kind);
}

/** The knobs a kind of suit part reads (knobs.json part_knobs). */
export function partKnobs(partKind) {
  return S.reg?.knobs?.part_knobs?.[partKind] || [];
}

/** The knobs an actuator type takes, as Registry.check_knobs: a motorless
 *  one only what its kind of drive reads (part_knobs, all but power for a
 *  kind not listed there), a motor all of them. */
export function actuatorKnobs(actId) {
  const all = Object.keys(S.reg?.knobs?.fields?.actuators || {});
  if (!motorless(actId)) return all;
  const listed = S.reg.knobs.part_knobs?.[S.reg.items.actuators[actId].kind];
  return (listed || all).filter((k) => k !== "power");
}

export function effective(kind, id, profile = S.profile) {
  const base = S.reg?.items?.[kind]?.[id];
  if (!base) return null;
  const item = structuredClone(base);
  const ov = profile.overrides?.[kind]?.[id] || {};
  for (const [p, v] of Object.entries(ov)) setPath(item, p, v);
  for (const [target, [src, factor]] of Object.entries(S.reg.knobs?.derived?.[kind] || {})) {
    if (!(target in item) && typeof item[src] === "number") item[target] = item[src] * factor;
  }
  const noMotor = kind === "actuators" && motorless(id);
  for (const [knob, mult] of Object.entries(profile.knobs?.[kind]?.[id] || {})) {
    if (knob === "power" && noMotor) continue;
    for (const [f, exp] of knobFields(kind, knob)) {
      if (f in ov) continue;
      if (typeof item[f] === "number") item[f] *= clampKnob(mult) ** exp;
    }
  }
  return item;
}

/** The kind that has an item with this id (for id-valued fields). */
/** The kind an id field points at (data/limits.json text.refs), as
 * Registry.id_kind: a link role "girdle" is not the human item "girdle". */
export function idKind(value) {
  if (typeof value !== "string") return null;
  const items = S.reg?.items || {};
  for (const kind of S.reg?.limits?.text?.refs || Object.keys(items)) {
    if (items[kind] && Object.hasOwn(items[kind], value)) return kind;
  }
  return null;
}

/** A text field that holds an id yet is no pick (limits.json text.fixed). */
export function fixedText(field) {
  return (S.reg?.limits?.text?.fixed || []).includes(field);
}

/** JSON with sorted keys, so two equal profiles compare equal. */
export function stable(o) {
  if (Array.isArray(o)) return `[${o.map(stable).join(",")}]`;
  if (o && typeof o === "object") {
    return `{${Object.keys(o)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${stable(o[k])}`)
      .join(",")}}`;
  }
  return JSON.stringify(o);
}

export function profileKey(p = S.profile) {
  return stable({ knobs: p.knobs || {}, overrides: p.overrides || {} });
}

export function toast(text, kind = "") {
  const box = $("toast");
  if (!box) return;
  box.textContent = text;
  box.className = `toast show ${kind}`;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (box.className = "toast"), 4200);
}
