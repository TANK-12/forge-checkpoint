/* Typeset: a list of documents, the Typst text, and its pages as SVG.
   Typing saves and recompiles after a short pause (one request at a time;
   a change made meanwhile is sent once that one is back). */

const $ = (id) => document.getElementById(id);
const enc = encodeURIComponent;
let info = { docs: [], templates: [], typst: {}, docs_dir: "" };
let current = null; // the open document's name
let timer = null;
let inflight = false;
let again = false;
let shownV = "";
let saved = null; // the text the server has for the open document
let saving = Promise.resolve(); // saves go one after another
let saveTimer = null;
const PAUSE = 600; // ms after the last key before it compiles
const SAVE_PAUSE = 300; // ms after the last key before it saves
const PICTURES = ["png", "jpg", "jpeg", "gif", "svg", "webp"];

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await errText(res, "that did not work"));
  return res.json();
}

const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function size(n) {
  if (n < 1e3) return n + " B";
  if (n < 1e6) return (n / 1e3).toFixed(0) + " kB";
  return (n / 1e6).toFixed(1) + " MB";
}

function when(t) {
  const d = new Date(t * 1000);
  return d.toDateString() === new Date().toDateString()
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString();
}

/* ---- the list ---- */

function drawDocs() {
  const box = $("docs");
  box.innerHTML = "";
  if (!info.docs.length) box.append(el("div", "muted small", "None yet."));
  for (const d of info.docs) {
    const b = el("button", d.name === current ? "on" : "");
    b.type = "button";
    b.append(d.name, el("span", "m", when(d.modified) + (d.pdf ? " · PDF" : "")));
    b.onclick = () => open(d.name);
    box.append(b);
  }
}

async function refresh() {
  info = await api("/api/state");
  $("docs-dir").textContent = info.docs_dir;
  const sel = $("new-template");
  if (!sel.options.length) {
    for (const t of info.templates) {
      const o = el("option", "", `${t.label}: ${t.about}`);
      o.value = t.id;
      sel.append(o);
    }
  }
  drawDocs();
}

$("new-form").onsubmit = async (e) => {
  e.preventDefault();
  const name = $("new-name").value.trim();
  if (!name) return toast("Give it a name first", "error");
  try {
    await api("/api/docs", json("POST", { name, template: $("new-template").value }));
    $("new-name").value = "";
    await refresh();
    await open(name);
  } catch (err) {
    toast(err.message, "error");
  }
};

/* ---- one document ---- */

async function open(name) {
  await flush();
  unsure();
  // Nothing typed while the next one loads can land in the wrong document.
  $("src").readOnly = true;
  let doc;
  try {
    doc = await api(`/api/docs/${enc(name)}`);
  } catch (err) {
    return toast(err.message, "error");
  } finally {
    $("src").readOnly = false;
  }
  clearTimeout(timer);
  timer = null;
  current = doc.name;
  saved = doc.text;
  localStorage.setItem("typeset-last", current);
  $("empty").hidden = true;
  $("edit").hidden = $("view").hidden = false;
  $("rename-form").hidden = true;
  $("doc-name").hidden = false;
  $("doc-name").textContent = current;
  $("src").value = doc.text;
  $("sheets").innerHTML = "";
  shownV = "";
  drawFiles(doc.assets);
  pdfLink(doc.pdf);
  drawDocs();
  if (!info.typst.ready) {
    $("sheets").append(el("p", "note", `The first preview fetches Typst ${info.typst.version} (${size(info.typst.bytes)}) once.`));
  }
  compile(false);
}

function pdfLink(has) {
  const a = $("pdf-link");
  a.hidden = !has;
  a.href = `/api/docs/${enc(current)}/pdf?t=${Date.now()}`;
}

function drawFiles(list) {
  const box = $("files");
  box.innerHTML = "";
  if (!list.length) return;
  box.append("Beside it: ");
  list.forEach((f, i) => {
    const c = el("code", "", f.name);
    c.title = "Put it in the text at the cursor";
    c.onclick = () => insert(snippet(f.name));
    box.append(i ? ", " : "", c);
  });
}

function snippet(name) {
  const ext = name.split(".").pop().toLowerCase();
  const q = JSON.stringify(name);
  if (PICTURES.includes(ext)) return `#image(${q}, width: 80%)\n`;
  if (ext === "bib") return `#bibliography(${q})\n`;
  if (ext === "csv") return `#let rows = csv(${q})\n`;
  if (["json", "yaml", "yml", "toml"].includes(ext)) return `#let data = ${ext === "yml" ? "yaml" : ext}(${q})\n`;
  if (ext === "typ") return `#include ${q}\n`;
  return `#read(${q})\n`;
}

function insert(text) {
  const t = $("src");
  const at = t.selectionStart;
  t.setRangeText(text, at, t.selectionEnd, "end");
  t.focus();
  changed();
}

/* ---- saving and compiling ---- */

function status(text) { $("status").textContent = text; }

function changed() {
  status("Editing...");
  clearTimeout(timer);
  timer = setTimeout(() => compile(true), PAUSE);
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, SAVE_PAUSE);
}

// Saving is apart from compiling and never waits for it, so closing the
// window mid-compile loses at most the last few hundred milliseconds.
function saveNow() {
  clearTimeout(saveTimer);
  saveTimer = null;
  const name = current;
  const text = $("src").value;
  if (!name || text === saved) return saving;
  saved = text;
  saving = saving
    .then(() => api(`/api/docs/${enc(name)}`, json("PUT", { text })))
    .catch((err) => {
      if (name === current) saved = null; // so the next save tries again
      toast(err.message, "error");
    });
  return saving;
}

async function compile(withText) {
  clearTimeout(timer);
  timer = null;
  if (!current) return;
  if (inflight) { again = true; return; }
  inflight = true;
  const name = current;
  status(info.typst.ready ? (withText ? "Saving..." : "Typesetting...") : `Fetching Typst ${info.typst.version}...`);
  try {
    if (withText) await saveNow();
    const res = await api(`/api/docs/${enc(name)}/preview`, json("POST", {}));
    info.typst.ready = true;
    if (name === current) drawResult(res, withText);
  } catch (err) {
    if (name === current) status(err.message);
    toast(err.message, "error");
  } finally {
    inflight = false;
  }
  if (again) { again = false; compile(true); }
}

// Before switching documents or leaving: send what has not been sent.
async function flush() {
  if (current) await saveNow();
}

function drawResult(res, saved) {
  const parts = [saved ? "Saved" : "Opened"];
  parts.push(res.pages === 1 ? "1 page" : `${res.pages} pages`);
  if (res.errors.length) {
    parts.push(res.errors.length === 1 ? "1 error" : `${res.errors.length} errors`);
    if (res.pages) parts.push("the preview shows the last good version");
  } else {
    parts.push(`${res.ms} ms`);
  }
  status(parts.join(" · "));
  $("pages").textContent = res.pages ? (res.pages === 1 ? "1 page" : `${res.pages} pages`) : "";
  drawProblems(res.errors, res.warnings);
  if (res.v === shownV) return;
  shownV = res.v;
  const box = $("sheets");
  box.innerHTML = "";
  for (let i = 1; i <= res.pages; i++) {
    const img = el("img");
    img.alt = `Page ${i}`;
    img.src = `/api/docs/${enc(current)}/page/${i}?v=${res.v}`;
    box.append(img);
  }
}

function drawProblems(errors, warnings) {
  const box = $("problems");
  box.innerHTML = "";
  const all = [...errors.map((p) => ["error", p]), ...warnings.map((p) => ["warning", p])];
  box.hidden = !all.length;
  for (const [kind, p] of all) {
    const li = el("li", kind);
    const where = p.line ? `${p.file && p.file !== "main.typ" ? p.file + " " : ""}line ${p.line}` : kind;
    li.append(el("b", "", where), " " + p.message);
    if (p.line && (!p.file || p.file === "main.typ")) li.onclick = () => jump(p.line, p.col);
    box.append(li);
  }
}

function jump(line, col) {
  const t = $("src");
  const lines = t.value.split("\n");
  let at = 0;
  for (let i = 0; i < line - 1 && i < lines.length; i++) at += lines[i].length + 1;
  at += Math.max(0, (col || 1) - 1);
  t.focus();
  t.setSelectionRange(at, at);
  const lh = parseFloat(getComputedStyle(t).lineHeight) || 20;
  t.scrollTop = Math.max(0, (line - 1) * lh - t.clientHeight / 3);
}

$("src").addEventListener("input", changed);
$("src").addEventListener("keydown", (e) => {
  if (e.key === "Tab" && !e.shiftKey && !e.ctrlKey && !e.altKey) {
    e.preventDefault();
    insert("  ");
  }
});
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "s") {
    e.preventDefault();
    compile(true);
  }
});
addEventListener("pagehide", () => {
  const text = $("src").value;
  if (!current || text === saved) return;
  const req = json("PUT", { text });
  // keepalive refuses bodies over 64 KiB; a plain fetch may still get there.
  const small = new Blob([req.body]).size < 60000;
  fetch(`/api/docs/${enc(current)}`, small ? { ...req, keepalive: true } : req);
});

/* ---- the buttons ---- */

$("export").onclick = async () => {
  const b = $("export");
  b.disabled = true;
  status("Making the PDF...");
  const name = current;
  try {
    await saveNow();
    const got = await api(`/api/docs/${enc(name)}/pdf`, json("POST", {}));
    toast(`Saved ${got.name} beside the document`);
    if (name === current) {
      status(`Saved ${got.name} (${size(got.bytes)})`);
      pdfLink(true);
    }
    refresh();
  } catch (err) {
    if (name === current) status("The PDF was not made");
    toast(err.message, "error");
  } finally {
    b.disabled = false;
  }
};

$("asset").onchange = async (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  const name = current;
  try {
    const got = await api(`/api/docs/${enc(name)}/assets?filename=${enc(f.name)}`, { method: "POST", body: f });
    if (name !== current) return toast(`Added ${got.name} beside ${name}`);
    const doc = await api(`/api/docs/${enc(name)}`);
    drawFiles(doc.assets);
    insert(snippet(got.name));
    toast(`Added ${got.name}`);
  } catch (err) {
    toast(err.message, "error");
  }
};

$("rename").onclick = () => {
  $("doc-name").hidden = true;
  $("rename-form").hidden = false;
  $("rename-to").value = current;
  $("rename-to").select();
};
$("rename-to").onkeydown = (e) => { if (e.key === "Escape") { $("rename-form").hidden = true; $("doc-name").hidden = false; } };
$("rename-form").onsubmit = async (e) => {
  e.preventDefault();
  const to = $("rename-to").value.trim();
  if (to === current) { $("rename-form").hidden = true; $("doc-name").hidden = false; return; }
  try {
    await flush();
    await api(`/api/docs/${enc(current)}/rename`, json("POST", { to }));
    current = null;
    await refresh();
    await open(to);
  } catch (err) {
    toast(err.message, "error");
  }
};

// The confirm belongs to one document: switching documents takes it back.
let sure = null;
function unsure() {
  clearTimeout(sure);
  sure = null;
  $("trash").textContent = "Move to trash";
}
$("trash").onclick = async () => {
  if (!sure) {
    $("trash").textContent = "Sure? Move it to the trash";
    sure = setTimeout(unsure, 4000);
    return;
  }
  unsure();
  const name = current;
  try {
    clearTimeout(timer);
    clearTimeout(saveTimer);
    timer = saveTimer = null;
    await saving;
    await api(`/api/docs/${enc(name)}/trash`, { method: "POST" });
    toast(`${name} is in the trash`);
    current = null;
    $("edit").hidden = $("view").hidden = true;
    $("empty").hidden = false;
    await refresh();
  } catch (err) {
    toast(err.message, "error");
  }
};

$("zoom").onclick = () => {
  const on = $("sheets").classList.toggle("actual");
  $("zoom").setAttribute("aria-pressed", String(on));
  $("zoom").textContent = on ? "Fit the width" : "Actual size";
};

/* ---- start ---- */

(async () => {
  try {
    await refresh();
  } catch (err) {
    return toast(err.message, "error");
  }
  const last = localStorage.getItem("typeset-last");
  if (last && info.docs.some((d) => d.name === last)) open(last);
})();
