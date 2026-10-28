// Vault: kinds and folders on the left, a grid of what is on disk (or a
// Poly Haven search) in the middle, the picked item with its preview and
// "send to" buttons on the right.

import { fileUrl, previewMode, size, targetsFor } from "./vault-logic.js";

const $ = (id) => document.getElementById(id);
const GLYPH = { model: "🧊", hdri: "🌅", texture: "🧱", image: "🖼️", sound: "🔊" };
let st = { kinds: [], targets: [], sources: [], godot_projects: [] };
let kind = "";
let source = "";
let tab = "disk";
let picked = null;
let stopView = () => {};
let pickSeq = 0; // a newer pick (or a double click) wins over a slow one
let viewer = null; // the three.js module, loaded the first time it is needed

function say(text, how = "") {
  $("status").textContent = text;
  $("status").className = "status" + (how ? " " + how : "");
}

async function api(path, options = {}) {
  if (options.json !== undefined) {
    options = {
      ...options,
      body: JSON.stringify(options.json),
      headers: { "Content-Type": "application/json" },
    };
  }
  const r = await fetch(path, options);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `${r.status}`);
  return body;
}

function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k.includes("-")) e.setAttribute(k, v); // aria-label and the like are attributes
    else e[k] = v;
  }
  e.append(...kids.filter((k) => k !== null && k !== undefined));
  return e;
}

function rowBtn(label, n, on, onclick) {
  const b = el("button", { type: "button", className: "row-btn" + (on ? " on" : "") },
    el("span", { textContent: label }), el("span", { className: "n", textContent: n }));
  b.onclick = onclick;
  return b;
}

function drawSide(counts = {}) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  $("kinds").replaceChildren(
    rowBtn("Everything", total, !kind, () => { kind = ""; load(); }),
    ...st.kinds.map((k) => {
      const b = rowBtn(`${GLYPH[k.id] || ""} ${k.label}`, counts[k.id] || 0, kind === k.id,
        () => { kind = k.id; load(); });
      b.dataset.kind = k.id;
      return b;
    }),
  );
  $("sources").replaceChildren(
    rowBtn("All folders", "", !source, () => { source = ""; load(); }),
    ...st.sources.map((s) => {
      const b = rowBtn(s.label, "", source === s.id, () => { source = s.id; load(); });
      b.title = s.exists ? s.path : `${s.path} (not there)`;
      if (!s.exists) b.classList.add("missing");
      b.dataset.source = s.id;
      const wrap = el("div", { className: "src" }, b);
      if (s.user) {
        const x = el("button", { type: "button", className: "forget", textContent: "✕",
          title: "Stop looking in this folder (the folder stays)" });
        x.setAttribute("aria-label", `Forget ${s.label}`);
        x.onclick = async () => {
          try {
            st.sources = await api(`/api/folders/${s.id}`, { method: "DELETE" });
            if (source === s.id) source = "";
            say(`Vault no longer looks in ${s.path}; nothing was deleted.`);
            load();
          } catch (e) { say(e.message, "bad"); }
        };
        wrap.append(x);
      }
      return wrap;
    }),
  );
}

function card(item) {
  const pic = el("div", { className: "pic" });
  if (item.kind === "image" || item.kind === "texture") {
    const img = el("img", { alt: "", loading: "lazy", src: `/api/items/${item.id}/thumb` });
    if (item.kind === "image" && item.size < 40000) img.classList.add("px");
    img.onerror = () => pic.replaceChildren(GLYPH[item.kind]);
    pic.append(img);
  } else {
    pic.textContent = GLYPH[item.kind] || "📦";
  }
  const c = el("button", { type: "button", className: "card" + (picked && picked.id === item.id ? " on" : "") },
    pic,
    el("span", { className: "t", textContent: item.name, title: item.name }),
    el("span", { className: "m", textContent: `${item.ext.slice(1)} · ${size(item.size)} · ${item.folder}` }));
  c.dataset.id = item.id;
  c.onclick = () => pick(item);
  return c;
}

let loadSeq = 0;
async function load() {
  if (tab !== "disk") return;
  const seq = ++loadSeq;
  const q = new URLSearchParams({ q: $("search").value, kind, source });
  try {
    const r = await api(`/api/items?${q}`);
    if (seq !== loadSeq) return;
    drawSide(r.counts);
    $("count").textContent = r.total > r.items.length
      ? `${r.items.length} of ${r.total} shown; search to narrow it down`
      : `${r.total} item${r.total === 1 ? "" : "s"}`;
    $("grid").replaceChildren(...r.items.map(card));
  } catch (e) {
    say(e.message, "bad");
  }
}

function facts(item) {
  const dl = el("dl", { className: "facts" });
  const add = (k, v) => v && dl.append(el("dt", { textContent: k }), el("dd", { textContent: v }));
  add("Kind", (st.kinds.find((k) => k.id === item.kind) || {}).label);
  add("Size", size(item.size));
  add("File", item.path);
  if (item.files.length > 1) add("Files", String(item.files.length));
  add("Licence", item.license);
  add("By", [].concat(item.authors || []).join(", "));
  add("Note", item.note);
  return dl;
}

function sendBox(item) {
  const box = el("div", { className: "send" }, el("h3", { textContent: "Send to" }));
  for (const t of targetsFor(item, st.targets)) {
    const btn = el("button", { type: "button", className: "btn btn-primary", textContent: t.label });
    btn.dataset.target = t.id;
    const one = el("div", { className: "one" }, btn);
    const extra = {};
    if (t.id === "godot") {
      const sel = el("select", { "aria-label": "Godot project" },
        ...st.godot_projects.map((p) => el("option", { value: p.path, textContent: p.name })));
      sel.id = "godot-project";
      if (!st.godot_projects.length) {
        sel.append(el("option", { value: "", textContent: "no Godot projects found" }));
        btn.disabled = true;
      }
      one.append(sel);
      extra.project = () => sel.value;
    }
    if (t.id === "pixelforge") {
      const px = el("select", { "aria-label": "Sprite size" },
        ...[16, 32, 64, 128, 256].map((n) => el("option", { value: n, textContent: `${n} px`, selected: n === 64 })));
      const cols = el("select", { "aria-label": "Colours" },
        ...[8, 16, 24, 32, 48].map((n) => el("option", { value: n, textContent: `${n} colours`, selected: n === 24 })));
      one.append(px, cols);
      extra.size = () => Number(px.value);
      extra.colors = () => Number(cols.value);
    }
    one.append(el("p", { className: "hint", textContent: t.hint }));
    btn.onclick = async () => {
      const body = Object.fromEntries(Object.entries(extra).map(([k, f]) => [k, f()]));
      btn.disabled = true;
      say(`Sending to ${t.label}...`);
      try {
        const r = await api(`/api/items/${item.id}/send/${t.id}`, { method: "POST", json: body });
        say(r.message, "good");
      } catch (e) {
        say(e.message, "bad");
      } finally {
        btn.disabled = false;
      }
    };
    box.append(one);
  }
  return box.childElementCount > 1 ? box : null;
}

async function preview(item, view, seq) {
  const mode = previewMode(item, st.kinds);
  if (mode === "image") {
    const img = el("img", { alt: item.name, src: fileUrl(item) });
    // small sprites are blown up with hard pixel edges instead of shown tiny
    img.onload = () => img.naturalWidth <= 128 && img.naturalHeight <= 128 && img.classList.add("px");
    view.append(img);
  } else if (mode === "3d" || mode === "sky") {
    viewer = viewer || (await import("./viewer.js"));
    if (seq !== pickSeq) return;
    stopView = mode === "3d" ? viewer.showModel(view, fileUrl(item)) : viewer.showSky(view, fileUrl(item));
  } else {
    const how = item.kind === "sound" ? "🔊" : `No preview for ${item.ext} files here; send it on to look at it.`;
    view.append(el("p", { className: "none", textContent: how }));
  }
}

async function pick(item) {
  const seq = ++pickSeq;
  picked = item;
  stopView();
  stopView = () => {};
  document.querySelectorAll(".card.on").forEach((c) => c.classList.remove("on"));
  const c = document.querySelector(`.card[data-id="${item.id}"]`);
  if (c) c.classList.add("on");
  const view = el("div", { className: "view", id: "view" });
  const kids = [el("h2", { textContent: item.name }), view];
  if (item.kind === "sound") kids.push(el("audio", { controls: true, preload: "metadata", src: fileUrl(item) }));
  if (item.kind === "texture" && item.files.length > 1) {
    kids.push(el("div", { className: "maps" }, ...item.files.slice(0, 8).map((f) =>
      el("img", { alt: f, title: f, loading: "lazy", src: fileUrl(item, f) }))));
  }
  kids.push(facts(item), sendBox(item));
  $("detail").replaceChildren(...kids.filter(Boolean));
  try {
    await preview(item, view, seq);
  } catch (e) {
    say(`Preview failed: ${e.message}`, "bad");
  }
}

// --- Poly Haven ---------------------------------------------------------------

function phCard(hit) {
  const img = el("img", { alt: "", loading: "lazy", src: `/api/polyhaven/thumb/${encodeURIComponent(hit.id)}` });
  const pic = el("div", { className: "pic" }, img);
  img.onerror = () => pic.replaceChildren("🌍");
  const res = el("select", { "aria-label": "Size" },
    ...["1k", "2k", "4k"].map((r) => el("option", { value: r, textContent: r })));
  const get = el("button", { type: "button", className: "btn" });
  const have = new Set(hit.sizes || []);
  const mark = () => {
    get.textContent = have.has(res.value) ? "Downloaded" : "Download";
    get.disabled = have.has(res.value);
  };
  res.onchange = mark;
  mark();
  get.onclick = async (ev) => {
    ev.stopPropagation();
    get.disabled = true;
    say(`Downloading ${hit.name} at ${res.value}...`);
    try {
      const r = await api("/api/polyhaven/get", { method: "POST", json: { id: hit.id, res: res.value } });
      have.add(res.value);
      mark();
      say(`${r.name} is in Forge assets now; it shows under On disk.`, "good");
    } catch (e) {
      mark();
      say(e.message, "bad");
    }
  };
  res.onclick = (ev) => ev.stopPropagation();
  const c = el("div", { className: "card" }, pic,
    el("span", { className: "t", textContent: hit.name, title: hit.name }),
    el("span", { className: "m", textContent: (hit.tags || []).join(", ") }),
    el("div", { className: "one m" }, res, get));
  c.dataset.ph = hit.id;
  return c;
}

let phSeq = 0;
async function phSearch() {
  const seq = ++phSeq;
  say("Asking Poly Haven...");
  try {
    const hits = await api(`/api/polyhaven?${new URLSearchParams({ kind: $("ph-kind").value, q: $("ph-q").value })}`);
    if (seq !== phSeq || tab !== "ph") return; // a newer search or the other tab won
    $("count").textContent = `${hits.length} from Poly Haven`;
    $("grid").replaceChildren(...hits.map(phCard));
    say("");
  } catch (e) {
    say(e.message, "bad");
  }
}

function setTab(which) {
  tab = which;
  phSeq++;
  pickSeq++;
  stopView(); // no 3D preview keeps drawing behind the other tab
  stopView = () => {};
  picked = null;
  $("detail").replaceChildren(el("p", { className: "muted", textContent: "Pick something to see it here." }));
  $("tab-disk").classList.toggle("on", which === "disk");
  $("tab-ph").classList.toggle("on", which === "ph");
  $("ph-bar").hidden = which !== "ph";
  $("search").disabled = which !== "disk";
  $("grid").replaceChildren();
  $("count").textContent = which === "ph" ? "Search Poly Haven above." : "";
  if (which === "disk") load();
}

$("tab-disk").onclick = () => setTab("disk");
$("tab-ph").onclick = () => setTab("ph");
$("ph-go").onclick = phSearch;
$("ph-q").addEventListener("keydown", (e) => { if (e.key === "Enter") phSearch(); });
let typing = 0;
$("search").addEventListener("input", () => {
  clearTimeout(typing);
  typing = setTimeout(load, 200);
});
$("refresh").onclick = async () => {
  say("Looking through the folders...");
  try {
    const r = await api("/api/refresh", { method: "POST" });
    say(`Found ${r.total} items.`, "good");
    if (tab === "disk") load();
  } catch (e) { say(e.message, "bad"); }
};
$("add-folder").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    st.sources = await api("/api/folders", { method: "POST", json: { path: $("folder-path").value } });
    $("folder-path").value = "";
    say("Folder added.", "good");
    load();
  } catch (err) { say(err.message, "bad"); }
});

(async () => {
  try {
    st = await api("/api/state");
  } catch (e) {
    say(e.message, "bad");
    return;
  }
  load();
})();
