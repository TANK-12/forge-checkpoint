/* Settings frontend.
 *
 * Every control carries data-key naming a setting in shared/forge_theme.py.
 * A change is saved (debounced), the backend answers with the theme it
 * produces, and that theme is posted to the Forge hub, which applies it at
 * once and passes it on to every open app.
 */

const $ = (id) => document.getElementById(id);
const state = { settings: null, fields: null, theme: null, walls: [], pending: {}, timer: null, section: "", onBattery: null, dragging: false, previewing: {}, saving: false, again: false, resetting: false, epoch: 0, current: null, options: null, optionsSaved: {}, perf: null };

// An error says whether it is worth trying again: `offline` when the backend
// did not answer (stopped, restarting) rather than refused the request.
async function api(path, options) {
  let r;
  try {
    r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  } catch (e) {
    throw Object.assign(new Error("the Settings backend is not answering"), { offline: true });
  }
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const d = (await r.json()).detail;
      if (typeof d === "string") detail = d;
      else if (Array.isArray(d)) detail = d.map((x) => x.msg).join("; ");
    } catch (e) {}
    throw Object.assign(new Error(detail || `error ${r.status}`), { status: r.status, offline: r.status >= 502 });
  }
  return r.json();
}

function saidStatus(text) {
  $("saved").textContent = text;
  $("saved").title = text;
}

function tellHub(theme) {
  try { window.parent.postMessage({ forge: "theme", theme }, "*"); } catch (e) {}
}

function thumbUrl(name) { return `/api/wallpapers/${encodeURIComponent(name)}/thumb`; }

// The picture Forge shows now: its name in the wallpaper folder ("" when it
// is kept elsewhere) and its thumbnail, which the backend serves wherever the
// picture is. A backend from before 2026-10-19 sends no `current`: then it is
// the theme's bare file name, as before.
function currentWall() {
  if (state.current) return state.current;
  const name = (state.theme && state.theme.wallpaper_name) || "";
  return { name, thumb: name ? thumbUrl(name) : "" };
}

function change(key, value, asked = false) {
  const spec = (state.fields || {})[key] || {};
  if (!asked && spec.ask_lower && isLower(spec, value, state.optionsSaved[key])) {
    askLower(key, value, spec);
    return;
  }
  state.settings[key] = value;
  state.pending[key] = value;
  saidStatus("Saving…");
  clearTimeout(state.timer);
  state.timer = setTimeout(flush, 180);
  renderControls();
}

/* One save at a time, so answers cannot arrive out of order and put back an
   older value; changes made meanwhile go in the next one. When the backend
   is away the change is kept, not dropped, and sent again with a growing
   wait (2 s up to 30 s) that rests while Settings is hidden. Returns false
   when it could not save. */
let retry = null;
async function flush() {
  clearTimeout(state.timer);
  if (state.resetting) return true;  // the reset decides what is kept
  if (state.saving) { state.again = true; return true; }
  const body = state.pending;
  if (!Object.keys(body).length) { stopRetry(); return true; }
  state.pending = {};
  state.saving = true;
  const epoch = state.epoch;
  let ok = true;
  try {
    // Forge's own settings go to /api/settings; an app's options (app:NAME:KEY)
    // go to /api/options/NAME, which saves them into that app's own file.
    const hub = {}, apps = {};
    Object.entries(body).forEach(([key, value]) => {
      if (!key.startsWith(OPT)) { hub[key] = value; return; }
      const [name, option] = optionParts(key);
      (apps[name] = apps[name] || {})[option] = value;
    });
    if (Object.keys(hub).length) {
      const r = await api("/api/settings", { method: "POST", body: JSON.stringify(hub) });
      stopRetry();
      if (epoch !== state.epoch) return true;  // a reset answered since: its values stand
      accept(r);
    }
    for (const [name, changes] of Object.entries(apps)) {
      const r = await api(`/api/options/${encodeURIComponent(name)}`,
        { method: "POST", headers: OPT_HEADERS, body: JSON.stringify(changes) });
      stopRetry();
      acceptOptions(name, r.values);
    }
    saidStatus(Object.keys(state.pending).length ? "Saving…" : "Saved");
  } catch (e) {
    ok = false;
    if (e.offline) {
      state.pending = { ...body, ...state.pending };
      saidStatus("Not saved yet: the backend is not answering. Trying again by itself…");
      startRetry();
    } else if (e.status === 423 && typeof Business !== "undefined") {
      saidStatus("Not saved: Business mode is locked.");
      Business.refused(body); // asks for the password, then sends it again
    } else {
      saidStatus("Not saved: " + e.message);
    }
  } finally {
    state.saving = false;
  }
  const more = state.again || Object.keys(state.pending).length;
  state.again = false;
  if (ok && more) return flush();
  if (!ok && !retry) refreshSoon();  // refused: show what is really stored
  return ok;
}

function startRetry() {
  if (retry || !window.ForgeIdle) return;
  retry = ForgeIdle.poll(flush, 2000, { backoff: 2, maxMs: 30000 });
}

function stopRetry() {
  if (retry) retry.stop();
  retry = null;
}

function accept(r) {
  // Anything changed or dragged here since the request left stays as it is,
  // and so do the apps' options, which Forge's own settings do not carry.
  state.settings = Object.assign(r.settings, optionValues(), state.previewing, state.pending);
  state.theme = r.theme;
  state.current = r.current || null;
  tellHub(r.theme);
  render();
  if (typeof Business !== "undefined") Business.refresh(); // the look may lock now
}

/* ------------------------------------------------------------- wallpaper */

// A thumbnail that cannot be had (a desktop picture outside the wallpaper
// folder, a file gone since the listing) shows the plain tile, not a broken
// image: an empty picture keeps the tile's size, border and background.
const NO_THUMB = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
function noThumb(img) {
  if (img.getAttribute("src") !== NO_THUMB) img.src = NO_THUMB;
}

function thumbInto(img, name, tile) {
  img.addEventListener("error", () => {
    noThumb(img);
    if (tile) tile.classList.add("no-thumb");
  });
  img.src = thumbUrl(name);
}

function buildWalls() {
  const grid = $("walls");
  grid.innerHTML = "";
  state.walls.forEach((w) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "wall";
    item.dataset.name = w.name;
    item.title = w.name;
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = "";
    thumbInto(img, w.name, item);
    const label = document.createElement("span");
    label.className = "name";
    label.textContent = w.name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ");
    item.append(img, label);
    item.addEventListener("click", () => change("wallpaper", w.name));
    grid.appendChild(item);
  });
}

function renderWallpaper() {
  const t = state.theme, now = currentWall();
  const name = t.wallpaper_name || "";
  $("current-name").textContent = name ? name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ") : "No wallpaper yet";
  $("current-name").classList.toggle("empty", !name);
  $("current-note").textContent = !t.follows_desktop
    ? `Chosen here · ${now.name || name}`
    : state.desktopFollow !== false
      ? "Following your desktop — it changes when the desktop's does."
      : name
        ? "The first picture in your wallpaper folder: pick another below."
        : `Forge shows a plain background for now. Put pictures in ${state.wallDir || "your wallpaper folder"} and pick one here.`;
  const thumb = $("current-thumb");
  if (now.thumb !== thumb.dataset.src) {
    thumb.dataset.src = now.thumb;
    if (now.thumb) thumb.src = now.thumb;
    else noThumb(thumb);
  }
  $("follow-desktop").checked = !!t.follows_desktop;
  document.querySelectorAll(".wall").forEach((item) =>
    item.classList.toggle("on", !!now.name && item.dataset.name === now.name));
}

// Favourites are starred in the Wallpapers browser; they are re-read whenever this
// page comes back into view, so a star added there shows here. The strip is
// only rebuilt when the list changed: rebuilding on every focus blinked each
// picture and threw away the strip's scroll. A failed read keeps what shows.
let favShown = null;
async function loadFavourites() {
  if (state.wallApp === false) return;
  let names;
  try { names = (await api("/api/favourites")).favourites; } catch (e) { return; }
  const key = JSON.stringify(names);
  if (key === favShown) {
    if (state.theme) renderWallpaper();
    return;
  }
  favShown = key;
  const box = $("favs");
  box.replaceChildren();
  if (!names.length) {
    const hint = document.createElement("div");
    hint.className = "muted small";
    hint.textContent = state.wallApp
      ? "No favourites yet: star wallpapers in Browse all wallpapers to keep them here."
      : "No favourites yet.";
    box.appendChild(hint);
    return;
  }
  names.forEach((name) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "wall fav";
    item.dataset.name = name;
    item.title = name;
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = "";
    thumbInto(img, name, item);
    const label = document.createElement("span");
    label.className = "name";
    label.textContent = name.split("/").pop().replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ");
    item.append(img, label);
    item.addEventListener("click", () => change("wallpaper", name));
    box.appendChild(item);
  });
  if (state.theme) renderWallpaper();
}

$("current-thumb").addEventListener("error", (e) => noThumb(e.target));

// The whole Wallpapers browser lives in this section: this
// backend serves the Wallpapers app at /wallpapers/, and the hub opens
// "Wallpapers" here at #wallpapers (its manifest's "inside"), so the frame
// loads only when it is first shown. `view` is the browser's own hash
// ("favourites").
function showWallBrowser(open, view) {
  const box = $("wall-browser"), frame = $("wall-frame");
  if (!state.wallApp) return;
  box.hidden = !open;
  $("open-wallpapers").setAttribute("aria-expanded", String(open));
  $("open-wallpapers").textContent = open ? "Hide the browser" : "Browse all wallpapers";
  if (!open) { loadFavourites(); return; }
  const want = "wallpapers/?embed=1" + (view ? "#" + view : "");
  if (!frame.getAttribute("src")) frame.setAttribute("src", want);
  else if (view) { try { frame.contentWindow.location.hash = view; } catch (e) {} }
  box.scrollIntoView({ block: "nearest", behavior: "smooth" });
}
$("open-wallpapers").addEventListener("click", () => showWallBrowser($("wall-browser").hidden));
// The browser hands a new theme up like any app: pass it on to the hub, which
// sends it back to every open app (this page re-reads its settings then).
// The hub's themes go down to the browser the same way, so it wears Forge's
// look like this page does: each new one, and the last one when it loads.
window.addEventListener("message", (event) => {
  const frame = $("wall-frame"), msg = event.data;
  if (!msg) return;
  if (event.source === window.parent && window.parent !== window && msg.forge === "theme" && msg.theme) {
    state.hubTheme = msg.theme;
    if (frame.contentWindow && frame.getAttribute("src")) frame.contentWindow.postMessage(msg, "*");
    return;
  }
  if (!frame.contentWindow || event.source !== frame.contentWindow) return;
  if (msg.forge === "ready" && state.hubTheme) {
    frame.contentWindow.postMessage({ forge: "theme", theme: state.hubTheme }, "*");
  } else if (msg.forge === "theme" && msg.theme) {
    tellHub(msg.theme);
    loadFavourites();
  } else if (msg.forge === "key") {
    try { window.parent.postMessage(msg, "*"); } catch (e) {}
  }
});
document.addEventListener("visibilitychange", () => { if (!document.hidden) loadFavourites(); });

/* Settings are also changed elsewhere: the Power app's frame-rate sliders, the
   bar's size panel. The hub passes every new theme to each open app, and says
   whether the laptop is on battery, so this page re-reads the settings then,
   and when it comes back into view. Not while a change of its own is saving. */
let refreshTimer = 0;
function refreshSoon() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(async () => {
    const busy = () => state.dragging || state.saving || Object.keys(state.pending).length;
    if (!state.settings || busy()) return;
    try {
      const s = await api("/api/settings");
      if (busy()) return;
      state.settings = Object.assign(s.settings, optionValues());
      state.theme = s.theme;
      state.current = s.current || null;
      render();
    } catch (e) {}
  }, 300);
}
window.addEventListener("message", (event) => {
  const msg = event.data;
  if (event.source !== window.parent || window.parent === window || !msg || msg.forge !== "theme") return;
  // forge_chrome.js has just applied the hub's text size: keep a drag's preview.
  if (state.dragging) showPreviews(state.previewing);
  if (msg.theme && typeof msg.theme.on_battery === "boolean" && msg.theme.on_battery !== state.onBattery) {
    state.onBattery = msg.theme.on_battery;
    markPowerNow();
  }
  const perf = msg.theme && msg.theme.perf;
  if (perf && typeof perf === "object" && JSON.stringify(perf) !== JSON.stringify(state.perf)) {
    state.perf = perf;
    markPerfNow();
  }
  refreshSoon();
});
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshSoon(); });
document.addEventListener("forge-visible", (e) => { if (e.detail && e.detail.visible) refreshSoon(); });
window.addEventListener("focus", loadFavourites);

// Stop following = keep the desktop's current picture, which only works when
// that picture is in the wallpaper folder; otherwise say so and open the picker.
$("follow-desktop").addEventListener("change", (e) => {
  if (e.target.checked) return change("wallpaper", "");
  const name = currentWall().name;
  if (name && state.walls.some((w) => w.name === name)) return change("wallpaper", name);
  e.target.checked = true;
  $("current-note").textContent = "Your desktop's picture is not in the wallpaper folder: pick one below to stop following it.";
  document.querySelector("details.quick").open = true;
});

$("wall-filter").addEventListener("input", (e) => {
  const needle = e.target.value.trim().toLowerCase();
  document.querySelectorAll(".wall").forEach((item) =>
    item.classList.toggle("hidden", !!needle && !item.dataset.name.toLowerCase().includes(needle)));
});

/* ---------------------------------------------------------------- colour */

// Rebuilt only when what it shows changed: the hub's theme message re-renders
// the page after every save, and a rebuild lost a focused swatch.
let swatchesShown = "";
function renderSwatches() {
  const chosen = state.settings.accent;
  const key = JSON.stringify([chosen, state.theme.accent, state.theme.on_accent, state.theme.swatches]);
  if (key === swatchesShown) return;
  swatchesShown = key;
  const box = $("swatches");
  box.innerHTML = "";
  const auto = document.createElement("button");
  auto.type = "button";
  auto.className = "swatch auto" + (chosen ? "" : " on");
  auto.textContent = "Automatic";
  auto.style.background = state.theme.accent;
  auto.style.color = state.theme.on_accent;
  auto.title = "Take the colour from the wallpaper";
  auto.addEventListener("click", () => change("accent", ""));
  box.appendChild(auto);
  (state.theme.swatches || []).forEach((colour) => {
    const swatch = document.createElement("button");
    swatch.type = "button";
    swatch.className = "swatch" + (chosen === colour ? " on" : "");
    swatch.style.background = colour;
    swatch.title = colour;
    swatch.addEventListener("click", () => change("accent", colour));
    box.appendChild(swatch);
  });
  $("custom-accent").value = state.theme.accent;
}

$("custom-accent").addEventListener("change", (e) => change("accent", e.target.value));

/* -------------------------------------------------------------- controls */

// How a number is printed beside its slider, by the setting's `unit`.
const UNITS = {
  percent: (v) => `${Math.round(v * 100)}%`,
  whole_percent: (v) => `${Math.round(v)}%`,
  solid: (v) => `${Math.round(v * 100)}% solid`,
  px: (v) => `${v} px`,
  ms: (v) => `${v} ms`,
  fps: (v) => `${v} fps`,
  s: (v) => `${v} s`,
  min: (v) => (Number(v) ? `${v} min` : "Never"),
  "%": (v) => `${v}%`,
  days: (v) => `${v} days`,
  times: (v) => `${Number(v).toFixed(2)}×`,
};

function formatValue(key, value) {
  const spec = state.fields[key] || {}, unit = spec.unit;
  if (spec.zero && Number(value) === 0) return spec.zero;  // 0 reads as "Forever"
  return UNITS[unit] ? UNITS[unit](value) : String(value);
}

/* A presets slider: steps through named sets of the settings in spec.sets
   (built-ins, then the user's own, as the theme lists them), with a box to
   save the current mix under a name. */
function presetRow(key, spec) {
  const row = document.createElement("div");
  row.className = "slider presets item";
  row.dataset.presets = key;
  row.dataset.search = "preset size small default comfortable large";
  row.innerHTML = `<label for="preset-${key}">Preset</label><input type="range" id="preset-${key}" min="0" step="1"><output></output>
    <form class="preset-save"><input type="text" placeholder="Name this mix" maxlength="30" spellcheck="false"><button class="btn">Save as custom</button></form>`;
  const list = () => ((state.theme || {})[key] || []);
  // A preset sets App size too, so like that slider it previews while
  // dragged and is applied once, on release (see wireInput).
  const range = row.querySelector("input[type=range]");
  range.addEventListener("input", () => {
    const p = list()[Number(range.value)];
    if (p) preview(Object.fromEntries(spec.sets.map((k) => [k, Number(p[k]) || 1])), row);
  });
  range.addEventListener("change", () => {
    endPreview();
    const p = list()[Number(range.value)];
    if (p) spec.sets.forEach((k) => change(k, Number(p[k]) || 1));
  });
  row.querySelector("form").addEventListener("submit", (e) => {
    e.preventDefault();
    const box = row.querySelector("input[type=text]");
    const name = box.value.trim().slice(0, 30);
    if (!name) return;
    const mine = list().filter((p) => p.mine && p.name !== name).map(({ mine: _, ...p }) => p);
    mine.push(Object.assign({ name }, Object.fromEntries(spec.sets.map((k) => [k, state.settings[k]]))));
    change(key, mine);
    box.value = "";
  });
  return row;
}

/* Forge's own keys: one box per action, showing its default until changed.
   Several keys for one action are separated by commas ("Alt+F, F11"). */
function keysTable(key, spec) {
  const box = document.createElement("div");
  box.className = "keys";
  box.dataset.keys = key;
  Object.entries(spec.defaults).forEach(([action, fallback]) => {
    const label = document.createElement("label");
    label.className = "item";
    const name = document.createElement("span");
    name.className = "key-name";
    name.textContent = (spec.labels || {})[action] || action;
    label.dataset.search = `${name.textContent} ${fallback} key shortcut`;
    const input = document.createElement("input");
    input.type = "text";
    input.spellcheck = false;
    input.placeholder = fallback;
    input.dataset.action = action;
    const save = (value) => {
      const next = Object.assign({}, state.settings[key]);
      if (value) next[action] = value;
      else delete next[action];
      change(key, next);
    };
    input.addEventListener("change", () => save(input.value.trim()));
    // Shown on a key of your own only, like a changed row's ↺. After the
    // input, so the label still focuses the input when its name is clicked.
    const back = document.createElement("button");
    back.type = "button";
    back.className = "to-default";
    back.title = `Back to the default (${fallback})`;
    back.setAttribute("aria-label", `Put ${name.textContent} back to ${fallback}`);
    back.addEventListener("click", (e) => { e.preventDefault(); input.value = ""; save(""); });
    label.append(name, input, back);
    box.appendChild(label);
  });
  const note = document.createElement("div");
  note.className = "muted small note";
  note.textContent = "Write keys like Alt+F or Ctrl+Alt+3; separate two with a comma. Empty means the default shown. These work inside every app.";
  box.appendChild(note);
  return box;
}

function renderKeys() {
  document.querySelectorAll("[data-keys]").forEach((box) => {
    const keys = state.settings[box.dataset.keys] || {};
    box.querySelectorAll("input[data-action]").forEach((input) => {
      if (document.activeElement !== input) input.value = keys[input.dataset.action] || "";
      // a key of your own is a change from the default, like a dot row
      input.closest(".item").classList.toggle("changed", !!keys[input.dataset.action]);
    });
  });
}

function renderPresets() {
  document.querySelectorAll("[data-presets]").forEach((row) => {
    const key = row.dataset.presets, spec = state.fields[key] || {};
    const list = (state.theme || {})[key] || [];
    const i = list.findIndex((p) => spec.sets.every((k) => Math.abs((Number(p[k]) || 1) - Number(state.settings[k])) < 0.001));
    const range = row.querySelector("input[type=range]");
    range.max = Math.max(0, list.length - 1);
    // No exact match: sit on the nearest preset, named as your own mix.
    const gap = (p) => spec.sets.reduce((sum, k) => sum + Math.abs((Number(p[k]) || 1) - Number(state.settings[k])), 0);
    range.value = i >= 0 ? i : list.reduce((best, p, j) => (gap(p) < gap(list[best]) ? j : best), 0);
    row.querySelector("output").textContent = i >= 0 ? list[i].name : "Your own mix";
  });
}

function renderControls() {
  markPowerNow();
  renderPresets();
  renderKeys();
  // the settings the Forge layout holds (Classic, shared/forge_theme.py
  // FORGE_LAYOUTS) show the value in use, locked; his own choice stays saved
  const holds = (state.theme && state.theme.layout_holds) || {};
  document.querySelectorAll("[data-key]").forEach((input) => {
    const key = input.dataset.key, held = key in holds, value = held ? holds[key] : state.settings[key];
    if (input.type === "checkbox") input.checked = !!value;
    else if (document.activeElement !== input) input.value = value;
    input.disabled = held;
    // a dot beside the name of anything changed from its default
    const spec = (state.fields || {})[key], row = input.closest(".item");
    if (row) row.classList.toggle("held", held);
    if (row && spec && "default" in spec) row.classList.toggle("changed", !held && JSON.stringify(value) !== JSON.stringify(spec.default));
  });
  document.querySelectorAll("output[data-for]").forEach((out) => {
    out.textContent = formatValue(out.dataset.for, state.settings[out.dataset.for]);
  });
  if (window.ForgeFxPreview) ForgeFxPreview.refreshAll();
  const n = changedCount();
  $("changed-count").textContent = n ? String(n) : "none";
  $("changed-only").classList.toggle("none", !n);
  if (typeof Resets !== "undefined") Resets.paint();
}

/* ------------------------------------------------- changed from default */

// Whether a setting differs from its default (false for one with none).
function isChanged(key) {
  const spec = (state.fields || {})[key];
  return !!spec && "default" in spec && JSON.stringify(state.settings[key]) !== JSON.stringify(spec.default);
}

// The settings a hand-made card stands for: the ones its reset button puts
// back (data-settings) and ones it shows without a row of their own
// (data-changed: the theme and the home layout, which Reset all counts too).
function ownKeys(sec) {
  return `${sec.dataset.settings || ""} ${sec.dataset.changed || ""}`.split(/\s+/).filter(Boolean);
}

// How many settings on the page differ from their defaults: each dot row
// once (a copy in Speed and detail is the same setting), each key of your
// own, and the hand-made cards' settings (ownKeys).
function changedCount() {
  const keys = new Set();
  document.querySelectorAll(".item.changed [data-key]").forEach((input) => keys.add(input.dataset.key));
  document.querySelectorAll(".item.changed input[data-action]").forEach((input) => keys.add(`keys:${input.dataset.action}`));
  document.querySelectorAll("section[data-settings], section[data-changed]").forEach((sec) =>
    ownKeys(sec).filter(isChanged).forEach((key) => keys.add(key)));
  return keys.size;
}

/* "Changed from default" under the search box: every page's changed rows in
   one view, each with its ↺, like a search for the dot. A row put back stays
   where it is until the view is opened again, so nothing moves under the
   pointer. Typing a search, Esc or picking a section leaves it. */
function showChanged() {
  $("search").value = "";
  document.body.classList.add("searching", "changed-view");
  $("changed-only").setAttribute("aria-pressed", "true");
  let any = false;
  sections().forEach((sec) => {
    const items = [...sec.querySelectorAll(".item")];
    let hits = 0;
    items.forEach((item) => {
      const hit = item.classList.contains("changed");
      item.classList.toggle("miss", !hit);
      hits += hit;
    });
    const own = ownKeys(sec).some(isChanged);
    const show = own || hits > 0;
    sec.hidden = !show;
    any = any || show;
    const b = document.querySelector(`#nav-list button[data-section="${sec.dataset.section}"]`);
    if (b) { b.classList.remove("on"); b.classList.toggle("hit", show); }
  });
  $("no-match").textContent = "Nothing is changed from its default: every setting is as Forge comes.";
  $("no-match").hidden = any;
}

function leaveChanged() {
  document.body.classList.remove("changed-view");
  $("changed-only").setAttribute("aria-pressed", "false");
}

$("changed-only").addEventListener("click", () => {
  if (document.body.classList.contains("changed-view")) showSection(state.section);
  else showChanged();
});

// What a setting's default reads as, for its ↺ button's tooltip.
function defaultText(key, spec) {
  const d = spec.default;
  if (spec.kind === "bool") return d ? "on" : "off";
  if (spec.kind === "number" || spec.kind === "int") return formatValue(key, d);
  const label = (spec.labels || {})[d];
  if (label) return label;
  return d === "" ? "empty" : String(d);
}

// What a setting with "preview" in its spec shows on this page while its
// slider is dragged, before it is applied everywhere on release.
const PREVIEWS = {
  text_size: (value) => window.ForgeChrome && ForgeChrome.previewTextSize && ForgeChrome.previewTextSize(value),
};

// A dragged "apply on release" slider: the value shows here (its number, the
// preset name, the setting's own preview) and nothing is saved or sent. Its
// own row keeps its text size: bigger letters there would move the slider
// under the pointer, the App size problem over again.
function preview(values, row) {
  if (row && !row.hasAttribute("data-pinned")) {
    row.setAttribute("data-pinned", "");
    row.style.setProperty("--forge-text", String((window.ForgeText && ForgeText.scale) || 1));
  }
  state.dragging = true;
  Object.assign(state.previewing, values);
  Object.assign(state.settings, values);
  showPreviews(values);
  renderControls();
}

function showPreviews(values) {
  Object.entries(values).forEach(([key, value]) => {
    const show = PREVIEWS[(state.fields[key] || {}).preview];
    if (show) show(value);
  });
}

function endPreview() {
  state.dragging = false;
  state.previewing = {};
  document.querySelectorAll("[data-pinned]").forEach((row) => {
    row.removeAttribute("data-pinned");
    row.style.removeProperty("--forge-text");
  });
}

function wireInput(input) {
  const key = input.dataset.key;
  const read = () => {
    const kind = (state.fields[key] || {}).kind;
    let value = input.type === "checkbox" ? input.checked : input.value;
    if (kind === "number" || kind === "int") value = Number(value);
    return value;
  };
  // A setting whose spec says "apply": "release" (App size, Text size, Icon
  // size) only previews while its slider is dragged and is applied once, on
  // release. App size zooms the whole Forge window, this page included, so
  // applying it mid-drag moved the slider under the pointer, which read a
  // new value and zoomed again: the size flip-flopped (the owner, 2026-10-07).
  const onRelease = () => input.type === "range" && (state.fields[key] || {}).apply === "release";
  input.addEventListener(input.type === "range" ? "input" : "change", () => {
    if (onRelease()) preview({ [key]: read() }, input.closest(".item"));
    else change(key, read());
  });
  if (input.type === "range") {
    input.addEventListener("change", () => {
      if (!onRelease()) return;
      endPreview();
      change(key, read());
    });
  }
}
// A drag let go where it started fires no change: stop counting it as a drag.
document.addEventListener("pointerup", () => setTimeout(endPreview, 0), true);

document.querySelectorAll("[data-key]").forEach(wireInput);

// One card per group from the settings table. Sliders first, then switches
// and choices, in the table's order.
function buildGroups() {
  const box = $("groups");
  box.replaceChildren();
  const groups = new Map();
  const add = (name, item) => {
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(item);
  };
  Object.entries(state.fields).forEach(([key, spec]) => {
    if ((spec.custom && spec.kind !== "presets" && spec.kind !== "keys") || !spec.group || spec.app) return;
    add(spec.group, [key, spec]);
  });
  // `also`: the same control again in another card (Speed and detail collects
  // every frame rate and detail slider), after that card's own, named with
  // the page it comes from. Both controls follow one setting.
  Object.entries(state.fields).forEach(([key, spec]) => {
    (spec.also || []).forEach((name) => {
      add(name, [key, Object.assign({}, spec, { label: `${spec.group}: ${spec.label}`, copyIn: name })]);
    });
  });
  groups.forEach((items, name) => {
    items.sort((a, b) => (b[1].kind === "presets") - (a[1].kind === "presets") || !!a[1].copyIn - !!b[1].copyIn);
    const card = document.createElement("section");
    card.className = "card gen";
    card.dataset.section = name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
    card.dataset.title = name;
    const head = document.createElement("div");
    head.className = "card-head";
    const title = document.createElement("h3");
    title.textContent = name;
    head.append(title);
    card.appendChild(head);
    // a card that holds particle settings shows them live as they change
    // (shared/forge_fx_preview.js; its KEYS say which settings those are):
    // the preview goes where the first of them is, and the rest of them
    // follow it, so the sliders sit right under the picture they change
    if (window.ForgeFxPreview && items.some(([key, spec]) => !spec.copyIn && ForgeFxPreview.wants(key))) {
      const fx = items.filter(([key, spec]) => !spec.copyIn && ForgeFxPreview.wants(key));
      const at = items.indexOf(fx[0]);
      items = [...items.slice(0, at).filter((it) => !fx.includes(it)), ["__fx_preview", { kind: "fx_preview" }], ...fx,
        ...items.slice(at).filter((it) => !fx.includes(it))];
    }

    items.forEach(([key, spec]) => {
      if (spec.kind === "fx_preview") card.appendChild(fxPreviewBox());
      else if (spec.kind === "presets") card.appendChild(presetRow(key, spec));
      else if (spec.kind === "keys") card.appendChild(keysTable(key, spec));
      else card.appendChild(settingRow(key, spec));
    });
    // Reset sits at the foot of the page (resets.js): it asks first and keeps
    // a copy to undo. Saved custom presets are his own and stay.
    const foot = document.createElement("div");
    foot.className = "card-foot";
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "btn reset-sec";
    reset.dataset.resetSection = name;
    reset.dataset.resetKeys = [...new Set(items.filter(([, spec]) => spec.kind !== "presets" && spec.kind !== "fx_preview").map(([key]) => key))].join(" ");
    reset.addEventListener("click", () => Resets.run({ section: name }));
    foot.appendChild(reset);
    card.appendChild(foot);
    box.appendChild(card);
  });
}

// The live particle preview's place in a card (buildGroups)
function fxPreviewBox() {
  const box = document.createElement("div");
  box.className = "fx-preview-box";
  ForgeFxPreview.mount(box, {
    look: () => Object.assign({}, state.theme, state.settings),
    labels: () => ((state.fields || {}).particles || {}).labels,
    picture: () => currentWall().thumb,
    hint: "live preview · click for sparks",
  });
  return box;
}

// One row per setting: its name and help on the left (with the ↺ that puts it
// back), the control on the right, so each help line sits under the thing it
// explains. The cards above and Settings > Apps both use it.
function settingWhat(key, spec) {
  const box = document.createElement("div");
  box.className = "what";
  const top = document.createElement("div");
  top.className = "what-top";
  const label = document.createElement("label");
  label.htmlFor = controlId(key, spec);
  label.textContent = spec.label;
  // Shown on a changed row only: puts this one setting back.
  const back = document.createElement("button");
  back.type = "button";
  back.className = "to-default";
  back.title = `Back to the default (${defaultText(key, spec)})`;
  back.setAttribute("aria-label", `Put ${spec.label} back to its default`);
  back.addEventListener("click", () => change(key, spec.default));
  top.append(label, back);
  box.appendChild(top);
  if (spec.help) {
    const help = document.createElement("small");
    help.className = "muted";
    help.textContent = spec.help;
    box.appendChild(help);
  }
  // Performance: which tier the hub runs now, and why
  if (spec.now === "perf") {
    const note = document.createElement("small");
    note.className = "perf-now";
    note.dataset.perfNow = "";
    box.appendChild(note);
    showPerfNow(note);
  }
  return box;
}

// "Now: Balanced, because only 4 processor threads" from the hub's theme
// (appTheme's perf); empty standalone, where no hub decides.
function showPerfNow(note) {
  const p = state.perf;
  note.hidden = !p || !p.label;
  if (note.hidden) return;
  const why = p.auto ? (p.why ? `because ${p.why}` : "") : "picked here";
  note.textContent = `Now: ${p.label}${why ? (p.auto ? `, ${why}` : ` (${why})`) : ""}`;
}
function markPerfNow() {
  document.querySelectorAll("[data-perf-now]").forEach(showPerfNow);
}

function settingRow(key, spec) {
  const row = document.createElement("div");
  row.dataset.search = searchText(key, spec);
  let input;
  if (spec.kind === "number" || spec.kind === "int") {
    row.className = "slider item";
    input = document.createElement("input");
    input.type = "range";
    input.min = spec.min;
    input.max = spec.max;
    input.step = spec.step || (spec.kind === "int" ? 1 : 0.01);
    const out = document.createElement("output");
    out.dataset.for = key;
    row.append(settingWhat(key, spec), input, out);
  } else {
    row.className = "set-row item";
    if (spec.kind === "bool") {
      input = document.createElement("input");
      input.type = "checkbox";
      input.className = "toggle";
    } else if (spec.kind === "text") {
      input = document.createElement("input");
      input.type = "text";
      input.spellcheck = false;
    } else {
      input = document.createElement("select");
      spec.choices.forEach((choice) => {
        const option = document.createElement("option");
        option.value = choice;
        option.textContent = (spec.labels || {})[choice] || choice;
        input.appendChild(option);
      });
    }
    row.append(settingWhat(key, spec), input);
  }
  input.id = controlId(key, spec);
  input.dataset.key = key;
  wireInput(input);
  return row;
}

// A control's id: set-<key>, and for its copy in another card the card's name too.
function controlId(key, spec) {
  return spec.copyIn ? `set-${key}-in-${spec.copyIn.toLowerCase().replace(/[^a-z0-9]+/g, "-")}` : `set-${key}`;
}

// Plugged in or on battery, as the hub last said (null standalone): the rows
// of Speed and detail that apply now are marked, from the theme's power_pairs.
function markPowerNow() {
  document.querySelectorAll(".item.now").forEach((row) => row.classList.remove("now"));
  if (state.onBattery === null) return;
  Object.entries((state.theme || {}).power_pairs || {}).forEach(([key, [twin]]) => {
    const live = state.onBattery ? twin : key;
    document.querySelectorAll(`[data-key="${live}"]`).forEach((input) => {
      const row = input.closest(".item");
      if (row) row.classList.add("now");
    });
  });
}

// What a search matches for one setting: its label, help, choices and key.
function searchText(key, spec) {
  return [spec.label, spec.help, key.replace(/_/g, " "), ...Object.values(spec.labels || {})]
    .filter(Boolean).join(" ");
}

/* ------------------------------------------------------------------ apps */

/* Settings > Apps: each app's own options, declared in apps/NAME/options.json
   (shared/forge_options.py). They join state.fields and state.settings as
   app:NAME:KEY, so the rows, the ↺, Changed from default and the search work
   as for Forge's own settings; flush() sends them to /api/options/NAME,
   which saves them into that app's own file, never into Forge's settings or
   the hub's theme. */
const OPT = "app:";
const OPT_HEADERS = { "Content-Type": "application/json", "X-Forge": "1" };
const optKey = (name, key) => `${OPT}${name}:${key}`;
function optionParts(fid) {
  const rest = fid.slice(OPT.length), at = rest.indexOf(":");
  return [rest.slice(0, at), rest.slice(at + 1)];
}
function optionValues() {
  return Object.fromEntries(Object.entries(state.settings || {}).filter(([key]) => key.startsWith(OPT)));
}

function acceptOptions(name, values) {
  Object.entries(values || {}).forEach(([key, value]) => {
    const fid = optKey(name, key);
    state.optionsSaved[fid] = value;
    if (!(fid in state.pending) && !(fid in state.previewing)) state.settings[fid] = value;
  });
  renderControls();
}

// A smaller number for an option that deletes things (Calendar's keep time)
// is asked about first; 0 counts as the most when the spec says what 0 means.
function isLower(spec, value, saved) {
  if (saved === undefined) return false;
  const size = (n) => (spec.zero && Number(n) === 0 ? Infinity : Number(n));
  return size(value) < size(saved);
}

async function askLower(key, value, spec) {
  const saved = state.optionsSaved[key];
  const ok = window.ForgeDialog
    ? await ForgeDialog.confirm(`${spec.label}: ${formatValue(key, value)} instead of ${formatValue(key, saved)}?\n${spec.ask_lower}`)
    : false;
  if (ok) return change(key, value, true);
  state.settings[key] = saved;
  renderControls();
}

async function loadOptions() {
  try {
    const data = await api("/api/options", { headers: OPT_HEADERS });
    data.apps.forEach((app) => Object.entries(app.options).forEach(([key, spec]) => {
      const fid = optKey(app.name, key);
      state.fields[fid] = Object.assign({}, spec, { app: app.name });
      state.settings[fid] = state.optionsSaved[fid] = app.values[key];
    }));
    state.options = data;
  } catch (e) {
    state.options = { error: e.message };
  }
}

const optEl = (tag, cls, text) => Object.assign(document.createElement(tag), cls ? { className: cls } : {}, text ? { textContent: text } : {});

function buildApps() {
  const list = $("apps-list"), without = $("apps-without"), data = state.options || {};
  if (!list) return;  // a release leaves App options out (FORGE_CUT_PAGES)
  list.replaceChildren();
  without.replaceChildren();
  if (data.error) {
    $("apps-cover").textContent = `The apps' options could not be read: ${data.error}.`;
    return;
  }
  const apps = data.apps || [], none = data.without || [], broken = data.broken || [];
  const total = apps.length + none.length + broken.length;
  $("apps-cover").textContent = `${apps.length} of ${total} apps show their options here. `
    + `The other ${total - apps.length} keep their options inside the app itself, `
    + "in its own settings panel: they have no options.json yet.";
  apps.forEach((app) => {
    const box = optEl("div", "app-opts");
    box.dataset.app = app.name;
    const live = app.live === "restart"
      ? `A change applies the next time ${app.label} starts.`
      : `A change applies within seconds: ${app.label} reads it again by itself.`;
    box.append(optEl("h4", "", `${app.icon ? app.icon + " " : ""}${app.label}`),
      optEl("div", "muted small", [app.about, live].filter(Boolean).join(" ")),
      optEl("div", "muted small app-file", `Kept in ${app.file}`));
    let group = null;
    Object.keys(app.options).forEach((key) => {
      const fid = optKey(app.name, key), spec = state.fields[fid];
      if (spec.group && spec.group !== group) box.appendChild(optEl("h5", "", (group = spec.group)));
      box.appendChild(settingRow(fid, spec));
    });
    list.appendChild(box);
  });
  broken.forEach((app) => without.appendChild(optEl("p", "apps-broken", `${app.label}: its options.json could not be used (${app.error}).`)));
  if (none.length) {
    const more = optEl("details", "apps-none");
    more.append(optEl("summary", "", `Apps without options.json yet (${none.length})`),
      optEl("p", "muted small", none.map((app) => app.label).join(", ")));
    without.appendChild(more);
  }
}

/* -------------------------------------------------------------- sections */

// Every card with a data-section is a page of its own, listed on the left in
// page order: the hand-made ones and one per group, so a new group in the
// settings table gets its page with no change here.
const sections = () => [...document.querySelectorAll(".settings section[data-section]")];

/* How Settings itself is laid out (the Layout section): the section list as a sidebar, tabs or
   one long page; density; width; pinned sections first. The owner
   (2026-09-27): "make the settings app a better layout or customizable".
   Kept in this browser only, like the open section. */
const LAYOUT_KEY = "forge.settings.layout";
// Compact by default (the owner, 2026-09-28: "settings more compact but still there")
const LAYOUT_DEFAULT = { nav: "sidebar", density: "compact", width: "normal", pins: [] };
function layout() {
  try { return { ...LAYOUT_DEFAULT, ...JSON.parse(localStorage.getItem(LAYOUT_KEY) || "{}") }; } catch (e) { return { ...LAYOUT_DEFAULT }; }
}
function setLayout(changes) {
  const next = { ...layout(), ...changes };
  try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(next)); } catch (e) {}
  applyLayout();
}
function applyLayout() {
  const l = layout(), b = document.body.classList;
  b.toggle("nav-tabs", l.nav === "tabs");
  b.toggle("nav-page", l.nav === "page");
  b.toggle("dense", l.density === "compact");
  b.toggle("wide", l.width === "wide");
  document.querySelectorAll("#layout-panel .seg").forEach((seg) => {
    seg.querySelectorAll("button").forEach((btn) => btn.classList.toggle("on", l[seg.dataset.pref] === btn.dataset.v));
  });
  if (sections().length) { buildNav(); showSection(state.section); }
}
let layoutWired = false;
function wireLayout() {
  if (layoutWired) return applyLayout();
  layoutWired = true;
  // Its own section in the list (it used to float over the top right).
  const panel = $("layout-panel");
  panel.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => setLayout({ [b.parentElement.dataset.pref]: b.dataset.v })));
  $("layout-reset").addEventListener("click", () => { try { localStorage.removeItem(LAYOUT_KEY); } catch (e) {} applyLayout(); });
  applyLayout();
}

function buildNav() {
  const list = $("nav-list");
  list.replaceChildren();
  const pins = layout().pins.filter((id) => sections().some((s) => s.dataset.section === id));
  const ordered = [...pins.map((id) => sections().find((s) => s.dataset.section === id)),
    ...sections().filter((s) => !pins.includes(s.dataset.section))];
  ordered.forEach((sec, i) => {
    const id = sec.dataset.section, item = document.createElement("div");
    item.className = "item";
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = sec.dataset.title;
    b.dataset.section = id;
    b.addEventListener("click", () => {
      $("search").value = "";
      showSection(id, true);
    });
    const pin = document.createElement("button");
    pin.type = "button";
    pin.className = "pin" + (pins.includes(id) ? " on" : "");
    pin.textContent = pins.includes(id) ? "★" : "☆";
    pin.title = pins.includes(id) ? "Unpin" : "Pin to the top";
    pin.setAttribute("aria-label", `${pin.title}: ${sec.dataset.title}`);
    pin.addEventListener("click", () => {
      const now = layout().pins;
      setLayout({ pins: now.includes(id) ? now.filter((p) => p !== id) : [...now, id] });
    });
    item.append(b, pin);
    list.appendChild(item);
    if (pins.length && i === pins.length - 1) list.appendChild(Object.assign(document.createElement("div"), { className: "pins-end" }));
  });
}

function showSection(id, jump) {
  const all = sections();
  if (!all.some((sec) => sec.dataset.section === id)) id = all[0].dataset.section;
  state.section = id;
  document.body.classList.remove("searching");
  leaveChanged();
  $("no-match").hidden = true;
  document.querySelectorAll(".miss").forEach((el) => el.classList.remove("miss"));
  const page = layout().nav === "page";
  all.forEach((sec) => (sec.hidden = !page && sec.dataset.section !== id));
  if (page && jump) {
    const sec = all.find((s) => s.dataset.section === id);
    sec.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    sec.classList.add("flash");
    setTimeout(() => sec.classList.remove("flash"), 900);
  }
  document.querySelectorAll("#nav-list button").forEach((b) => {
    b.classList.remove("hit");
    b.classList.toggle("on", b.dataset.section === id);
    if (b.dataset.section === id) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  try { history.replaceState(null, "", "#" + id); } catch (e) {}
  try { localStorage.setItem("forge.settings.section", id); } catch (e) {}
}

// The one-page layout opened at #system (or with a section remembered) lands
// on that section at once, without the smooth glide a click gets.
function landOn(id) {
  const sec = sections().find((s) => s.dataset.section === id);
  if (!sec || layout().nav !== "page") return;
  if (document.body.classList.contains("searching") || document.body.classList.contains("changed-view")) return;
  sec.scrollIntoView({ behavior: "auto", block: "start" });
}

// One setting brought into view and lit for a moment, its section shown first.
function landOnRow(key) {
  const k = CSS.escape(key);
  // plain rows carry data-key; the preset and key-binding rows drawn by hand
  // carry data-presets and data-keys
  const input = document.querySelector(`[data-key="${k}"], [data-presets="${k}"], [data-keys="${k}"]`);
  const item = input && (input.closest(".item") || input.closest("[data-search]") || input);
  if (!item) return;
  const sec = item.closest("[data-section]");
  if (sec && sec.dataset.section !== state.section) showSection(sec.dataset.section);
  item.scrollIntoView({ behavior: "auto", block: "center" });
  item.classList.add("flash-row");
  setTimeout(() => item.classList.remove("flash-row"), 1600);
}

// Forge changes only the hash when Settings is already open and another app
// or the hub's search asks for a page or a setting.
addEventListener("hashchange", () => {
  if (!state.fields) return;
  const [id, row] = decodeURIComponent(location.hash.slice(1)).split("/");
  // #wallpapers (opening the Wallpapers app) is the Wallpaper section with the
  // browser open, at its own view when one follows (#wallpapers/favourites)
  if (id === "wallpapers") {
    if (state.section !== "wallpaper") showSection("wallpaper", true);
    return showWallBrowser(true, row || "");
  }
  if (id && id !== state.section) showSection(id, true);
  if (row) landOnRow(row);
});

// Searching leaves the one-page view: every section with a match shows, with
// only its matching settings (all of them when the section's name matches).
function search(text) {
  const needle = text.trim().toLowerCase();
  if (!needle) return showSection(state.section);
  leaveChanged();
  document.body.classList.add("searching");
  let any = false;
  sections().forEach((sec) => {
    const whole = sec.dataset.title.toLowerCase().includes(needle);
    const items = [...sec.querySelectorAll(".item")];
    const hit = items.map((item) => (item.dataset.search || item.textContent).toLowerCase().includes(needle));
    const hits = hit.filter(Boolean).length;
    // A word found only in the section's own keywords ("laptop" for System)
    // shows the whole section, like a match on its name.
    const all = whole || (!hits && (sec.dataset.keywords || "").toLowerCase().includes(needle));
    items.forEach((item, i) => item.classList.toggle("miss", !(all || hit[i])));
    const show = all || hits > 0;
    sec.hidden = !show;
    any = any || show;
    const b = document.querySelector(`#nav-list button[data-section="${sec.dataset.section}"]`);
    if (b) { b.classList.remove("on"); b.classList.toggle("hit", show); }
  });
  $("no-match").textContent = "No setting matches that search.";
  $("no-match").hidden = any;
}

$("search").addEventListener("input", (e) => search(e.target.value));
$("search").addEventListener("keydown", (e) => {
  if (e.key === "Escape" && (e.target.value || document.body.classList.contains("changed-view"))) {
    e.preventDefault();
    e.target.value = "";
    search("");
  }
});
// Esc leaves the changed view wherever the focus is (the button just
// pressed, a ↺, or nothing), except in a box being typed in, where Esc
// belongs to that box; the search box has its own Esc above.
const TYPING = /^(TEXTAREA|SELECT)$|^INPUT:(?!(checkbox|radio|range|button|submit|reset|color)$)/;
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || e.defaultPrevented || !document.body.classList.contains("changed-view")) return;
  const at = document.activeElement;
  if (at && (at.isContentEditable || TYPING.test(at.tagName === "INPUT" ? `INPUT:${at.type}` : at.tagName))) return;
  e.preventDefault();
  search("");
});
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey && e.key === "f") || (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName))) {
    e.preventDefault();
    $("search").focus();
    $("search").select();
  }
});

function render() {
  renderWallpaper();
  renderSwatches();
  renderControls();
  if (typeof Business !== "undefined") Business.paint();
  if (typeof Themes !== "undefined") Themes.paint();
}

/* The first load. Until it works the page shows a calm card instead of empty
   sections, and tries again by itself (2 s, growing to 30 s, resting while
   hidden) when the backend is not up yet. */
let booter = null;
async function boot() {
  if (state.fields) return true;
  try {
    const [s, w] = await Promise.all([api("/api/settings"), api("/api/wallpapers")]);
    state.settings = s.settings;
    state.fields = s.fields;
    state.theme = s.theme;
    state.current = s.current || null;
    state.walls = w.wallpapers;
    await loadOptions();  // never stops the page: a failure is said in Apps
    state.wallDir = w.folder;
    // What this Forge has: with no Wallpapers app (a release has none) there
    // is no "Open Wallpapers" and no favourites, which are starred there; on
    // a desktop Forge cannot read the wallpaper of (macOS, most Linux
    // desktops) there is no "Follow my desktop wallpaper".
    state.wallApp = s.wall_browser === true;
    state.desktopFollow = s.desktop_follow !== false;
    ["open-wallpapers", "wall-app-note", "favs"].forEach((id) => { $(id).hidden = !state.wallApp; });
    if (!state.wallApp) $("wall-browser").hidden = true;
    document.querySelector(".fav-head").hidden = !state.wallApp;
    $("follow-desktop").closest("label").hidden = !state.desktopFollow;
    $("wall-filter").placeholder = `Search ${w.wallpapers.length} wallpapers in ${w.folder}…`;
    $("where").textContent = `Settings are kept in ${s.config}. Wallpaper copies and thumbnails `
      + `are cached in ${s.cache} and can be deleted at any time.`;
    // Read the asked-for section (#system, or the one open last time) before
    // wireLayout, whose first showSection would otherwise replace both with
    // the first section (seen 2026-10-19: Settings always opened on Wallpaper).
    // #section/key (the hub's search, Power's frame rate) also lands on
    // that one setting
    let [first, row] = decodeURIComponent(location.hash.slice(1)).split("/");
    const browse = first === "wallpapers" ? row || "" : null;
    if (browse !== null) [first, row] = ["wallpaper", ""];
    try { first = first || localStorage.getItem("forge.settings.section") || ""; } catch (e) {}
    state.section = first;
    buildGroups();
    buildApps();
    buildNav();
    wireLayout();
    showSection(first);
    buildWalls();
    render();
    const favs = loadFavourites();
    document.body.classList.remove("booting");
    if (first) {
      landOn(state.section);
      // The favourites strip above fills in a moment later and pushes the
      // sections below it down: land again once it has.
      favs.then(() => landOn(state.section));
    }
    if (row) {
      landOnRow(row);
      favs.then(() => landOnRow(row));
    }
    if (browse !== null) showWallBrowser(true, browse);
    if (booter) booter.stop();
    booter = null;
    return true;
  } catch (e) {
    state.fields = null;
    $("boot-title").textContent = "Settings is not reachable yet";
    $("boot-text").textContent = (e.offline ? "Its backend is not answering, probably still starting."
      : `The backend said: ${e.message}.`) + " Trying again by itself…";
    $("boot-retry").hidden = false;
    if (!booter && window.ForgeIdle) booter = ForgeIdle.poll(boot, 2000, { backoff: 2, maxMs: 30000 });
    return false;
  }
}

$("boot-retry").addEventListener("click", () => booter && booter.now());
boot();
