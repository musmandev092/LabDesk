"""User authentication + brute-force lockout."""

from __future__ import annotations

import logging
import time

from ._config import _LOCK_MAX_SECONDS, _LOCK_SECONDS, _MAX_FAILS
from ._driver import sqlite3
from .crypto import _dummy_verify, _verify_password, hash_password

_log = logging.getLogger("labdesk")


def _remaining_seconds(locked_until) -> int:
    """Seconds left on a lockout, self-healing against bad data and clock skew.

    A lock written by this module is never more than _LOCK_MAX_SECONDS in the
    future. A value beyond that can only come from the system clock being
    wrong/ahead at the moment the lock was written (dead RTC battery, no NTP — a
    common state on lab PCs) or a corrupted/edited row. Honouring it would trap
    the account for days, refusing even the correct password (the countdown never
    reaches zero). Treat any past-due OR implausibly-far value as "not locked" so
    the next correct password gets through and clears it.
    """
    if not locked_until:
        return 0
    try:
        rem = float(locked_until) - time.time()
    except (TypeError, ValueError, OverflowError):
        # OverflowError: a non-finite (inf) timestamp from a corrupted/edited DB.
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
    """Recovery: drop the brute-force lockout (and failure counter) for one user,
    or every user when *username* is None. Does NOT touch passwords. Returns the
    number of rows cleared. Used by the `--unlock` maintenance command so a locked
    admin can be let back in without waiting out the window."""
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
    # locked out from too many recent failures? (self-healing: a past-due or
    # implausibly-far locked_until counts as not locked — see _remaining_seconds.)
    if "locked_until" in cols:
        if _remaining_seconds(row["locked_until"]) > 0:
            return None  # still inside the lockout window
        if row["locked_until"]:
            # The window has ELAPSED → clear it AND reset the failure counter, so the
            # user gets a fresh set of attempts. Without this reset the counter stays
            # at/above the threshold, so a single mistype right after waiting re-locks
            # instantly and each repeat escalates the window toward an hour — the
            # "endless lockout loop". Safe: user login already sits behind the
            # database-unlock password, so this isn't the primary brute-force barrier.
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
            # transparently upgrade legacy sha256 hashes to scrypt
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
    # wrong password → count the failure, then lock with an exponentially
    # growing window once past _MAX_FAILS (60s, 120s, 240s … capped). Increment
    # ATOMICALLY in SQL (not read-modify-write) so two concurrent instances — which
    # the app explicitly supports via a shared DB — can't lose an increment.
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
        # The wrong-password attempt is still DENIED (we return None below). But if the
        # failure COUNTER can't be persisted, lockout throttling is effectively
        # bypassed — so make that visible rather than swallowing it silently.
        _log.warning(
            "brute-force lockout counter update failed for user id %s: %r", row["id"], e
        )
    return None
