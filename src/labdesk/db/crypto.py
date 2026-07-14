"""Password hashing — scrypt (memory-hard KDF, stdlib). Stored as "scrypt$N$r$p$salt$hexhash"."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from ._config import _SCRYPT_MAXMEM, _SCRYPT_N, _SCRYPT_P, _SCRYPT_R


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM,
        dklen=32,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt}${dk.hex()}", ""


def _verify_password(password: str, stored: str, legacy_salt: str) -> bool:
    """Constant-time verification against a scrypt string or a legacy sha256 hash."""
    stored = stored or ""
    if stored.startswith("scrypt$"):
        try:
            _, n, r, p, salt, hexh = stored.split("$", 5)
            dk = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt.encode("utf-8"),
                n=int(n),
                r=int(r),
                p=int(p),
                maxmem=_SCRYPT_MAXMEM,
                dklen=len(hexh) // 2,
            )
            return hmac.compare_digest(dk.hex(), hexh)
        except (ValueError, IndexError):
            return False
    h = hashlib.sha256(((legacy_salt or "") + password).encode("utf-8")).hexdigest()
    return hmac.compare_digest(h, stored)


# built at import, not lazily, so the first unknown-username attempt isn't slower
_DUMMY_HASH, _ = hash_password("login-timing-equaliser")


def _dummy_verify(password: str) -> None:
    """Constant-cost hash on the user-miss path — defeats username enumeration via timing."""
    _verify_password(password, _DUMMY_HASH, "")
