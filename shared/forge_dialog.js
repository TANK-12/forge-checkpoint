/* In-page confirm / prompt / alert for Forge apps.

   The browser's own confirm(), prompt() and alert() freeze the whole Forge
   page while they are open (every app and the hub share one page process), and
   that stops the hub's background music, whose levelling runs through WebAudio
   on the page. These look like a Forge dialog, never block, and return a
   Promise:

     if (!(await ForgeDialog.confirm("Delete it?"))) return;
     const name = await ForgeDialog.prompt("Folder name", "old");  // null = cancelled
     await ForgeDialog.alert("Saved.");

   Enter answers OK, Escape cancels, a click outside cancels. */
(() => {
  if (window.ForgeDialog) return;

  function style() {
    if (document.getElementById("forge-dialog-style")) return;
    const s = document.createElement("style");
    s.id = "forge-dialog-style";
    s.textContent = `
.forge-dialog-back { position: fixed; inset: 0; z-index: 2147483600; display: grid; place-items: center;
  background: rgba(0, 0, 0, .45); }
.forge-dialog { min-width: min(360px, 92vw); max-width: min(520px, 92vw); display: grid; gap: 12px; padding: 18px;
  border-radius: 12px; background: var(--panel, #171a21); color: var(--text, #e7e9ee);
  border: 1px solid var(--border, #2a2f3a); box-shadow: 0 18px 48px rgba(0, 0, 0, .5);
  font: 14px/1.45 system-ui, sans-serif; }
.forge-dialog p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.forge-dialog input { font: inherit; color: inherit; background: var(--panel-2, #1e222b);
  border: 1px solid var(--border, #2a2f3a); border-radius: 6px; padding: 7px 10px; }
.forge-dialog .row { display: flex; justify-content: flex-end; gap: 8px; }
.forge-dialog button { font: inherit; cursor: pointer; padding: 6px 14px; border-radius: 6px;
  color: var(--text, #e7e9ee); background: var(--panel-2, #1e222b); border: 1px solid var(--border, #2a2f3a); }
.forge-dialog button.ok { background: var(--accent, #6ea8fe); color: var(--on-accent, #0b1220); border-color: var(--accent, #6ea8fe); }`;
    document.head.appendChild(s);
  }

  // Resolves with the typed text (prompt), true (OK) or null (cancelled).
  function open(text, { input = false, value = "", ok = "OK", cancel = "Cancel" } = {}) {
    style();
    return new Promise((resolve) => {
      const back = document.createElement("div");
      back.className = "forge-dialog-back";
      const box = document.createElement("div");
      box.className = "forge-dialog";
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-modal", "true");
      const p = document.createElement("p");
      p.textContent = String(text ?? "");
      box.appendChild(p);
      let field = null;
      if (input) {
        field = document.createElement("input");
        field.value = String(value ?? "");
        box.appendChild(field);
      }
      const row = document.createElement("div");
      row.className = "row";
      const done = (answer) => { back.remove(); document.removeEventListener("keydown", keys, true); resolve(answer); };
      if (cancel) {
        const no = document.createElement("button");
        no.type = "button"; no.textContent = cancel;
        no.onclick = () => done(null);
        row.appendChild(no);
      }
      const yes = document.createElement("button");
      yes.type = "button"; yes.className = "ok"; yes.textContent = ok;
      yes.onclick = () => done(field ? field.value : true);
      row.appendChild(yes);
      box.appendChild(row);
      back.appendChild(box);
      back.addEventListener("mousedown", (e) => { if (e.target === back) done(cancel ? null : true); });
      function keys(e) {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); done(cancel ? null : true); }
        else if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); yes.click(); }
      }
      document.addEventListener("keydown", keys, true);
      document.body.appendChild(back);
      (field || yes).focus();
      if (field) field.select();
    });
  }

  window.ForgeDialog = {
    confirm: (text, opts) => open(text, opts).then((v) => v !== null),
    prompt: (text, value = "") => open(text, { input: true, value }),
    alert: (text) => open(text, { cancel: null }).then(() => undefined),
  };
})();
