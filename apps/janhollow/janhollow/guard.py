"""The quality guard: nothing a model says reaches the screen unchecked.

the owner's condition for running local models at all was "as long as the outputs
are fine", so this module is the price of admission rather than a nicety. A
0.8B model is fast and cheap and wrong often enough that a station full of its
unfiltered output would read as broken.

Two jobs:

1. **Get the line out.** The model is asked for {"line": "..."} and usually
   obliges, but it also returns bare quoted strings, fenced code blocks and
   JSON with a stray trailing comma. `extract` copes with all of those and
   gives up honestly when it cannot.
2. **Judge it.** CHECKS is a registry: a name, why the rule exists, and a
   function. Adding a rule is one entry, and every rule is a pure function of
   the line and its context, so the whole guard is testable with no Jan running
   at all -- which is most of what tests/test_voices.py does.

Every rejection is written to rejected.jsonl in the game's data folder, capped,
because the plan asks for "a small log of rejected samples" and because the way
to tune a prompt is to read what it actually produced.
"""

from __future__ import annotations

import json
import os
import re

# The prompt asks for at most 18 words. Twenty is the hard limit, which leaves
# a little room for a good sentence and rejects the prose a small model slips
# into -- "A small smile tugged at the corners of my mouth as the silence
# stretched" is 22 words of narration, and the retry after it is usually speech.
MAX_WORDS = 20
MAX_CHARS = 240
REJECT_LOG_CAP = 200

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_JSON_OBJECT = re.compile(r"\{.*\}", re.S)
_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)
_ASCII_LETTERS = re.compile(r"[A-Za-z]")
_NAME_LABEL = re.compile(r"^\s*[A-Z][\w'’-]{1,20}\s*:\s*")
_WORD = re.compile(r"[\w'’-]+", re.UNICODE)
# A reply cut off at the token limit never closes its brace, so the object
# regex above cannot see it. This pulls the value out of the wreckage rather
# than dropping a line that was perfectly good up to the cut.
_UNCLOSED = re.compile(r'"' + r"(?P<key>\w+)" + r'"\s*:\s*"(?P<value>[^"]{2,})', re.S)
_SCAFFOLD = re.compile(r'[{}]|"\s*:\s*"')


def extract(raw: str, key: str = "line") -> tuple[str, str]:
    """(line, how) from whatever the model sent. `how` is json, bare or none."""
    text = (raw or "").strip()
    if not text:
        return "", "none"
    text = _FENCE.sub("", text).strip()

    match = _JSON_OBJECT.search(text)
    if match:
        blob = match.group(0)
        for candidate in (blob, blob.replace(",\n}", "\n}").replace(",}", "}")):
            try:
                parsed = json.loads(candidate)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return _tidy(value), "json"
                # A model that ignores the key name but answers in one field.
                strings = [
                    v for v in parsed.values() if isinstance(v, str) and v.strip()
                ]
                if len(strings) == 1:
                    return _tidy(strings[0]), "json"
                # It answered in the right shape with nothing in it. Falling
                # back to the raw text here would hand the JSON itself to a
                # speech bubble, which is how {"line": ""} once passed.
                return "", "none"
            break

    unclosed = _UNCLOSED.search(text)
    if unclosed:
        # Prefer the key we asked for; take the only one there is otherwise.
        for candidate in _UNCLOSED.finditer(text):
            if candidate.group("key") == key:
                return _tidy(candidate.group("value")), "json"
        return _tidy(unclosed.group("value")), "json"

    first = text.split("\n")[0]
    return _tidy(first), "bare" if first.strip() else "none"


def _tidy(value: str) -> str:
    line = value.strip()
    line = _FENCE.sub("", line).strip()
    for pair in ('""', "''", "“”", "‘’"):
        if len(line) > 1 and line[0] == pair[0] and line[-1] == pair[1]:
            line = line[1:-1].strip()
    return line.strip()


# --- the rules --------------------------------------------------------------
#
# Each takes (line, context) and returns a problem, or "" when it is happy.
# context carries: speaker, listener, recent (lines said lately), example.


def _empty(line, context):
    return "nothing was said" if not line.strip() else ""


def _no_letters(line, context):
    return "no words in it" if not _LETTERS.search(line) else ""


def _too_long(line, context):
    words = _WORD.findall(line)
    if len(words) > MAX_WORDS or len(line) > MAX_CHARS:
        return f"too long ({len(words)} words)"
    return ""


def _not_english(line, context):
    """Small models drift into another language mid-run. Letters that are not
    ASCII are the cheap, dependency-free signal for it."""
    letters = _LETTERS.findall(line)
    if not letters:
        return ""
    ascii_letters = _ASCII_LETTERS.findall(line)
    if len(ascii_letters) / len(letters) < 0.85:
        return "not English"
    return ""


def _narration(line, context):
    if line.startswith(("*", "(", "[", "_", "{")):
        return "narration, not speech"
    if _SCAFFOLD.search(line):
        return "the reply's own JSON leaked into the line"
    if "<think" in line.lower() or "</think" in line.lower():
        return "thinking leaked into the line"
    if re.search(r"\*[^*]+\*", line):
        return "narration, not speech"
    return ""


def _name_label(line, context):
    return "starts with a name label" if _NAME_LABEL.match(line) else ""


def _talks_about_itself(line, context):
    """The commonest slip: the speaker refers to themselves in the third person
    -- "Bo is certainly looking for a good start" -- which reads as a stage
    direction rather than a person talking."""
    own = (context.get("speaker") or "").split()[:1]
    if not own:
        return ""
    first = own[0]
    if re.search(rf"\b{re.escape(first)}\b", line, re.IGNORECASE):
        return "refers to itself by name"
    return ""


# Narration wearing speech's clothes. Every pattern is real 0.8B output from
# 2026-09-16 that passed every other rule: short, English, first person, under
# the word cap -- and still a stage direction rather than a line.
_PROSE_PATTERNS = (
    (
        re.compile(r"^(you see|you watch|you notice|you hear|you feel)\b", re.I),
        "narrates at the listener",
    ),
    (
        re.compile(r"\b(she|he|they)\s+\w+ed\b", re.I),
        "past-tense narration about someone",
    ),
    (
        re.compile(r"'s\s+(smile|face|eyes|voice|grin|expression|smirk)\b", re.I),
        "describes a person's face",
    ),
    (
        re.compile('["\u201c][^"\u201d]{6,}["\u201d]'),
        "quotes dialogue inside a spoken line",
    ),
)


def _prose(line, context):
    """A line that tells a story rather than being said out loud.

    "Mira's smile softened as she looked at your empty plate" is ten words of
    plain English in which nobody speaks. Nothing else here catches it: the
    length cap does not, and the self-reference rule only watches the speaker.
    """
    for pattern, why in _PROSE_PATTERNS:
        if pattern.search(line):
            return why
    return ""


def _echo(line, context):
    """An example in the prompt gets copied verbatim, and a model asked twice in
    a row will happily say the same thing twice."""
    flat = _flatten(line)
    if context.get("example") and flat == _flatten(context["example"]):
        return "copied the example"
    for recent in context.get("recent") or ():
        if flat == _flatten(recent):
            return "said again"
    return ""


def _parrot(line, context):
    """Saying the last line back, slightly reworded.

    The exact-match rule above never fired on this, because a 0.8B does not
    repeat verbatim -- it repeats the shape. Three crew lines in a row began
    "I'll check Vessa" on 2026-09-16, which reads as a stuck record rather than
    a conversation. Two cheap signals catch it: a shared run of four words, or
    the same three words to start with.
    """
    words = _flatten(line).split()
    if len(words) < 3:
        return ""
    for recent in context.get("recent") or ():
        other = _flatten(recent).split()
        if not other:
            continue
        if words[:3] == other[:3]:
            return "starts the same way as the last line"
        runs = {tuple(other[i : i + 4]) for i in range(max(0, len(other) - 3))}
        if any(tuple(words[i : i + 4]) in runs for i in range(max(0, len(words) - 3))):
            return "repeats a phrase from the last line"
    return ""


def _repetition(line, context):
    words = [w.lower() for w in _WORD.findall(line)]
    run = 1
    for i in range(1, len(words)):
        run = run + 1 if words[i] == words[i - 1] else 1
        if run >= 3:
            return "stuck repeating a word"
    if len(words) >= 8 and len(set(words)) <= len(words) // 3:
        return "stuck repeating itself"
    return ""


def _flatten(text):
    return " ".join(_WORD.findall((text or "").lower()))


CHECKS = {
    "empty": {"why": "the model returned nothing usable", "check": _empty},
    "no_letters": {"why": "punctuation or digits only", "check": _no_letters},
    "too_long": {"why": "a speech bubble has to fit on screen", "check": _too_long},
    "not_english": {
        "why": "small models drift into another language",
        "check": _not_english,
    },
    "narration": {
        "why": "asterisks and parentheses are stage directions",
        "check": _narration,
    },
    "prose": {
        "why": "narration that reads like speech until you look at it",
        "check": _prose,
    },
    "name_label": {
        "why": "the speaker is already named on screen",
        "check": _name_label,
    },
    "self_third_person": {
        "why": "people do not say their own name to your face",
        "check": _talks_about_itself,
    },
    "echo": {"why": "copying the example or the last line", "check": _echo},
    "parrot": {"why": "saying the last line back in other words", "check": _parrot},
    "repetition": {"why": "a small model looping", "check": _repetition},
}


def judge(line: str, context: dict | None = None) -> list[str]:
    """Every problem with this line; empty means it may be said aloud."""
    context = context or {}
    problems = []
    for name, rule in CHECKS.items():
        problem = rule["check"](line, context)
        if problem:
            problems.append(f"{name}: {problem}")
    return problems


def check(raw: str, context: dict | None = None, key: str = "line"):
    """(line, problems). A line with problems is never shown."""
    line, how = extract(raw, key=key)
    context = dict(context or {}, how=how)
    return line, judge(line, context)


# --- the rejected log -------------------------------------------------------


def log_rejection(folder: str, raw: str, line: str, problems, context=None) -> str:
    """Append one rejected sample, keeping the file small.

    Kept as JSON lines because the point of it is to be read by a person -- or
    by the next session tuning the prompt -- not parsed by the game.
    """
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "rejected.jsonl")
    entry = {
        "raw": (raw or "")[:400],
        "line": line[:300],
        "problems": problems,
        "speaker": (context or {}).get("speaker", ""),
        "listener": (context or {}).get("listener", ""),
        "where": (context or {}).get("where", ""),
    }
    lines = []
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except OSError:
            lines = []
    lines.append(json.dumps(entry, ensure_ascii=False))
    if len(lines) > REJECT_LOG_CAP:
        lines = lines[-REJECT_LOG_CAP:]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return path
