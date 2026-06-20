"""Receipt money mutations: authorization, ledger balance, void idempotency, and
due payments (audit High H-1 + void double-reverse / receive_due mediums)."""

from __future__ import annotations

import pytest

from labdesk import db as dbpkg
from labdesk.application import receipts as svc


def _new_receipt(con, *, net=1000.0, paid=1000.0, due=0.0, voided=0):
    rid = con.execute(
        "INSERT INTO receipts(lab_no, net_amount, paid, due, status, voided) "
        "VALUES ('LAB-1', ?, ?, ?, 'pending', ?)",
        (net, paid, due, voided),
    ).lastrowid
    con.commit()
    return rid


def _ledger_count(con, kind):
    return con.execute("SELECT COUNT(*) FROM ledger WHERE kind=?", (kind,)).fetchone()[
        0
    ]


def test_void_denied_for_low_role(con):
    rid = _new_receipt(con)
    with pytest.raises(PermissionError):
        svc.void_receipt(con, rid, "mistake", "rita", actor_role="receptionist")
    assert (
        con.execute("SELECT voided FROM receipts WHERE id=?", (rid,)).fetchone()[0] == 0
    )


def test_void_reverses_ledger_for_admin(con):
    rid = _new_receipt(con, paid=1000.0)
    svc.void_receipt(con, rid, "duplicate bill", "adam", actor_role="admin")
    row = con.execute("SELECT voided, due FROM receipts WHERE id=?", (rid,)).fetchone()
    assert row["voided"] == 1 and row["due"] == 0
    assert _ledger_count(con, "void") == 1  # one reversing entry


def test_double_void_is_idempotent(con):
    """A second void must NOT post a second reversing ledger entry."""
    rid = _new_receipt(con, paid=1000.0)
    svc.void_receipt(con, rid, "x", "adam", actor_role="admin")
    svc.void_receipt(con, rid, "x again", "adam", actor_role="admin")
    assert _ledger_count(con, "void") == 1


def test_receive_due_requires_role(con):
    rid = _new_receipt(con, net=1000.0, paid=400.0, due=600.0)
    with pytest.raises(PermissionError):
        # 'unknown' role has level 0 < receive_payment (2)
        dbpkg.receive_due(con, rid, 100.0, "x", actor_role="unknown")


def test_receive_due_records_payment_and_balances(con):
    rid = _new_receipt(con, net=1000.0, paid=400.0, due=600.0)
    result = dbpkg.receive_due(con, rid, 250.0, "rita", actor_role="receptionist")
    assert result is not None
    _lab, new_paid, new_due = result
    assert new_paid == 650.0 and new_due == 350.0
    assert _ledger_count(con, "due_recovery") == 1


def test_receive_due_noop_when_nothing_owed(con):
    rid = _new_receipt(con, net=1000.0, paid=1000.0, due=0.0)
    assert dbpkg.receive_due(con, rid, 50.0, "rita", actor_role="receptionist") is None


def test_mark_delivered_requires_role(con):
    rid = _new_receipt(con)
    with pytest.raises(PermissionError):
        svc.mark_receipt_delivered(con, rid, "x", actor_role="unknown")
