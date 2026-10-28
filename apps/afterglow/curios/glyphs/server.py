"""Glyphs in Python: the same formula language and Compose as lang.js and
compose.js, so a Claude session can play headless.

    play.py glyphs try "sin(t - hypot(x - 7.5, y - 7.5))" [--t T] [--n N] [--png]
    play.py glyphs compose [--seed N] [--t T] [--n N]
    play.py glyphs keep FORMULA --name NAME [--note TEXT] [--grid N] ...

`try` and `compose` print one frame as text art (two characters per dot,
blocks for positive, rings for negative, bigger means larger |value|);
`--png` also writes a picture into the data folder and prints its path.

The rules mirror lang.js exactly: same grammar, same error messages and
columns, every node's NaN or Infinity becomes 0, `%` keeps the dividend's
sign (like JavaScript), round() is floor(v + 0.5), `&` and `|` work on 32-bit
integers, noise() and rand() use the same integer hash. Only sin, exp and
friends may differ from V8 in the last bit; tests/agree.mjs checks the rest.
"""

from __future__ import annotations

import argparse
import math
import random
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

import store

CURIO = "glyphs"
MAX_LENGTH = 400
MAX_DEPTH = 32
M32 = 0xFFFFFFFF

VARIABLES = {
    "t": "time in seconds",
    "i": "dot number, 0 to n*n - 1",
    "x": "column, 0 at the left",
    "y": "row, 0 at the top",
    "n": "dots per side",
    "u": "column, measured from the centre",
    "v": "row, measured from the centre",
    "r": "distance from the centre",
    "a": "angle around the centre, -PI to PI",
}
CONSTANTS = {"PI": math.pi, "TAU": 2 * math.pi, "pi": math.pi, "tau": 2 * math.pi}

Env = dict[str, float]
Fn = Callable[[Env], float]


class GlyphError(ValueError):
    def __init__(self, message: str, col: int) -> None:
        super().__init__(message)
        self.message = message
        self.col = col


# --- numbers that behave like JavaScript's ------------------------------------


def fin(v: float) -> float:
    return v + 0.0 if math.isfinite(v) else 0.0  # + 0.0 also turns -0.0 into 0.0


def i32(v: float) -> int:
    """JavaScript's ToInt32 for a finite number."""
    if not math.isfinite(v):
        return 0
    k = int(v) & M32
    return k - 0x100000000 if k >= 0x80000000 else k


def imul(a: int, b: int) -> int:
    return ((a & M32) * (b & M32)) & M32


def hash3(ix: int, iy: int, iz: int) -> float:
    h = (
        0x9E3779B9 ^ imul(ix, 0x27D4EB2D) ^ imul(iy, 0x165667B1) ^ imul(iz, 0x2C1B3C6D)
    ) & M32
    h = imul(h ^ (h >> 15), 0x85EBCA6B)
    h = imul(h ^ (h >> 13), 0xC2B2AE35)
    h = (h ^ (h >> 16)) & M32
    return h / M32


def noise(x: float, y: float = 0.0, z: float = 0.0) -> float:
    fx, fy, fz = float(math.floor(x)), float(math.floor(y)), float(math.floor(z))
    ix, iy, iz = i32(fx), i32(fy), i32(fz)
    jx, jy, jz = i32(ix + 1), i32(iy + 1), i32(iz + 1)
    dx, dy, dz = x - fx, y - fy, z - fz
    sx = dx * dx * (3 - 2 * dx)
    sy = dy * dy * (3 - 2 * dy)
    sz = dz * dz * (3 - 2 * dz)
    c000, c100 = hash3(ix, iy, iz), hash3(jx, iy, iz)
    c010, c110 = hash3(ix, jy, iz), hash3(jx, jy, iz)
    c001, c101 = hash3(ix, iy, jz), hash3(jx, iy, jz)
    c011, c111 = hash3(ix, jy, jz), hash3(jx, jy, jz)
    x00 = c000 + (c100 - c000) * sx
    x10 = c010 + (c110 - c010) * sx
    x01 = c001 + (c101 - c001) * sx
    x11 = c011 + (c111 - c011) * sx
    y0 = x00 + (x10 - x00) * sy
    y1 = x01 + (x11 - x01) * sy
    return (y0 + (y1 - y0) * sz) * 2 - 1


def rand(k: float) -> float:
    return hash3(i32(float(math.floor(k))), 1013, 7)


def _safe(fn: Callable[..., Any]) -> Callable[..., float]:
    def run(*args: float) -> float:
        try:
            out = fn(*args)
        except (ArithmeticError, ValueError):
            return 0.0
        return fin(float(out)) if not isinstance(out, complex) else 0.0

    return run


def _mod(p: float, q: float) -> float:
    m = math.fmod(p, q)
    if m != 0 and (m < 0) != (q < 0):
        m += q
    return m


def _sign(v: float) -> float:
    return 1.0 if v > 0 else -1.0 if v < 0 else 0.0


FUNCTIONS: dict[str, tuple[int, int, Callable[..., Any], str]] = {
    "sin": (1, 1, math.sin, "sine"),
    "cos": (1, 1, math.cos, "cosine"),
    "tan": (1, 1, math.tan, "tangent"),
    "abs": (1, 1, abs, "size without the sign"),
    "sqrt": (1, 1, math.sqrt, "square root"),
    "hypot": (2, 2, math.hypot, "length of (a, b)"),
    "atan2": (2, 2, math.atan2, "angle of the point (x=b, y=a)"),
    "min": (1, -1, lambda *a: min(a), "smallest"),
    "max": (1, -1, lambda *a: max(a), "largest"),
    "floor": (1, 1, lambda v: float(math.floor(v)), "round down"),
    "ceil": (1, 1, lambda v: float(math.ceil(v)), "round up"),
    "round": (1, 1, lambda v: float(math.floor(v + 0.5)), "nearest whole number"),
    "fract": (1, 1, lambda v: v - math.floor(v), "the part after the point"),
    "sign": (1, 1, _sign, "-1, 0 or 1"),
    "pow": (2, 2, math.pow, "a to the power b"),
    "exp": (1, 1, math.exp, "e to the power"),
    "log": (1, 1, math.log, "natural log"),
    "mod": (2, 2, _mod, "remainder that never goes negative"),
    "clamp": (3, 3, lambda v, lo, hi: min(max(v, lo), hi), "keep v between lo and hi"),
    "mix": (3, 3, lambda p, q, k: p + (q - p) * k, "blend from a to b by k"),
    "noise": (1, 3, noise, "smooth noise in -1..1"),
    "rand": (0, 1, rand, "a steady random 0..1 per whole number (default i)"),
}
SAFE = {name: _safe(spec[2]) for name, spec in FUNCTIONS.items()}
KNOWN = [*FUNCTIONS, *CONSTANTS, *VARIABLES]

# --- text -> tokens -> AST ----------------------------------------------------

TWO = {"**", "&&", "||", "==", "!=", "<=", ">="}
ONE = set("+-*/%^!?:(),<>&|")


def _digit(src: str, k: int) -> bool:
    return k < len(src) and "0" <= src[k] <= "9"


def _name_start(src: str, k: int) -> bool:
    return k < len(src) and (
        "a" <= src[k] <= "z" or "A" <= src[k] <= "Z" or src[k] == "_"
    )


def tokenize(src: str) -> list[tuple[str, str, int]]:
    """(kind, text, column) triples, ending with ("end", "", len + 1)."""
    out: list[tuple[str, str, int]] = []
    k = 0
    while k < len(src):
        c = src[k]
        if c in " \t\n\r":
            k += 1
            continue
        col = k + 1
        if _digit(src, k) or (c == "." and _digit(src, k + 1)):
            j = k
            while _digit(src, j):
                j += 1
            if j < len(src) and src[j] == ".":
                j += 1
                while _digit(src, j):
                    j += 1
            if (
                j < len(src)
                and src[j] in "eE"
                and (
                    _digit(src, j + 1)
                    or (j + 1 < len(src) and src[j + 1] in "+-" and _digit(src, j + 2))
                )
            ):
                j += 2
                while _digit(src, j):
                    j += 1
            out.append(("num", src[k:j], col))
            k = j
            continue
        if _name_start(src, k):
            j = k
            while _name_start(src, j) or _digit(src, j):
                j += 1
            out.append(("name", src[k:j], col))
            k = j
            continue
        if src[k : k + 2] in TWO:
            out.append(("op", src[k : k + 2], col))
            k += 2
            continue
        if c in ONE:
            out.append(("op", c, col))
            k += 1
            continue
        if c == "=":
            raise GlyphError("Use == to compare two values", col)
        raise GlyphError(f"I do not know the character '{c}'", col)
    out.append(("end", "", len(src) + 1))
    return out


def _distance(p: str, q: str) -> int:
    """Edit distance where swapping two neighbours counts as one edit (optimal
    string alignment), so "sni" is one step from "sin"."""
    d = [[i] for i in range(len(p) + 1)]
    d[0].extend(range(1, len(q) + 1))
    for i in range(1, len(p) + 1):
        for j in range(1, len(q) + 1):
            best = min(
                d[i - 1][j] + 1,
                d[i][j - 1] + 1,
                d[i - 1][j - 1] + (p[i - 1] != q[j - 1]),
            )
            if i > 1 and j > 1 and p[i - 1] == q[j - 2] and p[i - 2] == q[j - 1]:
                best = min(best, d[i - 2][j - 2] + 1)
            d[i].append(best)
    return d[len(p)][len(q)]


def suggest(name: str) -> str:
    if len(name) < 2:
        return ""
    limit = 2 if len(name) >= 4 else 1
    best, best_d = "", limit + 1
    for known in KNOWN:
        d = _distance(name.lower(), known.lower())
        if d < best_d:
            best, best_d = known, d
    return best


def _plural(k: int) -> str:
    return "1 value" if k == 1 else f"{k} values"


def _arity_text(lo: int, hi: int) -> str:
    if hi == lo:
        return _plural(lo)
    if hi < 0:
        return f"at least {_plural(lo)}"
    return f"{lo} to {hi} values"


def _js_number(text: str) -> float:
    try:
        return float(text)
    except OverflowError:
        return math.inf


class _Parser:
    def __init__(self, src: str) -> None:
        self.toks = tokenize(src)
        self.p = 0

    def peek(self) -> tuple[str, str, int]:
        return self.toks[self.p]

    def is_op(self, *ops: str) -> bool:
        kind, text, _ = self.toks[self.p]
        return kind == "op" and text in ops

    def deeper(self, depth: int) -> int:
        if depth >= MAX_DEPTH:
            raise GlyphError(
                f"Nested too deeply (more than {MAX_DEPTH} levels)", self.peek()[2]
            )
        return depth + 1

    def close_paren(self, open_col: int) -> None:
        if self.is_op(")"):
            self.p += 1
            return
        kind, text, col = self.peek()
        if kind == "end":
            raise GlyphError(f"Missing ')' for the '(' at column {open_col}", col)
        raise GlyphError(
            f"Expected ')' for the '(' at column {open_col}, found '{text}'", col
        )

    def ternary(self, depth: int) -> list:
        cond = self.chain(depth, 0)
        if not self.is_op("?"):
            return cond
        q = self.peek()[2]
        self.p += 1
        d = self.deeper(depth)
        yes = self.ternary(d)
        if not self.is_op(":"):
            kind, text, col = self.peek()
            if kind == "end":
                raise GlyphError(f"Missing ':' for the '?' at column {q}", col)
            raise GlyphError(
                f"Expected ':' for the '?' at column {q}, found '{text}'", col
            )
        self.p += 1
        return ["if", cond, yes, self.ternary(d)]

    LEVELS = [
        ("||",),
        ("&&",),
        ("<", "<=", ">", ">=", "==", "!="),
        ("|",),
        ("&",),
        ("+", "-"),
        ("*", "/", "%"),
    ]

    def chain(self, depth: int, level: int) -> list:
        if level == len(self.LEVELS):
            return self.unary(depth)
        left = self.chain(depth, level + 1)
        while self.is_op(*self.LEVELS[level]):
            op = self.peek()[1]
            self.p += 1
            left = ["bin", op, left, self.chain(depth, level + 1)]
        return left

    def unary(self, depth: int) -> list:
        if self.is_op("-", "+", "!"):
            op = self.peek()[1]
            d = self.deeper(depth)
            self.p += 1
            inner = self.unary(d)
            if op == "+":
                return inner
            return ["neg" if op == "-" else "not", inner]
        return self.power(depth)

    def power(self, depth: int) -> list:
        base = self.primary(depth)
        if self.is_op("**", "^"):
            d = self.deeper(depth)
            self.p += 1
            return ["bin", "**", base, self.unary(d)]
        return base

    def primary(self, depth: int) -> list:
        kind, text, col = self.peek()
        if kind == "num":
            self.p += 1
            return ["num", _js_number(text), text]
        if kind == "name":
            self.p += 1
            if text in FUNCTIONS:
                if not self.is_op("("):
                    raise GlyphError(f"'{text}' is a function: write {text}(...)", col)
                open_col = self.peek()[2]
                d = self.deeper(depth)
                self.p += 1
                args: list = []
                if not self.is_op(")"):
                    args.append(self.ternary(d))
                    while self.is_op(","):
                        self.p += 1
                        args.append(self.ternary(d))
                self.close_paren(open_col)
                lo, hi = FUNCTIONS[text][0], FUNCTIONS[text][1]
                if len(args) < lo or (hi >= 0 and len(args) > hi):
                    raise GlyphError(
                        f"'{text}' takes {_arity_text(lo, hi)}, got {len(args)}", col
                    )
                return ["call", text, *args]
            known = text in CONSTANTS or text in VARIABLES
            if known and self.is_op("("):
                raise GlyphError(f"'{text}' is a value, not a function", col)
            if text in CONSTANTS:
                return ["num", CONSTANTS[text], text]
            if text in VARIABLES:
                return ["var", text]
            hint = suggest(text)
            extra = f" (did you mean '{hint}'?)" if hint else ""
            raise GlyphError(f"Unknown name '{text}'{extra}", col)
        if self.is_op("("):
            d = self.deeper(depth)
            self.p += 1
            inner = self.ternary(d)
            self.close_paren(col)
            return inner
        if kind == "end":
            raise GlyphError("The formula ends too soon", col)
        raise GlyphError(f"Expected a value, found '{text}'", col)


def parse(src: str) -> list:
    """Text -> AST (the same nested lists lang.js builds). Raises GlyphError."""
    src = "" if src is None else str(src)
    if len(src) > MAX_LENGTH:
        raise GlyphError(
            f"Keep it under {MAX_LENGTH} characters (this one has {len(src)})",
            MAX_LENGTH + 1,
        )
    if src.strip(" \t\n\r") == "":
        raise GlyphError("Write a formula, for example sin(t - r)", 1)
    parser = _Parser(src)
    ast = parser.ternary(0)
    kind, text, col = parser.peek()
    if kind != "end":
        if kind != "op" or text == "(":
            raise GlyphError(f"Missing an operator before '{text}'", col)
        raise GlyphError(f"Did not expect '{text}'", col)
    return ast


def show(node: list) -> str:
    kind = node[0]
    if kind == "num":
        return node[2]
    if kind == "var":
        return node[1]
    if kind == "neg":
        return f"(-{show(node[1])})"
    if kind == "not":
        return f"(!{show(node[1])})"
    if kind == "bin":
        return f"({show(node[2])} {node[1]} {show(node[3])})"
    if kind == "if":
        return f"({show(node[1])} ? {show(node[2])} : {show(node[3])})"
    if kind == "call":
        return f"{node[1]}({', '.join(show(a) for a in node[2:])})"
    raise ValueError(f"unknown node {kind}")


# --- AST -> closures ----------------------------------------------------------


def _div(p: float, q: float) -> float:
    try:
        return fin(p / q)
    except ZeroDivisionError:
        return 0.0


def _rem(p: float, q: float) -> float:
    try:
        return fin(math.fmod(p, q))
    except ValueError:
        return 0.0


_POW = _safe(math.pow)

BIN: dict[str, Callable[[float, float], float]] = {
    "+": lambda p, q: fin(p + q),
    "-": lambda p, q: fin(p - q),
    "*": lambda p, q: fin(p * q),
    "/": _div,
    "%": _rem,
    "**": _POW,
    "<": lambda p, q: 1.0 if p < q else 0.0,
    "<=": lambda p, q: 1.0 if p <= q else 0.0,
    ">": lambda p, q: 1.0 if p > q else 0.0,
    ">=": lambda p, q: 1.0 if p >= q else 0.0,
    "==": lambda p, q: 1.0 if p == q else 0.0,
    "!=": lambda p, q: 1.0 if p != q else 0.0,
    "&": lambda p, q: float(i32(p) & i32(q)),
    "|": lambda p, q: float(i32(p) | i32(q)),
}


def compile_ast(node: list) -> Fn:
    kind = node[0]
    if kind == "num":
        k = fin(float(node[1]))
        return lambda s: k
    if kind == "var":
        name = node[1]
        return lambda s: s[name]
    if kind == "neg":
        a = compile_ast(node[1])
        return lambda s: fin(-a(s))
    if kind == "not":
        a = compile_ast(node[1])
        return lambda s: 1.0 if a(s) == 0 else 0.0
    if kind == "bin":
        op, a, b = node[1], compile_ast(node[2]), compile_ast(node[3])
        if op == "&&":
            return lambda s: b(s) if a(s) != 0 else 0.0
        if op == "||":

            def either(s: Env) -> float:
                v = a(s)
                return v if v != 0 else b(s)

            return either
        f = BIN[op]
        return lambda s: f(a(s), b(s))
    if kind == "if":
        c, a, b = compile_ast(node[1]), compile_ast(node[2]), compile_ast(node[3])
        return lambda s: a(s) if c(s) != 0 else b(s)
    if kind == "call":
        name = node[1]
        args = [compile_ast(arg) for arg in node[2:]]
        if name == "rand" and not args:
            args.append(lambda s: s["i"])
        f = SAFE[name]
        return lambda s: f(*(arg(s) for arg in args))
    raise ValueError(f"unknown node {kind}")


def geometry(n: int) -> list[Env]:
    c = (n - 1) / 2
    dots = []
    for k in range(n * n):
        x, y = k % n, k // n
        dots.append(
            {
                "i": float(k),
                "x": float(x),
                "y": float(y),
                "n": float(n),
                "u": x - c,
                "v": y - c,
                "r": math.hypot(x - c, y - c),
                "a": math.atan2(y - c, x - c),
            }
        )
    return dots


def frame(formula: str, t: float = 0.0, n: int = 16) -> list[float]:
    """Every dot's value at time t, row by row. Raises GlyphError."""
    fn = compile_ast(parse(formula))
    out = []
    t = fin(float(t))
    for dot in geometry(n):
        dot["t"] = t
        out.append(fn(dot))
    return out


# --- Compose (mirrors compose.js draw for draw) -------------------------------


def mulberry32(seed: int) -> Callable[[], float]:
    state = seed & M32

    def nxt() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & M32
        t = state
        t = imul(t ^ (t >> 15), t | 1)
        t = (t ^ ((t + imul(t ^ (t >> 7), t | 61)) & M32)) & M32
        return ((t ^ (t >> 14)) & M32) / 4294967296

    return nxt


def _pick(r: Callable[[], float], items: list) -> Any:
    return items[math.floor(r() * len(items))]


SPEEDS = ["0.6", "1", "1.5", "2", "3"]
MOODS = {
    "slow": ["Slow", "Patient", "Sleepy", "Quiet"],
    "mid": ["Steady", "Easy", "Warm", "Little"],
    "fast": ["Quick", "Restless", "Bright", "Giddy"],
}
NUMBER_WORDS = ["", "One", "Two", "Three", "Four", "Five"]
BANDS = [
    ("x", "current"),
    ("y", "staircase"),
    ("x + y", "slope"),
    ("x - y", "drift"),
    ("abs(u) + abs(v)", "diamond"),
    ("max(abs(u), abs(v))", "frame"),
    ("u*v/4", "saddle"),
]
GATES = [
    "sin(r*0.8 - t*S)",
    "sin(a*3 + r*0.5 - t*S)",
    "sin(x*0.6 + t*S) * cos(y*0.6 - t*S)",
    "noise(x/4, y/4, t*S/2)",
]
LACES = [
    "x & y",
    "x & (y + floor(t*S))",
    "(x + floor(t*S)) & y",
    "(x + y) & (x - y + n)",
]


def _mood(r: Callable[[], float], s: str) -> str:
    k = float(s)
    return _pick(
        r, MOODS["slow"] if k < 1 else MOODS["mid"] if k < 2 else MOODS["fast"]
    )


def _ripple(r: Callable[[], float], s: str) -> tuple[str, str]:
    k = _pick(r, ["0.6", "0.8", "1", "1.3"])
    way = _pick(r, ["-", "+"])
    body = f"sin(r*{k} {way} t*{s})"
    if r() < 0.5:
        body += f" * (1 - r/{_pick(r, ['8', '10', '12'])})"
    return body, f"{_mood(r, s)} {_pick(r, ['ripple', 'pond', 'tide', 'echo'])}"


def _spiral(r: Callable[[], float], s: str) -> tuple[str, str]:
    arms = _pick(r, ["1", "2", "3", "4", "5"])
    k = _pick(r, ["0.4", "0.6", "0.9"])
    turn = _pick(r, ["+", "-"])
    body = f"sin(a*{arms} {turn} r*{k} - t*{s})"
    noun = _pick(r, ["pinwheel", "whorl", "spiral", "galaxy"])
    if arms == "1":
        return body, f"{_mood(r, s)} {noun}"
    return body, f"{NUMBER_WORDS[int(arms)]}-arm {noun}"


def _weave(r: Callable[[], float], s: str) -> tuple[str, str]:
    k1 = _pick(r, ["0.5", "0.7", "0.9", "1.2"])
    k2 = _pick(r, ["0.5", "0.7", "0.9", "1.2"])
    s2 = _pick(r, SPEEDS)
    body = f"sin(x*{k1} + t*{s}) * cos(y*{k2} - t*{s2})"
    return body, f"{_mood(r, s)} {_pick(r, ['weave', 'plaid', 'lattice', 'quilt'])}"


def _bands(r: Callable[[], float], s: str) -> tuple[str, str]:
    way, noun = _pick(r, BANDS)
    k = _pick(r, ["0.5", "0.8", "1.2"])
    return f"sin(({way})*{k} - t*{s})", f"{_mood(r, s)} {noun}"


def _clouds(r: Callable[[], float], s: str) -> tuple[str, str]:
    k = _pick(r, ["3", "4", "6"])
    gain = _pick(r, ["2", "2.5", "3"])
    body = f"noise(x/{k}, y/{k}, t*{s}/2) * {gain}"
    return body, f"{_mood(r, s)} {_pick(r, ['weather', 'smoke', 'clouds', 'fog'])}"


def _gate(r: Callable[[], float], s: str) -> tuple[str, str]:
    inner = _pick(r, GATES).replace("S", s)
    th = _pick(r, ["0", "0.3", "0.5"])
    low = _pick(r, ["0", "-0.4", "-1"])
    body = f"{inner} > {th} ? 1 : {low}"
    feel = _mood(r, s)
    return body, f"{feel} {_pick(r, ['signal', 'stencil', 'switchboard', 'code'])}"


def _lace(r: Callable[[], float], s: str) -> tuple[str, str]:
    cond = _pick(r, LACES).replace("S", s)
    k = _pick(r, ["0.3", "0.5", "0.8"])
    low = _pick(r, ["0", "-0.2"])
    body = f"({cond}) == 0 ? sin(t*{s} - r*{k}) : {low}"
    return body, f"{_mood(r, s)} {_pick(r, ['lace', 'crumbs', 'triangles', 'frost'])}"


def _rain(r: Callable[[], float], _s: str) -> tuple[str, str]:
    s = _pick(r, ["4", "6", "9"])
    gap = _pick(r, ["4", "8", "12"])
    length = _pick(r, ["3", "4", "6"])
    body = (
        f"max(0, 1 - mod(t*{s}*(1 + rand(x)) + rand(x + 50)*n - y, n + {gap})/{length})"
    )
    feel = _mood(r, s)
    return body, f"{feel} {_pick(r, ['rain', 'drizzle', 'downpour', 'monsoon'])}"


RECIPES: dict[str, Callable[[Callable[[], float], str], tuple[str, str]]] = {
    "ripple": _ripple,
    "spiral": _spiral,
    "weave": _weave,
    "bands": _bands,
    "clouds": _clouds,
    "gate": _gate,
    "lace": _lace,
    "rain": _rain,
}


def compose(seed: int) -> dict:
    seed &= M32
    r = mulberry32(seed)
    recipe = _pick(r, list(RECIPES))
    s = _pick(r, SPEEDS)
    formula, title = RECIPES[recipe](r, s)
    return {"formula": formula, "title": title, "seed": seed, "recipe": recipe}


# --- seeing a frame without a browser -----------------------------------------

POSITIVE = ["  ", "░░", "▒▒", "▓▓", "██"]
NEGATIVE = ["  ", "··", "∘∘", "oo", "OO"]


def text_art(values: list[float], n: int) -> str:
    """Two characters per dot: blocks for positive, rings for negative."""
    rows = ["┌" + "─" * (2 * n) + "┐"]
    for y in range(n):
        line = []
        for x in range(n):
            v = values[y * n + x]
            level = min(4, int(min(1.0, abs(v)) * 4 + 0.5))
            line.append((POSITIVE if v >= 0 else NEGATIVE)[level])
        rows.append("│" + "".join(line) + "│")
    rows.append("└" + "─" * (2 * n) + "┘")
    return "\n".join(rows)


def picture(values: list[float], n: int, cell: int = 24) -> tuple[int, int, bytes]:
    """An RGB picture of the field: ember dots for positive, violet for negative."""
    size = n * cell
    rgb = bytearray(bytes((11, 9, 17)) * (size * size))
    ember, violet = (255, 180, 84), (165, 139, 255)
    for k, v in enumerate(values):
        rad = min(1.0, abs(v)) * cell * 0.44
        if rad < 0.5:
            continue
        colour = ember if v >= 0 else violet
        cx, cy = (k % n + 0.5) * cell, (k // n + 0.5) * cell
        for py in range(int(cy - rad), int(cy + rad) + 1):
            for px in range(int(cx - rad), int(cx + rad) + 1):
                if (px + 0.5 - cx) ** 2 + (py + 0.5 - cy) ** 2 <= rad * rad:
                    o = (py * size + px) * 3
                    rgb[o : o + 3] = bytes(colour)
    return size, size, bytes(rgb)


# --- play.py commands ---------------------------------------------------------


def _show_frame(formula: str, t: float, n: int, png: bool) -> int:
    try:
        values = frame(formula, t, n)
    except GlyphError as exc:
        print(f"{formula}\n{' ' * (exc.col - 1)}^ column {exc.col}: {exc.message}")
        return 1
    print(text_art(values, n))
    print(f"t = {t:g}, {n} x {n} dots.  ██ positive (ember)  OO negative (violet)")
    if png:
        import kit

        folder = store.data_dir() / "glyphs-renders"
        slug = store.slugify(formula)[:40] or "piece"
        w, h, rgb = picture(values, n)
        path = kit.write_png(folder / f"{slug}-t{t:g}.png", w, h, rgb)
        print(f"picture: {path}")
    return 0


def _frame_args(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"play.py glyphs {prog}")
    parser.add_argument("--t", type=float, default=1.0, help="time in seconds")
    parser.add_argument("--n", type=int, default=16, help="dots per side, 2 to 64")
    parser.add_argument("--png", action="store_true", help="also write a picture")
    return parser


def cli_try(args: list[str]) -> int:
    parser = _frame_args("try")
    parser.add_argument("formula")
    opts = parser.parse_args(args)
    return _show_frame(opts.formula, opts.t, max(2, min(64, opts.n)), opts.png)


def cli_compose(args: list[str]) -> int:
    parser = _frame_args("compose")
    parser.add_argument("--seed", type=int, default=None)
    opts = parser.parse_args(args)
    seed = random.getrandbits(32) if opts.seed is None else opts.seed
    piece = compose(seed)
    print(f"{piece['title']}  (seed {piece['seed']}, {piece['recipe']})")
    print(piece["formula"])
    return _show_frame(piece["formula"], opts.t, max(2, min(64, opts.n)), opts.png)


PALETTES = ("ember", "tixy", "sea", "paper")
SHAPES = ("circle", "square", "diamond")


def cli_keep(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="play.py glyphs keep")
    parser.add_argument("formula")
    parser.add_argument("--name", required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--grid", type=int, default=16)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--palette", choices=PALETTES, default="ember")
    parser.add_argument("--shape", choices=SHAPES, default="circle")
    opts = parser.parse_args(args)
    try:
        parse(opts.formula)
    except GlyphError as exc:
        print(f"Not kept: column {exc.col}: {exc.message}")
        return 1
    data = {
        "formula": opts.formula,
        "grid": max(4, min(64, opts.grid)),
        "speed": max(0.0, min(4.0, opts.speed)),
        "palette": opts.palette,
        "shape": opts.shape,
    }
    row = store.save_keepsake(
        CURIO, name=opts.name, note=opts.note, data=data, author="Claude"
    )
    print(f"Kept {row['id']}")
    return 0


COMMANDS = {
    "try": (cli_try, "FORMULA [--t T] [--n N] [--png]: one frame as text art"),
    "compose": (cli_compose, "[--seed N]: a new formula, its title and a frame"),
    "keep": (cli_keep, "FORMULA --name N [--note T]: keep a piece"),
}

# --- routes ---------------------------------------------------------------------

router = APIRouter()


@router.get("/compose")
def route_compose(seed: int = 0) -> dict:
    return compose(seed)


@router.get("/frame")
def route_frame(formula: str, t: float = 1.0, n: int = 16) -> dict:
    n = max(2, min(64, n))
    try:
        values = frame(formula, t, n)
    except GlyphError as exc:
        raise HTTPException(400, f"column {exc.col}: {exc.message}") from exc
    return {"n": n, "t": t, "values": values, "text": text_art(values, n)}
