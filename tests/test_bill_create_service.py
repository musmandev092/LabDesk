"""Wave 2 — bill creation at an authorized, audited service boundary.

Asserts the security guarantee directly: a role lacking ``create_receipt`` is
denied and NOTHING is written; an authorized role writes patient + receipt +
items + ledger + audit atomically. This is the service that ui/reception.py now
calls instead of running inline SQL in the Qt widget.
"""

from __future__ import annotations

import pytest

from factories import make_test
from labdesk.application import receipts as svc


def _draft(con, **over):
    test_id = make_test(con, name="CBC", charges=500.0)
    fields = {
        "existing_patient_id": None,
        "title": "Mr",
        "mr_no": "",
        "name": "John Doe",
        "age": 30,
        "age_desc": "years",
        "sex": "Male",
        "telephone": "03001234567",
        "address": "Somewhere",
        "wa_optout": 0,
        "doctor_id": None,
        "doctor_name": "Dr Who",
        "specimen": "Blood",
        "items": [{"test_id": test_id, "name": "CBC", "charge": 500.0}],
        "subtotal": 500.0,
        "discount_pct": 0.0,
        "net": 500.0,
        "paid": 500.0,
        "due": 0.0,
        "payment_method": "Cash",
        "discount_approved_by": None,
        "promo_pct": 0.0,
    }
    fields.update(over)
    return svc.BillDraft(**fields)


def _create(con, *, role="receptionist", user="rita", **over):
    return svc.create_receipt(
        con, _draft(con, **over), actor_username=user, actor_role=role
    )


def _count(con, sql, *args):
    return con.execute(sql, args).fetchone()[0]


def test_create_denied_for_low_role_writes_nothing(con):
    patients_before = _count(con, "SELECT COUNT(*) FROM patients")
    receipts_before = _count(con, "SELECT COUNT(*) FROM receipts")
    with pytest.raises(PermissionError):
        _create(con, role="unknown")
    assert _count(con, "SELECT COUNT(*) FROM patients") == patients_before
    assert _count(con, "SELECT COUNT(*) FROM receipts") == receipts_before


def test_create_new_patient_writes_all_tables(con):
    res = _create(con)
    assert res.new_patient is True
    assert res.lab_no  # a lab number was allocated

    rcpt = con.execute(
        "SELECT * FROM receipts WHERE id=?", (res.receipt_id,)
    ).fetchone()
    assert rcpt["lab_no"] == res.lab_no
    assert rcpt["net_amount"] == 500.0
    assert rcpt["status"] == "pending"
    assert rcpt["created_by"] == "rita"
    assert rcpt["patient_id"] is not None

    items = _count(
        con, "SELECT COUNT(*) FROM receipt_items WHERE receipt_id=?", res.receipt_id
    )
    assert items == 1
    ledger = _count(
        con,
        "SELECT COUNT(*) FROM ledger WHERE kind='income' AND ref_id=?",
        res.receipt_id,
    )
    assert ledger == 1
    audited = _count(
        con, "SELECT COUNT(*) FROM audit_log WHERE action='receipt_created'"
    )
    assert audited >= 1


def test_unpaid_bill_writes_no_ledger_row(con):
    res = _create(con, paid=0.0, due=500.0)
    ledger = _count(con, "SELECT COUNT(*) FROM ledger WHERE ref_id=?", res.receipt_id)
    assert ledger == 0


def test_returning_patient_reuses_row(con):
    first = _create(con)
    pid = con.execute(
        "SELECT patient_id FROM receipts WHERE id=?", (first.receipt_id,)
    ).fetchone()[0]
    patients_after_first = _count(con, "SELECT COUNT(*) FROM patients")

    second = _create(con, existing_patient_id=pid)
    assert second.new_patient is False
    assert _count(con, "SELECT COUNT(*) FROM patients") == patients_after_first
    assert (
        con.execute(
            "SELECT patient_id FROM receipts WHERE id=?", (second.receipt_id,)
        ).fetchone()[0]
        == pid
    )


def test_lab_numbers_are_sequential(con):
    a = _create(con)
    b = _create(con)
    assert a.lab_no != b.lab_no
    # both share the prefix + date head, differing in the trailing serial
    assert a.lab_no[:-3] == b.lab_no[:-3]
    assert int(b.lab_no[-3:]) == int(a.lab_no[-3:]) + 1


def test_discount_is_audited(con):
    _create(con, discount_pct=10.0, net=450.0, paid=450.0)
    audited = _count(
        con, "SELECT COUNT(*) FROM audit_log WHERE action='discount_approved'"
    )
    assert audited >= 1


def test_failure_rolls_back_whole_bill(con):
    # A bad (non-existent) doctor_id violates the receipt FK AFTER the patient insert —
    # the whole transaction must roll back: no patient, no receipt, nothing charged.
    patients_before = _count(con, "SELECT COUNT(*) FROM patients")
    with pytest.raises(Exception):  # noqa: B017 - sqlite IntegrityError subclass
        _create(con, doctor_id=999999)
    assert _count(con, "SELECT COUNT(*) FROM patients") == patients_before
    assert _count(con, "SELECT COUNT(*) FROM receipts WHERE created_by='rita'") == 0
