/* The Themes and Home layout cards.

   A theme (shared/themes/<id>.json) sets the colours, font, corners,
   wallpaper and home layout in one go; a layout (shared/layouts/<id>.json)
   only arranges the home screen. Both are drawn by
   shared/forge_theme_cards.js, the same cards as the hub's Alt+T switcher.
   A pick goes to /api/themes/pick or /api/layouts/pick and answers like a
   settings save, so accept() hands the new theme to the hub. Undo puts back
   what the last pick replaced. While the Business look is locked a pick
   answers 423 and Business.ask() asks for the password, then picks again.
   Which theme is in use comes from state.theme (render() calls paint()), so
   a pick made in the hub shows here too. */
const Themes = (() => {
  let list = null; // /api/themes: themes, layouts (cards with their pictures)
  let filter = "all";
  let busy = false;
  // the chips, in this order when a theme carries the tag
  const CHIPS = [["all", "All"], ["mine", "Yours"], ["dark", "Dark"], ["light", "Light"],
    ["live", "Moving"], ["fun", "Fun"], ["calm", "Calm"], ["cosy", "Cosy"], ["nature", "Nature"],
    ["anime", "Anime"], ["retro", "Retro"], ["business", "Work"], ["simple", "Simple"]];

  function say(text) { $("themes-said").textContent = text; }

  async function load() {
    try {
      list = await api("/api/themes");
    } catch (e) {
      say("Themes could not be read: " + e.message);
      return;
    }
    paint();
  }

  function now() {
    const t = state.theme || {};
    return {
      theme: t.theme !== undefined ? t.theme : (list && list.theme) || "",
      layout: t.layout_id || (list && list.layout_id) || "",
      undo: t.theme_can_undo !== undefined ? t.theme_can_undo : !!(list && list.theme_can_undo),
    };
  }

  function shown(t) {
    if (filter === "all") return true;
    if (filter === "mine") return t.mine;
    return (t.tags || []).includes(filter);
  }

  function paintChips() {
    const have = new Set();
    list.themes.forEach((t) => { (t.tags || []).forEach((g) => have.add(g)); if (t.mine) have.add("mine"); });
    if (filter !== "all" && !have.has(filter)) filter = "all";
    const row = $("theme-chips");
    row.replaceChildren(...CHIPS.filter(([id]) => id === "all" || have.has(id)).map(([id, label]) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "theme-chip";
      b.textContent = label;
      b.setAttribute("aria-pressed", String(id === filter));
      b.addEventListener("click", () => { filter = id; paint(); });
      return b;
    }));
  }

  function paint() {
    if (!list || !window.ForgeThemeCards || !state.settings) return;
    const cur = now();
    paintChips();
    $("theme-cards").replaceChildren(...list.themes.filter(shown).map((t) => {
      const card = ForgeThemeCards.theme(t, { current: t.id === cur.theme });
      card.addEventListener("click", () => pick("theme", t));
      return card;
    }));
    $("layout-cards").replaceChildren(...list.layouts.map((l) => {
      const card = ForgeThemeCards.layout(l, { current: l.id === cur.layout });
      card.addEventListener("click", () => pick("layout", l));
      return card;
    }));
    const theme = list.themes.find((t) => t.id === cur.theme);
    $("theme-now").textContent = theme ? `In use: ${theme.label}` : "No theme in use: your own look";
    $("theme-undo").disabled = busy || !cur.undo;
    $("theme-desktop").checked = state.settings.theme_desktop === "files";
    // a release build cuts the setting (FORGE_CUT_SETTINGS): no switch for it
    const desktop = "theme_desktop" in (state.fields || {});
    document.querySelector("label.theme-desktop").hidden = !desktop;
    $("theme-desktop-note").hidden = !desktop;
  }

  async function pick(kind, item) {
    if (busy) return;
    busy = true;
    say(`Switching to ${item.label}…`);
    try {
      await flush(); // a change still waiting is saved first, not laid over the pick
      take(await api(kind === "theme" ? "/api/themes/pick" : "/api/layouts/pick",
        { method: "POST", body: JSON.stringify({ id: item.id }) }));
      say(`${item.label} is on. Undo puts back what was there before.`);
    } catch (e) {
      if (e.status === 423 && typeof Business !== "undefined") {
        say("Business mode is locked: the password comes first.");
        Business.ask(() => pick(kind, item));
      } else {
        say(`Not switched: ${e.message}`);
      }
    } finally {
      busy = false;
      paint();
    }
  }

  function take(r) {
    if (r.themes) list = r.themes;
    accept(r); // settings, the hub, then render() repaints these cards
  }

  $("theme-undo").addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    try {
      take(await api("/api/themes/undo", { method: "POST", body: "{}" }));
      say("Put back what was there before the last pick.");
    } catch (e) {
      if (e.status === 423 && typeof Business !== "undefined") {
        Business.ask(() => $("theme-undo").click());
      } else {
        say(`Not undone: ${e.message}`);
      }
    } finally {
      busy = false;
      paint();
    }
  });

  $("theme-save").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("theme-name").value.trim();
    if (!name) { say("Give the look a name first."); $("theme-name").focus(); return; }
    try {
      await flush();
      const r = await api("/api/themes/save", { method: "POST", body: JSON.stringify({ name }) });
      list = r.themes;
      $("theme-name").value = "";
      filter = "mine";
      paint();
      say(`Saved as "${name}". It is under Yours, and in the Alt+T switcher.`);
    } catch (err) {
      say(`Not saved: ${err.message}`);
    }
  });

  $("theme-desktop").addEventListener("change", (e) => {
    change("theme_desktop", e.target.checked ? "files" : "off");
  });

  load();
  return { paint, load };
})();
