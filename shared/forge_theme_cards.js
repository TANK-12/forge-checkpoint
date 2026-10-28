/* ForgeThemeCards: the picker cards for themes and home layouts, shared by
 * the hub's theme switcher (Alt+T) and Settings > Themes, so both draw a
 * theme the same way. A plain script (no modules).
 *
 *   ForgeThemeCards.theme(preview, {current})  -> <button class="ftc ftc-theme">
 *   ForgeThemeCards.layout(layout, {current})  -> <button class="ftc ftc-layout">
 *
 * `preview` is one entry of the theme's "themes" list (shared/forge_themes.py
 * preview()): id, label, about, tags, mode, colours, wall (a picture link or
 * ""), radius, font_stack, live, companion, mine. `layout` is one entry of
 * "layouts": id, label, about, home (the layout's home rules). Each card is a
 * small drawing of Forge in that theme or layout, never a screenshot, so a
 * new theme file gets a card with nothing else to make.
 */
(function () {
  "use strict";
  if (window.ForgeThemeCards) return;
  var HEX = /^#[0-9a-f]{6}$/i;

  var CSS = [
    ".ftc { position: relative; display: flex; flex-direction: column; gap: 0; padding: 0; margin: 0; min-width: 0;",
    "  border-radius: 14px; overflow: hidden; cursor: pointer; text-align: left; font: inherit; color: var(--text, #e7e9ee);",
    "  border: 1px solid var(--border, #2a2f3a); background: var(--panel, #171a21);",
    "  transition: transform 140ms ease-out, box-shadow 140ms ease-out, border-color 140ms; }",
    ".ftc:hover, .ftc:focus-visible, .ftc.focus { outline: none; transform: translateY(-3px); border-color: var(--accent, #6ea8fe);",
    "  box-shadow: 0 0 0 2px var(--accent, #6ea8fe), 0 14px 30px rgba(0, 0, 0, .35); }",
    ".ftc.ftc-current { border-color: var(--accent, #6ea8fe); box-shadow: 0 0 0 2px var(--accent, #6ea8fe); }",
    ".ftc-shot { position: relative; aspect-ratio: 16 / 10; overflow: hidden; background: var(--t-bg) center / cover no-repeat; }",
    ".ftc-shot::after { content: \"\"; position: absolute; inset: 0; pointer-events: none;",
    "  background: linear-gradient(180deg, transparent 55%, rgba(0, 0, 0, .18)); }",
    ".ftc-bar { position: absolute; left: 5%; right: 5%; top: 5%; height: 7%; border-radius: 99px;",
    "  background: var(--t-panel); opacity: .9; display: flex; align-items: center; gap: 4%; padding: 0 3%; }",
    ".ftc-bar i { display: block; width: 6%; height: 40%; border-radius: 99px; background: var(--t-muted); opacity: .7; }",
    ".ftc-bar i:first-child { background: var(--t-accent); opacity: 1; width: 9%; }",
    ".ftc-clock { position: absolute; left: 8%; top: 19%; font-size: clamp(14px, 2.3vw, 26px); font-weight: 300;",
    "  letter-spacing: -.03em; color: var(--t-text); font-family: var(--t-font, inherit); text-shadow: 0 2px 10px rgba(0, 0, 0, .25); }",
    ".ftc-clock small { display: block; font-size: 38%; letter-spacing: 0; color: var(--t-accent); font-weight: 600; margin-top: 2px; }",
    ".ftc-tiles { position: absolute; left: 8%; right: 8%; bottom: 22%; display: grid; grid-template-columns: repeat(4, 1fr); gap: 4%; }",
    ".ftc-tiles i { display: flex; align-items: center; gap: 12%; aspect-ratio: 2.4 / 1; padding: 0 9%;",
    "  border-radius: var(--t-radius, 6px); background: var(--t-panel); border: 1px solid var(--t-border); }",
    ".ftc-tiles i::before { content: \"\"; flex: none; width: 26%; aspect-ratio: 1; border-radius: 28%; background: var(--t-accent); }",
    ".ftc-tiles i::after { content: \"\"; flex: 1; height: 16%; border-radius: 99px; background: var(--t-muted); opacity: .6; }",
    ".ftc-dock { position: absolute; left: 32%; right: 32%; bottom: 5%; height: 9%; border-radius: 99px;",
    "  background: var(--t-panel); border: 1px solid var(--t-border); opacity: .92; }",
    ".ftc-badges { position: absolute; right: 4%; top: 16%; display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }",
    ".ftc-badges span { font-size: 10.5px; font-weight: 650; padding: 2px 7px; border-radius: 99px;",
    "  color: var(--t-text); background: color-mix(in srgb, var(--t-panel) 85%, transparent); border: 1px solid var(--t-border); }",
    ".ftc-foot { display: flex; flex-direction: column; gap: 3px; padding: 9px 11px 11px; min-width: 0; }",
    ".ftc-name { display: flex; align-items: center; gap: 8px; font-weight: 650; font-size: 14px; }",
    ".ftc-name .ftc-dot { width: 10px; height: 10px; border-radius: 50%; flex: none; background: var(--t-accent);",
    "  box-shadow: 0 0 0 2px color-mix(in srgb, var(--t-accent) 30%, transparent); }",
    ".ftc-name em { margin-left: auto; font-style: normal; font-size: 11px; font-weight: 600; color: var(--accent, #6ea8fe); }",
    ".ftc-about { font-size: 12px; line-height: 1.35; color: var(--muted, #8b93a3); display: -webkit-box;",
    "  -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }",
    /* layouts: a sketch of the home screen in the page's own colours */
    ".ftc-plan { position: relative; aspect-ratio: 16 / 10; padding: 7% 8%; display: flex; flex-direction: column; gap: 5%;",
    "  background: linear-gradient(145deg, color-mix(in srgb, var(--accent, #6ea8fe) 16%, var(--panel-2, #1e222b)), var(--panel-2, #1e222b)); }",
    ".ftc-plan.center { align-items: center; }",
    ".ftc-plan .p-hero { display: flex; justify-content: space-between; align-items: flex-end; width: 100%; gap: 6%; }",
    ".ftc-plan.center .p-hero { flex-direction: column; align-items: center; gap: 8px; }",
    ".ftc-plan .p-clock { width: 34%; height: 26px; border-radius: 6px; background: color-mix(in srgb, var(--text, #e7e9ee) 70%, transparent); }",
    ".ftc-plan .p-clock.small { width: 20%; height: 12px; }",
    ".ftc-plan .p-search { width: 42%; height: 10px; border-radius: 99px; border: 1px solid var(--border, #2a2f3a);",
    "  background: color-mix(in srgb, var(--panel, #171a21) 80%, transparent); }",
    ".ftc-plan.center .p-search { width: 56%; }",
    ".ftc-plan .p-head { width: 22%; height: 6px; border-radius: 99px; background: var(--accent, #6ea8fe); opacity: .8; }",
    ".ftc-plan .p-row { display: grid; grid-template-columns: repeat(var(--n, 4), 1fr); gap: 4px; width: 100%; }",
    ".ftc-plan .p-row i { display: block; height: var(--h, 14px); border-radius: 4px; background: color-mix(in srgb, var(--text, #e7e9ee) 22%, transparent); }",
    ".ftc-plan .p-row.icons { gap: 6px; }",
    ".ftc-plan .p-row.icons i { width: 62%; height: auto; aspect-ratio: 1; margin: 0 auto; border-radius: 30%; background: color-mix(in srgb, var(--accent, #6ea8fe) 45%, transparent); }",
    ".ftc-plan .p-row.recent i { background: color-mix(in srgb, var(--accent, #6ea8fe) 35%, transparent); }",
    ".ftc-plan .p-more { width: 14%; height: 6px; border-radius: 99px; border: 1px solid var(--border, #2a2f3a); margin-top: -2%; }",
    ".ftc-plan .p-empty { flex: 1; width: 100%; border: 1px dashed color-mix(in srgb, var(--text, #e7e9ee) 25%, transparent); border-radius: 6px; }",
  ].join("\n");

  function style() {
    if (document.getElementById("forge-theme-cards-css")) return;
    var s = document.createElement("style");
    s.id = "forge-theme-cards-css";
    s.textContent = CSS;
    (document.head || document.documentElement).appendChild(s);
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function colour(value, fallback) {
    return HEX.test(value || "") ? value : fallback;
  }
  // A picture link in CSS: quotes and backslashes escaped, nothing else read.
  function cssUrl(link) {
    return 'url("' + String(link).replace(/["\\\n]/g, "\\$&") + '")';
  }

  function theme(p, opts) {
    style();
    opts = opts || {};
    var c = p.colours || {};
    var card = el("button", "ftc ftc-theme");
    card.type = "button";
    card.dataset.id = p.id;
    if (opts.current) card.classList.add("ftc-current");
    card.title = p.about || p.label;
    var light = p.mode === "light";
    var set = function (k, v) { card.style.setProperty(k, v); };
    set("--t-accent", colour(c.accent, "#6ea8fe"));
    set("--t-panel", colour(c.panel, light ? "#ffffff" : "#171a21"));
    set("--t-border", colour(c.border, light ? "#d9dce3" : "#2a2f3a"));
    set("--t-text", colour(c.text, light ? "#1d2230" : "#e7e9ee"));
    set("--t-muted", colour(c.muted, light ? "#6b7385" : "#8b93a3"));
    var bg = colour(c.bg, light ? "#f3f4f7" : "#0f1115");
    set("--t-bg", p.wall ? cssUrl(p.wall) + ", " + bg
      : "radial-gradient(120% 90% at 20% 10%, " + colour(c.panel_2, bg) + ", " + bg + ")");
    var r = Number(p.radius);
    if (isFinite(r) && p.radius !== null && p.radius !== undefined) set("--t-radius", Math.round(r * 0.45) + "px");
    if (p.font_stack) set("--t-font", p.font_stack);

    var shot = el("div", "ftc-shot");
    var bar = el("div", "ftc-bar");
    bar.append(el("i"), el("i"), el("i"));
    var clock = el("div", "ftc-clock", "12:30");
    clock.appendChild(el("small", null, "Good afternoon"));
    var tiles = el("div", "ftc-tiles");
    for (var i = 0; i < 4; i++) tiles.appendChild(el("i"));
    var badges = el("div", "ftc-badges");
    if (p.live) badges.appendChild(el("span", null, "Live"));
    if (p.companion) badges.appendChild(el("span", null, p.companion === "cat" ? "Cat" : "Friend"));
    shot.append(bar, clock, tiles, el("div", "ftc-dock"), badges);

    var foot = el("div", "ftc-foot");
    var name = el("div", "ftc-name");
    name.append(el("span", "ftc-dot"), el("span", null, p.label));
    if (opts.current) name.appendChild(el("em", null, "In use"));
    else if (p.mine) name.appendChild(el("em", null, "Yours"));
    foot.append(name, el("div", "ftc-about", p.about || ""));
    card.append(shot, foot);
    return card;
  }

  function row(n, h, cls) {
    var r = el("div", "p-row" + (cls ? " " + cls : ""));
    r.style.setProperty("--n", n);
    r.style.setProperty("--h", h + "px");
    for (var i = 0; i < n; i++) r.appendChild(el("i"));
    return r;
  }

  function layout(l, opts) {
    style();
    opts = opts || {};
    var h = l.home || {};
    var card = el("button", "ftc ftc-layout");
    card.type = "button";
    card.dataset.id = l.id;
    if (opts.current) card.classList.add("ftc-current");
    card.title = l.about || l.label;
    var plan = el("div", "ftc-plan" + (h.align === "center" ? " center" : ""));
    if (h.hero !== "none") {
      var hero = el("div", "p-hero");
      hero.append(el("div", "p-clock" + (h.hero === "small" ? " small" : "")), el("div", "p-search"));
      plan.appendChild(hero);
    } else {
      plan.appendChild(el("div", "p-search"));
    }
    if (h.recent !== false && h.sections !== "none") plan.appendChild(row(6, 6, "recent"));
    var tileH = h.tiles === "list" ? 5 : h.tiles === "compact" ? 8 : 14;
    var across = h.tiles === "list" ? 2 : h.tiles === "compact" ? 6 : h.tiles === "icons" ? 7 : 4;
    var kind = h.tiles === "icons" ? "icons" : "";
    if (h.sections === "none") {
      if (h.recent !== false) plan.appendChild(row(6, 6, "recent"));
      plan.appendChild(el("div", "p-empty"));
    } else if (h.sections === "flat") {
      for (var f = 0; f < 3; f++) plan.appendChild(row(across, tileH, kind));
    } else {
      for (var s = 0; s < 2; s++) {
        plan.appendChild(el("div", "p-head"));
        plan.appendChild(row(across, tileH, kind));
        if (h.sections === "rows") plan.appendChild(el("div", "p-more"));
        else if (h.tiles === "list") plan.appendChild(row(across, tileH, kind));
      }
    }
    var foot = el("div", "ftc-foot");
    var name = el("div", "ftc-name");
    name.appendChild(el("span", null, l.label));
    if (opts.current) name.appendChild(el("em", null, "In use"));
    foot.append(name, el("div", "ftc-about", l.about || ""));
    card.append(plan, foot);
    return card;
  }

  window.ForgeThemeCards = { theme: theme, layout: layout, style: style };
})();
