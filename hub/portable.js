/* Forge portable bridge: the hub page as forge_portable.py serves it.

   forge.py shows this page in a GTK WebKit view and the page talks to it
   through window.webkit.messageHandlers.forge; forge.py answers by running
   script in the page (forgeSetStatus, forgeMusic, forgeSetFullscreen...).
   A release has no such channel, so forge_portable.py rewrites those calls to
   window.forgeBridge, defined here, and sets window.FORGE_PORTABLE (token,
   system, what to hide) before this script runs:

   - messages go to the launcher as POSTs to /forge/bridge, in order, once the
     event stream is open (the answers come back on it);
   - the launcher's answers and status changes arrive on /forge/events and are
     handed to the same window.forge* functions forge.py calls;
   - full screen and popping an app out are done here, by the page itself:
     only a page may ask its window for full screen, and window.open makes the
     second window (in a pywebview window, which refuses window.open, the
     launcher makes it);
   - the controls of features this system does not have are hidden, and the
     home widgets it cannot feed are taken out of the widget menu;
   - the system numbers arrive every few seconds as a "stats" event.

   No app is named here; nothing here runs under forge.py. */
(() => {
  const config = window.FORGE_PORTABLE || {};
  const token = config.token || "";
  const call = (name, value) => {
    try { if (typeof window[name] === "function") window[name](value); } catch (e) { console.error(e); }
  };

  // --- Forge's own keys: forge.py's window catches them before the page --------
  // Here the page does (theme.page_keys, {signature: action}, from the launcher):
  // on the hub itself, and from each app's frame, whose shared/forge_chrome.js
  // is told the signatures once it is ready and passes a match up.
  // keySig has a twin in shared/forge_chrome.js; forge_portable.key_signature.
  const keySig = (e) => {
    const c = e.code || "";
    const k = /^[a-z0-9]$/i.test(e.key) ? e.key : /^Key[A-Z]$/.test(c) ? c.slice(3)
      : /^Digit[0-9]$/.test(c) ? c.slice(5) : c === "Space" ? "space" : e.key;
    return [e.ctrlKey && "ctrl", e.altKey && "alt", e.shiftKey && "shift", e.metaKey && "meta"]
      .filter(Boolean).concat(String(k).toLowerCase()).join("+");
  };
  const pageKeys = () => (window.FORGE_THEME || {}).page_keys || {};
  const keyRun = (action) => {
    if (action === "fullscreen") return document.getElementById("full-btn")?.click();
    call("forgeKey", action);
  };
  document.addEventListener("keydown", (e) => {
    const action = pageKeys()[keySig(e)];
    if (!action) return;
    e.preventDefault();
    e.stopPropagation();
    keyRun(action);
  }, true);
  addEventListener("message", (e) => {
    const msg = e.data;
    if (!msg || typeof msg !== "object") return;
    if (![...document.querySelectorAll("iframe")].some((f) => f.contentWindow === e.source)) return;
    if (msg.forge === "ready") e.source.postMessage({ forge: "page-keys", keys: Object.keys(pageKeys()) }, "*");
    if (msg.forge === "key" && typeof msg.sig === "string" && pageKeys()[msg.sig]) keyRun(pageKeys()[msg.sig]);
  });

  // --- what this system cannot do: hidden, not left as dead buttons -----------
  if (Array.isArray(config.hide) && config.hide.length) {
    const style = document.createElement("style");
    style.id = "forge-portable-hide";
    style.textContent = config.hide.map((s) => `${s} { display: none !important; }`).join("\n");
    document.head.appendChild(style);
  }
  // shared/forge_widgets.js defines every widget; the ones this system has no
  // numbers for go from its list as soon as it has run, before the hub mounts
  // the widgets (a saved or starter layout then simply leaves them out)
  const cutWidgets = Array.isArray(config.widgets) ? config.widgets : [];
  if (cutWidgets.length) {
    document.addEventListener("load", (e) => {
      const w = window.ForgeWidgets;
      if (!w || !w.KINDS || !(e.target instanceof HTMLScriptElement)) return;
      if (!/forge_widgets\.js(\?|$)/.test(e.target.src)) return;
      for (const kind of cutWidgets) delete w.KINDS[kind];
    }, true);
  }

  // --- where your things are kept: a button in the tray -------------------------
  const placeButton = () => {
    const tray = document.getElementById("tray");
    if (!tray || document.getElementById("place-btn")) return;
    const button = document.createElement("button");
    button.className = "bar-btn";
    button.id = "place-btn";
    button.title = "Where your things are kept";
    button.setAttribute("aria-label", "Where your things are kept");
    button.innerHTML = '<svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';
    button.addEventListener("click", () => { location.href = "/hub/data.html"; });
    tray.insertBefore(button, document.getElementById("settings-btn"));
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", placeButton);
  else placeButton();

  // --- events from the launcher -----------------------------------------------
  let status = {};
  let opened = null;
  const open = new Promise((resolve) => { opened = resolve; });
  const events = new EventSource("/forge/events?t=" + encodeURIComponent(token));
  const on = (name, handle) => events.addEventListener(name, (e) => {
    let data = null;
    try { data = JSON.parse(e.data); } catch (err) { return; }
    handle(data);
  });
  events.addEventListener("open", () => opened());
  on("status", (next) => {
    status = next || {};
    call("forgeSetStatus", status);
    for (const fn of waiting.splice(0)) fn();
  });
  on("music", (e) => call("forgeMusic", e));
  on("stats", (s) => call("forgeSetStats", s));
  on("media", (players) => call("forgeMediaSys", players));
  // the smart search's answer (shared/forge_ask.py), as forge.py calls forgeAsk
  on("ask", (answer) => call("forgeAsk", answer));
  // the theme switcher's answer (Alt+T), as forge.py runs forgeThemePicked
  on("theme_picked", (answer) => call("forgeThemePicked", answer));
  // where the user's things are kept: a drive pulled out, or a move, takes
  // the window to the page that says so (hub/welcome.html, hub/data.html)
  on("place", (place) => {
    if (!place || place.mode === "ready") return;
    location.replace(place.mode === "moving" ? "/hub/data.html" : "/hub/welcome.html");
  });
  on("quit", () => {
    events.close();
    document.title = "Forge has stopped";
    try { window.close(); } catch (e) {}
    // a browser tab may not close itself: say so instead of leaving a dead page
    setTimeout(() => {
      document.body.innerHTML = '<p style="font: 18px system-ui; padding: 3em; color: #ccc">Forge has stopped. You can close this window.</p>';
    }, 300);
  });

  // --- messages to the launcher, in order --------------------------------------
  let chain = Promise.resolve();
  const post = (text) => {
    chain = chain.then(() => open).then(() => fetch("/forge/bridge", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Forge": token },
      body: text,
    })).catch(() => {});
  };

  // --- full screen: the window's own --------------------------------------------
  const fullscreenOn = () => !!document.fullscreenElement;
  document.addEventListener("fullscreenchange", () => call("forgeSetFullscreen", fullscreenOn()));
  const fullscreen = (on) => {
    try {
      if (on && !fullscreenOn()) {
        // allowed only inside a click or key press: refused, the bar stays as it was
        const asked = document.documentElement.requestFullscreen();
        if (asked && asked.catch) asked.catch(() => call("forgeSetFullscreen", false));
      } else if (!on && fullscreenOn()) {
        document.exitFullscreen().catch(() => {});
      } else {
        call("forgeSetFullscreen", fullscreenOn());
      }
    } catch (e) {
      call("forgeSetFullscreen", false);
    }
  };

  // --- an app in a window of its own --------------------------------------------
  const waiting = [];
  const features = "popup,width=1200,height=800";
  const popout = (key) => {
    if (config.popout === "launcher") return post(JSON.stringify({ popout: key }));
    const app = status[key];
    if (app && app.available) {
      window.open(app.url, "forge-" + key, features);
      return;
    }
    // Not running yet: open the window now, while the click still allows a
    // new window (later it would be blocked as a pop-up), start the app and
    // send the window to it once it is up.
    const win = window.open("", "forge-" + key, features);
    if (win) {
      try {
        win.document.title = "Starting\u2026";
        win.document.body.innerHTML = '<p style="font: 18px system-ui; padding: 3em; color: #888">Starting\u2026</p>';
      } catch (e) {}
    }
    post(JSON.stringify({ start: key }));
    let tries = 0;
    const again = () => {
      const now = status[key];
      if (!now || !now.available) {
        if (++tries < 600) waiting.push(again);
        return;
      }
      if (win && !win.closed) win.location.href = now.url;
    };
    waiting.push(again);
  };

  window.forgeBridge = {
    postMessage(text) {
      let msg = null;
      try { msg = JSON.parse(text); } catch (e) { return; }
      if (msg && typeof msg.window === "boolean") return fullscreen(msg.window);
      if (msg && typeof msg.popout === "string") return popout(msg.popout);
      post(typeof text === "string" ? text : JSON.stringify(msg));
    },
  };
})();
