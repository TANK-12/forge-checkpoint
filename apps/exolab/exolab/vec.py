"""Small rotation and vector helpers on numpy (3-vectors and 3x3 matrices)."""

from __future__ import annotations

import math

import numpy as np

Vec = np.ndarray
Mat = np.ndarray

# Arm frame (x forward, y up, z right) to body frame (x left, y up, z forward)
# for the right arm. The left arm mirrors x.
ARM_TO_BODY_RIGHT = np.array([[0.0, 0.0, -1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]])


def v(x: float, y: float, z: float) -> Vec:
    return np.array([x, y, z], dtype=float)


def norm(a: Vec) -> float:
    return math.sqrt(float(np.dot(a, a)))


def cross(a: Vec, b: Vec) -> Vec:
    """a x b for two 3-vectors. np.cross costs about 30 us a call on vectors
    this small and was 70% of a shoulder range sweep; this is about 2 us."""
    a0, a1, a2 = a.tolist() if isinstance(a, np.ndarray) else a
    b0, b1, b2 = b.tolist() if isinstance(b, np.ndarray) else b
    return np.array((a1 * b2 - a2 * b1, a2 * b0 - a0 * b2, a0 * b1 - a1 * b0))


def unit(a: Vec, fallback: Vec | None = None) -> Vec:
    n = math.sqrt(float(np.dot(a, a)))
    if n < 1e-12:
        return np.array(fallback if fallback is not None else (1.0, 0.0, 0.0))
    return a / n


def rot(axis: Vec, angle: float) -> Mat:
    """Rotation matrix about a unit axis by an angle in radians (Rodrigues)."""
    x, y, z = unit(axis)
    c, s = math.cos(angle), math.sin(angle)
    k = 1.0 - c
    return np.array(
        [
            [c + x * x * k, x * y * k - z * s, x * z * k + y * s],
            [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
            [z * x * k - y * s, z * y * k + x * s, c + z * z * k],
        ]
    )


def rx(a: float) -> Mat:
    return rot(v(1, 0, 0), a)


def ry(a: float) -> Mat:
    return rot(v(0, 1, 0), a)


def rz(a: float) -> Mat:
    return rot(v(0, 0, 1), a)


def angle_between(a: Vec, b: Vec) -> float:
    """Unsigned angle in radians, robust near 0 and pi."""
    return math.atan2(norm(cross(a, b)), float(np.dot(a, b)))


def signed_angle(a: Vec, b: Vec, axis: Vec) -> float:
    """Angle from a to b about axis, after projecting both onto its plane."""
    n = unit(axis)
    pa = a - np.dot(a, n) * n
    pb = b - np.dot(b, n) * n
    return math.atan2(float(np.dot(cross(pa, pb), n)), float(np.dot(pa, pb)))


def arc(a: Vec, b: Vec) -> Mat:
    """Shortest rotation taking direction a onto direction b."""
    a, b = unit(a), unit(b)
    axis = cross(a, b)
    s = norm(axis)
    c = float(np.dot(a, b))
    if s < 1e-12:
        if c > 0:
            return np.eye(3)
        perp = cross(a, v(1, 0, 0))
        if norm(perp) < 1e-6:
            perp = cross(a, v(0, 1, 0))
        return rot(perp, math.pi)
    return rot(axis, math.atan2(s, c))


def rot_log(r: Mat) -> Vec:
    """Rotation vector (axis times angle) of a rotation matrix."""
    c = max(-1.0, min(1.0, (float(np.trace(r)) - 1.0) / 2.0))
    angle = math.acos(c)
    w = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]])
    if angle < 1e-9:
        return w / 2.0
    if math.pi - angle < 1e-6:
        # Near 180 degrees: take the axis from the symmetric part.
        m = (r + np.eye(3)) / 2.0
        i = int(np.argmax(np.diag(m)))
        axis = m[:, i] / math.sqrt(max(m[i, i], 1e-12))
        return unit(axis) * angle
    return w * (angle / (2.0 * math.sin(angle)))


def quat(r: Mat) -> list[float]:
    """Quaternion [x, y, z, w] of a rotation matrix (three.js order)."""
    t = float(np.trace(r))
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        w, x = 0.25 * s, (r[2, 1] - r[1, 2]) / s
        y, z = (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2
        w, x = (r[2, 1] - r[1, 2]) / s, 0.25 * s
        y, z = (r[0, 1] + r[1, 0]) / s, (r[0, 2] + r[2, 0]) / s
    elif r[1, 1] > r[2, 2]:
        s = math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2
        w, x = (r[0, 2] - r[2, 0]) / s, (r[0, 1] + r[1, 0]) / s
        y, z = 0.25 * s, (r[1, 2] + r[2, 1]) / s
    else:
        s = math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2
        w, x = (r[1, 0] - r[0, 1]) / s, (r[0, 2] + r[2, 0]) / s
        y, z = (r[1, 2] + r[2, 1]) / s, 0.25 * s
    return [float(x), float(y), float(z), float(w)]


def arm_to_body(a: Vec, side: str = "right") -> Vec:
    """Arm-frame vector (x fwd, y up, z lateral) to the body frame."""
    b = ARM_TO_BODY_RIGHT @ a
    if side == "left":
        b = b * np.array([-1.0, 1.0, 1.0])
    return b


def body_to_arm(b: Vec, side: str = "right") -> Vec:
    if side == "left":
        b = b * np.array([-1.0, 1.0, 1.0])
    return ARM_TO_BODY_RIGHT.T @ b


def rot_arm_to_body(r: Mat, side: str = "right") -> Mat:
    """Rotation expressed in the arm frame, re-expressed in the body frame."""
    s = ARM_TO_BODY_RIGHT
    if side == "left":
        s = np.diag([-1.0, 1.0, 1.0]) @ s
    out = s @ r @ s.T
    return out


def min_jerk(t: float) -> float:
    """Minimum-jerk blend 0..1 for t in 0..1 (Flash and Hogan 1985)."""
    t = max(0.0, min(1.0, t))
    return t * t * t * (10.0 - 15.0 * t + 6.0 * t * t)


def r3(a: Vec, nd: int = 4) -> list[float]:
    return [round(float(x), nd) for x in a]
