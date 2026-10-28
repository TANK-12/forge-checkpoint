/* Garden: Claude's L-system plants, growing with real time. The page side:
 * the canvas, panels and pointer handling. The logic lives in lsys.js (growth
 * and geometry), sky.js, words.js and draw.js; the garden itself is kept by
 * server.py at /api/curio/garden. */

import * as L from "./lsys.js";
import { skyAt } from "./sky.js";
import { ageText, crossName, genomeOk, nextGrowthText, parseRules, rulesText, suggestName } from "./words.js";
import * as D from "./draw.js";
import { freshSeed, hashString } from "../_kit/rng.js";

const STYLE = `
.gd { position: absolute; inset: 0; }
.gd canvas.gd-view { position: absolute; inset: 0; width: 100%; height: 100%; display: block; touch-action: none; }
.gd .ag-panel h3 { text-transform: none; letter-spacing: 0.01em; font-size: 12.5px; }
.gd-col { position: absolute; top: 12px; display: flex; flex-direction: column; gap: 10px;
  width: min(296px, calc(50% - 24px)); max-height: calc(100% - 24px); pointer-events: none; }
.gd-col > * { pointer-events: auto; }
.gd-left { left: 12px; }
.gd-right { right: 12px; }
.gd-right > .ag-panel { overflow-y: auto; min-height: 0; }
.gd-title { font-family: Georgia, "Noto Serif", serif; font-style: italic; font-size: 19px; color: var(--accent); margin: 0; }
.gd-line { font-size: 12.5px; color: var(--muted); margin: 0; line-height: 1.45; }
.gd-name { font-family: Georgia, "Noto Serif", serif; font-size: 19px; margin: 0; color: var(--text); display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
.gd-facts { display: grid; grid-template-columns: auto 1fr; gap: 3px 10px; font-size: 12.5px; margin: 0; }
.gd-facts dt { color: var(--muted); }
.gd-facts dd { margin: 0; }
.gd-bar { height: 5px; border-radius: 3px; background: rgba(255,255,255,0.08); overflow: hidden; }
.gd-bar > i { display: block; height: 100%; background: linear-gradient(90deg, #6fcf8a, var(--accent)); }
.gd-form { display: flex; flex-direction: column; gap: 6px; padding-top: 4px; border-top: 1px solid rgba(255,255,255,0.06); }
.gd-form input[type=text], .gd-form textarea { font: inherit; font-size: 13px; color: var(--text); background: var(--bg);
  border: 1px solid var(--border); border-radius: 8px; padding: 6px 8px; }
.gd-form textarea { resize: vertical; min-height: 52px; }
.gd-form .gd-rules { font-family: ui-monospace, "DejaVu Sans Mono", monospace; font-size: 12px; min-height: 58px; }
.gd-small { font-size: 11.5px; color: var(--muted); }
.gd-err { color: var(--bad); font-size: 12px; }
.gd-pick { color: var(--violet); }
.gd-pressed { position: absolute; top: 12px; left: 12px; width: min(296px, calc(100% - 24px)); }
.gd-note { white-space: pre-wrap; font-size: 13px; line-height: 1.5; color: #d9d2c8; margin: 0; }
.gd-hint { position: absolute; left: 50%; bottom: 8px; transform: translateX(-50%); font-size: 12px;
  color: rgba(255,236,210,0.55); pointer-events: none; white-space: nowrap; }
.gd.is-pressed .gd-col, .gd.is-pressed .gd-hint { display: none; }
`;

const DAY_MS = 86400000;
const BY = ""; // the server fills in the player's name
let startersCache = null;

function localHour(ms = Date.now()) {
  const d = new Date(ms);
  return d.getHours() + d.getMinutes() / 60 + d.getSeconds() / 3600;
}

function fmtDate(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function fmtClock(ms) {
  return new Date(ms).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** A plant with its cached geometry. */
function makeEntry(plant, genome = plant.genome) {
  const maxGen = Math.max(1, L.effectiveMaxGen(genome));
  return { plant, genome, maxGen, bounds: L.fullBounds(genome, maxGen), key: -1, geo: null, phase: (hashString(plant.id || plant.name) % 628) / 100 };
}

/** Where and how big to draw a plant now. The scale is the geometric mean of
 *  its full-grown scale and the scale that would fit it as it is today, so a
 *  young plant still reads but growing is still plain to see. */
function placeFor(spot, entry, ground, geo, tall) {
  const spanX = Math.max(1e-3, geo.maxX - geo.minX);
  const fitNow = Math.min((spot.x1 - spot.x0) * 0.88 / spanX, (tall * spot.stature) / Math.max(geo.maxY, 1e-3));
  const scale = Math.max(spot.scale, Math.sqrt(spot.scale * Math.max(spot.scale, fitNow)));
  const height = spot.height;
  const cx = spot.mid - ((geo.maxX + geo.minX) / 2) * scale;
  return {
    cx,
    ground,
    scale,
    trunk: Math.min(7, Math.max(1.4, height * 0.02)),
    leafPx: Math.min(7.5, Math.max(2.4, height * 0.016)),
    maxY: Math.max(geo.maxY, 1e-3),
  };
}

function geoFor(entry, stage) {
  const q = stage >= entry.maxGen ? entry.maxGen : Math.round(stage * 48) / 48;
  if (q !== entry.key) {
    entry.key = q;
    entry.geo = L.plantGeometry(entry.genome, q, entry.maxGen);
  }
  return entry.geo;
}

function makeCanvas() {
  return document.createElement("canvas");
}

let glowCache = null;
function glows() {
  if (!glowCache) {
    glowCache = {
      firefly: D.makeGlow(makeCanvas(), "rgba(255,250,200,1)", "rgba(200,255,140,0.35)"),
      flower: D.makeGlow(makeCanvas(), "rgba(255,220,170,0.9)", "rgba(255,150,90,0.25)"),
    };
  }
  return glowCache;
}

async function starters() {
  if (!startersCache) {
    const res = await fetch(new URL("./starters.json", import.meta.url));
    startersCache = await res.json();
  }
  return startersCache;
}

/** Draws a whole garden scene (used live and for the shelf still). */
function drawScene(g, w, h, state) {
  const { entries, layout, sky, t, nowMs, ahead, wind, bg, panX = 0 } = state;
  if (bg) g.drawImage(bg, 0, 0, w, h);
  else D.drawBackground(g, w, h, sky, layout.ground);
  D.drawStars(g, w, layout.ground, state.stars, sky.stars, t);
  const light = sky.light;
  const glow = sky.stars > 0.1 ? { canvas: glows().flower, alpha: Math.min(0.8, sky.stars * 0.8) } : null;
  g.save();
  g.translate(-panX, 0);
  entries.forEach((entry, i) => {
    const spot = layout.spots[i];
    if (spot.x1 - panX < -20 || spot.x0 - panX > w + 20) return;
    const stage = L.growthStage(entry.plant, nowMs, entry.maxGen, ahead);
    entry.stage = stage;
    const ring = state.rings && state.rings.get(entry.plant.id);
    if (ring) {
      const grad = g.createRadialGradient(spot.mid, layout.ground, 2, spot.mid, layout.ground, spot.x1 - spot.mid);
      grad.addColorStop(0, ring);
      grad.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = grad;
      g.fillRect(spot.x0, layout.ground - (spot.x1 - spot.x0) * 0.5, spot.x1 - spot.x0, spot.x1 - spot.x0);
    }
    const geo = geoFor(entry, stage);
    const place = placeFor(spot, entry, layout.ground, geo, layout.tall);
    // a small mound of soil at every foot
    g.fillStyle = `rgba(${Math.round(60 * light + 10)},${Math.round(42 * light + 8)},${Math.round(32 * light + 8)},0.9)`;
    g.beginPath();
    g.ellipse(spot.mid, layout.ground + 3, Math.min(34, (spot.x1 - spot.x0) * 0.18), 6, 0, Math.PI, 0);
    g.fill();
    if (stage < 1 && !geo.segs[0].length) {
      D.drawSeedling(g, spot.mid, layout.ground, 4, light, stage);
      entry.drawnHeight = 12;
    } else {
      const sway = wind > 0 ? { t, amp: wind, phase: entry.phase } : null;
      D.drawPlant(g, geo, entry.genome, place, D.plantColours(entry.genome, light), sway, glow);
      entry.drawnHeight = geo.maxY * place.scale;
    }
    if (state.labels) state.labels(g, entry, spot, layout.ground);
  });
  g.restore();
  const night = Math.max(0, (sky.stars - 0.3) / 0.7);
  D.drawFireflies(g, w, layout.ground, h, night, t, glows().firefly);
}

export default {
  async mount(root, ctx) {
    const ui = ctx.ui;
    const el = ui.el;
    const wrap = el("div", { class: "gd" });
    const style = el("style", { text: STYLE });
    const canvas = el("canvas", { class: "gd-view", "aria-label": "Claude's garden" });
    wrap.append(style, canvas);
    root.append(wrap);
    const g = canvas.getContext("2d");

    const st = {
      plants: [],
      entries: [],
      max: 40,
      selected: null,
      hover: null,
      mode: "garden", // garden | plant | cross | pressed
      picks: [],
      ahead: 0, // days
      follow: true,
      hour: localHour(),
      wind: 1,
      draft: null,
      panX: 0,
      pressed: null,
    };
    let w = 0;
    let h = 0;
    let dpr = 1;
    let layout = null;
    let bg = null;
    let bgKey = "";
    let pressedSheet = null;
    const stars = D.makeStars();
    const off = [];

    // --- panels -----------------------------------------------------------
    const left = el("div", { class: "gd-col gd-left" });
    const right = el("div", { class: "gd-col gd-right" });
    const hint = el("div", { class: "gd-hint", text: "" });
    wrap.append(left, right, hint);

    const head = ui.panel("");
    const title = el("p", { class: "gd-title", text: "Claude's garden" });
    const when = el("p", { class: "gd-line" });
    const count = el("p", { class: "gd-line" });
    const plantBtn = ui.button("Plant a seed", () => startPlant(), { kind: "primary", title: "Plant a new seed with a random genome; you name it" });
    const crossBtn = ui.button("Cross two", () => startCross(), { title: "Pick two plants; their child mixes both genomes" });
    const headRow = el("div", { class: "ag-row" }, plantBtn, crossBtn);
    const plantForm = el("div", { class: "gd-form", hidden: true });
    const crossBox = el("div", { class: "gd-form", hidden: true });
    head.body.append(title, when, count, headRow, plantForm, crossBox);
    left.append(head.el);

    // planting
    const seedName = el("input", { type: "text", maxlength: "40", title: "The new plant's name", placeholder: "A name for it" });
    const plantErr = el("p", { class: "gd-err", hidden: true });
    plantForm.append(
      el("label", { class: "gd-small", text: "Name the seed" }),
      seedName,
      plantErr,
      el(
        "div",
        { class: "ag-row" },
        ui.button("Plant it", () => doPlant(), { kind: "primary", title: "Put the seed in the ground at the end of the row" }),
        ui.button("Another name", () => (seedName.value = suggestName(freshSeed())), { title: "Suggest a different name" }),
        ui.button("Never mind", () => setMode("garden"), { kind: "ghost", title: "Close this without planting" }),
      ),
    );

    // crossing
    const crossText = el("p", { class: "gd-line gd-pick" });
    const crossName_ = el("input", { type: "text", maxlength: "40", title: "The child's name", placeholder: "A name for the child" });
    const crossErr = el("p", { class: "gd-err", hidden: true });
    const crossGo = ui.button("Cross them", () => doCross(), { kind: "primary", title: "Plant the child of these two at the end of the row" });
    const crossNameRow = el("div", { class: "gd-form", hidden: true }, crossName_, crossErr, el("div", { class: "ag-row" }, crossGo));
    crossBox.append(crossText, crossNameRow, el("div", { class: "ag-row" }, ui.button("Never mind", () => setMode("garden"), { kind: "ghost", title: "Stop crossing" })));

    // time and weather (advanced)
    const timePanel = ui.panel("Time and weather", { adv: true, fold: true, folded: { width: 1100, height: 720 } });
    const aheadSlider = ui.slider({
      label: "Days ahead",
      min: 0,
      max: 30,
      step: 0.25,
      value: 0,
      title: "Time-lapse: show the garden this many days from now (changes nothing)",
      oninput: (v) => (st.ahead = v),
    });
    const followToggle = ui.toggle("Sky follows the clock", true, (on) => {
      st.follow = on;
      if (on) hourSlider.set(localHour());
    }, { title: "Use the real local time for the sky; off to pick an hour" });
    const hourSlider = ui.slider({
      label: "Sky hour",
      min: 0,
      max: 24,
      step: 0.25,
      value: Math.round(localHour() * 4) / 4,
      title: "The hour the sky shows; moving it stops following the clock",
      oninput: (v) => {
        st.follow = false;
        followToggle.set(false);
        st.hour = v;
      },
    });
    const windSlider = ui.slider({ label: "Wind", min: 0, max: 2.5, step: 0.05, value: 1, title: "How hard the wind sways the plants", oninput: (v) => (st.wind = v) });
    timePanel.body.append(aheadSlider.el, followToggle.el, hourSlider.el, windSlider.el);
    left.append(timePanel.el);

    // the selected plant
    const info = ui.panel("");
    info.el.hidden = true;
    const nameLine = el("h2", { class: "gd-name" });
    const facts = el("dl", { class: "gd-facts" });
    const bar = el("div", { class: "gd-bar", title: "How far it has grown" }, el("i"));
    const pressBtn = ui.button("Press it", () => startPress(), { kind: "primary", title: "Keep this plant as it is now, pressed flat with a note" });
    const renameBtn = ui.button("Rename", () => startRename(), { title: "Give this plant a new name" });
    const closeInfo = ui.button("Close", () => select(null), { kind: "ghost", title: "Stop looking at this plant" });
    const pressForm = el("div", { class: "gd-form", hidden: true });
    const renameForm = el("div", { class: "gd-form", hidden: true });
    info.body.append(nameLine, facts, bar, el("div", { class: "ag-row" }, pressBtn, renameBtn, closeInfo), pressForm, renameForm);
    right.append(info.el);

    const pressName = el("input", { type: "text", maxlength: "80", title: "What to call the pressed plant" });
    const pressNote = el("textarea", { maxlength: "4000", placeholder: "A note for later (optional)", title: "An optional note kept with it" });
    pressForm.append(
      el("label", { class: "gd-small", text: "Press it with a name and a note" }),
      pressName,
      pressNote,
      el(
        "div",
        { class: "ag-row" },
        ui.button("Keep it", () => doPress(), { kind: "primary", title: "Save the pressed plant to the keepsakes" }),
        ui.button("Never mind", () => (pressForm.hidden = true), { kind: "ghost", title: "Close this without keeping anything" }),
      ),
    );
    const renameInput = el("input", { type: "text", maxlength: "40", title: "The plant's new name" });
    const renameErr = el("p", { class: "gd-err", hidden: true });
    renameForm.append(
      renameInput,
      renameErr,
      el(
        "div",
        { class: "ag-row" },
        ui.button("Save name", () => doRename(), { kind: "primary", title: "Keep the new name" }),
        ui.button("Never mind", () => (renameForm.hidden = true), { kind: "ghost", title: "Keep the old name" }),
      ),
    );

    // genome editor (advanced)
    const editor = el("div", { class: "gd-form adv" });
    const edErr = el("p", { class: "gd-err", hidden: true });
    const axiomIn = el("input", { type: "text", maxlength: "20", title: "The string every plant of this genome starts from" });
    const rulesIn = el("textarea", { class: "gd-rules", spellcheck: "false", title: "One rule per line: X = F[+X]FX, versions split by |, picked at random" });
    const num = (key, label, min, max, step, title) =>
      ui.slider({ label, min, max, step, value: min, title, oninput: (v) => editDraft((gnm) => (gnm[key] = v)) });
    const hue = (key, label) =>
      ui.slider({ label, min: 0, max: 359, step: 1, value: 0, title: `The ${key} colour, as a hue around the colour wheel`, oninput: (v) => editDraft((gnm) => (gnm.hues[key] = v)) });
    const sliders = {
      angle: num("angle", "Branch angle", 5, 60, 0.5, "Degrees each + or - turns"),
      len_decay: num("len_decay", "Length decay", 0.5, 1, 0.01, "How much shorter each branch level gets"),
      width_decay: num("width_decay", "Width decay", 0.4, 1, 0.01, "How much thinner each branch level gets"),
      jitter: num("jitter", "Jitter", 0, 20, 0.5, "Random wobble added to each turn, in degrees"),
      bloom: num("bloom", "Bloom", 0, 0.6, 0.01, "Share of buds that become flowers"),
      max_gen: num("max_gen", "Generations", 1, 7, 1, "How many generations it grows to (big ones stop earlier)"),
      hours_per_gen: num("hours_per_gen", "Hours per gen", 0.5, 48, 0.5, "Real hours each generation takes"),
    };
    const hues = { stem: hue("stem", "Stem hue"), leaf: hue("leaf", "Leaf hue"), flower: hue("flower", "Flower hue") };
    const flowerSeg = ui.seg(
      [
        { value: "round", label: "Round", title: "Five round petals" },
        { value: "star", label: "Star", title: "A pointed star" },
        { value: "bell", label: "Bell", title: "A hanging bell" },
        { value: "spark", label: "Spark", title: "Thin rays like a spark" },
      ],
      "round",
      (v) => editDraft((gnm) => (gnm.flower = v)),
      { title: "Flower shape" },
    );
    const draftNote = el("p", { class: "gd-small", text: "Changes show on this plant as a draft; it stays as it was until you plant the draft." });
    const plantDraft = ui.button("Plant the draft", () => doPlantDraft(), { kind: "primary", title: "Plant the edited genome as a new seed" });
    const undoDraft = ui.button("Undo changes", () => clearDraft(), { title: "Throw the draft away and show the plant as it is" });
    axiomIn.addEventListener("input", () => {
      const v = axiomIn.value.trim();
      if (!v || v.length > 20 || !genomeOk(v)) return showEdErr("the axiom uses F, capitals, + - [ ] with paired brackets");
      editDraft((gnm) => (gnm.axiom = v));
    });
    rulesIn.addEventListener("input", () => {
      const rules = parseRules(rulesIn.value);
      if (typeof rules === "string") return showEdErr(rules);
      editDraft((gnm) => (gnm.rules = rules));
    });
    editor.append(
      el("label", { class: "gd-small", text: "Genome" }),
      el("label", { class: "gd-small", text: "Axiom" }),
      axiomIn,
      el("label", { class: "gd-small", text: "Rules" }),
      rulesIn,
      edErr,
      ...Object.values(sliders).map((s) => s.el),
      ...Object.values(hues).map((s) => s.el),
      flowerSeg.el,
      draftNote,
      el("div", { class: "ag-row" }, plantDraft, undoDraft),
    );
    info.body.append(editor);

    // the pressed view
    const pressedPanel = ui.panel("");
    pressedPanel.el.classList.add("gd-pressed");
    pressedPanel.el.hidden = true;
    const pTitle = el("h2", { class: "gd-name" });
    const pMeta = el("p", { class: "gd-line" });
    const pNote = el("p", { class: "gd-note" });
    pressedPanel.body.append(
      pTitle,
      pMeta,
      pNote,
      el("div", { class: "ag-row" }, ui.button("Back to the garden", () => leavePressed(), { kind: "primary", title: "Close the pressed plant and return to the garden (Esc)" })),
    );
    wrap.append(pressedPanel.el);

    // --- data -------------------------------------------------------------
    async function reload(selectId) {
      const res = await ctx.api("plants");
      st.plants = res.plants;
      st.max = res.max || 40;
      st.entries = st.plants.map((p) => makeEntry(p));
      if (selectId) st.selected = selectId;
      if (st.selected && !st.plants.some((p) => p.id === st.selected)) st.selected = null;
      st.draft = null;
      relayout();
      if (selectId) scrollTo(selectId);
      renderInfo(true);
      updateHead();
      return res;
    }

    function relayout() {
      if (!w) return;
      layout = D.layoutGarden(st.entries, w, h);
      st.panX = Math.min(Math.max(0, st.panX), Math.max(0, layout.rowWidth - w));
    }

    function scrollTo(id) {
      const i = st.entries.findIndex((e) => e.plant.id === id);
      if (i < 0 || !layout) return;
      const spot = layout.spots[i];
      if (spot.x0 < st.panX || spot.x1 > st.panX + w) st.panX = Math.min(Math.max(0, spot.mid - w / 2), Math.max(0, layout.rowWidth - w));
    }

    function entryOf(id) {
      return st.entries.find((e) => e.plant.id === id) || null;
    }

    // --- modes and panels -------------------------------------------------
    function setMode(mode) {
      st.mode = mode;
      plantForm.hidden = mode !== "plant";
      crossBox.hidden = mode !== "cross";
      headRow.hidden = mode === "plant" || mode === "cross";
      if (mode !== "cross") st.picks = [];
      updateHead();
    }

    function updateHead() {
      const now = Date.now();
      const sky = skyAt(st.follow ? localHour() : st.hour);
      const clock = st.follow ? fmtClock(now) : `${String(Math.floor(st.hour)).padStart(2, "0")}:${String(Math.round((st.hour % 1) * 60)).padStart(2, "0")}`;
      when.textContent = `${sky.phase} · ${clock}`;
      const n = st.plants.length;
      const ahead = st.ahead ? ` Showing ${st.ahead} day${st.ahead === 1 ? "" : "s"} ahead.` : "";
      count.textContent = `${n} plant${n === 1 ? "" : "s"}, growing while nobody watches.${ahead}`;
      const full = n >= st.max;
      plantBtn.disabled = crossBtn.disabled = full;
      if (full) plantBtn.title = crossBtn.title = `The garden has room for ${st.max} plants`;
      if (st.mode === "cross") {
        crossText.textContent = st.picks.length === 0 ? "Click the first parent." : st.picks.length === 1 ? `${entryOf(st.picks[0])?.plant.name} and... click the second parent.` : `${entryOf(st.picks[0])?.plant.name} × ${entryOf(st.picks[1])?.plant.name}`;
        crossNameRow.hidden = st.picks.length < 2;
      }
      hint.textContent = st.mode === "cross" ? "Click two plants to cross" : st.selected ? "" : n ? "Click a plant to look closer" : "";
    }

    function startPlant() {
      select(null);
      seedName.value = suggestName(freshSeed());
      plantErr.hidden = true;
      setMode("plant");
      seedName.focus();
      seedName.select();
    }

    async function doPlant() {
      const name = seedName.value.trim();
      if (!name) return showErr(plantErr, "Give it a name first.");
      try {
        const plant = await ctx.api("plant", { method: "POST", body: { name, by: BY } });
        setMode("garden");
        await reload(plant.id);
        ctx.toast(`${plant.name} is in the ground. It comes up in a few hours.`);
      } catch (e) {
        showErr(plantErr, e.message);
      }
    }

    function startCross() {
      select(null);
      crossErr.hidden = true;
      setMode("cross");
    }

    function pickForCross(id) {
      if (st.picks.includes(id)) st.picks = st.picks.filter((p) => p !== id);
      else if (st.picks.length < 2) st.picks.push(id);
      if (st.picks.length === 2) {
        const [a, b] = st.picks.map((p) => entryOf(p).plant.name);
        crossName_.value = crossName(a, b);
      }
      updateHead();
      if (st.picks.length === 2) crossName_.focus();
    }

    async function doCross() {
      const name = crossName_.value.trim();
      if (st.picks.length < 2) return;
      if (!name) return showErr(crossErr, "Give the child a name first.");
      try {
        const plant = await ctx.api("cross", { method: "POST", body: { a: st.picks[0], b: st.picks[1], name, by: BY } });
        setMode("garden");
        await reload(plant.id);
        ctx.toast(`${plant.name} is planted: ${plant.parents.map((p) => p.name).join(" × ")}.`);
      } catch (e) {
        showErr(crossErr, e.message);
      }
    }

    function showErr(node, text) {
      node.textContent = text;
      node.hidden = false;
    }
    function showEdErr(text) {
      showErr(edErr, text);
    }

    function select(id) {
      if (st.selected !== id) {
        st.draft = null;
        pressForm.hidden = true;
        renameForm.hidden = true;
      }
      st.selected = id;
      if (id) scrollTo(id);
      renderInfo(true);
      updateHead();
    }

    let lastFacts = "";
    function renderInfo(full) {
      const entry = st.selected ? entryOf(st.selected) : null;
      info.el.hidden = !entry;
      if (!entry) return;
      const p = entry.plant;
      const shown = st.draft ? st.draft.entry : entry;
      const nowMs = Date.now();
      const aheadH = st.ahead * 24;
      const stage = L.growthStage(p, nowMs, shown.maxGen, aheadH);
      const gen = Math.floor(stage);
      const status = stage < 1 ? "still a seed" : stage >= shown.maxGen ? "full grown" : "growing";
      const parents = p.parents && p.parents.length ? p.parents.map((x) => x.name).join(" × ") : "none, a first seed";
      const next = nextGrowthText(stage, shown.maxGen, shown.genome.hours_per_gen);
      const rows = [
        ["Planted by", p.by],
        ["Planted", fmtDate(p.planted) + (p.head_start_hours ? ", as a seedling" : "")],
        ["Age", ageText(L.hoursGrown(p, nowMs, aheadH)) + (st.ahead ? " (time-lapse)" : "")],
        ["Generation", `${gen} of ${shown.maxGen}`],
        ["Parents", parents],
      ];
      if (next) rows.push(["Next", next.replace(/^next generation in /, "a generation in ")]);
      const key = JSON.stringify([p.name, rows, status, !!st.draft]);
      if (!full && key === lastFacts) return;
      lastFacts = key;
      nameLine.replaceChildren(p.name, el("span", { class: "ag-badge", text: st.draft ? "draft" : status }));
      facts.replaceChildren(...rows.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]));
      bar.firstChild.style.width = `${Math.round((stage / shown.maxGen) * 100)}%`;
      if (full) fillEditor(shown.genome);
    }

    // --- genome editor ------------------------------------------------------
    function fillEditor(genome) {
      axiomIn.value = genome.axiom;
      rulesIn.value = rulesText(genome.rules);
      for (const [k, s] of Object.entries(sliders)) s.set(genome[k]);
      for (const [k, s] of Object.entries(hues)) s.set(Math.round(genome.hues[k]));
      flowerSeg.set(genome.flower);
      edErr.hidden = true;
      plantDraft.disabled = undoDraft.disabled = !st.draft;
    }

    function editDraft(change) {
      const entry = entryOf(st.selected);
      if (!entry) return;
      const base = st.draft ? st.draft.genome : entry.plant.genome;
      const genome = JSON.parse(JSON.stringify(base));
      change(genome);
      genome.max_gen = Math.round(genome.max_gen);
      edErr.hidden = true;
      try {
        st.draft = { genome, entry: makeEntry(entry.plant, genome) };
      } catch (e) {
        return showEdErr(e.message);
      }
      plantDraft.disabled = undoDraft.disabled = false;
      renderInfo(false);
    }

    function clearDraft() {
      st.draft = null;
      renderInfo(true);
    }

    async function doPlantDraft() {
      const entry = entryOf(st.selected);
      if (!entry || !st.draft) return;
      try {
        const plant = await ctx.api("plant", {
          method: "POST",
          body: { name: suggestName(st.draft.genome.seed ^ 77), by: BY, genome: st.draft.genome },
        });
        await reload(plant.id);
        ctx.toast(`Planted the draft as ${plant.name}.`);
      } catch (e) {
        showEdErr(e.message);
      }
    }

    // --- pressing ------------------------------------------------------------
    function startPress() {
      const entry = entryOf(st.selected);
      if (!entry) return;
      renameForm.hidden = true;
      pressName.value = entry.plant.name;
      pressNote.value = "";
      pressForm.hidden = false;
      pressNote.focus();
    }

    function pressedData(entry) {
      const shown = st.draft ? st.draft.entry : entry;
      const p = entry.plant;
      return {
        kind: "pressed-plant",
        version: 1,
        plant: { id: p.id, name: p.name, by: p.by, planted: p.planted, parents: p.parents || null },
        genome: shown.genome,
        stage: Math.round(L.growthStage(p, Date.now(), shown.maxGen, st.ahead * 24) * 1000) / 1000,
        max_gen: shown.maxGen,
        pressed: new Date().toISOString(),
      };
    }

    async function doPress() {
      const entry = entryOf(st.selected);
      if (!entry) return;
      const data = pressedData(entry);
      const sheet = makeCanvas();
      sheet.width = 300;
      sheet.height = 400;
      drawPressedData(sheet.getContext("2d"), 300, 400, data);
      try {
        await ctx.keep({ name: pressName.value.trim() || entry.plant.name, note: pressNote.value.trim(), data, thumb: ctx.thumb(sheet) });
        pressForm.hidden = true;
        ctx.toast(`Pressed ${entry.plant.name}. It is on the keepsake wall.`);
      } catch (e) {
        ctx.toast(`Could not keep it: ${e.message}`);
      }
    }

    function startRename() {
      const entry = entryOf(st.selected);
      if (!entry) return;
      pressForm.hidden = true;
      renameInput.value = entry.plant.name;
      renameErr.hidden = true;
      renameForm.hidden = false;
      renameInput.focus();
      renameInput.select();
    }

    async function doRename() {
      try {
        const plant = await ctx.api("rename", { method: "POST", body: { id: st.selected, name: renameInput.value } });
        renameForm.hidden = true;
        await reload(plant.id);
      } catch (e) {
        showErr(renameErr, e.message);
      }
    }

    // --- the pressed view ------------------------------------------------------
    function showPressed(keepsake) {
      const data = keepsake.data || {};
      if (!data.genome) throw new Error("this keepsake holds no plant");
      st.pressed = keepsake;
      st.mode = "pressed";
      pressedSheet = null;
      wrap.classList.add("is-pressed");
      pressedPanel.el.hidden = false;
      pTitle.replaceChildren(keepsake.name, el("span", { class: "ag-badge", text: keepsake.seed ? "seed" : "pressed" }));
      const plantName = data.plant && data.plant.name && data.plant.name !== keepsake.name ? `${data.plant.name}, ` : "";
      pMeta.textContent = `${plantName}pressed by ${keepsake.author || "someone"}${keepsake.made ? ", " + fmtDate(keepsake.made) : ""}`;
      pNote.textContent = keepsake.note || "";
      pNote.hidden = !keepsake.note;
    }

    function leavePressed() {
      st.pressed = null;
      pressedSheet = null;
      wrap.classList.remove("is-pressed");
      pressedPanel.el.hidden = true;
      setMode("garden");
      if (location.hash.includes("/")) history.replaceState(null, "", `#${ctx.id}`);
    }

    // --- input -------------------------------------------------------------------
    function hit(px, py) {
      if (!layout) return null;
      const x = px + st.panX;
      for (let i = 0; i < st.entries.length; i++) {
        const s = layout.spots[i];
        if (x < s.x0 || x > s.x1) continue;
        const e = st.entries[i];
        const top = layout.ground - Math.max(40, (e.drawnHeight || 0) + 16);
        if (py >= top && py <= layout.ground + 34) return e.plant.id;
      }
      return null;
    }

    let down = null;
    const onDown = (e) => {
      down = { x: e.clientX, y: e.clientY, pan: st.panX, moved: false };
      canvas.setPointerCapture(e.pointerId);
    };
    const onMove = (e) => {
      const r = canvas.getBoundingClientRect();
      if (down) {
        const dx = e.clientX - down.x;
        if (Math.abs(dx) > 5 || Math.abs(e.clientY - down.y) > 5) down.moved = true;
        if (down.moved && layout && layout.rowWidth > w) st.panX = Math.min(Math.max(0, down.pan - dx), layout.rowWidth - w);
        return;
      }
      if (st.mode === "pressed") return;
      st.hover = hit(e.clientX - r.left, e.clientY - r.top);
      canvas.style.cursor = st.hover ? "pointer" : layout && layout.rowWidth > w ? "grab" : "default";
    };
    const onUp = (e) => {
      const was = down;
      down = null;
      if (!was || was.moved || st.mode === "pressed") return;
      const r = canvas.getBoundingClientRect();
      const id = hit(e.clientX - r.left, e.clientY - r.top);
      if (st.mode === "cross") {
        if (id) pickForCross(id);
        return;
      }
      if (st.mode === "plant") setMode("garden");
      select(id);
    };
    const onWheel = (e) => {
      if (!layout || layout.rowWidth <= w || st.mode === "pressed") return;
      e.preventDefault();
      const d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      st.panX = Math.min(Math.max(0, st.panX + d), layout.rowWidth - w);
    };
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointerleave", () => (st.hover = null));
    canvas.addEventListener("wheel", onWheel, { passive: false });

    const onKey = (e) => {
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.altKey || e.ctrlKey || e.metaKey || st.mode === "pressed" || !st.entries.length) return;
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      const i = st.entries.findIndex((x) => x.plant.id === st.selected);
      const n = st.entries.length;
      const next = i < 0 ? (e.key === "ArrowRight" ? 0 : n - 1) : (i + (e.key === "ArrowRight" ? 1 : -1) + n) % n;
      select(st.entries[next].plant.id);
    };
    window.addEventListener("keydown", onKey);

    off.push(
      ctx.onMode((adv) => {
        if (adv) return;
        st.ahead = 0;
        aheadSlider.set(0);
        st.follow = true;
        followToggle.set(true);
        st.draft = null;
        renderInfo(true);
      }),
    );

    // --- size ----------------------------------------------------------------------
    function resize() {
      const r = root.getBoundingClientRect();
      w = Math.max(1, Math.round(r.width));
      h = Math.max(1, Math.round(r.height));
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      bgKey = "";
      pressedSheet = null;
      relayout();
    }
    const ro = new ResizeObserver(resize);
    ro.observe(root);
    resize();

    // --- drawing ----------------------------------------------------------------------
    function background(sky) {
      const key = `${w}x${h}@${dpr}:${Math.round(sky.hour * 40)}`;
      if (key !== bgKey || !bg) {
        bg = bg || makeCanvas();
        bg.width = canvas.width;
        bg.height = canvas.height;
        const b = bg.getContext("2d");
        b.setTransform(dpr, 0, 0, dpr, 0, 0);
        D.drawBackground(b, w, h, sky, layout.ground);
        bgKey = key;
      }
      return bg;
    }

    function labels(gx, entry, spot, ground) {
      const id = entry.plant.id;
      const sel = id === st.selected;
      const picked = st.picks.includes(id);
      const hov = id === st.hover;
      gx.font = `italic ${sel ? 13.5 : 12.5}px Georgia, "Noto Serif", serif`;
      gx.textAlign = "center";
      gx.textBaseline = "top";
      gx.fillStyle = picked ? "#c9b8ff" : sel ? "#ffc56e" : hov ? "rgba(255,240,220,0.95)" : "rgba(255,236,210,0.62)";
      const width = spot.x1 - spot.x0 - 10;
      let name = entry.plant.name;
      while (name.length > 3 && gx.measureText(name).width > width) name = name.slice(0, -2);
      if (name !== entry.plant.name) name = name.trimEnd() + "…";
      gx.fillText(name, spot.mid, ground + 14);
      if (sel || hov) {
        gx.font = "11px system-ui, sans-serif";
        gx.fillStyle = "rgba(255,236,210,0.5)";
        gx.fillText(`gen ${Math.floor(entry.stage || 0)} of ${entry.maxGen}`, spot.mid, ground + 31);
      }
      gx.textAlign = "start";
    }

    function drawPressedData(gx, cw, chh, data) {
      const genome = data.genome;
      const maxGen = Math.max(1, Math.min(data.max_gen || genome.max_gen, L.effectiveMaxGen(genome)));
      const stage = Math.min(maxGen, Math.max(0, Number(data.stage) || 0));
      const geo = L.plantGeometry(genome, stage, maxGen);
      const bounds = { minX: geo.minX, maxX: geo.maxX, maxY: Math.max(geo.maxY, 1) };
      const plant = data.plant || {};
      D.drawPressed(gx, cw, chh, geo, genome, {
        name: plant.name || "A pressed plant",
        by: plant.by || "someone",
        stage,
        maxGen,
        parents: plant.parents && plant.parents.length ? plant.parents.map((p) => p.name).join(" × ") : "",
        pressed: data.pressed ? fmtDate(data.pressed) : "",
      }, bounds);
    }

    let lastInfo = 0;
    const loop = ctx.loop((t) => {
      if (!layout) return;
      const secs = t / 1000;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (st.mode === "pressed" && st.pressed) {
        if (!pressedSheet) {
          pressedSheet = pressedSheet || makeCanvas();
          pressedSheet.width = canvas.width;
          pressedSheet.height = canvas.height;
          const p = pressedSheet.getContext("2d");
          p.setTransform(dpr, 0, 0, dpr, 0, 0);
          p.fillStyle = "#130f16";
          p.fillRect(0, 0, w, h);
          const reserve = w > 760 ? Math.min(320, w * 0.34) : 0;
          p.translate(reserve, 0);
          drawPressedData(p, w - reserve, h, st.pressed.data);
        }
        g.setTransform(1, 0, 0, 1, 0, 0);
        g.drawImage(pressedSheet, 0, 0);
        return;
      }
      const hour = st.follow ? localHour() : st.hour;
      const sky = skyAt(hour);
      const rings = new Map();
      if (st.selected) rings.set(st.selected, "rgba(255,180,84,0.28)");
      for (const id of st.picks) rings.set(id, "rgba(165,139,255,0.35)");
      const entries = st.draft ? st.entries.map((e) => (e.plant.id === st.selected ? st.draft.entry : e)) : st.entries;
      drawScene(g, w, h, {
        entries,
        layout,
        sky,
        t: secs,
        nowMs: Date.now(),
        ahead: st.ahead * 24,
        wind: st.wind,
        bg: background(sky),
        panX: st.panX,
        stars,
        rings,
        labels,
      });
      if (t - lastInfo > 1000) {
        lastInfo = t;
        renderInfo(false);
        updateHead();
      }
    });

    setMode("garden");
    try {
      const res = await reload();
      const fresh = res.plants.length && res.plants.every((p) => Date.now() - Date.parse(p.planted) < 60000 && p.by.startsWith("Claude"));
      if (fresh) ctx.toast("Claude planted a few starters for you. Come back tomorrow: they grow while you are away.");
    } catch (e) {
      ctx.toast(`The garden did not load: ${e.message}`);
    }

    return {
      unmount() {
        loop.stop();
        ro.disconnect();
        window.removeEventListener("keydown", onKey);
        for (const fn of off) fn();
      },
      open(keepsake) {
        showPressed(keepsake);
      },
      onEscape() {
        if (st.mode === "pressed") {
          leavePressed();
          return true;
        }
        if (!pressForm.hidden || !renameForm.hidden) {
          pressForm.hidden = renameForm.hidden = true;
          return true;
        }
        if (st.mode === "plant" || st.mode === "cross") {
          setMode("garden");
          return true;
        }
        if (st.selected) {
          select(null);
          return true;
        }
        return false;
      },
    };
  },

  async preview(canvas, keepsake) {
    const g = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    if (keepsake && keepsake.data && keepsake.data.genome) {
      const data = keepsake.data;
      const genome = data.genome;
      const maxGen = Math.max(1, Math.min(data.max_gen || genome.max_gen, L.effectiveMaxGen(genome)));
      const stage = Math.min(maxGen, Math.max(0, Number(data.stage) || 0));
      const geo = L.plantGeometry(genome, stage, maxGen);
      D.drawPressed(g, w, h, geo, genome, { name: keepsake.name, by: (data.plant && data.plant.by) || "", stage, maxGen, parents: "", pressed: "" }, {
        minX: geo.minX,
        maxX: geo.maxX,
        maxY: Math.max(1, geo.maxY),
      });
      return;
    }
    const shipped = await starters();
    const now = Date.now();
    const picks = shipped.plants.slice(0, 3);
    const entries = picks.map((row, i) => {
      const plant = { id: `s${i}`, name: row.name, planted: new Date(now - DAY_MS * 3).toISOString(), head_start_hours: 0, genome: row.genome };
      return makeEntry(plant);
    });
    // a scale that reads at card size: CSS-ish units from the canvas height
    const unit = h / 180;
    g.save();
    g.scale(unit, unit);
    const cw = w / unit;
    const ch = h / unit;
    const sky = skyAt(19.6);
    const layout = D.layoutGarden(entries, cw, ch, 40);
    drawScene(g, cw, ch, { entries, layout, sky, t: 1.3, nowMs: now, ahead: 0, wind: 0.6, bg: null, stars: D.makeStars(60) });
    g.restore();
  },
};
