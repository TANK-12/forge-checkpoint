/* Attractors: hunt strange attractors in twelve-letter codes and watch
 * millions of points pile up into them. The sums live in sprott.js, the
 * pixels in render.js, the bookkeeping in finds.js; this file is the DOM. */

import { freshSeed } from "../_kit/rng.js";
import * as S from "./sprott.js";
import * as R from "./render.js";
import * as F from "./finds.js";

const FAVOURITE = "JCFHLVWNJDLG";
const MAX_PIXELS = 1_200_000; // histogram size cap: a tone map is about 4 ms at this size
const FILL_TARGET = 40_000_000; // points before a still attractor stops filling
const FADE_POINTS = 2_500_000; // points over which a new attractor fades in
const FRAME_MS = 7;
const TERMS = ["1", "x", "x²", "xy", "y", "y²"];

const CSS = `
.atr { background: #08070d; }
/* forge.css pads every input; a range slider wants none of that */
.atr input[type="range"] { padding: 0; border: 0; background: none; height: 18px; margin: 0; }
.atr .ag-slider { margin: 0; }
.atr .ag-num { padding: 3px 5px; }
.atr-hunt, .atr-lab, .atr-strip { scrollbar-width: thin; scrollbar-color: rgba(255, 180, 84, 0.35) transparent; }
.atr-canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.atr-ghost { pointer-events: none; opacity: 0; }
.atr-lost .atr-main { opacity: 0.35; transition: opacity 0.3s; }
.atr .ag-panel h3 { text-transform: none; letter-spacing: 0.01em; font-size: 13px; color: var(--text); }
.atr-hunt { position: absolute; top: 14px; left: 14px; width: 292px; max-height: calc(100% - 28px); overflow-y: auto; box-sizing: border-box; }
.atr-lab { position: absolute; top: 14px; right: 14px; width: 300px; max-height: calc(100% - 128px); overflow-y: auto; box-sizing: border-box; }
.atr-lab.folded { width: auto; min-width: 120px; overflow: visible; }
.atr-huntbtn { font-size: 16px; padding: 10px 14px; flex: 1; letter-spacing: 0.02em; }
.atr-huntbtn.busy { background: transparent; color: var(--accent); }
.atr-tally { font-size: 12px; line-height: 1.4; min-height: 17px; }
.atr-card { border: 1px solid rgba(255, 180, 84, 0.18); border-radius: 10px; padding: 8px 10px; background: rgba(0, 0, 0, 0.25); display: flex; flex-direction: column; gap: 4px; }
.atr-code { font: 600 21px/1.15 ui-monospace, "JetBrains Mono", "DejaVu Sans Mono", monospace; letter-spacing: 0.12em; color: var(--accent); background: none; border: 0; padding: 0; text-align: left; cursor: copy; }
.atr-code.rolling { color: var(--muted); }
.atr-code { user-select: text; }
.atr-nums { font-size: 12.5px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.atr-nums b { font-weight: 600; color: var(--text); }
.atr-desc { font-size: 12.5px; font-style: italic; line-height: 1.4; }
.atr-hint { font-size: 11.5px; line-height: 1.4; }
.atr-keep { display: flex; flex-direction: column; gap: 6px; }
.atr-keep input, .atr-keep textarea, .atr-codein {
  font: inherit; font-size: 13px; color: var(--text); background: var(--bg, #0c0b12);
  border: 1px solid var(--border); border-radius: 7px; padding: 5px 8px; resize: vertical; box-sizing: border-box; width: 100%;
}
.atr-codein { font-family: ui-monospace, "DejaVu Sans Mono", monospace; letter-spacing: 0.08em; text-transform: uppercase; flex: 1; width: auto; min-width: 0; }
.atr-codein::placeholder { text-transform: none; letter-spacing: 0.02em; font-family: system-ui, sans-serif; }
.atr-codein.bad { border-color: var(--bad, #f2637d); }
.atr-group { font-size: 12px; margin-top: 2px; }
.atr-lab .ag-slider { grid-template-columns: 58px 1fr 60px; }
.atr-lab .ag-panel-body { gap: 6px; }
.atr-strip { position: absolute; left: 50%; bottom: 12px; transform: translateX(-50%); display: flex; gap: 6px; padding: 6px; max-width: calc(100% - 28px); overflow-x: auto; box-sizing: border-box; }
.atr-strip:empty { display: none; }
.atr-find { padding: 0; border: 1px solid var(--border); border-radius: 7px; overflow: hidden; cursor: pointer; background: #08070d; flex: none; line-height: 0; transition: border-color 0.15s, transform 0.15s; }
.atr-find:hover, .atr-find:focus-visible { border-color: var(--accent); outline: none; transform: translateY(-2px); }
.atr-find.on { border-color: var(--accent); box-shadow: 0 0 12px -3px var(--glow); }
.atr-find canvas { width: 84px; height: 56px; display: block; }
@media (max-width: 1000px) { .atr-hunt { width: 262px; } .atr-lab { width: 270px; } }
`;

const fmt = (v, places) => (v === null || v === undefined ? "?" : v.toFixed(places));

/** Paint a small still of coeffs onto a canvas already sized in device px. */
function paintStill(canvas, coeffs, settings, points) {
  const g = canvas.getContext("2d");
  const { info } = F.measure(coeffs);
  const w = canvas.width;
  const h = canvas.height;
  if (!info.bounds) {
    g.fillStyle = R.background(settings.palette);
    g.fillRect(0, 0, w, h);
    return;
  }
  const start = info.sample.length ? info.sample[info.sample.length - 1] : [0.05, 0.05];
  const pts = points ?? Math.max(80000, Math.min(700000, Math.round(w * h * 2.5)));
  const out = R.still(coeffs, info.bounds, start, w, h, { points: pts, ...settings });
  g.putImageData(new ImageData(out.pixels, out.w, out.h), 0, 0);
}

export default {
  async mount(root, ctx) {
    const { el, button, slider, seg, panel, toggle } = ctx.ui;
    root.classList.add("atr");
    const main = el("canvas", { class: "atr-canvas atr-main", "aria-label": "The attractor" });
    const ghost = el("canvas", { class: "atr-canvas atr-ghost", "aria-hidden": "true" });
    root.append(el("style", { text: CSS }), main, ghost);
    const g = main.getContext("2d");
    const gg = ghost.getContext("2d");

    // --- state -------------------------------------------------------------------
    const st = {
      coeffs: S.decode(FAVOURITE),
      info: null,
      dimension: null,
      ...F.DEFAULTS,
      pointsPerFrame: 300000,
      minDimension: S.MIN_DIMENSION,
      driftOn: false,
      driftSpeed: 0.6,
      drift: null,
      hunting: null, // {hunter, tally}
      triedTonight: 0,
      recent: [],
    };
    let density = null;
    let image = null;
    let out = null;
    let lut = R.paletteLut(st.palette);
    let filling = false;
    let dirty = false;
    let fadeFrom = 0; // density.total at which the fade-in started; -1 for none
    let toneCost = 2;
    let viewBounds = null;
    let lastT = 0;
    let frameNo = 0;

    // --- the hunt panel ---------------------------------------------------------
    const huntP = panel("Strange attractors", { cls: "atr-hunt" });
    const huntBtn = button("Hunt", () => toggleHunt(), {
      kind: "primary",
      title: "Roll random codes until one is chaotic (Space or H). Click again to stop.",
    });
    huntBtn.classList.add("atr-huntbtn");
    const tally = el("div", {
      class: "atr-tally ag-muted",
      title: "What the last hunt tried and why it threw codes away",
      text: "Most codes fly off or settle down. Hunt rolls them until one is chaotic.",
    });
    const codeBtn = el("button", {
      type: "button",
      class: "atr-code",
      title: "The twelve-letter code of this attractor. Click to copy it.",
    });
    codeBtn.addEventListener("click", async () => {
      ctx.toast(await F.copyCode(st.coeffs, navigator.clipboard, selectCode));
    });
    /** Select the code's letters on the button (not the leading "≈"). */
    function selectCode() {
      const t = codeBtn.firstChild;
      if (!t || t.nodeType !== Node.TEXT_NODE) return;
      const range = document.createRange();
      range.setStart(t, Math.max(0, t.data.length - 12));
      range.setEnd(t, t.data.length);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    }
    const statusBadge = el("span", { class: "ag-badge", title: "What the orbit does" });
    const lyapEl = el("span", {
      class: "ag-muted",
      title: "Lyapunov exponent in bits per iteration: how fast two neighbouring points drift apart. Above 0.005 means chaos.",
    });
    const dimEl = el("span", {
      class: "ag-muted",
      title: "Correlation dimension estimated from 800 points: near 1 is thread-like, near 2 fills an area.",
    });
    const desc = el("div", { class: "atr-desc ag-muted" });
    const card = el(
      "div",
      { class: "atr-card" },
      codeBtn,
      el("div", { class: "atr-nums" }, statusBadge, lyapEl, dimEl),
      desc,
    );
    const paletteSeg = seg(
      Object.entries(R.PALETTES).map(([value, p]) => ({ value, label: p.label, title: p.title })),
      st.palette,
      (v) => setPalette(v),
      { title: "Colours" },
    );
    const exposureS = slider({
      label: "Exposure",
      min: F.LIMITS.exposure[0],
      max: F.LIMITS.exposure[1],
      step: 0.05,
      value: st.exposure,
      title: "Brightness: how quickly thin strands light up",
      oninput: (v) => {
        st.exposure = v;
        dirty = true;
      },
    });
    const gammaS = slider({
      label: "Gamma",
      min: F.LIMITS.gamma[0],
      max: F.LIMITS.gamma[1],
      step: 0.05,
      value: st.gamma,
      title: "Contrast curve: higher lifts the faint dust, lower keeps it dark",
      oninput: (v) => {
        st.gamma = v;
        dirty = true;
      },
    });

    // keep form, inline
    const nameIn = el("input", { type: "text", maxlength: 80, placeholder: "A name for it", title: "The name it is kept under" });
    const noteIn = el("textarea", { rows: 2, maxlength: 4000, placeholder: "A note (optional)", title: "Anything worth remembering about it" });
    const saveBtn = button("Keep it", () => saveKeep(), { kind: "primary", title: "Save this attractor with its colours" });
    const cancelBtn = button("Cancel", () => showKeep(false), { kind: "ghost", title: "Close without keeping" });
    const keepForm = el("form", { class: "atr-keep", hidden: true }, nameIn, noteIn, el("div", { class: "ag-row end" }, cancelBtn, saveBtn));
    keepForm.addEventListener("submit", (e) => {
      e.preventDefault();
      saveKeep();
    });
    const keepBtn = button("Keep this one", () => showKeep(true), {
      kind: "ghost",
      title: "Save this attractor as a keepsake, with a name and a note",
    });

    huntP.body.append(
      el("div", { class: "ag-row" }, huntBtn),
      tally,
      card,
      el("div", { class: "ag-row" }, paletteSeg.el),
      exposureS.el,
      gammaS.el,
      el("div", { class: "ag-row" }, keepBtn),
      keepForm,
      el("div", {
        class: "atr-hint ag-muted",
        text: "Space or H hunts. The arrow keys walk through your recent finds below.",
      }),
    );

    // --- the lab (advanced) ------------------------------------------------------
    // folded at first in a small window so the picture stays clear
    const labP = panel("Lab", { cls: "atr-lab", adv: true, fold: true, folded: { width: 1100, height: 720 } });
    labP.el.querySelector(".ag-fold").addEventListener("click", () => requestLayout());
    const codeIn = el("input", {
      type: "text",
      class: "atr-codein",
      maxlength: 12,
      placeholder: "Type a code",
      spellcheck: "false",
      autocomplete: "off",
      title: "Twelve letters from A to Y, for example FIRCDERRPVLD. Enter to draw it.",
    });
    const goBtn = button("Draw", () => goCode(), { title: "Draw the code typed on the left" });
    codeIn.addEventListener("keydown", (e) => {
      if (e.key === "Enter") goCode();
    });
    codeIn.addEventListener("input", () => codeIn.classList.remove("bad"));
    const coeffS = st.coeffs.map((v, i) =>
      slider({
        label: `a${i + 1} ${TERMS[i % 6]}`,
        min: -1.2,
        max: 1.2,
        step: 0.01,
        value: v,
        title: `Coefficient a${i + 1}: the ${TERMS[i % 6] === "1" ? "constant" : TERMS[i % 6]} term of ${i < 6 ? "x′" : "y′"}. Nudge it and watch.`,
        oninput: (val) => nudge(i, val),
      }),
    );
    const ppfS = slider({
      label: "Points per frame",
      min: 20000,
      max: 1000000,
      step: 10000,
      value: st.pointsPerFrame,
      title: "Most points added per frame (the frame-time budget also caps it)",
      oninput: (v) => (st.pointsPerFrame = v),
    });
    const pickyS = slider({
      label: "Least dimension",
      min: 0.8,
      max: 1.8,
      step: 0.05,
      value: st.minDimension,
      title: "Pickiness: the hunt skips chaotic finds thinner than this dimension",
      oninput: (v) => (st.minDimension = v),
    });
    const driftT = toggle("Drift", st.driftOn, (on) => setDrift(on), {
      title: "Let one coefficient wander slowly so the attractor breathes; it turns back before chaos is lost",
    });
    const driftS = slider({
      label: "Drift speed",
      min: 0.1,
      max: 2,
      step: 0.1,
      value: st.driftSpeed,
      title: "How fast the wandering coefficient moves",
      oninput: (v) => (st.driftSpeed = v),
    });
    const driftNote = el("span", { class: "ag-muted atr-hint" });
    labP.body.append(
      el("div", { class: "ag-row" }, codeIn, goBtn),
      el("div", { class: "ag-row" }, driftT.el, driftNote),
      driftS.el,
      el("div", { class: "atr-group ag-muted", text: "x′ = a1 + a2 x + a3 x² + a4 xy + a5 y + a6 y²" }),
      ...coeffS.slice(0, 6).map((s) => s.el),
      el("div", { class: "atr-group ag-muted", text: "y′ = a7 + a8 x + a9 x² + a10 xy + a11 y + a12 y²" }),
      ...coeffS.slice(6).map((s) => s.el),
      el("div", { class: "atr-group ag-muted", text: "Hunting and drawing" }),
      pickyS.el,
      ppfS.el,
    );

    const strip = el("div", { class: "atr-strip ag-panel", role: "list", "aria-label": "Recent finds" });
    root.append(huntP.el, labP.el, strip);

    // --- drawing -----------------------------------------------------------------
    function viewRect() {
      const r = root.getBoundingClientRect();
      const sx = density.w / Math.max(1, r.width);
      let left = 0;
      let right = r.width;
      let bottom = r.height;
      const hp = huntP.el.getBoundingClientRect();
      if (hp.width && r.width - (hp.right - r.left) > r.width * 0.45) left = hp.right - r.left + 8;
      const lp = labP.el.getBoundingClientRect();
      if (lp.width && lp.left - r.left - left > r.width * 0.4) right = lp.left - r.left - 8;
      const sp = strip.getBoundingClientRect();
      if (sp.height && sp.top - r.top > r.height * 0.6) bottom = sp.top - r.top - 4;
      return { x: left * sx, y: 0, w: (right - left) * sx, h: bottom * (density.h / Math.max(1, r.height)) };
    }

    function size() {
      const r = root.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      let w = Math.round(r.width * dpr);
      let h = Math.round(r.height * dpr);
      const k = Math.sqrt(MAX_PIXELS / (w * h));
      if (k < 1) {
        w = Math.round(w * k);
        h = Math.round(h * k);
      }
      if (density && density.w === w && density.h === h) {
        restart({ fade: false });
        return;
      }
      main.width = ghost.width = w;
      main.height = ghost.height = h;
      density = new R.Density(w, h);
      image = g.createImageData(w, h);
      out = new Uint32Array(image.data.buffer);
      restart({ fade: false });
    }

    function startPoint() {
      const s = st.info.sample;
      return s.length ? s[s.length - 1] : [0.05, 0.05];
    }

    function restart({ fade = true } = {}) {
      if (!density || !st.info || !st.info.bounds) return;
      density.clear();
      density.setMap(st.coeffs, startPoint());
      viewBounds = st.info.bounds.slice();
      density.setView(R.fitView(viewBounds, viewRect()));
      fadeFrom = fade ? 0 : -1;
      filling = true;
      dirty = true;
    }

    /** Freeze what is on screen into the ghost and let it fade away. */
    function crossfade() {
      if (!density) return;
      gg.clearRect(0, 0, ghost.width, ghost.height);
      gg.drawImage(main, 0, 0);
      ghost.style.transition = "none";
      ghost.style.opacity = "1";
      void ghost.offsetWidth;
      ghost.style.transition = "opacity 1.1s ease-out";
      ghost.style.opacity = "0";
    }

    function paint() {
      const t0 = performance.now();
      let fade = 1;
      if (fadeFrom >= 0) {
        const u = Math.min(1, (density.total - fadeFrom) / FADE_POINTS);
        fade = 0.2 + 0.8 * u * u * (3 - 2 * u);
        if (u >= 1) fadeFrom = -1;
      }
      R.toneMap(density, lut, out, { exposure: st.exposure, gamma: st.gamma, fade });
      g.putImageData(image, 0, 0);
      toneCost = 0.8 * toneCost + 0.2 * (performance.now() - t0);
    }

    // --- showing an attractor ----------------------------------------------------
    function showInfo() {
      const { info, dimension } = st;
      codeBtn.classList.remove("rolling");
      codeBtn.textContent = F.codeLabel(st.coeffs);
      statusBadge.textContent = S.STATUS_WORDS[info.status];
      lyapEl.replaceChildren("L ", el("b", { text: fmt(info.lyapunov, 3) }), " bits/iter");
      dimEl.replaceChildren("D₂ ≈ ", el("b", { text: fmt(dimension, 2) }));
      dimEl.hidden = dimension === null;
      lyapEl.hidden = info.lyapunov === null;
      desc.textContent =
        info.status === "chaotic"
          ? S.describe(info.lyapunov, dimension)[1]
          : info.status === "escapes"
            ? "Nothing to draw: the orbit leaves for infinity. Nudge it back."
            : "Not chaotic: the orbit settles into something regular.";
      root.classList.toggle("atr-lost", info.status === "escapes");
    }

    function syncLab() {
      st.coeffs.forEach((v, i) => coeffS[i].set(v));
    }

    /** Make coeffs the current attractor. */
    function setAttractor(coeffs, { fade = true, recent = true, measured = null } = {}) {
      const m = measured || F.measure(coeffs);
      st.coeffs = coeffs.slice();
      st.info = m.info;
      st.dimension = m.dimension;
      st.drift = st.driftOn && m.info.status === "chaotic" ? F.startDrift(st.coeffs, firstDriftable()) : null;
      driftNote.textContent = st.drift ? `a${st.drift.k + 1} wanders` : st.driftOn ? "waiting for chaos" : "";
      showInfo();
      syncLab();
      if (m.info.bounds) {
        if (fade) crossfade();
        restart({ fade });
      }
      if (recent && m.info.status === "chaotic") {
        st.recent = F.addRecent(st.recent, { coeffs: st.coeffs.slice() });
        renderStrip();
      } else markStrip();
    }

    function renderStrip() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      strip.replaceChildren(
        ...st.recent.map((f) => {
          const c = el("canvas");
          c.width = Math.round(84 * dpr);
          c.height = Math.round(56 * dpr);
          paintStill(c, f.coeffs, { palette: st.palette, exposure: st.exposure, gamma: st.gamma }, 70000);
          const b = el(
            "button",
            {
              type: "button",
              class: "atr-find",
              role: "listitem",
              title: `${F.codeLabel(f.coeffs)}: back to this one`,
              dataset: { key: F.keyOf(f.coeffs) },
              on: { click: () => setAttractor(f.coeffs, { recent: false }) },
            },
            c,
          );
          return b;
        }),
      );
      markStrip();
      requestLayout();
    }

    function markStrip() {
      const key = F.keyOf(st.coeffs);
      for (const b of strip.children) b.classList.toggle("on", b.dataset.key === key);
    }

    // --- hunting -----------------------------------------------------------------
    function toggleHunt() {
      if (st.hunting) return stopHunt();
      st.hunting = { hunter: S.hunter(freshSeed(), { minDimension: st.minDimension }), tally: F.newTally(), frames: 0 };
      huntBtn.textContent = "Hunting… click to stop";
      huntBtn.classList.add("busy");
      codeBtn.classList.add("rolling");
    }

    function stopHunt() {
      st.hunting = null;
      huntBtn.textContent = "Hunt";
      huntBtn.classList.remove("busy");
      if (st.info) showInfo();
    }

    function huntFrame() {
      const h = st.hunting;
      const before = h.tally.tried;
      // slow at first so the codes can be seen rolling, faster when luck is poor
      h.frames += 1;
      const maxCodes = Math.min(60, 2 + Math.floor(h.frames / 6));
      const { found, last } = F.huntSlice(h.hunter, h.tally, { maxCodes, budgetMs: 3 });
      st.triedTonight += h.tally.tried - before;
      tally.textContent = F.tallyText(h.tally);
      if (found) {
        stopHunt();
        setAttractor(found.coeffs, { measured: { info: found.result, dimension: found.dimension } });
        tally.textContent = `${F.tallyText(h.tally)} ${st.triedTonight.toLocaleString("en")} tried tonight.`;
      } else if (last) {
        codeBtn.textContent = last.code;
      }
    }

    // --- the lab -----------------------------------------------------------------
    function nudge(i, value) {
      const next = st.coeffs.slice();
      next[i] = value;
      setAttractor(next, { fade: false, recent: false });
    }

    function goCode() {
      const text = codeIn.value.trim();
      if (!S.isCode(text)) {
        codeIn.classList.add("bad");
        ctx.toast("A code is twelve letters from A to Y.");
        return;
      }
      setAttractor(S.decode(text));
      if (st.info.status !== "chaotic") ctx.toast(`${text.toUpperCase()}: ${S.STATUS_WORDS[st.info.status]}.`);
    }

    function firstDriftable() {
      // the coefficient with the most room: the one nearest zero
      let best = 0;
      st.coeffs.forEach((v, i) => {
        if (Math.abs(v) < Math.abs(st.coeffs[best])) best = i;
      });
      return best;
    }

    function setDrift(on) {
      const was = st.drift;
      st.driftOn = on;
      st.drift = on && st.info && st.info.status === "chaotic" ? F.startDrift(st.coeffs, firstDriftable()) : null;
      driftNote.textContent = st.drift ? `a${st.drift.k + 1} wanders` : "";
      if (!on && was) {
        // the drift only measured roughly as it went: measure where it stopped
        const m = F.measure(st.coeffs);
        st.info = m.info;
        st.dimension = m.dimension;
        showInfo();
        markStrip();
      }
      if (!on) restart({ fade: false });
    }

    const quick = { iterations: 4000, transient: 600, sample: 0 };
    function driftFrame(dt, deadline) {
      const res = F.driftStep(st.drift, st.coeffs, dt, st.driftSpeed, (c) => S.analyse(c, quick).status === "chaotic");
      st.drift = res.drift;
      driftNote.textContent = `a${st.drift.k + 1} wanders`;
      if (res.moved) {
        st.coeffs = res.coeffs;
        const info = S.analyse(st.coeffs, quick);
        if (info.bounds) {
          const k = 0.08;
          viewBounds = viewBounds.map((v, i) => v + (info.bounds[i] - v) * k);
          density.setView(R.fitView(viewBounds, viewRect()));
        }
        coeffS[st.drift.k].set(st.coeffs[st.drift.k]);
        codeBtn.textContent = F.codeLabel(st.coeffs);
        lyapEl.replaceChildren("L ", el("b", { text: fmt(info.lyapunov, 3) }), " bits/iter");
      }
      density.decay(3);
      density.setMap(st.coeffs, [density.x, density.y]);
      fillUntil(deadline);
    }

    /** Add points in chunks until the deadline or the per-frame cap. */
    function fillUntil(deadline) {
      const cap = st.pointsPerFrame;
      let done = 0;
      do {
        done += density.accumulate(Math.min(20000, cap - done));
      } while (done < cap && !density.lost && performance.now() < deadline);
    }

    // --- palette and keeping -----------------------------------------------------
    function setPalette(name) {
      crossfade();
      st.palette = name;
      lut = R.paletteLut(name);
      root.style.background = R.background(name);
      dirty = true;
      renderStrip();
    }

    function showKeep(on) {
      keepForm.hidden = !on;
      keepBtn.hidden = on;
      if (on) {
        nameIn.value = nameIn.value || S.encode(st.coeffs);
        nameIn.focus();
        nameIn.select();
      } else {
        root.focus({ preventScroll: true });
      }
    }

    async function saveKeep() {
      const name = nameIn.value.trim();
      if (!name) {
        nameIn.focus();
        ctx.toast("Give it a name first.");
        return;
      }
      const { data, measured } = F.keepNow(st);
      if (measured.info.status === "escapes") {
        ctx.toast("There is nothing on screen to keep.");
        return;
      }
      saveBtn.disabled = true;
      try {
        const pic = el("canvas");
        pic.width = 320;
        pic.height = 200;
        paintStill(pic, st.coeffs, { palette: st.palette, exposure: st.exposure, gamma: st.gamma }, 350000);
        await ctx.keep({ name, note: noteIn.value.trim(), data, thumb: ctx.thumb(pic) });
        ctx.toast(`Kept “${name}”.`);
        nameIn.value = "";
        noteIn.value = "";
        showKeep(false);
      } catch (e) {
        ctx.toast(`Not kept: ${e.message}`);
      } finally {
        saveBtn.disabled = false;
      }
    }

    // --- keys, resize, the loop --------------------------------------------------
    function onKey(e) {
      if (e.defaultPrevented || e.ctrlKey || e.altKey || e.metaKey) return;
      const t = e.target;
      if (t && (t.closest?.("input, textarea, select, [contenteditable]") || t.isContentEditable)) return;
      if (e.key === " " && t && t.closest?.("button")) return; // the button clicks itself
      if (e.key === " " || e.key === "h" || e.key === "H") {
        e.preventDefault();
        toggleHunt();
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        const f = F.neighbour(st.recent, st.coeffs, e.key === "ArrowLeft" ? 1 : -1);
        if (f) {
          e.preventDefault();
          setAttractor(f.coeffs, { recent: false });
        }
      }
    }
    window.addEventListener("keydown", onKey);

    let layoutPending = false;
    function requestLayout() {
      layoutPending = true;
    }
    const ro = new ResizeObserver(() => size());
    ro.observe(root);
    const offMode = ctx.onMode(() => {
      if (!ctx.advanced && st.driftOn) {
        driftT.set(false);
        setDrift(false);
      }
      requestLayout();
    });

    const loop = ctx.loop((t) => {
      const dt = lastT ? Math.min(0.1, (t - lastT) / 1000) : 0.016;
      lastT = t;
      if (!density) return;
      if (layoutPending) {
        layoutPending = false;
        if (st.info && st.info.bounds) {
          density.setView(R.fitView(viewBounds || st.info.bounds, viewRect()));
          if (!st.drift) restart({ fade: false });
        }
      }
      const t0 = performance.now();
      frameNo += 1;
      if (st.hunting) huntFrame();
      // a tone map every frame while fading in or drifting, else every third
      let tone = dirty;
      if (st.drift && st.info && st.info.bounds) {
        tone = true;
      } else if (filling) {
        tone = tone || fadeFrom >= 0 || frameNo % 3 === 0;
      }
      const spare = FRAME_MS - (tone ? toneCost : 0) - (performance.now() - t0);
      const deadline = performance.now() + Math.max(1.5, spare);
      if (st.drift && st.info && st.info.bounds) {
        driftFrame(dt, deadline);
      } else if (filling) {
        fillUntil(deadline);
        if (density.total >= FILL_TARGET || density.lost) {
          filling = false;
          tone = true;
        }
      }
      if (tone) {
        dirty = false;
        paint();
      }
    });

    // --- start -------------------------------------------------------------------
    root.style.background = R.background(st.palette);
    setAttractor(S.decode(FAVOURITE), { fade: false });
    size();

    return {
      unmount() {
        loop.stop();
        ro.disconnect();
        offMode();
        window.removeEventListener("keydown", onKey);
        st.hunting = null;
      },
      open(keepsake) {
        let s;
        try {
          s = F.settingsFrom(keepsake && keepsake.data);
        } catch (e) {
          ctx.toast(`Cannot open it: ${e.message}`);
          return;
        }
        if (st.hunting) stopHunt();
        crossfade();
        st.palette = s.palette;
        st.exposure = s.exposure;
        st.gamma = s.gamma;
        lut = R.paletteLut(s.palette);
        root.style.background = R.background(s.palette);
        paletteSeg.set(s.palette);
        exposureS.set(s.exposure);
        gammaS.set(s.gamma);
        setAttractor(s.coeffs, { fade: true });
        renderStrip();
        tally.textContent = keepsake.name ? `Opened “${keepsake.name}”.` : "";
      },
      onEscape() {
        if (!keepForm.hidden) {
          showKeep(false);
          return true;
        }
        if (st.hunting) {
          stopHunt();
          return true;
        }
        return false;
      },
    };
  },

  preview(canvas, keepsake) {
    let s = { coeffs: S.decode(FAVOURITE), ...F.DEFAULTS };
    if (keepsake) {
      try {
        s = F.settingsFrom(keepsake.data);
      } catch {
        // an unreadable keepsake keeps the favourite as its picture
      }
    }
    paintStill(canvas, s.coeffs, { palette: s.palette, exposure: s.exposure, gamma: s.gamma });
  },
};
