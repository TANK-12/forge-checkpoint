// Prompts: the list, the editor with one box per field of the target,
// {{variables}}, versions with a diff, and what came out of each version.

import { fill, lineDiff, parseTags, stars, variables } from "./prompts-logic.js";

const $ = (id) => document.getElementById(id);
let targets = {};
let filter = ""; // a target id, or "" for all
let open = null; // the prompt being edited, as the server last sent it
let values = Object.create(null); // what is typed into the {{variable}} boxes

function say(text, bad = false) {
  $("status").textContent = text;
  $("status").classList.toggle("bad", bad);
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
  Object.assign(e, props);
  e.append(...kids);
  return e;
}

function when(seconds) {
  return new Date(seconds * 1000).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/* ---------- list ---------- */

function drawFilters() {
  const box = $("filters");
  box.replaceChildren();
  for (const [id, label] of [["", "All"], ...Object.values(targets).map((t) => [t.id, t.label])]) {
    const chip = el("button", { className: "chip" + (filter === id ? " on" : ""), textContent: label, type: "button" });
    chip.onclick = () => {
      filter = id;
      drawFilters();
      refreshList();
    };
    box.append(chip);
  }
}

async function refreshList() {
  const q = new URLSearchParams({
    q: $("search").value,
    target: filter,
    archived: $("show-archived").checked ? "true" : "false",
  });
  const items = await api(`/api/prompts?${q}`);
  const list = $("list");
  list.replaceChildren();
  if (!items.length) {
    list.append(el("p", { className: "muted small", textContent: "No prompts here yet." }));
  }
  for (const item of items) {
    const t = targets[item.target];
    const meta = `v${item.versions} · ${item.results} result${item.results === 1 ? "" : "s"}`;
    const b = el(
      "button",
      { className: "item" + (open && open.id === item.id ? " on" : ""), type: "button" },
      el("span", { className: "t", textContent: item.title }),
      el(
        "span",
        { className: "m" },
        el("span", { className: "badge", textContent: t ? t.label : item.target }),
        `${meta}${item.best ? " · " + stars(item.best) : ""}${item.tags.length ? " · " + item.tags.join(", ") : ""}`,
      ),
      el("span", { className: "p", textContent: item.preview }),
    );
    b.onclick = () => openPrompt(item.id);
    list.append(b);
  }
}

/* ---------- editor ---------- */

function latest() {
  return open.history[0];
}

function boxValues() {
  const out = {};
  document.querySelectorAll("#boxes textarea").forEach((t) => (out[t.dataset.field] = t.value));
  return out;
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // WebKitGTK may refuse the async clipboard; a hidden textarea works
    const t = el("textarea", { value: text });
    document.body.append(t);
    t.select();
    document.execCommand("copy");
    t.remove();
  }
}

function drawBoxes(fields) {
  const target = targets[$("target").value];
  const box = $("boxes");
  box.replaceChildren();
  for (const f of target.fields) {
    const area = el("textarea", { rows: f.rows || 6, value: fields[f.id] || "" });
    area.dataset.field = f.id;
    area.setAttribute("aria-label", f.label);
    area.oninput = drawVars;
    const button = el("button", { className: "btn copy", type: "button", textContent: "Copy" });
    button.onclick = async () => {
      await copy(fill(area.value, values));
      say(`Copied ${f.label}${variables(area.value).length ? ", variables filled in" : ""}.`);
    };
    box.append(el("div", { className: "box" }, el("label", {}, f.label, button), area));
  }
  drawVars();
}

function drawVars() {
  const names = variables(...Object.values(boxValues()));
  const box = $("vars");
  box.hidden = !names.length;
  box.replaceChildren(
    el("span", { className: "muted small", textContent: "Fill in the {{variables}}; Copy puts the values in." }),
  );
  for (const name of names) {
    const input = el("input", { type: "text", value: Object.hasOwn(values, name) ? values[name] : "" });
    input.setAttribute("aria-label", name);
    input.oninput = () => (values[name] = input.value);
    box.append(el("div", { className: "row" }, el("label", { textContent: name }), input));
  }
}

function drawHistory() {
  const box = $("history");
  box.replaceChildren();
  const fieldIds = targets[open.target].fields.map((f) => f.id);
  open.history.forEach((v, n) => {
    const before = open.history[n + 1];
    const summary = el("summary", {}, `v${v.n} · ${when(v.at)}`);
    if (v.note) summary.append(el("span", { className: "note", textContent: ` · ${v.note}` }));
    const diff = el("div", { className: "diff" });
    const details = el("details", { className: "version" }, summary, diff);
    // worked out when opened, so a long history does not stall each redraw
    details.ontoggle = () => {
      if (!details.open || diff.childElementCount) return;
      for (const fid of fieldIds) {
        const lines = lineDiff(before ? before.fields[fid] || "" : "", v.fields[fid] || "");
        if (!lines.length || (before && lines.every((l) => l.op === "same"))) continue;
        diff.append(el("div", { className: "fid", textContent: fid }));
        for (const l of lines) diff.append(el("div", { className: l.op, textContent: l.line || " " }));
      }
    };
    const load = el("button", { className: "btn copy", type: "button", textContent: "Load into the editor" });
    load.onclick = () => {
      drawBoxes(v.fields);
      say(`Loaded v${v.n}. Save makes it the newest version.`);
    };
    details.append(load);
    box.append(details);
  });
}

function drawOutcomes() {
  const pick = $("result-version");
  pick.replaceChildren(...open.history.map((v) => new Option(`v${v.n}`, String(v.n))));
  const box = $("outcomes");
  box.replaceChildren();
  for (const r of open.outcomes) {
    const hide = el("button", { className: "hide", type: "button", textContent: "Remove", title: "Hide this result (kept in the export)" });
    hide.onclick = async () => {
      const id = open.id;
      try {
        const got = await api(`/api/results/${r.id}`, { method: "PATCH", json: { hidden: true } });
        if (open && open.id === id) {
          open = got;
          drawOutcomes();
        }
        refreshList();
      } catch (err) {
        say(`Not removed: ${err.message}`, true);
      }
    };
    const card = el(
      "div",
      { className: "outcome" },
      el("div", { className: "h" }, el("span", {}, `v${r.version} · ${when(r.at)}`), el("span", { className: "s", textContent: r.rating ? stars(r.rating) : "" }), hide),
      el("p", { textContent: r.text }),
    );
    if (r.link) {
      const web = /^https?:\/\//.test(r.link);
      card.append(web ? el("a", { href: r.link, textContent: r.link, target: "_blank", rel: "noopener noreferrer" }) : el("code", { textContent: r.link }));
    }
    box.append(card);
  }
}

/** What is typed in the editor now. */
function editorState() {
  return { title: $("title").value, tags: $("tags").value, note: $("note").value, fields: boxValues() };
}

/** Whether the editor holds anything not saved in `open`. */
function unsaved() {
  if (!open) return false;
  const now = editorState();
  const saved = latest().fields;
  return (
    now.title.trim() !== open.title ||
    parseTags(now.tags).join() !== open.tags.join() ||
    Object.keys(now.fields).some((k) => (now.fields[k] || "") !== (saved[k] || ""))
  );
}

/** Show `p` but keep what was typed in the editor (after archiving). */
function showKeeping(p) {
  const kept = editorState();
  showPrompt(p);
  $("title").value = kept.title;
  $("tags").value = kept.tags;
  $("note").value = kept.note;
  drawBoxes(kept.fields);
}

function showPrompt(p) {
  open = p;
  $("empty").hidden = true;
  $("edit").hidden = false;
  $("title").value = p.title;
  $("target").value = p.target;
  $("tags").value = p.tags.join(", ");
  $("archive").textContent = p.archived ? "Unarchive" : "Archive";
  $("note").value = "";
  drawBoxes(latest().fields);
  drawHistory();
  drawOutcomes();
}

async function openPrompt(id) {
  showPrompt(await api(`/api/prompts/${id}`));
  say("");
  refreshList();
}

function newPrompt() {
  open = null;
  $("empty").hidden = true;
  $("edit").hidden = false;
  $("title").value = "";
  $("tags").value = "";
  $("note").value = "";
  $("target").value = filter || Object.keys(targets)[0];
  $("archive").textContent = "Archive";
  drawBoxes({});
  $("history").replaceChildren();
  $("outcomes").replaceChildren();
  $("result-version").replaceChildren();
  say("A new prompt: Save keeps it as v1.");
  $("title").focus();
  refreshList();
}

async function save() {
  const meta = { title: $("title").value, tags: parseTags($("tags").value) };
  try {
    if (!open) {
      const made = await api("/api/prompts", {
        method: "POST",
        json: { ...meta, target: $("target").value, fields: boxValues(), note: $("note").value },
      });
      showPrompt(made);
      say("Saved as v1.");
    } else {
      // title, tags and text in one request: all of it is kept or none
      const id = open.id;
      const got = await api(`/api/prompts/${id}/versions`, {
        method: "POST",
        json: { ...meta, fields: boxValues(), note: $("note").value },
      });
      if (open && open.id === id) showPrompt(got.prompt);
      say(got.made ? `Saved as v${latest().n}.` : `No change to the text; kept at v${latest().n}.`);
    }
    refreshList();
  } catch (err) {
    say(`Not saved: ${err.message}`, true);
  }
}

async function changeTarget() {
  if (!open) return drawBoxes(boxValues());
  if (unsaved()) {
    $("target").value = open.target;
    return say("Save your changes first, then change the target.", true);
  }
  try {
    showPrompt(await api(`/api/prompts/${open.id}`, { method: "PATCH", json: { target: $("target").value } }));
    say(`Now a ${targets[open.target].label} prompt.`);
    refreshList();
  } catch (err) {
    $("target").value = open.target;
    say(`${err.message}. Make a new prompt for that target instead.`, true);
  }
}

async function addResult(event) {
  event.preventDefault();
  if (!open) return say("Save the prompt first.", true);
  const id = open.id;
  try {
    const got = await api(`/api/prompts/${id}/results`, {
      method: "POST",
      json: {
        version: Number($("result-version").value),
        text: $("result-text").value,
        rating: Number($("result-rating").value),
        link: $("result-link").value,
      },
    });
    refreshList();
    if (!open || open.id !== id) return; // another prompt was opened meanwhile
    open = got;
    $("result-text").value = "";
    $("result-link").value = "";
    $("result-rating").value = "0";
    drawOutcomes();
    say("Result added.");
  } catch (err) {
    say(`Not added: ${err.message}`, true);
  }
}

async function toggleArchive() {
  if (!open) return;
  const id = open.id;
  const got = await api(`/api/prompts/${id}`, { method: "PATCH", json: { archived: !open.archived } });
  if (!open || open.id !== id) return refreshList();
  showKeeping(got);
  say(open.archived ? "Archived: it shows under Archived, nothing is deleted." : "Back in the library.");
  refreshList();
}

async function boot() {
  const state = await api("/api/state");
  targets = Object.fromEntries(state.targets.map((t) => [t.id, t]));
  $("target").replaceChildren(...state.targets.map((t) => new Option(`${t.label} (${t.hint})`, t.id)));
  drawFilters();
  await refreshList();
  let typing = 0;
  $("search").oninput = () => {
    clearTimeout(typing);
    typing = setTimeout(refreshList, 200);
  };
  $("show-archived").onchange = refreshList;
  $("new").onclick = newPrompt;
  $("save").onclick = save;
  $("target").onchange = changeTarget;
  $("archive").onclick = toggleArchive;
  $("result-form").onsubmit = addResult;
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s" && !$("edit").hidden) {
      e.preventDefault();
      save();
    }
  });
}

boot().catch((err) => say(`Prompts did not start: ${err.message}`, true));
