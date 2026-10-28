"""Close fit: the fitted suit's shells against the moving skin and each other.

Plays the shoulder motions with the suit from static/assets/suits on the VRM
body (``body.py``). Every sampled frame it measures how far each shell sits
from the skin (negative = inside it) and how far apart the shells are that
move against each other, and marks where the closest point is.

How it stays fast (a few seconds a suit): the skin is split once into the
triangles the arm moves and the ones it never moves. The still part is
hashed into a grid once; only the arm's triangles are re-skinned and
re-hashed per frame, and a query always looks at both, so every distance is
signed against the whole posed skin. A shell on a still bone only needs new
numbers where the moving skin comes near it; the rest is cached from the
first look. Shell pairs are measured in one shell's own rest frame against a
grid built once, and skipped while their bounding spheres are apart or the
two bones keep their rest relation.

The body can go through itself (an arm at the side sinks into the hips
under linear blend skinning). That is reported on its own as body
self-contact, and a contact between an arm shell and the torso (or a torso
shell and the arm) is not counted against the suit where the arm skin at
the contact, or within SELF_NEAR of it, is already inside the torso.

Only the right arm moves (the core poses the right arm; the page shows the
left at rest), so the left side's result is the right side's by symmetry.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from .. import body as B
from .. import human
from ..arm import Rig, character_path
from ..registry import NotFound
from . import (
    frame_json,
    gravest,
    keep_worst,
    level_of,
    motion_errors,
    play,
    sample,
    worst,
)

KIND = "close_fit"

# The bones human.vrm_bones turns; everything below them moves with them.
MOVING = ["rightShoulder", "rightUpperArm", "rightLowerArm"]
# Skin and shells carried by these and the bones below are "the arm".
ARM = ["rightUpperArm"]
CELL = 0.010  # grid cell, metres
# Cells for grids rebuilt every frame: a coarser cell builds several times
# faster and, since ``body.nearest`` prunes by bounds, queries about as fast.
CELL_FRAME = 0.02
CELL_DEEP = 0.04
SELF_MM = 2.0  # arm skin this deep inside the torso is body self-contact
SELF_REACH = 0.04  # how deep self-contact is looked for
SELF_NEAR = 0.03  # a contact this near body self-contact is the pose's
BLAME_NEAR = 0.025  # how far from a contact the arm skin under it can be
ARM_OFF = 0.003  # arm skin nearer the torso than this at rest is the seam
REACH_MM = (5.0, 20.0)  # how deep and far the run may look (grids grow fast)
MAX_FRAMES = 300  # frames a run may measure, all motions together
BLEND = 0.9  # skin under a shell with less weight on its bone is blended


def _label(name: str) -> str:
    base, _, side = name.rpartition("_")
    if side in ("L", "R") and base:
        return f"{base.replace('_', ' ')} {'left' if side == 'L' else 'right'}"
    return name.replace("_", " ")


def _level(mm: float, warn: float, fail: float) -> str:
    return "fail" if mm < fail else "warn" if mm < warn else "pass"


def _clusters(
    verts: np.ndarray, cell: float
) -> tuple[np.ndarray, list[np.ndarray], np.ndarray]:
    """Vertices grouped by grid cell: one representative per cell (the
    vertex nearest the cell's mean), each cell's members, and how far the
    members lie from their representative."""
    key = np.floor(verts / cell).astype(np.int64)
    inv = np.unique(key, axis=0, return_inverse=True)[1].ravel()
    n = int(inv.max()) + 1
    cen = np.zeros((n, 3))
    np.add.at(cen, inv, verts)
    cen /= np.bincount(inv, minlength=n)[:, None]
    order = np.lexsort((np.linalg.norm(verts - cen[inv], axis=1), inv))
    cut = np.r_[0, np.nonzero(np.diff(inv[order]))[0] + 1]
    first = order[cut]
    rad = np.zeros(n)
    np.maximum.at(rad, inv, np.linalg.norm(verts - verts[first[inv]], axis=1))
    return first, np.split(order, cut[1:]), rad


def _split(got: tuple[np.ndarray, np.ndarray], sizes: list[int]):
    """One query's (distances, triangles) back into per-shell pieces."""
    cut = np.cumsum(sizes)[:-1]
    return np.split(got[0], cut), np.split(got[1], cut)


def _overlap(a, b) -> bool:
    """Do two (lo, hi) boxes overlap?"""
    return bool(np.all(a[0] <= b[1]) and np.all(b[0] <= a[1]))


def _to_rest(
    pts: np.ndarray, b: int, rot: np.ndarray, pos: np.ndarray, rest: np.ndarray
):
    """World points into bone b's rest frame (inverse of ``body.carry``)."""
    return (pts - pos[b]) @ rot[b] + rest[b]


class Fit:
    """Body, shells and everything about them that does not change per frame."""

    def __init__(
        self,
        vrm: str,
        asset: str,
        mats: tuple[str, ...],
        reach: float,
        shells: list[B.Shell] | None = None,
    ):
        self.body = bd = B.load_body(vrm, mats)
        self.shells = B.load_suit(asset, vrm, mats) if shells is None else shells
        self.reach = reach
        moving = bd.below(MOVING)
        w_mov = (bd.weights * moving[bd.joints]).sum(axis=1)
        self.mv = np.nonzero(w_mov > 1e-6)[0]
        tmov = np.any(w_mov[bd.tris] > 1e-6, axis=1)
        self.tmov = np.nonzero(tmov)[0]
        self.still = B.TriGrid(
            bd.verts, bd.tris[~tmov], reach, CELL, ids=np.nonzero(~tmov)[0]
        )
        rest_arm = B.TriGrid(bd.verts, bd.tris[tmov], reach, CELL, ids=self.tmov)
        # Arm and torso: a contact between the two can be the pose's fault
        # rather than the suit's. Skin is "arm" where the upper arm and the
        # bones below carry most of it; a shell is when its bone is one of
        # them. The part of the torso that moves (the chest and back the
        # shoulder bone pulls) is re-posed per frame.
        w_arm = (bd.weights * bd.below(ARM)[bd.joints]).sum(axis=1)
        self.tri_arm = w_arm[bd.tris].mean(axis=1) > 0.5
        self.torso_mov = np.nonzero(tmov & ~self.tri_arm)[0]
        # The torso skin is open where the arm joins it: behind a triangle at
        # that cut "inside" means nothing, so those never show the body in
        # itself.
        on_arm = np.zeros(len(bd.verts), bool)
        on_arm[bd.tris[self.tri_arm].ravel()] = True
        self.cut = ~self.tri_arm & on_arm[bd.tris].any(axis=1)
        self.still_deep = B.TriGrid(
            bd.verts, bd.tris[~tmov], SELF_REACH, 0.02, ids=np.nonzero(~tmov)[0]
        )
        # The room the pose leaves between arm and torso is read on the arm
        # skin that stands clear of the torso at rest (not the armpit seam);
        # body self-contact on a sample of it every ~12 mm.
        torso_rest = [
            self.still,
            B.TriGrid(
                bd.verts, bd.tris[self.torso_mov], reach, CELL, ids=self.torso_mov
            ),
        ]
        arm = np.nonzero(w_arm > BLEND)[0]
        d0, _ = B.nearest(bd.verts[arm], torso_rest, signed=False)
        clear = arm[d0 > ARM_OFF]
        self.arm = clear[_clusters(bd.verts[clear], 0.012)[0]]
        free = np.zeros(len(bd.verts), bool)
        free[clear] = True
        self.arm_tris = np.nonzero(self.tri_arm & free[bd.tris].all(axis=1))[0]
        self.grids = [B.TriGrid(s.verts, s.tris, reach, CELL) for s in self.shells]
        self.edges = [B.edges(s.tris) for s in self.shells]
        self.skin_edges = B.edges(bd.tris)
        self.moves = [bool(moving[s.bone]) for s in self.shells]
        self.shell_arm = [bool(bd.below(ARM)[s.bone]) for s in self.shells]
        self.centre = [s.verts.mean(axis=0) for s in self.shells]
        self.radius = [
            float(np.linalg.norm(s.verts - c, axis=1).max())
            for s, c in zip(self.shells, self.centre)
        ]
        self.boxes = [(s.verts.min(0), s.verts.max(0)) for s in self.shells]
        self.cache: list[tuple[np.ndarray, np.ndarray]] = []
        self.rest: list[dict] = []
        for i, s in enumerate(self.shells):
            d, t = B.nearest(s.verts, [self.still, rest_arm])
            self.rest.append(self._rest_numbers(s, d, t))
            # A still shell keeps these numbers wherever the arm is not near.
            self.cache.append(
                B.nearest(s.verts, [self.still]) if not self.moves[i] else (d, t)
            )
        self.pairs: list[tuple[int, int, float]] = []
        n = len(self.shells)
        for a in range(n):
            for b in range(a + 1, n):
                sa, sb = self.shells[a], self.shells[b]
                if sa.bone == sb.bone or not (self.moves[a] or self.moves[b]):
                    continue
                self.pairs.append((a, b, self._pair_rest(a, b)))
        self.bone_of = np.array([s.bone for s in self.shells], np.int64)
        self.centres = np.array(self.centre).reshape(-1, 3)
        self.radii = np.array(self.radius)
        self.pair_ab = np.array([p[:2] for p in self.pairs], np.int64).reshape(-1, 2)

    def _rest_numbers(self, s: B.Shell, d: np.ndarray, t: np.ndarray) -> dict:
        ok = np.isfinite(d)
        if not ok.any():
            return {"min_mm": None, "median_inner_mm": None, "region": ""}
        k = int(np.argmin(np.where(ok, d, np.inf)))
        inner = d[ok & (d < (s.gap_mm + s.thickness_mm / 2) / 1000.0)]
        return {
            "min_mm": round(float(d[k]) * 1000.0, 2),
            "median_inner_mm": (
                round(float(np.median(inner)) * 1000.0, 2) if len(inner) else None
            ),
            "region": B.bone_words(self.body.bones[int(self.body.tri_bone[t[k]])]),
        }

    def _live(self, rot: np.ndarray, pos: np.ndarray) -> np.ndarray:
        """The pairs worth measuring in a pose: their bounding spheres come
        within reach and their two bones have left their rest relation."""
        if not len(self.pairs):
            return np.zeros(0, np.int64)
        k = self.bone_of
        r = rot[k]
        off = pos[k] - np.einsum("nij,nj->ni", r, self.body.rest[k])
        cen = np.einsum("nij,nj->ni", r, self.centres) + off
        a, b = self.pair_ab.T
        near = np.linalg.norm(cen[a] - cen[b], axis=1) <= (
            self.radii[a] + self.radii[b] + self.reach
        )
        same = (np.abs(r[a] - r[b]).max(axis=(1, 2)) <= 1e-9) & (
            np.abs(off[a] - off[b]).max(axis=1) <= 1e-9
        )
        return np.nonzero(near & ~same)[0]

    def _pair_rest(self, a: int, b: int) -> float:
        da, _ = B.nearest(self.shells[a].verts, [self.grids[b]], signed=False)
        db, _ = B.nearest(self.shells[b].verts, [self.grids[a]], signed=False)
        return float(min(da.min(), db.min()))

    def pose(self, local: dict[str, list[float]]):
        """Bone frames, posed skin and the moving skin's grid for a pose."""
        bd = self.body
        rot, pos = B.bone_frames(bd, local)
        verts = bd.verts.copy()
        verts[self.mv] = B.skin_rows(bd, rot, pos, self.mv)
        arm = B.TriGrid(
            verts, bd.tris[self.tmov], self.reach, CELL_FRAME, ids=self.tmov
        )
        return rot, pos, verts, arm

    def blend(self, i: int, tri: int) -> str:
        """For a shell resting on skin it shares a side with: how much of
        that skin another bone carries, as words, or '' when the shell's
        own bone carries it (the result then hangs on the skin weights)."""
        bd, s = self.body, self.shells[i]
        v = bd.tris[tri]
        acc = np.zeros(len(bd.bones))
        np.add.at(acc, bd.joints[v].ravel(), bd.weights[v].ravel() / 3.0)
        if acc[s.bone] >= BLEND:
            return ""
        acc[s.bone] = 0.0
        o = int(np.argmax(acc))
        return (
            f"the skin there is {acc[o] * 100:.0f}% on the {B.bone_words(bd.bones[o])}"
        )

    def _skins(self, rot, pos, verts, grids, arm, room, rules) -> list:
        """Every shell's least clearance to the posed skin, not counting
        contacts that are the body's own: per shell (mm, where, skin
        triangle), or None when no skin comes within reach.

        Moving shells are measured at every vertex (a shell has a vertex
        every 3 to 9 mm, too few to gain from going coarse to fine against
        skin that is all within reach). Still shells keep their cached
        numbers except where the moving skin comes near. All shells share
        one query (a numpy call costs more than its points here)."""
        bd = self.body
        warn = rules["warn_mm"] / 1000.0
        n = len(self.shells)
        pts = [
            B.carry(s.verts, s.bone, bd, rot, pos) if self.moves[i] else s.verts
            for i, s in enumerate(self.shells)
        ]
        mov = [i for i in range(n) if self.moves[i]]
        idx: list[np.ndarray] = [np.zeros(0, np.int64)] * n
        d: list[np.ndarray] = [np.zeros(0)] * n
        t: list[np.ndarray] = [np.zeros(0, np.int64)] * n
        for i in mov:
            idx[i] = np.arange(len(pts[i]))
            d[i], t[i] = np.full(len(pts[i]), np.inf), np.full(len(pts[i]), -1)
        # Every point of the moving shells against the whole posed skin, and
        # the points of the still shells the moving skin comes near against
        # that skin only: the nearer of it and the cached still skin is the
        # nearest triangle of the whole skin, and its side gives the sign.
        ask = [(i, idx[i]) for i in mov]
        near: list[tuple[int, np.ndarray]] = []
        for i in range(n):
            if self.moves[i]:
                continue
            cd, ct = self.cache[i]
            m = (
                arm.near(pts[i])
                if _overlap(arm.box, self.boxes[i])
                else np.zeros(len(pts[i]), bool)
            )
            idx[i] = np.nonzero(m | np.isfinite(cd))[0]
            d[i], t[i] = cd[idx[i]].copy(), ct[idx[i]].copy()
            redo = np.nonzero(m[idx[i]])[0]
            if len(redo):
                near.append((i, redo))
        for todo, gs in ((near, [arm]), (ask, grids)):
            if not todo:
                continue
            q = np.vstack([pts[i][idx[i][k]] for i, k in todo])
            got = _split(B.nearest(q, gs), [len(k) for _, k in todo])
            for (i, k), di, ti in zip(todo, *got):
                if gs is grids:
                    d[i][k], t[i][k] = di, ti
                    continue
                # Near-ties (a seam between the two parts) take the whole
                # skin's rule for the sign: asked again with the rest.
                with np.errstate(invalid="ignore"):
                    gap = np.abs(di) - np.abs(d[i][k])
                eq = np.abs(np.where(np.isfinite(gap), gap, 1.0)) <= 5e-5
                nearer = (gap < 0) & ~eq
                d[i][k[nearer]], t[i][k[nearer]] = di[nearer], ti[nearer]
                if eq.any():
                    ask.append((i, k[eq]))
        # Which arm-torso contacts the body causes: one question for all.
        ok = [np.isfinite(di) for di in d]
        cross = [
            ok[i]
            & (d[i] < warn)
            & (self.tri_arm[np.maximum(t[i], 0)] != self.shell_arm[i])
            for i in range(n)
        ]
        cp = [pts[i][idx[i][cross[i]]] for i in range(n)]
        if sum(len(c) for c in cp):
            body = np.split(
                room.body_at(np.vstack(cp)), np.cumsum([len(c) for c in cp])[:-1]
            )
            for i in range(n):
                ok[i][np.nonzero(cross[i])[0]] = ~body[i]
        out: list = []
        for i in range(n):
            if not ok[i].any():
                out.append(None)
                continue
            k = int(np.argmin(np.where(ok[i], d[i], np.inf)))
            mm, at, tri = float(d[i][k]) * 1000.0, pts[i][idx[i][k]], int(t[i][k])
            if mm < 0 and self._deeper(i, idx[i], d[i], ok[i], pts[i], room):
                mm = -self.reach * 1000.0
            if 0 <= mm < rules["warn_mm"]:
                got1 = self._touch(
                    i,
                    pts[i],
                    idx[i],
                    ok[i] & (d[i] < warn),
                    t[i],
                    tri,
                    rot,
                    pos,
                    verts,
                    grids,
                    room,
                )
                if got1 is not None:
                    mm, (at, tri) = 0.0, got1
            out.append((mm, at, tri))
        return out

    def _deeper(self, i, idx, d, ok, pts, room) -> bool:
        """Whether shell i goes deeper into the skin than its deepest point
        in reach: a counted inside point has an edge to a point past the
        reach too short to have come back out (a signed distance changes
        no faster than the edge is long), so that point is further in. A
        point the body's own contact explains does not count."""
        s = self.shells[i]
        far = np.ones(len(s.verts), bool)
        far[idx[np.isfinite(d)]] = False
        depth = np.full(len(s.verts), -np.inf)  # only inside points count
        inside = ok & (d < 0)
        depth[idx[inside]] = -d[inside]
        e = self.edges[i]
        short = np.linalg.norm(s.verts[e[:, 0]] - s.verts[e[:, 1]], axis=1) - self.reach
        deep = np.concatenate(
            [
                e[far[e[:, 1]] & (short < depth[e[:, 0]]), 1],
                e[far[e[:, 0]] & (short < depth[e[:, 1]]), 0],
            ]
        )
        if not len(deep):
            return False
        return bool((~room.body_at(pts[np.unique(deep)])).any())

    def _touch(self, i, pts, idx, near, t, tri, rot, pos, verts, grids, room):
        """No vertex of shell i is inside, but a skin bump can still poke
        between them: test the shell's edges near the skin, and the skin's
        edges there. (where, skin triangle) of a crossing, or None."""
        bd, s = self.body, self.shells[i]
        close = np.zeros(len(s.verts), bool)
        close[idx[near]] = True
        e = self.edges[i][close[self.edges[i]].any(axis=1)]
        xp, xt = [], []
        for g in grids:
            x, tt = B.crossings(pts[e[:, 0]], pts[e[:, 1]], g)
            xp.append(x)
            xt.append(tt)
        vt = np.zeros(len(verts), bool)
        vt[bd.tris[np.unique(t[near])].ravel()] = True
        se = self.skin_edges[vt[self.skin_edges].any(axis=1)]
        q0 = _to_rest(verts[se[:, 0]], s.bone, rot, pos, bd.rest)
        q1 = _to_rest(verts[se[:, 1]], s.bone, rot, pos, bd.rest)
        xs, _ = B.crossings(q0, q1, self.grids[i])
        # A skin edge through the shell: name the skin by the nearest hit.
        xp.append(B.carry(xs, s.bone, bd, rot, pos))
        xt.append(np.full(len(xs), tri))
        xa, xta = np.vstack(xp), np.concatenate(xt).astype(np.int64)
        if not len(xa):
            return None
        keep = np.ones(len(xa), bool)
        cross = self.tri_arm[xta] != self.shell_arm[i]
        if cross.any():
            keep[cross] = ~room.body_at(xa[cross])
        hit = np.nonzero(keep)[0]
        return (xa[hit[0]], int(xta[hit[0]])) if len(hit) else None

    def _side(self, a: int, b: int, pts: np.ndarray):
        """Shell a's points (already in shell b's rest frame) against shell
        b: (signed distances, which points), only the points in reach of b.
        (Going coarse to fine saved nothing: shells that come near each
        other come near along whole rims.)"""
        lo, hi = self.grids[b].box
        idx = np.nonzero(np.all((pts >= lo) & (pts <= hi), axis=1))[0]
        d = B.nearest(pts[idx], [self.grids[b]])[0]
        # A shell is a thin closed solid: a point behind one of its
        # triangles but further than its thickness is not in its wall (the
        # sign of a far point near a rim is not to be trusted).
        wall = self.shells[b].thickness_mm / 1000.0 + 0.0005
        return np.where(d < -wall, -d, d), idx

    def _pair(self, a: int, b: int, rot, pos, room, rules):
        """Least gap between shells a and b (negative = one inside the
        other's wall, 0 = their surfaces cross) and where, or None when
        they are out of reach or only meet where the body is in itself."""
        bd, sa, sb = self.body, self.shells[a], self.shells[b]
        wa = B.carry(sa.verts, sa.bone, bd, rot, pos)
        pa = _to_rest(wa, sb.bone, rot, pos, bd.rest)
        box = self.grids[b].box
        if np.any(pa.min(0) > box[1]) or np.any(pa.max(0) < box[0]):
            return None
        wb = B.carry(sb.verts, sb.bone, bd, rot, pos)
        pb = _to_rest(wb, sa.bone, rot, pos, bd.rest)
        lim = rules["shell_warn_mm"] / 1000.0
        da, ia = self._side(a, b, pa)
        db, ib = self._side(b, a, pb)
        d = np.concatenate([da, db])
        at = np.vstack([wa[ia], wb[ib]])
        ok = np.isfinite(d)
        cross = self.shell_arm[a] != self.shell_arm[b]
        if cross:
            c = np.nonzero(ok & (d < lim))[0]
            ok[c] = ~room.body_at(at[c])
        if not ok.any():
            return None
        k = int(np.argmin(np.where(ok, d, np.inf)))
        mm, where = float(d[k]) * 1000.0, at[k]
        if 0 <= mm < rules["shell_warn_mm"]:
            near = ok & (d < lim)
            for sh, pts, idx, nr, other, bone in (
                (a, pa, ia, near[: len(da)], b, sb.bone),
                (b, pb, ib, near[len(da) :], a, sa.bone),
            ):
                close = np.zeros(len(pts), bool)
                close[idx[nr]] = True
                e = self.edges[sh][close[self.edges[sh]].any(axis=1)]
                xp, _ = B.crossings(pts[e[:, 0]], pts[e[:, 1]], self.grids[other])
                if len(xp):
                    xw = B.carry(xp, bone, bd, rot, pos)
                    if cross:
                        xw = xw[~room.body_at(xw)]
                    if len(xw):
                        return 0.0, xw[0]
        return mm, where

    def frame(self, local: dict[str, list[float]], rules: dict) -> dict:
        """Everything close_fit finds in one pose: issues, clash marks, the
        clearance of every shell to the skin and of every moving pair (mm),
        and the body's own self-contact."""
        bd = self.body
        rot, pos, verts, arm = self.pose(local)
        grids = [self.still, arm]
        room = Room(self, verts)
        issues: list[dict] = []
        marks: list[dict] = []
        skin: dict[str, dict] = {}
        pairs: dict[str, dict] = {}
        cap = self.reach * 1000.0 - 0.5

        def note(level, code, part, text, mm, at, other):
            issues.append(
                {
                    "level": level,
                    "code": code,
                    "part": part,
                    "text": text,
                    "value": round(mm, 2),
                }
            )
            marks.append(
                {
                    "part": part,
                    "with": other,
                    "level": level,
                    "mm": round(mm, 1),
                    "at": [round(float(x), 4) for x in at],
                }
            )

        def why(cross: bool, at: np.ndarray) -> str:
            """For a contact between arm and torso: the room the pose leaves."""
            if not cross:
                return ""
            r = float(room.least(at[None])[0])
            if not np.isfinite(r):
                return ""
            mm = r * 1000.0
            if mm < -0.5:
                return f"the pose already has the skin {-mm:.0f} mm in itself there"
            if mm < 0.5:
                return "the pose already has the skin touching itself there"
            return f"the pose leaves {mm:.0f} mm of skin to skin"

        # The body against itself: arm skin inside the torso skin.
        body = room.self_contact()
        if body:
            marks.append(
                {
                    "part": "body",
                    "with": body["torso"],
                    "level": "body",
                    "mm": body["mm"],
                    "at": [round(float(x), 4) for x in body["at"]],
                }
            )

        for i, got in enumerate(self._skins(rot, pos, verts, grids, arm, room, rules)):
            s = self.shells[i]
            if got is None:
                continue
            mm, at, tri = got
            region = B.bone_words(bd.bones[int(bd.tri_bone[tri])])
            skin[s.name] = {"mm": round(mm, 2), "against": region}
            lvl = _level(mm, rules["warn_mm"], rules["fail_mm"] + 1e-9)
            if lvl == "pass":
                continue
            name = _label(s.name)
            if mm < 0:
                deep = f"{cap + 0.5:.0f} mm or more" if -mm >= cap else f"{-mm:.1f} mm"
                text = f"{name} {deep} into the {region}"
            elif mm == 0:
                text = f"{name} touches the {region}"
            else:
                text = f"{name} {mm:.1f} mm from the {region}"
            cross = bool(self.tri_arm[tri] != self.shell_arm[i])
            extra = why(cross, at) if cross else self.blend(i, tri)
            note(
                lvl,
                "fit",
                s.name,
                f"{text} ({extra})" if extra else text,
                mm,
                at,
                region,
            )

        for j in self._live(rot, pos):
            a, b, gap0 = self.pairs[j]
            sa, sb = self.shells[a], self.shells[b]
            got = self._pair(a, b, rot, pos, room, rules)
            if got is None:
                continue
            mm, at = got
            name = f"{sa.name}+{sb.name}"
            pairs[name] = {"mm": round(mm, 2), "rest_mm": _mm(gap0 * 1000.0)}
            lvl = _level(mm, rules["shell_warn_mm"], rules["shell_fail_mm"])
            if lvl == "pass":
                continue
            text = (
                f"{_label(sa.name)} overlaps the {_label(sb.name)}"
                if mm <= 0
                else f"{_label(sa.name)} {mm:.1f} mm from the {_label(sb.name)}"
            )
            extra = why(self.shell_arm[a] != self.shell_arm[b], at)
            note(
                lvl,
                "overlap",
                name,
                f"{text} ({extra})" if extra else text,
                mm,
                at,
                sb.name,
            )

        return {
            "issues": issues,
            "marks": marks,
            "skin": skin,
            "pairs": pairs,
            "body": body,
        }


class Room:
    """The room one pose leaves between the arm skin and the torso skin,
    read only where a contact asks for it, and the body's self-contact."""

    def __init__(self, fit: Fit, verts: np.ndarray):
        self.fit, self.verts = fit, verts
        self._grids: list[B.TriGrid] | None = None
        self._near: list[B.TriGrid] | None = None
        self._arm: B.TriGrid | None = None
        self.inside = np.zeros((0, 3))

    def torso(self) -> list[B.TriGrid]:
        """The posed torso skin, reaching SELF_REACH."""
        if self._grids is None:
            f = self.fit
            mov = B.TriGrid(
                self.verts,
                f.body.tris[f.torso_mov],
                SELF_REACH,
                CELL_DEEP,
                ids=f.torso_mov,
            )
            self._grids = [f.still_deep, mov]
        return self._grids

    def torso_near(self) -> list[B.TriGrid]:
        """The posed torso skin, reaching only the fit's reach: enough to
        tell arm skin a little inside the torso (deeper is self-contact)."""
        if self._near is None:
            f = self.fit
            mov = B.TriGrid(
                self.verts,
                f.body.tris[f.torso_mov],
                f.reach,
                CELL_FRAME,
                ids=f.torso_mov,
            )
            self._near = [f.still, mov]
        return self._near

    def self_contact(self) -> dict | None:
        """The deepest arm sample inside the torso, or None; keeps every
        sample in self-contact for ``body_at``."""
        f, bd = self.fit, self.fit.body
        pts = self.verts[f.arm]
        ds, dt = B.nearest(pts, self.torso())
        deep = (ds < -SELF_MM / 1000.0) & ~f.cut[np.maximum(dt, 0)]
        self.inside = pts[deep]
        if not deep.any():
            return None
        k = int(np.argmin(ds))
        return {
            "mm": round(float(-ds[k]) * 1000.0, 1),
            "arm": B.bone_words(bd.bones[int(bd.joints[f.arm[k], 0])]),
            "torso": B.bone_words(bd.bones[int(bd.tri_bone[dt[k]])]),
            "at": pts[k],
        }

    def least(self, pts: np.ndarray) -> np.ndarray:
        """Per point, the room (metres, negative = inside the torso) at the
        nearest arm skin within BLAME_NEAR; +inf where no arm skin is that
        near or the torso is further than the reach from it."""
        out = np.full(len(pts), np.inf)
        f = self.fit
        if self._arm is None:
            self._arm = B.TriGrid(
                self.verts,
                f.body.tris[f.arm_tris],
                BLAME_NEAR,
                CELL_DEEP,
                ids=f.arm_tris,
            )
        d, t = B.nearest(pts, [self._arm], signed=False)
        ok = np.nonzero(np.isfinite(d))[0]
        if not len(ok):
            return out
        tri = f.body.tris[t[ok]]
        v = self.verts
        on = B.closest_on_tris(pts[ok], v[tri[:, 0]], v[tri[:, 1]], v[tri[:, 2]])
        d, t = B.nearest(on, self.torso_near())
        out[ok] = np.where(f.cut[np.maximum(t, 0)], np.inf, d)
        return out

    def body_at(self, pts: np.ndarray) -> np.ndarray:
        """Mask of the contacts at ``pts`` the body causes: the arm skin
        there is inside the torso, or body self-contact is within SELF_NEAR."""
        out = self.least(pts) < -SELF_MM / 1000.0
        if len(self.inside) and len(pts):
            for lo in range(0, len(pts), 256):
                q = pts[lo : lo + 256]
                d2 = ((q[:, None, :] - self.inside[None, :, :]) ** 2).sum(axis=2)
                out[lo : lo + 256] |= d2.min(axis=1) < SELF_NEAR**2
        return out


@lru_cache(maxsize=4)
def fit_for(vrm: str, asset: str, mats: tuple[str, ...], reach: float) -> Fit:
    return Fit(vrm, asset, mats, reach)


def rules_of(prm: dict) -> dict:
    return {
        "warn_mm": float(prm.get("warn_mm", 3.0)),
        "fail_mm": float(prm.get("fail_mm", 0.0)),
        "shell_warn_mm": float(prm.get("shell_warn_mm", 3.0)),
        "shell_fail_mm": float(prm.get("shell_fail_mm", 0.5)),
    }


def reach_of(prm: dict) -> float:
    """The test's reach_mm once a run can use it: within REACH_MM and above
    each warn distance (a ValueError says which not)."""
    rules = rules_of(prm)
    reach_mm = float(prm.get("reach_mm", 10))
    if not REACH_MM[0] <= reach_mm <= REACH_MM[1]:
        raise ValueError(
            f"reach_mm must be {REACH_MM[0]:g} to {REACH_MM[1]:g} (it is {reach_mm:g})"
        )
    if max(rules["warn_mm"], rules["shell_warn_mm"]) >= reach_mm:
        raise ValueError("the warn distances must be under reach_mm")
    return reach_mm


def too_many(frames: int) -> str | None:
    """Why a run measuring this many frames is refused, or None."""
    if frames <= MAX_FRAMES:
        return None
    return (
        f"{frames} frames is too slow for the close fit test; the most is"
        f" {MAX_FRAMES}: lower the frame rate or pick fewer motions"
    )


def save_errors(test: dict, reg, prof: dict) -> list[str]:
    """What a run of this test would refuse in a saved profile: its reach
    and warn distances, a motion it plays, too many frames in all."""
    prm = test.get("params") or {}
    errors: list[str] = []
    try:
        reach_of(prm)
    except ValueError as e:
        errors.append(f"test {test.get('id')}: {e}")
    ids = prm.get("motions", reg.ids("motions"))
    bad, frames = motion_errors(reg, prof, ids, float(prm.get("fps", 8)))
    too = None if bad else too_many(frames)
    return errors + bad + ([f"test {test.get('id')}: {too}"] if too else [])


def run(rig: Rig, test: dict, reg) -> dict:
    prm = test.get("params", {})
    rules = rules_of(prm)
    reach_mm = reach_of(prm)
    asset = reg.get("models", rig.model_id).get("suit_asset")
    if not asset:
        raise ValueError(f"{rig.model_id} has no fitted suit to check")
    fit = fit_for(
        str(character_path(rig.character)),
        str(asset),
        tuple(prm.get("skin_materials", ["_SKIN"])),
        reach_mm / 1000.0,
    )
    fps = float(prm.get("fps", 8))
    only = prm.get("only")
    ids = [m for m in prm.get("motions", reg.ids("motions")) if not only or m == only]
    if only and not ids:
        raise NotFound(f"no motion named {only!r} in this test")
    moves = {m: reg.effective("motions", m, rig.profile) for m in ids}
    too = too_many(sum(len(sample(mo["keys"], fps)) for mo in moves.values()))
    if too:
        raise ValueError(too)
    verdict = "pass"
    motions = []
    low: dict[str, dict] = {}
    self_worst: dict | None = None
    # Motions start and end in shared poses: each pose is measured once.
    seen: dict[tuple, dict] = {}
    for mid in ids:
        mo = moves[mid]
        payload = float(mo.get("payload_kg", 0.0))
        frames, lvl = [], "pass"
        worst_issue: dict[tuple[str, str], dict] = {}
        least_skin, least_shell, body_mm = np.inf, np.inf, 0.0
        for fr, ld, speeds in play(rig, mo["keys"], fps, payload):
            local = human.vrm_bones(fr.pose)
            key = tuple((k, *np.round(v, 9)) for k, v in sorted(local.items()))
            if key not in seen:
                seen[key] = fit.frame(local, rules)
            got = seen[key]
            issues = got["issues"]
            lvl = worst(lvl, level_of(issues))
            keep_worst(worst_issue, issues)
            where = {
                "motion": mo.get("name", mid),
                "motion_id": mid,
                "t": round(fr.t, 2),
            }
            for name, x in list(got["skin"].items()) + list(got["pairs"].items()):
                if name not in low or x["mm"] < low[name]["mm"]:
                    low[name] = dict(x, **where)
            least_skin = min([least_skin, *(x["mm"] for x in got["skin"].values())])
            least_shell = min([least_shell, *(x["mm"] for x in got["pairs"].values())])
            bod = got["body"]
            if bod:
                body_mm = max(body_mm, bod["mm"])
                if self_worst is None or bod["mm"] > self_worst["mm"]:
                    self_worst = {
                        "mm": bod["mm"],
                        "arm": bod["arm"],
                        "torso": bod["torso"],
                        **where,
                    }
            fj = frame_json(rig, fr, ld, issues, speeds)
            fj["clash"] = [dict(m) for m in got["marks"]]
            fj["fit"] = {
                "skin": got["skin"],
                "pairs": got["pairs"],
                "body_mm": bod["mm"] if bod else 0.0,
            }
            frames.append(fj)
        verdict = worst(verdict, lvl)
        motions.append(
            {
                "id": mid,
                "name": mo.get("name", mid),
                "about": mo.get("about", ""),
                "payload_kg": payload,
                "level": lvl,
                "issues": gravest(list(worst_issue.values())),
                "peaks": {
                    "min_skin_mm": _mm(least_skin),
                    "min_shell_mm": _mm(least_shell),
                    "body_self_mm": round(body_mm, 1),
                },
                "frames": frames,
            }
        )
    shells = []
    for i, s in enumerate(fit.shells):
        lo, r = low.get(s.name), fit.rest[i]
        if (
            lo
            and not fit.moves[i]
            and r["min_mm"] is not None
            and lo["mm"] >= r["min_mm"] - 0.05
        ):
            lo = None  # a still shell the moving arm never brought nearer
        mm = lo["mm"] if lo else r["min_mm"]
        shells.append(
            {
                "name": s.name,
                "label": _label(s.name),
                "bone": B.bone_words(fit.body.bones[s.bone]),
                "moves": fit.moves[i],
                "fit_gap_mm": s.gap_mm,
                "rest_mm": r["min_mm"],
                "rest_median_mm": r["median_inner_mm"],
                "min_mm": mm,
                "against": lo["against"] if lo else r["region"],
                "where": f"{lo['motion']} {lo['t']:.2f} s" if lo else "at rest",
                "motion_id": lo["motion_id"] if lo else None,
                "t": lo["t"] if lo else None,
                "level": (
                    "pass"
                    if mm is None
                    else _level(mm, rules["warn_mm"], rules["fail_mm"] + 1e-9)
                ),
            }
        )
    shells.sort(key=lambda r: (r["min_mm"] is None, r["min_mm"] or 0.0))
    pairs = []
    for a, b, gap0 in fit.pairs:
        name = f"{fit.shells[a].name}+{fit.shells[b].name}"
        # Two shells on bones that keep their rest relation are not measured
        # in a frame: one built too near the other shows at rest.
        rest = gap0 * 1000.0
        if rest < rules["shell_warn_mm"] and (
            name not in low or low[name]["mm"] > rest
        ):
            low[name] = {"mm": round(rest, 2), "motion": "at rest", "motion_id": None}
            lvl = _level(rest, rules["shell_warn_mm"], rules["shell_fail_mm"])
            verdict = worst(verdict, lvl)
        if name not in low:
            continue
        lo = low[name]
        pairs.append(
            {
                "name": name,
                "a": _label(fit.shells[a].name),
                "b": _label(fit.shells[b].name),
                "rest_mm": _mm(gap0 * 1000.0),
                "min_mm": lo["mm"],
                "where": (
                    f"{lo['motion']} {lo['t']:.2f} s" if lo["motion_id"] else "at rest"
                ),
                "motion_id": lo["motion_id"],
                "t": lo.get("t"),
                "level": _level(
                    lo["mm"], rules["shell_warn_mm"], rules["shell_fail_mm"]
                ),
            }
        )
    pairs.sort(key=lambda r: r["min_mm"])
    cards = _cards(shells, pairs, self_worst, fit.reach * 1000.0)
    edits = (rig.profile or {}).get("overrides", {}).get("models", {})
    if any(k.startswith("shells.") for k in edits.get(rig.model_id, {})):
        cards.append(
            {
                "level": "out",
                "title": "Shell edits",
                "value": "not used",
                "text": "this test reads the fitted suit file; the profile's shell"
                " gap and thickness edits do not move its shells",
            }
        )
    return {
        "kind": KIND,
        "verdict": verdict,
        "cards": cards,
        "motions": motions,
        "shells": shells,
        "pairs": pairs,
        "body_self": self_worst,
        "rules": rules,
        # Depths are only looked for this far: a shell this deep in the skin
        # is at least this deep.
        "reach_mm": round(fit.reach * 1000.0, 1),
        "suit": str(asset),
    }


def _mm(x: float) -> float | None:
    return round(float(x), 1) if np.isfinite(x) else None


def _cards(
    shells: list[dict], pairs: list[dict], body: dict | None, reach: float
) -> list[dict]:
    out = []
    near = [
        s
        for s in shells
        if s["min_mm"] is not None and (s["moves"] or s["where"] != "at rest")
    ]
    for s in near[:6]:
        mm = s["min_mm"]
        out.append(
            {
                "level": s["level"],
                "title": f"{s['label']} to skin",
                "value": (
                    f"{reach:.0f} mm or more in"
                    if mm <= -(reach - 0.5)
                    else f"{mm:.1f} mm"
                ),
                "text": (
                    f"closest to the {s['against']} in {s['where']}; "
                    f"{s['rest_mm']:.1f} mm at rest, fitted at {s['fit_gap_mm']:g} mm"
                    if s["rest_mm"] is not None
                    else f"closest to the {s['against']} in {s['where']}"
                ),
            }
        )
    for p in pairs[:6]:
        rest = (
            f"{p['rest_mm']:g} mm apart at rest"
            if p["rest_mm"] is not None
            else ("more than the reach apart at rest")
        )
        out.append(
            {
                "level": p["level"],
                "title": f"{p['a']} / {p['b']}",
                "value": "overlap" if p["min_mm"] <= 0 else f"{p['min_mm']:.1f} mm",
                "text": f"closest in {p['where']}; {rest}",
            }
        )
    # Self-contact is only looked for SELF_REACH deep.
    cap = SELF_REACH * 1000.0 - 0.5
    deep = (
        ""
        if not body
        else (
            f"{body['mm']:.0f} mm"
            if body["mm"] < cap
            else f"{cap + 0.5:.0f} mm or more"
        )
    )
    out.append(
        {
            "level": "out" if body else "pass",
            "title": "Body self-contact",
            "value": deep or "none",
            "text": (
                f"the pose pushes the {body['arm']} {deep} into the "
                f"{body['torso']} in {body['motion']} {body['t']:.2f} s (a limit of "
                "the pose, not the suit); suit contacts there are not counted"
                if body
                else "the arm skin never goes into the torso"
            ),
        }
    )
    return out
