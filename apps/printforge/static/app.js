// PrintForge page logic: library list, loading, info panel and settings.
import { Viewer, parseSTL } from "/viewer.js";

const $ = (id) => document.getElementById(id);
const viewer = new Viewer($("view"));
const COLOURS = ["#c9c3b5", "#e8e4da", "#9aa0a8", "#4a4f57", "#b8a47a", "#7a8f5a", "#d9824a"];
let settings = {};
let files = [];
let rootsShown = [];
let current = null;
let loading = null; // AbortController of the download in flight
let shown = ""; // key of the print on the bed, so a second click does not download it again
let lastInfo = null; // check result of the open print
let openSeq = 0; // bumps on every open, so a late answer for an older open is dropped
let restat = false; // a size-and-time read of the open print is on its way
let checkFailed = false; // the open print's check failed; a click on it tries again
let overhangOn = false;
const MODE_KEY = "printforge.advanced";

const mb = (b) => (b / 1e6).toFixed(1) + " MB";
const num = (x) => Number(x).toLocaleString();
const esc = (t) => String(t).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

async function api(path, opts) {
  let r;
  try {
    r = await fetch(path, opts);
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new Error("the PrintForge server is not answering");
  }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

// Saves and says so when it could not; true when the save went through.
async function saveSettings(values) {
  try {
    settings = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values: { ...values, advanced_mode: ForgeMode.saved } }),
    });
    return true;
  } catch (e) {
    toast("Could not save: " + e.message, "err");
    return false;
  }
}

// One save after the last change of a slider, not one per step of the drag.
function saveLater(values) {
  saveLater.pending = { ...saveLater.pending, ...values };
  clearTimeout(saveLater.t);
  saveLater.t = setTimeout(() => {
    const v = saveLater.pending;
    saveLater.pending = {};
    saveSettings(v);
  }, 400);
}

// Same path, size and time: the same file, already on show. The time is the
// server's nanosecond count, kept as a string so it compares exactly; whole
// seconds missed a same-size export made again within the same second.
const keyOf = (f) => `${f.path}|${f.bytes}|${f.mtime_ns}`;

// Runs a button's job once at a time, so a double click does it once.
function once(button, job) {
  button.onclick = async () => {
    if (button.disabled) return;
    button.disabled = true;
    try {
      await job();
    } finally {
      button.disabled = false;
    }
  };
}

const fileLabel = (f) => [mb(f.bytes), f.triangles ? num(f.triangles) + " triangles" : "", f.scale ? "scale " + f.scale : ""].filter(Boolean).join(" · ");

function renderLibrary() {
  const q = $("search").value.trim().toLowerCase();
  const box = $("files");
  box.innerHTML = "";
  let lastProj = null;
  let lastFold = null;
  const shown = files.filter((f) => !q || (f.project + " " + f.folder + " " + f.name).toLowerCase().includes(q));
  for (const f of shown) {
    if (f.project !== lastProj) {
      box.insertAdjacentHTML("beforeend", `<div class="proj"></div>`);
      box.lastChild.textContent = f.project;
      lastProj = f.project;
      lastFold = null;
    }
    if (f.folder !== lastFold) {
      if (f.folder) {
        box.insertAdjacentHTML("beforeend", `<div class="fold"></div>`);
        box.lastChild.textContent = f.folder;
      }
      lastFold = f.folder;
    }
    const b = document.createElement("button");
    b.className = "file" + (current && current.path === f.path ? " on" : "");
    b.dataset.path = f.path;
    b.textContent = f.name.replace(/_/g, " ");
    const small = document.createElement("small");
    small.textContent = fileLabel(f);
    b.appendChild(small);
    b.onclick = () => openFile(f);
    box.appendChild(b);
  }
  if (!shown.length) {
    box.innerHTML = `<div class="hint"></div>`;
    box.firstChild.textContent = files.length ? `No print matches "${$("search").value.trim()}".` : "No STL files found in these folders.";
  }
  $("rootsHint").textContent = "Searching: " + (rootsShown.length ? rootsShown : settings.roots || []).join(", ");
}

async function fetchWithProgress(url, signal, onProgress) {
  const r = await fetch(url, { signal });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "the server said " + r.status);
  const total = +r.headers.get("Content-Length") || 0;
  const reader = r.body.getReader();
  const parts = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value);
    got += value.length;
    if (total) onProgress(got / total);
  }
  const out = new Uint8Array(got);
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out.buffer;
}

function status(text, frac) {
  $("status").firstChild.textContent = text;
  $("status").style.display = text ? "" : "none";
  $("bar").style.display = frac === undefined ? "none" : "block";
  if (frac !== undefined) $("bar").firstChild.style.width = Math.round(frac * 100) + "%";
}

// Marks the open print in the list without rebuilding it, so the list keeps
// its scroll and the clicked button keeps keyboard focus.
function markSelected() {
  for (const b of $("files").querySelectorAll(".file")) b.classList.toggle("on", !!current && b.dataset.path === current.path);
}

// Reads the open print's size and time again (cheap, nothing downloaded) and
// updates its line in the list. True when it is still the file on the bed,
// false when it was exported again, null when the server could not say.
async function onDisk(f) {
  try {
    Object.assign(f, await api("/api/stat?path=" + encodeURIComponent(f.path)));
  } catch (e) {
    return null;
  }
  for (const b of $("files").querySelectorAll(".file")) if (b.dataset.path === f.path) b.lastChild.textContent = fileLabel(f);
  return keyOf(f) === shown;
}

// A click on the open print downloads it again only when the file changed on
// disk (exported again), or retries its check when that failed. `auto` is the
// same look when the page comes back into view: it reloads only a print that
// was on show and has changed, once its size has stopped moving (an export
// still being written is left for the next look).
async function openFile(f, auto = false) {
  if (current && current.path === f.path) {
    if (loading || restat || (auto && !shown)) return;
    const seq = openSeq;
    restat = true;
    let same;
    try {
      same = shown ? await onDisk(f) : false;
      if (auto && same === false) {
        const was = keyOf(f);
        await new Promise((r) => setTimeout(r, 800));
        if ((await onDisk(f)) !== false || keyOf(f) !== was) same = null;
      }
    } finally {
      restat = false;
    }
    if (seq !== openSeq) return; // another print was picked meanwhile
    if (same) {
      current = f;
      if (checkFailed && !auto) await runCheck(f, seq);
      return;
    }
    if (auto && same === null) return;
  } else if (auto) {
    return;
  }
  const seq = ++openSeq;
  const again = current && current.path === f.path && shown;
  current = f;
  lastInfo = null;
  checkFailed = false;
  markSelected();
  $("title").textContent = f.name.replace(/_/g, " ");
  $("facts").innerHTML = "";
  $("fitsBox").innerHTML = "";
  $("reportBox").innerHTML = "";
  $("openFolder").disabled = false;
  const what = again ? `The file has changed: loading the new version, ${mb(f.bytes)}` : `Loading ${mb(f.bytes)}`;
  status(what, 0);
  if (loading) loading.abort();
  const mine = (loading = new AbortController());
  try {
    const buf = await fetchWithProgress("/api/stl?path=" + encodeURIComponent(f.path), mine.signal, (x) => status(what, x));
    if (seq !== openSeq) return;
    status("Building the view");
    await new Promise((r) => setTimeout(r, 0));
    if (seq !== openSeq) return;
    const positions = parseSTL(buf);
    if (positions.length < 9 || !positions.every(Number.isFinite)) {
      viewer.clear();
      shown = "";
      status(positions.length < 9 ? "This file has no triangles to show" : "This file looks damaged: some corners are not numbers");
    } else {
      viewer.setOverhang(overhangOn, settings.overhang_angle);
      viewer.setMesh(positions);
      shown = keyOf(f);
      status("");
    }
  } catch (e) {
    if (e.name !== "AbortError" && seq === openSeq) {
      viewer.clear();
      shown = "";
      status("Could not open this file: " + e.message);
    }
    return;
  } finally {
    if (loading === mine) loading = null;
  }
  await runCheck(f, seq);
}

async function runCheck(f, seq) {
  checkFailed = false;
  $("facts").innerHTML = `<tr><td>Checking</td><td>reading every triangle</td></tr>`;
  try {
    const info = await api("/api/info?path=" + encodeURIComponent(f.path));
    if (seq !== openSeq) return;
    lastInfo = info;
    showInfo(info);
    showReport(info.report);
  } catch (e) {
    if (seq !== openSeq) return;
    checkFailed = true;
    $("facts").innerHTML = `<tr><td>Check failed</td><td></td></tr>`;
    $("facts").querySelector("td:last-child").textContent = `${e.message}. Click the print in the list to try again.`;
  }
}

function showInfo(i) {
  if (!i.triangles) {
    $("facts").innerHTML = `<tr><td>Triangles</td><td><span class="badge bad">none: the file is empty</span></td></tr><tr><td>File</td><td>${mb(i.bytes)}</td></tr>`;
    return;
  }
  const s = i.size_mm || [0, 0, 0];
  const rows = [
    ["Size", `${s[0]} × ${s[1]} × ${s[2]} mm`],
    ["Scale", i.scale || "as modelled"],
    ["Triangles", num(i.triangles)],
    ["File", mb(i.bytes)],
    ["Volume", `${i.volume_cm3} cm³ (about ${Math.round(i.volume_cm3)} ml of resin if solid)`],
    ["Surface", `${i.area_cm2} cm²`],
    ["Watertight", i.watertight ? `<span class="badge good">yes</span>` : i.open_edges ? `<span class="badge bad">no: ${num(i.open_edges)} open edges</span>` : `<span class="badge bad">almost: ${num(i.repeated_edges)} edges where two parts touch along a line</span>`],
    ["Pieces", i.shells === 1 ? `<span class="badge good">one piece</span>` : `<span class="badge bad">${i.shells} separate pieces</span>`],
  ];
  if (i.overhang_cm2) rows.push(["Overhangs", `<span id="ohCell">${overhangText(i)}</span>`]);
  if (i.inside_out) rows.push(["Normals", `<span class="badge bad">inside out</span>`]);
  $("facts").innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
  const fits = i.fits || {};
  $("fitsBox").innerHTML =
    `<h3>Fits these beds</h3>` +
    Object.entries(fits)
      .map(([name, f]) => {
        const tag = f.upright ? `<span class="badge good">standing</span>` : f.any_orientation ? `<span class="badge good">laid over</span>` : `<span class="badge bad">too big</span>`;
        return `<div class="pair"><label style="width:auto;flex:1">${esc(name)}</label>${tag}</div>`;
      })
      .join("");
}

// Area that faces down steeper than the support angle (bed faces left out).
function overhangText(i) {
  const angle = settings.overhang_angle;
  const a = (i.overhang_cm2 || {})[String(angle)];
  if (a === undefined) return "not checked";
  if (!a) return `<span class="badge good">none past ${angle}°</span>`;
  return `<span class="oh-key"></span>${a} cm² past ${angle}° needs support`;
}

// The print pipeline's build report for this file, when one names it.
function showReport(r) {
  const box = $("reportBox");
  if (!r) {
    box.innerHTML = "";
    return;
  }
  const show = (v) =>
    typeof v === "boolean" ? (v ? "yes" : "no")
    : typeof v === "number" ? num(v)
    : Array.isArray(v) ? v.map(show).join(v.every((x) => typeof x === "number") ? " × " : ", ")
    : String(v);
  const when = new Date(r.modified * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  box.innerHTML = `<h3>Build report</h3><table></table><div class="hint"></div>`;
  const table = box.querySelector("table");
  for (const [k, v] of [["Milestone", r.milestone], ["Part", r.entry], ...r.facts]) {
    if (v === null || v === undefined) continue;
    const tr = table.insertRow();
    tr.insertCell().textContent = k;
    tr.insertCell().textContent = show(v);
  }
  box.querySelector(".hint").textContent =
    `From ${r.report}, ${when}` +
    (r.others ? ` (newest of ${r.others + 1} reports naming this file)` : "") +
    (r.stl_newer ? ". The file has changed since this report." : ".");
}

function bedSize() {
  return settings.beds[settings.bed] || Object.values(settings.beds)[0];
}

function fillBeds() {
  const sel = $("bed");
  sel.innerHTML = "";
  for (const [name, d] of Object.entries(settings.beds)) {
    const o = document.createElement("option");
    o.value = name;
    o.textContent = `${name} (${d.join(" × ")})`;
    sel.appendChild(o);
  }
  sel.value = settings.bed in settings.beds ? settings.bed : Object.keys(settings.beds)[0];
  const [x, y, z] = bedSize();
  for (const [id, v] of [["bx", x], ["by", y], ["bz", z]]) {
    $(id).value = v;
    $(id + "N").value = v;
  }
}

function pair(id, onChange) {
  const r = $(id);
  const n = $(id + "N");
  r.addEventListener("input", () => { n.value = r.value; onChange(+r.value); });
  n.addEventListener("change", () => { r.value = n.value; onChange(+n.value); });
}

async function loadLibrary() {
  const lib = await api("/api/library");
  files = lib.files;
  rootsShown = lib.roots_shown || lib.roots || [];
  renderLibrary();
}

// A library read that fails retries by itself through ForgeIdle.poll: 2 s
// doubling to 30 s, resting while the page is hidden, ended by a read that
// works or by the next rescan (so Save and rescan never waits on it).
let libraryRetry = null;
function libraryFailed(e) {
  $("files").innerHTML = `<div class="hint"></div>`;
  $("files").firstChild.textContent = `Could not read the library: ${e.message}. Trying again by itself; fix the folders below and press Save and rescan.`;
}
async function loadLibraryUntilItWorks() {
  if (libraryRetry) libraryRetry.stop();
  libraryRetry = null;
  try {
    await loadLibrary();
    return true;
  } catch (e) {
    libraryFailed(e);
  }
  const retry = ForgeIdle.poll(async () => {
    try {
      await loadLibrary();
    } catch (e) {
      if (libraryRetry === retry) libraryFailed(e);
      return false;
    }
    retry.stop();
    if (libraryRetry === retry) libraryRetry = null;
    return true;
  }, 2000, { backoff: 2, maxMs: 30000 });
  libraryRetry = retry;
  return false;
}

async function start(wait = 2000) {
  try {
    settings = await api("/api/settings");
  } catch (e) {
    status(`PrintForge could not start: ${e.message}. Trying again in ${Math.round(wait / 1000)} s.`);
    setTimeout(() => start(Math.min(wait * 2, 30000)), wait);
    return;
  }
  status("Pick a print on the left");
  await main();
}

async function main() {
  ForgeMode.init(settings.advanced_mode);
  // remember the mode for the first frame of the next visit (see index.html)
  const keepMode = () => {
    try {
      localStorage.setItem(MODE_KEY, ForgeMode.on ? "1" : "0");
    } catch (e) {
      /* private mode: the sections just pop in as before */
    }
  };
  keepMode();
  new MutationObserver(keepMode).observe(document.body, { attributes: true, attributeFilter: ["class"] });
  fillBeds();
  viewer.setBed(bedSize(), true);
  viewer.setColor(settings.color);
  viewer.setLight(settings.light);
  $("light").value = $("lightN").value = settings.light;
  $("roots").value = settings.roots.join("\n");
  for (const c of COLOURS) {
    const d = document.createElement("div");
    d.className = "swatch" + (c === settings.color ? " on" : "");
    d.style.background = c;
    d.title = c;
    d.onclick = () => {
      document.querySelectorAll(".swatch").forEach((x) => x.classList.remove("on"));
      d.classList.add("on");
      viewer.setColor(c);
      saveLater({ color: c });
    };
    $("swatches").appendChild(d);
  }
  document.querySelectorAll("[data-view]").forEach((b) => (b.onclick = () => {
    viewer.setView(b.dataset.view);
    document.querySelectorAll("[data-view]").forEach((x) => x.classList.toggle("on", x === b));
  }));
  $("view").addEventListener("orbit", () => document.querySelectorAll("[data-view]").forEach((x) => x.classList.remove("on")));
  let spin = false;
  $("spin").onclick = () => { spin = !spin; viewer.setAutoRotate(spin); $("spin").classList.toggle("on", spin); };
  let wire = false;
  $("wire").onclick = () => { wire = !wire; viewer.setWireframe(wire); $("wire").classList.toggle("on", wire); };
  $("overhang").onclick = () => {
    overhangOn = !overhangOn;
    viewer.setOverhang(overhangOn, settings.overhang_angle);
    $("overhang").classList.toggle("on", overhangOn);
  };
  $("ohAngle").value = $("ohAngleN").value = settings.overhang_angle;
  pair("ohAngle", (v) => {
    const angle = Math.min(80, Math.max(30, Math.round(v / 5) * 5));
    $("ohAngle").value = $("ohAngleN").value = angle;
    settings.overhang_angle = angle;
    viewer.setOverhang(overhangOn, angle);
    if (lastInfo && $("ohCell")) $("ohCell").innerHTML = overhangText(lastInfo);
    saveLater({ overhang_angle: angle });
  });
  let bedOn = true;
  $("bedToggle").classList.add("on");
  $("bedToggle").onclick = () => { bedOn = !bedOn; viewer.setBed(bedSize(), bedOn); $("bedToggle").classList.toggle("on", bedOn); };
  $("bed").onchange = () => { settings.bed = $("bed").value; fillBeds(); viewer.setBed(bedSize(), bedOn); saveSettings({ bed: settings.bed }); };
  pair("light", (v) => { viewer.setLight(v); saveLater({ light: v }); });
  const custom = () => [+$("bx").value, +$("by").value, +$("bz").value];
  for (const id of ["bx", "by", "bz"]) pair(id, () => viewer.setBed(custom(), bedOn));
  once($("bedSave"), async () => {
    if (!(await saveSettings({ beds: { ...settings.beds, custom: custom() }, bed: "custom" }))) return;
    fillBeds();
    viewer.setBed(bedSize(), bedOn);
  });
  once($("rootsSave"), async () => {
    const roots = $("roots").value.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!(await saveSettings({ roots }))) return;
    $("files").innerHTML = `<div class="hint">Looking for STL files</div>`;
    await loadLibraryUntilItWorks();
  });
  once($("openFolder"), async () => {
    if (!current) return;
    try {
      await api("/api/open-folder", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: current.path }) });
    } catch (e) {
      toast("Could not open the folder: " + e.message, "err");
    }
  });
  $("shot").onclick = () => {
    const a = document.createElement("a");
    a.href = viewer.snapshot();
    a.download = (current ? current.name : "printforge") + ".png";
    a.click();
  };
  $("search").addEventListener("input", renderLibrary);
  document.addEventListener("keydown", (e) => {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "f") viewer.fit();
    if (e.key === "w") $("wire").click();
    if (e.key === "r") $("spin").click();
    if (e.key === "o") $("overhang").click();
  });
  // Back on the page (from Blender, say): pick up a new export of the open print.
  const backInView = () => {
    if (current && ForgeIdle.shown()) openFile(current, true);
  };
  document.addEventListener("visibilitychange", backInView);
  document.addEventListener("forge-visible", backInView);
  window.addEventListener("focus", backInView);
  await loadLibraryUntilItWorks();
  const want = new URLSearchParams(location.search).get("open");
  const first = files.find((f) => want && f.path.includes(want));
  if (first) {
    openFile(first);
    const view = new URLSearchParams(location.search).get("view");
    if (view) {
      setTimeout(() => {
        const button = $("toolbar").querySelector(`[data-view="${view}"]`);
        if (button) button.click();
        else viewer.setView(view);
      }, 0);
    }
  }
}

start();
