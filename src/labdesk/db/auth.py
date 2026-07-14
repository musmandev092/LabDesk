"""User authentication + brute-force lockout."""

from __future__ import annotations

import logging
import time

from ._config import _LOCK_MAX_SECONDS, _LOCK_SECONDS, _MAX_FAILS
from ._driver import sqlite3
from .crypto import _dummy_verify, _verify_password, hash_password

_log = logging.getLogger("labdesk")


def _remaining_seconds(locked_until) -> int:
    """Seconds left on a lockout. Self-healing: a lock is never written more than
    _LOCK_MAX_SECONDS ahead, so anything further out (clock skew, corrupted row)
    is treated as not-locked rather than trapping the account for days."""
    if not locked_until:
        return 0
    try:
        rem = float(locked_until) - time.time()
    except (TypeError, ValueError, OverflowError):
        return 0
    if rem <= 0 or rem > _LOCK_MAX_SECONDS:
        return 0
    return int(rem)


def lock_remaining(con: sqlite3.Connection, username: str) -> int:
    """Seconds remaining on a brute-force lockout for this username (0 = none)."""
    row = con.execute(
        "SELECT locked_until FROM users WHERE username=?", (username,)
    ).fetchone()
    if not row or "locked_until" not in row.keys():
        return 0
    return _remaining_seconds(row["locked_until"])


def clear_lockouts(con: sqlite3.Connection, username: str | None = None) -> int:
    """Drop the brute-force lockout + failure counter for one user, or all users
    if None. Returns the number of rows cleared. Used by the `--unlock` command."""
    if username:
        cur = con.execute(
            "UPDATE users SET failed_attempts=0, locked_until=NULL WHERE username=?",
            (username,),
        )
    else:
        cur = con.execute(
            "UPDATE users SET failed_attempts=0, locked_until=NULL "
            "WHERE failed_attempts<>0 OR locked_until IS NOT NULL"
        )
    con.commit()
    return cur.rowcount


def verify_user(con: sqlite3.Connection, username: str, password: str):
    row = con.execute(
        "SELECT * FROM users WHERE username=? AND active=1", (username,)
    ).fetchone()
    if not row:
        _dummy_verify(password)  # equalise timing so missing users aren't detectable
        return None
    cols = row.keys()
    if "locked_until" in cols:
        if _remaining_seconds(row["locked_until"]) > 0:
            return None  # still inside the lockout window
        if row["locked_until"]:
            # window elapsed: reset the counter too, else a mistype right after
            # waiting re-locks instantly and escalates again (endless lockout loop)
            try:
                con.execute(
                    "UPDATE users SET failed_attempts=0, locked_until=NULL WHERE id=?",
                    (row["id"],),
                )
                con.commit()
            except sqlite3.Error:
                pass
    legacy_salt = row["salt"] if "salt" in cols else ""
    if _verify_password(password, row["pass_hash"], legacy_salt):
        try:
            if not (row["pass_hash"] or "").startswith("scrypt$"):
                newh, _ = hash_password(password)
                con.execute(
                    "UPDATE users SET pass_hash=?, salt='' WHERE id=?",
                    (newh, row["id"]),
                )
            con.execute(
                "UPDATE users SET failed_attempts=0, locked_until=NULL WHERE id=?",
                (row["id"],),
            )
            con.commit()
        except (ValueError, sqlite3.Error):
            pass
        return row
    # atomic SQL increment (not read-modify-write) so concurrent instances can't
    # lose a count; lock with an exponentially growing window past _MAX_FAILS
    try:
        con.execute(
            "UPDATE users SET failed_attempts=COALESCE(failed_attempts,0)+1 WHERE id=?",
            (row["id"],),
        )
        fa = con.execute(
            "SELECT failed_attempts FROM users WHERE id=?", (row["id"],)
        ).fetchone()[0]
        if fa >= _MAX_FAILS:
            backoff = min(_LOCK_SECONDS * (2 ** (fa - _MAX_FAILS)), _LOCK_MAX_SECONDS)
            con.execute(
                "UPDATE users SET locked_until=? WHERE id=?",
                (str(time.time() + backoff), row["id"]),
            )
        con.commit()
    except sqlite3.Error as e:
        # attempt is still denied below; log since a lost counter bypasses throttling
        _log.warning(
            "brute-force lockout counter update failed for user id %s: %r", row["id"], e
        )
    return None
