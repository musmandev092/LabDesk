"""Characterization tests for db/audit.py — the tamper-evident SHA-256 hash chain.

Pins: a clean chain verifies; edits/deletions are detected at the right row; legacy
NULL-hash rows are tolerated only before chaining starts; rechain repairs after an
authorised purge; and log_audit NEVER raises (file fallback on DB failure). These are
the trust guarantees the whole audit feature exists to provide.
"""

from __future__ import annotations

import pytest

from labdesk.db.audit import (
    log_audit,
    rechain_audit,
    verify_audit_chain,
)


@pytest.fixture
def clean_audit(con):
    """A con with the audit_log emptied so tests control the whole chain."""
    con.execute("DELETE FROM audit_log")
    con.commit()
    return con


def _ids(con):
    return [r["id"] for r in con.execute("SELECT id FROM audit_log ORDER BY id")]


def test_clean_chain_verifies(clean_audit):
    con = clean_audit
    log_audit(con, "adam", "login", "ok")
    log_audit(con, "adam", "void_receipt", "id=1")
    log_audit(con, "rita", "logout", "")
    assert verify_audit_chain(con) == (True, None)
    assert len(_ids(con)) == 3


def test_edited_row_is_detected(clean_audit):
    con = clean_audit
    log_audit(con, "adam", "a", "1")
    log_audit(con, "adam", "b", "2")
    log_audit(con, "adam", "c", "3")
    middle = _ids(con)[1]
    con.execute("UPDATE audit_log SET detail='tampered' WHERE id=?", (middle,))
    con.commit()
    ok, bad = verify_audit_chain(con)
    assert ok is False
    assert bad == middle


def test_deleted_row_breaks_chain_at_next(clean_audit):
    con = clean_audit
    log_audit(con, "adam", "a", "1")
    log_audit(con, "adam", "b", "2")
    log_audit(con, "adam", "c", "3")
    _first, middle, last = _ids(con)
    con.execute("DELETE FROM audit_log WHERE id=?", (middle,))
    con.commit()
    ok, bad = verify_audit_chain(con)
    assert ok is False
    # The row that followed the deleted one no longer chains to its stored prev hash.
    assert bad == last


def test_leading_legacy_null_rows_are_tolerated(clean_audit):
    con = clean_audit
    # A legacy row predating the hash chain (hash IS NULL) followed by real entries.
    con.execute(
        "INSERT INTO audit_log(at, username, action, detail, hash) "
        "VALUES ('2020-01-01 00:00:00','old','legacy','x', NULL)"
    )
    con.commit()
    log_audit(con, "adam", "login", "ok")
    log_audit(con, "adam", "logout", "")
    assert verify_audit_chain(con) == (True, None)


def test_null_hash_after_chaining_is_tampering(clean_audit):
    con = clean_audit
    log_audit(con, "adam", "login", "ok")
    con.execute(
        "INSERT INTO audit_log(at, username, action, detail, hash) "
        "VALUES ('2026-01-01 00:00:00','x','y','z', NULL)"
    )
    con.commit()
    null_id = _ids(con)[-1]
    ok, bad = verify_audit_chain(con)
    assert ok is False
    assert bad == null_id


def test_rechain_repairs_after_purge(clean_audit):
    con = clean_audit
    log_audit(con, "adam", "a", "1")
    log_audit(con, "adam", "b", "2")
    log_audit(con, "adam", "c", "3")
    middle = _ids(con)[1]
    con.execute("DELETE FROM audit_log WHERE id=?", (middle,))
    con.commit()
    assert verify_audit_chain(con)[0] is False  # broken first
    rechain_audit(con)
    assert verify_audit_chain(con) == (True, None)  # repaired


def test_verify_on_missing_table_is_treated_as_ok(clean_audit):
    con = clean_audit
    con.execute("DROP TABLE audit_log")
    con.commit()
    # A SELECT error is swallowed → (True, None) rather than crashing the Logs page.
    assert verify_audit_chain(con) == (True, None)


def test_log_audit_coerces_non_string_args_without_raising(clean_audit):
    con = clean_audit
    # Passing an int username / dict action / object detail must not raise.
    log_audit(con, 123, {"a": 1}, detail=object())  # type: ignore[arg-type]
    assert len(_ids(con)) == 1
    assert verify_audit_chain(con) == (True, None)


def test_log_audit_never_raises_and_falls_back_to_file(data_dir):
    """On DB failure the entry is appended to an owner-only fallback log, not lost."""

    class _Boom:
        def execute(self, *a, **k):
            raise RuntimeError("connection is gone")

    log_audit(_Boom(), "adam", "void_receipt", "id=7")  # must not raise
    fallback = data_dir / "audit_fallback.log"
    assert fallback.exists()
    # the fallback can hold lab numbers / patient names → must be owner-only
    assert (fallback.stat().st_mode & 0o777) == 0o600
    body = fallback.read_text(encoding="utf-8")
    assert "void_receipt" in body and "adam" in body


def test_log_audit_default_detail_is_empty(clean_audit):
    """Calling log_audit without a detail stores '' (the default), not a placeholder."""
    con = clean_audit
    log_audit(con, "adam", "logout")  # no detail argument
    row = con.execute(
        "SELECT detail FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["detail"] == ""


# --- targeted mutation-kill tests (close real gaps mutmut found) --------------


def test_tampered_row_after_legacy_null_is_detected(clean_audit):
    """A legacy NULL-hash row must be SKIPPED (continue), not break the scan — else a
    tampered real row that follows it would go undetected."""
    con = clean_audit
    con.execute(
        "INSERT INTO audit_log(at, username, action, detail, hash) "
        "VALUES ('2020-01-01 00:00:00','old','legacy','x', NULL)"
    )
    con.commit()
    log_audit(con, "adam", "a", "1")
    log_audit(con, "adam", "b", "2")
    last = con.execute("SELECT MAX(id) FROM audit_log").fetchone()[0]
    con.execute("UPDATE audit_log SET detail='tampered' WHERE id=?", (last,))
    con.commit()
    ok, bad = verify_audit_chain(con)
    assert ok is False
    assert bad == last


def test_log_audit_persists_the_fields_verbatim(clean_audit):
    """The row must store the exact username/action/detail it was given."""
    con = clean_audit
    log_audit(con, "adam", "void_receipt", "lab-123 duplicate bill")
    row = con.execute(
        "SELECT username, action, detail FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["username"] == "adam"
    assert row["action"] == "void_receipt"
    assert row["detail"] == "lab-123 duplicate bill"


def test_log_audit_stores_empty_strings_not_placeholders(clean_audit):
    """An empty username/detail is stored as '' (not coerced to a placeholder)."""
    con = clean_audit
    log_audit(con, "", "login", "")
    row = con.execute(
        "SELECT username, detail FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["username"] == ""
    assert row["detail"] == ""


def test_verify_handles_empty_fields_consistently(clean_audit):
    """A row with empty username/action/detail must still verify — verify must use the
    SAME empty-string default log_audit used, not a different placeholder."""
    con = clean_audit
    log_audit(con, "", "", "")
    log_audit(con, "adam", "login", "ok")
    assert verify_audit_chain(con) == (True, None)


def test_rechain_handles_empty_fields(clean_audit):
    """Rechain must recompute with the same empty-string default so the result still
    verifies even when rows have empty fields."""
    con = clean_audit
    log_audit(con, "", "", "")
    log_audit(con, "adam", "b", "2")
    log_audit(con, "adam", "c", "3")
    mid = _ids(con)[1]
    con.execute("DELETE FROM audit_log WHERE id=?", (mid,))
    con.commit()
    rechain_audit(con)
    assert verify_audit_chain(con) == (True, None)
