/* Resets in layers and Pick for my machine.

   Every reset goes the same way: ask the backend what it would change
   (/api/reset/preview), show that in a dialog that asks first, then run it
   (/api/reset), which keeps a copy of the settings beforehand; the toast that
   follows has Undo (/api/reset/undo). Three layers use it:
     - the button at the foot of each page (app.js builds it, paint() keeps
       its count) and of each System panel that names a group (system.js),
     - the Reset groups card: settings that belong together, from
       reset_groups.json (visual effects, power, Wi-Fi and Bluetooth, ...),
     - Reset all settings at the very bottom, in About.
   A group with System actions (forget Wi-Fi networks, Bluetooth devices)
   lists each with a tick box; those cannot be undone and say so.
   While the Business look is locked the backend answers 423 and the
   password prompt opens; the reset runs once it is unlocked.

   Pick for my machine reads the hardware (/api/machine) and fills in a visual
   level and a power choice, applied to Forge, Forge Desktop or both through
   the same dialog, backup and Undo. */
const Resets = (() => {
  "use strict";
  const H = { "Content-Type": "application/json", "X-Forge": "1" };
  const post = (path, body) => api(path, { method: "POST", headers: H, body: JSON.stringify(body) });
  const MAX_LINES = 8;
  let kept = new Set();  // settings a page reset leaves alone (/api/reset/groups)
  let asking = false;    // a preview or dialog is under way: a second click waits

  function el(tag, attrs, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) node.append(kid);
    return node;
  }

  /* ------------------------------------------------------------ the dialog */

  // ask({title, intro, lines, steps, ok, note, empty}) -> null (cancelled)
  // or {system: {"panel/action": {option: value}}} for the ticked steps.
  // `empty` is what it says when there is nothing to do.
  function ask({ title, intro, lines, steps, ok, note, empty }) {
    const box = $("reset-dialog");
    if (!box.hidden) return Promise.resolve(null);  // one dialog at a time
    const back = document.activeElement;
    return new Promise((done) => {
      const ticks = (steps || []).map((step) => {
        const on = el("input", { type: "checkbox", checked: true });
        const opt = step.option ? el("input", { type: "checkbox", checked: true }) : null;
        const row = el("div", { class: "rd-step" },
          el("label", {}, on, ` ${step.label}`),
          opt && el("label", { class: "rd-opt" }, opt, ` ${step.option.label}`));
        on.addEventListener("change", () => { if (opt) opt.disabled = !on.checked; refresh(); });
        return { step, on, opt, row };
      });
      const shown = (lines || []).slice(0, MAX_LINES).map((line) => el("li", { text: line }));
      if ((lines || []).length > MAX_LINES) shown.push(el("li", { class: "muted", text: `and ${lines.length - MAX_LINES} more` }));
      const nothing = !(lines || []).length && !ticks.length;
      const okBtn = el("button", { class: "btn btn-danger", type: "button", id: "reset-ok", text: ok || "Reset" });
      const cancel = el("button", { class: "btn", type: "button", id: "reset-cancel", text: nothing ? "Close" : "Cancel" });
      function refresh() { okBtn.disabled = !(lines || []).length && !ticks.some((t) => t.on.checked); }
      function close(answer) {
        box.hidden = true;
        box.replaceChildren();
        document.removeEventListener("keydown", onKey, true);
        if (back && back.isConnected && back.focus) back.focus();
        done(answer);
      }
      function onKey(e) {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(null); }
      }
      okBtn.addEventListener("click", () => {
        const system = {};
        ticks.filter((t) => t.on.checked).forEach((t) => {
          system[t.step.id] = t.opt ? { [t.step.option.key]: t.opt.checked } : {};
        });
        close({ system });
      });
      cancel.addEventListener("click", () => close(null));
      box.replaceChildren(el("div", { class: "lock-box reset-box", role: "dialog", "aria-modal": "true", "aria-labelledby": "reset-title" },
        el("h3", { id: "reset-title", text: title }),
        el("p", { class: "muted small", text: nothing ? empty || "Everything here is already at its default." : intro || "" }),
        shown.length ? el("ul", { class: "rd-list" }, shown) : null,
        ticks.length ? el("div", { class: "rd-steps" }, ticks.map((t) => t.row)) : null,
        !nothing && note ? el("p", { class: "muted small rd-note", text: note }) : null,
        el("div", { class: "lock-row" }, cancel, nothing ? null : okBtn)));
      refresh();
      box.hidden = false;
      document.addEventListener("keydown", onKey, true);
      (nothing ? cancel : okBtn.disabled ? cancel : okBtn).focus();
    });
  }

  /* ---------------------------------------------------- running and undo */

  // One request that changes many settings, run like the old full reset: a
  // save already on its way lands first, so its late answer cannot put an old
  // value back; a change not yet saved is dropped only once this has worked.
  async function commit(request, said) {
    if (state.resetting) return null;  // one at a time
    clearTimeout(state.timer);
    stopRetry();
    state.resetting = true;
    for (let i = 0; state.saving && i < 100; i++) await new Promise((ok) => setTimeout(ok, 100));
    let r = null;
    try {
      r = await request();
      state.epoch++;
      state.pending = {};
      state.resetting = false;
      accept(r);
    } catch (e) {
      state.resetting = false;
      if (e.status === 423 && typeof Business !== "undefined") {
        Business.ask(() => commit(request, said));  // asks for the password, then runs it
      } else {
        saidStatus(`Not done: ${e.message}`);
      }
      if (Object.keys(state.pending).length) {
        if (e.offline) startRetry();
        else flush();
      }
      return null;
    } finally {
      state.resetting = false;
    }
    const failed = r.failed || [];
    saidStatus(failed.length ? `${said}, but ${failed.join("; ")}` : said);
    toast(failed.length ? `${said}. Not done: ${failed.join("; ")}` : said, r.backup);
    window.dispatchEvent(new CustomEvent("forge-reset"));
    loadGroups();
    return r;
  }

  let toastTimer = 0;
  function toast(text, backup) {
    const t = $("reset-toast");
    clearTimeout(toastTimer);
    t.replaceChildren(el("span", { text }),
      backup ? el("button", { type: "button", class: "btn", text: "Undo", onclick: () => undo(backup) }) : null,
      el("button", { type: "button", class: "linkish", "aria-label": "Close", text: "✕", onclick: () => { t.hidden = true; } }));
    t.hidden = false;
    toastTimer = setTimeout(() => { t.hidden = true; }, 20000);
  }

  function undo(backup) {
    $("reset-toast").hidden = true;
    return commit(() => post("/api/reset/undo", { backup }), "Put back as it was");
  }

  // A reset: preview, ask, run. `target` is {section}, {group}, {keys, label}
  // or {all: true}.
  async function run(target, title) {
    if (asking) return null;
    asking = true;
    try {
      return await runNow(target, title);
    } finally {
      asking = false;
    }
  }

  async function runNow(target, title) {
    let p;
    try {
      p = await post("/api/reset/preview", target);
    } catch (e) {
      saidStatus(`Could not check: ${e.message}`);
      return null;
    }
    const lines = p.changes.map((c) => `${c.label}: ${c.now} → ${c.default}`);
    if (p.autoclose.length) lines.push(`Auto-close rules for ${p.autoclose.join(", ")}`);
    const steps = p.system || [];
    const answer = await ask({
      title: title || `Reset ${p.label}?`,
      intro: lines.length
        ? `${lines.length === 1 ? "This goes" : `These ${lines.length} go`} back to the default:`
        : "Choose what to do:",
      lines,
      steps,
      ok: target.all ? "Reset everything" : "Reset",
      note: (target.all ? "Your app folders, hidden apps, saved size mixes and companies stay. " : "")
        + (lines.length ? "A copy of your settings is kept first, so Undo puts them back." : "")
        + (steps.length ? " Forgotten networks and devices cannot be undone: you join or pair them again." : ""),
    });
    if (!answer) return null;
    return commit(() => post("/api/reset", { ...target, system: answer.system }), `${p.label}: reset`);
  }

  // The page buttons: how many of the page's settings differ, or "all at
  // default" (disabled), kept current by app.js's renderControls.
  function paint() {
    document.querySelectorAll("[data-reset-keys]").forEach((b) => {
      const n = b.dataset.resetKeys.split(/\s+/).filter((k) => k && !kept.has(k)).filter(isChanged).length;
      b.disabled = !n;
      b.textContent = n ? `Reset this page (${n} changed)` : "All at default";
      b.title = n ? "Put this page's settings back to their defaults (asks first, can be undone)" : "Nothing on this page differs from its default";
    });
  }

  /* ------------------------------------------- groups card and About card */

  function when(seconds) {
    const d = new Date(seconds * 1000);
    const day = d.toDateString() === new Date().toDateString() ? "today" : d.toLocaleDateString([], { day: "numeric", month: "short" });
    return `${day} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  }

  async function loadGroups() {
    let data;
    try {
      data = await api("/api/reset/groups");
    } catch (e) {
      $("rg-list").replaceChildren(el("p", { class: "muted small", text: `Could not list them: ${e.message}` }));
      return;
    }
    kept = new Set(data.kept || []);
    paint();
    $("rg-list").replaceChildren(...data.groups.filter((g) => g.card).map((g) => el("div", { class: "rg-row item", "data-search": `reset ${g.label} ${g.about}` },
      el("div", { class: "grow" }, el("div", { class: "rg-name", text: g.label }), el("div", { class: "muted small", text: g.about })),
      el("button", { type: "button", class: "btn", text: "Reset…", "data-reset-group": g.id, onclick: () => run({ group: g.id }) }))));
    const list = data.backups || [];
    $("rb-list").replaceChildren(...(list.length ? list.slice(0, 5).map((b) => el("div", { class: "rb-row" },
      el("span", { class: "grow", text: `${when(b.when)}, before ${b.label}` }),
      el("button", { type: "button", class: "btn", text: "Put back", onclick: () => restore(b) })))
      : [el("p", { class: "muted small", text: "None yet: every reset keeps one here." })]));
  }

  async function restore(b) {
    const answer = await ask({
      title: "Put these settings back?",
      intro: `Your settings as they were ${when(b.when)}, before ${b.label}. The ones you have now are kept as a copy too.`,
      lines: [`Settings saved ${when(b.when)}`],
      steps: [],
      ok: "Put back",
    });
    if (answer) undo(b.id);
  }

  /* ----------------------------------------------------- Pick for my machine */

  const machine = { data: null, visual: "", power: "" };

  function facts(m) {
    const lines = [];
    lines.push(`CPU: ${m.cpu || "not readable here"}${m.threads ? `, ${m.threads} threads` : ""}`);
    lines.push(`Graphics: ${(m.gpus || []).join(", ") || "not readable here"}`);
    lines.push(`Memory: ${m.ram_gb ? `${Math.round(m.ram_gb)} GB` : "not readable here"}`);
    lines.push(`Power: ${m.has_battery === false ? "no battery, always on mains" : m.on_battery ? "on battery now" : m.has_battery ? "on the charger" : "not readable here"}`);
    const w = m.watts || {};
    if (w.sustained) lines.push(`CPU power limit: ${w.sustained} W sustained${w.burst ? `, ${w.burst} W burst` : ""} (the Power app sets these)`);
    return lines;
  }

  function seg(box, list, chosen, picked, onpick) {
    box.replaceChildren(...list.map((c) => el("button", {
      type: "button", "data-v": c.id, title: c.about, class: c.id === chosen ? "on" : null,
      onclick: () => onpick(c.id),
    }, c.label, c.id === picked ? el("span", { class: "mc-tag", text: " picked" }) : null)));
  }

  function paintMachine() {
    const d = machine.data;
    if (!d) return;
    seg($("mc-visual"), d.choices.visual, machine.visual, d.pick.visual, (v) => { machine.visual = v; paintMachine(); });
    seg($("mc-power"), d.choices.power, machine.power, d.pick.power, (v) => { machine.power = v; paintMachine(); });
    const about = (list, id) => (list.find((c) => c.id === id) || {}).about || "";
    $("mc-about").textContent = `${about(d.choices.visual, machine.visual)} ${about(d.choices.power, machine.power)}`;
  }

  async function loadMachine() {
    $("mc-facts").replaceChildren(el("p", { class: "muted small", text: "Reading this machine…" }));
    try {
      machine.data = await api("/api/machine");
    } catch (e) {
      $("mc-facts").replaceChildren(el("p", { class: "muted small", text: `Could not read it: ${e.message}` }));
      return;
    }
    machine.visual = machine.data.pick.visual;
    machine.power = machine.data.pick.power;
    $("mc-facts").replaceChildren(el("ul", { class: "mc-list" }, facts(machine.data.machine).map((t) => el("li", { text: t }))));
    $("mc-why").textContent = `Why: ${machine.data.pick.why.join(" ")}`;
    paintMachine();
  }

  async function applyMachine() {
    if (!machine.data) { saidStatus("This machine could not be read: try Read again"); return; }
    if (asking) return;
    asking = true;
    try {
      await applyNow();
    } finally {
      asking = false;
    }
  }

  async function applyNow() {
    const targets = [["forge", $("mc-forge").checked], ["desktop", $("mc-desktop").checked]].filter(([, on]) => on).map(([t]) => t);
    if (!targets.length) { saidStatus("Tick Forge, Forge Desktop or both"); return; }
    const body = { visual: machine.visual, power: machine.power, targets };
    let p;
    try {
      p = await post("/api/machine/preview", body);
    } catch (e) {
      saidStatus(`Could not check: ${e.message}`);
      return;
    }
    const label = (kind, id) => (machine.data.choices[kind].find((c) => c.id === id) || {}).label || id;
    const answer = await ask({
      title: `${label("visual", machine.visual)} visual effects, ${label("power", machine.power)} power use?`,
      intro: `For ${targets.map((t) => (t === "forge" ? "Forge" : "Forge Desktop")).join(" and ")}, these change:`,
      lines: p.changes.map((c) => `${c.label}: ${c.now} → ${c.to}`),
      steps: [],
      ok: "Apply",
      note: "A copy of your settings is kept first, so Undo puts them back.",
      empty: "Everything here is already set that way.",
    });
    if (answer) commit(() => post("/api/machine/apply", body), "Picked for this machine");
  }

  /* ------------------------------------------------------------ wiring */

  // A hand-made card with data-reset-label (Wallpaper, Colour) gets the same
  // foot button for the settings it lists in data-settings.
  document.querySelectorAll("section[data-reset-label][data-settings]").forEach((card) => {
    const keys = card.dataset.settings.split(/\s+/).filter(Boolean);
    const b = el("button", { type: "button", class: "btn reset-sec", "data-reset-keys": keys.join(" "),
      onclick: () => run({ keys, label: card.dataset.resetLabel }) });
    card.append(el("div", { class: "card-foot" }, b));
  });
  $("reset").addEventListener("click", () => run({ all: true }, "Reset all settings?"));
  loadGroups();
  // a release leaves Pick for my machine out (FORGE_CUT_PAGES)
  if ($("machine-panel")) {
    $("mc-apply").addEventListener("click", applyMachine);
    $("mc-again").addEventListener("click", loadMachine);
    // Reading the machine runs lspci: only once its card is first on screen.
    const seen = new IntersectionObserver((hits) => {
      if (!hits.some((h) => h.isIntersecting)) return;
      seen.disconnect();
      loadMachine();
    });
    seen.observe($("machine-panel"));
  }
  paint();

  return { run, paint, ask, commit };
})();
