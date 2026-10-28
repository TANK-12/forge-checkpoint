/* Forge idle helpers: keep pages from working while nobody can see them.

   A page is "shown" when the browser says it is visible and, inside the Forge
   hub, the hub has not told it (ForgeVisible in forge_chrome.js) that another
   app or the home screen is in front. Apps include this file instead of
   writing their own visibility checks.

     ForgeIdle.shown()                       true when the page can be seen
     ForgeIdle.poll(fn, ms, opts)            repeating job; returns { stop, now }
         opts.hiddenMs   0 (default) pauses completely while hidden; a number
                         keeps a slow tick (for example a heartbeat)
         opts.backoff    1 (default); above 1, every run where fn returns
                         exactly false stretches the wait by that factor up to
                         opts.maxMs (default 8 x ms); any other result resets
         opts.immediate  run once at once (default false)
       Runs never overlap (an async fn is awaited, for at most max(4 x ms,
       30 s) so a hung request cannot stop the poll), and coming back into
       view runs fn straight away if it has been waiting longer than ms,
       otherwise on its old beat.
     ForgeIdle.loop(frameFn)                 requestAnimationFrame loop that
         stops while hidden and carries on when shown; returns { stop }.
         frameFn(t) may return false to end the loop.

   Pages that hide also get class "forge-idle" on <html>, which pauses CSS
   animations (inside the hub, forge_chrome.js does the same with
   "forge-resting"). */
(function () {
  if (window.ForgeIdle) return;
  const listeners = new Set();

  function shown() {
    return !document.hidden && (!window.ForgeVisible || window.ForgeVisible.on !== false);
  }
  function changed() {
    document.documentElement.classList.toggle("forge-idle", !shown());
    listeners.forEach((fn) => { try { fn(shown()); } catch (e) { /* keep going */ } });
  }
  document.addEventListener("visibilitychange", changed);
  document.addEventListener("forge-visible", changed);

  const style = document.createElement("style");
  style.textContent = "html.forge-idle *, html.forge-idle *::before, html.forge-idle *::after { animation-play-state: paused !important; }";
  (document.head || document.documentElement).appendChild(style);

  function poll(fn, ms, opts) {
    const o = opts || {};
    const hiddenMs = Number(o.hiddenMs) || 0;
    const factor = Number(o.backoff) > 1 ? Number(o.backoff) : 1;
    const maxMs = Number(o.maxMs) || ms * 8;
    let wait = ms, timer = 0, stopped = false, running = false, lastRun = 0;

    async function run() {
      timer = 0;
      if (stopped || running) return;
      running = true;
      let result, guard = 0;
      // a job whose promise never settles (a backend that hangs without
      // closing) must not end the poll for good: give up waiting after a while
      const stuck = new Promise((done) => { guard = setTimeout(done, Math.max(4 * ms, 30000)); });
      try { result = await Promise.race([fn(), stuck]); } catch (e) { /* the job reports its own errors */ }
      clearTimeout(guard);
      running = false;
      lastRun = Date.now();
      wait = factor > 1 && result === false ? Math.min(maxMs, wait * factor) : ms;
      schedule();
    }
    function schedule() {
      if (stopped || timer || running) return;
      if (shown()) timer = setTimeout(run, wait);
      else if (hiddenMs > 0) timer = setTimeout(run, hiddenMs);
    }
    function onChange(isShown) {
      if (stopped) return;
      if (!isShown) {
        if (timer) { clearTimeout(timer); timer = 0; }
        schedule();
        return;
      }
      if (timer) { clearTimeout(timer); timer = 0; }
      if (running) return; // the run in flight schedules the next one
      wait = ms;
      // overdue: run now; otherwise keep the old beat, so a brief hide neither
      // adds a run nor pushes the next one back
      const since = Date.now() - lastRun;
      if (since >= ms) run(); else timer = setTimeout(run, ms - since);
    }
    listeners.add(onChange);
    if (o.immediate) run(); else schedule();
    return {
      now() { if (timer) { clearTimeout(timer); timer = 0; } run(); },
      stop() { stopped = true; if (timer) clearTimeout(timer); timer = 0; listeners.delete(onChange); },
    };
  }

  function loop(frameFn) {
    let id = 0, stopped = false;
    function frame(t) {
      id = 0;
      if (stopped) return;
      let go = true;
      try { go = frameFn(t) !== false; } catch (e) { setTimeout(() => { throw e; }); } // report, keep looping
      if (!go) { stopped = true; listeners.delete(onChange); return; }
      if (shown()) id = requestAnimationFrame(frame);
    }
    function onChange(isShown) {
      if (stopped) return;
      if (isShown && !id) id = requestAnimationFrame(frame);
      else if (!isShown && id) { cancelAnimationFrame(id); id = 0; }
    }
    listeners.add(onChange);
    if (shown()) id = requestAnimationFrame(frame);
    return { stop() { stopped = true; if (id) cancelAnimationFrame(id); id = 0; listeners.delete(onChange); } };
  }

  window.ForgeIdle = { shown, poll, loop };
  changed();
})();
