// The real-world tester: runs a bench test on the working profile, shows
// the verdict, cards, comparison, range map or charts, game stats and the
// part table, and plays the frames in the 3D view. Edits re-run it live.

import { $, LEVEL_CSS, MOTOR, S, api, emit, fmt, h, motorName, on, plain, profileKey, snapToStep, toast } from "./store.js";
import { lineChart, romMap } from "./charts.js";
import { jointLevel, kpaLevel, safetyLevel } from "./view3d.js";

const JCOL = { J1: "#ffb454", J2: "#8ee06e", J3: "#6ab8ff", elbow: "#d58cff" };
const CHARTS = [
  ["torque", "Motor torque"],
  ["speed", "Joint speed"],
  ["pressure", "Strap pressure"],
  ["misalign", "Misalignment"],
  ["you", "You carry"],
  ["power", "Motor power"],
];
const TILE_CODES = {
  misalign: ["misalign"],
  lock: ["lock"],
  joints: ["limit", "clash"],
  motors: ["torque", "speed", "unpowered", "cable"],
  straps: ["pressure"],
  struts: ["break"],
  fit: ["fit"],
  overlap: ["overlap"],
};
// Tests whose result is a list of motions, each with its own frames.
const MOTION_KINDS = ["motions", "close_fit"];

let view = null;
let seq = 0;
let timer = 0;
let playing = false;
let looping = false; // a playback frame is queued
let playT = 0;
let lastTs = 0;
let pick = null;
let poseBusy = false;
let poseAgain = false;
const compareCache = new Map();
let sortCol = "mass";
let sortDir = -1;
let fromEdit = false;
// A re-run the editor asks for after its own edit (dropping knobs nothing
// reads now) keeps that edit's before-numbers.
let carry = false;
let carryWas = null;
let resultFor = ""; // model|test of S.result: chips never compare two tests

export function initTester(v) {
  view = v;
  $("sel-model").addEventListener("change", (e) => {
    if (S.poseMode) setPoseMode(false);
    S.modelId = e.target.value;
    S.sub = 0;
    emit("model-picked");
    refresh();
  });
  $("sel-test").addEventListener("change", (e) => {
    S.testId = e.target.value;
    S.sub = 0;
    emit("test-picked");
    refresh();
  });
  $("sel-compare").addEventListener("change", (e) => {
    S.compareTo = e.target.value;
    refresh();
  });
  $("btn-run").addEventListener("click", () => refresh());
  $("btn-report").addEventListener("click", saveReport);
  $("btn-play").addEventListener("click", () => setPlaying(!playing));
  $("btn-worst").addEventListener("click", () => goFrame(worstIndex(S.frames)));
  document.addEventListener("keydown", playKeys);
  $("scrub").addEventListener("input", (e) => {
    setPlaying(false);
    showFrame(Number(e.target.value));
  });
  $("btn-pose").addEventListener("click", () => setPoseMode(!S.poseMode));
  for (const k of POSE_KEYS) {
    const slider = $(`pose-${k}`);
    const num = $(`pose-${k}-v`);
    slider.addEventListener("input", () => setPoseValue(k, slider.value));
    // A typed number moves the arm as it is typed; an empty or half-typed
    // field ("-") waits, and leaving the field shows the value in use (a
    // number past the slider's ends is held at the end).
    num.addEventListener("input", () => {
      if (num.value.trim() !== "" && Number.isFinite(Number(num.value))) setPoseValue(k, num.value, num);
    });
    num.addEventListener("change", () => (num.value = String(S.pose[k])));
  }
  const tabs = $("chart-tabs");
  for (const [id, name] of CHARTS) {
    tabs.append(
      h("button", {
        class: "tab",
        "data-id": id,
        text: name,
        onclick: () => {
          S.chart = id;
          drawChart();
        },
      }),
    );
  }
  for (const b of document.querySelectorAll("[data-cam]")) {
    b.addEventListener("click", () => view.setCamera(b.dataset.cam));
  }
  for (const b of document.querySelectorAll("[data-layer]")) {
    b.addEventListener("change", () => view.setLayer(b.dataset.layer, b.checked));
  }
  const map = $("rom-map");
  map.addEventListener("mousemove", (e) => {
    const c = pick && pick(e.offsetX, e.offsetY);
    $("map-tip").textContent = c ? cellText(c) : "Point at a cell; click to try that pose.";
  });
  map.addEventListener("click", (e) => {
    const c = pick && pick(e.offsetX, e.offsetY);
    if (!c || c.level === "out") return;
    Object.assign(S.pose, { plane: c.plane, elev: c.elev, axial: 0, elbow: S.result?.map?.elbow ?? 30 });
    setPoseMode(true);
  });
  $("parts").addEventListener("click", (e) => {
    const th = e.target.closest("th[data-sort]");
    if (!th) return;
    if (sortCol === th.dataset.sort) sortDir = -sortDir;
    else (sortCol = th.dataset.sort), (sortDir = -1);
    renderParts();
  });
  on("profile", schedule);
  on("saved", (name) => {
    for (const k of [...compareCache.keys()]) if (k.includes(`|${name}|`)) compareCache.delete(k);
  });
  window.addEventListener("resize", () => {
    drawChart();
    drawMap();
  });
}

// Playback from the keyboard while the tester is open: Space plays or
// pauses, the arrows step a frame (with Shift ten), Home and End go to the
// ends, W to the worst frame. Keys typed into a field, a slider, a list, a
// focused button, link or fold header (Space opens an editor fold) stay
// theirs.
const OWN_KEYS = "input, select, textarea, button, summary, a[href], [contenteditable]";
function playKeys(e) {
  if ($("tester").hidden || $("playbar").hidden || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.target instanceof Element && e.target.closest(OWN_KEYS)) return;
  if (!S.frames.length) return;
  const last = S.frames.length - 1;
  const by = e.shiftKey ? 10 : 1;
  if (e.key === " ") {
    if ($("btn-play").disabled) return;
    setPlaying(!playing);
  } else if (e.key === "ArrowLeft") goFrame(S.frame - by);
  else if (e.key === "ArrowRight") goFrame(S.frame + by);
  else if (e.key === "Home") goFrame(0);
  else if (e.key === "End") goFrame(last);
  else if (e.key === "w" || e.key === "W") goFrame(worstIndex(S.frames));
  else return;
  e.preventDefault();
}

// Go to a frame from the playbar or the keyboard: playback and pose mode
// stop, and on the hold test the pose row follows.
function goFrame(i) {
  if (!S.frames.length) return;
  setPlaying(false);
  if (S.poseMode) setPoseMode(false);
  const n = Math.max(0, Math.min(S.frames.length - 1, i | 0));
  showFrame(n);
  if (S.result?.kind === "hold" && S.sub !== n) {
    S.sub = n;
    renderSub();
  }
}

export function schedule(why) {
  clearTimeout(timer);
  fromEdit = why === "edit";
  carry = why === "stale";
  setRunState("wait", "edited…");
  timer = setTimeout(refresh, 380);
}

/** Model, run and game stats for the working profile; stale answers drop. */
export async function refresh() {
  clearTimeout(timer);
  const my = ++seq;
  const prof = S.profile;
  const sent = profileKey(prof); // the editor may change S.profile while this runs
  const model = S.modelId;
  const test = S.testId;
  setRunState("wait", "running…");
  // The first run has nothing to show yet: say what is running instead of
  // leaving the column blank (a later run keeps the last verdict until the
  // new one arrives).
  if (!$("verdict").childElementCount) {
    const items = S.reg.items;
    $("verdict").replaceChildren(
      h(
        "div",
        { class: "verdict-wait lv-wait" },
        h("b", { text: "Running…" }),
        h("span", { text: `${items.tests?.[test]?.name || test} · ${items.models?.[model]?.name || model}` }),
      ),
    );
  }
  // The numbers before an edit, for the chips saying what it did.
  const same = S.result && resultFor === `${model}|${test}`;
  const was = carry ? carryWas : fromEdit && same ? [...keyNumbers(S.result, S.model), ...gameNumbers(S.derive)] : null;
  fromEdit = false;
  carry = false;
  carryWas = was;
  if (was) emit("delta-start");
  $("err").hidden = true;
  delete $("err").dataset.from;
  try {
    const m = await api("/api/model", { model, profile: prof });
    if (my !== seq) return;
    S.model = m;
    S.modelFor = sent;
    emit("model", m);
    if (m.status !== "ready") {
      S.result = null;
      S.frames = [];
      renderPlanned(m);
      setRunState("out", "planned");
      emit("delta", null);
      return;
    }
    view.setBlank(false);
    $("plan").hidden = true;
    $("btn-pose").disabled = false;
    view.load(m);
    const [res, der] = await Promise.all([
      api("/api/run", { model, test, profile: prof }),
      api("/api/derive", { model, profile: prof }),
    ]);
    if (my !== seq) return;
    const base = await compareRun(model, test);
    if (my !== seq) return;
    S.result = res;
    resultFor = `${model}|${test}`;
    S.derive = der;
    S.base = base;
    renderResult();
    emit("delta", was ? changes(was, [...keyNumbers(res, m), ...gameNumbers(der)]) : null);
    setRunState(res.verdict, `${res.verdict === "pass" ? "pass" : res.verdict === "warn" ? "warning" : "fail"} · ${res.ms} ms`);
    const dropped = [...(m.warnings || []), ...(res.warnings || [])];
    $("ed-msg").textContent = dropped.length ? `Ignored: ${[...new Set(dropped)].join("; ")}` : "";
  } catch (err) {
    if (my !== seq) return;
    // Clear the last answer, so an old verdict, game stats, part table or
    // reading never sits beside the error.
    S.result = null;
    S.derive = null;
    S.frames = [];
    view.showReach(null);
    $("plan").hidden = true;
    emit("delta", null);
    $("verdict").replaceChildren(
      h("div", { class: "verdict lv-fail" }, h("b", { text: "No result" }), h("span", { text: "this run failed, see below" })),
    );
    $("cards").replaceChildren();
    $("readout").replaceChildren();
    for (const id of ["cmp-sec", "map-sec", "chart-sec", "sub-sec", "derive-sec", "parts-sec"]) $(id).hidden = true;
    $("playbar").hidden = true;
    setRunState("fail", "error");
    $("err").hidden = false;
    $("err").textContent = err.message;
  }
}

async function compareRun(model, test) {
  const name = S.compareTo;
  if (name === S.profileName && profileKey() === S.saved) return null; // comparing with itself
  const key = `${model}|${test}|${name}|`;
  if (!compareCache.has(key)) {
    const q = encodeURIComponent(name);
    const p = Promise.all([
      api("/api/run", { model, test, profile: name }),
      api(`/api/model/${model}?profile=${q}`),
      api(`/api/derive/${model}?profile=${q}`),
    ]).then(([run, mdl, der]) => ({ name, run, model: mdl, derive: der }));
    compareCache.set(key, p);
    p.catch(() => compareCache.delete(key));
  }
  return compareCache.get(key);
}

function setRunState(level, text) {
  const chip = $("run-state");
  chip.textContent = text;
  chip.className = `chip lv-${level}`;
}

// ----- results -----

// A planned model has no body, suit or numbers yet: an empty stage with its
// plan written large, and nothing left over from the last model.
function renderPlanned(m) {
  $("verdict").replaceChildren(
    h("div", { class: "verdict lv-out" }, h("b", { text: m.name }), h("span", { text: "planned, not built yet" })),
  );
  $("cards").replaceChildren();
  for (const id of ["cmp-sec", "map-sec", "chart-sec", "sub-sec", "derive-sec", "parts-sec"]) $(id).hidden = true;
  $("playbar").hidden = true;
  setPlaying(false);
  S.poseMode = false;
  S.poseFrame = null;
  $("posebox").hidden = true;
  $("btn-pose").classList.remove("on");
  $("btn-pose").disabled = true;
  $("readout").replaceChildren();
  view.showReach(null);
  view.setBlank(true);
  view.note.textContent = "";
  $("plan").replaceChildren(
    h("b", { text: m.name }),
    h("p", { class: "plan-text", text: m.about }),
    h("p", { class: "muted", text: `Planned for chunk ${m.chunk || "3 or 4"} of the plan. Nothing to run on it yet.` }),
  );
  $("plan").hidden = false;
}

function renderResult() {
  const res = S.result;
  for (const id of ["cmp-sec", "derive-sec", "parts-sec"]) $(id).hidden = false;
  $("plan").hidden = true;
  $("btn-pose").disabled = false;
  // A pass with an orange card says so in the headline.
  const warned = res.verdict === "pass" && res.cards.some((c) => c.level === "warn");
  const head = res.verdict === "pass" ? (warned ? "Pass, with warnings" : "Pass") : res.verdict === "warn" ? "Warning" : "Fail";
  $("verdict").replaceChildren(
    h(
      "div",
      { class: `verdict lv-${warned ? "warn" : res.verdict}` },
      h("b", { text: head }),
      h("span", { text: `${res.test_name} · ${res.model_name}` }),
    ),
    h("p", { class: "about", text: res.about }),
  );
  $("cards").replaceChildren(
    ...res.cards.map((c) =>
      h(
        "div",
        { class: `card lv-${c.level}` },
        h("div", { class: "card-top" }, h("span", { text: plain(c.title) }), h("b", { text: plain(c.value) })),
        h("div", { class: "card-text", text: plain(c.text) }),
      ),
    ),
  );
  renderCompare();
  renderSub();
  const frames = framesNow();
  S.frames = frames;
  const keepT = S.frames.length && S.frame < S.frames.length ? S.frame : worstFrame(frames);
  $("map-sec").hidden = res.kind !== "shoulder_rom";
  $("chart-sec").hidden = !(res.kind === "motions" || res.kind === "lift");
  $("playbar").hidden = false;
  $("scrub").max = Math.max(0, frames.length - 1);
  $("scrub").disabled = frames.length < 2;
  $("btn-play").disabled = frames.length < 2 || res.kind === "hold";
  $("btn-worst").disabled = frames.length < 2;
  if (res.kind === "shoulder_rom") drawMap();
  view.showReach(res.kind === "shoulder_rom" ? res.map : null);
  renderDerive();
  if (S.poseMode) requestPose();
  else showFrame(keepT);
}

function framesNow() {
  const res = S.result;
  if (!res) return [];
  if (MOTION_KINDS.includes(res.kind)) return res.motions?.[S.sub]?.frames || [];
  return res.frames || [];
}

/** The worst frame: the highest level (fail, then warn), then the most
 *  problems; the first of equals. 0 when every frame is clean. */
function worstIndex(frames) {
  const rank = { pass: 0, warn: 1, fail: 2 };
  const score = (f) => (rank[f.level] || 0) * 1000 + (f.issues?.length || 0);
  let best = 0;
  frames.forEach((f, i) => {
    if (score(f) > score(frames[best])) best = i;
  });
  return best;
}

function worstFrame(frames) {
  return S.result?.kind === "hold" ? S.sub : worstIndex(frames);
}

function renderSub() {
  const res = S.result;
  const box = $("sub");
  box.replaceChildren();
  $("sub-sec").hidden = !(MOTION_KINDS.includes(res.kind) || res.kind === "hold");
  if (MOTION_KINDS.includes(res.kind)) {
    $("sub-title").textContent = "Motions";
    res.motions.forEach((m, i) => {
      box.append(
        h(
          "button",
          {
            class: `pick lv-${m.level}${i === S.sub ? " on" : ""}`,
            title: m.about,
            onclick: () => {
              S.sub = i;
              S.frame = 0;
              setPoseMode(false);
              renderResult();
            },
          },
          h("b", { text: m.name }),
          h("span", {
            text:
              plain(m.issues?.[0]?.text) ||
              (res.kind === "close_fit"
                ? `closest ${fmt(m.peaks?.min_skin_mm, 1)} mm to the skin`
                : `${fmt(m.peaks?.misalign_mm, 0)} mm · ${fmt(m.peak_w, 0)} W peak`),
          }),
        ),
      );
    });
    if (res.kind === "close_fit") box.append(fitTables(res));
  } else if (res.kind === "hold") {
    $("sub-title").textContent = `Poses (held ${res.duration_s} s)`;
    const t = h(
      "table",
      { class: "grid" },
      h(
        "tr",
        {},
        ["Pose", "Load", "Motor", "You", "Safety", "Sag", "Power"].map((x) => h("th", { text: x })),
      ),
    );
    res.rows.forEach((r, i) => {
      const worstPct = Math.max(0, ...Object.values(r.load_pct || {}));
      t.append(
        h(
          "tr",
          {
            class: `lv-row lv-${r.level}${i === S.sub ? " on" : ""}`,
            title: (r.issues || []).map((x) => plain(x.text)).join("\n"),
            onclick: () => {
              S.sub = i;
              setPoseMode(false);
              showFrame(i);
              renderSub();
            },
          },
          h("td", { text: r.name }),
          h("td", { text: `${r.payload_kg} kg` }),
          h("td", { text: `${fmt(worstPct, 0)}%` }),
          h("td", { text: `${fmt(r.human_nm, 1)} N·m` }),
          h("td", { text: fmt(r.min_safety, 1) }),
          h("td", { text: `${fmt(r.hand_sag_mm, 1)} mm` }),
          h("td", { text: `${fmt(r.watts, 0)} W` }),
        ),
      );
    });
    box.append(t);
  }
}

// Close fit: every shell's least gap to the skin and every moving pair's
// least gap, each row a jump to the frame where it happens.
function fitTables(res) {
  const jump = (r) => {
    const mi = res.motions.findIndex((m) => m.id === r.motion_id);
    if (mi < 0) return;
    const frames = res.motions[mi].frames || [];
    let fi = 0;
    frames.forEach((f, i) => {
      if (Math.abs(f.t - r.t) < Math.abs(frames[fi].t - r.t)) fi = i;
    });
    S.sub = mi;
    S.frame = fi;
    setPoseMode(false);
    renderResult();
  };
  // Depths are only looked for reach_mm deep.
  const deep = res.reach_mm || 10;
  const mm = (v) => (v == null ? "–" : v <= -(deep - 0.5) ? `${fmt(deep, 0)}+ mm in` : `${fmt(v, 1)} mm`);
  const row = (r, cells) =>
    h(
      "tr",
      {
        class: `lv-row lv-${r.level}`,
        title: r.motion_id ? "Show this frame" : "",
        onclick: r.motion_id ? () => jump(r) : null,
      },
      cells.map((c, i) => h("td", { class: i ? "num" : "", text: c })),
    );
  const shells = h(
    "table",
    { class: "grid fit-shells" },
    h(
      "tr",
      {},
      ["Shell to skin", "Fitted", "At rest", "Closest", "Where"].map((x) => h("th", { text: x })),
    ),
    ...(res.shells || []).map((s) =>
      row(s, [s.label, `${fmt(s.fit_gap_mm, 0)} mm`, mm(s.rest_mm), mm(s.min_mm), s.where]),
    ),
  );
  const pairs = h(
    "table",
    { class: "grid fit-pairs" },
    h("tr", {}, ["Shell to shell", "At rest", "Closest", "Where"].map((x) => h("th", { text: x }))),
    ...(res.pairs || []).map((p) =>
      row(p, [`${p.a} / ${p.b}`, mm(p.rest_mm), p.min_mm <= 0 ? "overlap" : mm(p.min_mm), p.where]),
    ),
  );
  return h(
    "div",
    {},
    shells,
    res.pairs?.length ? pairs : h("p", { class: "muted small", text: "No two shells come within reach." }),
  );
}

function keyNumbers(res, model) {
  const out = [];
  const add = (label, v, unit, better, digits) => {
    if (Number.isFinite(v)) out.push({ label, v, unit, better, digits });
  };
  if (model?.suit) add("Suit mass", model.suit.total_kg, "kg", "down");
  if (!res) return out;
  const max = (xs) => (xs.length ? Math.max(...xs) : NaN);
  const min = (xs) => (xs.length ? Math.min(...xs) : NaN);
  if (res.kind === "shoulder_rom") {
    const m = res.metrics || {};
    add("Range followed", m.followed_pct, "%", "up");
    add("Clean, no warning", m.clean_pct, "%", "up");
    add("Worst misalignment", m.worst_misalign_mm, "mm", "down");
    add("Worst strap pressure", m.worst_kpa, "kPa", "down");
    add("Closest to gimbal lock", m.min_sing, "", "up", 2);
  } else if (res.kind === "motions") {
    const ms = res.motions || [];
    add("Motions passed", ms.filter((x) => x.level === "pass").length, `of ${ms.length}`, "up", 0);
    add("Worst misalignment", max(ms.map((x) => x.peaks?.misalign_mm ?? 0)), "mm", "down");
    add("Worst strap pressure", max(ms.map((x) => x.peaks?.kpa ?? 0)), "kPa", "down");
    add("Most you still carry", max(ms.map((x) => x.peaks?.human_nm ?? 0)), "N·m", "down");
    add("Energy, all motions", ms.reduce((a, x) => a + (x.energy_j || 0), 0), "J", "down");
    add("Peak power", max(ms.map((x) => x.peak_w ?? 0)), "W", "down");
  } else if (res.kind === "close_fit") {
    const ms = res.motions || [];
    add("Motions passed", ms.filter((x) => x.level === "pass").length, `of ${ms.length}`, "up", 0);
    add("Closest shell to skin", min((res.shells || []).map((s) => s.min_mm ?? Infinity)), "mm", "up", 1);
    add("Closest shells", min((res.pairs || []).map((p) => p.min_mm)), "mm", "up", 1);
    add(`Shells under ${res.rules?.warn_mm ?? 3} mm`, (res.shells || []).filter((s) => s.level !== "pass").length, `of ${res.shells?.length || 0}`, "down", 0);
    add("Body in itself", res.body_self?.mm ?? 0, "mm", "down", 0);
  } else if (res.kind === "hold") {
    const rows = res.rows || [];
    add("Poses passed", rows.filter((r) => r.level === "pass").length, `of ${rows.length}`, "up", 0);
    add("Worst motor load", max(rows.flatMap((r) => Object.values(r.load_pct || {}))), "%", "down");
    add("Most you still carry", max(rows.map((r) => r.human_nm ?? 0)), "N·m", "down");
    add("Lowest safety factor", min(rows.map((r) => r.min_safety ?? Infinity)), "", "up");
    add("Worst hand sag", max(rows.map((r) => r.hand_sag_mm ?? 0)), "mm", "down");
    add("Most power holding", max(rows.map((r) => r.watts ?? 0)), "W", "down");
  } else if (res.kind === "lift") {
    const p = res.peaks || {};
    for (const k of ["J1", "J2", "J3", "elbow"]) add(`Peak torque, ${motorName(k)} motor`, p[`torque_${k}`], "N·m", "down");
    add("Energy per lift", res.energy_per_lift_j, "J", "down");
    add("Lifts per charge", res.lifts_per_charge, "", "up", 0);
  }
  return out;
}

function gameNumbers(der) {
  if (!der?.move) return [];
  return [
    ["Sprint", der.move.sprint_mps, "m/s"],
    ["Boost jump", der.move.boost_jump_m, "m"],
    ["Lift, two arms", der.strength.lift_kg, "kg"],
    ["Lift in Strength mode", der.strength.strength_lift_kg, "kg"],
    ["Punch", der.strength.punch_j, "J"],
    ["Throw", der.strength.throw_j, "J"],
    ["Armour", der.armour.hp, "HP"],
    ["Battery at idle", der.energy.battery_min_idle, "min"],
  ].map(([label, v, unit]) => ({ label, v, unit, better: "up" }));
}

/** How a number moved from b to x: null under half a percent. */
function change(b, x) {
  if (!Number.isFinite(b.v) || !Number.isFinite(x.v)) return null;
  const d = x.v - b.v;
  const rel = Math.abs(d) / Math.max(Math.abs(b.v), 1e-9);
  if (rel < 0.005) return null;
  const good = d > 0 === (x.better === "up");
  const pct = Math.abs(b.v) > 1e-9 ? ` ${d > 0 ? "+" : "−"}${fmt(rel * 100, rel < 0.1 ? 1 : 0)}%` : "";
  return { rel, good, text: `${d > 0 ? "▲" : "▼"}${pct}` };
}

/** What an edit did: up to four numbers that moved, biggest first, each
 *  with its before -> after; [] when nothing moved. */
function changes(before, now) {
  const prev = new Map(before.map((x) => [x.label, x]));
  const out = [];
  for (const x of now) {
    const b = prev.get(x.label);
    const c = b && change(b, x);
    if (!c) continue;
    const unit = x.unit && !x.unit.startsWith("of ") ? ` ${x.unit}` : "";
    out.push({
      label: x.label,
      good: c.good,
      rel: c.rel,
      text: `${c.text.split(" ")[0]} ${fmt(b.v, x.digits)} → ${fmt(x.v, x.digits)}${unit}`,
      title: `${x.label}: ${fmt(b.v, x.digits)} before the edit, ${fmt(x.v, x.digits)}${unit} now (${c.text})`,
    });
  }
  return out.sort((a, b) => b.rel - a.rel).slice(0, 4);
}

function compareTable(now, before, baseName) {
  const prev = new Map((before || []).map((x) => [x.label, x]));
  const t = h(
    "table",
    { class: "cmp" },
    h("tr", {}, h("th", { text: "" }), h("th", { text: baseName || "–" }), h("th", { text: "now" }), h("th", { text: "" })),
  );
  for (const x of now) {
    const b = prev.get(x.label);
    const c = b ? change(b, x) : null;
    const arrow = c ? h("span", { class: c.good ? "up good" : "up bad", text: c.text }) : h("span", { class: "muted", text: b ? "=" : "" });
    t.append(
      h(
        "tr",
        {},
        h("td", { text: x.label }),
        h("td", { class: "num muted", text: b ? `${fmt(b.v, x.digits)} ${x.unit}` : "–" }),
        h("td", { class: "num", text: `${fmt(x.v, x.digits)} ${x.unit}` }),
        h("td", {}, arrow),
      ),
    );
  }
  return t;
}

function renderCompare() {
  const base = S.base;
  $("cmp-name").textContent = base ? base.name : "itself (pick another profile to compare)";
  const now = keyNumbers(S.result, S.model);
  const before = base ? keyNumbers(base.run, base.model) : null;
  $("compare").replaceChildren(compareTable(now, before, base?.name));
}

function renderDerive() {
  const now = gameNumbers(S.derive);
  const before = S.base ? gameNumbers(S.base.derive) : null;
  $("derive").replaceChildren(compareTable(now, before, S.base?.name));
}

// ----- the part table -----

function worstOver(frames) {
  const w = { torque: {}, safety: {}, kpa: {} };
  for (const f of frames) {
    for (const [k, v] of Object.entries(f.torques || {})) w.torque[k] = Math.max(w.torque[k] || 0, Math.abs(v));
    for (const s of f.structure || []) w.safety[s.id] = Math.min(w.safety[s.id] ?? Infinity, s.safety);
    for (const c of f.cuffs || []) w.kpa[c.id] = Math.max(w.kpa[c.id] || 0, c.pressure_kpa);
  }
  return w;
}

function allFrames() {
  const res = S.result;
  if (!res) return [];
  if (MOTION_KINDS.includes(res.kind)) return res.motions.flatMap((m) => m.frames || []);
  if (res.kind === "shoulder_rom") return [S.poseFrame || S.model?.rest].filter(Boolean);
  return res.frames || [];
}

// What the part table was last built from. Playback calls renderParts on
// every frame change, but the table shows the worst over the whole test, so
// it is rebuilt only when one of these changes.
let partsFrom = [];

function renderParts() {
  const suit = S.model?.suit;
  if (!suit) return;
  const from = [suit, S.result, S.poseFrame, S.model?.rest, S.reg, sortCol, sortDir];
  if (from.length === partsFrom.length && from.every((v, i) => v === partsFrom[i])) return;
  partsFrom = from;
  const w = worstOver(allFrames());
  const acts = S.reg.items.actuators;
  const comfort = S.reg.items.human.comfort;
  const rows = [];
  for (const j of suit.joints) {
    const t = w.torque[j.key];
    const pct = t != null && j.torque_cont_nm > 0 ? (100 * t) / j.torque_cont_nm : null;
    rows.push({
      hint: motorHint(j, acts),
      name: j.key.startsWith("J") ? `Shoulder ${motorName(j.key)} motor` : j.name,
      kind: "drive",
      what: acts[j.actuator]?.name || j.actuator,
      mass: j.mass_kg,
      rating: j.powered ? `${fmt(j.torque_cont_nm)} / ${fmt(j.torque_peak_nm)} N·m` : "passive",
      worst: pct,
      worstText: pct == null ? "–" : `${fmt(pct, 0)}% of cont`,
      level: t == null ? null : jointLevel(t, j),
    });
  }
  for (const ln of suit.links) {
    const s = w.safety[ln.id];
    rows.push({
      name: ln.name,
      kind: "strut",
      what: `${ln.material_name}, ${ln.shape} ${fmt(ln.outer_mm, 0)} mm`,
      mass: ln.mass_kg,
      rating: `yield ${fmt(ln.yield_mpa, 0)} MPa`,
      worst: s == null || !Number.isFinite(s) ? null : -s,
      worstText: s == null || !Number.isFinite(s) ? "–" : `safety ${fmt(s, 1)}`,
      level: s == null || !Number.isFinite(s) ? null : safetyLevel(s),
    });
  }
  for (const c of suit.cuffs) {
    const p = w.kpa[c.id];
    rows.push({
      name: c.name,
      kind: "cuff",
      what: `${c.material_name}, ${fmt(c.width_mm, 0)} mm wide`,
      mass: c.mass_kg,
      rating: `${fmt(c.area_cm2, 0)} cm²`,
      worst: p ?? null,
      worstText: p == null ? "–" : `${fmt(p, 1)} kPa`,
      level: p == null ? null : kpaLevel(p, comfort),
    });
  }
  for (const s of suit.shells) {
    rows.push({
      name: s.name,
      kind: "shell",
      what: `${s.material_name}, ${s.thickness_mm} mm`,
      mass: s.mass_kg,
      rating: `${fmt(s.area_m2 * 1e4, 0)} cm²${s.area_measured ? " (measured)" : ""}`,
      worst: null,
      worstText: "–",
      level: null,
    });
  }
  rows.push({
    name: "Battery",
    kind: "power",
    what: "Li-ion pack",
    mass: suit.masses.Battery,
    rating: `${fmt(suit.battery_wh, 0)} Wh`,
    worst: null,
    worstText: "–",
    level: null,
  });
  const key = { name: "name", kind: "kind", mass: "mass", worst: "worst" }[sortCol] || "mass";
  rows.sort((a, b) => {
    const x = a[key];
    const y = b[key];
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * sortDir;
  });
  const head = [
    ["name", "Part"],
    ["kind", "Kind"],
    ["", "Material or drive"],
    ["mass", "Mass"],
    ["", "Rating"],
    ["worst", "Worst in this test"],
  ];
  $("parts").replaceChildren(
    h(
      "tr",
      {},
      head.map(([k, t]) =>
        h("th", k ? { "data-sort": k, class: k === sortCol ? "sorted" : "" } : {}, t + (k === sortCol ? (sortDir > 0 ? " ▲" : " ▼") : "")),
      ),
    ),
    ...rows.map((r) =>
      h(
        "tr",
        {},
        h("td", { text: r.name, title: r.hint || "" }),
        h("td", { class: "muted", text: r.kind }),
        h("td", { class: "muted", text: r.what }),
        h("td", { class: "num", text: `${fmt(r.mass, 2)} kg` }),
        h("td", { class: "num muted", text: r.rating }),
        h("td", { class: `num${r.level ? ` lv-t-${r.level}` : ""}`, text: r.worstText }),
      ),
    ),
  );
  $("suit-total").textContent = `${fmt(suit.total_kg, 1)} kg in all`;
}

/** A motor's hover line, from the data: its joint, its drive and the drive's
 *  own note. */
function motorHint(j, acts) {
  const a = acts?.[j.actuator];
  const what = j.key in MOTOR && j.key !== "elbow" ? `The ${motorName(j.key)} motor (${j.name} in the mechanism data)` : j.name;
  return [`${what}: ${a?.name || j.actuator}.`, a?.note].filter(Boolean).join(" ");
}

// ----- frames, playback, pose mode -----

function leftFor(frame) {
  if (S.result?.kind === "lift") return frame; // both hands on the box
  return S.model?.rest || frame;
}

function currentFrame() {
  if (S.poseMode && S.poseFrame) return S.poseFrame;
  return S.frames[S.frame] || S.model?.rest || null;
}

export function showFrame(i) {
  if (S.frames.length) S.frame = Math.max(0, Math.min(S.frames.length - 1, i | 0));
  const fr = currentFrame();
  if (!fr) return;
  view.show(fr, { suit: S.model?.suit, comfort: S.reg.items.human.comfort, leftFrame: leftFor(fr) });
  $("scrub").value = S.frame;
  const end = S.frames.length ? S.frames[S.frames.length - 1].t : 0;
  $("time").textContent = S.poseMode
    ? "pose mode"
    : S.result?.kind === "hold"
      ? S.result.rows?.[S.frame]?.name || ""
      : S.frames.length
        ? `${fmt(fr.t, 2)} / ${fmt(end, 2)} s`
        : "rest pose";
  renderReadout(fr);
  drawChart();
  renderParts();
  if (S.result?.kind === "shoulder_rom") drawMap();
}

function setPlaying(on) {
  playing = on && S.frames.length > 1 && !S.poseMode;
  $("btn-play").textContent = playing ? "Pause" : "Play";
  if (playing) {
    const end = S.frames[S.frames.length - 1].t;
    playT = S.frame >= S.frames.length - 1 ? 0 : S.frames[S.frame].t;
    if (playT >= end) playT = 0;
    lastTs = 0;
    if (!looping) {
      looping = true;
      requestAnimationFrame(playLoop);
    }
  }
}

// Runs only while playing: nothing is queued on a paused or idle tester.
function playLoop(ts) {
  if (!playing || !S.frames.length) {
    looping = false;
    return;
  }
  requestAnimationFrame(playLoop);
  const dt = lastTs ? Math.min(0.1, (ts - lastTs) / 1000) : 0;
  lastTs = ts;
  const speed = Number($("speed").value) || 1;
  playT += dt * speed;
  const end = S.frames[S.frames.length - 1].t;
  if (playT > end) playT = 0;
  let i = 0;
  while (i < S.frames.length - 1 && S.frames[i + 1].t <= playT) i++;
  if (i !== S.frame) showFrame(i);
}

// Pose mode's sliders, each paired with a number field (pose-<key>-v).
const POSE_KEYS = ["plane", "elev", "axial", "elbow", "payload_kg"];

/** Set one pose value from its slider or its number field, held to the
 *  slider's range and step; the other control follows and the pose re-runs.
 *  A field being typed in keeps its text until it is left. */
function setPoseValue(k, raw, from = null) {
  const slider = $(`pose-${k}`);
  const v = snapToStep(raw, slider.min, slider.max, slider.step);
  S.pose[k] = v;
  slider.value = String(v);
  const num = $(`pose-${k}-v`);
  if (from !== num) num.value = String(v);
  requestPose();
}

export function setPoseMode(on) {
  S.poseMode = on;
  $("posebox").hidden = !on;
  $("btn-pose").classList.toggle("on", on);
  if (on) {
    setPlaying(false);
    for (const k of POSE_KEYS) {
      $(`pose-${k}`).value = S.pose[k];
      $(`pose-${k}-v`).value = S.pose[k];
    }
    requestPose();
  } else {
    S.poseFrame = null;
    showFrame(S.frame);
  }
}

async function requestPose() {
  if (!S.poseMode || S.model?.status !== "ready") return;
  if (poseBusy) {
    poseAgain = true;
    return;
  }
  poseBusy = true;
  try {
    const fr = await api("/api/pose", { model: S.modelId, profile: S.profile, ...S.pose });
    if (S.poseMode) {
      S.poseFrame = fr;
      showFrame(S.frame);
    }
    if ($("err").dataset.from === "pose") $("err").hidden = true;
  } catch (err) {
    // The last pose's numbers would read as this pose's: drop them.
    S.poseFrame = null;
    $("readout").replaceChildren(h("p", { class: "muted", text: "No reading: this pose failed, see the message above." }));
    $("err").hidden = false;
    $("err").textContent = err.message;
    $("err").dataset.from = "pose";
  } finally {
    poseBusy = false;
    if (poseAgain) {
      poseAgain = false;
      requestPose();
    }
  }
}

function tile(label, value, level, hint) {
  return h(
    "div",
    { class: `tile${level ? ` lv-${level}` : ""}`, title: hint || "" },
    h("span", { text: label }),
    h("b", { text: value }),
  );
}

function renderReadout(fr) {
  const box = $("readout");
  const issues = fr.issues || [];
  const lvl = (group) => {
    const codes = TILE_CODES[group];
    const mine = issues.filter((i) => codes.includes(i.code));
    if (mine.some((i) => i.level === "fail")) return "fail";
    return mine.length ? "warn" : "pass";
  };
  const joints = S.model?.suit?.joints || [];
  let worst = 0;
  let worstKey = "";
  for (const j of joints) {
    const t = fr.torques?.[j.key];
    if (t == null || !j.powered || !(j.torque_cont_nm > 0)) continue;
    const pct = (100 * Math.abs(t)) / j.torque_cont_nm;
    if (pct > worst) (worst = pct), (worstKey = j.key);
  }
  const cuffs = fr.cuffs || [];
  const worstCuff = cuffs.reduce((a, c) => (!a || c.pressure_kpa > a.pressure_kpa ? c : a), null);
  const struts = fr.structure || [];
  const weakest = struts.reduce((a, s) => (!a || s.safety < a.safety ? s : a), null);
  const p = fr.pose || {};
  const q = (fr.q_deg || []).map((x) => `${fmt(x, 0)}°`).join(" · ");
  box.replaceChildren(
    h(
      "div",
      { class: "ro-pose" },
      h("b", { text: S.poseMode ? "Your pose" : "This frame" }),
      ` plane ${fmt(p.plane, 0)}° · raised ${fmt(p.elev, 0)}° · twist ${fmt(p.axial, 0)}° · elbow ${fmt(p.elbow, 0)}°`,
      fr.payload_kg ? ` · holding ${fmt(fr.payload_kg, 1)} kg` : "",
      fr.in_rom === false ? h("span", { class: "lv-t-warn", text: " · outside a normal human range" }) : "",
    ),
    fr.fit ? fitTiles(fr, lvl, S.result) : mechTiles(),
    issues.length
      ? h(
          "ul",
          { class: "issues" },
          issues.map((i) => h("li", { class: `lv-t-${i.level}`, text: plain(i.text) })),
        )
      : h("p", { class: "muted small", text: "No problems in this frame." }),
  );

  function mechTiles() {
    return h(
      "div",
      { class: "tiles" },
      tile("Shoulder centre off", `${fmt(fr.misalign_mm, 1)} mm`, lvl("misalign"), "Gap between the exo's rotation centre and the real shoulder joint (yellow line)."),
      tile("Gimbal-lock margin", fmt(fr.sing, 2), lvl("lock"), "How far the three motor axes are from lining up: 1 far, 0 locked."),
      tile("Exo joints", q || "cable", lvl("joints"), "Exo shoulder joint angles (lift, swing, twist), against their limits and clashes."),
      tile(
        "Hardest motor",
        worstKey ? `${motorName(worstKey)} ${fmt(worst, 0)}%` : "–",
        lvl("motors"),
        `Torque as a share of the continuous rating.${worstKey ? ` ${motorHint(joints.find((j) => j.key === worstKey), S.reg.items.actuators)}` : ""}`,
      ),
      tile("Strap pressure", worstCuff ? `${fmt(worstCuff.pressure_kpa, 1)} kPa` : "–", lvl("straps"), "Highest cuff pressure on the skin; all-day limit about 4.3 kPa."),
      tile("Weakest strut", weakest ? `safety ${fmt(weakest.safety, 1)}` : "–", lvl("struts"), weakest ? weakest.name : ""),
      tile("You carry", `${fmt(fr.human_shoulder_nm, 1)} N·m`, null, `Shoulder torque your own muscles still give; elbow ${fmt(fr.human_elbow_nm, 1)} N·m. Assist ${fmt((fr.assist || 0) * 100, 0)}%.`),
      tile("Hand sag", `${fmt(fr.hand_sag_mm, 1)} mm`, null, "How far the hand drops from frame and drive flex under the load."),
    );
  }
}

function fitTiles(fr, lvl, res) {
  const deep = res?.reach_mm || 10;
  const warn = res?.rules?.warn_mm ?? 3;
  const least = (o) =>
    Object.entries(o || {}).reduce((a, [k, v]) => (!a || v.mm < a[1].mm ? [k, v] : a), null);
  const skin = least(fr.fit.skin);
  const pair = least(fr.fit.pairs);
  const label = (n) => n.replace(/_([LR])$/, (_, s) => (s === "L" ? " left" : " right")).replaceAll("_", " ");
  return h(
    "div",
    { class: "tiles" },
    tile(
      "Closest shell to skin",
      skin ? (skin[1].mm <= -(deep - 0.5) ? `${fmt(deep, 0)}+ mm in` : `${fmt(skin[1].mm, 1)} mm`) : "–",
      lvl("fit"),
      skin ? `${label(skin[0])}, against the ${skin[1].against}. Warns under ${warn} mm, fails inside the skin.` : "",
    ),
    tile(
      "Closest shells",
      pair ? (pair[1].mm <= 0 ? "overlap" : `${fmt(pair[1].mm, 1)} mm`) : "apart",
      lvl("overlap"),
      pair ? pair[0].split("+").map(label).join(" and ") : "No two moving shells within reach.",
    ),
    tile(
      "Body in itself",
      fr.fit.body_mm ? `${fmt(fr.fit.body_mm, 0)} mm` : "none",
      null,
      "Arm skin inside the torso: the pose or the skinning, not the suit. Suit contacts there are not counted.",
    ),
  );
}

// ----- charts and the map -----

function drawChart() {
  const res = S.result;
  if (!res || (res.kind !== "motions" && res.kind !== "lift")) return;
  for (const b of $("chart-tabs").children) b.classList.toggle("on", b.dataset.id === S.chart);
  const frames = S.frames;
  const t = frames.map((f) => f.t);
  const joints = (S.model?.suit?.joints || []).filter((j) => j.key in JCOL);
  const cursor = frames[S.frame]?.t;
  const canvas = $("chart");
  const comfort = S.reg.items.human.comfort;
  if (S.chart === "torque" || S.chart === "speed") {
    const field = S.chart === "torque" ? "torques" : "speeds";
    const limit = S.chart === "torque" ? "torque_cont_nm" : "speed_max_rad_s";
    const series = joints.map((j) => ({
      name: motorName(j.key),
      color: JCOL[j.key],
      values: frames.map((f) => Math.abs(f[field]?.[j.key] ?? 0)),
    }));
    const lines = joints
      .filter((j) => j.powered)
      .map((j) => ({ y: j[limit], color: JCOL[j.key], label: `${motorName(j.key)} ${S.chart === "torque" ? "cont" : "top"}` }));
    lineChart(canvas, { t, series, lines, cursor, unit: S.chart === "torque" ? "N·m" : "rad/s" });
  } else if (S.chart === "pressure") {
    const ids = (frames[0]?.cuffs || []).map((c) => [c.id, c.name]);
    const cols = ["#5fd0ff", "#ffb454", "#8ee06e"];
    const series = ids.map(([id, name], k) => ({
      name,
      color: cols[k % 3],
      values: frames.map((f) => f.cuffs.find((c) => c.id === id)?.pressure_kpa ?? 0),
    }));
    const lines = [
      { y: comfort.pressure_long_kpa, color: "#f2a154", label: "all day" },
      { y: comfort.pressure_short_kpa, color: "#f2637d", label: "short use" },
    ];
    lineChart(canvas, { t, series, lines, cursor, unit: "kPa" });
  } else if (S.chart === "misalign") {
    lineChart(canvas, {
      t,
      series: [
        { name: "centre off (mm)", color: "#ffe066", values: frames.map((f) => f.misalign_mm) },
        { name: "lock margin x10", color: "#6ab8ff", values: frames.map((f) => f.sing * 10), dash: true },
      ],
      lines: [{ y: 10, color: "#f2a154", label: "10 mm" }],
      cursor,
      unit: "mm",
    });
  } else if (S.chart === "you") {
    lineChart(canvas, {
      t,
      series: [
        { name: "shoulder", color: "#ff7aa8", values: frames.map((f) => f.human_shoulder_nm) },
        { name: "elbow", color: "#d58cff", values: frames.map((f) => f.human_elbow_nm) },
      ],
      cursor,
      unit: "N·m (your muscles)",
    });
  } else if (S.chart === "power") {
    const values = frames.map((f) =>
      Object.keys(JCOL).reduce((a, k) => a + Math.abs((f.torques?.[k] ?? 0) * (f.speeds?.[k] ?? 0)), 0),
    );
    lineChart(canvas, {
      t,
      series: [{ name: "shoulder and elbow motors, |torque x speed|", color: "#5fd0ff", values }],
      cursor,
      unit: "W",
    });
  }
}

function drawMap() {
  const res = S.result;
  if (!res?.map || $("map-sec").hidden) return;
  const fr = S.poseMode ? S.poseFrame : null;
  pick = romMap($("rom-map"), res.map, fr ? fr.pose : null);
}

function cellText(c) {
  if (c.level === "out") return `plane ${c.plane}°, raised ${c.elev}°: beyond a normal human range`;
  const why = c.why ? ` · ${c.why}` : "";
  return `plane ${c.plane}°, raised ${c.elev}°: ${c.level}${why} · ${fmt(c.misalign_mm, 1)} mm off · ${fmt(c.kpa, 1)} kPa · lock margin ${fmt(c.sing, 2)}`;
}

async function saveReport() {
  try {
    const r = await api("/api/report", { model: S.modelId, test: S.testId, profile: S.profile });
    toast(`Report saved: ${r.path}`, "good");
  } catch (err) {
    toast(`Report not saved: ${err.message}`, "bad");
  }
}

export { renderParts };
