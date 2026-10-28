/* Where your things are kept: the place in use, how much is there, Move
   (forge_portable.Launcher.move: every app stops, a verified copy, the
   pointer switched, the old copy kept and renamed), and the welcome again. */
(() => {
  const { ask, listen, h, icon, chooser, add } = window.ForgePlace;
  const card = document.getElementById("card");

  let state = null;
  let watching = false; // this page saw the move start: it shows how it ends
  let leaving = false;
  let timer = 0;

  const go = (where) => { leaving = true; location.replace(where); };

  function page() {
    const p = state.place;
    if (!p) return go("/hub/welcome.html");
    const sizeLine = h("dd", {}, h("span.waiting", {}, h("span.spin"), "Counting…"));
    const moveBox = h("div");
    card.textContent = "";
    add(card,
      h("h1", {}, "Where your things are kept"),
      h("p.lead", {}, "Your settings, saves and everything you make in Forge's apps."),
      h("dl.facts", {},
        h("dt", {}, "Folder"), h("dd", {}, h("span.path", {}, p.root)),
        h("dt", {}, "On"), h("dd", {}, p.on_computer ? "This computer" : p.drive,
          p.removable ? h("span.tag", {}, "removable") : null,
          p.fs ? h("span.tag", {}, p.fs.toUpperCase()) : null),
        h("dt", {}, "Size"), sizeLine,
        h("dt", {}, "Free there"), h("dd", {}, p.free_text || "unknown"),
      ),
      p.removable
        ? h("div.note", {}, icon("lock"), h("span", {}, `Forge opens only while ${p.drive} is plugged in. Quit Forge before you unplug it.`))
        : null,
      h("hr.soft"),
      h("h2", { style: "margin-top:0" }, "Move them"),
      moveBox,
      h("hr.soft"),
      h("div.row", {},
        h("button.btn", { type: "button", onclick: () => go("/hub/welcome.html?again=1") }, "Run the welcome again"),
        h("span.quiet.small", {}, "Look at where things are kept, and the look and text size."),
      ),
      h("div.foot", {},
        h("span.quiet.small", {}, state.version ? `Forge ${state.version}` : ""),
        h("button.btn.primary", { type: "button", onclick: () => go("/hub/index.html") }, "Back to Forge"),
      ),
    );
    sizeOf(sizeLine);
    if (!state.remember) {
      add(moveBox, h("p.quiet", {},
        "This Forge was started with --data, for this run only, so Move is off."));
      return;
    }
    moveForm(moveBox);
  }

  async function sizeOf(line) {
    let answer = null;
    try { answer = await ask("size"); } catch (e) { answer = null; }
    line.textContent = answer && answer.ok
      ? `${answer.text} in ${answer.files.toLocaleString()} file${answer.files === 1 ? "" : "s"}`
      : "unknown";
  }

  function moveForm(box) {
    const button = h("button.btn.primary", { type: "button", disabled: true }, "Move");
    const said = h("div.verdict");
    const mount = h("div");
    add(box,
      h("p.quiet", {},
        "Choose the new place. Forge stops every app, copies your things there, checks every file, ",
        "then carries on from the new place. The old copy stays where it is, renamed ",
        "“Forge data (old copy, date)”, until you delete it yourself."),
      mount,
      h("div.row.end", { style: "margin-top:14px" }, button),
      said,
    );
    const p = state.place || {};
    const picked = chooser(mount, {
      move: true,
      computer: p.on_computer ? null : { path: state.computer, free: state.computer_free },
      onChange: (answer) => { button.disabled = !(answer && answer.ok); },
    });
    button.addEventListener("click", async () => {
      const target = picked.checked();
      if (!target || !target.ok) return;
      button.disabled = true;
      said.textContent = "";
      let answer;
      try {
        answer = await ask("move", { path: target.folder });
      } catch (e) {
        answer = { ok: false, problem: "Forge did not answer. Is it still running?" };
      }
      if (!answer.ok) {
        button.disabled = false;
        add(said, h("div.bad", {}, answer.problem || "The move did not start."));
        return;
      }
      watching = true;
      route(await ask("state"));
    });
  }

  // -- a move under way, and how it ended --------------------------------------

  function moving() {
    const m = state.move || {};
    const done = m.phase === "done";
    const failed = m.phase === "failed";
    const fill = h("div", { class: "bar-fill" + (done || failed ? "" : " busy") });
    if (done) fill.style.width = "100%";
    card.textContent = "";
    add(card,
      h("div", { class: `icon-big ${failed ? "bad" : ""}` }, icon(failed ? "warn" : "box")),
      h("h1", {}, done ? "Your things have moved" : failed ? "The move did not finish" : "Moving your things"),
    );
    if (!done && !failed) {
      add(card,
        h("p.lead", {}, "Every app is stopped until this is done. Keep the drive plugged in."),
        h("dl.facts", {},
          h("dt", {}, "From"), h("dd", {}, h("span.path", {}, m.from || "")),
          h("dt", {}, "To"), h("dd", {}, h("span.path", {}, m.to || ""))),
        h("div.bar-track", {}, fill),
        h("p.quiet", {}, capital(m.text || "Working")),
      );
      return;
    }
    if (done) {
      add(card,
        h("p.lead", {}, "Forge now keeps them in ", h("span.path", {}, m.to || "")),
        h("p", {}, "Every file was checked after the copy. The old copy is still at ",
          h("span.path", {}, m.old || m.from || ""),
          ". Forge never uses it again; delete it yourself once you are happy."),
      );
    } else {
      add(card,
        h("p.lead", {}, "Nothing changed: your things are still in ", h("span.path", {}, m.from || ""), "."),
        h("p.quiet", {}, capital(m.text || "")),
      );
    }
    add(card, h("div.foot", {},
      h("button.btn", { type: "button", onclick: () => { watching = false; page(); } }, "Where your things are kept"),
      h("button.btn.primary", { type: "button", onclick: () => go("/hub/index.html") }, "Back to Forge"),
    ));
  }

  const capital = (text) => (text ? text[0].toUpperCase() + text.slice(1) : "");

  function route(next) {
    state = next;
    if (leaving) return;
    // the look the welcome or Settings chose (the launcher reads it only
    // while a place is in use, so a move keeps the one already shown)
    if (state.mode === "ready") document.body.classList.toggle("light", state.look === "light");
    if (state.mode === "welcome" || state.mode === "problem") {
      // a pulled drive, or a failed move that could not go back
      if (!(watching && state.move && state.move.phase === "failed")) return go("/hub/welcome.html");
    }
    if (state.mode === "moving") {
      watching = true;
      clearTimeout(timer);
      timer = setTimeout(poll, 700);
      return moving();
    }
    if (watching) return moving();
    page();
  }

  async function poll() {
    if (leaving) return;
    try {
      route(await ask("state"));
    } catch (e) {
      timer = setTimeout(poll, 1500);
    }
  }

  async function start() {
    try {
      route(await ask("state"));
    } catch (e) {
      card.textContent = "";
      add(card, h("h1", {}, "Forge is not answering"), h("p.lead", {}, "Close this window and start Forge again."));
      return;
    }
    listen((next) => {
      // the move's own polling shows its progress; this catches the rest
      if (state && state.mode === "moving" && next.mode === "moving") return;
      route(next);
    });
  }

  start();
})();
