/* Files - the page. Talks to web_app.py; every rule lives on the server. */
"use strict";

const $ = (id) => document.getElementById(id);
const S = {
  token: "",
  home: "",
  path: "",
  parent: null,
  items: [],        // what the server returned for this folder (or search)
  shown: [],        // after sort, in display order
  sel: new Set(),   // selected paths
  anchor: null,     // last clicked path, for shift-click ranges
  back: [],
  fwd: [],
  clip: null,       // {op: "copy"|"move", paths: []}
  searching: false,
  prefs: loadPrefs(),
};

function loadPrefs() {
  const def = { view: "list", sort: "name", dir: 1, hidden: false, preview: true, tile: 120 };
  try { return { ...def, ...JSON.parse(localStorage.getItem("files.prefs") || "{}") }; }
  catch { return def; }
}
function savePrefs() {
  try { localStorage.setItem("files.prefs", JSON.stringify(S.prefs)); } catch { /* private mode */ }
}

/* ---------------------------------------------------------------- server */

async function api(path, opts = {}) {
  const init = { headers: { "X-Forge": "1" } };
  if (opts.body !== undefined) {
    init.method = "POST";
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  let res;
  try { res = await fetch(path, init); }
  catch { throw new Error("The Files backend isn't answering. Try again in a moment."); }
  if (!res.ok) {
    const err = new Error(await errText(res, `${res.status}`));
    err.status = res.status;
    throw err;
  }
  return res.json();
}
const q = (params) => new URLSearchParams(params).toString();
const rawUrl = (p) => `/api/raw?${q({ path: p, t: S.token })}`;
const thumbUrl = (p) => `/api/thumb?${q({ path: p, t: S.token })}`;

/* ---------------------------------------------------------------- formatting */

const ICONS = {
  folder: "📁", image: "🖼️", video: "🎬", audio: "🎵", text: "📄",
  pdf: "📕", archive: "🗜️", file: "📦",
};
function fmtSize(n) {
  if (n < 1024) return `${n} B`;
  const u = ["KB", "MB", "GB", "TB"];
  let i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
  return `${n.toFixed(n < 10 ? 1 : 0)} ${u[i]}`;
}
function fmtDate(t) {
  if (!t) return "";
  const d = new Date(t * 1000);
  const today = new Date();
  if (d.toDateString() === today.toDateString())
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });
}
const baseName = (p) => p.split("/").filter(Boolean).pop() || "/";

/* ---------------------------------------------------------------- navigation */

/* Each folder load or search takes a ticket; only the newest one may draw,
   so a slow answer can't land on top of a folder opened after it. settledSeq
   is the newest ticket that has come back: while it trails navSeq a load is
   still on its way, and the folder watch must not start one over it. */
let navSeq = 0;
let settledSeq = 0;
function slowLoad(seq) {
  const t = setTimeout(() => { if (seq === navSeq) $("main").classList.add("loading"); }, 150);
  return () => { clearTimeout(t); if (seq === navSeq) $("main").classList.remove("loading"); };
}

/* Where each folder was scrolled to, so Back and Forward land where you were. */
const scrollMemo = new Map();

async function go(path, { push = true, scroll = 0 } = {}) {
  const seq = ++navSeq;
  const done = slowLoad(seq);
  let data;
  try {
    data = await api(`/api/list?${q({ path, hidden: S.prefs.hidden })}`);
  } catch (e) {
    done();
    if (seq === navSeq) { settledSeq = seq; toast(e.message, "err"); }
    return false;
  }
  done();
  if (seq !== navSeq) return false;
  settledSeq = seq;
  if (!online) { online = true; $("conn").classList.add("hidden"); syncToken(); }
  if (push && S.path && S.path !== data.path) {
    S.back.push(S.path);
    S.fwd = [];
  }
  const same = S.path === data.path;
  if (!same && S.path) {
    scrollMemo.delete(S.path);
    scrollMemo.set(S.path, $("items").scrollTop);
    if (scrollMemo.size > 60) scrollMemo.delete(scrollMemo.keys().next().value);
  }
  S.path = data.path;
  S.parent = data.parent;
  S.items = data.items;
  S.stamp = data.stamp;
  S.searching = false;
  if (!same) { S.sel.clear(); S.anchor = null; $("search").value = ""; S.scrollTo = scroll; }
  else { const have = new Set(data.items.map((i) => i.path)); for (const p of [...S.sel]) if (!have.has(p)) S.sel.delete(p); }
  $("free").textContent = data.free !== undefined ? `${fmtSize(data.free)} free` : "";
  try { localStorage.setItem("files.last", S.path); } catch { /* ignore */ }
  // this window's own place, in its address: a reload (F5 in a Forge
  // window) comes back here, not to the folder another window left last
  try { history.replaceState(history.state, "", `#${new URLSearchParams({ path: S.path })}`); } catch { /* ignore */ }
  render();
  return true;
}
const refresh = () => go(S.path, { push: false });

function goBack() {
  if (!S.back.length) return;
  S.fwd.push(S.path);
  const to = S.back.pop();
  go(to, { push: false, scroll: scrollMemo.get(to) || 0 });
}
function goFwd() {
  if (!S.fwd.length) return;
  S.back.push(S.path);
  const to = S.fwd.pop();
  go(to, { push: false, scroll: scrollMemo.get(to) || 0 });
}
function goUp() { if (S.parent) go(S.parent); }

async function runSearch() {
  const text = $("search").value.trim();
  if (!text) { refresh(); return; }
  const seq = ++navSeq;
  const done = slowLoad(seq);
  try {
    const data = await api(`/api/search?${q({ path: S.path, q: text, hidden: S.prefs.hidden })}`);
    done();
    if (seq !== navSeq) return;
    settledSeq = seq;
    S.items = data.items;
    S.searching = true;
    S.sel.clear();
    render();
    if (data.truncated) toast(`Showing the first ${data.items.length} matches`);
  } catch (e) { done(); if (seq === navSeq) { settledSeq = seq; toast(e.message, "err"); } }
}

/* ---------------------------------------------------------------- rendering */

function sorted(items) {
  const { sort, dir } = S.prefs;
  const key = {
    name: (i) => i.name.toLowerCase(),
    mtime: (i) => i.mtime,
    size: (i) => i.size,
    kind: (i) => i.kind + i.name.toLowerCase(),
  }[sort];
  return [...items].sort((a, b) => {
    if (a.dir !== b.dir) return a.dir ? -1 : 1;  // folders first, always
    const x = key(a), y = key(b);
    if (x < y) return -dir;
    if (x > y) return dir;
    return a.name.localeCompare(b.name, undefined, { numeric: true });
  });
}

function iconFor(item, big) {
  const box = document.createElement("span");
  box.className = "ico";
  const wantsThumb = item.kind === "image" || (big && (item.kind === "video" || item.kind === "pdf"));
  if (wantsThumb) {
    const img = document.createElement("img");
    img.loading = "lazy";
    img.decoding = "async";
    img.alt = "";
    img.src = thumbUrl(item.path);
    img.onload = () => img.classList.add("ready");
    img.onerror = () => { box.textContent = ICONS[item.kind]; };
    box.append(img);
  } else {
    box.textContent = ICONS[item.kind] || ICONS.file;
  }
  return box;
}

function render() {
  const main = $("main");
  main.classList.toggle("grid", S.prefs.view === "grid");
  main.style.setProperty("--tile", `${S.prefs.tile}px`);
  $("view").textContent = S.prefs.view === "grid" ? "☰" : "▦";
  $("hidden").classList.toggle("on", S.prefs.hidden);
  $("preview-toggle").classList.toggle("on", S.prefs.preview);
  $("preview").classList.toggle("off", !S.prefs.preview);
  $("sort").value = S.prefs.sort;
  $("sort-dir").textContent = S.prefs.dir > 0 ? "↓" : "↑";
  for (const h of document.querySelectorAll(".list-head span"))
    h.classList.toggle("sorted", h.dataset.sort === S.prefs.sort);
  $("back").disabled = !S.back.length;
  $("fwd").disabled = !S.fwd.length;
  $("up").disabled = !S.parent;

  renderCrumbs();
  renderSide();

  S.shown = sorted(window.FilesAdvanced ? window.FilesAdvanced.filter(S.items) : S.items);
  const box = $("items");
  const grid = S.prefs.view === "grid";
  const cut = S.clip?.op === "move" ? new Set(S.clip.paths) : null;
  // A new folder (or search) starts at the top, or where Back left it;
  // a redraw of the same one keeps its scroll.
  const view = `${S.path}\n${S.searching}`;
  const top = view === renderedView ? box.scrollTop : (S.searching ? 0 : S.scrollTo || 0);
  renderedView = view;
  S.scrollTo = 0;
  const frag = document.createDocumentFragment();
  const keep = new Map();
  for (const it of S.shown) {
    const row = rowFor(it, grid);
    row.classList.toggle("sel", S.sel.has(it.path));
    row.classList.toggle("cut", !!cut?.has(it.path));
    keep.set(it.path, rowCache.get(it.path));
    frag.append(row);
  }
  rowCache = keep;  // rows no longer shown are let go
  box.replaceChildren(frag);
  box.scrollTop = top;
  const empty = $("empty");
  empty.classList.toggle("hidden", S.shown.length > 0);
  empty.textContent = S.searching ? "Nothing matches that name." : "This folder is empty.";
  updateStatus();
  renderPreview();
}

/* Rows are kept per path and reused while the item is unchanged, so a
   redraw (after a paste, or when the folder changes by itself) puts the same
   elements back: thumbnails stay drawn and nothing blinks. */
let rowCache = new Map();
let renderedView = "";
function rowFor(it, grid) {
  const sig = [it.name, it.size, it.mtime, it.kind, it.link, grid, S.token, S.searching && S.path].join("|");
  const old = rowCache.get(it.path);
  if (old && old.sig === sig) return old.row;
  const row = document.createElement("div");
  row.className = "item";
  row.dataset.path = it.path;
  row.draggable = true;
  if (it.hidden) row.classList.add("hiddenfile");
  const name = document.createElement("div");
  name.className = "name";
  const label = document.createElement("span");
  label.className = "label";
  label.textContent = it.name;
  if (S.searching) label.title = it.path;
  name.append(iconFor(it, grid), label);
  const size = meta(it.dir ? "" : fmtSize(it.size));
  const kind = meta(it.link ? `${it.kind} (link)` : it.kind);
  const when = meta(S.searching ? it.path.replace(S.path, ".") : fmtDate(it.mtime));
  row.append(name, size, kind, when);
  rowCache.set(it.path, { sig, row });
  return row;
}

function meta(text) {
  const d = document.createElement("div");
  d.className = "meta";
  d.textContent = text;
  return d;
}

function renderCrumbs() {
  const nav = $("crumbs");
  nav.replaceChildren();
  const parts = S.path.split("/").filter(Boolean);
  let acc = "";
  const home = S.home;
  const startAtHome = S.path === home || S.path.startsWith(home + "/");
  const crumbs = [];
  if (startAtHome) {
    crumbs.push(["🏠 Home", home]);
    const rest = S.path.slice(home.length).split("/").filter(Boolean);
    acc = home;
    for (const p of rest) { acc += "/" + p; crumbs.push([p, acc]); }
  } else {
    crumbs.push(["/", "/"]);
    for (const p of parts) { acc += "/" + p; crumbs.push([p, acc]); }
  }
  crumbs.forEach(([label, path], i) => {
    if (i) { const s = document.createElement("span"); s.className = "sep"; s.textContent = "›"; nav.append(s); }
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.dataset.path = path;
    b.dataset.drop = "1";
    b.onclick = () => go(path);
    nav.append(b);
  });
  nav.scrollLeft = nav.scrollWidth;
}

let placesData = { places: [], drives: [], trash: null };
function renderSide() {
  const side = $("side");
  side.replaceChildren();
  const section = (title, list) => {
    if (!list.length) return;
    const h = document.createElement("h4");
    h.textContent = title;
    side.append(h);
    for (const p of list) {
      const b = document.createElement("button");
      b.className = "place";
      b.dataset.path = p.path;
      b.dataset.drop = "1";
      if (p.path === S.path) b.classList.add("active");
      const ico = document.createElement("span");
      ico.className = "ico";
      ico.textContent = p.icon;
      const label = document.createElement("span");
      label.textContent = p.label;
      b.append(ico, label);
      b.title = p.path;
      b.onclick = () => go(p.path);
      b.onmousedown = (e) => { if (e.button === 1) e.preventDefault(); };  // no autoscroll
      b.onauxclick = (e) => { if (e.button === 1) { e.preventDefault(); newWindow(p.path); } };
      side.append(b);
    }
  };
  section("Places", placesData.places);
  section("Drives", placesData.drives);
  if (placesData.trash) section("", [{ label: "Trash", path: placesData.trash, icon: "🗑️" }]);
}

function updateStatus() {
  const n = S.shown.length;
  $("count").textContent = `${n} item${n === 1 ? "" : "s"}`;
  const sel = selectedItems();
  if (!sel.length) { $("sel").textContent = ""; return; }
  const bytes = sel.reduce((a, i) => a + (i.dir ? 0 : i.size), 0);
  $("sel").textContent = `${sel.length} selected${bytes ? ` (${fmtSize(bytes)})` : ""}`;
}

function selectedItems() { return S.shown.filter((i) => S.sel.has(i.path)); }

function paintSelection() {
  for (const row of $("items").children) row.classList.toggle("sel", S.sel.has(row.dataset.path));
  updateStatus();
  renderPreview();
}

/* ---------------------------------------------------------------- preview */

let previewFor = null;
async function renderPreview() {
  const pane = $("preview");
  if (!S.prefs.preview) return;
  const sel = selectedItems();
  const it = sel.length === 1 ? sel[0] : null;
  const key = it ? `${it.path}|${it.mtime}|${S.token}` : `n${sel.length}:${S.path}`;
  if (key === previewFor) return;
  previewFor = key;
  pane.replaceChildren();
  if (!it) {
    const h = document.createElement("h3");
    h.textContent = sel.length ? `${sel.length} items selected` : baseName(S.path);
    const p = document.createElement("p");
    p.className = "muted small";
    p.textContent = sel.length ? "" : "Select a file to preview it.";
    pane.append(h, p);
    return;
  }
  const h = document.createElement("h3");
  h.textContent = it.name;
  let media = null;
  if (it.kind === "image") {
    media = document.createElement("img");
    media.src = rawUrl(it.path);
  } else if (it.kind === "video") {
    media = document.createElement("video");
    media.src = rawUrl(it.path);
    media.controls = true;
    media.preload = "metadata";
  } else if (it.kind === "audio") {
    media = document.createElement("audio");
    media.src = rawUrl(it.path);
    media.controls = true;
    media.preload = "metadata";
  }
  if (media) media.className = it.kind === "audio" ? "" : "media";
  const big = document.createElement("div");
  big.className = "big-ico";
  big.textContent = ICONS[it.kind] || ICONS.file;
  const dl = document.createElement("dl");
  const facts = [["Type", it.kind], ["Size", it.dir ? "" : fmtSize(it.size)], ["Modified", new Date(it.mtime * 1000).toLocaleString()], ["Where", it.path]];
  for (const [k, v] of facts) {
    if (!v) continue;
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = v;
    dl.append(dt, dd);
  }
  const actions = document.createElement("div");
  actions.className = "actions";
  actions.append(
    actionBtn(it.dir ? "Open folder" : "Open", () => openItem(it), true),
    actionBtn("Rename", () => renameSel()),
    ...(it.kind === "archive" ? [actionBtn("Extract here", () => archive("extract"))] : []),
    ...(inTrash() ? [actionBtn("Restore", () => restoreSel())] : [actionBtn("Move to trash", () => trashSel())]),
  );
  pane.append(h, media || (it.kind === "text" ? document.createTextNode("") : big), actions, dl);
  if (it.kind === "text" && it.size < 5_000_000) {
    try {
      const t = await api(`/api/text?${q({ path: it.path })}`);
      if (previewFor !== key) return;
      const pre = document.createElement("pre");
      pre.textContent = t.binary ? "(binary file)" : t.text + (t.truncated ? "\n…" : "");
      pane.insertBefore(pre, actions);
    } catch { /* unreadable: facts are enough */ }
  }
}

function actionBtn(label, fn, primary) {
  const b = document.createElement("button");
  b.className = primary ? "btn btn-primary" : "btn";
  b.textContent = label;
  b.onclick = fn;
  return b;
}

/* ---------------------------------------------------------------- selection */

function rowOf(el) { return el?.closest?.(".item"); }

function clickSelect(path, ev) {
  if (ev.shiftKey && S.anchor) {
    const paths = S.shown.map((i) => i.path);
    const a = paths.indexOf(S.anchor), b = paths.indexOf(path);
    if (!ev.ctrlKey) S.sel.clear();
    for (let i = Math.min(a, b); i <= Math.max(a, b); i++) S.sel.add(paths[i]);
  } else if (ev.ctrlKey || ev.metaKey) {
    S.sel.has(path) ? S.sel.delete(path) : S.sel.add(path);
    S.anchor = path;
  } else {
    S.sel.clear();
    S.sel.add(path);
    S.anchor = path;
  }
  paintSelection();
}

function moveCursor(delta, ev) {
  if (!S.shown.length) return;
  const paths = S.shown.map((i) => i.path);
  let i = S.anchor ? paths.indexOf(S.anchor) : -1;
  i = Math.max(0, Math.min(paths.length - 1, i + delta));
  if (ev.shiftKey) S.sel.add(paths[i]);
  else { S.sel.clear(); S.sel.add(paths[i]); }
  S.anchor = paths[i];
  paintSelection();
  $("items").querySelector(`.item[data-path="${CSS.escape(paths[i])}"]`)?.scrollIntoView({ block: "nearest" });
}

function gridColumns() {
  if (S.prefs.view !== "grid") return 1;
  const cols = getComputedStyle($("items")).gridTemplateColumns.split(" ").length;
  return Math.max(1, cols);
}

/* ---------------------------------------------------------------- actions */

async function openItem(it) {
  if (it.dir) { go(it.path); return; }
  try {
    await api("/api/open", { body: { path: it.path } });
    toast(`Opening ${it.name}`);
  } catch (e) { toast(e.message, "err"); }
}

function ask(label, value = "", okText = "OK") {
  return new Promise((resolve) => {
    const dlg = $("dialog"), input = $("dialog-input");
    $("dialog-label").textContent = label;
    $("dialog-ok").textContent = okText;
    input.value = value;
    dlg.classList.remove("hidden");
    input.focus();
    const dot = value.lastIndexOf(".");
    input.setSelectionRange(0, dot > 0 ? dot : value.length);
    const done = (v) => {
      dlg.classList.add("hidden");
      $("dialog-form").onsubmit = null;
      $("dialog-cancel").onclick = null;
      $("main").focus();
      resolve(v);
    };
    $("dialog-form").onsubmit = (e) => { e.preventDefault(); done(input.value.trim() || null); };
    $("dialog-cancel").onclick = () => done(null);
    input.onkeydown = (e) => { if (e.key === "Escape") { e.stopPropagation(); done(null); } };
  });
}

async function newFolder() {
  if (S.searching) return;
  const name = await ask("New folder name", "New folder", "Create");
  if (!name) return;
  try {
    const { path } = await api("/api/mkdir", { body: { parent: S.path, name } });
    await refresh();
    S.sel = new Set([path]);
    S.anchor = path;
    paintSelection();
  } catch (e) { toast(e.message, "err"); }
}

async function renameSel() {
  const sel = selectedItems();
  if (sel.length !== 1) return;
  const name = await ask(`Rename "${sel[0].name}" to`, sel[0].name, "Rename");
  if (!name || name === sel[0].name) return;
  try {
    const { path } = await api("/api/rename", { body: { path: sel[0].path, name } });
    S.sel = new Set([path]);
    S.anchor = path;
    await (S.searching ? runSearch() : refresh());
  } catch (e) { toast(e.message, "err"); }
}

// A second Delete press (or Restore click) while the first is on its way is
// ignored; different actions don't wait for each other.
const busy = new Set();
async function once(what, fn) {
  if (busy.has(what)) return;
  busy.add(what);
  try { await fn(); } finally { busy.delete(what); }
}

async function trashSel() {
  const sel = selectedItems();
  if (!sel.length) return;
  await once("trash", () => trashNow(sel));
}
async function trashNow(sel) {
  try {
    const out = await api("/api/trash", { body: { paths: sel.map((i) => i.path) } });
    if (out.trashed.length) toast(`Moved ${out.trashed.length} to the trash`);
    for (const f of out.failed) toast(`${baseName(f.path)}: ${f.error}`, "err");
    await (S.searching ? runSearch() : refresh());
  } catch (e) { toast(e.message, "err"); }
}

/* The clipboard every Files window shares lives in the backend (/api/clip):
   Copy or Cut in one window, Paste in another. The folder watch's stamp
   carries its number, so the other windows follow within a few seconds (cut
   items dim), a window catches up when it gets the focus, and Paste asks for
   the latest first. An older backend without the route: this window's own. */
let clipSeq = -1;

function takeClip(c) {
  if (!c || typeof c.seq !== "number" || c.seq < clipSeq) return;  // an older answer
  const changed = c.seq !== clipSeq;
  clipSeq = c.seq;
  if (!changed) return;
  S.clip = c.op === "copy" || c.op === "move" ? { op: c.op, paths: c.paths } : null;
  render();
}

async function shareClip() {
  try { takeClip(await api("/api/clip", { body: S.clip || { op: null, paths: [] } })); }
  catch { /* no shared clipboard: the clip stays in this window */ }
}

async function syncClip() {
  try { takeClip(await api("/api/clip")); } catch { /* as above */ }
}

function setClip(op) {
  const sel = selectedItems();
  if (!sel.length) return;
  S.clip = { op, paths: sel.map((i) => i.path) };
  shareClip();
  toast(`${op === "move" ? "Cut" : "Copied"} ${sel.length} item${sel.length === 1 ? "" : "s"}`);
  // Also put the paths on the system clipboard, so a terminal or editor can take them.
  navigator.clipboard?.writeText(S.clip.paths.join("\n")).catch(() => {});
  render();
}

async function paste(dest = S.path) {
  if (S.searching) return;
  await syncClip();
  if (!S.clip) return;
  const { op, paths } = S.clip;
  await transfer(op, paths, dest);
  if (op === "move") { S.clip = null; shareClip(); }
}

// Copy, move, extract and compress all run as backend jobs; one at a time.
const JOB_WORDS = {
  copy: ["Copying", "Copied"], move: ["Moving", "Moved"],
  extract: ["Extracting", "Extracted"], compress: ["Compressing", "Compressed"],
};
let jobRunning = false;
async function runJob(route, body) {
  if (jobRunning) { toast("Wait for the current job to finish", "err"); return; }
  jobRunning = true;  // before the request, so a quick second Ctrl+V can't start a twin job
  let job;
  try {
    job = await api(route, { body });
  } catch (e) { jobRunning = false; toast(e.message, "err"); return; }
  const [doing, did] = JOB_WORDS[job.op] || ["Working on", "Finished"];
  const items = `${job.count} item${job.count === 1 ? "" : "s"}`;
  $("job").classList.remove("hidden");
  // While the backend doesn't answer, ask less often (0.4 s doubling to 5 s);
  // after about a minute of silence, stop and say the job's fate is unknown.
  let wait = 400, silent = 0;
  while (job.state === "running") {
    const part = job.total ? job.done / job.total : 0;
    $("job-text").textContent = `${doing} ${items}… ${Math.round(part * 100)}%`;
    $("job-bar").value = part;
    await new Promise((r) => setTimeout(r, wait));
    await whenShown();  // the job runs on the server; no need to ask while hidden
    try {
      job = await api(`/api/jobs/${job.id}`);
      wait = 400; silent = 0;
    } catch (e) {
      if (e.status === 404) { job = { ...job, state: "lost" }; break; }  // a restarted backend forgot it
      silent += wait;
      if (silent > 60000) { job = { ...job, state: "lost" }; break; }
      wait = Math.min(wait * 2, 5000);
    }
  }
  jobRunning = false;
  $("job").classList.add("hidden");
  if (job.state === "error") toast(job.error, "err");
  else if (job.state === "lost") toast(`Lost track of ${doing.toLowerCase()} ${items}: the Files backend stopped answering or restarted. Look in the folder to see what arrived.`, "err");
  else toast(`${did} ${items}`);
  if (job.dest === S.path) { S.sel = new Set(job.results || []); }
  await refresh();
}
function whenShown() {
  if (ForgeIdle.shown()) return Promise.resolve();
  return new Promise((resolve) => {
    const on = () => {
      if (!ForgeIdle.shown()) return;
      document.removeEventListener("visibilitychange", on);
      document.removeEventListener("forge-visible", on);
      resolve();
    };
    document.addEventListener("visibilitychange", on);
    document.addEventListener("forge-visible", on);
  });
}
const transfer = (op, paths, dest) => runJob("/api/transfer", { op, paths, dest });
const archive = (op) => runJob("/api/archive", { op, paths: selectedItems().map((i) => i.path) });

async function restoreSel() {
  const sel = selectedItems();
  if (!sel.length) return;
  await once("restore", () => restoreNow(sel));
}
async function restoreNow(sel) {
  try {
    const out = await api("/api/restore", { body: { paths: sel.map((i) => i.path) } });
    if (out.restored.length) toast(`Put ${out.restored.length} back where ${out.restored.length === 1 ? "it was" : "they were"}`);
    for (const f of out.failed) toast(`${baseName(f.path)}: ${f.error}`, "err");
    await refresh();
  } catch (e) { toast(e.message, "err"); }
}
const inTrash = () => !!placesData.trash && S.path === placesData.trash;

function copyPaths() {
  const sel = selectedItems();
  const text = (sel.length ? sel.map((i) => i.path) : [S.path]).join("\n");
  navigator.clipboard?.writeText(text).then(() => toast("Path copied"), () => toast(text));
}

/* Another Forge app, found by its manifest role; the hub passes `hash` on to it.
   Standalone (no hub), the app's own port isn't known here, so say so. */
/* Apps whose manifest says they open this file type ("opens": [".docx"]), from /api/session. */
function openersFor(item) {
  const dot = item.name.lastIndexOf(".");
  return dot > 0 ? (S.openers?.[item.name.slice(dot).toLowerCase()] || []) : [];
}

function openIn(role, hash) {
  if (window.parent === window) { toast("Open this from inside Forge to jump to another app"); return; }
  window.parent.postMessage({ forge: "open", role, hash }, "*");
}

/* Another Files window with its own folder and history (New window, Ctrl+N,
   middle-click a folder). In Forge it is a real window: the hub, or in a
   popped-out window forge_popout's relay, hears {forge: "window", hash} and
   forge.py opens it. Outside Forge (a plain browser) it is a new tab. */
function newWindow(path) {
  const hash = new URLSearchParams({ path: path || S.path || S.home, view: S.prefs.view }).toString();
  const handlers = window.webkit?.messageHandlers;
  if (window.parent !== window || handlers?.forgewindow) {
    window.parent.postMessage({ forge: "window", hash }, "*");  // in a pop-out the parent is the page itself
  } else if (handlers) {
    // a Forge window from before New window existed: no tab in the browser
    toast("Restart Forge to open more Files windows", "err");
  } else window.open(`${location.pathname}#${hash}`, "_blank");
}

/* ---------------------------------------------------------------- context menu */

function showMenu(x, y, entries) {
  const m = $("menu");
  m.replaceChildren();
  for (const e of entries) {
    if (e === "-") { m.append(document.createElement("hr")); continue; }
    const b = document.createElement("button");
    const l = document.createElement("span"); l.textContent = e.label;
    b.append(l);
    if (e.key) { const k = document.createElement("kbd"); k.textContent = e.key; b.append(k); }
    b.disabled = !!e.disabled;
    b.onclick = () => { hideMenu(); e.run(); };
    m.append(b);
  }
  m.classList.remove("hidden");
  const r = m.getBoundingClientRect();
  m.style.left = `${Math.min(x, innerWidth - r.width - 6)}px`;
  m.style.top = `${Math.min(y, innerHeight - r.height - 6)}px`;
}
function hideMenu() { $("menu").classList.add("hidden"); }

function itemMenu(x, y) {
  const sel = selectedItems();
  const one = sel.length === 1 ? sel[0] : null;
  showMenu(x, y, [
    { label: one?.dir ? "Open folder" : "Open", key: "Enter", disabled: !one, run: () => openItem(one) },
    ...(one?.dir ? [{ label: "Open in new window", run: () => newWindow(one.path) }] : []),
    ...(S.searching && one ? [{ label: "Show in folder", run: () => go(one.path.slice(0, one.path.lastIndexOf("/")) || "/") }] : []),
    "-",
    { label: "Cut", key: "Ctrl+X", run: () => setClip("move") },
    { label: "Copy", key: "Ctrl+C", run: () => setClip("copy") },
    { label: "Paste into folder", disabled: !S.clip || !one?.dir, run: () => paste(one.path) },
    "-",
    { label: "Rename", key: "F2", disabled: !one, run: renameSel },
    { label: "Copy path", run: copyPaths },
    ...(one && !one.dir ? openersFor(one).map((o) => ({ label: `Open in ${o.label}`, run: () => openIn(o.role, `open=${encodeURIComponent(one.path)}`) })) : []),
    ...(one && (one.dir || one.kind === "text") ? [{ label: "Open in Code", run: () => openIn("code", `path=${one.path}`) }] : []),
    ...(one?.dir ? [{ label: "Open terminal here", run: () => openIn("terminal", `cwd=${one.path}`) }] : []),
    "-",
    ...(one?.kind === "archive" ? [{ label: "Extract here", run: () => archive("extract") }] : []),
    { label: "Compress to .zip", disabled: S.searching, run: () => archive("compress") },
    "-",
    ...(inTrash() ? [{ label: "Restore", run: restoreSel }] : []),
    { label: "Move to trash", key: "Delete", run: trashSel },
  ]);
}

function folderMenu(x, y) {
  showMenu(x, y, [
    { label: "New folder", key: "Ctrl+Shift+N", disabled: S.searching, run: newFolder },
    { label: "Paste", key: "Ctrl+V", disabled: !S.clip || S.searching, run: () => paste() },
    { label: "New window here", key: "Ctrl+N", run: () => newWindow() },
    "-",
    { label: "Select all", key: "Ctrl+A", run: selectAll },
    { label: S.prefs.hidden ? "Hide hidden files" : "Show hidden files", key: "Ctrl+H", run: toggleHidden },
    { label: "Copy folder path", run: () => { S.sel.clear(); copyPaths(); } },
    { label: "Open terminal here", run: () => openIn("terminal", `cwd=${S.path}`) },
    { label: "Open folder in Code", run: () => openIn("code", `path=${S.path}`) },
    { label: "Open folder in the default app", run: () => api("/api/open", { body: { path: S.path } }).catch((e) => toast(e.message, "err")) },
    { label: "Refresh", key: "F5", run: refresh },
  ]);
}

/* ---------------------------------------------------------------- prefs toggles */

function toggleHidden() { S.prefs.hidden = !S.prefs.hidden; savePrefs(); S.searching ? runSearch() : refresh(); }
function toggleView() { S.prefs.view = S.prefs.view === "grid" ? "list" : "grid"; savePrefs(); render(); }
function togglePreview() { S.prefs.preview = !S.prefs.preview; savePrefs(); previewFor = null; render(); }
function selectAll() { S.sel = new Set(S.shown.map((i) => i.path)); paintSelection(); }

/* ---------------------------------------------------------------- drag and drop */

const DRAG_TYPE = "application/x-forge-files";
let dragPaths = null;

function dropTarget(el) {
  const row = rowOf(el);
  if (row) {
    const it = S.shown.find((i) => i.path === row.dataset.path);
    return it?.dir && !dragPaths?.includes(it.path) ? { el: row, path: it.path } : null;
  }
  const d = el?.closest?.("[data-drop]");
  if (d) return { el: d, path: d.dataset.path };
  if (el?.closest?.("#main") && !S.searching) return { el: $("items"), path: S.path };
  return null;
}

function wireDnd() {
  document.addEventListener("dragstart", (e) => {
    const row = rowOf(e.target);
    if (!row) return;
    if (!S.sel.has(row.dataset.path)) { S.sel = new Set([row.dataset.path]); S.anchor = row.dataset.path; paintSelection(); }
    dragPaths = selectedItems().map((i) => i.path);
    e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(dragPaths));
    e.dataTransfer.setData("text/plain", dragPaths.join("\n"));
    // file:// links, so a desktop file manager or another app can take them
    e.dataTransfer.setData("text/uri-list", dragPaths.map(fileUri).join("\r\n"));
    e.dataTransfer.effectAllowed = "copyMove";
  });
  document.addEventListener("dragend", () => { dragPaths = null; clearDrop(); });
  let lastDrop = null;
  const clearDrop = () => { lastDrop?.classList.remove("drop"); lastDrop = null; };
  document.addEventListener("dragover", (e) => {
    const outside = isOutsideDrag(e.dataTransfer);
    if (!dragPaths && !outside) return;
    const t = dropTarget(e.target);
    if (!t) { clearDrop(); return; }
    e.preventDefault();
    e.dataTransfer.dropEffect = outside || e.ctrlKey ? "copy" : "move";
    if (t.el !== lastDrop) { clearDrop(); t.el?.classList.add("drop"); lastDrop = t.el; }
  });
  document.addEventListener("dragleave", (e) => { if (!e.relatedTarget) clearDrop(); });
  document.addEventListener("drop", (e) => {
    const outside = isOutsideDrag(e.dataTransfer);
    if (!dragPaths && !outside) return;
    const t = dropTarget(e.target);
    clearDrop();
    if (!t) return;
    e.preventDefault();
    if (outside) { dropIn(e.dataTransfer, t.path); return; }
    const paths = dragPaths;
    dragPaths = null;
    transfer(e.ctrlKey ? "copy" : "move", paths, t.path);
  });
}

/* Drops from outside Forge (a desktop file manager, a download in a browser).
   Real paths (file:// links) are copied by the backend as a normal job; when
   the page only gets the files themselves, they are uploaded one by one.
   A drop from outside always copies; it never moves anything. */
const fileUri = (p) => "file://" + p.split("/").map(encodeURIComponent).join("/");
const isOutsideDrag = (dt) =>
  !dragPaths && [...(dt?.types || [])].some((t) => t === "Files" || t === "text/uri-list");

function dropIn(dt, dest) {
  // read everything now: the browser empties the drop's data once this returns
  const paths = (dt.getData("text/uri-list") || "").split(/\r?\n/)
    .filter((l) => l.startsWith("file://"))
    .map((l) => { try { return decodeURIComponent(new URL(l).pathname); } catch { return ""; } })
    .filter(Boolean);
  if (paths.length) { transfer("copy", paths, dest); return; }
  const files = [], folders = [];
  for (const it of dt.items || []) {
    if (it.kind !== "file") continue;
    const entry = it.webkitGetAsEntry?.();
    const f = it.getAsFile();
    if (entry?.isDirectory) folders.push(entry.name);
    else if (f) files.push(f);
  }
  if (!dt.items?.length) files.push(...dt.files);
  if (folders.length) toast(`Folders from outside can't come in this way (${folders.join(", ")}); drop the files inside them`, "err");
  if (files.length) uploadFiles(files, dest);
  else if (!folders.length) toast("Only files can be dropped here", "err");
}

async function uploadFiles(files, dest) {
  if (jobRunning) { toast("Wait for the current job to finish", "err"); return; }
  jobRunning = true;
  const label = `${files.length} file${files.length === 1 ? "" : "s"}`;
  const total = files.reduce((a, f) => a + f.size, 0) || 1;
  let sent = 0;
  const show = (now) => {
    const part = Math.min(1, (sent + now) / total);
    $("job-text").textContent = `Copying in ${label}… ${Math.round(part * 100)}%`;
    $("job-bar").value = part;
  };
  $("job").classList.remove("hidden");
  const results = [];
  for (const f of files) {
    show(0);
    try { results.push((await sendFile(f, dest, show)).path); }
    catch (e) { toast(`${f.name}: ${e.message}`, "err"); }
    sent += f.size;
  }
  jobRunning = false;
  $("job").classList.add("hidden");
  if (results.length) toast(results.length === files.length ? `Copied in ${label}` : `Copied in ${results.length} of ${label}`);
  if (dest === S.path) S.sel = new Set(results);
  await refresh();
}

function sendFile(file, dest, show) {
  // XMLHttpRequest rather than fetch: it reports upload progress
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", `/api/upload?${q({ dest, name: file.name })}`);
    x.setRequestHeader("X-Forge", "1");
    x.upload.onprogress = (e) => show(e.loaded);
    x.onload = () => {
      let body = {};
      try { body = JSON.parse(x.responseText); } catch { /* not JSON: the status says enough */ }
      if (x.status === 200) resolve(body);
      else reject(new Error(typeof body.detail === "string" ? body.detail : `The backend said ${x.status}`));
    };
    x.onerror = () => reject(new Error("The Files backend isn't answering. Try again in a moment."));
    x.send(file);
  });
}

/* ---------------------------------------------------------------- rubber-band selection */

let banding = false;  // a rubber band is being drawn: the folder watch waits
function wireRubber() {
  const main = $("items");
  let start = null, box = null, base = null;
  main.addEventListener("mousedown", (e) => {
    if (e.button !== 0 || rowOf(e.target)) return;
    const r = main.getBoundingClientRect();
    start = { x: e.clientX - r.left, y: e.clientY - r.top + main.scrollTop };
    base = e.ctrlKey || e.shiftKey ? new Set(S.sel) : new Set();
    banding = true;
    if (!e.ctrlKey && !e.shiftKey) { S.sel.clear(); paintSelection(); }
  });
  document.addEventListener("mousemove", (e) => {
    if (!start) return;
    const r = main.getBoundingClientRect();
    const cur = { x: e.clientX - r.left, y: e.clientY - r.top + main.scrollTop };
    if (!box) {
      if (Math.abs(cur.x - start.x) + Math.abs(cur.y - start.y) < 6) return;
      box = document.createElement("div");
      box.className = "rubber";
      main.style.position = "relative";
      main.append(box);
    }
    const x0 = Math.min(start.x, cur.x), y0 = Math.min(start.y, cur.y);
    const x1 = Math.max(start.x, cur.x), y1 = Math.max(start.y, cur.y);
    Object.assign(box.style, { left: `${x0}px`, top: `${y0}px`, width: `${x1 - x0}px`, height: `${y1 - y0}px` });
    S.sel = new Set(base);
    for (const row of main.querySelectorAll(".item")) {
      const b = row.getBoundingClientRect();
      const bx = b.left - r.left, by = b.top - r.top + main.scrollTop;
      if (bx < x1 && bx + b.width > x0 && by < y1 && by + b.height > y0) S.sel.add(row.dataset.path);
    }
    for (const row of main.querySelectorAll(".item")) row.classList.toggle("sel", S.sel.has(row.dataset.path));
    updateStatus();
  });
  document.addEventListener("mouseup", () => {
    if (box) { box.remove(); renderPreview(); }
    start = box = null;
    banding = false;
  });
}

/* ---------------------------------------------------------------- wiring */

function wire() {
  $("back").onclick = goBack;
  $("fwd").onclick = goFwd;
  $("up").onclick = goUp;
  $("new-folder").onclick = newFolder;
  $("new-window").onclick = () => newWindow();
  $("view").onclick = toggleView;
  $("hidden").onclick = toggleHidden;
  $("preview-toggle").onclick = togglePreview;
  $("sort").onchange = () => { S.prefs.sort = $("sort").value; savePrefs(); render(); };
  $("sort-dir").onclick = () => { S.prefs.dir *= -1; savePrefs(); render(); };
  for (const h of document.querySelectorAll(".list-head span")) {
    h.onclick = () => {
      if (S.prefs.sort === h.dataset.sort) S.prefs.dir *= -1;
      else { S.prefs.sort = h.dataset.sort; S.prefs.dir = h.dataset.sort === "name" || h.dataset.sort === "kind" ? 1 : -1; }
      savePrefs(); render();
    };
  }

  let searchTimer = 0;
  $("search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 300); });
  $("search").addEventListener("keydown", (e) => {
    if (e.key === "Escape") { $("search").value = ""; refresh(); $("main").focus(); }
    if (e.key === "Enter") { clearTimeout(searchTimer); runSearch(); }
  });

  const pathEdit = $("path-edit");
  const editPath = () => {
    $("crumbs").classList.add("hidden");
    pathEdit.classList.remove("hidden");
    pathEdit.value = S.path;
    pathEdit.focus();
    pathEdit.select();
  };
  const endEdit = () => { pathEdit.classList.add("hidden"); $("crumbs").classList.remove("hidden"); };
  $("crumbs").ondblclick = editPath;
  pathEdit.onkeydown = async (e) => {
    if (e.key === "Enter") { if (await go(pathEdit.value.trim())) { endEdit(); $("main").focus(); } }
    if (e.key === "Escape") { endEdit(); $("main").focus(); }
  };
  pathEdit.onblur = endEdit;

  const items = $("items");
  items.addEventListener("click", (e) => { const r = rowOf(e.target); if (r) clickSelect(r.dataset.path, e); });
  // Middle-click a folder: it opens in a new window, this one stays put.
  items.addEventListener("mousedown", (e) => { if (e.button === 1) e.preventDefault(); });  // no autoscroll
  items.addEventListener("auxclick", (e) => {
    if (e.button !== 1) return;
    const r = rowOf(e.target);
    const it = r && S.shown.find((i) => i.path === r.dataset.path);
    if (it?.dir) { e.preventDefault(); newWindow(it.path); }
  });
  items.addEventListener("dblclick", (e) => {
    const r = rowOf(e.target);
    const it = r && S.shown.find((i) => i.path === r.dataset.path);
    if (it) openItem(it);
  });
  $("main").addEventListener("contextmenu", (e) => {
    e.preventDefault();
    const r = rowOf(e.target);
    if (r) {
      if (!S.sel.has(r.dataset.path)) clickSelect(r.dataset.path, {});
      itemMenu(e.clientX, e.clientY);
    } else folderMenu(e.clientX, e.clientY);
  });
  $("main").addEventListener("wheel", (e) => {
    if (!e.ctrlKey || S.prefs.view !== "grid") return;
    e.preventDefault();
    S.prefs.tile = Math.max(80, Math.min(260, S.prefs.tile - Math.sign(e.deltaY) * 20));
    savePrefs();
    $("main").style.setProperty("--tile", `${S.prefs.tile}px`);
  }, { passive: false });
  document.addEventListener("mousedown", (e) => { if (!e.target.closest("#menu")) hideMenu(); });
  document.addEventListener("mouseup", (e) => {
    if (e.button === 3) goBack();
    if (e.button === 4) goFwd();
  });

  document.addEventListener("keydown", onKey);
  wireDnd();
  wireRubber();
}

function onKey(e) {
  const typing = e.target.matches("input, textarea, select");
  const ctrl = e.ctrlKey || e.metaKey;
  const k = e.key;
  if (!$("dialog").classList.contains("hidden")) return;
  if (k === "Escape") { hideMenu(); if (!typing && S.sel.size) { S.sel.clear(); paintSelection(); } return; }
  if (ctrl && k.toLowerCase() === "l") { e.preventDefault(); $("crumbs").ondblclick(); return; }
  if (ctrl && k.toLowerCase() === "f") { e.preventDefault(); $("search").focus(); $("search").select(); return; }
  if (ctrl && k.toLowerCase() === "h") { e.preventDefault(); toggleHidden(); return; }
  if (ctrl && k.toLowerCase() === "g") { e.preventDefault(); toggleView(); return; }
  if (ctrl && e.shiftKey && k.toLowerCase() === "n") { e.preventDefault(); newFolder(); return; }
  if (ctrl && !e.shiftKey && k.toLowerCase() === "n") { e.preventDefault(); if (!e.repeat) newWindow(); return; }
  if (k === "F3") { e.preventDefault(); togglePreview(); return; }
  if (k === "F5") { e.preventDefault(); refresh(); return; }
  if (e.altKey && k === "ArrowLeft") { e.preventDefault(); goBack(); return; }
  if (e.altKey && k === "ArrowRight") { e.preventDefault(); goFwd(); return; }
  if (e.altKey && k === "ArrowUp") { e.preventDefault(); goUp(); return; }
  if (typing) return;
  if (ctrl && k.toLowerCase() === "a") { e.preventDefault(); selectAll(); return; }
  if (ctrl && k.toLowerCase() === "c") { e.preventDefault(); setClip("copy"); return; }
  if (ctrl && k.toLowerCase() === "x") { e.preventDefault(); setClip("move"); return; }
  if (ctrl && k.toLowerCase() === "v") { e.preventDefault(); paste(); return; }
  if (k === "Delete") { e.preventDefault(); trashSel(); return; }
  if (k === "F2") { e.preventDefault(); renameSel(); return; }
  if (k === "Backspace") { e.preventDefault(); goBack(); return; }
  if (k === "Enter") {
    const sel = selectedItems();
    if (sel.length === 1) openItem(sel[0]);
    return;
  }
  const cols = gridColumns();
  if (k === "ArrowDown") { e.preventDefault(); moveCursor(cols, e); return; }
  if (k === "ArrowUp") { e.preventDefault(); moveCursor(-cols, e); return; }
  if (cols > 1 && k === "ArrowRight") { e.preventDefault(); moveCursor(1, e); return; }
  if (cols > 1 && k === "ArrowLeft") { e.preventDefault(); moveCursor(-1, e); return; }
  if (k === "Home") { e.preventDefault(); moveCursor(-1e9, e); return; }
  if (k === "End") { e.preventDefault(); moveCursor(1e9, e); return; }
  // Type-ahead: jump to the first name starting with what was typed.
  if (k.length === 1 && !ctrl && !e.altKey) typeAhead(k);
}

let typed = "", typedAt = 0;
function typeAhead(ch) {
  const now = Date.now();
  typed = now - typedAt > 800 ? ch : typed + ch;
  typedAt = now;
  const hit = S.shown.find((i) => i.name.toLowerCase().startsWith(typed.toLowerCase()));
  if (hit) selectPath(hit.path);
}

/* Offline: a chip in the status bar while the backend doesn't answer. Coming
   back reloads the folder, since anything may have changed meanwhile. */
let online = true;
function setOnline(on) {
  if (on === online) return;
  online = on;
  $("conn").classList.toggle("hidden", on);
  if (on && S.path) refresh();
}

async function startSession() {
  try {
    const s = await api("/api/session");
    S.token = s.token;
    S.home = s.home;
    S.openers = s.openers || {};
    placesData = s;
    return true;
  } catch { return false; }
}

/* A restarted backend hands out a new token, and thumbnails and previews
   drawn with the old one break: fetch it again and redraw when it changed. */
async function syncToken() {
  try {
    const s = await api("/api/session");
    if (s.token === S.token) return;
    S.token = s.token;
    render();
  } catch { /* the drive poll will notice */ }
}

function offlineCard() {
  const empty = $("empty");
  empty.replaceChildren();
  const h = document.createElement("strong");
  h.textContent = "Can't reach the Files backend";
  const p = document.createElement("p");
  p.className = "muted small";
  p.textContent = "Trying again by itself. It may still be starting.";
  const b = actionBtn("Try now", () => waiter.now());
  empty.append(h, p, b);
  empty.classList.remove("hidden");
  let waiter = ForgeIdle.poll(async () => {
    if (!(await startSession())) return false;
    waiter.stop();
    empty.replaceChildren();
    $("conn").classList.add("hidden");
    online = true;
    await openStart();
  }, 3000, { backoff: 2, maxMs: 30000 });
}

async function boot() {
  wire();
  if (!(await startSession())) { $("conn").classList.remove("hidden"); online = false; offlineCard(); return; }
  await openStart();
}

async function openStart() {
  // #path=/some/folder opens there (other apps can link in); else the last folder.
  // #path=/folder opens there, #select=/folder/file opens its folder with it
  // selected, #view=grid|list picks the view: other apps link in this way.
  const h = new URLSearchParams(location.hash.slice(1));
  const pick = h.get("select");
  if (["grid", "list"].includes(h.get("view"))) S.prefs.view = h.get("view");
  let start = h.get("path") || (pick ? pick.slice(0, pick.lastIndexOf("/")) : "");
  if (!start) { try { start = localStorage.getItem("files.last") || S.home; } catch { start = S.home; } }
  if (!(await go(start, { push: false }))) await go(S.home, { push: false });
  if (pick) selectPath(pick);
  syncClip();
  addEventListener("focus", syncClip);
  $("main").focus();
  // Drives come and go; look again every so often while visible. The same
  // check notices the backend going away, and asks less often until it's back.
  ForgeIdle.poll(async () => {
    try {
      const s = await api("/api/session");
      if (JSON.stringify(s.drives) !== JSON.stringify(placesData.drives)) { placesData = s; renderSide(); }
      const fresh = s.token !== S.token;
      S.token = s.token;  // a restarted backend has a new token for thumbnails
      if (fresh && online) render();  // coming back from offline redraws anyway
      setOnline(true);
    } catch {
      setOnline(false);
      return false;
    }
  }, 10000, { backoff: 2, maxMs: 30000 });
  watchFolder();
}

/* The open folder redraws by itself when something lands in it or leaves it
   (a finished download, another app saving): a cheap stamp check every 3 s
   while the page is shown, and a relist only when the stamp moved. It waits
   while a search, a drag, a rubber band or a dialog is on screen, and stands
   aside for a folder you opened that is still loading (or opened while its
   stamp check was out), so it never reloads the old folder over the new. */
function watchFolder() {
  ForgeIdle.poll(async () => {
    const path = S.path;
    const seq = navSeq;
    if (!online || !path || S.searching || dragPaths || banding) return;
    if (seq !== settledSeq) return;
    if (!$("dialog").classList.contains("hidden")) return;
    let s;
    try { s = await api(`/api/stamp?${q({ path })}`); }
    catch (e) {
      if (e.status !== 400) return false;  // backend away: the drive poll says so
      if (path !== S.path || seq !== navSeq) return;
      toast(`${baseName(path)} isn't there any more; showing the folder above it`);
      if (!(await go(S.parent || S.home, { push: false }))) await go(S.home, { push: false });
      return;
    }
    if (typeof s.clip === "number" && s.clip !== clipSeq) syncClip();
    if (seq !== navSeq || path !== S.path || S.searching) return;
    if (s.stamp !== S.stamp) await refresh();
  }, 3000, { backoff: 2, maxMs: 30000 });
}

function selectPath(path) {
  if (!S.shown.some((i) => i.path === path)) return;
  S.sel = new Set([path]);
  S.anchor = path;
  paintSelection();
  $("items").querySelector(`.item[data-path="${CSS.escape(path)}"]`)?.scrollIntoView({ block: "nearest" });
}

addEventListener("hashchange", async () => {
  const h = new URLSearchParams(location.hash.slice(1));
  const pick = h.get("select");
  const p = h.get("path") || (pick ? pick.slice(0, pick.lastIndexOf("/")) : "");
  if (p && p !== S.path) await go(p);
  if (pick) selectPath(pick);
});

boot();
