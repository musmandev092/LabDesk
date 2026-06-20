"""Wave 5 — off-DB audit anchor (advisory tamper-evidence for log truncation).

The hash chain can't catch a key-holder who deletes recent rows and re-chains (the
shortened chain re-verifies). The off-DB anchor notices the shrink. It is advisory:
never raises, never hard-fails, and a legitimate restore reads 'behind'/'no_anchor'.
"""

from __future__ import annotations

import pytest

from labdesk.db import audit
from labdesk.db.audit import audit_anchor_status, log_audit, rechain_audit


@pytest.fixture
def clean_audit(con):
    con.execute("DELETE FROM audit_log")
    con.commit()
    return con


def test_anchor_created_owner_only_on_log(clean_audit, data_dir):
    log_audit(clean_audit, "adam", "login", "ok")
    anchor = data_dir / "audit_anchor"
    assert anchor.exists()
    assert (anchor.stat().st_mode & 0o777) == 0o600


def test_status_ok_after_appends(clean_audit):
    log_audit(clean_audit, "adam", "a", "1")
    log_audit(clean_audit, "adam", "b", "2")
    assert audit_anchor_status(clean_audit) == "ok"


def test_status_no_anchor_when_missing(clean_audit, data_dir):
    # No log written yet → no anchor file.
    assert not (data_dir / "audit_anchor").exists()
    assert audit_anchor_status(clean_audit) == "no_anchor"


def test_status_no_anchor_when_garbled(clean_audit, data_dir):
    log_audit(clean_audit, "adam", "a", "1")
    (data_dir / "audit_anchor").write_text("not-a-valid-anchor", encoding="utf-8")
    assert audit_anchor_status(clean_audit) == "no_anchor"


def test_status_behind_after_deleting_recent_rows(clean_audit):
    log_audit(clean_audit, "adam", "a", "1")
    log_audit(clean_audit, "adam", "b", "2")
    log_audit(clean_audit, "adam", "c", "3")  # anchor now records 3 rows
    last = clean_audit.execute("SELECT MAX(id) FROM audit_log").fetchone()[0]
    clean_audit.execute("DELETE FROM audit_log WHERE id=?", (last,))
    clean_audit.commit()
    # truncation: DB has fewer rows than the anchor recorded
    assert audit_anchor_status(clean_audit) == "behind"


def test_status_ahead_when_anchor_stale(clean_audit):
    log_audit(clean_audit, "adam", "a", "1")  # anchor records 1
    # insert a raw row WITHOUT log_audit so the anchor isn't advanced
    clean_audit.execute(
        "INSERT INTO audit_log(at, username, action, detail, hash) "
        "VALUES ('2026-01-01 00:00:00','x','y','z','deadbeef')"
    )
    clean_audit.commit()
    assert audit_anchor_status(clean_audit) == "ahead"


def test_rechain_refreshes_anchor(clean_audit):
    log_audit(clean_audit, "adam", "a", "1")
    log_audit(clean_audit, "adam", "b", "2")
    log_audit(clean_audit, "adam", "c", "3")
    last = clean_audit.execute("SELECT MAX(id) FROM audit_log").fetchone()[0]
    clean_audit.execute("DELETE FROM audit_log WHERE id=?", (last,))
    clean_audit.commit()
    assert audit_anchor_status(clean_audit) == "behind"
    rechain_audit(clean_audit)  # authorised purge refreshes the anchor
    assert audit_anchor_status(clean_audit) == "ok"


def test_log_audit_still_records_when_anchor_write_fails(clean_audit, monkeypatch):
    # Forcing the anchor write to fail must not break the audit write (never-raise).
    monkeypatch.setattr(
        audit, "_write_anchor", lambda con: (_ for _ in ()).throw(OSError("x"))
    )
    # _write_anchor is called inside log_audit's try; an OSError there would be caught
    # by the broad except and routed to the file fallback — but the row is already
    # committed before the anchor write, so it persists.
    log_audit(clean_audit, "adam", "login", "ok")
    assert clean_audit.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 1


# --- targeted mutation-kill tests (close real gaps mutmut found) --------------


def test_status_no_anchor_when_two_parts_but_count_not_numeric(clean_audit, data_dir):
    """A 2-field anchor whose count isn't a number is still rejected as no_anchor —
    the guard is `len != 2 OR not digit`, never letting a non-numeric count reach
    int() (which would raise)."""
    log_audit(clean_audit, "adam", "a", "1")
    (data_dir / "audit_anchor").write_text("abc\tdeadbeef", encoding="utf-8")
    assert audit_anchor_status(clean_audit) == "no_anchor"


def test_status_behind_on_in_place_edit_same_count(clean_audit):
    """Same row count but a different head = an in-place edit → 'behind' (not 'ok')."""
    log_audit(clean_audit, "adam", "a", "1")  # anchor records count=1, head=H1
    # tamper the row's hash in place: count stays 1, head changes, anchor not updated
    clean_audit.execute(
        "UPDATE audit_log SET hash='deadbeef' WHERE id=(SELECT MAX(id) FROM audit_log)"
    )
    clean_audit.commit()
    assert audit_anchor_status(clean_audit) == "behind"
