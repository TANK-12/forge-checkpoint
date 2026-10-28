"use strict";
/* The Log pane's filters and its in-place updates (Forge sweep, 2026-10-19).
 *
 * The log used to be rebuilt from scratch whenever a line arrived, which threw
 * a reader who had scrolled up back to the top of the pane. Now only the lines
 * that fell off the front are taken away and the new ones are added at the
 * end, so what you are reading stays where it is.
 *
 * The filters are data: a new one is one entry in FILTERS. `kinds` are the
 * log kinds from sim.py's note() (said, move, day, story, skip, note); null
 * means every kind. Pure functions of plain values so node can test them.
 */
const JanLog = {
  FILTERS: [
    { id: "all", label: "Everything", kinds: null, title: "Every line in the log" },
    { id: "talk", label: "Talk", kinds: ["said"], title: "What the crew, and you, said" },
    {
      id: "stories",
      label: "Stories",
      kinds: ["story", "day", "skip"],
      title: "The narrator's stories, arrivals, gifts, new days and time skips",
    },
    { id: "moves", label: "Comings and goings", kinds: ["move"], title: "Who went where, and why" },
  ],

  /* A filter by id, falling back to the first ("Everything"), so a stale
     choice saved in the browser can never leave the pane empty for good. */
  find(id) {
    return JanLog.FILTERS.find((f) => f.id === id) || JanLog.FILTERS[0];
  },

  /* The lines a filter keeps. `who` narrows it to one crew member's lines
     (the `who` field sim.py writes on moves and speech); "" keeps everyone. */
  pick(log, filter, who) {
    const kinds = filter && filter.kinds;
    return (log || []).filter(
      (line) =>
        (!kinds || kinds.includes(line.kind || "note")) && (!who || line.who === who)
    );
  },

  /* What identifies a line. Lines have no ids; two identical lines in the
     same station minute are rare and harmless (they look the same). */
  key(line) {
    return [line.day, line.at, line.kind || "note", line.who || "", line.text].join("|");
  },

  /* How to get from the lines on screen to the new ones: drop `drop` lines
     off the front and append the last `add` new lines. The log is a capped
     tail, so the common change is a few gone from the front and a few new at
     the end. Returns null when that does not fit (a filter change, a loaded
     save, the first lines arriving in an empty pane): the caller rebuilds.
     An empty pane that stays empty is nothing to do, so a filter that keeps
     no lines is not rebuilt on every poll. */
  diff(shown, next) {
    if (!shown.length) return next.length ? null : { drop: 0, add: 0 };
    for (let drop = 0; drop < shown.length; drop++) {
      const kept = shown.length - drop;
      if (kept > next.length) continue;
      let same = true;
      for (let i = 0; i < kept; i++) {
        if (shown[drop + i] !== next[i]) {
          same = false;
          break;
        }
      }
      if (same) return { drop, add: next.length - kept };
    }
    return null;
  },
};

if (typeof module !== "undefined") module.exports = JanLog;
