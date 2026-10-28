"""The top bar's smart search (shared/forge_ask.py, Relay task 438): the
rules that answer with no model and no web, and the routing to the engine
picked in Settings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))

import forge_ask  # noqa: E402
import forge_websearch  # noqa: E402

APPS = [
    {
        "key": "browser",
        "label": "Browser",
        "tagline": "An everyday browser",
        "icon": "",
        "section": "research",
        "text": "Tabs bookmarks downloads saved passwords find on page",
    },
    {
        "key": "calendar",
        "label": "Calendar",
        "tagline": "Your days and reminders",
        "icon": "",
        "section": "life",
        "text": "Events reminders weekly view",
    },
    {
        "key": "backup",
        "label": "Backup",
        "tagline": "Copies of your files to the Vault drive",
        "icon": "",
        "section": "system",
        "text": "Snapshots restore schedule",
    },
]


def test_maths_in_symbols_and_words():
    cases = {
        "2+2": "4",
        "what is 12 * 7?": "84",
        "15% of 80": "12",
        "3 x 4": "12",
        "2^10": "1,024",
        "sqrt 144": "12",
        "10 divided by 4": "2.5",
        "5 plus 6 times 2": "17",
        "1,000 + 1": "1,001",
        "5!": "120",
        "(1+2)*3=": "9",
        "sin(30)": "0.5",
    }
    for text, want in cases.items():
        got = forge_ask.maths(text)
        assert got and got["value"] == want, (text, got)


def test_not_maths():
    for text in [
        "42",
        "what is the capital of france",
        "open browser",
        "",
        "1/0",
        "9**9**9",
        "__import__('os')",
        "2 + x",
        "e",
    ]:
        assert forge_ask.maths(text) is None, text


def test_clock():
    now = 1793174400.0
    assert forge_ask.clock("what time is it?", now)
    assert "2026" in (forge_ask.clock("what's the date", now) or "")
    assert forge_ask.clock("whats the time", now)
    assert forge_ask.clock("time travel films", now) is None


def test_app_questions_find_the_right_app():
    for q, key in [
        ("where is the browser", "browser"),
        ("which app has reminders", "calendar"),
        ("which app does snapshots", "backup"),
        ("open calendar", "calendar"),
    ]:
        assert forge_ask.is_app_question(q), q
        found = forge_ask.find_apps(q, APPS)
        assert found and found[0]["key"] == key, (q, found)


def test_unrelated_words_find_no_app():
    assert forge_ask.find_apps("which app makes pancakes", APPS) == []


def test_real_manifests_load():
    apps = forge_ask.load_apps()
    keys = {a["key"] for a in apps}
    assert "settings" in keys
    found = forge_ask.find_apps("where is settings", apps)
    assert found[0]["key"] == "settings"


def test_rules_answer_before_any_engine():
    def boom(_q):
        raise AssertionError("engine called")

    engines = {"web": boom, "local": boom, "claude": boom}
    a = forge_ask.answer({"q": "2*21", "id": 1}, APPS, "web", engines)
    assert a["kind"] == "maths" and a["text"] == "42" and a["id"] == 1
    a = forge_ask.answer({"q": "where is backup", "id": 2}, APPS, "web", engines)
    assert a["kind"] == "apps" and a["apps"][0]["key"] == "backup"


def test_live_never_reaches_an_engine():
    def boom(_q):
        raise AssertionError("engine called")

    a = forge_ask.answer(
        {"q": "who wrote dune", "live": True}, APPS, "web", {"web": boom}
    )
    assert a["kind"] == "none"
    assert a["google"].startswith("https://www.google.com/search?q=who+wrote+dune")


def test_enter_goes_to_the_picked_engine():
    a = forge_ask.answer(
        {"q": "who wrote dune"},
        APPS,
        "local",
        {
            "local": lambda q: {
                "text": "Frank Herbert.",
                "source": "Local model (x)",
                "url": "",
            }
        },
    )
    assert a["kind"] == "local" and a["text"] == "Frank Herbert."
    a = forge_ask.answer({"q": "who wrote dune"}, APPS, "google")
    assert a["kind"] == "google" and "dune" in a["google"]


def test_engine_failure_is_an_error_answer():
    def broken(_q):
        raise RuntimeError("claude failed")

    a = forge_ask.answer({"q": "who wrote dune"}, APPS, "claude", {"claude": broken})
    assert a["kind"] == "error" and "claude" in a["text"]


WEB = {"text": "Frank Herbert.", "source": "Wikipedia", "url": "https://w"}


def test_local_failure_falls_back_to_the_web():
    def broken(_q):
        raise RuntimeError("Jan is not running")

    for engine in ("local", "auto"):
        a = forge_ask.answer(
            {"q": "who wrote dune"},
            APPS,
            engine,
            {"local": broken, "web": lambda q: WEB},
        )
        assert a["kind"] == "web" and a["text"] == "Frank Herbert.", engine
        assert "Jan is not running" in a["note"]


def test_auto_keeps_a_sure_local_answer_and_asks_the_web_when_unsure():
    sure = {"text": "Frank Herbert wrote it.", "source": "Local model (x)", "url": ""}
    unsure = {"text": "I'm not sure who wrote that.", "source": "Local", "url": ""}
    advice = "If you are not sure which size to buy, go one size up."
    assert not forge_ask._UNSURE.search(advice)
    assert not forge_ask._UNSURE.search('You cannot say "less people" here.')
    assert forge_ask._UNSURE.search("I don't know the current price.")
    web = {"web": lambda q: WEB}
    a = forge_ask.answer(
        {"q": "who wrote dune"}, APPS, "auto", {**web, "local": lambda q: sure}
    )
    assert a["kind"] == "local" and "note" not in a
    a = forge_ask.answer(
        {"q": "who wrote dune"}, APPS, "auto", {**web, "local": lambda q: unsure}
    )
    assert a["kind"] == "web" and "not sure" in a["note"]
    # "local" on its own keeps whatever the model said
    a = forge_ask.answer(
        {"q": "who wrote dune"}, APPS, "local", {**web, "local": lambda q: unsure}
    )
    assert a["kind"] == "local"


def test_maths_edge_cases():
    cases = {
        "10%3": "1",
        "10 % 3": "1",
        "10 mod 3": "1",
        "100 + 10%": "110",
        "200 - 15%": "170",
        "50%": "0.5",
        "sin 180": "0",
        "cos(90)": "0",
        "0.1 + 0.2": "0.3",
        "2^64": "18,446,744,073,709,551,616",
        "2^100": "1.2676506e+30",
        "30!": "2.652528598e+32",
        "-(2^100)": "-1.2676506e+30",
        "3^70": "2.503155505e+33",
        "100 / 10%": "1,000",
        "10 / 50%": "20",
        "2^50%": "1.41421356237",
        "100+10%+10%": "121",
        "100 - 10% - 10%": "81",
        "(100)+10%": "110",
        "10 - 5%": "9.5",
        "round(2.5)": "3",
    }
    for text, want in cases.items():
        got = forge_ask.maths(text)
        assert got and got["value"] == want, (text, got)
    for text in [
        "2026-10-28",
        "555-1234",
        "1-800-555-1234",
        "1/3/2026",
        "28.10.26",
        "0x10",
        "tan 90",
        "-5",
    ]:
        assert forge_ask.maths(text) is None, text
    # a sum that only looks like a date part still works
    assert (forge_ask.maths("10/5/2") or {}).get("value") == "1"
    assert (forge_ask.maths("10-5-2") or {}).get("value") == "3"


def test_word_endings_match_without_a_stemmer():
    assert forge_ask._same("chat", "chatting")
    assert forge_ask._same("reminders", "remind")
    assert forge_ask._same("key", "keys")
    assert not forge_ask._same("notes", "nothing")
    assert not forge_ask._same("files", "filter")
    assert not forge_ask._same("not", "notes")
    assert forge_ask._same("notes", "notebook", loose=True)
    assert not forge_ask._same("pass", "passwords")
    assert not forge_ask._same("back", "backup")
    apps = APPS + [
        {
            "key": "notes",
            "label": "Notes",
            "tagline": "Quick notes",
            "icon": "",
            "section": "life",
            "text": "Write things down",
        }
    ]
    found = forge_ask.find_apps("which app keeps notes", apps)
    assert found and found[0]["key"] == "notes"
    assert forge_ask.find_apps("which app has nothing", apps) == []


def test_place_and_errand_questions_are_not_app_questions():
    store = APPS + [
        {
            "key": "store",
            "label": "Store",
            "tagline": "Get more apps",
            "icon": "",
            "section": "system",
            "text": "Install apps keys",
        }
    ]
    called = []

    def web(q):
        called.append(q)
        return WEB

    for q in [
        "where is australia",
        "where are the keys",
        "is the corner store open on sunday",
        "can you open a jar",
        "open a new tab",
        "start the car",
        "launch codes",
    ]:
        a = forge_ask.answer({"q": q}, store, "web", {"web": web})
        assert a["kind"] == "web", (q, a)
    assert len(called) == 7
    # naming an app, or starting with open, still finds it
    for q, key in [
        ("open the store", "store"),
        ("where can i get more apps", "store"),
        ("which app installs apps", "store"),
        ("where is the browser", "browser"),
    ]:
        a = forge_ask.answer({"q": q}, store, "web", {"web": web})
        assert a["kind"] == "apps" and a["apps"][0]["key"] == key, (q, a)


def test_shutdown_releases_the_ask_model():
    class Owner:
        stopped = 0

        def stop(self):
            Owner.stopped += 1
            return ["m"]

    forge_ask._JAN = Owner()
    assert forge_ask.shutdown() == ["m"] and Owner.stopped == 1
    assert forge_ask._JAN is None and forge_ask.shutdown() == []


def test_empty_question():
    assert forge_ask.answer({"q": "  "}, APPS)["kind"] == "none"


def test_web_answer_prefers_the_instant_answer():
    got = forge_ask.web_answer(
        "dune author",
        search=lambda q, limit: [],
        instant=lambda q: {
            "text": "Frank Herbert wrote Dune.",
            "source": "Wikipedia",
            "url": "https://w",
        },
    )
    assert got["text"] == "Frank Herbert wrote Dune." and got["source"] == "Wikipedia"


def test_web_answer_falls_back_to_the_top_result():
    results = [
        forge_websearch.Result("Dune", "https://a", "Dune is a 1965 novel."),
        forge_websearch.Result("B", "https://b", "b"),
    ]
    got = forge_ask.web_answer(
        "dune",
        search=lambda q, limit: results,
        instant=lambda q: None,
        wiki=lambda q: {"text": "wrong"},
    )
    assert got["text"] == "Dune is a 1965 novel." and got["url"] == "https://a"
    assert got["more"] == [{"title": "B", "url": "https://b"}]


def test_claude_answer_uses_the_cli():
    class Done:
        returncode = 0
        stdout = "Paris.\n"
        stderr = ""

    seen = {}

    def run(argv, **kw):
        seen["argv"] = argv
        seen["cwd"] = kw.get("cwd")
        return Done()

    got = forge_ask.claude_answer("capital of france", run=run)
    argv = seen["argv"]
    assert got["text"] == "Paris." and argv[:2] == ["claude", "-p"]
    # a bare answerer: no tools, no MCP, no settings, an empty folder
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in argv and argv[-1].endswith("capital of france")
    assert seen["cwd"] and not Path(seen["cwd"]).exists()


def test_instant_parses_duckduckgo(monkeypatch):
    monkeypatch.setattr(
        forge_websearch,
        "_get",
        lambda url, timeout, form=None: '{"Answer": "", "AbstractText": "Mount Everest is the highest.", '
        '"AbstractSource": "Wikipedia", "AbstractURL": "https://en.wikipedia.org/wiki/Everest"}',
    )
    got = forge_websearch.instant("everest")
    assert got == {
        "text": "Mount Everest is the highest.",
        "source": "Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Everest",
    }
    monkeypatch.setattr(forge_websearch, "_get", lambda *a, **k: "not json")
    assert forge_websearch.instant("everest") is None


def test_open_url_goes_to_the_forge_browser_then_the_desktop():
    sent, opened = [], []
    got = forge_ask.open_url(
        "https://www.google.com/search?q=x",
        "http://127.0.0.1:8444",
        post=lambda u, b: sent.append((u, b)),
        opener=opened.append,
    )
    assert got == "browser" and sent[0][0] == "http://127.0.0.1:8444/api/agent/do"
    assert sent[0][1]["op"] == "open" and not opened

    def down(_u, _b):
        raise OSError("refused")

    got = forge_ask.open_url(
        "https://a.example", "http://127.0.0.1:8444", post=down, opener=opened.append
    )
    assert got == "desktop" and opened == ["https://a.example"]
    # only a local backend is posted to, and only web links are opened
    got = forge_ask.open_url(
        "https://a.example", "http://evil.example", post=down, opener=opened.append
    )
    assert got == "desktop"
    try:
        forge_ask.open_url("file:///etc/passwd", "", opener=opened.append)
        raise AssertionError("opened a file link")
    except ValueError:
        pass


def test_web_answer_falls_back_to_wikipedia_when_turned_away():
    def refused(q, limit):
        raise OSError("bot check")

    got = forge_ask.web_answer(
        "capital of australia",
        search=refused,
        instant=lambda q: None,
        wiki=lambda q: {
            "text": "Canberra is the capital city of Australia.",
            "source": "Wikipedia: Canberra",
            "url": "https://w/Canberra",
        },
    )
    assert got["text"].startswith("Canberra") and got["source"] == "Wikipedia: Canberra"
    nothing = forge_ask.web_answer(
        "zzqx", search=lambda q, limit: [], instant=lambda q: None, wiki=lambda q: None
    )
    assert nothing["text"] == ""


def test_a_wikipedia_article_that_only_shares_a_word_is_no_answer():
    got = forge_ask.web_answer(
        "best pizza in london",
        search=lambda q, limit: [],
        instant=lambda q: None,
        wiki=lambda q: {
            "text": "Chuck E. Cheese is a chain that serves pizza.",
            "source": "Wikipedia: Chuck E. Cheese",
            "url": "u",
        },
    )
    assert got["text"] == ""


def test_forge_py_bridge_answers_and_survives_a_crash(monkeypatch):
    import pytest

    pytest.importorskip("gi")  # the launcher imports Gtk: system python
    root = Path(__file__).resolve().parents[1]
    if not (root / "forge.py").exists():
        pytest.skip("forge.py, the desktop launcher, is not in this release")
    sys.path.insert(0, str(root))
    import forge  # noqa: E402  # pyright: ignore[reportMissingImports]

    got = forge.ask_answer({"q": "6*7", "id": 9})
    assert got["kind"] == "maths" and got["text"] == "42" and got["id"] == 9

    def broken(_req):
        raise RuntimeError("boom")

    monkeypatch.setattr(forge_ask, "answer", broken)
    got = forge.ask_answer({"q": "x", "id": 3})
    assert got["kind"] == "error" and got["id"] == 3
