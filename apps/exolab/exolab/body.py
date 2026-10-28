"""The wearer's skin and a suit's shells as triangle meshes, posed by the arm.

Both come straight from binary glTF: the skin of the VRM character
(positions, triangles and skin weights of the skin materials) and a suit GLB
from static/assets/suits, whose shells are rigid on one humanoid bone each
(``extras.bone``). Everything is in the body frame (+X the character's left,
+Y up, +Z forward, metres), the frame ``skeleton.load`` uses.

``bone_frames`` moves the bones the way the page does: ``human.vrm_bones``
gives local rotations of the VRM normalised bones, whose rest rotation is the
identity, so a bone's world rotation is the product down the chain and
anything carried by bone b moves as R_b (x - rest_b) + pose_b. The skin blends
those transforms by its weights (linear blend skinning, as three.js does); a
shell follows its bone rigidly (``Object3D.attach`` on the page).

``nearest`` is the close-fit bench's surface query, ported from the suit
build's fit check (~/Models/exolab/suit_check.py).
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from .registry import ROOT
from .skeleton import _local_matrix, _quat_matrix

SUIT_DIR = ROOT / "static" / "assets" / "suits"
_CT = {
    5120: np.int8,
    5121: np.uint8,
    5122: np.int16,
    5123: np.uint16,
    5125: np.uint32,
    5126: np.float32,
}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_FINGERS = ("Thumb", "Index", "Middle", "Ring", "Little")


def _glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    if data[:4] != b"glTF":
        raise ValueError(f"{path.name} is not a binary glTF file")
    jlen = struct.unpack_from("<I", data, 12)[0]
    gj = json.loads(data[20 : 20 + jlen])
    at, blob = 20 + jlen, b""
    if at + 8 <= len(data):
        blen, btype = struct.unpack_from("<II", data, at)
        if btype == 0x004E4942:  # "BIN"
            blob = data[at + 8 : at + 8 + blen]
    return gj, blob


def _accessor(gj: dict, blob: bytes, i: int) -> np.ndarray:
    acc = gj["accessors"][i]
    dt = np.dtype(_CT[acc["componentType"]])
    nc, n = _NC[acc["type"]], acc["count"]
    if "bufferView" not in acc:
        return np.zeros((n, nc), dt)
    bv = gj["bufferViews"][acc["bufferView"]]
    off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride") or dt.itemsize * nc
    a = np.ndarray((n, nc), dt, blob, off, (stride, dt.itemsize)).copy()
    if acc.get("normalized") and dt.kind in "iu":
        return a.astype(np.float64) / np.iinfo(dt).max
    return a


def _worlds(nodes: list[dict]) -> tuple[list[np.ndarray], dict[int, int]]:
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    out: dict[int, np.ndarray] = {}

    def world(i: int) -> np.ndarray:
        if i not in out:
            m = _local_matrix(nodes[i])
            out[i] = world(parent[i]) @ m if i in parent else m
        return out[i]

    return [world(i) for i in range(len(nodes))], parent


def bone_words(name: str) -> str:
    """'rightUpperArm' -> 'right upper arm', in the words the page uses."""
    side = (
        "right "
        if name.startswith("right")
        else "left " if name.startswith("left") else ""
    )
    if any(f in name for f in _FINGERS):
        return side + "hand"
    core = name[len(side) - 1 :] if side else name
    words = "".join(" " + c.lower() if c.isupper() else c for c in core).strip()
    words = {
        "upper chest": "chest",
        "lower arm": "forearm",
        "upper leg": "thigh",
        "lower leg": "shin",
        "spine": "waist",
        "": "body",
    }.get(words, words)
    return side + words


@dataclass
class Body:
    """The skin at rest, with every weight moved onto its humanoid bone."""

    verts: np.ndarray  # (n, 3) rest positions
    tris: np.ndarray  # (m, 3)
    joints: np.ndarray  # (n, 4) index into ``bones``
    weights: np.ndarray  # (n, 4), rows sum to 1
    bones: list[str]  # "" (the root) first, then parents before children
    rest: np.ndarray  # (b, 3) rest positions of the bones
    parent: list[int]  # index of the parent bone, -1 for the root
    tri_bone: np.ndarray  # (m,) the bone with the most weight on each triangle

    def index(self, name: str) -> int:
        return self.bones.index(name) if name in self.bones else 0

    def below(self, names: list[str]) -> np.ndarray:
        """Mask of the bones that are one of ``names`` or hang below one."""
        out = np.zeros(len(self.bones), bool)
        for i, n in enumerate(self.bones):
            p = self.parent[i]
            out[i] = n in names or (p >= 0 and bool(out[p]))
        return out


@lru_cache(maxsize=4)
def load_body(vrm_path: str, skin_materials: tuple[str, ...] = ("_SKIN",)) -> Body:
    """The skin triangles (materials whose name contains one of
    ``skin_materials``) of every skinned mesh in the VRM."""
    gj, blob = _glb(Path(vrm_path))
    nodes = gj.get("nodes", [])
    ext = gj.get("extensions", {})
    if "VRMC_vrm" in ext:
        hb = {
            k: v["node"] for k, v in ext["VRMC_vrm"]["humanoid"]["humanBones"].items()
        }
        flip = np.ones(3)
    elif "VRM" in ext:
        hb = {b["bone"]: b["node"] for b in ext["VRM"]["humanoid"]["humanBones"]}
        flip = np.array([-1.0, 1.0, -1.0])  # VRM 0.x faces -Z; turn it like three-vrm
    else:
        raise ValueError(f"{Path(vrm_path).name} has no VRM humanoid")
    worlds, parent = _worlds(nodes)
    node_bone = {v: k for k, v in hb.items()}

    def driver(i: int | None) -> str:
        while i is not None and i not in node_bone:
            i = parent.get(i)
        return node_bone[i] if i is not None else ""

    def depth(name: str) -> int:
        i, d = hb[name], 0
        while i in parent:
            i, d = parent[i], d + 1
        return d

    bones = [""] + sorted(hb, key=depth)
    rest = np.array([np.zeros(3)] + [worlds[hb[b]][:3, 3] * flip for b in bones[1:]])
    par = [-1] + [bones.index(driver(parent.get(hb[b]))) for b in bones[1:]]
    pats = tuple(skin_materials)
    vs, ts, js, ws, base = [], [], [], [], 0
    for ni, node in enumerate(nodes):
        if "mesh" not in node or "skin" not in node:
            continue
        skin_joints = gj["skins"][node["skin"]]["joints"]
        to_bone = np.array([bones.index(driver(j)) for j in skin_joints])
        wm = worlds[ni]
        seen: dict[int, int] = {}
        for pr in gj["meshes"][node["mesh"]]["primitives"]:
            mat = (
                gj["materials"][pr["material"]].get("name", "")
                if "material" in pr
                else ""
            )
            if not any(p in mat for p in pats) or "JOINTS_0" not in pr["attributes"]:
                continue
            pa = pr["attributes"]["POSITION"]
            if pa not in seen:
                v = _accessor(gj, blob, pa).astype(np.float64)
                vs.append(((wm[:3, :3] @ v.T).T + wm[:3, 3]) * flip)
                js.append(
                    to_bone[
                        _accessor(gj, blob, pr["attributes"]["JOINTS_0"]).astype(int)
                    ]
                )
                ws.append(
                    _accessor(gj, blob, pr["attributes"]["WEIGHTS_0"]).astype(
                        np.float64
                    )
                )
                seen[pa] = base
                base += len(v)
            idx = _accessor(gj, blob, pr["indices"]).reshape(-1, 3).astype(np.int64)
            ts.append(idx + seen[pa])
    if not ts:
        raise ValueError(
            f"no skin triangles (materials {pats}) in {Path(vrm_path).name}"
        )
    joints, weights = np.vstack(js), np.vstack(ws)
    weights /= np.maximum(weights.sum(axis=1, keepdims=True), 1e-12)
    tris = np.vstack(ts)
    acc = np.zeros((len(tris), len(bones)))
    for c in range(3):
        for k in range(joints.shape[1]):
            np.add.at(
                acc,
                (np.arange(len(tris)), joints[tris[:, c], k]),
                weights[tris[:, c], k],
            )
    return Body(
        verts=np.vstack(vs),
        tris=tris,
        joints=joints,
        weights=weights,
        bones=bones,
        rest=rest,
        parent=par,
        tri_bone=acc.argmax(axis=1),
    )


def bone_frames(
    body: Body, local: dict[str, list[float]]
) -> tuple[np.ndarray, np.ndarray]:
    """World rotation (b, 3, 3) and posed position (b, 3) of every bone, from
    local quaternions (x, y, z, w) of the normalised bones; others stay at rest."""
    rot = np.tile(np.eye(3), (len(body.bones), 1, 1))
    pos = body.rest.copy()
    for i, name in enumerate(body.bones):
        p = body.parent[i]
        if p < 0:
            continue
        q = local.get(name)
        rot[i] = rot[p] @ _quat_matrix(q) if q else rot[p]
        pos[i] = pos[p] + rot[p] @ (body.rest[i] - body.rest[p])
    return rot, pos


def skin(body: Body, rot: np.ndarray, pos: np.ndarray) -> np.ndarray:
    """Linear blend skinning of the rest skin."""
    out = np.zeros_like(body.verts)
    for k in range(body.joints.shape[1]):
        j, w = body.joints[:, k], body.weights[:, k]
        moved = np.einsum("nij,nj->ni", rot[j], body.verts - body.rest[j]) + pos[j]
        out += w[:, None] * moved
    return out


def skin_rows(
    body: Body, rot: np.ndarray, pos: np.ndarray, rows: np.ndarray
) -> np.ndarray:
    """Linear blend skinning of some rest vertices only."""
    v = body.verts[rows]
    out = np.zeros_like(v)
    for k in range(body.joints.shape[1]):
        j, w = body.joints[rows, k], body.weights[rows, k]
        out += w[:, None] * (np.einsum("nij,nj->ni", rot[j], v - body.rest[j]) + pos[j])
    return out


def carry(
    verts: np.ndarray, b: int, body: Body, rot: np.ndarray, pos: np.ndarray
) -> np.ndarray:
    """Points rigid on bone ``b``, moved from rest to the pose."""
    return (verts - body.rest[b]) @ rot[b].T + pos[b]


@dataclass
class Shell:
    name: str
    part: str
    kind: str
    side: str
    bone: int  # index into Body.bones
    verts: np.ndarray  # rest, body frame
    tris: np.ndarray
    gap_mm: float  # the fit gap it was built to
    thickness_mm: float


@lru_cache(maxsize=4)
def load_suit(
    asset: str, vrm_path: str, skin_materials: tuple[str, ...] = ("_SKIN",)
) -> list[Shell]:
    """Every shell of static/assets/suits/<asset>.glb, with its sidecar facts."""
    body = load_body(vrm_path, skin_materials)
    glb, side = SUIT_DIR / f"{asset}.glb", SUIT_DIR / f"{asset}.json"
    if not glb.is_file():
        raise ValueError(f"no fitted suit '{asset}' in static/assets/suits")
    facts = {}
    if side.is_file():
        facts = {p["name"]: p for p in json.loads(side.read_text()).get("parts", [])}
    gj, blob = _glb(glb)
    worlds, _ = _worlds(gj.get("nodes", []))
    out = []
    for ni, node in enumerate(gj.get("nodes", [])):
        if "mesh" not in node:
            continue
        name = node.get("name", f"node{ni}")
        f = facts.get(name, {})
        bone = (node.get("extras") or {}).get("bone") or f.get("bone", "")
        vs, ts, base = [], [], 0
        for pr in gj["meshes"][node["mesh"]]["primitives"]:
            v = _accessor(gj, blob, pr["attributes"]["POSITION"]).astype(np.float64)
            vs.append((worlds[ni][:3, :3] @ v.T).T + worlds[ni][:3, 3])
            ts.append(
                _accessor(gj, blob, pr["indices"]).reshape(-1, 3).astype(np.int64)
                + base
            )
            base += len(v)
        # glTF splits vertices along seams; weld them so each point counts once.
        v_all, t_all = np.vstack(vs), np.vstack(ts)
        _, first, inv = np.unique(
            np.round(v_all * 1e6).astype(np.int64),
            axis=0,
            return_index=True,
            return_inverse=True,
        )
        out.append(
            Shell(
                name=name,
                part=str(f.get("part", name)),
                kind=str(f.get("kind", "shell")),
                side=str(f.get("side", "")),
                bone=body.index(bone),
                verts=v_all[first],
                tris=inv.ravel()[t_all],
                gap_mm=float(f.get("fit_gap_mm", 0.0)),
                thickness_mm=float(f.get("thickness_mm", 0.0)),
            )
        )
    return out


def normals(verts: np.ndarray, tris: np.ndarray) -> np.ndarray:
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    n = np.cross(b - a, c - a)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-20)


def closest_on_tris(p, a, b, c) -> np.ndarray:
    """Closest points on triangles (a, b, c) to points p, broadcast (Ericson 5.1.5)."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
    bp = p - b
    d3, d4 = (ab * bp).sum(-1), (ac * bp).sum(-1)
    cp = p - c
    d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    eps = 1e-30
    denom = 1.0 / np.maximum(va + vb + vc, eps)
    res = a + ab * (vb * denom)[..., None] + ac * (vc * denom)[..., None]
    m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    t = d1 / np.where(np.abs(d1 - d3) > eps, d1 - d3, eps)
    res = np.where(m[..., None], a + ab * t[..., None], res)
    m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    t = d2 / np.where(np.abs(d2 - d6) > eps, d2 - d6, eps)
    res = np.where(m[..., None], a + ac * t[..., None], res)
    m = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    e = (d4 - d3) + (d5 - d6)
    t = (d4 - d3) / np.where(np.abs(e) > eps, e, eps)
    res = np.where(m[..., None], b + (c - b) * t[..., None], res)
    res = np.where(((d1 <= 0) & (d2 <= 0))[..., None], a, res)
    res = np.where(((d3 >= 0) & (d4 <= d3))[..., None], b, res)
    return np.where(((d6 >= 0) & (d5 <= d6))[..., None], c, res)


_OFF = 1 << 20


def _key(cells: np.ndarray) -> np.ndarray:
    c = cells.astype(np.int64) + _OFF
    return (c[..., 0] << 42) | (c[..., 1] << 21) | c[..., 2]


class TriGrid:
    """Triangles hashed into a uniform grid by their bounding boxes grown by
    ``reach``: every triangle within ``reach`` of a point is listed in the
    point's cell, so a query only meets nearby triangles. ``ids`` names the
    triangles in a larger mesh (several grids can share one query)."""

    def __init__(
        self,
        verts: np.ndarray,
        tris: np.ndarray,
        reach: float = 0.010,
        cell: float = 0.015,
        ids: np.ndarray | None = None,
    ):
        self.reach, self.cell = reach, cell
        self.ids = np.arange(len(tris)) if ids is None else np.asarray(ids)
        a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
        self.a, self.b, self.c = a, b, c
        self.norms = normals(verts, tris)
        # A bounding sphere per triangle about its centroid (a point on it):
        # cheap lower and upper bounds that let ``nearest`` skip most of the
        # exact point-triangle work.
        self.cen = (a + b + c) / 3.0
        self.rad = (
            np.sqrt(
                np.maximum.reduce(
                    [((x - self.cen) ** 2).sum(axis=1) for x in (a, b, c)]
                )
            )
            if len(tris)
            else np.zeros(0)
        )
        lo = np.floor((np.minimum(np.minimum(a, b), c) - reach) / cell).astype(np.int64)
        hi = np.floor((np.maximum(np.maximum(a, b), c) + reach) / cell).astype(np.int64)
        span = hi - lo + 1
        n = span.prod(axis=1)
        t = np.repeat(np.arange(len(tris)), n)
        k = np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n)
        sx, sy = span[t, 0], span[t, 1]
        cells = lo[t] + np.stack([k % sx, (k // sx) % sy, k // (sx * sy)], axis=1)
        key = _key(cells)
        order = np.argsort(key, kind="stable")
        ks = key[order]
        first = np.r_[True, ks[1:] != ks[:-1]] if len(ks) else np.zeros(0, bool)
        self.keys = ks[first]
        self.start = np.append(np.nonzero(first)[0], len(order))
        self.tri = t[order]
        self.lo = np.minimum(np.minimum(a, b), c) - reach
        self.hi = np.maximum(np.maximum(a, b), c) + reach
        self.box = (
            (
                (np.minimum(np.minimum(a, b), c).min(0) - reach)
                if len(tris)
                else np.zeros(3)
            ),
            (
                (np.maximum(np.maximum(a, b), c).max(0) + reach)
                if len(tris)
                else np.zeros(3)
            ),
        )

    def pairs(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(point index, triangle index) for every triangle in each point's cell."""
        if len(self.keys) == 0 or len(points) == 0:
            e = np.zeros(0, np.int64)
            return e, e
        key = _key(np.floor(points / self.cell))
        pos = np.minimum(np.searchsorted(self.keys, key), len(self.keys) - 1)
        hit = self.keys[pos] == key
        s = np.where(hit, self.start[pos], 0)
        cnt = np.where(hit, self.start[pos + 1] - self.start[pos], 0)
        p = np.repeat(np.arange(len(points)), cnt)
        off = np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        return p, self.tri[np.repeat(s, cnt) + off]

    def near(self, points: np.ndarray) -> np.ndarray:
        """Mask of the points that have any triangle in their cell."""
        if len(self.keys) == 0 or len(points) == 0:
            return np.zeros(len(points), bool)
        key = _key(np.floor(points / self.cell))
        pos = np.minimum(np.searchsorted(self.keys, key), len(self.keys) - 1)
        return self.keys[pos] == key


def nearest(
    points: np.ndarray, grids: list[TriGrid], signed: bool = True
) -> tuple[np.ndarray, np.ndarray]:
    """Distance from each point to the nearest triangle of all ``grids``
    within their reach, and that triangle's id (+inf and -1 where none comes
    that close). Signed: negative behind the nearest triangle; of near-ties
    (a shared edge or corner) the triangle seen most squarely decides."""
    n = len(points)
    dist, tri = np.full(n, np.inf), np.full(n, -1)
    reach = min(g.reach for g in grids) if grids else 0.0
    # Prune before the exact test. The centroid is on the triangle, so its
    # distance is an upper bound; the distance to the triangle's bounding
    # sphere and to its plane are lower ones. A candidate whose lower bound
    # passes the reach, or the point's least upper bound (plus the tie
    # margin the sign uses below), can not be the nearest.
    got, lbs, ubs = [], [], []
    for g in grids:
        p, t = g.pairs(points)
        q = points[p]
        d2 = ((q - g.cen[t]) ** 2).sum(axis=1)
        keep = d2 <= (g.rad[t] + reach) ** 2
        p, t, q = p[keep], t[keep], q[keep]
        if not len(p):
            continue
        dc = np.sqrt(d2[keep])
        plane = np.abs(((q - g.a[t]) * g.norms[t]).sum(axis=1))
        got.append((g, p, t))
        lbs.append(np.maximum(dc - g.rad[t], plane))
        ubs.append(dc)
    if not got:
        return dist, tri
    p = np.concatenate([x[1] for x in got])
    lb, ub = np.concatenate(lbs), np.concatenate(ubs)
    best = np.full(n, np.inf)
    np.minimum.at(best, p, ub)
    keep = lb <= np.minimum(best[p], reach) + 5e-5
    sel, lo = [], 0
    for g, _, t in got:
        sel.append(t[keep[lo : lo + len(t)]])
        lo += len(t)
    got = [(g, None, t) for (g, _, _), t in zip(got, sel)]
    p = p[keep]
    a = np.concatenate([g.a[t] for g, _, t in got])
    b = np.concatenate([g.b[t] for g, _, t in got])
    c = np.concatenate([g.c[t] for g, _, t in got])
    nm = np.concatenate([g.norms[t] for g, _, t in got])
    ids = np.concatenate([g.ids[t] for g, _, t in got])
    q = points[p]
    d = q - closest_on_tris(q, a, b, c)
    dd = np.linalg.norm(d, axis=1)
    keep = dd <= reach
    p, d, dd, nm, ids = p[keep], d[keep], dd[keep], nm[keep], ids[keep]
    if len(p) == 0:
        return dist, tri
    dmin = np.full(n, np.inf)
    np.minimum.at(dmin, p, dd)
    cosv = (d * nm).sum(axis=1) / np.maximum(dd, 1e-12)
    score = np.where(dd <= dmin[p] + 5e-5, np.abs(cosv), -1.0)
    order = np.lexsort((-score, p))
    first = order[np.r_[True, p[order][1:] != p[order][:-1]]]
    sgn = np.where(cosv[first] < 0, -1.0, 1.0) if signed else 1.0
    dist[p[first]] = dmin[p[first]] * sgn
    tri[p[first]] = ids[first]
    return dist, tri


def edges(tris: np.ndarray) -> np.ndarray:
    """Every edge of a triangle mesh once, as vertex index pairs."""
    e = np.sort(np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), axis=1)
    n = int(tris.max()) + 1 if len(tris) else 1
    key = np.unique(e[:, 0] * n + e[:, 1])
    return np.stack([key // n, key % n], axis=1)


def crossings(
    p0: np.ndarray, p1: np.ndarray, grid: TriGrid
) -> tuple[np.ndarray, np.ndarray]:
    """Segments p0 -> p1 that pass through a triangle of ``grid``: the
    crossing points (k, 3) and the grid triangle ids they cross."""
    none = np.zeros((0, 3)), np.zeros(0, np.int64)
    if len(p0) == 0:
        return none
    lo, hi = np.minimum(p0, p1), np.maximum(p0, p1)
    ok = np.nonzero(np.all((hi >= grid.box[0]) & (lo <= grid.box[1]), axis=1))[0]
    p0, p1 = p0[ok], p1[ok]
    # Sample each edge every ``reach`` so every triangle it could cross is met.
    k = np.ceil(np.linalg.norm(p1 - p0, axis=1) / grid.reach).astype(np.int64) + 1
    edge = np.repeat(np.arange(len(p0)), k)
    f = (np.arange(int(k.sum())) - np.repeat(np.cumsum(k) - k, k)) / np.repeat(
        np.maximum(k - 1, 1), k
    )
    i, t = grid.pairs(p0[edge] + (p1 - p0)[edge] * f[:, None])
    if len(i) == 0:
        return none
    nt = len(grid.a)
    pair = np.unique(edge[i] * nt + t)
    i, t = pair // nt, pair % nt
    o, dvec = p0[i], p1[i] - p0[i]
    e1, e2 = grid.b[t] - grid.a[t], grid.c[t] - grid.a[t]
    h = np.cross(dvec, e2)
    det = (e1 * h).sum(1)
    inv = 1.0 / np.where(np.abs(det) > 1e-18, det, 1.0)
    s = o - grid.a[t]
    u = (s * h).sum(1) * inv
    qv = np.cross(s, e1)
    v = (dvec * qv).sum(1) * inv
    w = (e2 * qv).sum(1) * inv
    hit = (
        (np.abs(det) > 1e-18) & (u >= 0) & (v >= 0) & (u + v <= 1) & (w >= 0) & (w <= 1)
    )
    return o[hit] + dvec[hit] * w[hit, None], grid.ids[t[hit]]
