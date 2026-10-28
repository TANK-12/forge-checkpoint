/* Afterglow's shell: the shelf, the stage a curio runs on, keepsakes and the
 * logbook. A curio is curios/<id>/ (README.md has the contract); this file
 * never names one. #<id> opens a curio, #<id>/<slug> opens one of its
 * keepsakes, an empty hash is the shelf.
 */

import * as ui from "/curios/_kit/ui.js";
import { signature, wallRows, curioCounts, surprise, logbookPages, fullKey } from "/shelf_logic.js";

const $ = (sel) => document.querySelector(sel);
const MODE_KEY = "afterglow.mode";
/** How many curios the shelf showed last time; index.html draws that many placeholders. */
const SHELF_KEY = "afterglow.shelfSize";
const FILTER_KEY = "afterglow.wall";
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let curios = [];
let advanced = localStorage.getItem(MODE_KEY) === "advanced";
let active = null; // { meta, ctx, instance, root }
let opening = 0; // bumps on every route, so a slow import cannot mount late
const modules = new Map();
const fullKeepsakes = new Map(); // fullKey(row) -> Promise of the full keepsake, for wall pictures
const wall = { rows: [], curio: localStorage.getItem(FILTER_KEY) || "", all: false, sig: "", lastPick: "" };
const book = { pages: [], all: false, sig: "" };
let shelfSig = "";
let shelfScroll = 0;

// --- server ---------------------------------------------------------------------

async function api(path, { method = "GET", body } = {}) {
  const opts = { method, headers: {} };
  if (method !== "GET") opts.headers["X-Forge"] = "1";
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const detail = data && data.detail;
    const msg = typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : text.slice(0, 200);
    throw new Error(msg || `the workshop answered ${res.status}`);
  }
  return data === null && text ? text : data;
}

let toastTimer = 0;
function toast(text, kind = "") {
  const box = $("#toast");
  box.textContent = text;
  box.className = `toast ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.add("hidden"), 3200);
}

// A message belongs to the screen it was raised on: opening another curio clears it.
function dropToast() {
  clearTimeout(toastTimer);
  $("#toast").classList.add("hidden");
}

const fmtDate = (iso) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};

function loadModule(meta) {
  if (!modules.has(meta.id)) {
    const p = import(`/curios/${meta.id}/${meta.entry}`).then((m) => {
      const def = m.default;
      if (!def || typeof def.mount !== "function") throw new Error("curio.js has no default export with mount()");
      return def;
    });
    p.catch(() => modules.delete(meta.id)); // a fixed file loads next time
    modules.set(meta.id, p);
  }
  return modules.get(meta.id);
}

// --- what a curio gets ----------------------------------------------------------

function rafLoop(fn) {
  let id = 0, stopped = false;
  const frame = (t) => {
    if (stopped) return;
    if (fn(t) === false) return;
    id = requestAnimationFrame(frame);
  };
  id = requestAnimationFrame(frame);
  return { stop() { stopped = true; cancelAnimationFrame(id); } };
}

function thumbOf(canvas, maxSide = 320) {
  const scale = Math.min(1, maxSide / Math.max(canvas.width, canvas.height, 1));
  const out = document.createElement("canvas");
  out.width = Math.max(1, Math.round(canvas.width * scale));
  out.height = Math.max(1, Math.round(canvas.height * scale));
  const g = out.getContext("2d");
  g.fillStyle = "#08070d";
  g.fillRect(0, 0, out.width, out.height);
  g.drawImage(canvas, 0, 0, out.width, out.height);
  for (const q of [0.85, 0.7, 0.5]) {
    const url = out.toDataURL("image/jpeg", q);
    if (url.length < 190000) return url;
  }
  return null;
}

function makeCtx(meta) {
  const id = meta.id;
  const loops = new Set();
  const modeFns = new Set();
  return {
    id,
    meta,
    base: `/curios/${id}/`,
    // the kit, with every titled panel remembering whether it was folded
    ui: { ...ui, panel: (title, opts = {}) => ui.panel(title, { remember: title ? `${id}/${title}` : "", ...opts }) },
    toast,
    api: (path, opts) => api(`/api/curio/${id}/${String(path).replace(/^\/+/, "")}`, opts),
    async keep({ name, note = "", data = null, thumb = null }) {
      const row = await api("/api/keepsakes", { method: "POST", body: { curio: id, name, note, data, thumb } });
      meta.keepsakes = (meta.keepsakes || 0) + 1;
      if (!$("#drawer").hidden) renderDrawer();
      return row;
    },
    thumb: thumbOf,
    keepsakes: () => api(`/api/keepsakes?curio=${encodeURIComponent(id)}`).then((r) => r.keepsakes),
    loadKeepsake: (slug) => api(`/api/keepsakes/${id}/${encodeURIComponent(slug)}`),
    loop(fn) {
      const handle = window.ForgeIdle ? window.ForgeIdle.loop(fn) : rafLoop(fn);
      const wrapped = { stop() { handle.stop(); loops.delete(wrapped); } };
      loops.add(wrapped);
      return wrapped;
    },
    get advanced() { return advanced; },
    onMode(fn) {
      modeFns.add(fn);
      return () => modeFns.delete(fn);
    },
    _modeChanged() { for (const fn of [...modeFns]) try { fn(advanced); } catch (e) { console.error(e); } },
    _dispose() {
      for (const h of [...loops]) h.stop();
      modeFns.clear();
    },
  };
}

// --- modes ------------------------------------------------------------------------

function setMode(adv) {
  advanced = adv;
  localStorage.setItem(MODE_KEY, adv ? "advanced" : "simple");
  document.body.classList.toggle("simple", !adv);
  // shared/forge.css hides .adv unless body has "advanced", so set both
  document.body.classList.toggle("advanced", adv);
  for (const b of document.querySelectorAll("#mode-seg button")) {
    b.classList.toggle("on", (b.dataset.mode === "advanced") === adv);
  }
  if (active) active.ctx._modeChanged();
}

// --- shelf ------------------------------------------------------------------------

async function drawPreview(meta, canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.max(1, Math.round((rect.width || 320) * dpr));
  canvas.height = Math.max(1, Math.round((rect.height || 180) * dpr));
  try {
    const mod = await loadModule(meta);
    if (typeof mod.preview === "function") {
      await mod.preview(canvas);
      return;
    }
  } catch (e) {
    console.error(`preview of ${meta.id}`, e);
  }
  const g = canvas.getContext("2d");
  const grad = g.createLinearGradient(0, 0, canvas.width, canvas.height);
  grad.addColorStop(0, "#1a1222");
  grad.addColorStop(1, "#2a140c");
  g.fillStyle = grad;
  g.fillRect(0, 0, canvas.width, canvas.height);
  g.font = `${Math.round(canvas.height * 0.4)}px serif`;
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(meta.icon || "✨", canvas.width / 2, canvas.height / 2);
}

function cardByline(meta) {
  if (meta.server_error) return "its server part did not load; the browser part may still work";
  const kept = meta.keepsakes ? ` · ${meta.keepsakes} kept` : "";
  return `made by ${meta.made_by || "Claude"}${meta.made ? ", " + fmtDate(meta.made) : ""}${kept}`;
}

/** Builds the shelf cards the first time and whenever the curios change; on a
 *  plain return from a curio only the "kept" counts change, so the previews
 *  are not wiped and redrawn. */
function renderShelf() {
  const shelf = $("#shelf");
  const sig = signature(curios, ["id", "name", "tagline", "icon", "about", "made", "made_by", "server_error"]);
  if (sig === shelfSig) {
    for (const meta of curios) {
      const by = shelf.querySelector(`.card[data-curio="${CSS.escape(meta.id)}"] .by`);
      if (by && by.textContent !== cardByline(meta)) by.textContent = cardByline(meta);
    }
    return;
  }
  shelfSig = sig;
  shelf.replaceChildren();
  shelf.removeAttribute("aria-busy");
  for (const meta of curios) {
    const canvas = ui.el("canvas", { "aria-hidden": "true" });
    const card = ui.el(
      "a",
      {
        href: `#${meta.id}`,
        class: meta.server_error ? "card broken" : "card",
        dataset: { curio: meta.id },
        title: meta.about || meta.tagline || "",
      },
      canvas,
      ui.el(
        "div",
        { class: "meta" },
        ui.el("h3", {}, ui.el("span", { text: meta.icon || "✨" }), meta.name),
        ui.el("p", { text: meta.tagline || "" }),
        ui.el("span", { class: "by", text: cardByline(meta) }),
      ),
    );
    shelf.append(card);
    requestAnimationFrame(() => drawPreview(meta, canvas));
  }
  shelf.append(
    ui.el(
      "div",
      { class: "card slot" },
      ui.el("p", {
        text: "Room on the shelf for the next toy.",
      }),
    ),
  );
  localStorage.setItem(SHELF_KEY, String(curios.length));
}

/** A keepsake in full, fetched once per page (pictures of seeds are drawn from it). */
function loadFull(row) {
  const key = fullKey(row);
  if (!fullKeepsakes.has(key)) {
    const p = api(`/api/keepsakes/${row.curio}/${encodeURIComponent(row.slug)}`);
    p.catch(() => fullKeepsakes.delete(key)); // a failed fetch is tried again next time
    fullKeepsakes.set(key, p);
  }
  return fullKeepsakes.get(key);
}

/** A keepsake's picture: its stored thumb, or else its curio draws it live
 *  (preview(canvas, keepsake)), or else the curio's icon. */
function keepPicture(row, meta, on) {
  const pic = ui.el("div", { class: "pic", text: row.thumb ? "" : (meta && meta.icon) || "✨", on });
  if (row.thumb) {
    pic.style.backgroundImage = `url("${row.thumb}")`;
    return pic;
  }
  if (!meta) return pic;
  requestAnimationFrame(async () => {
    try {
      const mod = await loadModule(meta);
      if (typeof mod.preview !== "function") return;
      const full = await loadFull(row);
      const rect = pic.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const canvas = ui.el("canvas", { "aria-hidden": "true" });
      canvas.width = Math.max(1, Math.round((rect.width || 160) * dpr));
      canvas.height = Math.max(1, Math.round((rect.height || 120) * dpr));
      await mod.preview(canvas, full);
      pic.textContent = "";
      pic.append(canvas);
    } catch (e) {
      console.error(`picture of ${row.id}`, e);
    }
  });
  return pic;
}

function keepTile(row) {
  const meta = curios.find((c) => c.id === row.curio);
  const pic = keepPicture(row, meta);
  return ui.el(
    "a",
    { class: "keep", href: `#${row.curio}/${row.slug}`, title: row.note || row.name },
    pic,
    ui.el(
      "div",
      { class: "k-meta" },
      ui.el("b", { text: row.name }),
      ui.el("small", { text: `${meta ? meta.name : row.curio} · ${row.author || "someone"}` }),
      ui.el("small", { text: row.seed ? "came with the shelf" : fmtDate(row.made) }),
    ),
  );
}

async function loadWall() {
  try {
    wall.rows = (await api("/api/keepsakes")).keepsakes.filter((r) => curios.some((c) => c.id === r.curio));
  } catch (e) {
    wall.sig = "";
    $("#keep-filter").hidden = true;
    $("#all-keepsakes").replaceChildren(ui.el("p", { class: "empty", text: `Keepsakes did not load: ${e.message}` }));
    return;
  }
  renderWall();
}

/** Draws the wall from wall.rows: the curio filter, the first 24 or all of
 *  them. Leaves the tiles alone when nothing shown has changed. */
function renderWall() {
  const counts = curioCounts(wall.rows, curios);
  if (wall.curio && !counts.some((c) => c.id === wall.curio)) wall.curio = "";
  const view = wallRows(wall.rows, { curio: wall.curio, all: wall.all });
  const sig = `${wall.curio}|${wall.all}|${signature(view.shown, ["id", "name", "note", "author", "made", "seed", "thumb"])}|${signature(counts, ["id", "count"])}`;
  $("#keep-count").textContent = wall.rows.length ? String(wall.rows.length) : "";
  $("#surprise").hidden = !wall.rows.length;
  const more = $("#keep-more");
  more.hidden = !view.hidden;
  more.textContent = `Show all ${view.total}`;
  if (sig === wall.sig) return;
  wall.sig = sig;
  const filter = $("#keep-filter");
  filter.hidden = counts.length < 2;
  const chip = (id, label, count) =>
    ui.el(
      "button",
      {
        type: "button",
        class: wall.curio === id ? "on" : "",
        "aria-pressed": wall.curio === id ? "true" : "false",
        on: { click: () => setWallFilter(id) },
      },
      label,
      ui.el("span", { class: "n", text: String(count) }),
    );
  filter.replaceChildren(
    chip("", "Everything", wall.rows.length),
    ...counts.map((c) => chip(c.id, `${c.icon} ${c.name}`.trim(), c.count)),
  );
  const grid = $("#all-keepsakes");
  if (!view.shown.length) {
    grid.replaceChildren(ui.el("p", { class: "empty", text: "Nothing kept yet. Open a curio and keep something you like." }));
    return;
  }
  grid.replaceChildren(...view.shown.map(keepTile));
}

function setWallFilter(id) {
  wall.curio = id;
  wall.all = false;
  localStorage.setItem(FILTER_KEY, id);
  renderWall();
}

function surpriseMe() {
  const pool = wallRows(wall.rows, { curio: wall.curio, all: true }).shown;
  const pick = surprise(pool, Math.random, wall.lastPick);
  if (!pick) return;
  wall.lastPick = pick.id;
  location.hash = `${pick.curio}/${pick.slug}`;
}

function pageNode(page) {
  const paras = page.body.split(/\n\s*\n/).map((t) => t.trim()).filter(Boolean);
  const first = paras.slice(0, 1).map((t) => ui.el("p", { text: t }));
  const rest = ui.el("div", { class: "rest" }, ...paras.slice(1).map((t) => ui.el("p", { text: t })));
  const meta = page.curio ? curios.find((c) => c.id === page.curio) : null;
  const node = ui.el(
    "article",
    { class: paras.length > 1 ? "page folded" : "page" },
    ui.el("h4", { text: page.title }),
    ui.el("div", {
      class: "when",
      text: [page.author, fmtDate(page.made), meta ? `${meta.icon || ""} ${meta.name}` : ""].filter(Boolean).join(" · "),
    }),
    ...first,
    rest,
  );
  if (paras.length > 1) {
    const more = ui.el("button", { type: "button", class: "more", text: "Read on" });
    more.addEventListener("click", () => {
      const folded = node.classList.toggle("folded");
      more.textContent = folded ? "Read on" : "Fold";
    });
    node.append(more);
  }
  if (window.ForgeVoice) node.append(readAloud(page));
  return node;
}

// Forge's own voice reads a page aloud (shared/forge_voice.js and the Voice app).
let reading = null; // the button of the page being read
function readAloud(page) {
  const btn = ui.el("button", {
    type: "button",
    class: "more read",
    text: "Read aloud",
    title: "Forge's own voice reads this page (the Voice app has to be running)",
  });
  const idle = () => {
    if (reading === btn) reading = null;
    btn.textContent = "Read aloud";
  };
  btn.addEventListener("click", async () => {
    if (reading === btn) {
      idle();
      window.ForgeVoice.stop();
      return;
    }
    if (reading) reading.textContent = "Read aloud";
    reading = btn;
    btn.textContent = "Hush";
    try {
      await window.ForgeVoice.speak(`${page.title}.\n\n${page.body}`, { app: "afterglow" });
    } catch (e) {
      toast(`Forge's voice is not answering (${e.message}). Is the Voice app running?`, "err");
    }
    if (reading === btn) idle();
  });
  return btn;
}

async function loadLogbook() {
  try {
    book.pages = (await api("/api/logbook")).pages;
  } catch (e) {
    book.sig = "";
    $("#pages").replaceChildren(ui.el("p", { class: "empty", text: `The logbook did not load: ${e.message}` }));
    return;
  }
  renderLogbook();
}

/** Draws the newest pages (or all of them). Pages already on screen stay as
 *  they are when nothing changed, so an unfolded page or a page being read
 *  aloud is not reset by coming back from a curio. */
function renderLogbook() {
  const view = logbookPages(book.pages, { all: book.all });
  const more = $("#pages-more");
  more.hidden = !view.hidden;
  more.textContent = `Show ${view.hidden} older ${view.hidden === 1 ? "page" : "pages"}`;
  const sig = `${book.all}|${signature(view.shown, ["title", "body", "author", "made", "curio"])}`;
  if (sig === book.sig) return;
  book.sig = sig;
  $("#pages").replaceChildren(
    ...(view.shown.length ? view.shown.map(pageNode) : [ui.el("p", { class: "empty", text: "No pages yet." })]),
  );
}

let shelfTries = 0;
let retryTimer = 0;
/** The curio list with keepsake counts. When the workshop does not answer,
 *  one retry is pending at a time, backing off up to 15 s. */
async function loadCurios() {
  const notice = $("#shelf-notice");
  try {
    const data = await api("/api/curios");
    curios = data.curios;
    shelfTries = 0;
    notice.hidden = !data.problems.length;
    notice.textContent = data.problems.length ? `Some curios did not load: ${data.problems.join("; ")}` : "";
    return true;
  } catch (e) {
    shelfTries += 1;
    notice.hidden = false;
    notice.textContent = `The workshop is not answering yet (${e.message}). Trying again.`;
    clearTimeout(retryTimer);
    retryTimer = setTimeout(() => {
      if (!$("#shelf-view").hidden) loadShelf();
    }, Math.min(15000, 1000 * 2 ** shelfTries));
    return false;
  }
}

async function loadShelf() {
  if (!(await loadCurios())) return false;
  renderShelf();
  loadWall();
  loadLogbook();
  return true;
}

// --- the ember strip behind the name ----------------------------------------------

function startEmbers() {
  const canvas = $("#embers");
  const g = canvas.getContext("2d");
  const sparks = [];
  let last = 0;
  const size = () => {
    const r = canvas.getBoundingClientRect();
    canvas.width = Math.max(1, Math.round(r.width));
    canvas.height = Math.max(1, Math.round(r.height));
  };
  size();
  window.addEventListener("resize", size);
  const spawn = () => ({
    x: Math.random() * canvas.width,
    y: canvas.height + 2,
    vy: 6 + Math.random() * 14,
    vx: (Math.random() - 0.5) * 6,
    life: 1,
    fade: 0.25 + Math.random() * 0.35,
    r: 0.6 + Math.random() * 1.3,
  });
  const draw = (t) => {
    const dt = Math.min(0.05, (t - last) / 1000 || 0.016);
    last = t;
    if (!$("#shelf-view").hidden || sparks.length) {
      if (!$("#shelf-view").hidden && sparks.length < 26 && Math.random() < 0.5) sparks.push(spawn());
    }
    g.clearRect(0, 0, canvas.width, canvas.height);
    g.globalCompositeOperation = "lighter";
    for (let i = sparks.length - 1; i >= 0; i--) {
      const s = sparks[i];
      s.y -= s.vy * dt;
      s.x += s.vx * dt + Math.sin((t / 600) + i) * 0.15;
      s.life -= s.fade * dt;
      if (s.life <= 0 || s.y < -4) {
        sparks.splice(i, 1);
        continue;
      }
      g.fillStyle = `rgba(255, ${Math.round(120 + 100 * s.life)}, 60, ${0.75 * s.life})`;
      g.beginPath();
      g.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      g.fill();
    }
    g.globalCompositeOperation = "source-over";
  };
  if (reduceMotion) return;
  let handle = null;
  const run = () => {
    if (!handle) handle = window.ForgeIdle ? window.ForgeIdle.loop(draw) : rafLoop(draw);
  };
  const halt = () => {
    if (handle) handle.stop();
    handle = null;
    g.clearRect(0, 0, canvas.width, canvas.height);
    sparks.length = 0;
  };
  return { run, halt };
}

// --- stage --------------------------------------------------------------------------

function closeCurio() {
  if (!active) return;
  const { instance, ctx, root } = active;
  active = null;
  try {
    instance && instance.unmount && instance.unmount();
  } catch (e) {
    console.error("unmount", e);
  }
  ctx._dispose();
  root.remove();
}

function showShelf() {
  closeCurio();
  $("#stage-view").hidden = true;
  $("#drawer").hidden = true;
  $("#drawer-btn").hidden = true;
  $("#crumb").hidden = true;
  $("#brand-sub").hidden = false;
  $("#shelf-view").hidden = false;
  $("#shelf-view").scrollTop = shelfScroll;
  document.body.classList.remove("on-stage", "ag-opening");
  document.title = "Afterglow";
  if (embers) embers.run();
  loadShelf();
}

function stageError(text) {
  $("#stage").replaceChildren(
    ui.el(
      "div",
      { class: "stage-error" },
      ui.el("p", {}, ui.el("b", { text: "This curio did not start." })),
      ui.el("p", { text }),
      ui.button("Back to the shelf", () => (location.hash = "")),
    ),
  );
}

async function openCurio(id, slug) {
  const ticket = ++opening;
  // an address that opens a curio fetches only the curio list; the shelf draws when it is shown
  const answered = curios.length > 0 || (await loadCurios());
  if (ticket !== opening) return;
  if (!answered) {
    location.hash = ""; // the shelf says the workshop is not answering and retries
    return;
  }
  const meta = curios.find((c) => c.id === id);
  if (!meta) {
    toast(`There is no curio called "${id}" on the shelf.`, "err");
    location.hash = "";
    return;
  }
  if (!active || active.meta.id !== id) {
    closeCurio();
    dropToast();
    if (embers) embers.halt();
    if (!$("#shelf-view").hidden) shelfScroll = $("#shelf-view").scrollTop;
    $("#shelf-view").hidden = true;
    $("#stage-view").hidden = false;
    document.body.classList.add("on-stage");
    document.body.classList.remove("ag-opening");
    $("#drawer").hidden = true;
    $("#crumb").hidden = false;
    $("#crumb").textContent = `${meta.icon || ""} ${meta.name}`;
    $("#brand-sub").hidden = true;
    $("#drawer-btn").hidden = false;
    $("#drawer-btn").textContent = `Kept ${meta.keepsake_noun ? meta.keepsake_noun + "s" : "things"}`;
    document.title = `${meta.name} · Afterglow`;
    const loading = ui.el("p", { class: "stage-loading", text: `Opening ${meta.name}…` });
    $("#stage").replaceChildren(loading);
    let mod;
    try {
      mod = await loadModule(meta);
    } catch (e) {
      if (ticket === opening) stageError(e.message);
      return;
    }
    if (ticket !== opening) return;
    const root = ui.el("div", { class: "curio-root", dataset: { curio: id }, tabindex: "-1" });
    $("#stage").append(root);
    const ctx = makeCtx(meta);
    const mine = { meta, ctx, root, instance: null };
    active = mine;
    try {
      mine.instance = (await mod.mount(root, ctx)) || {};
    } catch (e) {
      console.error(e);
      if (active === mine) {
        closeCurio();
        stageError(e.message);
      }
      return;
    }
    if (active !== mine) {
      // Another route closed this curio while it was still mounting: undo the late
      // mount, or its key and resize listeners would outlive it.
      try {
        mine.instance.unmount && mine.instance.unmount();
      } catch (e) {
        console.error("unmount", e);
      }
      ctx._dispose();
      root.remove();
      return;
    }
    loading.remove();
    if (ticket !== opening) return;
    root.focus({ preventScroll: true });
  }
  if (slug) await openKeepsake(slug);
}

async function openKeepsake(slug) {
  if (!active) return;
  const { ctx, instance, meta } = active;
  if (!instance || typeof instance.open !== "function") {
    toast(`${meta.name} cannot open keepsakes yet.`, "err");
    return;
  }
  try {
    const full = await ctx.loadKeepsake(slug);
    if (active && active.instance === instance) await instance.open(full);
  } catch (e) {
    toast(`Could not open it: ${e.message}`, "err");
  }
}

// --- keepsake drawer --------------------------------------------------------------

let editing = null;
async function renderDrawer() {
  if (!active) return;
  const { ctx, meta } = active;
  $("#drawer-title").textContent = `${meta.icon || ""} Kept ${meta.keepsake_noun ? meta.keepsake_noun + "s" : "things"}`;
  const list = $("#drawer-list");
  if (list.dataset.curio !== meta.id) {
    // another curio's list must not show while this one loads
    list.dataset.curio = meta.id;
    list.replaceChildren(ui.el("p", { class: "empty", text: "Opening the drawer…" }));
  }
  let rows;
  try {
    rows = await ctx.keepsakes();
  } catch (e) {
    if (active && active.meta.id === meta.id) {
      list.replaceChildren(ui.el("p", { class: "empty", text: `Did not load: ${e.message}` }));
    }
    return;
  }
  if (!active || active.meta.id !== meta.id) return; // left for another curio while it loaded
  if (!rows.length) {
    list.replaceChildren(ui.el("p", { class: "empty", text: "Nothing kept from this curio yet." }));
    return;
  }
  list.replaceChildren(
    ...rows.map((row) => {
      const go = () => (location.hash = `${meta.id}/${row.slug}`);
      const pic = keepPicture(row, meta, { click: go });
      const buttons = ui.el("div", { class: "ag-row" }, ui.button("Open", go, { kind: "primary" }));
      if (!row.seed) {
        buttons.append(
          ui.button("Rename", () => {
            editing = row;
            $("#edit-name").value = row.name;
            $("#edit-note").value = row.note;
            $("#edit-dialog").showModal();
          }),
        );
        const away = ui.button("Put away", async () => {
          if (away.dataset.sure !== "1") {
            away.dataset.sure = "1";
            away.textContent = "Sure? Put away";
            setTimeout(() => {
              away.dataset.sure = "";
              away.textContent = "Put away";
            }, 3000);
            return;
          }
          try {
            await api(`/api/keepsakes/${meta.id}/${row.slug}/put-away`, { method: "POST" });
            toast(`Put away "${row.name}". The file is kept in put-away/.`);
            renderDrawer();
          } catch (e) {
            toast(e.message, "err");
          }
        }, { kind: "ghost danger", title: "Moves it out of sight. Nothing is deleted." });
        buttons.append(away);
      }
      return ui.el(
        "div",
        { class: "d-item" },
        pic,
        ui.el(
          "div",
          { class: "d-body" },
          ui.el("b", { text: row.name }),
          ui.el("small", { text: `${row.author || "someone"} · ${row.seed ? "came with the shelf" : fmtDate(row.made)}` }),
          row.note ? ui.el("p", { text: row.note }) : null,
          buttons,
        ),
      );
    }),
  );
}

function toggleDrawer(show) {
  const drawer = $("#drawer");
  drawer.hidden = show === undefined ? !drawer.hidden : !show;
  if (!drawer.hidden) renderDrawer();
}

// --- wiring -------------------------------------------------------------------------

function route() {
  let hash = "";
  try {
    hash = decodeURIComponent(location.hash.replace(/^#/, ""));
  } catch {
    // a broken %-escape in the address: show the shelf rather than nothing
  }
  if (!hash) {
    opening++;
    showShelf();
    return;
  }
  const [id, slug] = hash.split("/");
  openCurio(id, slug || null);
}

const embers = startEmbers();

document.querySelectorAll("#mode-seg button").forEach((b) =>
  b.addEventListener("click", () => setMode(b.dataset.mode === "advanced")),
);
$("#drawer-btn").addEventListener("click", () => toggleDrawer());
$("#drawer-close").addEventListener("click", () => toggleDrawer(false));
$("#write-page").addEventListener("click", () => $("#page-dialog").showModal());
$("#surprise").addEventListener("click", surpriseMe);
$("#keep-more").addEventListener("click", () => {
  wall.all = true;
  renderWall();
});
$("#pages-more").addEventListener("click", () => {
  book.all = true;
  renderLogbook();
});
if (window.ForgeVoice) {
  const mic = window.ForgeVoice.micButton($("#page-body"), { app: "afterglow" });
  mic.classList.add("ag-btn", "ghost");
  $("#page-cancel").before(mic);
}
$("#page-cancel").addEventListener("click", () => $("#page-dialog").close());
$("#edit-cancel").addEventListener("click", () => $("#edit-dialog").close());
$("#page-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/logbook", {
      method: "POST",
      body: { title: $("#page-title").value, body: $("#page-body").value },
    });
    $("#page-dialog").close();
    $("#page-title").value = "";
    $("#page-body").value = "";
    toast("Written in the logbook.", "ok");
    loadLogbook();
  } catch (err) {
    toast(err.message, "err");
  }
});
$("#edit-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!editing || !active) return;
  try {
    await api(`/api/keepsakes/${active.meta.id}/${editing.slug}`, {
      method: "POST",
      body: { name: $("#edit-name").value, note: $("#edit-note").value },
    });
    $("#edit-dialog").close();
    renderDrawer();
  } catch (err) {
    toast(err.message, "err");
  }
});

window.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || e.defaultPrevented) return; // forge_chrome leaves full screen first
  if (document.querySelector("dialog[open]")) return; // the dialog closes itself
  if (!active) return;
  if (!$("#drawer").hidden) {
    toggleDrawer(false);
    return;
  }
  let handled = false;
  try {
    handled = !!(active.instance && active.instance.onEscape && active.instance.onEscape());
  } catch (err) {
    console.error(err);
  }
  if (!handled) location.hash = "";
});
window.addEventListener("hashchange", route);

setMode(advanced);
route();
