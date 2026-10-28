/* Janhollow — the page.
 *
 * The station is simulated in the backend, so this file is a window rather than
 * a game loop: it polls /api/world/state, eases each crew member towards where
 * the server says they are, and draws. Nothing here decides where anyone goes.
 *
 * It also sends a heartbeat to /api/world/presence, which is how the away modes
 * work: the backend can tell "you are looking at it", "the tab is in the
 * background" and "the tab is gone" apart only because of that heartbeat.
 */
"use strict";

const S = {
  library: null,
  tiles: null,
  crewArt: null,
  tile: 32,
  lightKey: "",
  lightCanvas: null,
  bakeWin: null,            // the light bakes' window (JanView.bakeWindow)
  player: null,
  cameraX: 0,
  cameraY: 0,
  zoom: 1,
  held: { up: false, down: false, left: false, right: false },
  menuOpen: false,
  sentHold: "",
  talking: false,
  decks: [],
  deck: null,
  locations: {},
  rooms: {},          // deckId -> Map("x,y" -> location)
  solid: {},          // deckId -> Set("x,y") of tiles with furniture on them
  crew: [],
  byId: {},
  selected: "",
  showNames: true,
  stars: {},
  settings: {},
  options: {},
  log: [],
  logFilter: remembered("janhollow.logFilter", "all"),  // logview.js FILTERS id
  logWho: "",          // one crew member's lines only ("" is everyone)
  logKeys: null,       // the keys of the lines on screen; null means rebuild
  follow: true,
  peeking: false,      // aboard, but looking at another deck (view.js)
  zoomBeforeFind: 0,   // the zoom to go back to after finding a crew member
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

/* A view choice kept in this browser. Storage can be switched off, and then
   the choice simply lasts until the page closes. */
function remembered(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch (err) {
    return fallback;
  }
}
function remember(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (err) {
    /* not kept, which is fine */
  }
}

function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.remove("hidden");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => el.classList.add("hidden"), 2600);
}

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(url + " → " + res.status);
  return res.json();
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error(url + " → " + res.status);
  return res.json();
}

/* Runs one button's request at a time: the button is disabled until it
   answers, so a double click sends one request, and a backend that is down
   gets a calm toast instead of an unhandled error. */
async function once(button, work) {
  if (button.dataset.busy) return;
  button.dataset.busy = "1";
  button.disabled = true;
  try {
    await work();
  } catch (err) {
    toast("the station is not answering; try again in a moment");
  } finally {
    delete button.dataset.busy;
    button.disabled = false;
  }
}

S.roomAt = function (deckId, x, y) {
  const map = S.rooms[deckId];
  return map ? map.get(x + "," + y) : null;
};

/* --- loading -------------------------------------------------------------- */

async function boot() {
  const [library, station, options] = await Promise.all([
    ForgeArt.load("/api/art/library"),
    getJSON("/api/station"),
    getJSON("/api/options"),
  ]);
  /* Two atlases on purpose: the deck is baked against the janhollow palette so
     it can be re-skinned on its own, and the crew against the crewroom one they
     were drawn for. Sprites are asked for by qualified "pack/name" because the
     32px packs reuse the 16px names deliberately. */
  S.library = library;
  S.tiles = ForgeArt.atlas(library, "janhollow");
  S.crewArt = ForgeArt.atlas(library, "crewroom");
  S.tile = tileSize();
  S.decks = station.decks;
  S.locations = station.locations;
  S.options = options;
  S.deck = S.decks[0] ? S.decks[0].id : "";

  for (const deck of S.decks) {
    S.rooms[deck.id] = new Map();
    /* Furniture, as a set of tiles. The page needs the same collision the
       backend has, because it now walks you itself rather than waiting to be
       told where you ended up. */
    S.solid[deck.id] = new Set(
      deck.props.filter((p) => p.solid !== false).map((p) => p.x + "," + p.y)
    );
  }
  for (const id in S.locations) {
    const loc = S.locations[id];
    const map = S.rooms[loc.deck];
    if (!map) continue;
    const [x, y, w, h] = loc.rect;
    for (let ty = y; ty < y + h; ty++) {
      for (let tx = x; tx < x + w; tx++) map.set(tx + "," + ty, loc);
    }
  }

  $("#data-root").textContent = options.data_root;
  $("#barks-hint").textContent =
    "New written lines: one JSON file in " + options.data_root.replace(/\/$/, "") +
    "/barks/, shaped like the files in the app's own barks folder.";
  const problems = (station.problems || []).join("\n");
  $("#problems").textContent = problems;

  applyHash();
  /* render.js already draws its own ellipse under every character, so the
     module's actor shadow is turned down rather than stacked on top of it —
     its author measured the two doubling up. */
  if (window.Atmosphere) Atmosphere.init(atmosphereSettings());

  drawDeckButtons();
  drawSettings();
  drawLogFilters();
  ForgeJan.panel($("#jan-settings")).catch(() => {});
  await refresh();
  // 200 ms while the world is on screen and focused; every 5 s when the
  // window is hidden or another Forge app is in front (the 4 s heartbeat
  // still reports presence). Five requests a second from a page nobody is
  // looking at was the backend's busiest caller.
  // Coming back into view polls at once, so the slow hidden beat never
  // shows a stale world. One chain: a call clears the pending timer first.
  // While the backend is down the beat stretches (1 s, 2 s, 4 s, 8 s, then
  // every 10 s on screen, 30 s out of sight) instead of asking five times a
  // second, and the first answer puts it back.
  let inFlight = false, pollT = 0, fails = 0;
  const poll = async () => {
    clearTimeout(pollT); pollT = 0;
    if (inFlight) return;
    inFlight = true;
    let ok = false;
    try { ok = await refresh(); } finally { inFlight = false; }
    if (ok && fails) {
      fails = 0;
      heartbeat.now();
    }
    if (!ok) fails += 1;
    const shown = !document.hidden && (!window.ForgeVisible || ForgeVisible.on);
    const beat = shown ? 200 : 5000;
    const cap = shown ? 10000 : 30000;
    pollT = setTimeout(poll, fails ? Math.max(beat, Math.min(cap, 500 * 2 ** fails)) : beat);
  };
  const onShow = () => {
    const shown = ForgeIdle.shown();
    if (window.Station && Station.rest) Station.rest(!shown);
    if (shown) {
      poll();
      return;
    }
    /* Out of sight nobody is pressing keys: let go of any held direction
       (a hidden window gets no keyup), and rest the sound. */
    if (S.held.up || S.held.down || S.held.left || S.held.right) {
      S.held = { up: false, down: false, left: false, right: false };
      pushHold();
    }
  };
  document.addEventListener("visibilitychange", onShow);
  document.addEventListener("forge-visible", onShow);
  pollT = setTimeout(poll, 200);
  ForgeIdle.poll(drawVoices, 3000, { backoff: 2, maxMs: 30000 });
  drawVoices();
  heartbeat.start();
  /* Drawn only while the page can be seen: behind another Forge app or in a
     hidden window the deck is not redrawn sixty times a second for nobody. */
  ForgeIdle.loop(frame);
}

/* The atmosphere's look, gentler when the system asks for reduced motion:
   lamps hold steady instead of flickering, light shafts stop breathing and
   the dust drifts slowly. Followed live if the setting changes; switching back
   restores the tuned values atmosphere.js shipped with. */
const reducedMotion = window.matchMedia
  ? window.matchMedia("(prefers-reduced-motion: reduce)")
  : null;
const STILLER = { flicker: 0, shaftBreath: 0, dustDrift: 2, dustRise: 1.5 };
let tunedMotion = null;
function atmosphereSettings() {
  if (!tunedMotion) {
    tunedMotion = {};
    for (const key in STILLER) tunedMotion[key] = Atmosphere.settings[key];
  }
  const still = !!(reducedMotion && reducedMotion.matches);
  return Object.assign({ actorShadow: 0.3 }, still ? STILLER : tunedMotion);
}
if (reducedMotion && reducedMotion.addEventListener) {
  reducedMotion.addEventListener("change", () => {
    if (window.Atmosphere) Atmosphere.init(atmosphereSettings());
  });
}

function drawDeckButtons() {
  const host = $("#decks");
  host.innerHTML = "";
  for (const deck of S.decks) {
    const button = document.createElement("button");
    button.className = "btn deck-btn" + (deck.id === S.deck ? " on" : "");
    button.textContent = deck.label;
    button.title = deck.tagline || "";
    button.onclick = () => lookAt(deck.id);
    host.appendChild(button);
  }
}

/* --- which deck is showing (rules in view.js) ------------------------------ */

const aboardNow = () => !!(S.player && S.player.aboard);
const myDeck = () => (S.player && S.player.deck) || "";

function showDeck(view) {
  const moved = view.deck !== S.deck;
  S.deck = view.deck;
  S.peeking = view.peeking;
  if (moved) {
    S.lightKey = "";
    drawDeckButtons();
  }
  drawPeek();
}

/* After every poll: a followed crew member, else you, else what was showing.
   Aboard, the view no longer snaps back to your deck while you are looking
   somewhere else. */
function applyView() {
  const followed = S.follow && S.selected && S.byId[S.selected];
  showDeck(JanView.afterSnapshot({
    current: S.deck,
    aboard: aboardNow(),
    playerDeck: myDeck(),
    peeking: S.peeking,
    followDeck: followed ? followed.deck : "",
  }));
}

/* A deck button or Tab: look at that deck, aboard or not. */
function lookAt(deckId) {
  S.follow = false;
  S.pickedDeck = true;
  unzoomFind();
  showDeck(JanView.pick({ target: deckId, aboard: aboardNow(), playerDeck: myDeck() }));
  if (S.peeking) {
    const deck = S.decks.find((d) => d.id === S.deck);
    if (deck) {
      S.cameraX = deck.width / 2;
      S.cameraY = deck.height / 2;
    }
  }
}

/* Walking or the Back to me button. */
function backToMe() {
  S.follow = false;
  unzoomFind();
  showDeck(JanView.backToMe({ current: S.deck, aboard: aboardNow(), playerDeck: myDeck() }));
}

function drawPeek() {
  const button = $("#back-to-me");
  if (!button) return;
  const show = JanView.showBack({
    aboard: aboardNow(),
    peeking: S.peeking,
    finding: !!(S.follow && S.selected),
  });
  button.hidden = !show;
  if (show) {
    const mine = S.decks.find((d) => d.id === myDeck());
    button.title = "You are on " + (mine ? mine.label : "another deck") + "; walking takes you back too";
  }
}

/* Finding a crew member zooms in on them; letting go puts the zoom back. */
function zoomToFind() {
  if (S.zoom >= 1.6) return;
  S.zoomBeforeFind = S.zoom;
  setZoom(1.6);
}

function unzoomFind() {
  if (!S.zoomBeforeFind) return;
  const back = S.zoomBeforeFind;
  S.zoomBeforeFind = 0;
  setZoom(back);
}

/* A deck and a pane can be named in the URL -- #deck=habitat&pane=settings --
   which is how a Forge link, or a screenshot run, opens the station on the part
   it means rather than on whatever was showing last. */
function applyHash() {
  const hash = new URLSearchParams((location.hash || "").replace(/^#/, ""));
  const deck = hash.get("deck");
  if (deck && S.decks.some((d) => d.id === deck)) {
    S.deck = deck;
    S.pickedDeck = true;
  }
  const pane = hash.get("pane");
  if (pane) {
    const tab = document.querySelector(`.tab[data-pane="${pane}"]`);
    if (tab) tab.click();
  }
}

/* --- state ---------------------------------------------------------------- */

function applySnapshot(snap) {
  S.settings = snap.settings;
  S.items = snap.items || [];
  if (snap.player) {
    const was = S.player;
    if (!was) {
      S.player = Object.assign({}, snap.player, {
        drawX: snap.player.x, drawY: snap.player.y, drawDeck: snap.player.deck,
      });
    } else {
      const drawX = was.drawX, drawY = was.drawY, drawDeck = was.drawDeck;
      S.player = Object.assign(was, snap.player, { drawX, drawY, drawDeck });
      reconcilePlayer(snap.player);
    }
    drawPlayerBar();
    drawActions();
  }
  /* Redraw the settings panel only when the server's values actually change.
     Drawing it on every poll would fight with a slider being dragged, and not
     drawing it at all left the panel showing nothing selected until something
     was clicked. */
  const stamp = JSON.stringify(snap.settings);
  if (S.settingsStamp !== stamp) {
    S.settingsStamp = stamp;
    if (S.options.away_modes) drawSettings();
    drawVoicesButton();
  }
  setText($("#clock"), snap.clock);
  S.minuteOfDay = snap.minute;
  setText($("#day"), "day " + snap.day);
  const mode = (S.options.away_modes || {})[snap.settings.away_mode];
  const away = snap.presence === "focused" ? "" : (mode ? mode.label.toLowerCase() : snap.presence);
  const state = $("#state");
  setText(state, away);
  if (state.title !== away) state.title = away;

  for (const member of snap.crew) {
    const known = S.byId[member.id];
    if (known) {
      Object.assign(known, member);
      /* A crew member who has taken the lift is somewhere else entirely; easing
         towards the new spot would send them gliding through walls. */
      if (known.drawDeck !== member.deck) {
        known.drawX = member.x;
        known.drawY = member.y;
        known.drawDeck = member.deck;
      }
    } else {
      const fresh = Object.assign({}, member, {
        drawX: member.x,
        drawY: member.y,
        drawDeck: member.deck,
      });
      S.byId[member.id] = fresh;
      S.crew.push(fresh);
    }
  }
  S.crew.sort((a, b) => a.label.localeCompare(b.label));

  /* Open on the deck with the most people on it. Watching a station is the
     point, and the first thing shown should have someone in it -- at 07:00
     nobody at all is on the command deck. */
  if (!S.pickedDeck && S.crew.length) {
    const heads = {};
    for (const member of S.crew) heads[member.deck] = (heads[member.deck] || 0) + 1;
    const busiest = Object.keys(heads).sort((a, b) => heads[b] - heads[a])[0];
    if (busiest) {
      S.deck = busiest;
      S.pickedDeck = true;
      drawDeckButtons();
    }
  }

  if (snap.log_length !== S.log.length || snap.log.length) {
    S.log = snap.log;
    drawLog();
  }
  applyView();
  drawCrewList();
}

/* True when the world answered, so the poll can tell a quiet backend from a
   gone one. */
async function refresh() {
  try {
    applySnapshot(await getJSON("/api/world/state"));
    $("#state").classList.remove("down");
    return true;
  } catch (err) {
    $("#state").textContent = "station not answering, trying again";
    $("#state").classList.add("down");
    return false;
  }
}

async function heartbeat() {
  try {
    const snap = await postJSON("/api/world/presence", {
      focused: document.hasFocus() && !document.hidden,
    });
    if (snap.caught_up) {
      toast(`${Math.round(snap.caught_up.minutes / 60)} hours passed while you were away`);
    }
    applySnapshot(snap);
    return true;
  } catch (err) {
    /* The heartbeat failing is not worth a message: the poll above says it. */
    return false;
  }
}

/* Every 4 s, hidden or not (the backend reads a missing heartbeat as the tab
   being closed, which is what the away modes are about). It stretches to 30 s
   while the backend is down, and the world poll calls now() the moment the
   backend answers again. */
heartbeat.timer = 0;
heartbeat.fails = 0;
heartbeat.busy = false;
heartbeat.now = async function () {
  clearTimeout(heartbeat.timer);
  if (heartbeat.busy) return;
  heartbeat.busy = true;
  let ok = false;
  try { ok = await heartbeat(); } finally { heartbeat.busy = false; }
  heartbeat.fails = ok ? 0 : heartbeat.fails + 1;
  const wait = heartbeat.fails ? Math.min(30000, 4000 * 2 ** heartbeat.fails) : 4000;
  clearTimeout(heartbeat.timer);
  heartbeat.timer = setTimeout(heartbeat.now, wait);
};
heartbeat.start = () => heartbeat.now();

/* --- panels --------------------------------------------------------------- */

/* The world poll runs five times a second and most answers change nothing a
   panel shows. Each panel keeps a stamp of what it last drew in its
   data-stamp and skips the rebuild when the stamp is the same, so the poll no
   longer throws away and rebuilds DOM next to the 60 fps canvas (Relay task
   174). A tab click clears the stamps so a pane always draws when opened. */
function setText(el, text) {
  if (el && el.textContent !== text) el.textContent = text;
}

function sameStamp(host, stamp) {
  if (host.dataset.stamp === stamp && host.firstChild) return true;
  host.dataset.stamp = stamp;
  return false;
}

function drawCrewList() {
  const host = $("#pane-crew");
  if (!host.classList.contains("on")) return;
  const stamp = JSON.stringify([S.selected, S.crew.map((m) => {
    const where = S.locations[m.location];
    return [m.id, m.label, m.job, m.activity, !!m.moving, where ? where.label : ""];
  })]);
  if (sameStamp(host, stamp)) return;
  host.innerHTML = "";
  for (const member of S.crew) {
    const row = document.createElement("div");
    row.className = "crew-row" + (S.selected === member.id ? " on" : "");
    const where = S.locations[member.location];
    row.innerHTML =
      `<span class="crew-dot${member.moving ? "" : " still"}"></span>` +
      `<span><span class="crew-name"></span><br><span class="crew-sub"></span></span>`;
    row.querySelector(".crew-name").textContent = member.label;
    row.querySelector(".crew-sub").textContent =
      `${member.job} — ${member.activity || "about"}` +
      (where ? ` · ${where.label}` : "");
    /* Clicking a name finds them: their deck, zoomed in and centred on
       them, followed as they walk. Aboard, that is a look elsewhere unless
       they are on your deck; walking or Back to me ends it. */
    row.onclick = () => {
      /* A second click lets go; a click after walking ended the follow finds
         them again rather than quietly deselecting. */
      S.selected = S.selected === member.id && S.follow ? "" : member.id;
      S.follow = true;
      if (S.selected) {
        S.pickedDeck = true;
        const mineHere = aboardNow() && member.deck === myDeck();
        if (!mineHere) zoomToFind();
        S.cameraX = member.drawX;
        S.cameraY = member.drawY;
        applyView();
        const deck = S.decks.find((d) => d.id === member.deck);
        toast(mineHere ? `${member.label} is on your deck` : `${member.label}, ${deck ? deck.label : "somewhere"}`);
      } else {
        unzoomFind();
        drawPeek();
      }
      if (S.logWho && S.logWho !== S.selected) {
        S.logWho = S.selected;
        S.logKeys = null;
      }
      drawCrewList();
      drawLogFilters();
      drawLog();
    };
    host.appendChild(row);
  }
}

/* The Log pane. New lines are added at the end and lines that fell off the
   front of the capped log are taken away, instead of rebuilding the pane, so a
   reader who scrolled up stays on the line they were reading; at the bottom it
   follows the newest line as before. */
function logLine(line) {
  const el = document.createElement("div");
  el.className = "log-line log-" + (line.kind || "note");
  el.innerHTML = `<span class="log-at"></span><span class="log-text"></span>`;
  el.querySelector(".log-at").textContent = `d${line.day} ${line.at}`;
  el.querySelector(".log-text").textContent = line.text;
  return el;
}

/* The note in a log pane that the filter leaves empty. Its words change only
   when they have to (the first line of a fresh world arriving under another
   filter), so a poll that finds the pane still empty touches nothing. */
function logEmptyNote(host) {
  const text = S.log.length
    ? "Nothing of this kind in the log yet."
    : "The log fills in as the crew go about their day.";
  let note = host.querySelector(".log-empty");
  if (!note) {
    note = document.createElement("div");
    note.className = "log-empty";
    host.appendChild(note);
  }
  if (note.textContent !== text) note.textContent = text;
}

function drawLog() {
  const pane = $("#pane-log");
  const host = $("#log-lines");
  if (!host || !pane.classList.contains("on")) return;
  const lines = JanLog.pick(S.log, JanLog.find(S.logFilter), S.logWho);
  const keys = lines.map(JanLog.key);
  const change = S.logKeys ? JanLog.diff(S.logKeys, keys) : null;
  if (change && !change.drop && !change.add) {
    if (!lines.length) logEmptyNote(host);
    return;
  }
  const stuck = pane.scrollTop + pane.clientHeight >= pane.scrollHeight - 20;
  if (!change) {
    host.replaceChildren(...lines.map(logLine));
    if (!lines.length) logEmptyNote(host);
    pane.scrollTop = pane.scrollHeight;
  } else {
    /* Keep the first line that stays exactly where it was on screen while
       the ones above it go. */
    const anchor = host.children[change.drop];
    const before = anchor ? anchor.getBoundingClientRect().top : 0;
    for (let i = 0; i < change.drop; i++) host.firstChild.remove();
    for (const line of lines.slice(lines.length - change.add)) host.appendChild(logLine(line));
    if (stuck) pane.scrollTop = pane.scrollHeight;
    else if (anchor) pane.scrollTop += anchor.getBoundingClientRect().top - before;
  }
  S.logKeys = keys;
}

/* The filter chips over the log, from JanLog.FILTERS, plus "Only <name>" while
   a crew member is picked in the Crew list. */
function drawLogFilters() {
  const host = $("#log-filters");
  if (!host) return;
  const picked = S.selected && S.byId[S.selected];
  if (!picked) S.logWho = "";
  const stamp = JSON.stringify([S.logFilter, S.logWho, picked ? picked.label : ""]);
  if (host.dataset.stamp === stamp) return;
  host.dataset.stamp = stamp;
  host.replaceChildren();
  const chip = (label, title, on, onclick) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.title = title;
    button.className = on ? "on" : "";
    button.setAttribute("aria-pressed", on ? "true" : "false");
    button.onclick = onclick;
    host.appendChild(button);
  };
  for (const filter of JanLog.FILTERS) {
    chip(filter.label, filter.title, S.logFilter === filter.id, () => {
      S.logFilter = filter.id;
      remember("janhollow.logFilter", filter.id);
      S.logKeys = null;
      drawLogFilters();
      drawLog();
    });
  }
  if (picked) {
    const first = picked.label.split(" ")[0];
    chip(
      "Only " + first,
      `Just what ${picked.label} did and said. Picking someone else in the Crew list moves this to them.`,
      S.logWho === picked.id,
      () => {
        S.logWho = S.logWho === picked.id ? "" : picked.id;
        S.logKeys = null;
        drawLogFilters();
        drawLog();
      }
    );
  }
}

/* What the models are doing. Polled only while the Settings pane is open, so a
   station being watched is not also being asked about its own plumbing three
   times a second. */
async function drawVoices() {
  const host = $("#voices");
  if (!host || !$("#pane-settings").classList.contains("on")) return;
  let data;
  try {
    data = await getJSON("/api/world/voices");
  } catch (err) {
    host.textContent = "the station is not answering; this fills in again when it does";
    return false;
  }
  const m = data.models || {};
  const d = data.director || {};
  const rows = [
    ["Jan", data.jan_online ? "running" : "not running"],
    ["Allowed right now", data.allowed_now ? "yes" : "no — " + (d.doing || "away mode")],
    ["Lines said", m.lines || 0],
    ["Conversations", m.conversations || 0],
    ["Written lines said", (m.written || 0) + " (from " + (d.written_sets || 0) + " sets, no model)"],
    ["Rejected by the guard", m.rejected || 0],
    ["Narrator runs", m.narrator_runs || 0],
  ];
  if (d.seconds_to_next > 0) rows.push(["Next conversation", Math.round(d.seconds_to_next) + "s"]);
  if (m.last_problem) rows.push(["Last rejection", m.last_problem]);
  if (m.last_error) rows.push(["Last error", m.last_error]);
  host.innerHTML = "";
  for (const [key, value] of rows) {
    const row = document.createElement("div");
    row.className = "crew-sub";
    row.innerHTML = "<b></b> <span></span>";
    row.querySelector("b").textContent = key + ":";
    row.querySelector("span").textContent = value;
    host.appendChild(row);
  }
  const roles = (S.options && S.options.roles) || {};
  for (const role in roles) {
    const row = document.createElement("div");
    row.className = "crew-sub";
    row.style.marginTop = "6px";
    row.innerHTML = "<b></b><br><span></span>";
    row.querySelector("b").textContent =
      roles[role].label + " — " + ((data.roles || {})[role] || "none");
    row.querySelector("span").textContent = roles[role].why;
    host.appendChild(row);
  }
}

function drawSettings() {
  const range = $("#day-range");
  const number = $("#day-number");
  const set = (value) => {
    range.value = Math.min(180, value);
    number.value = value;
  };
  set(S.settings.day_minutes || S.options.defaults.day_minutes);
  const push = (value) => {
    set(value);
    postJSON("/api/world/settings", { values: { day_minutes: Number(value) } }).then(
      (out) => (S.settings = out.settings),
      () => {
        set(S.settings.day_minutes || S.options.defaults.day_minutes);
        toast("the station is not answering; the day length was not changed");
      }
    );
  };
  range.oninput = () => set(range.value);
  range.onchange = () => push(range.value);
  number.onchange = () => push(number.value);

  const modes = $("#away-modes");
  modes.innerHTML = "";
  for (const key in S.options.away_modes) {
    const mode = S.options.away_modes[key];
    const el = document.createElement("div");
    el.className = "mode" + (S.settings.away_mode === key ? " on" : "");
    el.innerHTML = "<b></b><small></small>";
    el.querySelector("b").textContent = mode.label;
    el.querySelector("small").textContent = mode.detail;
    el.onclick = () =>
      once(el, async () => {
        const out = await postJSON("/api/world/settings", { values: { away_mode: key } });
        S.settings = out.settings;
        drawSettings();
        toast(mode.label);
      });
    modes.appendChild(el);
  }

  levelRow("#chatter", "chatter", (level) => `about ${level.per_minute} conversations a minute (from session 2)`);
  levelRow("#barks", "barks", (level) =>
    level.per_minute
      ? `about ${level.per_minute} written exchanges a minute; never uses Jan`
      : "no written lines"
  );
}

/* A row of level buttons for one setting, from the levels in /api/options. */
function levelRow(selector, setting, title) {
  const row = $(selector);
  if (!row) return;
  row.innerHTML = "";
  const levels = S.options[setting] || {};
  for (const key in levels) {
    const level = levels[key];
    const button = document.createElement("button");
    button.className = "btn" + (S.settings[setting] === key ? " btn-primary" : "");
    button.textContent = level.label;
    button.title = title(level);
    button.onclick = () =>
      once(button, async () => {
        const out = await postJSON("/api/world/settings", { values: { [setting]: key } });
        S.settings = out.settings;
        drawSettings();
      });
    row.appendChild(button);
  }
}

/* One press to start or stop the crew talking. The level lives in the settings
   pane as well, but the owner asked for it to be one press rather than a trip
   into a panel -- and it starts at "off", so wandering into the game never
   loads a model. */
function drawVoicesButton() {
  const button = $("#voices-btn");
  if (!button || !S.settings) return;
  const level = S.settings.chatter || "off";
  const label = ((S.options.chatter || {})[level] || {}).label || level;
  button.textContent = "Voices: " + label.toLowerCase();
  button.classList.toggle("on", level !== "off");
}

function cycleVoices() {
  return once($("#voices-btn"), cycleVoicesNow);
}

async function cycleVoicesNow() {
  const levels = Object.keys(S.options.chatter || { off: 1 });
  const at = levels.indexOf(S.settings.chatter || "off");
  const next = levels[(at + 1) % levels.length];
  const out = await postJSON("/api/world/settings", { values: { chatter: next } });
  S.settings = out.settings;
  drawVoicesButton();
  drawSettings();
  toast(
    next === "off"
      ? "the crew go quiet — nothing will use a model"
      : "the crew start talking (" + next + ")"
  );
}

/* Zoom, on the wheel and on the plus and minus keys. Watching, it zooms about
   the middle of the deck; playing, about you. */
function setZoom(next) {
  S.zoom = Math.max(0.5, Math.min(3.5, next));
  S.lightKey = "";
  if (!S.player || !S.player.aboard) {
    const deck = S.decks.find((d) => d.id === S.deck);
    if (deck) {
      S.cameraX = deck.width / 2;
      S.cameraY = deck.height / 2;
    }
  }
  const el = $("#zoom-label");
  if (el) el.textContent = Math.round(S.zoom * 100) + "%";
}

function wireZoom() {
  const stage = $("#stagewrap");
  stage.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      setZoom(S.zoom * (event.deltaY < 0 ? 1.12 : 1 / 1.12));
    },
    { passive: false }
  );
  window.addEventListener("keydown", (event) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((event.target || {}).tagName || "");
    if (typing || S.talking) return;
    if (event.key === "+" || event.key === "=") { event.preventDefault(); setZoom(S.zoom * 1.15); }
    if (event.key === "-" || event.key === "_") { event.preventDefault(); setZoom(S.zoom / 1.15); }
    if (event.key === "0") { event.preventDefault(); setZoom(1); }
  });
  $("#zoom-in").onclick = () => setZoom(S.zoom * 1.2);
  $("#zoom-out").onclick = () => setZoom(S.zoom / 1.2);
  $("#zoom-label").onclick = () => setZoom(1);
}

/* Sound is off until asked for, like the voices: opening the app should be
   silent. The first press is also the gesture a browser needs before it will
   make any noise at all. */
function wireSound() {
  const button = $("#sound-btn");
  if (!button || !window.Station) return;
  button.onclick = () => {
    const on = Station.toggle();
    button.textContent = "Sound: " + (on ? "on" : "off");
    button.classList.toggle("on", on);
    toast(on ? "the station hums" : "sound off");
  };
}

function wireButtons() {
  $("#voices-btn").onclick = cycleVoices;
  $$(".tab").forEach((tab) => {
    tab.onclick = () => {
      $$(".tab").forEach((t) => t.classList.toggle("on", t === tab));
      $$(".pane").forEach((p) => p.classList.toggle("on", p.id === "pane-" + tab.dataset.pane));
      $("#pane-crew").dataset.stamp = "";
      S.logKeys = null;
      drawCrewList();
      drawLog();
      drawVoices();
    };
  });
  $("#btn-talk").onclick = async () => {
    const button = $("#btn-talk");
    button.disabled = true;
    button.textContent = "asking…";
    try {
      const out = await postJSON("/api/world/talk");
      toast(out.happened ? "they had a word" : "nobody was free to talk");
    } catch (err) {
      toast("the chatter model did not answer");
    }
    button.disabled = false;
    button.textContent = "Make someone talk";
    drawVoices();
  };
  $("#btn-narrate").onclick = async () => {
    const button = $("#btn-narrate");
    button.disabled = true;
    button.textContent = "narrating… (~30s)";
    try {
      const out = await postJSON("/api/world/narrate");
      toast(out.day_story ? out.day_story.headline : "the narrator had nothing");
    } catch (err) {
      toast("the narrator did not answer");
    }
    button.disabled = false;
    button.textContent = "Narrate today";
    drawVoices();
  };
  $("#btn-save").onclick = () =>
    once($("#btn-save"), async () => {
      await postJSON("/api/saves/manual");
      $("#save-info").textContent = "saved to slot “manual”";
      toast("station saved");
    });
  $("#btn-load").onclick = () =>
    once($("#btn-load"), async () => {
      let snap;
      try {
        snap = await postJSON("/api/saves/manual/load");
      } catch (err) {
        if (!/404$/.test(err.message)) throw err;
        toast("no save in slot “manual” yet");
        return;
      }
      applySnapshot(snap);
      toast("station loaded");
    });
  $("#btn-reload").onclick = () =>
    once($("#btn-reload"), async () => {
      applySnapshot(await postJSON("/api/world/reload"));
      const station = await getJSON("/api/station");
      S.decks = station.decks;
      S.locations = station.locations;
      S.lightKey = ""; // the light bake keys on props, not deck rows
      toast("content re-read");
    });
  /* Starting over throws away the clock, the log and where you are, so it
     takes a second press within four seconds. */
  const fresh = $("#btn-new");
  fresh.onclick = () => {
    if (!fresh.dataset.armed) {
      fresh.dataset.armed = "1";
      fresh.textContent = "Press again to start over";
      clearTimeout(fresh._t);
      fresh._t = setTimeout(() => {
        delete fresh.dataset.armed;
        fresh.textContent = "Start over";
      }, 4000);
      return;
    }
    clearTimeout(fresh._t);
    delete fresh.dataset.armed;
    fresh.textContent = "Start over";
    once(fresh, async () => {
      applySnapshot(await postJSON("/api/world/new", { settings: S.settings }));
      toast("a new day one");
    });
  };
  window.addEventListener("keydown", (event) => {
    if (/^(INPUT|TEXTAREA|SELECT)$/.test((event.target || {}).tagName || "") || S.talking) return;
    if (event.key === "n") {
      S.showNames = !S.showNames;
    } else if (event.key === "Tab") {
      event.preventDefault();
      lookAt(JanView.next(S.decks, S.deck));
    }
  });
}

/* --- being aboard ---------------------------------------------------------- */

/* Walking, predicted here rather than waited for.
 *
 * The first version posted which way you were holding, and then eased you
 * towards whatever position the next poll reported. The poll is three times a
 * second, so you moved in three visible lurches a second -- "the wlaking is not
 * smooth at all". The backend is still the authority: it walks you too, and its
 * answer is used to correct drift. But what you SEE is computed here, every
 * frame, from your own key presses, so pressing a key moves you on the very
 * next frame.
 *
 * The rules below are a deliberate copy of Player.step in janhollow/player.py:
 * same speed, same corner box, same per-axis slide. If one changes the other
 * must, and the drift correction below is what makes a small mismatch harmless
 * rather than a visible snap.
 */
const WALK_SPEED = 3.1;   // tiles a second, matching player.py
const CORNER = 0.3;       // how much of a tile you take up, matching player.py
const SNAP_AT = 1.6;      // tiles of disagreement that mean "teleported, not drifted"

function tileFree(deckId, x, y) {
  const deck = S.decks.find((d) => d.id === deckId);
  if (!deck) return false;
  const row = deck.rows[y];
  if (row === undefined) return false;
  const ch = row[x];
  if (ch !== "." && ch !== "+" && ch !== "L") return false;
  const solid = S.solid[deckId];
  return !(solid && solid.has(x + "," + y));
}

function spotFree(deckId, x, y) {
  return (
    tileFree(deckId, Math.round(x - CORNER), Math.round(y - CORNER)) &&
    tileFree(deckId, Math.round(x + CORNER), Math.round(y - CORNER)) &&
    tileFree(deckId, Math.round(x - CORNER), Math.round(y + CORNER)) &&
    tileFree(deckId, Math.round(x + CORNER), Math.round(y + CORNER))
  );
}

function walkLocally(dt) {
  const player = S.player;
  if (!player || !player.aboard || player.riding) return;
  let dx = (S.held.right ? 1 : 0) - (S.held.left ? 1 : 0);
  let dy = (S.held.down ? 1 : 0) - (S.held.up ? 1 : 0);
  if (!dx && !dy) return;
  const length = Math.hypot(dx, dy);
  dx /= length;
  dy /= length;
  const distance = WALK_SPEED * dt;
  /* Each axis on its own, so walking into a wall at an angle slides along it
     instead of stopping you dead. */
  for (const [ax, ay] of [[dx, 0], [0, dy]]) {
    if (!ax && !ay) continue;
    const nx = player.drawX + ax * distance;
    const ny = player.drawY + ay * distance;
    if (spotFree(player.deck, nx, ny)) {
      player.drawX = nx;
      player.drawY = ny;
    }
  }
  player.facing = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "right" : "left") : dy > 0 ? "down" : "up";
  player.moving = true;
}

/* The server's answer, folded in gently. A big disagreement means something
   happened that was not walking -- the lift, a load, stepping aboard -- so take
   it whole; a small one is the two simulations drifting apart by a frame or
   two, and is nudged away rather than snapped. */
function reconcilePlayer(fresh) {
  const player = S.player;
  const away = Math.hypot(fresh.x - player.drawX, fresh.y - player.drawY);
  if (player.drawDeck !== fresh.deck || away > SNAP_AT || fresh.riding) {
    player.drawX = fresh.x;
    player.drawY = fresh.y;
  } else if (away > 0.05) {
    player.drawX += (fresh.x - player.drawX) * 0.12;
    player.drawY += (fresh.y - player.drawY) * 0.12;
  }
  player.drawDeck = fresh.deck;
}

/* Which way you are holding, sent only when it changes. The backend does the
   walking, so this is a few bytes on a key press rather than a request a
   frame. */
function pushHold() {
  const dx = (S.held.right ? 1 : 0) - (S.held.left ? 1 : 0);
  const dy = (S.held.down ? 1 : 0) - (S.held.up ? 1 : 0);
  const stamp = dx + "," + dy;
  if (stamp === S.sentHold) return;
  S.sentHold = stamp;
  if (S.player) S.player.moving = !!(dx || dy);
  /* Walking means you want to see yourself again. */
  if ((dx || dy) && (S.peeking || (S.follow && S.selected))) backToMe();
  postJSON("/api/player/hold", { dx, dy }).catch(() => {});
}

const KEYS = {
  arrowup: "up", w: "up", arrowdown: "down", s: "down",
  arrowleft: "left", a: "left", arrowright: "right", d: "right",
};

function drawPlayerBar() {
  const bar = $("#playbar");
  const player = S.player;
  if (!player) return;
  bar.hidden = false;
  $("#join").hidden = player.aboard;
  $("#leave").hidden = !player.aboard;
  $("#playhint").hidden = !player.aboard;
  setText($("#you"), player.aboard
    ? player.label + (player.role ? " — " + player.role : "")
    : "");
  $("#sit").hidden = !player.aboard;
  setText($("#sit"), "Do something (E)");
  $("#sleep").hidden = true;
  drawSlots();
}

/* The four slots in the play bar. Rebuilt only when what you carry changes,
   because the bar is redrawn on every poll. */
function drawSlots() {
  const host = $("#slots");
  const player = S.player;
  host.hidden = !player.aboard;
  if (!player.aboard) return;
  const carrying = player.carrying || [];
  const stamp = JSON.stringify([carrying.map((c) => c.uid), player.held]);
  if (host.dataset.stamp === stamp) return;
  host.dataset.stamp = stamp;
  host.innerHTML = "";
  for (let i = 0; i < 4; i++) {
    const slot = document.createElement("button");
    const thing = carrying[i];
    slot.className = "slot" + (thing && i === player.held ? " held" : "");
    slot.title = thing ? thing.label : "empty";
    const art = document.createElement("canvas");
    art.width = 32;
    art.height = 32;
    if (thing) {
      S.tiles.draw(art.getContext("2d"), thing.pack + "/" + thing.sprite, 0, 0, 0, 1);
    }
    const key = document.createElement("span");
    key.className = "key";
    key.textContent = String(i + 1);
    slot.append(art, key);
    slot.onclick = (event) => {
      event.stopPropagation();
      if (thing) carryDo("select", i);
    };
    host.appendChild(slot);
  }
}

/* Pick up, put down, give or choose. The backend says what happened. */
async function carryDo(what, slot) {
  const out = await postJSON("/api/player/carry", { do: what, slot: slot || 0 });
  if (!out.ok) toast(out.why || "that did not work");
  else if (what === "pickup") toast(`you pick up the ${out.item}`);
  else if (what === "drop") toast(`you put down the ${out.item}`);
  else if (what === "give") toast(`you give ${out.to} the ${out.item}` + (out.warmed ? " — they are pleased" : ""));
  await refresh();
}

function joinStation() {
  return once($("#join"), joinStationNow);
}

async function joinStationNow() {
  const player = await postJSON("/api/player/join");
  S.player = Object.assign({}, player, { drawX: player.x, drawY: player.y, drawDeck: player.deck });
  S.cameraX = player.x;
  S.cameraY = player.y;
  S.deck = player.deck;
  S.pickedDeck = true;
  S.follow = false;
  S.peeking = false;
  unzoomFind();
  drawDeckButtons();
  drawPlayerBar();
  drawPeek();
  const where = player.arrived || {};
  toast(
    "you step aboard" +
      (where.label ? " in the " + where.label : "") +
      (where.beside_label ? ", beside " + where.beside_label : "")
  );
}

function leaveStation() {
  return once($("#leave"), leaveStationNow);
}

async function leaveStationNow() {
  await postJSON("/api/player/leave");
  S.sentHold = "";
  S.held = { up: false, down: false, left: false, right: false };
  toast("you step back out");
  await refresh();
}

function openTalk() {
  if (!S.player || !S.player.aboard) return;
  S.talking = true;
  $("#talkwrap").hidden = false;
  $("#talk").value = "";
  $("#talk").focus();
  /* Stop dead when the talk box opens, or you carry on walking into a wall
     while typing. */
  S.held = { up: false, down: false, left: false, right: false };
  pushHold();
}

function closeTalk() {
  S.talking = false;
  $("#talkwrap").hidden = true;
  $("#stage").focus();
}

async function sendTalk() {
  const text = $("#talk").value.trim();
  if (!text) return closeTalk();
  $("#talk").value = "";
  $("#talk").disabled = true;
  try {
    const out = await postJSON("/api/player/say", { text });
    if (window.Station && out.heard_by) Station.chime("talk");
    if (!out.heard_by) toast("nobody close enough to hear you");
    else if (out.heard_by.fallback) toast(out.heard_by.who + " answers (no model running)");
  } catch (err) {
    toast("that did not get through");
  }
  $("#talk").disabled = false;
  $("#talk").focus();
}

/* Everything you can do where you stand, in one menu. The owner asked for "a
   button for interacting to things and manus for those interaction maby liek
   left click or e" — so E and left click both open this, and the entries come
   from the backend rather than being listed here, which means a new
   interaction is one entry in Player.actions and nothing else. */
function drawActions() {
  const host = $("#actions");
  const player = S.player;
  if (!host) return;
  const list = (player && player.aboard && player.actions) || [];
  if (!S.menuOpen || !list.length) {
    host.hidden = true;
    host.dataset.stamp = "";
    return;
  }
  host.hidden = false;
  /* Rebuilt only when the entries change: the poll calls this every time. */
  if (sameStamp(host, JSON.stringify(list))) return;
  host.innerHTML = "";
  for (const action of list) {
    const button = document.createElement("button");
    button.className = "btn";
    button.textContent = action.label;
    button.onclick = () => doAction(action);
    host.appendChild(button);
  }
  const close = document.createElement("button");
  close.className = "btn";
  close.textContent = "Never mind (Esc)";
  close.onclick = () => { S.menuOpen = false; drawActions(); };
  host.appendChild(close);
}

async function doAction(action) {
  S.menuOpen = false;
  drawActions();
  try {
    if (action.kind === "sit" || action.kind === "stand") await sitOrStand();
    else if (action.kind === "sleep") await sleepTillMorning();
    else if (action.kind === "ride") {
      await postJSON("/api/player/ride", { deck: action.target });
      if (window.Station) Station.chime("lift");
      toast("the lift closes");
    } else if (action.kind === "talk") openTalk();
    else if (["pickup", "drop", "give"].includes(action.kind)) await carryDo(action.kind);
  } catch (err) {
    toast("that did not work");
  }
  await refresh();
}

function toggleActions() {
  const list = (S.player && S.player.actions) || [];
  if (!list.length) {
    toast("nothing to do here");
    return;
  }
  S.menuOpen = !S.menuOpen;
  drawActions();
}

async function sitOrStand() {
  const out = await postJSON("/api/player/sit");
  if (out.nothing_here) toast("nothing to sit on here");
  await refresh();
}

async function sleepTillMorning() {
  try {
    const out = await postJSON("/api/player/sleep");
    toast(`you sleep through to ${out.clock}`);
    await refresh();
  } catch (err) {
    toast("there is nothing to sleep on here");
  }
}

function wirePlaying() {
  $("#join").onclick = joinStation;
  $("#leave").onclick = leaveStation;
  $("#back-to-me").onclick = backToMe;
  $("#sit").onclick = toggleActions;
  $("#sleep").onclick = sleepTillMorning;
  $("#talksend").onclick = sendTalk;
  $("#talkclose").onclick = closeTalk;

  window.addEventListener("keydown", (event) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((event.target || {}).tagName || "");
    if (S.talking || typing) {
      if (event.key === "Enter" && S.talking) { event.preventDefault(); sendTalk(); }
      if (event.key === "Escape" && S.talking) { event.preventDefault(); closeTalk(); }
      return;
    }
    const key = event.key.toLowerCase();
    if (KEYS[key] && S.player && S.player.aboard) {
      event.preventDefault();
      S.held[KEYS[key]] = true;
      pushHold();
      return;
    }
    if (!S.player || !S.player.aboard) return;
    /* Enter opens the talk box, and so does simply starting to type: the owner
       asked for both ways in. */
    if (event.key === "Enter") { event.preventDefault(); openTalk(); return; }
    if (key === "e") { event.preventDefault(); toggleActions(); return; }
    /* 1-4 choose what is in your hands, but only when that slot holds
       something; otherwise a digit still starts you talking. */
    const slot = "1234".indexOf(event.key);
    if (slot >= 0 && (S.player.carrying || [])[slot]) {
      event.preventDefault();
      carryDo("select", slot);
      return;
    }
    if (event.key === "Escape" && S.menuOpen) { event.preventDefault(); S.menuOpen = false; drawActions(); return; }
    if (event.key.length === 1 && /[a-z0-9'?!.]/i.test(event.key) && !KEYS[key]) {
      openTalk();
      $("#talk").value = event.key;
      event.preventDefault();
    }
  });

  /* Left click on the deck opens the same menu. */
  $("#stage").addEventListener("click", () => {
    if (S.player && S.player.aboard) toggleActions();
  });

  window.addEventListener("keyup", (event) => {
    const key = event.key.toLowerCase();
    if (KEYS[key]) {
      S.held[KEYS[key]] = false;
      pushHold();
    }
  });

  /* Holding a key while the window loses focus would leave you walking for
     ever. */
  window.addEventListener("blur", () => {
    S.held = { up: false, down: false, left: false, right: false };
    pushHold();
  });
}

/* --- the frame ------------------------------------------------------------ */

let lastFrame = 0;

function frame(now) {
  const canvas = $("#stage");
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.floor(canvas.clientWidth * dpr);
  const height = Math.floor(canvas.clientHeight * dpr);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
    S.stars = {};
    S.lightKey = "";
  }
  const ctx = ForgeArt.crisp(canvas.getContext("2d"));
  const dt = Math.min(0.2, (now - lastFrame) / 1000 || 0);
  lastFrame = now;

  /* Ease towards the server's position rather than snapping to it: the poll is
     three or four times a second and the eye sees every one of those steps. */
  /* The crew are carried along their own velocity between polls and only
     nudged towards the reported position, instead of being dragged towards a
     target that arrives three times a second. That dragging is what made
     everyone walk in steps. */
  const nudge = Math.min(1, dt * 2.5);
  for (const member of S.crew) {
    if (member.vx || member.vy) {
      member.drawX += member.vx * dt;
      member.drawY += member.vy * dt;
    }
    const away = Math.hypot(member.x - member.drawX, member.y - member.drawY);
    if (away > 1.6 || member.riding) {
      member.drawX = member.x;
      member.drawY = member.y;
    } else {
      member.drawX += (member.x - member.drawX) * nudge;
      member.drawY += (member.y - member.drawY) * nudge;
    }
  }
  if (S.player && S.player.aboard) {
    walkLocally(dt);
  }
  /* The camera trails a little behind whoever it is on: you on your own deck,
     else a crew member being found. At this speed a camera welded to someone's
     feet reads as the room sliding about rather than them walking. */
  const found = S.follow && S.selected && S.byId[S.selected];
  const target = JanView.cameraOn({
    deck: S.deck,
    aboard: aboardNow(),
    playerDeck: myDeck(),
    me: S.player ? { x: S.player.drawX, y: S.player.drawY } : null,
    found: found ? { deck: found.deck, x: found.drawX, y: found.drawY } : null,
  });
  /* Finding someone, keep them clear of the play bar: the canvas pixels the
     bar covers at the top of the stage (it wraps to three rows at 800 px). */
  S.findPad = 0;
  if (found && found.deck === S.deck) {
    const bar = $("#playbar");
    if (bar && !bar.hidden) {
      const covered = bar.getBoundingClientRect().bottom - canvas.getBoundingClientRect().top;
      S.findPad = Math.max(0, Math.min(canvas.height * 0.6, covered * dpr));
    }
  }
  if (target) {
    const follow = Math.min(1, dt * 7);
    S.cameraX += (target.x - S.cameraX) * follow;
    S.cameraY += (target.y - S.cameraY) * follow;
  }

  const deck = S.decks.find((d) => d.id === S.deck);
  if (deck && S.tiles) drawDeck(ctx, deck, canvas, now);

  if (window.Station) {
    Station.frame(now, {
      walking: !!(S.player && S.player.aboard && (S.held.up || S.held.down || S.held.left || S.held.right)),
      minute: S.minuteOfDay,
      loud: S.deck === "engineering",
    });
  }
}

wireButtons();
wireSound();
wireZoom();
wirePlaying();

/* The first load. If the backend is not up yet (Forge still starting it, or
   it fell over) the card says so and tries again by itself, 2 s, 4 s, 8 s,
   then every 10 s; Try now skips the wait. The page only gets going once. */
const starting = { tries: 0, timer: 0, running: false };
async function start() {
  clearTimeout(starting.timer);
  if (starting.running) return;
  starting.running = true;
  const card = $("#bootcard");
  try {
    await boot();
    card.classList.add("gone");
  } catch (err) {
    starting.tries += 1;
    const wait = Math.min(10000, 1000 * 2 ** starting.tries);
    $("#boot-title").textContent = "The station is not answering";
    $("#boot-text").textContent =
      "Its backend did not respond (" + err.message + "). Trying again in " +
      Math.round(wait / 1000) + " s.";
    $("#boot-retry").hidden = false;
    starting.timer = setTimeout(start, wait);
  } finally {
    starting.running = false;
  }
}
$("#boot-retry").onclick = () => {
  $("#boot-text").textContent = "Trying again…";
  start();
};
start();
