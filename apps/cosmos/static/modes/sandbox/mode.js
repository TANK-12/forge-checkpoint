/* Sandbox mode: a 2D gravity playground.
 *
 * The physics is core/nbody.js; this file is input, drawing and panels.
 * Presets come from ~/ForgeGameData/cosmos/scenarios through /api/scenarios,
 * and "Save" writes the running world back there as a new file.
 *
 * Throwing: pick a tool, press where the object should start and drag the
 * way it should go. How far you drag is scaled to the local orbital speed, so
 * the same gesture means the same thing in a scenario measured in thousands
 * of units as in one measured in ones. With orbit help on, the object starts
 * on a circular orbit around whatever pulls hardest and the drag adds to it.
 */

import { World } from "../../core/nbody.js";

// Masses and radii are fractions of the scenario's biggest body, so a tool
// makes a sensibly sized thing in any scenario.
const TOOLS = [
  { id: "select", key: "v", icon: "✋", label: "Select", hint: "Click a body to inspect it, drag one to move it, drag space to pan." },
  { id: "star", key: "s", icon: "☀️", label: "Star", mass: 0.1, radius: 0.6, kind: "star", colors: ["#ffd27a", "#ffe9b8", "#ffb36b", "#bcd4ff"] },
  { id: "planet", key: "p", icon: "🪐", label: "Planet", mass: 1e-3, radius: 0.22, kind: "planet", colors: ["#5aa0e0", "#d9b27c", "#7ad0b0", "#c9643b", "#b99cff", "#e8c98b"] },
  { id: "moon", key: "m", icon: "🌑", label: "Moon", mass: 2e-5, radius: 0.09, kind: "moon", colors: ["#bdb8ae", "#9d958c", "#d8d2c4"] },
  { id: "blackhole", key: "b", icon: "⚫", label: "Black hole", mass: 1, radius: 0.28, kind: "blackhole", colors: ["#ff9c4a"] },
  { id: "dust", key: "d", icon: "✨", label: "Dust", hint: "Hold and move to spray dust onto orbits." },
];

const SPEEDS = [0.25, 0.5, 1, 2, 4, 8];
const TRAIL_POINTS = 240;

const HTML = `
  <div class="sandbox">
    <canvas class="sim"></canvas>
    <div class="hud sb-tools">
      <button class="btn" data-act="back" title="Back to the menu (Esc)">← Menu</button>
      <span class="sep"></span>
      <span class="tool-buttons row"></span>
      <span class="sep"></span>
      <button class="btn" data-act="play" title="Pause or play (space)">❚❚</button>
      <button class="btn" data-act="step" title="One step (.)">Step</button>
      <button class="btn" data-act="slower" title="Slower ([)">−</button>
      <span class="btn speed" style="cursor:default">1×</span>
      <button class="btn" data-act="faster" title="Faster (])">+</button>
    </div>
    <aside class="hud sb-panel">
      <section>
        <h3>Presets</h3>
        <div class="sb-scenarios"></div>
      </section>
      <section>
        <h3>New objects</h3>
        <label class="slider-row">
          <span>Mass, times the usual</span>
          <input type="number" class="mass-num" min="0.01" max="100" step="any" value="1">
          <input type="range" min="-2" max="2" step="0.1" value="0" data-opt="massExp" aria-label="Mass of new objects">
        </label>
        <label class="row"><input type="checkbox" data-opt="orbitHelp" checked> Start on a circular orbit <kbd>o</kbd></label>
        <label class="row"><input type="checkbox" data-opt="reverse"> Orbit clockwise</label>
      </section>
      <section>
        <h3>Show</h3>
        <label class="row"><input type="checkbox" data-opt="trails" checked> Trails <kbd>t</kbd></label>
        <label class="row"><input type="checkbox" data-opt="predict" checked> Path preview <kbd>g</kbd></label>
        <label class="row"><input type="checkbox" data-opt="names" checked> Names</label>
      </section>
      <section class="selected-box" hidden>
        <h3>Selected</h3>
        <input type="text" class="sel-name" maxlength="40" style="width:100%">
        <dl class="facts sel-facts"></dl>
        <div class="row" style="margin-top:8px">
          <button class="btn small" data-act="follow">Follow <kbd>c</kbd></button>
          <button class="btn small" data-act="pin">Pin in place</button>
          <button class="btn small" data-act="delete">Delete <kbd>Del</kbd></button>
        </div>
      </section>
      <section>
        <h3>World</h3>
        <div class="row">
          <button class="btn small" data-act="reload" title="Start this preset again (r)">Restart</button>
          <button class="btn small" data-act="clear">Empty space</button>
        </div>
        <div class="row" style="margin-top:8px">
          <input type="text" class="save-name" placeholder="Name to save as" maxlength="80" style="flex:1;min-width:0">
          <button class="btn small" data-act="save">Save</button>
        </div>
        <p class="muted folder" style="font-size:11px;margin:6px 0 0"></p>
      </section>
    </aside>
    <div class="hud sb-stats"></div>
    <div class="hud sb-hint" hidden></div>
  </div>`;

function fmt(n) {
  if (!Number.isFinite(n)) return "–";
  const a = Math.abs(n);
  if (a !== 0 && (a >= 1e6 || a < 1e-3)) return n.toExponential(2);
  return n.toLocaleString("en-US", { maximumSignificantDigits: 4 });
}

export default {
  async mount(root, ctx) {
    root.innerHTML = HTML;
    const $ = (s) => root.querySelector(s);
    const canvas = $("canvas.sim");
    const g = canvas.getContext("2d");

    const state = {
      world: new World(),
      scenario: null,
      scenarioId: null,
      dt: 0.02,
      stepsPerFrame: 4,
      speed: 2,
      running: true,
      view: { x: 0, y: 0, zoom: 1 },
      tool: "select",
      selected: null,
      follow: null,
      refMass: 1000,
      refRadius: 10,
      e0: 0,
      opts: { massExp: 0, orbitHelp: true, reverse: false, trails: true, predict: true, names: true },
      effects: [],
      trails: new Map(),
    };
    let W = 0;
    let H = 0;
    let dpr = 1;
    const bgStars = [];

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = canvas.clientWidth;
      H = canvas.clientHeight;
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      bgStars.length = 0;
      for (let i = 0; i < (W * H) / 2200; i++) {
        bgStars.push({ x: Math.random(), y: Math.random(), r: Math.random() ** 3 * 1.3 + 0.2, a: 0.2 + Math.random() * 0.6, depth: 0.02 + Math.random() * 0.08 });
      }
    }

    // The view's centre is the middle of the open part of the canvas, not of
    // the whole canvas, so a preset does not start with a planet hidden under
    // the side panel (or, in a narrow window, under the panel at the bottom).
    // Measured on resize and when a preset loads, never mid-play, so showing
    // the Selected box cannot shift the picture.
    let cx = 0;
    let cy = 0;
    let freeW = 0;
    let freeH = 0;
    function measureFree() {
      const c = canvas.getBoundingClientRect();
      let [left, top, right, bottom] = [0, 0, W, H];
      const tools = $(".sb-tools").getBoundingClientRect();
      if (tools.height) top = Math.max(top, tools.bottom - c.top);
      const panel = $(".sb-panel").getBoundingClientRect();
      if (panel.height && panel.left - c.left > W / 2) right = Math.min(right, panel.left - c.left);
      else if (panel.height) bottom = Math.min(bottom, panel.top - c.top);
      if (right - left < W * 0.35 || bottom - top < H * 0.35) [left, top, right, bottom] = [0, 0, W, H];
      cx = (left + right) / 2;
      cy = (top + bottom) / 2;
      freeW = right - left;
      freeH = bottom - top;
    }

    // The presets panel sits just under the toolbar, however many rows it
    // wraps to (--sb-head in app.css). The view centre is left alone here.
    const sandboxBox = $(".sandbox");
    const headObserver = new ResizeObserver(() => {
      const tools = $(".sb-tools");
      if (tools.offsetHeight) sandboxBox.style.setProperty("--sb-head", `${tools.offsetTop + tools.offsetHeight}px`);
    });
    headObserver.observe($(".sb-tools"));

    resize();
    measureFree();
    const observer = new ResizeObserver(() => {
      resize();
      measureFree();
    });
    observer.observe(canvas);

    const toScreen = (x, y) => [(x - state.view.x) * state.view.zoom + cx, cy - (y - state.view.y) * state.view.zoom];
    const toWorld = (sx, sy) => [(sx - cx) / state.view.zoom + state.view.x, (cy - sy) / state.view.zoom + state.view.y];

    /* A preset's own zoom, eased out (to half at most) until its bodies and
     * most of its particles fit the open area. Saved worlds keep their view. */
    function fittedZoom(world, view) {
      let reach = 0;
      for (const b of world.bodies) reach = Math.max(reach, Math.hypot(b.x - view.x, b.y - view.y) + b.r);
      const P = world.particles;
      if (P.count) {
        const d = new Float64Array(P.count);
        for (let i = 0; i < P.count; i++) d[i] = Math.hypot(P.x[i] - view.x, P.y[i] - view.y);
        d.sort();
        reach = Math.max(reach, d[Math.floor(0.9 * (P.count - 1))]);
      }
      if (!reach || !freeW || !freeH) return view.zoom;
      const fit = (0.92 * Math.min(freeW, freeH)) / 2 / reach;
      return Math.max(view.zoom / 2, Math.min(view.zoom, fit));
    }

    /* --- scenarios ---------------------------------------------------------- */

    async function loadList() {
      try {
        const { scenarios, folder } = await ctx.api("/api/scenarios");
        $(".folder").textContent = `Saved to ${folder}`;
        const box = $(".sb-scenarios");
        if (!scenarios.length) {
          box.innerHTML = `<p class="muted" style="margin:0">No presets found. Add JSON files to ${folder}.</p>`;
          return scenarios;
        }
        box.replaceChildren(
          ...scenarios.map((s) => {
            const b = document.createElement("button");
            b.dataset.id = s.id;
            b.innerHTML = "<strong></strong><small></small>";
            b.querySelector("strong").textContent = s.saved ? `${s.name} (saved)` : s.name;
            b.querySelector("small").textContent = s.description || `${s.bodies} bodies, ${s.particles} particles`;
            b.title = s.description || "";
            b.classList.toggle("on", s.id === state.scenarioId);
            b.onclick = () => loadScenario(s.id);
            return b;
          }),
        );
        return scenarios;
      } catch (err) {
        ctx.toast(`Presets could not load: ${err.message}`);
        return [];
      }
    }

    async function loadScenario(id) {
      try {
        const s = await ctx.api(`/api/scenarios/${encodeURIComponent(id)}`);
        applyScenario(s, id);
      } catch (err) {
        ctx.toast(`That preset could not load: ${err.message}`);
      }
    }

    function applyScenario(s, id) {
      state.world = World.fromScenario(s);
      state.scenario = s;
      state.scenarioId = id;
      state.dt = s.dt ?? 0.02;
      state.stepsPerFrame = s.steps_per_frame ?? 4;
      state.view = { x: 0, y: 0, zoom: 1, ...(s.view || {}) };
      measureFree();
      if (!s.saved) state.view.zoom = fittedZoom(state.world, state.view);
      state.refMass = Math.max(...state.world.bodies.map((b) => b.m), 0) || 1000;
      state.refRadius = Math.max(...state.world.bodies.map((b) => b.r), 0) || 10;
      state.selected = null;
      state.follow = null;
      state.trails.clear();
      state.effects.length = 0;
      state.e0 = state.world.energy();
      root.querySelectorAll(".sb-scenarios button").forEach((b) => b.classList.toggle("on", b.dataset.id === id));
      showSelected();
    }

    async function save() {
      // one save at a time: a double click would otherwise save two copies
      if (save.busy) return;
      save.busy = true;
      const button = $('[data-act="save"]');
      button.disabled = true;
      try {
        await saveOnce();
      } finally {
        save.busy = false;
        button.disabled = false;
      }
    }

    async function saveOnce() {
      const input = $(".save-name");
      const name = input.value.trim() || `${state.scenario?.name || "My world"} (copy)`;
      const data = state.world.toScenario({
        name,
        description: `Saved from the sandbox${state.scenario?.name ? `, starting from "${state.scenario.name}"` : ""}.`,
        dt: state.dt,
        steps_per_frame: state.stepsPerFrame,
        view: { ...state.view },
      });
      try {
        const res = await ctx.api("/api/scenarios", { json: data });
        input.value = "";
        state.scenarioId = res.id;
        state.scenario = { ...data, saved: true };
        await loadList();
        ctx.toast(`Saved as ${res.id}.json`);
      } catch (err) {
        ctx.toast(`Could not save: ${err.message}`);
      }
    }

    /* --- the simulation -------------------------------------------------------- */

    function stepWorld(steps) {
      const w = state.world;
      const t0 = performance.now();
      for (let i = 0; i < steps; i++) {
        w.step(state.dt);
        // Keep the page responsive when a world gets heavy.
        if (performance.now() - t0 > 14) break;
      }
      for (const ev of w.events) {
        state.effects.push({ ...ev, born: performance.now() });
        if (state.selected && !w.bodyById(state.selected)) state.selected = ev.into;
        if (state.follow && !w.bodyById(state.follow)) state.follow = ev.into;
      }
      w.events.length = 0;
      if (state.selected && !w.bodyById(state.selected)) state.selected = null;
      if (state.opts.trails) {
        for (const b of w.bodies) {
          let t = state.trails.get(b.id);
          if (!t) {
            t = { pts: new Float32Array(TRAIL_POINTS * 2), head: 0, len: 0 };
            state.trails.set(b.id, t);
          }
          t.pts[t.head * 2] = b.x;
          t.pts[t.head * 2 + 1] = b.y;
          t.head = (t.head + 1) % TRAIL_POINTS;
          t.len = Math.min(TRAIL_POINTS, t.len + 1);
        }
      }
    }

    function newSpec(tool, x, y) {
      const k = 10 ** state.opts.massExp;
      const color = tool.colors[Math.floor(Math.random() * tool.colors.length)];
      const names = { star: "Star", planet: "Planet", moon: "Moon", blackhole: "Black hole" };
      const count = state.world.bodies.filter((b) => b.kind === tool.kind).length + 1;
      return {
        name: `${names[tool.kind]} ${count}`,
        kind: tool.kind,
        m: state.refMass * tool.mass * k,
        r: Math.max(state.refRadius * tool.radius * (tool.kind === "blackhole" ? k : Math.cbrt(k)), 0.5 / state.view.zoom),
        color,
        x,
        y,
      };
    }

    // World units of velocity per pixel of drag at a point.
    function dragScale(x, y) {
      const att = state.world.dominantAttractor(x, y);
      if (att) {
        const r = Math.hypot(x - att.x, y - att.y);
        return state.world.circularSpeed(att.m, Math.max(r, att.r)) / 140;
      }
      return 1 / (state.view.zoom * state.dt * state.stepsPerFrame * 60);
    }

    function launchVelocity(x, y, dxPx, dyPx) {
      const k = dragScale(x, y);
      let vx = dxPx * k;
      let vy = -dyPx * k;
      if (state.opts.orbitHelp) {
        const c = state.world.circularVelocity(x, y, state.opts.reverse ? -1 : 1);
        vx += c.vx;
        vy += c.vy;
      }
      return [vx, vy];
    }

    /* --- input -------------------------------------------------------------- */

    let pointer = null;
    let mouse = { x: 0, y: 0 };
    let prediction = null;

    function bodyAt(sx, sy) {
      let best = null;
      let bestD = Infinity;
      for (const b of state.world.bodies) {
        const [bx, by] = toScreen(b.x, b.y);
        const d = Math.hypot(bx - sx, by - sy) - Math.max(b.r * state.view.zoom, 4);
        if (d < 8 && d < bestD) {
          best = b;
          bestD = d;
        }
      }
      return best;
    }

    canvas.addEventListener("contextmenu", (e) => e.preventDefault());
    canvas.addEventListener("pointerdown", (e) => {
      canvas.setPointerCapture(e.pointerId);
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const [wx, wy] = toWorld(sx, sy);
      const tool = TOOLS.find((t) => t.id === state.tool);
      if (e.button === 1 || e.button === 2) {
        pointer = { mode: "pan", sx, sy };
        return;
      }
      if (tool.id === "select") {
        const hit = bodyAt(sx, sy);
        if (hit) {
          state.selected = hit.id;
          pointer = { mode: "move", id: hit.id, sx, sy, dx: hit.x - wx, dy: hit.y - wy, moved: false };
          showSelected();
        } else {
          pointer = { mode: "pan", sx, sy, click: true };
        }
      } else if (tool.id === "dust") {
        pointer = { mode: "dust", sx, sy };
      } else {
        pointer = { mode: "place", tool, wx, wy, sx, sy, cx: sx, cy: sy };
      }
    });
    canvas.addEventListener("pointermove", (e) => {
      const rect = canvas.getBoundingClientRect();
      mouse = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      if (!pointer) return;
      if (pointer.mode === "pan") {
        if (Math.hypot(mouse.x - pointer.sx, mouse.y - pointer.sy) > 3) pointer.click = false;
        state.view.x -= (mouse.x - pointer.sx) / state.view.zoom;
        state.view.y += (mouse.y - pointer.sy) / state.view.zoom;
        pointer.sx = mouse.x;
        pointer.sy = mouse.y;
        state.follow = null;
      } else if (pointer.mode === "move") {
        const b = state.world.bodyById(pointer.id);
        const [wx, wy] = toWorld(mouse.x, mouse.y);
        if (b) {
          b.x = wx + pointer.dx;
          b.y = wy + pointer.dy;
          state.world.touch();
          state.trails.delete(b.id);
          pointer.moved = true;
        }
      } else if (pointer.mode === "place") {
        pointer.cx = mouse.x;
        pointer.cy = mouse.y;
        prediction = null;
      }
    });
    canvas.addEventListener("pointerup", () => {
      if (!pointer) return;
      if (pointer.mode === "pan" && pointer.click) {
        state.selected = null;
        showSelected();
      }
      if (pointer.mode === "move" && pointer.moved) state.e0 = state.world.energy();
      if (pointer.mode === "place") {
        const [vx, vy] = launchVelocity(pointer.wx, pointer.wy, pointer.cx - pointer.sx, pointer.cy - pointer.sy);
        const b = state.world.addBody({ ...newSpec(pointer.tool, pointer.wx, pointer.wy), vx, vy });
        state.selected = b.id;
        state.e0 = state.world.energy();
        showSelected();
      }
      pointer = null;
      prediction = null;
    });
    canvas.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const rect = canvas.getBoundingClientRect();
        const sx = e.clientX - rect.left;
        const sy = e.clientY - rect.top;
        const [wx, wy] = toWorld(sx, sy);
        const delta = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
        state.view.zoom = Math.min(1e6, Math.max(1e-4, state.view.zoom * Math.exp(-delta * 0.0015)));
        if (!state.follow) {
          // Keep the point under the cursor where it is.
          const [nx, ny] = toWorld(sx, sy);
          state.view.x += wx - nx;
          state.view.y += wy - ny;
        }
      },
      { passive: false },
    );

    function sprayDust() {
      const [cx, cy] = toWorld(mouse.x, mouse.y);
      const spread = 22 / state.view.zoom;
      for (let i = 0; i < 10; i++) {
        const t = Math.random() * Math.PI * 2;
        const r = Math.sqrt(Math.random()) * spread;
        const x = cx + Math.cos(t) * r;
        const y = cy + Math.sin(t) * r;
        const v = state.world.circularVelocity(x, y, state.opts.reverse ? -1 : 1);
        const jitter = 1 + (Math.random() - 0.5) * 0.04;
        state.world.addParticle(x, y, v.vx * jitter, v.vy * jitter, ["#d8c8a8", "#a9b8d8", "#e8dcc8"][i % 3]);
      }
    }

    /* --- panels -------------------------------------------------------------- */

    const toolBox = $(".tool-buttons");
    for (const t of TOOLS) {
      const b = document.createElement("button");
      b.className = "btn";
      b.dataset.tool = t.id;
      b.title = `${t.label} (${t.key})`;
      b.innerHTML = "<span></span><span></span>";
      b.children[0].textContent = t.icon;
      b.children[1].textContent = t.label;
      b.onclick = () => setTool(t.id);
      toolBox.appendChild(b);
    }
    function setTool(id) {
      state.tool = id;
      toolBox.querySelectorAll("[data-tool]").forEach((b) => b.classList.toggle("on", b.dataset.tool === id));
      const t = TOOLS.find((x) => x.id === id);
      const hint = $(".sb-hint");
      hint.textContent = t.hint || `Press where the ${t.label.toLowerCase()} should start and drag the way to throw it. Release to let go.`;
      hint.hidden = false;
      clearTimeout(setTool.timer);
      setTool.timer = setTimeout(() => (hint.hidden = true), 4000);
    }
    setTool("select");

    root.querySelectorAll("[data-opt]").forEach((el) => {
      el.addEventListener("input", () => {
        state.opts[el.dataset.opt] = el.type === "checkbox" ? el.checked : Number(el.value);
        if (el.dataset.opt === "massExp") $(".mass-num").value = +(10 ** state.opts.massExp).toPrecision(3);
        if (el.dataset.opt === "trails" && !el.checked) state.trails.clear();
      });
    });
    // the number beside the mass slider: the multiplier itself, 0.01 to 100
    const massNum = $(".mass-num");
    massNum.addEventListener("input", () => {
      const v = Number(massNum.value);
      if (!(v >= 0.01 && v <= 100)) return;
      state.opts.massExp = Math.log10(v);
      $('[data-opt="massExp"]').value = state.opts.massExp;
    });
    massNum.addEventListener("change", () => (massNum.value = +(10 ** state.opts.massExp).toPrecision(3)));

    function setOpt(opt, value) {
      state.opts[opt] = value;
      const el = root.querySelector(`[data-opt="${opt}"]`);
      if (el) el.checked = value;
      if (opt === "trails" && !value) state.trails.clear();
    }

    function act(name) {
      const w = state.world;
      const sel = state.selected && w.bodyById(state.selected);
      if (name === "back") ctx.back();
      if (name === "play") state.running = !state.running;
      if (name === "step") {
        state.running = false;
        stepWorld(1);
      }
      if (name === "slower") state.speed = Math.max(0, state.speed - 1);
      if (name === "faster") state.speed = Math.min(SPEEDS.length - 1, state.speed + 1);
      if (name === "reload" && state.scenarioId) loadScenario(state.scenarioId);
      if (name === "clear") {
        const s = state.scenario || {};
        applyScenario({ name: "Empty space", G: s.G ?? 1, softening: s.softening ?? 0.1, dt: state.dt, steps_per_frame: state.stepsPerFrame, view: { ...state.view }, bodies: [] }, null);
        state.refMass = state.refMass || 1000;
      }
      if (name === "save") save();
      if (sel && name === "follow") state.follow = state.follow === sel.id ? null : sel.id;
      if (sel && name === "pin") {
        sel.fixed = !sel.fixed;
        sel.vx = 0;
        sel.vy = 0;
        w.touch();
        state.e0 = w.energy();
      }
      if (sel && name === "delete") {
        w.removeBody(sel.id);
        state.trails.delete(sel.id);
        if (state.follow === sel.id) state.follow = null;
        state.selected = null;
        state.e0 = w.energy();
      }
      syncUi();
      showSelected();
    }
    root.addEventListener("click", (e) => {
      const a = e.target.closest("[data-act]")?.dataset.act;
      if (a) act(a);
    });
    $(".sel-name").addEventListener("input", (e) => {
      const b = state.world.bodyById(state.selected);
      if (b) b.name = e.target.value;
    });

    function syncUi() {
      $('[data-act="play"]').textContent = state.running ? "❚❚" : "▶";
      $(".speed").textContent = `${SPEEDS[state.speed]}×`;
    }
    syncUi();

    function showSelected() {
      const b = state.selected && state.world.bodyById(state.selected);
      $(".selected-box").hidden = !b;
      if (!b) return;
      if (document.activeElement !== $(".sel-name")) $(".sel-name").value = b.name;
      $('[data-act="pin"]').textContent = b.fixed ? "Let go" : "Pin in place";
      $('[data-act="follow"]').classList.toggle("on", state.follow === b.id);
      const w = state.world;
      const rows = [
        ["Kind", { star: "Star", planet: "Planet", moon: "Moon", blackhole: "Black hole" }[b.kind] || b.kind],
        ["Mass", fmt(b.m)],
        ["Radius", fmt(b.r)],
        ["Speed", fmt(Math.hypot(b.vx, b.vy))],
      ];
      const att = w.dominantAttractor(b.x, b.y, b);
      if (att && !b.fixed) {
        const dx = b.x - att.x;
        const dy = b.y - att.y;
        const r = Math.hypot(dx, dy);
        const v2 = (b.vx - att.vx) ** 2 + (b.vy - att.vy) ** 2;
        const mu = w.G * (att.m + b.m);
        const inv = 2 / r - v2 / mu;
        rows.push([`Around`, att.name || att.kind]);
        rows.push(["Distance", fmt(r)]);
        if (inv > 0) {
          const a = 1 / inv;
          rows.push(["Orbit", `bound, period ${fmt(2 * Math.PI * Math.sqrt(a ** 3 / mu))}`]);
        } else {
          rows.push(["Orbit", "escaping"]);
        }
      }
      $(".sel-facts").replaceChildren(
        ...rows.flatMap(([k, v]) => {
          const dt = document.createElement("dt");
          dt.textContent = k;
          const dd = document.createElement("dd");
          dd.textContent = v;
          return [dt, dd];
        }),
      );
    }

    function onKey(e) {
      const tag = e.target?.tagName || "";
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || e.ctrlKey || e.metaKey || e.altKey) return;
      const tool = TOOLS.find((t) => t.key === e.key);
      if (tool) setTool(tool.id);
      else if (e.key === " ") act("play");
      else if (e.key === ".") act("step");
      else if (e.key === "[") act("slower");
      else if (e.key === "]") act("faster");
      else if (e.key === "r") act("reload");
      else if (e.key === "c") act("follow");
      else if (e.key === "Delete" || e.key === "Backspace") act("delete");
      else if (e.key === "t") setOpt("trails", !state.opts.trails);
      else if (e.key === "g") setOpt("predict", !state.opts.predict);
      else if (e.key === "o") setOpt("orbitHelp", !state.opts.orbitHelp);
      else return;
      e.preventDefault();
    }
    document.addEventListener("keydown", onKey);

    /* --- drawing ------------------------------------------------------------- */

    function drawBackground() {
      g.fillStyle = "#03040a";
      g.fillRect(0, 0, W, H);
      for (const s of bgStars) {
        // A little parallax so panning feels like moving through space.
        const x = (((s.x * W - state.view.x * state.view.zoom * s.depth) % W) + W) % W;
        const y = (((s.y * H + state.view.y * state.view.zoom * s.depth) % H) + H) % H;
        g.globalAlpha = s.a;
        g.fillStyle = "#dfe6ff";
        g.fillRect(x, y, s.r, s.r);
      }
      g.globalAlpha = 1;
    }

    function drawTrails() {
      if (!state.opts.trails) return;
      g.lineWidth = 1.2;
      for (const b of state.world.bodies) {
        const t = state.trails.get(b.id);
        if (!t || t.len < 2) continue;
        const start = (t.head - t.len + TRAIL_POINTS) % TRAIL_POINTS;
        // Four segments of rising opacity make the tail fade out.
        for (let seg = 0; seg < 4; seg++) {
          const from = Math.floor((seg * (t.len - 1)) / 4);
          const to = Math.floor(((seg + 1) * (t.len - 1)) / 4);
          g.strokeStyle = b.color;
          g.globalAlpha = 0.08 + seg * 0.14;
          g.beginPath();
          for (let k = from; k <= to; k++) {
            const i = (start + k) % TRAIL_POINTS;
            const [sx, sy] = toScreen(t.pts[i * 2], t.pts[i * 2 + 1]);
            if (k === from) g.moveTo(sx, sy);
            else g.lineTo(sx, sy);
          }
          g.stroke();
        }
      }
      g.globalAlpha = 1;
    }

    function drawParticles() {
      const P = state.world.particles;
      const z = state.view.zoom;
      const size = 1.6;
      for (let c = 0; c < P.palette.length; c++) {
        g.fillStyle = P.palette[c];
        g.globalAlpha = 0.85;
        g.beginPath();
        for (let i = 0; i < P.count; i++) {
          if (P.color[i] !== c) continue;
          const sx = (P.x[i] - state.view.x) * z + cx;
          const sy = cy - (P.y[i] - state.view.y) * z;
          if (sx < -2 || sy < -2 || sx > W + 2 || sy > H + 2) continue;
          g.rect(sx, sy, size, size);
        }
        g.fill();
      }
      g.globalAlpha = 1;
    }

    function drawBody(b, time) {
      const [sx, sy] = toScreen(b.x, b.y);
      const r = Math.max(b.r * state.view.zoom, b.kind === "moon" ? 1.8 : 2.6);
      if (sx < -r * 8 || sy < -r * 8 || sx > W + r * 8 || sy > H + r * 8) return;
      if (b.kind === "star") {
        const glow = g.createRadialGradient(sx, sy, r * 0.3, sx, sy, r * 5);
        glow.addColorStop(0, b.color);
        glow.addColorStop(0.25, hexAlpha(b.color, 0.35));
        glow.addColorStop(1, hexAlpha(b.color, 0));
        g.fillStyle = glow;
        g.beginPath();
        g.arc(sx, sy, r * 5, 0, Math.PI * 2);
        g.fill();
        g.fillStyle = "#fffaf0";
        g.beginPath();
        g.arc(sx, sy, r, 0, Math.PI * 2);
        g.fill();
      } else if (b.kind === "blackhole") {
        const spin = time / 900;
        const disc = g.createRadialGradient(sx, sy, r, sx, sy, r * 4);
        disc.addColorStop(0, hexAlpha(b.color, 0.9));
        disc.addColorStop(0.35, hexAlpha(b.color, 0.35));
        disc.addColorStop(1, hexAlpha(b.color, 0));
        g.fillStyle = disc;
        g.beginPath();
        g.arc(sx, sy, r * 4, 0, Math.PI * 2);
        g.fill();
        g.strokeStyle = hexAlpha("#ffe7c0", 0.8);
        g.lineWidth = Math.max(1, r * 0.18);
        g.beginPath();
        g.ellipse(sx, sy, r * 1.5, r * 0.55, spin, 0, Math.PI * 2);
        g.stroke();
        g.fillStyle = "#000";
        g.beginPath();
        g.arc(sx, sy, r, 0, Math.PI * 2);
        g.fill();
        g.strokeStyle = hexAlpha("#fff2d8", 0.9);
        g.lineWidth = 1;
        g.beginPath();
        g.arc(sx, sy, r * 1.04, 0, Math.PI * 2);
        g.stroke();
      } else {
        // Lit from whichever star or hole pulls hardest.
        const light = state.world.bodies
          .filter((o) => o !== b && (o.kind === "star" || o.kind === "blackhole"))
          .sort((p, q) => q.m / ((p.x - b.x) ** 2 + (p.y - b.y) ** 2 + 1) - p.m / ((q.x - b.x) ** 2 + (q.y - b.y) ** 2 + 1))[0];
        let lx = 0;
        let ly = 0;
        if (light) {
          const [ox, oy] = toScreen(light.x, light.y);
          const d = Math.hypot(ox - sx, oy - sy) || 1;
          lx = ((ox - sx) / d) * r * 0.45;
          ly = ((oy - sy) / d) * r * 0.45;
        }
        const shade = g.createRadialGradient(sx + lx, sy + ly, r * 0.1, sx, sy, r);
        shade.addColorStop(0, lighten(b.color));
        shade.addColorStop(0.7, b.color);
        shade.addColorStop(1, hexAlpha("#000000", 0.85));
        g.fillStyle = shade;
        g.beginPath();
        g.arc(sx, sy, r, 0, Math.PI * 2);
        g.fill();
      }
      if (b.fixed) {
        g.strokeStyle = "rgba(255,255,255,0.35)";
        g.setLineDash([3, 3]);
        g.beginPath();
        g.arc(sx, sy, r + 6, 0, Math.PI * 2);
        g.stroke();
        g.setLineDash([]);
      }
      if (b.id === state.selected) {
        g.strokeStyle = "#8fb4ff";
        g.lineWidth = 1.5;
        g.beginPath();
        g.arc(sx, sy, r + 9 + Math.sin(time / 250) * 1.5, 0, Math.PI * 2);
        g.stroke();
      }
      if (state.opts.names && b.name && (b.kind !== "moon" || state.view.zoom * b.r > 1.5 || b.id === state.selected)) {
        g.font = "12px system-ui, sans-serif";
        g.fillStyle = "rgba(220,228,255,0.85)";
        g.fillText(b.name, sx + r + 6, sy - r - 4);
      }
    }

    function drawEffects(time) {
      state.effects = state.effects.filter((fx) => time - fx.born < 900);
      for (const fx of state.effects) {
        const t = (time - fx.born) / 900;
        const [sx, sy] = toScreen(fx.x, fx.y);
        g.strokeStyle = fx.kind === "blackhole" ? `rgba(255,170,90,${1 - t})` : `rgba(255,240,210,${1 - t})`;
        g.lineWidth = 2.5 * (1 - t) + 0.5;
        g.beginPath();
        g.arc(sx, sy, 6 + t * 60, 0, Math.PI * 2);
        g.stroke();
      }
    }

    function drawPlacement() {
      if (!pointer || pointer.mode !== "place") return;
      const spec = newSpec(pointer.tool, pointer.wx, pointer.wy);
      const [vx, vy] = launchVelocity(pointer.wx, pointer.wy, pointer.cx - pointer.sx, pointer.cy - pointer.sy);
      if (state.opts.predict) {
        if (!prediction) {
          const period = state.dt * state.stepsPerFrame * 60 * 20;
          const steps = 1200;
          prediction = state.world.predict(pointer.wx, pointer.wy, vx, vy, { steps, dt: period / steps, every: 3 });
        }
        g.setLineDash([4, 5]);
        g.strokeStyle = prediction.hit ? "rgba(255,140,120,0.8)" : "rgba(170,200,255,0.75)";
        g.lineWidth = 1.2;
        g.beginPath();
        const pts = prediction.points;
        for (let i = 0; i < pts.length; i += 2) {
          const [sx, sy] = toScreen(pts[i], pts[i + 1]);
          if (i === 0) g.moveTo(sx, sy);
          else g.lineTo(sx, sy);
        }
        g.stroke();
        g.setLineDash([]);
      }
      g.strokeStyle = "rgba(255,255,255,0.7)";
      g.beginPath();
      g.moveTo(pointer.sx, pointer.sy);
      g.lineTo(pointer.cx, pointer.cy);
      g.stroke();
      g.globalAlpha = 0.6;
      drawBody({ ...spec, id: "__ghost", name: "" }, performance.now());
      g.globalAlpha = 1;
    }

    /* --- the loop ------------------------------------------------------------ */

    let frame = 0;
    let lastStats = 0;
    function tick(time) {
      if (state.running) stepWorld(Math.max(1, Math.round(state.stepsPerFrame * SPEEDS[state.speed])));
      if (pointer?.mode === "dust") sprayDust();
      const f = state.follow && state.world.bodyById(state.follow);
      if (f) {
        state.view.x = f.x;
        state.view.y = f.y;
      }
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      drawBackground();
      drawTrails();
      drawParticles();
      for (const b of state.world.bodies) drawBody(b, time);
      drawEffects(time);
      drawPlacement();

      if (time - lastStats > 250) {
        lastStats = time;
        const w = state.world;
        const e = w.energy();
        const drift = state.e0 ? Math.abs((e - state.e0) / state.e0) * 100 : 0;
        const [px, py] = w.momentum();
        $(".sb-stats").textContent = "";
        for (const [k, v] of [
          ["Time", fmt(w.time)],
          ["Bodies", w.bodies.length],
          ["Dust", w.particles.count.toLocaleString("en-US")],
          ["Energy", fmt(e)],
          ["Energy drift", `${drift < 0.001 ? "<0.001" : drift.toFixed(3)}%`],
          ["Momentum", fmt(Math.hypot(px, py))],
          ["Zoom", `${fmt(state.view.zoom)} px per unit`],
        ]) {
          const span = document.createElement("span");
          span.innerHTML = '<span class="muted"></span> ';
          span.firstChild.textContent = k;
          span.append(String(v));
          $(".sb-stats").appendChild(span);
        }
        showSelected();
      }
      frame = requestAnimationFrame(tick);
    }

    const list = await loadList();
    if (list.length) await loadScenario(list[0].id);
    frame = requestAnimationFrame(tick);

    return {
      onEscape() {
        if (pointer) {
          pointer = null;
          return true;
        }
        if (state.tool !== "select") {
          setTool("select");
          return true;
        }
        if (state.selected) {
          state.selected = null;
          showSelected();
          return true;
        }
        return false;
      },
      unmount() {
        cancelAnimationFrame(frame);
        observer.disconnect();
        headObserver.disconnect();
        document.removeEventListener("keydown", onKey);
        root.replaceChildren();
      },
      debug: { state, loadScenario },
    };
  },
};

function hexAlpha(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

function lighten(hex) {
  const n = parseInt(hex.slice(1), 16);
  const up = (c) => Math.min(255, Math.round(c + (255 - c) * 0.45));
  return `rgb(${up((n >> 16) & 255)},${up((n >> 8) & 255)},${up(n & 255)})`;
}
