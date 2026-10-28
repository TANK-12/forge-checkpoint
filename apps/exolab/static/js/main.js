// Exo Lab page: the home menu (real-world tester or game), hash routing
// (#home, #tester?model=&test=&edit=1&tab=), and the wiring between the
// tester, the editor and the 3D view.

import { $, S, api, emit, h, on, profileKey } from "./store.js";
import { View3D } from "./view3d.js";
import { initTester, refresh, setPoseMode } from "./tester.js";
import { editorOpen, initEditor, setEditorOpen, setTab } from "./editor.js";

let view = null;
let ran = false;

const byReady = (a, b) =>
  (a.status === "ready" ? 0 : 1) - (b.status === "ready" ? 0 : 1) || String(a.name).localeCompare(String(b.name));
const byOrder = (a, b) => (a.order ?? 99) - (b.order ?? 99);

async function boot() {
  try {
    S.reg = await api("/api/registry");
  } catch (err) {
    $("home-models").replaceChildren(h("p", { class: "err", text: `The Exo Lab backend did not answer: ${err.message}` }));
    return;
  }
  view = new View3D($("c3d"), $("v3d-note"));
  fillSelects();
  renderHome();
  initEditor();
  initTester(view);
  on("profiles", fillCompare);
  on("model-picked", writeHash);
  on("test-picked", writeHash);
  on("ui", writeHash);
  $("btn-editor").addEventListener("click", () => {
    showEditor(!editorOpen());
    writeHash();
  });
  for (const ev of ["model", "model-picked", "profile", "profiles", "saved"]) on(ev, gameLinks);
  window.addEventListener("hashchange", route);
  route();
  gameLinks();
}

/** Point every Game link at the suit on the bench (a ready one) and the
 *  profile as saved on the server; the game reads both from its URL. */
function gameLinks() {
  const models = S.reg.items.models || {};
  const id = models[S.modelId]?.status === "ready" ? S.modelId : "exo_full";
  const prof = (S.reg.profiles || []).includes(S.profileName) ? S.profileName : "baseline";
  const dirty = prof !== S.profileName || profileKey() !== S.saved;
  const name = models[id]?.name || id;
  for (const a of document.querySelectorAll('a[href^="game.html"]')) {
    a.setAttribute("href", `game.html?${new URLSearchParams({ model: id, profile: prof })}`);
    a.title = dirty
      ? `Play ${name} with the saved ${prof} profile; save first to play your unsaved edits`
      : `Play ${name} with the ${prof} profile`;
  }
}

function fillSelects() {
  const models = Object.values(S.reg.items.models || {}).sort(byReady);
  $("sel-model").replaceChildren(
    ...models.map((m) => h("option", { value: m.id }, m.status === "ready" ? m.name : `${m.name} (planned)`)),
  );
  const tests = Object.values(S.reg.items.tests || {}).sort(byOrder);
  $("sel-test").replaceChildren(...tests.map((t) => h("option", { value: t.id }, t.name)));
  $("sel-model").value = S.modelId;
  $("sel-test").value = S.testId;
  fillCompare();
}

function fillCompare() {
  const names = S.reg.profiles || ["baseline"];
  if (!names.includes(S.compareTo)) S.compareTo = "baseline";
  $("sel-compare").replaceChildren(...names.map((n) => h("option", { value: n }, n === "baseline" ? "baseline (as shipped)" : n)));
  $("sel-compare").value = S.compareTo;
}

function renderHome() {
  const models = Object.values(S.reg.items.models || {}).sort(byReady);
  $("home-models").replaceChildren(
    ...models.map((m) =>
      h(
        "a",
        { class: `mcard ${m.status === "ready" ? "ready" : "planned"}`, href: `#tester?model=${encodeURIComponent(m.id)}` },
        h(
          "div",
          { class: "mc-top" },
          h("b", { text: m.name }),
          h("span", { class: `chip lv-${m.status === "ready" ? "pass" : "out"}`, text: m.status === "ready" ? "ready to test" : "planned" }),
        ),
        h("p", { text: m.about || "" }),
      ),
    ),
  );
  const tests = Object.values(S.reg.items.tests || {}).sort(byOrder);
  $("home-tests").replaceChildren(
    ...tests.map((t) =>
      h("a", { class: "tcard", href: `#tester?test=${encodeURIComponent(t.id)}` }, h("b", { text: t.name }), h("p", { text: t.about || "" })),
    ),
  );
}

function showEditor(want) {
  setEditorOpen(want);
  $("tester").classList.toggle("with-editor", editorOpen());
  $("btn-editor").classList.toggle("on", editorOpen());
}

function route() {
  const [page, query] = location.hash.replace(/^#/, "").split("?");
  const q = new URLSearchParams(query || "");
  const tester = page === "tester";
  $("home").hidden = tester;
  $("tester").hidden = !tester;
  for (const a of document.querySelectorAll("[data-nav]")) a.classList.toggle("on", a.dataset.nav === (tester ? "tester" : "home"));
  view.active = tester;
  if (!tester) return;
  let again = !ran;
  const m = q.get("model");
  if (m && Object.hasOwn(S.reg.items.models || {}, m) && m !== S.modelId) {
    // Pose mode closes with its box and button: the next model runs its test.
    if (S.poseMode) setPoseMode(false);
    S.modelId = m;
    S.sub = 0;
    again = true;
    emit("model-picked");
  }
  const t = q.get("test");
  if (t && Object.hasOwn(S.reg.items.tests || {}, t) && t !== S.testId) {
    S.testId = t;
    S.sub = 0;
    again = true;
    emit("test-picked");
  }
  $("sel-model").value = S.modelId;
  $("sel-test").value = S.testId;
  if (q.get("tab")) setTab(q.get("tab"));
  const wantEditor = q.get("edit") === "1" || q.has("tab");
  if (wantEditor !== editorOpen()) showEditor(wantEditor);
  view.resize();
  if (again) {
    ran = true;
    refresh();
  }
  writeHash();
}

function writeHash() {
  if ($("tester").hidden) return;
  const q = new URLSearchParams({ model: S.modelId, test: S.testId });
  if (editorOpen()) {
    q.set("edit", "1");
    q.set("tab", S.tab);
  }
  history.replaceState(null, "", `#tester?${q}`);
}

boot();
