/* Taleforge front end. The server owns every rule; this file only draws the
   view it returns and sends actions back ({do: ...}). */
"use strict";

const $ = (id) => document.getElementById(id);
const S = { save: null, view: null, target: null, creation: null, campaign: null, roll: null, polling: null };

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return n;
}
const btn = (text, onclick, cls = "btn", extra = {}) => el("button", { class: cls, type: "button", onclick, ...extra }, text);

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

let toastTimer = null;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 4200);
}

function show(screen) {
  for (const id of ["home", "create", "play"]) $(id).hidden = id !== screen;
  $("clock").hidden = $("gold").hidden = $("hp").hidden = screen !== "play";
  if (screen !== "play") $("where").textContent = "";
}

/* text size --------------------------------------------------------------- */
function setSize(px) {
  px = Math.max(16, Math.min(34, px));
  document.documentElement.style.setProperty("--story-size", px + "px");
  localStorage.setItem("taleforge.size", px);
}
$("smaller").onclick = () => setSize((+localStorage.getItem("taleforge.size") || 21) - 2);
$("bigger").onclick = () => setSize((+localStorage.getItem("taleforge.size") || 21) + 2);
setSize(+localStorage.getItem("taleforge.size") || 21);

/* home -------------------------------------------------------------------- */
async function home() {
  show("home");
  stopPolling();
  const [{ campaigns }, { saves }, settings] = await Promise.all([api("/api/campaigns"), api("/api/saves"), api("/api/settings")]);
  const names = Object.fromEntries(campaigns.map((c) => [c.id, c.name]));
  $("campaigns").replaceChildren(
    ...campaigns.map((c) =>
      el("button", { class: "card", type: "button", onclick: () => create(c.id) },
        el("h3", { text: c.name }),
        el("p", { class: "muted", text: c.genre ? `${c.genre} · ${c.ruleset}` : c.ruleset }),
        el("p", { text: c.tagline }),
        el("p", { class: "muted small", text: `${c.counts.regions} regions, ${c.counts.locations} places, ${c.counts.quests} quests, ${c.counts.companions} companions` }))));
  $("saves").replaceChildren(
    ...(saves.length ? saves.map((s) =>
      el("div", { class: "save" },
        el("div", { class: "grow" },
          el("b", { text: s.name }), ` · level ${s.level} ${s.class} · ${names[s.campaign] || s.campaign} · day ${s.day}`,
          s.ending ? el("span", { class: "muted", text: " · finished" }) : null),
        btn("Continue", () => open(s.id), "btn btn-primary"),
        btn("Move to trash", async () => {
          if (!confirm(`Move ${s.name}'s game to the trash folder?`)) return;
          await api(`/api/saves/${s.id}`, { method: "DELETE" });
          home();
        }, "btn btn-danger"))) : [el("p", { class: "muted", text: "No saved games yet." })]));
  $("narrate").checked = settings.narrate;
  const problems = [settings.jan_error ? `Last Jan problem: ${settings.jan_error}` : "", ...(settings.jan_notes || [])];
  $("jan-error").textContent = problems.filter(Boolean).join(" · ");
  if (!home.janDrawn && window.ForgeJan) {
    ForgeJan.panel($("jan-panel"), { labels: { dialogue: "Characters (dialogue)", narration: "Narrator (world)" } });
    home.janDrawn = true;
  }
}
$("narrate").onchange = (e) => api("/api/settings", { method: "POST", body: { narrate: e.target.checked } });
$("menu").onclick = () => home().catch((e) => toast(e.message));

/* character creation -------------------------------------------------------- */
const C = { cls: null, bg: null, method: "array", scores: {}, skills: new Set() };

async function create(cid) {
  S.campaign = cid;
  S.creation = await api(`/api/campaigns/${cid}/creation`);
  const cr = S.creation;
  $("create-title").textContent = `New character · ${cr.campaign.name}`;
  $("create-tagline").textContent = cr.campaign.tagline;
  C.cls = cr.classes[0].id;
  C.bg = cr.backgrounds[0].id;
  C.skills = new Set();
  setMethod("array");
  drawCreate();
  show("create");
  $("c-name").focus();
}

function setMethod(m) {
  C.method = m;
  const spec = S.creation.ability_scores;
  C.scores = {};
  if (m === "point_buy") for (const a of S.creation.abilities) C.scores[a.id] = spec.point_buy.min;
  if (m === "array") {
    const cls = S.creation.classes.find((c) => c.id === C.cls);
    const order = [...S.creation.abilities.map((a) => a.id)].sort((a, b) => (a === cls.primary ? -1 : b === cls.primary ? 1 : 0));
    const vals = [...spec.standard_array].sort((a, b) => b - a);
    order.forEach((a, i) => (C.scores[a] = vals[i]));
  }
  $("c-reroll").hidden = m !== "roll";
  if (m === "roll" && !S.roll) rollScores();
}

async function rollScores() {
  S.roll = await api(`/api/campaigns/${S.campaign}/roll`, { method: "POST" });
  const sorted = [...S.roll.scores].sort((a, b) => b - a);
  S.creation.abilities.forEach((a, i) => (C.scores[a.id] = sorted[i]));
  drawCreate();
}
$("c-reroll").onclick = rollScores;
for (const r of document.querySelectorAll("input[name=method]")) r.onchange = () => { setMethod(r.value); drawCreate(); };

const mod = (v) => { const m = Math.floor((v - 10) / 2); return (m >= 0 ? "+" : "") + m; };

function drawCreate() {
  const cr = S.creation;
  const cls = cr.classes.find((c) => c.id === C.cls);
  const bg = cr.backgrounds.find((b) => b.id === C.bg);
  $("c-classes").replaceChildren(...cr.classes.map((c) =>
    el("button", { class: "card" + (c.id === C.cls ? " on" : ""), type: "button", onclick: () => { C.cls = c.id; C.skills.clear(); if (C.method === "array") setMethod("array"); drawCreate(); } },
      el("h3", { text: c.name }), el("p", { class: "small", text: c.about }),
      el("p", { class: "muted small", text: `d${c.hit_die} hit die · ${c.abilities.filter((a) => a.level === 1).map((a) => a.name).join(", ")}` }))));
  $("c-backgrounds").replaceChildren(...cr.backgrounds.map((b) =>
    el("button", { class: "card" + (b.id === C.bg ? " on" : ""), type: "button", onclick: () => { C.bg = b.id; C.skills.clear(); drawCreate(); } },
      el("h3", { text: b.name }), el("p", { class: "small", text: b.about }),
      el("p", { class: "muted small", text: "Skills: " + b.skills.map((s) => cr.skills.find((k) => k.id === s)?.name || s).join(", ") }))));
  const spec = cr.ability_scores;
  let budget = "";
  if (C.method === "point_buy") {
    const cost = Object.values(C.scores).reduce((t, v) => t + spec.point_buy.cost[String(v)], 0);
    budget = `${spec.point_buy.budget - cost} of ${spec.point_buy.budget} points left`;
  }
  $("c-budget").textContent = budget;
  const pool = C.method === "array" ? spec.standard_array : C.method === "roll" && S.roll ? S.roll.scores : null;
  $("c-scores").replaceChildren(...cr.abilities.map((a) => {
    let input;
    if (pool) {
      input = el("select", { onchange: (e) => swapScore(a.id, +e.target.value) },
        ...[...pool].sort((x, y) => y - x).map((v) => el("option", { value: v, selected: v === C.scores[a.id] }, v)));
    } else {
      input = el("input", { type: "number", min: spec.point_buy.min, max: spec.point_buy.max, value: C.scores[a.id] ?? 8,
        onchange: (e) => { C.scores[a.id] = Math.max(spec.point_buy.min, Math.min(spec.point_buy.max, +e.target.value)); drawCreate(); } });
    }
    return el("div", { class: "score" }, el("b", { text: a.name }), input, el("span", { class: "mod", text: mod(C.scores[a.id] ?? 10) }));
  }));
  drawSkills(cr, cls, bg);
}

function drawSkills(cr, cls, bg) {
  $("c-skillnote").textContent = `choose ${cls.skill_count}, ${C.skills.size} picked (your background gives ${bg.skills.length})`;
  $("c-skills").replaceChildren(...TaleLogic.skillRows(cr.skills, cls, bg, C.skills).map((s) => {
    const box = el("input", { type: "checkbox", checked: s.checked, disabled: s.locked,
      onchange: (e) => {
        if (!TaleLogic.tickSkill(C.skills, s.id, e.target.checked, cls.skill_count)) {
          e.target.checked = false;
          toast(`Pick ${cls.skill_count} skills; untick one first.`);
        }
        drawSkills(cr, cls, bg);
      } });
    return el("label", { class: "skill" + (s.locked ? " from-bg" : "") }, box,
      el("span", { class: "grow", text: s.name }),
      el("span", { class: "muted small", text: s.locked ? `${s.ability}, background` : s.ability }));
  }));
}

function swapScore(ability, value) {
  const other = Object.keys(C.scores).find((k) => k !== ability && C.scores[k] === value);
  if (other) C.scores[other] = C.scores[ability];
  C.scores[ability] = value;
  drawCreate();
}

$("c-back").onclick = () => home();
$("create-form").onsubmit = async (e) => {
  e.preventDefault();
  $("c-error").textContent = "";
  const character = {
    name: $("c-name").value, pronouns: $("c-pronouns").value, look: $("c-look").value,
    class: C.cls, background: C.bg, method: C.method, scores: C.scores, skills: [...C.skills],
    roll_token: S.roll?.token,
  };
  try {
    const v = await api("/api/saves", { method: "POST", body: { campaign: S.campaign, character } });
    S.roll = null;
    enter(v);
  } catch (err) {
    $("c-error").textContent = err.message;
  }
};

/* playing ------------------------------------------------------------------ */
async function open(sid) {
  enter(await api(`/api/saves/${sid}`));
}

function enter(v) {
  S.save = v.id;
  $("log").replaceChildren();
  S.seen = new Set();
  show("play");
  render(v);
  $("input").focus();
}

async function act(action) {
  if (S.busy) return;
  S.busy = true;
  document.body.classList.add("busy");
  try {
    render(await api(`/api/saves/${S.save}/act`, { method: "POST", body: { action } }));
  } catch (err) {
    toast(err.message);
  } finally {
    S.busy = false;
    document.body.classList.remove("busy");
  }
}

$("say").onsubmit = (e) => {
  e.preventDefault();
  const text = $("input").value.trim();
  if (!text) return;
  $("input").value = "";
  act({ do: "text", text });
};

function render(v) {
  S.view = v;
  $("where").textContent = `${v.campaign.name} · ${v.here.name}${v.here.region ? ", " + v.here.region : ""}`;
  $("clock").textContent = `Day ${v.day}, ${v.clock} (${v.period})`;
  $("gold").textContent = `${v.gold} ${v.labels.gold || "gold"}`;
  $("hp").textContent = `${v.labels.hp || "HP"} ${v.sheet.hp}/${v.sheet.max_hp}`;
  $("hp").classList.toggle("low", v.sheet.hp * 3 <= v.sheet.max_hp);
  drawLog(v.log);
  drawChoices(v);
  drawCombat(v);
  // the fight and scene panels take room from the log; keep its last lines in view
  $("log").scrollTop = $("log").scrollHeight;
  drawHere(v);
  drawChar(v);
  drawParty(v);
  drawQuests(v);
  drawBag(v);
  lockSide(v);
  poll();
}

/* the story log */
function entryText(e) { return e.jan_text || e.text || ""; }

function entryNode(e) {
  const cls = `e ${e.kind.replace("_", "-")}` + (e.pending ? " pending" : "") + (e.jan_text ? " jan" : "");
  const k = e.kind;
  const txt = entryText(e);
  if (k === "intro") return el("div", { class: cls }, el("h2", { text: e.title }), el("p", { text: txt }));
  if (k === "place") return el("div", { class: cls }, el("h3", { text: e.title }), el("p", { text: txt }));
  if (k === "speech" || (k === "scene" && e.speaker)) return el("div", { class: cls + (k === "scene" ? " voiced" : "") }, el("span", { class: "who", text: e.name }), txt);
  if (k === "scene_title") return el("div", { class: "e scene-title", text: e.text });
  if (k === "roll") return el("div", { class: cls + (e.success ? " ok" : " no") + (e.enemy ? " enemy" : ""), text: e.text });
  if (k === "ending") return el("div", { class: cls }, el("h2", { text: e.title }), el("p", { text: e.text }), btn("Back to the games list", () => home()));
  if (k === "topics") {
    return el("div", { class: "e topics" }, el("div", { class: "opts" },
      ...e.topics.map((t) => btn(t.prompt, () => act({ do: "topic", to: e.to, topic: t.id }), "btn opt"))));
  }
  if (k === "offers") {
    return el("div", { class: "e offers" }, el("p", { text: e.text }), ...e.offers.map((o) =>
      el("div", { class: "offer" }, el("b", { text: o.name }), el("p", { text: o.summary }),
        el("span", { class: "muted", text: `Reward: ${o.rewards.xp} XP, ${o.rewards.gold} ${S.view.labels.gold || "gold"} ` }),
        btn("Take it", () => act({ do: "take_work", id: o.id }), "btn opt"))));
  }
  if (k === "prose" && !txt && !e.pending) return null;
  if (k === "prose" && !txt) return el("div", { class: cls + " prose" }, "");
  return el("div", { class: cls, text: txt });
}

function drawLog(log) {
  const box = $("log");
  let chips = box.lastElementChild?.classList.contains("chips") ? box.lastElementChild : null;
  for (const e of log) {
    if (S.seen.has(e.id)) continue;
    S.seen.add(e.id);
    if (e.kind === "chip") {
      if (!chips) { chips = el("div", { class: "chips" }); box.append(chips); }
      chips.append(el("span", { class: `chip ${e.tone || "info"}`, text: e.text }));
      continue;
    }
    chips = null;
    const n = entryNode(e);
    if (n) { n.dataset.id = e.id; box.append(n); }
  }
  for (const old of box.querySelectorAll(".e.topics, .e.offers")) {
    if (old !== box.lastElementChild) old.querySelectorAll("button").forEach((b) => b.disabled = true);
  }
  box.scrollTop = box.scrollHeight;
}

/* waiting for Jan */
function stopPolling() { clearTimeout(S.polling); S.polling = null; }

function poll(round = 0) {
  stopPolling();
  const ids = [...$("log").querySelectorAll(".pending")].map((n) => n.dataset.id).filter(Boolean);
  if (!ids.length || round > 120 || !S.save) return;
  S.polling = setTimeout(async () => {
    try {
      const { entries } = await api(`/api/saves/${S.save}/entries?ids=${ids.join(",")}`);
      for (const e of entries) {
        if (e.pending) continue;
        const old = $("log").querySelector(`[data-id="${e.id}"]`);
        const n = entryNode(e);
        if (old && n) { n.dataset.id = e.id; old.replaceWith(n); } else if (old) old.remove();
      }
      const box = $("log");
      box.scrollTop = box.scrollHeight;
    } catch (err) { /* the server may be restarting; try again */ }
    poll(round + 1);
  }, 1500);
}

/* scene choices */
function drawChoices(v) {
  const box = $("choices");
  box.hidden = !v.scene;
  if (!v.scene) return box.replaceChildren();
  box.replaceChildren(...v.scene.choices.map((c, i) =>
    el("button", { class: "btn", type: "button", onclick: () => act({ do: "choose", index: c.index }) },
      `${i + 1}. ${c.text}`, c.check ? el("span", { class: "tag", text: c.check }) : null)));
}

/* combat */
function drawCombat(v) {
  const box = $("combat");
  box.hidden = !v.combat;
  $("say").hidden = !!v.scene;
  if (!v.combat) return box.replaceChildren();
  const alive = v.combat.enemies.filter((e) => !e.down);
  if (!alive.find((e) => e.uid === S.target)) S.target = alive[0]?.uid;
  const powers = v.sheet.powers.filter((p) => p.kind !== "passive");
  box.replaceChildren(
    el("div", { class: "muted", text: `Round ${v.combat.round} · you: ${v.sheet.hp}/${v.sheet.max_hp} ${v.labels.hp || "HP"}, ${v.labels.ac || "AC"} ${v.sheet.ac} · pick a target` }),
    el("div", { class: "foes" }, ...v.combat.enemies.map((e) =>
      el("button", { class: "foe" + (e.uid === S.target ? " on" : "") + (e.down ? " down" : ""), type: "button", disabled: e.down,
        onclick: () => { S.target = e.uid; drawCombat(S.view); } },
        el("b", { text: e.name }), ` ${e.hp}/${e.max_hp} · AC ${e.ac}`,
        el("div", { class: "bar" }, el("i", { style: `width:${(100 * e.hp) / e.max_hp}%` }))))),
    el("div", { class: "row" },
      btn(`Attack (${v.sheet.weapon})`, () => act({ do: "attack", target: S.target }), "btn btn-primary"),
      ...powers.map((p) => btn(p.max ? `${p.name} (${p.uses}/${p.max})` : p.name, () => act({ do: "ability", id: p.id, target: S.target }), "btn", { disabled: p.max && !p.uses })),
      ...v.combat.items.map((i) => btn(`${i.name} x${i.count}`, () => act({ do: "item", item: i.id }))),
      btn("Defend", () => act({ do: "defend" })),
      btn("Flee", () => act({ do: "flee" }), "btn btn-danger")));
}

/* side panels */
// Mid-fight or mid-scene only the panel under the story acts; the side
// buttons would just be refused, so grey them out and say why.
function lockSide(v) {
  const why = v.combat ? "In a fight: use the buttons under the story." : v.scene ? "Pick one of the choices first." : "";
  for (const id of ["tab-here", "tab-char", "tab-party", "tab-quests", "tab-bag"]) {
    const tab = $(id);
    if (!tab) continue;
    tab.querySelectorAll("button, select").forEach((b) => {
      if (why && !b.dataset.combat) b.disabled = true;
    });
    if (why) tab.prepend(el("p", { class: "muted lock-note", text: why }));
  }
}

function pane(id, ...kids) { $(id).replaceChildren(...kids.flat().filter(Boolean)); }

function drawHere(v) {
  const h = v.here;
  const doing = [];
  if (h.can_explore) doing.push(btn("Explore the area (1 hour)", () => act({ do: "explore" })));
  if (h.board) doing.push(btn("Look for work", () => act({ do: "work" })));
  doing.push(btn("Look around", () => act({ do: "look" }), "btn", { "data-combat": "1" }));
  doing.push(btn(`${v.labels.rest_short || "Short rest"} (1 hour)`, () => act({ do: "rest", kind: "short" })));
  if (h.can_sleep) doing.push(btn(`${h.sleep_how === "camp" ? "Make camp" : v.labels.rest_long || "Sleep"}${h.rest_cost ? ` (${h.rest_cost} ${v.labels.gold || "gold"})` : ""}`, () => act({ do: "rest", kind: "long" })));
  pane("tab-here",
    el("h2", { text: h.name }), el("p", { class: "muted", text: h.region }),
    el("p", { text: h.description }),
    el("h3", { text: "Go" }),
    el("div", { class: "list" }, ...h.exits.map((x) =>
      btn(`${x.label}${x.hours >= 1 ? ` (${x.hours} h)` : ""}${x.visited ? "" : " • new"}`, () => act({ do: "go", to: x.to }),
        "btn" + (x.open ? "" : " locked"), { title: x.locked || x.name, disabled: !x.open }))),
    h.people.length ? el("h3", { text: "People" }) : null,
    el("div", { class: "list" }, ...h.people.map((p) =>
      el("div", { class: "item" },
        el("span", { class: "grow" }, el("b", { text: p.name }), p.in_party ? el("span", { class: "muted", text: " (with you)" }) : null),
        btn("Talk", () => act({ do: "talk", to: p.id })),
        p.can_recruit ? btn("Ask to join", () => act({ do: "recruit", to: p.id })) : null))),
    h.features.length ? el("h3", { text: "Look closer" }) : null,
    el("div", { class: "list" }, ...h.features.map((f) =>
      btn(`${f.name}${f.used ? " (done)" : ""}`, () => act({ do: "examine", feature: f.id }), "btn" + (f.used ? " locked" : "")))),
    el("h3", { text: "Do" }), el("div", { class: "list" }, ...doing),
    h.shop ? [el("h3", { text: h.shop.name }), el("div", { class: "list" }, ...h.shop.items.map((i) =>
      el("div", { class: "item", title: i.text },
        el("span", { class: "grow", text: i.name }), el("span", { class: "muted", text: `${i.price} ${v.labels.gold || "gold"}` }),
        btn("Buy", () => act({ do: "buy", item: i.id }), "btn", { disabled: v.gold < i.price }))))] : null);
}

function drawChar(v) {
  const c = v.sheet;
  const xpPct = c.xp_next ? (100 * c.xp) / c.xp_next : 100;
  pane("tab-char",
    el("h2", { text: c.name }),
    el("p", { class: "muted", text: `Level ${c.level} ${c.class} · ${c.background} · ${c.pronouns}` }),
    el("div", {}, `${v.labels.hp || "HP"} ${c.hp} / ${c.max_hp}`, el("div", { class: "bar hp" }, el("i", { style: `width:${(100 * c.hp) / c.max_hp}%` }))),
    el("div", { style: "margin-top:.4rem" }, `${v.labels.xp || "XP"} ${c.xp}${c.xp_next ? " / " + c.xp_next : " (top level)"}`, el("div", { class: "bar xp" }, el("i", { style: `width:${Math.min(100, xpPct)}%` }))),
    el("h3", { text: "Numbers" }),
    el("div", { class: "kv" }, el("span", { text: v.labels.ac || "AC" }), el("b", { text: c.ac }),
      el("span", { text: "Attack" }), el("b", { text: `${c.attack} with ${c.weapon}, ${c.damage}` }),
      el("span", { text: "Proficiency" }), el("b", { text: c.proficiency })),
    el("h3", { text: c.ability_points ? `Abilities (${c.ability_points} points to spend)` : "Abilities" }),
    el("div", { class: "statgrid" }, ...c.abilities.map((a) =>
      el("div", { class: "stat" }, el("span", { class: "muted small", text: a.name }), el("b", { text: a.score }), a.mod,
        c.ability_points ? btn("+1", () => act({ do: "raise", ability: a.id }), "btn") : null))),
    el("h3", { text: "Powers" }),
    el("div", { class: "list" }, ...c.powers.map((p) =>
      el("div", { class: "item", title: p.text },
        el("span", { class: "grow" }, el("b", { text: p.name }), el("span", { class: "muted small", text: p.max ? ` ${p.uses}/${p.max} per ${p.per} rest` : p.kind === "passive" ? " always on" : "" })),
        p.field && !v.combat ? btn("Use", () => act({ do: "ability", id: p.id }), "btn", { disabled: p.max && !p.uses }) : null))),
    el("h3", { text: "Skills" }),
    ...c.skills.map((s) => el("div", { class: "skill-row" + (s.proficient ? " prof" : "") },
      el("span", { text: s.name + (s.expert ? " (expert)" : "") }), el("b", { text: s.bonus }))));
}

function drawParty(v) {
  const here = new Set(v.here.people.map((p) => p.id));
  const gifts = v.bag.filter((i) => i.giftable);
  pane("tab-party",
    v.companions.length ? null : el("p", { class: "muted", text: "You have not met any companions yet. Talk to people; some of them may join you." }),
    ...v.companions.map((c) => {
      const pct = (c.affection + 100) / 2;
      const giftSel = el("select", {}, el("option", { value: "" }, "Give a gift…"), ...gifts.map((g) => el("option", { value: g.id }, g.name)));
      giftSel.onchange = () => { if (giftSel.value) act({ do: "give", to: c.id, item: giftSel.value }); };
      return el("div", { class: "item", style: "display:block" },
        el("div", { class: "row" }, el("b", { text: c.name }), el("span", { class: "muted small", text: `${c.pronouns} · ${c.class}` })),
        el("p", { class: "small", text: c.description }),
        el("div", {}, `${c.stage}${c.romance ? " · " + c.romance : ""}${c.partner ? " · your partner" : ""}${c.heartbroken ? " · heartbroken" : ""} (${c.affection})`,
          el("div", { class: "bar love" }, el("i", { style: `width:${pct}%` }))),
        el("p", { class: "muted small", text: c.in_party ? `With you · ${c.hp}/${c.max_hp} HP` : c.where ? `At ${c.where}` : "" }),
        el("div", { class: "row" },
          here.has(c.id) ? btn("Talk", () => act({ do: "talk", to: c.id })) : null,
          c.in_party ? btn("Part ways here", () => act({ do: "dismiss", to: c.id })) : here.has(c.id) ? btn("Ask to join", () => act({ do: "recruit", to: c.id })) : null,
          here.has(c.id) && gifts.length ? giftSel : null));
    }));
}

function drawQuests(v) {
  const act_ = v.journal.filter((q) => q.status === "active");
  const done = v.journal.filter((q) => q.status !== "active");
  const card = (q) => el("div", { class: `quest ${q.kind} ${q.status}` },
    el("b", { text: q.name }), el("span", { class: "muted small", text: ` ${q.kind}${q.status !== "active" ? ", " + q.status : ""}` }),
    q.objective ? el("div", { text: "→ " + q.objective }) : null,
    el("div", { class: "muted small", text: q.text || q.summary }),
    q.generated && q.status === "active" ? btn("Drop this job", () => act({ do: "abandon", id: q.id }), "btn opt small") : null);
  pane("tab-quests", el("h3", { text: "Active" }), act_.length ? act_.map(card) : el("p", { class: "muted", text: "Nothing on." }),
    done.length ? [el("h3", { text: "Finished" }), done.map(card)] : null);
}

function drawBag(v) {
  const selling = v.here.shop && v.here.shop.buys;
  const people = v.here.people;
  pane("tab-bag", el("p", { text: `${v.gold} ${v.labels.gold || "gold"}` }),
    ...v.bag.map((i) => {
      const give = people.length && i.giftable ? el("select", {}, el("option", { value: "" }, "Give to…"), ...people.map((p) => el("option", { value: p.id }, p.name))) : null;
      if (give) give.onchange = () => { if (give.value) act({ do: "give", to: give.value, item: i.id }); };
      return el("div", { class: "item", title: i.text },
        el("span", { class: "grow" }, el("b", { text: i.name }), i.count > 1 ? ` x${i.count}` : "", i.equipped ? el("span", { class: "muted", text: " (equipped)" }) : null,
          el("div", { class: "muted small", text: i.text })),
        i.equippable ? btn(i.equipped ? "Unequip" : "Equip", () => act({ do: "equip", item: i.id })) : null,
        i.usable ? btn("Use", () => act({ do: v.combat ? "item" : "use", item: i.id }), "btn", v.combat && i.kind === "consumable" ? { "data-combat": "1" } : {}) : null,
        selling && !i.equipped ? btn(`Sell ${i.value}`, () => act({ do: "sell", item: i.id })) : null,
        give);
    }));
}

for (const t of document.querySelectorAll(".tab")) {
  t.onclick = () => {
    for (const o of document.querySelectorAll(".tab")) o.classList.toggle("on", o === t);
    for (const p of document.querySelectorAll(".tabpane")) p.hidden = p.id !== "tab-" + t.dataset.tab;
  };
}

document.addEventListener("keydown", (e) => {
  if (!S.view || $("play").hidden || e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  const n = parseInt(e.key, 10);
  if (S.view.scene && n >= 1 && n <= S.view.scene.choices.length) act({ do: "choose", index: S.view.scene.choices[n - 1].index });
});

// ?save=<id> resumes a save, ?new=<campaign> opens character creation
const params = new URLSearchParams(location.search);
const want = params.get("save"), fresh = params.get("new");
(want ? open(want) : fresh ? create(fresh) : home()).catch((e) => { toast(e.message); home(); });
