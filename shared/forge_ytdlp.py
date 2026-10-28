"""yt-dlp command lines and output, shared by everything in Forge that saves
YouTube audio or video: Media's Download tab and the hub's background music
("add from a YouTube link").

yt-dlp is the system one (/usr/bin/yt-dlp); ffmpeg turns audio into mp3.
Nothing here starts yt-dlp; callers do, so tests can hand in a fake.
normalise() runs ffmpeg through a `run` it is handed, for the same reason.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

_PROGRESS_RE = re.compile(r"\[download\]\s+([0-9.]+)%")
# yt-dlp prints where the finished file went on one of these lines
_DEST_RE = re.compile(
    r'^\[(?:ExtractAudio|Merger|download)\] (?:Destination: |Merging formats into ")(.+?)"?$'
)
_ALREADY_RE = re.compile(r"^\[download\] (.+) has already been downloaded")


# every download is evened out to this loudness (EBU R128 integrated, in
# LUFS), so one song is not much quieter than the next; -16.4 is where
# "System Prompt (For Humans)" sat, which the owner picked as the right level
TARGET_LUFS = -16.4
TRUE_PEAK = -1.5


def ytdlp() -> Optional[str]:
    return shutil.which("yt-dlp")


def download_command(urls: list[str], folder: Path, kind: str = "audio") -> list[str]:
    """yt-dlp for a batch: mp3 with cover and tags for audio, an mp4 up to
    1080p for video. Names are the video titles; a file that already exists
    is skipped, so re-running a channel only fetches what is new."""
    exe = ytdlp() or "yt-dlp"
    out = str(folder / "%(title).150s [%(id)s].%(ext)s")
    cmd = [
        exe,
        "--no-warnings",
        "--newline",
        "--no-overwrites",
        "--no-playlist",
        "-o",
        out,
    ]
    if kind == "video":
        cmd += [
            "-f",
            "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
            "--merge-output-format",
            "mp4",
        ]
    else:
        cmd += [
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--embed-thumbnail",
            "--embed-metadata",
        ]
    return cmd + list(urls)


def progress_of(line: str) -> Optional[float]:
    m = _PROGRESS_RE.search(line)
    return float(m.group(1)) / 100.0 if m else None


def destination_of(line: str) -> Optional[str]:
    """The file a line says was written (the last one wins: the mp3 after
    the webm it came from), or None."""
    m = _DEST_RE.match(line.strip()) or _ALREADY_RE.match(line.strip())
    return m.group(1) if m else None


def measure_command(path: Path) -> list[str]:
    """ffmpeg's first loudnorm pass: measures, writes nothing."""
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-af",
        f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK}:LRA=20:print_format=json",
        "-f",
        "null",
        "-",
    ]


def parse_measure(text: str) -> Optional[dict]:
    """The JSON block loudnorm prints at the end of its stderr, or None."""
    start, end = text.rfind("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    keys = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    if not all(k in data for k in keys):
        return None
    try:
        if float(data["input_i"]) == float("-inf"):
            return None  # silence: nothing to even out
    except ValueError:
        return None
    return {k: data[k] for k in keys}


def apply_command(src: Path, dst: Path, m: dict) -> list[str]:
    """The second pass: a straight gain to the target (linear, so the music's
    dynamics are kept) with everything but the audio copied as is."""
    af = (
        f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK}:LRA=20:linear=true"
        f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
        f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
        f":offset={m['target_offset']}"
    )
    if src.suffix.lower() == ".mp3":
        codec = ["-c:a", "libmp3lame", "-q:a", "0", "-id3v2_version", "3"]
    else:
        codec = ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    return [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-map",
        "0",
        "-c",
        "copy",
        "-af",
        af,
        "-ar",
        "48000",
        *codec,
        str(dst),
    ]


def normalise(path: Path, run=subprocess.run) -> bool:
    """Even a downloaded file out to TARGET_LUFS in place. False (file left
    untouched) when ffmpeg is missing, the file is silent or a pass fails."""
    path = Path(path)
    if not shutil.which("ffmpeg") or not path.is_file():
        return False
    proc = run(measure_command(path), capture_output=True, text=True)
    m = parse_measure(proc.stderr or "") if proc.returncode == 0 else None
    if m is None:
        return False
    tmp = path.with_name(path.stem + ".loudnorm" + path.suffix)
    proc = run(apply_command(path, tmp, m), capture_output=True, text=True)
    if proc.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        return False
    os.replace(tmp, path)
    return True
