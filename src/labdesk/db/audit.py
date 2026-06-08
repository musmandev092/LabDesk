"""Tamper-evident audit trail (rolling SHA-256 hash chain).

Each row carries a rolling hash of (prev_hash, at, user, action, detail), so any
later edit/deletion is detectable. Writes never raise — on DB failure they fall
back to an owner-only file so the gap stays visible.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import sqlite3

from .paths import data_dir


def _audit_fallback(username, action, detail, err) -> None:
    """If the audit DB write fails, append to a local file so the gap is visible."""
    try:
        p = data_dir() / "audit_fallback.log"
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(f"{username}\t{action}\t{detail}\t(audit-db-error: {err})\n")
        # this file can hold lab numbers / patient names — keep it owner-only
        with contextlib.suppress(OSError):
            os.chmod(p, 0o600)
    except OSError:
        pass


def log_audit(con: sqlite3.Connection, username: str, action: str, detail: str = "") -> None:
    """Append one tamper-evident entry to the audit trail (shown on the admin Logs
    page). Each row carries a rolling SHA-256 hash of (prev_hash, at, user, action,
    detail), so any later edit/deletion is detectable. Never raises — recording an
    action must never break the action itself; on DB failure it falls back to a file."""
    # str() coercion keeps the "never raises" contract even when a caller passes a
    # non-string (int/dict/object): slicing those directly would throw before the try.
    username = str(username or "")[:64]
    action = str(action or "")[:64]
    detail = str(detail or "")[:500]
    try:
        prev = con.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = (prev["hash"] or "") if (prev and "hash" in prev.keys()) else ""
        ts = con.execute("SELECT datetime('now','localtime')").fetchone()[0]
        chain = hashlib.sha256(
            "|".join([prev_hash, ts, username, action, detail]).encode("utf-8")
        ).hexdigest()
        con.execute(
            "INSERT INTO audit_log(at, username, action, detail, hash) VALUES (?,?,?,?,?)",
            (ts, username, action, detail, chain),
        )
        con.commit()
    except sqlite3.Error as e:
        _audit_fallback(username, action, detail, e)


def verify_audit_chain(con: sqlite3.Connection):
    """Recompute the rolling hash chain. Returns (ok, first_bad_id|None). A
    mismatch or a missing hash after chaining began means the log was altered."""
    prev = ""
    started = False
    try:
        rows = con.execute(
            "SELECT id, at, username, action, detail, hash FROM audit_log ORDER BY id"
        ).fetchall()
    except sqlite3.Error:
        return True, None
    for row in rows:
        if row["hash"] is None:
            if started:
                return False, row["id"]
            continue  # legacy rows that predate the hash chain
        started = True
        expect = hashlib.sha256(
            "|".join(
                [
                    prev,
                    row["at"] or "",
                    row["username"] or "",
                    row["action"] or "",
                    row["detail"] or "",
                ]
            ).encode("utf-8")
        ).hexdigest()
        if row["hash"] != expect:
            return False, row["id"]
        prev = row["hash"]
    return True, None


def rechain_audit(con: sqlite3.Connection) -> None:
    """Recompute the rolling hash chain over all current rows. Used after an
    authorised purge (Clear old logs) so verify_audit_chain stays valid instead of
    reporting tampering at the new first row."""
    rows = con.execute(
        "SELECT id, at, username, action, detail FROM audit_log ORDER BY id"
    ).fetchall()
    prev = ""
    for r in rows:
        h = hashlib.sha256(
            "|".join(
                [prev, r["at"] or "", r["username"] or "", r["action"] or "", r["detail"] or ""]
            ).encode("utf-8")
        ).hexdigest()
        con.execute("UPDATE audit_log SET hash=? WHERE id=?", (h, r["id"]))
        prev = h
    con.commit()
