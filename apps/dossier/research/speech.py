"""Saying a dossier out loud.

Nothing is installed for this. NovelForge already has Piper in its own
virtualenv and the voice models already sit in `~/NovelMakerData/tts_voices/`,
so this shells out to that binary with that voice rather than adding a second
copy of a 120MB model and an onnxruntime to Dossier's venv.

Two things can be spoken:

  a tour     built straight from the stored timeline, claims and quotes. No
             model is involved at all, so there is nothing for one to invent -
             the narration is the record read aloud, in order.

  an answer  a typed question run through `ask.py`, which already deletes any
             sentence that cites nothing. The citation markers are stripped
             before speaking, because "[4]" is not a sound, but they are kept
             in the transcript that comes back with the file.

That second point is the rule this module exists to respect: if a sentence is
not good enough to appear in writing, it is not good enough to be spoken, where
it is harder to check.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import ask as ask_mod
import dossier
import store

FORGE = Path.home() / "Forge"
PIPER = FORGE / "apps" / "novelforge" / ".venv" / "bin" / "piper"
VOICES_DIR = Path.home() / "NovelMakerData" / "tts_voices"
DEFAULT_VOICE = "en_US-ryan-high"

AUDIO_DIR = "audio"
RENDER_TIMEOUT = 900  # a long tour on a CPU voice is slow, not broken

# Citation markers read as noise out loud.
MARKER = re.compile(r"\s*\[\d+\](?:\[\d+\])*")


def voice_path(voice: str = DEFAULT_VOICE) -> Path:
    return VOICES_DIR / f"{voice}.onnx"


def available(voice: str = DEFAULT_VOICE) -> dict:
    """What is present, and what is missing if anything is."""
    model = voice_path(voice)
    ffmpeg = shutil.which("ffmpeg")
    voices = (
        sorted(p.stem for p in VOICES_DIR.glob("*.onnx")) if VOICES_DIR.is_dir() else []
    )
    missing = []
    if not PIPER.is_file():
        missing.append(f"Piper is not installed in NovelForge's venv ({PIPER})")
    if not model.is_file():
        missing.append(f"the voice '{voice}' is not in {VOICES_DIR}")
    if not ffmpeg:
        missing.append(
            "ffmpeg is not on the path, so nothing can be turned into an mp3"
        )
    return {
        "ready": not missing,
        "missing": missing,
        "voice": voice,
        "voices": voices,
        "piper": str(PIPER),
        "voices_dir": str(VOICES_DIR),
    }


def speakable(text: str) -> str:
    """Text as it should be heard: no citation markers, no doubled spaces."""
    return re.sub(r"\s{2,}", " ", MARKER.sub("", text or "")).strip()


def _audio_dir(root: Path | None = None) -> Path:
    d = (root or store.data_root().path) / AUDIO_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def planned_path(
    text: str, name: str, voice: str = DEFAULT_VOICE, root: Path | None = None
) -> Path:
    """Where this exact text in this exact voice would be written.

    The name is a hash of the content, so asking twice for the same tour gets
    the same file and the second ask costs nothing.
    """
    spoken = speakable(text)
    stem = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()[:60] or "dossier"
    digest = hashlib.sha1(f"{voice}:{spoken}".encode("utf-8")).hexdigest()[:10]
    return _audio_dir(root) / f"{stem}-{digest}.mp3"


def existing_tour(
    slug: str, voice: str = DEFAULT_VOICE, root: Path | None = None
) -> str:
    """The tour recording for this subject if it has already been made."""
    script = tour_script(slug, root=root)
    if script.get("error") or not script.get("text"):
        return ""
    path = planned_path(script["text"], f"tour-{slug}", voice, root)
    return path.name if path.is_file() else ""


def render(
    text: str, name: str, voice: str = DEFAULT_VOICE, root: Path | None = None
) -> dict:
    """Speak `text` into an mp3 and return where it landed."""
    state = available(voice)
    if not state["ready"]:
        return {"ok": False, "error": "; ".join(state["missing"]), "path": ""}

    spoken = speakable(text)
    if not spoken:
        return {"ok": False, "error": "There is nothing to say.", "path": ""}

    mp3 = planned_path(text, name, voice, root)
    if mp3.is_file():
        return {"ok": True, "path": str(mp3), "reused": True, "seconds": 0}

    wav = mp3.with_suffix(".wav")
    try:
        subprocess.run(
            [str(PIPER), "-m", str(voice_path(voice)), "-f", str(wav)],
            input=spoken.encode("utf-8"),
            capture_output=True,
            timeout=RENDER_TIMEOUT,
            check=True,
        )
        # mp3 rather than the wav Piper writes: a long tour is tens of
        # megabytes as wav and the library lives on a USB drive.
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(wav),
                "-b:a",
                "96k",
                str(mp3),
            ],
            capture_output=True,
            timeout=RENDER_TIMEOUT,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or b"").decode("utf-8", "replace")[-300:]
        return {"ok": False, "error": f"Rendering failed: {detail}", "path": ""}
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "Rendering took too long and was stopped.",
            "path": "",
        }
    finally:
        wav.unlink(missing_ok=True)

    return {
        "ok": True,
        "path": str(mp3),
        "reused": False,
        "bytes": mp3.stat().st_size if mp3.is_file() else 0,
    }


# --- what there is to say ---------------------------------------------------


def tour_script(slug: str, limit: int = 40, root: Path | None = None) -> dict:
    """A narration of one subject, built only from what is stored.

    Deliberately not written by a model. The timeline is already in date order
    and already carries its sources, so reading it out is both the most useful
    tour and the only one that cannot be wrong.
    """
    stored = dossier.load(slug, root)
    if not stored:
        return {"slug": slug, "lines": [], "text": "", "error": "No dossier stored."}

    subject = stored.get("subject") or {}
    name = subject.get("name", slug)
    identity = subject.get("identity") or {}
    lines: list[dict] = []

    opening = f"{name}."
    if identity.get("description"):
        opening = f"{name}. {identity['description']}."
    lines.append({"kind": "opening", "text": opening, "url": ""})

    events = [e for e in (stored.get("timeline") or []) if e.get("date")]
    events = [e for e in events if _worth_saying(e, subject.get("entity_type", ""))]
    events.sort(key=lambda e: e.get("date") or "")
    if events:
        lines.append(
            {
                "kind": "heading",
                "text": f"There are {len(events)} dated events on file. In order:",
                "url": "",
            }
        )
    for event in events[:limit]:
        title = (event.get("title") or "").strip().rstrip(".")
        if not title:
            continue
        lines.append(
            {
                "kind": "event",
                "text": f"{_spoken_date(event['date'])}. {title}.",
                "url": event.get("url", ""),
            }
        )

    verified = [
        c
        for c in (stored.get("claims") or [])
        if c.get("confidence") == "verified" and c.get("text")
    ]
    if verified:
        lines.append(
            {
                "kind": "heading",
                "text": "Corroborated by more than one independent source:",
                "url": "",
            }
        )
        for claim in verified[:12]:
            lines.append(
                {
                    "kind": "claim",
                    "text": claim["text"].strip().rstrip(".") + ".",
                    "url": (claim.get("evidence") or [{}])[0].get("url", ""),
                }
            )

    disputed = [
        c for c in (stored.get("claims") or []) if c.get("confidence") == "disputed"
    ]
    if disputed:
        lines.append(
            {
                "kind": "heading",
                "text": f"{len(disputed)} claims on file are disputed - "
                "the sources contradict each other. They are in the dossier, "
                "not in this tour.",
                "url": "",
            }
        )

    text = " ".join(line["text"] for line in lines)
    return {"slug": slug, "name": name, "lines": lines, "text": text, "error": ""}


# Which timeline entries belong in a spoken tour. Every event carries a `kind`
# already, and reading all of them out is worse than reading some: a person's
# tour narrating "government debt: 20.9%" between two elections is noise. For a
# country those indicators are the story, so the rule is per subject type
# rather than absolute.
TOUR_KINDS = {
    "country": ("life", "office", "indicator", "coverage"),
    "organisation": ("life", "office", "indicator", "coverage"),
}
TOUR_KINDS_DEFAULT = ("life", "office", "coverage")


def _worth_saying(event: dict, entity_type: str) -> bool:
    allowed = TOUR_KINDS.get(entity_type, TOUR_KINDS_DEFAULT)
    return (event.get("kind") or "coverage") in allowed


def _spoken_date(date: str) -> str:
    """1990-10-03 as something a voice can read."""
    months = (
        "January February March April May June July August September October "
        "November December"
    ).split()
    parts = (date or "").split("-")
    try:
        if len(parts) >= 3:
            return f"{int(parts[2])} {months[int(parts[1]) - 1]} {parts[0]}"
        if len(parts) == 2:
            return f"{months[int(parts[1]) - 1]} {parts[0]}"
        return parts[0]
    except (ValueError, IndexError):
        return date


def narrate(slug: str, voice: str = DEFAULT_VOICE, root: Path | None = None) -> dict:
    """Render the tour for one subject to an mp3."""
    script = tour_script(slug, root=root)
    if script.get("error"):
        return {"ok": False, "error": script["error"], "path": ""}
    out = render(script["text"], f"tour-{slug}", voice, root)
    return {**out, "script": script}


def answer_aloud(
    slug: str, question: str, voice: str = DEFAULT_VOICE, root: Path | None = None
) -> dict:
    """Answer a question from the stored evidence and speak the answer.

    `ask.answer` has already removed any sentence that cites nothing, so what
    is spoken is exactly what would have been shown in writing.
    """
    answered = ask_mod.answer(slug, question)
    if answered.get("error") or not answered.get("answer"):
        return {
            "ok": False,
            "error": answered.get("error") or "Nothing in the sources answers that.",
            "path": "",
            "answer": answered.get("answer", ""),
            "used": answered.get("used", []),
        }
    out = render(answered["answer"], f"answer-{slug}", voice, root)
    return {**out, "answer": answered["answer"], "used": answered.get("used", [])}
