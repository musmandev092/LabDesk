"""Pure-Python Ed25519 (RFC 8032 reference implementation).

Vendored so LabDesk's license check needs NO third-party dependency and works
inside the compiled binary as-is. This is the public-domain reference code from RFC 8032
Appendix A (extended/projective coordinates — a verify is ~10-20 ms, fine for a
once-per-launch license check). Verified against the RFC 8032 test vector in the
module self-test (`python -m labdesk.licensing._ed25519`).

The app only ever calls `verify()`. `sign()` / `secret_to_public()` exist for the
off-line vendor tools (generate_keys.py / issue_license.py) which run on the
developer's machine with the PRIVATE key — never shipped logic that matters.
"""

from __future__ import annotations

import hashlib

# Base field Z_p
p = 2**255 - 19


def _sha512(s: bytes) -> bytes:
    return hashlib.sha512(s).digest()


def _modp_inv(x: int) -> int:
    return pow(x, p - 2, p)


# Curve constant
d = -121665 * _modp_inv(121666) % p

# Group order
q = 2**252 + 27742317777372353535851937790883648493


def _sha512_modq(s: bytes) -> int:
    return int.from_bytes(_sha512(s), "little") % q


# Points are (X, Y, Z, T) extended coords with x = X/Z, y = Y/Z, x*y = T/Z
def _point_add(P, Q):
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % p
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % p
    C = 2 * P[3] * Q[3] * d % p
    D = 2 * P[2] * Q[2] % p
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % p, G * H % p, F * G % p, E * H % p)


def _point_mul(s: int, P):
    Q = (0, 1, 1, 0)  # neutral element
    while s > 0:
        if s & 1:
            Q = _point_add(Q, P)
        P = _point_add(P, P)
        s >>= 1
    return Q


def _point_equal(P, Q) -> bool:
    if (P[0] * Q[2] - Q[0] * P[2]) % p != 0:
        return False
    return (P[1] * Q[2] - Q[1] * P[2]) % p == 0


# Point compression / decompression
_modp_sqrt_m1 = pow(2, (p - 1) // 4, p)


def _recover_x(y: int, sign: int):
    if y >= p:
        return None
    x2 = (y * y - 1) * _modp_inv(d * y * y + 1) % p
    if x2 == 0:
        if sign:
            return None
        return 0
    x = pow(x2, (p + 3) // 8, p)
    if (x * x - x2) % p != 0:
        x = x * _modp_sqrt_m1 % p
    if (x * x - x2) % p != 0:
        return None
    if (x & 1) != sign:
        x = p - x
    return x


# Base point
_g_y = 4 * _modp_inv(5) % p
_g_x = _recover_x(_g_y, 0)
G = (_g_x, _g_y, 1, _g_x * _g_y % p)


def _point_compress(P) -> bytes:
    zinv = _modp_inv(P[2])
    x = P[0] * zinv % p
    y = P[1] * zinv % p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _point_decompress(s: bytes):
    if len(s) != 32:
        raise ValueError("Invalid input length for decompression")
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % p)


def _secret_expand(secret: bytes):
    if len(secret) != 32:
        raise ValueError("Bad size of private key")
    h = _sha512(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return (a, h[32:])


def secret_to_public(secret: bytes) -> bytes:
    """Derive the 32-byte public key from a 32-byte secret seed."""
    (a, _) = _secret_expand(secret)
    return _point_compress(_point_mul(a, G))


def sign(secret: bytes, msg: bytes) -> bytes:
    """Sign `msg` with a 32-byte secret seed → 64-byte signature."""
    a, prefix = _secret_expand(secret)
    A = _point_compress(_point_mul(a, G))
    r = _sha512_modq(prefix + msg)
    R = _point_mul(r, G)
    Rs = _point_compress(R)
    h = _sha512_modq(Rs + A + msg)
    s = (r + h * a) % q
    return Rs + int.to_bytes(s, 32, "little")


def verify(public: bytes, msg: bytes, signature: bytes) -> bool:
    """True iff `signature` is a valid Ed25519 signature of `msg` under `public`.
    Returns False (never raises) on any malformed input."""
    try:
        if len(public) != 32 or len(signature) != 64:
            return False
        A = _point_decompress(public)
        if not A:
            return False
        Rs = signature[:32]
        R = _point_decompress(Rs)
        if not R:
            return False
        s = int.from_bytes(signature[32:], "little")
        if s >= q:
            return False
        h = _sha512_modq(Rs + public + msg)
        sB = _point_mul(s, G)
        hA = _point_mul(h, A)
        return _point_equal(sB, _point_add(R, hA))
    except Exception:
        return False


def _selftest() -> None:
    # RFC 8032, section 7.1, test vector 2 (TEST 2).
    sk = bytes.fromhex(
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"
    )
    pk = bytes.fromhex(
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c"
    )
    msg = bytes.fromhex("72")
    sig = bytes.fromhex(
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
        "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
    )
    assert secret_to_public(sk) == pk, "pubkey derivation mismatch"
    assert sign(sk, msg) == sig, "signature mismatch vs RFC 8032 vector"
    assert verify(pk, msg, sig), "verify failed on valid signature"
    assert not verify(pk, b"\x73", sig), "verify accepted a wrong message"
    bad = bytearray(sig)
    bad[0] ^= 0x01
    assert not verify(pk, msg, bytes(bad)), "verify accepted a tampered signature"
    print("ed25519 self-test OK (RFC 8032 vector + negative cases)")


if __name__ == "__main__":
    _selftest()
