/* forge_lightbox.js -- click an image, see it big, zoom and pan it.

   One include turns it on for a page:

     <script src="/shared/forge_lightbox.js"></script>

   It loads forge_lightbox.css from beside itself, then any click on an <img>
   that is worth zooming opens it filling the window. Mouse wheel or pinch
   zooms around the pointer, dragging pans, double-click resets (or zooms in
   when already reset), and a click outside the image, Escape or the X in the
   corner closes it. + - and 0 zoom from the keyboard.

   Which images open is decided here, so an app only states its exceptions:

     data-no-zoom            on an image or any ancestor: never open it.
     data-zoom               on an image: always open it (small or not).
     data-zoom-src="<url>"   on an image: open this (say the full size)
                             instead of the thumbnail shown.
     data-skip="<selectors>" on the script tag: images matching these never
                             open (game sprites, avatars, icons).
     data-zoom="<selectors>" on the script tag: images matching these always
                             open, e.g. a 28 px attachment chip.

   Without a rule, an image is skipped when the app already handles its click
   (inside a link, a button, [role=button] or [onclick], or showing a pointer
   cursor), when it is smaller than 48 px, or when it has not loaded.

   While the viewer is up the page behind gets no keys. It covers the app's
   own area (an app is a frame inside Forge), not the hub's sidebar. In
   Forge's "app alone" full screen the first Esc leaves full screen (Forge
   takes that key before the page) and the second closes the viewer.

   ForgeZoom is the zoom-and-pan engine on its own, for a page with a viewer
   of its own (Claude's Pictures keeps its arrows and Copy path):

     const zoom = ForgeZoom.attach(stageEl, imgEl);  // zoom.reset() on change

   The arithmetic is plain functions (ForgeZoom.math) so node can test it:
   tests/forge_lightbox.test.js. */
(function () {
  "use strict";

  const MIN_SIDE = 48; // px on screen: smaller images are icons
  const MAX_ZOOM = 40;

  // ---- pure arithmetic ---------------------------------------------------

  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  /** One axis of the pan. The image's centre sits at `center` (in view
      coordinates, untransformed) with length `size`; scaled by `s` and moved
      by `t`. Smaller than the view: stays centred where the layout put it.
      Bigger: may move only while it still covers the whole view. */
  function clampAxis(t, s, size, center, view) {
    const half = (size * s) / 2;
    if (size * s <= view) return 0;
    return clamp(t, view - center - half, half - center);
  }

  /** The zoom limit for an image shown at `shown` px wide whose file is
      `natural` px wide: at least 4x, or 3x its real pixels. */
  function maxZoom(shown, natural) {
    if (!(shown > 0)) return 4;
    return clamp(Math.max(4, (3 * (natural || shown)) / shown), 1, MAX_ZOOM);
  }

  /** Zoom from scale s to s2 keeping the point p (offset from the image's
      untransformed centre) still on screen. Returns the new translation. */
  function zoomAt(t, s, s2, p) {
    return p - ((p - t) * s2) / s;
  }

  /** The scale that fits a natural w x h into a box, allowing upscale. */
  function fitScale(w, h, boxW, boxH) {
    if (!(w > 0 && h > 0)) return 1;
    return Math.min(boxW / w, boxH / h);
  }

  /** The wheel delta in pixels whatever the deltaMode (lines are ~16 px). */
  function wheelPixels(dy, mode) {
    return mode === 1 ? dy * 16 : mode === 2 ? dy * 400 : dy;
  }

  /** How much one wheel event zooms: a pinch on a touchpad arrives as a
      ctrl+wheel with small deltas, so it gets a stronger factor. */
  function wheelFactor(dyPixels, pinch) {
    return Math.exp(-clamp(dyPixels, -120, 120) * (pinch ? 0.01 : 0.0025));
  }

  /** Does a clicked image open? `f` holds the facts gathered from the DOM. */
  function wantsZoom(f) {
    if (f.optedOut) return false;
    if (!f.loaded) return false;
    if (f.forced) return true;
    if (f.interactive || f.pointer) return false;
    return f.width >= MIN_SIDE && f.height >= MIN_SIDE;
  }

  const math = { clampAxis, maxZoom, zoomAt, fitScale, wheelPixels, wheelFactor, wantsZoom, MIN_SIDE };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { math };
    return; // node: arithmetic only
  }

  // ---- the engine ----------------------------------------------------------

  /** Make `img` zoomable inside `stage`. The image keeps its own layout
      (that is scale 1); the engine only sets its transform. */
  function attach(stage, img, opts = {}) {
    const st = { s: 1, x: 0, y: 0 };
    const pointers = new Map();
    let pinch = null; // {d, s, cx, cy}
    let drag = null; // {x, y, tx, ty}
    let moved = false;
    let gestureS = 1;

    img.classList.add("fz-img");
    img.draggable = false;
    stage.classList.add("fz-stage");

    function apply() {
      img.style.transform = st.s === 1 && !st.x && !st.y
        ? "" : `translate(${st.x}px, ${st.y}px) scale(${st.s})`;
      img.classList.toggle("fz-zoomed", st.s > 1.001);
      if (opts.onChange) opts.onChange(st.s);
    }

    // The untransformed box of the image, relative to the stage.
    function base() {
      const r = img.getBoundingClientRect();
      const v = stage.getBoundingClientRect();
      const w = r.width / st.s;
      const h = r.height / st.s;
      return {
        w, h, vw: v.width, vh: v.height,
        cx: r.left + r.width / 2 - st.x - v.left,
        cy: r.top + r.height / 2 - st.y - v.top,
        left: v.left, top: v.top,
      };
    }

    function set(s, x, y) {
      const b = base();
      const lim = maxZoom(b.w, img.naturalWidth);
      st.s = clamp(s, 1, lim);
      st.x = clampAxis(x, st.s, b.w, b.cx, b.vw);
      st.y = clampAxis(y, st.s, b.h, b.cy, b.vh);
      apply();
    }

    /** Zoom by `k` around the screen point (px, py); the centre without one. */
    function zoomBy(k, px, py) {
      const b = base();
      if (!(b.w > 0)) return;
      const ox = px === undefined ? 0 : px - b.left - b.cx;
      const oy = py === undefined ? 0 : py - b.top - b.cy;
      const s2 = clamp(st.s * k, 1, maxZoom(b.w, img.naturalWidth));
      set(s2, zoomAt(st.x, st.s, s2, ox), zoomAt(st.y, st.s, s2, oy));
    }

    function reset() {
      st.s = 1; st.x = 0; st.y = 0;
      pinch = null; drag = null;
      pointers.clear(); // a finger lifted after a close never reports here
      moved = false;
      apply();
    }

    // A new file (thumbnail to full size) or a resized window changes the
    // image's box: keep a zoomed view inside the new limits.
    const reclamp = () => { if (st.s !== 1 || st.x || st.y) set(st.s, st.x, st.y); };
    img.addEventListener("load", reclamp);
    window.addEventListener("resize", reclamp);

    stage.addEventListener("wheel", (e) => {
      e.preventDefault();
      const dy = wheelPixels(e.deltaY, e.deltaMode);
      zoomBy(wheelFactor(dy, e.ctrlKey), e.clientX, e.clientY);
    }, { passive: false });

    // WebKit's own touchpad pinch, where it is sent.
    stage.addEventListener("gesturestart", (e) => { e.preventDefault(); gestureS = 1; });
    stage.addEventListener("gesturechange", (e) => {
      e.preventDefault();
      zoomBy(e.scale / gestureS, e.clientX, e.clientY);
      gestureS = e.scale;
    });

    stage.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest("button, a, input")) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      moved = false;
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, s: st.s, x: st.x, y: st.y,
                  cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2 };
        drag = null;
      } else if (pointers.size === 1) {
        drag = { x: e.clientX, y: e.clientY, tx: st.x, ty: st.y };
      }
    });

    // Capture the pointer only once it really drags: captured from the press,
    // the click that follows would be aimed at the stage, not the image.
    const capture = (id) => {
      try { stage.setPointerCapture(id); } catch (err) { /* already released */ }
    };

    stage.addEventListener("pointermove", (e) => {
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pinch && pointers.size >= 2) {
        const [a, b] = [...pointers.values()];
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        const bx = base();
        const s2 = clamp(pinch.s * (d / pinch.d), 1, maxZoom(bx.w, img.naturalWidth));
        const ox = pinch.cx - bx.left - bx.cx;
        const oy = pinch.cy - bx.top - bx.cy;
        set(s2, zoomAt(pinch.x, pinch.s, s2, ox) + ((a.x + b.x) / 2 - pinch.cx),
            zoomAt(pinch.y, pinch.s, s2, oy) + ((a.y + b.y) / 2 - pinch.cy));
        if (!moved) { moved = true; [...pointers.keys()].forEach(capture); }
      } else if (drag) {
        const dx = e.clientX - drag.x;
        const dy = e.clientY - drag.y;
        if (!moved && Math.abs(dx) + Math.abs(dy) > 4) { moved = true; capture(e.pointerId); }
        if (moved && st.s > 1) set(st.s, drag.tx + dx, drag.ty + dy);
      }
    });

    const up = (e) => {
      pointers.delete(e.pointerId);
      if (pointers.size < 2) pinch = null;
      if (pointers.size === 0) drag = null;
    };
    stage.addEventListener("pointerup", up);
    stage.addEventListener("pointercancel", up);

    // A drag ends in a click; it must not count as "clicked outside".
    stage.addEventListener("click", (e) => {
      if (moved) { e.stopPropagation(); e.preventDefault(); moved = false; }
    }, true);

    stage.addEventListener("dblclick", (e) => {
      if (e.target !== img) return;
      e.preventDefault();
      if (st.s > 1.001) reset();
      else zoomBy(2.5, e.clientX, e.clientY);
    });

    /** + - 0 from the keyboard; returns true when it used the key. */
    function key(e) {
      if (e.ctrlKey || e.metaKey || e.altKey) return false;
      if (e.key === "+" || e.key === "=") zoomBy(1.25);
      else if (e.key === "-" || e.key === "_") zoomBy(0.8);
      else if (e.key === "0") reset();
      else return false;
      return true;
    }

    return { reset, zoomBy, key, get scale() { return st.s; } };
  }

  window.ForgeZoom = { attach, math };

  // ---- the lightbox ----------------------------------------------------------

  const script = document.currentScript;
  const skipSel = ((script && script.dataset.skip) || "").trim();
  const zoomSel = ((script && script.dataset.zoom) || "").trim();

  if (script && script.src && !document.querySelector("link[data-forge-lightbox]")) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = script.src.replace(/\.js(\?.*)?$/, ".css$1");
    link.dataset.forgeLightbox = "";
    document.head.appendChild(link);
  }

  const safeMatch = (node, sel) => {
    if (!sel) return false;
    try { return node.matches(sel); } catch (e) { return false; }
  };
  const safeClosest = (node, sel) => {
    if (!sel) return null;
    try { return node.closest(sel); } catch (e) { return null; }
  };

  /** The facts wantsZoom needs, read from the page. */
  function facts(img) {
    const r = img.getBoundingClientRect();
    const parent = img.parentElement;
    const own = img.classList.contains("fz-hint") ? "" : getComputedStyle(img).cursor;
    return {
      // .fz-img: already inside a zoom viewer (ours or an app's own).
      optedOut: img.classList.contains("fz-img") || !!img.closest("[data-no-zoom]")
        || !!safeClosest(img, skipSel),
      forced: img.hasAttribute("data-zoom") || safeMatch(img, zoomSel),
      loaded: img.complete && img.naturalWidth > 0,
      interactive: !!(parent && parent.closest("a[href], button, [role=button], [onclick], label, summary")),
      pointer: own === "pointer" || (!!parent && getComputedStyle(parent).cursor === "pointer"),
      width: r.width,
      height: r.height,
    };
  }

  let box = null; // the overlay, built on first use
  let zoom = null;
  let lastFocus = null;
  // The second click of a double-click on a page image lands on the viewer
  // it just opened, at the same spot: it must neither close it nor zoom in.
  let grace = null; // {t, x, y} of the click that opened it
  const GRACE_MS = 450;
  const GRACE_PX = 16;

  function build() {
    box = document.createElement("div");
    box.className = "fl-overlay";
    box.hidden = true;
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.setAttribute("aria-label", "Image viewer");
    box.innerHTML =
      '<div class="fl-stage"><img class="fl-img" alt=""></div>' +
      '<button type="button" class="fl-close" title="Close (Esc)" aria-label="Close">✕</button>' +
      '<div class="fl-hint"><span class="fl-pct">100%</span>' +
      '<span>scroll or pinch to zoom · drag to move · double-click to reset · Esc to close</span></div>';
    document.body.appendChild(box);
    const early = (e) => {
      if (grace && performance.now() - grace.t < GRACE_MS
          && Math.hypot(e.clientX - grace.x, e.clientY - grace.y) < GRACE_PX) {
        e.stopPropagation();
        e.preventDefault();
      }
    };
    box.addEventListener("click", early, true);
    box.addEventListener("dblclick", early, true);
    const stage = box.querySelector(".fl-stage");
    const img = box.querySelector(".fl-img");
    const pct = box.querySelector(".fl-pct");
    zoom = attach(stage, img, {
      onChange: (s) => { pct.textContent = Math.round(s * 100) + "%"; },
    });
    img.addEventListener("load", fit);
    img.addEventListener("error", () => {
      img.classList.remove("fl-loading");
      pct.textContent = "could not load the image";
    });
    box.querySelector(".fl-close").addEventListener("click", close);
    // Outside the image (a drag never gets here: the engine eats its click).
    stage.addEventListener("click", (e) => { if (e.target !== img) close(); });
    window.addEventListener("resize", () => { if (!box.hidden) fit(); });
  }

  /** Size the image to fill the window (upscaling small ones). */
  function fit() {
    const img = box.querySelector(".fl-img");
    const k = fitScale(img.naturalWidth, img.naturalHeight,
                       window.innerWidth * 0.96, window.innerHeight * 0.92);
    img.style.width = Math.max(1, Math.round(img.naturalWidth * k)) + "px";
    img.style.height = Math.max(1, Math.round(img.naturalHeight * k)) + "px";
    img.classList.remove("fl-loading");
    zoom.reset();
  }

  /** Open `src` in the viewer. */
  function open(src, alt) {
    if (!box) build();
    const img = box.querySelector(".fl-img");
    lastFocus = document.activeElement;
    grace = null;
    zoom.reset();
    img.alt = alt || "";
    if (img.getAttribute("src") === src && img.complete && img.naturalWidth) fit();
    else {
      img.style.width = "";
      img.style.height = "";
      img.classList.add("fl-loading");
      img.src = src;
    }
    box.hidden = false;
    document.documentElement.classList.add("fl-open");
    box.querySelector(".fl-close").focus({ preventScroll: true });
  }

  function close() {
    if (!box || box.hidden) return;
    box.hidden = true;
    document.documentElement.classList.remove("fl-open");
    zoom.reset();
    if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true });
  }

  const isOpen = () => !!box && !box.hidden;

  // Capture phase on window, so no key reaches the page behind while the
  // viewer is up: not its Escape, and not Delete, Enter, arrows or "/" (the
  // Files app would trash or open the file being looked at). Tab stays on
  // the X, the one control; Enter or Space on it closes.
  window.addEventListener("keydown", (e) => {
    if (!isOpen()) return;
    e.stopImmediatePropagation();
    const closeBtn = box.querySelector(".fl-close");
    const onClose = e.target === closeBtn;
    if (e.key === "Escape") close();
    else if (e.key === "Tab") closeBtn.focus({ preventScroll: true });
    else if (zoom.key(e)) { /* zoomed */ }
    else if (onClose && (e.key === "Enter" || e.key === " ")) return; // the button's own press
    else if (e.ctrlKey || e.metaKey || e.altKey) return; // copy and the like
    e.preventDefault();
  }, true);

  // Bubble phase: an app handler that already took the click (and said so
  // with preventDefault) wins.
  document.addEventListener("click", (e) => {
    const img = e.target;
    if (e.defaultPrevented || e.button !== 0 || !(img instanceof HTMLImageElement)) return;
    if (!wantsZoom(facts(img))) return;
    e.preventDefault();
    open(img.dataset.zoomSrc || img.currentSrc || img.src, img.alt);
    grace = { t: performance.now(), x: e.clientX, y: e.clientY };
  });

  // The zoom-in cursor on images that would open.
  document.addEventListener("pointerover", (e) => {
    const img = e.target;
    if (!(img instanceof HTMLImageElement) || img.classList.contains("fz-img")) return;
    img.classList.remove("fz-hint");
    img.classList.toggle("fz-hint", wantsZoom(facts(img)));
  });

  window.ForgeLightbox = { open, close, isOpen, wantsZoom: (img) => wantsZoom(facts(img)) };
})();
