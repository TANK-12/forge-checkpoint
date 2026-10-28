// The parts of Prompts that need no page: {{variables}}, filling them in,
// a line diff between versions and tag parsing. No DOM, so node --test
// runs them (tests/).

const VAR = /\{\{\s*([A-Za-z][\w -]{0,39}?)\s*\}\}/g;

/** The {{names}} in the texts, each once, in the order they first appear. */
export function variables(...texts) {
  const seen = [];
  for (const t of texts) {
    for (const m of (t || "").matchAll(VAR)) if (!seen.includes(m[1])) seen.push(m[1]);
  }
  return seen;
}

/** The text with each {{name}} that has a non-empty value replaced. */
export function fill(text, values) {
  return (text || "").replace(VAR, (whole, name) =>
    Object.hasOwn(values, name) && typeof values[name] === "string" && values[name] !== "" ? values[name] : whole,
  );
}

/** "Rock, Night drive ,rock" -> ["rock", "night drive"] */
export function parseTags(raw) {
  const out = [];
  for (const part of (raw || "").split(",")) {
    const tag = part.trim().toLowerCase();
    if (tag && !out.includes(tag)) out.push(tag);
  }
  return out;
}

/** Line diff of a -> b as [{op: "same" | "del" | "add", line}] (LCS).
 * Empty text has no lines. */
export function lineDiff(a, b) {
  const x = a ? a.split("\n") : [];
  const y = b ? b.split("\n") : [];
  const n = x.length;
  const m = y.length;
  if (n * m > 4_000_000) {
    // too big to compare line by line: show it as replaced
    return [...x.map((line) => ({ op: "del", line })), ...y.map((line) => ({ op: "add", line }))];
  }
  const len = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      len[i][j] = x[i] === y[j] ? len[i + 1][j + 1] + 1 : Math.max(len[i + 1][j], len[i][j + 1]);
  const out = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) {
      out.push({ op: "same", line: x[i] });
      i++;
      j++;
    } else if (len[i + 1][j] >= len[i][j + 1]) out.push({ op: "del", line: x[i++] });
    else out.push({ op: "add", line: y[j++] });
  }
  while (i < n) out.push({ op: "del", line: x[i++] });
  while (j < m) out.push({ op: "add", line: y[j++] });
  return out;
}

export function stars(n) {
  return "★".repeat(n) + "☆".repeat(5 - n);
}
