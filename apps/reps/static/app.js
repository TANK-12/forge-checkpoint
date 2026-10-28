"use strict";
// Reps' page: today's trackers with their streaks and a quick log, the
// history chart, and the tracker list. Every piece of text is shown with
// textContent.

const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
const WEEK = ["M", "T", "W", "T", "F", "S", "S"];
let S = null; // /api/state
let tabNow = "today";
let picked = ""; // the tracker History shows

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function svg(tag, attrs, text) {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (text !== undefined) e.textContent = text;
  return e;
}

async function api(method, url, body) {
  const r = await fetch(url, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `${r.status} ${r.statusText}`);
  return data;
}

let toastTimer = 0;
function toast(text, kind = "err", action = null) {
  const t = $("toast");
  t.textContent = text;
  if (action) {
    const b = el("button", "btn", action.label);
    b.type = "button";
    b.style.marginLeft = "10px";
    b.addEventListener("click", () => {
      t.hidden = true;
      action.run();
    });
    t.append(b);
  }
  t.className = "toast " + kind;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), action ? 9000 : 5000);
}

function dayLabel(day) {
  return new Date(day + "T12:00:00").toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function kindOf(tracker) {
  return S.kinds[tracker.kind] || null;
}

function describe(entry, kind) {
  if (!kind || !kind.fields.length) return "Done";
  const parts = kind.fields
    .filter((f) => entry.values[f.id] !== undefined)
    .map((f) => `${f.label} ${entry.values[f.id]}${f.unit ? " " + f.unit : ""}`);
  return parts.join(" · ") || "Done";
}

function streakText(st) {
  return st.current ? `🔥 ${plural(st.current, st.unit)}` : "No streak yet";
}

// --- loading -----------------------------------------------------------------

async function load() {
  const want = $("day").value;
  S = await api("GET", "/api/state" + (want ? `?day=${encodeURIComponent(want)}` : ""));
  const day = $("day");
  day.max = S.today;
  day.value = S.day;
  renderHeadline();
  renderToday();
  renderTrackers();
  if (tabNow === "history") await renderHistory();
}

function active() {
  return S.trackers.filter((t) => !t.archived);
}

function renderHeadline() {
  const list = active();
  const done = list.filter((t) => t.today.length).length;
  $("headline").textContent = list.length ? `${done} of ${list.length} done today` : "";
}

// --- today -------------------------------------------------------------------

function weekRow(t) {
  const row = el("div", "week");
  const now = (new Date(S.today + "T12:00:00").getDay() + 6) % 7;
  WEEK.forEach((letter, i) => {
    const dot = el("span", "", letter);
    if (t.week_days[i]) dot.classList.add("on");
    if (i === now) dot.classList.add("now");
    row.append(dot);
  });
  const met = t.week >= t.goal ? " ✓" : "";
  row.append(el("em", "", `${t.week} of ${t.goal} this week${met}`));
  return row;
}

function logForm(t, kind) {
  const form = el("form", "log");
  const inputs = kind.fields.map((f) => {
    const input = el("input");
    input.type = "number";
    input.min = f.min;
    input.max = f.max;
    input.step = f.step;
    input.placeholder = f.label; // the unit is in the tooltip and on the chip
    input.title = f.label + (f.unit ? ` (${f.unit})` : "");
    input.setAttribute("aria-label", input.title);
    input.required = !!f.required;
    input.dataset.field = f.id;
    form.append(input);
    return input;
  });
  const go = el("button", "btn btn-primary", kind.fields.length ? "Log" : t.on_day.length ? "Again" : "Done");
  go.type = "submit";
  form.append(go);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const values = {};
    for (const input of inputs) if (input.value !== "") values[input.dataset.field] = input.value;
    const day = S.day;
    go.disabled = true;
    try {
      await api("POST", "/api/entries", { tracker: t.id, day, values });
      if (day !== S.today) toast(`Logged ${t.name} for ${dayLabel(day)}`, "ok");
      await load();
    } catch (e) {
      toast(e.message);
    } finally {
      go.disabled = false;
    }
  });
  return form;
}

function entryChips(t, kind) {
  const chips = el("div", "chips");
  for (const entry of t.on_day) {
    const chip = el("span", "chip", describe(entry, kind));
    const x = el("button", "", "×");
    x.type = "button";
    x.title = "Remove this entry";
    x.addEventListener("click", () => removeEntry(entry, t.name));
    chip.append(x);
    chips.append(chip);
  }
  return chips;
}

function renderToday() {
  const cards = $("cards");
  cards.textContent = "";
  const list = active();
  $("today-empty").hidden = list.length > 0;
  $("day-note").textContent =
    S.day !== S.today ? `Showing and logging ${dayLabel(S.day)}; streaks and the week count from today` : "";
  for (const t of list) {
    const kind = kindOf(t);
    const card = el("article", "card");
    card.dataset.id = t.id;
    if (t.on_day.length) card.classList.add("done");
    const head = el("div", "card-head");
    head.append(el("span", "", kind ? kind.icon : "❔"), el("h3", "", t.name));
    head.append(el("span", "flame" + (t.streak.current ? "" : " cold"), streakText(t.streak)));
    card.append(head, weekRow(t));
    if (!kind) {
      card.append(el("p", "muted small", `Its kind (${t.kind}) is gone from kinds.json.`));
    } else {
      card.append(logForm(t, kind));
      if (t.on_day.length) card.append(entryChips(t, kind));
    }
    if (t.streak.best > t.streak.current) {
      card.append(el("p", "muted small", `Best: ${plural(t.streak.best, t.streak.unit)}`));
    }
    cards.append(card);
  }
}

async function removeEntry(entry, name) {
  try {
    const gone = await api("DELETE", `/api/entries/${encodeURIComponent(entry.id)}`);
    await load();
    toast(`Removed an entry from ${name}`, "ok", {
      label: "Undo",
      run: async () => {
        try {
          await api("POST", "/api/entries/restore", gone);
          await load();
        } catch (e) {
          toast(e.message);
        }
      },
    });
  } catch (e) {
    toast(e.message);
  }
}

// --- history -----------------------------------------------------------------

function fillPick() {
  const pick = $("pick");
  pick.textContent = "";
  for (const t of S.trackers) {
    const opt = el("option", "", t.name + (t.archived ? " (archived)" : ""));
    opt.value = t.id;
    pick.append(opt);
  }
  if (!S.trackers.some((t) => t.id === picked)) picked = (active()[0] || S.trackers[0] || {}).id || "";
  pick.value = picked;
}

function drawChart(chart) {
  const box = $("chart");
  box.textContent = "";
  const W = 560;
  const H = 190;
  const top = 16;
  const base = H - 22;
  const slot = W / chart.bars.length;
  const most = Math.max(1, ...chart.bars.map((b) => b.value));
  const pic = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": chart.label });
  pic.append(svg("line", { class: "axis", x1: 0, x2: W, y1: base, y2: base }));
  pic.append(svg("text", { x: 2, y: 11 }, String(most)));
  chart.bars.forEach((b, i) => {
    const x = i * slot;
    if (b.value > 0) {
      const h = Math.max(2, ((base - top) * b.value) / most);
      const bar = svg("rect", {
        class: "bar-v" + (b.day === S.today ? " today" : ""),
        x: x + 1.5,
        y: base - h,
        width: Math.max(2, slot - 3),
        height: h,
        rx: 1.5,
      });
      bar.append(svg("title", {}, `${dayLabel(b.day)}: ${b.value}`));
      pic.append(bar);
    }
    const d = new Date(b.day + "T12:00:00");
    if (d.getDay() === 1) {
      const label = d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
      pic.append(svg("text", { x: x + 1, y: H - 6 }, label));
    }
  });
  box.append(pic);
}

async function renderHistory() {
  fillPick();
  const none = !S.trackers.length;
  $("history-empty").hidden = !none;
  $("history").hidden = none;
  if (none) return;
  const want = picked;
  let h;
  try {
    h = await api("GET", `/api/trackers/${encodeURIComponent(want)}/history`);
  } catch (e) {
    toast(e.message);
    return;
  }
  if (want !== picked) return; // a later pick is on its way
  const t = h.tracker;
  const kind = kindOf(t);
  const numbers = $("numbers");
  numbers.textContent = "";
  for (const [big, small] of [
    [plural(t.streak.current, t.streak.unit), "streak now"],
    [plural(t.streak.best, t.streak.unit), "best streak"],
    [`${t.week} of ${t.goal}`, "this week"],
    [String(h.days_logged), "days logged"],
  ]) {
    const box = el("div");
    box.append(el("b", "", big), el("span", "", small));
    numbers.append(box);
  }
  $("chart-title").textContent = `${h.chart.label || "Entries"}, last eight weeks`;
  drawChart(h.chart);
  const body = $("entries").querySelector("tbody");
  body.textContent = "";
  $("entries").hidden = !h.entries.length;
  $("entries-empty").hidden = h.entries.length > 0;
  for (const e of h.entries) {
    const row = el("tr");
    row.append(el("td", "", dayLabel(e.day)), el("td", "", describe(e, kind)), el("td", "muted", e.note || ""));
    const cell = el("td");
    const x = el("button", "x", "×");
    x.type = "button";
    x.title = "Remove this entry";
    x.addEventListener("click", () => removeEntry(e, t.name));
    cell.append(x);
    row.append(cell);
    body.append(row);
  }
  const more = h.total_entries - h.entries.length;
  $("entries-more").hidden = more <= 0;
  $("entries-more").textContent = more > 0 ? `The newest ${h.entries.length} of ${h.total_entries} are shown.` : "";
}

// --- trackers ----------------------------------------------------------------

function goalOptions(select, value) {
  select.textContent = "";
  for (let n = 1; n <= 7; n++) {
    const opt = el("option", "", n === 7 ? "Every day" : `${n} day${n === 1 ? "" : "s"} a week`);
    opt.value = String(n);
    select.append(opt);
  }
  select.value = String(value);
}

function kindHelp() {
  const kind = S.kinds[$("add-kind").value];
  if (!kind) return;
  const fields = kind.fields.map((f) => f.label.toLowerCase() + (f.unit ? ` (${f.unit})` : ""));
  $("kind-help").textContent = fields.length
    ? `Each entry holds ${fields.join(" and ")}; the chart adds up ${kind.chart.label.toLowerCase()}.`
    : "One tap marks it done for the day; the chart counts the times.";
}

function fillAddForm() {
  const kindSel = $("add-kind");
  if (kindSel.options.length) return;
  for (const [id, kind] of Object.entries(S.kinds)) {
    const opt = el("option", "", `${kind.icon} ${kind.label}`);
    opt.value = id;
    kindSel.append(opt);
  }
  const first = Object.values(S.kinds)[0];
  goalOptions($("add-goal"), first ? first.goal : 7);
  kindSel.addEventListener("change", () => {
    const kind = S.kinds[kindSel.value];
    if (kind) $("add-goal").value = String(kind.goal);
    kindHelp();
  });
  kindHelp();
}

function renderTrackers() {
  fillAddForm();
  const list = $("list");
  list.textContent = "";
  $("list-empty").hidden = S.trackers.length > 0;
  const ordered = [...active(), ...S.trackers.filter((t) => t.archived)];
  for (const t of ordered) {
    const kind = kindOf(t);
    const row = el("div", "row-t" + (t.archived ? " archived" : ""));
    row.dataset.id = t.id;
    const name = el("input");
    name.value = t.name;
    name.maxLength = 60;
    name.setAttribute("aria-label", "Name");
    const goal = el("select");
    goal.setAttribute("aria-label", "Goal");
    goalOptions(goal, t.goal);
    const save = el("button", "btn", "Save");
    save.type = "button";
    save.disabled = true;
    const changed = () => (save.disabled = name.value.trim() === t.name && goal.value === String(t.goal));
    name.addEventListener("input", changed);
    goal.addEventListener("change", changed);
    save.addEventListener("click", () => edit(t, { name: name.value, goal: goal.value }));
    name.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !save.disabled) save.click();
    });
    const arch = el("button", "btn", t.archived ? "Restore" : "Archive");
    arch.type = "button";
    arch.addEventListener("click", () => edit(t, { archived: !t.archived }));
    row.append(name, el("span", "kind", kind ? `${kind.icon} ${kind.label}` : t.kind), goal, save, arch);
    list.append(row);
  }
}

async function edit(t, body) {
  try {
    await api("PATCH", `/api/trackers/${encodeURIComponent(t.id)}`, body);
    await load();
    if ("archived" in body) toast(body.archived ? `${t.name} is archived; Restore brings it back` : `${t.name} is back`, "ok");
  } catch (e) {
    toast(e.message);
  }
}

// --- wiring ------------------------------------------------------------------

function show(tab) {
  tabNow = tab;
  for (const b of document.querySelectorAll(".tab")) b.classList.toggle("on", b.dataset.tab === tab);
  for (const p of ["today", "history", "trackers"]) $("pane-" + p).hidden = p !== tab;
  if (tab === "history") renderHistory();
}

document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));
$("go-trackers").addEventListener("click", () => {
  show("trackers");
  $("add-name").focus();
});
$("day").addEventListener("change", () =>
  load().catch((e) => {
    toast(e.message); // a day the server refuses: back to today
    $("day").value = "";
    load().catch(() => {});
  }),
);
$("pick").addEventListener("change", () => {
  picked = $("pick").value;
  renderHistory();
});
$("add-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    const t = await api("POST", "/api/trackers", {
      name: $("add-name").value,
      kind: $("add-kind").value,
      goal: $("add-goal").value,
    });
    $("add-name").value = "";
    await load();
    toast(`${t.name} added; log it from Today`, "ok");
  } catch (e) {
    toast(e.message);
  }
});
// a new day while the page stays open
setInterval(() => {
  const now = new Date();
  const local = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  if (S && local !== S.today) {
    $("day").value = "";
    load().catch(() => {});
  }
}, 60000);

load().catch((e) => toast(e.message));
