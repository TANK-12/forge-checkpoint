/* Orbit puzzles: launch a probe and let real gravity carry it to the goal.
 *
 * The rules are core/puzzle.js, the physics core/nbody3d.js, endless levels
 * core/levelgen.js and the drawing view.js. This file is the screens, input,
 * sound and saving. Levels come from ~/ForgeGameData/cosmos/levels through
 * /api/levels, so adding one is adding a file.
 *
 * Time is frozen while you aim: the planets sit where they will be at launch,
 * and the dotted preview is the exact path the probe will fly (asteroids
 * aside). The preview gets shorter on harder levels (level.preview).
 *
 * For checking in a headless browser the URL can open a level directly:
 *   ?pz=<level id> | endless-<difficulty>   (&pzseed=N for a fixed endless seed)
 *   &pzghosts=3   fly three near misses first, so their ghosts show
 *   &pzfire=1     launch the level's stored reference solution
 *   &pzwarp=6     start at that time-warp step
 *   &pzfit=1      zoom out to the whole level
 * and the mode's root element carries the same actions as __debug.
 */

import { RailSystem, makeProbe, predict } from "../../core/nbody3d.js";
import { Field, Run, aimDirection, checkLevel, clampAim, discoverableIds, launchState, orbitAround, prepareLevel, score, waypointPosition } from "../../core/puzzle.js";
import { generateLevel } from "../../core/levelgen.js";
import { PuzzleView } from "./view.js";

const WARPS = [0.25, 0.5, 1, 2, 4, 8, 16, 32, 64];
const DEFAULT_WARP = 2;
const BURN_KEYS = { w: "prograde", s: "retrograde", a: "antiradial", d: "radial", q: "normal", e: "antinormal" };
const BURN_LABELS = { prograde: "Prograde", retrograde: "Retrograde", antiradial: "Radial in", radial: "Radial out", normal: "Normal", antinormal: "Anti-normal" };
const GOAL_WORDS = { reach: "Reach", orbit: "Orbit", waypoints: "Rings", land: "Land", explore: "Explore" };

const HTML = `
  <div class="puzzles">
    <div class="pz-canvas"></div>
    <div class="pz-labels"></div>
    <div class="hud pz-top">
      <button class="btn" data-act="levels" title="Level select (Esc)">← Levels</button>
      <span class="pz-title"></span>
      <span class="sep"></span>
      <button class="btn" data-act="retry" title="Try again (r)">Retry</button>
      <button class="btn" data-act="play" title="Pause or play (space)">❚❚</button>
      <button class="btn" data-act="slower" title="Slower time ([)">−</button>
      <span class="btn pz-warp" style="cursor:default"></span>
      <button class="btn" data-act="faster" title="Faster time (])">+</button>
      <span class="sep"></span>
      <button class="btn" data-act="fit" title="Show the whole level (h)">Fit</button>
      <button class="btn" data-act="follow" title="Follow the probe (c)">Follow</button>
      <button class="btn" data-act="fps" title="Frame rate: a cap at 30 saves power on the laptop"></button>
      <button class="btn" data-act="help" title="Keys and controls (?)">?</button>
    </div>
    <div class="hud pz-caption"></div>
    <aside class="hud pz-aim" hidden>
      <h3>Launch</h3>
      <label class="pz-field"><span>Speed</span><input type="number" step="0.01" data-aim="speed"><input type="range" step="0.001" data-aim-range="speed"></label>
      <label class="pz-field"><span>Heading (degrees)</span><input type="number" step="0.1" data-aim="heading"><input type="range" step="0.1" data-aim-range="heading"></label>
      <label class="pz-field pz-elev"><span>Elevation (degrees)</span><input type="number" step="0.1" data-aim="elevation"><input type="range" step="0.1" data-aim-range="elevation"></label>
      <p class="pz-cost"></p>
      <label class="row"><input type="checkbox" data-opt="preview" checked> Path preview <kbd>g</kbd></label>
      <button class="btn pz-launch" data-act="launch">Launch <kbd>space</kbd></button>
      <p class="muted pz-tip">Drag out from the glowing ring to aim: direction is heading, distance is speed. Shift-drag from the ring sets elevation. Time waits until you launch.</p>
    </aside>
    <aside class="hud pz-flight" hidden>
      <h3>Flight</h3>
      <dl class="facts pz-facts"></dl>
      <div class="pz-fuel-box">
        <div class="row pz-fuel-row"><span class="muted">Fuel (delta-v)</span><span class="pz-fuel-text"></span></div>
        <div class="pz-fuel"><i></i></div>
        <div class="pz-burns"></div>
      </div>
    </aside>
    <div class="hud pz-status"></div>
    <div class="hud pz-result" hidden></div>
    <div class="hud pz-help" hidden>
      <h2>Keys and controls</h2>
      <dl>
        <dt><kbd>space</kbd></dt><dd>Launch, or pause a flight</dd>
        <dt><kbd>r</kbd></dt><dd>Try again; your last paths stay as faint ghosts</dd>
        <dt><kbd>n</kbd></dt><dd>Next level after a win</dd>
        <dt><kbd>[</kbd> <kbd>]</kbd></dt><dd>Slower or faster time</dd>
        <dt><kbd>←</kbd> <kbd>→</kbd> <kbd>↑</kbd> <kbd>↓</kbd></dt><dd>Nudge heading and speed while aiming (shift for bigger steps)</dd>
        <dt><kbd>w</kbd> <kbd>s</kbd></dt><dd>Hold to burn prograde (speed up) or retrograde (slow down)</dd>
        <dt><kbd>a</kbd> <kbd>d</kbd></dt><dd>Hold to burn radial in or out</dd>
        <dt><kbd>q</kbd> <kbd>e</kbd></dt><dd>Hold to burn normal or anti-normal, out of the plane</dd>
        <dt><kbd>g</kbd></dt><dd>Path preview on or off</dd>
        <dt><kbd>c</kbd> <kbd>h</kbd></dt><dd>Follow the probe; fit the whole level</dd>
        <dt>Mouse</dt><dd>Drag to turn, right-drag to pan, scroll to zoom</dd>
        <dt><kbd>f</kbd> <kbd>Esc</kbd></dt><dd>Full screen; back out one level</dd>
      </dl>
    </div>
    <div class="pz-select" hidden>
      <div class="pz-select-card">
        <div class="row pz-select-head">
          <div>
            <h2>Orbit puzzles</h2>
            <p class="muted">Launch a probe and let real gravity bend it to the goal.</p>
          </div>
          <button class="btn" data-act="menu">← Cosmos menu</button>
        </div>
        <div class="pz-grid"></div>
        <h3 class="pz-sub">Keep playing</h3>
        <div class="pz-extra"></div>
        <p class="muted pz-folder"></p>
      </div>
    </div>
  </div>`;

function fmt(n, digits = 3) {
  if (!Number.isFinite(n)) return "–";
  const a = Math.abs(n);
  if (a !== 0 && (a >= 1e6 || a < 1e-3)) return n.toExponential(2);
  return n.toLocaleString("en-US", { maximumSignificantDigits: digits });
}

const starText = (n) => "★".repeat(n) + "☆".repeat(3 - n);

/* The frame-rate cap is a per-machine convenience, so it lives in the browser. */
const FPS_KEY = "cosmos.puzzles.maxFps";
function readFpsCap() {
  const fromUrl = new URLSearchParams(location.search).get("pzfps");
  if (fromUrl !== null) return Number(fromUrl) || 0;
  try {
    // Unset means the power-saving default; a stored -1 means "Smooth" was chosen.
    const stored = Number(localStorage.getItem(FPS_KEY));
    return stored > 0 ? stored : stored < 0 ? 0 : 30;
  } catch {
    return 30;
  }
}
function writeFpsCap(value) {
  try {
    localStorage.setItem(FPS_KEY, String(value));
  } catch {
    /* private window: the choice just does not stick */
  }
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/* Sound from the shared recipes (shared/forge_sound.js), started on the first
 * click or key because browsers refuse audio before that. */
function makeSound() {
  let actx = null;
  let resting = false;
  let master = null;
  let noise = null;
  let byEvent = new Map();
  const engine = () => (typeof ForgeSound !== "undefined" ? ForgeSound : null); // eslint-disable-line no-undef
  return {
    load(list) {
      byEvent = new Map(list.map((d) => [d.event, d]));
    },
    unlock() {
      const fs = engine();
      if (!fs) return;
      if (!actx) {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return;
        actx = new Ctx();
        master = actx.createGain();
        master.gain.value = 0.55;
        master.connect(actx.destination);
        noise = fs.makeNoise(actx, 1);
      }
      if (actx.state === "suspended") actx.resume();
    },
    play(event) {
      const def = byEvent.get(event);
      const fs = engine();
      if (!def || !fs || !actx || actx.state !== "running") return;
      fs.schedule(actx, master, noise, def, actx.currentTime, 1);
    },
    // Hidden (another app in front, or the window away): let the audio
    // device sleep. Shown again: wake it, if it was awake before.
    rest(hidden) {
      if (!actx || actx.state === "closed") return;
      if (hidden && actx.state === "running") {
        resting = true;
        actx.suspend();
      } else if (!hidden && resting) {
        resting = false;
        actx.resume();
      }
    },
    close() {
      actx?.close();
    },
  };
}

export default {
  async mount(root, ctx) {
    root.innerHTML = HTML;
    const host = root.querySelector(".puzzles");
    const $ = (s) => root.querySelector(s);
    // The caption and the launch panel sit just under the toolbar, however
    // many rows it wraps to in a narrow window (--pz-head in app.css).
    const headObserver = new ResizeObserver(() => {
      const top = $(".pz-top");
      if (top.offsetHeight) host.style.setProperty("--pz-head", `${top.offsetTop + top.offsetHeight}px`);
    });
    headObserver.observe($(".pz-top"));
    const view3d = new PuzzleView($(".pz-canvas"));
    const sound = makeSound();
    const params = new URLSearchParams(location.search);

    const state = {
      phase: "select",
      levels: [],
      folder: "",
      progress: { levels: {}, endless: { best_difficulty: 0 } },
      meta: null,
      level: null,
      sys: null,
      fields: [],
      aim: { speed: 1, heading: 90, elevation: 0 },
      run: null,
      carry: 0,
      warp: DEFAULT_WARP,
      paused: false,
      preview: true,
      follow: true,
      view: { target: [0, 0, 0], yaw: 0.5, pitch: 0.85, dist: 100 },
      burning: new Set(),
      referenceBurns: null,
      previewDirty: true,
      flightPreviewAt: 0,
      lastBurnSound: 0,
      labels: [],
      extent: 50,
      dirty: true,
      found: new Set(),
      discoverTotal: 0,
      saveTimer: 0,
      saveWarned: false,
      maxFps: readFpsCap(),
    };

    const L = () => state.level;
    const currentTime = () => (state.run ? state.run.time : 0);
    const aimOrigin = () => (L().launch.from !== undefined ? state.sys.position(L().launch.from, 0) : L().launch.pos);

    /* --- lists and progress ------------------------------------------------ */

    async function loadLists() {
      try {
        const [lv, pr] = await Promise.all([ctx.api("/api/levels"), ctx.api("/api/puzzles/progress")]);
        state.levels = lv.levels;
        state.folder = lv.folder;
        state.progress = pr;
      } catch (err) {
        ctx.toast(`The levels could not load: ${err.message}`);
      }
    }

    function card({ top, name, text, stars, foot, dataset }) {
      const b = el("button", "pz-card");
      Object.assign(b.dataset, dataset);
      b.append(el("span", "num", top), el("strong", "", name), el("small", "", text));
      if (stars !== undefined) b.append(el("span", "stars", starText(stars)));
      if (foot) b.append(el("span", "foot muted", foot));
      return b;
    }

    function renderSelect() {
      const hand = state.levels.filter((l) => l.goal !== "explore");
      const explore = state.levels.filter((l) => l.goal === "explore");
      const grid = $(".pz-grid");
      if (!hand.length) {
        grid.replaceChildren(el("p", "muted", `No levels found. Level files go in ${state.folder}.`));
      } else {
        grid.replaceChildren(
          ...hand.map((l, i) => {
            const saved = state.progress.levels[l.id] || {};
            return card({
              top: `Level ${i + 1} · ${GOAL_WORDS[l.goal] || l.goal}`,
              name: l.name,
              text: (l.caption || "").split(/(?<=\.)\s/)[0],
              stars: saved.stars || 0,
              foot: Number.isFinite(saved.best_cost) ? `Best cost ${fmt(saved.best_cost)}` : saved.plays ? `${saved.plays} tries` : "",
              dataset: { level: l.id },
            });
          }),
        );
      }
      const best = state.progress.endless?.best_difficulty || 0;
      const extras = [
        card({
          top: "Endless",
          name: "New level every time",
          text: "Made on the spot and flown once to prove it can be solved before you see it. Each win raises the difficulty.",
          foot: best ? `Best: difficulty ${best}. Starts at 1.` : "Starts at difficulty 1.",
          dataset: { endless: "1" },
        }),
      ];
      if (best > 1) {
        extras.push(
          card({ top: "Endless", name: `Carry on at difficulty ${best}`, text: "Pick up where your best run reached.", dataset: { endless: String(best) } }),
        );
      }
      for (const l of explore) {
        const found = state.progress.explore?.[l.id]?.found?.length || 0;
        extras.push(card({ top: "Explore", name: l.name, text: (l.caption || "").split(/(?<=\.)\s/).slice(0, 2).join(" "), foot: `★ ${found} of ${l.discoverable || 0} stars found`, dataset: { level: l.id } }));
      }
      $(".pz-extra").replaceChildren(...extras);
      $(".pz-folder").textContent = `Levels are JSON files in ${state.folder}; stars are saved beside them.`;
    }

    async function showSelect() {
      if (state.phase === "flying") saveExplore(false);
      await loadLists();
      renderSelect();
      showPhase("select");
    }

    /* Explore levels save what was found as it is found, not only when a probe
     * is lost: a probe can coast for ever, and Forge can be closed mid-flight. */
    /* Send progress. No answer at all (the server is down or restarting):
       keep the result and try again through ForgeIdle.poll, less often the
       longer it takes and never while hidden, until it lands. A refusal from
       the server goes to `refused` instead. A newer save under the same key
       replaces a waiting older one. */
    const retries = new Map();
    let retryWarned = false;
    function sendProgress(key, body, refused) {
      retries.get(key)?.stop();
      retries.delete(key);
      const attempt = () =>
        ctx
          .api("/api/puzzles/progress", { json: body })
          .then((p) => {
            state.progress = p;
            return true;
          })
          .catch((err) => {
            if (!err.status) return false;
            refused(err);
            return true;
          });
      attempt().then((done) => {
        if (done || !window.ForgeIdle) return;
        if (!retryWarned) {
          retryWarned = true;
          ctx.toast("Cosmos is not answering. Your progress is kept and saved when it is back.", 6000);
        }
        const job = ForgeIdle.poll(
          async () => {
            if (!(await attempt())) return false;
            job.stop();
            if (retries.get(key) === job) retries.delete(key);
          },
          3000,
          { backoff: 2, maxMs: 30000 },
        );
        retries.set(key, job);
      });
    }

    function saveExplore(ended) {
      clearTimeout(state.saveTimer);
      const run = state.run;
      if (state.meta?.kind !== "explore" || !run) return;
      const body = { explore: state.meta.id, found: [...state.found], farthest: Math.round(run.farthest * 100) / 100, time: Math.round(run.time * 100) / 100, ended };
      sendProgress(`explore:${body.explore}`, body, (err) => {
        if (state.saveWarned) return;
        state.saveWarned = true;
        ctx.toast(`Stars found were not saved: ${err.message}`, 9000);
      });
    }

    function saveResult(run, sc) {
      const meta = state.meta;
      if (meta.kind === "explore") return saveExplore(true);
      let body = null;
      if (meta.kind === "level") body = { level: meta.id, won: sc.won, stars: sc.stars, cost: Math.round(sc.cost * 1e4) / 1e4, time: Math.round(run.time * 100) / 100 };
      if (meta.kind === "endless" && sc.won) body = { endless_difficulty: meta.difficulty };
      if (!body) return;
      sendProgress(`result:${Date.now()}:${Math.random()}`, body, (err) => ctx.toast(`Your result was not saved: ${err.message}`));
    }

    /* --- opening a level ------------------------------------------------------ */

    function extentNow() {
      const sys = state.sys.at(0);
      let e = 1;
      for (let i = 0; i < sys.bodies.length; i++) e = Math.max(e, Math.hypot(sys.px[i], sys.py[i], sys.pz[i]));
      return e;
    }

    function fitView(useLevelCamera) {
      const cam = useLevelCamera ? L().camera || {} : {};
      let target = [0, 0, 0];
      if (typeof cam.target === "string" && state.sys.body(cam.target)) target = state.sys.position(cam.target, currentTime());
      else if (Array.isArray(cam.target)) target = cam.target;
      state.view = { target, yaw: cam.yaw ?? 0.5, pitch: cam.pitch ?? 0.85, dist: cam.dist ?? state.extent * 2.4 };
      state.follow = state.phase === "flying" ? state.follow : true;
      state.dirty = true;
    }

    function buildLabels() {
      const box = $(".pz-labels");
      box.replaceChildren();
      state.labels = state.sys.bodies.map((b, index) => {
        const node = el("div", `pz-label ${b.kind}`, b.name);
        box.appendChild(node);
        return { node, body: index };
      });
      if (L().goal.type === "waypoints") {
        L().goal.points.forEach((_, k) => {
          const node = el("div", "pz-label ring", String(k + 1));
          box.appendChild(node);
          state.labels.push({ node, ring: k });
        });
      }
    }

    function buildBurnButtons() {
      const box = $(".pz-burns");
      box.replaceChildren(
        ...Object.entries(BURN_KEYS).map(([key, dir]) => {
          const b = el("button", "btn small", `${BURN_LABELS[dir]} `);
          b.append(el("kbd", "", key));
          b.dataset.burn = dir;
          const stop = () => state.burning.delete(dir);
          b.addEventListener("pointerdown", () => {
            sound.unlock();
            if (state.phase === "flying") state.burning.add(dir);
          });
          b.addEventListener("pointerup", stop);
          b.addEventListener("pointerleave", stop);
          return b;
        }),
      );
    }

    function setLevel(raw, meta) {
      const problems = checkLevel(raw);
      if (problems.length) {
        ctx.toast(`${raw?.name || "This level"} cannot be played: ${problems.slice(0, 3).join(" ")}`, 9000);
        return false;
      }
      const level = prepareLevel(raw);
      level.time_scale ??= 6;
      state.level = level;
      state.meta = meta;
      state.sys = new RailSystem({ G: level.G, softening: level.softening, bodies: level.bodies });
      state.fields = level.fields.map((f) => new Field(f, state.sys));
      state.run = null;
      state.referenceBurns = null;
      state.burning.clear();
      state.paused = false;
      state.carry = 0;
      state.extent = extentNow();
      state.discoverTotal = meta.kind === "explore" ? discoverableIds(level).length : 0;
      state.found = new Set(meta.kind === "explore" ? state.progress.explore?.[meta.id]?.found || [] : []);

      const launch = level.launch;
      let heading = 90;
      if (launch.from !== undefined) {
        const v = state.sys.velocity(launch.from, 0);
        if (Math.hypot(v[0], v[1]) > 0) heading = (Math.atan2(v[1], v[0]) * 180) / Math.PI;
      }
      state.aim = clampAim(level, { speed: launch.speed[0] + (launch.speed[1] - launch.speed[0]) * 0.4, heading, elevation: 0 });

      view3d.setLevel(level, state.sys, state.fields);
      buildLabels();
      buildBurnButtons();
      $(".pz-title").textContent = meta.kind === "endless" ? `Endless · difficulty ${meta.difficulty}` : level.name;
      $(".pz-caption").textContent = level.caption || "";
      $(".pz-caption").hidden = !level.caption;
      setupAimInputs();
      showPhase("aim");
      fitView(true);
      state.previewDirty = true;
      return true;
    }

    async function openLevel(id) {
      try {
        const raw = await ctx.api(`/api/levels/${encodeURIComponent(id)}`);
        return setLevel(raw, { kind: raw.goal?.type === "explore" ? "explore" : "level", id });
      } catch (err) {
        ctx.toast(`That level could not load: ${err.message}`);
        return false;
      }
    }

    function openEndless(difficulty, seed = null) {
      ctx.toast("Building a level and checking it can be solved…", 2000);
      return new Promise((resolve) => {
        setTimeout(() => {
          const s = seed ?? Math.floor(Math.random() * 1e9);
          try {
            const level = generateLevel(s, difficulty);
            resolve(setLevel(level, { kind: "endless", id: level.id, seed: s, difficulty }));
          } catch (err) {
            ctx.toast(`No level could be built: ${err.message}`);
            resolve(false);
          }
        }, 40);
      });
    }

    /* --- aiming ---------------------------------------------------------------- */

    function aimInputs(key) {
      return [root.querySelector(`[data-aim="${key}"]`), root.querySelector(`[data-aim-range="${key}"]`)];
    }

    function setupAimInputs() {
      const launch = L().launch;
      const ranges = {
        speed: launch.speed,
        heading: launch.heading[0] <= 0 && launch.heading[1] >= 360 ? [0, 360] : launch.heading,
        elevation: launch.elevation,
      };
      for (const [key, [lo, hi]] of Object.entries(ranges)) {
        for (const input of aimInputs(key)) {
          input.min = lo;
          input.max = hi;
        }
      }
      $(".pz-elev").hidden = launch.elevation[0] === launch.elevation[1];
      syncAimInputs();
    }

    function syncAimInputs(except = null) {
      for (const key of ["speed", "heading", "elevation"]) {
        const [num, range] = aimInputs(key);
        const v = state.aim[key];
        if (num !== except) num.value = key === "speed" ? v.toFixed(3) : v.toFixed(1);
        if (range !== except) range.value = v;
      }
    }

    function computePreview() {
      const level = L();
      state.previewDirty = false;
      const start = launchState(level, state.sys, state.aim);
      const span = level.launch.speed[1] - level.launch.speed[0] || 1;
      const frac = (start.aim.speed - level.launch.speed[0]) / span;
      view3d.setAim({ origin: aimOrigin(), dir: aimDirection(start.aim), lengthPx: 30 + 140 * frac });
      if (state.preview && level.preview > 0) {
        const duration = level.preview * level.preview_time;
        const res = predict(state.sys, makeProbe(start.p, start.v, 0), {
          duration,
          dt: level.preview_dt,
          every: Math.max(1, Math.round(duration / level.preview_dt / 3000)),
          bounds: level.bounds,
        });
        view3d.setPreview(res.points, res.hit >= 0);
      } else {
        view3d.setPreview(null);
      }
      const parts = [`Launch speed ${fmt(start.aim.speed, 4)}`];
      if (Number.isFinite(level.par)) parts.push(`par ${fmt(level.par, 4)}`);
      if (level.fuel > 0 && level.goal.type !== "explore") parts.push(`plus ${fmt(level.fuel)} fuel for burns`);
      $(".pz-cost").textContent = parts.join(" · ");
      state.dirty = true;
    }

    /* --- flying ------------------------------------------------------------------ */

    function launch({ reference = false } = {}) {
      if (state.phase !== "aim") return;
      const level = L();
      if (reference && level.reference) {
        state.aim = clampAim(level, level.reference);
        state.referenceBurns = [...(level.reference.burns || [])].sort((a, b) => a.t - b.t);
        syncAimInputs();
      } else {
        state.referenceBurns = null;
      }
      state.run = new Run(level, state.aim, { sys: state.sys });
      state.flightPreviewAt = 0;
      state.carry = 0;
      state.paused = false;
      view3d.setAim(null);
      view3d.setPreview(null);
      view3d.setTrail(state.run.trail);
      sound.play("launch");
      showPhase("flying");
    }

    function retry() {
      if (!state.level || state.phase === "select") return;
      if (state.phase === "flying") saveExplore(true);
      if (state.run && state.run.trail.length > 6) view3d.addGhost(state.run.trail);
      state.run = null;
      state.referenceBurns = null;
      state.burning.clear();
      view3d.setTrail(null);
      showPhase("aim");
      state.previewDirty = true;
    }

    function applyBurns(dt, now) {
      const run = state.run;
      if (state.referenceBurns) {
        while (state.referenceBurns.length && run.time >= state.referenceBurns[0].t) {
          const b = state.referenceBurns.shift();
          run.burn(b.dir, b.dv);
          sound.play("burn");
        }
      }
      for (const dir of state.burning) {
        const spent = run.burn(dir, L().burn_rate * dt);
        if (spent > 0 && now - state.lastBurnSound > 150) {
          sound.play("burn");
          state.lastBurnSound = now;
        }
      }
    }

    function flyFrame(realDt, now) {
      const level = L();
      const run = state.run;
      let budget = state.carry + realDt * level.time_scale * WARPS[state.warp];
      const started = performance.now();
      let steps = 0;
      while (budget >= level.dt && run.status === "flying") {
        applyBurns(level.dt, now);
        run.step();
        budget -= level.dt;
        if (++steps % 64 === 0 && performance.now() - started > 12) {
          budget = 0;
          break;
        }
      }
      state.carry = budget;
      for (const ev of run.events) {
        if (ev.type === "waypoint") sound.play("waypoint");
        if (ev.type === "discover" && !state.found.has(ev.id)) {
          state.found.add(ev.id);
          sound.play("waypoint");
          ctx.toast(`Discovered ${ev.name}: ${state.found.size} of ${state.discoverTotal} stars found`);
          clearTimeout(state.saveTimer);
          state.saveTimer = setTimeout(() => saveExplore(false), 1500);
        }
      }
      run.events.length = 0;
      view3d.setTrail(run.trail);
      if (state.follow) {
        const k = 1 - Math.exp(-realDt * 5);
        const p = run.probe;
        state.view.target = [0, 1, 2].map((i) => state.view.target[i] + ([p.x, p.y, p.z][i] - state.view.target[i]) * k);
      }
      if (state.preview && level.preview > 0 && now >= state.flightPreviewAt && run.status === "flying") {
        const started = performance.now();
        const duration = level.preview * level.preview_time * 0.5;
        const res = predict(state.sys, run.probe, { duration, dt: level.preview_dt, every: Math.max(1, Math.round(duration / level.preview_dt / 2000)), bounds: level.bounds });
        view3d.setPreview(res.points, res.hit >= 0);
        // The live path costs a whole prediction; wait long enough that it stays a
        // small share of a CPU core on a big level, and refresh faster while burning.
        state.flightPreviewAt = now + Math.max(250, (performance.now() - started) * (state.burning.size ? 6 : 20));
      } else if (!state.preview) {
        view3d.setPreview(null);
      }
      if (run.status !== "flying") endFlight();
      state.dirty = true;
    }

    function bonusText(level, run) {
      const B = level.bonus;
      if (!B) return "";
      if (B.text) return B.text;
      if (B.type === "no_burns") return "Bonus: no burns";
      if (B.type === "time_under") return `Bonus: arrive by time ${fmt(B.value)} (you took ${fmt(run.time)})`;
      if (B.type === "close_pass") return `Bonus: pass within ${fmt(B.within)} of ${state.sys.body(B.body)?.name || B.body}`;
      return "";
    }

    function endFlight() {
      const run = state.run;
      const level = L();
      state.burning.clear();
      view3d.setPreview(null);
      const sc = score(level, run);
      sound.play(run.status === "won" ? "win" : "crash");
      showPhase("ended");
      const box = $(".pz-result");
      box.replaceChildren();
      if (state.meta.kind === "explore") {
        box.append(
          el("h2", "", "Probe lost"),
          el("p", "pz-reason", run.reason),
          el("div", "pz-stars pz-found", `★ ${state.found.size} of ${state.discoverTotal}`),
          el("p", "muted", `stars found and saved · this probe found ${run.discovered.size}, flew ${fmt(run.time)} time units and reached ${fmt(run.farthest)} from the centre. Nothing to fail here: launch another.`),
        );
        const row = el("div", "row pz-result-buttons");
        row.append(button("Launch another", "retry", "r"), button("Levels", "levels", "Esc"));
        box.append(row);
      } else {
        box.append(el("h2", "", sc.won ? "Goal reached" : "Not this time"), el("p", "pz-reason", run.reason));
        const stars = el("div", "pz-stars");
        for (let k = 0; k < 3; k++) stars.append(el("span", k < sc.stars ? "on" : "off", "★"));
        box.append(stars);
        const list = el("ul");
        list.append(el("li", sc.finish ? "on" : "off", "Finish the goal"));
        if (Number.isFinite(level.par)) list.append(el("li", sc.par ? "on" : "off", `Cost at or under par: ${fmt(sc.cost, 4)} of ${fmt(level.par, 4)}`));
        if (level.bonus) list.append(el("li", sc.bonus ? "on" : "off", bonusText(level, run)));
        box.append(list);
        const row = el("div", "row pz-result-buttons");
        row.append(button("Retry", "retry", "r"));
        if (sc.won) row.append(button(state.meta.kind === "endless" ? `Difficulty ${state.meta.difficulty + 1}` : "Next level", "next", "n"));
        row.append(button("Levels", "levels", "Esc"));
        box.append(row);
      }
      saveResult(run, sc);
    }

    function button(text, act, key) {
      const b = el("button", "btn", `${text} `);
      b.dataset.act = act;
      if (key) b.append(el("kbd", "", key));
      return b;
    }

    async function next() {
      if (state.phase !== "ended" || state.run?.status !== "won") return;
      const meta = state.meta;
      if (meta.kind === "endless") {
        await openEndless(meta.difficulty + 1);
        return;
      }
      const hand = state.levels.filter((l) => l.goal !== "explore");
      const i = hand.findIndex((l) => l.id === meta.id);
      if (i >= 0 && i + 1 < hand.length) await openLevel(hand[i + 1].id);
      else await showSelect();
    }

    /* Fly a few near misses instantly, so there are ghosts to look at. */
    function flyGhosts(count) {
      const level = L();
      const base = level.reference || state.aim;
      for (let k = 1; k <= count; k++) {
        const aim = clampAim(level, { ...base, heading: base.heading + (k % 2 ? 1 : -1) * k * 2.5, speed: base.speed * (1 - 0.03 * k) });
        const run = new Run(level, aim, { sys: state.sys });
        const limit = level.preview_time * 1.5;
        for (let s = 0; s < 80000 && run.status === "flying" && run.time < limit; s++) run.step();
        view3d.addGhost(run.trail);
      }
      state.dirty = true;
    }

    /* --- screens and readouts --------------------------------------------------- */

    function showPhase(phase) {
      state.phase = phase;
      const inLevel = phase !== "select";
      $(".pz-select").hidden = inLevel;
      $(".pz-top").hidden = !inLevel;
      $(".pz-status").hidden = !inLevel;
      $(".pz-labels").hidden = !inLevel;
      $(".pz-caption").hidden = !inLevel || !L()?.caption;
      $(".pz-aim").hidden = phase !== "aim";
      $(".pz-flight").hidden = phase !== "flying" && phase !== "ended";
      $(".pz-result").hidden = phase !== "ended";
      if (!inLevel) $(".pz-help").hidden = true;
      state.dirty = true;
      updateHud();
    }

    function fact(rows, key, value, className = "") {
      rows.push([key, value, className]);
    }

    function updateHud() {
      $(".pz-warp").textContent = `${WARPS[state.warp]}×`;
      $('[data-act="play"]').textContent = state.paused ? "▶" : "❚❚";
      $('[data-act="play"]').disabled = state.phase !== "flying";
      $('[data-act="follow"]').classList.toggle("on", state.follow);
      $('[data-act="fps"]').textContent = state.maxFps > 0 ? "Power saver" : "Smooth";
      const level = L();
      if (!level || state.phase === "select") return;
      const status = [];
      if (state.phase === "aim") status.push("Aiming · time waits for launch");
      if (state.meta.kind === "explore") status.push(`★ ${state.found.size} of ${state.discoverTotal} stars found`);
      if (state.meta.kind === "endless") status.push(`seed ${state.meta.seed}`);
      const saved = state.meta.kind === "level" ? state.progress.levels[state.meta.id] : null;
      if (saved) status.push(`best ${starText(saved.stars || 0)}`);
      if (state.phase === "flying" && state.paused) status.push("Paused");
      $(".pz-status").textContent = status.join(" · ");

      const run = state.run;
      if (!run) return;
      const sys = state.sys.at(run.time);
      const s = run.probe;
      const rows = [];
      fact(rows, "Time", fmt(run.time));
      const dom = sys.dominant(s.x, s.y, s.z, s.t);
      if (dom >= 0) {
        const v = Math.hypot(s.vx - sys.vx[dom], s.vy - sys.vy[dom], s.vz - sys.vz[dom]);
        fact(rows, `Speed near ${sys.bodies[dom].name}`, fmt(v));
      }
      const cost = run.launchSpeed + run.dvUsed;
      fact(rows, "Cost so far", Number.isFinite(level.par) ? `${fmt(cost, 4)} / par ${fmt(level.par, 4)}` : fmt(cost, 4), Number.isFinite(level.par) && cost > level.par ? "warn" : "");
      const g = level.goal;
      if (g.type === "explore") {
        fact(rows, "Stars found", `${state.found.size} of ${state.discoverTotal} (${run.discovered.size} by this probe)`);
        fact(rows, "From the centre", fmt(Math.hypot(s.x, s.y, s.z)));
      }
      if (g.type === "reach") {
        const i = sys.index.get(g.target);
        const d = Math.hypot(s.x - sys.px[i], s.y - sys.py[i], s.z - sys.pz[i]) - sys.bodies[i].r - g.radius;
        fact(rows, `To ${sys.bodies[i].name}`, fmt(Math.max(0, d)));
      } else if (g.type === "waypoints") {
        const w = g.points[Math.min(run.waypoint, g.points.length - 1)];
        const c = waypointPosition(sys, w, run.time);
        fact(rows, "Ring", `${Math.min(run.waypoint + 1, g.points.length)} of ${g.points.length}`);
        fact(rows, "Distance", fmt(Math.max(0, Math.hypot(s.x - c[0], s.y - c[1], s.z - c[2]) - w.radius)));
      } else if (g.type === "orbit") {
        const i = sys.index.get(g.target);
        const o = orbitAround(sys, i, s);
        const name = sys.bodies[i].name;
        if (o.bound) {
          fact(rows, "Lowest point", fmt(o.periapsis - sys.bodies[i].r), o.periapsis < sys.bodies[i].r + g.min_altitude ? "warn" : "");
          fact(rows, "Highest point", `${fmt(o.apoapsis - sys.bodies[i].r)} (limit ${fmt(g.max_apoapsis - sys.bodies[i].r)})`, o.apoapsis >= g.max_apoapsis ? "warn" : "");
        } else {
          fact(rows, `Around ${name}`, "not captured yet");
        }
        fact(rows, "Held in orbit", `${fmt(run.holdTime, 2)} of ${fmt(g.hold)}`);
      } else if (g.type === "land") {
        const i = sys.index.get(g.target);
        const d = Math.hypot(s.x - sys.px[i], s.y - sys.py[i], s.z - sys.pz[i]) - sys.bodies[i].r;
        const v = Math.hypot(s.vx - sys.vx[i], s.vy - sys.vy[i], s.vz - sys.vz[i]);
        fact(rows, `Height above ${sys.bodies[i].name}`, fmt(Math.max(0, d)));
        fact(rows, "Speed toward it", `${fmt(v)} (land at ${fmt(g.max_speed)} or slower)`, v > g.max_speed ? "warn" : "");
      }
      $(".pz-facts").replaceChildren(
        ...rows.flatMap(([k, v, cls]) => {
          const dd = el("dd", cls, v);
          return [el("dt", "", k), dd];
        }),
      );
      const hasFuel = level.fuel > 0;
      $(".pz-fuel-box").hidden = !hasFuel;
      if (hasFuel) {
        const fuelShown = level.goal.type === "explore" ? "plenty" : `${fmt(run.fuelLeft)} of ${fmt(level.fuel)}`;
        $(".pz-fuel-text").textContent = fuelShown;
        $(".pz-fuel i").style.width = `${Math.max(0, Math.min(1, run.fuelLeft / level.fuel)) * 100}%`;
        root.querySelectorAll("[data-burn]").forEach((b) => {
          b.disabled = run.fuelLeft <= 0 || state.phase !== "flying";
          b.classList.toggle("on", state.burning.has(b.dataset.burn));
        });
      }
    }

    function updateLabels() {
      const sys = state.sys.at(currentTime());
      const placed = [];
      for (const l of state.labels) {
        let p;
        if (l.body !== undefined) p = [sys.px[l.body], sys.py[l.body], sys.pz[l.body]];
        else p = waypointPosition(sys, L().goal.points[l.ring], currentTime());
        const s = view3d.project(p);
        let crowded = l.body !== undefined && placed.some((q) => Math.abs(q.x - s.x) < 70 && Math.abs(q.y - s.y) < 15);
        if (l.body !== undefined) {
          const b = sys.bodies[l.body];
          // A planet drawn right on top of its star only hides the star's name.
          const pi = b.parentIndex;
          if (!crowded && pi >= 0 && sys.bodies[pi].kind !== "blackhole") {
            const ps = view3d.project([sys.px[pi], sys.py[pi], sys.pz[pi]]);
            crowded = Math.hypot(ps.x - s.x, ps.y - s.y) < 28;
          }
          const found = state.found.has(b.id);
          if (l.found !== found) {
            l.found = found;
            l.node.textContent = found ? `★ ${b.name}` : b.name;
            l.node.classList.toggle("found", found);
          }
        }
        if (!s.visible || crowded || s.x < -50 || s.y < -20 || s.x > view3d.width + 50 || s.y > view3d.height + 20) {
          if (!l.node.hidden) l.node.hidden = true;
          continue;
        }
        if (l.node.hidden) l.node.hidden = false;
        const gap = l.body !== undefined ? Math.min(view3d.bodyRadiusPx(l.body), 200) * 0.75 : 0;
        const tx = l.ring !== undefined ? s.x - 4 : s.x + 9 + gap;
        const ty = l.ring !== undefined ? s.y - 30 : s.y - 8 - gap;
        // Only touch the page when a label really moved: style writes are what cost.
        if (!(Math.abs(tx - (l.x ?? -1e9)) < 0.5 && Math.abs(ty - (l.y ?? -1e9)) < 0.5)) {
          l.node.style.transform = `translate(${tx}px, ${ty}px)`;
          l.x = tx;
          l.y = ty;
        }
        if (l.body !== undefined) placed.push(s);
      }
    }

    /* --- input ---------------------------------------------------------------- */

    function act(name) {
      if (name === "menu") ctx.back();
      if (name === "levels") showSelect();
      if (name === "retry") retry();
      if (name === "launch") launch();
      if (name === "next") next();
      if (name === "play" && state.phase === "flying") state.paused = !state.paused;
      if (name === "slower") state.warp = Math.max(0, state.warp - 1);
      if (name === "faster") state.warp = Math.min(WARPS.length - 1, state.warp + 1);
      if (name === "fit" && state.level) {
        state.follow = false;
        fitView(false);
      }
      if (name === "follow") state.follow = !state.follow;
      if (name === "fps") {
        state.maxFps = state.maxFps ? 0 : 30;
        writeFpsCap(state.maxFps || -1);
      }
      if (name === "help") $(".pz-help").hidden = !$(".pz-help").hidden;
      updateHud();
    }

    root.addEventListener("click", (e) => {
      sound.unlock();
      const target = e.target.closest("[data-act],[data-level],[data-endless]");
      if (!target) return;
      if (target.dataset.act) act(target.dataset.act);
      else if (target.dataset.level) openLevel(target.dataset.level);
      else if (target.dataset.endless) openEndless(Number(target.dataset.endless) || 1);
    });

    root.addEventListener("input", (e) => {
      const t = e.target;
      if (t.dataset.opt === "preview") {
        state.preview = t.checked;
        state.previewDirty = true;
        return;
      }
      const key = t.dataset.aim || t.dataset.aimRange;
      if (!key || state.phase !== "aim") return;
      const v = Number(t.value);
      if (!Number.isFinite(v) || t.value === "") return;
      state.aim = clampAim(L(), { ...state.aim, [key]: v });
      syncAimInputs(t);
      state.previewDirty = true;
    });

    const canvasBox = $(".pz-canvas");
    let drag = null;
    canvasBox.addEventListener("contextmenu", (e) => e.preventDefault());
    canvasBox.addEventListener("pointerdown", (e) => {
      sound.unlock();
      if (!state.level) return;
      canvasBox.setPointerCapture(e.pointerId);
      const rect = canvasBox.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      if (state.phase === "aim" && e.button === 0) {
        const s = view3d.project(aimOrigin());
        if (s.visible && Math.hypot(s.x - sx, s.y - sy) < 44) {
          drag = { mode: e.shiftKey ? "elevate" : "aim", ox: s.x, oy: s.y, sy, elevation: state.aim.elevation };
          canvasBox.classList.add("aiming");
          return;
        }
      }
      drag = { mode: e.button === 2 || e.button === 1 || e.shiftKey ? "pan" : "turn", x: e.clientX, y: e.clientY };
      canvasBox.classList.add("dragging");
    });
    canvasBox.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const rect = canvasBox.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      if (drag.mode === "aim") {
        const origin = aimOrigin();
        const range = L().launch.speed;
        const frac = Math.min(1, Math.max(0, (Math.hypot(sx - drag.ox, sy - drag.oy) - 12) / 260));
        const nextAim = { ...state.aim, speed: range[0] + frac * (range[1] - range[0]) };
        const hit = view3d.planeHit(e.clientX, e.clientY, origin[2]);
        if (hit && Math.hypot(hit[0] - origin[0], hit[1] - origin[1]) > 1e-9) nextAim.heading = (Math.atan2(hit[1] - origin[1], hit[0] - origin[0]) * 180) / Math.PI;
        state.aim = clampAim(L(), nextAim);
        syncAimInputs();
        state.previewDirty = true;
      } else if (drag.mode === "elevate") {
        state.aim = clampAim(L(), { ...state.aim, elevation: drag.elevation - (sy - drag.sy) * 0.25 });
        syncAimInputs();
        state.previewDirty = true;
      } else {
        const dx = e.clientX - drag.x;
        const dy = e.clientY - drag.y;
        drag.x = e.clientX;
        drag.y = e.clientY;
        if (drag.mode === "turn") {
          state.view.yaw -= dx * 0.006;
          state.view.pitch = Math.min(1.52, Math.max(-1.52, state.view.pitch + dy * 0.006));
        } else {
          const perPx = (state.view.dist * 2 * Math.tan((50 * Math.PI) / 360)) / view3d.height;
          const { right, up } = view3d.screenAxes();
          state.view.target = [0, 1, 2].map((i) => state.view.target[i] - right[i] * dx * perPx + up[i] * dy * perPx);
          state.follow = false;
        }
      }
      state.dirty = true;
    });
    const endDrag = () => {
      drag = null;
      canvasBox.classList.remove("aiming", "dragging");
    };
    canvasBox.addEventListener("pointerup", endDrag);
    canvasBox.addEventListener("pointercancel", endDrag);
    canvasBox.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        if (!state.level) return;
        const delta = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
        state.view.dist = Math.min(L().bounds * 3, Math.max(0.3, state.view.dist * Math.exp(delta * 0.0013)));
        state.dirty = true;
      },
      { passive: false },
    );

    function onKey(e) {
      const tag = e.target?.tagName || "";
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (state.phase === "select") return;
      sound.unlock();
      const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      if (BURN_KEYS[k]) {
        if (state.phase === "flying") state.burning.add(BURN_KEYS[k]);
        e.preventDefault();
        return;
      }
      const level = L();
      if (k === " ") {
        if (state.phase === "aim") launch();
        else if (state.phase === "flying") state.paused = !state.paused;
        else if (state.phase === "ended") retry();
      } else if (k === "r") retry();
      else if (k === "n") next();
      else if (k === "[") act("slower");
      else if (k === "]") act("faster");
      else if (k === "g") {
        state.preview = !state.preview;
        root.querySelector('[data-opt="preview"]').checked = state.preview;
        state.previewDirty = true;
        if (!state.preview) view3d.setPreview(null);
      } else if (k === "c") act("follow");
      else if (k === "h") act("fit");
      else if (k === "?") act("help");
      else if (state.phase === "aim" && /^Arrow/.test(k)) {
        const big = e.shiftKey ? 10 : 1;
        const span = level.launch.speed[1] - level.launch.speed[0];
        const a = { ...state.aim };
        if (k === "ArrowLeft") a.heading += 0.5 * big;
        if (k === "ArrowRight") a.heading -= 0.5 * big;
        if (k === "ArrowUp") a.speed += span * 0.004 * big;
        if (k === "ArrowDown") a.speed -= span * 0.004 * big;
        state.aim = clampAim(level, a);
        syncAimInputs();
        state.previewDirty = true;
      } else return;
      e.preventDefault();
      state.dirty = true;
    }
    function onKeyUp(e) {
      const dir = BURN_KEYS[e.key.length === 1 ? e.key.toLowerCase() : e.key];
      if (dir) state.burning.delete(dir);
    }
    const onBlur = () => state.burning.clear();
    document.addEventListener("keydown", onKey);
    document.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    const onShown = () => sound.rest(!(window.ForgeIdle ? ForgeIdle.shown() : !document.hidden));
    document.addEventListener("visibilitychange", onShown);
    document.addEventListener("forge-visible", onShown);

    /* --- the loop ---------------------------------------------------------------- */

    let frame = 0;
    let last = performance.now();
    let lastRender = 0;
    let lastHud = 0;
    let frameCount = 0;
    function tick(now) {
      frame = requestAnimationFrame(tick);
      // With a cap, skip whole frames (physics and drawing); time still advances correctly.
      if (state.maxFps > 0 && now - last < 1000 / state.maxFps - 2) return;
      const realDt = Math.min(0.1, Math.max(0, (now - last) / 1000));
      last = now;
      if (!state.level || state.phase === "select") return;
      if (state.phase === "flying" && !state.paused) flyFrame(realDt, now);
      if (state.phase === "aim" && state.previewDirty) computePreview();
      // With nothing moving, redraw only often enough for the gentle pulses.
      if (state.dirty || now - lastRender > 66) {
        view3d.render(state.view, {
          t: currentTime(),
          now,
          phase: state.phase,
          probe: state.run ? state.run.probe : null,
          waypoint: state.run ? state.run.waypoint : 0,
          launchOrigin: state.phase === "aim" ? aimOrigin() : null,
          showGrid: true,
        });
        // A galaxy has well over a hundred names; moving them every other frame looks the same.
        if (state.labels.length < 40 || (frameCount++ & 1) === 0) updateLabels();
        state.renders = (state.renders || 0) + 1;
        lastRender = now;
        state.dirty = false;
      }
      if (now - lastHud > 120) {
        updateHud();
        lastHud = now;
      }
    }

    ctx
      .api("/api/sounds")
      .then((r) => {
        sound.load(r.sounds);
        if (r.problems.length) console.warn("Cosmos sound recipes with problems:", r.problems);
      })
      .catch(() => {});
    await showSelect();
    frame = requestAnimationFrame(tick);

    const debug = {
      state,
      openLevel,
      openEndless,
      launchReference: () => launch({ reference: true }),
      flyGhosts,
      retry,
      setWarp: (i) => (state.warp = Math.max(0, Math.min(WARPS.length - 1, i))),
    };
    host.__debug = debug;

    const pz = params.get("pz");
    if (pz) {
      const ok = pz.startsWith("endless") ? await openEndless(Number(pz.split("-")[1]) || 1, params.has("pzseed") ? Number(params.get("pzseed")) : null) : await openLevel(pz);
      if (ok) {
        if (params.has("pzghosts")) flyGhosts(Number(params.get("pzghosts")) || 0);
        if (params.has("pzwarp")) debug.setWarp(Number(params.get("pzwarp")));
        if (params.has("pzfit")) act("fit");
        if (params.has("pzfire")) launch({ reference: true });
      }
    }

    return {
      onEscape() {
        if (!$(".pz-help").hidden) {
          $(".pz-help").hidden = true;
          return true;
        }
        if (state.phase !== "select") {
          showSelect();
          return true;
        }
        return false;
      },
      unmount() {
        if (state.phase === "flying") saveExplore(false);
        cancelAnimationFrame(frame);
        headObserver.disconnect();
        document.removeEventListener("keydown", onKey);
        document.removeEventListener("keyup", onKeyUp);
        window.removeEventListener("blur", onBlur);
        document.removeEventListener("visibilitychange", onShown);
        document.removeEventListener("forge-visible", onShown);
        view3d.dispose();
        sound.close();
        root.replaceChildren();
      },
      debug,
    };
  },
};
