"""Ed25519 signature check (RFC 8032), standard library only.

Forge checks its licence file and (later) its update feed with this module,
so a bundle needs no compiled crypto package. It only verifies: signing
happens on the owner's laptop with the `cryptography` package
(tools/forge_licence_sign.py), because big-integer maths in Python is not
constant-time and must never touch a private key.

Strict decoding, as RFC 8032 section 5.1.7 asks:
    - the public key and R must be canonical point encodings: a y of p or
      more is refused, and so is x = 0 with the sign bit set;
    - S must be less than L (the group order), so a signature cannot be
      changed into a second valid one by adding L;
    - the check is the cofactored equation [8][S]B = [8]R + [8][k]A.

Checked against the RFC's section 7.1 test vectors and a sweep of
signatures made by `cryptography` (tests/test_licence.py). One check takes
a few milliseconds.
"""

from __future__ import annotations

import hashlib

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)

Point = tuple[int, int, int, int]  # extended coordinates (X, Y, Z, T)
IDENTITY: Point = (0, 1, 1, 0)


def _add(a: Point, b: Point) -> Point:
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    e1 = (y1 - x1) * (y2 - x2) % P
    e2 = (y1 + x1) * (y2 + x2) % P
    c = 2 * t1 * t2 * D % P
    d = 2 * z1 * z2 % P
    e, f, g, h = e2 - e1, d - c, d + c, e2 + e1
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(scalar: int, point: Point) -> Point:
    out = IDENTITY
    while scalar:
        if scalar & 1:
            out = _add(out, point)
        point = _add(point, point)
        scalar >>= 1
    return out


def _same(a: Point, b: Point) -> bool:
    x1, y1, z1, _ = a
    x2, y2, z2, _ = b
    return (x1 * z2 - x2 * z1) % P == 0 and (y1 * z2 - y2 * z1) % P == 0


def _recover_x(y: int, sign: int) -> int | None:
    """The x for this y and sign bit, or None when there is none or the
    encoding is not canonical."""
    if y >= P:
        return None
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


def decode_point(data: bytes) -> Point | None:
    """A 32-byte point encoding, or None when it is not a canonical point."""
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % P)


_GY = 4 * pow(5, P - 2, P) % P
_GX = _recover_x(_GY, 0)
assert _GX is not None
BASE: Point = (_GX, _GY, 1, _GX * _GY % P)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """True when signature is a valid Ed25519 signature of message under
    public_key (32 bytes); False for anything else, never an exception."""
    if not isinstance(public_key, bytes) or not isinstance(signature, bytes):
        return False
    if len(public_key) != 32 or len(signature) != 64:
        return False
    a = decode_point(public_key)
    r = decode_point(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= L:
        return False
    k = (
        int.from_bytes(
            hashlib.sha512(signature[:32] + public_key + message).digest(), "little"
        )
        % L
    )
    left = _mul(8, _mul(s, BASE))
    right = _mul(8, _add(r, _mul(k, a)))
    return _same(left, right)
