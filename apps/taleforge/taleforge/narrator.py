"""Jan as narrator and voice. The engine has already decided everything; Jan
is handed the facts and asked to tell them well. Two roles, each its own
model setting (shared/forge_jan.py): `dialogue` for companions and NPCs (a
small fast model), `narration` for the world (a larger one).

Jan runs on one background worker. The fallback text is already in the log,
so a slow or missing Jan only means the hand-written words stay."""

from __future__ import annotations

import queue
from typing import Any
import re
import threading
from pathlib import Path
import sys

ROLES = ("dialogue", "narration")
# LFM2.5 1.2B for both: on Taleforge's own
# prompts it wrote 19 tok/s on the CPU, a line in about 5 s, where the 4B
# wrote 5 tok/s and took 19 s, and it kept to the facts better than Qwen3
# 1.7B or Gemma 3 1B (~/Forge/docs/library/models/2026-10-24-taleforge-small-model.md).
SMALL_MODEL = "LFM2_5-1_2B-Instruct-Q5_K_M"
DEFAULT_MODELS = {"dialogue": SMALL_MODEL, "narration": SMALL_MODEL}
MAX_TOKENS = {"dialogue": 160, "narration": 260}
TEMPERATURE = {"dialogue": 0.85, "narration": 0.8}
TIMEOUT = 120.0
BACKLOG = 6  # pending jobs per save beyond which the oldest are dropped
SHARED = Path(__file__).resolve().parents[3] / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))
import forge_jan  # noqa: E402

# a closed think block, or one the model never closed (cut off mid-thought)
THINK = re.compile(r"<think>.*?(</think>|$)", re.S)
SENTENCE = re.compile(r"[^.!?…]+[.!?…]+[\"'”’)]*|[^.!?…]+$")
NOT_SAY = re.compile(
    r"\b(rolls? (a|an) (d\d+|die|natural|check)|roll for|you rolled|rolls? (of )?the dice|"
    r"dice roll|d20|hit points|hp|dc|xp|armou?r class|as an ai|language model|"
    r"level(led|ed)? up|saving throw|skill check|game master)\b",
    re.I,
)
# a number in words next to what the engine counts ("seven wounds", "ten
# gold"); "the two of you" and "a thousand lanterns" are ordinary prose
NUMBER_WORDS = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|"
    r"fifty|sixty|seventy|eighty|ninety|hundred|thousand)\s+(\w+\s+)?"
    r"(damage|wounds?|points?|gold|coins?|crowns?|silver|experience|health|hp|xp)\b",
    re.I,
)
# narration that makes the player's choices for them (what they did is
# fact and may be retold; what they decide is theirs)
PLAYER_ACTS = re.compile(
    r"\byou (decide|agree|choose|accept|refuse|promise|resolve|vow)\b",
    re.I,
)


# prompts ----------------------------------------------------------------------
def context(game) -> str:
    loc = game.location()
    bits = [
        f"Where: {loc['name']} ({game.world.data['regions'].get(game.region_id(), {}).get('name', '')}), {game.period()}."
    ]
    pc = game.pc
    cls = game.rules["_classes"][pc["class"]]["name"]
    bits.append(
        f"The player character: {pc['name']} ({pc['pronouns']}), a level {pc['level']} {cls}."
        + (f" Looks: {pc['look']}" if pc.get("look") else "")
    )
    if game.party():
        bits.append(
            "Travelling with them: "
            + ", ".join(game.person_name(c) for c in game.party())
            + "."
        )
    return "\n".join(bits)


def narration_messages(game, entry: dict) -> list[dict]:
    world = game.world
    nar = world.campaign.get("narrator", {})
    rules = world.rules.get("narration", {}).get("rules", "")
    job = entry["jan"]
    length = "one or two sentences" if job.get("short") else "two to four sentences"
    system = (
        f"{rules}\n\nThe world: {nar.get('voice', '')}\nRomance: {nar.get('romance', '')}\n"
        f"Write {length} of prose, second person, present tense. Plain text only."
    )
    user = (
        context(game)
        + "\n\nWhat happened (facts, all of them true, add nothing that changes them):\n"
    )
    user += "\n".join("- " + f for f in job.get("facts", []))
    if entry.get("text"):
        user += f"\n\nThe book's own words for this moment, which you may retell: {entry['text']}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def stage_name(game, cid: str) -> str:
    aff = game.comp(cid)["affection"]
    name = "Acquainted"
    for st in game.rules["relationships"]["stages"]:
        if aff >= st["min"]:
            name = st["name"]
    return name


def dialogue_messages(game, entry: dict) -> list[dict]:
    world = game.world
    job = entry["jan"]
    pid = job["speaker"]
    p = world.person(pid) or {}
    first = p.get("name", pid)
    nar = world.campaign.get("narrator", {})
    lines = [
        f"You are {first} ({p.get('pronouns', '')}), a character in a tabletop role-playing game. Stay in character.",
        f"Who you are: {p.get('description', '')} {p.get('appearance', '')}",
        f"Personality: {p.get('personality', '')}",
        f"How you talk: {p.get('speech', '')}",
    ]
    if p.get("backstory"):
        lines.append(f"Your past: {p['backstory']}")
    known = [tp["text"] for tp in p.get("topics", []) if tp.get("text")][:5]
    if known:
        lines.append(
            "Things you know, all true in this world (draw on them, do not contradict them): "
            + " ".join(known)
        )
    if pid in world.data["companions"]:
        c = game.comp(pid)
        lines.append(f"How you feel about {game.pc['name']}: {stage_name(game, pid)}.")
        if c["romance"] != "none":
            lines.append(
                f"Romance between you: {c['romance']}. {nar.get('romance', '')}"
            )
        if c["memories"]:
            lines.append("You remember: " + "; ".join(c["memories"][-6:]))
    lines.append(
        "Reply with one to three short sentences: what you say, in quotes, with at most one brief action outside them, "
        "written in the third person (she, he, they or your name), never 'I'. If you do not know something, say so in character. "
        "Never mention game rules, dice or numbers. Never agree to join, leave, give items, pay or promise anything: the game decides that. "
        "Never speak or act for the player."
    )
    messages = [{"role": "system", "content": "\n".join(lines)}]
    user = context(game) + "\n"
    if pid in world.data["companions"]:
        hist = [h for h in game.comp(pid)["history"] if h.get("entry") != entry["id"]][
            -6:
        ]
        for h in hist[:-1] if job.get("said") else hist:
            who = game.pc["name"] if h["who"] == "player" else first
            user += f"\n{who}: {h['text']}"
    if job.get("said"):
        user += f"\n\n{game.pc['name']} says to you: \"{job['said']}\""
    if job.get("prompt"):
        user += f"\n\nThe moment: {job['prompt']}"
    user += f"\n\nWhat you would say in the book (keep its meaning, say it your way): {entry['text']}"
    messages.append({"role": "user", "content": user.strip()})
    return messages


def messages_for(game, entry: dict) -> list[dict]:
    if entry["jan"]["role"] == "dialogue":
        return dialogue_messages(game, entry)
    return narration_messages(game, entry)


# the guard --------------------------------------------------------------------
def clean(text: str, role: str, limit: int = 700) -> str | None:
    """Jan's words made safe to show, or None to keep the fallback.

    Narration may not state numbers (the engine's numbers are the only true
    ones) or ask the player what they do. Dialogue may not talk rules."""
    text = (text or "").split("</think>")[-1]
    text = THINK.sub("", text).replace("*", "").strip()
    text = re.sub(r"^(narrator|gm|game master)\s*:\s*", "", text, flags=re.I)
    kept = []
    for raw in SENTENCE.findall(" ".join(text.split())):
        sent = raw.strip()
        if not sent or NOT_SAY.search(sent):
            continue
        if role == "narration" and (
            re.search(r"\d", sent)
            or NUMBER_WORDS.search(sent)
            or PLAYER_ACTS.search(sent)
            or sent.rstrip("\"'”’").endswith("?")
        ):
            continue
        kept.append(sent)
        if sum(len(k) for k in kept) > limit:
            break
    out = " ".join(kept).strip()
    if role == "dialogue" and out.count("“") + out.count('"') == 0 and len(out) < 300:
        out = "“" + out.strip("'") + "”"
    return out if len(out) >= 12 else None


def served_now(name: str) -> bool:
    """True when Jan's router lists `name`, or when the list cannot be read
    (then the request itself will say what is wrong)."""
    ids = forge_jan.models()
    return not ids or name in ids


# the worker -------------------------------------------------------------------
class Narrator:
    """Runs Jan jobs one at a time and hands each result to `deliver`.

    `deliver(save_id, entry_id, text_or_None, note)` writes it into the save.
    `owner` is the app's forge_jan.AppJan (None in tests: then `ask` is set
    directly)."""

    def __init__(self, deliver, owner=None, ask=None, installed=None, served=None):
        self.deliver = deliver
        self.installed = installed or forge_jan.installed
        self.served = served or served_now
        self.owner = owner
        self.ask = ask or self._ask
        self.q: queue.Queue = queue.Queue()
        self.pending: dict[str, list[str]] = {}
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.last_error = ""

    def model(self, role: str) -> str:
        """The role's chosen model if its file is really on disk, else the
        other role's, else any installed chat model. Jan keeps listing an
        entry after its .gguf is deleted (the 2B was, on 2026-10-20), so
        trusting the list alone makes every line fail to load."""
        chosen = self.owner.settings()["models"] if self.owner is not None else {}
        wanted = [chosen.get(role), DEFAULT_MODELS[role]]
        wanted += [chosen.get(r) for r in ROLES if r != role]
        wanted += [DEFAULT_MODELS[r] for r in ROLES if r != role]
        for name in wanted:
            if name and self.on_disk(name):
                return name
        found = [
            m
            for m in forge_jan.models()
            if "embed" not in m.lower() and "sentence-transformer" not in m.lower()
        ]
        found = [m for m in found if self.on_disk(m)]
        if not found:
            raise forge_jan.JanError(
                "Jan is not running or has no chat model installed"
            )
        return found[0]

    def on_disk(self, name: str) -> bool:
        """On disk and served: Jan's router reads its model list once, at
        start, so a model added since is on disk but not served until Jan
        restarts."""
        return self.installed(name) and self.served(name)

    def _ask(self, role: str, messages: list[dict]) -> str:
        model = self.model(role)
        kw: dict[str, Any] = dict(
            temperature=TEMPERATURE[role], max_tokens=MAX_TOKENS[role], timeout=TIMEOUT
        )
        if self.owner is not None:
            with self.owner.using(model):
                return forge_jan.chat_messages(model, messages, **kw)
        return forge_jan.chat_messages(model, messages, **kw)

    def submit(self, save_id: str, game, entries: list[dict]) -> list[str]:
        """Queue every entry with a Jan job; returns the ids marked pending."""
        ids = []
        for e in entries:
            job = e.get("jan")
            if not job:
                continue
            e["pending"] = True
            msgs = messages_for(game, e)
            ids.append(e["id"])
            with self.lock:
                self.pending.setdefault(save_id, []).append(e["id"])
                stale = self.pending[save_id][:-BACKLOG]
                self.pending[save_id] = self.pending[save_id][-BACKLOG:]
            for old in stale:
                self.deliver(save_id, old, None, "skipped")
            self.q.put((save_id, e["id"], job["role"], msgs))
        self.start()
        return ids

    def start(self) -> None:
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(
                target=self._run, name="taleforge-jan", daemon=True
            )
            self.thread.start()

    def _run(self) -> None:
        while True:
            try:
                save_id, eid, role, msgs = self.q.get(timeout=30)
            except queue.Empty:
                return
            with self.lock:
                live = eid in self.pending.get(save_id, [])
            if not live:
                continue
            text, note = None, ""
            try:
                text = clean(self.ask(role, msgs), role)
                note = "jan" if text else "unusable"
                self.last_error = ""
            except Exception as exc:  # Jan down, slow, or odd: keep the fallback
                note = "jan_down"
                self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            with self.lock:
                if eid in self.pending.get(save_id, []):
                    self.pending[save_id].remove(eid)
            self.deliver(save_id, eid, text, note)

    def drain(self, timeout: float = 600.0) -> None:
        """Wait until the queue is empty (tests and the playthrough script)."""
        import time

        end = time.time() + timeout
        while time.time() < end:
            with self.lock:
                busy = any(self.pending.values())
            if not busy:
                return
            time.sleep(0.2)
