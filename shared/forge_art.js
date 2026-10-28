/* The Forge sprite library, browser side.
 *
 * Turns palette-indexed character rows into canvases you can blit. Baking
 * happens once at boot: every frame of every sprite becomes an offscreen
 * canvas, so the render loop only ever calls drawImage. Because colour lives
 * in a separate palette, re-skinning the whole world -- season, night,
 * weather, a different biome -- is one rebake of a few hundred small canvases,
 * which costs milliseconds, rather than a second copy of every sprite.
 *
 * Shared by PixelForge (the editor) and Emberfield (the game); neither owns
 * the format.
 */
(function (global) {
  "use strict";

  const TRANSPARENT = ".";

  function hexToRGB(hex) {
    const n = parseInt(String(hex).slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  function makeCanvas(w, h) {
    // OffscreenCanvas where available, but WebKitGTK is the target and a
    // detached <canvas> works everywhere, so prefer the boring option.
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    return c;
  }

  /* One frame -> one canvas. Built through ImageData so a 16x16 tile costs a
   * single putImageData rather than 256 fillRect calls. */
  function bakeFrame(rows, w, h, lut) {
    const canvas = makeCanvas(w, h);
    const ctx = canvas.getContext("2d");
    const img = ctx.createImageData(w, h);
    const data = img.data;
    for (let y = 0; y < h; y++) {
      const row = rows[y] || "";
      for (let x = 0; x < w; x++) {
        const ch = row[x];
        const i = (y * w + x) * 4;
        if (!ch || ch === TRANSPARENT) continue;
        const rgb = lut[ch];
        if (!rgb) continue; // unknown key renders as a gap, never as a crash
        data[i] = rgb[0];
        data[i + 1] = rgb[1];
        data[i + 2] = rgb[2];
        data[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return canvas;
  }

  class Atlas {
    constructor(library, paletteId) {
      this.library = library;
      this.paletteId = paletteId;
      this.sprites = new Map(); // id -> {w,h,frames:[canvas],durations:[ms],total}
      this.index = new Map(); // bare name -> "pack/name", for convenience
      this.rebake(paletteId);
    }

    get palette() {
      return this.library.palettes[this.paletteId] || { colors: {}, roles: {} };
    }

    /** A named semantic colour, e.g. role("grass_mid"). This is what lets the
     * procedural nature layer draw in colours that belong to the same palette
     * as the hand-authored tiles instead of hardcoding greens. */
    role(name, fallback) {
      const p = this.palette;
      const key = (p.roles || {})[name];
      const hex = key ? (p.colors || {})[key] : null;
      return hex || fallback || "#ff00ff";
    }

    color(key, fallback) {
      return (this.palette.colors || {})[key] || fallback || "#ff00ff";
    }

    rebake(paletteId) {
      if (paletteId) this.paletteId = paletteId;
      const colors = this.palette.colors || {};
      const lut = Object.create(null);
      for (const key in colors) lut[key] = hexToRGB(colors[key]);

      this.sprites.clear();
      this.index.clear();
      const packs = this.library.packs || {};
      for (const packId in packs) {
        const pack = packs[packId];
        const sprites = pack.sprites || {};
        for (const name in sprites) {
          const s = sprites[name];
          const frames = (s.frames || []).map((f) => bakeFrame(f.rows || [], s.w, s.h, lut));
          const durations = (s.frames || []).map((f) => Math.max(0, f.ms | 0));
          const total = durations.reduce((a, b) => a + b, 0);
          const full = packId + "/" + name;
          this.sprites.set(full, {
            w: s.w,
            h: s.h,
            frames,
            durations,
            total,
            tags: s.tags || [],
            pack: packId,
            name,
          });
          if (!this.index.has(name)) this.index.set(name, full);
        }
      }
      return this;
    }

    /** Accepts "pack/name" or a bare "name". Bare names are unambiguous in
     * practice and keep game code readable; the qualified form is there for
     * when two packs deliberately collide (a reskin). */
    get(id) {
      return this.sprites.get(id) || this.sprites.get(this.index.get(id)) || null;
    }

    has(id) {
      return !!this.get(id);
    }

    ids() {
      return Array.from(this.sprites.keys());
    }

    /** The canvas for a sprite at a point in time. Sprites with a single frame,
     * or with every duration zero, are static and ignore `timeMs`. */
    frame(id, timeMs) {
      const s = this.get(id);
      if (!s || !s.frames.length) return null;
      if (s.frames.length === 1 || !s.total) return s.frames[0];
      let t = ((timeMs || 0) % s.total + s.total) % s.total;
      for (let i = 0; i < s.frames.length; i++) {
        t -= s.durations[i];
        if (t < 0) return s.frames[i];
      }
      return s.frames[s.frames.length - 1];
    }

    frameIndex(id, timeMs) {
      const s = this.get(id);
      if (!s || s.frames.length < 2 || !s.total) return 0;
      let t = ((timeMs || 0) % s.total + s.total) % s.total;
      for (let i = 0; i < s.frames.length; i++) {
        t -= s.durations[i];
        if (t < 0) return i;
      }
      return 0;
    }

    /** Blit at integer pixels. Non-integer destinations make pixel art shimmer
     * as the camera moves, which is the single most common way a tile renderer
     * ends up looking wrong. */
    draw(ctx, id, x, y, timeMs, scale) {
      const canvas = this.frame(id, timeMs);
      if (!canvas) return false;
      const k = scale || 1;
      ctx.drawImage(
        canvas,
        Math.round(x),
        Math.round(y),
        Math.round(canvas.width * k),
        Math.round(canvas.height * k)
      );
      return true;
    }
  }

  const ForgeArt = {
    TRANSPARENT,
    Atlas,
    hexToRGB,

    async load(url) {
      // a backend that never answers fails after 20 s instead of hanging boot
      const res = await fetch(url || "/api/art/library", { signal: AbortSignal.timeout(20000) });
      if (!res.ok) throw new Error("could not load the art library (" + res.status + ")");
      return res.json();
    },

    atlas(library, paletteId) {
      return new Atlas(library, paletteId);
    },

    /** Crisp scaling. Every canvas drawing pixel art needs this, and forgetting
     * it is why a tile renderer comes out blurry. */
    crisp(ctx) {
      ctx.imageSmoothingEnabled = false;
      ctx.mozImageSmoothingEnabled = false;
      ctx.webkitImageSmoothingEnabled = false;
      return ctx;
    },
  };

  global.ForgeArt = ForgeArt;
})(window);
