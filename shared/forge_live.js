/* ForgeLive: live wallpapers and companions for the Forge hub.
 *
 * A plain script (no modules). Scenes live in <base>live/<id>.js and call
 * ForgeLive.scene(id, def); companions live in <base>companions/<id>.js and
 * call ForgeLive.companion(id, def). Both load on demand with a <script> tag.
 *
 *   ForgeLive.apply({live, companion, accent, surfaces, mode, animations,
 *                    lite, max_fps, home, bottom})  -> Promise (resolves once drawn)
 *   ForgeLive.setHome(bool)        false pauses the scene (last frame stays)
 *   ForgeLive.setPaused(bool)      true holds the scene and the companion
 *                                  (the window lost focus); false goes on
 *   ForgeLive.still(id, t, opts)   draw scene id once at time t -> Promise
 *
 * Scene def: {fps, res, start(ctx,w,h,opts), frame(ctx,t,dt,w,h),
 *             resize?(ctx,w,h), update?(opts), stop?()}
 * Companion def: {layer?, start(layer, opts) -> {stop(), update?(opts), still?(bool)}}
 *   layer "back" draws it just over the wallpaper, behind the home tiles,
 *   apps, dock and bar (butterflies, birds, fish: scenery); anything else
 *   draws it over everything, apps included (the pets that walk across).
 *
 * Performance tier (shared/forge_perf.js, Relay task 379): apply() also takes
 * tier ("full" | "balanced" | "light"), tier_live / tier_companion (the
 * theme's own fallback, or null) and tier_live_default /
 * tier_companion_default (shared/perf/tiers.json). Each scene and companion
 * declares its own in its def: lighter: {balanced: ..., light: ...}; a
 * scene's rule is "" (as is), "still" (one frame), "off" (not drawn: the
 * theme's still picture shows) or {fps, res} factors, a companion's "",
 * "still" or "off". The theme's word wins, then the item's, then the tier's.
 *
 * Scenes should draw as a pure function of t (randomness from ForgeLive.util.rng
 * with a fixed seed) so stills are repeatable and a pause/resume is seamless.
 */
(function () {
  "use strict";
  var FL = (window.ForgeLive = window.ForgeLive || {});
  if (FL._ready) return;
  FL._ready = true;
  if (typeof FL.base !== "string") FL.base = "../shared/";

  var ID = /^[a-z0-9-]+$/;
  var STILL_T = 12; // the time drawn when animations are off (matches the stills)
  var MAX_PIXELS = 2.2e6;
  var registry = { live: {}, companions: {} };
  var loading = {};

  /* ---------- small helpers shared with scene files ---------- */
  function rng(seed) {
    var a = seed >>> 0 || 1;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function hex(h, fallback) {
    var m = /^#?([0-9a-f]{6})$/i.exec(String(h || "").trim());
    if (!m) {
      m = /^#?([0-9a-f]{3})$/i.exec(String(h || "").trim());
      if (m) {
        var s = m[1];
        m = [0, s[0] + s[0] + s[1] + s[1] + s[2] + s[2]];
      }
    }
    if (!m) return fallback ? hex(fallback) : [128, 128, 128];
    var n = parseInt(m[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function rgba(c, a) {
    if (typeof c === "string") c = hex(c);
    return (
      "rgba(" +
      Math.round(c[0]) + "," + Math.round(c[1]) + "," + Math.round(c[2]) + "," +
      (a === undefined ? 1 : +a.toFixed(4)) + ")"
    );
  }
  function mix(a, b, t) {
    if (typeof a === "string") a = hex(a);
    if (typeof b === "string") b = hex(b);
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
  }
  function lum(c) {
    if (typeof c === "string") c = hex(c);
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255;
  }
  function layer(w, h) {
    var c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(w));
    c.height = Math.max(1, Math.round(h));
    return c;
  }
  FL.util = { rng: rng, hex: hex, rgba: rgba, mix: mix, lum: lum, layer: layer };

  /* ---------- registry and loading ---------- */
  FL.scene = function (id, def) {
    if (ID.test(id) && def) registry.live[id] = def;
  };
  FL.companion = function (id, def) {
    if (ID.test(id) && def) registry.companions[id] = def;
  };
  function load(kind, id) {
    if (!id || !ID.test(id)) return Promise.resolve(null);
    if (registry[kind][id]) return Promise.resolve(registry[kind][id]);
    var key = kind + "/" + id;
    if (!loading[key]) {
      loading[key] = new Promise(function (resolve) {
        var s = document.createElement("script");
        s.src = FL.base + key + ".js";
        s.async = true;
        s.onload = function () {
          resolve(registry[kind][id] || null);
        };
        s.onerror = function () {
          delete loading[key];
          console.warn("ForgeLive: could not load " + key);
          resolve(null);
        };
        (document.head || document.documentElement).appendChild(s);
      });
    }
    return loading[key];
  }

  /* ---------- DOM ---------- */
  function canvasEl() {
    var c = document.getElementById("live-wall");
    if (!c) {
      c = document.createElement("canvas");
      c.id = "live-wall";
      c.setAttribute("aria-hidden", "true");
      c.style.cssText =
        "position:fixed;inset:0;width:100%;height:100%;z-index:0;pointer-events:none;display:block";
      c.hidden = true;
      document.body.insertBefore(c, document.body.firstChild);
    }
    return c;
  }
  function layerEl() {
    var l = document.getElementById("companion-layer");
    if (!l) {
      l = document.createElement("div");
      l.id = "companion-layer";
      l.setAttribute("aria-hidden", "true");
      l.style.cssText =
        "position:fixed;inset:0;pointer-events:none;z-index:90;overflow:hidden";
      l.dataset.frontZ = "90";
      document.body.appendChild(l);
    }
    return l;
  }
  // the layer, raised over everything or lowered behind it as the companion
  // asks (def.layer, Relay task 388); the hub's own CSS keeps the front height
  var BACK_Z = "2"; // over #live-wall (0) and #particles (1), under #home (5)
  function layerFor(def) {
    var l = layerEl();
    if (l.dataset.frontZ === undefined) l.dataset.frontZ = l.style.zIndex || "";
    var back = !!def && def.layer === "back";
    l.dataset.layer = back ? "back" : "front";
    l.style.zIndex = back ? BACK_Z : l.dataset.frontZ || "";
    return l;
  }

  /* ---------- options ---------- */
  var DEFAULTS = {
    live: "",
    companion: "",
    accent: "#6ea8fe",
    surfaces: {},
    mode: "dark",
    animations: true,
    lite: false,
    max_fps: 60,
    home: true,
    bottom: 0,
    tier: "full",
    tier_live: null,
    tier_live_default: "",
    tier_companion: null,
    tier_companion_default: "",
  };
  var TIERS = ["full", "balanced", "light"];
  var opts = norm({});
  function norm(o) {
    var out = {};
    for (var k in DEFAULTS) out[k] = o[k] === undefined ? DEFAULTS[k] : o[k];
    out.accent = "#" + hex(out.accent, DEFAULTS.accent).map(function (v) {
      return ("0" + v.toString(16)).slice(-2);
    }).join("");
    out.surfaces = out.surfaces && typeof out.surfaces === "object" ? out.surfaces : {};
    out.mode = out.mode === "light" ? "light" : "dark";
    out.animations = out.animations !== false;
    out.lite = !!out.lite;
    out.home = out.home !== false;
    out.max_fps = Math.max(1, +out.max_fps || 60);
    out.bottom = Math.max(0, +out.bottom || 0);
    out.live = typeof out.live === "string" ? out.live : "";
    out.companion = typeof out.companion === "string" ? out.companion : "";
    if (o.t !== undefined && isFinite(+o.t)) out.t = +o.t; // fixed still time
    if (o.res !== undefined && +o.res > 0) out.res = Math.min(1, +o.res); // render scale override
    if (o.pose) out.pose = String(o.pose); // companion pose for previews
    if (TIERS.indexOf(out.tier) < 0) out.tier = "full";
    return out;
  }
  function colourKey(o) {
    return JSON.stringify([o.accent, o.surfaces, o.mode]);
  }

  /* ---------- the tier's rule for a scene or companion ---------- */
  function rule(own, override, fallback) {
    if (opts.tier === "full") return "";
    if (override !== null && override !== undefined) return override;
    var mine = own && typeof own === "object" ? own[opts.tier] : undefined;
    if (mine !== null && mine !== undefined) return mine;
    return fallback || "";
  }
  function liveRule(def) {
    return rule(def && def.lighter, opts.tier_live, opts.tier_live_default);
  }
  function compRule(def) {
    return rule(def && def.lighter, opts.tier_companion, opts.tier_companion_default);
  }
  function factor(r, k) {
    return r && typeof r === "object" && +r[k] > 0 ? Math.min(1, +r[k]) : 1;
  }

  /* ---------- scene runner ---------- */
  var cur = null; // {id, def, ctx, w, h, t, last, raf, broken, rule}
  var home = true;
  var paused = false;

  function guard(fn) {
    if (!cur || cur.broken) return false;
    try {
      fn();
      return true;
    } catch (e) {
      console.warn("ForgeLive: scene " + cur.id + " stopped after an error", e);
      cur.broken = true;
      stopScene();
      return false;
    }
  }
  function size() {
    var c = cur.canvas;
    var w = Math.max(1, window.innerWidth || c.clientWidth || 1);
    var h = Math.max(1, window.innerHeight || c.clientHeight || 1);
    var res = opts.res || cur.def.res || 0.75;
    if (opts.lite) res *= 0.7;
    res *= factor(cur.rule, "res");
    var scale = res * (window.devicePixelRatio || 1);
    if (w * h * scale * scale > MAX_PIXELS) scale = Math.sqrt(MAX_PIXELS / (w * h));
    c.width = Math.max(1, Math.round(w * scale));
    c.height = Math.max(1, Math.round(h * scale));
    cur.ctx.setTransform(c.width / w, 0, 0, c.height / h, 0, 0);
    cur.w = w;
    cur.h = h;
  }
  function fps() {
    var f = Math.min(cur.def.fps || 30, opts.max_fps);
    if (opts.lite) f /= 2;
    f *= factor(cur.rule, "fps");
    return Math.max(1, f);
  }
  function moving() {
    return (
      cur && !cur.broken && opts.animations && opts.t === undefined && home &&
      !document.hidden && !paused && cur.rule !== "still"
    );
  }
  function drawOnce() {
    if (!cur) return;
    var t = opts.t !== undefined ? opts.t : opts.animations && cur.rule !== "still" ? cur.t : STILL_T;
    guard(function () {
      cur.def.frame(cur.ctx, t, 0, cur.w, cur.h);
    });
  }
  function tick(now) {
    if (!cur) return;
    cur.raf = 0;
    if (!moving()) return;
    cur.raf = requestAnimationFrame(tick);
    var step = 1000 / fps();
    if (cur.last && now - cur.last < step - 2) return;
    var dt = cur.last ? Math.min((now - cur.last) / 1000, 0.1) : 0;
    cur.last = now;
    cur.t += dt;
    guard(function () {
      cur.def.frame(cur.ctx, cur.t, dt, cur.w, cur.h);
    });
  }
  function schedule() {
    if (!cur) return;
    if (moving()) {
      if (!cur.raf) {
        cur.last = 0;
        cur.raf = requestAnimationFrame(tick);
      }
    } else if (cur.raf) {
      cancelAnimationFrame(cur.raf);
      cur.raf = 0;
    }
  }
  function startScene(id, def) {
    var c = canvasEl();
    cur = { id: id, def: def, canvas: c, ctx: c.getContext("2d"), t: 0, last: 0, raf: 0, rule: liveRule(def) };
    cur.key = colourKey(opts);
    cur.res = opts.res;
    cur.lite = opts.lite;
    size();
    c.hidden = false;
    var ok = guard(function () {
      def.start(cur.ctx, cur.w, cur.h, opts);
    });
    if (!ok) return;
    drawOnce();
    schedule();
  }
  function stopScene() {
    if (!cur) return;
    var old = cur;
    cur = null;
    if (old.raf) cancelAnimationFrame(old.raf);
    try {
      if (old.def.stop) old.def.stop();
    } catch (e) {
      /* a scene failing to stop must not break the caller */
    }
    old.canvas.hidden = true;
    old.ctx.setTransform(1, 0, 0, 1, 0, 0);
    old.ctx.clearRect(0, 0, old.canvas.width, old.canvas.height);
  }
  function restartScene() {
    if (!cur) return;
    var id = cur.id, def = cur.def, t = cur.t;
    stopScene();
    startScene(id, def);
    if (cur) cur.t = t;
  }

  /* ---------- companion runner ---------- */
  var pal = null; // {id, inst}
  function compOpts() {
    return {
      animations: opts.animations && opts.t === undefined && (!pal || pal.rule !== "still"),
      lite: opts.lite,
      bottom: opts.bottom,
      accent: opts.accent,
      mode: opts.mode,
      surfaces: opts.surfaces,
      pose: opts.pose,
      max_fps: opts.max_fps, // the frame cap (Settings, battery, tier)
    };
  }
  function stopComp() {
    if (!pal) return;
    try {
      pal.inst && pal.inst.stop && pal.inst.stop();
    } catch (e) {
      console.warn("ForgeLive: companion " + pal.id + " failed to stop", e);
    }
    pal = null;
  }
  function startComp(id, def) {
    var r = compRule(def);
    if (r === "off") return;
    try {
      pal = { id: id, rule: r, inst: null };
      pal.inst = def.start(layerFor(def), compOpts()) || null;
      if (paused && pal.inst && pal.inst.still) pal.inst.still(true);
    } catch (e) {
      console.warn("ForgeLive: companion " + id + " stopped after an error", e);
      pal = null;
    }
  }

  /* ---------- public API ---------- */
  var token = 0;
  FL.apply = function (o) {
    var prev = opts;
    opts = norm(o || {});
    home = opts.home;
    var my = ++token;
    var want = ID.test(opts.live) ? opts.live : "";
    var pet = ID.test(opts.companion) ? opts.companion : "";
    var jobs = [];

    var known = want ? registry.live[want] : null;
    if (!want || (known && liveRule(known) === "off") || opts.tier_live === "off") stopScene();
    else if (cur && cur.id === want && !cur.broken) {
      var key = colourKey(opts);
      var was = cur.rule;
      cur.rule = liveRule(cur.def);
      if (cur.res !== opts.res || cur.lite !== opts.lite || factor(was, "res") !== factor(cur.rule, "res")) restartScene();
      else if (key !== cur.key) {
        if (cur.def.update) {
          cur.key = key;
          guard(function () {
            cur.def.update(opts);
          });
        } else restartScene();
      }
      if (cur) {
        if (!moving()) drawOnce();
        schedule();
      }
    } else {
      stopScene();
      jobs.push(
        load("live", want).then(function (def) {
          if (my !== token || !def) return;
          stopScene();
          if (liveRule(def) !== "off") startScene(want, def);
        })
      );
    }

    var knownPet = pet ? registry.companions[pet] : null;
    if (!pet || opts.tier_companion === "off" || (knownPet && compRule(knownPet) === "off")) stopComp();
    else if (pal && pal.id === pet && pal.rule !== compRule(knownPet)) {
      stopComp();
      if (knownPet) startComp(pet, knownPet);
    } else if (pal && pal.id === pet) {
      if (pal.inst && pal.inst.update) {
        try {
          pal.inst.update(compOpts());
        } catch (e) {
          stopComp();
        }
      } else if (JSON.stringify(compOpts()) !== JSON.stringify(prevComp(prev))) {
        var d = registry.companions[pet];
        stopComp();
        if (d) startComp(pet, d);
      }
    } else {
      stopComp();
      jobs.push(
        load("companions", pet).then(function (def) {
          if (my !== token || !def) return;
          stopComp();
          startComp(pet, def);
        })
      );
    }
    return Promise.all(jobs).then(function () {});
  };
  function prevComp(p) {
    var keep = opts;
    opts = p;
    var c = compOpts();
    opts = keep;
    return c;
  }

  FL.setHome = function (on) {
    home = !!on;
    opts.home = home;
    schedule();
  };

  FL.setPaused = function (on) {
    on = !!on;
    if (on === paused) return;
    paused = on;
    schedule();
    if (pal && pal.inst && pal.inst.still) {
      try {
        // paused: hold still; back: as the companion's own settings say
        pal.inst.still(on || !compOpts().animations);
      } catch (e) {
        console.warn("ForgeLive: companion " + pal.id + " failed to pause", e);
      }
    }
  };

  FL.still = function (id, t, o) {
    var base = {};
    for (var k in opts) base[k] = opts[k];
    for (var k2 in o || {}) base[k2] = o[k2];
    base.live = id;
    base.t = +t || 0;
    base.animations = false;
    return FL.apply(base);
  };

  /* Read-only view for debugging and tests. */
  FL.state = function () {
    return {
      live: cur ? cur.id : "",
      running: !!(cur && cur.raf),
      rule: cur ? cur.rule : "",
      tier: opts.tier,
      paused: paused,
      companion: pal ? pal.id : "",
      companionRule: pal ? pal.rule : "",
      scenes: Object.keys(registry.live),
      companions: Object.keys(registry.companions),
    };
  };

  document.addEventListener("visibilitychange", schedule);
  var resizeQueued = false;
  window.addEventListener("resize", function () {
    if (resizeQueued) return;
    resizeQueued = true;
    requestAnimationFrame(function () {
      resizeQueued = false;
      if (!cur) return;
      size();
      guard(function () {
        if (cur.def.resize) cur.def.resize(cur.ctx, cur.w, cur.h);
        else cur.def.start(cur.ctx, cur.w, cur.h, opts);
      });
      if (!moving()) drawOnce();
    });
  });
})();
