"""Wave 2 — user account mutations behind require("manage_users") + audit.

Asserts the privileged user-management writes are authorized at the service
boundary (not just the settings widget), and audited.
"""

from __future__ import annotations

import pytest

from labdesk.application import users as svc


def _count(con, sql, *args):
    return con.execute(sql, args).fetchone()[0]


def _make(con, username="newstaff", role="receptionist", actor_role="admin"):
    svc.create_user(
        con,
        username=username,
        full_name="New Staff",
        password="secret123",
        role=role,
        actor_username="adam",
        actor_role=actor_role,
    )


def test_create_denied_for_non_admin(con):
    before = _count(con, "SELECT COUNT(*) FROM users")
    with pytest.raises(PermissionError):
        _make(con, actor_role="technician")
    assert _count(con, "SELECT COUNT(*) FROM users") == before


def test_create_user_writes_row_and_audits(con):
    _make(con, username="rita")
    row = con.execute("SELECT * FROM users WHERE username='rita'").fetchone()
    assert row is not None
    assert row["must_change_password"] == 1
    assert row["role"] == "receptionist"
    assert row["pass_hash"]
    assert (
        _count(con, "SELECT COUNT(*) FROM audit_log WHERE action='user_created'") >= 1
    )


def test_set_user_active_toggles_and_audits(con):
    _make(con, username="rita")
    uid = con.execute("SELECT id FROM users WHERE username='rita'").fetchone()[0]
    assert con.execute("SELECT active FROM users WHERE id=?", (uid,)).fetchone()[0] == 1
    now = svc.set_user_active(
        con, user_id=uid, actor_username="adam", actor_role="admin"
    )
    assert now is False
    assert con.execute("SELECT active FROM users WHERE id=?", (uid,)).fetchone()[0] == 0
    assert (
        _count(con, "SELECT COUNT(*) FROM audit_log WHERE action='user_disabled'") >= 1
    )


def test_set_user_active_denied_for_non_admin(con):
    _make(con, username="rita")
    uid = con.execute("SELECT id FROM users WHERE username='rita'").fetchone()[0]
    with pytest.raises(PermissionError):
        svc.set_user_active(
            con, user_id=uid, actor_username="x", actor_role="receptionist"
        )
    assert con.execute("SELECT active FROM users WHERE id=?", (uid,)).fetchone()[0] == 1


def test_reset_password_returns_temp_and_forces_change(con):
    _make(con, username="rita")
    uid = con.execute("SELECT id FROM users WHERE username='rita'").fetchone()[0]
    con.execute(
        "UPDATE users SET failed_attempts=3, locked_until='2030-01-01', "
        "must_change_password=0 WHERE id=?",
        (uid,),
    )
    con.commit()
    uname, temp = svc.reset_user_password(
        con, user_id=uid, actor_username="adam", actor_role="admin"
    )
    assert uname == "rita"
    assert temp.startswith("Temp-")
    row = con.execute(
        "SELECT must_change_password, failed_attempts, locked_until FROM users WHERE id=?",
        (uid,),
    ).fetchone()
    assert row["must_change_password"] == 1
    assert row["failed_attempts"] == 0
    assert row["locked_until"] is None
    assert (
        _count(con, "SELECT COUNT(*) FROM audit_log WHERE action='password_reset'") >= 1
    )


def test_reset_password_denied_for_non_admin(con):
    _make(con, username="rita")
    uid = con.execute("SELECT id FROM users WHERE username='rita'").fetchone()[0]
    with pytest.raises(PermissionError):
        svc.reset_user_password(
            con, user_id=uid, actor_username="x", actor_role="technician"
        )
