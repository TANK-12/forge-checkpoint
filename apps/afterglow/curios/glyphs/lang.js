/* Glyphs: the formula language. No DOM, so node can test it.
 *
 * One formula f(t, i, x, y) runs for every dot of an n x n field each frame.
 * Text -> tokens -> AST (plain arrays, the same shape server.py builds) ->
 * a tree of closures compiled once. Never eval, never new Function. Every
 * node's result that is NaN or +-Infinity becomes 0, so nothing can poison
 * the field. server.py mirrors this file rule for rule; the agreement sweep
 * in tests/test_glyphs.py (through tests/agree.mjs) keeps the two honest.
 *
 * AST nodes:
 *   ["num", value, text]   a number or a constant (text is what was typed)
 *   ["var", name]          t i x y n u v r a
 *   ["neg", a] ["not", a]
 *   ["bin", op, a, b]      op: + - * / % ** < <= > >= == != && || & |
 *   ["if", cond, a, b]
 *   ["call", name, ...args]
 */

export const MAX_LENGTH = 400;
export const MAX_DEPTH = 32;

export const VARIABLES = {
  t: "time in seconds",
  i: "dot number, 0 to n*n - 1",
  x: "column, 0 at the left",
  y: "row, 0 at the top",
  n: "dots per side",
  u: "column, measured from the centre",
  v: "row, measured from the centre",
  r: "distance from the centre",
  a: "angle around the centre, -PI to PI",
};

export const CONSTANTS = { PI: Math.PI, TAU: 2 * Math.PI, pi: Math.PI, tau: 2 * Math.PI };

const fin = (v) => (v - v === 0 ? v + 0 : 0); // + 0 also turns -0 into 0
const i32 = (v) => v | 0;
const M32 = 4294967295;

/** A 0..1 hash of three int32 lattice coordinates (murmur-style finish). */
export function hash3(ix, iy, iz) {
  let h = (0x9e3779b9 ^ Math.imul(ix, 0x27d4eb2d) ^ Math.imul(iy, 0x165667b1) ^ Math.imul(iz, 0x2c1b3c6d)) >>> 0;
  h = Math.imul(h ^ (h >>> 15), 0x85ebca6b) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35) >>> 0;
  h = (h ^ (h >>> 16)) >>> 0;
  return h / M32;
}

/** Smooth value noise in [-1, 1]; the same numbers on every machine. */
export function noise(x, y = 0, z = 0) {
  const fx = Math.floor(x);
  const fy = Math.floor(y);
  const fz = Math.floor(z);
  const ix = i32(fx);
  const iy = i32(fy);
  const iz = i32(fz);
  const jx = i32(ix + 1);
  const jy = i32(iy + 1);
  const jz = i32(iz + 1);
  const dx = x - fx;
  const dy = y - fy;
  const dz = z - fz;
  const sx = dx * dx * (3 - 2 * dx);
  const sy = dy * dy * (3 - 2 * dy);
  const sz = dz * dz * (3 - 2 * dz);
  const c000 = hash3(ix, iy, iz);
  const c100 = hash3(jx, iy, iz);
  const c010 = hash3(ix, jy, iz);
  const c110 = hash3(jx, jy, iz);
  const c001 = hash3(ix, iy, jz);
  const c101 = hash3(jx, iy, jz);
  const c011 = hash3(ix, jy, jz);
  const c111 = hash3(jx, jy, jz);
  const x00 = c000 + (c100 - c000) * sx;
  const x10 = c010 + (c110 - c010) * sx;
  const x01 = c001 + (c101 - c001) * sx;
  const x11 = c011 + (c111 - c011) * sx;
  const y0 = x00 + (x10 - x00) * sy;
  const y1 = x01 + (x11 - x01) * sy;
  return (y0 + (y1 - y0) * sz) * 2 - 1;
}

/** A steady random number in [0, 1] for each whole number k. */
export function rand(k) {
  return hash3(i32(Math.floor(k)), 1013, 7);
}

function mod(a, b) {
  let m = a % b;
  if (m !== 0 && m < 0 !== b < 0) m += b;
  return m;
}

/** name: [fewest args, most args (-1 = any), fn, help]. Order matters: it
 *  breaks ties when suggesting a name for a typo. */
export const FUNCTIONS = {
  sin: [1, 1, Math.sin, "sine"],
  cos: [1, 1, Math.cos, "cosine"],
  tan: [1, 1, Math.tan, "tangent"],
  abs: [1, 1, Math.abs, "size without the sign"],
  sqrt: [1, 1, Math.sqrt, "square root"],
  hypot: [2, 2, Math.hypot, "length of (a, b)"],
  atan2: [2, 2, Math.atan2, "angle of the point (x=b, y=a)"],
  min: [1, -1, Math.min, "smallest"],
  max: [1, -1, Math.max, "largest"],
  floor: [1, 1, Math.floor, "round down"],
  ceil: [1, 1, Math.ceil, "round up"],
  round: [1, 1, (v) => Math.floor(v + 0.5), "nearest whole number"],
  fract: [1, 1, (v) => v - Math.floor(v), "the part after the point"],
  sign: [1, 1, (v) => (v > 0 ? 1 : v < 0 ? -1 : 0), "-1, 0 or 1"],
  pow: [2, 2, Math.pow, "a to the power b"],
  exp: [1, 1, Math.exp, "e to the power"],
  log: [1, 1, Math.log, "natural log"],
  mod: [2, 2, mod, "remainder that never goes negative"],
  clamp: [3, 3, (v, lo, hi) => Math.min(Math.max(v, lo), hi), "keep v between lo and hi"],
  mix: [3, 3, (p, q, k) => p + (q - p) * k, "blend from a to b by k"],
  noise: [1, 3, noise, "smooth noise in -1..1"],
  rand: [0, 1, rand, "a steady random 0..1 per whole number (default i)"],
};

const KNOWN = [...Object.keys(FUNCTIONS), ...Object.keys(CONSTANTS), ...Object.keys(VARIABLES)];

export class GlyphError extends Error {
  constructor(message, col) {
    super(message);
    this.col = col;
  }
}

const isDigit = (c) => c !== undefined && c >= "0" && c <= "9";
const isNameStart = (c) => c !== undefined && ((c >= "a" && c <= "z") || (c >= "A" && c <= "Z") || c === "_");
const isName = (c) => isNameStart(c) || isDigit(c);
const TWO = new Set(["**", "&&", "||", "==", "!=", "<=", ">="]);
const ONE = new Set(["+", "-", "*", "/", "%", "^", "!", "?", ":", "(", ")", ",", "<", ">", "&", "|"]);

export function tokenize(src) {
  const out = [];
  let k = 0;
  while (k < src.length) {
    const c = src[k];
    if (c === " " || c === "\t" || c === "\n" || c === "\r") {
      k++;
      continue;
    }
    const col = k + 1;
    if (isDigit(c) || (c === "." && isDigit(src[k + 1]))) {
      let j = k;
      while (isDigit(src[j])) j++;
      if (src[j] === ".") {
        j++;
        while (isDigit(src[j])) j++;
      }
      if (
        (src[j] === "e" || src[j] === "E") &&
        (isDigit(src[j + 1]) || ((src[j + 1] === "+" || src[j + 1] === "-") && isDigit(src[j + 2])))
      ) {
        j += 2;
        while (isDigit(src[j])) j++;
      }
      out.push({ kind: "num", text: src.slice(k, j), col });
      k = j;
      continue;
    }
    if (isNameStart(c)) {
      let j = k;
      while (isName(src[j])) j++;
      out.push({ kind: "name", text: src.slice(k, j), col });
      k = j;
      continue;
    }
    const two = src.slice(k, k + 2);
    if (TWO.has(two)) {
      out.push({ kind: "op", text: two, col });
      k += 2;
      continue;
    }
    if (ONE.has(c)) {
      out.push({ kind: "op", text: c, col });
      k++;
      continue;
    }
    if (c === "=") throw new GlyphError("Use == to compare two values", col);
    throw new GlyphError(`I do not know the character '${String.fromCodePoint(src.codePointAt(k))}'`, col);
  }
  out.push({ kind: "end", text: "", col: src.length + 1 });
  return out;
}

/** Edit distance where swapping two neighbours counts as one edit (optimal
 *  string alignment), so "sni" is one step from "sin". */
function distance(p, q) {
  const d = [];
  for (let i = 0; i <= p.length; i++) d.push([i]);
  for (let j = 1; j <= q.length; j++) d[0].push(j);
  for (let i = 1; i <= p.length; i++) {
    for (let j = 1; j <= q.length; j++) {
      let best = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (p[i - 1] === q[j - 1] ? 0 : 1));
      if (i > 1 && j > 1 && p[i - 1] === q[j - 2] && p[i - 2] === q[j - 1]) best = Math.min(best, d[i - 2][j - 2] + 1);
      d[i].push(best);
    }
  }
  return d[p.length][q.length];
}

/** The known name closest to a typo, or "" when nothing is close. */
export function suggest(name) {
  if (name.length < 2) return "";
  const limit = name.length >= 4 ? 2 : 1;
  let best = "";
  let bestD = limit + 1;
  for (const k of KNOWN) {
    const d = distance(name.toLowerCase(), k.toLowerCase());
    if (d < bestD) {
      best = k;
      bestD = d;
    }
  }
  return best;
}

function plural(k) {
  return k === 1 ? "1 value" : `${k} values`;
}

function arityText(lo, hi) {
  if (hi === lo) return plural(lo);
  if (hi < 0) return `at least ${plural(lo)}`;
  return `${lo} to ${hi} values`;
}

/** Text -> AST. Throws GlyphError(message, col) with a 1-based column. */
export function parse(src) {
  src = String(src ?? "");
  const length = [...src].length;
  if (length > MAX_LENGTH) {
    throw new GlyphError(`Keep it under ${MAX_LENGTH} characters (this one has ${length})`, MAX_LENGTH + 1);
  }
  if (/^[ \t\n\r]*$/.test(src)) throw new GlyphError("Write a formula, for example sin(t - r)", 1);
  const toks = tokenize(src);
  let p = 0;
  const peek = () => toks[p];
  const isOp = (...ops) => toks[p].kind === "op" && ops.includes(toks[p].text);
  const deeper = (depth) => {
    if (depth >= MAX_DEPTH) throw new GlyphError(`Nested too deeply (more than ${MAX_DEPTH} levels)`, toks[p].col);
    return depth + 1;
  };
  const tooSoon = () => new GlyphError("The formula ends too soon", toks[p].col);

  function closeParen(open) {
    if (isOp(")")) {
      p++;
      return;
    }
    if (peek().kind === "end") throw new GlyphError(`Missing ')' for the '(' at column ${open}`, peek().col);
    throw new GlyphError(`Expected ')' for the '(' at column ${open}, found '${peek().text}'`, peek().col);
  }

  function ternary(depth) {
    const cond = or(depth);
    if (!isOp("?")) return cond;
    const q = peek().col;
    p++;
    const d = deeper(depth);
    const yes = ternary(d);
    if (!isOp(":")) {
      if (peek().kind === "end") throw new GlyphError(`Missing ':' for the '?' at column ${q}`, peek().col);
      throw new GlyphError(`Expected ':' for the '?' at column ${q}, found '${peek().text}'`, peek().col);
    }
    p++;
    return ["if", cond, yes, ternary(d)];
  }

  function chain(next, ops) {
    return (depth) => {
      let left = next(depth);
      while (isOp(...ops)) {
        const op = toks[p++].text;
        left = ["bin", op, left, next(depth)];
      }
      return left;
    };
  }

  function unary(depth) {
    if (isOp("-", "+", "!")) {
      const op = toks[p].text;
      const d = deeper(depth);
      p++;
      const inner = unary(d);
      if (op === "+") return inner;
      return [op === "-" ? "neg" : "not", inner];
    }
    return power(depth);
  }

  function power(depth) {
    const base = primary(depth);
    if (isOp("**", "^")) {
      const d = deeper(depth);
      p++;
      return ["bin", "**", base, unary(d)];
    }
    return base;
  }

  function primary(depth) {
    const tok = peek();
    if (tok.kind === "num") {
      p++;
      return ["num", Number(tok.text), tok.text];
    }
    if (tok.kind === "name") {
      p++;
      const name = tok.text;
      if (Object.hasOwn(FUNCTIONS, name)) {
        if (!isOp("(")) throw new GlyphError(`'${name}' is a function: write ${name}(...)`, tok.col);
        const open = peek().col;
        const d = deeper(depth);
        p++;
        const args = [];
        if (!isOp(")")) {
          args.push(ternary(d));
          while (isOp(",")) {
            p++;
            args.push(ternary(d));
          }
        }
        closeParen(open);
        const [lo, hi] = FUNCTIONS[name];
        if (args.length < lo || (hi >= 0 && args.length > hi)) {
          throw new GlyphError(`'${name}' takes ${arityText(lo, hi)}, got ${args.length}`, tok.col);
        }
        return ["call", name, ...args];
      }
      const known = Object.hasOwn(CONSTANTS, name) || Object.hasOwn(VARIABLES, name);
      if (known && isOp("(")) throw new GlyphError(`'${name}' is a value, not a function`, tok.col);
      if (Object.hasOwn(CONSTANTS, name)) return ["num", CONSTANTS[name], name];
      if (Object.hasOwn(VARIABLES, name)) return ["var", name];
      const hint = suggest(name);
      throw new GlyphError(`Unknown name '${name}'${hint ? ` (did you mean '${hint}'?)` : ""}`, tok.col);
    }
    if (isOp("(")) {
      const open = tok.col;
      const d = deeper(depth);
      p++;
      const inner = ternary(d);
      closeParen(open);
      return inner;
    }
    if (tok.kind === "end") throw tooSoon();
    throw new GlyphError(`Expected a value, found '${tok.text}'`, tok.col);
  }

  const mul = chain(unary, ["*", "/", "%"]);
  const add = chain(mul, ["+", "-"]);
  const band = chain(add, ["&"]);
  const bor = chain(band, ["|"]);
  const cmp = chain(bor, ["<", "<=", ">", ">=", "==", "!="]);
  const and = chain(cmp, ["&&"]);
  const or = chain(and, ["||"]);

  const ast = ternary(0);
  const rest = peek();
  if (rest.kind !== "end") {
    if (rest.kind !== "op" || rest.text === "(") {
      throw new GlyphError(`Missing an operator before '${rest.text}'`, rest.col);
    }
    throw new GlyphError(`Did not expect '${rest.text}'`, rest.col);
  }
  return ast;
}

/** The AST as fully bracketed text; server.py prints the very same. */
export function show(node) {
  switch (node[0]) {
    case "num":
      return node[2];
    case "var":
      return node[1];
    case "neg":
      return `(-${show(node[1])})`;
    case "not":
      return `(!${show(node[1])})`;
    case "bin":
      return `(${show(node[2])} ${node[1]} ${show(node[3])})`;
    case "if":
      return `(${show(node[1])} ? ${show(node[2])} : ${show(node[3])})`;
    case "call":
      return `${node[1]}(${node.slice(2).map(show).join(", ")})`;
  }
  throw new Error(`unknown node ${node[0]}`);
}

const BIN = {
  "+": (A, B) => (s) => fin(A(s) + B(s)),
  "-": (A, B) => (s) => fin(A(s) - B(s)),
  "*": (A, B) => (s) => fin(A(s) * B(s)),
  "/": (A, B) => (s) => fin(A(s) / B(s)),
  "%": (A, B) => (s) => fin(A(s) % B(s)),
  "**": (A, B) => (s) => fin(Math.pow(A(s), B(s))),
  "<": (A, B) => (s) => (A(s) < B(s) ? 1 : 0),
  "<=": (A, B) => (s) => (A(s) <= B(s) ? 1 : 0),
  ">": (A, B) => (s) => (A(s) > B(s) ? 1 : 0),
  ">=": (A, B) => (s) => (A(s) >= B(s) ? 1 : 0),
  "==": (A, B) => (s) => (A(s) === B(s) ? 1 : 0),
  "!=": (A, B) => (s) => (A(s) !== B(s) ? 1 : 0),
  "&&": (A, B) => (s) => (A(s) !== 0 ? B(s) : 0),
  "||": (A, B) => (s) => {
    const v = A(s);
    return v !== 0 ? v : B(s);
  },
  "&": (A, B) => (s) => A(s) & B(s),
  "|": (A, B) => (s) => A(s) | B(s),
};

/** AST -> fn(s), s = {t, i, x, y, n, u, v, r, a}. Built once, run per dot. */
export function compile(node) {
  switch (node[0]) {
    case "num": {
      const k = fin(node[1]);
      return () => k;
    }
    case "var": {
      const name = node[1];
      return (s) => s[name];
    }
    case "neg": {
      const A = compile(node[1]);
      return (s) => fin(-A(s));
    }
    case "not": {
      const A = compile(node[1]);
      return (s) => (A(s) === 0 ? 1 : 0);
    }
    case "bin":
      return BIN[node[1]](compile(node[2]), compile(node[3]));
    case "if": {
      const C = compile(node[1]);
      const A = compile(node[2]);
      const B = compile(node[3]);
      return (s) => (C(s) !== 0 ? A(s) : B(s));
    }
    case "call": {
      const f = FUNCTIONS[node[1]][2];
      const args = node.slice(2).map(compile);
      if (node[1] === "rand" && args.length === 0) args.push((s) => s.i);
      if (node[1] === "noise") while (args.length < 3) args.push(() => 0);
      if (args.length === 1) {
        const [A] = args;
        return (s) => fin(f(A(s)));
      }
      if (args.length === 2) {
        const [A, B] = args;
        return (s) => fin(f(A(s), B(s)));
      }
      if (args.length === 3) {
        const [A, B, C] = args;
        return (s) => fin(f(A(s), B(s), C(s)));
      }
      return (s) => fin(f(...args.map((A) => A(s))));
    }
  }
  throw new Error(`unknown node ${node[0]}`);
}

/** Text -> {ok: true, fn, ast} or {ok: false, error: {message, col}}. */
export function prepare(src) {
  try {
    const ast = parse(src);
    return { ok: true, ast, fn: compile(ast) };
  } catch (e) {
    if (e instanceof GlyphError) return { ok: false, error: { message: e.message, col: e.col } };
    throw e;
  }
}

/** Per-dot positions for an n x n field, worked out once per size. */
export function geometry(n) {
  const count = n * n;
  const g = { n, x: new Float64Array(count), y: new Float64Array(count), u: new Float64Array(count) };
  g.v = new Float64Array(count);
  g.r = new Float64Array(count);
  g.a = new Float64Array(count);
  const c = (n - 1) / 2;
  for (let k = 0; k < count; k++) {
    const x = k % n;
    const y = (k - x) / n;
    g.x[k] = x;
    g.y[k] = y;
    g.u[k] = x - c;
    g.v[k] = y - c;
    g.r[k] = Math.hypot(x - c, y - c);
    g.a[k] = Math.atan2(y - c, x - c);
  }
  return g;
}

/** Run fn for every dot at time t into out (length n*n). A t that is not
 *  finite counts as 0, like every other value. */
export function evalFrame(fn, t, geo, out) {
  const s = { t: fin(t), i: 0, x: 0, y: 0, n: geo.n, u: 0, v: 0, r: 0, a: 0 };
  const count = geo.n * geo.n;
  for (let k = 0; k < count; k++) {
    s.i = k;
    s.x = geo.x[k];
    s.y = geo.y[k];
    s.u = geo.u[k];
    s.v = geo.v[k];
    s.r = geo.r[k];
    s.a = geo.a[k];
    out[k] = fn(s);
  }
  return out;
}

/** One frame of a formula as a plain array (tests, previews). */
export function frame(src, t, n) {
  const fn = compile(parse(src));
  return Array.from(evalFrame(fn, t, geometry(n), new Float64Array(n * n)));
}
