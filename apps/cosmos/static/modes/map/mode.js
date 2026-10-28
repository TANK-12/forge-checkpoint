/* Map mode: the real solar system for any date, out to the galaxy.
 *
 * Owns the interaction and the panels; view.js owns the 3D scene. Everything
 * about a body (its orbit, size, colour, blurb) comes from data/bodies/*.json
 * through /api/bodies, so this file never names a planet except the Sun and
 * Earth, which it needs as reference points for distances.
 */

import { Ephemeris } from "../../core/ephemeris.js";
import { moonPhase, nextElongation } from "../../core/events.js";
import { CONSTELLATIONS, prettyStarName } from "../../core/constellations.js";
import { bvToTemperature } from "../../core/color.js";
import { galacticCenterEcliptic, galacticToEcliptic, SUN_TO_CENTER_PC } from "../../core/galaxy.js";
import {
  AU_KM,
  LIGHT_YEAR_AU,
  PARSEC_AU,
  PARSEC_LY,
  formatDistance,
  formatDuration,
  jdFromMs,
  msFromJd,
} from "../../core/units.js";
import { MapView, fromThree } from "./view.js";

const G_KM3_KG_S2 = 6.6743e-20;
const EARTH_MASS_KG = 5.9722e24;
const MIN_JD = jdFromMs(Date.UTC(1600, 0, 1));
const MAX_JD = jdFromMs(Date.UTC(2400, 0, 1));
const VALID_FROM = jdFromMs(Date.UTC(1800, 0, 1));
const VALID_TO = jdFromMs(Date.UTC(2050, 0, 1));
const MAX_DIST = 1.2e10;

const RATES = [
  { days: 1 / 86400, label: "real time" },
  { days: 60 / 86400, label: "1 minute per second" },
  { days: 1 / 24, label: "1 hour per second" },
  { days: 1, label: "1 day per second" },
  { days: 7, label: "1 week per second" },
  { days: 30.4375, label: "1 month per second" },
  { days: 365.25, label: "1 year per second" },
  { days: 3652.5, label: "10 years per second" },
];

const KIND_LABEL = { star: "Star", planet: "Planet", dwarf: "Dwarf planet", moon: "Moon" };
const KIND_PRIORITY = { star: 100, planet: 80, dwarf: 60, moon: 40 };

const JUMPS = [
  { id: "planet", label: "Earth", title: "Fly to Earth and its Moon" },
  { id: "system", label: "Solar system", title: "The whole planetary system" },
  { id: "kuiper", label: "Kuiper Belt", title: "Out to Pluto and Eris" },
  { id: "stars", label: "Nearby stars", title: "The Sun among its neighbours" },
  { id: "galaxy", label: "Milky Way", title: "The whole galaxy (a model)" },
];

const HTML = `
  <div class="map">
    <div class="map-canvas"></div>
    <div class="map-labels"></div>
    <header class="hud map-top">
      <button class="btn" data-act="back" title="Back to the menu (Esc)">← Menu</button>
      <div class="search">
        <input type="search" placeholder="Find a planet, moon or star  /" spellcheck="false" autocomplete="off">
        <div class="search-results" hidden></div>
      </div>
      <div class="row">
        <button class="btn small" data-act="reverse" title="Run time backwards">◀◀</button>
        <button class="btn small" data-act="play" title="Play or pause (space)">❚❚</button>
        <button class="btn small" data-act="slower" title="Slower ([)">−</button>
        <button class="btn small" data-act="faster" title="Faster (])">+</button>
        <button class="btn small" data-act="now" title="Back to right now (n)">Now</button>
      </div>
      <div>
        <div class="map-clock"></div>
        <div class="map-rate"></div>
      </div>
      <input type="datetime-local" class="map-date" title="Jump to a date and time (UTC)">
      <span class="map-range warn" hidden>Positions are approximate outside 1800 to 2050</span>
    </header>
    <aside class="hud map-layers">
      <h3>Show</h3>
      <label><input type="checkbox" data-opt="showOrbits" checked> Orbits <kbd>o</kbd></label>
      <label><input type="checkbox" data-opt="showLabels" checked> Labels <kbd>l</kbd></label>
      <label><input type="checkbox" data-opt="showStars" checked> Stars</label>
      <label><input type="checkbox" data-opt="showGalaxy" checked> Galaxy model</label>
      <label><input type="checkbox" data-opt="trueScale"> True sizes <kbd>t</kbd></label>
      <h3>Star brightness</h3>
      <label class="slider-row">
        <span title="Stars fainter than this magnitude are hidden. 6.5 is what an eye sees on a dark night.">Faintest magnitude</span>
        <input type="number" min="3" max="11" step="0.1" value="6.5" data-opt="starLimit">
        <input type="range" min="3" max="11" step="0.1" value="6.5" data-opt="starLimit" aria-label="Faintest star shown">
      </label>
      <span class="muted stars-note"></span>
      <button class="btn small get-stars" hidden>Get the stars</button>
      <button class="btn small" data-act="help">Keys and controls <kbd>?</kbd></button>
    </aside>
    <aside class="hud map-info" hidden></aside>
    <footer class="hud map-bottom">
      <span class="map-scale"></span>
      <span class="row jumps"></span>
      <span class="map-credit"></span>
    </footer>
    <div class="hud help" hidden>
      <h2>Getting around</h2>
      <dl>
        <dt>Drag</dt><dd>Turn the view around what you are looking at</dd>
        <dt>Right drag or shift drag</dt><dd>Slide the view sideways</dd>
        <dt>Scroll</dt><dd>Zoom, all the way from a moon to the whole galaxy</dd>
        <dt>Click</dt><dd>Details for a planet, moon or star</dd>
        <dt>Double click, or <kbd>c</kbd></dt><dd>Fly to it and follow it</dd>
        <dt><kbd>/</kbd></dt><dd>Search by name</dd>
        <dt><kbd>space</kbd></dt><dd>Pause or play time</dd>
        <dt><kbd>[</kbd> <kbd>]</kbd></dt><dd>Slower or faster time; <kbd>r</kbd> runs it backwards</dd>
        <dt><kbd>n</kbd></dt><dd>Back to the present moment</dd>
        <dt><kbd>h</kbd></dt><dd>Home: the whole solar system</dd>
        <dt><kbd>o</kbd> <kbd>l</kbd> <kbd>t</kbd></dt><dd>Orbits, labels, true sizes</dd>
        <dt><kbd>f</kbd></dt><dd>Full screen</dd>
        <dt><kbd>Esc</kbd></dt><dd>Close details, then back to the menu</dd>
      </dl>
    </div>
  </div>`;

function ease(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

function fmtNumber(n, digits = 3) {
  if (!Number.isFinite(n)) return "unknown";
  const abs = Math.abs(n);
  if (abs !== 0 && (abs >= 1e7 || abs < 1e-3)) {
    const [m, e] = n.toExponential(2).split("e");
    return `${m} × 10${superscript(Number(e))}`;
  }
  return n.toLocaleString("en-US", { maximumSignificantDigits: digits });
}

function superscript(n) {
  const map = { "-": "⁻", 0: "⁰", 1: "¹", 2: "²", 3: "³", 4: "⁴", 5: "⁵", 6: "⁶", 7: "⁷", 8: "⁸", 9: "⁹" };
  return String(n).split("").map((c) => map[c]).join("");
}

function lightTime(au) {
  const seconds = au * 499.00478;
  if (seconds < 60) return `${seconds.toFixed(1)} seconds`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)} minutes`;
  if (seconds < 86400 * 2) return `${(seconds / 3600).toFixed(1)} hours`;
  return formatDuration(seconds / 86400);
}

export default {
  async mount(root, ctx) {
    root.innerHTML = HTML;
    const $ = (sel) => root.querySelector(sel);
    const bodyList = (await ctx.api("/api/bodies")).bodies;
    const eph = new Ephemeris(bodyList);
    const view3d = new MapView($(".map-canvas"), eph);

    const state = {
      jd: jdFromMs(Date.now()),
      playing: true,
      rateIndex: 0,
      direction: 1,
      view: { target: [0, 0, 0], dist: 45, yaw: -0.5, pitch: 0.5 },
      focus: { type: "body", id: "sun" },
      selected: null,
      flight: null,
      opts: {
        showOrbits: true,
        showLabels: true,
        showStars: true,
        showGalaxy: true,
        trueScale: false,
        starLimit: 6.5,
      },
    };
    let starNames = [];
    let starByIndex = new Map();
    let catalog = null;

    /* --- star catalog, loaded after the first frames are up --------------- */
    const starsNote = $(".stars-note");
    const getStars = $(".get-stars");
    let fetchTimer = 0;
    let gone = false; // left the map: stop asking about the download
    // No catalog yet (a fresh install): say so and offer the download. While
    // it runs the note follows the server, then the stars load in place.
    function offerStars(c) {
      const f = c.fetch || {};
      getStars.hidden = f.state === "getting";
      getStars.disabled = f.state === "getting";
      starsNote.textContent = f.state === "getting" || f.state === "error" ? f.message : c.hint || "No star catalog yet.";
      clearTimeout(fetchTimer);
      if (f.state === "getting" && !gone) fetchTimer = setTimeout(loadStars, 2000);
    }
    getStars.addEventListener("click", () => {
      getStars.disabled = true;
      ctx
        .api("/api/catalog/get", { method: "POST" })
        .then(loadStars)
        .catch((err) => {
          getStars.disabled = false;
          starsNote.textContent = `The download could not start: ${err.message}`;
        });
    });
    function loadStars() {
      return ctx
        .api("/api/catalog")
        .then(async (c) => {
          if (gone) return;
          catalog = c;
          $(".map-credit").textContent = `Positions: JPL. ${c.credit}.`;
          if (!c.available) return offerStars(c);
          getStars.hidden = true;
          starsNote.textContent = `Loading ${c.count.toLocaleString("en-US")} stars…`;
          const [buffer, names] = await Promise.all([ctx.apiBuffer("/api/stars"), ctx.api("/api/star-names")]);
          if (gone) return;
          const count = view3d.setStars(buffer);
          starNames = names.stars.map((s) => ({ ...s, display: s.proper ? s.name : prettyStarName(s.name) }));
          starByIndex = new Map(starNames.map((s) => [s.i, s]));
          starsNote.textContent = `${count.toLocaleString("en-US")} stars`;
        })
        .catch((err) => {
          starsNote.textContent = `Stars could not load: ${err.message}`;
        });
    }
    loadStars();

    /* --- where things are ------------------------------------------------- */

    function focusPosition(f = state.focus) {
      if (!f) return null;
      if (f.type === "body") return eph.position(f.id, state.jd);
      if (f.type === "star") return view3d.starPosition(f.index);
      if (f.type === "fixed") return f.position;
      return null;
    }

    function flyTo(focus, { dist, yaw, pitch, duration = 1400 } = {}) {
      state.focus = focus;
      // asked for less motion: arrive at once instead of sweeping there
      const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      state.flight = {
        t0: performance.now(),
        duration: still ? 1 : duration,
        from: { ...state.view, target: [...state.view.target] },
        dist: Math.min(Math.max(dist ?? state.view.dist, 1e-7), MAX_DIST),
        yaw,
        pitch,
      };
    }

    function viewDistanceFor(body) {
      const kids = eph.children(body.id);
      if (body.id === "sun") return 45;
      if (kids.length) {
        const far = Math.max(...kids.map((k) => (k.elements.a_km ?? 0) / AU_KM));
        return far * 3.2;
      }
      return (body.radius_km / AU_KM) * 9;
    }

    function jump(id) {
      const earth = eph.get("earth");
      if (id === "planet") flyTo({ type: "body", id: "earth" }, { dist: viewDistanceFor(earth) });
      if (id === "system") flyTo({ type: "body", id: "sun" }, { dist: 45, pitch: 0.55 });
      if (id === "kuiper") flyTo({ type: "body", id: "sun" }, { dist: 190, pitch: 0.7 });
      if (id === "stars") flyTo({ type: "body", id: "sun" }, { dist: 12 * PARSEC_AU, pitch: 0.4, duration: 2200 });
      if (id === "galaxy") {
        const gc = galacticCenterEcliptic().map((v) => v * PARSEC_AU);
        const target = gc.map((v) => v * 0.5);
        const opts = { dist: 3.4 * SUN_TO_CENTER_PC * PARSEC_AU, duration: 2600, ...galaxyPoleAngles() };
        flyTo({ type: "fixed", position: target }, opts);
      }
    }

    /* Yaw and pitch that put the camera above the galactic plane: mostly
     * toward the galactic north pole, tipped a little toward the centre. */
    function galaxyPoleAngles() {
      const ecl = galacticToEcliptic([0.4, 0, 0.9]);
      const len = Math.hypot(...ecl);
      const t = [ecl[0] / len, ecl[2] / len, -ecl[1] / len];
      return { yaw: Math.atan2(t[0], t[2]), pitch: Math.asin(t[1]) };
    }

    /* --- labels ------------------------------------------------------------- */

    const labelLayer = $(".map-labels");
    const labelPool = new Map();
    function label(key, text, cls, color) {
      let el = labelPool.get(key);
      if (!el) {
        el = document.createElement("div");
        el.className = `lbl ${cls}`;
        el.innerHTML = "<i></i><span></span>";
        el.querySelector("span").textContent = text;
        if (color) el.querySelector("i").style.background = color;
        else el.querySelector("i").remove();
        labelLayer.appendChild(el);
        labelPool.set(key, el);
      }
      return el;
    }

    let starLabelCache = { at: 0, list: [] };
    function brightestStarsFromCamera() {
      const now = performance.now();
      if (now - starLabelCache.at < 250) return starLabelCache.list;
      const cam = view3d.cameraWorld(state.view).map((v) => v / PARSEC_AU);
      const ranked = [];
      for (const s of starNames) {
        if (!s.proper) continue;
        const p = view3d.starPosition(s.i).map((v) => v / PARSEC_AU);
        const d = Math.max(Math.hypot(p[0] - cam[0], p[1] - cam[1], p[2] - cam[2]), 1e-6);
        ranked.push({ s, m: s.absmag + 5 * Math.log10(d) - 5 });
      }
      ranked.sort((a, b) => a.m - b.m);
      starLabelCache = { at: now, list: ranked.slice(0, 40) };
      return starLabelCache.list;
    }

    function drawLabels() {
      const placed = [];
      const wanted = [];
      const selId = state.selected?.type === "body" ? state.selected.id : null;
      if (state.opts.showLabels) {
        for (const body of bodyList) {
          const info = view3d.screen.get(body.id);
          if (!info?.visible) continue;
          if (body.kind === "moon" && (info.crowded || (info.orbitPx ?? 0) < 26) && selId !== body.id) continue;
          if (body.kind !== "star" && view3d.systemFade < 0.3) continue;
          wanted.push({
            key: `b:${body.id}`,
            text: body.name,
            cls: body.kind === "moon" ? "moon" : "body",
            x: info.x + Math.max(info.r, 3) + 3,
            y: info.y,
            pri: selId === body.id ? 1000 : KIND_PRIORITY[body.kind],
            selected: selId === body.id,
          });
        }
        if (view3d.stars && view3d.sunDistance > 300 && view3d.galaxyFade < 0.6) {
          for (const { s, m } of brightestStarsFromCamera()) {
            if (m > state.opts.starLimit - 1) continue;
            const scr = view3d.project(view3d.starPosition(s.i), state.view);
            if (!scr) continue;
            const sel = state.selected?.type === "star" && state.selected.index === s.i;
            wanted.push({ key: `s:${s.i}`, text: s.display, cls: "star", x: scr.x + 6, y: scr.y, pri: sel ? 999 : 30 - m, selected: sel });
          }
        }
        if (view3d.galaxyFade > 0.3) {
          for (const [i, g] of view3d.galaxyModel.labels.entries()) {
            const scr = view3d.project(g.position.map((v) => v * PARSEC_AU), state.view);
            if (scr) wanted.push({ key: `g:${i}`, text: g.name, cls: "galaxy", x: scr.x, y: scr.y, pri: 20 - i });
          }
          const sunScr = view3d.project([0, 0, 0], state.view);
          if (sunScr) wanted.push({ key: "g:sun", text: "The Sun is here", cls: "galaxy", color: "#ffd27a", x: sunScr.x + 4, y: sunScr.y, pri: 50 });
        }
      }
      if (state.selected?.type === "star" && !wanted.some((w) => w.selected)) {
        const s = starByIndex.get(state.selected.index);
        const scr = s && view3d.project(view3d.starPosition(s.i), state.view);
        if (scr) wanted.push({ key: `s:${s.i}`, text: s.display, cls: "star", x: scr.x + 6, y: scr.y, pri: 999, selected: true });
      }
      wanted.sort((a, b) => b.pri - a.pri);
      const seen = new Set();
      for (const w of wanted) {
        const width = w.text.length * 6.6 + (w.color ? 12 : 2);
        const box = { x0: w.x, x1: w.x + width, y0: w.y - 8, y1: w.y + 8 };
        if (w.x < -width || w.x > view3d.width || w.y < -10 || w.y > view3d.height + 10) continue;
        if (placed.some((b) => box.x0 < b.x1 && box.x1 > b.x0 && box.y0 < b.y1 && box.y1 > b.y0)) continue;
        placed.push(box);
        const el = label(w.key, w.text, w.cls, w.color);
        el.style.transform = `translate(${w.x.toFixed(1)}px, ${(w.y - 8).toFixed(1)}px)`;
        el.classList.toggle("selected", !!w.selected);
        el.hidden = false;
        seen.add(w.key);
      }
      for (const [key, el] of labelPool) if (!seen.has(key)) el.hidden = true;
    }

    /* --- details panel ----------------------------------------------------- */

    const info = $(".map-info");
    let infoKey = "";
    let infoFacts = null;

    function select(sel, { fly = false } = {}) {
      state.selected = sel;
      if (!sel) {
        info.hidden = true;
        infoKey = "";
        return;
      }
      if (sel.type === "body") renderBodyInfo(eph.get(sel.id));
      if (sel.type === "star") renderStarInfo(starByIndex.get(sel.index));
      info.hidden = false;
      if (fly) goToSelected();
    }

    function goToSelected() {
      const sel = state.selected;
      if (!sel) return;
      if (sel.type === "body") flyTo({ type: "body", id: sel.id }, { dist: viewDistanceFor(eph.get(sel.id)) });
      if (sel.type === "star") flyTo({ type: "star", index: sel.index }, { dist: 3e5, duration: 2200 });
    }

    function renderBodyInfo(body) {
      infoKey = `b:${body.id}`;
      const kids = eph.children(body.id);
      const parent = body.parent ? eph.get(body.parent) : null;
      info.innerHTML = `
        <h2></h2>
        <div class="kind"></div>
        <p class="summary"></p>
        <dl class="facts"></dl>
        <div class="chips"></div>
        <div class="row" style="margin-top:12px">
          <button class="btn" data-act="goto">Fly here and follow <kbd>c</kbd></button>
          <button class="btn" data-act="close">Close</button>
        </div>`;
      info.querySelector("h2").textContent = body.name;
      info.querySelector(".kind").textContent =
        (KIND_LABEL[body.kind] || body.kind) + (parent && parent.id !== "sun" ? ` of ${parent.name}` : "");
      info.querySelector(".summary").textContent = body.summary || "";
      const chips = info.querySelector(".chips");
      for (const k of kids) {
        const b = document.createElement("button");
        b.className = "btn small";
        b.textContent = k.name;
        b.onclick = () => select({ type: "body", id: k.id }, { fly: true });
        chips.appendChild(b);
      }
      if (body.notes) {
        const note = document.createElement("p");
        note.className = "muted";
        note.textContent = body.notes;
        info.appendChild(note);
      }
      const source = document.createElement("p");
      source.className = "muted";
      source.style.fontSize = "11px";
      source.textContent = body.elements ? `Orbit: ${body.elements.source}.` : "";
      info.appendChild(source);
      infoFacts = () => bodyFacts(body);
      updateFacts();
    }

    function bodyFacts(body) {
      const jd = state.jd;
      const p = eph.position(body.id, jd);
      const earth = eph.position("earth", jd);
      const rows = [];
      const toEarth = Math.hypot(p[0] - earth[0], p[1] - earth[1], p[2] - earth[2]);
      if (body.id !== "sun") rows.push(["From the Sun", formatDistance(Math.hypot(...p))]);
      if (body.id !== "earth") {
        rows.push(["From Earth", formatDistance(toEarth)]);
        rows.push(["Light from Earth takes", lightTime(toEarth)]);
      }
      if (body.elements) {
        const dt = 0.01;
        const a = eph.orbitalOffset(body.id, jd - dt);
        const b = eph.orbitalOffset(body.id, jd + dt);
        const kms = (Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]) / (2 * dt)) * (AU_KM / 86400);
        const around = eph.get(body.parent);
        rows.push([`Orbital speed around ${around.name}`, `${kms.toFixed(kms < 10 ? 2 : 1)} km/s`]);
        rows.push(["One orbit takes", formatDuration(eph.periodDays(body.id, jd))]);
      }
      rows.push(...skyEvents(body, p));
      rows.push(["Radius", `${fmtNumber(body.radius_km, 4)} km`]);
      if (body.gm_km3_s2) {
        const kg = body.gm_km3_s2 / G_KM3_KG_S2;
        rows.push(["Mass", `${fmtNumber(kg)} kg`]);
        rows.push(["Mass in Earths", fmtNumber(kg / EARTH_MASS_KG)]);
      }
      return rows;
    }

    /* What is coming up for this body in Earth's sky: the phase and the next
     * full and new moon for Earth's own moon, the next opposition for a
     * planet beyond Earth. Each answer is kept until the clock passes it. */
    const nextCache = new Map();
    function upcoming(id, target, search) {
      const key = `${id}:${target}`;
      const hit = nextCache.get(key);
      if (hit && hit.at !== null && state.jd >= hit.from && state.jd < hit.at) return hit.at;
      const at = nextElongation(eph, id, target, state.jd, search);
      nextCache.set(key, { from: state.jd, at });
      return at;
    }
    const when = (at) =>
      at === null
        ? "not in the next two years"
        : `${new Date(msFromJd(at)).toISOString().slice(0, 16).replace("T", " ")} UTC, in ${formatDuration(at - state.jd)}`;

    function skyEvents(body, p) {
      if (body.parent === "earth") {
        const phase = moonPhase(eph, state.jd, body.id);
        const month = { step: 0.5, within: 31 };
        return [
          ["Phase", `${phase.name}, ${Math.round(phase.lit * 100)}% lit`],
          ["Next full moon", when(upcoming(body.id, 180, month))],
          ["Next new moon", when(upcoming(body.id, 0, month))],
        ];
      }
      if (body.parent === "sun" && body.id !== "earth" && Math.hypot(...p) > 1.2) {
        return [["Next opposition, best seen", when(upcoming(body.id, 180, { step: 2, within: 800 }))]];
      }
      return [];
    }

    function renderStarInfo(s) {
      if (!s) return;
      infoKey = `s:${s.i}`;
      const ly = s.dist_pc * PARSEC_LY;
      const temp = view3d.starRecords ? bvToTemperature(view3d.starRecords[s.i * 6 + 5]) : null;
      info.innerHTML = `
        <h2></h2>
        <div class="kind"></div>
        <p class="summary"></p>
        <dl class="facts"></dl>
        <div class="row" style="margin-top:12px">
          <button class="btn" data-act="goto">Fly here <kbd>c</kbd></button>
          <button class="btn" data-act="close">Close</button>
        </div>
        <p class="muted" style="font-size:11px"></p>`;
      info.querySelector("h2").textContent = s.display;
      const con = CONSTELLATIONS[s.con];
      info.querySelector(".kind").textContent = `Star${s.spect ? `, type ${s.spect}` : ""}${con ? `, in ${con}` : ""}`;
      const year = new Date().getUTCFullYear() - ly;
      info.querySelector(".summary").textContent =
        ly < 1
          ? ""
          : `The light reaching Earth tonight left this star ${
              ly < 1000 ? `${ly.toFixed(ly < 20 ? 1 : 0)} years ago, around the year ${Math.round(year) > 0 ? Math.round(year) : `${Math.round(-year)} BCE`}` : `about ${Math.round(ly).toLocaleString("en-US")} years ago`
            }.`;
      info.querySelector("p.muted").textContent = catalog?.credit || "";
      infoFacts = () => {
        const rows = [
          ["Distance", `${ly < 100 ? ly.toFixed(2) : Math.round(ly).toLocaleString("en-US")} light-years`],
          ["Brightness from Earth", `magnitude ${s.mag.toFixed(2)}`],
          ["Absolute magnitude", s.absmag.toFixed(2)],
        ];
        if (s.lum) rows.push(["Luminosity", `${fmtNumber(s.lum)} × the Sun`]);
        if (temp) rows.push(["Surface temperature", `about ${Math.round(temp / 100) * 100} K`]);
        if (s.name !== s.display) rows.push(["Catalogue name", s.name]);
        return rows;
      };
      updateFacts();
    }

    function updateFacts() {
      if (!infoFacts || info.hidden) return;
      const dl = info.querySelector(".facts");
      if (!dl) return;
      dl.replaceChildren(
        ...infoFacts().flatMap(([k, v]) => {
          const dt = document.createElement("dt");
          dt.textContent = k;
          const dd = document.createElement("dd");
          dd.textContent = v;
          return [dt, dd];
        }),
      );
    }

    info.addEventListener("click", (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (act === "goto") goToSelected();
      if (act === "close") select(null);
    });

    /* --- picking ------------------------------------------------------------- */

    function pick(x, y) {
      let best = null;
      let bestD = Infinity;
      for (const body of bodyList) {
        const s = view3d.screen.get(body.id);
        if (!s?.visible) continue;
        const d = Math.hypot(s.x - x, s.y - y) - s.r;
        const reach = 14;
        if (d < reach && d < bestD) {
          bestD = d;
          best = { type: "body", id: body.id };
        }
      }
      if (best && bestD < 0) return best;
      if (view3d.stars && state.opts.showStars && view3d.galaxyFade < 0.9) {
        const cam = view3d.cameraWorld(state.view).map((v) => v / PARSEC_AU);
        for (const s of starNames) {
          const scr = view3d.project(view3d.starPosition(s.i), state.view);
          if (!scr) continue;
          const p = view3d.starPosition(s.i).map((v) => v / PARSEC_AU);
          const dpc = Math.max(Math.hypot(p[0] - cam[0], p[1] - cam[1], p[2] - cam[2]), 1e-6);
          if (s.absmag + 5 * Math.log10(dpc) - 5 > state.opts.starLimit + 1) continue;
          const d = Math.hypot(scr.x - x, scr.y - y);
          if (d < 10 && d < bestD) {
            bestD = d;
            best = { type: "star", index: s.i };
          }
        }
      }
      return best;
    }

    /* --- input --------------------------------------------------------------- */

    const canvasBox = $(".map-canvas");
    let drag = null;
    canvasBox.addEventListener("contextmenu", (e) => e.preventDefault());
    canvasBox.addEventListener("pointerdown", (e) => {
      canvasBox.setPointerCapture(e.pointerId);
      drag = { x: e.clientX, y: e.clientY, moved: false, pan: e.button === 2 || e.shiftKey || e.button === 1 };
    });
    canvasBox.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x;
      const dy = e.clientY - drag.y;
      if (!drag.moved && Math.hypot(dx, dy) < 4) return;
      drag.moved = true;
      canvasBox.classList.add("dragging");
      drag.x = e.clientX;
      drag.y = e.clientY;
      const v = state.view;
      if (drag.pan) {
        const auPerPx = (v.dist * 2 * Math.tan((50 * Math.PI) / 360)) / view3d.height;
        const cam = view3d.camera;
        const right = fromThree(cam.getWorldDirection(cam.position.clone()).cross(cam.up).normalize());
        const up = fromThree(cam.up.clone().applyQuaternion(cam.quaternion).normalize());
        const here = focusPosition() || v.target;
        state.focus = { type: "fixed", position: [0, 1, 2].map((i) => here[i] - right[i] * dx * auPerPx + up[i] * dy * auPerPx) };
        state.flight = null;
      } else {
        v.yaw -= dx * 0.005;
        v.pitch = Math.min(1.55, Math.max(-1.55, v.pitch + dy * 0.005));
        if (state.flight) {
          state.flight.yaw = undefined;
          state.flight.pitch = undefined;
        }
      }
    });
    canvasBox.addEventListener("pointerup", (e) => {
      canvasBox.classList.remove("dragging");
      if (drag && !drag.moved) {
        const rect = canvasBox.getBoundingClientRect();
        select(pick(e.clientX - rect.left, e.clientY - rect.top));
      }
      drag = null;
    });
    canvasBox.addEventListener("dblclick", (e) => {
      const rect = canvasBox.getBoundingClientRect();
      const hit = pick(e.clientX - rect.left, e.clientY - rect.top);
      if (hit) select(hit, { fly: true });
    });
    canvasBox.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const delta = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
        const f = state.focus?.type === "body" ? eph.get(state.focus.id) : null;
        const minDist = f ? (f.radius_km / AU_KM) * 1.6 : 1e-7;
        const next = state.view.dist * Math.exp(delta * 0.0014);
        state.view.dist = Math.min(MAX_DIST, Math.max(minDist, next));
        if (state.flight) state.flight.dist = state.view.dist;
      },
      { passive: false },
    );

    function onKey(e) {
      const tag = e.target?.tagName || "";
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || e.ctrlKey || e.metaKey || e.altKey) return;
      const k = e.key;
      const toggle = (opt) => {
        state.opts[opt] = !state.opts[opt];
        const box = root.querySelector(`[data-opt="${opt}"]`);
        if (box) box.checked = state.opts[opt];
      };
      if (k === " ") state.playing = !state.playing;
      else if (k === "[") state.rateIndex = Math.max(0, state.rateIndex - 1);
      else if (k === "]") state.rateIndex = Math.min(RATES.length - 1, state.rateIndex + 1);
      else if (k === "r") state.direction *= -1;
      else if (k === "n") act("now");
      else if (k === "h") jump("system");
      else if (k === "o") toggle("showOrbits");
      else if (k === "l") toggle("showLabels");
      else if (k === "t") toggle("trueScale");
      else if (k === "c") goToSelected();
      else if (k === "/") {
        searchInput.focus();
        searchInput.select();
      } else if (k === "?") $(".help").hidden = !$(".help").hidden;
      else return;
      e.preventDefault();
      syncTimeUi();
    }
    document.addEventListener("keydown", onKey);

    /* --- toolbar and panels -------------------------------------------------- */

    function act(name) {
      if (name === "back") ctx.back();
      if (name === "play") state.playing = !state.playing;
      if (name === "reverse") state.direction *= -1;
      if (name === "slower") state.rateIndex = Math.max(0, state.rateIndex - 1);
      if (name === "faster") state.rateIndex = Math.min(RATES.length - 1, state.rateIndex + 1);
      if (name === "now") {
        state.jd = jdFromMs(Date.now());
        state.rateIndex = 0;
        state.direction = 1;
        state.playing = true;
      }
      if (name === "help") $(".help").hidden = !$(".help").hidden;
      syncTimeUi();
    }
    // The Show panel and the info card sit just under the top bar, however
    // many rows it wraps to (--map-head in app.css; critic round F1, Relay
    // task 405: in a 1024 px window the panel covered the date field).
    const headObserver = new ResizeObserver(() => {
      const top = $(".map-top");
      if (top.offsetHeight) $(".map").style.setProperty("--map-head", `${top.offsetTop + top.offsetHeight}px`);
    });
    headObserver.observe($(".map-top"));
    root.querySelector(".map-top").addEventListener("click", (e) => {
      const a = e.target.closest("[data-act]")?.dataset.act;
      if (a) act(a);
    });
    $(".map-layers").addEventListener("click", (e) => {
      const a = e.target.closest("[data-act]")?.dataset.act;
      if (a) act(a);
    });
    $(".help").addEventListener("click", () => ($(".help").hidden = true));
    // a slider and its number field share one data-opt and follow each other
    root.querySelectorAll("[data-opt]").forEach((el) => {
      el.addEventListener("input", () => {
        if (el.type === "checkbox") return void (state.opts[el.dataset.opt] = el.checked);
        const v = Number(el.value);
        if (el.value === "" || !(v >= Number(el.min) && v <= Number(el.max))) return;
        state.opts[el.dataset.opt] = v;
        for (const twin of root.querySelectorAll(`[data-opt="${el.dataset.opt}"]`)) if (twin !== el) twin.value = v;
      });
      if (el.type === "number") el.addEventListener("change", () => (el.value = state.opts[el.dataset.opt]));
    });
    const jumps = $(".jumps");
    for (const j of JUMPS) {
      const b = document.createElement("button");
      b.className = "btn small";
      b.textContent = j.label;
      b.title = j.title;
      b.onclick = () => jump(j.id);
      jumps.appendChild(b);
    }

    const dateInput = $(".map-date");
    dateInput.addEventListener("change", () => {
      const ms = Date.parse(dateInput.value + "Z");
      if (Number.isFinite(ms)) state.jd = Math.min(MAX_JD, Math.max(MIN_JD, jdFromMs(ms)));
    });

    function syncTimeUi() {
      const rate = RATES[state.rateIndex];
      root.querySelector('[data-act="play"]').textContent = state.playing ? "❚❚" : "▶";
      root.querySelector('[data-act="reverse"]').classList.toggle("on", state.direction < 0);
      $(".map-rate").textContent = state.playing
        ? `${state.direction < 0 ? "Backwards, " : ""}${rate.label}`
        : "Paused";
    }
    syncTimeUi();

    /* --- search ---------------------------------------------------------------- */

    const searchInput = $(".search input");
    const results = $(".search-results");
    let hits = [];
    let hot = 0;
    function runSearch() {
      const q = searchInput.value.trim().toLowerCase();
      if (!q) {
        results.hidden = true;
        return;
      }
      const found = [];
      for (const b of bodyList) {
        if (b.name.toLowerCase().includes(q)) {
          found.push({ label: b.name, note: KIND_LABEL[b.kind], sel: { type: "body", id: b.id }, rank: b.name.toLowerCase().startsWith(q) ? 0 : 1 });
        }
      }
      for (const s of starNames) {
        const hay = `${s.display} ${s.name}`.toLowerCase();
        if (hay.includes(q)) {
          const ly = s.dist_pc * PARSEC_LY;
          found.push({
            label: s.display,
            note: `star, ${ly < 100 ? ly.toFixed(1) : Math.round(ly)} ly`,
            sel: { type: "star", index: s.i },
            rank: (s.display.toLowerCase().startsWith(q) ? 2 : 3) + (s.proper ? 0 : 2) + s.mag / 100,
          });
        }
      }
      found.sort((a, b) => a.rank - b.rank);
      hits = found.slice(0, 9);
      hot = 0;
      results.replaceChildren(
        ...hits.map((h, i) => {
          const b = document.createElement("button");
          b.innerHTML = "<span></span><small></small>";
          b.querySelector("span").textContent = h.label;
          b.querySelector("small").textContent = h.note;
          b.classList.toggle("hot", i === hot);
          b.onmousedown = (e) => {
            e.preventDefault();
            choose(h);
          };
          return b;
        }),
      );
      results.hidden = hits.length === 0;
    }
    function choose(h) {
      searchInput.value = "";
      results.hidden = true;
      searchInput.blur();
      select(h.sel, { fly: true });
    }
    searchInput.addEventListener("input", runSearch);
    searchInput.addEventListener("blur", () => setTimeout(() => (results.hidden = true), 100));
    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && hits[hot]) choose(hits[hot]);
      else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        hot = (hot + (e.key === "ArrowDown" ? 1 : hits.length - 1)) % Math.max(hits.length, 1);
        [...results.children].forEach((c, i) => c.classList.toggle("hot", i === hot));
        e.preventDefault();
      } else if (e.key === "Escape") {
        searchInput.value = "";
        results.hidden = true;
        searchInput.blur();
        e.stopPropagation();
      }
    });

    /* --- the frame loop ------------------------------------------------------ */

    let frame = 0;
    let last = performance.now();
    let slowTick = 0;
    function tick(now) {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      if (state.playing) {
        state.jd = Math.min(MAX_JD, Math.max(MIN_JD, state.jd + RATES[state.rateIndex].days * state.direction * dt));
      }
      const v = state.view;
      const goal = focusPosition();
      const f = state.flight;
      if (f) {
        const t = Math.min(1, (now - f.t0) / f.duration);
        const e = ease(t);
        const to = goal || f.from.target;
        // Travel through distance on a log scale so a flight from the galaxy
        // to a moon spends its time evenly across the scales.
        v.target = [0, 1, 2].map((i) => f.from.target[i] + (to[i] - f.from.target[i]) * e);
        const logFrom = Math.log(f.from.dist);
        const logTo = Math.log(f.dist);
        const bump = Math.log(Math.max(1, dist3(f.from.target, to) / Math.max(f.from.dist, f.dist))) * 0.8;
        v.dist = Math.exp(logFrom + (logTo - logFrom) * e + bump * Math.sin(Math.PI * e));
        if (f.yaw !== undefined) {
          const dy = Math.atan2(Math.sin(f.yaw - f.from.yaw), Math.cos(f.yaw - f.from.yaw));
          v.yaw = f.from.yaw + dy * e;
        }
        if (f.pitch !== undefined) v.pitch = f.from.pitch + (f.pitch - f.from.pitch) * e;
        if (t >= 1) state.flight = null;
      } else if (goal) {
        v.target = goal;
      }

      view3d.render(v, state.jd, { ...state.opts, selectedId: state.selected?.type === "body" ? state.selected.id : null });
      drawLabels();

      if (now - slowTick > 200) {
        slowTick = now;
        const date = new Date(msFromJd(state.jd));
        $(".map-clock").textContent = `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`;
        if (document.activeElement !== dateInput) dateInput.value = date.toISOString().slice(0, 16);
        $(".map-range").hidden = state.jd >= VALID_FROM && state.jd <= VALID_TO;
        const width = v.dist * 2 * Math.tan((50 * Math.PI) / 360) * (view3d.width / view3d.height);
        $(".map-scale").textContent = `Across the screen: ${formatDistance(width)}` + (v.dist > LIGHT_YEAR_AU * 0.1 && view3d.sunDistance > 1e4 ? ` · Sun ${formatDistance(view3d.sunDistance)} away` : "");
        updateFacts();
      }
      frame = requestAnimationFrame(tick);
    }
    frame = requestAnimationFrame(tick);

    return {
      onEscape() {
        if (!$(".help").hidden) {
          $(".help").hidden = true;
          return true;
        }
        if (state.selected) {
          select(null);
          return true;
        }
        return false;
      },
      unmount() {
        gone = true;
        clearTimeout(fetchTimer);
        cancelAnimationFrame(frame);
        headObserver.disconnect();
        document.removeEventListener("keydown", onKey);
        view3d.dispose();
        root.replaceChildren();
      },
      // Exposed for checking the map from a browser console or a test page.
      debug: { state, eph, view3d, jump, select },
    };
  },
};

function dist3(a, b) {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}
