/* The welcome (first launch), the problem screen (the place for the user's
   things cannot be used now), and the welcome again (?again=1, from the
   data page). Three short steps: Hello, where your things are kept, how
   Forge looks. Every request goes through place.js to the launcher. */
(() => {
  const { ask, listen, h, icon, chooser, add } = window.ForgePlace;
  const card = document.getElementById("card");
  const again = new URLSearchParams(location.search).has("again");
  const STEPS = ["Hello", "Your things", "The look"];

  let state = null;
  let place = null; // the checked answer for the chosen place
  // A place that already holds Forge data keeps its own look and size
  // unless the user picks another (critic round E1).
  let lookFor = "", lookPicked = false, sizePicked = false;
  // ...and when that look is not Dark or Light, neither is pressed (critic
  // round F1: Dark showed pressed over a Sakura place).
  let ownLook = false;
  let placeChoice = null; // how it was chosen, so Back reopens on it
  let look = "dark";
  let size = "Default";
  let fromProblem = false;
  let leaving = false;
  let shown = ""; // "steps", or "problem:<why>" for the problem screen

  const go = (where) => { leaving = true; location.replace(where); };

  function frame(index, ...body) {
    shown = "steps";
    card.textContent = "";
    add(card,
      h("ol.steps", { "aria-label": "Steps" }, STEPS.map((name, i) =>
        h("li", { class: i === index ? "on" : i < index ? "past" : "", "aria-current": i === index ? "step" : null }, name))),
      ...body,
    );
    const first = card.querySelector("h1");
    if (first) { first.tabIndex = -1; first.focus({ preventScroll: true }); }
  }

  function foot(back, next) {
    return h("div.foot", {}, back || h("span"), next);
  }

  // -- the steps ---------------------------------------------------------------

  function hello() {
    frame(0,
      h("h1", {}, again ? "The welcome, again" : "Welcome to Forge"),
      h("p.lead", {},
        "One window for your tools: writing, pictures, music, games and more. ",
        "Everything runs on this computer."),
      h("p.quiet", {}, again
        ? "Look at where your things are kept, and change how Forge looks."
        : "Two quick choices and you are in. You can change both later."),
      foot(
        h("span.quiet.small", {}, state.version ? `Version ${state.version}` : ""),
        h("button.btn.primary.big", { type: "button", onclick: where }, again ? "Next" : "Get started"),
      ),
    );
  }

  function where() {
    if (again && state.place) return whereNow();
    const next = h("button.btn.primary.big", { type: "button", disabled: true, onclick: () => { place = picked.checked(); placeChoice = picked.choice(); placeLook(); theLook(); } }, "Next");
    const back = fromProblem
      ? h("button.btn", { type: "button", onclick: problem }, "Back")
      : h("button.btn", { type: "button", onclick: hello }, "Back");
    const mount = h("div");
    frame(1,
      h("h1", {}, "Where should Forge keep your things?"),
      h("p.lead", {}, "Your settings, saves and everything you make in Forge's apps. You can move them later."),
      mount,
      fromProblem && state.problem
        ? h("div.note", {}, icon("box"), h("span", {},
            "A new place starts with a fresh Forge. Your things in ",
            h("span.path", {}, state.problem.root), " stay where they are."))
        : null,
      h("div.note", {}, icon("lock"), h("span", {},
        "Your things stay on this computer or on that drive. Nothing is uploaded.")),
      foot(back, next),
    );
    const picked = chooser(mount, {
      computer: { path: state.computer, free: state.computer_free },
      initial: placeChoice,
      onChange: (answer) => { next.disabled = !(answer && answer.ok); },
    });
  }

  function whereNow() {
    const p = state.place;
    frame(1,
      h("h1", {}, "Where your things are kept"),
      h("p.lead", {}, p.on_computer ? "On this computer, in" : `On ${p.drive}, in`),
      h("p", {}, h("span.path", {}, p.root)),
      h("p.quiet", {}, p.free_text ? `${p.free_text} free there.` : ""),
      h("p", {}, "To keep them somewhere else, ",
        h("a", { href: "/hub/data.html" }, "move them"),
        ": Forge copies everything, checks every file, and keeps the old copy."),
      foot(
        h("button.btn", { type: "button", onclick: hello }, "Back"),
        h("button.btn.primary.big", { type: "button", onclick: theLook }, "Next"),
      ),
    );
  }

  function placeLook() {
    if (!place || !place.adopt || place.folder === lookFor) return;
    lookFor = place.folder;
    look = place.look || "dark";
    size = place.size || "";
    ownLook = !!place.own_look;
    lookPicked = sizePicked = false;
    document.body.classList.toggle("light", look === "light");
  }

  function theLook() {
    const sample = h("div.sample", {}, "This is how big text will be in Forge's own pages and menus.");
    const looks = ["dark", "light"].map((name) =>
      h("button.choice", { type: "button", "aria-pressed": String(!ownLook && look === name), onclick: () => pickLook(name) },
        h("div", { class: `look-pic ${name}` },
          h("div.bar", {}, h("i"), h("i"), h("i")),
          h("div.tiles", {}, h("i"), h("i"), h("i"), h("i"))),
        h("span.title", {}, h("span.dot"), name === "dark" ? "Dark" : "Light"),
      ));
    const presets = state.presets && state.presets.length
      ? state.presets
      : [{ name: "Default", text_scale: 1 }];
    const sizes = presets.map((p) =>
      h("button.size", { type: "button", "aria-pressed": String(size === p.name), onclick: () => pickSize(p) },
        h("span.aa", { style: `font-size:${Math.round(17 * (p.text_scale || 1))}px` }, "Aa"),
        h("span.nm", {}, p.name)));
    const done = h("button.btn.primary.big", { type: "button", onclick: () => finish(done) },
      again ? "Done" : "Open Forge");
    frame(2,
      h("h1", {}, "How should Forge look?"),
      h("p.lead", {}, place && place.adopt && !(lookPicked || sizePicked)
        ? "Your things already have a look: leave this as it is to keep it, or pick another. Settings has many more themes and sizes."
        : "Settings has many more themes and sizes."),
      h("div.choices.two", {}, looks),
      h("h2", {}, "Text size"),
      h("div.sizes", { role: "group", "aria-label": "Text size" }, sizes),
      sample,
      h("div.verdict", { id: "finish-problem" }),
      foot(h("button.btn", { type: "button", onclick: where }, "Back"), done),
    );
    const chosen = presets.find((p) => p.name === size) || presets[0];
    sample.style.setProperty("--sample", chosen.text_scale || 1);

    function pickLook(name) {
      look = name;
      lookPicked = true;
      ownLook = false;
      document.body.classList.toggle("light", name === "light");
      looks.forEach((b, i) => b.setAttribute("aria-pressed", String(["dark", "light"][i] === name)));
    }
    function pickSize(p) {
      size = p.name;
      sizePicked = true;
      sizes.forEach((b, i) => b.setAttribute("aria-pressed", String(presets[i].name === p.name)));
      sample.style.setProperty("--sample", p.text_scale || 1);
    }
  }

  async function finish(button) {
    const problemLine = document.getElementById("finish-problem");
    button.disabled = true;
    button.textContent = again ? "Saving…" : "Setting up your place…";
    let answer;
    try {
      answer = again
        ? await ask("done", { size, look })
        : await ask("use", {
          path: place && place.folder,
          size: place && place.adopt && !sizePicked ? null : size,
          look: place && place.adopt && !lookPicked ? null : look,
        });
    } catch (e) {
      answer = { ok: false, problem: "Forge did not answer. Is it still running?" };
    }
    if (answer.ok) return go(answer.go || "/hub/index.html");
    button.disabled = false;
    button.textContent = again ? "Done" : "Open Forge";
    problemLine.textContent = "";
    add(problemLine, h("div.bad", {}, answer.problem || "That did not work."),
      again ? null : h("button.link", { type: "button", onclick: where }, "Choose another place"));
  }

  // -- the problem screen --------------------------------------------------------

  function problemText(p) {
    const drive = p.drive && p.drive !== "this computer" ? p.drive : "";
    const root = h("span.path", {}, p.root);
    switch (p.why) {
      case "missing":
        return drive
          ? { icon: "plug", tone: "", title: `Your Forge data is on ${drive}, which is not plugged in`,
              body: ["Plug it in and Forge carries on by itself. No app has started, so nothing is lost."] }
          : { icon: "warn", tone: "warn", title: "Forge cannot find your things",
              body: ["They were kept in ", root, ", which is not there now. If that folder is on a drive, plug it in. If you moved the folder, choose where it is now."] };
      case "empty":
        return { icon: "plug", tone: "", title: drive ? `Plug in ${drive}` : "Your things are not in their folder",
          body: ["The folder ", root, " is there, but your Forge data is not in it. That happens when a drive is not plugged in (or not opened yet) and its folder is left behind. Plug the drive in, or choose where your things are now."] };
      case "gone":
        return { icon: "plug", tone: "warn", title: drive ? `${drive} was unplugged while Forge was running` : "Your things went away while Forge was running",
          body: ["Forge stopped every app at once so nothing is written to the wrong place. Plug it back in and Forge carries on by itself."] };
      case "other":
        return { icon: "box", tone: "warn", title: "That folder holds other Forge data",
          body: [root, ` holds Forge data made ${p.made ? "on " + p.made : "on another day"}, not the copy this Forge was using. That happens when a drive was swapped or the folder was replaced.`] };
      case "read-only":
        return { icon: "warn", tone: "bad", title: "Forge cannot write to your things",
          body: [root, " is read-only now. A drive pulled out without ejecting it often turns read-only: plug it in again and eject it properly before unplugging, or check the drive for errors."] };
      case "full":
        return { icon: "warn", tone: "warn", title: drive ? `${drive} is full` : "The disk with your things is full",
          body: [`Only ${p.free_text || "a little"} is left at `, root, ". Apps may fail to save. Make some room, then try again."] };
      default:
        return { icon: "warn", tone: "warn", title: "Forge cannot use your things now", body: [root] };
    }
  }

  function problem() {
    fromProblem = true;
    // the look the place had (the launcher keeps it), unless one was picked;
    // a place chosen in the steps then puts its own look on again (critic)
    if (!lookPicked && state.look) {
      look = state.look;
      lookFor = "";
    }
    document.body.classList.toggle("light", look === "light");
    const p = state.problem || {};
    const text = problemText(p);
    const waits = ["missing", "empty", "gone"].includes(p.why);
    const said = h("div.verdict");
    const buttons = [];
    const act = async (what, button) => {
      button.disabled = true;
      said.textContent = "";
      let answer;
      try {
        answer = await ask(what);
      } catch (e) {
        answer = { ok: false };
      }
      button.disabled = false;
      if (answer.ok) return go("/hub/index.html");
      if (answer.problem && answer.problem.why) {
        state.problem = answer.problem;
        if (answer.problem.why !== p.why) return problem();
      }
      said.textContent = "";
      add(said, h("div.bad", {}, typeof answer.problem === "string"
        ? answer.problem : "Still the same." + (waits ? " Forge keeps looking." : "")));
    };
    const tryAgain = h("button.btn.primary", { type: "button", onclick: () => act("retry", tryAgain) }, "Try again");
    if (p.why === "other") {
      const adopt = h("button.btn.primary", { type: "button", onclick: () => act("adopt", adopt) }, "Use the Forge data there");
      buttons.push(adopt);
    } else {
      buttons.push(tryAgain);
    }
    if (p.why === "full") {
      const anyway = h("button.btn", { type: "button", onclick: () => act("anyway", anyway) }, "Open anyway");
      buttons.push(anyway);
    }
    if (p.why !== "gone") {
      buttons.push(h("button.btn", { type: "button", onclick: where }, "Choose another place"));
    }
    const quit = h("button.btn", { type: "button", onclick: async () => {
      quit.disabled = true;
      try { await ask("quit"); } catch (e) { /* it may stop before it answers */ }
      window.ForgePlace.stopped();
    } }, "Quit");
    shown = "problem:" + p.why;
    card.textContent = "";
    add(card,
      h("div", { class: `icon-big ${text.tone}` }, icon(text.icon)),
      h("h1", {}, text.title),
      h("p.lead", {}, ...text.body),
      p.root && !text.body.some((b) => b instanceof Node) ? h("p.quiet.small", {}, "Kept in ", h("span.path", {}, p.root)) : null,
      waits ? h("p.waiting", {}, h("span.spin"), "Forge is watching for it…") : null,
      said,
      h("div.foot", {}, quit, h("div.row", {}, buttons)),
    );
    card.querySelector("h1").tabIndex = -1;
    card.querySelector("h1").focus({ preventScroll: true });
  }

  // -- what the launcher says --------------------------------------------------

  function route(next) {
    const before = state && state.mode;
    state = next;
    if (leaving) return;
    if (state.mode === "moving") return go("/hub/data.html");
    if (state.mode === "ready" && (!again || before === "problem")) return go("/hub/index.html");
    if (state.mode === "problem") {
      // the user is choosing another place, or the screen says this already
      if (shown === "steps" && fromProblem) return;
      if (shown === "problem:" + (state.problem || {}).why) return;
      return problem();
    }
    if (before === undefined || before === null) {
      if (state.size) size = state.size;
      if (state.look) look = state.look;
      document.body.classList.toggle("light", look === "light");
      if (state.mode === "welcome" && !again) {
        document.title = "Welcome to Forge";
      }
      hello();
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
    listen(route);
    // the events may drop (a sleeping laptop): look again now and then while
    // the problem screen waits for a drive
    setInterval(async () => {
      if (leaving || !state || state.mode !== "problem") return;
      try { route(await ask("state")); } catch (e) { /* Forge stopped */ }
    }, 3000);
  }

  start();
})();
