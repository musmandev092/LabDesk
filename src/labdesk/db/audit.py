"""Tamper-evident audit trail (rolling SHA-256 hash chain). Writes never raise."""

from __future__ import annotations

import contextlib
import hashlib
import os
from pathlib import Path

from ._driver import sqlite3
from .paths import data_dir

_ANCHOR_NAME = "audit_anchor"


def _audit_fallback(username: str, action: str, detail: str, err: object) -> None:
    """If the audit DB write fails, append to a local owner-only file."""
    try:
        p = data_dir() / "audit_fallback.log"
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(f"{username}\t{action}\t{detail}\t(audit-db-error: {err})\n")
        with contextlib.suppress(OSError):
            os.chmod(p, 0o600)
    except OSError:
        pass


def log_audit(
    con: sqlite3.Connection, username: str, action: str, detail: str = ""
) -> None:
    """Append one tamper-evident, rolling-hash-chained entry to the audit trail.
    Never raises — falls back to a file on DB failure."""
    # str() coercion: a non-string caller arg would throw on slicing before the try
    username = str(username or "")[:64]
    action = str(action or "")[:64]
    detail = str(detail or "")[:500]
    try:
        prev = con.execute(
            "SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
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
        _write_anchor(con)
    except Exception as e:
        # catch everything, not just sqlite3.Error: a stale connection (e.g. after a
        # restore swapped the DB file underneath it) can surface non-sqlite errors
        _audit_fallback(username, action, detail, e)


def verify_audit_chain(con: sqlite3.Connection) -> tuple[bool, int | None]:
    """Recompute the rolling hash chain. Returns (ok, first_bad_id|None)."""
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
    """Recompute the hash chain over all rows (after an authorised purge)."""
    rows = con.execute(
        "SELECT id, at, username, action, detail FROM audit_log ORDER BY id"
    ).fetchall()
    prev = ""
    for r in rows:
        h = hashlib.sha256(
            "|".join(
                [
                    prev,
                    r["at"] or "",
                    r["username"] or "",
                    r["action"] or "",
                    r["detail"] or "",
                ]
            ).encode("utf-8")
        ).hexdigest()
        con.execute("UPDATE audit_log SET hash=? WHERE id=?", (h, r["id"]))
        prev = h
    con.commit()
    _write_anchor(con)


# Off-DB tamper anchor (advisory only, never raises/blocks): the hash chain alone
# can't detect a key-holder who deletes recent rows and re-chains, so the chain
# head + row count is mirrored to an owner-only file outside the DB to notice a
# shrink. A legitimate backup-restore just reads "behind"/"no_anchor".
def _anchor_path() -> Path:
    return data_dir() / _ANCHOR_NAME


def _chain_head(con: sqlite3.Connection) -> tuple[str, int]:
    """(head_hash, row_count) for the current audit_log."""
    n = con.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    head_row = con.execute(
        "SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    head = (head_row["hash"] or "") if head_row else ""
    return head, int(n)


def _write_anchor(con: sqlite3.Connection) -> None:
    """Persist the chain head + row count to an owner-only file (best-effort)."""
    with contextlib.suppress(Exception):
        head, n = _chain_head(con)
        fd = os.open(str(_anchor_path()), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"{n}\t{head}")


def audit_anchor_status(con: sqlite3.Connection) -> str:
    """Compare the live audit_log against the off-DB anchor: "ok" | "behind"
    (fewer rows or same count/different head) | "ahead" (anchor stale) | "no_anchor"."""
    try:
        raw = _anchor_path().read_text(encoding="utf-8").strip()
    except OSError:
        return "no_anchor"
    parts = raw.split("\t")
    if len(parts) != 2 or not parts[0].isdigit():
        return "no_anchor"
    anchor_n, anchor_head = int(parts[0]), parts[1]
    try:
        head, n = _chain_head(con)
    except sqlite3.Error:
        return "ok"  # advisory — never alarm on a transient DB read error
    if n < anchor_n:
        return "behind"
    if n > anchor_n:
        return "ahead"
    return "ok" if head == anchor_head else "behind"
