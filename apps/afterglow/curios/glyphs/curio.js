/* Glyphs: the browser side. Everything with a DOM lives here; the language
 * (lang.js), Compose (compose.js) and the drawing (render.js) are pure. */

import { prepare, geometry, evalFrame, VARIABLES, FUNCTIONS } from "./lang.js";
import { compose } from "./compose.js";
import { PALETTES, GRID_MIN, GRID_MAX, SPEED_MAX, drawField, ease, fieldBox, dotAt, cleanPiece } from "./render.js";
import { freshSeed } from "../_kit/rng.js";

/** The piece the curio opens with and the shelf card shows. */
const FAVOURITE = {
  name: "Spiral clock",
  data: { formula: "sin(a*3 - r*0.7 + t*2) * (1 - r/12)", grid: 16, speed: 1, palette: "ember", shape: "circle" },
};
const FAVOURITE_T = 2.2;
const SHAPE_OPTIONS = [
  { value: "circle", label: "Circle", title: "Round dots" },
  { value: "square", label: "Square", title: "Square dots" },
  { value: "diamond", label: "Diamond", title: "Dots turned into diamonds" },
];

const typing = (node) =>
  !!node && (node.tagName === "INPUT" || node.tagName === "TEXTAREA" || node.tagName === "SELECT" || node.isContentEditable);

/** Draw one frame of a piece, filling the canvas. */
function still(canvas, data, t) {
  const piece = cleanPiece(data);
  const prep = prepare(piece.formula);
  const fn = prep.ok ? prep.fn : prepare(FAVOURITE.data.formula).fn;
  const n = piece.grid;
  const values = evalFrame(fn, t, geometry(n), new Float64Array(n * n));
  const g = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  const size = Math.min(w, h) * 0.86;
  g.setTransform(1, 0, 0, 1, 0, 0);
  drawField(g, { w, h, box: { x: (w - size) / 2, y: (h - size) / 2, size }, n, values, ...piece });
}

export default {
  async mount(root, ctx) {
    const { ui } = ctx;
    const { el } = ui;
    let alive = true;
    const piece = cleanPiece(FAVOURITE.data);
    let fn = prepare(piece.formula).fn;
    let geo = geometry(piece.grid);
    let target = new Float64Array(piece.grid * piece.grid);
    let shown = new Float64Array(piece.grid * piece.grid);
    let time = 0;
    let paused = false;
    let glow = true;
    let last = 0;
    let dirty = true;
    let settling = true;
    let hover = -1;
    let box = { x: 0, y: 0, size: 100 };
    let w = 1;
    let h = 1;
    let charW = 9;
    let shownTime = "";
    let shownReadout = "";

    const wrap = el("div", { class: "glyphs", dataset: { palette: piece.palette } });
    wrap.append(el("link", { rel: "stylesheet", href: `${ctx.base}glyphs.css`, on: { load: () => layout() } }));
    const canvas = el("canvas", { class: "gl-canvas", title: "Click a dot to pause or play" });
    const g = canvas.getContext("2d");

    // --- the field panel (top left) ---
    const fieldPanel = ui.panel("Field", { cls: "gl-field", fold: true, folded: { width: 600 } });
    const grid = ui.slider({
      label: "Grid",
      min: GRID_MIN,
      max: GRID_MAX,
      step: 1,
      value: piece.grid,
      title: "How many dots along each side",
      oninput: (v) => setGrid(v),
    });
    const speed = ui.slider({
      label: "Speed",
      min: 0,
      max: SPEED_MAX,
      step: 0.05,
      value: piece.speed,
      title: "How fast time runs for the formula; 0 holds it still",
      oninput: (v) => {
        piece.speed = v;
      },
    });
    const palette = ui.seg(
      Object.entries(PALETTES).map(([value, p]) => ({ value, label: p.label, title: p.title })),
      piece.palette,
      (v) => {
        piece.palette = v;
        wrap.dataset.palette = v;
        dirty = true;
      },
      { title: "Colours for positive and negative values" },
    );
    const shape = ui.seg(
      SHAPE_OPTIONS,
      piece.shape,
      (v) => {
        piece.shape = v;
        dirty = true;
      },
      { title: "The shape of each dot" },
    );
    const glowToggle = ui.toggle(
      "Soft glow",
      true,
      (v) => {
        glow = v;
        dirty = true;
      },
      { adv: true, title: "A faint halo around the brightest dots (Ember and Sea)" },
    );
    const fromZero = ui.button("Time from zero", () => {
      time = 0;
      dirty = true;
    }, { adv: true, title: "Start the clock t again at 0" });
    fieldPanel.body.append(
      grid.el,
      speed.el,
      el("div", { class: "gl-seg-row" }, el("span", { class: "ag-slider-label", text: "Colours" }), palette.el),
      el("div", { class: "gl-seg-row adv" }, el("span", { class: "ag-slider-label", text: "Dots" }), shape.el),
      el("div", { class: "ag-row adv gl-tools" }, glowToggle.el, fromZero),
    );

    // --- the help card (Advanced) ---
    const help = ui.panel("Words it knows", { adv: true, cls: "gl-help", fold: true, folded: { width: 760 } });
    const chip = (text, insert, title) =>
      el("button", { type: "button", class: "gl-chip", text, title, on: { click: () => insertAtCaret(insert) } });
    help.body.append(
      el("p", { class: "gl-help-line", text: "Click a word to put it into the formula." }),
      el("div", { class: "gl-chips" }, Object.entries(VARIABLES).map(([k, d]) => chip(k, k, `${k}: ${d}`))),
      el("div", { class: "gl-chips" }, ["PI", "TAU"].map((k) => chip(k, k, k === "PI" ? "3.14159..." : "2 x PI"))),
      el(
        "div",
        { class: "gl-chips fns" },
        Object.entries(FUNCTIONS).map(([k, spec]) => chip(k, `${k}(`, `${k}: ${spec[3]}`)),
      ),
      el("p", {
        class: "gl-help-line",
        text: "+ - * / % and ** (or ^); < <= > >= == != give 1 or 0; && || ! and c ? a : b; & | on whole numbers.",
      }),
      el("p", { class: "gl-help-line", text: "Bigger |value| means a bigger dot, up to 1. Dividing by zero just gives 0." }),
    );
    const left = el("div", { class: "gl-left" }, fieldPanel.el, help.el);

    // --- the gallery (top right) ---
    const gallery = ui.panel("Claude's pieces", { cls: "gl-gallery", fold: true, folded: { width: 760 } });
    gallery.body.append(el("p", { class: "ag-muted gl-small", text: "Loading..." }));
    let activeSlug = "";

    // --- the formula bar (bottom) ---
    const nameEl = el("span", { class: "gl-name", text: FAVOURITE.name });
    const seedBadge = el("span", { class: "ag-badge adv", hidden: true, title: "The Compose seed that wrote this piece" });
    const timeEl = el("span", { class: "gl-time adv", title: "The clock t the formula sees" });
    const input = el("input", {
      class: "gl-formula",
      type: "text",
      spellcheck: false,
      autocomplete: "off",
      maxlength: 400,
      value: piece.formula,
      title: "The formula, run for every dot every frame. Edit it: it plays as soon as it makes sense",
      "aria-label": "Formula",
    });
    const caret = el("span", { class: "gl-caret", hidden: true });
    const status = el("div", { class: "gl-status", "aria-live": "polite" });
    const pauseBtn = ui.button("Pause", () => togglePause(), { kind: "ghost", title: "Pause or play the clock (Space)" });
    const composeBtn = ui.button("Compose", () => composeNew(), {
      kind: "primary",
      title: "Let Claude write a new piece from a random seed",
    });
    const keepBtn = ui.button("Keep", () => openKeep(), { title: "Keep this piece with a name and a note" });
    const bar = el(
      "section",
      { class: "ag-panel gl-bar" },
      el("div", { class: "gl-head" }, nameEl, seedBadge, timeEl),
      el("div", { class: "gl-input" }, el("span", { class: "gl-fx", text: "f(t,i,x,y) =" }), input, caret),
      el("div", { class: "gl-foot" }, status, pauseBtn, composeBtn, keepBtn),
    );

    // --- the keep form (over the bar) ---
    const keepName = el("input", { type: "text", maxlength: 80, title: "A name for this piece", "aria-label": "Name" });
    const keepNote = el("textarea", { rows: 2, maxlength: 4000, title: "An optional note", "aria-label": "Note" });
    const keepForm = el(
      "form",
      { class: "ag-panel gl-keep", hidden: true },
      el("h3", { text: "Keep this piece" }),
      el("label", { class: "gl-field-label" }, "Name", keepName),
      el("label", { class: "gl-field-label" }, "Note (optional)", keepNote),
      el(
        "div",
        { class: "ag-row end" },
        ui.button("Cancel", () => closeKeep(), { kind: "ghost", title: "Close without keeping" }),
        el("button", { type: "submit", class: "ag-btn primary", text: "Keep it", title: "Save it to the kept pieces" }),
      ),
    );
    keepForm.addEventListener("submit", (e) => {
      e.preventDefault();
      saveKeep();
    });

    const readout = el("div", { class: "gl-readout", hidden: true });
    wrap.append(canvas, left, gallery.el, readout, bar, keepForm);
    root.append(wrap);

    // --- behaviour ---
    function setStatus(text, bad = false) {
      status.textContent = text;
      status.classList.toggle("bad", bad);
    }
    function okStatus() {
      setStatus(`Playing ${piece.grid * piece.grid} dots. Space pauses; hover a dot to read it.`);
      input.classList.remove("bad");
      caret.hidden = true;
    }

    function tryFormula(src) {
      const prep = prepare(src);
      if (prep.ok) {
        fn = prep.fn;
        piece.formula = src;
        dirty = true;
        okStatus();
        return true;
      }
      const { message, col } = prep.error;
      setStatus(`Column ${col}: ${message}. The last good piece keeps playing.`, true);
      input.classList.add("bad");
      placeCaret(col);
      return false;
    }

    function placeCaret(col) {
      const cs = getComputedStyle(input);
      const x = input.offsetLeft + parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth);
      const at = x + (col - 1) * charW - input.scrollLeft;
      const max = input.offsetLeft + input.offsetWidth - 10;
      caret.style.left = `${Math.min(max, Math.max(input.offsetLeft + 4, at))}px`;
      caret.hidden = false;
    }

    function setTitle(text, seed) {
      nameEl.textContent = text;
      seedBadge.hidden = seed === undefined;
      if (seed !== undefined) seedBadge.textContent = `seed ${seed}`;
    }

    function setFormula(src) {
      input.value = src;
      tryFormula(src);
    }

    function insertAtCaret(text) {
      const start = input.selectionStart ?? input.value.length;
      const end = input.selectionEnd ?? start;
      input.focus();
      input.setRangeText(text, start, end, "end");
      edited();
    }

    function edited() {
      if (tryFormula(input.value)) {
        setTitle("Your piece");
        markActive("");
      }
    }
    input.addEventListener("input", edited);
    input.addEventListener("scroll", () => {
      if (!caret.hidden) tryFormula(input.value);
    });

    function setGrid(v) {
      const n = Math.round(v);
      if (n === piece.grid) return;
      piece.grid = n;
      geo = geometry(n);
      target = new Float64Array(n * n);
      shown = new Float64Array(n * n);
      dirty = true;
      if (!status.classList.contains("bad")) okStatus();
    }

    function togglePause() {
      paused = !paused;
      pauseBtn.textContent = paused ? "Play" : "Pause";
      wrap.classList.toggle("paused", paused);
      dirty = true;
    }

    function composeNew() {
      const seed = freshSeed();
      const p = compose(seed);
      setFormula(p.formula);
      setTitle(p.title, seed);
      markActive("");
    }

    function apply(data, name, slug = "") {
      const p = cleanPiece(data);
      grid.set(p.grid);
      setGrid(p.grid);
      speed.set(p.speed);
      piece.speed = p.speed;
      palette.set(p.palette);
      piece.palette = p.palette;
      wrap.dataset.palette = p.palette;
      shape.set(p.shape);
      piece.shape = p.shape;
      time = 0;
      setFormula(p.formula);
      setTitle(name || "Untitled piece");
      markActive(slug);
      dirty = true;
    }

    function openKeep() {
      keepName.value = nameEl.textContent === "Your piece" ? "" : nameEl.textContent;
      keepNote.value = "";
      keepForm.hidden = false;
      keepName.focus();
      keepName.select();
    }
    function closeKeep() {
      keepForm.hidden = true;
    }
    async function saveKeep() {
      const name = keepName.value.trim();
      if (!name) {
        ctx.toast("Give it a name first.");
        keepName.focus();
        return;
      }
      const data = { ...piece };
      const pic = document.createElement("canvas");
      pic.width = 320;
      pic.height = 320;
      still(pic, data, time);
      try {
        await ctx.keep({ name, note: keepNote.value.trim(), data, thumb: ctx.thumb(pic) });
        if (!alive) return;
        closeKeep();
        setTitle(name);
        ctx.toast(`Kept "${name}".`);
      } catch (e) {
        if (alive) ctx.toast(`Not kept: ${e.message}`);
      }
    }

    function markActive(slug) {
      activeSlug = slug;
      for (const b of gallery.body.querySelectorAll(".gl-piece")) b.classList.toggle("on", b.dataset.slug === slug);
    }

    async function loadGallery() {
      try {
        const rows = (await ctx.keepsakes()).filter((r) => r.seed);
        const full = await Promise.all(rows.map((r) => ctx.loadKeepsake(r.slug)));
        if (!alive) return;
        gallery.body.replaceChildren();
        const dpr = Math.min(2, window.devicePixelRatio || 1);
        for (const k of full) {
          const pic = el("canvas", { "aria-hidden": "true" });
          pic.width = pic.height = Math.round(40 * dpr);
          still(pic, k.data, 1);
          gallery.body.append(
            el(
              "button",
              {
                type: "button",
                class: "gl-piece",
                dataset: { slug: k.slug },
                title: k.note || k.name,
                on: { click: () => apply(k.data, k.name, k.slug) },
              },
              pic,
              el("span", { text: k.name }),
            ),
          );
        }
        if (!full.length) gallery.body.append(el("p", { class: "ag-muted gl-small", text: "No pieces shipped." }));
        markActive(activeSlug);
      } catch (e) {
        if (!alive) return;
        gallery.body.replaceChildren(el("p", { class: "ag-muted gl-small", text: `The pieces did not load: ${e.message}` }));
      }
    }

    function layout() {
      if (!alive) return;
      const rect = root.getBoundingClientRect();
      w = Math.max(1, rect.width);
      h = Math.max(1, rect.height);
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      wrap.style.setProperty("--gl-bar", `${bar.offsetHeight}px`);
      const pad = 14;
      const leftEdge = left.offsetLeft + left.offsetWidth + pad;
      const rightEdge = gallery.el.offsetWidth ? gallery.el.offsetLeft - pad : w - pad;
      box = fieldBox(w, h, { left: leftEdge, right: rightEdge, top: pad, bottom: bar.offsetTop - pad });
      const probe = document.createElement("canvas").getContext("2d");
      probe.font = getComputedStyle(input).font;
      charW = probe.measureText("0000000000").width / 10 || 9;
      readout.style.left = `${box.x}px`;
      readout.style.top = `${Math.max(4, box.y - 26)}px`;
      if (!caret.hidden) tryFormula(input.value);
      dirty = true;
    }

    canvas.addEventListener("pointermove", (e) => {
      const r = canvas.getBoundingClientRect();
      hover = dotAt(box, piece.grid, e.clientX - r.left, e.clientY - r.top);
      readout.hidden = hover < 0;
      canvas.style.cursor = hover < 0 ? "default" : "pointer";
    });
    canvas.addEventListener("pointerleave", () => {
      hover = -1;
      readout.hidden = true;
    });
    canvas.addEventListener("click", (e) => {
      const r = canvas.getBoundingClientRect();
      if (dotAt(box, piece.grid, e.clientX - r.left, e.clientY - r.top) >= 0) togglePause();
    });

    const onKey = (e) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.key !== " ") return;
      if (typing(e.target) || (e.target && e.target.tagName === "BUTTON")) return;
      if (!root.isConnected || root.offsetParent === null) return;
      e.preventDefault();
      togglePause();
    };
    window.addEventListener("keydown", onKey);

    const ro = new ResizeObserver(() => layout());
    for (const node of [root, left, gallery.el, bar]) ro.observe(node);
    const offMode = ctx.onMode(() => layout());

    const loop = ctx.loop((now) => {
      const dt = last ? Math.min(0.1, (now - last) / 1000) : 0;
      last = now;
      if (!paused) time += dt * piece.speed;
      const moving = !paused && piece.speed > 0;
      if (moving || dirty || settling) {
        evalFrame(fn, time, geo, target);
        settling = ease(shown, target, dt, 11) > 0.002;
        drawField(g, { w, h, box, n: piece.grid, values: shown, palette: piece.palette, shape: piece.shape, glow });
        dirty = false;
      }
      const tt = `t = ${time.toFixed(1)}`;
      if (tt !== shownTime) timeEl.textContent = shownTime = tt;
      if (hover >= 0 && hover < target.length) {
        const n = piece.grid;
        const text = `x ${hover % n}  y ${Math.floor(hover / n)}  i ${hover}  →  ${target[hover].toFixed(2)}`;
        if (text !== shownReadout) readout.textContent = shownReadout = text;
      }
    });

    okStatus();
    layout();
    loadGallery();

    return {
      unmount() {
        alive = false;
        loop.stop();
        ro.disconnect();
        offMode();
        window.removeEventListener("keydown", onKey);
      },
      open(keepsake) {
        if (keepsake && keepsake.data) apply(keepsake.data, keepsake.name, keepsake.seed ? keepsake.slug : "");
      },
      onEscape() {
        if (!keepForm.hidden) {
          closeKeep();
          return true;
        }
        const focused = document.activeElement;
        if (focused && root.contains(focused) && typing(focused)) {
          focused.blur();
          return true;
        }
        return false;
      },
    };
  },

  preview(canvas, keepsake) {
    if (keepsake && keepsake.data) still(canvas, keepsake.data, 1);
    else still(canvas, FAVOURITE.data, FAVOURITE_T);
  },
};
