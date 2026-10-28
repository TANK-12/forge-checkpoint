/* The Business card: the look's password lock and the company profiles.

   The lock is shared/forge_lock.py behind /api/lock (which needs X-Forge: 1).
   While it is shut every save answers 423: app.js hands the refused change to
   Business.refused(), which opens the password prompt and sends the change
   again once the password opens the lock. The password is only ever typed
   into a password box and sent to /api/lock; nothing here keeps or shows it.
   Company profiles are ordinary settings (business_companies and
   business_company), saved through change() like any other, so they are
   locked the same way; a logo is uploaded first and saved by name. The hub
   is told when the lock opens or shuts (look_open_until), so its own
   changes (hide an app, folders, sizes) follow the same window.
   "Back to my old look" (card, banner and prompt) picks the look from
   before Business (back_look in /api/lock), asking for the password first
   while it is locked; the forced settings were never saved, so his own come
   back with it. */
const Business = (() => {
  const lock = { look_locks: false, has_password: false, locked: false, open_until: 0,
    back_look: "classic", back_label: "Classic" };
  let refusedBody = null;
  let retry = null; // a refused step that is not a settings save (a logo upload)
  let logoData = "";
  let told = "";
  let backAsked = false; // the open prompt was opened to go back to the old look
  let backSaid = ""; // the look gone back to, said once the save is in

  async function call(path, body) {
    let r;
    try {
      r = await fetch(path, {
        method: body ? "POST" : "GET",
        headers: { "Content-Type": "application/json", "X-Forge": "1" },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      throw new Error("the Settings backend is not answering");
    }
    let data = {};
    try { data = await r.json(); } catch (e) {}
    if (!r.ok) {
      const text = typeof data.detail === "string" ? data.detail : `error ${r.status}`;
      throw Object.assign(new Error(text), { status: r.status, wait: data.wait || 0 });
    }
    return data;
  }

  function say(text) { $("biz-said").textContent = text; }

  // the hub's copy of the lock, sent only when it changed
  function tellLock() {
    const now = { look_locked: !!(lock.look_locks && lock.has_password), look_open_until: lock.open_until || 0 };
    if (JSON.stringify(now) === told) return;
    told = JSON.stringify(now);
    tellHub(now);
  }

  function update(status) {
    Object.assign(lock, status);
    tellLock();
  }

  async function refresh() {
    try { update(await call("/api/lock")); } catch (e) { return; }
    paint();
    if (backSaid && !lock.look_locks) { say(`Back to ${backSaid}.`); backSaid = ""; }
  }

  function clock(seconds) {
    return new Date(seconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function stateText() {
    if (!lock.look_locks) return "Off";
    if (!lock.has_password) return "On, not locked: no password set";
    if (lock.locked) return "On, locked";
    return `On, unlocked until ${clock(lock.open_until)}`;
  }

  function companies() { return (state.settings && state.settings.business_companies) || []; }

  function paintCompanies() {
    const box = $("biz-companies");
    const list = companies();
    const active = (state.settings && state.settings.business_company) || "";
    box.replaceChildren();
    if (!list.length) {
      const none = document.createElement("div");
      none.className = "muted small";
      none.textContent = "No company yet. Add one below; its logo shows on the Business home screen.";
      box.append(none);
      return;
    }
    list.forEach((c) => {
      const row = document.createElement("label");
      row.className = "biz-company" + (c.id === active ? " on" : "");
      const pick = document.createElement("input");
      pick.type = "radio";
      pick.name = "biz-company";
      pick.checked = c.id === active;
      pick.addEventListener("change", () => change("business_company", c.id));
      const logo = document.createElement("img");
      logo.alt = "";
      if (c.logo) logo.src = `/api/business/logo/${encodeURIComponent(c.logo)}`;
      else logo.classList.add("empty");
      const name = document.createElement("span");
      name.className = "biz-company-name";
      name.textContent = c.name;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn";
      remove.textContent = "Remove";
      remove.addEventListener("click", (e) => {
        e.preventDefault();
        change("business_companies", companies().filter((x) => x.id !== c.id));
        if (c.id === active) change("business_company", "");
      });
      row.append(pick, logo, name, remove);
      box.append(row);
    });
  }

  function paint() {
    document.body.classList.toggle("forge-locked", !!lock.locked);
    $("lock-banner").hidden = !lock.locked;
    $("biz-state").textContent = stateText();
    $("biz-state").className = "biz-state" + (lock.locked ? " locked" : "");
    const on = !!(state.settings && lock.look_locks);
    $("biz-on").hidden = on || !state.settings;
    $("biz-unlock").hidden = !lock.locked;
    $("biz-relock").hidden = !(lock.look_locks && lock.has_password && !lock.locked);
    $("biz-current").hidden = !lock.has_password;
    const back = `Back to my old look (${lock.back_label})`;
    $("biz-back").hidden = !on;
    $("biz-back").textContent = back;
    $("lock-banner-back").textContent = back;
    $("lock-go-back").textContent = back;
    if (state.settings) paintCompanies();
  }

  function openPrompt(why, back = false) {
    backAsked = back;
    $("lock-why").textContent = why
      || "Enter the password to change settings. It stays unlocked for 10 minutes, or until you lock it again.";
    $("lock-submit").textContent = back ? "Unlock and go back" : "Unlock";
    $("lock-go-back").hidden = back || !lock.look_locks;
    $("lock-error").textContent = "";
    $("lock-password").value = "";
    $("lock-dialog").hidden = false;
    $("lock-password").focus();
  }

  function closePrompt() {
    backAsked = false;
    $("lock-dialog").hidden = true;
    $("lock-password").value = "";
  }

  // A save the lock refused (app.js flush): ask, then send it again.
  function refused(body) {
    refusedBody = { ...(refusedBody || {}), ...body };
    lock.locked = true;
    paint();
    if ($("lock-dialog").hidden) openPrompt("That change needs the password: Business mode is locked.");
  }

  // A step that is not a settings save (a reset) the lock refused: ask for
  // the password, then run `again` once it is unlocked.
  function ask(again) {
    retry = again;
    refused({});
  }

  // `viaBack`: the prompt's own "Back to my old look" button sent it.
  async function unlock(e, viaBack = false) {
    e.preventDefault();
    const password = $("lock-password").value;
    if (!password) {
      if (viaBack) { $("lock-error").textContent = "Type the password first."; $("lock-password").focus(); }
      return;
    }
    const back = backAsked || viaBack;
    try {
      update(await call("/api/lock/unlock", { password }));
    } catch (err) {
      $("lock-password").value = "";
      $("lock-error").textContent = err.message;
      return;
    }
    closePrompt();
    paint();
    say(`Unlocked until ${clock(lock.open_until)}.`);
    if (back) {
      // going back leaves Business: a change or reset it refused is dropped,
      // not saved into his own settings on the way out
      refusedBody = null;
      retry = null;
      goBack();
      return;
    }
    if (refusedBody && Object.keys(refusedBody).length) {
      Object.assign(state.pending, refusedBody);
      flush();
    }
    refusedBody = null;
    if (retry) { const again = retry; retry = null; again(); }
  }

  // Leave Business for the look before it (or the default look); while
  // locked, the password comes first and the prompt goes back once it opens.
  function goBack() {
    if (!lock.look_locks) return;
    if (lock.locked) {
      openPrompt(`Enter the Business password to go back to your old look (${lock.back_label}).`, true);
      return;
    }
    backSaid = lock.back_label;
    change("look", lock.back_look || "classic");
  }

  function cancel() {
    closePrompt();
    backSaid = "";
    if (refusedBody || retry) {
      refusedBody = null;
      retry = null;
      saidStatus("Not saved: Business mode is locked.");
    }
  }

  async function addCompany(e) {
    if (e) e.preventDefault();
    const name = $("biz-name").value.trim();
    if (!name) { say("Give the company a name first."); return; }
    let logo = "";
    if (logoData) {
      try {
        logo = (await call("/api/business/logo", { data: logoData })).logo;
      } catch (err) {
        if (err.status === 423) { retry = () => addCompany(); return refused({}); }
        say("The logo was not kept: " + err.message);
        return;
      }
    }
    const id = "c" + Date.now().toString(36);
    change("business_companies", companies().concat([{ id, name, logo }]));
    if (!state.settings.business_company) change("business_company", id);
    $("biz-name").value = "";
    $("biz-logo").value = "";
    $("biz-logo-name").textContent = "No logo picked";
    logoData = "";
    say(`${name} added.`);
  }

  function pickLogo() {
    const file = $("biz-logo").files[0];
    logoData = "";
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) { say("A logo can be up to 4 MB."); return; }
    const reader = new FileReader();
    reader.onload = () => { logoData = String(reader.result || ""); $("biz-logo-name").textContent = file.name; };
    reader.readAsDataURL(file);
  }

  async function savePassword(e) {
    e.preventDefault();
    const body = { current: $("biz-current").value, new: $("biz-new").value };
    try {
      update(await call("/api/lock/password", body));
    } catch (err) {
      say(err.message);
      return;
    } finally {
      $("biz-current").value = "";
      $("biz-new").value = "";
    }
    paint();
    say("Password saved.");
  }

  async function relock() {
    try { update(await call("/api/lock/relock", {})); } catch (err) { say(err.message); return; }
    paint();
    say("Locked.");
  }

  $("lock-form").addEventListener("submit", unlock);
  $("lock-cancel").addEventListener("click", cancel);
  $("lock-dialog").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); cancel(); } });
  $("lock-banner-open").addEventListener("click", () => openPrompt());
  $("biz-unlock").addEventListener("click", () => openPrompt());
  $("biz-relock").addEventListener("click", relock);
  $("biz-back").addEventListener("click", goBack);
  $("lock-banner-back").addEventListener("click", goBack);
  $("lock-go-back").addEventListener("click", (e) => unlock(e, true));
  $("biz-on").addEventListener("click", () => change("look", "business"));
  $("biz-add").addEventListener("submit", addCompany);
  $("biz-logo").addEventListener("change", pickLogo);
  $("biz-pass").addEventListener("submit", savePassword);
  // The window shuts by itself after 10 minutes: look again now and then.
  setInterval(() => { if (!document.hidden) refresh(); }, 20000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  refresh();

  return { paint, refresh, refused, openPrompt, ask, goBack };
})();
