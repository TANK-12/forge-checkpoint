/* Ctrl+Z undoes and Ctrl+Shift+Z or Ctrl+Y redoes in every text box in Forge.

   WebKitGTK binds no key to undo (WebKitGTK 2.5x in Forge, checked
   2026-10-07 with real key presses: Ctrl+Z, Ctrl+Shift+Z and Ctrl+Y left a
   textarea as it was). It still keeps each box's undo history, and
   execCommand reaches it, so the keys are bound here. forge_chrome.js loads
   this file on every page that loads it, the hub included. A page that
   handles one of these keys itself (a canvas editor's own undo) calls
   preventDefault and is left alone. Setting a box's .value from a script
   empties its history; execCommand("insertText") keeps it. */
(function () {
  if (window.ForgeUndo) return;

  const TEXT_INPUTS = ["text", "search", "url", "email", "tel", "password", "number", ""];

  /** "undo", "redo" or null for a keydown. */
  function action(e) {
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return null;
    const key = String(e.key || "").toLowerCase();
    if (key === "z") return e.shiftKey ? "redo" : "undo";
    if (key === "y" && !e.shiftKey) return "redo";
    return null;
  }

  /** Whether an element is a text box the keys should act in. */
  function editable(el) {
    if (!el || el.disabled || el.readOnly) return false;
    if (el.isContentEditable) return true;
    const tag = String(el.tagName || "").toUpperCase();
    if (tag === "TEXTAREA") return true;
    return tag === "INPUT" && TEXT_INPUTS.includes(String(el.getAttribute("type") || "").toLowerCase());
  }

  function onKey(e) {
    if (e.defaultPrevented || e.isComposing) return;
    const what = action(e);
    if (!what || !editable(e.target)) return;
    e.preventDefault();
    document.execCommand(what);
  }

  window.addEventListener("keydown", onKey);
  window.ForgeUndo = { action, editable, onKey };
})();
