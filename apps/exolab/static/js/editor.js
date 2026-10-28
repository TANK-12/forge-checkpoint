// The editor: the four relative knobs (stiffness, strength, weight, power)
// for every material, joint drive and suit part as log sliders, every
// absolute value in advanced mode, saved profiles with undo and redo, and a
// live re-run: each edit emits "profile", which the tester re-runs on
// (debounced). Readouts follow an edit at once (store.js ports the core's
// effective-value rule); part masses follow when the re-run's model arrives.

import { $, S, actuatorKnobs, api, effective, emit, fmt, fixedText, getPath, h, idKind, knobFields, label, limitOf, motorName, on, partKnobs, profileKey, toast } from "./store.js";
import { ashby } from "./charts.js";

const TABS = [
  ["materials", "Materials"],
  ["joints", "Joints"],
  ["parts", "Parts"],
  ["mechanism", "Mechanism"],
  ["human", "Human"],
  ["tests", "Tests"],
];
const KNOB_HELP = {
  stiffness: "Stiffer: bends and twists less under the same load.",
  strength: "Stronger: takes more stress or torque before it yields or slips.",
  weight: "Heavier: a denser material or a heavier part.",
  power:
    "A bigger motor: torque and top speed rise with the square root, rated power, mass and rotor inertia in full (x4 is twice the torque at four times the weight).",
};
// The battery's power knob is more cells, not a bigger motor.
const BATTERY_HELP = "More cells: more energy and more mass, in step.";
// A spring type's strength reaches only the arm joints that use it.
const SPRING_HELP = "Stronger: caps the spring's torque on an arm joint. A leg spring is weight only, so this changes nothing while only a leg uses it.";
function knobHelp(kind, id, knob) {
  if (knob === "power" && (kind === "power" || String(id).endsWith("/battery"))) return BATTERY_HELP;
  if (kind === "actuators" && knob === "strength" && S.reg.items.actuators?.[id]?.kind === "passive_spring") return SPRING_HELP;
  return KNOB_HELP[knob] || "";
}
// The knobs each kind of suit part reads (exolab/parts.py).
const LO = 0.05;
const HI = 20;
const LOG_HI = Math.log10(HI);
// Fields that describe an item rather than spec it.
const SKIP = new Set([
  "id",
  "name",
  "short",
  "about",
  "note",
  "notes",
  "source",
  "colour",
  "category",
  "kind",
  "status",
  "suit_asset",
  "shape",
  "order",
  "mechanism_overrides",
  "design_note",
]);
// Free-text fields with a fixed set of answers (data/limits.json text.choices);
// other free text names bones and roles, which only the data files change.
const choicesOf = (field) => S.reg?.limits?.text?.choices?.[field];
const SHORT = {
  youngs_modulus_gpa: "E",
  yield_strength_mpa: "yield",
  fatigue_strength_mpa: "fatigue",
  density_kg_m3: "density",
  torque_cont_nm: "continuous",
  torque_peak_nm: "peak",
  torque_limit_nm: "slips at",
  speed_max_rad_s: "top speed",
  power_cont_w: "rated",
  stiffness_nm_rad: "",
  mass_kg: "",
  remote_mass_kg: "remote",
};
const SECTION_LABEL = { d_mm: "Tube diameter", wall_mm: "Wall", w_mm: "Width", h_mm: "Height" };
const NAME_RE = /^[A-Za-z0-9](?:[A-Za-z0-9 _.-]{0,46}[A-Za-z0-9_-])?$/; // exolab/registry.py NAME_RE (pinned by a test)

let open = false;
let body = null;
let readers = [];
let builtFor = "";
let gen = 0; // bumps when many values change at once (load, undo, reset): the tab rebuilds
let active = null; // the input being edited right now; readers leave it alone
let hotMat = "";
let mechView = "";
const opened = new Set();
const closed = new Set();
const undoStack = [];
const redoStack = [];
let pending = null;
let pendTimer = 0;
const savedState = new Map(); // profile name -> {key, notes} as last loaded or saved

const clampK = (m) => Number(Math.min(HI, Math.max(LO, Number(m) || 1)).toPrecision(3));
const snapK = (m) => (Math.abs(Math.log10(m)) < 0.012 ? 1 : clampK(m));
const kfmt = (m) => (m >= 10 ? m.toFixed(1) : m.toFixed(2));
const fmtIn = (v) => (typeof v === "number" ? String(Number(v.toPrecision(6))) : v == null ? "" : String(v));

export function initEditor() {
  body = h("div", { class: "ed-body" });
  $("editor").replaceChildren(
    profileBar(),
    h(
      "div",
      { class: "tabs ed-tabs", id: "ed-tabs" },
      TABS.map(([id, name]) => h("button", { class: "tab", "data-tab": id, onclick: () => setTab(id) }, name, h("i", { class: "count" }))),
    ),
    h("div", { id: "ed-msg", class: "ed-msg small" }),
    body,
  );
  markSaved();
  fillProfiles();
  on("model", () => {
    dropStaleKnobs();
    render();
  });
  on("model-picked", () => {
    mechView = "";
    render();
  });
  on("test-picked", render);
  on("delta", showDelta);
  on("delta-start", () => {
    deltaRow = lastRow;
    deltaKey = lastKey;
  });
  on("profiles", fillProfiles);
  document.addEventListener("keydown", onKey);
  updateBar();
}

export function setEditorOpen(want) {
  open = !!want;
  $("editor").hidden = !open;
  render();
}

export const editorOpen = () => open;

export function setTab(id) {
  if (!TABS.some(([t]) => t === id) || id === S.tab) return;
  S.tab = id;
  render();
  emit("ui");
}

// ----- profiles, undo and redo -----

function profileBar() {
  return h(
    "div",
    { class: "ed-bar" },
    h(
      "div",
      { class: "ed-row" },
      h("select", {
        id: "ed-prof",
        title: "Saved profiles: named sets of edits. The baseline is the data as shipped and never changes.",
        onchange: (e) => loadProfile(e.target.value),
      }),
      h("span", { id: "ed-dirty", class: "chip" }),
      h("span", { class: "grow" }),
      h("button", { id: "ed-undo", title: "Undo (Ctrl+Z)", onclick: undo }, "Undo"),
      h("button", { id: "ed-redo", title: "Redo (Ctrl+Shift+Z or Ctrl+Y)", onclick: redo }, "Redo"),
    ),
    h(
      "div",
      { class: "ed-row" },
      h("button", { id: "ed-save", class: "primary", title: "Save (Ctrl+S)", onclick: save }, "Save"),
      h("button", { title: "Save these edits under a new name", onclick: () => showSaveAs(true) }, "Save as…"),
      h("button", { title: "Clear every edit (Undo brings them back)", onclick: resetAll }, "Reset all"),
      h("span", { class: "grow" }),
      h(
        "label",
        {
          class: "switch",
          title: "Advanced adds every absolute value: section sizes, axis angles, comfort limits, test settings.",
        },
        h("input", {
          type: "checkbox",
          id: "ed-adv",
          onchange: (e) => {
            S.advanced = e.target.checked;
            render();
          },
        }),
        " Advanced",
      ),
    ),
    h(
      "div",
      { class: "ed-row", id: "ed-saveas", hidden: true },
      h("input", {
        id: "ed-name",
        type: "text",
        placeholder: "New profile name",
        maxlength: 48,
        onkeydown: (e) => {
          if (e.key === "Enter") saveAs();
          else if (e.key === "Escape") showSaveAs(false);
        },
      }),
      h("button", { class: "primary", onclick: saveAs }, "Save"),
      h("button", { onclick: () => showSaveAs(false) }, "Cancel"),
    ),
    h(
      "details",
      { class: "ed-notes" },
      h("summary", {}, "Notes"),
      h("textarea", {
        id: "ed-notes",
        rows: 3,
        placeholder: "What this profile is for",
        oninput: (e) => {
          S.profile.notes = e.target.value;
          updateBar();
        },
      }),
    ),
  );
}

function fillProfiles() {
  const sel = $("ed-prof");
  if (!sel) return;
  const names = [...(S.reg?.profiles || ["baseline"])];
  if (!names.includes(S.profileName)) names.push(S.profileName);
  sel.replaceChildren(...names.map((n) => h("option", { value: n }, n === "baseline" ? "baseline (as shipped)" : n)));
  sel.value = S.profileName;
}

function markSaved() {
  S.saved = profileKey();
  savedState.set(S.profileName, { key: S.saved, notes: S.profile.notes || "" });
}

function isDirty() {
  const s = savedState.get(S.profileName);
  return !s || profileKey() !== s.key || (S.profile.notes || "") !== s.notes;
}

function snapshot() {
  return JSON.stringify({ name: S.profileName, profile: S.profile });
}

/** Change the working profile; a burst of changes (a slider drag) is one undo step. */
function edit(fn) {
  if (pending === null) pending = snapshot();
  S.profile.knobs ||= {};
  S.profile.overrides ||= {};
  fn(S.profile);
  prune(S.profile);
  clearTimeout(pendTimer);
  pendTimer = setTimeout(settle, 600);
  emit("profile", "edit");
  updateBar();
  if (open) runReaders();
}

function settle() {
  clearTimeout(pendTimer);
  if (pending !== null && pending !== snapshot()) {
    undoStack.push(pending);
    if (undoStack.length > 200) undoStack.shift();
    redoStack.length = 0;
  }
  pending = null;
  updateBar();
}

function undo() {
  settle();
  if (!undoStack.length) return;
  redoStack.push(snapshot());
  restore(undoStack.pop());
}

function redo() {
  settle();
  if (!redoStack.length) return;
  undoStack.push(snapshot());
  restore(redoStack.pop());
}

function restore(snap) {
  const o = JSON.parse(snap);
  const renamed = o.name !== S.profileName;
  S.profileName = o.name;
  S.profile = o.profile;
  S.saved = savedState.get(o.name)?.key ?? "";
  if (renamed) fillProfiles();
  gen += 1;
  render();
  emit("profile");
  updateBar();
}

function prune(p) {
  for (const top of ["knobs", "overrides"]) {
    if (!p[top] || typeof p[top] !== "object") p[top] = {};
    for (const [kind, items] of Object.entries(p[top])) {
      for (const [id, box] of Object.entries(items || {})) {
        if (!box || !Object.keys(box).length) delete items[id];
      }
      if (!items || !Object.keys(items).length) delete p[top][kind];
    }
  }
}

/** Drop the knobs nothing reads any more, so Save never meets one the
 *  server refuses: a part knob on a part its model no longer has or whose
 *  kind does not read it (J1 swapped for a free bearing loses its power
 *  knob, on every suit that shares the mechanism), and an actuator knob its
 *  type does not take. Runs on each model answer for the profile as it is
 *  now; no undo step of its own, so Undo of the swap brings the knobs back
 *  with the drive. */
function dropStaleKnobs() {
  const every = S.model?.part_knobs_of;
  if (!every || S.model.id !== S.modelId || S.modelFor !== profileKey()) return;
  const gone = [];
  const drop = (box, ok, what, tail = "") => {
    for (const k of Object.keys(box || {})) {
      if (ok.includes(k)) continue;
      delete box[k];
      gone.push(`${what} ${k}${tail}`);
    }
  };
  for (const [pk, box] of Object.entries(S.profile.knobs?.parts || {})) {
    const cut = pk.indexOf("/");
    const owner = cut < 0 ? pk : pk.slice(0, cut);
    const part = cut < 0 ? "" : pk.slice(cut + 1);
    const tail = owner === S.modelId ? "" : ` (${S.reg.items.models?.[owner]?.name || owner})`;
    drop(box, every[owner]?.[part] || [], part, tail);
  }
  for (const [id, box] of Object.entries(S.profile.knobs?.actuators || {})) {
    if (S.reg.items.actuators?.[id]) drop(box, actuatorKnobs(id), S.reg.items.actuators[id].name || id);
  }
  if (!gone.length) return;
  prune(S.profile);
  toast(`Dropped knobs nothing reads now: ${gone.join(", ")}.`);
  emit("profile", "stale");
  updateBar();
}

function setKnob(kind, id, knob, mult) {
  const m = clampK(mult);
  if (kind === "materials") hotMat = id;
  edit((p) => {
    const box = ((p.knobs[kind] ||= {})[id] ||= {});
    if (m === 1) delete box[knob];
    else box[knob] = m;
  });
}

/** An absolute value; undefined, or the value that is there anyway (dflt), clears it. */
function setOverride(kind, id, path, value, dflt) {
  if (kind === "materials") hotMat = id;
  edit((p) => {
    const box = ((p.overrides[kind] ||= {})[id] ||= {});
    if (value === undefined || value === dflt) delete box[path];
    else box[path] = value;
  });
}

async function loadProfile(name) {
  settle();
  let p;
  try {
    p = await api(`/api/profiles/${encodeURIComponent(name)}`);
  } catch (err) {
    toast(`Could not load ${name}: ${err.message}`, "bad");
    $("ed-prof").value = S.profileName;
    return;
  }
  undoStack.push(snapshot());
  redoStack.length = 0;
  S.profileName = name;
  S.profile = { name, knobs: p.knobs || {}, overrides: p.overrides || {}, notes: p.notes || "" };
  markSaved();
  fillProfiles();
  gen += 1;
  render();
  emit("profile");
  updateBar();
  toast(`Loaded ${name}; Undo goes back to the edits before it.`);
}

async function save() {
  if (S.profileName === "baseline") return showSaveAs(true);
  return put(S.profileName);
}

async function put(name) {
  settle();
  try {
    const res = await api(`/api/profiles/${encodeURIComponent(name)}`, { ...S.profile, name }, "PUT");
    S.reg.profiles = res.profiles;
    S.profileName = name;
    S.profile = {
      name,
      knobs: res.profile.knobs || {},
      overrides: res.profile.overrides || {},
      notes: res.profile.notes || "",
    };
    markSaved();
    fillProfiles();
    updateBar();
    emit("profiles");
    emit("saved", name);
    if (S.compareTo === name) emit("profile");
    toast(`Saved the profile ${name}.`, "good");
    return true;
  } catch (err) {
    toast(`Not saved: ${err.message}`, "bad");
    return false;
  }
}

function showSaveAs(show) {
  $("ed-saveas").hidden = !show;
  if (!show) return;
  const input = $("ed-name");
  input.value = S.profileName === "baseline" ? "" : `${S.profileName} copy`.slice(0, 48);
  input.focus();
  input.select();
}

async function saveAs() {
  const name = $("ed-name").value.trim();
  if (!NAME_RE.test(name)) {
    toast("A profile name starts with a letter or digit, then letters, digits, space, dot, dash or underscore (48 at most).", "bad");
    return;
  }
  if (name === "baseline") {
    toast("The baseline is read-only; pick another name.", "bad");
    return;
  }
  if ((S.reg.profiles || []).includes(name) && name !== S.profileName) {
    toast(`A profile named ${name} exists already: pick another name, or load it and save there.`, "bad");
    return;
  }
  if (await put(name)) showSaveAs(false);
}

function resetAll() {
  if (!Object.keys(S.profile.knobs || {}).length && !Object.keys(S.profile.overrides || {}).length) {
    toast("No edits to clear.");
    return;
  }
  touched(null);
  edit((p) => {
    p.knobs = {};
    p.overrides = {};
  });
  settle();
  gen += 1;
  render();
  toast("Every edit cleared; Undo brings them back.");
}

function resetItem(kind, id) {
  edit((p) => {
    delete p.knobs?.[kind]?.[id];
    delete p.overrides?.[kind]?.[id];
  });
  settle();
}

function resetModel(mid) {
  touched(null);
  edit((p) => {
    delete p.overrides?.models?.[mid];
    for (const k of Object.keys(p.knobs?.parts || {})) if (k.startsWith(`${mid}/`)) delete p.knobs.parts[k];
  });
  settle();
  gen += 1;
  render();
}

function onKey(e) {
  if (!open || !(e.ctrlKey || e.metaKey) || e.altKey) return;
  const k = String(e.key || "").toLowerCase();
  if (k === "s") {
    e.preventDefault();
    save();
    return;
  }
  const t = e.target;
  const typing =
    t && (t.tagName === "TEXTAREA" || t.isContentEditable || (t.tagName === "INPUT" && /^(text|search|number)$/.test(t.type)));
  if (typing) return; // text boxes keep their own undo (forge_undo.js)
  if (k === "z" && !e.shiftKey) undo();
  else if ((k === "z" && e.shiftKey) || (k === "y" && !e.shiftKey)) redo();
  else return;
  e.preventDefault();
}

// ----- drawing -----

function editCount(kind, id) {
  return (
    Object.keys(S.profile.knobs?.[kind]?.[id] || {}).length + Object.keys(S.profile.overrides?.[kind]?.[id] || {}).length
  );
}

function tabCount(tab) {
  const p = S.profile;
  const n = (top, kind, keep) =>
    Object.entries(p[top]?.[kind] || {})
      .filter(([id]) => !keep || keep(id))
      .reduce((a, [, box]) => a + Object.keys(box || {}).length, 0);
  if (tab === "materials") return n("knobs", "materials") + n("overrides", "materials");
  if (tab === "joints") return n("knobs", "actuators") + n("overrides", "actuators") + n("overrides", "power");
  if (tab === "parts")
    return n("knobs", "parts", (id) => id.startsWith(`${S.modelId}/`)) + n("overrides", "models", (id) => id === S.modelId);
  if (tab === "mechanism") return n("overrides", "mechanisms");
  if (tab === "human") return n("overrides", "human");
  if (tab === "tests") return n("overrides", "tests") + n("overrides", "motions");
  return 0;
}

function updateBar() {
  if (!$("ed-dirty")) return;
  const dirty = isDirty();
  const chip = $("ed-dirty");
  chip.textContent = dirty ? "unsaved edits" : S.profileName === "baseline" ? "as shipped" : "saved";
  chip.className = `chip lv-${dirty ? "warn" : "pass"}`;
  $("ed-undo").disabled = !undoStack.length && !(pending !== null && pending !== snapshot());
  $("ed-redo").disabled = !redoStack.length;
  $("ed-save").disabled = !dirty;
  $("ed-adv").checked = S.advanced;
  const notes = $("ed-notes");
  if (document.activeElement !== notes) notes.value = S.profile.notes || "";
  for (const b of $("ed-tabs").children) {
    b.classList.toggle("on", b.dataset.tab === S.tab);
    const n = tabCount(b.dataset.tab);
    b.querySelector(".count").textContent = n ? String(n) : "";
  }
}

function render() {
  updateBar();
  if (!open || !S.reg || !body) return;
  const key = `${S.tab}|${S.modelId}|${S.testId}|${S.advanced}|${gen}|${mechView}`;
  if (key !== builtFor) {
    builtFor = key;
    readers = [];
    const box = document.createDocumentFragment();
    (BUILD[S.tab] || BUILD.parts)(box);
    body.replaceChildren(box);
  }
  runReaders();
}

function runReaders() {
  for (const fn of readers) {
    try {
      fn();
    } catch (err) {
      console.error("editor readout failed", err);
    }
  }
  active = null;
}

function fold(key, head, opts, ...kids) {
  const d = h("details", { class: "fold" }, h("summary", {}, head), ...kids);
  d.open = opened.has(key) || (!!opts?.open && !closed.has(key));
  d.addEventListener("toggle", () => {
    if (d.open) {
      opened.add(key);
      closed.delete(key);
      if (opts?.onOpen) opts.onOpen();
    } else {
      closed.add(key);
      opened.delete(key);
    }
  });
  return d;
}

function unitOf(path) {
  const keys = path.split(".").filter((k) => !/^\d+$/.test(k));
  return label(keys[keys.length - 1] || "")[1];
}

/** "links.0.section.d_mm" -> "Back frame · Section · D". */
function pathLabel(item, path) {
  const out = [];
  let cur = item;
  for (const k of path.split(".")) {
    const list = Array.isArray(cur);
    const next = list ? cur[Number(k)] : cur?.[k];
    if (list) {
      const i = Number(k);
      if (next && typeof next === "object") out.push(next.name || next.id || `#${i + 1}`);
      else out.push(cur.length === 2 ? ["min", "max"][i] : cur.length === 3 ? ["x", "y", "z"][i] : `${i + 1}`);
    } else if (k !== "params") {
      out.push(label(k)[0]);
    }
    cur = next;
  }
  return out.join(" · ");
}

/** Every editable leaf of an item as a dotted path. */
function leafPaths(obj, prefix = "", out = []) {
  for (const [k, v] of Object.entries(obj || {})) {
    if (SKIP.has(k) || k.endsWith("_note")) continue;
    const p = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object") leafPaths(v, p, out);
    else if (typeof v !== "string" || k === "character" || choicesOf(k) || (idKind(v) && !fixedText(k))) out.push(p);
  }
  return out;
}

// The row whose knob or field was edited last: the chips saying what that
// edit did to the test's numbers go under it.
// A field row is found again by its title after a rebuild replaces it.
let lastRow = null;
let lastKey = "";
let deltaRow = null;
let deltaKey = "";

function touched(row) {
  if (lastRow && lastRow !== row) lastRow.querySelector(".k-delta")?.remove();
  lastRow = row;
  lastKey = row?.classList.contains("field") ? row.title : "";
}

/** Chips under the edited row: each number the edit moved, before -> after. */
function showDelta(d) {
  let row = deltaRow;
  if (!row?.isConnected && deltaKey) {
    row = [...document.querySelectorAll("#editor .field")].find((f) => f.title === deltaKey) || null;
    deltaRow = row;
  }
  for (const old of document.querySelectorAll("#editor .k-delta")) if (old.parentElement !== row) old.remove();
  if (!row?.isConnected) return;
  let box = row.querySelector(".k-delta");
  if (d == null) {
    box?.remove();
    return;
  }
  if (!box) row.append((box = h("div", { class: "k-delta" })));
  box.replaceChildren(
    ...(d.length
      ? d.map((c) => h("span", { class: c.good ? "up good" : "up bad", title: c.title, text: `${c.label} ${c.text}` }))
      : [h("span", { class: "muted", text: "no change in this test" })]),
  );
}

function knobRow(kind, id, knob, readout) {
  const get = () => {
    const v = S.profile.knobs?.[kind]?.[id]?.[knob];
    return typeof v === "number" ? v : 1;
  };
  const name = S.reg.knobs?.labels?.[knob] || knob;
  const slider = h("input", { type: "range", min: -LOG_HI, max: LOG_HI, step: 0.001, "aria-label": `${name} multiplier` });
  const num = h("input", { type: "number", class: "k-num", min: LO, max: HI, step: 0.05, "aria-label": `${name} multiplier` });
  const reset = h("button", { class: "mini", title: "Back to 1×" }, "↺");
  const out = h("div", { class: "k-out" });
  slider.addEventListener("input", () => {
    active = slider;
    const m = snapK(10 ** Number(slider.value));
    num.value = kfmt(m);
    touched(row);
    setKnob(kind, id, knob, m);
  });
  slider.addEventListener("dblclick", () => {
    touched(row);
    setKnob(kind, id, knob, 1);
  });
  num.addEventListener("change", () => {
    const m = clampK(Number(num.value) > 0 ? Number(num.value) : 1);
    num.value = kfmt(m);
    touched(row);
    setKnob(kind, id, knob, m);
  });
  reset.addEventListener("click", () => {
    touched(row);
    setKnob(kind, id, knob, 1);
  });
  const row = h(
    "div",
    { class: "knob" },
    h("span", { class: "k-name", title: knobHelp(kind, id, knob), text: name }),
    slider,
    h("span", { class: "k-in" }, num, h("i", { class: "unit", text: "×" })),
    reset,
    out,
  );
  readers.push(() => {
    const m = get();
    if (active !== slider) slider.value = String(Math.log10(m));
    if (document.activeElement !== num) num.value = kfmt(m);
    row.classList.toggle("edited", m !== 1);
    reset.style.visibility = m !== 1 ? "visible" : "hidden";
    out.textContent = readout ? readout() : "";
    out.hidden = !out.textContent;
  });
  return row;
}

/** What a knob scales on a data item, with the value it gives now. */
function knobText(kind, id, knob) {
  const eff = effective(kind, id);
  if (!eff) return "";
  return knobFields(kind, knob)
    .map(([f]) => f)
    .filter((f) => typeof eff[f] === "number")
    .map((f) => {
      const [nice, unit] = label(f);
      const word = SHORT[f] ?? nice.toLowerCase();
      return `${word ? `${word} ` : ""}${fmt(eff[f])}${unit ? ` ${unit}` : ""}`;
    })
    .join(" · ");
}

function knobNote(kind, id, path, own) {
  for (const knob of Object.keys(S.reg.knobs?.fields?.[kind] || {})) {
    if (!knobFields(kind, knob).some(([f]) => f === path)) continue;
    const m = S.profile.knobs?.[kind]?.[id]?.[knob];
    if (typeof m !== "number" || m === 1) continue;
    if (own) return `Your value replaces the ${knob} knob (×${kfmt(m)}) here.`;
    const eff = getPath(effective(kind, id), path);
    const unit = unitOf(path);
    return `The ${knob} knob (×${kfmt(m)}) makes it ${fmtIn(typeof eff === "number" ? Number(eff.toPrecision(4)) : eff)}${unit ? ` ${unit}` : ""}.`;
  }
  return "";
}

/** One absolute value: a number, a switch, or a pick from another kind. */
function fieldRow(kind, id, path, opts = {}) {
  const item = S.reg.items[kind]?.[id];
  if (!item) return null;
  const base = getPath(item, path);
  const dflt = opts.dflt !== undefined ? opts.dflt : base;
  if (dflt === undefined) return null;
  const last = path.split(".").pop();
  const ref = typeof dflt === "string" && !fixedText(last) ? (last === "character" ? "characters" : idKind(dflt)) : null;
  const choices = choicesOf(last);
  if (typeof dflt === "string" && !ref && !choices) return null;
  const own = () => {
    const o = S.profile.overrides?.[kind]?.[id];
    return o && Object.prototype.hasOwnProperty.call(o, path) ? { v: o[path] } : null;
  };
  const cur = () => own()?.v ?? dflt;
  let input;
  const commit = (v) => {
    active = input;
    touched(input.closest(".field") || input.parentElement);
    setOverride(kind, id, path, v, dflt);
    if (opts.rebuild) {
      gen += 1;
      render();
    }
  };
  if (typeof dflt === "boolean") {
    input = h("input", { type: "checkbox", onchange: () => commit(input.checked) });
  } else if (ref || choices) {
    const ids = choices || (ref === "characters" ? S.reg.characters || [] : Object.keys(S.reg.items[ref] || {}));
    const nice = (i) => (ref && ref !== "characters" ? S.reg.items[ref][i]?.name || i : i);
    input = h("select", { onchange: () => commit(input.value) }, ids.map((i) => h("option", { value: i }, nice(i))));
  } else {
    const [lo, hi] = limitOf(kind, path, typeof dflt === "number" ? dflt : 0);
    input = h("input", {
      type: "number",
      step: "any",
      min: lo,
      max: hi,
      placeholder: dflt === null ? "auto" : "",
      onchange: () => {
        const t = input.value.trim();
        if (t === "") return commit(undefined);
        const v = Number(t);
        if (!Number.isFinite(v)) {
          input.value = fmtIn(cur());
          return;
        }
        if (v < lo || v > hi) {
          const c = Math.min(hi, Math.max(lo, v));
          toast(`This field stays between ${fmtIn(lo)} and ${fmtIn(hi)}, so it is ${fmtIn(c)}`);
          input.value = fmtIn(c);
          return commit(c);
        }
        commit(v);
      },
    });
  }
  const unit = unitOf(path);
  const reset = h(
    "button",
    {
      class: "mini",
      title: `Back to ${dflt === null ? "auto" : fmtIn(ref ? S.reg.items[ref]?.[dflt]?.name || dflt : dflt)}`,
      onclick: () => {
        touched(reset.closest(".field"));
        setOverride(kind, id, path, undefined);
        if (opts.rebuild) {
          gen += 1;
          render();
        }
      },
    },
    "↺",
  );
  const note = h("div", { class: "f-note" });
  const row = h(
    "div",
    { class: "field", title: `${kind}/${id}: ${path}` },
    h("span", { class: "f-name", text: opts.label || pathLabel(item, path) }),
    h("span", { class: "f-in" }, input, unit ? h("i", { class: "unit", text: unit }) : null),
    reset,
    note,
  );
  readers.push(() => {
    const o = own();
    const v = cur();
    if (active !== input && document.activeElement !== input) {
      if (input.type === "checkbox") input.checked = !!v;
      else if (input.tagName === "SELECT") input.value = v;
      else input.value = fmtIn(v);
    }
    row.classList.toggle("edited", !!o);
    reset.style.visibility = o ? "visible" : "hidden";
    note.textContent = opts.note ? opts.note() : knobNote(kind, id, path, o);
    note.hidden = !note.textContent;
  });
  return row;
}

/** A data item: its knobs, and its absolute values in advanced mode (or
 *  always, for kinds without knobs). */
function itemFold(kind, id, { tag = null, openDefault = false, keep = null } = {}) {
  const item = S.reg.items[kind]?.[id];
  if (!item) return null;
  // A passive actuator takes only the knobs its drive reads (check_knobs refuses the rest).
  const knobs = kind === "actuators" ? actuatorKnobs(id) : Object.keys(S.reg.knobs?.fields?.[kind] || {});
  const dot = h("i", { class: "dot", title: "edited" });
  const tagEl = h("span", { class: "tag" });
  const reset = h(
    "button",
    {
      class: "mini",
      title: "Clear this item's edits",
      onclick: (e) => {
        e.preventDefault();
        e.stopPropagation();
        touched(reset.closest(".fold"));
        resetItem(kind, id);
      },
    },
    "Reset",
  );
  const kids = [];
  const about = item.note || item.about;
  if (about) kids.push(h("p", { class: "muted small", text: about }));
  for (const k of knobs) kids.push(knobRow(kind, id, k, () => knobText(kind, id, k)));
  if (S.advanced || !knobs.length) {
    const rows = leafPaths(item)
      .filter((p) => !keep || keep(p))
      .map((p) => fieldRow(kind, id, p))
      .filter(Boolean);
    if (rows.length && knobs.length) {
      kids.push(h("div", { class: "sub-h", text: "Absolute values: a value typed here replaces the baseline, and its knob no longer applies to it." }));
    }
    kids.push(...rows);
  }
  if (S.advanced && item.source) kids.push(h("p", { class: "muted small src", text: `Source: ${item.source}` }));
  readers.push(() => {
    const n = editCount(kind, id);
    dot.hidden = !n;
    reset.hidden = !n;
    const t = typeof tag === "function" ? tag() : tag;
    tagEl.textContent = t?.text || "";
    tagEl.title = t?.title || "";
    tagEl.hidden = !t?.text;
  });
  const head = [h("b", { text: item.name || id }), tagEl, dot, h("span", { class: "grow" }), reset];
  return fold(`${kind}/${id}`, head, { open: openDefault }, ...kids);
}

function suitNow() {
  return S.model && S.model.id === S.modelId ? S.model.suit : null;
}

/** A suit part: its own fields, its own knobs (knobs.parts["model/part"]).
 *  `allowed` says which of those knobs the part reads now (a drive swapped
 *  for a passive one loses its power knob). */
function partFold(key, title, fields, knobs, read, allowed = null) {
  const pk = `${S.modelId}/${key}`;
  const out = h("span", { class: "p-out" });
  const dot = h("i", { class: "dot", title: "edited" });
  const kids = fields.filter(Boolean);
  const rows = knobs.map((k) => [k, knobRow("parts", pk, k, null)]);
  if (rows.length) {
    kids.push(h("div", { class: "sub-h", text: "Knobs for this part only" }), ...rows.map(([, r]) => r));
  }
  const d = fold(`part/${pk}`, [h("b", { text: title }), dot, h("span", { class: "grow" }), out], { open: false }, ...kids);
  readers.push(() => {
    if (allowed) {
      const now = allowed();
      for (const [k, r] of rows) r.hidden = !now.includes(k);
    }
    out.textContent = read ? read() : "";
    dot.hidden = !d.querySelector(".field.edited, .knob.edited");
  });
  return d;
}

/** The knobs this part of the open model reads now, as the server says
 *  (/api/model part_knobs), or null before that answer is in. */
function partKnobsNow(key) {
  return S.model && S.model.id === S.modelId ? S.model.part_knobs?.[key] || null : null;
}

/** "J1", "J1 flexion" -> "Lift motor · flexion". */
function motorTitle(key, name) {
  const m = motorName(key);
  const rest = String(name || "").replace(/^J[123]\s*/, "");
  return `${m[0].toUpperCase()}${m.slice(1)} motor${rest ? ` · ${rest}` : ""}`;
}

function jointFold(key, title, fields) {
  return partFold(key, title, fields, partKnobs("drive"), () => {
    const j = suitNow()?.joints?.find((x) => x.key === key);
    if (!j) return "";
    const drive = S.reg.items.actuators?.[j.actuator]?.name || j.actuator;
    return j.powered
      ? `${fmt(j.torque_cont_nm)} N·m · ${fmt(j.speed_max_rad_s)} rad/s · ${fmt(j.mass_kg, 2)} kg`
      : `${drive.split(" (")[0]}, unpowered · ${fmt(j.mass_kg, 2)} kg`;
  }, () => partKnobsNow(key) || partKnobs("drive"));
}

/** What the open model uses for a mechanism field before any profile edit. */
function mechDefault(mechId, path) {
  const sh = effective("models", S.modelId)?.shoulder;
  const mo = sh?.mechanism_overrides?.[mechId] || {};
  return Object.prototype.hasOwnProperty.call(mo, path) ? mo[path] : getPath(S.reg.items.mechanisms?.[mechId], path);
}

function usedMaterials() {
  const m = effective("models", S.modelId);
  const out = new Map();
  const add = (id, what) => {
    if (!id) return;
    if (!out.has(id)) out.set(id, []);
    out.get(id).push(what);
  };
  for (const l of m?.links || []) add(l.material, l.name);
  for (const c of m?.cuffs || []) add(c.material, c.name);
  for (const s of m?.shells || []) add(s.material, s.name);
  if (m?.legs?.strut_material) add(m.legs.strut_material, "Leg struts");
  return out;
}

function drawAshby(canvas) {
  const pt = (m) => [(m.youngs_modulus_gpa * 1e3) / m.density_kg_m3, (m.yield_strength_mpa * 1e3) / m.density_kg_m3];
  const ok = (p) => p.every((x) => Number.isFinite(x) && x > 0);
  const mats = Object.entries(S.reg.items.materials || {})
    .filter(([, m]) => ok(pt(m)))
    .map(([id, m]) => {
      const now = pt(effective("materials", id));
      return { base: pt(m), now: ok(now) ? now : pt(m), colour: m.colour || "#8b93a3", short: m.short || m.name, hot: id === hotMat };
    });
  if (mats.length) ashby(canvas, mats);
}

// ----- the tabs -----

const BUILD = {
  materials(box) {
    const used = usedMaterials();
    const canvas = h("canvas", { class: "ashby" });
    const draw = () => {
      if (canvas.isConnected && canvas.clientWidth) drawAshby(canvas);
    };
    readers.push(draw);
    box.append(
      fold(
        "chart/ashby",
        [h("b", { text: "Materials chart" })],
        { open: true, onOpen: draw },
        canvas,
        h("p", {
          class: "muted small",
          text: "Stiffness and strength per kilogram, on log scales: up and to the right makes a lighter suit for the same job. A ring is the baseline, a dot your edit; the outlined dot is the one you touched last.",
        }),
      ),
    );
    const mats = S.reg.items.materials || {};
    const ids = Object.keys(mats).sort(
      (a, b) => (used.has(a) ? 0 : 1) - (used.has(b) ? 0 : 1) || mats[a].name.localeCompare(mats[b].name),
    );
    for (const id of ids) {
      const tag = () => {
        const u = usedMaterials().get(id);
        return u ? { text: `in ${u.length} part${u.length > 1 ? "s" : ""}`, title: u.join(", ") } : { text: mats[id].category || "" };
      };
      box.append(itemFold("materials", id, { tag }));
    }
  },

  joints(box) {
    box.append(
      h("p", {
        class: "muted small",
        text: "A drive is the motor and gear (or the spring, cable or bearing) at a joint. Its knobs change it everywhere it is used; one joint's own knobs are on the Parts tab.",
      }),
    );
    const usedBy = () => {
      const out = new Map();
      for (const j of suitNow()?.joints || []) {
        if (!out.has(j.actuator)) out.set(j.actuator, []);
        out.get(j.actuator).push(j.key);
      }
      return out;
    };
    const used = usedBy();
    const acts = S.reg.items.actuators || {};
    const ids = Object.keys(acts).sort(
      (a, b) => (used.has(a) ? 0 : 1) - (used.has(b) ? 0 : 1) || acts[a].name.localeCompare(acts[b].name),
    );
    for (const id of ids) {
      const tag = () => {
        const u = usedBy().get(id);
        return u ? { text: u.map(motorName).join(" "), title: "Motors of this model that use it" } : null;
      };
      box.append(itemFold("actuators", id, { tag }));
    }
    const cells = Object.keys(S.reg.items.power || {});
    if (cells.length) {
      box.append(h("h4", { text: "Battery cells" }));
      for (const id of cells) box.append(itemFold("power", id, {}));
    }
  },

  parts(box) {
    const mid = S.modelId;
    const m = effective("models", mid);
    const base = S.reg.items.models?.[mid];
    if (!m || !base) return;
    const total = h("span", { class: "muted" });
    const resetBtn = h("button", { class: "mini", title: "Clear this model's part edits", onclick: () => resetModel(mid) }, "Reset");
    readers.push(() => {
      const s = suitNow();
      total.textContent = s ? `${fmt(s.total_kg, 1)} kg in all · battery ${fmt(s.battery_wh, 0)} Wh` : "";
      resetBtn.hidden = !tabCount("parts");
    });
    box.append(h("div", { class: "ed-head" }, h("b", { text: m.name }), total, h("span", { class: "grow" }), resetBtn));
    if (m.status !== "ready") {
      box.append(
        h("p", {
          class: "muted",
          text: `${m.name} is planned, not built yet. Its specs are open in Advanced; its tests come with its chunk of the plan.`,
        }),
      );
      if (S.advanced) box.append(itemFold("models", mid, { openDefault: true }));
      return;
    }

    const mechId = m.shoulder?.mechanism;
    const mech = effective("mechanisms", mechId);
    const joints = (mech?.joints || []).map((j, i) =>
      jointFold(`J${i + 1}`, motorTitle(`J${i + 1}`, j.name), [
        fieldRow("mechanisms", mechId, `joints.${i}.actuator`, { label: "Drive", dflt: mechDefault(mechId, `joints.${i}.actuator`) }),
      ]),
    );
    box.append(
      fold(
        `parts/${mid}/shoulder`,
        [h("b", { text: "Shoulder" }), h("span", { class: "muted", text: mech?.name || "" })],
        { open: true },
        fieldRow("models", mid, "shoulder.mechanism", { label: "Mechanism", rebuild: true }),
        fieldRow("models", mid, "shoulder.assist_share", {
          label: "Share of the arm the suit holds",
          note: () => "0 to 1: how much of your own arm's weight the suit carries.",
        }),
        ...joints,
        h("p", {
          class: "muted small",
          text: `The three shoulder drives belong to the ${mech?.name || "mechanism"}: a drive picked here applies to every model that uses it. The Mechanism tab has its geometry.`,
        }),
      ),
    );

    const limbs = [jointFold("elbow", "Elbow", [fieldRow("models", mid, "elbow.actuator", { label: "Drive" })])];
    for (const leg of ["hip", "knee"]) {
      if (base.legs?.[leg]?.actuator) {
        limbs.push(jointFold(leg, leg === "hip" ? "Hip" : "Knee", [fieldRow("models", mid, `legs.${leg}.actuator`, { label: "Drive" })]));
      }
    }
    box.append(fold(`parts/${mid}/limbs`, [h("b", { text: "Elbow and leg drives" })], { open: true }, ...limbs));

    const links = (base.links || []).map((l, i) =>
      partFold(
        l.id,
        l.name,
        [
          fieldRow("models", mid, `links.${i}.material`, { label: "Material" }),
          ...Object.keys(l.section || {})
            .filter((k) => k !== "shape")
            .map((k) => fieldRow("models", mid, `links.${i}.section.${k}`, { label: SECTION_LABEL[k] || label(k)[0] })),
          l.length_m != null ? fieldRow("models", mid, `links.${i}.length_m`, { label: "Length" }) : null,
          S.advanced && l.side_offset_mm != null
            ? fieldRow("models", mid, `links.${i}.side_offset_mm`, { label: "Offset from the limb" })
            : null,
        ],
        partKnobs("link"),
        () => {
          const s = suitNow()?.links?.find((x) => x.id === l.id);
          return s ? `${fmt(s.mass_kg, 2)} kg · ${s.shape === "tube" ? "Ø" : ""}${fmt(s.outer_mm, 0)} mm · yield ${fmt(s.yield_mpa, 0)} MPa` : "";
        },
      ),
    );
    box.append(fold(`parts/${mid}/links`, [h("b", { text: "Struts and frame" })], { open: true }, ...links));

    const cuffs = (base.cuffs || []).map((c, i) =>
      partFold(
        c.id,
        c.name,
        [
          fieldRow("models", mid, `cuffs.${i}.width_mm`, { label: "Width" }),
          fieldRow("models", mid, `cuffs.${i}.gap_mm`, { label: "Gap to the limb" }),
          fieldRow("models", mid, `cuffs.${i}.thickness_mm`, { label: "Thickness" }),
          fieldRow("models", mid, `cuffs.${i}.material`, { label: "Shell" }),
          c.liner
            ? h("p", { class: "muted small", text: `Liner: ${S.reg.items.materials?.[c.liner]?.name || c.liner} · comfort only, not modelled` })
            : null,
          S.advanced ? fieldRow("models", mid, `cuffs.${i}.at`, { label: "Where along the limb (0 to 1)" }) : null,
        ],
        partKnobs("cuff"),
        () => {
          const s = suitNow()?.cuffs?.find((x) => x.id === c.id);
          return s ? `${fmt(s.area_cm2, 0)} cm² · ${fmt(s.mass_kg, 2)} kg` : "";
        },
      ),
    );
    if (cuffs.length) box.append(fold(`parts/${mid}/cuffs`, [h("b", { text: "Cuffs and straps" })], { open: true }, ...cuffs));

    const shells = (base.shells || []).map((s, i) =>
      partFold(
        s.id,
        s.mirror ? `${s.name} (pair)` : s.name,
        [
          fieldRow("models", mid, `shells.${i}.material`, { label: "Material" }),
          fieldRow("models", mid, `shells.${i}.thickness_mm`, { label: "Thickness" }),
          S.advanced
            ? fieldRow("models", mid, `shells.${i}.fit_gap_mm`, {
                label: "Gap to the body",
                note: () => "Used when the suit is built in Blender; the tests do not read it.",
              })
            : null,
          S.advanced ? fieldRow("models", mid, `shells.${i}.area_m2`, { label: "Area if not measured" }) : null,
        ],
        partKnobs("shell"),
        () => {
          const x = suitNow()?.shells?.find((y) => y.id === s.id);
          return x ? `${fmt(x.mass_kg, 2)} kg` : "";
        },
      ),
    );
    if (shells.length) {
      box.append(fold(`parts/${mid}/shells`, [h("b", { text: "Shells" }), h("span", { class: "muted", text: `${shells.length}` })], {}, ...shells));
    }

    const extra = [];
    if (base.battery) {
      extra.push(
        partFold(
          "battery",
          "Battery",
          [fieldRow("models", mid, "battery.mass_kg", { label: "Pack mass" }), fieldRow("models", mid, "battery.power", { label: "Cells" })],
          partKnobs("battery"),
          () => {
            const s = suitNow();
            return s ? `${fmt(s.battery_wh, 0)} Wh` : "";
          },
        ),
      );
    }
    if (typeof base.hand_grip === "boolean") {
      extra.push(
        fieldRow("models", mid, "hand_grip", { label: "Load-bearing gauntlets", note: () => base.hand_grip_note || "" }),
      );
    }
    if (S.advanced) {
      for (const k of Object.keys(base.extras_mass_kg || {})) {
        extra.push(fieldRow("models", mid, `extras_mass_kg.${k}`, { label: k.charAt(0).toUpperCase() + k.slice(1) }));
      }
    }
    if (extra.length) box.append(fold(`parts/${mid}/power`, [h("b", { text: "Battery and the rest" })], { open: true }, ...extra));
    if (S.advanced) box.append(itemFold("models", mid, {}));
  },

  mechanism(box) {
    const mine = effective("models", S.modelId)?.shoulder?.mechanism;
    const mechs = S.reg.items.mechanisms || {};
    const ids = Object.keys(mechs);
    const id = ids.includes(mechView) ? mechView : ids.includes(mine) ? mine : ids[0];
    if (!id) return;
    const sel = h(
      "select",
      {
        onchange: () => {
          mechView = sel.value;
          render();
        },
      },
      ids.map((i) => h("option", { value: i }, `${mechs[i].name}${i === mine ? " (this model)" : ""}`)),
    );
    sel.value = id;
    box.append(h("div", { class: "ed-row" }, h("span", { class: "muted", text: "Mechanism" }), sel));
    const item = mechs[id];
    if (item.about) box.append(h("p", { class: "muted small", text: item.about }));
    if (item.design_note) box.append(h("p", { class: "muted small", text: item.design_note }));
    const model = effective("models", S.modelId);
    const mo = model?.shoulder?.mechanism_overrides?.[id] || {};
    if (Object.keys(mo).length) {
      const said = Object.entries(mo).map(([p, v]) => `${pathLabel(item, p)}: ${S.reg.items.actuators?.[v]?.name || v}`);
      box.append(h("p", { class: "muted small", text: `${model.name} changes these for itself: ${said.join("; ")}.` }));
    }
    if (id !== mine) {
      box.append(h("p", { class: "small lv-t-warn", text: "Not the open model's mechanism: edits here reach the models that use it." }));
    }
    const groups = new Map();
    for (const p of leafPaths(item)) {
      const g = p.includes(".") ? p.split(".")[0] : "";
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(p);
    }
    for (const [g, paths] of groups) {
      const rows = paths.map((p) => fieldRow("mechanisms", id, p, { dflt: Object.prototype.hasOwnProperty.call(mo, p) ? mo[p] : undefined }));
      box.append(fold(`mech/${id}/${g}`, [h("b", { text: g ? label(g)[0] : "Layout" })], { open: true }, ...rows));
    }
  },

  human(box) {
    const items = S.reg.items.human || {};
    const simple = ["subject", "comfort"];
    const ids = Object.keys(items).sort((a, b) => (simple.includes(a) ? simple.indexOf(a) : 9) - (simple.includes(b) ? simple.indexOf(b) : 9));
    for (const id of ids) {
      if (!S.advanced && !simple.includes(id)) continue;
      box.append(itemFold("human", id, { openDefault: id === "subject" }));
    }
    if (!S.advanced) {
      box.append(
        h("p", {
          class: "muted small",
          text: "Advanced adds the shoulder girdle motion, the range of motion envelope and the body segment table.",
        }),
      );
    }
  },

  tests(box) {
    const tests = S.reg.items.tests || {};
    const ids = Object.keys(tests).sort(
      (a, b) => (a === S.testId ? -1 : b === S.testId ? 1 : (tests[a].order ?? 99) - (tests[b].order ?? 99)),
    );
    for (const id of ids) {
      if (!S.advanced && id !== S.testId) continue;
      box.append(itemFold("tests", id, { openDefault: id === S.testId, tag: id === S.testId ? { text: "open test" } : null }));
    }
    if (S.advanced || tests[S.testId]?.kind === "motions") {
      box.append(h("h4", { text: "Motions" }));
      for (const id of Object.keys(S.reg.items.motions || {})) box.append(itemFold("motions", id, {}));
    }
    if (!S.advanced) {
      box.append(h("p", { class: "muted small", text: "Advanced adds the other tests and every motion's key poses." }));
    }
  },
};
