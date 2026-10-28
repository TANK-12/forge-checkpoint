"""Turn TopoJSON world boundaries into ready-to-draw SVG paths.

Run once; the output is committed into static/ and the app never fetches
anything at runtime. Doing the projection here rather than in the browser means
the frontend needs no mapping library at all - it sets a fill colour on paths
that are already the right shape.

Source data: world-atlas (Natural Earth 110m), public domain.
Usage: python3 tools/build_map.py <topojson-in> <json-out>
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

# Robinson projection tables, every 5 degrees of latitude. Equirectangular is
# simpler but stretches the high latitudes badly enough to be distracting on a
# political map; Robinson is the usual compromise and is a table lookup.
ROBINSON_X = [
    1.0000,
    0.9986,
    0.9954,
    0.9900,
    0.9822,
    0.9730,
    0.9600,
    0.9427,
    0.9216,
    0.8962,
    0.8679,
    0.8350,
    0.7986,
    0.7597,
    0.7186,
    0.6732,
    0.6213,
    0.5722,
    0.5322,
]
ROBINSON_Y = [
    0.0000,
    0.0620,
    0.1240,
    0.1860,
    0.2480,
    0.3100,
    0.3720,
    0.4340,
    0.4958,
    0.5571,
    0.6176,
    0.6769,
    0.7346,
    0.7903,
    0.8435,
    0.8936,
    0.9394,
    0.9761,
    1.0000,
]


def _interp(table: list[float], lat: float) -> float:
    lat = min(abs(lat), 90.0)
    i = int(lat / 5.0)
    if i >= 18:
        return table[18]
    frac = (lat - i * 5.0) / 5.0
    return table[i] + (table[i + 1] - table[i]) * frac


def project(lon: float, lat: float) -> tuple[float, float]:
    x = 0.8487 * _interp(ROBINSON_X, lat) * math.radians(lon)
    y = 1.3523 * _interp(ROBINSON_Y, lat) * (1 if lat >= 0 else -1)
    return x, y


def decode_arcs(topology: dict) -> list[list[tuple[float, float]]]:
    """TopoJSON stores arcs as quantised deltas; undo that."""
    scale = topology["transform"]["scale"]
    translate = topology["transform"]["translate"]
    out = []
    for arc in topology["arcs"]:
        x = y = 0
        points = []
        for dx, dy in arc:
            x += dx
            y += dy
            points.append((x * scale[0] + translate[0], y * scale[1] + translate[1]))
        out.append(points)
    return out


def ring_points(arcs: list, indexes: list[int]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for index in indexes:
        arc = arcs[~index][::-1] if index < 0 else arcs[index]
        points.extend(arc if not points else arc[1:])
    return points


def split_antimeridian(
    ring: list[tuple[float, float]],
) -> list[list[tuple[float, float]]]:
    """Break a ring wherever it crosses the 180th meridian.

    Russia, Fiji and a few others have territory either side of the date line.
    Projected naively, the polygon closes by running straight back across the
    whole map, which draws a hairline right through the middle of the world.
    Splitting the ring where longitude jumps more than 180 degrees keeps each
    piece on its own side.
    """
    pieces: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    previous_lon = None
    for lon, lat in ring:
        if previous_lon is not None and abs(lon - previous_lon) > 180:
            if len(current) >= 3:
                pieces.append(current)
            current = []
        current.append((lon, lat))
        previous_lon = lon
    if len(current) >= 3:
        pieces.append(current)
    return pieces


def to_path(rings: list[list[tuple[float, float]]], bounds: dict) -> list:
    parts = []
    for ring in rings:
        if len(ring) < 3:
            continue
        for piece in split_antimeridian(ring):
            coords = []
            for lon, lat in piece:
                x, y = project(lon, lat)
                bounds["minx"] = min(bounds["minx"], x)
                bounds["maxx"] = max(bounds["maxx"], x)
                bounds["miny"] = min(bounds["miny"], y)
                bounds["maxy"] = max(bounds["maxy"], y)
                coords.append((x, y))
            parts.append(coords)
    return parts


def build(source: Path, target: Path) -> dict:
    topology = json.loads(source.read_text())
    arcs = decode_arcs(topology)
    bounds = {"minx": 1e9, "maxx": -1e9, "miny": 1e9, "maxy": -1e9}

    raw: list[dict] = []
    for geometry in topology["objects"]["countries"]["geometries"]:
        name = (geometry.get("properties") or {}).get("name", "")
        if not name:
            continue
        rings: list[list[tuple[float, float]]] = []
        if geometry["type"] == "Polygon":
            rings = [ring_points(arcs, ring) for ring in geometry["arcs"]]
        elif geometry["type"] == "MultiPolygon":
            for polygon in geometry["arcs"]:
                rings.extend(ring_points(arcs, ring) for ring in polygon)
        else:
            continue
        raw.append({"name": name, "rings": to_path(rings, bounds)})

    width = bounds["maxx"] - bounds["minx"]
    height = bounds["maxy"] - bounds["miny"]
    scale = 1000.0 / width

    countries = []
    for entry in raw:
        pieces = []
        for coords in entry["rings"]:
            bits = []
            for i, (x, y) in enumerate(coords):
                px = (x - bounds["minx"]) * scale
                # SVG y grows downward; latitude grows upward.
                py = (bounds["maxy"] - y) * scale
                bits.append(f"{'M' if i == 0 else 'L'}{px:.1f} {py:.1f}")
            if bits:
                pieces.append("".join(bits) + "Z")
        if pieces:
            countries.append({"name": entry["name"], "d": "".join(pieces)})

    payload = {
        "source": "Natural Earth 110m via world-atlas (public domain)",
        "projection": "Robinson",
        "viewBox": f"0 0 1000 {height * scale:.1f}",
        "countries": sorted(countries, key=lambda c: c["name"]),
    }
    target.write_text(json.dumps(payload, separators=(",", ":")))
    return payload


if __name__ == "__main__":
    if {"-h", "--help"} & set(sys.argv[1:]):  # usage only, no work
        print(__doc__)
        sys.exit(0)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("static/world-map.json")
    result = build(src, dst)
    size = dst.stat().st_size
    print(f"{len(result['countries'])} countries -> {dst} ({size/1024:.0f} KB)")
    print(f"viewBox: {result['viewBox']}")
