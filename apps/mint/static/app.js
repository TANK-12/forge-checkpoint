/* Mint's page: five tabs over the API in web_app.py.
 *   Plan    where the weekly money could go: fans of real-history futures
 *   Lab     test a trading idea on real prices, every real cost counted
 *   Paper   fake-money accounts that only run forward
 *   Ready?  the checklist an idea must pass before any real money
 *   Learn   the published figures, with sources
 * Nothing here can reach a broker or move money. #<tab>/<account id> routes.
 */

import { histChart, lineChart, money } from "/chart.js";

const $ = (sel, root = document) => root.querySelector(sel);
const pct = (v, d = 1) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(d)}%`);
const SERIES = ["#3987e5", "#d95926"]; // the idea, the plain fund: palette slots 1 and 2
const MUTED = "#8b93a3";
const GOAL = "#e4e7ee"; // the goal line: light and dashed, apart from every path colour
const PLAN_FIELDS = ["#p-start", "#p-weekly", "#p-years", "#p-goal", "#p-salary"];
const TABS = ["plan", "lab", "paper", "ready", "learn"];
const STATE_WORDS = { pass: ["✓", "passed"], fail: ["✗", "not passed"], wait: ["…", "waiting"], "n/a": ["–", "does not apply"] };
const S = { meta: null, settings: null, plan: null, planCfd: null, planRun: 0, accounts: [], learn: null };

function h(tag, props, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "style") n.style.cssText = v;
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false || kid === "") continue;
    n.append(kid instanceof Node ? kid : String(kid));
  }
  return n;
}

// replaceChildren with h()'s rules: nested lists flattened, empty values dropped
function put(host, ...kids) {
  host.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false && k !== ""));
  return host;
}

async function api(path, { method = "GET", body } = {}) {
  // every call carries X-Forge: the API refuses calls without it, reads too
  const opts = { method, headers: { "X-Forge": "1" } };
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
    const d = data && data.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((e) => `${(e.loc || []).slice(-1)[0]}: ${e.msg}`).join("; ") : "";
    throw new Error(msg || `Mint answered ${res.status}`);
  }
  return data;
}

let toastTimer = 0;
function toast(text, kind = "err") {
  const box = $("#toast");
  box.textContent = text;
  box.className = `toast ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.add("hidden"), 5000);
}

async function busy(btn, job) {
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "Working…";
  try {
    return await job();
  } catch (e) {
    toast(e.message);
    return null;
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

const num = (sel) => Number($(sel).value);
const venueOf = (id) => S.meta.venues.find((v) => v.id === id);
const marketOf = (sym) => S.meta.markets.find((m) => m.symbol === sym);
const strategyOf = (id) => S.meta.strategies.find((s) => s.id === id);

function setMode(mode) {
  document.body.classList.toggle("advanced", mode === "advanced");
  for (const b of document.querySelectorAll("#mode-switch button")) b.classList.toggle("on", b.dataset.mode === mode);
  try {
    // index.html reads it on the next open, so the first frame is already in this mode
    localStorage.setItem("mint.mode", mode);
  } catch {
    /* storage blocked: the settings file still has it */
  }
}

// ---- sliders -------------------------------------------------------------------
// A range input with data-for="<id>" moves that number field and follows it.
// The slider's own min/max/step live in index.html; the number field can go
// past the slider's end (the slider then sits at its end).

function pairSliders() {
  for (const r of document.querySelectorAll('input[type="range"][data-for]')) {
    const box = document.getElementById(r.dataset.for);
    r.addEventListener("input", () => {
      box.value = r.value;
      box.dispatchEvent(new Event("input"));
    });
    box.addEventListener("input", () => (r.value = box.value || r.min));
  }
}

function syncSliders() {
  for (const r of document.querySelectorAll('input[type="range"][data-for]')) r.value = document.getElementById(r.dataset.for).value || r.min;
  document.body.classList.add("sliders-set");
}

// ---- tabs ----------------------------------------------------------------------

function route() {
  const [tab, arg] = (location.hash.slice(1) || "plan").split("/");
  const name = TABS.includes(tab) ? tab : "plan";
  for (const t of TABS) {
    $(`#tab-${t}`).classList.toggle("active", t === name);
    $(`#tabs [data-tab="${t}"]`).setAttribute("aria-selected", String(t === name));
  }
  if (name === "paper") showPaper(arg ? decodeURIComponent(arg) : "");
  if (name === "ready") showReady(arg ? decodeURIComponent(arg) : "");
  if (name === "learn") showLearn();
}

// ---- plan ----------------------------------------------------------------------

function readPlan() {
  return {
    start: num("#p-start"),
    weekly: num("#p-weekly"),
    years: Math.round(num("#p-years")),
    comfort: Number($("#p-comfort").value),
    cautious: $("#p-cautious").checked,
    salary: $("#p-salary").value === "" ? 0 : Math.max(0, num("#p-salary")),
    goal: $("#p-goal").value === "" ? 0 : Math.max(0, num("#p-goal")),
    // the goal is in the dollars the page shows
    goal_today: $("#p-today").checked,
  };
}

// A field part-way through an edit (years cleared, a number past its limit)
// waits with a word in the status line instead of an error from the server.
function planProblem(body) {
  for (const sel of PLAN_FIELDS) {
    const el = $(sel);
    const v = el.validity;
    if (v.badInput || v.rangeUnderflow || v.rangeOverflow || v.valueMissing) {
      const name = el.closest("label").firstChild.textContent.trim();
      return `${name}: ${el.validationMessage || "not a number Mint can use"}`;
    }
  }
  if (!(body.start > 0) && !(body.weekly > 0)) return "Put in a starting amount or a weekly amount.";
  return "";
}

let planTimer = 0;
function planSoon() {
  clearTimeout(planTimer);
  planTimer = setTimeout(runPlan, 450);
}

async function runPlan() {
  const body = readPlan();
  const run = ++S.planRun;
  const status = $("#plan-status");
  const problem = planProblem(body);
  if (problem) {
    status.textContent = problem;
    return;
  }
  const { cautious, goal_today, ...keep } = body;
  api("/api/settings", { method: "POST", body: keep }).catch(() => {});
  status.textContent = "Working out a thousand futures from real history…";
  try {
    const main = await api("/api/plan", { method: "POST", body: { ...body, kinds: ["cash", "fund"] } });
    if (run !== S.planRun) return;
    S.plan = main;
    S.planCfd = null;
    renderPlan();
    status.textContent = "Now the trading path: a few hundred coin-flip traders on real ASX 200 prices…";
    const cfd = await api("/api/plan", { method: "POST", body: { ...body, kinds: ["zero_skill"] } });
    if (run !== S.planRun) return;
    S.planCfd = cfd;
    status.textContent = "";
    renderPlan();
  } catch (e) {
    if (run === S.planRun) {
      status.textContent = "";
      toast(e.message);
    }
  }
}

function renderPlan() {
  const P = S.plan;
  const today = $("#p-today").checked;
  const k = (year) => (today ? (1 + (P.inflation_pct || 0) / 100) ** -year : 1);
  const order = S.meta.paths.map((p) => p.id);
  const paths = [...P.paths, ...(S.planCfd ? S.planCfd.paths : [])].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
  const hs = P.history;
  $("#plan-history").textContent =
    `Built from ${hs.months} real months (${hs.first} to ${hs.last}), replayed a year at a time in a thousand shuffled orders. ` +
    `Over those months Australian shares made ${pct(hs.assets.au.a_year)} a year with dividends, US shares ${pct(hs.assets.us.a_year)} a year in Australian dollars, ` +
    `and the cash rate averaged ${hs.assets.cash.average_rate.toFixed(1)}%.` +
    (P.cautious ? " Cautious is on: share returns are cut a little every year." : "") +
    (today ? ` Amounts are in today's dollars (prices rising ${P.inflation_pct}% a year).` : "");
  const years = Array.from({ length: P.years + 1 }, (_, i) => i);
  const at = (p, key) => [P.start, ...p.fan.map((f) => f[key] * k(f.year))];
  const series = paths.map((p) => ({ name: p.short, color: p.colour, values: at(p, "p50") }));
  if (paths.length) series.push({ name: "Money put in", color: MUTED, dash: true, values: at(paths[0], "money_in") });
  // the goal is in the dollars shown, so it is a flat line either way; far
  // above the paths it is named over the chart instead of squashing them
  if (P.goal > 0 && P.goal_today === today)
    series.push({ name: `Your goal, ${money(P.goal)}`, color: GOAL, dash: true, guide: true, values: years.map(() => P.goal) });
  lineChart($("#plan-chart"), {
    x: years,
    series,
    height: 280,
    xFormat: (y) => (y ? `After ${y} year${y > 1 ? "s" : ""}` : "Today"),
    label: "Middle future for each path, year by year",
  });
  const cards = $("#plan-cards");
  put(cards, ...paths.map((p) => pathCard(p, P.years, k, at, goalBadge(p, P, today))));
  if (!S.planCfd) cards.append(h("article", { class: "card path-card waiting" }, h("p", { class: "muted" }, "The trading path is still being worked out…")));
  put($("#plan-info"),
    ...P.info.map((r) => h("article", { class: "card info-card" }, h("h3", {}, r.label), h("ul", {}, r.lines.map((l) => h("li", {}, l))), sources(r.sources))),
  );
  $("#plan-tax").textContent = P.tax_note || "";
  put($("#plan-table"), planTable(paths, P.years, k, P.goal > 0 && P.goal_today === today));
}

// How often a path reaches the goal: the share of futures there at its last
// year, and the first year at least half of them are.
function goalWords(g) {
  const n = g.by_year.length;
  const half = g.half_year ? `half get there by year ${g.half_year}` : `fewer than half get there within ${n} year${n === 1 ? "" : "s"}`;
  return { share: `${pct(g.share, 0)} of futures reach it after ${n} year${n === 1 ? "" : "s"}`, half };
}

function goalBadge(p, P, today) {
  if (!(P.goal > 0)) return null;
  // a goal worked out in the other dollars waits for the run already on its way
  if (!p.goal || P.goal_today !== today) return h("span", { class: "badge" }, "🎯 Goal: working it out…");
  const w = goalWords(p.goal);
  return h(
    "span",
    { class: p.goal.share >= 0.5 ? "badge good" : "badge bad", title: `Your goal: ${money(P.goal)}${today ? " in today's dollars" : ""}, before tax` },
    `🎯 ${money(P.goal)}: ${w.share}; ${w.half}`,
  );
}

function pathCard(p, years, k, at, goal) {
  const fanHost = h("div", { class: "mini" });
  const ok = p.comfort === "ok";
  const card = h(
    "article",
    { class: "card path-card" },
    h("header", {}, h("span", { class: "chip", style: `--c:${p.colour}` }), h("h3", {}, p.short)),
    h("p", { class: "muted small" }, p.label),
    h("div", { class: "big" }, money(p.end.p50 * k(years))),
    h("p", { class: "muted small" }, `middle future after ${years} year${years === 1 ? "" : "s"}; ${money(p.money_in * k(years))} put in`),
    fanHost,
    h("p", {}, p.words),
    h(
      "div",
      { class: "badges" },
      h("span", { class: ok ? "badge good" : "badge bad" }, ok ? "✓ Falls stay inside your comfort" : "⚠ Falls go past your comfort"),
      goal,
      h("span", { class: "badge" }, `${pct(p.below_money_in, 0)} of futures ended below the money put in`),
      p.locked ? h("span", { class: "badge bad" }, "🔒 Locked until you are 60") : null,
      h(
        "span",
        { class: "badge" },
        p.locked
          ? `Middle after tax (rough), and locked: ${money(p.after_tax_p50 * k(years))}`
          : `Middle if sold, after tax (rough): ${money(p.after_tax_p50 * k(years))}`,
      ),
      p.median_costs !== undefined && h("span", { class: "badge" }, `Middle costs paid: ${money(p.median_costs * k(years))}`),
    ),
    h("p", { class: "muted small" }, p.summary),
    p.locked ? h("p", { class: "note" }, p.locked) : null,
    h(
      "details",
      { class: "more" },
      h("summary", {}, "Sources and assumptions"),
      sources(p.sources),
      p.assumptions && p.assumptions.length ? h("ul", { class: "assume" }, p.assumptions.map((a) => h("li", {}, a))) : null,
      (p.notes || []).map((n) => h("p", { class: "note" }, n)),
    ),
  );
  requestAnimationFrame(() =>
    lineChart(fanHost, {
      x: Array.from({ length: years + 1 }, (_, i) => i),
      series: [
        { name: p.short, color: p.colour, values: at(p, "p50"), band: [at(p, "p10"), at(p, "p90")] },
        { name: "Money put in", color: MUTED, dash: true, values: at(p, "money_in") },
      ],
      height: 150,
      endLabels: false,
      xFormat: (y) => (y ? `After ${y} year${y > 1 ? "s" : ""}` : "Today"),
      label: `${p.short}: one in ten futures below the band, one in ten above, the line is the middle`,
    }),
  );
  return card;
}

function sources(list) {
  if (!list || !list.length) return null;
  return h("p", { class: "sources" }, "Sources: ", list.join("; "));
}

function planTable(paths, years, k, goalOn) {
  const head = ["Path", "Money put in", "One in ten below", "Middle", "One in ten above", "Ended below money in", "Worst fall (typical / bad)", "Middle after tax (rough)"];
  if (goalOn) head.push("Reach the goal");
  return h(
    "table",
    { class: "grid-table" },
    h("thead", {}, h("tr", {}, head.map((c) => h("th", {}, c)))),
    h(
      "tbody",
      {},
      paths.map((p) =>
        h(
          "tr",
          {},
          h("td", {}, p.short),
          [p.money_in, p.end.p10, p.end.p50, p.end.p90].map((v) => h("td", { class: "num" }, money(v * k(years)))),
          h("td", { class: "num" }, pct(p.below_money_in, 0)),
          h("td", { class: "num" }, `${pct(p.fall_p50, 0)} / ${pct(p.fall_p90, 0)}`),
          h("td", { class: "num" }, p.locked ? `${money(p.after_tax_p50 * k(years))}, locked until 60` : `${money(p.after_tax_p50 * k(years))} if sold`),
          goalOn ? h("td", {}, p.goal ? Object.values(goalWords(p.goal)).join("; ") : "…") : null,
        ),
      ),
    ),
  );
}

// ---- shared market / venue / strategy pickers ------------------------------------

function fillMarkets(select, venueId, keep) {
  const v = venueOf(venueId);
  const ok = (m) => !v || !v.tradeable || !v.tradeable.length || v.tradeable.includes(m.kind);
  const groups = {};
  for (const m of S.meta.markets.filter(ok)) (groups[m.kind] = groups[m.kind] || []).push(m);
  const names = { etf: "Funds (ETFs)", index: "Share indexes", share: "Single shares", fx: "Currencies", commodity: "Commodities", crypto: "Crypto" };
  put(select,
    ...Object.entries(groups).map(([kind, ms]) =>
      h("optgroup", { label: names[kind] || kind }, ms.map((m) => h("option", { value: m.symbol }, `${m.name} (${m.symbol})`))),
    ),
  );
  if (keep && [...select.options].some((o) => o.value === keep)) select.value = keep;
}

function fillSelect(select, items, keep) {
  put(select, ...items.map(([value, text]) => h("option", { value }, text)));
  if (keep && items.some(([v]) => v === keep)) select.value = keep;
}

function levCap(venueId, symbol) {
  const v = venueOf(venueId);
  const m = marketOf(symbol);
  if (!v || v.kind !== "cfd") return 1;
  const caps = v.leverage_caps || {};
  return caps[m && m.cls] || caps.default || 1;
}

function paramInputs(host, strategyId, prefix) {
  const st = strategyOf(strategyId);
  put(host,
    ...(st ? st.params : []).map((p) =>
      h(
        "label",
        { class: "field", title: p.help || "" },
        p.label,
        h("input", { type: "number", id: `${prefix}-${p.key}`, "data-key": p.key, min: p.min, max: p.max, step: p.step || 1, value: p.default }),
      ),
    ),
  );
}

function readParams(host) {
  const out = {};
  for (const inp of host.querySelectorAll("input[data-key]")) out[inp.dataset.key] = Number(inp.value);
  return out;
}

// ---- lab -----------------------------------------------------------------------

function labAbout() {
  const m = marketOf($("#l-market").value);
  const v = venueOf($("#l-venue").value);
  const st = strategyOf($("#l-strategy").value);
  const cap = levCap(v.id, m.symbol);
  const lev = $("#l-lev");
  lev.max = String(cap);
  if (Number(lev.value) > cap) lev.value = String(cap);
  $("#l-lev-field").hidden = v.kind !== "cfd";
  $("#l-lev-cap").textContent = v.kind === "cfd" ? `up to ${cap}x for this market (ASIC's cap)` : "";
  put($("#lab-about"),
    h("p", {}, h("b", {}, m.name), ": ", m.blurb),
    m.warning ? h("p", { class: "warn" }, `⚠ ${m.warning}`) : null,
    h("p", {}, h("b", {}, v.label), ": ", v.summary),
    st ? h("p", {}, h("b", {}, st.name), ": ", st.summary) : null,
  );
}

function labBody() {
  const venue = $("#l-venue").value;
  return {
    symbol: $("#l-market").value,
    venue,
    strategy: $("#l-strategy").value,
    params: readParams($("#l-params")),
    config: {
      start_cash: num("#l-start"),
      deposit: num("#l-deposit"),
      deposit_every_days: Math.round(num("#l-every")),
      leverage: venueOf(venue).kind === "cfd" ? num("#l-lev") : 1,
      stop_pct: num("#l-stop"),
    },
    start: $("#l-from").value,
    end: $("#l-to").value,
    split: num("#l-split") / 100,
    luck_runs: Math.round(num("#l-luck")),
  };
}

function buildLab() {
  fillSelect($("#l-venue"), S.meta.venues.map((v) => [v.id, v.label]), "cash");
  fillMarkets($("#l-market"), "cash", "VAS.AX");
  fillSelect($("#l-strategy"), S.meta.strategies.map((s) => [s.id, s.name]), "trend_200");
  paramInputs($("#l-params"), "trend_200", "lp");
  $("#l-venue").addEventListener("change", () => {
    fillMarkets($("#l-market"), $("#l-venue").value, $("#l-market").value);
    labAbout();
  });
  $("#l-market").addEventListener("change", labAbout);
  $("#l-strategy").addEventListener("change", () => {
    paramInputs($("#l-params"), $("#l-strategy").value, "lp");
    labAbout();
  });
  $("#l-run").addEventListener("click", (ev) =>
    busy(ev.currentTarget, async () => renderBacktest(await api("/api/backtest", { method: "POST", body: labBody() }))),
  );
  $("#l-sweep").addEventListener("click", (ev) =>
    busy(ev.currentTarget, async () => renderSweep(await api("/api/sweep", { method: "POST", body: { ...labBody(), steps: 6 } }))),
  );
  $("#l-zero").addEventListener("click", (ev) =>
    busy(ev.currentTarget, async () => {
      const b = labBody();
      const body = { symbol: b.symbol, venue: b.venue, config: b.config, years: num("#l-zyears"), runs: Math.round(num("#l-zruns")), trades_per_year: Math.round(num("#l-ztrades")), hold_days: Math.round(num("#l-zhold")) };
      renderZero(await api("/api/zero-skill", { method: "POST", body }));
    }),
  );
  labAbout();
}

function statRows(r) {
  const parts = ["whole", "tuning", "test"];
  const row = (label, f) => h("tr", {}, h("th", {}, label), parts.map((p) => h("td", { class: "num" }, f(p))));
  return h(
    "table",
    { class: "grid-table" },
    h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", {}, "Whole run"), h("th", {}, `Tuning years (to ${r.split_date})`), h("th", {}, `Test years (from ${r.split_date})`))),
    h(
      "tbody",
      {},
      row("This idea, a year", (p) => pct(r[p].money_weighted)),
      row("Plain fund, a year", (p) => pct(r.bench[p].money_weighted)),
      row("Worst fall: this idea", (p) => pct(r[p].max_drawdown, 0)),
      row("Worst fall: plain fund", (p) => pct(r.bench[p].max_drawdown, 0)),
      row("Ended with: this idea", (p) => money(r[p].final)),
      row("Ended with: plain fund", (p) => money(r.bench[p].final)),
    ),
  );
}

function costWords(t) {
  const c = t.costs;
  let s =
    `Costs paid: ${money(t.costs_total)} (spread ${money(c.spread)}, overnight funding ${money(c.funding)}, brokerage ${money(c.brokerage)}, currency ${money(c.fx)}). ` +
    `Interest on idle cash: ${money(t.interest)}. ${t.dividends ? `Dividend adjustments: ${money(t.dividends)}.` : "Dividends are already in the prices."} ` +
    `${t.entries} trade${t.entries === 1 ? "" : "s"} in, ${t.win_rate === null ? "no finished trades" : `${pct(t.win_rate, 0)} of finished trades made money`}, in the market ${pct(t.time_in_market, 0)} of the time.`;
  if (t.closeouts) s += ` The broker closed positions ${t.closeouts} times for lack of margin.`;
  if (t.stops_hit) s += ` Stop-losses hit: ${t.stops_hit}.`;
  if (t.written_off) s += ` Losses beyond the account written off by the broker: ${money(t.written_off)}.`;
  return s;
}

function tradeLog(rows) {
  if (!rows || !rows.length) return null;
  return h(
    "details",
    { class: "more adv" },
    h("summary", {}, `Trades (${rows.length} shown)`),
    h(
      "table",
      { class: "grid-table small" },
      h("thead", {}, h("tr", {}, ["Date", "Side", "Units", "Price", "Value", "Cost", "Why"].map((c) => h("th", {}, c)))),
      h(
        "tbody",
        {},
        rows.map((t) =>
          h("tr", {}, h("td", {}, t.date), h("td", {}, t.side), h("td", { class: "num" }, t.units), h("td", { class: "num" }, t.price.toFixed(2)), h("td", { class: "num" }, money(t.value)), h("td", { class: "num" }, money(t.cost)), h("td", {}, t.reason)),
        ),
      ),
    ),
  );
}

function renderBacktest(r) {
  const chart = h("div", { class: "chart-host" });
  const luck = r.luck && !r.luck.skipped ? h("div", { class: "chart-host" }) : null;
  put($("#lab-out"),
    h("p", { class: "verdict" }, r.verdict),
    r.warning ? h("p", { class: "warn" }, `⚠ ${r.warning}`) : null,
    r.source && r.source !== "yahoo" && r.source !== "rba"
      ? h("p", { class: "warn" }, `⚠ These prices did not come from Yahoo Finance or the RBA (source: ${r.source}). Mint cannot check them, so Ready? never passes on them.`)
      : null,
    (r.notes || []).map((n) => h("p", { class: "note" }, n)),
    h("h3", {}, `${r.strategy_name} on ${r.name}, ${r.venue_label}${r.leverage_used > 1 ? `, ${r.leverage_used}x` : ""}`),
    chart,
    statRows(r),
    h("p", { class: "small" }, costWords(r.trades)),
    luck ? [h("h3", {}, "Luck test"), h("p", {}, r.luck.verdict), luck, h("p", { class: "muted small" }, `${r.luck.runs} coin-flip copies of the same days: the same trades and sizes, with each day's move kept or turned round at random. The line is this idea.`)] : null,
    tradeLog(r.trade_log),
  );
  const split = r.curve.dates.findIndex((d) => d >= r.split_date);
  lineChart(chart, {
    x: r.curve.dates,
    series: [
      { name: r.strategy_name, color: SERIES[0], values: r.curve.equity },
      { name: `Plain ${r.bench.symbol}`, color: SERIES[1], values: r.curve.bench },
      { name: "Money put in", color: MUTED, dash: true, values: r.curve.money_in },
    ].filter((s) => s.values),
    marker: split > 0 ? { index: split, label: "test years →" } : null,
    label: "Account value over time: this idea, the plain fund and the money put in",
  });
  if (luck) histChart(luck, { ...r.luck.hist, markLabel: "this idea", label: "Where this idea lands among coin-flip copies of the same days" });
}

function renderSweep(s) {
  const rows = [...s.rows].sort((a, b) => b.tuning - a.tuning);
  const txt = (p) => Object.entries(p).map(([k, v]) => `${k} ${v}`).join(", ");
  put($("#lab-out"),
    h("p", { class: "verdict" }, s.verdict),
    (s.notes || []).map((n) => h("p", { class: "note" }, n)),
    h(
      "div",
      { class: "tiles" },
      [
        ["Picked on the tuning years", txt(s.best.params)],
        [`Tuning years (to ${s.split_date}), a year`, pct(s.best.tuning)],
        ["Test years after, a year", pct(s.best.test)],
      ].map(([l, v]) => h("div", { class: "tile" }, h("span", { class: "muted small" }, l), h("b", {}, v))),
    ),
    h(
      "table",
      { class: "grid-table" },
      h("thead", {}, h("tr", {}, h("th", {}, "Settings"), h("th", {}, `Tuning years (to ${s.split_date}), a year`))),
      h(
        "tbody",
        {},
        rows.map((r, i) => h("tr", { class: i === 0 ? "best" : "" }, h("td", {}, txt(r.params)), h("td", { class: "num" }, pct(r.tuning)))),
      ),
    ),
    h(
      "p",
      { class: "muted small" },
      `Only the picked setting shows its test years here. Testing settings one at a time shows every one's, so the past is a minimum only and Ready? judges luck on the first 90 paper days. Across all ${s.tried} settings, the middle one made ${pct(s.median_test)} a year on the test years.`,
    ),
  );
}

function renderZero(z) {
  const fan = z.fan && z.fan.length > 1 ? h("div", { class: "chart-host" }) : null;
  put($("#lab-out"),
    h(
      "p",
      { class: "verdict" },
      `${pct(z.lost_share, 0)} of ${z.runs} coin-flip traders lost money over ${z.years} year${z.years === 1 ? "" : "s"} on ${z.name} at ${z.leverage}x, ` +
        `${z.trades_per_year} trades a year, each held ${z.hold_days} days. ${pct(z.lost_half_share, 0)} lost more than half.`,
    ),
    h(
      "p",
      {},
      `Money put in (middle): ${money(z.money_in_median)}. Ended with: one in ten below ${money(z.p10)}, middle ${money(z.p50)}, one in ten above ${money(z.p90)}. ` +
        `Middle costs paid: ${money(z.median_costs)}. Worst fall on the way: ${pct(z.fall_p50, 0)} typical, ${pct(z.fall_p90, 0)} in a bad run.` +
        (z.closeout_share ? ` ${pct(z.closeout_share, 0)} had positions closed by the broker for lack of margin.` : ""),
    ),
    h(
      "p",
      { class: "muted small" },
      `Random start days between ${z.first} and ${z.last}, real prices and this account's real costs.` +
        ((venueOf(z.venue) || {}).kind === "cfd" ? " ASIC found 68% of Australian retail CFD clients lost money in FY24." : ""),
    ),
    (z.notes || []).map((n) => h("p", { class: "note" }, n)),
    fan,
  );
  if (fan) {
    const x = z.fan.map((f) => f.year);
    const at = (key) => z.fan.map((f) => f[key]);
    lineChart(fan, {
      x,
      series: [
        { name: "Coin-flip traders", color: SERIES[0], values: at("p50"), band: [at("p10"), at("p90")] },
        { name: "Money put in", color: MUTED, dash: true, values: at("money_in") },
      ],
      xFormat: (y) => `After ${y} year${y > 1 ? "s" : ""}`,
      label: "Coin-flip traders year by year",
    });
  }
}

// ---- paper ---------------------------------------------------------------------

async function loadAccounts() {
  const d = await api("/api/paper");
  S.accounts = d.accounts || [];
  return S.accounts;
}

function buildPaperForm() {
  fillSelect($("#n-venue"), S.meta.venues.map((v) => [v.id, v.label]), "cash");
  fillMarkets($("#n-market"), "cash", "VAS.AX");
  fillSelect($("#n-strategy"), S.meta.strategies.map((s) => [s.id, s.name]), "trend_200");
  paramInputs($("#n-params"), "trend_200", "np");
  const sync = () => {
    const bot = $("#n-kind").value === "bot";
    $("#n-bot").hidden = !bot;
    const cfd = venueOf($("#n-venue").value).kind === "cfd";
    $("#n-lev-field").hidden = !cfd;
    $("#n-lev").max = String(levCap($("#n-venue").value, $("#n-market").value));
    const least = venueOf($("#n-venue").value).min_trade || 0;
    const startWith = num("#n-start");
    $("#n-min").hidden = !(least > 0 && startWith < least);
    $("#n-min").textContent =
      `This account's smallest trade is ${money(least)}, so the first buy waits until the money in it reaches that` +
      (num("#n-deposit") > 0 ? "; the weekly top-ups get it there." : ". Add a weekly amount, or start with more.");
  };
  $("#n-kind").addEventListener("change", sync);
  $("#n-venue").addEventListener("change", () => {
    fillMarkets($("#n-market"), $("#n-venue").value, $("#n-market").value);
    sync();
  });
  $("#n-market").addEventListener("change", sync);
  $("#n-start").addEventListener("input", sync);
  $("#n-deposit").addEventListener("input", sync);
  $("#n-strategy").addEventListener("change", () => paramInputs($("#n-params"), $("#n-strategy").value, "np"));
  $("#paper-new").addEventListener("click", () => {
    $("#paper-form").hidden = !$("#paper-form").hidden;
    sync();
  });
  $("#paper-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const venue = $("#n-venue").value;
    const body = {
      name: $("#n-name").value.trim(),
      kind: $("#n-kind").value,
      symbol: $("#n-market").value,
      venue,
      strategy: $("#n-strategy").value,
      params: readParams($("#n-params")),
      start_cash: num("#n-start"),
      deposit: num("#n-deposit"),
      deposit_every_days: 7,
      leverage: venueOf(venue).kind === "cfd" ? num("#n-lev") : 1,
      stop_pct: num("#n-stop"),
    };
    await busy($("#n-make"), async () => {
      const a = await api("/api/paper", { method: "POST", body });
      $("#paper-form").hidden = true;
      toast(`Made "${a.name}". It starts from the last trading day and only runs forward.`, "ok");
      location.hash = `#paper/${encodeURIComponent(a.id)}`;
    });
  });
}

let paperSeq = 0;
let readySeq = 0;

async function showPaper(id) {
  // a slow answer for an account clicked earlier must not replace a newer one
  const seq = ++paperSeq;
  try {
    await loadAccounts();
  } catch (e) {
    toast(e.message);
    return;
  }
  if (seq !== paperSeq) return;
  const list = $("#paper-list");
  const live = S.accounts.filter((a) => !a.archived);
  const old = S.accounts.filter((a) => a.archived);
  const item = (a) =>
    h(
      "a",
      { class: `acct${a.id === id ? " on" : ""}`, href: `#paper/${encodeURIComponent(a.id)}` },
      h("b", {}, a.name),
      h("span", { class: "muted small" }, `${a.kind === "bot" ? "Bot" : "Mine"} · ${a.symbol} · ${money(a.equity)} from ${money(a.money_in)} in`),
    );
  put(list,
    live.length ? live.map(item) : h("p", { class: "muted" }, "No paper accounts yet. Make one: it starts on the last trading day and only runs forward, so its record cannot be tuned after the fact."),
    old.length ? h("details", { class: "more" }, h("summary", {}, `Archived (${old.length})`), old.map(item)) : null,
  );
  const target = id || (live[0] && live[0].id);
  const detail = $("#paper-detail");
  if (!target) {
    put(detail);
    return;
  }
  // the account on show stays (dimmed) until the next one arrives: no blank pane
  if (detail.children.length) detail.setAttribute("aria-busy", "true");
  else put(detail, h("p", { class: "muted" }, "Replaying the account…"));
  try {
    const a = await api(`/api/paper/${encodeURIComponent(target)}`);
    if (seq === paperSeq) renderAccount(a);
  } catch (e) {
    toast(e.message);
  } finally {
    if (seq === paperSeq) detail.removeAttribute("aria-busy");
  }
}

function targetWords(t) {
  if (t === 0) return "out (cash)";
  return `${Math.round(Math.abs(t) * 100)}% ${t > 0 ? "long" : "short"}`;
}

function renderAccount(a) {
  S.showing = a.id;
  const id = encodeURIComponent(a.id);
  const again = (next) => {
    if (S.showing === a.id) renderAccount(next);
  };
  const chart = a.curve.dates.length > 1 ? h("div", { class: "chart-host" }) : null;
  const venue = venueOf(a.venue);
  const orderRow = h("div", { class: "row" });
  const order = (target) =>
    h(
      "button",
      {
        type: "button",
        class: "btn",
        onclick: (ev) => {
          // one order at a time: every order button waits for the answer
          const all = [...orderRow.querySelectorAll("button")];
          all.forEach((b) => (b.disabled = true));
          busy(ev.currentTarget, async () => {
            again(await api(`/api/paper/${id}/order`, { method: "POST", body: { target } }));
            toast(`Order placed: ${targetWords(target)}. It fills at the next trading day's open.`, "ok");
          }).finally(() => all.forEach((b) => (b.disabled = false)));
        },
      },
      target === 1 ? "All in" : target === 0.5 ? "Half in" : target === 0 ? "Out" : target === -0.5 ? "Half short" : "All short",
    );
  const manual = a.kind === "manual" && !a.archived;
  put($("#paper-detail"),
    h("h2", {}, a.name),
    h(
      "p",
      { class: "muted" },
      `${a.kind === "bot" ? `Bot: ${a.strategy_name}` : "Your own trades"} on ${a.market}, ${a.venue_label}${a.config.leverage > 1 ? `, ${a.config.leverage}x` : ""}. ` +
        `Running since ${a.since}: ${a.days} trading day${a.days === 1 ? "" : "s"}, prices up to ${a.last_date}.`,
    ),
    a.archived ? h("p", { class: "note" }, `Archived on ${a.archived}: it stopped there and stays listed. Nothing is deleted.`) : null,
    h(
      "div",
      { class: "tiles" },
      [
        ["Value now", money(a.equity)],
        ["Money put in", money(a.money_in)],
        ["Profit", money(a.profit)],
        a.bench ? [`Plain ${a.bench.symbol}, same deposits`, money(a.bench.final)] : ["Plain fund", "no prices"],
      ].map(([l, v]) => h("div", { class: "tile" }, h("span", { class: "muted small" }, l), h("b", {}, v))),
    ),
    chart || h("p", { class: "muted small" }, "The chart starts once there are two trading days."),
    manual
      ? h(
          "div",
          { class: "card" },
          h("p", {}, `Position now: ${targetWords(a.exposure)}. Wanted: ${targetWords(a.wanted)}.`),
          put(orderRow, order(1), order(0.5), order(0), venue && venue.allow_short ? [order(-0.5), order(-1)] : null),
          h("p", { class: "muted small" }, "An order fills at the open of the next trading day, at the real price plus the real spread and costs."),
        )
      : null,
    a.kind === "bot" ? h("p", { class: "muted small" }, "A bot is frozen: its rules cannot change after it starts, so its record stays honest.") : null,
    a.orders && a.orders.length ? h("details", { class: "more" }, h("summary", {}, `Orders (${a.orders.length})`), h("ul", {}, a.orders.map((o) => h("li", {}, `${o.date}: ${targetWords(o.target)}`)))) : null,
    (a.notes || []).map((n) => h("p", { class: "note" }, n)),
    a.warning ? h("p", { class: "warn" }, `⚠ ${a.warning}`) : null,
    h("p", { class: "small" }, costWords(a.trades)),
    tradeLog(a.trade_log),
    h(
      "div",
      { class: "row" },
      h(
        "button",
        {
          type: "button",
          class: "btn",
          onclick: (ev) => busy(ev.currentTarget, async () => again(await api(`/api/paper/${id}/refresh`, { method: "POST" }))),
        },
        "Fetch new prices",
      ),
      h("a", { class: "btn", href: `#ready/${id}` }, "Is it ready?"),
      a.archived
        ? null
        : h(
            "button",
            {
              type: "button",
              class: "btn btn-danger",
              onclick: (ev) => {
                if (!confirm("Archive stops this account on today's date. It stays listed and nothing is deleted. Archive it?")) return;
                busy(ev.currentTarget, async () => {
                  await api(`/api/paper/${id}/archive`, { method: "POST" });
                  showPaper(a.id);
                });
              },
            },
            "Archive",
          ),
    ),
  );
  if (chart) {
    lineChart(chart, {
      x: a.curve.dates,
      series: [
        { name: a.name, color: SERIES[0], values: a.curve.equity },
        a.bench ? { name: `Plain ${a.bench.symbol}`, color: SERIES[1], values: a.curve.bench } : null,
        { name: "Money put in", color: MUTED, dash: true, values: a.curve.money_in },
      ].filter((s) => s && s.values),
      label: "This paper account against the plain fund",
    });
  }
}

// ---- ready ---------------------------------------------------------------------

async function showReady(id) {
  const seq = ++readySeq;
  try {
    await loadAccounts();
  } catch (e) {
    toast(e.message);
    return;
  }
  if (seq !== readySeq) return;
  const sel = $("#ready-account");
  const live = S.accounts.filter((a) => !a.archived);
  fillSelect(sel, S.accounts.map((a) => [a.id, `${a.name}${a.archived ? " (archived)" : ""}`]), id || (live[0] && live[0].id));
  const out = $("#ready-out");
  if (!sel.value) {
    put(out, h("p", { class: "muted" }, "Make a paper account first (Paper tab). The checklist judges an idea on its forward record, never on tuned history alone."));
    return;
  }
  // an earlier checklist stays (dimmed) while this one is worked out
  if (out.querySelector(".checks")) out.setAttribute("aria-busy", "true");
  else put(out, h("p", { class: "muted" }, "Checking…"));
  try {
    const r = await api(`/api/paper/${encodeURIComponent(sel.value)}/ready?comfort=${S.settings.comfort}`);
    if (seq !== readySeq) return;
    put(out,
      h("p", { class: "muted" }, `Checked: ${r.account.name} (${r.account.market}).`),
      h(
        "ul",
        { class: "checks" },
        r.checks.map((c) => {
          const [icon, word] = STATE_WORDS[c.state] || ["?", c.state];
          return h("li", { class: `check ${c.state === "n/a" ? "na" : c.state}` }, h("span", { class: "icon", "aria-hidden": "true" }, icon), h("div", {}, h("b", {}, c.label), h("span", { class: "muted small" }, ` ${word}. `), h("span", { class: "small" }, c.detail)));
        }),
      ),
      r.passed ? h("div", { class: "card" }, h("h3", {}, "Every check passed. A plan you could carry out yourself:"), h("ol", {}, r.plan.map((l) => h("li", {}, l)))) : h("div", { class: "card" }, r.meanwhile.map((l) => h("p", {}, l))),
      h("p", { class: "muted small" }, "Mint never trades. Real money only ever moves by your own hand, after your explicit OK. Account files live on this laptop: a hand-made file can fake a record, so a pass is only as honest as the files."),
    );
  } catch (e) {
    if (seq !== readySeq) return;
    put(out);
    toast(e.message);
  } finally {
    if (seq === readySeq) out.removeAttribute("aria-busy");
  }
}

// ---- learn ---------------------------------------------------------------------

async function showLearn() {
  if (S.learn) return;
  try {
    S.learn = await api("/api/learn");
  } catch (e) {
    put($("#learn-out"), h("p", { class: "muted" }, `Mint could not load the figures: ${e.message}`));
    return;
  }
  const groups = {};
  for (const f of S.learn.facts) (groups[f.group] = groups[f.group] || []).push(f);
  put($("#learn-out"),
    h("p", { class: "muted" }, S.learn.about),
    Object.entries(groups).map(([g, fs]) => [
      h("h2", {}, g),
      h("div", { class: "facts" }, fs.map((f) => h("article", { class: "card fact" }, h("div", { class: "big" }, f.figure), h("p", {}, f.words), h("p", { class: "sources" }, f.source)))),
    ]),
  );
}

// ---- start ---------------------------------------------------------------------

async function init() {
  try {
    [S.meta, S.settings] = await Promise.all([api("/api/meta"), api("/api/settings")]);
  } catch (e) {
    toast(`Mint could not start: ${e.message}`);
    return;
  }
  setMode(S.settings.mode);
  for (const b of document.querySelectorAll("#mode-switch button")) {
    b.addEventListener("click", () => {
      setMode(b.dataset.mode);
      api("/api/settings", { method: "POST", body: { mode: b.dataset.mode } }).catch(() => {});
    });
  }
  $("#p-start").value = S.settings.start;
  $("#p-weekly").value = S.settings.weekly;
  $("#p-years").value = S.settings.years;
  $("#p-salary").value = S.settings.salary > 0 ? S.settings.salary : "";
  $("#p-goal").value = S.settings.goal > 0 ? S.settings.goal : "";
  pairSliders();
  syncSliders();
  // a new paper account starts like the plan: the same start and weekly amount
  $("#n-start").value = S.settings.start;
  $("#n-deposit").value = S.settings.weekly;
  fillSelect($("#p-comfort"), S.meta.comfort.map((c) => [String(c.fall), c.label]), String(S.settings.comfort));
  for (const sel of [...PLAN_FIELDS, "#p-comfort", "#p-cautious"]) {
    $(sel).addEventListener("input", planSoon);
    $(sel).addEventListener("change", planSoon);
  }
  $("#p-comfort").addEventListener("change", () => (S.settings.comfort = Number($("#p-comfort").value)));
  $("#p-today").addEventListener("change", () => {
    if (S.plan) renderPlan();
    // a goal is in the dollars shown, so switching them asks again
    if (readPlan().goal > 0) planSoon();
  });
  $("#ready-account").addEventListener("change", () => (location.hash = `#ready/${encodeURIComponent($("#ready-account").value)}`));
  buildLab();
  buildPaperForm();
  window.addEventListener("hashchange", route);
  route();
  runPlan();
}

init();
