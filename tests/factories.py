"""Lightweight data factories for building a patient/receipt/result/culture graph.

Plain functions over a live encrypted ``con`` (no factory_boy dependency) — each
returns the new row id so tests can compose a graph declaratively and assert on it.
Foreign keys are enforced (PRAGMA foreign_keys=ON), so ``make_item`` mints a real
``tests`` row and children always reference a real parent.
"""

from __future__ import annotations


def make_test(con, *, name="CBC", charges=500.0, category="Routine"):
    """Insert a catalogue test and return its id."""
    rid = con.execute(
        "INSERT INTO tests(name, charges, category) VALUES (?,?,?)",
        (name, charges, category),
    ).lastrowid
    con.commit()
    return rid


def make_receipt(
    con,
    *,
    lab_no="LAB-1",
    patient_name="John Doe",
    reported_at="2026-01-02 10:00:00",
    net_amount=500.0,
    paid=500.0,
    due=0.0,
    status="reported",
):
    """Insert a receipt header and return its id."""
    rid = con.execute(
        "INSERT INTO receipts(lab_no, patient_name, reported_at, net_amount, "
        "paid, due, status) VALUES (?,?,?,?,?,?,?)",
        (lab_no, patient_name, reported_at, net_amount, paid, due, status),
    ).lastrowid
    con.commit()
    return rid


def make_item(con, receipt_id, *, test_id=None, test_name="CBC", charge=500.0):
    """Insert a receipt line item (minting a catalogue test if none given)."""
    if test_id is None:
        test_id = make_test(con, name=test_name, charges=charge)
    iid = con.execute(
        "INSERT INTO receipt_items(receipt_id, test_id, test_name, charge) "
        "VALUES (?,?,?,?)",
        (receipt_id, test_id, test_name, charge),
    ).lastrowid
    con.commit()
    return iid


def make_result(
    con,
    item_id,
    *,
    name="Haemoglobin",
    value="13.5",
    seq=0,
    hidden=0,
    parameter_id=None,
):
    """Insert a result line for a receipt item."""
    rid = con.execute(
        "INSERT INTO results(receipt_item_id, parameter_id, seq, name, value, hidden) "
        "VALUES (?,?,?,?,?,?)",
        (item_id, parameter_id, seq, name, value, hidden),
    ).lastrowid
    con.commit()
    return rid


def make_culture(
    con,
    item_id,
    *,
    specimen="Urine",
    growth="No growth",
    organism="",
    colony_count="",
    gram_stain="",
    zn_stain="",
    remarks="",
):
    """Insert a culture record for a receipt item."""
    cid = con.execute(
        "INSERT INTO cultures(receipt_item_id, specimen, growth, organism, "
        "colony_count, gram_stain, zn_stain, remarks) VALUES (?,?,?,?,?,?,?,?)",
        (
            item_id,
            specimen,
            growth,
            organism,
            colony_count,
            gram_stain,
            zn_stain,
            remarks,
        ),
    ).lastrowid
    con.commit()
    return cid


def make_sensitivity(con, culture_id, *, antibiotic="Amikacin", result="S"):
    """Insert a culture-sensitivity row."""
    sid = con.execute(
        "INSERT INTO culture_sensitivity(culture_id, antibiotic, result) "
        "VALUES (?,?,?)",
        (culture_id, antibiotic, result),
    ).lastrowid
    con.commit()
    return sid


def build_full_receipt(con):
    """A reported receipt with one item, one result, one culture + one sensitivity —
    enough to exercise every branch of report.verify.report_fingerprint. Returns the
    receipt id."""
    rid = make_receipt(con)
    iid = make_item(con, rid)
    make_result(con, iid, name="Haemoglobin", value="13.5")
    cid = make_culture(con, iid, growth="Growth present", organism="E. coli")
    make_sensitivity(con, cid, antibiotic="Amikacin", result="S")
    return rid
