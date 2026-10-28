"""Sound with ffmpeg: music and recordings, or the sound of a video."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

CONVERTER = {
    "id": "audio",
    "label": "Audio",
    "order": 2,
    "from": [
        "mp3",
        "wav",
        "flac",
        "ogg",
        "oga",
        "opus",
        "m4a",
        "aac",
        "wma",
        "aiff",
        "aif",
        "mp4",
        "mkv",
        "mov",
        "webm",
        "avi",
        "m4v",
    ],
    "to": ["mp3", "flac", "wav", "ogg", "opus", "m4a"],
    "options": [
        {
            "id": "quality",
            "label": "Quality",
            "type": "choice",
            "choices": [
                {"id": "high", "label": "High"},
                {"id": "medium", "label": "Medium"},
                {"id": "small", "label": "Small file"},
            ],
            "default": "high",
            "for": ["mp3", "ogg", "opus", "m4a"],
        }
    ],
}

CODECS = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", {"high": "0", "medium": "2", "small": "5"}],
    "ogg": ["-c:a", "libvorbis", "-q:a", {"high": "8", "medium": "5", "small": "3"}],
    "opus": [
        "-c:a",
        "libopus",
        "-b:a",
        {"high": "192k", "medium": "128k", "small": "64k"},
    ],
    "m4a": ["-c:a", "aac", "-b:a", {"high": "256k", "medium": "192k", "small": "128k"}],
    "flac": ["-c:a", "flac"],
    "wav": ["-c:a", "pcm_s16le"],
}


def seconds(src: Path) -> float:
    """How long the sound is, from ffprobe; 0 when it cannot tell."""
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(src),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
        return float(json.loads(out)["format"]["duration"])
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return 0.0


def args_for(to: str, quality: str) -> list[str]:
    return [a[quality] if isinstance(a, dict) else a for a in CODECS[to]]


def convert(src: Path, dst: Path, to: str, opts: dict, ctx) -> None:
    if not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg is not installed")
    total = seconds(src)

    def line(text: str) -> None:
        if text.startswith("out_time_us=") and total > 0:
            try:
                ctx.job.progress(int(text.split("=", 1)[1]) / 1e6 / total)
            except ValueError:
                pass

    cover = ["-map", "0:a:0"]  # the first sound only; covers and video stay out
    ctx.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-y",
            "-loglevel",
            "error",
            "-i",
            src,
            *cover,
            "-map_metadata",
            "0",
            *args_for(to, opts.get("quality", "high")),
            "-progress",
            "pipe:1",
            "-nostats",
            dst,
        ],
        on_line=line,
    )
