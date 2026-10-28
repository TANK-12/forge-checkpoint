"""Reads a VRM character's humanoid skeleton straight from the .vrm file.

A .vrm is a binary glTF: the JSON chunk holds the node tree and the humanoid
bone map. This returns each humanoid bone's rest position in the body frame
(VRM normalised humanoid: +X left, +Y up, +Z forward), so bone lengths in the
physics come from the same character the page draws.
"""

from __future__ import annotations

import json
import struct
from functools import lru_cache
from pathlib import Path

import numpy as np


def _gltf_json(path: Path) -> dict:
    data = path.read_bytes()
    magic, _version, _length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError(f"{path.name} is not a binary glTF/VRM file")
    chunk_len, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != 0x4E4F534A:  # "JSON"
        raise ValueError(f"{path.name}: first chunk is not JSON")
    return json.loads(data[20 : 20 + chunk_len])


def _quat_matrix(q: list[float]) -> np.ndarray:
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def _local_matrix(node: dict) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T
    m = np.eye(4)
    m[:3, :3] = _quat_matrix(node.get("rotation", [0, 0, 0, 1])) @ np.diag(
        node.get("scale", [1, 1, 1])
    )
    m[:3, 3] = node.get("translation", [0, 0, 0])
    return m


@lru_cache(maxsize=8)
def load(path_str: str) -> dict:
    """Bone name -> rest position (list of 3 floats, body frame), plus facts."""
    path = Path(path_str)
    gj = _gltf_json(path)
    nodes = gj.get("nodes", [])
    ext = gj.get("extensions", {})
    if "VRMC_vrm" in ext:
        bones = {
            name: b["node"]
            for name, b in ext["VRMC_vrm"]["humanoid"]["humanBones"].items()
        }
        flip = False  # VRM 1.0 already faces +Z
        version = "1.0"
    elif "VRM" in ext:
        bones = {b["bone"]: b["node"] for b in ext["VRM"]["humanoid"]["humanBones"]}
        flip = True  # VRM 0.x faces -Z; turn it to face +Z like three-vrm does
        version = "0.x"
    else:
        raise ValueError(f"{path.name} has no VRM humanoid")
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i
    world: dict[int, np.ndarray] = {}

    def world_of(i: int) -> np.ndarray:
        if i not in world:
            m = _local_matrix(nodes[i])
            world[i] = world_of(parent[i]) @ m if i in parent else m
        return world[i]

    out = {}
    for name, idx in bones.items():
        p = world_of(idx)[:3, 3].copy()
        if flip:
            p = p * np.array([-1.0, 1.0, -1.0])
        out[name] = [float(x) for x in p]
    pos = {k: np.array(p) for k, p in out.items()}

    def dist(a: str, b: str) -> float:
        if a in pos and b in pos:
            return float(np.linalg.norm(pos[a] - pos[b]))
        return 0.0

    head_top = pos["head"][1] + 0.22 if "head" in pos else 0.0
    return {
        "file": path.name,
        "vrm_version": version,
        "bones": out,
        "lengths": {
            "upper_arm": dist("rightUpperArm", "rightLowerArm"),
            "forearm": dist("rightLowerArm", "rightHand"),
            "clavicle": dist("rightShoulder", "rightUpperArm"),
            "thigh": dist("rightUpperLeg", "rightLowerLeg"),
            "shank": dist("rightLowerLeg", "rightFoot"),
            "shoulder_width": dist("leftUpperArm", "rightUpperArm"),
        },
        "height_estimate_m": round(head_top, 3),
    }
