"""Regression tests for the audit (2026-06-30) bug-hunt fixes."""

from __future__ import annotations

from factories import make_item, make_receipt
from labdesk.report.verify import verification_code, verify


# --------------------------------------------------------------------------
# #2 income from the ledger (by event date), not the receipts.paid snapshot
# --------------------------------------------------------------------------
def test_income_between_uses_ledger_event_dates(db, con):
    con.executescript(
        "INSERT INTO ledger(kind,ref_id,detail,credit,date) "
        "VALUES('income',1,'bill',100,'2026-01-05');"
        "INSERT INTO ledger(kind,ref_id,detail,credit,date) "
        "VALUES('due_recovery',1,'due',40,'2026-06-10');"
        "INSERT INTO ledger(kind,detail,debit,date) VALUES('expense','rent',30,'2026-01-05');"
        "INSERT INTO ledger(kind,ref_id,detail,debit,date) VALUES('void',2,'void',20,'2026-01-05');"
    )
    con.commit()
    # Jan: 100 income − 20 void = 80 (expense excluded from income)
    assert db.income_between(con, "2026-01-01", "2026-01-31") == 80
    # the due collected in June counts in June, not back in January
    assert db.income_between(con, "2026-06-01", "2026-06-30") == 40


def test_income_by_method_joins_receipt_method(db, con):
    con.execute(
        "INSERT INTO receipts(id,lab_no,payment_method,status) VALUES(501,'L','Card','reported')"
    )
    con.execute(
        "INSERT INTO ledger(kind,ref_id,detail,credit,date) VALUES('income',501,'a',100,'2026-02-01')"
    )
    con.commit()
    rows = db.income_by_method(con, "2026-02-01", "2026-02-28")
    assert any(r["m"] == "Card" and r["total"] == 100 for r in rows)


# --------------------------------------------------------------------------
# #3 verification HMAC now covers the impression; legacy v1 codes still verify
# --------------------------------------------------------------------------
def test_verify_covers_impression_and_keeps_v1_valid(con):
    rid = make_receipt(con, status="reported")
    iid = make_item(con, rid, test_id=678, test_name="USG")
    con.execute("UPDATE receipt_items SET conclusion='Normal study.' WHERE id=?", (iid,))
    con.execute(
        "INSERT INTO results(receipt_item_id,parameter_id,seq,part_type,name,value) "
        "VALUES(?,NULL,0,'N','Result','x')",
        (iid,),
    )
    con.commit()
    code = verification_code(con, rid)  # v2
    assert verify(con, rid, code)
    # tampering with the impression must now break the code
    con.execute("UPDATE receipt_items SET conclusion='Abnormal!' WHERE id=?", (iid,))
    con.commit()
    assert not verify(con, rid, code)
    # a legacy v1 code (results-only) is still accepted (reports issued before v2)
    assert verify(con, rid, verification_code(con, rid, "v1"))


# --------------------------------------------------------------------------
# #4 catalog re-seed matches by legacy key → an id collision no longer drops
# shipped tests, and re-running is idempotent
# --------------------------------------------------------------------------
def test_catalog_resync_recovers_id_collision(db, con):
    from labdesk.db import connection as C

    t = con.execute("SELECT id, legacy_no FROM tests ORDER BY id LIMIT 1").fetchone()
    tid, legacy = t["id"], t["legacy_no"]
    # the shipped test is "missing" from the live DB and its id was reused by a custom
    con.execute("DELETE FROM test_parameters WHERE test_id=?", (tid,))
    con.execute("DELETE FROM tests WHERE id=?", (tid,))
    con.execute(
        "INSERT INTO tests(id,name,legacy_no) VALUES(?, 'My Custom Test', NULL)", (tid,)
    )
    con.execute("UPDATE settings SET value='1' WHERE key='catalog_version'")
    con.commit()

    C._sync_catalog_from_seed(con)
    # shipped test recovered (by legacy_no) AND the custom test survived
    assert con.execute(
        "SELECT COUNT(*) FROM tests WHERE legacy_no=?", (legacy,)
    ).fetchone()[0] == 1
    assert con.execute(
        "SELECT COUNT(*) FROM tests WHERE name='My Custom Test'"
    ).fetchone()[0] == 1

    # idempotent: a second sync adds no duplicates
    con.execute("UPDATE settings SET value='1' WHERE key='catalog_version'")
    con.commit()
    C._sync_catalog_from_seed(con)
    assert con.execute(
        "SELECT COUNT(*) FROM tests WHERE legacy_no=?", (legacy,)
    ).fetchone()[0] == 1


# --------------------------------------------------------------------------
# #11 a returning/auto-matched patient keeps its stored permanent MR
# --------------------------------------------------------------------------
def test_returning_patient_mr_not_overwritten(con):
    from labdesk.application.receipts import BillDraft, _upsert_patient

    con.execute("INSERT INTO patients(id,name,mr_no) VALUES(900,'Pat','26-000-11A')")
    con.commit()
    d = BillDraft(
        existing_patient_id=900,
        title="",
        mr_no="99-999-99Z",  # a different value typed for what looked like a new reg
        name="Pat",
        age=0,
        age_desc="Years",
        sex="Male",
        telephone="",
        address="",
        wa_optout=0,
        doctor_id=None,
        doctor_name="",
        specimen="",
        items=[],
        subtotal=0.0,
        discount_pct=0.0,
        net=0.0,
        paid=0.0,
        due=0.0,
        payment_method="Cash",
        discount_approved_by=None,
        promo_pct=0.0,
    )
    _, mr_no, new = _upsert_patient(con, d, "")
    assert new is False
    assert mr_no == "26-000-11A"  # stored permanent MR kept, typed one ignored
    stored = con.execute("SELECT mr_no FROM patients WHERE id=900").fetchone()[0]
    assert stored == "26-000-11A"
