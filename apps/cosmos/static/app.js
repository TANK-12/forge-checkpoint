/* The Cosmos shell: the mode menu, and switching between modes.
 *
 * Modes are discovered, not listed here. The backend scans
 * static/modes/<id>/mode.json and this page builds its menu from the answer.
 * A mode's entry module default-exports `{ mount(root, ctx) }`, and mount
 * resolves to an instance with `unmount()` and, optionally, `onEscape()`
 * (return true if the mode used the key, for example to clear a selection).
 *
 * The URL hash is the current mode (#map, #sandbox), so reloading the page
 * keeps you where you were.
 */

const menu = document.getElementById("menu");
const stage = document.getElementById("stage");
const list = document.getElementById("mode-list");
const toastEl = document.getElementById("toast");

let modes = [];
let active = null;
let routeToken = 0;

export async function api(path, options = {}) {
  const init = { ...options };
  if (init.json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(init.json);
    delete init.json;
  }
  const res = await fetch(path, init);
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      message = body.error || body.detail || message;
    } catch {
      /* not JSON; keep the status line */
    }
    // .status tells a refusal (the server answered) from no answer at all
    throw Object.assign(new Error(message), { status: res.status });
  }
  return res.json();
}

export async function apiBuffer(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.arrayBuffer();
}

let toastTimer = 0;
export function toast(message, ms = 3200) {
  toastEl.textContent = message;
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toastEl.hidden = true), ms);
}

function renderMenu() {
  list.replaceChildren(
    ...modes.map((m, i) => {
      const card = document.createElement("a");
      card.className = "mode-card";
      card.href = `#${encodeURIComponent(m.id)}`;
      card.innerHTML = `
        <span class="mode-icon"></span>
        <span class="mode-text"><strong></strong><span></span></span>
        <kbd></kbd>`;
      card.querySelector(".mode-icon").textContent = m.icon || "✦";
      card.querySelector("strong").textContent = m.name || m.id;
      card.querySelector(".mode-text span").textContent = m.tagline || "";
      card.querySelector("kbd").textContent = i < 9 ? String(i + 1) : "";
      return card;
    }),
  );
}

async function route() {
  const token = ++routeToken;
  const id = decodeURIComponent(location.hash.slice(1));
  if (active && active.id === id) return;
  if (active) {
    try {
      active.instance?.unmount?.();
    } catch (err) {
      console.error(err);
    }
    active = null;
    stage.replaceChildren();
  }
  const mode = modes.find((m) => m.id === id);
  if (!mode) {
    stage.hidden = true;
    menu.hidden = false;
    startMenuSky();
    if (token > 1) loadCredit(); // stars fetched in the map since the last look
    return;
  }
  menu.hidden = true;
  stage.hidden = false;
  stopMenuSky();
  // a calm line instead of a blank stage while the mode's code loads; its
  // mount() replaces the stage's contents
  const wait = document.createElement("p");
  wait.className = "stage-loading";
  wait.textContent = `Opening ${mode.name || mode.id}\u2026`;
  stage.replaceChildren(wait);
  try {
    const mod = await import(`./modes/${mode.id}/${mode.entry}`);
    if (token !== routeToken) return;
    const instance = await mod.default.mount(stage, {
      api,
      apiBuffer,
      toast,
      mode,
      back: () => (location.hash = ""),
    });
    if (token !== routeToken) {
      instance?.unmount?.();
      return;
    }
    active = { id, instance };
  } catch (err) {
    console.error(err);
    if (token === routeToken) stage.replaceChildren();
    toast(`${mode.name} could not start: ${err.message}`, 6000);
    location.hash = "";
  }
}

document.addEventListener("keydown", (e) => {
  const tag = e.target?.tagName || "";
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || e.ctrlKey || e.metaKey || e.altKey) return;
  if (!menu.hidden && /^[1-9]$/.test(e.key)) {
    const m = modes[Number(e.key) - 1];
    if (m) location.hash = m.id;
    return;
  }
  if (e.key === "Escape" && active) {
    // Full screen's own Escape handler runs after this one; leave it the key.
    if (window.ForgeChrome?.hidden) return;
    if (active.instance?.onEscape?.()) return;
    location.hash = "";
  }
});

// The hub's Close app button sits left of Full screen (app.css), whose width
// follows the font: measured, so the two never overlap (critic round F1,
// Relay task 405: on a fallback font they met by two pixels).
const fullscreenBtn = document.getElementById("go-fullscreen");
if (fullscreenBtn) {
  new ResizeObserver(() => {
    if (fullscreenBtn.offsetWidth) {
      document.documentElement.style.setProperty("--fs-w", `${fullscreenBtn.offsetWidth}px`);
    }
  }).observe(fullscreenBtn);
}

/* --- the menu's backdrop: a slow, twinkling sky ---------------------------- */

const sky = document.getElementById("menu-sky");
let skyLoop = null;
let skyStars = [];
// The twinkle is slow, so 30 frames a second looks the same as 60 for half the work.
const SKY_FPS = 30;
// ForgeIdle.loop (shared/forge_idle.js) also rests while the page is hidden.
const frameLoop =
  window.ForgeIdle?.loop ||
  ((fn) => {
    let id = requestAnimationFrame(function step(t) {
      fn(t);
      id = requestAnimationFrame(step);
    });
    return { stop: () => cancelAnimationFrame(id) };
  });

function startMenuSky() {
  if (skyLoop) return;
  const g = sky.getContext("2d");
  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    sky.width = sky.clientWidth * dpr;
    sky.height = sky.clientHeight * dpr;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    skyStars = Array.from({ length: Math.round((sky.clientWidth * sky.clientHeight) / 2600) }, () => ({
      x: Math.random() * sky.clientWidth,
      y: Math.random() * sky.clientHeight,
      r: Math.random() ** 3 * 1.6 + 0.3,
      phase: Math.random() * 6.28,
      speed: 0.4 + Math.random() * 1.6,
      hue: Math.random(),
    }));
  };
  // asked for less motion: draw the sky once (and again on a resize) and leave it still
  const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const onResize = () => {
    resize();
    if (still) paint(0);
  };
  resize();
  window.addEventListener("resize", onResize);
  let lastDraw = -1e9;
  const draw = (t) => {
    if (t - lastDraw < 1000 / SKY_FPS - 2) return;
    lastDraw = t;
    paint(t);
  };
  function paint(t) {
    const w = sky.clientWidth;
    const h = sky.clientHeight;
    g.clearRect(0, 0, w, h);
    const glow = g.createRadialGradient(w * 0.72, h * 0.3, 0, w * 0.72, h * 0.3, Math.max(w, h) * 0.7);
    glow.addColorStop(0, "rgba(80, 90, 170, 0.22)");
    glow.addColorStop(0.5, "rgba(120, 60, 130, 0.08)");
    glow.addColorStop(1, "rgba(0, 0, 0, 0)");
    g.fillStyle = glow;
    g.fillRect(0, 0, w, h);
    for (const s of skyStars) {
      const a = 0.45 + 0.55 * Math.sin(s.phase + (t / 1000) * s.speed) ** 2;
      g.fillStyle = s.hue < 0.15 ? `rgba(255,205,160,${a})` : s.hue > 0.85 ? `rgba(170,200,255,${a})` : `rgba(240,240,255,${a})`;
      g.beginPath();
      g.arc(s.x, s.y, s.r, 0, 6.2832);
      g.fill();
    }
  }
  if (still) {
    paint(0);
    skyLoop = { stop() {} };
  } else skyLoop = frameLoop(draw);
  startMenuSky.stopResize = () => window.removeEventListener("resize", onResize);
}

function stopMenuSky() {
  skyLoop?.stop();
  skyLoop = null;
  startMenuSky.stopResize?.();
}

let modesError = null;

async function loadModes() {
  try {
    modes = (await api("/api/modes")).modes;
  } catch (err) {
    modesError = err;
    return false;
  }
  renderMenu();
  return true;
}

// Cosmos's server not up yet (Forge still starting it, or it went down): say so
// calmly and keep trying, less often the longer it takes.
function waitForServer() {
  const note = document.createElement("p");
  note.className = "menu-wait";
  // an answer with an error (.status) is not "not answering": say what it was
  const say = () => {
    note.textContent = modesError?.status
      ? `Cosmos could not list its modes (${modesError.message}). Trying again by itself\u2026`
      : "Cosmos is not answering yet. Trying again by itself\u2026";
  };
  say();
  list.replaceChildren(note);
  const retry = async () => {
    if (!(await loadModes())) {
      say();
      return false;
    }
    job.stop();
    loadCredit();
    route();
  };
  const job = window.ForgeIdle
    ? ForgeIdle.poll(retry, 3000, { backoff: 2, maxMs: 30000 })
    : { stop() {} };
}

function loadCredit() {
  api("/api/catalog")
    .then((c) => {
      // Not available yet is the normal state before the download: say how to
      // get the stars. Only a real failure (an error field) says "not available".
      const missing = c.error
        ? " The star catalog is not available right now."
        : c.hint
          ? ` ${c.hint}`
          : " The star catalog is not available right now.";
      document.getElementById("credit").textContent =
        `Planet and moon positions from JPL. ${c.credit}.` +
        (c.available ? "" : missing);
    })
    .catch(() => {});
}

async function boot() {
  if (await loadModes()) loadCredit();
  else waitForServer();
  window.addEventListener("hashchange", route);
  route();
}

boot();
