"""Video is MediaForge's: its Video Enhancer re-encodes, resizes and
smooths, so Convert points there instead of doing it a second time."""

CONVERTER = {
    "id": "video",
    "label": "Video",
    "order": 4,
    "from": [
        "mp4",
        "mkv",
        "mov",
        "webm",
        "avi",
        "m4v",
        "wmv",
        "flv",
        "mpg",
        "mpeg",
        "ts",
    ],
    "handoff": {
        "app": "mediaforge",
        "hash": "tool=enhance",
        "label": "Open in MediaForge's Video Enhancer",
        "why": "MediaForge re-encodes video: a new size, codec or frame rate.",
    },
}
