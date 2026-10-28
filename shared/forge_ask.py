"""The top bar's smart search: one question in, one short answer out.

the owner (2026-10-28, Relay task 438): a search box that answers like a Google
AI overview. Maths, the time and "which app does X" are plain rules here, with
no model and no web, so they answer while he types. Anything else goes to the
engine picked in Settings > Home screen > "Questions are answered by"
(setting `ask_answers`):

    auto    the local model when Jan is running and sure of itself, else the web
    web     the web's short answer: DuckDuckGo's instant answer, else the top
            result's snippet (shared/forge_websearch.py). The default.
    local   the Jan model picked for Forge's "ask" role, loaded when asked and
            released when idle (shared/forge_jan.py, ~/.config/forge/jan/ask.json)
    claude  Claude online (`claude -p`, a small model); uses his Claude usage
    google  no answer here, just the Google search opened in a browser

When the local model cannot answer (Jan off, no model, an error) the web
answers instead, with a note saying so.

Google's own AI overview cannot be fetched from here: a plain request gets a
"turn on JavaScript" page and headless Chrome a captcha (both tried
2026-10-28). Every web answer carries a Google link so the real overview is
one click away.

answer() is plain data in, plain data out; forge.py runs it off the GTK main
loop and hands the dict to the hub's window.forgeAsk.
"""

from __future__ import annotations

import ast
import decimal
import json
import math
import operator
import re
import subprocess
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINES = ("web", "auto", "local", "claude", "google")
DEFAULT_ENGINE = "web"
JAN_APP = "ask"
JAN_ROLE = "answer"
# small enough to load in a couple of seconds; Forge Models changes it (the
# "ask" row, ~/.config/forge/jan/ask.json)
JAN_DEFAULT = "Qwen3_5-4B-IQ4_XS"
GOOGLE = "https://www.google.com/search?q="
CLAUDE_MODEL = "haiku"
ANSWER_LIMIT = 900  # characters of answer text the dropdown shows

# --- maths -------------------------------------------------------------------

_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class _NotMaths(Exception):
    pass


def _snap(value: float) -> float:
    """sin 180 is 1.2e-16 in floats; a trig answer that small is 0."""
    return 0.0 if abs(value) < 1e-12 else value


def _tan(degrees: float) -> float:
    cos = _snap(math.cos(math.radians(degrees)))
    if cos == 0:
        raise _NotMaths("tan of a right angle")
    return _snap(math.sin(math.radians(degrees))) / cos


_FUNCS = {
    "sqrt": math.sqrt,
    "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x),
    "sin": lambda x: _snap(math.sin(math.radians(x))),
    "cos": lambda x: _snap(math.cos(math.radians(x))),
    "tan": _tan,
    "log": math.log10,
    "ln": math.log,
    "abs": abs,
    "round": lambda x: math.copysign(math.floor(abs(x) + 0.5), x),  # 2.5 is 3
    "floor": math.floor,
    "ceil": math.ceil,
    "factorial": math.factorial,
}
_NAMES = {"pi": math.pi, "e": math.e, "tau": math.tau}
_WORDS = [
    (r"\bmultiplied by\b|\btimes\b", "*"),
    (r"\bdivided by\b|\bover\b", "/"),
    (r"\bplus\b|\band\b", "+"),
    (r"\bminus\b|\btake away\b", "-"),
    (r"\bsquared\b", "**2"),
    (r"\bcubed\b", "**3"),
    (r"\bto the power of\b|\bto the\b", "**"),
    (r"\bmod\b", "%"),
    (r"\bsquare root of\b", "sqrt "),
]
_LEAD = re.compile(
    r"^(what(?:'s| is)|whats|calculate|calc|compute|work out|how much is|solve)\s+",
    re.I,
)

# a date, a phone number or a hex code is not a sum, though it parses as one
_NOT_A_SUM = re.compile(
    r"\b\d{4}-\d{1,2}-\d{1,2}\b"  # 2026-10-28
    r"|\b\d{1,2}([/.])\d{1,2}\1\d{2,4}\b"  # 1/3/2026, 28.10.26
    r"|^\+?\(?\d{3}\)?[\s-]?\d{3}-\d{4}$|^\d{3}-\d{4}$"  # 555-1234
    r"|\b\d{1,4}(?:-\d{3,4}){2,}\b"  # 1-800-555-1234
    r"|\b0[xob][0-9a-f]+\b",  # 0x10
    re.I,
)
EXACT_DIGITS = 30  # whole numbers up to this long are shown exactly (2^64 is 20)


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name) and node.id in _NAMES:
        return _NAMES[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 1000 or abs(left) > 1e6):
            raise _NotMaths("too big")
        return _BIN[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCS
        and len(node.args) == 1
        and not node.keywords
    ):
        arg = _eval(node.args[0])
        if node.func.id == "factorial" and (arg > 500 or arg != int(arg)):
            raise _NotMaths("factorial")
        return _FUNCS[node.func.id](int(arg) if node.func.id == "factorial" else arg)
    raise _NotMaths(type(node).__name__)


def _number(value: float) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _NotMaths("not a number")
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise _NotMaths("not finite")
        value = float(f"{value:.12g}")  # 0.1 + 0.2 is 0.3, not 0.30000000000000004
        if value.is_integer() and abs(value) < 1e15:
            value = int(value)
        else:
            return f"{value:.12g}"
    digits = str(abs(value))
    if len(digits) <= EXACT_DIGITS:
        return f"{value:,}"
    # too long to read: scientific, rounded from the exact digits
    lead, power = f"{decimal.Decimal(value):.9e}".split("e")
    return f"{lead.rstrip('0').rstrip('.')}e{power}"


_ADD_PCT = re.compile(r"([-+])\s*([\d.]+)\s*%(?!\s*[\d(.])")


def _percent(text: str) -> str:
    """100 + 10% is 110 and 100 + 10% + 10% is 121, as a calculator does;
    10%3 is a remainder; any other 50% is 0.5 (so 100 / 10% is 1000)."""
    while True:
        hit = _ADD_PCT.search(text)
        left = text[: hit.start()].strip() if hit else ""
        if not hit or not left or left.count("(") != left.count(")"):
            break
        sign, num = hit.group(1), hit.group(2)
        text = f"({left})*(1{sign}{num}/100)" + text[hit.end() :]
    return re.sub(r"([\d.]+)\s*%(?!\s*[\d(.])", r"(\1/100)", text)


def maths(question: str) -> dict | None:
    """A sum typed in words or symbols, worked out: {"expr", "value"}, or
    None when the text is not a sum (a lone number is not one)."""
    text = _LEAD.sub("", question.strip()).strip().rstrip("?=").strip()
    if not text or len(text) > 200 or _NOT_A_SUM.search(text):
        return None
    if re.fullmatch(r"[-+]?\s*[\d.,]+", text):
        return None  # -5 on its own is a number, not a sum
    pct = re.fullmatch(r"([\d.,]+)\s*%\s*of\s*([\d.,]+)", text, re.I)
    if pct:
        text = f"{pct.group(1)}/100*{pct.group(2)}"
    for pattern, repl in _WORDS:
        text = re.sub(pattern, repl, text, flags=re.I)
    text = text.replace("×", "*").replace("÷", "/").replace("^", "**")
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 1,000 -> 1000
    text = re.sub(r"(?<=\d)\s*x\s*(?=[\d(])", "*", text)  # 3 x 4
    text = _percent(text)
    text = re.sub(r"\b(sqrt|cbrt|log|ln|abs|sin|cos|tan)\s+([\d.]+)", r"\1(\2)", text)
    text = re.sub(r"\b([\d.]+)\s*!", r"factorial(\1)", text)
    if not re.search(r"[-+*/%(]|\b(?:" + "|".join(_FUNCS) + r")\b", text):
        return None
    if re.search(
        r"[A-Za-z_]", re.sub(r"\b(?:" + "|".join([*_FUNCS, *_NAMES]) + r")\b", "", text)
    ):
        return None
    try:
        tree = ast.parse(text, mode="eval")
        value = _number(_eval(tree))
    except (
        _NotMaths,
        SyntaxError,
        ValueError,
        ZeroDivisionError,
        OverflowError,
        TypeError,
    ):
        return None
    return {"expr": text.replace("**", "^"), "value": value}


# --- the time ----------------------------------------------------------------

_TIME = re.compile(
    r"^(what(?:'s| is)? the time|whats the time|what time is it|time now|the time)\??$",
    re.I,
)
_DATE = re.compile(
    r"^((?:what(?:'s| is)?|whats) (?:the date|today'?s date|today)|what day is (?:it|today)|today'?s date|date today)\??$",
    re.I,
)


def clock(question: str, now: float | None = None) -> str | None:
    q = question.strip()
    t = time.localtime(now)
    if _TIME.match(q):
        return time.strftime("%H:%M", t)
    if _DATE.match(q):
        # %-d is not on Windows (the portable build)
        return time.strftime(f"%A {t.tm_mday} %B %Y", t)
    return None


# --- apps --------------------------------------------------------------------

_STOP = set("""a an the is are was be to of for in on at by with and or it its this that
    my me i you your do does did can could which what where whats app apps tool
    tools has have having lets let open find show me any some there one thing
    forge program use used using how who should would will into from about""".split())
_APP_ASK = re.compile(
    r"\b(where(?:'s| is| are| do i| can i| would i)|which (?:app|tool|one)|what (?:app|tool)|app (?:for|that|to|which)"
    r"|tool (?:for|that|to)|find (?:the )?app|is there an app)\b|^(?:open|launch|start)\b",
    re.I,
)
# a question that names apps or tools may match on the feature lists alone;
# any other ("where is australia", "open a new tab") needs an app's name or
# tagline
_SAYS_APP = re.compile(r"\b(apps?|tools?)\b", re.I)


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP]


_ENDING = re.compile(r"(?:s|es|d|ed|r|er|ers|ing|ings|ion|ions|ly|ment|ments)?")


def _same(a: str, b: str, loose: bool = False) -> bool:
    """One word is the other with an ending: chat ~ chatting, remind ~
    reminders, key ~ keys. A shared start shorter than four
    letters is not enough (notes is not nothing, files is not filter), nor is
    one word inside a longer one (pass is not passwords) unless `loose`,
    for app names made of two words (notes ~ Notebook)."""
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    plural = short + ("es" if re.search(r"(s|x|z|ch|sh)$", short) else "s")
    if long_ == plural and len(short) >= 3:
        return True
    if len(short) < 4 or not long_.startswith(short[:4]):
        return False
    shared = len(short)
    while not long_.startswith(short[:shared]):
        shared -= 1
    if shared < len(short) - 1:
        return False
    if loose:
        return True
    rest = long_[shared:]
    if len(rest) > 1 and rest[0] == long_[shared - 1]:
        rest = rest[1:]  # chatting, planned
    return bool(_ENDING.fullmatch(rest))


def _has(term: str, words: set[str], loose: bool = False) -> bool:
    return term in words or any(_same(term, w, loose) for w in words)


def load_apps(dirs: list[Path] | None = None) -> list[dict]:
    """Every app's manifest boiled down to what a question can match:
    {key, label, tagline, icon, section, text}. Hidden apps are left out."""
    dirs = dirs or [
        ROOT / "apps",
        Path.home() / ".local/share/forge/store/apps",
    ]
    apps, seen = [], set()
    for base in dirs:
        for path in sorted(base.glob("*/forge_app.json")):
            try:
                m = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            key = m.get("name") or path.parent.name
            if key in seen or m.get("hidden") is True:
                continue
            seen.add(key)
            extra = m.get("manifest") if isinstance(m.get("manifest"), dict) else {}
            feats = extra.get("features")
            feats = feats if isinstance(feats, list) else []
            text = " ".join(
                [str(extra.get("summary") or ""), str(m.get("description") or "")]
                + [
                    f"{f.get('name', '')} {f.get('description', '')}"
                    for f in feats
                    if isinstance(f, dict)
                ]
                + [
                    f"{a.get('label', '')} {a.get('words', '')}"
                    for a in m.get("actions") or []
                    if isinstance(a, dict)
                ]
            )
            apps.append(
                {
                    "key": key,
                    "label": str(m.get("label") or key),
                    "tagline": str(m.get("tagline") or ""),
                    "icon": str(m.get("icon") or ""),
                    "section": str(m.get("section") or ""),
                    "text": text,
                }
            )
    return apps


_APPS: dict = {"at": 0.0, "apps": []}
APPS_TTL = 30.0  # seconds; a live answer comes on every key, the apps rarely change


def cached_apps(now: float | None = None) -> list[dict]:
    now = time.monotonic() if now is None else now
    if not _APPS["apps"] or now - _APPS["at"] > APPS_TTL:
        _APPS["apps"], _APPS["at"] = load_apps(), now
    return _APPS["apps"]


def find_apps(
    question: str, apps: list[dict], limit: int = 3, floor: float = 0.6
) -> list[dict]:
    """Apps that fit the question, best first: a name match beats words in
    the tagline, which beat words in the feature list."""
    terms = list(dict.fromkeys(_words(question)))
    if not terms:
        return []
    q = question.lower()
    hits = []
    for i, app in enumerate(apps):
        label = app["label"].lower()
        name = set(_words(app["label"])) | {app["key"].lower()}
        tag = set(_words(app["tagline"]))
        body = set(_words(app["text"]))
        score = 0.0
        if re.search(r"\b" + re.escape(label) + r"\b", q):
            score += 4
        for t in terms:
            if _has(t, name, loose=True):
                score += 3
            elif _has(t, tag):
                score += 1.5
            elif _has(t, body):
                score += 0.6
        score /= max(1, len(terms)) ** 0.5
        if score >= floor:
            hits.append((score, i, app))
    hits.sort(key=lambda h: (-h[0], h[1]))
    # a stray feature word does not sit beside a name match
    hits = [h for h in hits if h[0] >= hits[0][0] * 0.4] if hits else []
    return [
        {
            "key": a["key"],
            "label": a["label"],
            "tagline": a["tagline"],
            "icon": a["icon"],
            "section": a["section"],
            "score": round(s, 2),
        }
        for s, _i, a in hits[:limit]
    ]


def is_app_question(question: str) -> bool:
    return bool(_APP_ASK.search(question))


# --- the engines -------------------------------------------------------------


def google_url(question: str) -> str:
    return GOOGLE + urllib.parse.quote_plus(question.strip())


def _clip(text: str, limit: int = ANSWER_LIMIT) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _fits(question: str, text: str) -> bool:
    """Most of the question's own words turn up in the text."""
    terms = set(_words(question)) - {"best", "good", "top", "near", "much", "many"}
    have = set(_words(text))
    found = sum(1 for t in terms if _has(t, have))
    return not terms or found >= math.ceil(len(terms) * 0.6)


def web_answer(question: str, search=None, instant=None, wiki=None) -> dict:
    """The web's short answer: an instant answer when there is one, else the
    top results' snippets, else the best-fitting Wikipedia article's opening
    (DuckDuckGo turns a quick run of searches away with a bot check)."""
    import forge_websearch

    instant = instant or forge_websearch.instant
    search = search or forge_websearch.search
    wiki = wiki or forge_websearch.wikipedia
    got = instant(question)
    try:
        results = [] if got and got.get("text") else search(question, limit=3)
    except OSError:
        results = []
    if not results and not (got and got.get("text")):
        got = wiki(question)
        if got and not _fits(
            question, f"{got.get('source', '')} {got.get('text', '')}"
        ):
            got = None  # an article that only shares a word is no answer
    if got and got.get("text"):
        return {
            "text": _clip(got["text"]),
            "source": got.get("source") or "",
            "url": got.get("url") or "",
        }
    if not results:
        return {"text": "", "source": "", "url": ""}
    top = results[0]
    return {
        "text": _clip(top.snippet),
        "source": top.title,
        "url": top.url,
        "more": [{"title": r.title, "url": r.url} for r in results[1:3]],
    }


SYSTEM = (
    "You answer questions typed into a desktop search box. Reply in at most "
    "three short sentences of plain text, no markdown. If you are not sure, "
    "say so briefly."
)

_JAN = None
_JAN_LOCK = threading.Lock()  # two quick questions must not make two watchers


def jan():
    """Forge's own Jan handle for the "ask" role; its watcher releases the
    model once nothing has used it for the idle minutes in its settings."""
    global _JAN
    with _JAN_LOCK:
        if _JAN is None:
            import forge_jan

            owner = forge_jan.AppJan(JAN_APP, roles=(JAN_ROLE,), log=lambda _m: None)
            if not forge_jan.settings_path(JAN_APP).is_file():
                # written once, so Forge Models lists the ask role to change
                owner.update({"models": {JAN_ROLE: JAN_DEFAULT}})
            owner.watch()
            _JAN = owner
    return _JAN


def shutdown() -> list[str]:
    """Forge is closing: release the ask model now rather than leave it
    loaded in Jan until Jan's own idle timer. Returns the models released."""
    global _JAN
    with _JAN_LOCK:
        owner, _JAN = _JAN, None
    return owner.stop() if owner is not None else []


# the model speaking about itself, not advice ("if you are not sure, ...")
_UNSURE = re.compile(
    r"\bI(?:'m| am) (?:not (?:sure|certain)|unsure)\b"
    r"|\bI (?:don'?t|do not) (?:know|have (?:access|real-time|current))\b"
    r"|\bI (?:cannot|can'?t) (?:say|know|answer|be sure|confirm)\b"
    r"|\bas of my (?:last|knowledge)\b",
    re.I,
)


def local_answer(question: str) -> dict:
    import forge_jan

    if not forge_jan.router_alive():
        raise RuntimeError("Jan is not running")
    owner = jan()
    model = owner.model_for(JAN_ROLE, JAN_DEFAULT)
    if not model:
        raise RuntimeError("Jan has no model to answer with")
    with owner.using(model):
        text = forge_jan.chat(
            model, SYSTEM, question, temperature=0.3, max_tokens=260, timeout=90
        )
    return {"text": _clip(text), "source": f"Local model ({model})", "url": ""}


def claude_answer(question: str, run=subprocess.run) -> dict:
    # a bare answerer: no tools, no MCP servers, no project or user settings,
    # run from an empty folder so no CLAUDE.md is read (3.5 s, 2026-10-28)
    with tempfile.TemporaryDirectory(prefix="forge-ask-") as cwd:
        done = run(
            [
                "claude",
                "-p",
                "--model",
                CLAUDE_MODEL,
                "--strict-mcp-config",
                "--tools",
                "",
                "--setting-sources",
                "",
                "--system-prompt",
                SYSTEM,
                f"Question: {question}",  # never read as an option ("-5 ...")
            ],
            capture_output=True,
            text=True,
            timeout=90,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
        )
    if done.returncode != 0:
        raise RuntimeError(
            (done.stderr or done.stdout or "claude failed").strip()[:200]
        )
    return {"text": _clip(done.stdout), "source": "Claude (online)", "url": ""}


def engine_setting() -> str:
    try:
        import forge_theme

        pick = forge_theme.load().get("ask_answers")
    except Exception:  # noqa: BLE001 -- a bad settings file still answers
        pick = None
    return pick if pick in ENGINES else DEFAULT_ENGINE


def open_url(url: str, browser: str = "", post=None, opener=None) -> str:
    """Open a link from an answer: in the Forge Browser (its backend at
    `browser`, e.g. http://127.0.0.1:8444) when there is one, else in the
    desktop's own browser. Returns where it went: "browser" or "desktop"."""
    if not re.match(r"https?://", url or ""):
        raise ValueError("not a web link")
    if browser and re.match(r"http://127\.0\.0\.1:\d+$", browser):
        post = post or _post_json
        try:
            post(browser + "/api/agent/do", {"op": "open", "url": url, "timeout": 30})
            return "browser"
        except OSError:
            pass
    (opener or webbrowser.open)(url)  # the desktop's browser, on any system
    return "desktop"


def _post_json(url: str, body: dict) -> dict:
    import urllib.request

    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Forge": "1"},
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        return json.loads(response.read() or b"{}")


# --- one question ------------------------------------------------------------


def answer(
    req: dict,
    apps: list[dict] | None = None,
    engine: str | None = None,
    engines: dict | None = None,
) -> dict:
    """One hub request {"q", "id", "live"} to its answer. "live" (sent while
    typing) runs the rules only; Enter sends it without, and then a question
    the rules cannot answer goes to the engine. The answer always has
    "kind": maths | clock | apps | web | local | claude | google | none | error,
    and "note" when the web stood in for the local model."""
    if req.get("op") == "open":
        try:
            went = open_url(str(req.get("url") or ""), str(req.get("browser") or ""))
            return {"id": req.get("id"), "kind": "opened", "where": went}
        except (OSError, ValueError) as e:
            return {"id": req.get("id"), "kind": "error", "text": str(e)}
    q = str(req.get("q") or "").strip()[:500]
    out: dict = {"id": req.get("id"), "q": q, "google": google_url(q) if q else ""}
    if not q:
        return {**out, "kind": "none"}
    sum_ = maths(q)
    if sum_:
        return {**out, "kind": "maths", "text": sum_["value"], "expr": sum_["expr"]}
    told = clock(q)
    if told:
        return {**out, "kind": "clock", "text": told}
    apps = cached_apps() if apps is None else apps
    if is_app_question(q):
        found = find_apps(q, apps, floor=0.6 if _SAYS_APP.search(q) else 1.5)
        if found:
            return {**out, "kind": "apps", "apps": found}
    if req.get("live"):
        return {**out, "kind": "none"}
    engine = engine or engine_setting()
    if engine == "google":
        return {**out, "kind": "google"}
    runs = {"web": web_answer, "local": local_answer, "claude": claude_answer}
    runs.update(engines or {})
    kind, note = engine, ""
    try:
        if engine in ("local", "auto"):
            kind = "local"
            try:
                got = runs["local"](q)
            except Exception as e:  # noqa: BLE001 -- the web answers instead
                kind, note = (
                    "web",
                    f"The local model did not answer ({_clip(str(e), 120)}), so this is from the web.",
                )
                got = runs["web"](q)
            else:
                if engine == "auto" and (
                    not got.get("text") or _UNSURE.search(got["text"])
                ):
                    kind, note = (
                        "web",
                        "The local model was not sure, so this is from the web.",
                    )
                    got = runs["web"](q)
        else:
            kind = engine if engine in runs else "web"
            got = runs[kind](q)
    except Exception as e:  # noqa: BLE001 -- the hub waits on an answer
        return {**out, "kind": "error", "engine": kind, "text": _clip(str(e), 200)}
    # apps beside a web answer only on a strong match (a name or tagline)
    found = find_apps(q, apps, limit=2, floor=1.5)
    return {
        **out,
        "kind": kind,
        **got,
        "apps": found,
        **({"note": note} if note else {}),
    }
