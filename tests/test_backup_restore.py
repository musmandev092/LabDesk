"""Backup / restore round-trip, rollback preservation, and source validation
(audit High H-4 + DR safety)."""

from __future__ import annotations

from pathlib import Path


def test_backup_roundtrip(con, db, data_dir):
    con.execute(
        "INSERT INTO settings(key,value) VALUES ('marker','keep-me') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    con.commit()
    dest = data_dir / "mybackup.sqlite"
    assert db.backup_to(str(dest)) is True
    assert dest.exists()
    # the backup opens with the same key and carries the data
    assert db._looks_like_labdesk_db(dest) is True


def test_restore_validates_source(con, db, data_dir):
    """A garbage / non-LabDesk file must be refused as a restore source."""
    junk = data_dir / "junk.sqlite"
    junk.write_bytes(b"not a database")
    assert db.restore_db(str(junk)) is False


def test_restore_rejects_empty_users_db(con, db, data_dir):
    """An otherwise-valid-looking DB with no users is refused (forgery guard)."""
    db.backup_to(str(data_dir / "b.sqlite"))
    # build an encrypted DB that has the tables but an empty users table
    import labdesk.db.connection as conn

    empty = data_dir / "empty.sqlite"
    c = conn.sqlite3.connect(str(empty))
    conn._apply_key(c, "test-passphrase-123")
    c.executescript("CREATE TABLE users(id INTEGER); CREATE TABLE settings(key TEXT);")
    c.commit()
    c.close()
    assert db._looks_like_labdesk_db(empty) is False


def test_restore_preserves_prior_rollback(con, db, data_dir):
    """H-4: two successive restores must not clobber each other's safety copy."""
    good = data_dir / "good.sqlite"
    assert db.backup_to(str(good)) is True
    assert db.restore_db(str(good)) is True
    assert db.restore_db(str(good)) is True
    cur = db.db_path()
    rollbacks = list(Path(cur.parent).glob(f"{cur.name}.pre-restore-*"))
    assert len(rollbacks) >= 2, "each restore must keep its own timestamped rollback"


def test_restore_writes_audit_fallback(con, db, data_dir):
    good = data_dir / "good2.sqlite"
    db.backup_to(str(good))
    db.restore_db(str(good))
    fallback = data_dir / "audit_fallback.log"
    assert fallback.exists()
    assert "database_restored" in fallback.read_text(encoding="utf-8")
