/* Crucible: a falling-sand forge with real heat. The world lives in sim.js,
 * the pixels in render.js, keepsakes in codec.js and the composed scenes in
 * scenes.js; this file is the DOM: the canvas, the brush and the controls. */

import * as S from "./sim.js";
import * as R from "./render.js";
import * as C from "./codec.js";
import * as SC from "./scenes.js";
import { stepper } from "./stepper.js";

const { M, TOOLS, MATERIALS } = S;

// What the palette offers; the ones marked adv only show in Advanced mode.
const PALETTE = [
  { tool: M.SAND },
  { tool: M.WATER },
  { tool: M.ORE },
  { tool: M.COAL },
  { tool: M.WOOD },
  { tool: M.STONE },
  { tool: M.ICE },
  { tool: M.MOLTEN },
  { tool: M.FIRE },
  { tool: M.IRON, adv: true },
  { tool: M.EMBER, adv: true },
  { tool: M.STEAM, adv: true },
  { tool: M.GLASS, adv: true },
  { tool: M.SHOT, adv: true },
].map((p) => ({ ...p, label: MATERIALS[p.tool].label, tip: MATERIALS[p.tool].tip, color: MATERIALS[p.tool].color }));

const TOOL_LIST = [
  { tool: TOOLS.TORCH, label: "torch", tip: "Torch: heat whatever is under the brush (T)", color: [255, 150, 40] },
  { tool: TOOLS.FROST, label: "frost", tip: "Frost: chill whatever is under the brush (C)", color: [150, 210, 255] },
  { tool: TOOLS.ERASE, label: "eraser", tip: "Eraser: clear cells back to air (E, or paint with the right button)", color: [70, 66, 84] },
];

const CSS = `
.cru { background: #07060c; overflow: hidden; }
.cru input[type="range"] { padding: 0; border: 0; background: none; height: 18px; margin: 0; }
.cru .ag-slider { margin: 0; }
.cru .ag-num { padding: 3px 5px; }
.cru .ag-panel h3 { text-transform: none; letter-spacing: 0.01em; font-size: 13px; color: var(--text); }
.cru-view { position: absolute; image-rendering: pixelated; image-rendering: crisp-edges; display: block; touch-action: none; cursor: none; }
.cru-bloom { position: absolute; pointer-events: none; mix-blend-mode: screen; display: block; }
.cru-bloom.off { display: none; }
.cru-ring { position: absolute; pointer-events: none; border: 1.5px solid rgba(255, 220, 180, 0.85); border-radius: 50%; box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.5); display: none; transform: translate(-50%, -50%); }
.cru-ring.torch { border-color: rgba(255, 150, 60, 0.95); }
.cru-ring.frost { border-color: rgba(150, 210, 255, 0.95); }
.cru-dock { position: absolute; left: 0; right: 0; bottom: 0; display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; padding: 8px 14px; box-sizing: border-box; background: rgba(12, 10, 18, 0.94); border-top: 1px solid rgba(255, 255, 255, 0.07); }
.cru-group { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
.cru-sw { display: inline-flex; align-items: center; gap: 6px; padding: 4px 9px 4px 6px; border-radius: 8px; border: 1px solid var(--border); background: rgba(255, 255, 255, 0.03); color: var(--text); font: inherit; font-size: 12.5px; cursor: pointer; white-space: nowrap; }
.cru-sw:hover, .cru-sw:focus-visible { border-color: rgba(255, 180, 84, 0.55); outline: none; }
.cru-sw.on { border-color: var(--accent); background: rgba(255, 180, 84, 0.16); color: var(--accent); }
.cru-dot { width: 13px; height: 13px; border-radius: 4px; box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.18); flex: none; }
.cru-sep { width: 1px; align-self: stretch; background: rgba(255, 255, 255, 0.08); }
.cru-dock .ag-slider { min-width: 230px; margin-left: 6px; }
.cru-run { position: absolute; top: 12px; right: 12px; width: 268px; max-height: calc(100% - 120px); overflow-y: auto; box-sizing: border-box; scrollbar-width: thin; }
.cru-run .ag-slider { grid-template-columns: 76px 1fr 60px; }
.cru-run .ag-panel-body { gap: 7px; }
.cru-run .ag-btn { padding: 5px 10px; }
.cru-keep { display: flex; flex-direction: column; gap: 6px; }
.cru-keep input, .cru-keep textarea { font: inherit; font-size: 13px; color: var(--text); background: var(--bg, #0c0b12); border: 1px solid var(--border); border-radius: 7px; padding: 5px 8px; resize: vertical; box-sizing: border-box; width: 100%; }
.cru-readout { white-space: pre-line; font-size: 12px; line-height: 1.45; font-variant-numeric: tabular-nums; min-height: 34px; }
.cru-hint { font-size: 11.5px; line-height: 1.4; }
`;

const rgbCss = (c) => `rgb(${c[0]}, ${c[1]}, ${c[2]})`;

// Detail: how many cells stand for one cell of the 240 by 135 base grid, in
// each direction. 2 (480 by 270) runs a frame in well under 16 ms on the
// Latitude's i5-1245U (numbers in WIP.md); 3 is offered but is heavy there.
const DETAIL_KEY = "afterglow.crucible.detail";
const DEFAULT_DETAIL = 2;
// keepsakes over this many characters are kept at a lower detail (the store takes up to 1 MB)
const KEEP_LIMIT = 900_000;

function readDetail() {
  try {
    const v = Number(globalThis.localStorage.getItem(DETAIL_KEY));
    if (Number.isInteger(v) && v >= 1 && v <= S.MAX_DETAIL) return v;
  } catch {
    // no storage (a sandboxed page): use the default
  }
  return DEFAULT_DETAIL;
}

function saveDetail(v) {
  try {
    globalThis.localStorage.setItem(DETAIL_KEY, String(v));
  } catch {
    // full or refused storage: the setting still applies, it just will not be remembered
  }
}

/** The world encoded for a keepsake, at the finest detail that fits the store. */
function encodeToKeep(s) {
  let w = s;
  for (;;) {
    const data = C.encode(w);
    if (w.detail <= 1 || JSON.stringify(data).length <= KEEP_LIMIT) return { data, detail: w.detail };
    w = S.resample(w, w.detail - 1);
  }
}

/** Draw a world, glow included, to fill a canvas of any size (cover fit). */
function drawStill(canvas, s, opts = {}) {
  const pix = document.createElement("canvas");
  pix.width = s.w;
  pix.height = s.h;
  const rgba = new Uint8ClampedArray(s.w * s.h * 4);
  const det = s.detail || 1;
  const { bw, bh } = R.bloomSize(s.w, s.h, det);
  const glow = new Float32Array(bw * bh * 3);
  R.render(s, rgba, glow, { heat: !!opts.heat, time: opts.time || 0 });
  pix.getContext("2d").putImageData(new ImageData(rgba, s.w, s.h), 0, 0);
  const g = canvas.getContext("2d");
  const k = Math.max(canvas.width / s.w, canvas.height / s.h);
  const dw = s.w * k;
  const dh = s.h * k;
  const dx = (canvas.width - dw) / 2;
  const dy = (canvas.height - dh) / 2;
  g.save();
  g.imageSmoothingEnabled = false;
  g.drawImage(pix, dx, dy, dw, dh);
  if (!opts.heat) {
    const bl = document.createElement("canvas");
    bl.width = bw;
    bl.height = bh;
    const brgba = new Uint8ClampedArray(bw * bh * 4);
    R.bloom(glow, bw, bh, brgba, opts.bloom ?? 1, det);
    bl.getContext("2d").putImageData(new ImageData(brgba, bw, bh), 0, 0);
    g.imageSmoothingEnabled = true;
    g.globalCompositeOperation = "screen";
    g.drawImage(bl, dx, dy, (bw * 4 * det * dw) / s.w, (bh * 4 * det * dh) / s.h);
  }
  g.restore();
}

function typing() {
  const a = document.activeElement;
  return !!a && (a.tagName === "INPUT" || a.tagName === "TEXTAREA" || a.tagName === "SELECT" || a.isContentEditable);
}

export default {
  async mount(root, ctx) {
    const { el, button, slider, panel, toggle } = ctx.ui;
    root.classList.add("cru");

    // --- the world and its buffers -------------------------------------------------
    const startDetail = readDetail();
    // a worker steps the world when it can; `world` is what the page draws and reads
    const runner = stepper(S.resample(SC.starter(), startDetail));
    let world = runner.world;
    let rgba = null;
    let glow = null;
    let brgba = null;
    let img = null;
    let bimg = null;
    const st = {
      tool: M.SAND,
      radius: 4,
      speed: 2,
      detail: startDetail,
      paused: false,
      heat: false,
      bloom: 1,
      frameMs: 0,
      frame: 0,
      pace: 0,
    };

    const view = el("canvas", { class: "cru-view", "aria-label": "The forge: paint here" });
    const glowC = el("canvas", { class: "cru-bloom", "aria-hidden": "true" });
    const ring = el("div", { class: "cru-ring" });
    root.append(el("style", { text: CSS }), view, glowC, ring);
    const g = view.getContext("2d");
    const gg = glowC.getContext("2d");

    function buffers() {
      const { w, h } = world;
      const { bw, bh } = R.bloomSize(w, h, world.detail);
      view.width = w;
      view.height = h;
      glowC.width = bw;
      glowC.height = bh;
      rgba = new Uint8ClampedArray(w * h * 4);
      glow = new Float32Array(bw * bh * 3);
      brgba = new Uint8ClampedArray(bw * bh * 4);
      img = new ImageData(rgba, w, h);
      bimg = new ImageData(brgba, bw, bh);
      layout();
    }

    // --- the dock: materials, tools, brush ----------------------------------------------
    const swatches = [];
    const swatch = (p) => {
      const b = el(
        "button",
        {
          type: "button",
          class: `cru-sw${p.adv ? " adv" : ""}`,
          title: p.tip,
          on: { click: () => setTool(p.tool) },
        },
        el("span", { class: "cru-dot", style: { background: rgbCss(p.color) } }),
        p.label,
      );
      swatches.push({ tool: p.tool, el: b });
      return b;
    };
    const brushS = slider({
      label: "Brush",
      min: 1,
      max: 14,
      step: 1,
      value: st.radius,
      title: "Brush size; it covers the same patch of screen at every detail ([ and ] change it)",
      oninput: (v) => {
        st.radius = v;
        ringSize();
      },
    });
    const detailS = slider({
      label: "Detail",
      min: 1,
      max: S.MAX_DETAIL,
      step: 1,
      value: st.detail,
      title:
        "How fine the grains are: 1 is the original 240 by 135 grid, 2 is 480 by 270, 3 is 720 by 405 and slow on this laptop. Changing it keeps the scene you have; going down a step merges fine grains into bigger ones.",
      oninput: (v) => detailSoon(v),
    });
    // the detail changes once the slider settles (let go, or a moment without moving),
    // so dragging across a value, or typing in the box, does not coarsen the scene on the way
    let detailTimer = 0;
    function detailSoon(v) {
      clearTimeout(detailTimer);
      detailTimer = setTimeout(() => setDetail(v), 350);
    }
    detailS.el.addEventListener("change", () => {
      clearTimeout(detailTimer);
      setDetail(detailS.get());
    });
    const dock = el(
      "div",
      { class: "cru-dock" },
      el("div", { class: "cru-group", role: "group", "aria-label": "Materials" }, PALETTE.map(swatch)),
      el("span", { class: "cru-sep" }),
      el("div", { class: "cru-group", role: "group", "aria-label": "Tools" }, TOOL_LIST.map(swatch)),
      brushS.el,
      detailS.el,
    );
    root.append(dock);

    function setTool(tool) {
      st.tool = tool;
      for (const s of swatches) s.el.classList.toggle("on", s.tool === tool);
      ring.className = `cru-ring${tool === TOOLS.TORCH ? " torch" : tool === TOOLS.FROST ? " frost" : ""}`;
      ring.style.display = hover ? "block" : "none";
    }

    // --- the run panel ----------------------------------------------------------------
    const runP = panel("Crucible", { cls: "cru-run" });
    const pauseBtn = button("Pause", () => setPaused(!st.paused), { title: "Pause or run the forge (Space)" });
    const stepBtn = button("Step", () => stepOnce(), { title: "One step while paused (.)" });
    const resetBtn = button("Reset", () => reset(), { title: "Back to the starter forge" });
    const speedS = slider({
      label: "Speed",
      min: 1,
      max: 8,
      step: 1,
      value: st.speed,
      title:
        "How fast the world runs, in steps of the base grid per frame. At detail 2 and 3 this laptop cannot keep up with the top speeds; the readout (Advanced) shows the pace it really reaches.",
      oninput: (v) => (st.speed = v),
    });
    const heatT = toggle("Heat view", st.heat, (v) => setHeat(v), {
      title: "Colour every cell by its temperature, blue cold to white hot (H)",
    });
    const bloomS = slider({
      label: "Glow",
      min: 0,
      max: 2.5,
      step: 0.1,
      value: st.bloom,
      adv: true,
      title: "How strongly hot things light up the air around them",
      oninput: (v) => (st.bloom = v),
    });
    const roomS = slider({
      label: "Room",
      min: -30,
      max: 40,
      step: 1,
      value: world.ambient,
      adv: true,
      title: "Room temperature in degrees C: open air drifts towards it. Below zero, still water freezes.",
      oninput: (v) => {
        world.ambient = v;
        runner.queue(["ambient", v]);
      },
    });
    const readout = el("div", { class: "cru-readout ag-muted adv", title: "The cell under the pointer, and the cost of a frame" });
    const hint = el("div", {
      class: "cru-hint ag-muted",
      text: "Paint with the left button, erase with the right. Live coal glows: whatever touches it heats up.",
    });

    // keep form, inline
    const nameIn = el("input", { type: "text", placeholder: "Name", maxLength: 80, "aria-label": "Name" });
    const noteIn = el("textarea", { rows: 3, placeholder: "A note (optional)", maxLength: 2000, "aria-label": "Note" });
    const saveBtn = el("button", { type: "submit", class: "ag-btn primary", text: "Keep" });
    const cancelBtn = button("Cancel", () => showKeep(false), { kind: "ghost", title: "Close without keeping" });
    const keepForm = el("form", { class: "cru-keep", hidden: true }, nameIn, noteIn, el("div", { class: "ag-row end" }, cancelBtn, saveBtn));
    keepForm.addEventListener("submit", (e) => {
      e.preventDefault();
      keepIt();
    });
    const keepBtn = button("Keep this scene", () => showKeep(true), {
      kind: "primary",
      title: "Save the world as it is now, as a keepsake with a name and a note",
    });
    runP.body.append(
      el("div", { class: "ag-row" }, pauseBtn, stepBtn, resetBtn),
      speedS.el,
      el("div", { class: "ag-row" }, heatT.el),
      bloomS.el,
      roomS.el,
      el("div", { class: "ag-row" }, keepBtn),
      keepForm,
      readout,
      hint,
    );
    root.append(runP.el);

    function setPaused(on) {
      st.paused = on;
      pauseBtn.textContent = on ? "Run" : "Pause";
      pauseBtn.classList.toggle("primary", on);
    }
    // a brush that covers the same patch of screen at every detail
    const brush = () => st.radius * world.detail;
    function stepOnce() {
      if (!st.paused) setPaused(true);
      runner.later(world.detail); // one step of the base grid
    }
    function setDetail(v) {
      const d = Math.max(1, Math.min(S.MAX_DETAIL, Math.round(v) || 1));
      st.detail = d;
      saveDetail(d);
      if (d === world.detail) return;
      // the same scene, finer or coarser (coarser keeps the most common grain of each block)
      world = S.resample(world, d);
      runner.set(world);
      if (drawing) {
        drawing.x = (drawing.x + 0.5) * (world.w / drawing.w) - 0.5;
        drawing.y = (drawing.y + 0.5) * (world.w / drawing.w) - 0.5;
        drawing.w = world.w;
      }
      buffers();
    }
    function setHeat(on) {
      st.heat = on;
      heatT.set(on);
      glowC.classList.toggle("off", on);
    }
    function load(s, quiet) {
      // a keepsake finer than the setting opens at its own detail, so none of it is lost
      const d = Math.max(st.detail, s.detail || 1);
      if (d !== st.detail) {
        st.detail = d;
        detailS.set(d);
      }
      world = S.resample(s, d);
      runner.set(world);
      roomS.set(Math.round(world.ambient));
      buffers();
      if (!quiet) setPaused(false);
    }
    function reset() {
      load(SC.starter());
      ctx.toast("A fresh crucible on a lit coal bed.");
    }
    function showKeep(on) {
      keepForm.hidden = !on;
      keepBtn.hidden = on;
      if (on) {
        if (!nameIn.value) nameIn.value = `Forge at step ${world.tick}`;
        nameIn.focus();
        nameIn.select();
      }
    }
    async function keepIt() {
      const name = nameIn.value.trim();
      if (!name) {
        nameIn.focus();
        return;
      }
      saveBtn.disabled = true;
      try {
        const pic = document.createElement("canvas");
        pic.width = 480;
        pic.height = 270;
        drawStill(pic, world, { heat: st.heat, bloom: st.bloom, time: st.frame });
        const kept = encodeToKeep(world);
        await ctx.keep({ name, note: noteIn.value.trim(), data: kept.data, thumb: ctx.thumb(pic) });
        const coarser = kept.detail < world.detail ? ` at detail ${kept.detail}, the finest that fits` : "";
        ctx.toast(`Kept “${name}”${coarser}.`);
        nameIn.value = "";
        noteIn.value = "";
        showKeep(false);
      } catch (e) {
        ctx.toast(`Could not keep it: ${e.message}`);
      } finally {
        saveBtn.disabled = false;
      }
    }

    // --- layout: the grid fills the space above the dock ------------------------------
    let box = { x: 0, y: 0, w: 1, h: 1 };
    function layout() {
      const W = root.clientWidth;
      const H = Math.max(40, root.clientHeight - dock.offsetHeight);
      const det = world.detail;
      const dpr = window.devicePixelRatio || 1;
      // room in device pixels per cell of the base grid; whole pixels per cell where
      // that costs no size (render.js cellPixels), so a finer grid fills the same box
      const k = Math.max(0.1, Math.min(W / world.w, H / world.h)) * det * dpr;
      const kd = R.cellPixels(k, det) / dpr;
      const w = world.w * kd;
      const h = world.h * kd;
      box = { x: Math.round((W - w) / 2), y: Math.round((H - h) / 2), w, h };
      // the glow canvas has one texel per 4 base cells, so it can reach a little past the grid
      const { bw, bh } = R.bloomSize(world.w, world.h, world.detail);
      const reach = 4 * world.detail;
      const sizes = [
        [view, w, h],
        [glowC, (w * bw * reach) / world.w, (h * bh * reach) / world.h],
      ];
      for (const [c, cw, ch] of sizes) {
        c.style.left = `${box.x}px`;
        c.style.top = `${box.y}px`;
        c.style.width = `${cw}px`;
        c.style.height = `${ch}px`;
      }
      ringSize();
    }
    function ringSize() {
      const d = (2 * brush() + 1) * (box.w / world.w);
      ring.style.width = `${d}px`;
      ring.style.height = `${d}px`;
    }
    const ro = new ResizeObserver(() => layout());
    ro.observe(root);
    ro.observe(dock);

    // --- pointer drawing ----------------------------------------------------------------
    let drawing = null; // {tool, x, y, id}
    let hover = null; // {x, y} in cells, or null
    function cellAt(e) {
      const r = view.getBoundingClientRect();
      return {
        x: ((e.clientX - r.left) / r.width) * world.w - 0.5,
        y: ((e.clientY - r.top) / r.height) * world.h - 0.5,
        px: e.clientX - root.getBoundingClientRect().left,
        py: e.clientY - root.getBoundingClientRect().top,
      };
    }
    function moveRing(c) {
      ring.style.left = `${c.px}px`;
      ring.style.top = `${c.py}px`;
      ring.style.display = "block";
    }
    view.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 && e.button !== 2) return;
      e.preventDefault();
      const c = cellAt(e);
      const tool = e.button === 2 ? TOOLS.ERASE : st.tool;
      drawing = { tool, x: c.x, y: c.y, w: world.w, id: e.pointerId };
      view.setPointerCapture(e.pointerId);
      runner.queue(["paint", c.x, c.y, brush(), tool]);
      hover = c;
      moveRing(c);
    });
    view.addEventListener("pointermove", (e) => {
      const c = cellAt(e);
      hover = c;
      moveRing(c);
      if (!drawing || e.pointerId !== drawing.id) return;
      // every coalesced point, so a fast flick is followed as drawn
      const pts = e.getCoalescedEvents ? e.getCoalescedEvents() : [];
      for (const p of pts.length ? pts : [e]) {
        const q = cellAt(p);
        runner.queue(["stroke", drawing.x, drawing.y, q.x, q.y, brush(), drawing.tool]);
        drawing.x = q.x;
        drawing.y = q.y;
      }
    });
    const endStroke = (e) => {
      if (drawing && e.pointerId === drawing.id) drawing = null;
    };
    view.addEventListener("pointerup", endStroke);
    view.addEventListener("pointercancel", endStroke);
    view.addEventListener("pointerleave", (e) => {
      if (!drawing) {
        hover = null;
        ring.style.display = "none";
      }
      if (e.pointerType !== "mouse") endStroke(e);
    });
    view.addEventListener("contextmenu", (e) => e.preventDefault());

    // --- keys -----------------------------------------------------------------------------
    const KEY_TOOLS = { t: TOOLS.TORCH, c: TOOLS.FROST, e: TOOLS.ERASE };
    function onKey(e) {
      if (e.ctrlKey || e.altKey || e.metaKey || typing() || !root.isConnected) return;
      const k = e.key;
      if (k === " ") {
        if (document.activeElement && document.activeElement.tagName === "BUTTON") return;
        setPaused(!st.paused);
      } else if (k === ".") stepOnce();
      else if (k === "h" || k === "H") setHeat(!st.heat);
      else if (KEY_TOOLS[k]) setTool(KEY_TOOLS[k]);
      else if (k === "[" || k === "]") {
        brushS.set(st.radius + (k === "]" ? 1 : -1));
        st.radius = brushS.get();
        ringSize();
      } else if (/^[1-9]$/.test(k)) setTool(PALETTE[Number(k) - 1].tool);
      else return;
      e.preventDefault();
    }
    window.addEventListener("keydown", onKey);

    const offMode = ctx.onMode((adv) => {
      if (!adv && PALETTE.some((p) => p.adv && p.tool === st.tool)) setTool(M.SAND);
      layout();
    });

    // --- the frame ------------------------------------------------------------------------
    function describeHover() {
      if (!hover) return "Point at a cell to read its temperature.";
      const x = Math.round(hover.x);
      const y = Math.round(hover.y);
      if (!S.inside(world, x, y)) return "Point at a cell to read its temperature.";
      const i = y * world.w + x;
      const m = MATERIALS[world.mat[i]].label;
      return `${m}, ${Math.round(world.temp[i])} C`;
    }
    // the share of the asked steps the world really took, over about a second of running
    let paceAt = { t: 0, tick: 0, world: null, asked: 0 };
    function pace(now) {
      const restart = paceAt.world !== world || world.tick < paceAt.tick || st.paused || now - paceAt.t > 2000;
      if (restart) {
        paceAt = { t: now, tick: world.tick, world, asked: 0 };
        return;
      }
      paceAt.asked += st.speed * world.detail;
      if (now - paceAt.t < 1000) return;
      st.pace = (world.tick - paceAt.tick) / paceAt.asked;
      paceAt = { t: now, tick: world.tick, world, asked: 0 };
    }
    const loop = ctx.loop(() => {
      const t0 = performance.now();
      if (!st.paused) {
        // a brush held still keeps pouring (or heating): one dab per frame's worth of
        // steps, wherever the steps are taken and however far behind they run
        runner.hold(drawing ? ["paint", drawing.x, drawing.y, brush(), drawing.tool] : null);
        // a finer world takes detail steps for each step of the base grid, so it keeps the same pace
        runner.run(st.speed * world.detail);
      } else {
        runner.hold(null);
        runner.run(0); // strokes made while paused still land
      }
      pace(t0);
      st.frame++;
      R.render(world, rgba, st.heat ? null : glow, { heat: st.heat, time: st.frame });
      g.putImageData(img, 0, 0);
      if (!st.heat) {
        const { bw, bh } = R.bloomSize(world.w, world.h, world.detail);
        R.bloom(glow, bw, bh, brgba, st.bloom, world.detail);
        gg.putImageData(bimg, 0, 0);
      }
      const ms = performance.now() - t0;
      st.frameMs = st.frameMs ? st.frameMs * 0.9 + ms * 0.1 : ms;
      if (st.frame % 10 === 0) {
        // the worker's time for one frame's steps, beside the page's own
        const stepping = runner.stepMs * st.speed * world.detail;
        const alongside = runner.threaded ? `, plus ${stepping.toFixed(1)} ms of steps alongside` : "";
        const behind = !st.paused && st.pace > 0 && st.pace < 0.9 ? `, running at ${Math.round(100 * st.pace)}% of the speed asked` : "";
        readout.textContent = `${describeHover()}\n${world.w} by ${world.h} cells, step ${world.tick}, ${st.frameMs.toFixed(1)} ms a frame${alongside}${behind}`;
      }
    });

    // --- start ------------------------------------------------------------------------------
    setTool(M.SAND);
    buffers();

    return {
      unmount() {
        loop.stop();
        clearTimeout(detailTimer);
        runner.stop();
        ro.disconnect();
        offMode();
        window.removeEventListener("keydown", onKey);
        drawing = null;
      },
      open(keepsake) {
        let s;
        try {
          s = C.decode(keepsake && keepsake.data);
        } catch (e) {
          ctx.toast(`Cannot open it: ${e.message}`);
          return;
        }
        const before = st.detail;
        load(s);
        const own = st.detail !== before ? ` at detail ${st.detail}, the detail it was kept at` : "";
        if (keepsake && keepsake.name) ctx.toast(`Opened “${keepsake.name}”${own}.`);
      },
      onEscape() {
        if (!keepForm.hidden) {
          showKeep(false);
          return true;
        }
        return false;
      },
    };
  },

  preview(canvas, keepsake) {
    let s = null;
    if (keepsake) {
      try {
        s = C.decode(keepsake.data);
      } catch {
        // an unreadable keepsake shows the forge instead
      }
    }
    drawStill(canvas, s || SC.showcase());
  },
};
