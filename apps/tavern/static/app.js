"use strict";
// Tavern's page: campaigns, the story with Jan as game master, party, map, dice.
// Every piece of text from the player or Jan is shown with textContent.

const $ = (id) => document.getElementById(id);
let S = null; // /api/state
let C = null; // the open campaign
let busy = false; // the buttons are off: a request is out, or the server is writing
let inFlight = false; // this page is waiting on a game master request
let pollTimer = 0;
let pendingShow = null; // a campaign that arrived mid-drag, shown on pointer-up
let tool = "move"; // "move" or a terrain key
let picked = ""; // selected token id
let whoNow = "";

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
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
  if (!r.ok) {
    const err = new Error(data.detail || `${r.status} ${r.statusText}`);
    err.status = r.status;
    throw err;
  }
  return data;
}

let toastTimer = 0;
function toast(text, kind = "err") {
  const t = $("toast");
  t.textContent = text;
  t.className = "toast " + kind;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 6000);
}

// --- campaigns ---------------------------------------------------------------

async function loadState() {
  S = await api("GET", "/api/state");
  renderCampaigns();
}

function renderCampaigns() {
  const box = $("campaigns");
  box.textContent = "";
  if (!S.campaigns.length) box.append(el("p", "muted small", "None yet."));
  for (const c of S.campaigns) {
    const b = el("button", C && C.id === c.id ? "on" : "");
    b.type = "button";
    b.append(el("span", "", c.name));
    const world = S.worlds[c.world] ? S.worlds[c.world].label : c.world;
    b.append(el("span", "m", `${world} · ${c.party.join(", ")}`));
    b.addEventListener("click", () => open(c.id));
    box.append(b);
  }
}

async function open(id) {
  try {
    show(await api("GET", `/api/campaigns/${id}`));
    localStorage.setItem("tavern-open", id);
  } catch (err) {
    toast(err.message);
  }
}

function show(c) {
  if (drag || painting) {
    pendingShow = c;
    return;
  }
  C = c;
  const world = S.worlds[c.world];
  $("title").textContent = `${c.name} · ${world ? world.label : c.world}`;
  $("empty").hidden = true;
  $("log").hidden = $("act").hidden = $("panel").hidden = false;
  $("export").hidden = $("trash").hidden = false;
  $("export").href = `/api/campaigns/${c.id}/export`;
  $("trash").textContent = "Move to trash";
  $("trash").dataset.sure = "";
  $("roles").textContent = "";
  for (const r of world ? world.roles : []) $("roles").append(new Option(r, r));
  if (!$("summary").hidden) $("summary-text").textContent = c.summary || "";
  renderCampaigns();
  renderLog();
  renderWho();
  renderParty();
  renderMaps();
  renderRolls();
  setBusy(inFlight || !!c.busy);
  clearTimeout(pollTimer);
  // opened while the server is still writing (say, after a reload): look again
  if (c.busy && !inFlight) pollTimer = setTimeout(() => C && C.id === c.id && !inFlight && open(c.id), 2000);
}

function closeCampaign() {
  C = null;
  $("title").textContent = "Tabletop campaigns with Jan as the game master";
  $("empty").hidden = false;
  for (const id of ["log", "act", "panel", "export", "trash", "summary"]) $(id).hidden = true;
  localStorage.removeItem("tavern-open");
}

// --- the story ---------------------------------------------------------------

function renderLog() {
  const log = $("log");
  const atEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  log.textContent = "";
  if (!C.log.length) {
    log.append(el("p", "muted", "The table is set. Press “GM, go on” and Jan opens the campaign, or write what the party does first."));
  }
  for (const e of C.log) log.append(entry(e));
  if (busy) log.append(el("p", "writing", "The game master is writing…"));
  if (atEnd || busy) log.scrollTop = log.scrollHeight;
  const lastGm = C.log.length && C.log[C.log.length - 1].kind === "gm";
  $("again").disabled = busy || !lastGm;
}

function entry(e) {
  const d = el("div", "entry " + e.kind);
  d.dataset.n = e.n;
  if (e.kind === "gm") {
    d.append(document.createTextNode(e.text));
    for (const h of e.hp || []) {
      if (!h.delta) continue;
      const sign = h.delta > 0 ? "+" : "−";
      d.append(el("span", "hp" + (h.delta > 0 ? " heal" : ""), `${h.who} ${sign}${Math.abs(h.delta)} HP`));
    }
    const asks = (e.asks || []).map((a, i) => {
      const label = `🎲 ${a.expr}` + (a.who ? ` for ${a.who}` : "") + (a.why ? ` (${a.why})` : "");
      const b = el("button", "btn", a.done ? label + " · rolled" : label);
      b.type = "button";
      b.disabled = !!a.done;
      b.dataset.ask = `${e.n}.${i}`;
      b.addEventListener("click", async () => {
        b.disabled = true; // one roll per ask
        if (!(await rollDice(a.expr, a.who, a.why, `${e.n}.${i}`))) b.disabled = false;
      });
      return b;
    });
    if (asks.length) {
      const row = el("div", "asks");
      row.append(...asks);
      d.append(row);
    }
  } else if (e.kind === "roll") {
    d.append(el("b", "", e.who || "Someone"), ` rolls ${e.roll.expr}` + (e.text ? ` for ${e.text}` : "") + ": ");
    d.append(el("span", "", e.roll.text.replace(/ = -?\d+$/, "")), el("span", "total", String(e.roll.total)));
  } else if (e.kind === "note") {
    d.textContent = `(${e.who || "Note"}: ${e.text})`;
  } else {
    d.append(el("b", "", (e.who || "The party") + ": "), document.createTextNode(e.text));
  }
  return d;
}

function renderWho() {
  const sel = $("who");
  const keep = sel.value || whoNow;
  sel.textContent = "";
  sel.append(new Option("The party", ""));
  for (const m of C.party) sel.append(new Option(m.name, m.name));
  sel.value = C.party.some((m) => m.name === keep) ? keep : C.party[0] ? C.party[0].name : "";
}

function setBusy(on) {
  busy = on;
  for (const id of ["send", "note", "go-on", "recap"]) $(id).disabled = on;
  $("status").textContent = on ? "Jan is writing…" : "";
  if (C) $("again").disabled = on || !(C.log.length && C.log[C.log.length - 1].kind === "gm");
}

// true when Jan answered, else the HTTP status of the refusal (0: none sent)
async function gm(path, body) {
  if (busy || !C) return 0;
  const id = C.id;
  inFlight = true;
  setBusy(true);
  renderLog();
  try {
    const c = await api("POST", `/api/campaigns/${id}/${path}`, body);
    inFlight = false;
    if (C && C.id === id) show(c);
    return true;
  } catch (err) {
    toast(err.message);
    inFlight = false;
    setBusy(false);
    if (C && C.id === id) await open(id);
    return err.status || 0;
  } finally {
    inFlight = false;
    if (busy && !(C && C.busy)) setBusy(false);
    loadState().catch(() => {});
  }
}

async function act(ev) {
  ev.preventDefault();
  const text = $("text").value.trim();
  if (!text) return;
  whoNow = $("who").value;
  $("text").value = "";
  const res = await gm("turn", { who: whoNow, text });
  // Jan down (503) keeps the action in the story; any other refusal saved
  // nothing, so the words go back in the box
  if (res !== true && res !== 503 && !$("text").value) $("text").value = text;
}

async function note() {
  const text = $("text").value.trim();
  if (!text || !C) return;
  try {
    show(await api("POST", `/api/campaigns/${C.id}/say`, { who: $("who").value, text, kind: "note" }));
    $("text").value = "";
  } catch (err) {
    toast(err.message);
  }
}

async function recap() {
  if ($("summary").hidden === false) {
    $("summary").hidden = true;
    return;
  }
  if ((await gm("recap")) !== true) return;
  $("summary-text").textContent =
    C.summary || "Nothing to sum up yet: Jan still reads the whole story each turn.";
  $("summary").hidden = false;
}

// --- dice --------------------------------------------------------------------

async function rollDice(expr, who, why = "", ask = "") {
  if (!C) return false;
  try {
    show(await api("POST", `/api/campaigns/${C.id}/roll`, { expr, who, why, ask }));
    return true;
  } catch (err) {
    toast(err.message);
    return false;
  }
}

function renderRolls() {
  const box = $("rolls");
  box.textContent = "";
  const rolls = C.log.filter((e) => e.kind === "roll").slice(-12).reverse();
  for (const e of rolls) {
    const d = el("div");
    d.append(el("b", "", String(e.roll.total)), ` ${e.who || "Someone"}: ${e.roll.text}`);
    box.append(d);
  }
}

// --- party -------------------------------------------------------------------

function renderParty() {
  const box = $("party");
  box.textContent = "";
  for (const m of C.party) {
    const card = el("div", "card");
    const head = el("div", "head");
    head.append(el("b", "", m.name), el("span", "role", m.role));
    card.append(head);
    const bar = el("div", "bar");
    const fill = el("i");
    const share = Math.max(0, m.hp) / m.max_hp;
    fill.style.width = `${Math.round(share * 100)}%`;
    if (m.hp <= 0) fill.className = "down";
    else if (share <= 0.34) fill.className = "low";
    bar.append(fill);
    card.append(bar);
    const row = el("div", "row");
    row.append(el("span", "num", `${m.hp} / ${m.max_hp} HP` + (m.hp <= 0 ? " · down" : "")));
    for (const [label, delta] of [["−5", -5], ["−1", -1], ["+1", 1], ["+5", 5]]) {
      const b = el("button", "btn", label);
      b.type = "button";
      b.title = `${delta > 0 ? "Heal" : "Hurt"} ${m.name} by ${Math.abs(delta)}`;
      b.addEventListener("click", () => hp(m.id, delta));
      row.append(b);
    }
    const edit = el("button", "btn", "Edit");
    edit.type = "button";
    edit.addEventListener("click", () => editMember(m));
    const drop = el("button", "btn btn-danger", "Remove");
    drop.type = "button";
    drop.addEventListener("click", () => removeMember(m, drop));
    row.append(edit, drop);
    card.append(row);
    if (m.notes) card.append(el("div", "notes", m.notes));
    box.append(card);
  }
}

async function hp(pid, delta) {
  try {
    show(await api("POST", `/api/campaigns/${C.id}/party/${pid}/hp`, { delta }));
  } catch (err) {
    toast(err.message);
  }
}

function editMember(m) {
  $("member-title").textContent = m ? `Edit ${m.name}` : "Add a character";
  $("m-id").value = m ? m.id : "";
  $("m-name").value = m ? m.name : "";
  $("m-role").value = m ? m.role : "";
  $("m-hp").value = m ? m.hp : "";
  $("m-max").value = m ? m.max_hp : "";
  $("m-notes").value = m ? m.notes : "";
  $("m-cancel").hidden = !m;
  if (m) $("m-name").focus();
}

async function saveMember(ev) {
  ev.preventDefault();
  const body = { name: $("m-name").value, role: $("m-role").value, notes: $("m-notes").value };
  if ($("m-id").value) body.id = $("m-id").value;
  if ($("m-max").value !== "") body.max_hp = Number($("m-max").value);
  if ($("m-hp").value !== "") body.hp = Number($("m-hp").value);
  try {
    show(await api("POST", `/api/campaigns/${C.id}/party`, body));
    editMember(null);
  } catch (err) {
    toast(err.message);
  }
}

async function removeMember(m, button) {
  if (!button.dataset.sure) {
    button.dataset.sure = "1";
    button.textContent = "Sure?";
    setTimeout(() => {
      button.dataset.sure = "";
      button.textContent = "Remove";
    }, 4000);
    return;
  }
  try {
    show(await api("DELETE", `/api/campaigns/${C.id}/party/${m.id}`));
  } catch (err) {
    toast(err.message);
  }
}

// --- map ---------------------------------------------------------------------

const MAP_W = 350;
let cell = 14;
let drag = null; // {token, moved}
let painting = false;
let paintedAny = false;

function currentMap() {
  return C && (C.maps.find((m) => m.id === C.map) || C.maps[0]);
}

function renderMaps() {
  const sel = $("map-pick");
  sel.textContent = "";
  for (const m of C.maps) sel.append(new Option(`${m.name} (${m.w}×${m.h})`, m.id));
  sel.value = C.map;
  const pal = $("palette");
  pal.textContent = "";
  const moveBtn = el("button", tool === "move" ? "on" : "", "✋ Move");
  moveBtn.type = "button";
  moveBtn.dataset.tool = "move";
  pal.append(moveBtn);
  for (const t of S.terrain) {
    const b = el("button", tool === t.key ? "on" : "");
    b.type = "button";
    b.dataset.tool = t.key;
    const sw = el("i");
    sw.style.background = t.color;
    b.append(sw, t.label);
    pal.append(b);
  }
  for (const b of pal.children) {
    b.addEventListener("click", () => {
      tool = b.dataset.tool;
      renderMaps();
    });
  }
  $("map").classList.toggle("move", tool === "move");
  $("map-help").textContent =
    tool === "move" ? "Drag a token to move it; click one to pick it." : "Click or drag to paint squares.";
  drawMap();
}

function drawMap() {
  const mp = currentMap();
  if (!mp) return;
  const canvas = $("map");
  const room = $("pane-map").clientWidth - 30;
  cell = Math.max(10, Math.floor((room > 100 ? room : MAP_W) / mp.w));
  canvas.width = mp.w * cell;
  canvas.height = mp.h * cell;
  const ctx = canvas.getContext("2d");
  const colors = Object.fromEntries(S.terrain.map((t) => [t.key, t.color]));
  for (let y = 0; y < mp.h; y++) {
    for (let x = 0; x < mp.w; x++) {
      ctx.fillStyle = colors[mp.cells[y][x]] || "#000";
      ctx.fillRect(x * cell, y * cell, cell, cell);
    }
  }
  ctx.strokeStyle = "rgba(255,255,255,0.07)";
  ctx.lineWidth = 1;
  for (let x = 0; x <= mp.w; x++) {
    ctx.beginPath();
    ctx.moveTo(x * cell + 0.5, 0);
    ctx.lineTo(x * cell + 0.5, mp.h * cell);
    ctx.stroke();
  }
  for (let y = 0; y <= mp.h; y++) {
    ctx.beginPath();
    ctx.moveTo(0, y * cell + 0.5);
    ctx.lineTo(mp.w * cell, y * cell + 0.5);
    ctx.stroke();
  }
  for (const t of mp.tokens) {
    const cx = t.x * cell + cell / 2;
    const cy = t.y * cell + cell / 2;
    ctx.beginPath();
    ctx.arc(cx, cy, cell * 0.42, 0, Math.PI * 2);
    ctx.fillStyle = t.color;
    ctx.fill();
    ctx.lineWidth = t.id === picked ? 3 : 1.5;
    ctx.strokeStyle = t.id === picked ? "#fff" : "rgba(0,0,0,0.6)";
    ctx.stroke();
    ctx.fillStyle = "#111";
    ctx.font = `bold ${Math.round(cell * 0.5)}px sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(t.name.charAt(0).toUpperCase(), cx, cy + 1);
  }
  $("t-remove").hidden = !mp.tokens.some((t) => t.id === picked);
}

function squareAt(ev) {
  const r = $("map").getBoundingClientRect();
  const mp = currentMap();
  const x = Math.floor(((ev.clientX - r.left) / r.width) * mp.w);
  const y = Math.floor(((ev.clientY - r.top) / r.height) * mp.h);
  if (x < 0 || y < 0 || x >= mp.w || y >= mp.h) return null;
  return { x, y };
}

function paint(sq) {
  const mp = currentMap();
  const row = mp.cells[sq.y];
  if (row[sq.x] === tool) return;
  mp.cells[sq.y] = row.slice(0, sq.x) + tool + row.slice(sq.x + 1);
  paintedAny = true;
  drawMap();
}

function mapDown(ev) {
  const sq = squareAt(ev);
  if (!sq) return;
  $("map").setPointerCapture(ev.pointerId);
  const mp = currentMap();
  if (tool === "move") {
    const token = [...mp.tokens].reverse().find((t) => t.x === sq.x && t.y === sq.y);
    picked = token ? token.id : "";
    drag = token ? { token, moved: false } : null;
    drawMap();
  } else {
    painting = true;
    paintedAny = false;
    paint(sq);
  }
}

function mapMove(ev) {
  const sq = squareAt(ev);
  if (!sq) return;
  if (drag && (drag.token.x !== sq.x || drag.token.y !== sq.y)) {
    drag.token.x = sq.x;
    drag.token.y = sq.y;
    drag.moved = true;
    drawMap();
  } else if (painting) {
    paint(sq);
  }
}

function mapUp() {
  const mid = currentMap().id;
  const moved = drag && drag.moved ? { id: drag.token.id, x: drag.token.x, y: drag.token.y } : null;
  const cells = painting && paintedAny ? currentMap().cells : null;
  drag = null;
  painting = false;
  // a reply that came in mid-gesture is shown now, with the gesture put on it
  if (pendingShow) {
    const c = pendingShow;
    pendingShow = null;
    show(c);
  }
  const mp = C.maps.find((m) => m.id === mid);
  if (!mp) return;
  if (moved) {
    const t = mp.tokens.find((t) => t.id === moved.id);
    if (t) {
      t.x = moved.x;
      t.y = moved.y;
      saveMap({ tokens: mp.tokens }, mid);
    }
  }
  if (cells) {
    mp.cells = cells;
    saveMap({ cells }, mid);
  }
}

async function saveMap(body, mid) {
  const id = mid || currentMap().id;
  try {
    show(await api("PUT", `/api/campaigns/${C.id}/maps/${id}`, body));
  } catch (err) {
    toast(err.message);
    open(C.id);
  }
}

async function addToken(ev) {
  ev.preventDefault();
  const name = $("t-name").value.trim();
  const mp = currentMap();
  if (!name || !mp) return;
  const taken = new Set(mp.tokens.map((t) => `${t.x},${t.y}`));
  let spot = { x: 0, y: 0 };
  outer: for (let y = 0; y < mp.h; y++) {
    for (let x = 0; x < mp.w; x++) {
      if (!taken.has(`${x},${y}`)) {
        spot = { x, y };
        break outer;
      }
    }
  }
  $("t-name").value = "";
  await saveMap({ tokens: [...mp.tokens, { name, color: $("t-color").value, ...spot }] });
}

async function removeToken() {
  const mp = currentMap();
  const tokens = mp.tokens.filter((t) => t.id !== picked);
  picked = "";
  await saveMap({ tokens });
}

async function newMap(ev) {
  ev.preventDefault();
  const name = $("map-name").value.trim() || `Map ${C.maps.length + 1}`;
  try {
    show(await api("POST", `/api/campaigns/${C.id}/maps`, { name, w: S.map.w, h: S.map.h }));
    $("map-name").value = "";
  } catch (err) {
    toast(err.message);
  }
}

// --- new campaign --------------------------------------------------------------

function partyRow(name = "", role = "") {
  const row = el("div", "pair");
  const n = el("input");
  n.placeholder = "Character name";
  n.maxLength = 60;
  n.value = name;
  n.className = "p-name";
  const r = el("input");
  r.placeholder = "Role";
  r.maxLength = 60;
  r.value = role;
  r.className = "p-role";
  r.setAttribute("list", "roles");
  const x = el("button", "btn", "×");
  x.type = "button";
  x.title = "Leave this one out";
  x.addEventListener("click", () => row.remove());
  row.append(n, r, x);
  return row;
}

function worldPicked() {
  const w = S.worlds[$("c-world").value];
  $("c-blurb").textContent = w ? w.blurb : "";
  $("roles").textContent = "";
  for (const r of w ? w.roles : []) $("roles").append(new Option(r, r));
}

function newCampaign() {
  const sel = $("c-world");
  sel.textContent = "";
  for (const [id, w] of Object.entries(S.worlds)) sel.append(new Option(w.label, id));
  worldPicked();
  $("c-name").value = "";
  $("c-party").textContent = "";
  $("c-party").append(partyRow(), partyRow());
  $("new-dialog").showModal();
  $("c-name").focus();
}

async function createCampaign(ev) {
  ev.preventDefault();
  const party = [...$("c-party").children]
    .map((row) => ({ name: row.querySelector(".p-name").value.trim(), role: row.querySelector(".p-role").value.trim() }))
    .filter((p) => p.name);
  try {
    const c = await api("POST", "/api/campaigns", { name: $("c-name").value, world: $("c-world").value, party });
    $("new-dialog").close();
    await loadState();
    show(c);
    localStorage.setItem("tavern-open", c.id);
  } catch (err) {
    toast(err.message);
  }
}

async function trashCampaign() {
  const b = $("trash");
  if (!b.dataset.sure) {
    b.dataset.sure = "1";
    b.textContent = "Sure? It goes to the trash";
    setTimeout(() => {
      b.dataset.sure = "";
      b.textContent = "Move to trash";
    }, 4000);
    return;
  }
  try {
    await api("DELETE", `/api/campaigns/${C.id}`);
    closeCampaign();
    await loadState();
    toast("Moved to the trash.", "ok");
  } catch (err) {
    toast(err.message);
  }
}

// --- wiring ------------------------------------------------------------------

function tab(name) {
  for (const t of document.querySelectorAll(".tab")) t.classList.toggle("on", t.dataset.tab === name);
  for (const p of ["party", "map", "dice"]) $("pane-" + p).hidden = p !== name;
  if (name === "map") drawMap();
}

function wire() {
  $("new").addEventListener("click", newCampaign);
  $("c-world").addEventListener("change", worldPicked);
  $("c-add").addEventListener("click", () => {
    if ($("c-party").children.length < S.party_max) $("c-party").append(partyRow());
  });
  $("c-cancel").addEventListener("click", () => $("new-dialog").close());
  $("new-form").addEventListener("submit", createCampaign);
  $("act").addEventListener("submit", act);
  $("text").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      if (!busy) $("act").requestSubmit();
    }
  });
  $("note").addEventListener("click", note);
  $("go-on").addEventListener("click", () => gm("turn", {}));
  $("again").addEventListener("click", () => gm("retry"));
  $("recap").addEventListener("click", recap);
  $("trash").addEventListener("click", trashCampaign);
  for (const t of document.querySelectorAll(".tab")) t.addEventListener("click", () => tab(t.dataset.tab));
  $("member-form").addEventListener("submit", saveMember);
  $("m-cancel").addEventListener("click", () => editMember(null));
  const canvas = $("map");
  canvas.addEventListener("pointerdown", mapDown);
  canvas.addEventListener("pointermove", mapMove);
  canvas.addEventListener("pointerup", mapUp);
  canvas.addEventListener("pointercancel", mapUp);
  $("map-pick").addEventListener("change", () => saveMap({}, $("map-pick").value));
  $("map-form").addEventListener("submit", newMap);
  $("token-form").addEventListener("submit", addToken);
  $("t-remove").addEventListener("click", removeToken);
  const dice = $("dice");
  for (const d of ["d4", "d6", "d8", "d10", "d12", "d20", "d100", "2d6"]) {
    const b = el("button", "btn", d);
    b.type = "button";
    b.addEventListener("click", () => rollDice(d.startsWith("d") ? "1" + d : d, $("who").value));
    dice.append(b);
  }
  $("roll-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const expr = $("expr").value.trim();
    if (expr) rollDice(expr, $("who").value);
  });
}

async function start() {
  wire();
  try {
    await loadState();
  } catch (err) {
    toast(err.message);
    return;
  }
  const last = localStorage.getItem("tavern-open");
  if (last && S.campaigns.some((c) => c.id === last)) await open(last);
  if (window.ForgeJan) {
    ForgeJan.panel($("jan-panel"), { labels: { gm: "Game master", recap: "Story so far (recaps)" } });
  }
}

start();
