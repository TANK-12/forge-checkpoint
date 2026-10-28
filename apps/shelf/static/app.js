/* Shelf page: the list on the left, the reader on the right. */
"use strict";

const S = { view: "unread", q: "", open: null, targets: [], size: 18 };
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

function when(ts) {
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

async function loadList() {
  const p = new URLSearchParams({ view: S.view, q: S.q });
  const d = await api("/api/articles?" + p);
  for (const b of document.querySelectorAll(".view-btn")) {
    b.classList.toggle("active", b.dataset.view === S.view);
    b.querySelector(".n").textContent = d.counts[b.dataset.view] || "";
  }
  const list = $("list");
  list.replaceChildren();
  if (!d.articles.length) {
    list.append(el("div", "muted small", S.q ? "Nothing saved matches that." : "Nothing here yet."));
  }
  for (const a of d.articles) {
    const b = el("button", "item" + (a.read ? " read" : "") + (a.id === S.open ? " active" : ""));
    b.type = "button";
    b.dataset.id = a.id;
    b.append(el("div", "t", a.title));
    b.append(el("div", "m", [a.site, `${a.minutes} min`, when(a.saved)].filter(Boolean).join(" · ")));
    if (a.snippet) {
      const s = el("div", "s");
      s.innerHTML = a.snippet; // server-escaped, only <mark> left
      b.append(s);
    }
    b.addEventListener("click", () => openArticle(a.id));
    list.append(b);
  }
}

async function openArticle(id) {
  const a = await api("/api/articles/" + id);
  S.open = a.id;
  $("empty").classList.add("hidden");
  $("article").classList.remove("hidden");
  $("a-title").textContent = a.title;
  const by = $("a-byline");
  by.replaceChildren();
  const bits = [a.author, a.site, a.published, `${a.minutes} min read`].filter(Boolean);
  by.append(bits.join(" · ") + " · ");
  const link = el("a", "", "original");
  link.href = a.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  by.append(link);
  $("a-body").innerHTML = a.html; // cleaned to an allow-list by shelf_core.clean
  // the article's own heading usually repeats the title shown above it
  const first = $("a-body").querySelector("h1, h2");
  const same = (t) => t.replace(/\s+/g, " ").trim().toLowerCase();
  if (first && a.title && same(a.title).startsWith(same(first.textContent))) first.remove();
  $("toggle-read").textContent = a.read ? "Mark unread" : "Mark read";
  $("toggle-archive").textContent = a.archived ? "Unarchive" : "Archive";
  $("toggle-read").dataset.on = a.read ? "1" : "";
  $("toggle-archive").dataset.on = a.archived ? "1" : "";
  S.article = a;
  $("reader").scrollTop = 0;
  for (const b of document.querySelectorAll(".item")) b.classList.toggle("active", b.dataset.id === id);
}

async function setFlag(flag, button) {
  const on = !button.dataset.on;
  await api("/api/articles/" + S.open, { method: "POST", body: { [flag]: on } });
  await openArticle(S.open);
  await loadList();
}

async function save(url) {
  $("save").disabled = true;
  $("save").textContent = "Saving...";
  try {
    const d = await api("/api/save", { method: "POST", body: { url } });
    toast(d.new ? `Kept: ${d.article.title}` : "That one is already on the shelf", "ok");
    $("url").value = "";
    if (S.view === "archived") S.view = "unread";
    await loadList();
    await openArticle(d.article.id);
  } catch (e) {
    toast(e.message, "err");
  } finally {
    $("save").disabled = false;
    $("save").textContent = "Save";
  }
}

function askSend(target) {
  $("ask-label").textContent = target.ask || target.label;
  $("ask-name").value = (S.article && S.article[target.prefill]) || (S.article ? S.article.title : "");
  $("ask").dataset.target = target.id;
  $("ask").classList.remove("hidden");
  $("ask-name").focus();
  $("ask-name").select();
}

function setSize(n) {
  S.size = Math.max(14, Math.min(28, n));
  $("article").style.setProperty("--size", S.size + "px");
  localStorage.setItem("shelf-size", String(S.size));
}

async function init() {
  setSize(Number(localStorage.getItem("shelf-size")) || 18);
  $("bookmarklet").href =
    "javascript:location.href='" + location.origin + "/#save='+encodeURIComponent(location.href)";
  $("bookmarklet").addEventListener("click", (e) => {
    e.preventDefault();
    toast("Drag it to the bookmarks bar instead of clicking it here");
  });
  $("save-form").addEventListener("submit", (e) => {
    e.preventDefault();
    save($("url").value.trim());
  });
  let typing;
  $("search").addEventListener("input", () => {
    clearTimeout(typing);
    typing = setTimeout(() => {
      S.q = $("search").value.trim();
      loadList().catch((e) => toast(e.message, "err"));
    }, 200);
  });
  for (const b of document.querySelectorAll(".view-btn")) {
    b.addEventListener("click", () => {
      S.view = b.dataset.view;
      loadList();
    });
  }
  $("toggle-read").addEventListener("click", (e) => setFlag("read", e.currentTarget));
  $("toggle-archive").addEventListener("click", (e) => setFlag("archived", e.currentTarget));
  $("smaller").addEventListener("click", () => setSize(S.size - 1));
  $("bigger").addEventListener("click", () => setSize(S.size + 1));
  $("remove").addEventListener("click", async () => {
    if (!confirm("Move this article and its pictures to the bin?")) return;
    try {
      await api("/api/articles/" + S.open, { method: "DELETE" });
      toast("Moved to the bin", "ok");
      S.open = null;
      $("article").classList.add("hidden");
      $("empty").classList.remove("hidden");
      await loadList();
    } catch (e) {
      toast(e.message, "err");
    }
  });
  $("ask-cancel").addEventListener("click", () => $("ask").classList.add("hidden"));
  $("ask-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const d = await api("/api/send", {
        method: "POST",
        body: { target: $("ask").dataset.target, name: $("ask-name").value },
      });
      toast(d.done, "ok");
      $("ask").classList.add("hidden");
    } catch (err) {
      toast(err.message, "err");
    }
  });

  const cfg = await api("/api/config");
  S.targets = cfg.send_to;
  for (const t of S.targets) {
    const b = el("button", "btn", t.label);
    b.type = "button";
    b.dataset.target = t.id;
    b.addEventListener("click", () => askSend(t));
    $("send-buttons").append(b);
  }

  // the bookmarklet's #save=<address>: fill the box, wait for a click
  const m = location.hash.match(/^#save=(.+)$/);
  if (m) {
    $("url").value = decodeURIComponent(m[1]);
    history.replaceState(null, "", location.pathname);
    $("save").focus();
    toast("Press Save to keep it");
  }
  await loadList();
}

init().catch((e) => toast(e.message, "err"));
