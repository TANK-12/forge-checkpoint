/* What the welcome (hub/welcome.html) and the data page (hub/data.html)
   share: the requests to the launcher (POST /forge/place, see
   forge_portable.Launcher.place_action), the launcher's events, and the
   place chooser (this computer, a drive plugged in, a folder from the
   system's own picker, or a typed path), which checks every choice with the
   launcher before it can be used.

   forge_portable.py puts window.FORGE_PLACE ({token, system, version}) in
   front of this script. */
window.ForgePlace = (() => {
  const config = window.FORGE_PLACE || {};
  const token = config.token || "";

  async function ask(what, extra = {}) {
    const res = await fetch("/forge/place", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Forge": token },
      body: JSON.stringify({ ...extra, do: what }),
    });
    if (!res.ok) throw new Error(`Forge answered ${res.status}`);
    return res.json();
  }

  // the launcher's events: "place" when the place changes (a drive pulled
  // out, a move), "quit" when Forge stops
  function listen(onPlace) {
    let events = null;
    try {
      events = new EventSource("/forge/events?t=" + encodeURIComponent(token));
    } catch (e) {
      return null;
    }
    events.addEventListener("place", (e) => {
      try { onPlace(JSON.parse(e.data)); } catch (err) { /* not JSON */ }
    });
    events.addEventListener("quit", () => { events.close(); stopped(); });
    return events;
  }

  function stopped() {
    document.title = "Forge has stopped";
    document.body.innerHTML =
      '<div class="shell"><div class="brand">FORGE<i>.</i></div>' +
      '<div class="card"><h1>Forge has stopped</h1>' +
      '<p class="lead">You can close this window.</p></div></div>';
    try { window.close(); } catch (e) { /* a tab may not close itself */ }
  }

  // a small element maker: h("p.quiet", {}, "text", child, ...)
  function h(spec, attrs = {}, ...children) {
    const [tag, ...classes] = spec.split(".");
    const node = document.createElement(tag || "div");
    if (classes.length) node.className = classes.join(" ");
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (key === "html") node.innerHTML = value;
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  /* node.append(...), leaving out null, undefined and false (append would
     write them as text). */
  function add(node, ...children) {
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child);
    }
    return node;
  }

  const ICONS = {
    computer:
      '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>',
    drive:
      '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7" width="18" height="10" rx="2"/><path d="M7 12h.01M11 12h6"/></svg>',
    folder:
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
    lock:
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>',
    plug:
      '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2v6M15 2v6M6 8h12v3a6 6 0 0 1-12 0zM12 17v5"/></svg>',
    warn:
      '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/></svg>',
    box:
      '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7l9-4 9 4-9 4z"/><path d="M3 7v10l9 4 9-4V7M12 11v10"/></svg>',
  };
  const icon = (name) => h("span", { html: ICONS[name] || "" });

  /* The place chooser. `mount` is the element it fills; opts:
       move     - true on the data page: the choice must be a new, empty place
       computer - this computer's folder ({path, free}); omitted on the data
                  page's Move when the things are on this computer already
       onChange - called with the check's answer (ok or not), or null
       initial  - an earlier choice() to open on (the welcome's Back)
     Returns {checked(): the last answer, choice(): {mode, path}, refresh()}. */
  function chooser(mount, opts = {}) {
    let last = null;
    const start = opts.initial || {};
    let mode = opts.computer && start.mode !== "elsewhere" ? "computer" : "elsewhere";
    let pickedDrive = "";
    let seq = 0;

    const verdict = h("div.verdict", { "aria-live": "polite" });
    const input = h("input", {
      type: "text",
      spellcheck: "false",
      autocomplete: "off",
      placeholder: config.system === "windows"
        ? "For example D:\\"
        : `For example ${["", "run", "media", "you", "MyDrive"].join("/")}`, // the release scrub leaves it whole
      "aria-label": "A folder's path",
      onkeydown: (e) => { if (e.key === "Enter") check(input.value); },
    });
    input.value = start.path || "";
    const driveList = h("div.drives");
    const driveNote = h("p.quiet.small");
    const elsewhere = h("div.more", {},
      h("h2", { style: "margin-top:0" }, "Drives plugged in"),
      driveList,
      driveNote,
      h("h2", {}, "Or a folder"),
      h("div.row", {},
        h("div.grow", {}, input),
        h("button.btn", { type: "button", onclick: () => check(input.value) }, "Use this path"),
        h("button.btn", { type: "button", onclick: pick }, icon("folder"), " Choose a folder\u2026"),
      ),
      h("p.quiet.small", { style: "margin:8px 0 0" },
        "Forge makes a folder named \u201cForge data\u201d inside the one you choose."),
    );

    let computerBtn = null;
    let elsewhereBtn = null;
    if (opts.computer) {
      computerBtn = h("button.choice", { type: "button", onclick: () => choose("computer") },
        h("span.title", {}, h("span.dot"), icon("computer"), "On this computer"),
        h("div.sub", {}, "The usual choice. ",
          h("span.path", {}, opts.computer.path),
          opts.computer.free ? ` (${opts.computer.free} free)` : ""),
      );
      elsewhereBtn = h("button.choice", { type: "button", onclick: () => choose("elsewhere") },
        h("span.title", {}, h("span.dot"), icon("drive"), "On a drive or folder I choose"),
        h("div.sub", {}, "A USB drive or another disk: your things go wherever it goes."),
      );
      mount.append(h("div.choices", {}, computerBtn, elsewhereBtn), elsewhere, verdict);
    } else {
      mount.append(elsewhere, verdict);
    }

    function setLast(answer) {
      last = answer;
      if (opts.onChange) opts.onChange(answer);
    }

    function show(answer) {
      verdict.textContent = "";
      if (!answer) return;
      if (answer.ok) {
        const where = answer.adopt
          ? "Forge will use the Forge data already in "
          : opts.move ? "Forge will move your things to " : "Forge will keep your things in ";
        verdict.append(h("div", {}, h("span.ok", {}, "\u2713 "), where, h("span.path", {}, answer.folder)));
      } else {
        verdict.append(h("div.bad", {}, answer.problem || "That place cannot be used."));
      }
      const notes = answer.notes || [];
      if (notes.length) verdict.append(h("ul", {}, notes.map((n) => h("li", {}, n))));
    }

    async function check(path) {
      const mine = ++seq;
      verdict.textContent = "";
      verdict.append(h("span.waiting", {}, h("span.spin"), "Checking that place\u2026"));
      setLast(null);
      let answer;
      try {
        answer = await ask("check", { path, move: !!opts.move });
      } catch (e) {
        answer = { ok: false, problem: "Forge did not answer. Is it still running?" };
      }
      if (mine !== seq) return; // a newer choice came in meanwhile
      show(answer);
      setLast(answer);
      for (const b of driveList.querySelectorAll(".drive")) {
        b.setAttribute("aria-pressed", String(b.dataset.mount === pickedDrive && path === pickedDrive));
      }
    }

    async function pick() {
      const start = input.value.trim();
      verdict.textContent = "";
      verdict.append(h("span.waiting", {}, h("span.spin"), "The folder picker is open\u2026"));
      let answer;
      try {
        answer = await ask("pick", { path: start });
      } catch (e) {
        answer = { none: true };
      }
      if (answer.path) {
        input.value = answer.path;
        pickedDrive = "";
        return check(answer.path);
      }
      verdict.textContent = "";
      if (answer.none) {
        verdict.append(h("div.quiet", {},
          "This computer has no folder picker Forge can open. Type the folder's path above instead."));
      }
      if (last) show(last);
    }

    async function loadDrives() {
      driveList.textContent = "";
      driveNote.textContent = "Looking for drives\u2026";
      let list = [];
      try {
        list = (await ask("drives")).drives || [];
      } catch (e) {
        list = [];
      }
      driveNote.textContent = "";
      for (const d of list) {
        const button = h("button.drive", {
          type: "button",
          "data-mount": d.mount,
          "aria-pressed": "false",
          title: d.folder,
          onclick: () => { pickedDrive = d.mount; input.value = d.mount; check(d.mount); },
        },
          h("b", {}, d.name, d.removable ? h("span.tag", {}, "removable") : null),
          h("span", {}, d.free_text ? `${d.free_text} free` : "free space unknown",
            d.fs ? ` \u00b7 ${d.fs.toUpperCase()}` : ""),
        );
        driveList.append(button);
      }
      driveNote.append(
        list.length ? "" : "No other drive is plugged in. ",
        h("button.link", { type: "button", onclick: loadDrives }, list.length ? "Look again" : "Plug one in, then look again"),
      );
    }

    function choose(which) {
      mode = which;
      if (computerBtn) {
        computerBtn.setAttribute("aria-pressed", String(which === "computer"));
        elsewhereBtn.setAttribute("aria-pressed", String(which === "elsewhere"));
      }
      elsewhere.hidden = which !== "elsewhere";
      if (which === "computer") {
        check(opts.computer.path);
      } else {
        seq++;
        verdict.textContent = "";
        setLast(null);
        loadDrives();
        if (input.value.trim()) check(input.value);
      }
    }

    choose(mode);
    return {
      checked: () => last,
      choice: () => ({ mode, path: input.value }),
      refresh: () => choose(mode),
    };
  }

  return { config, ask, listen, stopped, h, icon, chooser, add };
})();
