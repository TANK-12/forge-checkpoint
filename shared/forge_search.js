/* The home screen's one search, past the app and place tiles (experience plan
   B3, Relay task 392). Typing on Home also finds:

     - settings: each one opens Settings at that row (theme.search_settings,
       written by shared/forge_theme.py from its SETTINGS table);
     - actions an app declares in its manifest ("actions": [{label, hash,
       words}]), each opening that app at that hash;
     - apps and places already open, to switch straight back;
     - and last, "Search everything", which hands the words to the app whose
       manifest role is "search" (Librarian).

   finds() is plain data in, plain rows out, so node tests it with no page
   (shared/forge_search.test.js); the hub draws the rows and opens them. The
   ranking is the tiles' own (shared/forge_fuzzy.js). */
(function (root) {
  const F = root.ForgeFuzzy || (typeof require === "function" ? require("./forge_fuzzy.js") : null);

  // How many of each kind a search shows at most, so the list stays short.
  const LIMITS = { open: 3, action: 5, setting: 5 };
  // A settings row has to be this close to show: a stray word in a long help
  // text is not a match. Actions are few and named on purpose, so they count
  // a little more than a setting of the same closeness.
  const FLOOR = { setting: 0.6, action: 0.45, open: 0.3 };
  const ACTION_WORTH = 1.15;

  function clip(list, n) {
    return list.slice(0, Math.max(0, n));
  }

  function ranked(query, items, docOf, kind, worth = 1) {
    return items
      .map((item, i) => ({ item, i, score: F.score(query, docOf(item)) * worth }))
      .filter((hit) => hit.score >= FLOOR[kind] * worth)
      .sort((a, b) => b.score - a.score || a.i - b.i)
      .map(({ item, score }) => Object.assign({ kind, score }, item));
  }

  /* query: what was typed. src:
       settings:   [{key, label, help, section, section_label}]
       actions:    [{app, app_label, label, hash, words}]
       open:       [{key, label}]           apps and places open now
       everything: {app, label} or null     the role "search" app, if any
     Returns rows, best first: open windows, then actions and settings by
     closeness, then "Search everything". Each row has kind, label, where,
     score, and what to open: {key} for a window, {app, hash} otherwise. */
  function finds(query, src = {}) {
    const q = String(query || "").trim();
    if (!q || !F) return [];
    const open = clip(ranked(q, src.open || [], (o) => ({ name: o.label, text: o.text || "" }), "open"), LIMITS.open)
      .map((o) => ({ kind: "open", label: o.label, where: "Open now", score: o.score, key: o.key }));
    const actions = clip(ranked(q, src.actions || [], (a) => [
      { name: a.label, text: `${a.words || ""} ${a.app_label || ""}` },
    ], "action", ACTION_WORTH), LIMITS.action)
      .map((a) => ({ kind: "action", label: a.label, where: a.app_label || a.app, score: a.score, app: a.app, hash: a.hash || "" }));
    const settings = clip(ranked(q, src.settings || [], (s) => [
      { name: s.label, text: `${s.section_label || ""} ${(s.key || "").replace(/_/g, " ")}` },
      // the help text counts, but well below the name
      { name: "", text: s.help || "" },
    ], "setting"), LIMITS.setting)
      .map((s) => ({
        kind: "setting", label: s.label, where: `Settings, ${s.section_label || s.section}`, score: s.score,
        app: "", role: "settings", hash: `${s.section}/${s.key}`,
      }));
    const rows = open.concat(actions.concat(settings).sort((a, b) => b.score - a.score));
    if (src.everything && q.length >= 2) {
      rows.push({
        kind: "everything", label: `Search everything for "${q}"`, where: src.everything.label || "Search",
        score: 0, app: src.everything.app, hash: `q=${encodeURIComponent(q)}`,
      });
    }
    return rows;
  }

  /* Which result Enter opens. items: the tiles' hits ({tile, score}) then
     the rows ({row, find, score}), in the order shown. The closest tile,
     setting or action wins (a tile on a tie: it is shown first); an open
     window comes next, and "Search everything" only when nothing else
     matched. -1 for an empty list. */
  function best(items) {
    let at = -1;
    let top = -1;
    items.forEach((item, i) => {
      const kind = item.find ? item.find.kind : "tile";
      if (kind === "open" || kind === "everything") return;
      if (item.score > top) {
        top = item.score;
        at = i;
      }
    });
    if (at >= 0) return at;
    const open = items.findIndex((item) => item.find && item.find.kind === "open");
    return open >= 0 ? open : items.length ? 0 : -1;
  }

  // A manifest's "actions", kept only when well formed: a label of its own,
  // an optional hash and words; at most 12 per app.
  function cleanActions(app, appLabel, list) {
    if (!Array.isArray(list)) return [];
    return list
      .filter((a) => a && typeof a.label === "string" && a.label.trim())
      .slice(0, 12)
      .map((a) => ({
        app, app_label: appLabel, label: a.label.trim().slice(0, 80),
        hash: typeof a.hash === "string" ? a.hash.replace(/^#/, "").slice(0, 400) : "",
        words: typeof a.words === "string" ? a.words.slice(0, 200) : "",
      }));
  }

  const api = { finds, best, cleanActions, LIMITS };
  root.ForgeSearch = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
