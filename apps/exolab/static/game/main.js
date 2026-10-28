// Exo Lab game, first pass: boots the stats, the test range, the soldier and
// the HUD, reads the keyboard, mouse and gamepad, and runs the fixed-step sim.
// The pad's bindings live in game/controls.json (read through pad.js).
// URL: game.html?model=<id>&profile=<name>[&demo=1&speed=<x>]

import * as THREE from "three";
import { STEP, createSim, step } from "./sim.js";
import { bestKey, loadBest, saveBest } from "./records.js";
import { testRange } from "./level.js";
import { rayBoxes } from "./physics.js";
import { View } from "./view.js";
import { Hud } from "./hud.js";
import { loadCharacter } from "./character.js";
import { runDemo } from "./demo.js";
import { choosePad, createPad, layoutFor, labelsFor, listPads, lockMenu, menuMove, padHelp, rumbleFor, stepPad } from "./pad.js";

const params = new URLSearchParams(location.search);
const MODEL = params.get("model") || "exo_full";
const PROFILE = params.get("profile") || "baseline";
const DEMO = params.get("demo") === "1";
const DEMO_SPEED = Math.max(0.25, Number(params.get("speed") || 1));
const $ = (sel) => document.querySelector(sel);
const status = (t) => ($("#loading p").textContent = t);
const notes = [];

// Capture the mouse for mouse look. The browser may refuse (no real click
// behind the call, as with a pad press on the menu, or a frame without the
// permission): play goes on, and a click on the view asks again.
function lockMouse(canvas) {
  try {
    const asked = canvas.requestPointerLock?.();
    if (asked && typeof asked.catch === "function") asked.catch(() => {});
  } catch {
    // older engines throw instead of rejecting: the same refusal
  }
}

// The page's localStorage, or null where the browser refuses it.
function recordStore() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

// Fill any field the API left out from the stub, so one missing number
// cannot turn into NaN in the sim; say which ones.
function fillFrom(dst, src, path, missing) {
  for (const [k, v] of Object.entries(src)) {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      if (!dst[k] || typeof dst[k] !== "object") dst[k] = {};
      fillFrom(dst[k], v, `${path}${k}.`, missing);
    } else if (typeof v === "number" && typeof dst[k] !== "number") {
      dst[k] = v;
      missing.push(path + k);
    }
  }
}

async function loadStats() {
  const stub = await getJSON("game/stub.json");
  const q = `?profile=${encodeURIComponent(PROFILE)}`;
  const derive = async (model) => {
    const r = await fetch(`/api/derive/${encodeURIComponent(model)}${q}`);
    if (r.ok) return { stats: await r.json() };
    let why = `HTTP ${r.status}`;
    try {
      const body = await r.json();
      if (body && body.detail) why = String(body.detail);
    } catch {
      // no JSON body: keep the status
    }
    return { why, client: r.status >= 400 && r.status < 500 };
  };
  let got;
  try {
    got = await derive(MODEL);
    if (!got.stats && got.client && MODEL !== stub.model) {
      notes.push(`${MODEL} cannot be played: ${got.why}. Playing ${stub.model} instead`);
      got = await derive(stub.model);
    }
  } catch (err) {
    got = { why: err.message };
  }
  if (!got.stats) {
    notes.push(`Stats API unreachable (${got.why}); playing with the ${stub.model} stub`);
    return { stats: stub, source: "stub" };
  }
  const missing = [];
  fillFrom(got.stats, stub, "", missing);
  if (missing.length) notes.push(`Missing from the derive, taken from the stub: ${missing.join(", ")}`);
  return { stats: got.stats, source: "api" };
}

async function loadModelInfo(model) {
  const out = { vrm: "/characters/hairsample_female/HairSample_Female.vrm", suit: null };
  let glb = `/assets/suits/${model}.glb`;
  let side = `/assets/suits/${model}.json`;
  try {
    const m = await getJSON(`/api/model/${encodeURIComponent(model)}`);
    if (m.character && m.character.url) out.vrm = m.character.url;
    if (m.suit_asset) {
      glb = m.suit_asset.glb;
      side = m.suit_asset.sidecar;
    }
  } catch (err) {
    notes.push(`Model info unreachable: ${err.message}`);
  }
  if (glb && side) {
    try {
      out.suit = { glbUrl: glb, sidecar: await getJSON(side) };
    } catch {
      out.suit = null;
    }
  }
  return out;
}

// --- input ---------------------------------------------------------------

const input = { wish: [0, 0], yaw: 0, pitch: 0, sprint: false, walk: false, actions: [] };
const held = new Set();
const cam = { yaw: 0, pitch: -0.12, dist: 3.4, pos: new THREE.Vector3(), target: new THREE.Vector3() };
let paused = !DEMO;
let started = false;
const lastTap = {};
const DIRS = { KeyW: [0, 1], KeyS: [0, -1], KeyA: [-1, 0], KeyD: [1, 0] };
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);

// Gamepad: `controls` is controls.json (null if it did not load), `padIn`
// the pad's frame while playing, `device` what the HUD names keys for.
let controls = null;
const padState = createPad();
let padIn = null;
let device = "keys";
let menuIdx = -1;
let hud = null;
// `padBlocked` is why the page may not read pads (null = it may); `front` is
// false while Forge's hub has another app in front.
let padBlocked = null;
let front = true;
// When the pad was last used (performance.now() ms), for pad.mouse_quiet_s.
let lastPadT = -Infinity;

function camDir(fwd, right) {
  const fx = Math.sin(cam.yaw);
  const fz = Math.cos(cam.yaw);
  // Right of a soldier facing (fx, fz) is (-fz, fx) in x, z (+X is left).
  return [fx * fwd - fz * right, fz * fwd + fx * right];
}

function readKeys() {
  let f = 0;
  let r = 0;
  if (held.has("KeyW") || held.has("ArrowUp")) f += 1;
  if (held.has("KeyS") || held.has("ArrowDown")) f -= 1;
  if (held.has("KeyD") || held.has("ArrowRight")) r += 1;
  if (held.has("KeyA") || held.has("ArrowLeft")) r -= 1;
  const n = Math.hypot(f, r) || 1;
  f /= n;
  r /= n;
  // No movement key down: the left stick moves, keeping how far it is tilted.
  if (f === 0 && r === 0 && padIn) [r, f] = padIn.move;
  input.wish = camDir(f, r);
  input.sprint = held.has("ShiftLeft") || held.has("ShiftRight") || !!(padIn && padIn.sprint);
  input.walk = held.has("AltLeft") || held.has("AltRight") || !!(padIn && padIn.walk);
  input.yaw = cam.yaw;
  input.pitch = cam.pitch;
}

function bindInput(canvas) {
  const onKey = (e) => {
    if (DEMO) return;
    useDevice("keys");
    if (e.code === "Escape") {
      setPaused(!paused);
      return;
    }
    if (paused) return;
    // Ctrl is the slide key, so Ctrl+W and friends must not reach the browser.
    if (e.ctrlKey || ["Space", "AltLeft", "AltRight", "ControlLeft", "Tab"].includes(e.code)) e.preventDefault();
    if (e.repeat) return;
    held.add(e.code);
    const c = e.code;
    if (c === "Space") input.actions.push({ type: "jump" });
    else if (c === "KeyQ") input.actions.push({ type: "dash" });
    else if (c === "ControlLeft" || c === "ControlRight" || c === "KeyC") input.actions.push({ type: "crouch" });
    else if (c === "KeyE") input.actions.push({ type: "use" });
    else if (c === "KeyR") input.actions.push({ type: "repair" });
    else if (c === "KeyF") input.actions.push({ type: "punch" });
    else if (c === "Backspace") input.actions.push({ type: "respawn" });
    else if (/^Digit[1-4]$/.test(c)) {
      const mode = ["armour", "strength", "speed", "cloak"][Number(c.slice(5)) - 1];
      input.actions.push({ type: "mode", mode });
    }
    if (DIRS[c]) {
      const now = performance.now();
      if (lastTap[c] && now - lastTap[c] < 250) {
        input.actions.push({ type: "dash", dir: camDir(DIRS[c][1], DIRS[c][0]) });
        lastTap[c] = 0;
      } else lastTap[c] = now;
    }
  };
  window.addEventListener("keydown", onKey);
  // Alt is walk and F is punch, but the shared Forge script takes Alt+F for
  // full screen. While playing, the game takes Alt+F first and stops it there.
  window.addEventListener(
    "keydown",
    (e) => {
      if (DEMO || paused || !e.altKey || e.code !== "KeyF") return;
      e.stopImmediatePropagation();
      onKey(e);
    },
    true,
  );
  window.addEventListener("keyup", (e) => held.delete(e.code));
  window.addEventListener("blur", padAway);
  window.addEventListener("focus", padBack);
  canvas.addEventListener("mousedown", (e) => {
    if (DEMO) return;
    if (paused) return;
    // The DualSense touchpad is also a desktop touchpad, and brushing it must
    // not punch or take the pointer: a click within pad.mouse_quiet_s of a
    // pad button or firm stick does nothing, and the first click after pad
    // play only hands the controls back to the mouse (also with a stick that
    // drifts past the deadzone, which a gentle walk looks just like).
    if (padQuiet()) return;
    const fromPad = device === "pad";
    useDevice("keys");
    if (fromPad) return;
    if (document.pointerLockElement !== canvas) lockMouse(canvas);
    if (e.button === 0) input.actions.push({ type: "punch" });
  });
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  window.addEventListener("mousemove", (e) => {
    if (paused || DEMO) return;
    const locked = document.pointerLockElement === canvas;
    if (!locked && !(e.buttons & 2)) return;
    // While the pad is in use the mouse does not turn the camera: a brush
    // of the touchpad would. A click hands the controls back first.
    if (padQuiet() || device === "pad") return;
    cam.yaw -= e.movementX * 0.0025;
    cam.pitch = Math.max(-0.9, Math.min(0.6, cam.pitch - e.movementY * 0.0022));
  });
  document.addEventListener("pointerlockchange", () => {
    if (document.pointerLockElement !== canvas && started && !paused) setPaused(true);
  });
  $("#resume").addEventListener("click", () => {
    setPaused(false);
    lockMouse(canvas);
  });
  // Restart in place: the sim resets the range on its next step, with no
  // page reload (the suit, the soldier and the best lap stay loaded).
  $("#restart").addEventListener("click", () => {
    input.actions.push({ type: "restart" });
    setPaused(false);
    lockMouse(canvas);
  });
  // A real click on the pause menu right after pad input (the touchpad
  // again) clicks nothing; the pad's own presses are el.click(), not real
  // clicks, and a click the keyboard makes (Enter or Space, detail 0) is
  // not the touchpad: both go through.
  $("#pause").addEventListener(
    "click",
    (e) => {
      if (!e.isTrusted || !e.detail || !padQuiet()) return;
      e.stopPropagation();
      e.preventDefault();
    },
    true,
  );
}

// The window lost focus (its own blur, or Forge's window as the hub tells
// it): keys are let go, and pad play (the pad is the device in use, or its
// stick is moving the soldier) stops at the menu, which takes no direction
// until it is let go. An unfocused window gets no new pad state, so the last
// one would otherwise play on.
function padAway() {
  held.clear();
  lockMenu(padState);
  if ((device === "pad" || padMoving()) && started && !paused) setPaused(true);
}

// The window has focus again: what it saw of the pad while away may have
// been frozen, so the menu waits for the stick to be seen resting again (a
// stick already held on the way back moves nothing).
function padBack() {
  lockMenu(padState, true);
}

// The pad's sticks are moving the soldier or the camera (past the deadzone).
function padMoving() {
  return !!padIn && (padIn.move.some(Boolean) || padIn.look.some(Boolean));
}

// True for pad.mouse_quiet_s after the last pad input.
function padQuiet() {
  const quiet = controls ? Number(controls.pad.mouse_quiet_s) || 0 : 0;
  return performance.now() - lastPadT < quiet * 1000;
}

function setPaused(on) {
  paused = on;
  started = true;
  $("#pause").hidden = !on;
  held.clear();
  padIn = null;
  if (on && document.pointerLockElement) document.exitPointerLock();
  if (on) padLine();
  else focusMenu(null);
}

// --- gamepad -------------------------------------------------------------

// Every pad the page can see. Once getGamepads() has been refused (an iframe
// the hub has not allowed the pad) it is not asked again.
function gamepads() {
  if (padBlocked) return [];
  const { pads, blocked } = listPads(navigator);
  padBlocked = blocked;
  return pads;
}

// The pad the game reads (the one in use, not just the first slot), or null.
// Once a frame, by pollPad: it moves padState on to that pad and tells a loss.
function activePad() {
  return choosePad(gamepads(), controls, padState);
}

// The pad activePad() would read, for the menu line and rumble: it leaves
// padState alone, so a disconnect event before the frame does not hide the
// loss from pollPad.
function peekPad() {
  return choosePad(gamepads(), controls, { padIndex: padState.padIndex });
}

function useDevice(d) {
  if (d === device || !hud) return;
  device = d;
  hud.setLabels(d === "pad" && controls ? labelsFor(controls) : null);
}

const menuItems = () => [...document.querySelectorAll("#pause .buttons > *")];

// Pad focus on the pause menu's buttons (null clears it).
function focusMenu(i) {
  const items = menuItems();
  menuIdx = i == null || !items.length ? -1 : Math.max(0, Math.min(items.length - 1, i));
  items.forEach((el, k) => el.classList.toggle("padfocus", k === menuIdx));
  if (menuIdx >= 0) items[menuIdx].focus({ preventScroll: true });
  else if (document.activeElement && document.activeElement.closest("#pause")) document.activeElement.blur();
}

function menuKey(m) {
  if (m === "prev" || m === "next") focusMenu(menuMove(menuIdx, m, menuItems().length));
  else if (m === "press") {
    const el = menuItems()[Math.max(0, menuIdx)];
    if (!el || el.id === "resume") setPaused(false);
    else el.click();
  } else if (m === "back") setPaused(false);
}

// Once a frame: menu moves while paused; otherwise the sticks, held sprint
// and walk, and one action per press.
function pollPad(dt) {
  // Behind another Forge app the pad is not read (the game is paused there).
  const gp = front ? activePad() : null;
  const lost = front && padState.padLost;
  if (front) padToHub(!!gp);
  const out = stepPad(padState, gp, controls, dt, paused);
  if (out.active) {
    useDevice("pad");
    lastPadT = performance.now();
  }
  if (paused) {
    for (const m of out.menu) menuKey(m);
    return;
  }
  if (out.pause) {
    setPaused(true);
    focusMenu(0);
    return;
  }
  // A pad lost in pad play (battery, Bluetooth) pauses, as a console does,
  // also when another pad is left connected.
  if ((!gp || lost) && padIn && device === "pad") {
    setPaused(true);
    return;
  }
  padIn = gp ? out : null;
  input.actions.push(...out.actions);
  cam.yaw -= out.look[0];
  cam.pitch = Math.max(-0.9, Math.min(0.6, cam.pitch - out.look[1]));
}

// Tell Forge whether this page reads the pad itself: while it does, Forge
// keeps shared/pad (the pad as mouse and keys) quiet, so Circle is not also
// Esc, the d-pad the arrow keys and Cross a click. Only while a pad is seen,
// so the service still drives the page when the page cannot see the pad.
// Posted to the parent even at the top level: the hub hears it in Forge's
// window, forge_popout's script in a pop-out; a plain tab ignores it.
let padNative = false;
function padToHub(native) {
  if (native === padNative) return;
  padNative = native;
  window.parent.postMessage({ forge: "pad", native }, "*");
}

function rumble(e) {
  const fx = controls && rumbleFor(controls, e);
  const act = fx ? peekPad()?.vibrationActuator : null;
  if (act && act.playEffect) act.playEffect("dual-rumble", fx).catch(() => {});
}

// The pause menu's controller line: what the page can see right now.
function padLine() {
  const el = $("#padline");
  if (!el) return;
  if (!controls) {
    el.textContent = "The controller bindings did not load, so the pad is off this time.";
    return;
  }
  const N = controls.names;
  const gp = peekPad();
  const any = gamepads();
  if (padBlocked)
    el.textContent = `The controller cannot be read in this window (${padBlocked}). In Forge, close and reopen Forge once; or open the game in a browser tab.`;
  else if (gp)
    el.textContent = `Controller: ${gp.id}. ${N[controls.menu.press[0]]} picks, ${controls.menu.back.map((b) => N[b]).join(" or ")} goes back to the game.`;
  else if (any.length)
    el.textContent = `A controller is connected but its layout is not known here: ${any[0].id} (mapping "${any[0].mapping}").`;
  else
    el.textContent =
      "No controller in use. Plug the DualSense in with a USB-C cable or pair it over Bluetooth, then press a d-pad arrow on it: the page only sees a pad after a press, and in Forge an arrow is the one press that does nothing else.";
}

function bindPad(sim) {
  const say = (text) => {
    sim.messages.push({ t: sim.t, text: esc(text), kind: "info" });
    if (sim.messages.length > 6) sim.messages.shift();
  };
  // Forge's hub says which app is in front (behind another one the game
  // pauses and stops reading the pad) and when Forge's window loses or gets
  // back focus.
  window.addEventListener("message", (e) => {
    if (e.source !== window.parent || !e.data) return;
    if (e.data.forge === "visible") {
      front = e.data.visible !== false;
      if (!front && started && !paused) setPaused(true);
    } else if (e.data.forge === "focus") {
      if (e.data.focused === false) padAway();
      else padBack();
    }
  });
  window.addEventListener("pagehide", () => padToHub(false));
  // An error may have stopped the frame loop, and with it the pad: Forge
  // takes the pad back until a live frame claims it again.
  window.addEventListener("error", () => padToHub(false));
  window.addEventListener("gamepadconnected", (e) => {
    const ok = controls && layoutFor(e.gamepad, controls);
    say(ok ? `Controller connected: ${e.gamepad.id}` : `Controller ${e.gamepad.id} has no known layout; keyboard and mouse only`);
    padLine();
  });
  window.addEventListener("gamepaddisconnected", (e) => {
    say(`Controller disconnected: ${e.gamepad.id}`);
    padLine();
  });
  if (controls)
    $("#padkeys").innerHTML = padHelp(controls)
      .map(([b, d]) => `<div><b>${esc(b)}</b> ${esc(d)}</div>`)
      .join("");
  padLine();
}

// --- camera --------------------------------------------------------------

function updateCamera(view, sim, dt) {
  const p = sim.player;
  const fx = Math.sin(cam.yaw);
  const fz = Math.cos(cam.yaw);
  const eyeY = p.y + (p.sliding ? 1.0 : 1.5);
  const want = new THREE.Vector3(p.x - fz * 0.45, eyeY, p.z + fx * 0.45);
  cam.target.lerp(want, Math.min(1, dt * 18));
  if (cam.target.distanceTo(want) > 3) cam.target.copy(want);
  const dir = [fx * Math.cos(cam.pitch), Math.sin(cam.pitch), fz * Math.cos(cam.pitch)];
  const back = [-dir[0], -dir[1], -dir[2]];
  const o = [cam.target.x, cam.target.y, cam.target.z];
  const boxes = sim.statics.filter((b) => b.kind !== "ground").concat(sim.walls.filter((w) => w.intact));
  const hit = rayBoxes(o, back, boxes, cam.dist);
  const d = Math.max(0.6, Math.min(cam.dist, hit - 0.2));
  view.camera.position.set(o[0] + back[0] * d, Math.max(0.25, o[1] + back[1] * d), o[2] + back[2] * d);
  view.camera.lookAt(o[0] + dir[0] * 10, o[1] + dir[1] * 10, o[2] + dir[2] * 10);
}

// --- boot ----------------------------------------------------------------

async function boot() {
  status("Loading the suit's derived stats...");
  const { stats, source } = await loadStats();
  try {
    controls = await getJSON("game/controls.json");
  } catch (err) {
    notes.push(`Controller bindings not loaded (${err.message}); keyboard and mouse only`);
  }
  const level = testRange();
  const sim = createSim(stats, level);
  // The best lap for this suit and profile, kept between visits (not for the
  // stub, whose numbers are not the tester's, nor for the scripted demo).
  const records = !DEMO && source === "api" ? recordStore() : null;
  const recordKey = bestKey(stats.model || MODEL, PROFILE);
  if (records) sim.lap.best = loadBest(records, recordKey);
  const canvas = $("#view");
  const view = new View(canvas, sim);
  hud = new Hud(stats, source);
  cam.yaw = level.spawn.yaw;
  bindInput(canvas);
  if (!DEMO) bindPad(sim);

  status("Loading the soldier...");
  const info = await loadModelInfo(stats.model || MODEL);
  let character = null;
  try {
    character = await loadCharacter(info.vrm, info.suit, (t) => notes.push(t));
    view.add(character.root);
  } catch (err) {
    notes.push(`Character not loaded: ${err.message}`);
  }
  await Promise.race([Promise.allSettled(view.loads), new Promise((r) => setTimeout(r, 8000))]);
  $("#loading").hidden = true;
  $("#pause").hidden = DEMO;
  $("#notes").textContent = notes.join(" · ");

  let pending = null;
  let acc = 0;
  let last = performance.now();
  const fps = { n: 0, t: 0, ms: 0 };
  const game = {
    sim,
    input,
    source,
    stats,
    character: character ? character.info : null,
    soldier: character,
    notes,
    fps,
    cam,
    run(sec, perStep) {
      return new Promise((resolve) => {
        pending = { steps: Math.max(1, Math.round(sec / STEP)), perStep, resolve };
      });
    },
    lookAt(yaw) {
      cam.yaw = yaw;
    },
    demoPanel(checks, ok) {
      const el = $("#demo");
      el.hidden = false;
      const head = ok == null ? "Demo running..." : ok ? "Demo: all checks pass" : "Demo: some checks fail";
      el.innerHTML =
        `<h3 class="${ok == null ? "" : ok ? "good" : "bad"}">${head}</h3>` +
        checks
          .map((c) => {
            const got = typeof c.got === "number" ? c.got.toFixed(2) : c.got;
            const want = typeof c.want === "number" ? c.want.toFixed(2) : c.want;
            return `<div class="${c.ok ? "good" : "bad"}"><b>${c.ok ? "pass" : "fail"}</b> ${c.name}: ${got} (want ${want}) <small>${c.note || ""}</small></div>`;
          })
          .join("");
    },
  };
  window.__exoGame = game;

  function frame(now) {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    if (!DEMO && controls) pollPad(dt);
    let simDt = 0;
    if (DEMO) {
      if (pending) {
        let n = Math.max(1, Math.floor((dt * DEMO_SPEED) / STEP));
        n = Math.min(n, pending.steps);
        for (let i = 0; i < n; i++) {
          if (pending.perStep) pending.perStep();
          step(sim, input);
          simDt += STEP;
        }
        pending.steps -= n;
        if (pending.steps <= 0) {
          const done = pending.resolve;
          pending = null;
          done();
        }
      }
    } else if (!paused) {
      acc += dt;
      readKeys();
      while (acc >= STEP) {
        step(sim, input);
        acc -= STEP;
        simDt += STEP;
      }
    }
    for (const e of sim.events.splice(0)) {
      if (e.type === "lap" && records) saveBest(records, recordKey, e.time);
      view.onEvent(e);
      if (game.onEvent) game.onEvent(e);
      if (device === "pad") rumble(e);
    }
    if (character) character.update(sim.player, stats, sim.t, simDt);
    view.update(simDt, sim.player);
    if (!DEMO || simDt > 0) updateCamera(view, sim, Math.max(simDt, dt));
    hud.update(sim);
    view.render();
    fps.n += 1;
    fps.t += dt;
    if (fps.t >= 1) {
      fps.ms = (fps.t / fps.n) * 1000;
      $("#fps").textContent = `${(fps.n / fps.t).toFixed(0)} fps`;
      fps.n = 0;
      fps.t = 0;
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  if (DEMO) {
    game.demoPanel([]);
    runDemo(game).catch((err) => {
      window.__exoDemo = { ok: false, checks: [], error: String(err && err.stack ? err.stack : err) };
      $("#demo").textContent = `Demo error: ${err}`;
    });
  }
}

boot().catch((err) => {
  status(`Could not start: ${err.message}`);
  window.__exoDemo = { ok: false, checks: [], error: String(err) };
});
