/* Convert: files go on a list, each picks a format, then converts as a job
   (shared/forge_jobs.py, followed with forgeStream). What each file can
   become comes from the server's converters/ registry, never from here. */

const $ = (id) => document.getElementById(id);
const queue = new Map(); // id -> { file?, path?, name, size, choices, row, state }
let info = { converters: [], tools: {}, out_dir: "" };
let seq = 0;
const AT_ONCE = 2; // the server runs two at a time too; the rest wait here
let running = 0;

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

function size(n) {
  if (!n) return "";
  if (n < 1e3) return n + " B";
  if (n < 1e6) return (n / 1e3).toFixed(0) + " kB";
  if (n < 1e9) return (n / 1e6).toFixed(1) + " MB";
  return (n / 1e9).toFixed(2) + " GB";
}

const conv = (id) => info.converters.find((c) => c.id === id);
const remembered = () => JSON.parse(localStorage.getItem("convert-last") || "{}");

/* ---- adding files ---- */

async function add(item) {
  const id = "f" + ++seq;
  try {
    const got = await api(`/api/choices?name=${encodeURIComponent(item.name)}`);
    item.choices = got.choices;
  } catch (e) {
    return toast(e.message, "error");
  }
  if (!item.choices.length) {
    toast(`Nothing here reads .${item.name.split(".").pop()} files (${item.name})`, "error");
    return;
  }
  item.state = "waiting";
  queue.set(id, item);
  draw(id);
  $("queue-head").classList.remove("hidden");
}

function addFiles(files) {
  for (const f of files) add({ file: f, name: f.name, size: f.size });
}

$("pick").onchange = (e) => { addFiles(e.target.files); e.target.value = ""; };
$("add-path").onclick = () => {
  const p = val("path").trim();
  if (!p.startsWith("/") && !p.startsWith("~")) return toast("Type the whole path, from / or ~", "error");
  add({ path: p, name: p.split("/").pop(), size: 0 });
  setVal("path", "");
};
$("path").onkeydown = (e) => { if (e.key === "Enter") $("add-path").click(); };

const drop = $("drop");
for (const ev of ["dragenter", "dragover"]) {
  document.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); });
}
document.addEventListener("dragleave", (e) => { if (!e.relatedTarget) drop.classList.remove("over"); });
document.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
});

/* ---- one file's row ---- */

function draw(id) {
  const it = queue.get(id);
  const row = it.row || el("div", "file");
  row.innerHTML = "";
  row.dataset.id = id;
  const left = el("div");
  left.append(el("div", "name", it.name), el("div", "m", [size(it.size), it.path || ""].filter(Boolean).join(" · ")));
  const pick = el("div", "pick");
  const sel = el("select");
  sel.setAttribute("aria-label", "Convert to");
  const last = remembered();
  // A file another app handles (video) starts with nothing picked, so
  // Convert all leaves it alone; its sound is there to choose.
  const elsewhere = it.choices.some((c) => c.handoff);
  if (elsewhere && it.choices.some((c) => c.to.length)) {
    const o = el("option", "", "Only its sound, as...");
    o.value = "";
    sel.append(o);
  }
  let chosen = "";
  for (const ch of it.choices) {
    if (!ch.to.length) continue;
    const g = el("optgroup");
    g.label = ch.label;
    for (const t of ch.to) {
      const o = el("option", "", "." + t);
      o.value = `${ch.converter}:${t}`;
      g.append(o);
    }
    sel.append(g);
    if (!chosen && !elsewhere) chosen = `${ch.converter}:${last[ch.converter] || ch.to[0]}`;
  }
  const go = el("button", "btn btn-primary", "Convert");
  go.type = "button";
  go.onclick = () => run(id);
  const drop = el("button", "btn", "Take off the list");
  drop.type = "button";
  drop.onclick = () => {
    it.removed = true; // a send still on its way is stopped once it lands
    if (it.abort) it.abort.abort();
    if (it.job) stopJob(it);
    queue.delete(id);
    row.remove();
    if (!queue.size) $("queue-head").classList.add("hidden");
  };
  if (sel.options.length) {
    sel.value = it.target || chosen;
    if (!sel.value && !elsewhere) sel.selectedIndex = 0;
    it.target = sel.value || null;
    sel.onchange = () => { it.target = sel.value || null; drawOptions(it, row); };
    pick.append(sel, go);
  }
  for (const ch of it.choices) {
    if (!ch.handoff) continue;
    const b = el("button", "btn handoff", ch.handoff.label);
    b.type = "button";
    b.title = ch.handoff.why || "";
    b.onclick = () => handoff(ch.handoff, it);
    pick.append(b);
  }
  pick.append(drop);
  row.append(left, pick, el("div", "opts"), el("div", "note"), el("div", "bar"));
  row.querySelector(".bar").append(el("div"));
  it.row = row;
  if (!row.isConnected) $("queue").append(row);
  drawOptions(it, row);
}

function drawOptions(it, row) {
  const box = row.querySelector(".opts");
  const note = row.querySelector(".note");
  box.innerHTML = "";
  note.textContent = "";
  it.options = it.options || {};
  if (!it.target) {
    const h = it.choices.find((c) => c.handoff);
    if (h) note.textContent = h.handoff.why;
    return;
  }
  const [cid, to] = it.target.split(":");
  const c = conv(cid);
  for (const opt of c.options || []) {
    if (opt.for && !opt.for.includes(to)) continue;
    const lab = el("label", "", opt.label);
    let input;
    if (opt.type === "choice") {
      input = el("select");
      for (const ch of opt.choices) { const o = el("option", "", ch.label); o.value = ch.id; input.append(o); }
    } else {
      input = el("input");
      input.type = "number";
      if (opt.min !== undefined) input.min = opt.min;
      if (opt.max !== undefined) input.max = opt.max;
    }
    input.value = it.options[opt.id] ?? opt.default;
    input.dataset.opt = opt.id;
    input.onchange = () => { it.options[opt.id] = opt.type === "number" ? Number(input.value) : input.value; };
    lab.append(input);
    box.append(lab);
  }
  const notes = [];
  if (c.needs && info.tools[c.needs] && !info.tools[c.needs].ready) {
    const t = info.tools[c.needs];
    notes.push(`The first time, ${c.needs} ${t.version} (${size(t.bytes)}) is fetched once and checked.`);
  }
  if (c.note) notes.push(c.note);
  note.textContent = notes.join(" ");
}

function setState(it, state, text) {
  it.state = state;
  it.row.classList.toggle("done", state === "done");
  it.row.classList.toggle("failed", state === "failed");
  const note = it.row.querySelector(".note");
  note.textContent = "";
  if (text) note.append(text);
}

/* ---- converting ---- */

// Convert (one or all) puts files in line; pump() starts them AT_ONCE at a
// time, so a long list never ties up every connection the page has.
function run(id) {
  const it = queue.get(id);
  if (!it || it.state === "running" || it.state === "queued" || !it.target) return;
  setState(it, "queued", el("span", "", "Waiting for a free slot..."));
  it.row.querySelector(".pick .btn-primary").disabled = true;
  pump();
}

function pump() {
  for (const [id, it] of queue) {
    if (running >= AT_ONCE) return;
    if (it.state === "queued") start(id);
  }
}

function finish(it) {
  if (!it.counted) return;
  it.counted = false;
  running--;
  pump();
}

async function start(id) {
  const it = queue.get(id);
  running++;
  it.counted = true;
  const [cid, to] = it.target.split(":");
  const last = remembered();
  last[cid] = to;
  localStorage.setItem("convert-last", JSON.stringify(last));
  const opts = {};
  it.row.querySelectorAll("[data-opt]").forEach((i) => { opts[i.dataset.opt] = i.type === "number" ? Number(i.value) : i.value; });
  setState(it, "running", el("span", "", it.file ? "Sending the file..." : "Starting..."));
  it.abort = new AbortController();
  try {
    let got;
    if (it.file) {
      const q = new URLSearchParams({ name: it.name, converter: cid, to, options: JSON.stringify(opts) });
      got = await api(`/api/convert/file?${q}`, { method: "POST", body: it.file, signal: it.abort.signal });
    } else {
      got = await api("/api/convert/path", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: it.path, converter: cid, to, options: opts }),
        signal: it.abort.signal,
      });
    }
    it.abort = null;
    if (it.removed) {
      it.job = got.job;
      stopJob(it);
      return finish(it);
    }
    follow(it, got.job);
  } catch (e) {
    it.abort = null;
    if (it.removed) return finish(it);
    failed(it, e.message);
  }
}

function follow(it, jobId) {
  it.job = jobId;
  const bar = it.row.querySelector(".bar div");
  setState(it, "running", el("span", "", "Converting..."));
  const stop = el("button", "btn", "Stop");
  stop.type = "button";
  stop.onclick = () => stopJob(it);
  it.row.querySelector(".note").append(" ", stop);
  forgeStream(jobId, {
    onLog: (t) => { const s = it.row.querySelector(".note span"); if (s && !t.startsWith("Saved")) s.textContent = t; },
    onProgress: (e) => { bar.style.width = Math.round(e.frac * 100) + "%"; },
    onDone: async () => {
      it.job = null;
      finish(it);
      bar.style.width = "100%";
      try {
        const j = await api(`/api/jobs/${jobId}`);
        const a = el("a", "", j.result.name);
        a.href = `/api/out/${encodeURIComponent(j.result.name)}`;
        a.setAttribute("download", j.result.name);
        const span = el("span", "", `Saved as `);
        span.append(a, ` (${size(j.result.bytes)}) in ${info.out_dir}`);
        setState(it, "done", span);
      } catch (e) {
        setState(it, "done", el("span", "", "Saved"));
      }
      it.row.querySelector(".pick .btn-primary").disabled = false;
      refresh();
    },
    onError: (msg) => { it.job = null; finish(it); failed(it, msg); },
  });
}

function failed(it, msg) {
  finish(it);
  it.row.querySelector(".bar div").style.width = "0";
  setState(it, "failed", el("span", "err", msg === "stopped" ? "Stopped; nothing was saved." : msg));
  const b = it.row.querySelector(".pick .btn-primary");
  if (b) b.disabled = false;
}

async function stopJob(it) {
  if (!it.job) return;
  try { await api(`/api/jobs/${it.job}/stop`, { method: "POST" }); } catch (e) { toast(e.message, "error"); }
}

$("convert-all").onclick = () => { for (const [id, it] of queue) if (it.state === "waiting" || it.state === "failed") run(id); };
$("clear-done").onclick = () => {
  for (const [id, it] of queue) if (it.state === "done") { it.row.remove(); queue.delete(id); }
  if (!queue.size) $("queue-head").classList.add("hidden");
};

/* ---- handing a file to another Forge app ---- */

function handoff(h, it) {
  if (window.parent === window) return toast("Open MediaForge from Forge's sidebar; that is where video is converted.", "error");
  const hash = h.hash + (it.path ? "&files=" + encodeURIComponent(it.path) : "");
  window.parent.postMessage({ forge: "open", app: h.app, hash }, "*");
  if (!it.path) toast("MediaForge needs the video's path; type it in its Files box.");
  else if (it.path.includes(",")) toast("MediaForge splits its Files box at commas; this name has one, so fix it there.", "error");
}

/* ---- the converted list ---- */

function drawRecent(files) {
  const box = $("recent");
  box.innerHTML = "";
  if (!files.length) { box.append(el("div", "muted small", "Nothing converted yet.")); return; }
  for (const f of files) {
    const a = el("a");
    a.href = `/api/out/${encodeURIComponent(f.name)}`;
    a.setAttribute("download", f.name);
    a.append(el("span", "", f.name), el("span", "m", `${size(f.bytes)} · ${new Date(f.made * 1000).toLocaleString()}`));
    box.append(a);
  }
}

async function refresh() {
  try {
    info = await api("/api/state");
  } catch (e) {
    return toast(e.message, "error");
  }
  $("out-dir").textContent = info.out_dir;
  $("kinds").textContent = info.converters.map((c) => c.label.toLowerCase()).join(", ").replace(/, ([^,]*)$/, " and $1");
  drawRecent(info.recent);
  for (const it of queue.values()) if (it.state === "waiting") drawOptions(it, it.row);
}

refresh();
