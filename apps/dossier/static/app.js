/* Dossier frontend.
 *
 * The page knows how to draw a handful of generic block kinds - facts,
 * timeline, claims, quotes, sources, relations, prose, notes - and nothing
 * about any particular page or subject type. The backend's registries decide
 * which pages a dossier has and what goes in them, so adding a page type or a
 * subject type needs no change here.
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
  status: null, library: [], world: [], map: null, subject: null,
  page: 0, minRelevance: 0, selectedCountry: null, queueWatch: null, historyWatch: null, newInfoWatch: null,
  arcs: [], arcKinds: [], arcOn: new Set(), centres: null, watch: null,
  byMap: new Map(), mapNames: new Set(), libLimit: 0, queueDone: null,
  libPlace: null,
};

/* ---------------------------------------------------------------- views */

function showView(name, hash) {
  document.querySelectorAll(".view").forEach((v) =>
    v.classList.toggle("on", v.id === "view-" + name));
  document.querySelectorAll(".views button").forEach((b) =>
    b.classList.toggle("on", b.dataset.view === name));
  const target = hash || "#/" + name;
  if (location.hash !== target) history.replaceState(null, "", target);
  if (name === "jobs") refreshQueue();
  if (name === "library") renderLibrary();
  if (name === "watch") loadWatch();
  // The graph is read from disk on the backend, so it is loaded when the tab
  // is first opened rather than on every page load.
  if (name === "links") { fillGraphNames(); loadGraphStats(); }
}

/* A dossier has a URL, so it can be linked to, reopened and screenshotted. */
function routeFromHash() {
  const match = (location.hash || "").match(/^#\/subject\/([\w.-]+)(?:\/([\w.-]+))?$/);
  if (match) {
    openSubject(decodeURIComponent(match[1]),
      match[2] ? decodeURIComponent(match[2]) : "");
    return true;
  }
  // A mind map has a URL too, for the same reason a dossier does: so it can be
  // linked to, reopened and screenshotted.
  const graphed = (location.hash || "").match(/^#\/links\/(.+)$/);
  if (graphed) {
    showView("links", location.hash);
    fillGraphNames(); loadGraphStats();
    $("graph-centre").value = decodeURIComponent(graphed[1]);
    drawGraph();
    return true;
  }
  const view = (location.hash || "").replace("#/", "");
  if (["world", "library", "links", "watch", "jobs"].includes(view)) { showView(view); return true; }
  return false;
}
window.addEventListener("hashchange", routeFromHash);
document.querySelectorAll(".views button").forEach((b) =>
  b.addEventListener("click", () => showView(b.dataset.view)));

/* Numeric settings get a slider beside their number field. The two stay in
   step; letting go of the slider fires the number field's own "change", so
   whatever already listens to the field keeps working. */
function pairSlider(input) {
  const range = document.createElement("input");
  range.type = "range";
  range.className = "pair-range";
  range.min = input.min; range.max = input.max; range.step = input.step || "1";
  range.value = input.value;
  range.title = input.title || "";
  range.addEventListener("input", () => { input.value = range.value; });
  range.addEventListener("change", () => input.dispatchEvent(new Event("change")));
  input.addEventListener("input", () => { range.value = input.value; });
  input.before(range);
}
const syncPair = (input) => {
  const range = input.previousElementSibling;
  if (range && range.classList.contains("pair-range")) range.value = input.value;
};
["recipe-limit", "watch-per"].forEach((id) => pairSlider($(id)));

/* ----------------------------------------------------------------- boot */

/* The Jan and storage pills, from /api/status. */
function paintStatus(s) {
  $("pill-jan").textContent = s.jan
    ? `Jan · ${Object.values(s.tiers).filter(Boolean).length} tiers`
    : "Jan offline";
  $("pill-jan").className = "pill " + (s.jan ? "ok" : "bad");
  $("pill-jan").title = s.jan
    ? Object.entries(s.tiers).map(([k, v]) => `${k}: ${v || "none"}`).join("\n")
    : s.jan_detail;

  // in a Forge release the library stays with the rest of the user's things
  // and Forge moves it with them: no chooser of Dossier's own
  const fixed = !!s.storage.fixed;
  $("pill-store").dataset.fixed = fixed ? "1" : "";
  $("pill-store").textContent =
    (fixed ? "" : s.storage.on_usb ? "USB drive · " : "local disk · ") + s.storage.free_gb + " GB free";
  $("pill-store").className = "pill " + (s.storage.on_usb ? "ok" : "") + (fixed ? "" : " clickable");
  $("pill-store").title = fixed
    ? s.storage.detail + ": move them all from Forge's Where your things are kept.\n" + s.storage.path
    : s.storage.detail + "\n" + s.storage.path;
}

async function boot() {
  try {
    state.status = await api("/api/status");
  } catch (e) {
    $("pill-jan").textContent = "backend unreachable";
    $("pill-jan").className = "pill bad";
    return;
  }
  paintStatus(state.status);
  const s = state.status;

  const typeSelect = $("add-type"), libType = $("lib-type");
  s.entity_types.forEach((t) => {
    typeSelect.appendChild(new Option(t.label, t.name));
    libType.appendChild(new Option(t.plural, t.name));
  });

  // A view named in the URL opens straight away, not after the map and the
  // library have arrived: the World tab used to show first and then jump.
  routeFromHash();

  $("recipes").innerHTML = "";
  s.seeds.forEach((seed) => {
    const row = el("div", "recipe");
    const info = el("div", "info");
    info.innerHTML = `<b>${esc(seed.label)}</b><div>${esc(seed.description)}</div>`;
    const go = el("button", "primary", "Queue");
    go.addEventListener("click", () => queueRecipe(seed.name, go));
    row.append(info, go);
    $("recipes").appendChild(row);
  });

  await Promise.all([loadMap(), refreshLibrary(), loadBriefing()]);
  loadArcs();
  refreshQueue();
}

/* ------------------------------------------------------------------ map */

async function loadMap() {
  try {
    state.map = await (await fetch("/world-map.json")).json();
  } catch (e) { return; }
  const svg = $("worldmap");
  svg.setAttribute("viewBox", state.map.viewBox);
  state.mapNames = new Set(state.map.countries.map((c) => c.name));
  svg.innerHTML = "";
  const ns = "http://www.w3.org/2000/svg";
  const group = document.createElementNS(ns, "g");
  group.id = "mapgroup";
  state.map.countries.forEach((c) => {
    const p = document.createElementNS(ns, "path");
    p.setAttribute("d", c.d);
    p.dataset.name = c.name;
    group.appendChild(p);
  });
  svg.appendChild(group);
  wireMap();
  paintMap();
  renderOffMap();
  if (state.library.length) renderCoverage();
}

/* Country names differ between Wikidata labels and Natural Earth. Only the
   ones that actually collide are listed; everything else matches on name. */
const COUNTRY_ALIASES = {
  "United States": "United States of America",
  "USA": "United States of America",
  "Czech Republic": "Czechia",
  "Republic of Ireland": "Ireland",
  "Kingdom of the Netherlands": "Netherlands",
  "People's Republic of China": "China",
  "Republic of China": "Taiwan",
  "South Korea": "South Korea",
  "Republic of Korea": "South Korea",
  "North Korea": "North Korea",
  "Russian Federation": "Russia",
  "United Kingdom of Great Britain and Northern Ireland": "United Kingdom",
  "Kingdom of Denmark": "Denmark",
  "Kingdom of Spain": "Spain",
  "Federal Republic of Germany": "Germany",
  "Republic of India": "India",
  "Islamic Republic of Iran": "Iran",
  "State of Israel": "Israel",
  "Republic of Turkey": "Turkey",
  "Türkiye": "Turkey",
  "Swiss Confederation": "Switzerland",
  "Bosnia and Herzegovina": "Bosnia and Herz.",
  "Dominican Republic": "Dominican Rep.",
  "Central African Republic": "Central African Rep.",
  "South Sudan": "S. Sudan",
  "Democratic Republic of the Congo": "Dem. Rep. Congo",
  "Republic of the Congo": "Congo",
  "Ivory Coast": "Côte d'Ivoire",
  "Myanmar": "Myanmar",
  "Burma": "Myanmar",
  "East Timor": "Timor-Leste",
  "Eswatini": "eSwatini",
  "Kingdom of Eswatini": "eSwatini",
  "Solomon Islands": "Solomon Is.",
  "Equatorial Guinea": "Eq. Guinea",
  "Western Sahara": "W. Sahara",
  "Sahrawi Arab Democratic Republic": "W. Sahara",
  // Natural Earth still calls it Macedonia; mapping it to itself left it unshaded.
  "North Macedonia": "Macedonia",
  "Republic of North Macedonia": "Macedonia",
  "The Gambia": "Gambia",
  "The Bahamas": "Bahamas",
  "Northern Cyprus": "N. Cyprus",
  "Turkish Republic of Northern Cyprus": "N. Cyprus",
  "State of Palestine": "Palestine",
  "Palestinian territories": "Palestine",
  "Occupied Palestinian territory": "Palestine",
  "Vatican City": "Vatican",
  "Holy See": "Vatican",
};
const mapName = (n) => COUNTRY_ALIASES[n] || n;

/* Several Wikidata labels can land on one map shape ("United States" and
   "United States of America"), so the per-place totals are merged by the name
   the map uses. Before this the tooltip and the panel showed only whichever
   label came first. A place with no shape (a historical state, a microstate,
   "Unattributed") keeps its own name and is listed under the map instead.

   A subject recorded under two labels of one shape ("Republic of China" and
   "Taiwan") is in both totals. When every label lists all its names, the
   totals are recounted from the distinct subjects, so it counts once; past the
   40 names a label carries, that cannot be known here and the sum stands. */
function mergeByMapName(countries, rows) {
  const merged = new Map();
  countries.forEach((c) => {
    const key = mapName(c.country);
    const complete = c.names.length >= c.subjects;
    const into = merged.get(key);
    if (!into) {
      merged.set(key, { ...c, country: key, labels: [c.country], names: [...c.names], complete });
      return;
    }
    into.labels.push(c.country);
    into.complete = into.complete && complete;
    into.subjects += c.subjects; into.claims += c.claims;
    into.disputed += c.disputed; into.events += c.events;
    const seen = new Set(into.names.map((n) => n.slug));
    c.names.forEach((n) => { if (!seen.has(n.slug)) into.names.push(n); });
  });
  const bySlug = new Map((rows || []).map((r) => [r.slug, r]));
  merged.forEach((m) => {
    const held = m.names.map((n) => bySlug.get(n.slug));
    if (m.labels.length < 2 || !m.complete || held.some((r) => !r)) return;
    m.subjects = held.length;
    m.claims = held.reduce((t, r) => t + (r.claims || 0), 0);
    m.disputed = held.reduce((t, r) => t + (r.disputed || 0), 0);
    m.events = held.reduce((t, r) => t + (r.timeline || 0), 0);
  });
  return merged;
}

function paintMap() {
  if (!state.map) return;
  const byCountry = state.byMap;
  const max = Math.max(1, ...[...byCountry.values()]
    .filter((c) => state.mapNames.has(c.country)).map((c) => c.subjects));
  document.querySelectorAll("#worldmap path[data-name]").forEach((p) => {
    const hit = byCountry.get(p.dataset.name);
    p.classList.toggle("has-data", !!hit);
    if (hit) {
      // Square-root so one dossier is still visible next to a country with fifty.
      const weight = Math.sqrt(hit.subjects / max);
      p.style.fill = `color-mix(in srgb, var(--accent) ${Math.round(18 + weight * 82)}%, #1b1f27)`;
    } else {
      p.style.fill = "";
    }
  });
}

function wireMap() {
  const svg = $("worldmap"), tip = $("maptip"), group = $("mapgroup");
  let view = { x: 0, y: 0, k: 1 }, drag = null;
  const box = state.map.viewBox.split(" ").map(Number);

  const apply = () => {
    group.setAttribute("transform",
      `translate(${view.x} ${view.y}) scale(${view.k})`);
  };
  const zoom = (factor, cx, cy) => {
    const k = Math.min(8, Math.max(1, view.k * factor));
    const scale = k / view.k;
    view.x = cx - (cx - view.x) * scale;
    view.y = cy - (cy - view.y) * scale;
    view.k = k;
    if (view.k === 1) { view.x = 0; view.y = 0; }
    apply();
  };
  const toLocal = (evt) => {
    const r = svg.getBoundingClientRect();
    return {
      x: (evt.clientX - r.left) / r.width * box[2],
      y: (evt.clientY - r.top) / r.height * box[3],
    };
  };

  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const p = toLocal(e);
    zoom(e.deltaY < 0 ? 1.22 : 1 / 1.22, p.x, p.y);
  }, { passive: false });

  // mouseup reaches the window before the click reaches the map, so whether
  // the press was a drag is remembered past it: letting go of a pan over a
  // country used to open that country.
  let dragged = false;
  svg.addEventListener("mousedown", (e) => {
    drag = { ...toLocal(e), x0: view.x, y0: view.y, moved: false };
    dragged = false;
    svg.classList.add("dragging");
  });
  window.addEventListener("mouseup", () => {
    if (drag && drag.moved) dragged = true;
    drag = null; svg.classList.remove("dragging");
  });
  svg.addEventListener("mousemove", (e) => {
    const p = toLocal(e);
    if (drag) {
      view.x = drag.x0 + (p.x - drag.x);
      view.y = drag.y0 + (p.y - drag.y);
      // A hand that shakes by a pixel is still a click.
      if (Math.hypot(view.x - drag.x0, view.y - drag.y0) > 3) drag.moved = true;
      apply();
      tip.classList.remove("on");
      return;
    }
    const path = e.target.closest("path");
    if (!path) { tip.classList.remove("on"); return; }
    // Arcs live in the same group as the countries, so they arrive here too.
    if (path.dataset.arc) { arcTip(path, e); return; }
    const name = path.dataset.name;
    const hit = state.byMap.get(name);
    tip.innerHTML = hit
      ? `<b>${esc(name)}</b><br>${hit.subjects} held · ${hit.claims} claims`
        + (hit.disputed ? ` · <span style="color:var(--disputed)">${hit.disputed} disputed</span>` : "")
      : `<b>${esc(name)}</b><br><span class="muted">nothing held yet</span>`;
    const r = svg.getBoundingClientRect();
    tip.style.left = Math.min(e.clientX - r.left + 14, r.width - 250) + "px";
    tip.style.top = (e.clientY - r.top + 14) + "px";
    tip.classList.add("on");
  });
  svg.addEventListener("mouseleave", () => tip.classList.remove("on"));

  svg.addEventListener("click", (e) => {
    if (dragged) { dragged = false; return; }
    const path = e.target.closest("path");
    if (!path) return;
    // Clicking a tie opens the dossier that recorded it, which is the whole
    // point of the arc carrying its provenance.
    if (path.dataset.arc) {
      const via = (JSON.parse(path.dataset.arc).via || [])[0];
      if (via) openSubject(via.slug);
      return;
    }
    document.querySelectorAll("#worldmap path[data-name]").forEach((p) =>
      p.classList.toggle("selected", p === path));
    selectCountry(path.dataset.name);
  });

  $("zoom-in").addEventListener("click", () => zoom(1.4, box[2] / 2, box[3] / 2));
  $("zoom-out").addEventListener("click", () => zoom(1 / 1.4, box[2] / 2, box[3] / 2));
  $("zoom-reset").addEventListener("click", () => { view = { x: 0, y: 0, k: 1 }; apply(); });
}

function selectCountry(mapCountry) {
  const hit = state.byMap.get(mapCountry);
  // A place picked from the list under the map is not a shape on it, so no
  // country stays outlined as if it had been clicked.
  if (!state.mapNames.has(mapCountry)) {
    document.querySelectorAll("#worldmap path.selected").forEach((p) =>
      p.classList.remove("selected"));
  }
  const panel = $("country-panel");
  panel.hidden = false;
  panel.innerHTML = "";
  panel.appendChild(el("h3", null, mapCountry));
  if (!hit) {
    panel.appendChild(el("div", "small muted",
      "Nothing held for this country yet. Add a subject, or run a bulk job."));
    return;
  }
  const summary = el("div", "small muted",
    `${hit.subjects} subjects · ${hit.claims} claims · ${hit.disputed} disputed · ${hit.events} dated events`);
  panel.appendChild(summary);
  if (hit.labels.length > 1) {
    panel.appendChild(el("div", "small muted",
      "Recorded as " + hit.labels.join(", ")));
  }
  const bySlug = new Map(state.library.map((r) => [r.slug, r]));
  const grid = el("div", "grid");
  grid.style.marginTop = "10px";
  hit.names.forEach((n) => grid.appendChild(subjectCard(bySlug.get(n.slug) || n)));
  panel.appendChild(grid);
  if (hit.subjects > hit.names.length) {
    const more = el("button", "ghost",
      `Look for all ${hit.subjects} in the library`);
    more.style.marginTop = "10px";
    more.title = `Shows the first ${hit.names.length} here; the library lists all ${hit.subjects}.`;
    more.addEventListener("click", () => showPlaceInLibrary(mapCountry, hit, more));
    panel.appendChild(more);
  }
  if (!state.mapNames.has(mapCountry)) panel.scrollIntoView({ block: "nearest" });
}

/* The library filtered to exactly the subjects the map counts under a place.
   A text search cannot do it: "Unattributed" is stored in no subject, and
   "Republic of China" also matches "People's Republic of China". */
async function showPlaceInLibrary(name, hit, button) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "Finding them…";
  let found;
  try {
    const query = hit.labels.map((l) => "name=" + encodeURIComponent(l)).join("&");
    found = await api("/api/world/place?" + query);
  } catch (e) {
    button.disabled = false;
    button.textContent = label;
    ForgeDialog.alert("Could not list that place: " + e.message);
    return;
  }
  button.disabled = false;
  button.textContent = label;
  state.libPlace = { name, slugs: new Set(found.slugs) };
  $("lib-search").value = "";
  $("lib-type").value = ""; $("lib-depth").value = "";
  showView("library");
  renderLibrary(true);
  $("view-library").scrollTop = 0;
}

function clearLibraryPlace() {
  state.libPlace = null;
  renderLibrary(true);
}

/* Places with subjects but no shape on a modern map: historical states, the
   microstates the map is too coarse to draw, and subjects with no recorded
   country. Without this list, about a third of the library could not be
   reached from the World tab at all. */
function renderOffMap() {
  const box = $("offmap");
  if (!box || !state.map) return;
  const rows = [...state.byMap.values()]
    .filter((c) => !state.mapNames.has(c.country))
    .sort((a, b) => b.subjects - a.subjects);
  $("offmap-card").hidden = !rows.length;
  if (!rows.length) return;
  const all = box.dataset.all === "1";
  const shown = all ? rows : rows.slice(0, 24);
  const total = rows.reduce((n, c) => n + c.subjects, 0);
  const places = rows.filter((c) => c.country !== "Unattributed").length;
  const unplaced = rows.length > places ? ", plus unattributed" : "";
  $("offmap-count").textContent =
    `${places} places${unplaced} · ${total} subjects`;
  const frag = document.createDocumentFragment();
  shown.forEach((c) => {
    const chip = el("button", "offchip");
    chip.type = "button";
    chip.append(el("span", null, c.country), el("b", null, String(c.subjects)));
    chip.title = `${c.subjects} subjects · ${c.events} dated events`;
    chip.addEventListener("click", () => selectCountry(c.country));
    frag.appendChild(chip);
  });
  if (rows.length > shown.length || all) {
    const toggle = el("button", "ghost offmore",
      all ? "Show fewer" : `Show all ${rows.length}`);
    toggle.type = "button";
    toggle.addEventListener("click", () => {
      box.dataset.all = all ? "" : "1";
      renderOffMap();
    });
    frag.appendChild(toggle);
  }
  box.replaceChildren(frag);
}

/* -------------------------------------------------------------- library */

async function refreshLibrary() {
  const [lib, world] = await Promise.all([api("/api/library"), api("/api/world")]);
  state.library = lib.subjects;
  state.world = world.countries;
  state.byMap = mergeByMapName(state.world, state.library);
  state.libVersion = (state.libVersion || 0) + 1;
  paintMap();
  renderOffMap();
  renderLibrary();
  renderCoverage();
  if ($("view-links").classList.contains("on")) fillGraphNames();
}

function renderCoverage() {
  const byType = {};
  state.library.forEach((r) => byType[r.entity_type] = (byType[r.entity_type] || 0) + 1);
  const total = state.library.length;
  if (!total) { $("coverage").textContent = "Nothing held yet."; return; }
  const labels = Object.fromEntries(
    (state.status?.entity_types || []).map((t) => [t.name, t.plural]));
  // Historical states and "Unattributed" are not countries on today's map, so
  // they are counted apart rather than inflating the country figure.
  const places = [...state.byMap.keys()].filter((n) => n !== "Unattributed");
  const onMap = state.mapNames.size
    ? places.filter((n) => state.mapNames.has(n)).length : places.length;
  const elsewhere = state.mapNames.size ? places.length - onMap : 0;
  const where = elsewhere
    ? `<b>${onMap}</b> countries and <b>${elsewhere}</b> other places`
    : `<b>${onMap}</b> countries`;
  $("coverage").innerHTML =
    `<b>${total}</b> subjects held across ${where}<br>` +
    Object.entries(byType).sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${v} ${esc(labels[k] || k)}`).join(" · ");
}

function subjectCard(row) {
  const card = el("div", "subject");
  card.appendChild(el("h4", null, row.name));
  if (row.description) card.appendChild(el("div", "desc", row.description));

  // What places a subject: the office someone holds, the party they sit for,
  // the country a party contests, where a company is based. A list of names and
  // counts alone is hard to read.
  const placing = [row.role, row.party, row.based, row.industry, row.country]
    .filter(Boolean);
  if (placing.length) {
    const line = el("div", "placing");
    placing.slice(0, 3).forEach((bit, i) => {
      if (i) line.appendChild(el("span", "sep", "·"));
      line.appendChild(el("span", null, bit));
    });
    card.appendChild(line);
  }

  const meta = el("div", "meta");
  const label = (state.status?.entity_types || [])
    .find((t) => t.name === row.entity_type)?.label || row.entity_type;
  meta.appendChild(el("span", "tag type", label));
  if (row.depth === "deep") meta.appendChild(el("span", "tag deep", "deep dived"));
  if (row.sources !== undefined) meta.appendChild(el("span", "tag", row.sources + " sources"));
  if (row.verified) meta.appendChild(el("span", "tag", row.verified + " verified"));
  if (row.disputed) meta.appendChild(el("span", "tag", row.disputed + " disputed"));
  card.appendChild(meta);
  card.addEventListener("click", () => openSubject(row.slug));
  return card;
}

/* The library is drawn a page at a time: 2,450 cards at once took long
   enough to freeze typing in the search box. More arrive as the list is
   scrolled to its end, or from the button there. */
const LIB_PAGE = 150;
const LIB_SORTS = {
  name: (a, b) => a.name.localeCompare(b.name),
  updated: (a, b) => (b.updated || "").localeCompare(a.updated || ""),
  added: (a, b) => (b.added || "").localeCompare(a.added || ""),
  sources: (a, b) => (b.sources || 0) - (a.sources || 0),
  claims: (a, b) => (b.claims || 0) - (a.claims || 0) || (b.verified || 0) - (a.verified || 0),
};
// What a search looks through: the name, the one-line description, and what
// places a subject (office, party, base, industry, country), so "Germany" or
// "prime minister" finds people as well as the country itself.
const LIB_SEARCHED = ["name", "description", "role", "party", "based", "industry", "country"];

function libraryRows() {
  const term = ($("lib-search").value || "").trim().toLowerCase();
  const type = $("lib-type").value, depth = $("lib-depth").value;
  const place = state.libPlace;
  const rows = state.library.filter((r) =>
    (!place || place.slugs.has(r.slug)) &&
    (!term || LIB_SEARCHED.some((k) => String(r[k] || "").toLowerCase().includes(term))) &&
    (!type || r.entity_type === type) &&
    (!depth || r.depth === depth));
  return rows.sort(LIB_SORTS[$("lib-sort").value] || LIB_SORTS.name);
}

/* `fresh` starts again from the top (a new search or sort); otherwise as many
   cards as were showing are drawn again, so a refresh while a queue runs does
   not throw away how far down the list you had scrolled. */
function renderLibrary(fresh) {
  if (!state.libVersion) return;  // not read yet: keep saying so
  const rows = libraryRows();
  if (fresh || !state.libLimit) state.libLimit = LIB_PAGE;
  const place = state.libPlace;
  const key = [state.libVersion, $("lib-search").value, $("lib-type").value,
    $("lib-depth").value, $("lib-sort").value, state.libLimit, place?.name].join("|");
  if (key === state.libKey) return;
  state.libKey = key;
  $("lib-count").textContent = `${rows.length} of ${state.library.length}`;
  $("lib-place").hidden = !place;
  if (place) $("lib-place-name").textContent = place.name;
  const grid = $("lib-grid");
  if (!rows.length) {
    grid.innerHTML = state.library.length
      ? `<div class="empty">Nothing ${place ? "from this place " : ""}matches that search.</div>`
      : '<div class="empty">Nothing held yet. Add a subject from the World tab, or run a bulk job.</div>';
    $("lib-more").hidden = true;
    return;
  }
  const frag = document.createDocumentFragment();
  rows.slice(0, state.libLimit).forEach((r) => frag.appendChild(subjectCard(r)));
  grid.replaceChildren(frag);
  const left = rows.length - state.libLimit;
  $("lib-more").hidden = left <= 0;
  $("lib-more").textContent = `Show ${Math.min(left, LIB_PAGE)} more (${left} not shown)`;
}

function showMoreLibrary() {
  if ($("lib-more").hidden) return;
  state.libLimit += LIB_PAGE;
  renderLibrary();
}
$("lib-more").addEventListener("click", showMoreLibrary);
$("lib-place").addEventListener("click", clearLibraryPlace);
if ("IntersectionObserver" in window) {
  new IntersectionObserver((seen) => {
    if (seen.some((e) => e.isIntersecting)) showMoreLibrary();
  }, { root: $("view-library"), rootMargin: "400px" }).observe($("lib-more"));
}

let libTyping = null;
$("lib-search").addEventListener("input", () => {
  clearTimeout(libTyping);
  libTyping = setTimeout(() => { renderLibrary(true); $("view-library").scrollTop = 0; }, 140);
});
["lib-type", "lib-depth", "lib-sort"].forEach((id) =>
  $(id).addEventListener("change", () => { renderLibrary(true); $("view-library").scrollTop = 0; }));

/* -------------------------------------------------------------- subject */

async function openSubject(slug, pageName) {
  showView("subject", "#/subject/" + encodeURIComponent(slug)
    + (pageName ? "/" + encodeURIComponent(pageName) : ""));
  $("subject-body").innerHTML = '<div class="empty">Loading…</div>';
  try {
    state.subject = await api("/api/subject/" + encodeURIComponent(slug));
  } catch (e) {
    $("subject-body").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    return;
  }
  // A named tab in the URL wins; otherwise the first one.
  const wanted = state.subject.pages.findIndex((p) => p.name === pageName);
  state.page = wanted >= 0 ? wanted : 0;
  renderSubject();
}

function renderSubject() {
  const d = state.subject;
  if (!d) return;
  const body = $("subject-body");
  body.innerHTML = "";
  const identity = d.subject.identity || {};

  const head = el("div", "dosshead");

  // A portrait if one has been downloaded, a flag for a country. Only pictures
  // already on disk are offered by the API, so this never renders a broken one.
  const picture = (d.images || []).find((i) => i.kind === "portrait")
    || (d.images || []).find((i) => i.kind === "flag")
    || (d.images || []).find((i) => i.kind === "logo");
  if (picture) {
    const frame = el("div", "portrait");
    const img = document.createElement("img");
    img.src = picture.url;
    img.alt = `${d.subject.name} — ${picture.label || picture.kind}`;
    img.title = picture.credit || "";
    img.loading = "lazy";
    frame.appendChild(img);
    head.appendChild(frame);
  }

  const left = el("div");
  left.style.flex = "1";
  left.appendChild(el("h2", null, d.subject.name));
  left.appendChild(el("div", "muted small", identity.description || ""));
  const meta = el("div", "meta");
  meta.style.marginTop = "8px";
  meta.appendChild(el("span", "tag type", d.entity_type));
  meta.appendChild(el("span", "tag", `${d.counts.sources} sources`));
  meta.appendChild(el("span", "tag", `${d.counts.claims} claims`));
  meta.appendChild(el("span", "tag", `${d.counts.timeline} events`));
  meta.appendChild(el("span", "tag", `${d.counts.quotes} quotes`));
  if (d.subject.depth === "deep") meta.appendChild(el("span", "tag deep", "deep dived"));
  left.appendChild(meta);
  head.appendChild(left);

  const actions = el("div", "row");
  const deepen = el("button", "primary", "Deep dive");
  deepen.addEventListener("click", async () => {
    deepen.disabled = true; deepen.textContent = "queued";
    await api("/api/research", { method: "POST", body: JSON.stringify({
      name: d.subject.name, entity_type: d.entity_type, phase: "deep" }) });
    refreshQueue();
  });
  const refresh = el("button", "ghost", "Update");
  refresh.addEventListener("click", async () => {
    refresh.disabled = true; refresh.textContent = "queued";
    await api("/api/research", { method: "POST", body: JSON.stringify({
      name: d.subject.name, entity_type: d.entity_type, phase: "quick" }) });
    refreshQueue();
  });
  const pictures = el("button", "ghost", "Get pictures");
  pictures.addEventListener("click", async () => {
    pictures.disabled = true; pictures.textContent = "queued";
    await api("/api/research", { method: "POST", body: JSON.stringify({
      name: d.subject.name, entity_type: d.entity_type, phase: "images" }) });
    refreshQueue();
  });

  // Narration is a CPU voice on a long script, so it takes a minute or two.
  // The button says so rather than looking hung.
  const listen = el("button", "ghost", "Listen");
  listen.title = "Read this dossier out loud, in date order";
  listen.addEventListener("click", async () => {
    listen.disabled = true; listen.textContent = "reading it…";
    try {
      const r = await api(`/api/subject/${encodeURIComponent(d.subject.slug)}/tour`,
        { method: "POST", body: "{}" });
      if (r.ready) {
        playAudio(r.url, `${d.subject.name} — a tour of the record`);
        listen.textContent = "Listen";
      } else {
        // Reading a dossier aloud is over a minute of CPU, so it goes through
        // the queue like any other slow job rather than holding the page.
        listen.textContent = "queued to read";
        refreshQueue();
      }
    } catch (e) {
      listen.textContent = "no voice";
      ForgeDialog.alert(e.message);
    } finally { listen.disabled = false; }
  });

  // Everything added to Dossier since this subject was researched, merged
  // into what is already held. Runs without the queue, then reloads the page.
  const newInfo = el("button", "ghost", "Get new info");
  newInfo.title = "Adds five years of news and a fresh copy of the full article. "
    + "Nothing already stored is removed.";
  newInfo.addEventListener("click", async () => {
    const slug = d.subject.slug;
    const pageName = (d.pages[state.page] || {}).name || "";
    newInfo.disabled = true; newInfo.textContent = "getting new info…";
    try {
      await api(`/api/subject/${encodeURIComponent(slug)}/new-info`,
        { method: "POST", body: "{}" });
    } catch (e) {
      ForgeDialog.alert(e.message);
      newInfo.disabled = false; newInfo.textContent = "Get new info";
      return;
    }
    // Five years of news takes minutes, so progress is read through a
    // watcher: it rests while hidden and waits longer while the server is away.
    watch("newInfoWatch", null, 0, false);
    watch("newInfoWatch", async () => {
      let h;
      try { h = await api("/api/history"); } catch (e) { return false; }
      if (h.running) return true;
      watch("newInfoWatch", null, 0, false);
      if (state.subject && state.subject.subject.slug === slug) {
        state.flash = `Added ${h.events_added} news items`
          + (h.articles_added ? " and a fresh copy of the article" : "")
          + ". Everything already held was kept.";
        await openSubject(slug, pageName);
      }
      return true;
    }, 1500, true);
  });

  actions.append(deepen, refresh, newInfo, pictures, listen);
  head.appendChild(actions);
  body.appendChild(head);
  if (state.flash) {
    body.appendChild(el("div", "hint", state.flash));
    state.flash = "";
  }

  const tabs = el("div", "pagetabs");
  d.pages.forEach((page, i) => {
    const b = el("button", i === state.page ? "on" : "", page.title);
    b.addEventListener("click", () => {
      state.page = i;
      const slug = d.subject.slug;
      history.replaceState(null, "",
        "#/subject/" + encodeURIComponent(slug) + "/" + encodeURIComponent(page.name));
      renderSubject();
    });
    tabs.appendChild(b);
  });
  body.appendChild(tabs);

  const page = d.pages[state.page];
  if (page.blurb) body.appendChild(el("div", "muted small", page.blurb));

  const needsSlider = page.blocks.some((b) => b.kind === "claims" || b.kind === "sources");
  if (needsSlider) body.appendChild(relevanceSlider());

  page.blocks.forEach((block) => body.appendChild(renderBlock(block, d)));
  body.appendChild(askBox(d));
}

function relevanceSlider() {
  const wrap = el("div", "card");
  const row = el("div", "slider");
  row.appendChild(el("span", null, "Show only what scores at least"));
  const input = document.createElement("input");
  input.type = "range"; input.min = "0"; input.max = "100";
  input.value = String(Math.round(state.minRelevance * 100));
  const out = el("b", null, state.minRelevance.toFixed(2));
  input.addEventListener("input", () => {
    state.minRelevance = Number(input.value) / 100;
    out.textContent = state.minRelevance.toFixed(2);
    renderSubject();
  });
  row.append(input, out);
  row.appendChild(el("span", null, "on relevance to this subject"));
  wrap.appendChild(row);
  return wrap;
}

function renderBlock(block, d) {
  const card = el("div", "card");
  switch (block.kind) {
    case "facts": {
      if (!block.rows.length) return el("span");
      const dl = el("dl", "facts");
      block.rows.forEach((r) => {
        dl.appendChild(el("dt", null, r.label));
        dl.appendChild(el("dd", null, r.value));
      });
      card.appendChild(dl);
      break;
    }
    case "timeline": {
      card.appendChild(el("h3", null, `Timeline · ${block.events.length} events`));
      if (!block.events.length) { card.appendChild(el("div", "muted small", "No dated events.")); break; }
      const list = el("div", "timeline");
      block.events.forEach((e) => {
        const row = el("div", "event " + (e.kind || ""));
        row.innerHTML =
          `<span class="when">${esc(e.date)}${e.end ? "–" + esc(e.end) : ""}</span>` +
          `<span class="what">${esc(e.title)}</span>` +
          (e.detail && !e.detail.includes(e.title) && e.detail !== e.title
            ? `<div class="who">${esc(e.detail)}</div>` : "");
        if (e.url) {
          const a = el("a", null, " source");
          a.href = e.url; a.target = "_blank"; a.className = "small muted";
          row.appendChild(a);
        }
        list.appendChild(row);
      });
      card.appendChild(list);
      break;
    }
    case "claims": {
      const claims = block.claims.filter((c) => (c.relevance ?? 1) >= state.minRelevance);
      card.appendChild(el("h3", null, `Claims · ${claims.length}`));
      if (!claims.length) {
        card.appendChild(el("div", "muted small",
          block.claims.length
            ? "Everything here scores below the relevance floor you set."
            : "No claims yet — a deep dive reads the articles and extracts them."));
        break;
      }
      claims.forEach((c) => {
        const node = el("div", "claim");
        const text = el("div", "text");
        text.appendChild(withNameLinks(c.text, state.subject?.subject?.slug));
        node.appendChild(text);
        const ev = (c.evidence || [])[0];
        if (ev && ev.span) node.appendChild(el("div", "span", "“" + ev.span + "”"));
        (c.conflicts || []).forEach((x) => node.appendChild(el("div", "conflict", "⚠ " + x)));
        const foot = el("div", "foot");
        foot.appendChild(el("span", "badge " + c.confidence, c.confidence));
        foot.appendChild(el("span", "tag", c.independent_sources + " independent"));
        foot.appendChild(el("span", "tag", "relevance " + (c.relevance ?? 0).toFixed(2)));
        (c.evidence || []).slice(0, 4).forEach((e) => {
          if (!e.url) return;
          const a = el("a", "tag", e.domain || "source");
          a.href = e.url; a.target = "_blank";
          foot.appendChild(a);
        });
        node.appendChild(foot);
        card.appendChild(node);
      });
      break;
    }
    case "quotes": {
      card.appendChild(el("h3", null, `Quotes · ${block.quotes.length}`));
      if (!block.quotes.length) { card.appendChild(el("div", "muted small", "No quotes held.")); break; }
      block.quotes.forEach((q) => {
        const node = el("div", "quote" + (q.sourced ? "" : " uncited"));
        node.appendChild(el("div", "text", "“" + q.text + "”"));
        const cite = el("div", "cite",
          q.citation || "no citation recorded — treat as unverified");
        node.appendChild(cite);
        card.appendChild(node);
      });
      break;
    }
    case "sources": {
      const rows = block.sources.filter((s) => s.relevance >= state.minRelevance);
      card.appendChild(el("h3", null, `Sources · ${rows.length} of ${block.sources.length}`));
      const table = el("table", "sources");
      table.innerHTML = "<thead><tr><th>relevance</th><th>source</th><th>tier</th>" +
        "<th>found via</th><th>date</th><th>words</th></tr></thead>";
      const tbody = el("tbody");
      rows.forEach((s) => {
        const tr = el("tr");
        tr.innerHTML =
          `<td><span class="relbar"><i style="width:${Math.round(s.relevance * 100)}%"></i></span>${s.relevance.toFixed(2)}</td>` +
          `<td><a href="${esc(s.url)}" target="_blank">${esc(s.title || s.url)}</a>` +
          `<div class="muted small">${esc(s.domain)}</div></td>` +
          `<td>${esc(s.tier)}</td><td>${esc(s.origin)}</td>` +
          `<td>${esc(s.published || "")}</td><td>${s.words}</td>`;
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      card.appendChild(table);
      break;
    }
    case "relations": {
      card.appendChild(el("h3", null, `Connections · ${block.relations.length}`));
      if (!block.relations.length) { card.appendChild(el("div", "muted small", "None recorded.")); break; }
      const list = el("div", "row");
      block.relations.forEach((r) => {
        const tag = el("span", "tag", `${r.relation}: ${r.target}`);
        const known = state.library.find((x) =>
          x.name.toLowerCase() === (r.target || "").toLowerCase());
        if (known) {
          tag.className = "tag type";
          tag.style.cursor = "pointer";
          tag.addEventListener("click", () => openSubject(known.slug));
        }
        list.appendChild(tag);
      });
      card.appendChild(list);
      break;
    }
    case "notes": {
      card.appendChild(el("h3", null, "Your notes"));
      const area = el("textarea", "notes");
      area.value = block.markdown || "";
      area.placeholder = "Your reading of this subject: opinions, plans, questions, "
        + "things to check. Nothing automatic ever writes here.";
      const save = el("button", "primary", "Save notes");
      const said = el("span", "muted small", block.updated ? "last saved " + block.updated : "");
      save.addEventListener("click", async () => {
        save.disabled = true;
        const r = await api(`/api/subject/${state.subject.subject.slug}/notes`,
          { method: "POST", body: JSON.stringify({ markdown: area.value }) });
        said.textContent = "saved " + r.updated;
        save.disabled = false;
      });
      const actions = el("div", "row");
      actions.append(save, said);
      card.append(area, actions);
      break;
    }
    case "grouped_facts": {
      if (!block.panels || !block.panels.length) return el("span");
      card.appendChild(el("h3", null, "What is known"));
      block.panels.forEach((panel) => {
        card.appendChild(el("h4", "factgroup", panel.label));
        const dl = el("dl", "facts");
        panel.rows.forEach((r) => {
          dl.appendChild(el("dt", null, r.label));
          dl.appendChild(el("dd", null, r.value));
        });
        card.appendChild(dl);
      });
      break;
    }
    case "seats": {
      if (!block.seats) return el("span");
      const share = block.share || 0;
      card.appendChild(el("h3", null, "Seats"));
      const head = el("div", "seatline");
      head.innerHTML = `<b>${block.seats}</b> of <b>${block.total || "?"}</b>` +
        (block.body ? ` in the ${esc(block.body)}` : "") +
        (share ? ` — <b>${(share * 100).toFixed(1)}%</b>` : "");
      card.appendChild(head);
      if (share) {
        // A bare seat count says little; the share is the political fact.
        const bar = el("div", "seatbar");
        const fill = el("i");
        fill.style.width = Math.min(100, share * 100).toFixed(1) + "%";
        if (share >= 0.5) fill.classList.add("majority");
        bar.appendChild(fill);
        card.appendChild(bar);
        card.appendChild(el("div", "muted small",
          share >= 0.5 ? "An outright majority of the chamber."
            : share >= 0.33 ? "Large enough to lead a coalition."
            : share >= 0.1 ? "A substantial bloc." : "A minor presence."));
      }
      // Parties sit in more than one chamber; show the rest underneath.
      (block.chambers || []).slice(1).forEach((c) => {
        const row = el("div", "muted small");
        row.textContent = `${c.seats} of ${c.total || "?"} in the ${c.body}` +
          (c.share ? ` — ${(c.share * 100).toFixed(1)}%` : "");
        card.appendChild(row);
      });
      if (block.url) {
        const a = el("a", "small muted", "chamber on Wikidata");
        a.href = block.url; a.target = "_blank";
        card.appendChild(a);
      }
      break;
    }
    case "article": {
      if (!block.sections || !block.sections.length) return el("span");
      card.classList.add("articleblock");
      card.appendChild(el("h3", null,
        `${block.title} · ${Number(block.words || 0).toLocaleString()} words · ${block.sections.length} sections`));
      const meta = el("div", "small muted", `From Wikipedia, fetched ${(block.fetched || "").slice(0, 10)} · `);
      const original = el("a", null, "read the original");
      original.href = block.url; original.target = "_blank";
      meta.appendChild(original);
      card.appendChild(meta);
      block.sections.forEach((section, i) => {
        const box = el("details", "lvl" + Math.min(section.level || 2, 4));
        if (i === 0) box.open = true;
        const summary = el("summary", null, section.heading);
        summary.appendChild(el("span", "muted small",
          ` · ${section.text.split(/\s+/).length} words`));
        box.appendChild(summary);
        section.text.split("\n").forEach((para) => {
          if (para.trim()) box.appendChild(el("p", null, para));
        });
        card.appendChild(box);
      });
      break;
    }
    case "news": {
      if (!block.total) return el("span");
      card.classList.add("newsblock");
      card.appendChild(el("h3", null, `News · ${block.total.toLocaleString()} items`));
      const years = el("div", "row");
      Object.entries(block.by_year || {}).forEach(([year, count]) =>
        years.appendChild(el("span", "tag", `${year}: ${count}`)));
      card.appendChild(years);
      const filter = el("input", "newsfilter");
      filter.placeholder = "Filter these items, e.g. election, sanctions, a name…";
      card.appendChild(filter);
      const body = el("div");
      card.appendChild(body);
      const item = (e) => {
        const row = el("div", "event " + (e.kind || ""));
        row.appendChild(el("span", "when", e.date));
        row.appendChild(el("span", "what", e.title));
        const who = el("div", "who");
        const bits = e.kind === "news"
          ? [e.category, (e.topics || []).join(" › ")]
          : [e.detail];
        const said = bits.filter(Boolean).join(" · ");
        if (said) who.append(said + " ");
        const cites = (e.citations && e.citations.length)
          ? e.citations : (e.url ? [{ outlet: "source", url: e.url }] : []);
        cites.forEach((c) => {
          const a = el("a", "tag", c.outlet || "source");
          a.href = c.url; a.target = "_blank";
          who.appendChild(a);
        });
        row.appendChild(who);
        return row;
      };
      const draw = () => {
        const needle = filter.value.trim().toLowerCase();
        body.innerHTML = "";
        block.groups.forEach((group) => {
          const events = needle
            ? group.events.filter((e) =>
              `${e.title} ${e.detail || ""}`.toLowerCase().includes(needle))
            : group.events;
          const box = el("details");
          box.open = group.label === "Past year" || !!needle;
          box.appendChild(el("summary", null, `${group.label} · ${events.length}`));
          const list = el("div", "timeline");
          box.appendChild(list);
          // Thousands of rows are only built for a group someone opens.
          const fill = () => {
            if (!box.open || list.childElementCount) return;
            events.forEach((e) => list.appendChild(item(e)));
          };
          box.addEventListener("toggle", fill);
          fill();
          body.appendChild(box);
        });
      };
      let pending = null;
      filter.addEventListener("input", () => {
        clearTimeout(pending);
        pending = setTimeout(draw, 200);
      });
      draw();
      break;
    }
    case "pictures": {
      const shots = d.images || [];
      card.appendChild(el("h3", null, `Pictures · ${shots.length}`));
      if (!shots.length) {
        card.appendChild(el("div", "muted small", "No pictures held for this subject."));
        break;
      }
      const grid = el("div", "picturegrid");
      shots.forEach((p) => {
        const fig = el("figure");
        const img = document.createElement("img");
        img.src = p.url;
        img.loading = "lazy";
        img.alt = `${d.subject.name} — ${p.label || p.kind}`;
        fig.appendChild(img);
        fig.appendChild(el("figcaption", "muted small",
          [p.label || p.kind, p.credit].filter(Boolean).join(" · ")));
        grid.appendChild(fig);
      });
      card.appendChild(grid);
      break;
    }
    case "source_texts": {
      card.classList.add("textsblock");
      card.appendChild(el("h3", null, `Sources and their saved text · ${block.sources.length}`));
      if (!block.sources.length) {
        card.appendChild(el("div", "muted small", "No sources held."));
        break;
      }
      const status = el("div", "muted small", "Checking which sources have their text saved…");
      const list = el("div");
      card.append(status, list);
      const slug = encodeURIComponent(block.slug);
      // Only the list of what is saved comes now; each text loads when opened.
      api(`/api/subject/${slug}/texts`).then(({ texts }) => {
        const held = block.sources.filter((s) => texts[s.source_id]).length;
        status.textContent = `${held} of ${block.sources.length} have their text saved here, `
          + "so they stay readable even if the original link stops working.";
        block.sources.forEach((s) => {
          const words = texts[s.source_id];
          const box = el("details");
          const summary = el("summary", null, (s.title || s.url) + " ");
          summary.appendChild(el("span", "muted small", [
            s.domain, s.tier, s.published,
            `relevance ${(s.relevance ?? 0).toFixed(2)}`,
            words ? `${words.toLocaleString()} words saved` : "no saved text",
          ].filter(Boolean).join(" · ")));
          box.appendChild(summary);
          if (s.url) {
            const original = el("a", "small muted", "open the original");
            original.href = s.url; original.target = "_blank";
            box.appendChild(original);
          }
          if (words) {
            box.addEventListener("toggle", async () => {
              if (!box.open || box.dataset.loaded) return;
              box.dataset.loaded = "1";
              try {
                const r = await api(`/api/subject/${slug}/text/${encodeURIComponent(s.source_id)}`);
                r.text.split(/\n+/).forEach((para) => {
                  if (para.trim()) box.appendChild(el("p", null, para));
                });
              } catch (e) {
                box.appendChild(el("div", "muted small", "Could not load the saved text: " + e.message));
              }
            });
          }
          list.appendChild(box);
        });
      }).catch((e) => { status.textContent = "Could not list the saved text: " + e.message; });
      break;
    }
    case "prose":
      card.appendChild(el("div", null, block.text));
      break;
    case "hint":
      return el("div", "hint", block.text);
    default:
      card.appendChild(el("div", "muted small", "Unknown block: " + block.kind));
  }
  return card;
}

function askBox(d) {
  const card = el("div", "card");
  card.appendChild(el("h3", null, "Ask about this subject"));
  const row = el("div", "row");
  const input = el("input");
  input.placeholder = "e.g. what did they say about the refugee policy?";
  input.style.flex = "1";
  const go = el("button", "primary", "Ask");
  const aloud = el("button", "ghost", "Ask aloud");
  aloud.title = "Answer it and read the answer out as an mp3";
  row.append(input, go, aloud);
  card.appendChild(row);
  card.appendChild(el("div", "hint",
    "Answers come only from what is stored for this subject, and every sentence "
    + "must cite a stored item. Anything uncited is stripped before you see it, "
    + "so 'Not in the sources' is a real answer."));
  const out = el("div");
  card.appendChild(out);

  const ask = async () => {
    const question = input.value.trim();
    if (!question) return;
    out.innerHTML = '<div class="muted small">Thinking…</div>';
    go.disabled = true;
    try {
      const r = await api(`/api/subject/${d.subject.slug}/ask`,
        { method: "POST", body: JSON.stringify({ question }) });
      out.innerHTML = "";
      if (r.error) { out.appendChild(el("div", "muted small", r.error)); return; }
      out.appendChild(el("div", "answer", r.answer));
      if (r.note) out.appendChild(el("div", "hint", r.note));
      if (r.used && r.used.length) {
        const cited = el("div", "cited");
        cited.appendChild(el("b", null, "Drawn from:"));
        const ul = el("ul");
        r.used.forEach((u) => {
          const li = el("li");
          li.innerHTML = `[${u.n}] ${esc(u.text.slice(0, 190))}` +
            (u.url ? ` <a href="${esc(u.url)}" target="_blank">source</a>` : "");
          ul.appendChild(li);
        });
        cited.appendChild(ul);
        out.appendChild(cited);
      }
      if (r.dropped) out.appendChild(el("div", "muted small",
        `${r.dropped} uncited sentence${r.dropped > 1 ? "s were" : " was"} removed.`));
    } catch (e) {
      out.innerHTML = `<div class="muted small">${esc(e.message)}</div>`;
    } finally { go.disabled = false; }
  };
  // The spoken answer goes through the same gate as the written one: ask.py has
  // already deleted any sentence that cites nothing, so nothing is said that
  // would not have been shown.
  const askAloud = async () => {
    const question = input.value.trim();
    if (!question) return;
    out.innerHTML = '<div class="muted small">Thinking, then reading it out…</div>';
    aloud.disabled = true;
    try {
      const r = await api(`/api/subject/${d.subject.slug}/ask-aloud`,
        { method: "POST", body: JSON.stringify({ question }) });
      out.innerHTML = "";
      out.appendChild(el("div", "answer", r.answer));
      playAudio(r.url, `${d.subject.name} — ${question}`);
    } catch (e) {
      out.innerHTML = `<div class="muted small">${esc(e.message)}</div>`;
    } finally { aloud.disabled = false; }
  };

  go.addEventListener("click", ask);
  aloud.addEventListener("click", askAloud);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") ask(); });
  return card;
}

/* ----------------------------------------------------------------- jobs */

async function queueRecipe(name, button) {
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "asking Wikidata…";
  try {
    const r = await api("/api/queue/recipe", { method: "POST", body: JSON.stringify({
      recipe: name,
      limit: Number($("recipe-limit").value) || 100,
      phase: $("recipe-phase").value,
    }) });
    // Say what actually happened. This used to report every name Wikidata
    // returned, so a second press claimed to queue 148 while adding none.
    button.textContent = r.queued
      ? `queued ${r.queued}`
      : (r.already_queued ? "already queued" : "already held");
    showView("jobs");
    refreshQueue();
  } catch (e) {
    button.textContent = "failed";
    ForgeDialog.alert("Seeding failed: " + e.message);
  } finally {
    setTimeout(() => { button.disabled = false; button.textContent = original; }, 2500);
  }
}

/* Job watchers: while the queue or the history job runs, the page re-reads
   it on a beat. Hidden, a watcher rests; while the server does not answer,
   its wait stretches to 30 s and the page says so; it ends with the job. */
function watch(key, fn, ms, on) {
  if (on && !state[key]) {
    state[key] = ForgeIdle.poll(fn, ms, { backoff: 2, maxMs: 30000 });
  } else if (!on && state[key]) {
    state[key].stop();
    state[key] = null;
  }
}

async function refreshQueue() {
  let q;
  try { q = await api("/api/queue"); } catch (e) {
    if (state.queueWatch) $("q-summary").textContent = "Dossier's server is not answering; trying again shortly";
    return false;
  }
  const c = q.counts;
  const total = c.queued + c.running + c.done + c.failed;
  const finished = c.done + c.failed;

  const pill = $("pill-queue");
  if (c.queued || c.running) {
    pill.hidden = false;
    pill.className = "pill busy";
    pill.textContent = q.paused ? `paused · ${c.queued} waiting`
      : `${finished}/${total}` + (q.current ? ` · ${q.current.name}` : "");
  } else { pill.hidden = true; }

  $("q-bar").style.width = total ? (finished / total * 100).toFixed(1) + "%" : "0%";
  const eta = q.eta_seconds
    ? ` · about ${q.eta_seconds > 5400
        ? Math.round(q.eta_seconds / 3600) + " hours"
        : Math.round(q.eta_seconds / 60) + " min"} left`
    : "";
  $("q-summary").textContent = total
    ? `${c.done} done · ${c.failed} failed${
        c.skipped ? ` · ${c.skipped} skipped as already held` : ""} · ${c.queued} waiting${
        q.average_seconds ? ` · averaging ${q.average_seconds}s each` : ""}${eta}`
    : "idle";

  renderQueues(q);

  setLog($("q-log"), (q.log || []).join("\n") || "nothing running");

  const errors = q.errors.length
    ? q.errors.map((e) => `<div>${esc(e.name)}: <span class="muted">${esc(e.error)}</span></div>`).join("")
    : "none";
  if ($("q-errors").innerHTML !== errors) $("q-errors").innerHTML = errors;

  // Redrawn only when a job actually changed, and at the same scroll
  // position: every 4 s the list used to be rebuilt and jumped to the top.
  const list = $("q-jobs");
  const jobsSig = JSON.stringify(q.jobs.map((j) =>
    [j.slug, j.status, j.phase, j.seconds, j.note]));
  if (jobsSig !== state.jobsSig) {
    state.jobsSig = jobsSig;
    const keep = list.scrollTop;
    list.replaceChildren(...q.jobs.map(jobRow));
    list.scrollTop = keep;
  }

  watch("queueWatch", refreshQueue, 4000, Boolean(c.running || (q.running && c.queued)));
  // The library and map are re-read when a subject has finished, not on
  // every beat: re-reading them meant redrawing 2,450 cards every 4 s.
  if (state.queueDone !== null && c.done !== state.queueDone) refreshLibrary();
  state.queueDone = c.done;
  return true;
}

function jobRow(j) {
  const row = el("div", "jobrow");
  row.appendChild(el("span", "st " + j.status, j.status));
  const name = el("span", null, j.name);
  name.style.flex = "1";
  row.appendChild(name);
  row.appendChild(el("span", "tag", j.phase));
  if (j.prominence) row.appendChild(el("span", "tag", j.prominence + " wikis"));
  if (j.status === "skipped" && j.note) row.appendChild(el("span", "muted small", j.note));
  if (j.seconds) row.appendChild(el("span", "muted small", j.seconds + "s"));
  if (j.status === "done") {
    row.style.cursor = "pointer";
    row.addEventListener("click", () => openSubject(j.slug));
  }
  return row;
}

/* A log that follows new lines only while you are at its end: scrolled up to
   read something, it stays where you put it. */
function setLog(node, text) {
  if (node.textContent === text) return;
  const atEnd = node.scrollHeight - node.scrollTop - node.clientHeight < 24;
  node.textContent = text;
  if (atEnd) node.scrollTop = node.scrollHeight;
}

/* One queue is active and the workers only pull from that one, so this is a
   picker rather than a set of toggles. */
function renderQueues(q) {
  const list = $("queue-list");
  list.innerHTML = "";
  (q.queues || []).forEach((entry) => {
    const row = el("div", "qrow" + (entry.active ? " active" : ""));
    row.appendChild(el("span", "qname", entry.name));

    const bits = [];
    if (entry.waiting) bits.push(entry.waiting + " waiting");
    if (entry.counts.done) bits.push(entry.counts.done + " done");
    if (entry.counts.skipped) bits.push(entry.counts.skipped + " skipped");
    if (entry.paused) bits.push("paused");
    row.appendChild(el("span", "qcount", bits.join(" · ") || "empty"));

    if (entry.active) {
      const rename = el("button", "ghost", "Rename");
      rename.addEventListener("click", async (e) => {
        e.stopPropagation();
        const name = await ForgeDialog.prompt("Rename this queue", entry.name);
        if (!name) return;
        await api(`/api/queues/${entry.id}/rename`, {
          method: "POST", body: JSON.stringify({ name }) });
        refreshQueue();
      });
      row.appendChild(rename);
    }
    if ((q.queues || []).length > 1) {
      const drop = el("button", "ghost", "Delete");
      drop.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!await ForgeDialog.confirm(`Delete the queue "${entry.name}" and its ${entry.total} jobs?`)) return;
        await api(`/api/queues/${entry.id}`, { method: "DELETE" });
        refreshQueue();
      });
      row.appendChild(drop);
    }

    row.addEventListener("click", async () => {
      if (entry.active) return;
      await api(`/api/queues/${entry.id}/activate`, { method: "POST", body: "{}" });
      refreshQueue();
    });
    list.appendChild(row);
  });

  $("queue-redo").checked = !!(q.active_queue && q.active_queue.redo_held);
}

$("queue-new").addEventListener("click", async () => {
  const field = $("queue-new-name");
  const name = field.value.trim();
  if (!name) { field.focus(); return; }
  await api("/api/queues", { method: "POST", body: JSON.stringify({ name }) });
  field.value = "";
  refreshQueue();
});

$("queue-redo").addEventListener("change", async (e) => {
  const q = await api("/api/queue");
  if (!q.active_queue) return;
  await api(`/api/queues/${q.active_queue.id}/redo`, {
    method: "POST", body: JSON.stringify({ redo: e.target.checked }) });
  refreshQueue();
});

/* A queue button stays disabled until its answer is back: three quick clicks
   on "deepen" used to queue 75 deep dives instead of 25. */
function postOnce(button, path, body) {
  button.addEventListener("click", async () => {
    if (button.disabled) return;
    button.disabled = true;
    try { await api(path, { method: "POST", body }); }
    catch (e) { ForgeDialog.alert(e.message); }
    finally { button.disabled = false; }
    refreshQueue();
  });
}
["start", "pause", "stop", "clear"].forEach((action) =>
  postOnce($("q-" + action), "/api/queue/" + action, "{}"));
postOnce($("q-deepen"), "/api/queue/deepen", JSON.stringify({ limit: 25 }));

/* ------------------------------------------------------------ audio */

/* One player, reused. A second recording replaces the first rather than
   stacking players nobody stops. */
function playAudio(url, label) {
  let bar = document.getElementById("audiobar");
  if (!bar) {
    bar = el("div", null);
    bar.id = "audiobar";
    document.body.appendChild(bar);
  }
  bar.innerHTML = "";
  const title = el("div", "small", label || "Playing");
  const audio = document.createElement("audio");
  audio.controls = true;
  audio.autoplay = true;
  audio.src = url;

  const save = el("a", "tag", "Save the mp3");
  save.href = url;
  save.setAttribute("download", "");

  const close = el("button", "ghost", "Close");
  close.addEventListener("click", () => bar.remove());

  const row = el("div", "row");
  row.append(audio, save, close);
  bar.append(title, row);
}

/* ------------------------------------------------- names as links */

/* A person named inside someone else's dossier usually has a dossier of their
   own. One regex is built from every held name, longest first so that a full
   name wins over the surname inside it, and reused for every piece of prose. */

const nameIndex = { pattern: null, bySlug: new Map(), builtFrom: 0 };

function buildNameIndex() {
  const rows = state.library || [];
  if (nameIndex.pattern && nameIndex.builtFrom === rows.length) return;
  nameIndex.builtFrom = rows.length;
  nameIndex.bySlug = new Map();

  const names = [];
  rows.forEach((row) => {
    // Very short names ("Q", "US") match inside ordinary words far too often
    // to be worth linking.
    if (!row.name || row.name.length < 5) return;
    names.push(row.name);
    nameIndex.bySlug.set(row.name.toLowerCase(), row.slug);
  });
  if (!names.length) { nameIndex.pattern = null; return; }

  names.sort((a, b) => b.length - a.length);
  const escaped = names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  nameIndex.pattern = new RegExp(`\\b(${escaped.join("|")})\\b`, "gi");
}

/** Text with every known subject name turned into a link. Returns a node. */
function withNameLinks(text, exceptSlug) {
  buildNameIndex();
  const out = document.createDocumentFragment();
  if (!text) return out;
  if (!nameIndex.pattern) { out.appendChild(document.createTextNode(text)); return out; }

  nameIndex.pattern.lastIndex = 0;
  let at = 0, match;
  while ((match = nameIndex.pattern.exec(text)) !== null) {
    const slug = nameIndex.bySlug.get(match[0].toLowerCase());
    // Linking a dossier to itself is noise, not navigation.
    if (!slug || slug === exceptSlug) continue;
    if (match.index > at) {
      out.appendChild(document.createTextNode(text.slice(at, match.index)));
    }
    const link = el("a", "namelink", match[0]);
    link.title = "Open this dossier";
    link.addEventListener("click", (e) => { e.stopPropagation(); openSubject(slug); });
    out.appendChild(link);
    at = match.index + match[0].length;
  }
  if (at < text.length) out.appendChild(document.createTextNode(text.slice(at)));
  return out;
}

/* ------------------------------------------------------- connections */

/* The mind map is inline SVG with a spring layout run right here, the same
   no-library approach as the world map. The backend does the graph arithmetic
   (paths, neighbourhoods) and never calls a model for any of it. */

const graphState = { data: null, view: { x: 0, y: 0, k: 1 } };

function layout(nodes, edges, width, height) {
  // Spring layout: edges pull, every pair pushes, the centre stays put. A few
  // hundred iterations is plenty for the ~90 nodes a neighbourhood holds.
  const index = new Map(nodes.map((n, i) => [n.key, i]));
  const cx = width / 2, cy = height / 2;
  nodes.forEach((n, i) => {
    const ring = (n.hops || 0) + 1;
    const angle = (i / nodes.length) * Math.PI * 2;
    n.x = cx + Math.cos(angle) * ring * 90;
    n.y = cy + Math.sin(angle) * ring * 90;
    n.vx = 0; n.vy = 0;
  });
  const links = edges
    .map((e) => [index.get(e.from), index.get(e.to)])
    .filter(([a, b]) => a !== undefined && b !== undefined);

  for (let step = 0; step < 300; step++) {
    const cool = 1 - step / 300;
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = b.x - a.x, dy = b.y - a.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { d2 = 1; dx = Math.random() - 0.5; dy = Math.random() - 0.5; }
        const force = 5200 / d2;
        const d = Math.sqrt(d2);
        a.vx -= (dx / d) * force; a.vy -= (dy / d) * force;
        b.vx += (dx / d) * force; b.vy += (dy / d) * force;
      }
    }
    links.forEach(([ai, bi]) => {
      const a = nodes[ai], b = nodes[bi];
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const pull = (d - 110) * 0.02;
      a.vx += (dx / d) * pull; a.vy += (dy / d) * pull;
      b.vx -= (dx / d) * pull; b.vy -= (dy / d) * pull;
    });
    nodes.forEach((n) => {
      // Pull everything gently homeward so detached pieces do not drift off.
      n.vx += (cx - n.x) * 0.002;
      n.vy += (cy - n.y) * 0.002;
      if (n.hops === 0) { n.vx = 0; n.vy = 0; n.x = cx; n.y = cy; return; }
      n.x += Math.max(-25, Math.min(25, n.vx * cool));
      n.y += Math.max(-25, Math.min(25, n.vy * cool));
      n.vx *= 0.55; n.vy *= 0.55;
    });
  }
  return nodes;
}

function renderGraph(data) {
  graphState.data = data;
  const box = $("graph-canvas");
  box.innerHTML = "";
  if (!data.nodes.length) {
    box.innerHTML = '<div class="muted small pad">Nothing connects to that yet.</div>';
    return;
  }

  const width = box.clientWidth || 700, height = box.clientHeight || 520;
  const nodes = layout(data.nodes.slice(), data.edges, width, height);
  const at = new Map(nodes.map((n) => [n.key, n]));

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
  svg.appendChild(g);

  data.edges.forEach((e) => {
    const a = at.get(e.from), b = at.get(e.to);
    if (!a || !b) return;
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
    line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
    line.setAttribute("class", "gedge");
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = `${a.name} — ${e.relation} — ${b.name}`;
    line.appendChild(title);
    g.appendChild(line);
  });

  nodes.forEach((n) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", "g");
    node.setAttribute("class",
      "gnode " + (n.hops === 0 ? "centre" : n.held ? "held" : "outside"));
    node.setAttribute("transform", `translate(${n.x},${n.y})`);

    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("r", Math.min(11, 4 + Math.sqrt(n.degree || 1)));
    node.appendChild(circle);

    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", 12); label.setAttribute("y", 3.5);
    label.textContent = n.name.length > 28 ? n.name.slice(0, 27) + "…" : n.name;
    node.appendChild(label);

    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = `${n.name} · ${n.degree} link${n.degree === 1 ? "" : "s"}`
      + (n.held ? "" : " · no dossier yet");
    node.appendChild(title);

    node.addEventListener("click", () => {
      if (n.held && n.hops !== 0) { openSubject(n.slug); return; }
      $("graph-centre").value = n.name;
      drawGraph();
    });
    g.appendChild(node);
  });

  // Start with the whole graph in view. The spring layout spreads wider than
  // the canvas on a busy subject, so without this the first thing you see is
  // the middle of a graph whose edges run off the sides.
  const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y);
  const pad = 46;
  const spanX = Math.max(...xs) - Math.min(...xs) || 1;
  const spanY = Math.max(...ys) - Math.min(...ys) || 1;
  const fit = Math.min(1, (width - pad * 2) / spanX, (height - pad * 2) / spanY);
  const midX = (Math.max(...xs) + Math.min(...xs)) / 2;
  const midY = (Math.max(...ys) + Math.min(...ys)) / 2;

  // Pan and zoom, held in one transform rather than redrawing.
  const view = {
    x: width / 2 - midX * fit,
    y: height / 2 - midY * fit,
    k: fit,
  };
  const apply = () => g.setAttribute("transform",
    `translate(${view.x},${view.y}) scale(${view.k})`);
  apply();
  let dragging = false, lastX = 0, lastY = 0;
  svg.addEventListener("mousedown", (e) => {
    dragging = true; lastX = e.clientX; lastY = e.clientY; svg.classList.add("dragging");
  });
  addEventListener("mouseup", () => { dragging = false; svg.classList.remove("dragging"); });
  svg.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    view.x += e.clientX - lastX; view.y += e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY; apply();
  });
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    view.k = Math.max(0.25, Math.min(4, view.k * (e.deltaY < 0 ? 1.12 : 0.89)));
    apply();
  }, { passive: false });

  box.appendChild(svg);
  $("graph-note").textContent = data.truncated
    ? `Showing the ${data.nodes.length} closest connections — there are more.`
    : `${data.nodes.length} nodes, ${data.edges.length} links. Filled circles have a dossier; click to open. Hollow ones re-centre.`;
}

async function drawGraph() {
  const who = $("graph-centre").value.trim();
  if (!who) return;
  const depth = Number($("graph-depth").value) || 2;
  const box = $("graph-canvas");
  box.innerHTML = '<div class="muted small pad">Working it out…</div>';
  try {
    renderGraph(await api(`/api/graph/${encodeURIComponent(who)}?depth=${depth}`));
  } catch (e) {
    box.innerHTML = `<div class="muted small pad">${esc(e.message)}</div>`;
  }
}

async function findPath() {
  const a = $("path-a").value.trim(), b = $("path-b").value.trim();
  const out = $("path-result");
  if (!a || !b) { out.textContent = "Two subjects are needed."; return; }
  out.textContent = "Looking…";
  let r;
  try {
    r = await api(`/api/path?start=${encodeURIComponent(a)}&goal=${encodeURIComponent(b)}`);
  } catch (e) { out.textContent = e.message; return; }

  if (!r.found) {
    out.textContent = `No recorded chain joins ${r.start.name} and ${r.goal.name}. `
      + "That means nothing links them in what is stored — not that nothing links them.";
    return;
  }
  out.innerHTML = "";
  const lead = el("div", "small muted",
    `${r.hops.length} hop${r.hops.length === 1 ? "" : "s"} from ${r.start.name} to ${r.goal.name}:`);
  out.appendChild(lead);
  r.hops.forEach((h) => {
    const row = el("div", "hop");
    row.appendChild(el("span", "rel", h.relation));
    const who = el("span", "who");
    who.textContent = h.to.name;
    if (h.to.held && h.to.slug) {
      const link = el("a", null, h.to.name);
      link.addEventListener("click", () => openSubject(h.to.slug));
      who.textContent = "";
      who.appendChild(link);
    }
    row.appendChild(who);
    row.appendChild(el("span", "said", "from " + h.stated_by));
    out.appendChild(row);
  });
  const draw = el("button", "ghost", "Show this on the map");
  draw.addEventListener("click", () => {
    $("graph-centre").value = r.start.name;
    drawGraph();
  });
  out.appendChild(draw);
}

async function loadGraphStats() {
  try {
    const s = await api("/api/graph");
    $("graph-stats").innerHTML =
      `<div>${s.nodes} things, ${s.edges} links between them.</div>` +
      `<div class="muted">${s.held} have a dossier; ${s.named_only} are named by ` +
      `someone's record but not researched yet.</div>` +
      `<div style="margin-top:8px">Most connected:</div>`;
    const row = el("div", "row");
    s.most_connected.slice(0, 12).forEach((n) => {
      const tag = el("span", "tag" + (n.held ? " type" : ""), `${n.name} · ${n.links}`);
      tag.style.cursor = "pointer";
      tag.addEventListener("click", () => {
        $("graph-centre").value = n.name;
        drawGraph();
      });
      row.appendChild(tag);
    });
    $("graph-stats").appendChild(row);
  } catch (e) {
    $("graph-stats").textContent = "The graph could not be read.";
  }
}

function fillGraphNames() {
  const list = $("graph-names");
  list.innerHTML = "";
  (state.library || []).slice(0, 1200).forEach((row) => {
    const opt = document.createElement("option");
    opt.value = row.name;
    list.appendChild(opt);
  });
}

$("graph-draw").addEventListener("click", drawGraph);
$("graph-centre").addEventListener("keydown", (e) => { if (e.key === "Enter") drawGraph(); });
$("path-go").addEventListener("click", findPath);
$("path-b").addEventListener("keydown", (e) => { if (e.key === "Enter") findPath(); });

/* --------------------------------------------------------- full screen */

// Nothing to wire here: shared/forge_chrome.js finds the `go-fullscreen`
// button in the topbar and binds it, along with the `f` key and Escape, as
// soon as it loads. It hides the Forge sidebar, takes real fullscreen, and
// forge.py fullscreens the GTK window behind it. This file used to call
// ForgeChrome.init() behind an `if (window.ForgeChrome)` guard that was
// always false - the helper was a top-level `const` in forge.js and so never
// reached `window`, which is why the button did nothing at all.

/* ------------------------------------------------------------- briefing */

async function loadBriefing() {
  let b;
  try { b = await api("/api/briefing"); } catch (e) {
    $("briefing-body").textContent = "Could not read the briefing.";
    return;
  }
  renderBriefing(b);
}

function renderBriefing(b) {
  const node = $("briefing-body");
  if (!b || !b.events_total) {
    node.textContent = "No briefing built yet. Research some subjects, then build one.";
    return;
  }
  node.innerHTML = "";
  if (b.summary) {
    node.appendChild(el("div", null, b.summary));
  } else if (b.jan_available === false) {
    node.appendChild(el("div", "muted",
      "Jan was unavailable, so no written summary — the country figures below are still real."));
  }
  node.appendChild(el("div", "muted small",
    `${b.events_total} dated events across ${b.countries.length} countries, `
    + `last ${b.window_days} days · built ${b.generated}`));
  if (b.summary_points_dropped) {
    node.appendChild(el("div", "muted small",
      `${b.summary_points_dropped} point(s) dropped for citing nothing.`));
  }
  const list = el("div");
  list.style.marginTop = "8px";
  b.countries.slice(0, 12).forEach((c) => {
    const row = el("div", "small");
    row.innerHTML = `<b>${esc(c.country)}</b> <span class="muted">${c.events} events · `
      + `${esc(c.subjects.slice(0, 3).join(", "))}${c.subjects.length > 3 ? "…" : ""}</span>`;
    list.appendChild(row);
  });
  node.appendChild(list);
}

$("briefing-build").addEventListener("click", async () => {
  const b = $("briefing-build");
  b.disabled = true; b.textContent = "building…";
  try {
    renderBriefing(await api("/api/briefing/rebuild", { method: "POST",
      body: JSON.stringify({ days: Number($("briefing-days").value), summary: true }) }));
  } catch (e) { ForgeDialog.alert(e.message); }
  b.disabled = false; b.textContent = "Build briefing";
});

/* ------------------------------------------------------------ add subject */

$("add-go").addEventListener("click", async () => {
  const name = $("add-name").value.trim();
  if (!name) return;
  const button = $("add-go");
  button.disabled = true; button.textContent = "queued";
  try {
    await api("/api/research", { method: "POST", body: JSON.stringify({
      name, entity_type: $("add-type").value, phase: $("add-phase").value }) });
    $("add-name").value = "";
    showView("jobs");
    refreshQueue();
  } catch (e) { ForgeDialog.alert(e.message); }
  button.disabled = false; button.textContent = "Research";
});
$("add-name").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("add-go").click();
});

boot();

/* ----------------------------------------------------------------- arcs */
/* Ties between countries, drawn over the map.
 *
 * Every arc comes from the backend as a pair of country names and the
 * dossiers that recorded the tie, so hovering one can always name what it is
 * evidence of. Nothing here decides that two countries are linked - that
 * judgement is arithmetic over stored relations, done on the CPU.
 */

/* A country's drawing position: the centre of its LARGEST piece.
 *
 * Averaging every point of the path would put France in the Atlantic, because
 * its path includes French Guiana; the mainland is the part a reader looks
 * for. Computed once and cached, since the paths never change.
 */
function countryCentres() {
  if (state.centres) return state.centres;
  const centres = new Map();
  document.querySelectorAll("#worldmap path[data-name]").forEach((path) => {
    let best = null, bestCount = 0;
    (path.getAttribute("d") || "").split("M").forEach((piece) => {
      const nums = piece.match(/-?\d+(?:\.\d+)?/g);
      if (!nums || nums.length < 6) return;
      const points = nums.length >> 1;
      if (points <= bestCount) return;
      let sx = 0, sy = 0;
      for (let i = 0; i < points; i++) { sx += +nums[2 * i]; sy += +nums[2 * i + 1]; }
      bestCount = points;
      best = { x: sx / points, y: sy / points };
    });
    if (best) centres.set(path.dataset.name, best);
  });
  state.centres = centres;
  return centres;
}

async function loadArcs() {
  try {
    const payload = await api("/api/world/arcs");
    state.arcs = payload.arcs || [];
    state.arcKinds = payload.kinds || [];
  } catch (e) { return; }
  state.arcKinds.forEach((k) => state.arcOn.add(k.name));
  buildArcControls();
  drawArcs();
}

/* The filter is built from whatever kinds the backend reports, so a new kind
   of arc appears here without this file being edited. */
function buildArcControls() {
  const bar = $("arc-controls");
  if (!bar) return;
  bar.querySelectorAll(".arctoggle").forEach((n) => n.remove());
  const anchor = bar.querySelector(".spacer");
  state.arcKinds.forEach((kind) => {
    const label = el("label", "arctoggle");
    label.title = kind.blurb || "";
    const box = el("input");
    box.type = "checkbox";
    box.checked = state.arcOn.has(kind.name);
    box.addEventListener("change", () => {
      box.checked ? state.arcOn.add(kind.name) : state.arcOn.delete(kind.name);
      drawArcs();
    });
    const swatch = el("i");
    swatch.className = "arcswatch " + kind.name;
    label.append(box, swatch, document.createTextNode(kind.label));
    bar.insertBefore(label, anchor);
  });
}

function drawArcs() {
  const group = $("mapgroup");
  if (!group) return;
  const existing = document.getElementById("arcgroup");
  if (existing) existing.remove();
  const shown = state.arcs.filter((a) => state.arcOn.has(a.kind));
  const centres = countryCentres();
  const ns = "http://www.w3.org/2000/svg";
  const layer = document.createElementNS(ns, "g");
  layer.id = "arcgroup";

  let drawn = 0;
  const heaviest = Math.max(1, ...shown.map((a) => a.weight || 1));
  shown.forEach((arc) => {
    const from = centres.get(mapName(arc.a)), to = centres.get(mapName(arc.b));
    // A country the map does not carry - a historical state like the Soviet
    // Union - simply is not drawn. It is honest data with nowhere to go.
    if (!from || !to) return;
    const path = document.createElementNS(ns, "path");
    // Bow the line out perpendicular to itself, so two arcs between the same
    // pair never sit exactly on top of each other and none is a straight line
    // through a third country.
    const mx = (from.x + to.x) / 2, my = (from.y + to.y) / 2;
    const dx = to.x - from.x, dy = to.y - from.y;
    const length = Math.hypot(dx, dy) || 1;
    const bow = Math.min(60, length * 0.22);
    const cx = mx - (dy / length) * bow, cy = my + (dx / length) * bow;
    path.setAttribute("d", `M${from.x} ${from.y}Q${cx} ${cy} ${to.x} ${to.y}`);
    path.setAttribute("class", "arc " + arc.kind);
    path.setAttribute("stroke-width", (0.6 + (arc.weight / heaviest) * 1.8).toFixed(2));
    path.dataset.arc = JSON.stringify({
      a: arc.a, b: arc.b, reads: arc.reads, via: arc.via, weight: arc.weight,
    });
    layer.appendChild(path);
    drawn++;
  });
  group.appendChild(layer);
  const count = $("arc-count");
  if (count) {
    count.textContent = shown.length
      ? `${drawn} drawn${shown.length > drawn ? ` · ${shown.length - drawn} between places the map has no border for` : ""}`
      : "none shown";
  }
}

/* An arc is a claim about the world, so hovering it names the dossiers it came
   from and clicking it opens one. */
function arcTip(target, evt) {
  const tip = $("maptip"), svg = $("worldmap");
  const data = JSON.parse(target.dataset.arc);
  const via = data.via.map((v) => esc(v.name)).join(", ");
  tip.innerHTML = `<b>${esc(data.a)}</b> ${esc(data.reads)} <b>${esc(data.b)}</b>`
    + `<br><span class="muted">${via}</span>`
    + (data.weight > data.via.length ? `<br><span class="muted">and ${data.weight - data.via.length} more</span>` : "");
  const r = svg.getBoundingClientRect();
  tip.style.left = Math.min(evt.clientX - r.left + 14, r.width - 250) + "px";
  tip.style.top = (evt.clientY - r.top + 14) + "px";
  tip.classList.add("on");
}

/* ---------------------------------------------------------------- watch */

async function loadWatch() {
  loadHistory();
  try { state.watch = await api("/api/watch"); }
  catch (e) { $("watch-status").textContent = "could not read the watcher"; return; }
  renderWatch();
}

function renderWatch() {
  const w = state.watch;
  if (!w) return;
  $("watch-enabled").checked = !!w.enabled;
  $("watch-hours").value = String(w.every_hours);
  $("watch-per").value = w.per_sweep;
  syncPair($("watch-per"));

  const bits = [];
  bits.push(w.enabled
    ? `Watching ${w.held} subjects, ${w.per_sweep} at a time, every ${w.every_hours} hours.`
    : "Switched off — nothing is refreshed on its own.");
  if (w.last_sweep) bits.push(`Last sweep ${w.last_sweep.replace("T", " ").replace("+00:00", "")} — ${w.last_result}.`);
  else bits.push("No sweep has run yet.");
  if (w.blocked) bits.push(`Waiting: ${w.blocked}.`);
  else if (w.enabled && w.due) bits.push("A sweep is due and will start on the next tick.");
  $("watch-status").textContent = bits.join(" ");

  const next = $("watch-next");
  next.innerHTML = "";
  (w.next_up || []).forEach((row) => {
    const line = el("div", "watchrow");
    const name = el("a", "name", row.name);
    name.href = "#/subject/" + encodeURIComponent(row.slug);
    name.addEventListener("click", (e) => { e.preventDefault(); openSubject(row.slug); });
    line.append(name, el("span", "muted small",
      row.updated ? "last looked at " + row.updated.slice(0, 10) : "never refreshed"));
    next.appendChild(line);
  });
  if (!next.children.length) next.appendChild(el("div", "muted small", "Nothing held yet."));

  const fresh = $("watch-fresh");
  fresh.innerHTML = "";
  (w.freshest || []).forEach((row) => {
    const line = el("div", "watchrow");
    const name = el("a", "name", row.name);
    name.href = "#/subject/" + encodeURIComponent(row.slug);
    name.addEventListener("click", (e) => { e.preventDefault(); openSubject(row.slug); });
    line.append(name, el("span", "muted small",
      `${row.timeline} events · ${row.updated.slice(0, 10)}`));
    fresh.appendChild(line);
  });
  if (!fresh.children.length) fresh.appendChild(el("div", "muted small", "Nothing refreshed yet."));

  const sweeps = $("watch-sweeps");
  sweeps.innerHTML = "";
  (w.sweeps || []).slice(0, 10).forEach((sweep) => {
    sweeps.appendChild(el("div", "watchrow",
      `${sweep.at.replace("T", " ").replace("+00:00", "")} — queued ${sweep.queued}`));
  });
  if (!sweeps.children.length) sweeps.textContent = "none yet";
}

async function saveWatch(patch) {
  try { state.watch = await api("/api/watch", { method: "POST", body: JSON.stringify(patch) }); }
  catch (e) { ForgeDialog.alert(e.message); return; }
  renderWatch();
}

$("watch-enabled").addEventListener("change", (e) =>
  saveWatch({ enabled: e.target.checked }));
$("watch-hours").addEventListener("change", (e) =>
  saveWatch({ every_hours: Number(e.target.value) }));
$("watch-per").addEventListener("change", (e) =>
  saveWatch({ per_sweep: Number(e.target.value) }));

$("watch-now").addEventListener("click", async () => {
  const button = $("watch-now");
  button.disabled = true; button.textContent = "sweeping…";
  try {
    const result = await api("/api/watch/sweep", { method: "POST", body: JSON.stringify({ force: true }) });
    state.watch = result.state;
    renderWatch();
    if (!result.ran) $("watch-status").textContent = "Sweep deferred: " + result.reason + ".";
    else refreshQueue();
  } catch (e) { ForgeDialog.alert(e.message); }
  button.disabled = false; button.textContent = "Sweep now";
});

/* -------------------------------------------------------------- history */
/* Five years of news and the full article for subjects already held. The
 * work runs on the backend; the page only reads its progress while it runs. */

async function loadHistory() {
  let h;
  try { h = await api("/api/history"); }
  catch (e) { $("history-status").textContent = "could not read the history job"; return false; }
  renderHistory(h);
  watch("historyWatch", loadHistory, 3000, Boolean(h.running));
  return true;
}

function renderHistory(h) {
  const a = h.archive || {};
  const bits = [];
  if (a.error) bits.push(`The archive could not be read: ${a.error}.`);
  else bits.push(`Archive: ${a.months_held} of ${a.months_in_window} months held `
    + `(${a.window_start} to ${a.window_end}), ${Number(a.events || 0).toLocaleString()} events.`);
  if (h.running) {
    bits.push(`Working on ${h.stage || "starting"}`
      + (h.total ? ` — ${h.done} of ${h.total} subjects.` : "."));
  } else if (h.finished) {
    bits.push(`Last run finished ${h.finished.replace("T", " ").replace("+00:00", "")}: `
      + `${h.events_added} events and ${h.articles_added} articles added.`);
  }
  $("history-status").textContent = bits.join(" ");
  $("history-bar").style.width = (h.total ? Math.round((100 * h.done) / h.total) : 0) + "%";
  setLog($("history-log"), (h.log || []).join("\n"));
  $("history-start").disabled = !!h.running;
  $("history-stop").disabled = !h.running;
  $("history-stop").hidden = !h.running; // nothing to stop: no greyed-out button
}

$("history-start").addEventListener("click", async () => {
  const button = $("history-start");
  if (button.disabled) return;
  button.disabled = true;  // renderHistory sets it again from the job state
  try { renderHistory(await api("/api/history", { method: "POST", body: "{}" })); }
  catch (e) { ForgeDialog.alert(e.message); button.disabled = false; }
  loadHistory();
});
$("history-stop").addEventListener("click", async () => {
  try { renderHistory(await api("/api/history/stop", { method: "POST" })); }
  catch (e) { ForgeDialog.alert(e.message); }
});

// --- library folder: find the library again after it moved (A25) ------------
function fmtWhen(t) {
  return new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

async function openLocation(folder, auto) {
  const q = folder ? "?folder=" + encodeURIComponent(folder) : "";
  const loc = await api("/api/location" + q);
  const found = loc.found.filter((f) => !auto || f.subjects > loc.current.subjects);
  if (auto && !found.length) return;
  $("loc-current").textContent =
    `In use: ${loc.current.path} (${loc.current.subjects} subjects). ${loc.current.detail}`;
  const box = $("loc-found");
  box.replaceChildren();
  if (!found.length) {
    box.textContent = "No other library folder found in " + loc.searched.join(", ") + ".";
  }
  for (const f of found) {
    const row = document.createElement("div");
    row.className = "loc-row";
    const where = document.createElement("div");
    where.className = "where";
    where.innerHTML = "<strong></strong><div class='muted'></div>";
    where.querySelector("strong").textContent = f.path;
    where.querySelector("div").textContent = `${f.subjects} subjects · last changed ${fmtWhen(f.modified)}`;
    const use = document.createElement("button");
    use.className = "ghost";
    use.textContent = "Use this folder";
    use.addEventListener("click", async () => {
      use.disabled = true;
      await api("/api/location", { method: "POST", body: JSON.stringify({ path: f.path }) });
      $("loc-dialog").close();
      await switchedLibrary();
    });
    row.append(where, use);
    box.appendChild(row);
  }
  if (!$("loc-dialog").open) $("loc-dialog").showModal();
}

/* Another library folder was picked: re-read everything that came from the
   old one in place, rather than reloading the whole page (which flashed and
   lost the tab you were on). */
async function switchedLibrary() {
  try { state.status = await api("/api/status"); paintStatus(state.status); }
  catch (e) { return; }
  state.subject = null; state.libPlace = null;
  state.jobsSig = null; state.queueDone = null;
  $("subject-body").innerHTML = '<div class="empty">Pick a subject from the library or the map.</div>';
  $("country-panel").hidden = true;
  if (location.hash.startsWith("#/subject/")) showView("world");
  await Promise.all([refreshLibrary(), loadBriefing()]);
  loadArcs();
  refreshQueue();
  if ($("view-watch").classList.contains("on")) loadWatch();
}

$("pill-store").addEventListener("click", () => {
  if (!$("pill-store").dataset.fixed) openLocation();
});
$("loc-search").addEventListener("click", () => openLocation($("loc-folder").value.trim()));
$("loc-close").addEventListener("click", () => $("loc-dialog").close());
// The library looks empty but a fuller one exists elsewhere: offer it once.
openLocation("", true).catch(() => {});
