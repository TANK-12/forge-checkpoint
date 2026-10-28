/* Taleforge page logic that needs no DOM: which skills the creation screen
   offers and how the pick limit works. Loaded by the page as a plain script
   (window.TaleLogic) and by node --test as a CommonJS module. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.TaleLogic = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /* The rows of the skill picker: the background's skills first (ticked and
     locked), then the class's options to choose from. Skills the class cannot
     take are left out, so there are no empty cells. */
  function skillRows(skills, cls, bg, chosen) {
    const fromBg = new Set(bg.skills);
    const row = (s, locked) => ({
      id: s.id, name: s.name, ability: s.ability, locked,
      checked: locked || chosen.has(s.id),
    });
    return [
      ...skills.filter((s) => fromBg.has(s.id)).map((s) => row(s, true)),
      ...skills.filter((s) => !fromBg.has(s.id) && cls.skill_options.includes(s.id)).map((s) => row(s, false)),
    ];
  }

  /* Tick or untick one skill. Returns false (and leaves `chosen` alone) when
     ticking would go over the class's count. */
  function tickSkill(chosen, id, on, count) {
    if (!on) { chosen.delete(id); return true; }
    if (chosen.has(id)) return true;
    if (chosen.size >= count) return false;
    chosen.add(id);
    return true;
  }

  return { skillRows, tickSkill };
});
