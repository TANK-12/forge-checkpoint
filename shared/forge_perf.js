/* ForgePerf: the performance tier (Relay task 379, the owner 2026-10-27: "run
   smoothly on low-end computers too, switching by itself to lighter looks").

   Three tiers, defined in shared/perf/tiers.json (carried in theme.js as
   perf_tiers): full, balanced, light. A tier never swaps the theme away; it
   lays plainer values over it (lighten), from four places, later ones
   winning:
     1. the tier itself            shared/perf/tiers.json  settings
     2. the theme's own fallback   shared/themes/<id>.json lighter.<tier>
     3. the layout's fallback      shared/layouts/<id>.json lighter.<tier>
     4. the glass and motion style the "lighter:" line of shared/glass/*.css
                                   and shared/motion/*.css
   The live wallpaper and companion each declare theirs in their own def
   (shared/live/*.js, shared/companions/*.js, `lighter: {balanced, light}`);
   ForgeLive resolves those with the tier's default (tiers.json live and
   companion) and the theme's own override (lighter.<tier>.live/companion).

   Settings > Speed and detail > Performance is "auto" (default) or a tier.
   Auto takes the lightest of:
     - the ceiling: what the machine and its state allow (detect): processor
       threads, memory, WebGL and software drawing, reduced motion asked by
       the desktop, battery saver (on battery at or under battery_saver %)
     - the frame watcher: a probe counts frames in one-second buckets while
       something moves on screen; BAD_RUN bad buckets in a row step one tier
       down, and UP_AFTER of visible time with no bad bucket steps one back
       up (never above the ceiling). A drop soon after stepping up doubles
       the wait, up to UP_MAX, so a machine at its edge does not flip-flop.

   Pure: no DOM. The hub feeds it the environment and frame times; node
   loads it in the tests (shared/forge_perf.test.js). */
(function (root) {
  const TIERS = ["full", "balanced", "light"];
  const MODES = ["auto"].concat(TIERS);
  // a bucket under this many frames a second (or 3/4 of what is wanted, the
  // screen's rate or the frame cap, when that is lower) is a bad one
  const BAD_FPS = 40;
  const BUCKET_MS = 1000;
  // a frame later than this after the one before: the page was hidden,
  // paused or the probe stopped, not a slow frame; the bucket is dropped
  const GAP_MS = 1000;
  const BAD_RUN = 3;
  const UP_AFTER = 20000;
  const UP_MAX = 600000;
  // stepping down this soon after stepping up doubles the wait
  const RELAPSE_MS = 60000;
  // nothing is judged for this long after a tier change (the restyle and a
  // restarted wallpaper cost a few frames); the hub also settles it once the
  // new wallpaper has drawn
  const SETTLE_MS = 3000;

  const index = (tier) => Math.max(0, TIERS.indexOf(tier));
  const lighter = (a, b) => TIERS[Math.max(index(a), index(b))];

  /** The ceiling for Auto from the machine and its state.
      env: {cores, memory (GB), gl: "hardware"|"software"|"none"|undefined,
            reducedMotion, powerSaver (the desktop's power saver mode),
      onBattery, battery (percent), saver (percent)}
      -> {tier, why}. The lightest rule wins; why names that rule. */
  function detect(env) {
    const e = env || {};
    const rules = [];
    const add = (tier, why) => rules.push({ tier, why });
    if (e.reducedMotion) add("light", "the desktop asks for reduced motion");
    if (e.powerSaver) add("light", "the desktop's power saver is on");
    const saver = Number(e.saver ?? 20);
    if (e.onBattery && saver > 0 && e.battery != null && Number(e.battery) <= saver)
      add("light", `battery saver: ${Math.round(Number(e.battery))}% left`);
    if (e.gl === "software") add("light", "no graphics acceleration (drawn in software)");
    const cores = Number(e.cores);
    if (cores > 0 && cores <= 2) add("light", `only ${cores} processor thread${cores === 1 ? "" : "s"}`);
    else if (cores > 0 && cores <= 4) add("balanced", `only ${cores} processor threads`);
    const mem = Number(e.memory);
    if (mem > 0 && mem <= 2) add("light", `only ${mem} GB of memory`);
    else if (mem > 0 && mem <= 4) add("balanced", `only ${mem} GB of memory`);
    if (e.gl === "none") add("balanced", "no WebGL");
    let best = { tier: "full", why: "this computer keeps up" };
    rules.forEach((r) => { if (index(r.tier) > index(best.tier)) best = r; });
    return best;
  }

  /** The frame watcher. Feed it every frame the page draws (frame(t), from
      ForgeFrameCap.watch: no extra frames of its own) while it should judge,
      and a tick now and then with whether that time counts (tick(t,
      active)); setCap(fps) is the frame cap in force. It answers with
      {tier, why} through state(). `ceiling` is detect()'s answer. */
  function watcher(ceiling) {
    let ceil = ceiling && TIERS.includes(ceiling.tier) ? ceiling : { tier: "full", why: "" };
    let drops = 0; // tiers stepped down by the watcher, under the ceiling
    let start = -1, frames = 0, last = -1, badRun = 0, lastFps = 0;
    let refresh = 60, cap = 60, settleUntil = -Infinity, goodMs = 0, tickAt = -1;
    let upWait = UP_AFTER, upAt = -Infinity, changes = 0, dropFps = 0;

    const tierNow = () => TIERS[Math.min(TIERS.length - 1, index(ceil.tier) + drops)];
    const room = () => index(ceil.tier) + drops < TIERS.length - 1;
    // the drops that count under the ceiling now (the rest wait for it to lift)
    const counted = () => Math.min(drops, TIERS.length - 1 - index(ceil.tier));
    function settle(t) {
      settleUntil = t + SETTLE_MS;
      start = -1;
      frames = 0;
      badRun = 0;
      goodMs = 0;
    }
    function down(t) {
      if (!room()) return;
      drops += 1;
      dropFps = lastFps;
      changes += 1;
      if (t - upAt < RELAPSE_MS) upWait = Math.min(UP_MAX, upWait * 2);
      settle(t);
    }
    function up(t) {
      if (!counted()) return;
      drops = counted() - 1;
      changes += 1;
      upAt = t;
      settle(t);
    }
    function bucket(t, fps) {
      if (fps > refresh && cap >= refresh) refresh = Math.min(250, fps);
      lastFps = fps;
      if (fps < Math.min(BAD_FPS, 0.75 * Math.min(cap, refresh))) {
        goodMs = 0;
        badRun += 1;
        if (badRun >= BAD_RUN) down(t);
      } else {
        badRun = 0;
      }
    }
    return {
      frame(t) {
        if (t < settleUntil) { last = t; return; }
        if (last >= 0 && t - last > GAP_MS) { start = -1; badRun = 0; } // a gap: start over
        last = t;
        if (start < 0) { start = t; frames = 0; return; }
        frames += 1;
        if (t - start >= BUCKET_MS) {
          const fps = (frames * 1000) / (t - start);
          start = t;
          frames = 0;
          bucket(t, fps);
        }
      },
      /** active: visible, in use and something to watch; only that time
          counts towards stepping back up. */
      tick(t, active) {
        const dt = tickAt >= 0 ? Math.max(0, Math.min(t - tickAt, 5000)) : 0;
        tickAt = t;
        if (!active || t < settleUntil) return;
        goodMs += dt;
        // under a lighter ceiling the drops past it wait: good frames there
        // say nothing about the tiers above
        if (counted() && goodMs >= upWait) up(t);
      },
      setCap(fps) {
        const n = Number(fps);
        const next = n >= 1 ? Math.min(250, n) : 60;
        if (next !== cap) { cap = next; start = -1; }
      },
      setCeiling(next) {
        if (!next || !TIERS.includes(next.tier)) return;
        if (next.tier === ceil.tier && next.why === ceil.why) return;
        const before = tierNow();
        ceil = next;
        if (tierNow() !== before) settle(tickAt >= 0 ? tickAt : 0);
      },
      /** A theme change or the page coming back: judge nothing for a moment. */
      settle(t) { settle(t); },
      state() {
        const tier = tierNow();
        const why = counted()
          ? `frames dropped to ${Math.round(dropFps)} a second`
          : ceil.why;
        return { tier, why, drops, changes, refresh, upWait, ceiling: ceil.tier };
      },
    };
  }

  /** What applies: the mode from Settings and Auto's own answer. */
  function choose(mode, auto) {
    if (TIERS.includes(mode)) return { tier: mode, why: "picked in Settings", auto: false };
    const a = auto && TIERS.includes(auto.tier) ? auto : { tier: "full", why: "" };
    return { tier: a.tier, why: a.why, auto: true };
  }

  // One setting rule from a tier or a fallback: a plain value replaces;
  // {"min": n} keeps the lower; {"scale": f} multiplies.
  function rule(now, r) {
    if (r && typeof r === "object" && !Array.isArray(r)) {
      if (typeof r.min === "number") return Math.min(Number(now ?? r.min), r.min);
      if (typeof r.scale === "number") return Math.round(Number(now ?? 1) * r.scale * 1000) / 1000;
      return now;
    }
    return r;
  }
  function overlay(t, settings) {
    if (!settings || typeof settings !== "object") return;
    Object.entries(settings).forEach(([k, r]) => { t[k] = rule(t[k], r); });
  }
  const pick = (map, tier) => (map && typeof map === "object" && map[tier]) || null;

  /** The theme the hub shows at `tier` (see the top of this file). The
      result carries perf_tier, perf_css (the tier's CSS switches),
      perf_live / perf_companion (the theme's own override or the tier's
      default, for ForgeLive) and never touches `theme` itself. */
  function lighten(theme, tier) {
    const base = theme || {};
    const t = Object.assign({}, base);
    const level = TIERS.includes(tier) ? tier : "full";
    t.perf_tier = level;
    const def = pick(base.perf_tiers, level) || {};
    t.perf_css = Array.isArray(def.css) ? def.css.slice() : [];
    t.perf_live_default = def.live ?? "";
    t.perf_companion_default = def.companion ?? "";
    if (level === "full") return t;
    overlay(t, def.settings);
    const own = pick(base.theme_lighter, level) || {};
    overlay(t, own.settings);
    const lay = pick(base.layout_lighter, level) || {};
    overlay(t, lay.settings);
    if (lay.home && typeof lay.home === "object") t.layout_home = Object.assign({}, base.layout_home || {}, lay.home);
    const glass = pick((base.glass_lighter || {})[t.glass_style], level);
    if (typeof glass === "string") t.glass_style = glass;
    const motion = pick((base.motion_lighter || {})[t.motion || "glide"], level);
    if (typeof motion === "string") t.motion = motion;
    if (typeof own.live === "string" || (own.live && typeof own.live === "object")) t.perf_live = own.live;
    if (typeof own.companion === "string") t.perf_companion = own.companion;
    return t;
  }

  /** A live wallpaper's or companion's rule at `tier`: the theme's override,
      else the item's own `lighter`, else the tier's default. "" leaves it as
      it is; scenes also take "still", "off" or {fps, res} factors,
      companions "still" or "off". */
  function itemRule(tier, override, own, fallback) {
    if (tier === "full") return "";
    if (override !== undefined && override !== null) return override;
    const mine = own && typeof own === "object" ? own[tier] : undefined;
    if (mine !== undefined && mine !== null) return mine;
    return fallback ?? "";
  }

  const api = {
    TIERS, MODES, BAD_FPS, BUCKET_MS, GAP_MS, BAD_RUN, UP_AFTER, UP_MAX, RELAPSE_MS, SETTLE_MS,
    detect, watcher, choose, lighten, itemRule, lighter,
  };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ForgePerf = api;
})(this);
