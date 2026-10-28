/* PixelForge editor state, kept free of the DOM so node can test it
   (tests/editor_state.test.mjs).

   Baseline: "unsaved changes" is a comparison, not a flag. Each document
   (a pack, a sound) keeps the JSON it had when it was loaded or last saved,
   and it is dirty exactly when it differs from that, so undoing back to the
   saved state reads as clean again.

   History: undo and redo steps for the sprite editor. Each step remembers
   which sprite it belongs to, so undo after switching sprites goes back to
   the sprite that was edited rather than pasting its frames into another.

   SHORTCUTS: the keyboard registry. A new key is one entry here plus one case
   in the page's action switch. Drawing tools (pencil B, fill F, ...) carry
   their own keys in tools.js; the page joins the two tables. */
(function (root) {
  "use strict";

  class Baseline {
    constructor() { this._saved = new Map(); }
    mark(id, value) { this._saved.set(id, JSON.stringify(value)); }
    markJSON(id, json) { this._saved.set(id, json); }
    forget(id) { this._saved.delete(id); }
    /** True when the document differs from its baseline, or never had one. */
    isDirty(id, value) { return this._saved.get(id) !== JSON.stringify(value); }
    /** A fresh copy of the saved state, or null. */
    saved(id) {
      const json = this._saved.get(id);
      return json === undefined ? null : JSON.parse(json);
    }
  }

  class History {
    constructor(limit = 40) { this.limit = limit; this.clear(); }
    clear() { this._undo = []; this._redo = []; }
    canUndo() { return this._undo.length > 0; }
    canRedo() { return this._redo.length > 0; }
    /** Call before an edit with the state it is about to change. */
    record(entry) {
      this._undo.push(entry);
      if (this._undo.length > this.limit) this._undo.shift();
      this._redo = [];
    }
    /** Pops one step; `now(entry)` gives that target's current state so the
        step can be redone. Returns the entry to restore, or null. */
    undo(now) { return this._move(this._undo, this._redo, now); }
    redo(now) { return this._move(this._redo, this._undo, now); }
    _move(from, to, now) {
      const entry = from.pop();
      if (!entry) return null;
      to.push({ ...entry, frames: now(entry) });
      return entry;
    }
  }

  /** A pack after a refresh from disk: sprites changed since `saved` (the
      last loaded or saved copy) or new in `edited` keep the unsaved edits;
      every other sprite, and any sprite only on disk, comes from `disk`.
      With nothing edited the result equals `disk`, so it reads clean. */
  function mergePack(saved, edited, disk) {
    const out = JSON.parse(JSON.stringify(disk));
    if (!edited) return out;
    const before = (saved && saved.sprites) || {};
    out.sprites = out.sprites || {};
    for (const [name, spr] of Object.entries(edited.sprites || {}))
      if (!before[name] || JSON.stringify(before[name]) !== JSON.stringify(spr))
        out.sprites[name] = JSON.parse(JSON.stringify(spr));
    return out;
  }

  /* keys: combos from comboOf(). tabs: where the key works. button: the
     element whose title gets the hint. Alt+key is left to the Forge shell. */
  const SHORTCUTS = [
    { action: "undo", keys: ["mod+z"], tabs: ["sprites"], label: "Undo", button: "undo" },
    { action: "redo", keys: ["mod+shift+z", "mod+y"], tabs: ["sprites"], label: "Redo", button: "redo" },
    { action: "save", keys: ["mod+s"], tabs: ["sprites", "sounds"], label: "Save", button: "save" },
    { action: "eraser", keys: ["e"], tabs: ["sprites"], label: "Eraser (transparent)" },
    { action: "mirror", keys: ["m"], tabs: ["sprites"], label: "Mirror left and right", button: "mirrorBtn" },
    { action: "onion", keys: ["o"], tabs: ["sprites"], label: "Onion skin: show the previous frame faintly", button: "onionBtn" },
    { action: "prevFrame", keys: ["["], tabs: ["sprites"], label: "Previous frame" },
    { action: "nextFrame", keys: ["]"], tabs: ["sprites"], label: "Next frame" },
    { action: "play", keys: ["space"], tabs: ["sprites", "sounds"], label: "Play or stop", button: "play" },
    { action: "zoomIn", keys: ["=", "+"], tabs: ["sprites"], label: "Zoom in", button: "zoomIn" },
    { action: "zoomOut", keys: ["-"], tabs: ["sprites"], label: "Zoom out", button: "zoomOut" },
    { action: "grid", keys: ["g"], tabs: ["sprites"], label: "Grid on or off", button: "gridBtn" },
  ];

  const NAMED = { " ": "space", spacebar: "space" };

  /** "mod+shift+z" style name for a keydown. Shift is only counted for
      letters and named keys: for "+" or "{" it is part of the character. */
  function comboOf(e) {
    let k = String(e.key || "");
    k = NAMED[k.toLowerCase()] || NAMED[k] || k.toLowerCase();
    const wordy = /^[a-z]$/.test(k) || k.length > 1;
    const parts = [];
    if (e.ctrlKey || e.metaKey) parts.push("mod");
    if (e.altKey) parts.push("alt");
    if (e.shiftKey && wordy) parts.push("shift");
    parts.push(k);
    return parts.join("+");
  }

  /** The action for a keydown in a tab, or null. */
  function match(e, tab, table = SHORTCUTS) {
    if (e.altKey) return null;
    const combo = comboOf(e);
    for (const s of table) if (s.tabs.includes(tab) && s.keys.includes(combo)) return s.action;
    return null;
  }

  const SHOW = { mod: "Ctrl", shift: "Shift", space: "Space" };
  /** Readable keys for an action, for button titles: "Ctrl+Shift+Z or Ctrl+Y". */
  function hint(action, table = SHORTCUTS) {
    const s = table.find((x) => x.action === action);
    if (!s) return "";
    return s.keys
      .map((c) => c.split("+").filter(Boolean).map((p) => SHOW[p] || p.toUpperCase()).join("+") || c)
      .join(" or ");
  }

  const api = { Baseline, History, SHORTCUTS, comboOf, match, hint, mergePack };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PixelState = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
