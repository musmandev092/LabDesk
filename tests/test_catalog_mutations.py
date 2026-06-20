"""Catalog mutators (panels + test parameters): authorization AND audit are now
enforced inside the data layer, not the UI — a privileged write always leaves a
trail regardless of caller (audit-centralization for the mutation layer)."""

from __future__ import annotations

import pytest

from labdesk import db as dbpkg


def _audited(con, action):
    return con.execute(
        "SELECT COUNT(*) FROM audit_log WHERE action=?", (action,)
    ).fetchone()[0]


def _two_test_ids(con):
    return [r[0] for r in con.execute("SELECT id FROM tests WHERE active=1 LIMIT 2")]


def test_save_panel_denied_for_low_role(con):
    with pytest.raises(PermissionError):
        dbpkg.save_panel(
            con,
            "Fever Panel",
            _two_test_ids(con),
            actor_role="technician",
            username="t",
        )


def test_save_panel_creates_and_audits(con):
    pid = dbpkg.save_panel(
        con, "Fever Panel", _two_test_ids(con), actor_role="admin", username="adam"
    )
    assert pid
    assert _audited(con, "panel_created") == 1
    # updating the same panel audits as an update
    dbpkg.save_panel(
        con,
        "Fever Panel v2",
        _two_test_ids(con),
        pid,
        actor_role="admin",
        username="adam",
    )
    assert _audited(con, "panel_updated") == 1


def test_delete_panel_audits_with_name(con):
    pid = dbpkg.save_panel(
        con, "Throwaway", _two_test_ids(con), actor_role="admin", username="adam"
    )
    dbpkg.delete_panel(con, pid, actor_role="admin", username="adam")
    assert _audited(con, "panel_deleted") == 1
    detail = con.execute(
        "SELECT detail FROM audit_log WHERE action='panel_deleted' ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    assert "Throwaway" in detail


def test_save_test_parameters_audits(con):
    tid = _two_test_ids(con)[0]
    rows = [{"name": "Hemoglobin", "units": "g/dL", "part_type": "N"}]
    dbpkg.save_test_parameters(con, tid, rows, actor_role="admin", username="adam")
    assert _audited(con, "parameters_edited") == 1


def test_save_test_parameters_denied_for_low_role(con):
    tid = _two_test_ids(con)[0]
    with pytest.raises(PermissionError):
        dbpkg.save_test_parameters(
            con, tid, [], actor_role="receptionist", username="r"
        )
