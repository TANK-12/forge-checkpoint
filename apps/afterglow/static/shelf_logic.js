/* Pure helpers for the shelf (no DOM), so node can test them.
 * app.js uses them to decide what the keepsake wall and the logbook show and
 * whether anything changed since the last time it drew them. */

export const WALL_LIMIT = 24;
export const PAGE_LIMIT = 30;

/** A string that changes whenever any of `keys` changes in any row. */
export function signature(rows, keys) {
  return JSON.stringify((rows || []).map((r) => keys.map((k) => (r && r[k] !== undefined ? r[k] : null))));
}

/** What the keepsake wall shows: rows of one curio ("" is every curio),
 *  at most `limit` of them unless `all`. */
export function wallRows(rows, { curio = "", all = false, limit = WALL_LIMIT } = {}) {
  const picked = curio ? rows.filter((r) => r.curio === curio) : rows.slice();
  const shown = all ? picked : picked.slice(0, limit);
  return { shown, total: picked.length, hidden: picked.length - shown.length };
}

/** How many keepsakes each curio has, in shelf order, leaving out curios with none. */
export function curioCounts(rows, curios) {
  const counts = new Map();
  for (const r of rows) counts.set(r.curio, (counts.get(r.curio) || 0) + 1);
  return curios
    .filter((c) => counts.get(c.id))
    .map((c) => ({ id: c.id, name: c.name, icon: c.icon || "", count: counts.get(c.id) }));
}

/** A random keepsake for "Surprise me": never `lastId` again while there is another. */
export function surprise(rows, rand = Math.random, lastId = "") {
  if (!rows.length) return null;
  const pool = rows.length > 1 ? rows.filter((r) => r.id !== lastId) : rows;
  return pool[Math.min(pool.length - 1, Math.floor(rand() * pool.length))];
}

/** The pages the logbook shows: the newest `limit` unless `all`. */
export function logbookPages(pages, { all = false, limit = PAGE_LIMIT } = {}) {
  const shown = all ? pages.slice() : pages.slice(0, limit);
  return { shown, hidden: pages.length - shown.length };
}

/** A cache key for a keepsake's full JSON: a new keepsake that reuses a
 *  put-away one's slug has another `made`, so it never gets the old data. */
export function fullKey(row) {
  return `${row.curio}/${row.slug}@${row.made || ""}`;
}
