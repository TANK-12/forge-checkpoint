/* Janhollow — atmosphere passes.
 *
 * Sheepy: A Short Adventure gets its mood from five cheap things layered over
 * ordinary pixel art: bloom that reads as light rather than as fog, a hard
 * contact shadow wherever anything meets the floor, dust that only exists
 * inside a light pool, soft shafts spilling out of openings, and a *restrained*
 * screen pass. This file is those five, as five passes render.js calls in
 * order. It owns no game state, mutates no scene, and draws nothing on its own.
 *
 * Load order: a classic script, before render.js. It exposes exactly one
 * global, `window.Atmosphere`.
 *
 * Suggested call order inside a frame (each pass is independent, so a caller
 * may skip any of them):
 *
 *     drawDeck(...)                       // floors, walls, props
 *     Atmosphere.groundShadowPass(ctx, scene)   // before the actors, so the
 *                                               // deck sits in its shadow
 *     drawCrew(...)
 *     Atmosphere.lightPass(ctx, scene)          // additive, over the lit things
 *     Atmosphere.dustPass(ctx, scene, dt)
 *     Atmosphere.screenPass(ctx, scene)         // always last
 *
 * WHAT IS CACHED, AND WHY
 * -----------------------
 * Radial gradients and per-pixel noise are the two expensive things in
 * canvas2d. Neither of them changes between frames here, so both are baked
 * once to offscreen canvases and the frame pays only for blits:
 *
 *   bloomSprites   one 128px radial per light colour. Twenty lamps then cost
 *                  twenty drawImage calls instead of twenty gradient fills.
 *                  Scaling a soft blob is invisible, so one texture serves
 *                  every radius.
 *   contactCanvas  every wall-base gradient and every static prop shadow on
 *                  the deck, pre-composited: one blit per frame. This is the
 *                  single biggest win, because contact shadow is also the
 *                  single biggest visual win and is pure geometry.
 *   shaftCanvas    every door/viewport cone. Baked; only its global alpha
 *                  breathes per frame, which is free.
 *   toneCanvas     vignette + warm/cool split + the faked chromatic fringe.
 *                  Depends on canvas size alone, so it survives camera moves.
 *   grainTiles     six 128px noise tiles, cycled. Generating noise per frame
 *                  costs whole milliseconds; the eye cannot tell six frames of
 *                  grain from infinitely many.
 *   lightField     a coarse grid (one cell per `dustFieldCell` pixels) of "how
 *                  lit is this pixel". A dust mote's brightness is then one
 *                  array lookup instead of a loop over every lamp — the reason
 *                  a few hundred motes stay free.
 *   lightGains     per-light "how much darkness is this lamp standing in",
 *                  which is what makes bloom read as light (see lightPass).
 *
 * Everything geometry-shaped is keyed on a signature of tile size, scale,
 * the deck rows, and light/prop positions, plus the canvas size, a settings
 * revision and the bake window (scene.bake, see bakeWindowOf). Change a
 * tunable at runtime and the bakes rebuild on the next frame by themselves.
 * The camera offset is not in the key: the bakes cover a window bigger than
 * the screen and are blitted at the offset, so a moving camera only rebakes
 * when it leaves the window.
 *
 * Nothing here throws on a malformed scene: every pass returns early when the
 * fields it needs are missing, so a caller can wire it in before the backend
 * is sending lights or props.
 */
"use strict";

window.Atmosphere = (function () {
  /* The backend's one-character-per-tile alphabet, same as render.js. */
  const HULL = " ", FLOOR = ".", WALL = "#", DOOR = "+", LIFT = "L";

  /* Hull and wall both block light and both cast onto the floor beside them;
     for shadow purposes the outside of the station is just a very large wall. */
  const isBlocker = (ch) => ch === WALL || ch === HULL || ch === undefined;
  const isOpen = (ch) => ch === FLOOR || ch === DOOR || ch === LIFT;

  /* ------------------------------------------------------------------ *
   * settings                                                            *
   * ------------------------------------------------------------------ *
   * Intensities are 0..1 and default deliberately low. Sheepy is moody,
   * not filtered: every one of these looks better slightly under-done than
   * slightly over-done, and four subtle passes stack into something strong.
   * Set any intensity to 0 to switch that effect off entirely (the pass then
   * costs one comparison). Writing to this object is safe at any time —
   * `settingsRevision()` folds it into the bake keys.                    */
  const settings = {
    /* --- master ----------------------------------------------------- */
    enabled: true,          // false makes every pass a no-op
    quality: 1,             // 0..1 — scales particle count and grain size for
                            // weak GPUs. 1 is the tuned look.

    /* --- 1. bloom (lightPass) --------------------------------------- */
    bloom: 0.55,            // overall additive strength of every light
    bloomRadius: 1.35,      // multiplier on each light's `reach`. Above 1 so
                            // glow spills past the lit floor, which is what
                            // sells it as air rather than as a decal.
    bloomCore: 0.5,         // strength of the small near-white hot centre. The
                            // core is what stops bloom reading as fog: a real
                            // light has a bright point in it.
    bloomContrast: 0.6,     // how much extra a lamp standing in darkness gets.
                            // 0 = every lamp blooms identically (flat, dull).
    flicker: 0.5,           // scales each light's own `flicker` 0..1 field
    lightShafts: 0.35,      // 4. cone intensity out of doors and viewports
    shaftLength: 4.5,       // tiles a cone reaches before it is gone
    shaftBreath: 0.25,      // how much shaft alpha drifts over time, 0..1

    /* --- 2. contact shadow (groundShadowPass) ----------------------- */
    contact: 0.7,           // darkness of the gradient at a wall base
    contactLength: 0.62,    // how far it reaches onto the floor, in tiles
    contactSide: 0.45,      // relative strength of the thinner shadow on the
                            // left/right of a wall (and above it). Sides are
                            // weaker because the implied key light is high and
                            // slightly toward the camera.
    ambientOcclusion: 0.5,  // extra corner darkening where two walls meet
    propShadow: 0.6,        // ellipse under every solid prop
    actorShadow: 0.65,      // ellipse under every actor, drawn per frame

    /* --- 3. dust (dustPass) ----------------------------------------- */
    dust: 0.75,             // overall mote opacity
    dustCount: 520,         // motes on a 1400x900 canvas; scaled by area and
                            // by `quality` so a small window is not crowded
    dustDrift: 7,           // px/second sideways at depth 1
    dustRise: 5,            // px/second upward bias. Dust in still air falls,
                            // but rising dust reads as "warm air off a lamp",
                            // which is the Sheepy tell.
    dustParallax: 0.8,      // 0 = all motes move together; 1 = full depth split
    dustGateFloor: 0.14,    // light level below which a mote is fully invisible.
                            // This is the whole trick: motes outside a pool
                            // must not exist, or they read as snow.

    /* --- 5. screen pass --------------------------------------------- */
    vignette: 0.55,
    grain: 0.05,            // deliberately tiny. At 0.12 it looks like a filter
                            // and the pixel art stops reading as pixel art.
    grainFps: 16,           // grain that updates every frame shimmers; film
                            // grain at ~16Hz reads as texture, not as noise.
    split: 0.35,            // warm centre / cool edge tone separation
    chromatic: 0.3,         // faked colour fringe in the far corners

    /* --- internal --------------------------------------------------- */
    seed: 20260916,         // motes and grain are deterministic from this, so
                            // two screenshots of the same frame match.
  };

  /* Cache keys have to notice a settings change, but hashing the whole object
     every frame is silly. Only the values that a *bake* depends on go in. */
  function settingsRevision() {
    return [
      settings.quality, settings.contact, settings.contactLength,
      settings.contactSide, settings.ambientOcclusion, settings.propShadow,
      settings.lightShafts, settings.shaftLength, settings.vignette,
      settings.bloom, settings.bloomRadius, settings.bloomCore,
      settings.bloomContrast, settings.flicker,
      settings.split, settings.chromatic, settings.grain, settings.seed,
    ].join(",");
  }

  /* ------------------------------------------------------------------ *
   * small utilities                                                     *
   * ------------------------------------------------------------------ */

  const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
  const num = (v, fallback) => (typeof v === "number" && isFinite(v) ? v : fallback);

  /* A 32-bit LCG. Deterministic, seedable and about ten times cheaper than
     Math.random with the bonus that a screenshot is reproducible. */
  function makeRng(seed) {
    let s = (seed >>> 0) || 1;
    return function () {
      s = (s * 1664525 + 1013904223) >>> 0;
      return s / 4294967296;
    };
  }

  /* FNV-1a over a string. Used to fold the deck rows into a cache key. */
  function hashString(str) {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
    }
    return h >>> 0;
  }

  /* Any CSS colour to {r,g,b,a}. Rather than write a CSS colour parser, hand
     the string to a scratch canvas and read back what the browser normalised
     it to — that gets named colours, hsl() and colour spaces for free, and it
     is memoised so the cost is once per distinct colour for the life of the
     page. An unparseable colour falls back to a warm lamp white rather than
     throwing, because a bad colour in one manifest should not blank the deck. */
  const colourCache = new Map();
  let colourProbe = null;
  function parseColour(css) {
    if (colourCache.has(css)) return colourCache.get(css);
    let out = { r: 255, g: 226, b: 176, a: 1 };
    try {
      if (!colourProbe) {
        const c = document.createElement("canvas");
        c.width = c.height = 1;
        colourProbe = c.getContext("2d");
      }
      colourProbe.fillStyle = "#000";
      colourProbe.fillStyle = css;
      const norm = String(colourProbe.fillStyle);
      let m = /^#([0-9a-f]{6})$/i.exec(norm);
      if (m) {
        const v = parseInt(m[1], 16);
        out = { r: (v >> 16) & 255, g: (v >> 8) & 255, b: v & 255, a: 1 };
      } else if ((m = /^rgba?\(([^)]+)\)$/i.exec(norm))) {
        const p = m[1].split(",").map((s) => parseFloat(s));
        out = { r: p[0] | 0, g: p[1] | 0, b: p[2] | 0, a: p.length > 3 ? p[3] : 1 };
      }
    } catch (e) {
      /* no-op: the fallback above is a perfectly good lamp colour */
    }
    colourCache.set(css, out);
    return out;
  }

  const rgba = (c, a) => `rgba(${c.r},${c.g},${c.b},${a})`;

  function makeCanvas(w, h) {
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.ceil(w));
    c.height = Math.max(1, Math.ceil(h));
    return c;
  }

  /* The same canvas back, cleared, when it is already the right size; a new
     one otherwise. Saves a full-size allocation on every rebake. */
  function reuseCanvas(c, w, h) {
    const cw = Math.max(1, Math.ceil(w)), ch = Math.max(1, Math.ceil(h));
    if (!c || c.width !== cw || c.height !== ch) return makeCanvas(cw, ch);
    const ctx = c.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, cw, ch);
    return c;
  }

  /* ------------------------------------------------------------------ *
   * module state                                                        *
   * ------------------------------------------------------------------ */

  const state = {
    w: 0, h: 0,               // canvas size in device px
    sig: "",                  // geometry signature the bakes were made for
    baseSig: "",              // the same without the bake window, for dust
    bakeX: 0, bakeY: 0,       // bake window corner in deck px (screen - ox)
    bakeW: 0, bakeH: 0,       // bake window size in device px
    sizeSig: "",              // canvas-size signature the size-only bakes used
    contactCanvas: null,
    shaftCanvas: null,
    shaftRect: { x: 0, y: 0 },
    bloomCanvas: null,
    bloomRect: { x: 0, y: 0 },
    toneCanvas: null,
    grainTiles: [],
    grainPatterns: [],
    lightField: null,         // Float32Array, `fieldW` x `fieldH`
    litCells: [],             // indices into lightField worth seeding dust in
    fieldW: 0, fieldH: 0, fieldCell: 16,
    lightGains: null,         // Float32Array, one per light
    bloomSprites: new Map(),  // css colour -> baked 128px canvas
    motes: null,
    moteRng: null,
    moteCount: 0,
    lastOx: null, lastOy: null,
    buckets: null,            // reused per-alpha-bucket coordinate arrays
  };

  const BLOOM_TEX = 128;      // baked bloom sprite size. Big enough that the
                              // soft falloff has no visible banding, small
                              // enough that twenty of them are ~1MB of VRAM.
  const GRAIN_TILE = 128;
  const GRAIN_FRAMES = 6;
  const MOTE_LIFE_MIN = 5;    // seconds. Long enough to drift visibly across a
  const MOTE_LIFE_MAX = 13;   // pool, short enough that dark corners clear out.
  const MOTE_FADE = 1.4;      // seconds of fade at each end of a life, which is
                              // what makes a respawn invisible.
  const ALPHA_BUCKETS = 8;    // dust is drawn in this many alpha groups so we
                              // set globalAlpha eight times, not 320 times.

  /* ------------------------------------------------------------------ *
   * scene access, all of it tolerant of a half-built scene              *
   * ------------------------------------------------------------------ */

  function usable(scene) {
    return !!(settings.enabled && scene && typeof scene === "object");
  }

  function geom(scene) {
    const tile = num(scene.tile, 32);
    const scale = num(scene.scale, 1);
    return {
      tile,
      scale,
      px: tile * scale,                 // one tile in screen pixels
      ox: num(scene.ox, 0),
      oy: num(scene.oy, 0),
      width: Math.max(0, num(scene.width, 0) | 0),
      height: Math.max(0, num(scene.height, 0) | 0),
      rows: Array.isArray(scene.rows) ? scene.rows : null,
      bake: bakeWindowOf(scene),
    };
  }

  /* The area the geometry bakes cover, in deck pixels (screen x minus ox).
     render.js passes a window a margin bigger than the screen that only moves
     when the camera leaves it, so the bakes outlive a moving
     camera. Without one the window is the screen itself, which is exactly the
     old behaviour. Whole pixels only, so every blit lands on a whole pixel. */
  function bakeWindowOf(scene) {
    const b = scene.bake;
    if (b && typeof b === "object") {
      const x = num(b.x, NaN), y = num(b.y, NaN), w = num(b.w, NaN), h = num(b.h, NaN);
      if (isFinite(x) && isFinite(y) && w >= 1 && h >= 1) {
        return { x: Math.round(x), y: Math.round(y), w: Math.ceil(w), h: Math.ceil(h) };
      }
    }
    return { x: -num(scene.ox, 0), y: -num(scene.oy, 0), w: state.w, h: state.h };
  }

  /* The geometry as the bakes see it: the deck's corner moved into the bake
     window's own pixels. */
  function bakeGeom(g) {
    return Object.assign({}, g, { ox: -g.bake.x, oy: -g.bake.y });
  }

  /* Where the bake window's corner is on screen this frame. */
  const shiftX = (g) => g.ox + state.bakeX;
  const shiftY = (g) => g.oy + state.bakeY;

  function charAt(g, x, y) {
    if (!g.rows || y < 0 || y >= g.rows.length) return undefined;
    const row = g.rows[y];
    if (typeof row !== "string" || x < 0 || x >= row.length) return undefined;
    return row[x];
  }

  /* Lights, props and actors are all optional and all may carry junk. Normalise
     once per bake rather than defending at every use site. */
  function lightsOf(scene) {
    const src = Array.isArray(scene.lights) ? scene.lights : [];
    const out = [];
    for (let i = 0; i < src.length; i++) {
      const l = src[i];
      if (!l || typeof l !== "object") continue;
      const x = num(l.x, NaN), y = num(l.y, NaN);
      if (!isFinite(x) || !isFinite(y)) continue;
      out.push({
        x, y,
        reach: Math.max(0.2, num(l.reach, 3)),
        colour: typeof l.colour === "string" ? l.colour : "#ffd9a0",
        flicker: clamp01(num(l.flicker, 0)),
      });
    }
    return out;
  }

  function propsOf(scene) {
    const src = Array.isArray(scene.props) ? scene.props : [];
    const out = [];
    for (let i = 0; i < src.length; i++) {
      const p = src[i];
      if (!p || typeof p !== "object") continue;
      const x = num(p.x, NaN), y = num(p.y, NaN);
      if (!isFinite(x) || !isFinite(y)) continue;
      out.push({ x, y, solid: !!p.solid, sprite: p.sprite });
    }
    return out;
  }

  function actorsOf(scene) {
    const src = Array.isArray(scene.actors) ? scene.actors : [];
    const out = [];
    for (let i = 0; i < src.length; i++) {
      const a = src[i];
      if (!a || typeof a !== "object") continue;
      const x = num(a.x, NaN), y = num(a.y, NaN);
      if (!isFinite(x) || !isFinite(y)) continue;
      out.push({ x, y, h: Math.max(1, num(a.h, 48)) });
    }
    return out;
  }

  /* ------------------------------------------------------------------ *
   * cache invalidation                                                  *
   * ------------------------------------------------------------------ *
   * One string decides whether every geometry bake is still good. Hashing the
   * deck rows is about a thousand character reads, which is nothing next to
   * rebuilding a full-canvas shadow layer, and it means a caller can hand us a
   * brand new deck with no notification and the right thing happens. */
  function signature(scene, g, lights, props) {
    let rowsHash = 0;
    if (g.rows) rowsHash = hashString(g.rows.join("\n"));
    let lightHash = 2166136261;
    for (let i = 0; i < lights.length; i++) {
      const l = lights[i];
      lightHash = (lightHash ^ ((l.x * 73856093) ^ (l.y * 19349663) ^ (l.reach * 83492791))) >>> 0;
      lightHash = (lightHash + hashString(l.colour)) >>> 0;
    }
    let propHash = 2166136261;
    for (let i = 0; i < props.length; i++) {
      const p = props[i];
      propHash = (propHash ^ ((p.x * 2654435761) ^ (p.y * 40503) ^ (p.solid ? 7 : 0))) >>> 0;
    }
    /* No camera offset in here: the bake window below stands in for it. */
    return [
      state.w, state.h, g.tile, g.scale.toFixed(4),
      g.width, g.height, rowsHash, lightHash, propHash, settingsRevision(),
    ].join("|");
  }

  /* Called at the top of every pass. Cheap when nothing moved: one join and
     one hash, then a string compare. */
  function ensure(ctx, scene) {
    const canvas = ctx && ctx.canvas;
    if (canvas && (canvas.width !== state.w || canvas.height !== state.h)) {
      resize(canvas.width, canvas.height);
    }
    if (!state.w || !state.h) return null;

    const g = geom(scene);
    const lights = lightsOf(scene);
    const props = propsOf(scene);
    const base = signature(scene, g, lights, props);
    const b = g.bake;
    const sig = base + "|" + b.x + "|" + b.y + "|" + b.w + "|" + b.h;
    const cached = { g, lights, props };

    if (sig !== state.sig) {
      /* A new deck, zoom or setting puts the dust back into the light pools.
         A camera that only left its bake window keeps the dust where it is,
         so walking does not re-scatter it. */
      const fresh = base !== state.baseSig;
      state.sig = sig;
      state.baseSig = base;
      state.bakeX = b.x;
      state.bakeY = b.y;
      state.bakeW = b.w;
      state.bakeH = b.h;
      const bg = bakeGeom(g);
      if (fresh) bakeLightGains(bg, lights);
      bakeStaticBloom(bg, lights);
      bakeLightField(bg, lights);
      if (fresh) seedMotes(g);
      bakeContact(bg, props);
      bakeShafts(bg, lights);
    }
    const sizeSig = state.w + "x" + state.h + "|" + settingsRevision();
    if (sizeSig !== state.sizeSig) {
      state.sizeSig = sizeSig;
      bakeTone();
      bakeGrain();
    }
    return cached;
  }

  /* ------------------------------------------------------------------ *
   * bake: how much darkness is each lamp standing in                    *
   * ------------------------------------------------------------------ *
   * Bloom that is the same everywhere reads as haze. What makes a light read
   * as *light* is contrast: the lamp at the end of a black corridor should
   * blaze, the fourth ceiling panel in a bright room should barely glow. Two
   * things go into the gain:
   *
   *   structure  — how much of the ring of tiles around the lamp is wall or
   *                hull. A lamp in a tight dark space bounces nothing back and
   *                is surrounded by black to bloom against.
   *   isolation  — how little other lamps already light this spot. A lamp in a
   *                crowd is just one of a row of ceiling panels.
   *
   * Both are pure geometry, so this is baked with the rest.                */
  function bakeLightGains(g, lights) {
    const gains = new Float32Array(lights.length);
    for (let i = 0; i < lights.length; i++) {
      const l = lights[i];

      /* Sample a ring at 60% of reach: close enough to matter, far enough to
         see the room rather than the lamp's own tile. Sixteen samples was the
         point where adding more stopped changing the number. */
      let dark = 0;
      const rr = l.reach * 0.6;
      for (let s = 0; s < 16; s++) {
        const a = (s / 16) * Math.PI * 2;
        const ch = charAt(g, Math.round(l.x + Math.cos(a) * rr), Math.round(l.y + Math.sin(a) * rr));
        if (isBlocker(ch)) dark++;
      }
      dark /= 16;

      let crowd = 0;
      for (let j = 0; j < lights.length; j++) {
        if (j === i) continue;
        const o = lights[j];
        const d = Math.hypot(o.x - l.x, o.y - l.y);
        if (d < o.reach) crowd += 1 - d / o.reach;
      }
      const isolation = 1 / (1 + crowd);

      /* 0.6/0.4 by eye: structure is the stronger cue, but without the crowd
         term a bank of consoles turns into one enormous blob. */
      gains[i] = 1 + settings.bloomContrast * (0.6 * dark + 0.4 * isolation);
    }
    state.lightGains = gains;
  }

  /* ------------------------------------------------------------------ *
   * bake: the coarse light field the dust reads                         *
   * ------------------------------------------------------------------ *
   * One float per `fieldCell` square of screen. Built once per geometry, it
   * turns "is this mote inside a light pool" into a single array index. At a
   * 16px cell a 1400x900 canvas is ~5k cells: a few milliseconds to build and
   * free thereafter. The falloff is squared because a mote should light up
   * near the lamp and vanish well before the edge of the visible pool —
   * matching the pool exactly makes the dust look like a sticker of the pool. */
  function bakeLightField(g, lights) {
    const cell = state.fieldCell = Math.max(8, Math.round(16 / Math.max(0.3, settings.quality)));
    const fw = state.fieldW = Math.ceil(state.bakeW / cell) + 1;
    const fh = state.fieldH = Math.ceil(state.bakeH / cell) + 1;
    const field = new Float32Array(fw * fh);

    for (let i = 0; i < lights.length; i++) {
      const l = lights[i];
      const cx = g.ox + (l.x + 0.5) * g.px;
      const cy = g.oy + (l.y + 0.5) * g.px;
      const r = l.reach * g.px * settings.bloomRadius;
      const gain = state.lightGains ? state.lightGains[i] : 1;

      /* Only touch the cells the light can reach. */
      const x0 = Math.max(0, Math.floor((cx - r) / cell));
      const x1 = Math.min(fw - 1, Math.ceil((cx + r) / cell));
      const y0 = Math.max(0, Math.floor((cy - r) / cell));
      const y1 = Math.min(fh - 1, Math.ceil((cy + r) / cell));
      const r2 = r * r;
      for (let fy = y0; fy <= y1; fy++) {
        const dy = fy * cell - cy;
        for (let fx = x0; fx <= x1; fx++) {
          const dx = fx * cell - cx;
          const d2 = dx * dx + dy * dy;
          if (d2 >= r2) continue;
          const t = 1 - Math.sqrt(d2) / r;
          field[fy * fw + fx] += t * t * gain;
        }
      }
    }
    /* While we have the field, keep the list of cells that are lit enough for
       a mote to be visible in. Dust is respawned into this list rather than
       uniformly over the screen: a uniform field wastes nine motes in ten on
       dark floor, and the pools end up with three specks in them. Seeding
       straight into the light is what makes a lamp look like it has air in
       front of it without paying for thousands of particles. */
    const lit = [];
    for (let i = 0; i < field.length; i++) {
      if (field[i] > 1) field[i] = 1;
      if (field[i] > settings.dustGateFloor * 1.2) lit.push(i);
    }
    state.lightField = field;
    state.litCells = lit;
  }

  /* x and y are in the bake window's pixels: screen minus shiftX/shiftY. */
  function sampleField(x, y) {
    const f = state.lightField;
    if (!f) return 0;
    const cell = state.fieldCell;
    const fx = (x / cell) | 0, fy = (y / cell) | 0;
    if (fx < 0 || fy < 0 || fx >= state.fieldW || fy >= state.fieldH) return 0;
    return f[fy * state.fieldW + fx];
  }

  /* ------------------------------------------------------------------ *
   * bake: contact shadow                                                *
   * ------------------------------------------------------------------ *
   * The one effect that does more for depth than everything else here put
   * together, and it is pure geometry, so the entire deck's worth of it is one
   * offscreen canvas and one blit per frame.
   *
   * The implied key light is high and slightly toward the camera, which in a
   * top-down view means the strong shadow falls *down* the screen from a wall
   * onto the floor below it, with thinner shadow on the other three sides for
   * the ambient term. Doubling up at corners is not a bug: two walls meeting is
   * exactly where a room should go darkest, and the extra `ambientOcclusion`
   * dab there is what makes a corner look like a corner.                  */
  function bakeContact(g, props) {
    const canvas = reuseCanvas(state.contactCanvas, state.bakeW, state.bakeH);
    if (settings.contact <= 0 && settings.propShadow <= 0) {
      state.contactCanvas = canvas;
      return;
    }
    const ctx = canvas.getContext("2d");
    const t = g.px;
    const drop = Math.max(2, t * settings.contactLength);
    const side = Math.max(1, drop * 0.55);

    const X = (tx) => g.ox + tx * t;
    const Y = (ty) => g.oy + ty * t;

    /* Gradients are created per direction, not per tile: a gradient object is
       expensive to make and the four we need are identical everywhere once
       translated. Canvas gradients are bound to coordinates, so instead of
       translating them we build one per direction at the origin and move the
       canvas under it with setTransform — one gradient allocation for the
       whole deck instead of one per wall. */
    const a = settings.contact;
    const down = ctx.createLinearGradient(0, 0, 0, drop);
    down.addColorStop(0, `rgba(0,0,0,${a})`);
    down.addColorStop(0.35, `rgba(0,0,0,${a * 0.42})`);
    down.addColorStop(1, "rgba(0,0,0,0)");

    const sideA = a * settings.contactSide;
    const up = ctx.createLinearGradient(0, 0, 0, -side);
    up.addColorStop(0, `rgba(0,0,0,${sideA})`);
    up.addColorStop(1, "rgba(0,0,0,0)");
    const right = ctx.createLinearGradient(0, 0, side, 0);
    right.addColorStop(0, `rgba(0,0,0,${sideA})`);
    right.addColorStop(1, "rgba(0,0,0,0)");
    const left = ctx.createLinearGradient(0, 0, -side, 0);
    left.addColorStop(0, `rgba(0,0,0,${sideA})`);
    left.addColorStop(1, "rgba(0,0,0,0)");

    for (let y = 0; y < g.height; y++) {
      for (let x = 0; x < g.width; x++) {
        if (!isBlocker(charAt(g, x, y))) continue;
        const sx = X(x), sy = Y(y);

        /* Below: the real contact shadow. */
        if (isOpen(charAt(g, x, y + 1))) {
          ctx.save();
          ctx.translate(sx, sy + t);
          ctx.fillStyle = down;
          ctx.fillRect(0, 0, t + 1, drop);
          ctx.restore();
        }
        /* Above, and the two sides: ambient contact, much weaker. */
        if (isOpen(charAt(g, x, y - 1))) {
          ctx.save();
          ctx.translate(sx, sy);
          ctx.fillStyle = up;
          ctx.fillRect(0, -side, t + 1, side);
          ctx.restore();
        }
        if (isOpen(charAt(g, x + 1, y))) {
          ctx.save();
          ctx.translate(sx + t, sy);
          ctx.fillStyle = right;
          ctx.fillRect(0, 0, side, t + 1);
          ctx.restore();
        }
        if (isOpen(charAt(g, x - 1, y))) {
          ctx.save();
          ctx.translate(sx, sy);
          ctx.fillStyle = left;
          ctx.fillRect(-side, 0, side, t + 1);
          ctx.restore();
        }
      }
    }

    /* Inside corners: where an open tile has blockers on two perpendicular
       sides, put a small radial dab in that corner. Cheap, and it is the
       difference between "a room" and "a floor with walls drawn on it". */
    if (settings.ambientOcclusion > 0) {
      const ao = settings.ambientOcclusion * 0.5;
      const rad = t * 0.75;
      const dab = ctx.createRadialGradient(0, 0, 0, 0, 0, rad);
      dab.addColorStop(0, `rgba(0,0,0,${ao})`);
      dab.addColorStop(0.6, `rgba(0,0,0,${ao * 0.28})`);
      dab.addColorStop(1, "rgba(0,0,0,0)");
      for (let y = 0; y < g.height; y++) {
        for (let x = 0; x < g.width; x++) {
          if (!isOpen(charAt(g, x, y))) continue;
          const l = isBlocker(charAt(g, x - 1, y)), r = isBlocker(charAt(g, x + 1, y));
          const u = isBlocker(charAt(g, x, y - 1)), d = isBlocker(charAt(g, x, y + 1));
          const corners = [];
          if (l && u) corners.push([0, 0]);
          if (r && u) corners.push([t, 0]);
          if (l && d) corners.push([0, t]);
          if (r && d) corners.push([t, t]);
          for (const c of corners) {
            ctx.save();
            ctx.translate(X(x) + c[0], Y(y) + c[1]);
            ctx.fillStyle = dab;
            ctx.fillRect(-rad, -rad, rad * 2, rad * 2);
            ctx.restore();
          }
        }
      }
    }

    /* Solid props sit still, so their shadows belong in the bake with
       everything else static. Actors are the only thing shadowed per frame. */
    if (settings.propShadow > 0) {
      for (const p of props) {
        if (!p.solid) continue;
        ellipseShadow(ctx, X(p.x) + t * 0.5, Y(p.y) + t * 0.86, t * 0.36, t * 0.15,
                      settings.propShadow);
      }
    }
    state.contactCanvas = canvas;
  }

  /* A soft grounded ellipse. Drawn with a radial gradient in a squashed
     transform rather than ctx.ellipse + shadowBlur: shadowBlur is the slowest
     thing in canvas2d and this looks the same. */
  function ellipseShadow(ctx, cx, cy, rx, ry, alpha) {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.scale(1, ry / rx);
    const gr = ctx.createRadialGradient(0, 0, 0, 0, 0, rx);
    gr.addColorStop(0, `rgba(0,0,0,${alpha})`);
    gr.addColorStop(0.45, `rgba(0,0,0,${alpha * 0.62})`);
    gr.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = gr;
    ctx.fillRect(-rx, -rx, rx * 2, rx * 2);
    ctx.restore();
  }

  /* One black radial blob, baked once, used for every per-frame shadow. Making
     a gradient per actor per frame is the kind of thing that quietly costs a
     millisecond at twenty crew; a scaled blit costs nothing. */
  let blobCanvas = null;
  function shadowBlob() {
    if (blobCanvas) return blobCanvas;
    const size = 64;
    const c = makeCanvas(size, size);
    const ctx = c.getContext("2d");
    const gr = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    gr.addColorStop(0, "rgba(0,0,0,1)");
    gr.addColorStop(0.45, "rgba(0,0,0,0.62)");
    gr.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = gr;
    ctx.fillRect(0, 0, size, size);
    blobCanvas = c;
    return c;
  }

  /* ------------------------------------------------------------------ *
   * bake: light shafts                                                  *
   * ------------------------------------------------------------------ *
   * Seen from above, a "shaft" is light spilling through an opening and
   * fanning across the floor beyond it. So every door casts a cone into each
   * open side it has, and every light sitting against the hull (a viewport)
   * casts one into the room. Two overlapping cones per opening — a narrow
   * bright one inside a wide faint one — because a single triangle has a hard
   * edge at its sides and real spill does not.
   *
   * Alpha here is *very* low on purpose. Shafts are the effect that most
   * easily turns a moody room into a smoke machine. The whole layer is baked
   * and only its global alpha breathes per frame.                         */
  function bakeShafts(g, lights) {
    state.shaftCanvas = null;
    if (settings.lightShafts <= 0 || !g.rows) return;
    const canvas = makeCanvas(state.bakeW, state.bakeH);
    const ctx = canvas.getContext("2d");
    ctx.globalCompositeOperation = "lighter";
    const t = g.px;

    /* The union of every cone, so the finished layer can be cropped. A
       full-canvas additive blit every frame was measured at ~5ms in software
       rendering; cropping to the region that actually has shafts in it cuts
       that to the area that is lit, which on a normal deck is a fraction. */
    let bx0 = Infinity, by0 = Infinity, bx1 = -Infinity, by1 = -Infinity;
    const grow = (x, y) => {
      if (x < bx0) bx0 = x;
      if (y < by0) by0 = y;
      if (x > bx1) bx1 = x;
      if (y > by1) by1 = y;
    };

    /* How far a cone can go before it hits something. Light spilling out of a
       doorway should stop at the far wall, not print a triangle through it;
       walking the tiles is a handful of lookups in a bake we do once. */
    const clearRun = (tx, ty, dx, dy) => {
      let run = 0;
      for (let step = 1; step <= Math.ceil(settings.shaftLength) + 1; step++) {
        if (!isOpen(charAt(g, tx + dx * step, ty + dy * step))) break;
        run = step;
      }
      return Math.min(settings.shaftLength, run + 0.5);
    };

    const cone = (cx, cy, dx, dy, colour, strength, runTiles) => {
      const c = parseColour(colour);
      /* Perpendicular, for the mouth and the far end of the cone. */
      const nx = -dy, ny = dx;
      for (let pass = 0; pass < 2; pass++) {
        const wide = pass === 0;
        const mouth = t * (wide ? 0.5 : 0.3);
        const far = t * (wide ? 2.3 : 1.15);
        const reach = runTiles * t * (wide ? 1 : 0.78);
        if (reach < t * 0.4) continue;
        const a = strength * (wide ? 0.5 : 1);
        const gr = ctx.createLinearGradient(cx, cy, cx + dx * reach, cy + dy * reach);
        gr.addColorStop(0, rgba(c, a));
        gr.addColorStop(0.45, rgba(c, a * 0.34));
        gr.addColorStop(1, rgba(c, 0));
        ctx.fillStyle = gr;
        ctx.beginPath();
        ctx.moveTo(cx + nx * mouth, cy + ny * mouth);
        ctx.lineTo(cx - nx * mouth, cy - ny * mouth);
        ctx.lineTo(cx + dx * reach - nx * far, cy + dy * reach - ny * far);
        ctx.lineTo(cx + dx * reach + nx * far, cy + dy * reach + ny * far);
        ctx.closePath();
        ctx.fill();
        grow(cx + nx * mouth, cy + ny * mouth);
        grow(cx - nx * mouth, cy - ny * mouth);
        grow(cx + dx * reach - nx * far, cy + dy * reach - ny * far);
        grow(cx + dx * reach + nx * far, cy + dy * reach + ny * far);
      }
    };

    const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1]];
    const base = settings.lightShafts * 0.16; // 0.16 found by eye: at 0.3 the
                                              // floor washed out to grey.

    for (let y = 0; y < g.height; y++) {
      for (let x = 0; x < g.width; x++) {
        const ch = charAt(g, x, y);
        if (ch !== DOOR && ch !== LIFT) continue;
        const cx = g.ox + (x + 0.5) * t, cy = g.oy + (y + 0.5) * t;
        /* A door's own cool strip light; a lift's is a touch stronger. */
        const colour = ch === LIFT ? "#8fd8ff" : "#bfe6de";
        for (const d of DIRS) {
          if (!isOpen(charAt(g, x + d[0], y + d[1]))) continue;
          cone(cx, cy, d[0], d[1], colour, base * (ch === LIFT ? 1.2 : 1),
               clearRun(x, y, d[0], d[1]));
        }
      }
    }

    /* A light with hull behind it is a viewport: it throws a cone inward. */
    for (const l of lights) {
      const lx = Math.round(l.x), ly = Math.round(l.y);
      for (const d of DIRS) {
        const behind = charAt(g, lx - d[0], ly - d[1]);
        if (behind !== HULL && behind !== undefined) continue;
        if (!isOpen(charAt(g, lx + d[0], ly + d[1]))) continue;
        const cx = g.ox + (l.x + 0.5) * t, cy = g.oy + (l.y + 0.5) * t;
        cone(cx, cy, d[0], d[1], l.colour, base * 1.35, clearRun(lx, ly, d[0], d[1]));
      }
    }

    if (bx1 <= bx0 || by1 <= by0) { state.shaftCanvas = null; return; }
    const rx = Math.max(0, Math.floor(bx0)), ry = Math.max(0, Math.floor(by0));
    const rw = Math.min(state.bakeW, Math.ceil(bx1)) - rx;
    const rh = Math.min(state.bakeH, Math.ceil(by1)) - ry;
    if (rw <= 0 || rh <= 0) { state.shaftCanvas = null; return; }
    const cropped = makeCanvas(rw, rh);
    cropped.getContext("2d").drawImage(canvas, -rx, -ry);
    state.shaftCanvas = cropped;
    state.shaftRect = { x: rx, y: ry };
  }

  /* ------------------------------------------------------------------ *
   * bake: tone (vignette + warm/cool split + faked chromatic fringe)     *
   * ------------------------------------------------------------------ *
   * Depends only on canvas size, so it survives every camera move and every
   * deck change. Three things live in one canvas so the screen pass is one
   * blit instead of three:
   *
   *   vignette   a plain darkening toward the corners.
   *   split      warm toward the centre, cool at the edges. This is the whole
   *              of the "colour grade": Sheepy's warmth comes from its lamps,
   *              not from an orange filter over the frame.
   *   chromatic  real chromatic aberration means redrawing the frame once per
   *              channel, which is far too expensive. What the eye actually
   *              notices is a faint warm ring just inside a faint cool ring in
   *              the far corners, and that is free to bake.                */
  function bakeTone() {
    const canvas = makeCanvas(state.w, state.h);
    state.toneCanvas = canvas;
    const ctx = canvas.getContext("2d");
    const w = state.w, h = state.h;
    const cx = w / 2, cy = h / 2;
    const r = Math.hypot(cx, cy);

    if (settings.vignette > 0) {
      const v = settings.vignette;
      const gr = ctx.createRadialGradient(cx, cy, r * 0.32, cx, cy, r);
      gr.addColorStop(0, "rgba(0,0,0,0)");
      gr.addColorStop(0.62, `rgba(2,4,9,${v * 0.22})`);
      gr.addColorStop(1, `rgba(1,2,6,${v * 0.82})`);
      ctx.fillStyle = gr;
      ctx.fillRect(0, 0, w, h);
    }

    if (settings.split > 0) {
      const s = settings.split;
      ctx.globalCompositeOperation = "lighter";
      const warm = ctx.createRadialGradient(cx, cy * 0.92, 0, cx, cy * 0.92, r * 0.72);
      warm.addColorStop(0, `rgba(58,36,14,${s * 0.30})`);
      warm.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = warm;
      ctx.fillRect(0, 0, w, h);
      ctx.globalCompositeOperation = "source-over";
      /* The cool half of the split is a *subtractive-ish* blue at the edges:
         drawn as low-alpha navy rather than added, so it deepens shadow
         instead of lifting it. */
      const cool = ctx.createRadialGradient(cx, cy, r * 0.45, cx, cy, r);
      cool.addColorStop(0, "rgba(0,0,0,0)");
      cool.addColorStop(1, `rgba(16,30,58,${s * 0.34})`);
      ctx.fillStyle = cool;
      ctx.fillRect(0, 0, w, h);
    }

    if (settings.chromatic > 0) {
      const a = settings.chromatic;
      ctx.globalCompositeOperation = "lighter";
      const warmRing = ctx.createRadialGradient(cx, cy, r * 0.74, cx, cy, r * 0.94);
      warmRing.addColorStop(0, "rgba(0,0,0,0)");
      warmRing.addColorStop(0.6, `rgba(42,16,6,${a * 0.13})`);
      warmRing.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = warmRing;
      ctx.fillRect(0, 0, w, h);
      const coolRing = ctx.createRadialGradient(cx, cy, r * 0.9, cx, cy, r * 1.04);
      coolRing.addColorStop(0, "rgba(0,0,0,0)");
      coolRing.addColorStop(0.5, `rgba(6,22,46,${a * 0.16})`);
      coolRing.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = coolRing;
      ctx.fillRect(0, 0, w, h);
      ctx.globalCompositeOperation = "source-over";
    }
  }

  /* ------------------------------------------------------------------ *
   * bake: grain                                                         *
   * ------------------------------------------------------------------ *
   * Six tiles of salt-and-pepper noise, tiled with a CanvasPattern and cycled
   * at `grainFps`. Both halves matter: white specks alone silver the shadows,
   * black specks alone mud the highlights, and together they read as film.
   * Drawn with plain source-over rather than 'overlay' — a full-screen blend
   * mode is the one thing here that could actually miss 60fps on an iGPU, and
   * at this alpha nobody can tell the two apart.                          */
  function bakeGrain() {
    state.grainTiles = [];
    state.grainPatterns = [];
    if (settings.grain <= 0) return;
    const size = GRAIN_TILE;
    const rnd = makeRng(settings.seed);
    const probe = makeCanvas(1, 1).getContext("2d");
    for (let f = 0; f < GRAIN_FRAMES; f++) {
      const c = makeCanvas(size, size);
      const ctx = c.getContext("2d");
      const img = ctx.createImageData(size, size);
      const d = img.data;
      for (let i = 0; i < d.length; i += 4) {
        const v = rnd();
        /* Only about a third of pixels carry a speck; a fully dense field is
           a grey wash, not grain. */
        if (v < 0.17) { d[i] = d[i + 1] = d[i + 2] = 255; d[i + 3] = 255; }
        else if (v < 0.34) { d[i] = d[i + 1] = d[i + 2] = 0; d[i + 3] = 255; }
        else { d[i + 3] = 0; }
      }
      ctx.putImageData(img, 0, 0);
      state.grainTiles.push(c);
      state.grainPatterns.push(probe.createPattern(c, "repeat"));
    }
  }

  /* ------------------------------------------------------------------ *
   * bake: one bloom sprite per light colour                             *
   * ------------------------------------------------------------------ *
   * A radial gradient fill is the expensive call in canvas2d; drawImage is a
   * blit. One 128px texture per distinct colour, scaled to whatever radius a
   * light wants — scaling a soft blob has no visible artefact, so a single
   * texture serves every lamp of that colour on every deck.
   *
   * The stop list is the whole look. A near-white core in the first 6% is what
   * makes it read as a light source rather than as fog; the long tail past 60%
   * is what makes the air around it feel thick.                            */
  function bloomSprite(colour) {
    const key = colour + "|" + settings.bloomCore.toFixed(2);
    let sprite = state.bloomSprites.get(key);
    if (sprite) return sprite;
    const c = parseColour(colour);
    const size = BLOOM_TEX;
    const canvas = makeCanvas(size, size);
    const ctx = canvas.getContext("2d");
    const m = size / 2;
    const gr = ctx.createRadialGradient(m, m, 0, m, m, m);
    const core = clamp01(settings.bloomCore);
    /* Blend the colour toward white for the core only. */
    const wr = Math.round(c.r + (255 - c.r) * core);
    const wg = Math.round(c.g + (255 - c.g) * core);
    const wb = Math.round(c.b + (255 - c.b) * core);
    gr.addColorStop(0.00, `rgba(${wr},${wg},${wb},1)`);
    gr.addColorStop(0.05, `rgba(${wr},${wg},${wb},0.92)`);
    gr.addColorStop(0.12, rgba(c, 0.72));
    gr.addColorStop(0.26, rgba(c, 0.38));
    gr.addColorStop(0.46, rgba(c, 0.19));
    gr.addColorStop(0.70, rgba(c, 0.07));
    gr.addColorStop(1.00, rgba(c, 0));
    ctx.fillStyle = gr;
    ctx.fillRect(0, 0, size, size);
    state.bloomSprites.set(key, canvas);
    return canvas;
  }

  /* ------------------------------------------------------------------ *
   * bake: the bloom of every light that does not flicker                *
   * ------------------------------------------------------------------ *
   * `lighter` is commutative, so a steady lamp's glow can be pre-added into
   * one layer and blitted once. This matters because additive fill rate is
   * what costs: twenty lamps drawn individually paint roughly four million
   * additive pixels a frame, while their union cropped to its bounding box
   * paints closer to one. Only lights with a non-zero `flicker` stay in the
   * per-frame loop, which is usually a handful.                           */
  function bakeStaticBloom(g, lights) {
    state.bloomCanvas = null;
    if (settings.bloom <= 0) return;
    const steady = [];
    for (let i = 0; i < lights.length; i++) {
      if (lights[i].flicker > 0 && settings.flicker > 0) continue;
      steady.push(i);
    }
    if (!steady.length) return;

    const scratch = makeCanvas(state.bakeW, state.bakeH);
    const ctx = scratch.getContext("2d");
    ctx.globalCompositeOperation = "lighter";
    let bx0 = Infinity, by0 = Infinity, bx1 = -Infinity, by1 = -Infinity;
    let drew = false;
    for (const i of steady) {
      const l = lights[i];
      const gain = (state.lightGains && state.lightGains[i]) || 1;
      const a = clamp01(settings.bloom * gain);
      if (a <= 0.004) continue;
      const r = l.reach * g.px * settings.bloomRadius;
      const cx = g.ox + (l.x + 0.5) * g.px;
      const cy = g.oy + (l.y + 0.5) * g.px;
      if (cx + r < 0 || cy + r < 0 || cx - r > state.bakeW || cy - r > state.bakeH) continue;
      ctx.globalAlpha = a;
      ctx.drawImage(bloomSprite(l.colour), cx - r, cy - r, r * 2, r * 2);
      drew = true;
      if (cx - r < bx0) bx0 = cx - r;
      if (cy - r < by0) by0 = cy - r;
      if (cx + r > bx1) bx1 = cx + r;
      if (cy + r > by1) by1 = cy + r;
    }
    if (!drew) return;
    const rx = Math.max(0, Math.floor(bx0)), ry = Math.max(0, Math.floor(by0));
    const rw = Math.min(state.bakeW, Math.ceil(bx1)) - rx;
    const rh = Math.min(state.bakeH, Math.ceil(by1)) - ry;
    if (rw <= 0 || rh <= 0) return;
    const cropped = makeCanvas(rw, rh);
    cropped.getContext("2d").drawImage(scratch, -rx, -ry);
    state.bloomCanvas = cropped;
    state.bloomRect = { x: rx, y: ry };
  }

  /* Deterministic, non-repeating-looking flicker. Two sines at incommensurate
     rates give a slow wander; the third much faster term is the fluorescent
     buzz. `amount` is the light's own 0..1 field, so a steady lamp is steady. */
  function flickerOf(i, nowMs, amount) {
    if (amount <= 0 || settings.flicker <= 0) return 1;
    const t = nowMs / 1000;
    const p = i * 1.7;
    const slow = Math.sin(t * 1.31 + p) * 0.5 + Math.sin(t * 2.17 + p * 2.3) * 0.3;
    const buzz = Math.sin(t * 17.3 + p * 4.1) * 0.2;
    return 1 + (slow + buzz) * 0.42 * amount * settings.flicker;
  }

  /* ------------------------------------------------------------------ *
   * dust motes                                                          *
   * ------------------------------------------------------------------ *
   * Kept in parallel typed arrays rather than an array of objects: a few
   * hundred motes updated every frame is exactly the shape of loop where
   * object churn shows up as GC stutter, and stutter is the one thing that
   * would break the mood.
   *
   * Positions live in *screen* pixels, not world tiles, because a mote is air
   * in front of the camera rather than a thing on the deck. Depth then does
   * two jobs: it is the parallax factor when the camera moves, and it is the
   * size and brightness of the mote.                                     */
  function makeMotes() {
    const area = state.w * state.h;
    const want = Math.max(0, Math.round(settings.dustCount * clamp01(settings.quality) *
                                        (area / (1400 * 900))));
    const n = state.moteCount = want;
    const rnd = makeRng(settings.seed ^ 0x5eed);
    const m = state.motes = {
      x: new Float32Array(n), y: new Float32Array(n),
      depth: new Float32Array(n), size: new Float32Array(n),
      phase: new Float32Array(n), drift: new Float32Array(n),
      life: new Float32Array(n), span: new Float32Array(n),
    };
    for (let i = 0; i < n; i++) {
      m.x[i] = rnd() * state.w;
      m.y[i] = rnd() * state.h;
      /* Depth cubed biases the population toward the far plane, so the few
         big near motes feel like an accident rather than a layer. */
      const d = rnd();
      m.depth[i] = 0.15 + 0.85 * d * d;
      m.size[i] = m.depth[i] > 0.72 ? 2 : 1;   // whole pixels only: this is
                                               // pixel art, and a 1.4px mote
                                               // is a grey smudge.
      m.phase[i] = rnd() * Math.PI * 2;
      m.drift[i] = rnd() * 2 - 1;              // each mote has its own sideways
                                               // preference, or the whole field
                                               // slides like a curtain.
      /* Staggered lifetimes, so motes recycle a few at a time instead of the
         whole field blinking together every eight seconds. */
      m.span[i] = MOTE_LIFE_MIN + rnd() * (MOTE_LIFE_MAX - MOTE_LIFE_MIN);
      m.life[i] = rnd() * m.span[i];
    }
    state.moteRng = makeRng(settings.seed ^ 0xb15);
    state.buckets = [];
    for (let b = 0; b < ALPHA_BUCKETS; b++) state.buckets.push([]);
  }

  /* Put every mote straight into a light pool. Called whenever the light
     field is rebuilt, because otherwise a fresh deck spends ten seconds with
     its dust still hanging where the *previous* deck's lamps were, and the
     first screenshot of a room shows three specks. Lives stay staggered so the
     field still recycles a few at a time from here on. */
  function seedMotes(g) {
    const m = state.motes, lit = state.litCells;
    if (!m || !state.moteCount || !lit || !lit.length) return;
    const rnd = state.moteRng || (state.moteRng = makeRng(settings.seed ^ 0xb15));
    for (let i = 0; i < state.moteCount; i++) {
      placeInLight(m, i, g, rnd);
      m.span[i] = MOTE_LIFE_MIN + rnd() * (MOTE_LIFE_MAX - MOTE_LIFE_MIN);
      m.life[i] = MOTE_FADE + rnd() * (m.span[i] - MOTE_FADE);
    }
  }

  /* Put mote i in a lit cell that is on screen. The light field covers the
     whole bake window, which is bigger than the screen, so a few picks are
     tried before falling back to anywhere on screen; a mote put off screen
     would only wrap round to a random spot. */
  function placeInLight(m, i, g, rnd) {
    const lit = state.litCells, cell = state.fieldCell;
    const sx = shiftX(g), sy = shiftY(g);
    if (lit && lit.length) {
      for (let tries = 0; tries < 8; tries++) {
        const c = lit[(rnd() * lit.length) | 0];
        const x = (c % state.fieldW) * cell + rnd() * cell + sx;
        const y = ((c / state.fieldW) | 0) * cell + rnd() * cell + sy;
        if (x >= 0 && y >= 0 && x < state.w && y < state.h) {
          m.x[i] = x;
          m.y[i] = y;
          return;
        }
      }
    }
    m.x[i] = rnd() * state.w;
    m.y[i] = rnd() * state.h;
  }

  /* ------------------------------------------------------------------ *
   * the passes                                                          *
   * ------------------------------------------------------------------ */

  /* 1. Bloom, plus the baked shafts, both additive and both over the lit
        things. `lighter` is the only composite mode used per frame and only
        over the small rect each light covers, which keeps the fill rate down. */
  function lightPass(ctx, scene) {
    if (!usable(scene) || !ctx) return;
    const cache = ensure(ctx, scene);
    if (!cache) return;
    const g = cache.g;
    const now = num(scene.now, 0);

    ctx.save();
    ctx.globalCompositeOperation = "lighter";

    if (state.bloomCanvas) {
      ctx.globalAlpha = 1;
      ctx.drawImage(state.bloomCanvas, state.bloomRect.x + shiftX(g), state.bloomRect.y + shiftY(g));
    }

    if (settings.bloom > 0 && settings.flicker > 0) {
      for (let i = 0; i < cache.lights.length; i++) {
        const l = cache.lights[i];
        if (l.flicker <= 0) continue;   // already in the baked layer
        const gain = (state.lightGains && state.lightGains[i]) || 1;
        const flick = flickerOf(i, now, l.flicker);
        const a = clamp01(settings.bloom * gain * flick);
        if (a <= 0.004) continue;
        /* Flicker moves the radius a little as well as the brightness. A lamp
           whose brightness alone pulses looks like a fade, not a flicker. */
        const r = l.reach * g.px * settings.bloomRadius * (0.96 + 0.04 * flick);
        const cx = g.ox + (l.x + 0.5) * g.px;
        const cy = g.oy + (l.y + 0.5) * g.px;
        if (cx + r < 0 || cy + r < 0 || cx - r > state.w || cy - r > state.h) continue;
        ctx.globalAlpha = a;
        ctx.drawImage(bloomSprite(l.colour), cx - r, cy - r, r * 2, r * 2);
      }
    }

    if (state.shaftCanvas && settings.lightShafts > 0) {
      /* Two slow sines so the breath never settles into an obvious loop. The
         air in a station is moving; a perfectly steady shaft looks painted. */
      const t = now / 1000;
      const breath = 1 + settings.shaftBreath *
        (Math.sin(t * 0.37) * 0.6 + Math.sin(t * 0.83 + 1.1) * 0.4) * 0.5;
      ctx.globalAlpha = clamp01(breath);
      ctx.drawImage(state.shaftCanvas, state.shaftRect.x + shiftX(g), state.shaftRect.y + shiftY(g));
    }

    ctx.restore();
  }

  /* 2. Contact shadow. One blit of the baked deck-wide layer, then one small
        blob per actor. Call it before the actors are drawn so they stand in
        their own shadow rather than on top of it. */
  function groundShadowPass(ctx, scene) {
    if (!usable(scene) || !ctx) return;
    const cache = ensure(ctx, scene);
    if (!cache) return;

    const g = cache.g;
    if (state.contactCanvas) ctx.drawImage(state.contactCanvas, shiftX(g), shiftY(g));

    if (settings.actorShadow > 0) {
      const actors = actorsOf(scene);
      if (!actors.length) return;
      const blob = shadowBlob();
      ctx.save();
      for (const a of actors) {
        /* 0.86 of a tile down from the actor's own tile origin is where
           render.js already puts the crew's feet; matching it means the two
           shadows stack instead of fighting. */
        const cx = g.ox + (a.x + 0.5) * g.px;
        const cy = g.oy + (a.y + 0.86) * g.px;
        /* A taller sprite throws a slightly wider, slightly softer patch. */
        const tall = clamp01((a.h - g.tile) / (g.tile * 1.2));
        const rx = g.px * (0.30 + 0.07 * tall);
        const ry = rx * 0.42;
        ctx.globalAlpha = settings.actorShadow * (1 - 0.18 * tall);
        ctx.drawImage(blob, cx - rx, cy - ry, rx * 2, ry * 2);
      }
      ctx.restore();
    }
  }

  /* 3. Dust. Motes only exist inside a light pool: the field lookup gates them
        and the gate floor makes the gate hard-edged enough that an unlit
        corridor has visibly no dust in it. That absence is what makes the lit
        rooms feel like they have air in them. */
  function dustPass(ctx, scene, dtSeconds) {
    if (!usable(scene) || !ctx || settings.dust <= 0) return;
    const cache = ensure(ctx, scene);
    if (!cache) return;
    if (!state.motes || state.moteCount === 0) return;
    const g = cache.g;
    const m = state.motes;
    const n = state.moteCount;

    /* A stalled tab hands back a huge dt; clamping stops every mote teleporting
       off screen on the frame after the window is focused again. */
    let dt = num(dtSeconds, 1 / 60);
    if (dt < 0) dt = 0;
    if (dt > 0.1) dt = 0.1;

    /* Camera parallax: the deck offset moved, so the air should lag behind it
       by depth. Nothing else in the module needs to know the camera moved. */
    let camX = 0, camY = 0;
    if (state.lastOx !== null) {
      camX = (g.ox - state.lastOx);
      camY = (g.oy - state.lastOy);
    }
    state.lastOx = g.ox;
    state.lastOy = g.oy;

    const now = num(scene.now, 0) / 1000;
    const gate = clamp01(settings.dustGateFloor);
    const gateSpan = Math.max(0.05, 1 - gate);
    const buckets = state.buckets;
    for (let b = 0; b < ALPHA_BUCKETS; b++) buckets[b].length = 0;

    const rnd = state.moteRng || (state.moteRng = makeRng(settings.seed ^ 0xb15));
    const sx = shiftX(g), sy = shiftY(g);

    for (let i = 0; i < n; i++) {
      /* Age first: a mote whose life ran out is moved into a lit cell rather
         than deleted, so the population is constant and no allocation happens
         in the frame loop. */
      m.life[i] -= dt;
      if (m.life[i] <= 0) {
        m.span[i] = MOTE_LIFE_MIN + rnd() * (MOTE_LIFE_MAX - MOTE_LIFE_MIN);
        m.life[i] = m.span[i];
        placeInLight(m, i, g, rnd);
        m.phase[i] = rnd() * Math.PI * 2;
      }
      const life = m.life[i];
      const fade = Math.min(1, life / MOTE_FADE, (m.span[i] - life) / MOTE_FADE);

      const d = m.depth[i];
      const par = 0.25 + 0.75 * d * settings.dustParallax;

      /* Sway is a sine on the mote's own phase; without it the field drifts in
         straight lines and reads as rain. */
      const sway = Math.sin(now * 0.45 + m.phase[i]) * 0.6 + m.drift[i];
      let x = m.x[i] + (sway * settings.dustDrift * par * dt) + camX * par * 0.35;
      let y = m.y[i] - (settings.dustRise * (0.35 + 0.65 * d) * dt) + camY * par * 0.35;

      /* Wrap with a margin so a mote never pops in at the exact edge. */
      if (y < -6) { y = state.h + 6; }
      else if (y > state.h + 6) y = -6;
      if (x < -6) x += state.w + 12;
      else if (x > state.w + 6) x -= state.w + 12;
      m.x[i] = x; m.y[i] = y;

      const lit = sampleField(x - sx, y - sy);
      if (lit <= gate) continue;
      const t = (lit - gate) / gateSpan;
      /* Squared so the mote fades in near the lamp and not across the pool. */
      const a = t * t * settings.dust * (0.45 + 0.55 * d) * fade *
                (0.75 + 0.25 * Math.sin(now * 1.7 + m.phase[i] * 3));
      if (a <= 0.02) continue;
      let b = (a * ALPHA_BUCKETS) | 0;
      if (b >= ALPHA_BUCKETS) b = ALPHA_BUCKETS - 1;
      const bucket = buckets[b];
      bucket.push(x | 0, y | 0, m.size[i]);
    }

    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    /* Motes are lamp-coloured rather than white: white specks on a dark blue
       deck read as stars, and this is meant to be air, not space. */
    ctx.fillStyle = "#ffeccd";
    for (let b = 0; b < ALPHA_BUCKETS; b++) {
      const bucket = buckets[b];
      if (!bucket.length) continue;
      /* One globalAlpha write per bucket instead of one per mote: state
         changes, not fills, are what make a particle loop slow. */
      ctx.globalAlpha = (b + 0.5) / ALPHA_BUCKETS;
      for (let k = 0; k < bucket.length; k += 3) {
        ctx.fillRect(bucket[k], bucket[k + 1], bucket[k + 2], bucket[k + 2]);
      }
    }
    ctx.restore();
  }

  /* 5. Screen pass: one blit of the baked tone layer, one tiled blit of grain.
        Restraint is the whole brief here — everything strong has already
        happened in the four passes above, and this only has to stop the frame
        looking like a clean render. */
  function screenPass(ctx, scene) {
    if (!usable(scene) || !ctx) return;
    if (!ensure(ctx, scene)) return;

    if (state.toneCanvas) ctx.drawImage(state.toneCanvas, 0, 0);

    if (settings.grain > 0 && state.grainPatterns.length) {
      const now = num(scene.now, 0);
      const step = Math.max(1, Math.round(1000 / Math.max(1, settings.grainFps)));
      const idx = Math.floor(now / step) % state.grainPatterns.length;
      /* Nudge the pattern origin as well as swapping the tile, so the 128px
         lattice never becomes visible as a repeating texture. */
      const jx = (idx * 37) % GRAIN_TILE;
      const jy = (idx * 53) % GRAIN_TILE;
      ctx.save();
      ctx.globalAlpha = clamp01(settings.grain);
      ctx.translate(-jx, -jy);
      ctx.fillStyle = state.grainPatterns[idx];
      ctx.fillRect(jx, jy, state.w, state.h);
      ctx.restore();
    }
  }

  /* ------------------------------------------------------------------ *
   * lifecycle                                                           *
   * ------------------------------------------------------------------ */

  /* `opts` may be flat (`{bloom: 0.4}`) or wrapped (`{settings: {...}}`), and
     may carry width/height. Unknown keys are ignored rather than rejected so a
     caller can pass its own config object straight through. */
  function init(opts) {
    const o = (opts && typeof opts === "object") ? opts : {};
    const src = (o.settings && typeof o.settings === "object") ? o.settings : o;
    for (const key in src) {
      if (Object.prototype.hasOwnProperty.call(settings, key) &&
          typeof src[key] === typeof settings[key]) {
        settings[key] = src[key];
      }
    }
    state.sig = "";
    state.baseSig = "";
    state.sizeSig = "";
    state.bloomSprites.clear();
    blobCanvas = null;
    const w = num(o.width, state.w), h = num(o.height, state.h);
    if (w && h) resize(w, h);
    else if (state.w && state.h) makeMotes();
    return window.Atmosphere;
  }

  /* Every bake is canvas-sized, so a resize throws all of them away. Passes
     also call this themselves if they notice the context's canvas changed
     size, which means a caller that forgets to wire resize still works. */
  function resize(width, height) {
    const w = Math.max(1, Math.round(num(width, 0)));
    const h = Math.max(1, Math.round(num(height, 0)));
    if (!w || !h) return;
    if (w === state.w && h === state.h) return;
    state.w = w;
    state.h = h;
    state.sig = "";
    state.baseSig = "";
    state.sizeSig = "";
    state.contactCanvas = null;
    state.shaftCanvas = null;
    state.bloomCanvas = null;
    state.toneCanvas = null;
    state.lightField = null;
    state.lastOx = null;
    state.lastOy = null;
    makeMotes();
  }

  return { init, resize, lightPass, dustPass, groundShadowPass, screenPass, settings };
})();
