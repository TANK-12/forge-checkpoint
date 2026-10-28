/* Real-depth 2.5D wallpaper (the owner, 2026-09-29: "make the 2.5d way cooler
   ... more layers or even actually be 3d").

   One WebGL canvas inside the hub's #wall draws the picture bent by its depth
   map (shared/forge_layers.py's <key>-depth.png, light = near). For every
   pixel the shader walks a short ray through the depth map, near to far, and
   shows the first surface the ray meets. Nearer parts slide further than far
   ones and cover what is behind them, as in a 3D photo, so the picture has as
   many layers as it has depths instead of two.

   The cut-out (when forge_layers found a subject) stays as its own layer on
   top, with the particles between it and this canvas: a second canvas inside
   the hub's #wall-fg that bends the cut-out by the same depth map, so it sits
   on its own pixels in the picture at every view (task 275: drawn as a flat
   card it was not zoomed or bent with the picture and slid off it). The view
   pivots on the subject's own depth: the world swings round the character.

   It draws only while something moves (the pointer, the slow drift, the beat)
   and stops asking for frames once the view has settled. Its frames go
   through requestAnimationFrame, so Forge's frame-rate cap and its rest while
   hidden apply. Without WebGL, or when the picture cannot be read into it,
   mount() or load() fails and the hub keeps the two-layer look.

   API: mount(parent, cutParent) -> bool, load(image, depth, cutout, plate)
   -> Promise, cut (whether the cut-out canvas is showing a cut-out),
   set({ strength, drift }), point(x, y) with -1..1, beat(k), stop(). */
(function (root) {
  const VS = "attribute vec2 p; varying vec2 uv;"
    + "void main() { uv = vec2(p.x * 0.5 + 0.5, 0.5 - p.y * 0.5); gl_Position = vec4(p, 0.0, 1.0); }";
  // off: how far the view has moved, in picture widths; fit: the part of the
  // picture on screen (cover fit, less the margin the movement needs)
  //
  // Two layers (task 327; shared/forge_layers.py split_depth). The depth
  // picture holds, in r, the near things' depth (a pole, a wire, a person,
  // spread a few pixels round them, 0 elsewhere), in g the scene behind them
  // (filled in under them and smoothed so it never folds) and in b how much
  // of each pixel is a near thing. The scene is the plate (the picture with
  // the near things filled in), bent by g: s = at(t, g(s)) settles in a few
  // rounds and leaves no gap. The near things are found by a ray walked near
  // to far through r, its hit halved REFINE times onto the surface; a hit on
  // the side of one (where r climbs WALL within two texels, and faster than
  // the ray falls there) is not a surface (drawing it streaked the side's
  // last pixels across the gap, tasks 275 and 327): the ray passes it, and if the far side is a near thing too (an arm
  // before the body) that one is mirrored in. Each hit is laid over the last
  // by its b, and the scene shows through what is left.
  //
  // MARCH is shared by the picture and the cut-out shader so the
  // cut-out lands on exactly the same pixels; LAYER(AT, OF), a near thing
  // at AT covering OF of the pixel, is each shader's own.
  const MARCH = `
varying vec2 uv;
uniform sampler2D dep;
uniform vec2 off;
uniform vec4 fit;
uniform float focus;
uniform float steps;
uniform vec2 texel;
const int STEPS = 16;
const int REFINE = 5;
const float WALL = 0.06;
const float RIM = 0.05; // a near thing's share from which the scene is the plate
vec2 at(vec2 t, float z) { return t - off * (z - focus); }
vec2 inside(vec2 s) { return clamp(s, vec2(0.001), vec2(0.999)); }
vec3 depthAt(vec2 s) { return texture2D(dep, inside(s)).rgb; }
// the scene behind: where it puts its own pixel under this one
vec2 sceneAt(vec2 t) {
  vec2 s = t;
  for (int i = 0; i < 6; i++) s = at(t, depthAt(s).g);
  return s;
}
// what is still seen through the layers laid so far (1 = all of it)
float through = 1.0;
vec4 laid = vec4(0.0);
void walk(vec2 t) {
  vec2 back = -normalize(off + vec2(1e-6)) * texel * 2.0;
  // how far the ray itself falls over those two texels: a rim that climbs
  // less than that is a surface it meets from above (at rest, every rim)
  float fall = length(back) / max(length(off), 1e-6);
  float pz = 1.0, pf = -1.0;
  for (int i = 1; i <= STEPS; i++) {
    if (float(i) > steps || through < 0.02) break;
    float z = 1.0 - float(i) / steps;
    float f = depthAt(at(t, z)).r - z;
    if (f >= 0.0 && pf < 0.0) {
      float hi = pz, lo = z;
      for (int j = 0; j < REFINE; j++) {
        float m = 0.5 * (hi + lo);
        if (depthAt(at(t, m)).r >= m) lo = m; else hi = m;
      }
      vec2 h = at(t, lo);
      vec3 d = depthAt(h), e = depthAt(h + back);
      if (d.r - e.r < max(WALL, fall)) {
        LAYER(h, d.b);
      } else if (e.b > 0.5) {
        // between two near things: the farther one mirrored into the gap
        vec2 m = inside(2.0 * h - at(t, e.r));
        LAYER(m, depthAt(m).b);
      }
    }
    pz = z; pf = f;
  }
}
`;
  const HEAD = `#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
`;
  const FS = HEAD + `uniform sampler2D img;
uniform sampler2D plate;
vec3 behind(vec2 s);
#define LAYER(AT, OF) { vec2 a = inside(AT); laid.rgb += through * (texture2D(img, a).rgb - (1.0 - (OF)) * behind(a)); through *= 1.0 - (OF); }
` + MARCH + `
// the scene at s: the plate wherever a near thing covers any of the pixel.
// A near thing's own share of a pixel is the picture less the scene's
// share (LAYER above), so its soft rim moves with it and leaves no
// outline, and at rest the two add up to the picture exactly.
vec3 behind(vec2 s) {
  return mix(texture2D(img, s).rgb, texture2D(plate, s).rgb, smoothstep(0.0, RIM, depthAt(s).b));
}
void main() {
  vec2 t = uv * fit.xy + fit.zw;
  walk(t);
  gl_FragColor = vec4(laid.rgb + through * behind(inside(sceneAt(t))), 1.0);
}`;
  // The cut-out, laid by the same walk: where the walk shows a near thing,
  // the cut-out's own pixel there; where it shows the scene, the cut-out's
  // pixel only off the near things (on them, the scene there is filled in,
  // so the cut-out would show twice). Not premultiplied: the colour is
  // divided back out.
  const CUT_FS = HEAD + `uniform sampler2D img;
#define LAYER(AT, OF) { vec4 c = texture2D(img, inside(AT)); laid += through * (OF) * vec4(c.rgb * c.a, c.a); through *= 1.0 - (OF); }
` + MARCH + `
void main() {
  vec2 t = uv * fit.xy + fit.zw;
  walk(t);
  vec2 s = sceneAt(t);
  vec4 c = texture2D(img, inside(s));
  float open = through * (1.0 - smoothstep(0.0, RIM, depthAt(s).b)) * c.a;
  vec4 o = laid + vec4(c.rgb * open, open);
  gl_FragColor = vec4(o.rgb / max(o.a, 1e-4), o.a);
}`;
  const MAX_SHIFT = 0.022; // picture widths per step of 2.5D depth
  // The slow drift alone moves the nearest layer under a pixel a frame at 24
  // frames a second, and every frame is a full-screen ray walk (task 56); the
  // pointer and the beat still draw at the full rate.
  // v2 (2026-10-07, the owner: "a bit too heavy on the GPU"): 20 a second for
  // the drift, a ray walk of 10 steps while only drifting (16 while the
  // pointer or the beat moves it, 8 on the reduced tier), and the canvas
  // drawn at 3/4 of the screen (1/2 reduced) and stretched: the picture is
  // soft, and that is about half the pixels.
  const DRIFT_FPS = 20;
  const STEPS_MOVING = 16, STEPS_DRIFT = 10, STEPS_REDUCED = 8;
  const RES = { full: 0.75, reduced: 0.5 };
  // the shared power tier (shared/forge_power.js, v2 2026-10-07): reduced
  // drifts at half that rate, paused draws nothing until it changes
  // set({ tier }) from the host, else the page theme's power_tier
  let tierName = "";
  const tier = () => String(tierName || (typeof window === "object" && window.FORGE_THEME && window.FORGE_THEME.power_tier) || "full").split(":")[0].trim();

  const D = {
    canvas: null, gl: null, prog: null, u: {}, tex: {}, size: [1, 1], ready: false, focus: 0.5,
    // the cut-out's canvas: { canvas, gl, u, tex }, and whether it has a cut-out
    fg: null, cut: false, fgFailed: false,
    strength: 1, drift: () => false, x: 0, y: 0, tx: 0, ty: 0, k: 0, raf: 0, timer: 0, t0: 0, token: 0,
    // s: the strength shown, eased toward the setting; behind an open app
    // (body.in-app) toward 0, so the picture goes back to a plain cover fit
    // instead of the zoom the movement margin needs, then it stops drawing
    s: 1, away: false,

    // one full-screen quad drawn with this fragment shader; null when the
    // context or the shader cannot be had
    context(canvas, fs, names, alpha) {
      const gl = canvas.getContext("webgl", { alpha, antialias: false, premultipliedAlpha: false, powerPreference: "low-power" });
      if (!gl) return null;
      const sh = (type, src) => {
        const s = gl.createShader(type);
        gl.shaderSource(s, src);
        gl.compileShader(s);
        return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null;
      };
      // a failed try gives its context back rather than hold it
      const give = () => { const x = gl.getExtension("WEBGL_lose_context"); if (x) x.loseContext(); return null; };
      const vs = sh(gl.VERTEX_SHADER, VS), f = sh(gl.FRAGMENT_SHADER, fs);
      if (!vs || !f) return give();
      const prog = gl.createProgram();
      gl.attachShader(prog, vs);
      gl.attachShader(prog, f);
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return give();
      gl.useProgram(prog);
      const buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      const at = gl.getAttribLocation(prog, "p");
      gl.enableVertexAttribArray(at);
      gl.vertexAttribPointer(at, 2, gl.FLOAT, false, 0, 0);
      const u = {};
      for (const n of names) u[n] = gl.getUniformLocation(prog, n);
      gl.uniform1i(u[names[0]], 0);
      gl.uniform1i(u.dep, 1);
      return { canvas, gl, prog, u, tex: {} };
    },

    mount(parent, cutParent) {
      if (this.gl) {
        if (this.canvas.parentNode !== parent) parent.appendChild(this.canvas);
        this.canvas.hidden = false;
        this.mountCut(cutParent);
        return true;
      }
      const c = document.createElement("canvas");
      c.className = "depth";
      const ctx = this.context(c, FS, ["img", "dep", "plate", "texel", "off", "fit", "focus", "steps"], false);
      if (!ctx) return false;
      ctx.gl.uniform1i(ctx.u.plate, 2);
      Object.assign(this, { gl: ctx.gl, prog: ctx.prog, u: ctx.u, tex: ctx.tex });
      c.addEventListener("webglcontextlost", (e) => { e.preventDefault(); this.ready = false; });
      document.addEventListener("forge-power", () => this.wake());
      // an app opened or closed in the hub: ease the depth out or back in
      const watch = () => {
        const away = document.body.classList.contains("in-app");
        if (away !== this.away) { this.away = away; this.wake(); }
      };
      new MutationObserver(watch).observe(document.body, { attributes: true, attributeFilter: ["class"] });
      watch();
      this.canvas = c;
      parent.appendChild(c);
      this.mountCut(cutParent);
      return true;
    },
    // the cut-out's own canvas; without it (no second WebGL context) the hub
    // hides the cut-out in real depth rather than show it off the picture
    mountCut(parent) {
      if (!parent || this.fgFailed) return;
      if (!this.fg) {
        const c = document.createElement("canvas");
        c.className = "depth-cut";
        const ctx = this.context(c, CUT_FS, ["img", "dep", "texel", "off", "fit", "focus", "steps"], true);
        // tried once: each failed try would hold another WebGL context
        if (!ctx) { this.fgFailed = true; return; }
        c.addEventListener("webglcontextlost", (e) => {
          e.preventDefault();
          this.cut = false;
          c.hidden = true;
          document.body.classList.remove("depth-cut");
        });
        this.fg = ctx;
      }
      if (this.fg.canvas.parentNode !== parent) parent.appendChild(this.fg.canvas);
      this.fg.canvas.hidden = false;
    },

    picture(url) {
      return new Promise((ok, bad) => {
        const im = new Image();
        im.decoding = "async";
        im.onload = () => ok(im);
        im.onerror = () => bad(new Error(`could not load ${url}`));
        im.src = url;
      });
    },
    upload(unit, im, ctx = this, format = ctx.gl.RGB) {
      const gl = ctx.gl;
      const tex = ctx.tex[unit] || gl.createTexture();
      ctx.tex[unit] = tex;
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texImage2D(gl.TEXTURE_2D, 0, format, format, gl.UNSIGNED_BYTE, im); // throws on a picture it may not read
    },
    // the depth the view pivots on: the cut-out's own (its alpha-weighted mean
    // depth), or a third of the way in for a landscape with no subject
    pivot(depthIm, cutIm) {
      if (!cutIm) return 0.35;
      const n = 96, c = document.createElement("canvas");
      c.width = c.height = n;
      const x = c.getContext("2d", { willReadFrequently: true });
      x.drawImage(depthIm, 0, 0, n, n);
      const d = x.getImageData(0, 0, n, n).data;
      x.clearRect(0, 0, n, n);
      x.drawImage(cutIm, 0, 0, n, n);
      const a = x.getImageData(0, 0, n, n).data;
      let sum = 0, weight = 0;
      for (let i = 0; i < d.length; i += 4) { sum += (d[i] / 255) * a[i + 3]; weight += a[i + 3]; }
      return weight > 0 ? sum / weight : 0.35;
    },
    // the picture, its two-layer depth and its plate are needed (all made by
    // forge_layers); the cut-out only when it found a subject
    async load(image, depth, cutout, plate) {
      const token = ++this.token;
      this.ready = false;
      const maybe = (url) => (url ? this.picture(url).catch(() => null) : null);
      const [im, dm, cut, pl] = await Promise.all([this.picture(image), this.picture(depth), maybe(cutout), this.picture(plate)]);
      if (token !== this.token || !this.gl) return false;
      this.upload(0, im);
      this.upload(1, dm);
      this.upload(2, pl);
      const texel = [1 / (dm.naturalWidth || 1), 1 / (dm.naturalHeight || 1)];
      this.cut = false;
      if (cut && this.fg) {
        try {
          this.upload(0, cut, this.fg, this.fg.gl.RGBA);
          this.upload(1, dm, this.fg);
          this.fg.gl.uniform2f(this.fg.u.texel, ...texel);
          this.cut = true;
        } catch (e) { /* the cut-out stays hidden */ }
      }
      this.gl.useProgram(this.prog);
      this.gl.uniform2f(this.u.texel, ...texel);
      this.size = [im.naturalWidth || 1, im.naturalHeight || 1];
      this.focus = this.pivot(dm, cut);
      this.ready = true;
      this.wake();
      return true;
    },

    set(o) {
      if ("strength" in o) {
        this.strength = Math.max(0, Number(o.strength) || 0);
        if (!this.ready) this.s = this.strength;
      }
      if ("tier" in o) tierName = ["full", "reduced", "paused"].includes(o.tier) ? o.tier : "";
      if ("drift" in o) this.drift = typeof o.drift === "function" ? o.drift : () => !!o.drift;
      this.wake();
    },
    point(x, y) { this.tx = x; this.ty = y; this.wake(); },
    beat(k) { this.k = Math.max(this.k, Number(k) || 0); if (this.k > 0.01) this.wake(); },
    stop() {
      cancelAnimationFrame(this.raf);
      clearTimeout(this.timer);
      this.raf = this.timer = 0;
      this.token++;
      this.ready = false;
      if (this.canvas) this.canvas.hidden = true;
      if (this.fg) this.fg.canvas.hidden = true;
      this.cut = false;
    },
    wake() {
      if (this.raf || !this.ready || tier() === "paused") return;
      clearTimeout(this.timer);
      this.timer = 0;
      this.raf = requestAnimationFrame((t) => this.frame(t));
    },

    frame(t) {
      this.raf = 0;
      if (!this.ready || !this.gl || tier() === "paused") return;
      const goal = this.away ? 0 : this.strength;
      this.s += (goal - this.s) * 0.12;
      if (Math.abs(goal - this.s) < 0.003) this.s = goal;
      const drifting = !this.away && this.strength > 0 && this.drift();
      this.x += (this.tx - this.x) * 0.1;
      this.y += (this.ty - this.y) * 0.1;
      this.k *= 0.88;
      let ox = this.x, oy = this.y;
      if (drifting) {
        const s = (t || 0) / 1000;
        ox += Math.sin(s * 0.21) * 0.55 + Math.sin(s * 0.047) * 0.25;
        oy += Math.cos(s * 0.17) * 0.35;
      }
      const settled = Math.abs(this.tx - this.x) < 0.002 && Math.abs(this.ty - this.y) < 0.002 && this.k < 0.01 && this.s === goal;
      this.draw(ox, oy, settled && drifting ? STEPS_DRIFT : STEPS_MOVING);
      if (!settled) this.raf = requestAnimationFrame((n) => this.frame(n));
      else if (drifting) {
        this.timer = setTimeout(() => {
          this.timer = 0;
          this.raf = requestAnimationFrame((n) => this.frame(n));
        }, 1000 / (tier() === "reduced" ? DRIFT_FPS / 2 : DRIFT_FPS) - 4);
      }
    },
    draw(ox, oy, steps = STEPS_MOVING) {
      const gl = this.gl, c = this.canvas, reduced = tier() === "reduced";
      // a share of the screen's pixels, never above 1920 across: the canvas
      // is stretched to the screen by its CSS size
      const scale = Math.min(reduced ? RES.reduced : RES.full, 1920 / Math.max(1, c.clientWidth));
      const w = Math.max(1, Math.round(c.clientWidth * scale)), h = Math.max(1, Math.round(c.clientHeight * scale));
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
      gl.viewport(0, 0, w, h);
      const shift = MAX_SHIFT * this.s * (1 + this.k * 0.8);
      // cover fit, then leave the margin the shift needs so no edge shows
      const [iw, ih] = this.size;
      const cover = Math.max(w / iw, h / ih);
      const margin = 1 - Math.min(0.3, shift * 2.2);
      const fx = (w / (iw * cover)) * margin, fy = (h / (ih * cover)) * margin;
      gl.uniform4f(this.u.fit, fx, fy, (1 - fx) / 2, (1 - fy) / 2);
      gl.uniform2f(this.u.off, -ox * shift, -oy * shift * (iw / ih));
      gl.uniform1f(this.u.focus, this.focus);
      const walk = reduced ? Math.min(steps, STEPS_REDUCED) : steps;
      gl.uniform1f(this.u.steps, walk);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      if (!this.cut) return;
      // the cut-out: the same view, at the same size, so it sits on the picture
      const f = this.fg, fc = f.canvas, g = f.gl;
      if (fc.width !== w || fc.height !== h) { fc.width = w; fc.height = h; }
      g.viewport(0, 0, w, h);
      g.uniform4f(f.u.fit, fx, fy, (1 - fx) / 2, (1 - fy) / 2);
      g.uniform2f(f.u.off, -ox * shift, -oy * shift * (iw / ih));
      g.uniform1f(f.u.focus, this.focus);
      g.uniform1f(f.u.steps, walk);
      g.drawArrays(g.TRIANGLE_STRIP, 0, 4);
    },
  };
  if (typeof module === "object" && module.exports) module.exports = D;
  else root.ForgeDepth = D;
})(this);
