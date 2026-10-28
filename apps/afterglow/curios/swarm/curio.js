/* Swarm: the browser side. The simulation (sim.js) and the drawing
 * (render.js) are pure; this file owns the canvas, the panels and the keys. */

import {
  LIMITS,
  cleanRules,
  clumping,
  createSwarm,
  mirrorRules,
  poke,
  randomRules,
  recount,
  reshape,
  resizeRules,
  step,
} from "./sim.js";
import { COLOURS, NAMES, drawSwarm, smallSwarm, stillSwarm } from "./render.js";
import { rng, freshSeed } from "../_kit/rng.js";

/** The swarm the curio opens with and the shelf card shows (seeds/cell-weather.json). */
export const FAVOURITE = {
  name: "Cell weather",
  data: {
    colours: 5,
    matrix: [
      0.85, -0.35, -0.55, -0.85, -0.55, 0, -0.85, 0.95, 0.25, 0.4, 0.55, -0.25, 0.45, 0.75, 0.05, 0.5, -0.15, 0, 0.45,
      0.85, 0.95, -0.05, -0.3, 0.6, -0.45,
    ],
    count: 1400,
    reach: 0.1,
    pull: 10,
    glide: 0.04,
    seed: 4,
  },
};
const CELL_STEP = 0.25;

const typing = (node) =>
  !!node && (node.tagName === "INPUT" || node.tagName === "TEXTAREA" || node.tagName === "SELECT" || node.isContentEditable);

/** How a rule reads in words, for the table's readout. */
function ruleWords(m, k, i, j) {
  const v = m[i * k + j];
  const a = NAMES[i];
  const b = i === j ? "its own colour" : NAMES[j];
  if (v === 0) return `${a} ignores ${b} (0)`;
  return v > 0 ? `${a} is pulled toward ${b} (${v.toFixed(2)})` : `${a} is pushed from ${b} (${v.toFixed(2)})`;
}

function cellColour(v) {
  if (v === 0) return "rgba(255, 255, 255, 0.04)";
  const a = 0.16 + Math.abs(v) * 0.7;
  return v > 0 ? `rgba(255, 180, 84, ${a})` : `rgba(165, 139, 255, ${a})`;
}

export default {
  async mount(root, ctx) {
    const { ui } = ctx;
    const { el } = ui;
    let alive = true;
    let rules = cleanRules(FAVOURITE.data);
    let sw = createSwarm(rules, 16 / 9);
    let paused = false;
    let trails = true;
    let fresh = true;
    let last = 0;
    let w = 1;
    let h = 1;
    let dpr = 1;
    let held = null;
    let measuredAt = 0;
    let shownGather = "";

    const wrap = el("div", { class: "swarm" });
    wrap.append(el("link", { rel: "stylesheet", href: `${ctx.base}swarm.css`, on: { load: () => layout() } }));
    const canvas = el("canvas", {
      class: "sw-canvas",
      title: "Click or drag to push the swarm apart; hold Shift to pull it in",
    });
    const g = canvas.getContext("2d");

    // --- the main panel (top left) ---
    const main = ui.panel("Swarm", { cls: "sw-main", fold: true, folded: { width: 700, height: 560 } });
    const countSlider = ui.slider({
      label: "Particles",
      ...LIMITS.count,
      value: rules.count,
      title: "How many particles there are; more is slower",
      oninput: (v) => setCount(v),
    });
    const colourSlider = ui.slider({
      label: "Colours",
      ...LIMITS.colours,
      value: rules.colours,
      title: "How many kinds of particle the rules tell apart",
      oninput: (v) => setColours(v),
    });
    const reachSlider = ui.slider({
      label: "Reach",
      ...LIMITS.reach,
      value: rules.reach,
      adv: true,
      title: "How far a particle feels the others, as a share of the height; more is slower",
      oninput: (v) => {
        rules.reach = v;
        changed();
      },
    });
    const pullSlider = ui.slider({
      label: "Pull",
      ...LIMITS.pull,
      value: rules.pull,
      adv: true,
      title: "How hard the rules push and pull",
      oninput: (v) => {
        rules.pull = v;
        changed();
      },
    });
    const glideSlider = ui.slider({
      label: "Glide",
      ...LIMITS.glide,
      value: rules.glide,
      adv: true,
      title: "Seconds a particle takes to lose half its speed; more glides further",
      oninput: (v) => {
        rules.glide = v;
        changed();
      },
    });
    const trailToggle = ui.toggle(
      "Trails",
      true,
      (v) => {
        trails = v;
      },
      { adv: true, title: "Let movement leave a short streak" },
    );
    const gatherEl = el("span", {
      class: "sw-gather ag-muted adv",
      title: "Neighbours within half a reach, against an even scatter: about 1 is even, more is gathered",
    });
    const newBtn = ui.button("New rules", () => newRules(), {
      kind: "primary",
      title: "Roll a fresh rule table and scatter the particles",
    });
    const scatterBtn = ui.button("Scatter", () => scatter(), {
      title: "Throw the particles back to random places, same rules",
    });
    const pauseBtn = ui.button("Pause", () => togglePause(), { kind: "ghost", title: "Pause or play (Space)" });
    const keepBtn = ui.button("Keep", () => openKeep(), { title: "Keep these rules with a name and a note" });
    main.body.append(
      countSlider.el,
      colourSlider.el,
      reachSlider.el,
      pullSlider.el,
      glideSlider.el,
      el("div", { class: "ag-row adv sw-tools" }, trailToggle.el, gatherEl),
      el("div", { class: "ag-row sw-buttons" }, newBtn, scatterBtn, pauseBtn, keepBtn),
    );

    // --- the rule table (Advanced) ---
    const table = ui.panel("Rules", { cls: "sw-rules", adv: true, fold: true, folded: { width: 900 } });
    const grid = el("div", { class: "sw-grid", role: "grid", "aria-label": "Rule table" });
    const ruleLine = el("p", { class: "sw-rule-line ag-muted", text: "Rows feel columns. Click to pull more, Shift-click or right-click to push." });
    const tableTools = el(
      "div",
      { class: "ag-row sw-table-tools" },
      ui.button("Mirror", () => mirror(), {
        kind: "ghost",
        title: "Make every pair feel each other the same way (copy the top right over the bottom left)",
      }),
      ui.button("Shuffle", () => shuffle(), { kind: "ghost", title: "New rules, particles left where they are" }),
      ui.button("Clear", () => clearRules(), { kind: "ghost", title: "Set every rule to 0" }),
    );
    table.body.append(grid, ruleLine, tableTools);

    // --- the shipped swarms, and any Claude kept from play.py (under the main panel) ---
    const gallery = ui.panel("Claude's swarms", { cls: "sw-gallery", fold: true, folded: { width: 900, height: 680 } });
    gallery.body.append(el("p", { class: "ag-muted sw-small", text: "Loading..." }));
    let activeSlug = "cell-weather";

    const left = el("div", { class: "sw-left" }, main.el, gallery.el);

    // --- the name (bottom left) ---
    const nameEl = el("div", { class: "sw-name", text: FAVOURITE.name });
    const pausedEl = el("span", { class: "sw-paused", text: "Paused", hidden: true });
    const nameRow = el("div", { class: "sw-name-row" }, nameEl, pausedEl);

    // --- the keep form ---
    const keepName = el("input", { type: "text", maxlength: 80, title: "A name for this swarm", "aria-label": "Name" });
    const keepNote = el("textarea", { rows: 2, maxlength: 4000, title: "An optional note", "aria-label": "Note" });
    const keepForm = el(
      "form",
      { class: "ag-panel sw-keep", hidden: true },
      el("h3", { text: "Keep this swarm" }),
      el("label", { class: "sw-field-label" }, "Name", keepName),
      el("label", { class: "sw-field-label" }, "Note (optional)", keepNote),
      el(
        "div",
        { class: "ag-row end" },
        ui.button("Cancel", () => closeKeep(), { kind: "ghost", title: "Close without keeping" }),
        el("button", { type: "submit", class: "ag-btn primary", text: "Keep it", title: "Save it to the kept swarms" }),
      ),
    );
    keepForm.addEventListener("submit", (e) => {
      e.preventDefault();
      saveKeep();
    });

    wrap.append(canvas, left, table.el, nameRow, keepForm);
    root.append(wrap);

    function buildTable() {
      const k = rules.colours;
      grid.style.setProperty("--sw-k", String(k + 1));
      const dot = (c) => {
        const node = el("span", { class: "sw-dot", title: NAMES[c] });
        node.style.setProperty("--c", COLOURS[c]);
        return node;
      };
      const cells = [el("span", { class: "sw-corner", "aria-hidden": "true" })];
      for (let j = 0; j < k; j++) cells.push(dot(j));
      for (let i = 0; i < k; i++) {
        cells.push(dot(i));
        for (let j = 0; j < k; j++) {
          const words = ruleWords(rules.matrix, k, i, j);
          cells.push(
            el("button", {
              type: "button",
              class: "sw-cell",
              dataset: { i: String(i), j: String(j) },
              title: words,
              "aria-label": words,
              style: { background: cellColour(rules.matrix[i * k + j]) },
            }),
          );
        }
      }
      grid.replaceChildren(...cells);
    }

    function nudgeCell(button, by) {
      const k = rules.colours;
      const i = Number(button.dataset.i);
      const j = Number(button.dataset.j);
      const at = i * k + j;
      rules.matrix[at] = Number(Math.min(1, Math.max(-1, rules.matrix[at] + by)).toFixed(2)) || 0;
      const words = ruleWords(rules.matrix, k, i, j);
      button.style.background = cellColour(rules.matrix[at]);
      button.title = words;
      button.setAttribute("aria-label", words);
      ruleLine.textContent = words;
      changed();
    }
    grid.addEventListener("click", (e) => {
      const b = e.target.closest(".sw-cell");
      if (b) nudgeCell(b, e.shiftKey ? -CELL_STEP : CELL_STEP);
    });
    grid.addEventListener("contextmenu", (e) => {
      const b = e.target.closest(".sw-cell");
      if (!b) return;
      e.preventDefault();
      nudgeCell(b, -CELL_STEP);
    });
    grid.addEventListener("pointerover", (e) => {
      const b = e.target.closest(".sw-cell");
      if (b) ruleLine.textContent = b.title;
    });

    function setName(text) {
      nameEl.textContent = text;
    }
    /** The rules moved away from whatever was opened. */
    function changed() {
      if (nameEl.textContent !== "Your swarm") setName("Your swarm");
      if (activeSlug) markActive("");
      setAddress("");
    }
    /** Keeps the address naming the swarm on show, without a new history step.
     *  The router acts only when the address changes, so a stale one would make
     *  the Kept drawer's Open do nothing and a reload open the wrong swarm. */
    function setAddress(slug) {
      const here = `#${ctx.id}`;
      if (!alive || (location.hash !== here && !location.hash.startsWith(`${here}/`))) return;
      const want = slug ? `${here}/${encodeURIComponent(slug)}` : here;
      if (location.hash !== want) history.replaceState(history.state, "", want);
    }

    function aspect() {
      return w / Math.max(1, h);
    }
    function setCount(v) {
      rules.count = v;
      sw = recount(sw, v, rng(freshSeed()));
      changed();
    }
    function setColours(k) {
      if (k === rules.colours) return;
      rules.matrix = resizeRules(rules.matrix, rules.colours, k, rng(freshSeed()));
      rules.colours = k;
      sw.k = k;
      buildTable();
      changed();
    }
    function scatter() {
      rules.seed = freshSeed();
      sw = createSwarm(rules, aspect());
      fresh = true;
    }
    function newRules() {
      rules.matrix = randomRules(rng(freshSeed()), rules.colours);
      buildTable();
      scatter();
      setName("Your swarm");
      markActive("");
      setAddress("");
    }
    function shuffle() {
      rules.matrix = randomRules(rng(freshSeed()), rules.colours);
      buildTable();
      changed();
    }
    function mirror() {
      rules.matrix = mirrorRules(rules.matrix, rules.colours);
      buildTable();
      changed();
    }
    function clearRules() {
      rules.matrix.fill(0);
      buildTable();
      changed();
    }
    function togglePause() {
      paused = !paused;
      pauseBtn.textContent = paused ? "Play" : "Pause";
      pausedEl.hidden = !paused;
    }

    function apply(data, name, slug = "") {
      rules = cleanRules(data);
      countSlider.set(rules.count);
      colourSlider.set(rules.colours);
      reachSlider.set(rules.reach);
      pullSlider.set(rules.pull);
      glideSlider.set(rules.glide);
      sw = createSwarm(rules, aspect());
      fresh = true;
      buildTable();
      setName(name || "Untitled swarm");
      markActive(slug);
      setAddress(slug);
    }

    function markActive(slug) {
      activeSlug = slug;
      for (const b of gallery.body.querySelectorAll(".sw-piece")) b.classList.toggle("on", b.dataset.slug === slug);
    }

    /** The shipped swarms plus any Claude kept (play.py swarm hunt --keep).
     *  Their small pictures are drawn one a frame, so opening stays smooth. */
    async function loadGallery() {
      try {
        const rows = (await ctx.keepsakes()).filter((r) => r.seed || r.author === "Claude");
        const full = await Promise.all(rows.map((r) => ctx.loadKeepsake(r.slug)));
        if (!alive) return;
        gallery.body.replaceChildren();
        const dpr = Math.min(2, window.devicePixelRatio || 1);
        const toDraw = [];
        for (const k of full) {
          const pic = el("canvas", { "aria-hidden": "true" });
          pic.width = pic.height = Math.round(40 * dpr);
          toDraw.push([pic, k.data]);
          gallery.body.append(
            el(
              "button",
              {
                type: "button",
                class: "sw-piece",
                dataset: { slug: k.slug },
                title: k.note || k.name,
                on: { click: () => apply(k.data, k.name, k.slug) },
              },
              pic,
              el("span", { text: k.name }),
            ),
          );
        }
        if (!full.length) gallery.body.append(el("p", { class: "ag-muted sw-small", text: "No swarms shipped." }));
        markActive(activeSlug);
        const drawNext = () => {
          const job = alive && toDraw.shift();
          if (!job) return;
          smallSwarm(job[0], job[1]);
          requestAnimationFrame(drawNext);
        };
        requestAnimationFrame(drawNext);
      } catch (e) {
        if (!alive) return;
        gallery.body.replaceChildren(el("p", { class: "ag-muted sw-small", text: `The swarms did not load: ${e.message}` }));
      }
    }

    function openKeep() {
      keepName.value = nameEl.textContent === "Your swarm" ? "" : nameEl.textContent;
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
      const data = cleanRules(rules);
      const pic = document.createElement("canvas");
      pic.width = 320;
      pic.height = 320;
      const s = Math.min(canvas.width, canvas.height);
      pic.getContext("2d").drawImage(canvas, (canvas.width - s) / 2, (canvas.height - s) / 2, s, s, 0, 0, 320, 320);
      try {
        const row = await ctx.keep({ name, note: keepNote.value.trim(), data, thumb: ctx.thumb(pic) });
        if (!alive) return;
        closeKeep();
        setName(name);
        if (row && row.slug) setAddress(row.slug);
        ctx.toast(`Kept "${name}".`);
      } catch (e) {
        if (alive) ctx.toast(`Not kept: ${e.message}`);
      }
    }

    function layout() {
      if (!alive) return;
      const rect = root.getBoundingClientRect();
      w = Math.max(1, rect.width);
      h = Math.max(1, rect.height);
      dpr = Math.min(2, window.devicePixelRatio || 1);
      const cw = Math.round(w * dpr);
      const ch = Math.round(h * dpr);
      if (canvas.width !== cw || canvas.height !== ch) {
        canvas.width = cw;
        canvas.height = ch;
        fresh = true;
      }
      reshape(sw, aspect());
    }

    function worldAt(e) {
      const r = canvas.getBoundingClientRect();
      return { x: ((e.clientX - r.left) / r.width) * sw.W, y: ((e.clientY - r.top) / r.height) * sw.H, sign: e.shiftKey ? -1 : 1 };
    }
    canvas.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      held = worldAt(e);
      poke(sw, held.x, held.y, 0.12, 1.2 * held.sign);
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", (e) => {
      if (held) held = worldAt(e);
    });
    const letGo = () => {
      held = null;
    };
    canvas.addEventListener("pointerup", letGo);
    canvas.addEventListener("pointercancel", letGo);

    const onKey = (e) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.key !== " ") return;
      if (typing(e.target) || (e.target && e.target.tagName === "BUTTON")) return;
      if (!root.isConnected || root.offsetParent === null) return;
      e.preventDefault();
      togglePause();
    };
    window.addEventListener("keydown", onKey);

    const ro = new ResizeObserver(() => layout());
    ro.observe(root);

    const loop = ctx.loop((now) => {
      const dt = last ? Math.min(1 / 30, (now - last) / 1000) : 1 / 60;
      last = now;
      if (paused && !fresh) return;
      if (!paused) {
        if (held) poke(sw, held.x, held.y, 0.09, 6 * dt * held.sign);
        step(sw, rules, dt);
      }
      drawSwarm(g, sw, { w: canvas.width, h: canvas.height, trails: trails && !fresh, dot: 2 * dpr });
      fresh = false;
      if (ctx.advanced && now - measuredAt > 1000) {
        measuredAt = now;
        const text = `Gathered ${clumping(sw, rules.reach).toFixed(1)}×`;
        if (text !== shownGather) gatherEl.textContent = shownGather = text;
      }
    });

    buildTable();
    layout();
    loadGallery();

    return {
      unmount() {
        alive = false;
        loop.stop();
        ro.disconnect();
        window.removeEventListener("keydown", onKey);
      },
      open(keepsake) {
        if (keepsake && keepsake.data) apply(keepsake.data, keepsake.name, keepsake.slug);
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
    stillSwarm(canvas, keepsake && keepsake.data ? keepsake.data : FAVOURITE.data);
  },
};
