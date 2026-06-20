"""Wave 4b — integer-paisa money columns stay exactly in sync with the REAL columns.

The cutover is additive: every money write dual-writes a *_paisa twin, and a backfill
fills paisa from REAL on connect. The invariant everywhere: paisa == round(real*100).
"""

from __future__ import annotations

from factories import make_test
from labdesk import db as dbpkg
from labdesk.application import receipts as svc
from labdesk.db.connection import _backfill_paisa


def _create(con, **over):
    test_id = make_test(con, name="CBC", charges=500.0)
    fields = {
        "existing_patient_id": None,
        "title": "Mr",
        "mr_no": "",
        "name": "J",
        "age": 30,
        "age_desc": "years",
        "sex": "Male",
        "telephone": "0300",
        "address": "x",
        "wa_optout": 0,
        "doctor_id": None,
        "doctor_name": "Dr",
        "specimen": "Blood",
        "items": [{"test_id": test_id, "name": "CBC", "charge": 500.0}],
        "subtotal": 500.0,
        "discount_pct": 10.0,
        "net": 450.0,
        "paid": 450.0,
        "due": 0.0,
        "payment_method": "Cash",
        "discount_approved_by": None,
        "promo_pct": 0.0,
    }
    fields.update(over)
    return svc.create_receipt(
        con, svc.BillDraft(**fields), actor_username="rita", actor_role="receptionist"
    )


def _assert_twins(con, table, pairs, where, *args):
    cols = ", ".join(f"{r} AS {r}, {p} AS {p}" for r, p in pairs)
    row = con.execute(f"SELECT {cols} FROM {table} WHERE {where}", args).fetchone()
    assert row is not None
    for real_col, paisa_col in pairs:
        assert row[paisa_col] == round((row[real_col] or 0) * 100), (
            f"{table}.{paisa_col}"
        )


def test_create_dual_writes_exact_paisa(con):
    res = _create(con)
    rid = res.receipt_id
    rcpt = con.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()
    assert rcpt["subtotal_paisa"] == 50000
    assert rcpt["net_amount_paisa"] == 45000
    assert rcpt["paid_paisa"] == 45000
    assert rcpt["due_paisa"] == 0
    assert rcpt["less_paisa"] == 0
    item = con.execute(
        "SELECT charge_paisa FROM receipt_items WHERE receipt_id=?", (rid,)
    ).fetchone()
    assert item["charge_paisa"] == 50000
    led = con.execute(
        "SELECT credit_paisa FROM ledger WHERE kind='income' AND ref_id=?", (rid,)
    ).fetchone()
    assert led["credit_paisa"] == 45000


def test_invariant_holds_for_created_bill(con):
    rid = _create(con).receipt_id
    _assert_twins(
        con,
        "receipts",
        [
            ("subtotal", "subtotal_paisa"),
            ("less", "less_paisa"),
            ("net_amount", "net_amount_paisa"),
            ("paid", "paid_paisa"),
            ("due", "due_paisa"),
        ],
        "id=?",
        rid,
    )
    _assert_twins(
        con, "receipt_items", [("charge", "charge_paisa")], "receipt_id=?", rid
    )
    _assert_twins(
        con, "ledger", [("credit", "credit_paisa")], "ref_id=? AND kind='income'", rid
    )


def test_backfill_fills_paisa_from_real_only(con):
    # A row inserted with only REAL money (paisa NULL) gets backfilled exactly.
    rid = con.execute(
        "INSERT INTO receipts(lab_no, subtotal, less, net_amount, paid, due, status) "
        "VALUES ('LAB-BF', 123.45, 0, 123.45, 100.00, 23.45, 'pending')",
        (),
    ).lastrowid
    con.commit()
    assert (
        con.execute(
            "SELECT net_amount_paisa FROM receipts WHERE id=?", (rid,)
        ).fetchone()[0]
        is None
    )
    _backfill_paisa(con)
    row = con.execute(
        "SELECT net_amount_paisa, paid_paisa, due_paisa FROM receipts WHERE id=?",
        (rid,),
    ).fetchone()
    assert row["net_amount_paisa"] == 12345
    assert row["paid_paisa"] == 10000
    assert row["due_paisa"] == 2345


def test_backfill_is_idempotent_and_only_fills_null(con):
    rid = _create(con).receipt_id
    # Corrupt one paisa value to a non-NULL wrong number; backfill must NOT overwrite it
    # (it only fills NULLs — dual-writes are the source of truth for live rows).
    con.execute("UPDATE receipts SET due_paisa=999 WHERE id=?", (rid,))
    con.commit()
    _backfill_paisa(con)
    assert (
        con.execute("SELECT due_paisa FROM receipts WHERE id=?", (rid,)).fetchone()[0]
        == 999
    )
    # but a genuinely-NULL one gets filled
    con.execute("UPDATE receipts SET paid_paisa=NULL WHERE id=?", (rid,))
    con.commit()
    _backfill_paisa(con)
    assert (
        con.execute("SELECT paid_paisa FROM receipts WHERE id=?", (rid,)).fetchone()[0]
        == 45000
    )


def test_void_zeroes_due_paisa_and_writes_ledger_twin(con):
    rid = _create(con).receipt_id
    svc.void_receipt(con, rid, "dup", "adam", actor_role="admin")
    assert (
        con.execute("SELECT due_paisa FROM receipts WHERE id=?", (rid,)).fetchone()[0]
        == 0
    )
    _assert_twins(
        con, "ledger", [("debit", "debit_paisa")], "ref_id=? AND kind='void'", rid
    )


def test_receive_due_dual_writes_paisa(con):
    rid = _create(con, paid=200.0, due=250.0).receipt_id  # net 450, paid 200, due 250
    dbpkg.receive_due(con, rid, 100.0, "rita", actor_role="receptionist")
    _assert_twins(
        con, "receipts", [("paid", "paid_paisa"), ("due", "due_paisa")], "id=?", rid
    )
    _assert_twins(
        con,
        "ledger",
        [("credit", "credit_paisa")],
        "ref_id=? AND kind='due_recovery'",
        rid,
    )


def test_global_invariant_every_money_row_has_consistent_paisa(con):
    """Exercise several writers, then scan EVERY money column in EVERY table: any row
    with a REAL value must have paisa == round(real*100) and never NULL. This catches
    any writer (now or future) that forgets to dual-write the paisa twin."""
    from labdesk.db._config import _PAISA_COLUMNS

    a = _create(con)  # paid bill
    b = _create(con, paid=100.0, due=400.0)  # partial
    dbpkg.receive_due(con, b.receipt_id, 50.0, "rita", actor_role="receptionist")
    svc.void_receipt(con, a.receipt_id, "dup", "adam", actor_role="admin")
    con.execute(
        "INSERT INTO expenses(date,head,amount,amount_paisa) "
        "VALUES ('2026-01-01','reagents',12.34,CAST(ROUND(12.34*100) AS INTEGER))"
    )
    con.commit()

    # A non-zero REAL value must have a matching paisa twin. (A zero REAL — e.g. the
    # unused credit/debit side of a one-directional ledger row — may leave paisa NULL;
    # NULL ≡ 0 for aggregation and the on-open backfill fills it to 0 anyway.)
    for table, pairs in _PAISA_COLUMNS.items():
        for real_col, paisa_col in pairs:
            bad = con.execute(
                f'SELECT COUNT(*) FROM "{table}" '
                f"WHERE {real_col} IS NOT NULL AND {real_col} != 0 "
                f"AND ({paisa_col} IS NULL "
                f"OR {paisa_col} != CAST(ROUND({real_col} * 100) AS INTEGER))"
            ).fetchone()[0]
            assert bad == 0, (
                f"{table}.{paisa_col}: {bad} rows out of sync with {real_col}"
            )
