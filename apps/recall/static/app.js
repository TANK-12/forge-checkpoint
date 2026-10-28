/* Recall page: decks on the left; Review, Cards and Import on the right. */
"use strict";

const S = { deck: "", tab: "review", card: null, shown: false, editing: null, q: "", sure: null };
const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) throw new Error(await errText(res, "that did not work"));
  return res.json();
}

function span(seconds) {
  const m = seconds / 60;
  if (m < 1) return "now";
  if (m < 60) return Math.round(m) + " min";
  const h = m / 60;
  if (h < 24) return Math.round(h) + " h";
  const d = h / 24;
  if (d < 31) return Math.round(d) + (Math.round(d) === 1 ? " day" : " days");
  if (d < 365) return Math.round(d / 30.4) + " mo";
  return (d / 365).toFixed(1) + " yr";
}

async function loadDecks() {
  const d = await api("/api/decks");
  const list = $("decks");
  list.replaceChildren();
  const row = (name, label, c) => {
    const b = el("button", "deck" + (name === S.deck ? " active" : ""));
    b.type = "button";
    b.dataset.deck = name;
    b.title = `${c.due} due, ${c.new_today} new today, ${c.total} cards`;
    b.append(el("span", "name", label), el("span", "due", String(c.due)), el("span", "new", "+" + c.new_today));
    b.onclick = () => pickDeck(name);
    list.append(b);
  };
  row("", "All decks", d.all);
  for (const x of d.decks) row(x.name, x.name, x);
  if (!d.decks.length) list.append(el("p", "muted small", "No cards yet."));
  if (S.deck && !d.decks.some((x) => x.name === S.deck)) S.deck = "";
  const names = $("deck-names");
  names.replaceChildren(...d.decks.map((x) => { const o = el("option"); o.value = x.name; return o; }));
  const st = d.stats;
  const parts = [`${st.today} answered today`];
  if (st.remembered !== null) parts.push(`${Math.round(st.remembered * 100)}% remembered over 30 days`);
  parts.push(`${st.due_by_tomorrow} due by tomorrow night`);
  $("stats").textContent = parts.join(" · ");
}

function pickDeck(name) {
  S.deck = name;
  document.querySelectorAll(".deck").forEach((b) => b.classList.toggle("active", b.dataset.deck === name));
  if (!S.editing) setVal("f-deck", name);
  refresh();
}

async function loadNext() {
  const d = await api("/api/next?deck=" + encodeURIComponent(S.deck));
  S.card = d.card;
  S.shown = false;
  $("review").classList.toggle("hidden", !d.card);
  $("review-empty").classList.toggle("hidden", !!d.card);
  if (!d.card) {
    const where = S.deck ? `in ${S.deck}` : "anywhere";
    let text = d.left.total ? `Nothing due ${where} right now.` : "No cards here yet.";
    if (d.left.total && d.left.new && !d.left.new_today) text += " Today's new cards are done.";
    if (d.next_due) text += ` The next one is due in ${span(d.next_due - Date.now() / 1000)}.`;
    $("review-empty-text").textContent = text;
    return;
  }
  $("r-deck").textContent = d.card.deck + (d.card.state === "new" ? " · new card" : "");
  $("r-left").textContent = `${d.left.due} due · ${d.left.new_today} new left today`;
  $("r-front").textContent = d.card.front;
  $("r-back").textContent = d.card.back;
  $("r-back-wrap").classList.add("hidden");
  $("r-show").classList.remove("hidden");
  $("r-rate").classList.add("hidden");
  document.querySelectorAll(".rate").forEach((b) => {
    b.querySelector(".when").textContent = span(d.after[b.dataset.rating]);
  });
}

function show() {
  if (!S.card || S.shown) return;
  S.shown = true;
  $("r-back-wrap").classList.remove("hidden");
  $("r-show").classList.add("hidden");
  $("r-rate").classList.remove("hidden");
}

async function rate(rating) {
  if (!S.card || !S.shown) return;
  const id = S.card.id;
  S.card = null;
  try {
    await api("/api/answer", { method: "POST", body: { id, rating } });
  } catch (e) {
    toast(e.message, "error");
  }
  await Promise.all([loadNext(), loadDecks()]);
}

function cardRow(c) {
  const item = el("div", "item card");
  const acts = el("div", "acts");
  const edit = el("button", "btn", "Edit");
  edit.type = "button";
  edit.onclick = () => startEdit(c);
  const rm = el("button", "btn btn-danger", "Remove");
  rm.type = "button";
  rm.onclick = () => removeCard(c.id, rm);
  acts.append(edit, rm);
  let meta = c.deck + " · " + (c.state === "new" ? "new" : `${c.state}, due in ${span(c.due - Date.now() / 1000)}`);
  if (c.recall !== undefined) meta += `, ${Math.round(c.recall * 100)}% likely remembered now`;
  if (c.imported) meta += " · imported";
  item.append(el("div", "t", c.front), el("div", "t muted", c.back), acts, el("div", "m", meta));
  return item;
}

async function loadCards() {
  const d = await api(`/api/cards?deck=${encodeURIComponent(S.deck)}&q=${encodeURIComponent(S.q)}`);
  const box = $("cards");
  box.replaceChildren(...d.cards.map(cardRow));
  if (!d.cards.length) box.append(el("p", "placeholder", S.q ? "No card has those words." : "No cards in this deck yet."));
}

function startEdit(c) {
  S.editing = c.id;
  setVal("f-deck", c.deck);
  setVal("f-front", c.front);
  setVal("f-back", c.back);
  $("f-save").textContent = "Save card";
  $("f-cancel").classList.remove("hidden");
  $("f-front").focus();
}

function stopEdit() {
  S.editing = null;
  setVal("f-front", "");
  setVal("f-back", "");
  setVal("f-deck", S.deck);
  $("f-save").textContent = "Add card";
  $("f-cancel").classList.add("hidden");
}

async function saveCard(ev) {
  ev.preventDefault();
  const body = { deck: val("f-deck"), front: val("f-front"), back: val("f-back") };
  try {
    if (S.editing) {
      await api(`/api/cards/${S.editing}`, { method: "PUT", body });
      toast("Card saved");
      stopEdit();
    } else {
      await api("/api/cards", { method: "POST", body });
      toast(`Added to ${body.deck.trim()}`);
      setVal("f-front", "");
      setVal("f-back", "");
      $("f-front").focus();
    }
  } catch (e) {
    toast(e.message, "error");
    return;
  }
  await Promise.all([loadCards(), loadDecks()]);
}

async function removeCard(id, button) {
  if (S.sure !== id) {
    S.sure = id;
    button.textContent = "Remove it?";
    setTimeout(() => { if (S.sure === id) { S.sure = null; button.textContent = "Remove"; } }, 4000);
    return;
  }
  S.sure = null;
  try {
    await api(`/api/cards/${id}/remove`, { method: "POST" });
    toast("Card removed");
  } catch (e) {
    toast(e.message, "error");
  }
  if (S.editing === id) stopEdit();
  await Promise.all([loadCards(), loadDecks()]);
}

async function loadSources() {
  const d = await api("/api/sources");
  const box = $("sources");
  box.replaceChildren();
  if (!d.sources.length)
    box.append(el("p", "small muted", "Nothing to import from here: the apps Recall imports from are not installed."));
  for (const s of d.sources) {
    const row = el("div", "source card");
    const about = el("div", "about");
    about.append(el("h3", "", s.label), el("p", "small muted", s.about));
    const found = s.offers
      ? `Offers ${s.offers} cards (${s.decks.join(", ")}); ${s.have} already in Recall.`
      : `Nothing found in ${s.root}.`;
    about.append(el("p", "small", found));
    const go = el("button", "btn btn-primary", "Import");
    go.type = "button";
    go.disabled = !s.offers;
    go.onclick = () => importSource(s.id, go);
    row.append(about, go);
    box.append(row);
  }
}

async function importSource(id, button) {
  button.disabled = true;
  try {
    const r = await api("/api/import", { method: "POST", body: { source: id } });
    toast(`Added ${r.added}, updated ${r.changed}, ${r.same} unchanged`
      + (r.kept ? `, ${r.kept} you edited kept as you wrote them` : "")
      + (r.skipped ? `, ${r.skipped} left out` : ""));
  } catch (e) {
    toast(e.message, "error");
  }
  await Promise.all([loadSources(), loadDecks()]);
}

function refresh() {
  if (S.tab === "review") return loadNext();
  if (S.tab === "cards") return loadCards();
  return loadSources();
}

let searchTimer = 0;
$("search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { S.q = val("search").trim(); loadCards(); }, 200);
});
$("show").onclick = show;
document.querySelectorAll(".rate").forEach((b) => { b.onclick = () => rate(Number(b.dataset.rating)); });
$("card-form").addEventListener("submit", saveCard);
$("f-cancel").onclick = stopEdit;
document.addEventListener("keydown", (e) => {
  if (S.tab !== "review" || e.target.closest("input, textarea") || e.ctrlKey || e.metaKey || e.altKey) return;
  if ((e.key === " " || e.key === "Enter") && !S.shown) { e.preventDefault(); show(); }
  else if (S.shown && "1234".includes(e.key) && e.key.length === 1) { e.preventDefault(); rate(Number(e.key)); }
});
initTabs((name) => { S.tab = name; refresh(); });
loadDecks().then(refresh).catch((e) => toast(e.message, "error"));
