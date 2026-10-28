/* Forge particle preview: a small live window that shows the particles as
   their settings change, before they are applied (the owner, 2026-10-28:
   "make particle effect and its settings have a preview window in some apps
   like settings, wallpapers and wherever it suits").

   One component for every app. Needs shared/forge_particles.js on the page
   (it draws with Particles.preview(), so every kind looks as it does on the
   home screen) and nothing else.

     const pv = ForgeFxPreview.mount(box, { look: () => settings, labels, picture });
     pv.refresh();          // after a setting changed (ForgeFxPreview.refreshAll() does every one)
     pv.picture(url);       // the picture behind it (a wallpaper); none draws a night sky
     pv.stop();             // gone for good

   look is the settings to show (an object or a function giving one; so can
   picture be, read again on every refresh): the
   particle keys below plus accent and wall_light. KEYS is the registry of
   the settings a preview follows: a host puts a preview beside the controls
   that hold any of them (wants(key)), so a new particle setting added here
   shows up in every host's preview by itself. */

const ForgeFxPreview = {
  KEYS: ["particles", "particles_shown", "particle_amount", "particle_size", "particle_speed", "wallpaper_particles"],
  all: new Set(),
  wants(key) { return this.KEYS.includes(key); },
  style() {
    if (document.getElementById("forge-fxp-style")) return;
    const s = document.createElement("style");
    s.id = "forge-fxp-style";
    s.textContent = `
.forge-fxp { position: relative; margin: 0; height: 132px; border-radius: 12px; overflow: hidden; isolation: isolate;
  background: radial-gradient(120% 90% at 80% 0%, color-mix(in srgb, var(--accent, #8ab4ff) 35%, transparent), transparent 60%),
    radial-gradient(90% 80% at 0% 100%, color-mix(in srgb, #ff8fc7 30%, transparent), transparent 65%),
    linear-gradient(180deg, #141a33, #0a0d1c);
  background-size: cover; background-position: center;
  border: 1px solid color-mix(in srgb, var(--accent, #8ab4ff) 40%, transparent);
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.04), 0 6px 18px rgba(0,0,0,.25); }
.forge-fxp .fxp-pic { position: absolute; inset: 0; z-index: 0; background-size: cover; background-position: center; }
.forge-fxp.pic .fxp-pic::after { content: ""; position: absolute; inset: 0;
  background: linear-gradient(180deg, rgba(8,10,24,.05), rgba(8,10,24,.45)); }
.forge-fxp canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; z-index: 1; cursor: crosshair; }
.forge-fxp figcaption { position: absolute; left: 8px; right: 8px; bottom: 7px; z-index: 2; display: flex; gap: 6px; align-items: center;
  pointer-events: none; font-size: 12px; color: #fff; text-shadow: 0 1px 3px rgba(0,0,0,.7); }
.forge-fxp .fxp-live { padding: 2px 8px; border-radius: 999px; font-weight: 700; letter-spacing: .03em;
  background: color-mix(in srgb, var(--accent, #8ab4ff) 75%, #000 10%); color: var(--on-accent, #0b1220); text-shadow: none; }
.forge-fxp .fxp-kind { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.forge-fxp .fxp-hint { opacity: .8; white-space: nowrap; }
`;
    document.head.append(s);
  },
  mount(host, opts = {}) {
    this.style();
    const fig = document.createElement("figure");
    fig.className = "forge-fxp";
    fig.setAttribute("aria-label", "Particle preview");
    const canvas = document.createElement("canvas"), cap = document.createElement("figcaption");
    const live = document.createElement("span"), kind = document.createElement("span"), hint = document.createElement("span");
    live.className = "fxp-live"; live.textContent = "Preview";
    kind.className = "fxp-kind";
    hint.className = "fxp-hint"; hint.textContent = opts.hint ?? "click for sparks";
    cap.append(live, kind, hint);
    const pic = document.createElement("div");
    pic.className = "fxp-pic";
    fig.append(pic, canvas, cap);
    host.append(fig);
    const read = () => (typeof opts.look === "function" ? opts.look() : opts.look) || {};
    // the preview shows the kind even while Forge's animations are off or
    // Alt+P hides the particles, and says so (they would show nothing at all)
    const drawer = Particles.preview(canvas, () => ({ ...read(), animations: true, particles_shown: true }));
    let said = opts.hint ?? "click for sparks";
    const pv = {
      el: fig, canvas, drawer,
      refresh() {
        drawer.apply();
        const level = drawer.level, labels = (typeof opts.labels === "function" ? opts.labels() : opts.labels) || {};
        const name = level === "off" ? "Particles are off" : String(labels[level] || level).replace(/^\w/, (c) => c.toUpperCase());
        const look = read(), own = look.wallpaper_particles;
        if (typeof opts.picture === "function") pv.picture(opts.picture());
        const why = level === "off" ? (look.particles === "off" ? "" : "off for this wallpaper")
          : own && own !== "off" && look.particles !== "off" && own !== look.particles && level === own ? "this wallpaper's own pick wins (Wallpapers)"
          : look.animations === false ? "animations are off, so they only move here"
          : look.particles_shown === false ? "hidden now (Alt+P)" : said;
        hint.textContent = why;
        kind.textContent = name;
        fig.dataset.kind = level;
      },
      // a picture that fails to load leaves the night sky under it showing
      picture(url) {
        const css = !url ? "" : /^(url|linear|radial)/.test(url) ? url : `url("${String(url).replace(/"/g, "%22")}")`;
        pic.style.backgroundImage = css;
        fig.classList.toggle("pic", !!css && css !== "none");
      },
      hint(text) { said = text; pv.refresh(); },
      stop() { drawer.stop(); ForgeFxPreview.all.delete(pv); fig.remove(); },
    };
    if (opts.picture && typeof opts.picture !== "function") pv.picture(opts.picture);
    this.all.add(pv);
    pv.refresh();
    return pv;
  },
  refreshAll() {
    for (const pv of this.all) {
      if (!pv.el.isConnected) { pv.drawer.stop(); this.all.delete(pv); } else pv.refresh();
    }
  },
};
if (typeof window !== "undefined") window.ForgeFxPreview = ForgeFxPreview;
