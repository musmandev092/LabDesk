"""Performance guards — query plans + throughput/latency budgets, stdlib only.

No new dependencies (no pytest-benchmark): timing is ``time.perf_counter`` and the
plan checks are SQLite ``EXPLAIN QUERY PLAN``. These are deliberately *gross*-regression
guards, not micro-benchmarks — budgets are set ~3-5x the locally-observed time so they
catch "we accidentally added a full table scan / O(n) write" without flaking on slow CI.

The plan tests seed a handful of rows first so the planner has real statistics and an
equality/range on an indexed column is genuinely cheaper than a scan. Observed numbers
are printed in every assertion message so a failure tells you the actual cost.
"""

from __future__ import annotations

import time

import pytest

from factories import make_test
from labdesk.application import receipts as svc
from labdesk.db import NOT_VOIDED, RECEIVED_TODAY

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _plan_detail(con, sql, *params):
    rows = con.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return " ".join(str(r["detail"]) for r in rows)


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


def _seed_receipts(con, n, *, with_children=False):
    """Insert ``n`` receipts straight via SQL (fast path; reads don't need the
    paisa dual-write). Returns a list of the new receipt ids. When ``with_children``
    is set, also mints one item + one result per receipt so the child-table plan
    tests have realistic data on the indexed FK columns."""
    test_id = make_test(con, name="Seed", charges=100.0)
    # mint real patient rows first so the receipts FK is satisfiable
    patient_ids = [
        con.execute(
            "INSERT INTO patients(name, telephone) VALUES (?,?)",
            (f"Seed Pt {i}", f"0311{i:07d}"),
        ).lastrowid
        for i in range(25)
    ]
    ids = []
    for i in range(n):
        rid = con.execute(
            "INSERT INTO receipts(lab_no, patient_id, patient_name, received_at, "
            "net_amount, paid, due, status) VALUES (?,?,?,?,?,?,?,?)",
            (
                f"SEED-{i:05d}",
                patient_ids[i % 25],
                f"Patient {i}",
                "2026-06-16 09:00:00",
                100.0,
                100.0,
                0.0,
                "reported",
            ),
        ).lastrowid
        ids.append(rid)
        if with_children:
            iid = con.execute(
                "INSERT INTO receipt_items(receipt_id, test_id, test_name, charge) "
                "VALUES (?,?,?,?)",
                (rid, test_id, "Seed", 100.0),
            ).lastrowid
            con.execute(
                "INSERT INTO results(receipt_item_id, seq, name, value) "
                "VALUES (?,?,?,?)",
                (iid, 0, "Hb", "13.5"),
            )
    con.commit()
    return ids


def _seed_patients(con, n):
    for i in range(n):
        con.execute(
            "INSERT INTO patients(name, telephone) VALUES (?,?)",
            (f"Patient {i:05d}", f"0300{i:07d}"),
        )
    con.commit()


def _seed_ledger(con, n):
    for i in range(n):
        con.execute(
            "INSERT INTO ledger(date, kind, ref_id, credit) VALUES (?,?,?,?)",
            ("2026-06-16", "income", i + 1, 100.0),
        )
    con.commit()


# --------------------------------------------------------------------------- #
# query-plan guards — hot lookups must use an index, never scan the big table
# --------------------------------------------------------------------------- #


def test_receipts_by_patient_id_uses_index(con):
    _seed_receipts(con, 50)
    detail = _plan_detail(con, "SELECT * FROM receipts WHERE patient_id=?", 1)
    assert "USING INDEX" in detail, f"plan was: {detail!r}"
    assert "SCAN receipts" not in detail, f"full scan on receipts: {detail!r}"


def test_receipts_received_today_range_uses_index(con):
    _seed_receipts(con, 50)
    detail = _plan_detail(con, f"SELECT * FROM receipts WHERE {RECEIVED_TODAY}")
    assert "USING INDEX" in detail, f"plan was: {detail!r}"
    assert "SCAN receipts" not in detail, f"full scan on receipts: {detail!r}"


def test_receipts_by_status_uses_index(con):
    _seed_receipts(con, 50)
    detail = _plan_detail(con, "SELECT * FROM receipts WHERE status=?", "reported")
    assert "USING INDEX" in detail, f"plan was: {detail!r}"
    assert "SCAN receipts" not in detail, f"full scan on receipts: {detail!r}"


def test_receipt_items_by_receipt_id_uses_index(con):
    _seed_receipts(con, 30, with_children=True)
    detail = _plan_detail(con, "SELECT * FROM receipt_items WHERE receipt_id=?", 5)
    assert "USING INDEX" in detail, f"plan was: {detail!r}"
    assert "SCAN receipt_items" not in detail, f"full scan: {detail!r}"


def test_results_by_receipt_item_id_uses_index(con):
    _seed_receipts(con, 30, with_children=True)
    detail = _plan_detail(con, "SELECT * FROM results WHERE receipt_item_id=?", 5)
    assert "USING INDEX" in detail, f"plan was: {detail!r}"
    assert "SCAN results" not in detail, f"full scan on results: {detail!r}"


def test_patient_lookup_by_telephone_uses_index(con):
    _seed_patients(con, 50)
    detail = _plan_detail(
        con, "SELECT * FROM patients WHERE telephone=?", "03000000001"
    )
    assert "USING INDEX" in detail, f"plan was: {detail!r}"
    assert "SCAN patients" not in detail, f"full scan on patients: {detail!r}"


def test_patient_search_by_name_prefix_uses_index(con):
    # A left-anchored prefix search compiles to an index range scan: name >= 'p'
    # AND name < 'p￿'. (Plain LIKE can't use the index because SQLite's default
    # LIKE is case-insensitive and ix_patients_name is a BINARY-collation index.)
    _seed_patients(con, 50)
    detail = _plan_detail(
        con,
        "SELECT * FROM patients WHERE name >= ? AND name < ?",
        "Patient 0",
        "Patient 0￿",
    )
    assert "USING INDEX" in detail, f"plan was: {detail!r}"
    assert "SCAN patients" not in detail, f"full scan on patients: {detail!r}"


def test_ledger_by_date_uses_index(con):
    _seed_ledger(con, 50)
    detail = _plan_detail(con, "SELECT * FROM ledger WHERE date=?", "2026-06-16")
    assert "USING INDEX" in detail, f"plan was: {detail!r}"
    assert "SCAN ledger" not in detail, f"full scan on ledger: {detail!r}"


# --------------------------------------------------------------------------- #
# write-throughput budget — bill creation through the real audited service
# --------------------------------------------------------------------------- #


def test_bill_creation_throughput(con):
    n = 50
    # warm up one bill (catalogue/test rows, prepared statements) outside the timer
    svc.create_receipt(
        con, _draft(con), actor_username="rita", actor_role="receptionist"
    )

    start = time.perf_counter()
    for _ in range(n):
        svc.create_receipt(
            con, _draft(con), actor_username="rita", actor_role="receptionist"
        )
    elapsed = time.perf_counter() - start
    per_bill_ms = (elapsed / n) * 1000.0

    # Generous CI budget: gross-regression guard, ~5x typical observed cost.
    assert per_bill_ms < 150.0, (
        f"bill creation too slow: {per_bill_ms:.1f} ms/bill "
        f"({elapsed:.2f}s total for {n} bills); budget 150 ms/bill"
    )
    assert elapsed < 8.0, f"total {elapsed:.2f}s for {n} bills exceeds 8s budget"


# --------------------------------------------------------------------------- #
# read-latency budgets — list / aggregate queries over a seeded table
# --------------------------------------------------------------------------- #


def test_sum_paid_over_date_range_budget(con):
    _seed_receipts(con, 200)
    sql = (
        f"SELECT COALESCE(SUM(paid),0) FROM receipts "
        f"WHERE {NOT_VOIDED} AND date(received_at) BETWEEN ? AND ?"
    )
    # warm the cache / planner once, then time a fresh execution
    con.execute(sql, ("2026-06-01", "2026-06-30")).fetchone()

    start = time.perf_counter()
    total = con.execute(sql, ("2026-06-01", "2026-06-30")).fetchone()[0]
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert total == pytest.approx(200 * 100.0)
    assert elapsed_ms < 200.0, (
        f"SUM(paid) over 200 receipts took {elapsed_ms:.1f} ms; budget 200 ms"
    )


def test_receipts_history_list_budget(con):
    _seed_receipts(con, 200)
    sql = (
        "SELECT id, lab_no, patient_name, received_at, net_amount, paid, due, status "
        "FROM receipts ORDER BY received_at DESC, id DESC LIMIT 100"
    )
    con.execute(sql).fetchall()  # warm

    start = time.perf_counter()
    rows = con.execute(sql).fetchall()
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert len(rows) == 100
    assert elapsed_ms < 200.0, (
        f"history list over 200 receipts took {elapsed_ms:.1f} ms; budget 200 ms"
    )
