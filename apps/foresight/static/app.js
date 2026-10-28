/* Foresight frontend.
 *
 * The page draws whatever the backend's registries report — tiers, signal
 * sources, analysers — and names none of them itself. Adding a source or a
 * tier needs no change here.
 *
 * The one thing this page insists on: every answer shows which tier produced
 * it and whether a model was involved. A rules answer must never be mistaken
 * for a model's, or the point of having a rules tier is lost.
 */

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, options) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return r.json();
}

const state = {
  status: null, tier: "rules", findings: [], findingsSig: "",
  sweepPoll: null, bootPoll: null, sweeping: false, logText: "", subject: null,
};

/* Small things kept on this computer between reloads (answers, filters). A
   full or blocked localStorage only costs the memory, never the page. */
function remembered(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : JSON.parse(raw);
  } catch (e) { return fallback; }
}
function remember(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* memory only */ }
}

/* ---------------------------------------------------------------- views */

/* The views are whatever sections the page holds, not a list kept here. */
const VIEWS = [...document.querySelectorAll(".view")].map((v) => v.id.replace("view-", ""));

function currentView() {
  const on = document.querySelector(".view.on");
  return on ? on.id.replace("view-", "") : "ask";
}

function showView(name) {
  document.querySelectorAll(".view").forEach((v) =>
    v.classList.toggle("on", v.id === "view-" + name));
  document.querySelectorAll(".views button").forEach((b) =>
    b.classList.toggle("on", b.dataset.view === name));
  const target = "#/" + name;
  if (location.hash !== target) history.replaceState(null, "", target);
  if (name === "findings") loadFindings();
  if (name === "plans") loadPlans();
  if (name === "watch") loadWatchlist();
}

function routeFromHash() {
  const view = (location.hash || "").replace("#/", "");
  showView(VIEWS.includes(view) ? view : "ask");
}
window.addEventListener("hashchange", routeFromHash);
document.querySelectorAll(".views button").forEach((b) =>
  b.addEventListener("click", () => showView(b.dataset.view)));

/* ----------------------------------------------------------- fullscreen */
/* Three separate things, which is why F11 alone was never enough: the Forge
   sidebar is hidden by a postMessage to the hub, the page takes real
   fullscreen, and forge.py fullscreens the GTK window behind it. All of that
   lives in shared/forge_chrome.js now, which wires the `go-fullscreen` button
   and the `f` key by itself the moment it loads -- there is nothing to do
   here. F11 is handled by the window in forge.py, not by the page. */

/* ----------------------------------------------------------------- boot */

/* If the server is not up yet, boot keeps trying on a stretching wait (it
   rests while hidden) instead of leaving the page dead until a reload. */
async function boot() {
  if (!state.sweepPoll) {
    state.sweepPoll = ForgeIdle.poll(pollSweep, 15000, { backoff: 2, maxMs: 30000, immediate: true });
  }
  try {
    state.status = await api("/api/status");
  } catch (e) {
    $("pill-jan").textContent = "backend unreachable";
    $("pill-jan").className = "pill bad";
    if (!state.bootPoll) {
      state.bootPoll = ForgeIdle.poll(boot, 4000, { backoff: 2, maxMs: 30000 });
    }
    return false;
  }
  const recovered = !!state.bootPoll;
  if (state.bootPoll) { state.bootPoll.stop(); state.bootPoll = null; }
  const s = state.status;

  $("pill-store").textContent =
    (s.storage.on_usb ? "USB drive · " : "local disk") +
    (s.storage.free_gb >= 0 ? (s.storage.on_usb ? "" : " · ") + s.storage.free_gb + " GB free" : "");
  $("pill-store").className = "pill " + (s.storage.on_usb ? "ok" : "");
  $("pill-store").title = s.storage.detail + "\n" + s.storage.path;

  $("pill-dossier").textContent = s.dossier.available
    ? `Dossier · ${s.dossier.subjects} subjects`
    : "Dossier unreachable";
  $("pill-dossier").className = "pill " + (s.dossier.available ? "ok" : "bad");
  $("pill-dossier").title = s.dossier.detail;

  renderJanPill(s.jan);
  renderTiers(s.tiers);
  renderSources(s.sources);
  renderAnalysers(s.analysers);
  $("storage-detail").textContent =
    `${s.storage.detail}\nEverything Foresight stores — signal series, findings, `
    + `chats — lives at ${s.storage.path}, beside Dossier's library rather than `
    + `inside it. Nothing here ever writes into Dossier's data.`;

  fillPlanTiers();
  // The view was drawn at once from the address; it only needs reading again
  // when the server was not answering the first time.
  if (recovered) routeFromHash();
  return true;
}

function renderJanPill(jan) {
  const pill = $("pill-jan");
  if (!jan.jan) {
    pill.textContent = "Jan offline · rules tier still works";
    pill.className = "pill";
    pill.title = jan.detail || "";
    return;
  }
  const think = jan.tiers.think || {};
  pill.textContent = think.model ? `Jan · think: ${think.model}` : "Jan";
  pill.className = "pill " + (think.is_ideal ? "ok" : "");
  pill.title = Object.entries(jan.tiers)
    .map(([t, v]) => `${t}: ${(v && v.model) || "none"}${v && !v.is_ideal ? ` (ideal ${v.ideal})` : ""}`)
    .join("\n");
}

/* ----------------------------------------------------------------- ask */

function renderTiers(tiers) {
  const pick = $("tier-pick");
  pick.innerHTML = "";
  const help = $("tier-help");
  help.innerHTML = "";
  tiers.forEach((tier) => {
    const b = el("button", tier.uses_model ? "" : "norobot");
    if (tier.name === state.tier) b.classList.add("on");
    b.append(el("span", "lbl", tier.label));
    b.append(el("span", "sub", tier.uses_model ? "uses a model" : "no model"));
    b.addEventListener("click", () => {
      state.tier = tier.name;
      renderTiers(tiers);
    });
    pick.appendChild(b);

    const line = el("div", "solver");
    line.append(el("b", null, tier.label + (tier.uses_model ? "" : " — no model")));
    line.append(document.createTextNode(tier.description));
    help.appendChild(line);

    if (!tier.uses_model && tier.solvers.length) {
      const list = $("solver-list");
      list.innerHTML = "";
      tier.solvers.forEach((s) => {
        const row = el("div", "solver");
        row.append(el("b", null, s.label));
        row.append(document.createTextNode(s.description));
        list.appendChild(row);
      });
    }
  });
}

function renderAnswer(question, answer) {
  const card = el("div", "card answer");
  card.appendChild(el("div", "question", question));

  const who = el("span", "who " + (answer.used_model ? "model" : "rules"));
  who.textContent = answer.used_model
    ? `${answer.tier} · ${answer.model || "model"} · ${answer.seconds}s`
    : `${answer.tier} · no model used`;
  card.appendChild(who);
  if (answer.asked) {
    const when = new Date(answer.asked);
    if (!isNaN(when)) {
      card.appendChild(el("span", "when", when.toLocaleString([], {
        day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
      })));
    }
  }

  const text = el("pre", "text");
  text.textContent = answer.text;
  card.appendChild(text);

  // The thinking is the point of the think tier, so it is kept and shown -
  // folded away, because it is long.
  if (answer.reasoning) {
    const details = el("details", "thinking");
    details.appendChild(el("summary", null,
      `its thinking (${answer.reasoning.length.toLocaleString()} characters)`));
    const pre = el("pre");
    pre.textContent = answer.reasoning;
    details.appendChild(pre);
    card.appendChild(details);
  }

  const answers = $("ask-answers");
  answers.insertBefore(card, answers.firstChild);
}

/* The last answers survive a reload (Forge reloads a tab when it restarts an
   app), newest first, until "Clear answers". The think tier's reasoning can
   run to tens of thousands of characters, so the kept copy is capped. */
const ANSWERS_KEY = "foresight.answers.v1";
const KEEP_ANSWERS = 20;

function keepAnswer(question, answer) {
  const kept = remembered(ANSWERS_KEY, []);
  const slim = { ...answer };
  if (slim.reasoning && slim.reasoning.length > 40000) {
    slim.reasoning = slim.reasoning.slice(0, 40000) + "\n… (cut when kept)";
  }
  kept.push({ question, answer: slim });
  remember(ANSWERS_KEY, kept.slice(-KEEP_ANSWERS));
  $("ask-clear").hidden = false;
}

function restoreAnswers() {
  const kept = remembered(ANSWERS_KEY, []);
  if (!Array.isArray(kept)) return;
  kept.forEach((row) => {
    if (row && row.question && row.answer) renderAnswer(row.question, row.answer);
  });
  $("ask-clear").hidden = !kept.length;
}

$("ask-clear").addEventListener("click", async () => {
  const n = remembered(ANSWERS_KEY, []).length;
  const ok = await ForgeDialog.confirm(
    `Clear the ${n} kept answer${n === 1 ? "" : "s"} from this page? Nothing else is touched.`,
    { ok: "Clear" });
  if (!ok) return;
  remember(ANSWERS_KEY, []);
  $("ask-answers").replaceChildren();
  $("ask-clear").hidden = true;
});

async function ask() {
  const question = $("ask-box").value.trim();
  if (!question) return;
  const button = $("ask-go");
  const note = $("ask-note");
  if (!state.status) {
    note.textContent = "Foresight's server is not answering yet; try again in a moment.";
    return;
  }
  button.disabled = true;
  const usesModel = (state.status.tiers.find((t) => t.name === state.tier) || {}).uses_model;
  note.textContent = usesModel
    ? "thinking — the think tier is allowed to take minutes…"
    : "computing…";
  try {
    const answer = await api("/api/ask", {
      method: "POST",
      body: JSON.stringify({
        question,
        tier: state.tier,
        prefer_rules: $("prefer-rules").checked,
      }),
    });
    answer.asked = new Date().toISOString();
    renderAnswer(question, answer);
    keepAnswer(question, answer);
    $("ask-box").value = "";
    note.textContent = "";
  } catch (e) {
    note.textContent = e.message;
  }
  button.disabled = false;
}
$("ask-go").addEventListener("click", ask);
$("ask-box").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) ask();
});

/* ------------------------------------------------------------- findings */

function sparkline(points) {
  if (!points || points.length < 2) return null;
  const values = points.map((p) => Number(p.value) || 0);
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const step = 100 / (values.length - 1);
  const coords = values.map((v, i) =>
    `${(i * step).toFixed(2)},${(28 - ((v - min) / span) * 26).toFixed(2)}`);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", "spark");
  svg.setAttribute("viewBox", "0 0 100 30");
  svg.setAttribute("preserveAspectRatio", "none");
  const line = document.createElementNS(ns, "polyline");
  line.setAttribute("points", coords.join(" "));
  svg.appendChild(line);
  // A zero-length segment with a round cap and a non-scaling stroke draws a
  // round dot; a <circle> is stretched into an oval by the free aspect ratio.
  const last = coords[coords.length - 1];
  const dot = document.createElementNS(ns, "polyline");
  dot.setAttribute("class", "last");
  dot.setAttribute("points", `${last} ${last}`);
  svg.appendChild(dot);
  return svg;
}

/* "from 2026-09-11 (28 days ago)": every card says how old its reading is. */
function ageText(at, days) {
  if (days === null || days === undefined) return "";
  const ago = days <= 0 ? "today" : `${days} day${days === 1 ? "" : "s"} ago`;
  return `from ${String(at).slice(0, 10)} (${ago})`;
}

function minutes(seconds) {
  const m = Math.round(seconds / 60);
  return m < 1 ? "under a minute" : `about ${m} minute${m === 1 ? "" : "s"}`;
}

/* Above the list: how old the freshest reading is, and the one click that
   refreshes it when the page is mostly old news. */
function renderAgeNote(payload) {
  const box = $("findings-age");
  const findings = payload.findings || [];
  const stale = payload.stale || 0;
  if (!payload.newest || !stale) { box.hidden = true; return; }
  const newest = findings.find((f) => String(f.at).slice(0, 10) === payload.newest);
  const est = payload.sweep_estimate || { subjects: 25, seconds: 125 };
  $("findings-age-text").textContent =
    `The newest reading is ${ageText(payload.newest, newest ? newest.age_days : null)}; `
    + `${stale} of ${findings.length} findings are older than their source stays news, `
    + `and are greyed out.`;
  const button = $("findings-sweep");
  button.textContent =
    `Sweep the watchlist now (${est.subjects} subjects, stale ones first, ${minutes(est.seconds)})`;
  state.sweepNow = est.list || [];
  box.hidden = false;
}

/* One finding. The headline opens the subject panel when there is a subject
   to open (`link`), which there is not inside the panel itself. */
function findingCard(f, link = true) {
  const rising = /up sharply/.test(f.headline);
  const card = el("div", "finding " + (rising ? "rising" : "falling")
    + (f.stale ? " stale" : ""));
  const head = el("div", "head");
  if (link && f.slug) {
    const name = el("button", "linkish", f.headline);
    name.title = "Everything held about " + (f.subject || f.slug);
    name.addEventListener("click", () => openSubject(f.slug, f.subject));
    head.appendChild(name);
  } else {
    head.appendChild(el("b", null, f.headline));
  }
  head.appendChild(el("span", "tag", f.source));
  head.appendChild(el("span", "tag norobot", "no model"));
  const age = ageText(f.at, f.age_days);
  if (age) {
    const tag = el("span", "age", age);
    if (f.stale) tag.title = "Older than this source stays news; sweep to refresh it";
    head.appendChild(tag);
  }
  card.appendChild(head);
  card.appendChild(el("div", "detail", f.detail));
  const spark = sparkline(f.evidence);
  if (spark) card.appendChild(spark);
  return card;
}

/* Filters over the findings already read: by subject text, source, kind and
   freshness. The choices offered come from the findings themselves, and the
   last choice is kept across reloads. */
const FILTER_KEY = "foresight.findingsFilter.v1";
const filters = Object.assign({ text: "", source: "", kind: "", fresh: false },
  remembered(FILTER_KEY, {}));

function filtering() {
  return !!(filters.text || filters.source || filters.kind || filters.fresh);
}

function passes(f) {
  if (filters.fresh && f.stale) return false;
  if (filters.source && f.source !== filters.source) return false;
  if (filters.kind && f.kind !== filters.kind) return false;
  if (filters.text) {
    const hay = `${f.subject || ""} ${f.headline || ""}`.toLowerCase();
    if (!hay.includes(filters.text.toLowerCase())) return false;
  }
  return true;
}

function fillChoices(select, values, chosen) {
  const first = select.options[0];
  const want = [...new Set(values.filter(Boolean))].sort();
  if (chosen && !want.includes(chosen)) want.push(chosen);
  select.replaceChildren(first, ...want.map((v) => {
    const o = document.createElement("option");
    o.value = v;
    o.textContent = v;
    return o;
  }));
  select.value = chosen || "";
}

function renderFilters() {
  fillChoices($("ff-source"), state.findings.map((f) => f.source), filters.source);
  fillChoices($("ff-kind"), state.findings.map((f) => f.kind), filters.kind);
  $("ff-text").value = filters.text;
  $("ff-fresh").checked = !!filters.fresh;
  $("ff-reset").hidden = !filtering();
}

function renderFindings() {
  const all = state.findings;
  const findings = all.filter(passes);
  const list = $("findings-list");
  $("findings-count").textContent = !all.length ? ""
    : filtering() ? `${findings.length} of ${all.length} findings`
    : `${all.length} findings`;
  $("ff-reset").hidden = !filtering();
  if (!all.length) {
    list.replaceChildren(el("div", "empty",
      "Nothing has broken out of its baseline. Gather some signals first — "
      + "a series needs about ten readings before it has a normal to depart from."));
    return;
  }
  if (!findings.length) {
    list.replaceChildren(el("div", "empty", "No finding matches these filters."));
    return;
  }
  list.replaceChildren(...findings.map((f) => findingCard(f)));
}

/* Read again on every visit and after a sweep, but redrawn only when
   something changed, so coming back to the tab keeps the place in the list. */
async function loadFindings() {
  const button = $("findings-refresh");
  button.disabled = true;
  try {
    const payload = await api("/api/findings");
    const sig = JSON.stringify(payload.findings);
    if (sig !== state.findingsSig) {
      state.findingsSig = sig;
      state.findings = payload.findings || [];
      renderFilters();
      renderFindings();
    }
    renderAgeNote(payload);
  } catch (e) {
    state.findingsSig = "";
    $("findings-list").replaceChildren(el("div", "empty", e.message));
  } finally {
    button.disabled = false;
  }
}
$("findings-refresh").addEventListener("click", loadFindings);

function setFilter(key, value) {
  filters[key] = value;
  remember(FILTER_KEY, filters);
  renderFindings();
}
$("ff-text").addEventListener("input", (e) => setFilter("text", e.target.value.trim()));
$("ff-source").addEventListener("change", (e) => setFilter("source", e.target.value));
$("ff-kind").addEventListener("change", (e) => setFilter("kind", e.target.value));
$("ff-fresh").addEventListener("change", (e) => setFilter("fresh", e.target.checked));
$("ff-reset").addEventListener("click", () => {
  Object.assign(filters, { text: "", source: "", kind: "", fresh: false });
  remember(FILTER_KEY, filters);
  renderFilters();
  renderFindings();
});

/* The same sweep the Signals tab starts, over the most prominent subjects. */
$("findings-sweep").addEventListener("click", async () => {
  const button = $("findings-sweep");
  button.disabled = true;
  try {
    const r = await api("/api/sweep", {
      method: "POST",
      body: JSON.stringify(state.sweepNow && state.sweepNow.length
        ? { subjects: state.sweepNow }
        : { limit: 25 }),
    });
    $("findings-age-text").textContent =
      `Sweeping ${r.subjects} subjects; progress is on the Signals tab, `
      + `and this list refreshes itself when it finishes.`;
    sweepStarted();
  } catch (e) { button.disabled = false; ForgeDialog.alert(e.message); }
});

/* -------------------------------------------------------------- signals */

async function loadWatchlist() {
  const list = $("watchlist");
  let payload;
  try {
    payload = await api("/api/watchlist?limit=60");
  } catch (e) {
    list.replaceChildren(el("div", "muted small", "Could not read the watchlist: " + e.message));
    return;
  }
  if (!payload.subjects.length) {
    list.replaceChildren(el("div", "muted small",
      "Dossier's library is not reachable — is the drive plugged in?"));
    return;
  }
  list.replaceChildren(...payload.subjects.map((s, i) => {
    const row = el("div", "watchrow");
    const name = el("button", "linkish", `${i + 1}. ${s.name}`);
    name.title = "Everything held about " + s.name;
    name.addEventListener("click", () => openSubject(s.slug, s.name));
    row.append(name, el("span", "muted small", s.entity_type));
    return row;
  }));
}

/* The sweep's progress, read every 15 s while the page is shown and every
   1.5 s while a sweep runs (a sweep this page starts is read at once). Hidden,
   it rests; while the server does not answer, the wait stretches to 30 s and
   the page says so. */
/* The line under the bar between sweeps: a sweep that failed or was stopped
   says so, instead of reading like one that finished. */
function idleSummary(p) {
  if (!p.last) return "idle";
  const when = p.last.replace("T", " ").replace("+00:00", "");
  if (p.outcome === "failed") return `last sweep failed at ${when}; the reason is in the live log`;
  if (p.outcome === "stopped") return `last sweep stopped at ${when}, after ${p.done} of ${p.total} subjects`;
  return `last swept ${when}`;
}

/* This page just started a sweep: its end is reported even when the sweep is
   over before the first poll (one that fails at once used to end silently). */
function sweepStarted() {
  state.sweeping = true;
  state.sweepPoll.now();
}

let sweepFast = 0;
async function pollSweep() {
  let payload;
  try { payload = await api("/api/sweep"); } catch (e) {
    $("sweep-summary").textContent = "Foresight's server is not answering; trying again shortly";
    return false;
  }
  const pill = $("pill-sweep");
  pill.hidden = !payload.running;
  if (payload.running) {
    pill.className = "pill busy";
    pill.textContent = `sweeping ${payload.done}/${payload.total}`;
  }
  const pct = payload.total ? (payload.done / payload.total) * 100 : 0;
  $("sweep-bar").style.width = pct.toFixed(1) + "%";
  $("sweep-summary").textContent = payload.running
    ? (payload.stopping
      ? `stopping after the subject under way — ${payload.done} of ${payload.total} done`
      : `sweeping — ${payload.done} of ${payload.total} done`)
    : idleSummary(payload);
  const stop = $("sweep-stop");
  stop.hidden = !payload.running;
  stop.disabled = !!payload.stopping;
  stop.textContent = payload.stopping ? "Stopping…" : "Stop after this subject";
  // One sweep at a time: while one runs, starting another would only be refused.
  for (const id of ["sweep-go", "sweep-history", "findings-sweep"]) $(id).disabled = !!payload.running;
  writeLog((payload.log || []).join("\n") || "nothing running");
  const ended = state.sweeping && !payload.running;
  state.sweeping = !!payload.running;
  if (ended) sweepEnded(payload);
  clearTimeout(sweepFast);
  if (payload.running) {
    sweepFast = setTimeout(() => { if (ForgeIdle.shown()) state.sweepPoll.now(); }, 1500);
  }
  return true;
}

/* The log is rewritten only when it changed, and follows the newest line only
   if it was already at the bottom, so reading back through it is not undone
   by the next poll. */
function writeLog(text) {
  if (text === state.logText) return;
  const box = $("sweep-log");
  const atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
  const top = box.scrollTop;
  state.logText = text;
  box.textContent = text;
  box.scrollTop = atEnd ? box.scrollHeight : top;
}

/* A sweep just finished: what it gathered reaches the page without a click.
   The backend's `outcome` decides the message, so a sweep that crashed is
   never reported as a stop that was asked for. */
function sweepEnded(payload) {
  $("plan-names").replaceChildren();
  const [message, kind] = sweepEndMessage(payload);
  toast(message, kind);
  if (currentView() === "findings") loadFindings();
}

function sweepEndMessage(p) {
  const read = `${p.done} of ${p.total} subjects read`;
  if (p.outcome === "failed") {
    return [p.done
      ? `Sweep failed after ${read}: ${p.error}. What it read is kept.`
      : `Sweep failed before reading any subject: ${p.error}`, "err"];
  }
  if (p.outcome === "stopped") return [`Sweep stopped: ${read}, and kept.`, "ok"];
  if (p.outcome === "finished") return [`Sweep finished: ${read}.`, "ok"];
  // A backend from before `outcome` existed: say only what is known.
  return [`Sweep ended: ${read}.`, "ok"];
}

/* The slider and the number box are one setting. */
function pairLimit(from, to) {
  $(from).addEventListener("input", () => { $(to).value = $(from).value; });
}
pairLimit("sweep-limit-range", "sweep-limit");
pairLimit("sweep-limit", "sweep-limit-range");

$("sweep-go").addEventListener("click", async () => {
  const button = $("sweep-go");
  button.disabled = true;
  try {
    await api("/api/sweep", {
      method: "POST",
      body: JSON.stringify({
        limit: Number($("sweep-limit").value),
        days: Number($("sweep-days").value),
      }),
    });
    sweepStarted();
  } catch (e) { button.disabled = false; ForgeDialog.alert(e.message); }
});

$("sweep-history").addEventListener("click", async () => {
  const button = $("sweep-history");
  button.disabled = true;
  try {
    const r = await api("/api/sweep", {
      method: "POST",
      body: JSON.stringify({ history: true, limit: Number($("sweep-limit").value) }),
    });
    $("sweep-summary").textContent = `getting five years for ${r.subjects} subjects…`;
    sweepStarted();
  } catch (e) { button.disabled = false; ForgeDialog.alert(e.message); }
});

/* Stops between subjects: the one under way finishes, so nothing is left
   half-merged, and everything already gathered stays. */
$("sweep-stop").addEventListener("click", async () => {
  const button = $("sweep-stop");
  button.disabled = true;
  try {
    await api("/api/sweep/stop", { method: "POST" });
  } catch (e) { toast(e.message, "err"); }
  state.sweepPoll.now();
});

/* -------------------------------------------------------------- sources */

function renderSources(sources) {
  const list = $("source-list");
  list.innerHTML = "";
  sources.forEach((s) => {
    const row = el("div", "sourcerow");
    const head = el("div", "row");
    head.append(el("b", null, s.label));
    head.append(el("span", "tag", s.kind));
    head.append(el("span", "tag", s.unit));
    if (s.needs_credentials) head.append(el("span", "tag", "needs credentials"));
    row.appendChild(head);
    row.appendChild(el("div", "small muted", s.description));
    row.appendChild(el("div", "caveat", "Caveat: " + s.caveat));
    list.appendChild(row);
  });
}

function renderAnalysers(analysers) {
  const list = $("analyser-list");
  list.innerHTML = "";
  analysers.forEach((a) => {
    const row = el("div", "solver");
    const title = el("b");
    title.textContent = a.label;
    row.appendChild(title);
    row.append(document.createTextNode(a.description));
    if (!a.uses_model) row.append(el("span", "tag norobot", "no model"));
    list.appendChild(row);
  });
}

restoreAnswers();
routeFromHash();
boot();


/* ---------------------------------------------------------------- plans */
/*
 * A scenario is branches of the future, each carrying dated, falsifiable
 * indicators. The page never decides what a tier is or what an outcome means —
 * both come from the backend, so adding a tier or an outcome needs no edit
 * here.
 */

const OUTCOME_LABEL = {
  pending: "not due yet",
  met: "happened",
  missed: "did not happen",
  unscorable: "cannot be marked",
};

/* Read on every visit and after every change, but redrawn only when
   something differs, so coming back to the tab keeps the place and focus. */
async function loadPlans() {
  fillPlanTiers();
  fillPlanNames();
  let data;
  try {
    data = await api("/api/plans");
  } catch (e) {
    state.plansSig = "";
    $("plan-list").replaceChildren(el("div", "empty", e.message));
    return;
  }
  fillPlanHorizons(data.horizons);
  const sig = JSON.stringify([data.record, data.scenarios]);
  if (sig === state.plansSig) return;
  state.plansSig = sig;
  renderRecord(data.record);
  renderScenarios(data.scenarios);
}

/* How far ahead the rules tier looks: the usual three, or one chosen distance
   (two weeks comes due soonest). The choices come from the backend; a model
   tier picks its own dates, so the picker shows only for a no-model tier. */
function fillPlanHorizons(horizons) {
  const select = $("plan-horizon");
  if (select.options.length < 2 && Array.isArray(horizons)) {
    horizons.forEach((h) => {
      const option = document.createElement("option");
      option.value = h.days;
      option.textContent = "only " + h.label.replace(/^in /, "");
      select.appendChild(option);
    });
  }
  syncPlanHorizon();
}

function syncPlanHorizon() {
  const tiers = (state.status && state.status.tiers) || [];
  const tier = tiers.find((t) => t.name === $("plan-tier").value);
  $("plan-horizon").hidden = !!(tier && tier.uses_model);
}
$("plan-tier").addEventListener("change", syncPlanHorizon);

function fillPlanTiers() {
  const select = $("plan-tier");
  if (select.options.length || !state.status || !state.status.tiers) return;
  state.status.tiers.forEach((tier) => {
    const option = document.createElement("option");
    option.value = tier.name;
    option.textContent = tier.uses_model ? tier.label : tier.label + " (no model)";
    select.appendChild(option);
  });
  syncPlanHorizon();
}

/* The picker offers the subjects that have signals stored, which is what a
   scenario needs; the box also takes a name ("Elon Musk") or a slug. */
async function fillPlanNames() {
  const list = $("plan-names");
  if (list.options.length) return;
  try {
    const rows = await api("/api/held");
    (rows.subjects || []).forEach((row) => {
      const option = document.createElement("option");
      option.value = row.slug;
      option.label = row.name;
      option.textContent = row.name;
      list.appendChild(option);
    });
  } catch (e) { /* the picker is a convenience; typing a slug still works */ }
}

/* 1841160000000 is not a claim anyone can check at a glance. */
function prettyNumber(value) {
  const n = Number(value);
  if (!isFinite(n)) return String(value);
  const size = Math.abs(n);
  for (const [unit, suffix] of [[1e12, "tn"], [1e9, "bn"], [1e6, "m"], [1e3, "k"]]) {
    if (size >= unit) return (n / unit).toFixed(size / unit >= 100 ? 0 : 2) + suffix;
  }
  return size >= 10 ? n.toFixed(2) : n.toPrecision(3);
}

/* What backtesting against stored history taught. Drawn apart from the live
 * ledger on purpose: being marked against the past is not being marked against
 * a future nobody had seen. */
function renderLessons(lessons) {
  const box = $("plan-lessons");
  box.innerHTML = "";
  if (!lessons || !lessons.series) {
    box.appendChild(el("div", "muted",
      "Nothing learned yet. Sweep some subjects, then learn from their history."));
    return;
  }
  const line = (label, value) => {
    const row = el("div", "ledger-row");
    row.appendChild(el("span", "k", label));
    row.appendChild(el("span", "v", String(value)));
    box.appendChild(row);
  };
  line("subjects", lessons.subjects);
  line("series backtested", lessons.series);
  line("straight-line claims held",
    `${lessons.hits} of ${lessons.claims}`
    + (lessons.hit_rate === null || lessons.hit_rate === undefined
      ? "" : ` (${Math.round(lessons.hit_rate * 100)}%)`));
  line("a line beat no change", lessons.trend_wins);
  line("no change beat a line", lessons.persistence_wins);
}

function renderRecord(record) {
  const box = $("plan-record");
  box.innerHTML = "";
  renderLessons((record || {}).backtest);
  const totals = (record || {}).totals || {};
  if (!totals.scenarios) {
    box.appendChild(el("div", "muted", "Nothing forecast yet."));
    return;
  }
  const line = (label, value) => {
    const row = el("div", "ledger-row");
    row.appendChild(el("span", "k", label));
    row.appendChild(el("span", "v", String(value)));
    box.appendChild(row);
  };
  line("scenarios", totals.scenarios);
  line("indicators settled", totals.settled);
  line("happened", totals.met);
  line("did not happen", totals.missed);
  line("not due yet", totals.pending);
  if (totals.unscorable) line("cannot be marked", totals.unscorable);
  line(
    "hit rate",
    totals.accuracy === null || totals.accuracy === undefined
      ? "— nothing has come due"
      : Math.round(totals.accuracy * 100) + "%"
  );
  Object.entries((record || {}).by_tier || {}).forEach(([tier, line2]) => {
    if (!line2.settled) return;
    box.appendChild(el("div", "small muted",
      `${tier}: ${line2.met}/${line2.settled} (${Math.round(line2.accuracy * 100)}%)`));
  });
}

function renderScenarios(scenarios) {
  const list = $("plan-list");
  list.innerHTML = "";
  if (!scenarios || !scenarios.length) {
    list.appendChild(el("div", "empty",
      "No scenarios yet. Pick a subject that has signals stored and write one."));
    return;
  }
  scenarios.forEach((scenario) => {
    const card = el("div", "card scenario");
    const head = el("div", "head");
    head.appendChild(el("b", null, scenario.title));
    head.appendChild(el("span", "tag", scenario.tier));
    if (!scenario.model) head.appendChild(el("span", "tag norobot", "no model"));
    else head.appendChild(el("span", "tag", scenario.model));
    card.appendChild(head);
    card.appendChild(el("div", "basis", `${scenario.created} — ${scenario.basis}`));

    (scenario.branches || []).forEach((branch) => {
      const box = el("div", "finding branch");
      const bh = el("div", "head");
      bh.appendChild(el("b", null, branch.name));
      if (branch.likelihood) bh.appendChild(el("span", "tag", branch.likelihood));
      box.appendChild(bh);
      if (branch.narrative) box.appendChild(el("div", "detail", branch.narrative));
      (branch.indicators || []).forEach((ind) => {
        const row = el("div", "indicator " + ind.outcome);
        row.appendChild(el("span", "outcome", OUTCOME_LABEL[ind.outcome] || ind.outcome));
        let claim = `${ind.series} ${ind.direction} ${prettyNumber(ind.threshold)}`
          + ` by ${ind.by_date}`;
        if (ind.observed !== null && ind.observed !== undefined) {
          claim += ` — it was ${prettyNumber(ind.observed)}`;
        }
        row.appendChild(el("span", "claim", claim));
        if (ind.note) row.appendChild(el("span", "means", ind.note));
        box.appendChild(row);
      });
      card.appendChild(box);
    });

    const actions = el("div", "row");
    actions.style.marginTop = "10px";
    const mark = el("button", "ghost", "Mark what is due");
    mark.addEventListener("click", async () => {
      mark.disabled = true;
      try { await api(`/api/plans/${scenario.id}/score`, { method: "POST" }); await loadPlans(); }
      catch (e) { toast(e.message, "err"); }
      finally { mark.disabled = false; }
    });
    const open = el("button", "ghost", "Open subject");
    open.addEventListener("click", () => openSubject(scenario.slug, scenario.subject));
    const drop = el("button", "ghost", "Delete");
    drop.addEventListener("click", async () => {
      const ok = await ForgeDialog.confirm(
        `Delete "${scenario.title}"? It leaves the ledger and is moved to the `
        + `plans/deleted folder, so it can be put back by hand.`, { ok: "Delete" });
      if (!ok) return;
      drop.disabled = true;
      try { await api(`/api/plans/${scenario.id}`, { method: "DELETE" }); await loadPlans(); }
      catch (e) { toast(e.message, "err"); drop.disabled = false; }
    });
    actions.append(mark, open, drop);
    card.appendChild(actions);
    list.appendChild(card);
  });
}

$("plan-make").addEventListener("click", async () => {
  const slug = $("plan-subject").value.trim();
  if (!slug) return;
  const button = $("plan-make");
  button.disabled = true;
  $("plan-note").textContent = "Working it out…";
  try {
    const horizon = $("plan-horizon");
    const body = { slug, tier: $("plan-tier").value };
    if (!horizon.hidden && horizon.value) body.horizon_days = Number(horizon.value);
    await api("/api/plans", { method: "POST", body: JSON.stringify(body) });
    $("plan-note").textContent = "";
    await loadPlans();
  } catch (e) {
    $("plan-note").textContent = e.message;
  } finally {
    button.disabled = false;
  }
});

$("plan-score").addEventListener("click", async () => {
  const button = $("plan-score");
  button.disabled = true;
  try { await api("/api/plans/score", { method: "POST" }); await loadPlans(); }
  catch (e) { toast(e.message, "err"); }
  finally { button.disabled = false; }
});

$("plan-learn").addEventListener("click", async () => {
  const button = $("plan-learn");
  button.disabled = true;
  try { await api("/api/plans/learn", { method: "POST", body: "{}" }); await loadPlans(); }
  catch (e) { toast(e.message, "err"); }
  finally { button.disabled = false; }
});


/* -------------------------------------------------------------- subject */
/*
 * Everything held about one subject in a side panel: what Dossier holds, the
 * findings, and every stored series with its newest reading and a sparkline
 * of the last 120 readings. Opened from a finding, the watchlist or a
 * scenario; the two buttons carry the subject on to the Plans or Ask tab.
 */

function seriesRow(name, meta, points) {
  const row = el("div", "sp-series");
  const top = el("div", "sp-top");
  top.appendChild(el("b", null, meta.label || name));
  const latest = meta.latest || {};
  top.appendChild(el("span", "sp-value",
    `${prettyNumber(latest.value)} on ${String(latest.date || "").slice(0, 10)}`));
  row.appendChild(top);
  row.appendChild(el("div", "small muted",
    `${meta.count.toLocaleString()} reading${meta.count === 1 ? "" : "s"} since `
    + `${String(meta.first).slice(0, 10)}${meta.unit ? " · " + meta.unit : ""}`));
  const spark = sparkline(points);
  if (spark) row.appendChild(spark);
  return row;
}

async function openSubject(slug, name) {
  if (!slug) return;
  // Focus goes back to whatever opened the panel when it closes.
  if (!state.subject) state.subjectOpener = document.activeElement;
  state.subject = { slug, name: name || slug };
  $("sp-name").textContent = name || slug;
  $("sp-slug").textContent = slug;
  const body = $("sp-body");
  body.replaceChildren(el("div", "muted small", "reading what is held…"));
  $("subject-backdrop").hidden = false;
  $("subject-panel").hidden = false;
  $("subject-panel").focus();
  let data;
  try {
    data = await api(`/api/subject/${encodeURIComponent(slug)}?points=120`);
  } catch (e) {
    if (state.subject && state.subject.slug === slug) {
      body.replaceChildren(el("div", "empty", e.message));
    }
    return;
  }
  if (!state.subject || state.subject.slug !== slug) return;
  state.subject.name = data.name;
  $("sp-name").textContent = data.name;
  const parts = [el("pre", "sp-summary", data.summary)];
  if (data.findings && data.findings.length) {
    parts.push(el("h3", null, "Findings"));
    data.findings.forEach((f) => parts.push(findingCard(f, false)));
  }
  const series = Object.entries(data.series_meta || {}).filter(([, m]) => m.latest);
  parts.push(el("h3", null, series.length ? "Stored series" : "No signals stored yet"));
  series.forEach(([key, meta]) => parts.push(seriesRow(key, meta, (data.series || {})[key])));
  body.replaceChildren(...parts);
}

function closeSubject() {
  state.subject = null;
  $("subject-panel").hidden = true;
  $("subject-backdrop").hidden = true;
  const opener = state.subjectOpener;
  state.subjectOpener = null;
  if (opener && opener.isConnected && typeof opener.focus === "function") opener.focus();
}

$("sp-close").addEventListener("click", closeSubject);
$("subject-backdrop").addEventListener("click", closeSubject);
// Escape closes the panel before it would leave full screen.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || $("subject-panel").hidden) return;
  e.preventDefault();
  e.stopPropagation();
  closeSubject();
});

$("sp-plan").addEventListener("click", () => {
  const { slug } = state.subject || {};
  closeSubject();
  showView("plans");
  $("plan-subject").value = slug || "";
  $("plan-subject").focus();
});

$("sp-ask").addEventListener("click", () => {
  const { name } = state.subject || {};
  closeSubject();
  showView("ask");
  $("ask-box").value = name || "";
  $("ask-box").focus();
});
