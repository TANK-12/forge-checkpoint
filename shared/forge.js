/* ==========================================================================
   Forge shared frontend helpers.
   ==========================================================================

   Served by each app's own backend at /shared/forge.js (each web_app.py
   mounts this directory), so a fix here reaches all three tools at once.
   Load it before the app's own <script>:

       <script src="/shared/forge.js"></script>

   Everything here is deliberately DOM-agnostic where it can be: forgeStream()
   hands you raw events and lets each app decide where the text goes, because
   the three tools genuinely differ on that and pretending otherwise is how
   the old per-app copies drifted.
   ========================================================================== */

/* --------------------------------------------------------------------------
   Tiny DOM conveniences
   -------------------------------------------------------------------------- */
function val(id) { return document.getElementById(id).value; }
function setVal(id, v) { document.getElementById(id).value = v ?? ""; }
function checked(id) { return document.getElementById(id).checked; }
function setChecked(id, v) { document.getElementById(id).checked = !!v; }

function toast(msg, kind) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.className = "toast" + (kind ? " " + kind : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), 5000);
}

/* --------------------------------------------------------------------------
   Errors
   --------------------------------------------------------------------------
   A failed request does not always carry a JSON body: an unhandled server
   exception returns plain text, so res.json() throws there and the real error
   gets replaced by a confusing JSON parse error. Always go through this. */
async function errText(res, fallback) {
  try {
    const body = await res.json();
    return body.detail || fallback;
  } catch (e) {
    return `${fallback} (HTTP ${res.status})`;
  }
}

/* --------------------------------------------------------------------------
   Jobs
   --------------------------------------------------------------------------

   THE ONE RULE (for the job queues most apps have): one EventSource per job.

   In shared/forge_jobs.py and the app job managers built like it, job events
   travel through a queue.Queue on the server, which is single-consumer -- a
   second connection to the same job does not mirror the stream, it STEALS
   half of it, including (unpredictably) the terminal "done" event, so the
   panel hangs forever. This has been written as a bug twice already, once in
   NovelForge's audiobook panel and once in MediaForge's storage scan. If a
   panel needs log text AND progress AND a status line, they are all
   callbacks on this one call.

   A backend that numbers its events instead can serve any number of
   viewers, each getting every event, and a reconnect resumes where it left
   off. NovelForge's web_app.py does this (Job.snapshot, events_after and
   job_events, with the SSE id field and Last-Event-ID); copy that pattern
   when several panels or windows need to follow one job. */
function forgeStream(jobId, { onLog, onStream, onProgress, onDone, onError } = {}) {
  const es = new EventSource(`/api/jobs/${jobId}/events`);

  es.onmessage = (ev) => {
    const e = JSON.parse(ev.data);
    if (e.type === "log") onLog && onLog(e.text, e);
    else if (e.type === "stream") onStream && onStream(e.text, e);
    else if (e.type === "progress") onProgress && onProgress(e);
    else if (e.type === "done") { es.close(); onDone && onDone(); }
    else if (e.type === "error") { es.close(); onError && onError(e.error || "unknown error"); }
  };

  // EventSource reconnects on its own, which is right for a transient drop but
  // wrong for a job that has already ended -- that would spin forever with the
  // panel's buttons stuck disabled. Ask the server what actually happened and
  // settle the UI from the job's real status.
  es.onerror = async () => {
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      if (res.status === 404) {                    // lost when the backend restarted
        es.close();
        onError && onError(JOB_GONE);
        return;
      }
      const j = await res.json();
      if (j.status === "running") return;          // genuinely transient; let it retry
      es.close();
      if (j.status === "error") onError && onError(j.error || "connection lost");
      else onDone && onDone();
    } catch (e) {
      /* server unreachable -- keep retrying */
    }
  };

  return es;
}

/* A buffered writer for a scrolling log box. Returns write(text), with
   write.flush() to push out what is waiting right away.

   Writing `box.textContent += text` per message rebuilds the whole text and
   makes the browser lay out the entire box each time, and reading
   scrollHeight straight after forces that layout at once. This writer
   instead gathers text and adds it once per animation frame as a new text
   node, so a burst of messages costs one layout. Browsers hold animation
   frames while the page is hidden, so a hidden panel does no layout at all.

   It follows the bottom until the user scrolls up, so reading older lines
   is not undone by the next one, and follows again once they scroll back
   down. That is read from the box's scroll events, not measured at each
   write: a box on a hidden tab has no size, and a measurement taken there
   would stop it following for good once the tab is shown. Text past maxChars
   is dropped from the top. A newer writer on the same box takes over: an
   older one's waiting text is dropped, so a stale frame cannot write into a
   box that was cleared for a new job. Clearing the box (the x button sets
   textContent to "") is noticed and the running count starts again. */
function forgeBoxWriter(box, { maxChars = 50000 } = {}) {
  let pending = "";
  let scheduled = false;
  let total = 0;
  let last = null;
  const token = {};
  if (box) {
    box._forgeWriter = token;
    const atBottom = () => box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    box._forgeFollow = !box.clientHeight || atBottom();
    if (!box._forgeFollowWatch && box.addEventListener) {
      box._forgeFollowWatch = true;
      box.addEventListener("scroll", () => {
        if (box.clientHeight) box._forgeFollow = atBottom();
      }, { passive: true });
    }
  }

  const flush = () => {
    scheduled = false;
    if (!box || !pending || box._forgeWriter !== token) { pending = ""; return; }
    // Someone else changed the box (cleared it, or set new text): recount.
    if (!last || last.parentNode !== box || box.lastChild !== last) {
      total = box.textContent.length;
    }
    const text = pending.length > maxChars ? pending.slice(-maxChars) : pending;
    pending = "";
    last = document.createTextNode(text);
    box.appendChild(last);
    total += text.length;
    while (total > maxChars && box.childNodes.length > 1) {
      total -= box.firstChild.textContent.length;
      box.removeChild(box.firstChild);
    }
    if (box._forgeFollow) box.scrollTop = box.scrollHeight;
  };

  const write = (text) => {
    if (!box || !text) return;
    pending += text;
    // Frames are held while the page is hidden; keep only what could show.
    if (pending.length > 2 * maxChars) pending = pending.slice(-maxChars);
    if (!scheduled) { scheduled = true; requestAnimationFrame(flush); }
  };
  write.flush = flush;
  return write;
}

/* Append log/stream text into a scrolling box. The common case for a panel
   that just wants to watch a job run. Waiting text is pushed out before
   onDone or onError runs, so a caller reading the box then sees all of it. */
function forgeStreamInto(jobId, box, opts = {}) {
  const write = forgeBoxWriter(box);
  return forgeStream(jobId, Object.assign({}, opts, {
    onLog: (t, e) => { write(t + "\n"); opts.onLog && opts.onLog(t, e); },
    onStream: (t, e) => { write(t); opts.onStream && opts.onStream(t, e); },
    onDone: (...a) => { write.flush(); opts.onDone && opts.onDone(...a); },
    onError: (...a) => { write.flush(); opts.onError && opts.onError(...a); },
  }));
}

/* Poll a job to completion. For panels that need the job's RESULT rather than
   its log stream. Reports failures instead of charging ahead into a result
   fetch that 400s and then throws on undefined fields.

   It rests while the page cannot be seen (another app in front inside Forge,
   or a hidden window) and asks again as soon as it can; a failed request
   slows it down (up to 8 x `every`) instead of hammering a busy backend; and
   a job the backend no longer knows (a 404, after a restart) ends it with an
   error instead of polling forever. Returns { stop() }. */
const JOB_GONE = "This job is no longer known to the app; it may have restarted while the job ran.";

function pollJob(jobId, { onDone, onError, every = 700 } = {}) {
  let timer = 0, stopped = false, busy = false, wait = every;
  const shown = () => (window.ForgeIdle
    ? window.ForgeIdle.shown()
    : !document.hidden && (!window.ForgeVisible || window.ForgeVisible.on !== false));
  const stop = () => {
    stopped = true;
    clearTimeout(timer);
    timer = 0;
    document.removeEventListener("visibilitychange", wake);
    document.removeEventListener("forge-visible", wake);
  };
  const schedule = () => {
    if (!stopped && !timer && !busy && shown()) timer = setTimeout(tick, wait);
  };
  async function tick() {
    timer = 0;
    if (stopped || busy) return;
    if (!shown()) return;                          // wake() starts it again
    busy = true;
    let j = null;
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      if (res.status === 404) {
        busy = false;
        stop();
        onError && onError(JOB_GONE);
        return;
      }
      if (res.ok) j = await res.json();
    } catch (e) {
      j = null;                                    // transient; try again later
    }
    busy = false;
    if (stopped) return;
    if (!j || j.status === "running") {
      wait = j ? every : Math.min(every * 8, wait * 2);
      schedule();
      return;
    }
    stop();
    if (j.status === "error") onError && onError(j.error || "unknown error");
    else onDone && onDone(j);
  }
  function wake() {
    if (stopped || !shown() || busy) return;
    clearTimeout(timer);
    timer = 0;
    tick();
  }
  document.addEventListener("visibilitychange", wake);
  document.addEventListener("forge-visible", wake);
  schedule();
  return { stop };
}

/* --------------------------------------------------------------------------
   Sliders paired with number boxes
   --------------------------------------------------------------------------
   Every numeric setting is a slider with a number box beside it. Opt in:

       ForgeSliders.pair(rangeInput)      add a number box after a slider
       ForgeSliders.pairNumber(numInput)  add a slider before a number box
       ForgeSliders.watch(root)           pair every slider under root, now
                                          and whenever more are drawn

   A slider that already has a number box right after it, or carries
   data-no-pair, is left alone. Each side drives the other by setting its
   value and firing the other's own input/change events, so the handlers an
   app already has keep working; a value set from code (slider.value = 3)
   shows in the box too. A readout span right after the slider (span.val) is
   hidden, since the box says the same. Moved here from PanelForge's
   PF.pairSliders (2026-10-20). */
window.ForgeSliders = window.ForgeSliders || (function () {
  const valueProp = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  const nameOf = (input) => {
    const own = input.getAttribute("aria-label") || input.title;
    if (own) return own;
    const host = input.closest(".slider-row, .field, label");
    const words = host ? host.textContent.trim().split(/\s+/).slice(0, 4).join(" ") : "";
    return words || "value";
  };
  const copyLimits = (from, to) => ["min", "max", "step"].forEach((a) => {
    if (from.hasAttribute(a)) to.setAttribute(a, from.getAttribute(a));
  });
  // `source` drives `mirror`: values set on source (by code or by hand) show
  // in mirror, and typing in mirror sets source and fires source's events.
  function link(source, mirror) {
    const show = () => {
      if (document.activeElement !== mirror) valueProp.set.call(mirror, valueProp.get.call(source));
    };
    Object.defineProperty(source, "value", {
      configurable: true,
      get() { return valueProp.get.call(this); },
      set(v) { valueProp.set.call(this, v); show(); },
    });
    source.addEventListener("input", show);
    source.addEventListener("change", show);
    const push = (type) => {
      const v = parseFloat(valueProp.get.call(mirror));
      if (!Number.isFinite(v)) return;             // half-typed ("-", "") waits for more
      valueProp.set.call(source, String(v));
      source.dispatchEvent(new Event(type, { bubbles: true }));
    };
    // the mirror's own events stop here, so handlers on a whole card only
    // ever see the source's
    mirror.addEventListener("input", (e) => { e.stopPropagation(); push("input"); });
    mirror.addEventListener("change", (e) => {
      e.stopPropagation();
      push("change");
      valueProp.set.call(mirror, valueProp.get.call(source));  // clamped and stepped
    });
  }
  function pair(range) {
    if (!range || range.dataset.forgePaired || range.hasAttribute("data-no-pair")) return null;
    range.dataset.forgePaired = "1";
    const next = range.nextElementSibling;
    if (next && next.matches('input[type="number"]')) return null;
    const num = document.createElement("input");
    num.type = "number";
    num.className = "forge-pair-num";
    copyLimits(range, num);
    num.value = range.value;
    num.setAttribute("aria-label", nameOf(range));
    const wrap = document.createElement("span");
    wrap.className = "forge-pair";
    range.before(wrap);
    wrap.append(range);
    if (next && next.matches("span.val")) {
      next.classList.add("forge-pair-hidden");
      wrap.append(next);
    }
    wrap.append(num);
    link(range, num);
    return num;
  }
  function pairNumber(num) {
    if (!num || num.dataset.forgePaired || num.hasAttribute("data-no-pair")) return null;
    num.dataset.forgePaired = "1";
    const prev = num.previousElementSibling;
    if (prev && prev.matches('input[type="range"]')) return null;
    const range = document.createElement("input");
    range.type = "range";
    range.className = "forge-pair-range";
    copyLimits(num, range);
    range.value = num.value;
    range.setAttribute("aria-label", nameOf(num));
    range.dataset.forgePaired = "1";
    num.before(range);
    link(num, range);
    return range;
  }
  function scan(node) {
    if (!(node instanceof Element)) return;
    if (node.matches('input[type="range"]')) pair(node);
    else node.querySelectorAll('input[type="range"]').forEach(pair);
  }
  function watch(root) {
    // watch(document) works too: a Document is not an Element, so use its root
    const top = root && root.nodeType === Node.DOCUMENT_NODE ? root.documentElement : root || document.documentElement;
    scan(top);
    const seen = new MutationObserver((records) => records.forEach((r) => r.addedNodes.forEach(scan)));
    seen.observe(top, { childList: true, subtree: true });
    return { stop: () => seen.disconnect() };
  }
  return { pair, pairNumber, watch };
})();

/* --------------------------------------------------------------------------
   Simple / Advanced mode
   --------------------------------------------------------------------------
   Everything marked class="adv" is hidden in Simple mode (the rule lives in
   forge.css). The choice persists to the app's own settings endpoint as
   advanced_mode, which both apps already had in config.py.

   Usage, once the app knows its stored setting:
       ForgeMode.init(settings.advanced_mode);
   and include `advanced_mode: ForgeMode.saved` in any settings save so a later
   save does not reset it. */
const ForgeMode = {
  on: false,
  stored: false, // the app's own saved choice (advanced_mode)
  hubMode: null, // Settings > Apps > Apps open in: simple, advanced or remember
  touched: false, // switched by hand on this page: the hub no longer decides
  started: false,
  // what a settings save should store: a click's choice, else the saved one
  // (the hub opening it in Simple is not a choice to keep)
  get saved() {
    return this.touched ? this.on : this.stored;
  },

  // What the page opens in: Simple unless Settings says Advanced or "the one
  // I used last in that app". The app's
  // saved choice is only overwritten by a click on its switch.
  pick() {
    if (this.hubMode === "simple") return false;
    if (this.hubMode === "advanced") return true;
    return this.stored;
  },

  apply(state) {
    this.on = !!state;
    document.body.classList.toggle("advanced", this.on);
    const s = document.getElementById("modeSimple");
    const a = document.getElementById("modeAdvanced");
    if (s) s.classList.toggle("on", !this.on);
    if (a) a.classList.toggle("on", this.on);
    // the hub's app frame shows the same switch (shared/forge_chrome.js)
    if (this.started && window.ForgeChrome && window.ForgeChrome.modeNow) window.ForgeChrome.modeNow();
  },

  async set(state) {
    this.touched = true;
    if (!!state === this.on) return;
    this.apply(state);
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values: { advanced_mode: this.on } }),
    });
  },

  // shared/forge_chrome.js passes the hub's app_mode on every theme
  fromHub(mode) {
    this.hubMode = typeof mode === "string" ? mode : null;
    if (this.started && !this.touched) this.apply(this.pick());
  },

  init(state) {
    this.stored = !!state;
    if (this.hubMode === null && typeof window.__forgeAppMode === "string") this.hubMode = window.__forgeAppMode;
    this.started = true;
    this.apply(this.touched ? this.on : this.pick());
    const s = document.getElementById("modeSimple");
    const a = document.getElementById("modeAdvanced");
    if (s) s.addEventListener("click", () => this.set(false));
    if (a) a.addEventListener("click", () => this.set(true));
  },
};
// on window too: a top-level const is not, and forge_chrome.js looks for it there
window.ForgeMode = ForgeMode;

/* --------------------------------------------------------------------------
   Clear ("x") buttons
   --------------------------------------------------------------------------
   Every element marked data-clearable gets a small x in its corner that
   empties it. Call once at startup; safe to call again after adding boxes. */
function initClearButtons() {
  document.querySelectorAll("[data-clearable]").forEach(box => {
    if (box.dataset.clearInit) return;
    box.dataset.clearInit = "1";
    const wrap = document.createElement("div");
    wrap.className = "clearable-wrap";
    box.parentNode.insertBefore(wrap, box);
    wrap.appendChild(box);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "clear-x";
    btn.textContent = "×";
    btn.title = "Clear";
    btn.setAttribute("aria-label", "Clear this panel");
    btn.addEventListener("click", () => { box.textContent = ""; });
    wrap.appendChild(btn);
  });
}

/* --------------------------------------------------------------------------
   Thumbnails
   --------------------------------------------------------------------------
   Rendering one costs an ffmpeg spawn on the server for video, so these are
   loading="lazy": only rows the user actually scrolls to are ever rendered,
   and the server caches each result on disk. Requires the app's backend to
   expose GET /api/thumbnail?path=&w= (MediaForge does). */
function fileThumb(path, w = 96) {
  const img = document.createElement("img");
  img.className = "file-thumb blank";
  img.loading = "lazy";
  img.decoding = "async";
  img.alt = "";
  img.src = `/api/thumbnail?path=${encodeURIComponent(path)}&w=${w}`;
  img.dataset.zoomSrc = `/api/thumbnail?path=${encodeURIComponent(path)}&w=480`;
  img.addEventListener("load", () => img.classList.remove("blank"));
  // Formats ffmpeg/Pillow can't open, or a file that vanished, keep the
  // hatched placeholder rather than showing a broken-image icon.
  img.addEventListener("error", () => { img.removeAttribute("src"); });
  return img;
}

/* --------------------------------------------------------------------------
   Tabs
   --------------------------------------------------------------------------
   Both apps use the same nav .tab / .panel[data-panel] markup. onSelect fires
   with the tab name, which is where panels do their lazy loading. */
function initTabs(onSelect) {
  const select = (name) => {
    document.querySelectorAll("nav .tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
    document.querySelectorAll(".panel").forEach(p => p.classList.toggle("active", p.dataset.panel === name));
    onSelect && onSelect(name);
  };
  document.querySelectorAll("nav .tab").forEach(t => {
    t.addEventListener("click", () => select(t.dataset.tab));
  });
  return select;
}

/* --------------------------------------------------------------------------
   Fullscreen inside the hub

   Moved out to shared/forge_chrome.js, which every app loads on its own line:

       <script src="/shared/forge_chrome.js"></script>

   It lives in its own file because the apps that most want a full-screen
   button (AI Studio, PixelForge) do not load this one -- they have their own
   DOM helpers and the `val`/`toast`/`checked` globals here would collide with
   them. It also used to be a top-level `const` in this file, which meant it
   was never on `window` and every `if (window.ForgeChrome)` guard silently
   skipped wiring the button.
   -------------------------------------------------------------------------- */
