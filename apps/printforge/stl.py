"""STL reading and print checks for PrintForge.

`read_triangles` loads binary or ASCII STL into an (n, 3, 3) float32 array.
`analyse` answers the questions a slicer would complain about: is it watertight,
how many separate shells, how big, how much material, how much of it hangs
over and needs support. `fits` compares a size with print beds.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

_REC = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])


def is_binary(data: bytes) -> bool:
    """Binary when the triangle count in the header matches the file length."""
    if len(data) < 84:
        return False
    n = struct.unpack_from("<I", data, 80)[0]
    if 84 + n * 50 == len(data):
        return True
    return not data.lstrip()[:5].lower() == b"solid"


def read_triangles(path: str | Path) -> np.ndarray:
    """Triangles of an STL file as an (n, 3, 3) float32 array (file units, normally mm)."""
    data = Path(path).read_bytes()
    if is_binary(data):
        n = struct.unpack_from("<I", data, 80)[0]
        n = min(n, (len(data) - 84) // 50)
        return np.frombuffer(data, dtype=_REC, count=n, offset=84)["v"].copy()
    rows = [
        line.split()[1:4]
        for line in data.decode("ascii", "replace").splitlines()
        if line.strip().startswith("vertex")
    ]
    if len(rows) % 3:
        raise ValueError("ASCII STL with a vertex count that is not a multiple of 3")
    return np.array(rows, dtype=np.float32).reshape(-1, 3, 3)


def triangle_count(path: str | Path) -> int | None:
    """Triangle count from a binary header without reading the file (None for ASCII)."""
    p = Path(path)
    size = p.stat().st_size
    if size < 84:
        return None
    with p.open("rb") as f:
        f.seek(80)
        n = struct.unpack("<I", f.read(4))[0]
    return n if 84 + n * 50 == size else None


def shell_count(nverts: int, a: np.ndarray, b: np.ndarray) -> int:
    """Connected pieces of a mesh graph (vertices joined by edges a[i]-b[i])."""
    if nverts == 0:
        return 0
    parent = np.arange(nverts)
    while True:
        pa, pb = parent[a], parent[b]
        differ = pa != pb
        if not differ.any():
            break
        lo = np.minimum(pa, pb)[differ]
        hi = np.maximum(pa, pb)[differ]
        np.minimum.at(parent, hi, lo)
        while True:
            nxt = parent[parent]
            if np.array_equal(nxt, parent):
                break
            parent = nxt
    used = np.zeros(nverts, dtype=bool)
    used[a] = True
    used[b] = True
    return int(len(np.unique(parent[used])))


# Overhang angles the check reports, in degrees from vertical (0 is a wall,
# 90 a flat ceiling). Slicers default to supports past about 45.
OVERHANG_ANGLES = tuple(range(30, 85, 5))
BED_MM = 0.2  # faces this close to the lowest point rest on the bed


def overhang_areas(v: np.ndarray, cross: np.ndarray, flip: bool) -> dict:
    """Area (cm2) of the faces that point down steeper than each angle in
    OVERHANG_ANGLES, leaving out the faces that rest on the bed.

    `v` is the (n, 3, 3) triangles, `cross` their edge cross products (the
    face normal times twice the area) and `flip` is True for an inside-out
    mesh, whose normals point in."""
    twice = np.linalg.norm(cross, axis=1)
    ok = twice > 0
    nz = np.zeros(len(v))
    nz[ok] = cross[ok, 2] / twice[ok]
    if flip:
        nz = -nz
    on_bed = v[:, :, 2].max(axis=1) <= v[:, :, 2].min() + BED_MM
    down = ok & (nz < 0) & ~on_bed
    steep = np.degrees(np.arcsin(np.clip(-nz[down], 0, 1)))
    area = 0.5 * twice[down]
    return {
        str(a): round(float(area[steep > a].sum()) / 100, 2) for a in OVERHANG_ANGLES
    }


def analyse(tris: np.ndarray) -> dict:
    """Size, volume, area, watertightness and shell count of a triangle soup."""
    n = len(tris)
    if n == 0:
        return {"triangles": 0, "watertight": False, "shells": 0}
    if not np.isfinite(tris).all():
        raise ValueError("some corners are not numbers (the file looks damaged)")
    flat = tris.reshape(-1, 3)
    uniq, inv = np.unique(flat, axis=0, return_inverse=True)
    face = np.asarray(inv).reshape(-1, 3)
    flat_face = (
        (face[:, 0] == face[:, 1])
        | (face[:, 1] == face[:, 2])
        | (face[:, 0] == face[:, 2])
    )
    degenerate = int(flat_face.sum())
    # A zero-area triangle (two corners the same) is dropped by slicers; its
    # edges would otherwise count as a second copy of a real edge and turn
    # a closed mesh into "almost" watertight. It cancels itself as an open
    # edge either way.
    a = face[~flat_face].reshape(-1)
    b = face[~flat_face][:, [1, 2, 0]].reshape(-1)
    nv = np.int64(len(uniq))
    key = a.astype(np.int64) * nv + b
    rkey = b.astype(np.int64) * nv + a
    _, counts = np.unique(key, return_counts=True)
    repeated = int((counts > 1).sum())
    open_edges = int((~np.isin(key, rkey)).sum())
    v = tris.astype(np.float64)
    cross = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    area = float(0.5 * np.linalg.norm(cross, axis=1).sum())
    volume = float(np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2])).sum() / 6)
    mn, mx = uniq.min(axis=0), uniq.max(axis=0)
    return {
        "triangles": n,
        "size_mm": [round(float(x), 2) for x in (mx - mn)],
        "min_mm": [round(float(x), 2) for x in mn],
        "volume_cm3": round(abs(volume) / 1000, 2),
        "inside_out": volume < 0,
        "area_cm2": round(area / 100, 1),
        "open_edges": open_edges,
        "repeated_edges": repeated,
        "degenerate_triangles": degenerate,
        "watertight": open_edges == 0 and repeated == 0 and len(a) > 0,
        "shells": shell_count(len(uniq), a, b),
        "overhang_cm2": overhang_areas(v, cross, volume < 0),
    }


def fits(size: list[float], bed: list[float]) -> dict:
    """Whether a part fits a bed standing as modelled, and in any orientation."""
    upright = sorted(size[:2]) <= sorted(bed[:2]) and all(
        s <= d for s, d in zip(sorted(size[:2]), sorted(bed[:2]))
    )
    upright = upright and size[2] <= bed[2]
    anyway = all(s <= d for s, d in zip(sorted(size), sorted(bed)))
    return {"upright": bool(upright), "any_orientation": bool(anyway)}
