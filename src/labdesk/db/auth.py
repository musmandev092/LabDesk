"""User authentication + brute-force lockout."""

from __future__ import annotations

import sqlite3
import time

from ._config import _LOCK_MAX_SECONDS, _LOCK_SECONDS, _MAX_FAILS
from .crypto import _dummy_verify, _verify_password, hash_password


def lock_remaining(con: sqlite3.Connection, username: str) -> int:
    """Seconds remaining on a brute-force lockout for this username (0 = none)."""
    row = con.execute("SELECT locked_until FROM users WHERE username=?", (username,)).fetchone()
    if not row or "locked_until" not in row.keys() or not row["locked_until"]:
        return 0
    try:
        return max(0, int(float(row["locked_until"]) - time.time()))
    except (TypeError, ValueError, OverflowError):
        # OverflowError: a non-finite (inf) timestamp from a corrupted/edited DB.
        return 0


def verify_user(con: sqlite3.Connection, username: str, password: str):
    row = con.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
    if not row:
        _dummy_verify(password)  # equalise timing so missing users aren't detectable
        return None
    cols = row.keys()
    # locked out from too many recent failures?
    if "locked_until" in cols and row["locked_until"]:
        try:
            if time.time() < float(row["locked_until"]):
                return None
        except (TypeError, ValueError):
            pass
    legacy_salt = row["salt"] if "salt" in cols else ""
    if _verify_password(password, row["pass_hash"], legacy_salt):
        try:
            # transparently upgrade legacy sha256 hashes to scrypt
            if not (row["pass_hash"] or "").startswith("scrypt$"):
                newh, _ = hash_password(password)
                con.execute("UPDATE users SET pass_hash=?, salt='' WHERE id=?", (newh, row["id"]))
            con.execute(
                "UPDATE users SET failed_attempts=0, locked_until=NULL WHERE id=?", (row["id"],)
            )
            con.commit()
        except (ValueError, sqlite3.Error):
            pass
        return row
    # wrong password → count the failure, then lock with an exponentially
    # growing window once past _MAX_FAILS (60s, 120s, 240s … capped).
    try:
        fa = (
            row["failed_attempts"] if "failed_attempts" in cols and row["failed_attempts"] else 0
        ) + 1
        lock = None
        if fa >= _MAX_FAILS:
            backoff = min(_LOCK_SECONDS * (2 ** (fa - _MAX_FAILS)), _LOCK_MAX_SECONDS)
            lock = str(time.time() + backoff)
        con.execute(
            "UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?", (fa, lock, row["id"])
        )
        con.commit()
    except sqlite3.Error:
        pass
    return None
