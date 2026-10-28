/* The About card's top: Forge's version, edition and licence, adding or
   removing a licence file, and the support report.

   Everything comes from /api/about (about_api.py over shared/forge_edition.py),
   so the card holds no rules of its own. A licence file is read in the page
   and sent as text; the backend checks it offline and refuses a bad one
   without writing anything. While the Business lock is shut, adding or
   removing a licence answers 423 and the card says to unlock first. The
   support report is a new zip in Downloads with home paths, emails and keys
   scrubbed out; the card says where it went. */
const About = (() => {
  async function call(path, body) {
    let r;
    try {
      r = await fetch(path, {
        method: body === undefined ? "GET" : "POST",
        headers: { "Content-Type": "application/json", "X-Forge": "1" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      throw new Error("the Settings backend is not answering");
    }
    let data = {};
    try { data = await r.json(); } catch (e) {}
    if (r.status === 423) throw new Error("Settings are locked. Unlock them in the Business card first.");
    if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : `error ${r.status}`);
    return data;
  }

  function say(text, bad) {
    const el = $("about-said");
    el.textContent = text;
    el.classList.toggle("bad", !!bad);
  }

  function row(label, value) {
    const div = document.createElement("div");
    div.className = "about-row";
    const k = document.createElement("span");
    k.className = "muted";
    k.textContent = label;
    const v = document.createElement("span");
    v.textContent = value;
    div.append(k, v);
    return div;
  }

  // The badge beside the edition's name says where the licence stands.
  const STATE_WORDS = {
    free: "Free",
    valid: "Licensed",
    invalid: "Licence not valid",
    expired: "Licence expired",
    past_updates: "Licensed, updates ended",
  };

  function show(a) {
    $("about-name").textContent = a.label;
    $("about-version").textContent = a.version ? `version ${a.version}` : "";
    $("about-edition").textContent = STATE_WORDS[a.state] || a.state;
    $("about-line").textContent = a.line;
    $("about-line").classList.toggle("bad", a.state === "invalid" || a.state === "expired" || a.state === "past_updates");
    const rows = $("about-rows");
    rows.replaceChildren();
    if (a.licensee) rows.append(row("Licensed to", a.licensee));
    if (a.licensed_label && a.licensed_label !== a.label) rows.append(row("Licence for", a.licensed_label));
    if (a.seats) rows.append(row("Seats", String(a.seats)));
    if (a.updates_until) rows.append(row("Updates until", a.updates_until));
    if (a.expires) rows.append(row("Expires", a.expires));
    if (a.licence_id) rows.append(row("Licence", a.licence_id));
    if (a.released) rows.append(row("This build", a.released));
    $("licence-remove").hidden = a.state === "free";
    const list = $("about-features");
    list.replaceChildren();
    for (const f of a.features || []) {
      const li = document.createElement("li");
      li.textContent = `${f.what} (${f.edition_label})`;
      list.append(li);
    }
    $("about-enforced").textContent = a.enforced
      ? "Features outside this edition are switched off."
      : "Editions are declared but not enforced yet: every feature still works in every edition.";
  }

  async function load() {
    try { show(await call("/api/about")); } catch (e) { say(`Could not read the licence: ${e.message}`, true); }
  }

  async function addFile(file) {
    if (!file) return;
    if (file.size > 16384) { say("That file is too big to be a Forge licence.", true); return; }
    try {
      const a = await call("/api/about/licence", { text: await file.text() });
      show(a);
      say(`Licence added: ${a.line}`);
    } catch (e) {
      say(e.message, true);
    }
  }

  async function remove() {
    const text = "Remove this licence? Forge becomes the free edition. The file is kept beside it, renamed, not deleted.";
    if (!(await ForgeDialog.confirm(text, { ok: "Remove licence" }))) return;
    try {
      const a = await call("/api/about/licence/remove", {});
      show(a);
      say(a.moved_to ? `Licence removed; the old file is kept as ${a.moved_to}.` : "There was no licence file.");
    } catch (e) {
      say(e.message, true);
    }
  }

  async function report() {
    const btn = $("support-report");
    btn.disabled = true;
    say("Making the report…");
    try {
      const r = await call("/api/about/report", {});
      say(`Report saved as ${r.name} in ${r.folder} (${Math.max(1, Math.round(r.bytes / 1024))} KB). `
        + "Home folders, emails and keys are scrubbed out; open it to check before sending it to anyone.");
    } catch (e) {
      say(e.message, true);
    } finally {
      btn.disabled = false;
    }
  }

  function wire() {
    const input = $("licence-file");
    $("licence-add").addEventListener("click", () => input.click());
    input.addEventListener("change", () => { addFile(input.files[0]); input.value = ""; });
    $("licence-remove").addEventListener("click", remove);
    $("support-report").addEventListener("click", report);
    load();
  }

  wire();
  return { load };
})();
