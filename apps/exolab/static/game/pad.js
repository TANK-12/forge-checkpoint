// Gamepad mapping for the game, kept free of the DOM so node can test it with
// fake pads (tests/js/pad_map.mjs). The bindings live in controls.json; this
// file only knows how to read them.
//
// stepPad(state, gamepad, controls, dt, paused) is called once a frame and
// returns what the game should do: move and look amounts, held sprint/walk,
// one action per button press (never repeated while the button stays down),
// the pause press, and menu moves while paused.

// The layout a pad uses, from controls.layouts: the first whose `when`
// matches the pad's mapping and, if given, its id. null = not usable.
export function layoutFor(gp, reg) {
  if (!gp || gp.connected === false || !Array.isArray(reg.layouts)) return null;
  for (const lay of reg.layouts) {
    const w = lay.when || {};
    if (w.mapping != null && (gp.mapping || "") !== w.mapping) continue;
    if (w.id && !new RegExp(w.id, "i").test(gp.id || "")) continue;
    return lay;
  }
  return null;
}

// The pads the page can see. getGamepads() may throw a SecurityError where
// the page is not allowed a pad (the spec's permissions policy: an iframe
// without allow="gamepad"); that comes back as `blocked`, so the game can say
// why and go on with keyboard and mouse.
export function listPads(nav) {
  if (!nav || typeof nav.getGamepads !== "function") return { pads: [], blocked: "this browser has no Gamepad API" };
  try {
    return { pads: [...(nav.getGamepads() || [])].filter(Boolean), blocked: null };
  } catch (err) {
    return { pads: [], blocked: String((err && err.message) || err || "refused") };
  }
}

// A radial deadzone: inside it the stick reads [0, 0]; outside, the length is
// rescaled so it starts from 0 at the edge and reaches 1 at full tilt.
export function deadzone(x, y, dz) {
  x = Number.isFinite(x) ? x : 0;
  y = Number.isFinite(y) ? y : 0;
  const m = Math.hypot(x, y);
  if (m <= dz) return [0, 0];
  const k = Math.min(1, (m - dz) / (1 - dz)) / m;
  return [x * k, y * k];
}

// The named buttons held down and the raw sticks, read through a layout.
// Buttons in pad.analog (the triggers) count by how far they are pulled:
// down past pad.trigger, and let go only under pad.trigger_release (never
// above pad.trigger), so a finger resting on the line does not press them
// again every frame. `was` is last frame's set.
export function readPad(gp, lay, reg, was = new Set()) {
  const pad = reg.pad;
  const analog = new Set(pad.analog || []);
  const release = Math.min(pad.trigger_release ?? pad.trigger, pad.trigger);
  const down = new Set();
  const buttons = gp.buttons || [];
  const axes = gp.axes || [];
  for (const [name, i] of Object.entries(lay.buttons || {})) {
    const b = buttons[i];
    if (!b) continue;
    const value = Number.isFinite(b.value) ? b.value : b.pressed ? 1 : 0;
    const on = analog.has(name) ? value > (was.has(name) ? release : pad.trigger) : !!b.pressed || value > 0.5;
    if (on) down.add(name);
  }
  if (lay.hat) {
    const hx = axes[lay.hat.x] || 0;
    const hy = axes[lay.hat.y] || 0;
    if (hx < -0.5) down.add("left");
    if (hx > 0.5) down.add("right");
    if (hy < -0.5) down.add("up");
    if (hy > 0.5) down.add("down");
  }
  const ax = (k) => {
    const v = axes[lay.axes[k]];
    return Number.isFinite(v) ? v : 0;
  };
  return { down, left: [ax("lx"), ax("ly")], right: [ax("rx"), ax("ry")] };
}

// A button down or a stick pushed past pad.menu_stick: a pad being used. A
// stick drifting a little past the deadzone does not count.
function busy({ down, left, right }, reg) {
  const firm = reg.pad.menu_stick;
  return down.size > 0 || Math.hypot(...left) > firm || Math.hypot(...right) > firm;
}

// The pad to read out of `pads` (getGamepads() order): the one read last time
// (`st.padIndex`) while it is there, unless it rests and another pad with a
// known layout is being used; else the first being used, else the first with
// a known layout. A second pad, or a virtual one in slot 0, does not take
// over by just being plugged in while this one is read. `st.padLost` says,
// for this call only, that the pad read last time is gone (cable, battery,
// Bluetooth), also when another pad is left to read.
export function choosePad(pads, reg, st) {
  const known = (pads || []).filter((gp) => gp && layoutFor(gp, reg));
  const inUse = (p) => busy(readPad(p, layoutFor(p, reg), reg), reg);
  let gp = known.find((p) => p.index === st.padIndex) || null;
  st.padLost = st.padIndex != null && !gp;
  if (!gp || !inUse(gp)) gp = known.find((p) => p !== gp && inUse(p)) || gp || known[0] || null;
  st.padIndex = gp ? gp.index : null;
  return gp;
}

// The pause menu item a move lands on, out of n: from no focus the first, then
// one step, stopping at the ends. No wrap: a push past Play must not land on
// Back to Exo Lab.
export function menuMove(i, m, n) {
  if (!(n > 0)) return -1;
  if (!(i >= 0 && i < n)) return 0;
  return Math.max(0, Math.min(n - 1, i + (m === "next" ? 1 : m === "prev" ? -1 : 0)));
}

// The menu stick's push and let-go lines: past pad.menu_stick it moves the
// menu, and it keeps counting the way it went down to pad.menu_stick_release.
function menuLines(reg) {
  const firm = reg.pad.menu_stick;
  return [firm, Math.min(reg.pad.menu_stick_release ?? firm, firm)];
}

// The way the menu would move for these inputs: "prev", "next" or null.
// `was` is last frame's way, so a stick resting on the line moves once.
function menuDirOf({ down, left, right }, reg, was) {
  const m = reg.menu;
  const [sx, sy] = m.stick === "right" ? right : left;
  const [firm, release] = menuLines(reg);
  const line = (d) => (d === was ? release : firm);
  if (m.prev.some((n) => down.has(n)) || sy < -line("prev") || sx < -line("prev")) return "prev";
  if (m.next.some((n) => down.has(n)) || sy > line("next") || sx > line("next")) return "next";
  return null;
}

// How far the menu stick is pushed.
function menuStick({ left, right }, reg) {
  const [sx, sy] = reg.menu.stick === "right" ? right : left;
  return Math.hypot(sx, sy);
}

// Nothing moves the menu: no menu direction button is held, and the menu
// stick is inside its let-go line and has rested for pad.menu_rest_s
// (`menuRest`). A stick swinging through the centre in a dodge has not
// rested; a d-pad let go is let go.
function menuFree(read, reg, st) {
  const m = reg.menu;
  const button = [...m.prev, ...m.next].some((n) => read.down.has(n));
  return !button && menuStick(read, reg) < menuLines(reg)[1] && st.menuRest >= (reg.pad.menu_rest_s ?? 0);
}

// `menuLock`: the menu takes no direction until nothing moves it (menuFree).
// Set in play while something does (so the stick a player is still steering
// with when Options opens the menu moves nothing), on the waking press, and
// by main.js through lockMenu() when the window loses focus (a frozen pad)
// or gets it back. `menuRest` is how long the menu stick has rested, counted
// in play too: in play inside the deadzone (a gentle walk is not a rest), on
// the menu inside its let-go line, and only between two frames that both
// found it resting (`menuIn`), so one long frame as it comes in is no rest.
// A pad just seen starts rested (nothing says its stick was moving).
export function createPad() {
  return {
    down: new Set(),
    latch: {},
    rest: 0,
    moveT: 0,
    menuDir: null,
    menuT: 0,
    menuLock: false,
    menuRest: Infinity,
    menuIn: true,
    wake: false,
    padIndex: null,
    padLost: false,
  };
}

// Lock the menu until nothing moves it. `restAgain`: the rest seen so far
// does not count (the window just got focus back, and what it saw while away
// may have been a frozen pad), so the stick must be seen resting again.
export function lockMenu(st, restAgain = false) {
  st.menuLock = true;
  if (restAgain) st.menuIn = false;
}

export function stepPad(st, gp, reg, dt, paused) {
  const out = { move: [0, 0], look: [0, 0], actions: [], menu: [], pause: false, active: false };
  for (const b of reg.bindings) {
    const [kind, arg] = b.do.split(":");
    if (kind === "hold" || kind === "latch") out[arg] = false;
  }
  const lay = layoutFor(gp, reg);
  if (!lay) {
    // No pad: start clean. The press that brings one (back) is a wake-up, not
    // an action: a page sees a pad only after a press, and in Forge the
    // pad-as-mouse service has already acted on that one.
    Object.assign(st, createPad(), { wake: true });
    return out;
  }
  const pad = reg.pad;
  const read = readPad(gp, lay, reg, st.down);
  const { down } = read;
  const dir = menuDirOf(read, reg, st.menuDir);
  if (st.wake) {
    st.wake = false;
    st.down = down;
    lockMenu(st);
  }
  const at = menuStick(read, reg);
  const resting = paused ? at < menuLines(reg)[1] : at <= pad.deadzone;
  st.menuRest = resting ? (st.menuIn ? st.menuRest + dt : 0) : 0;
  st.menuIn = resting;
  const pressed = (name) => down.has(name) && !st.down.has(name);
  // Which stick moves and which looks: controls.sticks, by `do`.
  const stick = (role) => {
    const row = (reg.sticks || []).find((s) => s.do === role);
    const xy = row && read[row.stick];
    return xy ? deadzone(xy[0], xy[1], pad.deadzone) : [0, 0];
  };
  const mv = stick("move");
  const lk = stick("look");
  const moving = mv[0] !== 0 || mv[1] !== 0;
  out.active = busy(read, reg);

  if (paused) {
    // Menu: the d-pad or a firm stick moves to the previous or next item
    // (repeating while held), cross presses, circle or options goes back.
    // While the menu is locked no direction moves it, until nothing does.
    const m = reg.menu;
    if (st.menuLock) {
      if (menuFree(read, reg, st)) st.menuLock = false;
      st.menuDir = dir;
      st.menuT = 0;
    } else if (dir !== st.menuDir) {
      st.menuDir = dir;
      st.menuT = 0;
      if (dir) out.menu.push(dir);
    } else if (dir) {
      st.menuT += dt;
      const [first, every] = pad.menu_repeat_s;
      if (st.menuT >= first) {
        out.menu.push(dir);
        st.menuT -= every;
      }
    }
    if (m.press.some(pressed)) out.menu.push("press");
    if (m.back.some(pressed)) out.menu.push("back");
    st.latch = {};
    st.down = down;
    return out;
  }

  st.menuLock = !menuFree(read, reg, st);
  st.menuDir = dir;
  st.menuT = 0;
  st.rest = moving ? 0 : st.rest + dt;
  st.moveT = moving ? st.moveT + dt : 0;
  const restS = pad.latch_rest_s ?? 0;
  for (const b of reg.bindings) {
    const [kind, arg] = b.do.split(":");
    if (kind === "hold") {
      if (down.has(b.button)) out[arg] = true;
    } else if (kind === "latch") {
      // A press turns it on; it turns it off only after latch_rest_s of
      // moving, so a press after a short stop, or just before the push,
      // always means on.
      if (pressed(b.button)) {
        st.latch[arg] = !(st.latch[arg] && st.moveT >= restS);
        st.rest = 0;
      }
    } else if (pressed(b.button)) {
      if (kind === "pause") out.pause = true;
      else if (kind === "mode") out.actions.push({ type: "mode", mode: arg });
      else out.actions.push({ type: kind });
    }
  }
  // A latched move (sprint) stays on until the move stick has rested for
  // pad.latch_rest_s, like sprint on a console; so a flick through the
  // centre keeps it.
  if (!moving && st.rest >= restS) st.latch = {};
  if (moving) for (const [k, on] of Object.entries(st.latch)) if (on) out[k] = true;

  // Stick up is forward; look is radians to turn this frame, right and down
  // positive, with a curve so small tilts aim finely.
  out.move = [mv[0], -mv[1] || 0];
  const lm = Math.hypot(lk[0], lk[1]);
  if (lm > 0) {
    const k = Math.pow(lm, pad.look_curve) / lm;
    const flip = pad.invert_y ? -1 : 1;
    out.look = [lk[0] * k * pad.look_speed[0] * dt, flip * lk[1] * k * pad.look_speed[1] * dt || 0];
  }
  st.down = down;
  return out;
}

// The rumble for a sim event, as a "dual-rumble" effect, or null.
export function rumbleFor(reg, ev) {
  const r = reg.rumble && ev ? reg.rumble[ev.type] : null;
  if (!Array.isArray(r) || r.length !== 3) return null;
  return { startDelay: 0, duration: r[0], strongMagnitude: r[1], weakMagnitude: r[2] };
}

// Button names for each binding's `do` (the first button wins), for the HUD.
export function labelsFor(reg) {
  const out = {};
  for (const b of reg.bindings) if (!(b.do in out)) out[b.do] = reg.names[b.button] || b.button;
  return out;
}

// The pause menu's controller list: [buttons, what they do], buttons that do
// the same thing sharing a row.
export function padHelp(reg) {
  const rows = (reg.sticks || []).map((s) => [`${s.stick[0].toUpperCase()}${s.stick.slice(1)} stick`, s.does]);
  const seen = new Map();
  for (const b of reg.bindings) {
    const name = reg.names[b.button] || b.button;
    if (seen.has(b.does)) seen.get(b.does)[0] += ` / ${name}`;
    else {
      const row = [name, b.does];
      seen.set(b.does, row);
      rows.push(row);
    }
  }
  return rows;
}
