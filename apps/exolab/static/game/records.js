// Best lap per suit and profile, kept between visits in the browser's
// localStorage. A profile edited and saved under the same name keeps its
// record; the stub (no stats from the tester) keeps none. Plain functions on
// any Storage-like object, so tests/js/game_sim.mjs runs them in Node.

const PREFIX = "exolab.bestLap.";

/** The storage key for a suit (model id) and profile name. */
export function bestKey(model, profile) {
  return `${PREFIX}${model}|${profile}`;
}

/** The saved best lap in seconds, or null (none, unreadable or no storage). */
export function loadBest(store, key) {
  try {
    const v = Number(store?.getItem(key));
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch {
    return null; // storage refused (private window, sandboxed frame)
  }
}

/** Keep `time` if it beats the saved best. True when it beats a record saved
 *  earlier; the first lap sets the record quietly. */
export function saveBest(store, key, time) {
  if (!Number.isFinite(time) || time <= 0) return false;
  const old = loadBest(store, key);
  if (old != null && old <= time) return false;
  try {
    store?.setItem(key, String(Math.round(time * 1000) / 1000));
  } catch {
    return false; // full or refused: the record lives for this visit only
  }
  return old != null;
}
