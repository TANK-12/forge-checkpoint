/* forge_media.js - an app's audio and video, for the hub's Now playing.

   Loaded by forge_chrome.js when an app runs inside the Forge hub. It tells
   the hub what this app is playing and takes commands back, so the bar's
   music button can pause, skip, seek and turn up whatever is playing in any
   app, and "Go to it" knows which app that is (the owner, 2026-09-26: the
   Media app kept playing and the music button's pause did nothing to it).

   No wiring needed: any <audio> or <video>, in the page or made with
   new Audio(), is seen when it plays. An app with its own playlist may add
   more before or after this loads:

     window.ForgeMedia = { next() {...}, prev() {...},
                           describe(el) { return { title, artist, artwork }; } };

   Messages to the hub:  {forge: "media", state, title, artist, artwork,
                          kind, current, duration, volume, canNext, canPrev}
   Messages from the hub: {forge: "media-cmd", op, time?, volume?}
                          op: toggle | play | pause | seek | volume | next | prev
   Volume runs 0..2: past 1 the element is boosted through Web Audio, which
   only works for media from the app's own server (anything else would play
   silent through Web Audio, so it stays at 1). */
(() => {
  if (window.parent === window || window.__forgeMedia) return;
  window.__forgeMedia = true;
  // Looked up on use: an app may set window.ForgeMedia after this loads.
  if (!window.ForgeMedia) window.ForgeMedia = {};
  const hooks = () => window.ForgeMedia || {};

  const watched = new WeakSet();
  let active = null;
  let lastSent = 0;
  const boost = new WeakMap(); // element -> { ctx, gain }

  const post = (msg) => {
    try { window.parent.postMessage(Object.assign({ forge: "media" }, msg), "*"); } catch (e) { /* no hub */ }
  };

  function nameFromSrc(el) {
    const src = el.currentSrc || el.src || "";
    try {
      const u = new URL(src, location.href);
      const path = u.searchParams.get("path") || u.searchParams.get("file") || u.pathname;
      const leaf = decodeURIComponent(path.split("/").pop() || "");
      return leaf.replace(/\.[a-z0-9]{2,4}$/i, "");
    } catch (e) {
      return "";
    }
  }

  function describe(el) {
    let custom = null;
    try { custom = hooks().describe ? hooks().describe(el) : null; } catch (e) { custom = null; }
    const meta = (navigator.mediaSession && navigator.mediaSession.metadata) || null;
    const art = custom && custom.artwork ? custom.artwork
      : meta && meta.artwork && meta.artwork.length ? meta.artwork[0].src : el.poster || "";
    let artwork = "";
    try { artwork = art ? new URL(art, location.href).href : ""; } catch (e) { artwork = ""; }
    return {
      title: (custom && custom.title) || (meta && meta.title) || el.title || el.dataset.title
        || nameFromSrc(el) || document.title,
      artist: (custom && custom.artist) || (meta && meta.artist) || "",
      artwork,
    };
  }

  function report(el, force) {
    if (!el) return;
    const now = performance.now();
    if (!force && now - lastSent < 900) return;
    lastSent = now;
    const b = boost.get(el);
    post(Object.assign(describe(el), {
      state: el.ended ? "ended" : el.paused ? "paused" : "playing",
      kind: el.tagName.toLowerCase(),
      current: el.currentTime || 0,
      duration: Number.isFinite(el.duration) ? el.duration : 0,
      volume: el.muted ? 0 : el.volume * (b ? b.gain.gain.value : 1),
      canBoost: sameOrigin(el),
      canNext: !!hooks().next,
      canPrev: true,
    }));
  }

  function watch(el) {
    if (!el || watched.has(el)) return;
    watched.add(el);
    const bump = () => { active = el; report(el, true); };
    el.addEventListener("play", bump);
    el.addEventListener("pause", () => report(el, true));
    el.addEventListener("ended", () => report(el, true));
    el.addEventListener("volumechange", () => report(el, true));
    el.addEventListener("loadedmetadata", () => { if (el === active) report(el, true); });
    el.addEventListener("timeupdate", () => { if (el === active) report(el, false); });
  }

  // Elements in the page: media events do not bubble, but a capturing
  // listener on the document still hears them.
  document.addEventListener("play", (e) => {
    if (e.target instanceof HTMLMediaElement) { watch(e.target); active = e.target; report(active, true); }
  }, true);
  // Elements never put in the page (new Audio()) only show up through play().
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (...args) {
    watch(this);
    return play.apply(this, args);
  };

  function sameOrigin(el) {
    try {
      const u = new URL(el.currentSrc || el.src || "", location.href);
      return u.origin === location.origin || u.protocol === "blob:" || u.protocol === "data:";
    } catch (e) {
      return false;
    }
  }

  function setVolume(el, v) {
    const want = Math.max(0, Math.min(2, Number(v) || 0));
    el.muted = false;
    let b = boost.get(el);
    if (want > 1 && !b && sameOrigin(el)) {
      try {
        const ctx = new AudioContext();
        const gain = ctx.createGain();
        ctx.createMediaElementSource(el).connect(gain);
        gain.connect(ctx.destination);
        b = { ctx, gain };
        boost.set(el, b);
      } catch (e) {
        b = null;
      }
    }
    if (b) {
      el.volume = Math.min(1, want);
      b.gain.gain.value = want > 1 ? want : 1;
      if (b.ctx.state === "suspended") b.ctx.resume().catch(() => {});
    } else {
      el.volume = Math.min(1, want);
    }
    report(el, true);
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const m = event.data;
    if (!m || m.forge !== "media-cmd") return;
    const el = active;
    const run = (fn) => { try { fn(); } catch (e) { /* the app's own hook failed */ } };
    switch (m.op) {
      case "toggle":
        if (el) el.paused ? el.play().catch(() => {}) : el.pause();
        break;
      case "play":
        if (el) el.play().catch(() => {});
        break;
      case "pause":
        if (el) el.pause();
        break;
      case "seek":
        if (el && Number.isFinite(Number(m.time))) {
          el.currentTime = Math.max(0, Math.min(Number(m.time), el.duration || Number(m.time)));
        }
        break;
      case "volume":
        if (el) setVolume(el, m.volume);
        break;
      case "next":
        if (hooks().next) run(() => hooks().next());
        else if (el && Number.isFinite(el.duration)) el.currentTime = el.duration;
        break;
      case "prev":
        if (hooks().prev) run(() => hooks().prev());
        else if (el) el.currentTime = 0;
        break;
      case "report":
        report(el, true);
        break;
      default:
    }
  });

  window.addEventListener("pagehide", () => post({ state: "gone" }));
})();
