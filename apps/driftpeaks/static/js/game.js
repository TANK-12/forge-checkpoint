/* Drift Peaks: the loop that ties the mountain, the rider and the drawing
   together, plus the menus, the goals, the save file and the sound.

   Two modes. Goals: a crash ends the run, and the level's three goals are
   counted. Zen: no score, no crashes that end anything - a fall just puts
   you back on the snow - and the weather and the day roll on. */

import { World, PX_PER_M } from "./world.js";
import { newRider, step, bounce, recover, crash } from "./rider.js";
import { skyAt, nightness, resolveRoles, companion, TIMES } from "./palette.js";
import { Weather, STORMY } from "./weather.js";
import * as R from "./render.js";
import { defaults, clean, buildForm } from "./settings.js";
import { createMusic } from "./music.js";
import { newStats, currentLevel, newlyMet, goalKey, progressText } from "./goals.js";
import { MODES, todayKey, modeFromLink, flagMetres } from "./modes.js";
import { EMPTY_SAVE, mergeSave, overTitle } from "./save.js";

const $ = (id) => document.getElementById(id);
const canvas = $("view");
const ctx = canvas.getContext("2d");

const game = {
  shapes: {}, levels: [], sounds: {},
  save: mergeSave({}, EMPTY_SAVE), // a fresh copy of the empty save until the real one is read
  settings: defaults(),
  mode: "goals", phase: "loading", // "loading" until boot() has the shapes: keys do nothing yet
  world: null, rider: null, weather: new Weather(), stats: newStats(),
  cam: { x: 0, y: 0 }, zoom: 1, time: 0, dayT: 0.3,
  combo: 0, comboT: 0, comboScore: 0, trail: [], scarf: [], spray: [], shake: 0,
  theme: { accent: "#8ab4ff", accent_2: "" },
  input: { pressed: false, held: false },
  level: 0, metThisRun: [], drawMs: 0,
  day: todayKey(), flagX: 0, flagLabel: "", flagPassed: false, repaint: false,
};
// what the chosen way to ride does (modes.js)
const mode = () => MODES[game.mode] || MODES.goals;

// --- the Forge theme ---------------------------------------------------------

addEventListener("message", (e) => {
  const m = e.data;
  if (e.source === window.parent && m && m.forge === "theme" && m.theme) {
    game.theme = { ...game.theme, ...m.theme };
    document.documentElement.style.setProperty("--accent", game.theme.accent);
  }
});

function accents() {
  const a = game.theme.accent || "#8ab4ff";
  return [a, game.theme.accent_2 && game.theme.accent_2 !== a ? game.theme.accent_2 : companion(a)];
}

// --- sound -----------------------------------------------------------------

const audio = { ctx: null, gain: null, noise: null, last: {} };
const music = createMusic();
// Settings says what plays and where a player's own music goes.
document.addEventListener("music-tracks", (e) => {
  const { count, folder } = e.detail;
  const where = folder || "the music folder";
  document.getElementById("music-note").textContent = count
    ? `Music: ${count} track${count === 1 ? "" : "s"} from ${where}.`
    : `Music: Drift Peaks' own tune. To ride to your own, put audio files (mp3, ogg, flac, m4a) in ${where} and open the game again.`;
});
// the first key or click is what lets the browser start the music
for (const type of ["keydown", "pointerdown"]) addEventListener(type, () => music.start(), { capture: true });
function sound(event, pitch = 1) {
  const def = game.sounds[event];
  if (!def || !window.ForgeSound || game.settings.volume <= 0) return;
  try {
    if (!audio.ctx) {
      audio.ctx = new AudioContext();
      audio.gain = audio.ctx.createGain();
      audio.gain.connect(audio.ctx.destination);
      audio.noise = ForgeSound.makeNoise(audio.ctx);
    }
    if (audio.ctx.state === "suspended") audio.ctx.resume();
    const now = audio.ctx.currentTime;
    if (audio.last[event] && now - audio.last[event] < 0.05) return;
    audio.last[event] = now;
    audio.gain.gain.value = game.settings.volume / 100;
    ForgeSound.schedule(audio.ctx, audio.gain, audio.noise, def, now, pitch);
  } catch (err) {
    /* no audio device: the game plays on silently */
  }
}

// --- saving ----------------------------------------------------------------

// The save goes out 400 ms after the last change. A failed one is kept and
// tried again, waiting longer each time (2 s doubling up to 30 s), and only
// while the game is on screen; each try sends the save as it is by then, so
// the newest state always wins.
//
// Nothing is written until the real save has been read (save.js): if the read
// failed while the page opened, each try reads it again first, and what was
// ridden in the meantime is laid on top of it. Until then an empty save would
// land on top of the real bests and coins.
const shown = () => !document.hidden && (window.ForgeVisible ? ForgeVisible.on !== false : true);
let saveTimer = 0, saveWait = 0, saveOwed = false, saveTried = 0, saveRead = false, settingsChanged = false;
function persist(delay = 400) {
  saveOwed = true;
  trySave(delay);
}
function trySave(delay) {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    if (saveWait && !shown()) return; // a retry waits for the game to be back on screen
    saveTried = Date.now();
    let ok = saveRead || (await readSave());
    if (ok && saveOwed) {
      saveOwed = false; // a change made while this one is on its way owes another
      game.save.settings = game.settings;
      try {
        const r = await fetch("api/save", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(game.save) });
        ok = r.ok || r.status === 413; // too large does not get better by retrying
      } catch (err) {
        ok = false;
      }
      if (!ok) saveOwed = true;
    }
    if (ok) { saveWait = 0; return; }
    saveWait = Math.min(30000, saveWait ? saveWait * 2 : 2000);
    if (shown()) trySave(saveWait);
  }, delay);
}
// back on screen with a save still owed (or not yet read): try now, unless a
// failed try was too recent, in which case it waits out the rest of its backoff
function onShown() {
  if ((saveRead && !saveOwed) || !shown()) return;
  const left = saveWait ? saveTried + saveWait - Date.now() : 0;
  trySave(Math.max(400, left));
}

// The save from the backend, or null when it could not be read
async function fetchSave() {
  try {
    const r = await fetch("api/save");
    if (!r.ok) return null;
    const body = await r.json();
    return body && typeof body === "object" && !Array.isArray(body) ? body : null;
  } catch (err) {
    return null;
  }
}

async function readSave() {
  const real = await fetchSave();
  if (saveRead) return true; // another try got there first: merging twice would count the coins twice
  if (!real) return false;
  takeSave(real);
  return true;
}

// The real save arrives: lay this page's save on top of it. At boot this
// page's save is still empty, so it is simply the real one.
function takeSave(real) {
  const opening = game.phase === "loading";
  game.save = mergeSave(real, game.save, settingsChanged);
  saveRead = true;
  if (!settingsChanged) {
    game.settings = clean(game.save.settings);
    music.setVolume(game.settings.music);
    showFps();
    if (!opening) resize();
  }
  if (MODES[game.save.mode] && (opening || game.phase === "title")) game.mode = game.save.mode;
  if (game.phase === "title") renderTitle();
}

// --- a run -----------------------------------------------------------------

function params() {
  const s = game.settings;
  return { gravity: s.gravity, jump: s.jump, flip_speed: s.flip_speed, min_speed: s.min_speed,
    max_speed: s.max_speed, forgiveness: s.forgiveness, friction: 0.18 };
}

function newRun() {
  game.day = todayKey();
  const m = mode();
  const seed = m.seed ? m.seed(game.day) : game.settings.seed || Math.floor(Math.random() * 1e9);
  game.world = new World(seed, game.shapes);
  game.rider = newRider(game.world);
  // a flag where the best run ended: distance only grows while riding, so the
  // best run's end is that many metres on from the start
  const best = game.settings.best_flag ? flagMetres(game.mode, game.save, game.day) : 0;
  game.flagX = best > 0 ? game.rider.x + best * PX_PER_M : 0;
  game.flagLabel = `${Math.floor(best).toLocaleString()} m`;
  game.flagPassed = false;
  game.stats = newStats();
  game.combo = 0; game.comboT = 0; game.comboScore = 0;
  game.trail = []; game.scarf = []; game.spray = [];
  game.cam.x = game.rider.x - 300; game.cam.y = game.rider.y;
  game.level = currentLevel(game.levels, game.save.done);
  game.metThisRun = [];
  game.over = 0;
}

function start() {
  newRun();
  setPhase("playing");
}

function setPhase(p) {
  game.phase = p;
  for (const id of ["title", "over", "pause", "settings", "art"]) $(id).hidden = id !== p;
  $("hud").hidden = !(p === "playing" || p === "pause");
  if (p === "title") renderTitle();
}

function popup(text) {
  const el = document.createElement("div");
  el.className = "pop";
  el.textContent = text;
  $("popups").appendChild(el);
  setTimeout(() => el.remove(), 1400);
}

function trick(name, points, flips = 1) {
  game.combo += flips;
  game.comboT = 2.2;
  const pts = Math.round(points * Math.max(1, game.combo));
  game.comboScore += pts;
  game.stats.score += pts;
  game.stats.combo = Math.max(game.stats.combo, game.combo);
  if (mode().scored) popup(`${name}  +${pts.toLocaleString()}`);
  else popup(name);
  if (game.combo >= 3 && game.combo - flips < 3) {
    game.rider.boost = 2.5;
    sound("combo");
  } else if (game.combo >= 3) game.rider.boost = Math.max(game.rider.boost, 1.6);
}

function endCombo() {
  if (game.combo >= 2 && mode().scored) popup(`Combo x${game.combo}`);
  game.combo = 0; game.comboScore = 0;
}

function handle(events) {
  const st = game.stats, r = game.rider;
  for (const e of events) {
    if (e.type === "jump") sound("jump");
    else if (e.type === "grinding") st.grind += e.px / PX_PER_M;
    else if (e.type === "land") {
      sound("land");
      burst(r.x, r.y, 10);
      if (e.flips > 0) {
        st.flips += e.flips;
        st.jump_flips = Math.max(st.jump_flips, e.flips);
        const name = ["", "Backflip", "Double backflip", "Triple backflip", "Quadruple backflip"][Math.min(4, e.flips)] || `${e.flips}x backflip`;
        trick(name, 250 * e.flips, e.flips);
        sound("flip", 1 + 0.1 * Math.min(6, game.combo));
      }
      if (e.on === "rope") { trick("Grind", 120); sound("grind"); }
      if (e.on === "ground") {
        const cleared = game.world.chasms.filter((c) => c.x1 >= e.takeoffX - 40 && c.x2 <= r.x).length;
        if (cleared) { st.chasms += cleared; trick("Chasm", 150 * cleared); }
      }
    } else if (e.type === "crash") {
      sound("crash");
      game.shake = 0.5;
      burst(r.x, r.y, 26);
      endCombo();
      if (!mode().crashEnds) game.over = -1.2; // back on the snow in a moment
      else game.over = 1.6; // let the tumble play, then the summary
    }
  }
}

function collide() {
  const r = game.rider, w = game.world, st = game.stats;
  if (r.state === "crashed") return;
  for (const it of w.items) {
    if (it.taken || Math.abs(it.x - r.x) > 60) continue;
    if (it.type === "coin") {
      if (Math.hypot(it.x - r.x, it.y - (r.y - 18)) < 26) {
        it.taken = true; st.coins++; game.save.coins++; st.score += 10; sound("coin", 1 + (st.coins % 5) * 0.06);
      }
    } else if (it.type === "rock") {
      const top = it.y - it.radius * 1.2;
      if (Math.abs(it.x - r.x) > it.radius + 6) continue;
      if (r.state === "air" && r.vy > 0 && r.y >= top - 6 && r.y <= it.y) {
        bounce(r, params());
        st.rocks++;
        trick("Rock bounce", 150);
        sound("jump", 1.3);
      } else if (r.state === "ground" && r.y > top) {
        handle(crash(r, [], "rock"));
      }
    }
  }
  for (const a of w.animals) {
    if (a.caught) continue;
    if (Math.abs(a.x - r.x) < 26 && Math.abs(a.y - r.y) < 34) {
      a.caught = true; a.flee = 1; st.goats++;
      trick("Goat caught", 300);
      sound("goat");
    }
  }
}

function updateAnimals(dt) {
  const w = game.world;
  for (const a of w.animals) {
    const speed = a.caught ? a.speed * 1.8 : a.speed;
    a.x += speed * dt;
    const g = w.groundAt(a.x);
    if (g === null) { a.hop = 0.5; a.vy = -500; }
    a.hop = Math.max(0, a.hop - dt);
    a.vy += 1500 * dt;
    a.y += a.vy * dt;
    if (g !== null && a.y >= g) { a.y = g; a.vy = Math.random() < dt * 1.2 ? -380 : 0; if (a.vy) a.hop = 0.3; }
    if (a.caught) { a.flee -= dt; if (a.flee < -2) a.gone = true; }
  }
}

function burst(x, y, n) {
  for (let i = 0; i < n; i++) {
    game.spray.push({ x, y: y - 2, vx: (Math.random() - 0.2) * 260, vy: -Math.random() * 260, life: 0.6 + Math.random() * 0.4 });
  }
}

function update(dt) {
  const s = game.settings;
  game.time += dt;
  if (s.time === "cycle") game.dayT = (game.dayT + dt / (s.day_minutes * 60)) % 1;
  else game.dayT += (TIMES[s.time] - game.dayT) * Math.min(1, dt * 0.5);
  const events = [];
  game.weather.update(dt, s.weather, Math.random, canvas.width, canvas.height, s.density / 100, events);
  if (events.includes("thunder")) sound("thunder");

  if (game.phase !== "playing") return;
  const r = game.rider, w = game.world;
  w.ensure(r.x + canvas.width / game.zoom + 1500);
  w.trim(game.cam.x - 800);

  const before = r.x;
  const ev = step(r, w, game.input, params(), dt);
  game.input.pressed = false;
  handle(ev);
  collide();
  updateAnimals(dt);

  const moved = Math.max(0, r.x - before) / PX_PER_M;
  if (r.state !== "crashed") {
    game.stats.distance += moved;
    if (mode().scored) game.stats.score += moved;
    if (nightness(skyAt(game.dayT)) > 0.6) game.stats.night_distance += moved;
    if (STORMY.has(game.weather.kind) && game.weather.blend > 0.5) game.stats.storm_distance += moved;
    if (game.flagX && !game.flagPassed && r.x >= game.flagX) {
      game.flagPassed = true;
      popup("Past your best");
      sound("goal", 1.5);
    }
  }
  if (game.combo && (r.state === "ground")) {
    game.comboT -= dt;
    if (game.comboT <= 0) endCombo();
  }

  // the board's groove, and snow thrown up at speed
  if (r.state === "ground") {
    game.trail.push([r.x, r.y]);
    if (Math.random() < r.speed / 3000) game.spray.push({ x: r.x - 18, y: r.y, vx: -60 - Math.random() * 80, vy: -40 - Math.random() * 80, life: 0.5 });
  } else if (game.trail.length && game.trail[game.trail.length - 1]) game.trail.push(null);
  if (game.trail.length > 240) game.trail.splice(0, game.trail.length - 240);
  for (const p of game.spray) { p.vy += 900 * dt; p.x += p.vx * dt; p.y += p.vy * dt; p.life -= dt * 1.4; }
  game.spray = game.spray.filter((p) => p.life > 0);

  // the scarf: each link chases the one before it, and the wind pulls it back
  const anchor = R.scarfAnchor(r, game.shapes.rider);
  if (!game.scarf.length) game.scarf = Array.from({ length: 7 }, () => anchor.slice());
  game.scarf[0] = anchor;
  const wind = game.weather.mixed.wind;
  for (let i = 1; i < game.scarf.length; i++) {
    const p = game.scarf[i], q = game.scarf[i - 1];
    p[0] -= (40 + r.speed * 0.02 - wind * 0.02) * dt;
    p[1] += Math.sin(game.time * 12 + i) * 0.8;
    const dx = p[0] - q[0], dy = p[1] - q[1], d = Math.hypot(dx, dy) || 1, want = 6;
    p[0] = q[0] + (dx / d) * want; p[1] = q[1] + (dy / d) * want;
  }

  // goals
  if (mode().goals) {
    for (const key of newlyMet(game.levels, game.level, game.stats, game.save.done)) {
      game.save.done[key] = true;
      game.metThisRun.push(key);
      const [li, gi] = key.split(":").map(Number);
      popup(`Goal: ${game.levels[li].goals[gi].text}`);
      sound("goal");
      persist();
    }
  }

  if (game.over > 0) {
    game.over -= dt;
    if (game.over <= 0) finishRun();
  } else if (game.over < 0) {
    game.over += dt;
    if (game.over >= 0) { recover(r, w); game.scarf = []; game.over = 0; }
  }
  hud();
}

function finishRun() {
  const st = game.stats, sv = game.save;
  sv.runs = (sv.runs || 0) + 1;
  const newBest = st.score > (sv.best.score || 0);
  sv.best.score = Math.max(sv.best.score || 0, Math.floor(st.score));
  sv.best.distance = Math.max(sv.best.distance || 0, Math.floor(st.distance));
  const m = mode();
  const dayBest = m.record ? m.record(sv, game.day, st) : false;
  const before = game.level;
  const after = currentLevel(game.levels, sv.done);
  persist();
  const end = overTitle({ saveRead, levelDone: after > before, levelName: game.levels[before]?.name, newBest, dayBest });
  $("over-title").textContent = end.title;
  const rows = [
    ["Distance", `${Math.floor(st.distance).toLocaleString()} m`], ["Score", Math.floor(st.score).toLocaleString()],
    ["Coins", st.coins], ["Backflips", st.flips], ["Best combo", `x${st.combo}`], ["Grind", `${Math.floor(st.grind)} m`],
    ["Goats", st.goats], ["Chasms", st.chasms],
  ];
  $("over-stats").innerHTML = rows.map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join("");
  modeBox($("over-goals"), before, game.day, game.metThisRun);
  setPhase("over");
  if (end.cheer) sound("goal", 1.25);
}

function goalList(box, li, fresh = []) {
  box.textContent = "";
  const level = game.levels[li];
  if (!level) return;
  const head = document.createElement("div");
  head.className = "level-name";
  head.textContent = level.name;
  box.appendChild(head);
  level.goals.forEach((goal, gi) => {
    const key = goalKey(li, gi);
    const row = document.createElement("div");
    row.className = "goal" + (game.save.done[key] ? " done" : "") + (fresh.includes(key) ? " fresh" : "");
    const tick = document.createElement("span"); tick.className = "tick";
    const text = document.createElement("span"); text.textContent = goal.text;
    const prog = document.createElement("span"); prog.className = "prog";
    prog.textContent = game.save.done[key] ? "done" : game.phase === "over" ? progressText(goal, game.stats) : "";
    row.append(tick, text, prog);
    box.appendChild(row);
  });
}

// The mode buttons, one per entry in MODES
function buildModes() {
  const box = document.querySelector(".modes");
  box.textContent = "";
  for (const [key, m] of Object.entries(MODES)) {
    const b = document.createElement("button");
    b.className = "mode";
    b.dataset.mode = key;
    b.textContent = m.label;
    b.setAttribute("role", "radio");
    b.addEventListener("click", () => {
      game.mode = key;
      game.save.mode = key; // the title opens on the last way you rode
      persist();
      renderTitle();
    });
    box.appendChild(b);
  }
}

// Under the mode buttons and under a finished run's numbers: the level goals
// for a mode that counts them, otherwise the mode's own summary line
function modeBox(box, li, day, fresh = []) {
  const m = mode();
  if (m.goals) return goalList(box, li, fresh);
  box.textContent = "";
  if (!m.summary) return;
  const row = document.createElement("div");
  row.className = "goal summary";
  row.textContent = m.summary(game.save, day);
  box.appendChild(row);
}

function renderTitle() {
  document.querySelectorAll(".mode").forEach((b) => {
    const on = b.dataset.mode === game.mode;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", String(on));
  });
  $("mode-help").textContent = mode().help;
  modeBox($("goals-box"), currentLevel(game.levels, game.save.done), todayKey());
  const b = game.save.best;
  $("bests").textContent = `Best ${Math.floor(b.distance || 0).toLocaleString()} m · ${Math.floor(b.score || 0).toLocaleString()} points · ${game.save.coins || 0} coins`;
}

let hudLast = 0;
function hud() {
  if (game.time - hudLast < 0.1) return;
  hudLast = game.time;
  const st = game.stats, zen = !mode().scored;
  $("hud-dist").textContent = `${Math.floor(st.distance).toLocaleString()} m`;
  $("hud-score").textContent = zen ? "" : Math.floor(st.score).toLocaleString();
  $("hud-coins").textContent = st.coins;
  $("combo").textContent = game.combo >= 2 ? `x${game.combo} combo` : "";
}

// --- the camera and a frame ---------------------------------------------------

function camera(dt) {
  const W = canvas.width, H = canvas.height, r = game.rider;
  const base = (H / 560) * (game.settings.zoom / 100);
  let zoom = base;
  if (r && game.world) {
    const g = game.world.groundAt(r.x);
    const height = g === null ? 200 : Math.max(0, g - r.y);
    zoom = base * Math.max(0.62, 1 - height / 1400);
    const tx = r.x - (W * 0.33) / game.zoom;
    const ty = r.y - (H * 0.08) / game.zoom + Math.min(200, height * 0.3);
    game.cam.x += (tx - game.cam.x) * Math.min(1, dt * 8);
    game.cam.y += (ty - game.cam.y) * Math.min(1, dt * 4);
  } else {
    game.cam.x += 60 * dt; // the title screen drifts past the mountains
  }
  game.zoom += (zoom - game.zoom) * Math.min(1, dt * 2);
}

function draw() {
  const W = canvas.width, H = canvas.height, s = game.settings;
  const sky = skyAt(game.dayT);
  const wx = game.weather.mixed;
  const [accent, accent2] = accents();
  const strength = s.strength / 100;
  const state = {
    sky, night: nightness(sky), dayT: game.dayT, time: game.time, cam: game.cam, zoom: game.zoom,
    accent, accent2, strength, weather: wx, aurora: s.aurora,
    roles: resolveRoles(sky, accent, accent2, strength, wx.overcast),
  };
  ctx.save();
  if (game.shake > 0 && s.shake) ctx.translate((Math.random() - 0.5) * 12 * game.shake, (Math.random() - 0.5) * 12 * game.shake);
  R.drawSky(ctx, W, H, state);
  R.drawRanges(ctx, W, H, state, game.shapes, s.quality);
  if (game.world) {
    R.drawItems(ctx, H, state, game.world, game.shapes, "back");
    R.drawGround(ctx, W, H, state, game.world);
    R.drawTrail(ctx, H, state, game.trail);
    R.drawRopes(ctx, H, state, game.world);
    R.drawFlag(ctx, H, state, game.world, game.flagX, game.flagLabel);
    R.drawItems(ctx, H, state, game.world, game.shapes, "mid");
    R.drawAnimals(ctx, H, state, game.world, game.shapes);
    R.drawRider(ctx, H, state, game.rider, game.scarf, game.shapes);
    R.drawSpray(ctx, H, state, game.spray);
    R.drawItems(ctx, H, state, game.world, game.shapes, "front");
  }
  game.weather.draw(ctx, W, H, state.roles, state.night);
  ctx.restore();
}

// The frame-rate readout, in Goals and Zen alike: a small dark pill under the
// distance, readable over snow and sky (it used to be pale text over the snow)
function showFps() {
  const el = $("fps");
  el.hidden = !game.settings.fps;
  if (!el.textContent) el.textContent = "… fps";
}

let last = 0, fpsN = 0, fpsT = 0;
function frame(t) {
  const raw = Math.max(0, (t - last) / 1000);
  const dt = Math.min(1 / 30, raw || 1 / 60);
  last = t;
  const running = game.phase !== "pause"; // menus float over the live mountain
  const visible = !document.hidden && (window.ForgeVisible ? ForgeVisible.on : true);
  let drew = false;
  if (running && visible) {
    update(dt);
    camera(dt);
    game.shake = Math.max(0, game.shake - dt);
    const t0 = performance.now();
    draw();
    game.drawMs += (performance.now() - t0 - game.drawMs) * 0.1;
    drew = true;
  } else if (visible && game.repaint) {
    draw(); // paused: a resize cleared the canvas, so the still frame is drawn again
    drew = true;
  }
  if (drew) {
    game.repaint = false;
    if (!document.body.dataset.painted) document.body.dataset.painted = "1"; // the canvas fades in on its first picture
  }
  // the real time between frames, not the capped step: capped, anything
  // under 30 fps was reported as 30
  if (game.settings.fps && raw < 1) {
    fpsN++; fpsT += raw;
    document.body.dataset.drawMs = game.drawMs.toFixed(1);
    if (fpsT > 0.5) { $("fps").textContent = `${Math.round(fpsN / fpsT)} fps · ${game.drawMs.toFixed(1)} ms to draw`; fpsN = 0; fpsT = 0; }
  }
  requestAnimationFrame(frame);
}

// Setting a canvas's size wipes it, so only a real change does, and a paused
// game draws its still frame again on the next frame (game.repaint)
function resize() {
  const dpr = Math.min(2, devicePixelRatio || 1) * (game.settings.quality === "low" ? 0.75 : 1);
  const w = Math.round(innerWidth * dpr), h = Math.round(innerHeight * dpr);
  if (canvas.width === w && canvas.height === h) return;
  canvas.width = w;
  canvas.height = h;
  game.repaint = true;
}

// --- input -----------------------------------------------------------------

function press() {
  if (game.phase === "playing") { game.input.pressed = true; game.input.held = true; }
}
function release() { game.input.held = false; }

addEventListener("keydown", (e) => {
  if (e.target.closest && e.target.closest("input, textarea, select")) return;
  if (e.code === "Space" || e.code === "ArrowUp" || e.code === "KeyW") {
    e.preventDefault();
    if (e.repeat) return;
    if (game.phase === "title" || game.phase === "over") start();
    else if (game.phase === "pause") setPhase("playing");
    else press();
  } else if (e.code === "Escape" || e.code === "KeyP") {
    if (game.phase === "playing") setPhase("pause");
    else if (game.phase === "pause") setPhase("playing");
    else if (game.phase === "settings" || game.phase === "art") setPhase("title");
  }
});
addEventListener("keyup", (e) => {
  if (e.code === "Space" || e.code === "ArrowUp" || e.code === "KeyW") release();
});
canvas.addEventListener("pointerdown", (e) => { e.preventDefault(); press(); });
addEventListener("pointerup", release);
addEventListener("blur", () => { release(); if (game.phase === "playing") setPhase("pause"); });
document.addEventListener("forge-visible", (e) => {
  if (!e.detail.visible) { if (game.phase === "playing") setPhase("pause"); rest(); }
  else onShown();
});
document.addEventListener("visibilitychange", () => (document.hidden ? rest() : onShown()));
// out of sight the sound effects' audio device is let go; the next effect
// wakes it again (see sound())
function rest() {
  if (audio.ctx && audio.ctx.state === "running") audio.ctx.suspend().catch(() => {});
}

// --- menus -----------------------------------------------------------------

buildModes();
$("play-btn").addEventListener("click", start);
$("again-btn").addEventListener("click", start);
$("menu-btn").addEventListener("click", () => { game.world = null; setPhase("title"); });
$("pause-btn").addEventListener("click", () => setPhase("pause"));
$("resume-btn").addEventListener("click", () => setPhase("playing"));
$("quit-btn").addEventListener("click", () => { if (!mode().scored) { game.world = null; setPhase("title"); } else finishRun(); });

function openSettings() {
  const draw = () => buildForm($("settings-form"), game.settings, $("adv-toggle").checked, (k, v) => {
    game.settings[k] = v;
    settingsChanged = true;
    if (k === "quality") resize();
    if (k === "music") music.setVolume(v);
    showFps();
    persist();
  });
  $("adv-toggle").onchange = draw;
  $("reset-btn").onclick = () => {
    game.settings = defaults();
    settingsChanged = true;
    music.setVolume(game.settings.music);
    resize();
    persist();
    draw();
  };
  draw();
  setPhase("settings");
}
$("settings-btn").addEventListener("click", openSettings);
$("settings-close").addEventListener("click", () => setPhase("title"));

// --- the Art editor ------------------------------------------------------------

function artRoles() {
  const [a, b] = accents();
  return resolveRoles(skyAt(0.45), a, b, game.settings.strength / 100, 0);
}

function fitShape(c, shape) {
  const g = c.getContext("2d");
  g.clearRect(0, 0, c.width, c.height);
  if (!shape || !Array.isArray(shape.parts)) return;
  const pts = shape.parts.flatMap((p) => (Array.isArray(p.points) ? p.points : []));
  if (!pts.length) return;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const w = Math.max(...xs) - Math.min(...xs) || 1, h = Math.max(...ys) - Math.min(...ys) || 1;
  const k = Math.min((c.width * 0.8) / w, (c.height * 0.8) / h);
  const cx = c.width / 2 - ((Math.max(...xs) + Math.min(...xs)) / 2) * k;
  const cy = c.height / 2 - ((Math.max(...ys) + Math.min(...ys)) / 2) * k;
  R.drawShape(g, shape, artRoles(), cx, cy, k);
}

let editing = null;
function openArt() {
  const grid = $("art-grid");
  grid.textContent = "";
  $("art-edit").hidden = true;
  grid.hidden = false;
  for (const [id, shape] of Object.entries(game.shapes)) {
    const tile = document.createElement("div");
    tile.className = "art-tile";
    const c = Object.assign(document.createElement("canvas"), { width: 192, height: 144 });
    const name = document.createElement("span");
    name.textContent = shape.label || id;
    tile.append(c, name);
    tile.addEventListener("click", () => editShape(id));
    grid.appendChild(tile);
    fitShape(c, shape);
  }
  setPhase("art");
}

function editShape(id) {
  editing = id;
  const shape = game.shapes[id];
  $("art-grid").hidden = true;
  $("art-edit").hidden = false;
  $("art-name").textContent = shape.label || id;
  const { id: _drop, ...rest } = shape;
  $("art-json").value = JSON.stringify(rest, null, 1);
  $("art-status").textContent = "";
  $("art-roles").textContent = "Colour roles: " + Object.keys(artRoles()).join(", ");
  fitShape($("art-preview"), shape);
}

$("art-json").addEventListener("input", () => {
  try {
    const shape = JSON.parse($("art-json").value);
    fitShape($("art-preview"), shape);
    $("art-status").textContent = "";
  } catch (err) {
    $("art-status").textContent = "Not valid JSON yet: " + err.message;
  }
});
// Save and revert are locked while one is on its way (a double click sends
// one request), and a server that does not answer gets a calm sentence
let artBusy = false;
async function artJob(job) {
  if (artBusy) return;
  artBusy = true;
  const buttons = ["art-save", "art-revert", "art-back"].map($);
  buttons.forEach((b) => (b.disabled = true));
  try {
    await job();
  } catch (err) {
    $("art-status").textContent = "The game's server is not answering, so nothing changed. Try again in a moment.";
  } finally {
    artBusy = false;
    buttons.forEach((b) => (b.disabled = false));
  }
}
$("art-save").addEventListener("click", () => artJob(async () => {
  let shape;
  try { shape = JSON.parse($("art-json").value); } catch (err) { $("art-status").textContent = "Not valid JSON: " + err.message; return; }
  const id = editing;
  $("art-status").textContent = "Saving…";
  const res = await fetch(`api/shapes/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(shape) });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) { $("art-status").textContent = "Not saved: " + (body.detail || res.status); return; }
  game.shapes[id] = { ...shape, id };
  $("art-status").textContent = "Saved. The game uses it from the next run.";
}));
$("art-revert").addEventListener("click", () => artJob(async () => {
  const id = editing;
  const res = await fetch(`api/shapes/${id}`, { method: "DELETE" });
  if (!res.ok) { $("art-status").textContent = "Could not put it back."; return; }
  await loadShapes();
  editShape(id);
  $("art-status").textContent = "The original is back.";
}));
$("art-back").addEventListener("click", openArt);
$("art-btn").addEventListener("click", openArt);
$("art-close").addEventListener("click", () => setPhase("title"));

// --- boot ------------------------------------------------------------------

async function getJSON(url, fallback) {
  try {
    const r = await fetch(url);
    return r.ok ? await r.json() : fallback;
  } catch (err) {
    return fallback;
  }
}

async function loadShapes() {
  const body = await getJSON("api/shapes", { shapes: {} });
  game.shapes = body.shapes || {};
}

async function boot() {
  resize();
  addEventListener("resize", resize);
  const [, levels, saved, sounds] = await Promise.all([
    loadShapes(), getJSON("api/levels", { levels: [] }), fetchSave(), getJSON("api/sounds", { sounds: [] }),
  ]);
  game.levels = levels.levels || [];
  if (saved) takeSave(saved);
  else {
    // the backend is restarting or busy: play on the defaults, write nothing,
    // and read the save again in a moment (see trySave)
    music.setVolume(game.settings.music);
    saveWait = 2000;
    trySave(saveWait);
  }
  for (const snd of sounds.sounds || []) game.sounds[snd.event] = snd;
  showFps();
  game.dayT = game.settings.time === "cycle" ? 0.3 : TIMES[game.settings.time];
  // the title screen rides a mountain of its own, with nobody on it
  game.world = null;
  setPhase("title");
  // #ride / #zen / #daily start straight away: a link into a run, and the browser check
  const linked = modeFromLink(location.hash);
  if (linked) { game.mode = linked; start(); }
  else if (location.hash === "#art") openArt();
  else if (location.hash === "#settings") openSettings();
  document.body.dataset.ready = "1";
  document.body.dataset.shapes = String(Object.keys(game.shapes).length);
  requestAnimationFrame(frame);
}

window.driftpeaks = game; // for the browser checks and for poking at in devtools
boot();
