/* ==========================================================================
   Forge shared chrome control -- "Full screen" for every app.
   ==========================================================================

   Served by each app's own backend at /shared/forge_chrome.js (every
   web_app.py mounts ~/Forge/shared). One line in an app's index.html:

       <script src="/shared/forge_chrome.js"></script>

   ...and that app has a working full-screen control. Nothing else is needed:
   the script wires itself up on load, so a new app under apps/ gets this for
   free rather than copying a block of code.

   THREE LAYERS, and they are separate on purpose:

     1. The Forge sidebar. A page cannot touch it -- it lives in the hub shell,
        one document up -- so it is asked away by postMessage. The hub listens
        for {forge:"chrome", hidden:bool} and toggles `chromeless` on its body.
     2. The real Fullscreen API, so the app fills the window (and, standalone
        in a browser, fills the screen). The hub gives every workspace iframe
        `allowfullscreen`, so this is allowed from inside one.
     3. The GTK window itself. forge.py listens for WebKit's enter-fullscreen
        signal and fullscreens the window with it, which is what makes layer 2
        actually cover the screen rather than just the WebView.

   This used to live at the bottom of forge.js as `const ForgeChrome`, which is
   why Dossier's button did nothing: a top-level `const` in a classic script
   goes into the global LEXICAL scope, not onto `window`, so the app's
   `if (window.ForgeChrome)` guard was always false and the button was never
   wired. The assignment to window at the end of this file is not decoration.
   ========================================================================== */

(function () {
  "use strict";

  const ForgeChrome = {
    hidden: false,

    /** Show a text size on this page only, until the hub's next theme
        (Settings previews its Text size slider while it is dragged). */
    help() { Help.ask(); },
    /** Tell the hub's app frame which tab is showing, for an app whose tabs
        are not its location hash (a hash change is told by itself). */
    tabNow(id) { Framed.tell(typeof id === "string" ? id : undefined); },
    /** Tell the frame the page's Simple/Advanced: ForgeMode's (shared/forge.js)
        by itself, or pass true/false from an app with its own switch. */
    modeNow(advanced) { Framed.mode(advanced); },
    previewTextSize(value) {
      applyTextSize((applyTextSize.latest = value));
    },
    _wired: false,
    _buttons: [],

    /** Hide or show the hub's sidebar AND take/leave real fullscreen.
        Every part is a harmless no-op outside the hub or outside a browser
        that allows it, so this is safe to call from anywhere. */
    set(hidden, { real = true } = {}) {
      this.hidden = !!hidden;

      // Layer 1: the hub sidebar. Inside the hub, the hub also fills the
      // window itself (`window`), in place of layer 2: element fullscreen
      // lifts the app's frame into WebKit's top layer over a black backdrop,
      // which hid the hub's wallpaper behind every glass app.
      const embedded = window.parent !== window;
      try {
        window.parent.postMessage(
          { forge: "chrome", hidden: this.hidden, window: real ? this.hidden : undefined },
          "*");
      } catch (e) {
        /* a stricter embedder; the layers below still apply */
      }
      document.body.classList.toggle("forge-fullscreen", this.hidden);

      // Layer 2: real fullscreen, standalone only. Only attempted on a user
      // gesture -- a rejected promise here is normal (no user activation)
      // and must not become an unhandled rejection.
      if (real && !embedded) {
        try {
          const d = document;
          if (this.hidden && !d.fullscreenElement) {
            const p = d.documentElement.requestFullscreen();
            if (p && p.catch) p.catch(() => {});
          } else if (!this.hidden && d.fullscreenElement) {
            const p = d.exitFullscreen();
            if (p && p.catch) p.catch(() => {});
          }
        } catch (e) {
          /* an engine without the Fullscreen API; layer 1 still worked */
        }
      }

      this._relabel();
      if (this._onChange) this._onChange(this.hidden);
      return this.hidden;
    },

    toggle(opts) { return this.set(!this.hidden, opts); },

    /** The hub left full screen on its own (Esc or F11 caught by the
        window): match it without asking the hub again. */
    _hubSays(hidden) {
      this.hidden = !!hidden;
      document.body.classList.toggle("forge-fullscreen", this.hidden);
      this._relabel();
      if (this._onChange) this._onChange(this.hidden);
    },

    _relabel() {
      const text = this.hidden ? "Exit full screen" : "Full screen";
      for (const el of this._buttons) {
        el.textContent = text;
        el.setAttribute("aria-pressed", this.hidden ? "true" : "false");
      }
    },

    /** Wire a button and a key. Pass `key: null` for no keyboard shortcut.
        Kept to the signature the apps already call, so existing
        `ForgeChrome.init({button: "go-fullscreen", key: "f"})` calls still
        mean what they meant. */
    init({ button = null, key = "f", onChange = null } = {}) {
      this._wired = true;
      if (onChange) this._onChange = onChange;

      if (button) {
        const el = typeof button === "string"
          ? document.getElementById(button) : button;
        if (el && this._buttons.indexOf(el) === -1) {
          this._buttons.push(el);
          el.addEventListener("click", () => this.toggle());
        }
      }

      if (key && !this._keyBound) {
        this._keyBound = true;
        window.addEventListener("keydown", (e) => {
          if (e.key === "Escape" && this.hidden) {
            e.preventDefault();
            this.set(false);
            return;
          }
          // Alt+key only: a bare "f" went full screen whenever it was typed
          // outside a text box. Inside Forge, forge.py takes Alt+F first.
          if (e.metaKey || e.ctrlKey || e.shiftKey || !e.altKey) return;
          if (e.key.toLowerCase() === key || e.code === "Key" + key.toUpperCase()) {
            e.preventDefault();
            this.toggle();
          }
        });
      }

      this._relabel();
      return this;
    },

    /** Ask the hub to close this app: go home, throw the page away, stop the
        backend. The owner asked for it after opening a game by accident and
        finding it had started a language model behind his back -- hiding an
        app is not closing it. Outside the hub there is nothing to ask, so this
        is a no-op rather than an error. */
    close() {
      try {
        window.parent.postMessage({ forge: "close" }, "*");
      } catch (e) {
        /* standalone: nothing above us to hear it */
      }
    },

    /** The close control, put next to the full-screen one wherever that is:
        beside the app's own header button if it has one, or beside the
        injected floating button if it does not. Every app gets it without
        editing a line of its own markup. */
    _injectClose(next_to) {
      const el = document.createElement("button");
      el.id = "forge-close-app";
      el.className = "forge-chrome-btn forge-close-btn";
      el.type = "button";
      el.textContent = "Close app";
      el.title =
        "Close this app: stops its backend and anything it is running, and goes back to the home screen. It starts again next time you open it.";
      el.addEventListener("click", () => this.close());
      if (next_to && next_to.parentNode) {
        next_to.parentNode.insertBefore(el, next_to.nextSibling);
        // Sitting in an app's own header, it should look like that header's
        // buttons rather than like the floating one.
        el.classList.add("forge-close-inline");
      } else {
        document.body.appendChild(el);
        // forge.css lifts .toast above the floating pair while it is shown.
        document.documentElement.classList.add("forge-floating-chrome");
      }
      this._closeButton = el;
      return el;
    },

    /** Inject a button for apps whose markup has no place for one. Apps that
        do have somewhere sensible put `id="go-fullscreen"` in their own
        header and this never runs. */
    _inject() {
      const el = document.createElement("button");
      el.id = "go-fullscreen";
      el.className = "forge-chrome-btn";
      el.type = "button";
      el.title = "Full screen: hides the Forge sidebar and fills the screen (Alt+F). Esc comes back.";
      document.body.appendChild(el);
      return el;
    },

    _style() {
      if (document.getElementById("forge-chrome-style")) return;
      const s = document.createElement("style");
      s.id = "forge-chrome-style";
      // Tokens come from shared/forge.css where the app loads it; the
      // fallbacks are for the apps that style themselves (ai-studio,
      // PixelForge), so the button is legible either way.
      s.textContent = `
.forge-chrome-btn {
  position: fixed; right: 12px; bottom: 12px; z-index: 2147483000;
  padding: 6px 12px; border-radius: 999px; cursor: pointer;
  font: 12px/1 -apple-system, "Segoe UI", Roboto, sans-serif;
  background: var(--panel-2, #1e222b); color: var(--muted, #8b93a3);
  border: 1px solid var(--border, #2a2f3a);
  opacity: .55; transition: opacity .15s, color .15s, border-color .15s;
}
.forge-chrome-btn:hover, .forge-chrome-btn:focus-visible {
  opacity: 1; color: var(--text, #e7e9ee); border-color: var(--accent, #6ea8fe);
}
/* The floating pair sit side by side; the close one goes to the left of
   full screen so the button under the cursor does not change meaning. */
.forge-close-btn { right: 108px; }
.forge-close-btn:hover, .forge-close-btn:focus-visible {
  color: var(--bad, #ff8080); border-color: var(--bad, #ff8080);
}
/* Inside an app's own header it is an ordinary button in the flow. z-index
   auto: as a flex item it would otherwise keep the floating button's huge
   z-index and paint over the app's own drawers and dialogs. */
.forge-close-inline {
  position: static; z-index: auto; margin-left: 6px; opacity: .75;
  white-space: nowrap; flex-shrink: 0;
}
/* A narrow window: a cross instead of the words, so a busy header (Terminal's
   tab strip) keeps its room. The label stays for screen readers. */
@media (max-width: 760px) {
  .forge-close-inline { font-size: 0; padding: 6px 9px; }
  .forge-close-inline::before { content: "\\00d7"; font-size: 15px; line-height: 12px; }
}`;
      document.head.appendChild(s);
    },

    /** Called automatically on load. Uses the app's own button if it has one
        (any element with id `go-fullscreen`, or `[data-forge-fullscreen]`),
        and injects a floating one otherwise. */
    mount() {
      if (this._mounted) return this;
      this._mounted = true;
      this._style();

      let el = document.getElementById("go-fullscreen")
        || document.querySelector("[data-forge-fullscreen]");
      const ownHeader = !!el;
      // Inside Forge the hub's bar carries Full screen and Close for every
      // app, so nothing floats over the app's own corner (it used to cover
      // the Board's Send button). Standalone, the floating pair stays.
      const inHub = window.parent !== window;
      if (!el && !inHub) el = this._inject();
      this.init({ button: el, key: "f" });
      if (!document.getElementById("forge-close-app") && (ownHeader || !inHub)) {
        this._injectClose(ownHeader ? el : null);
      }

      // Leaving fullscreen by Escape, F11 or the window manager must put the
      // sidebar back too -- otherwise the app is left with no chrome and no
      // obvious way to get it back. `real: false` because the browser has
      // already left; asking again would be a second, failing request.
      document.addEventListener("fullscreenchange", () => {
        if (!document.fullscreenElement && this.hidden) this.set(false, { real: false });
      });
      return this;
    },
  };

  // Text size lives in its own shared file, next to this one, because the hub
  // uses it too. Loaded the first time a theme asks for a size other than 1.
  const textSizeSrc = new URL("forge_textsize.js", (document.currentScript || {}).src || location.href).href;
  const themesBase = new URL("themes/", (document.currentScript || {}).src || location.href).href;

  /* The frame-rate cap (B39, setting max_fps) is shared/forge_framecap.js,
     beside this file, so the hub uses the same one. Inside Forge it is loaded
     straight away and set from the hub's theme message; standalone nothing
     arrives, so it isn't loaded. */
  const FrameCap = {
    want: null,
    src: new URL("forge_framecap.js", (document.currentScript || {}).src || location.href).href,
    load() {
      if (window.parent === window || window.ForgeFrameCap) return;
      const tag = document.createElement("script");
      tag.src = this.src;
      tag.onload = () => { if (this.want !== null) window.ForgeFrameCap.set(this.want); };
      (document.head || document.documentElement).appendChild(tag);
    },
    set(value) {
      this.want = value;
      if (window.ForgeFrameCap) window.ForgeFrameCap.set(value);
    },
  };
  FrameCap.load();

  // Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y in text boxes (shared/forge_undo.js):
  // WebKitGTK binds no key to undo, so every page that loads this one gets it.
  if (!document.getElementById("forge-undo-js")) {
    const u = document.createElement("script");
    u.id = "forge-undo-js";
    u.src = new URL("forge_undo.js", (document.currentScript || {}).src || location.href).href;
    (document.head || document.documentElement).appendChild(u);
  }

  // Inside the hub, every app reports what it plays to the bar's Now playing
  // and takes play/pause/seek/volume back (shared/forge_media.js).
  if (window.parent !== window && !document.getElementById("forge-media-js")) {
    const m = document.createElement("script");
    m.id = "forge-media-js";
    m.src = new URL("forge_media.js", (document.currentScript || {}).src || location.href).href;
    (document.head || document.documentElement).appendChild(m);
  }
  // Every app page loads it straight away now: the reading size (15 px body
  // text, Relay task 383) is on unless the hub's app_text says "original".
  function applyTextSize(value) {
    const scale = Number(value) || 1;
    if (window.ForgeText) {
      window.ForgeText.lift(applyTextSize.lift !== false);
      return window.ForgeText.apply(scale);
    }
    if (document.getElementById("forge-textsize-js")) return;
    const s = document.createElement("script");
    s.id = "forge-textsize-js";
    s.src = textSizeSrc;
    s.onload = () => {
      if (!window.ForgeText) return;
      window.ForgeText.lift(applyTextSize.lift !== false);
      window.ForgeText.apply(applyTextSize.latest);
    };
    (document.head || document.documentElement).appendChild(s);
  }
  applyTextSize.lift = true;
  applyTextSize(1);

  /* The F1 help sheet. F1 anywhere in the page asks the hub, which draws one sheet from the app's manifest; a page may
     add its own keys as window.ForgeHelpKeys = [["Ctrl+S", "Save"], ...].
     Standalone (no hub above) a small sheet of the page's own title and keys
     is drawn here instead. */
  const Help = {
    keys() {
      const k = window.ForgeHelpKeys;
      return Array.isArray(k) ? k.filter((r) => Array.isArray(r) && r.length === 2).map((r) => [String(r[0]), String(r[1])]) : [];
    },
    ask() {
      if (window.parent !== window) {
        try { window.parent.postMessage({ forge: "help", keys: this.keys() }, "*"); } catch (e) { /* no hub */ }
        return;
      }
      this.local();
    },
    local() {
      let el = document.getElementById("forge-help-sheet");
      if (el) { el.remove(); return; }
      el = document.createElement("div");
      el.id = "forge-help-sheet";
      el.setAttribute("role", "dialog");
      el.style.cssText = "position:fixed;inset:0;z-index:2147483000;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.5);font-size:15px;line-height:1.5";
      const box = document.createElement("div");
      box.style.cssText = "background:var(--panel,#171a21);color:var(--text,#e7e9ee);border:1px solid var(--border,#2a2f3a);border-radius:12px;padding:24px 28px;max-width:640px;width:90vw;max-height:85vh;overflow:auto";
      const h = document.createElement("h2");
      h.style.margin = "0 0 8px";
      h.textContent = document.title || "Help";
      box.appendChild(h);
      const rows = this.keys().concat([["F1", "Show or hide this help"], ["Alt+F", "Full screen"], ["Esc", "Leave full screen or close this"]]);
      const t = document.createElement("table");
      rows.forEach(([k, what]) => {
        const tr = t.insertRow();
        const a = tr.insertCell(), b = tr.insertCell();
        a.textContent = k;
        a.style.cssText = "padding:3px 14px 3px 0;white-space:nowrap;color:var(--accent,#6ea8fe);font-family:monospace";
        b.textContent = what;
      });
      box.appendChild(t);
      el.appendChild(box);
      el.addEventListener("click", () => el.remove());
      document.body.appendChild(el);
    },
  };
  // F1 caught by forge.py reaches the hub, not the page: tell it the page's keys up front
  const sayKeys = () => {
    if (window.parent === window || !Help.keys().length) return;
    try { window.parent.postMessage({ forge: "help-keys", keys: Help.keys() }, "*"); } catch (e) { /* no hub */ }
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", sayKeys);
  else setTimeout(sayKeys, 0);
  window.addEventListener("keydown", (e) => {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
    const sheet = document.getElementById("forge-help-sheet");
    if (sheet && e.key === "Escape") { sheet.remove(); e.preventDefault(); return; }
    // F1 only: a bare ? is typed in games and the Typing drills
    if (e.key === "F1") {
      e.preventDefault();
      Help.ask();
    }
  });


  /* Forge's own keys (Alt+H, Alt+S...). forge.py's window catches them before
     the page; a release's window cannot, so its hub (hub/portable.js) sends
     their signatures once this page is ready, and a match goes to the hub
     instead of the page. Under forge.py nothing is sent and nothing changes.
     keySig has a twin in hub/portable.js. */
  let hubKeys = null;
  const keySig = (e) => {
    const c = e.code || "";
    const k = /^[a-z0-9]$/i.test(e.key) ? e.key : /^Key[A-Z]$/.test(c) ? c.slice(3)
      : /^Digit[0-9]$/.test(c) ? c.slice(5) : c === "Space" ? "space" : e.key;
    return [e.ctrlKey && "ctrl", e.altKey && "alt", e.shiftKey && "shift", e.metaKey && "meta"]
      .filter(Boolean).concat(String(k).toLowerCase()).join("+");
  };
  window.addEventListener("message", (event) => {
    const msg = event.data;
    if (event.source !== window.parent || !msg || msg.forge !== "page-keys" || !Array.isArray(msg.keys)) return;
    hubKeys = new Set(msg.keys.filter((k) => typeof k === "string"));
  });
  window.addEventListener("keydown", (e) => {
    if (!hubKeys || !hubKeys.has(keySig(e))) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    try { window.parent.postMessage({ forge: "key", sig: keySig(e) }, "*"); } catch (err) { /* no hub */ }
  }, true);

  /* The hub's theme. Inside Forge the hub sends {forge:"theme", theme} once
     the app has loaded, and again whenever Settings changes it. Tokens are set
     inline on <html>, which beats any stylesheet's :root, so an app with its
     own palette is themed too. The page goes see-through and the hub draws the
     blurred wallpaper behind it; panels stay mostly solid so text stays
     readable. Only a message from the parent frame is accepted, and
     standalone nothing arrives, so nothing changes. */
  function applyTheme(t) {
    applyTextSize.lift = t.app_text !== "original";
    applyTextSize((applyTextSize.latest = t.text_scale));
    // Simple or Advanced when the app opens (Settings > Apps > Apps open in)
    if (window.ForgeMode && typeof window.ForgeMode.fromHub === "function") window.ForgeMode.fromHub(t.app_mode);
    else window.__forgeAppMode = t.app_mode;
    const html = document.documentElement;
    const glass = Math.max(0.2, Math.min(1, Number(t.glass) || 0.62));
    if (t.unify_accent && t.accent) {
      html.style.setProperty("--accent", t.accent);
      html.style.setProperty("--accent-2", t.accent_2 || t.accent);
      html.style.setProperty("--on-accent", t.on_accent || "#0b1220");
    }
    // Panel colours: tinted by the wallpaper when Settings says so, the
    // classic greys otherwise. Border and text come solid; the fills keep
    // the glass so the blurred wallpaper shows through.
    const s = t.surfaces || {};
    const rgba = (hex, fallback, alpha) => {
      const value = /^#[0-9a-f]{6}$/i.test(hex || "") ? hex : fallback;
      const n = parseInt(value.slice(1), 16);
      return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha.toFixed(2)})`;
    };
    // Every token comes from one table (forge_themes.SURFACE_TOKENS, Relay
    // task 388): the raised panels, faint text and hairlines too, so an app's
    // own dark cards never keep a light theme's dark text on them.
    const glassAlpha = {
      bg: glass,
      panel: Math.min(1, 0.5 + glass * 0.45),
      panel_2: Math.min(1, 0.6 + glass * 0.38),
    };
    const fallback = { bg: "#0d0f13", panel: "#171a21", panel_2: "#1e222b" };
    const rows = Array.isArray(t.surface_tokens) && t.surface_tokens.length ? t.surface_tokens
      : [["--bg", "bg", "bg"], ["--panel", "panel", "panel"], ["--panel-2", "panel_2", "panel_2"],
        ["--border", "border", null], ["--text", "text", null], ["--muted", "muted", null],
        // a hub from before the table: lift the raised panels and quiet text
        // to its colours rather than leave an app's dark ones under light text
        ["--surface", "bg", "bg"], ["--raise", "panel", "panel"], ["--raise-2", "panel_2", "panel_2"], ["--faint", "muted", null]];
    // An app that keeps its own dark colours (a game, a map, a 3D view) says
    // so in its page with <meta name="forge-colours" content="own">: a light
    // theme leaves it as it is rather than lay light panels under its own
    // light text. Accent, font and text size still apply.
    const own = t.theme_mode === "light"
      && !!document.querySelector('meta[name="forge-colours"][content="own"]');
    for (const [token, key, see] of rows) {
      if (!/^--[a-z0-9-]+$/.test(token || "")) continue;
      if (own) {
        html.style.removeProperty(token);
        continue;
      }
      if (typeof see === "number") {
        if (s[key]) html.style.setProperty(token, rgba(s[key], "#808080", Math.max(0, Math.min(1, see))));
      } else if (see && glassAlpha[see] !== undefined) {
        html.style.setProperty(token, rgba(s[key], fallback[see], glassAlpha[see]));
      } else if (s[key]) {
        html.style.setProperty(token, s[key]);
      }
    }

    // Font and size, from Settings. "" / 1 leave the app exactly as it is.
    if (t.font_stack) {
      html.style.setProperty("--forge-font", t.font_stack);
      if (!document.getElementById("forge-font-style")) {
        const f = document.createElement("style");
        f.id = "forge-font-style";
        f.textContent = "html.forge-font body, html.forge-font button, html.forge-font input,"
          + " html.forge-font select, html.forge-font textarea { font-family: var(--forge-font); }";
        document.head.appendChild(f);
      }
    }
    html.classList.toggle("forge-font", !!t.font_stack);
    // App size is not applied here: forge.py zooms the whole window.
    // <html> and <body> both paint var(--bg); only one of them may, or the
    // glass is laid down twice and comes out nearly solid.
    html.style.background = own ? "" : "transparent";
    html.classList.add("forge-themed");
    // The hub's look (classic, material, brain...), for an app that wants to
    // match it: style against html[data-forge-look="material"].
    html.dataset.forgeLook = t.look || "classic";
    // The theme (Settings > Themes, shared/forge_themes.py): light or dark,
    // and its own stylesheet, shared/themes/<id>.css, which styles an app
    // under html[data-forge-theme="<id>"]. A dark theme leaves the app's own
    // color-scheme alone.
    const mode = t.theme_mode === "light" && !own ? "light" : "dark";
    html.dataset.forgeMode = mode;
    html.style.colorScheme = mode === "light" ? "light" : "";
    const css = !own && /^[a-z0-9-]+$/.test(t.theme_css || "") ? t.theme_css : "";
    if (css) html.dataset.forgeTheme = css;
    else delete html.dataset.forgeTheme;
    let themeLink = document.getElementById("forge-theme-css");
    if (css && !themeLink) {
      themeLink = document.createElement("link");
      themeLink.id = "forge-theme-css";
      themeLink.rel = "stylesheet";
      document.head.appendChild(themeLink);
    }
    if (themeLink && themeLink.dataset.css !== css) {
      themeLink.dataset.css = css;
      if (css) themeLink.href = themesBase + css + ".css";
      else themeLink.removeAttribute("href");
    }
    // Lighter effects (#225, setting lite_effects): the hub decides when
    // (always, or only on battery) and sends lite. Looping animations play
    // once and stop; the frosted blur goes flat.
    if (t.lite && !document.getElementById("forge-lite-css")) {
      const css = document.createElement("style");
      css.id = "forge-lite-css";
      css.textContent = "html.forge-lite *, html.forge-lite *::before, html.forge-lite *::after {"
        + " animation-iteration-count: 1 !important; backdrop-filter: none !important;"
        + " -webkit-backdrop-filter: none !important; }";
      document.head.appendChild(css);
    }
    html.classList.toggle("forge-lite", !!t.lite);
    // The performance tier's "no-blur" (shared/perf/tiers.json, Relay task
    // 379): the frosted glass goes flat in the apps too.
    const flat = Array.isArray(t.perf_css) && t.perf_css.includes("no-blur");
    if (flat && !document.getElementById("forge-perf-css")) {
      const css = document.createElement("style");
      css.id = "forge-perf-css";
      css.textContent = "html.perf-no-blur *, html.perf-no-blur *::before, html.perf-no-blur *::after {"
        + " backdrop-filter: none !important; -webkit-backdrop-filter: none !important; }";
      document.head.appendChild(css);
    }
    html.classList.toggle("perf-no-blur", flat);
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent || window.parent === window) return;
    const msg = event.data;
    if (msg && msg.forge === "theme" && msg.theme && typeof msg.theme === "object") {
      applyTheme(msg.theme);
      FrameCap.set(msg.theme.max_fps);
      Painted.themed();
    }
  });

  /* The hub keeps a fresh app frame see-through until the page inside has
     drawn with its theme, so an app never opens as an unstyled or solid
     page that then jumps to glass (2026-10-19 sweep). "ready" (the page is
     parsed: send the theme now rather than at load, which waits for every
     image) and "painted" (the frame after the theme went on) tell it when.
     A hub that never answers costs nothing: it shows the frame at load. */
  const Painted = {
    sent: false,
    tell(what) {
      this.tellData({ forge: what });
    },
    tellData(data) {
      try { window.parent.postMessage(data, "*"); } catch (err) { /* no parent */ }
    },
    ready() {
      if (window.parent !== window) this.tell("ready");
    },
    themed() {
      if (this.sent) return;
      this.sent = true;
      const raf = Rest.realRaf || window.requestAnimationFrame.bind(window);
      let done = false;
      const send = () => { if (!done) { done = true; this.tell("painted"); } };
      raf(() => raf(send));
      setTimeout(send, 250); // a frame held back (resting, throttled) is no reason to wait
    },
  };

  /* Does this page hold work that is not saved yet? (2026-10-20 sweep)
     The hub asks before it closes the app, reloads it (the reload button,
     Ctrl+R, Try again) or reloads it by itself after the backend restarted:
     a frame the hub removes gets no beforeunload, so without this question
     unsaved work went with it silently.
     The answer is yes when the page said so (ForgeUnsaved.set(true)), or
     when one of its own beforeunload handlers would hold the page: the
     question runs them once with a cancelable event, so an app that
     already guards a normal tab close (Cutroom, PixelForge) needs nothing
     new. Those handlers may save as a side effect (a draft, a place), which
     is what they do on any close anyway. */
  const ForgeUnsaved = {
    flag: false,
    set(on) { this.flag = !!on; },
    check() {
      if (this.flag) return true;
      const ev = new Event("beforeunload", { cancelable: true });
      try { window.dispatchEvent(ev); } catch (err) { return false; }
      return ev.defaultPrevented;
    },
  };
  window.ForgeUnsaved = ForgeUnsaved;

  // The hub telling us full screen ended without our button, or asking
  // whether we hold unsaved work.
  window.addEventListener("message", (event) => {
    const msg = event.data;
    if (event.source !== window.parent || !msg) return;
    if (msg.forge === "chrome-state") ForgeChrome._hubSays(msg.hidden);
    if (window.parent !== window) {
      if (msg.forge === "frame") Framed.set(msg.on && Framed.mine());
      if (msg.forge === "action" && typeof msg.id === "string") Framed.act(msg.id);
      if (msg.forge === "tab" && typeof msg.id === "string") Framed.go(msg.id);
      if (msg.forge === "mode" && typeof msg.advanced === "boolean") Framed.setMode(msg.advanced);
    }
    if (msg.forge === "unsaved?") {
      Painted.tellData({ forge: "unsaved", ask: msg.ask, on: ForgeUnsaved.check() });
    }
  });

  /* The app frame (experience plan B4, Relay task 392). Inside Forge, an app
     whose manifest has "frame" sits under one strip the hub draws over its
     window: its name or its place's tabs, its own tabs, Simple/Advanced and a
     More menu; Full screen and Close are on the hub's bar. The frame's name
     says it before the page draws, and the hub says {forge:"frame", on} once
     the page is ready (and again when the layout changes); the page then
     hides what the strip carries (its own Full screen and Close, and whatever
     it marked data-forge-frame-hide) and tells the strip its tab and mode.
     An app whose tabs or mode are not the hash and ForgeMode sets
       window.ForgeFrame = { go(id), tab() -> id, mode(advanced), advanced() -> bool }
     (any of them); otherwise a tab is the location hash, which most apps
     follow, and the mode is ForgeMode. Standalone, in a pop-out or inside
     another app nothing arrives and the page keeps its own header.
     Marks the page can put on its own (hidden) parts instead of code
:
       data-forge-frame-tabs   on its tab row: a strip tab clicks the
                               [data-tab=id] in it; the one with class on or
                               active (or aria-selected) is the tab shown, and
                               the ones not hidden are the strip's tabs
       data-forge-mode-switch  on a Simple/Advanced switch of [data-mode]
                               buttons (or #modeSimple/#modeAdvanced): the
                               strip clicks it and follows its on button
       data-forge-frame-badge="<tab id>"  a count shown on that strip tab
       data-forge-frame-note   a short live line (status, saved note) shown
                               in the strip, so its row can go
       data-forge-frame-action="<id>"  a button of the page's own (Jobs, Show
                               the teacher) the strip carries as a button that
                               clicks it; its text is the label (up to 3) */
  const Framed = {
    on: false,
    hash() {
      try { return decodeURIComponent(location.hash.replace(/^#/, "")); } catch (e) { return location.hash.replace(/^#/, ""); }
    },
    post(msg) {
      if (!this.on || window.parent === window) return;
      try { window.parent.postMessage(msg, "*"); } catch (e) { /* no hub */ }
    },
    tell(id) {
      const f = window.ForgeFrame;
      if (id === undefined) {
        try { id = f && typeof f.tab === "function" ? f.tab() : this.marked() ?? this.hash(); } catch (e) { id = this.hash(); }
      }
      this.post({ forge: "tab-now", id: String(id == null ? "" : id).slice(0, 200) });
    },
    mode(advanced) {
      const f = window.ForgeFrame;
      const m = window.ForgeMode;
      if (typeof advanced !== "boolean") {
        try { advanced = f && typeof f.advanced === "function" ? f.advanced() : m && m.started ? m.on : this.switchOn(); } catch (e) { advanced = undefined; }
      }
      if (typeof advanced === "boolean") this.post({ forge: "mode-now", advanced });
    },
    setMode(advanced) {
      const f = window.ForgeFrame;
      const m = window.ForgeMode;
      const own = document.getElementById(advanced ? "modeAdvanced" : "modeSimple");
      const sw = this.switchButton(advanced);
      try {
        if (f && typeof f.mode === "function") f.mode(advanced);
        else if (sw) sw.click();
        // the page's own switch (hidden, still there): its handlers save the choice the way this app does
        else if (own && (!m || m.started)) own.click();
        else if (m && m.started) m.set(advanced);
      } catch (e) { /* the app's own switch failed */ }
      // the strip only changes when told: say what the page is on now
      setTimeout(() => this.mode(), 0);
    },
    set(on) {
      this.on = !!on;
      document.documentElement.classList.toggle("forge-framed", this.on);
      if (this.on && !document.getElementById("forge-frame-style")) {
        const s = document.createElement("style");
        s.id = "forge-frame-style";
        s.textContent = "html.forge-framed #go-fullscreen, html.forge-framed [data-forge-fullscreen], html.forge-framed #forge-close-app, html.forge-framed [data-forge-frame-hide] { display: none !important; }";
        (document.head || document.documentElement).appendChild(s);
      }
      if (this.on) { this.tell(); this.mode(); this.watch(); this.sent = ""; this.bits(); }
    },
    // the page's tab row (data-forge-frame-tabs) and its tab buttons
    tabRow() { return document.querySelector("[data-forge-frame-tabs]"); },
    tabButtons() {
      const row = this.tabRow();
      return row ? [...row.querySelectorAll("[data-tab]")] : [];
    },
    isOn(b) { return b.classList.contains("on") || b.classList.contains("active") || b.getAttribute("aria-selected") === "true" || b.getAttribute("aria-pressed") === "true"; },
    shown(el) { return !el.hidden && getComputedStyle(el).display !== "none"; },
    // the marked row's tab shown (undefined: no marked row, so the hash says)
    marked() {
      const all = this.tabButtons();
      if (!all.length) return undefined;
      const b = all.find((x) => this.isOn(x));
      return b ? b.dataset.tab : "";
    },
    switchButton(advanced) {
      const sw = document.querySelector("[data-forge-mode-switch]");
      if (!sw) return null;
      return sw.querySelector(`[data-mode="${advanced ? "advanced" : "simple"}"]`) || sw.querySelector(advanced ? "#modeAdvanced" : "#modeSimple");
    },
    switchOn() {
      const a = this.switchButton(true);
      return a ? this.isOn(a) : undefined;
    },
    // badges, the note line and the tabs the page shows, sent when they change
    sent: "",
    bits() {
      // a note may hide itself in the page (data-forge-frame-hide): the strip carries it
      const seen = (el) => this.shown(el) || (!el.hidden && el.matches("[data-forge-frame-hide]") && el.style.display !== "none");
      const text = (el) => (seen(el) ? (el.textContent || "").replace(/\s+/g, " ").trim() : "");
      // (an action button is hidden by the page while the strip carries it)
      const badges = {};
      document.querySelectorAll("[data-forge-frame-badge]").forEach((el) => {
        const t = text(el);
        if (t) badges[el.getAttribute("data-forge-frame-badge")] = t.slice(0, 12);
      });
      const note = [...document.querySelectorAll("[data-forge-frame-note]")].map(text).filter(Boolean).join(" \u00b7 ").slice(0, 160);
      const all = this.tabButtons();
      const shown = all.length ? all.filter((b) => this.shown(b)).map((b) => b.dataset.tab) : null;
      const actions = [...document.querySelectorAll("[data-forge-frame-action]")]
        .filter((el) => seen(el) && text(el))
        .slice(0, 3)
        // "Jobs" and its count "2" are two parts: "Jobs 2"
        .map((el) => ({ id: el.getAttribute("data-forge-frame-action") || "", label: [...el.childNodes].map((n) => (n.textContent || "").replace(/\s+/g, " ").trim()).filter(Boolean).join(" ").slice(0, 40),
          pressed: el.getAttribute("aria-expanded") === "true" || el.getAttribute("aria-pressed") === "true" }));
      const msg = { forge: "strip", note, badges, shown, actions };
      const key = JSON.stringify(msg);
      if (key === this.sent) return;
      this.sent = key;
      this.post(msg);
    },
    // watch the marked parts (not the whole page: some apps redraw a lot)
    watching: false,
    watch() {
      if (this.watching) return;
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => this.watch(), { once: true });
        return;
      }
      this.watching = true;
      // one send per burst of changes, saying everything any of them touched
      let soon = 0;
      const due = { tab: false, mode: false };
      const later = (tab, mode) => {
        due.tab = due.tab || tab;
        due.mode = due.mode || mode;
        clearTimeout(soon);
        soon = setTimeout(() => {
          this.bits();
          if (due.tab) this.tell();
          if (due.mode) this.mode();
          due.tab = due.mode = false;
        }, 30);
      };
      const deep = { attributes: true, childList: true, characterData: true, subtree: true };
      const tabs = new MutationObserver(() => later(true, false));
      const sw = new MutationObserver(() => later(false, true));
      const rest = new MutationObserver(() => later(false, false));
      const row = this.tabRow();
      if (row) tabs.observe(row, deep);
      const swEl = document.querySelector("[data-forge-mode-switch]");
      if (swEl) sw.observe(swEl, deep);
      document.querySelectorAll("[data-forge-frame-badge], [data-forge-frame-note], [data-forge-frame-action]").forEach((el) => rest.observe(el, deep));
      // a mode or a sign-in on <body> can show or hide tabs by CSS
      if (row) rest.observe(document.body, { attributes: true });
      this.bits();
      this.tell();
      this.mode();
    },
    // the strip's copy of a marked button was clicked
    act(id) {
      const el = [...document.querySelectorAll("[data-forge-frame-action]")].find((x) => x.getAttribute("data-forge-frame-action") === id);
      if (el && !el.disabled) el.click();
    },
    // the frame's name says this page's origin (a page the frame navigated to is not framed)
    mine() {
      const named = /(?:^|\s)forge-framed@(\S+)/.exec(window.name || "");
      return !!named && named[1] === location.origin;
    },
    go(id) {
      const f = window.ForgeFrame;
      if (f && typeof f.go === "function") {
        try { f.go(id); } catch (e) { /* the app's own handler failed: leave the page as it is */ }
        return;
      }
      const b = this.tabButtons().find((x) => x.dataset.tab === id);
      if (b) {
        b.click();
        // the same tab again changes nothing the watcher sees: say it anyway
        setTimeout(() => this.tell(), 0);
        return;
      }
      if (this.tabRow()) return;
      // the same hash again is no hashchange: say it anyway, so the app goes back to that tab's top
      if (this.hash() === id) window.dispatchEvent(new HashChangeEvent("hashchange"));
      else location.hash = id;
    },
  };
  // after the app's own hashchange handler has switched its page
  window.addEventListener("hashchange", () => setTimeout(() => Framed.tell(), 0));
  // the frame's name carries the app's origin, so a page the frame navigates
  // to later (another site, another app) does not take it as its own
  if (window.parent !== window && Framed.mine()) Framed.set(true);

  // The whole point of this file: a global the apps can actually see.
  window.ForgeChrome = ForgeChrome;

  /* Is this app the one on screen?
     The hub posts {forge:"visible", visible:bool} to every mounted app when
     the workspace changes or the window hides. ForgeVisible.on is that flag
     (true standalone, where there is no hub), and "forge-visible" fires on
     document with detail {visible}, so a page can pause a poll or an
     animation behind the home screen instead of running for nobody.
     An app that holds other apps in iframes (Acchan's tabs) passes the flag
     on: a child frame is visible only while this page is and the frame
     itself is laid out, so one inside a display:none pane rests. An
     IntersectionObserver notices a pane being shown or hidden, so the app
     does not have to say so. */
  const ForgeVisible = {
    on: true,
    seen: null,
    init() {
      addEventListener("message", (e) => {
        const m = e.data;
        if (!m || m.forge !== "visible") return;
        const next = !!m.visible;
        if (next !== this.on) {
          this.on = next;
          Rest.set(!next);
          document.dispatchEvent(new CustomEvent("forge-visible", { detail: { visible: next } }));
        }
        this.tellFrames();
      });
      if (window.IntersectionObserver) {
        this.seen = new IntersectionObserver((entries) => entries.forEach((en) => this.tell(en.target)));
      }
      // load does not bubble, but a capturing listener on document (not
      // window, which an element's load never reaches) sees every iframe's
      // load: a frame added or navigated later learns the state it starts in.
      document.addEventListener("load", (e) => {
        if (e.target && e.target.tagName === "IFRAME") {
          if (this.seen) this.seen.observe(e.target);
          this.tell(e.target);
        }
      }, true);
    },
    tell(frame) {
      try {
        frame.contentWindow.postMessage(
          { forge: "visible", visible: this.on && frame.getClientRects().length > 0 }, "*");
      } catch (err) { /* a frame being torn down */ }
    },
    tellFrames() {
      document.querySelectorAll("iframe").forEach((f) => this.tell(f));
    },
  };

  /* Off screen inside Forge, an app rests like a browser's background tab
     (B18): its CSS animations pause and its animation frames wait until it is
     back, when the held ones run together. Timers, network and media carry
     on. WebKit keeps an iframe that is merely invisible running at full
     rate, so without this every open game and effect drew for nobody.
     Standalone (no hub above) nothing is wrapped. */
  const Rest = {
    on: false, held: new Map(), next: 1e9, realRaf: null,
    install() {
      if (window.parent === window) return;
      const realRaf = window.requestAnimationFrame.bind(window);
      const realCancel = window.cancelAnimationFrame.bind(window);
      this.realRaf = realRaf;
      window.requestAnimationFrame = (cb) => {
        if (!Rest.on) return realRaf(cb);
        const id = Rest.next++;
        Rest.held.set(id, cb);
        return id;
      };
      window.cancelAnimationFrame = (id) => {
        if (!Rest.held.delete(id)) realCancel(id);
      };
      const style = document.createElement("style");
      style.textContent = "html.forge-resting *, html.forge-resting *::before, html.forge-resting *::after { animation-play-state: paused !important; }";
      (document.head || document.documentElement).appendChild(style);
    },
    set(resting) {
      if (!this.realRaf) return;
      this.on = resting;
      document.documentElement.classList.toggle("forge-resting", resting);
      if (resting || !this.held.size) return;
      const waiting = [...this.held.values()];
      this.held.clear();
      this.realRaf((t) => waiting.forEach((cb) => {
        try { cb(t); } catch (err) { setTimeout(() => { throw err; }); }
      }));
    },
  };
  Rest.install();
  ForgeVisible.init();
  window.ForgeVisible = ForgeVisible;

  if (document.readyState === "loading") {
    // When the app's own full-screen button is already parsed (this script at
    // the end of <body>), put Close app beside it now, before the first paint,
    // instead of at DOMContentLoaded, which nudged the header after it drew.
    if (document.getElementById("go-fullscreen") || document.querySelector("[data-forge-fullscreen]")) {
      ForgeChrome.mount();
    }
    document.addEventListener("DOMContentLoaded", () => { ForgeChrome.mount(); Painted.ready(); });
  } else {
    ForgeChrome.mount();
    Painted.ready();
  }
})();
