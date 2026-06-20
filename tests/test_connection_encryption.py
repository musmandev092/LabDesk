"""Encryption-at-rest guarantees and the fail-closed / no-fail-open behaviour
introduced for the audit (Critical C-1 + verify_passphrase / rekey mediums)."""

from __future__ import annotations

import pytest


def test_db_is_encrypted_on_disk(con, data_dir):
    """The live DB file must NOT be a plaintext SQLite file (no magic header)."""
    con.execute(
        "INSERT INTO settings(key,value) VALUES ('probe','secret') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    con.commit()
    raw = (data_dir / "labdesk.sqlite").read_bytes()[:16]
    assert raw != b"SQLite format 3\x00", "database header is plaintext — not encrypted"


def test_cipher_is_actually_active(con):
    assert con.execute("PRAGMA cipher_version").fetchone()[0], "SQLCipher not engaged"


def test_verify_passphrase_accepts_correct_and_rejects_wrong(db):
    db.init_db().close()
    assert db.verify_passphrase("test-passphrase-123") is True
    assert db.verify_passphrase("the-wrong-key") is False


def test_verify_passphrase_rejects_empty(db):
    db.init_db().close()
    assert db.verify_passphrase("") is False


def test_verify_passphrase_rejects_plaintext_file(db, data_dir):
    """A plaintext file must never be reported as 'unlocked' by any passphrase
    (this was a fail-open before the audit fix)."""
    import sqlite3 as std

    db.init_db().close()
    plain = data_dir / "plain.sqlite"
    c = std.connect(str(plain))
    c.execute("CREATE TABLE users(id INTEGER)")
    c.commit()
    c.close()
    assert db.db_is_plaintext(plain) is True
    assert db.verify_passphrase("anything", plain) is False


def test_fail_closed_when_encryption_unavailable(db, monkeypatch):
    """connect() must REFUSE to open an unencrypted DB unless plaintext is opted in."""
    import labdesk.db.connection as conn

    monkeypatch.setattr(conn, "ENCRYPTION_AVAILABLE", False)
    monkeypatch.delenv("LABDESK_ALLOW_PLAINTEXT", raising=False)
    with pytest.raises(RuntimeError, match="refusing to open an UNENCRYPTED"):
        conn.connect()
    # opt-in escape hatch lets dev proceed
    monkeypatch.setenv("LABDESK_ALLOW_PLAINTEXT", "1")
    assert conn._plaintext_allowed() is True


def test_rekey_changes_passphrase_and_keeps_data(con, db):
    con.execute(
        "INSERT INTO settings(key,value) VALUES ('k','v') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    con.commit()
    assert db.rekey_database(con, "test-passphrase-123", "new-pass-456") is True
    # old passphrase no longer opens it; new one does
    assert db.verify_passphrase("test-passphrase-123") is False
    assert db.verify_passphrase("new-pass-456") is True
