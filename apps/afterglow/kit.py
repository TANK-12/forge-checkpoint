"""Small helpers any curio's server.py may use: a PNG writer and palettes.

The PNG writer is what lets a Claude session see what it made without a
browser: a curio renders into an RGB byte buffer, writes a PNG, and the
session opens the file. Stdlib only (zlib + struct).
"""

from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path

# The Afterglow palette, dark to bright: night, ember, flame, spark.
EMBER = [(8, 6, 14), (74, 20, 40), (190, 64, 36), (255, 150, 60), (255, 236, 190)]


def png_bytes(width: int, height: int, rgb: bytes | bytearray) -> bytes:
    """An 8-bit RGB PNG from rows of width*3 bytes, top row first."""
    if width <= 0 or height <= 0 or len(rgb) != width * height * 3:
        raise ValueError("rgb must hold width * height * 3 bytes")
    stride = width * 3
    raw = b"".join(
        b"\x00" + bytes(rgb[y * stride : (y + 1) * stride]) for y in range(height)
    )

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def png_data_url(width: int, height: int, rgb: bytes | bytearray) -> str:
    return "data:image/png;base64," + base64.b64encode(
        png_bytes(width, height, rgb)
    ).decode("ascii")


def write_png(
    path: str | Path, width: int, height: int, rgb: bytes | bytearray
) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(png_bytes(width, height, rgb))
    return target


def ramp(stops: list[tuple[int, int, int]], t: float) -> tuple[int, int, int]:
    """The colour at t (0..1) along evenly spaced stops."""
    t = min(1.0, max(0.0, t)) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    f = t - i
    a, b = stops[i], stops[i + 1]
    return (
        round(a[0] + (b[0] - a[0]) * f),
        round(a[1] + (b[1] - a[1]) * f),
        round(a[2] + (b[2] - a[2]) * f),
    )
