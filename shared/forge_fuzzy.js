/* Forgiving search ranking, shared by the home screen and the app switcher.

   score(query, docs) says how close a typed query is to something with a
   name and a description; 0 means no match. Every typed word is matched to
   its closest word in the name or description: the same word scores most,
   then the start of a word, then a word with a typo or two, then a word that
   means the same (shared/forge_search_words.js). The name counts more than
   the description, and a name that is, or starts with, the whole query
   comes first. rank() sorts a list by that score, closest first. */
(function (root) {
  const words =
    root.FORGE_SEARCH_WORDS ||
    (typeof require === "function" ? safeRequire("./forge_search_words.js") : null) ||
    [];

  function safeRequire(path) {
    try {
      return require(path);
    } catch (e) {
      return null;
    }
  }

  function tokens(text) {
    return String(text || "")
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter(Boolean);
  }

  // Edits between two words, a swapped pair counting as one; stops early
  // once it is past `limit`.
  function edits(a, b, limit) {
    if (Math.abs(a.length - b.length) > limit) return limit + 1;
    let prev2 = null;
    let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
    for (let i = 1; i <= a.length; i++) {
      const row = [i];
      let best = i;
      for (let j = 1; j <= b.length; j++) {
        const cost = a[i - 1] === b[j - 1] ? 0 : 1;
        let d = Math.min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + cost);
        if (prev2 && i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1])
          d = Math.min(d, prev2[j - 2] + 1);
        row.push(d);
        best = Math.min(best, d);
      }
      if (best > limit) return limit + 1;
      prev2 = prev;
      prev = row;
    }
    return prev[b.length];
  }

  // How many typos a typed word may carry: none for short words, where one
  // edit turns almost anything into anything.
  function allowed(q) {
    return q.length <= 3 ? 0 : q.length <= 6 ? 1 : 2;
  }

  // How close one typed word is to one word of the text, 0 to 1. A typo
  // scores below any real word, so the closest word always wins; on a short
  // word one edit is a bigger guess than on a long one.
  function closeness(q, w) {
    if (q === w) return 1;
    if (w.startsWith(q)) return 0.8 + 0.15 * (q.length / w.length);
    if (q.length >= 3 && w.includes(q)) return 0.75;
    const limit = allowed(q);
    if (!limit) return 0;
    const short = q.length <= 4 ? 0.1 : 0;
    const whole = edits(q, w, limit);
    if (whole <= limit) return 0.6 - 0.1 * (whole - 1) - short;
    // a typo in a word still being typed: "nvoel" for "novelforge"
    let start = limit + 1;
    for (let n = q.length - 1; n <= q.length + 1; n++)
      if (n > 0 && n < w.length) start = Math.min(start, edits(q, w.slice(0, n), limit));
    return start <= limit ? 0.5 - 0.1 * (start - 1) - short : 0;
  }

  // The typed word plus the words that mean the same, each with how much a
  // hit on it is worth. A meaning line counts when the typed word is one of
  // its words, or close to one ("msuic" still brings "song").
  const meaningCache = new Map();
  function meanings(q) {
    if (meaningCache.has(q)) return meaningCache.get(q);
    const out = new Map([[q, 1]]);
    for (const line of words) {
      let near = 0;
      for (const w of line) {
        const c = w === q ? 1 : closeness(q, w);
        // a meaning only counts for a whole word or a near miss, not a mere prefix
        if (c >= 0.5 && (w === q || q.length >= 4)) near = Math.max(near, c);
      }
      if (!near) continue;
      for (const w of line) if (w !== q) out.set(w, Math.max(out.get(w) || 0, 0.65 * near));
    }
    meaningCache.set(q, out);
    return out;
  }

  const NAME = 1;
  const TEXT = 0.7;

  function scoreOne(query, doc) {
    const name = tokens(doc.name);
    const text = tokens(doc.text);
    const typed = tokens(query);
    if (!typed.length || (!name.length && !text.length)) return 0;
    let total = 0;
    let matched = 0;
    for (const q of typed) {
      let best = 0;
      for (const [m, worth] of meanings(q)) {
        for (const w of name) best = Math.max(best, NAME * worth * closeness(m, w));
        for (const w of text) best = Math.max(best, TEXT * worth * closeness(m, w));
      }
      if (best > 0) matched++;
      total += best;
    }
    if (!matched) return 0;
    // every word counts: a query only half found ranks below one found whole
    let score = (total / typed.length) * (matched / typed.length);
    const joined = typed.join("");
    const whole = name.join("");
    if (whole === joined) score += 1;
    else if (whole.startsWith(joined)) score += 0.5;
    return score < 0.3 ? 0 : score;
  }

  // docs: one { name, text } or several (a folder and its apps); the best counts.
  function score(query, docs) {
    const list = Array.isArray(docs) ? docs : [docs];
    return list.reduce((best, doc) => Math.max(best, scoreOne(query, doc || {})), 0);
  }

  // The keys that match, closest first; equal scores keep their given order.
  function rank(query, keys, docsOf) {
    return keys
      .map((key, i) => ({ key, i, score: score(query, docsOf(key)) }))
      .filter((hit) => hit.score > 0)
      .sort((a, b) => b.score - a.score || a.i - b.i)
      .map(({ key, score }) => ({ key, score }));
  }

  const api = { score, rank, tokens, edits };
  root.ForgeFuzzy = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
