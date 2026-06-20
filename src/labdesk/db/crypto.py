"""Password hashing — scrypt (memory-hard KDF, stdlib).

The stored string is self-describing: "scrypt$N$r$p$salt$hexhash". Legacy
sha256 rows are still verified and transparently upgraded on the next
successful login.
"""

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


_DUMMY_HASH = ""  # lazily-built scrypt string used only to equalise login timing


def _dummy_verify(password: str) -> None:
    """Run one scrypt hash on the user-miss path so an unknown/inactive username
    costs about the same as a real one — defeats username-enumeration via timing."""
    global _DUMMY_HASH
    if not _DUMMY_HASH:
        _DUMMY_HASH, _ = hash_password("login-timing-equaliser")
    _verify_password(password, _DUMMY_HASH, "")
