"""Build Cosmos's star catalog from the HYG database.

HYG (Hipparcos, Yale Bright Star and Gliese catalogs combined, by David Nash
at astronexus.com, CC BY-SA 4.0) lists about 120,000 real stars with
distances, magnitudes and colours. The raw CSV is 14 MB compressed; the map
only needs six numbers per star, so this packs it into a small binary file the
browser can read straight into a Float32Array.

The built files (about 3.5 MB together) go to COSMOS_STARS_DIR (Forge's data
folder in a release, ~/.cache/forge/cosmos/ otherwise). With COSMOS_DRIVE_ROOT
set, the source and a first copy live on that drive instead:

    <drive>/Cosmos/stars/hyg_v44.csv.gz   downloaded source
    <drive>/Cosmos/stars/stars-v1.bin      packed positions
    <drive>/Cosmos/stars/star-names.json   names and details

and the local copy keeps the map in stars when the drive is unplugged. The
app's "Get the stars" button runs `fetch_and_build` into the local folder.

stars-v1.bin layout (little-endian):

    4 bytes   b"CSTR"
    uint32    format version (1)
    uint32    star count N
    N * 6 float32   x, y, z (parsecs, J2000 ecliptic, Sun at the origin),
                    absolute magnitude, apparent magnitude, B-V colour index

The header is 12 bytes, so the records start on a 4-byte boundary.

Run:
    .venv/bin/python tools/build_star_catalog.py
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import shutil
import struct
import sys
import urllib.request
from collections.abc import Iterator
from pathlib import Path

HYG_URL = "https://codeberg.org/astronexus/hyg/media/branch/main/data/hyg/CURRENT/hyg_v44.csv.gz"
HYG_FILE = "hyg_v44.csv.gz"
HYG_VERSION = "HYG v4.4"
CREDIT = (
    "Star data: HYG Database v4.4 by David Nash, astronexus.com, "
    "licensed CC BY-SA 4.0"
)

DRIVE_ROOT: Path | None = (
    Path(os.environ["COSMOS_DRIVE_ROOT"])
    if os.environ.get("COSMOS_DRIVE_ROOT")
    else None
)
DRIVE_DIR: Path | None = DRIVE_ROOT / "Cosmos" / "stars" if DRIVE_ROOT else None
CACHE_DIR = Path(
    os.environ.get("COSMOS_STARS_DIR")
    or str(Path.home() / ".cache" / "forge" / "cosmos")
)
STARS_FILE = "stars-v1.bin"
NAMES_FILE = "star-names.json"

MAGIC = b"CSTR"
FORMAT_VERSION = 1
RECORD = struct.Struct("<6f")
HEADER = struct.Struct("<4sII")

# HYG writes this distance for stars whose parallax is missing or unusable.
UNKNOWN_DISTANCE_PC = 100000.0
# B-V for stars with no measured colour: the Sun's, so they draw white-yellow.
DEFAULT_COLOR_INDEX = 0.65
OBLIQUITY = math.radians(23.4392911)


def equatorial_to_ecliptic(x: float, y: float, z: float) -> tuple[float, float, float]:
    c, s = math.cos(OBLIQUITY), math.sin(OBLIQUITY)
    return x, y * c + z * s, -y * s + z * c


def read_rows(source: Path) -> Iterator[dict[str, str]]:
    with gzip.open(source, "rt", newline="", encoding="utf-8") as fh:
        yield from csv.DictReader(fh)


def display_name(row: dict[str, str]) -> str | None:
    """A name a person would recognise, or None for catalogue-number-only stars."""
    if row.get("proper"):
        return row["proper"]
    con = row.get("con", "")
    if row.get("bayer") and con:
        return f"{row['bayer']} {con}"
    if row.get("flam") and con:
        return f"{row['flam']} {con}"
    return None


def _float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build(source: Path, out_dir: Path) -> dict[str, int]:
    records = bytearray()
    names: list[dict[str, object]] = []
    count = skipped = 0
    for row in read_rows(source):
        if row.get("id") == "0" or row.get("proper") == "Sol":
            continue  # the Sun is a body in the map, not a catalogue star
        dist = _float(row.get("dist", ""))
        x, y, z = (_float(row.get(k, "")) for k in ("x", "y", "z"))
        absmag = _float(row.get("absmag", ""))
        mag = _float(row.get("mag", ""))
        if (
            dist is None
            or x is None
            or y is None
            or z is None
            or absmag is None
            or mag is None
            or not 0 < dist < UNKNOWN_DISTANCE_PC
        ):
            skipped += 1
            continue
        ci = _float(row.get("ci", ""))
        ex, ey, ez = equatorial_to_ecliptic(x, y, z)
        records += RECORD.pack(
            ex, ey, ez, absmag, mag, DEFAULT_COLOR_INDEX if ci is None else ci
        )
        name = display_name(row)
        if name:
            names.append(
                {
                    "i": count,
                    "name": name,
                    "proper": bool(row.get("proper")),
                    "spect": row.get("spect", ""),
                    "con": row.get("con", ""),
                    "mag": round(mag, 2),
                    "absmag": round(absmag, 2),
                    "dist_pc": round(dist, 3),
                    "lum": _float(row.get("lum", "")),
                }
            )
        count += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_atomic(
        out_dir / STARS_FILE,
        HEADER.pack(MAGIC, FORMAT_VERSION, count) + bytes(records),
    )
    _write_atomic(
        out_dir / NAMES_FILE,
        json.dumps(
            {
                "version": FORMAT_VERSION,
                "source": HYG_VERSION,
                "credit": CREDIT,
                "count": count,
                "stars": names,
            },
            separators=(",", ":"),
        ).encode(),
    )
    return {"count": count, "skipped": skipped, "named": len(names)}


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def download(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(HYG_URL, timeout=120) as resp, tmp.open("wb") as fh:
        shutil.copyfileobj(resp, fh)
    tmp.replace(dest)


def fetch_and_build(out_dir: Path) -> dict[str, int]:
    """Download HYG into out_dir, build the catalog there and drop the
    download again (the map needs only the two built files)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    source = out_dir / HYG_FILE
    try:
        download(source)
        return build(source, out_dir)
    finally:
        source.unlink(missing_ok=True)
        source.with_suffix(source.suffix + ".part").unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build Cosmos's star catalog from the HYG database."
    )
    home = DRIVE_DIR or CACHE_DIR
    parser.add_argument("--source", type=Path, default=home / HYG_FILE)
    parser.add_argument("--out", type=Path, default=home)
    parser.add_argument(
        "--no-cache-copy",
        action="store_true",
        help="do not copy the built files to ~/.cache/forge/cosmos",
    )
    args = parser.parse_args(argv)

    if DRIVE_ROOT and args.out.is_relative_to(DRIVE_ROOT) and not DRIVE_ROOT.is_mount():
        print(f"The drive at {DRIVE_ROOT} is not mounted. Plug it in, or pass --out.")
        return 1
    if not args.source.exists():
        print(f"Downloading {HYG_URL}")
        download(args.source)
    result = build(args.source, args.out)
    print(
        f"{result['count']} stars written ({result['named']} named, "
        f"{result['skipped']} skipped for missing distance or magnitude) to {args.out}"
    )
    if not args.no_cache_copy and args.out != CACHE_DIR:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for name in (STARS_FILE, NAMES_FILE):
            shutil.copy2(args.out / name, CACHE_DIR / name)
        print(f"Copied to {CACHE_DIR} for when the drive is unplugged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
