"""Wave 2 — clinical result + culture release behind an authorized service boundary.

Asserts the security guarantee directly: a role lacking ``finalize_results`` is
denied and nothing is written; an authorized role writes the results/culture rows,
flips the receipt to 'reported', and audits — atomically. These are the services
ui/worklist.py and ui/microbiology.py now call instead of inline SQL in the widgets.
"""

from __future__ import annotations

import pytest

from factories import make_item, make_receipt
from labdesk.application import results as svc


def _count(con, sql, *args):
    return con.execute(sql, args).fetchone()[0]


# --------------------------------------------------------------------------
# release_results (worklist)
# --------------------------------------------------------------------------


def test_release_denied_for_low_role_writes_nothing(con):
    rid = make_receipt(con, status="pending")
    iid = make_item(con, rid)
    rows = [{"item_id": iid, "parameter_id": None, "value": "13.5", "hidden": 0}]
    with pytest.raises(PermissionError):
        svc.release_results(
            con,
            receipt_id=rid,
            result_rows=rows,
            remarks={},
            static_rows=[],
            actor_username="rita",
            actor_role="receptionist",
        )
    assert _count(con, "SELECT COUNT(*) FROM results WHERE receipt_item_id=?", iid) == 0
    assert (
        con.execute("SELECT status FROM receipts WHERE id=?", (rid,)).fetchone()[0]
        == "pending"
    )


def test_release_writes_results_and_reports(con):
    rid = make_receipt(con, status="pending")
    iid = make_item(con, rid)
    rows = [{"item_id": iid, "parameter_id": None, "value": "13.5", "hidden": 0}]
    lab_no = svc.release_results(
        con,
        receipt_id=rid,
        result_rows=rows,
        remarks={iid: "looks fine"},
        static_rows=[],
        actor_username="tom",
        actor_role="technician",
    )
    assert lab_no  # returned lab number / id

    res = con.execute(
        "SELECT value FROM results WHERE receipt_item_id=? AND parameter_id IS NULL",
        (iid,),
    ).fetchone()
    assert res["value"] == "13.5"
    rcpt = con.execute(
        "SELECT status, reported_at FROM receipts WHERE id=?", (rid,)
    ).fetchone()
    assert rcpt["status"] == "reported"
    assert rcpt["reported_at"] is not None
    assert (
        con.execute("SELECT remarks FROM receipt_items WHERE id=?", (iid,)).fetchone()[
            0
        ]
        == "looks fine"
    )
    assert (
        _count(con, "SELECT COUNT(*) FROM audit_log WHERE action='results_saved'") >= 1
    )


def test_release_does_not_re_stamp_already_reported(con):
    # An already-reported receipt keeps its original reported_at (status guard).
    rid = make_receipt(con, status="reported", reported_at="2020-01-01 00:00:00")
    iid = make_item(con, rid)
    svc.release_results(
        con,
        receipt_id=rid,
        result_rows=[{"item_id": iid, "parameter_id": None, "value": "x", "hidden": 0}],
        remarks={},
        static_rows=[],
        actor_username="tom",
        actor_role="technician",
    )
    assert (
        con.execute("SELECT reported_at FROM receipts WHERE id=?", (rid,)).fetchone()[0]
        == "2020-01-01 00:00:00"
    )


# --------------------------------------------------------------------------
# save_culture (microbiology)
# --------------------------------------------------------------------------


def _culture():
    return {
        "specimen": "Urine",
        "growth": "Growth present",
        "organism": "E. coli",
        "colony_count": ">10^5",
        "gram_stain": "GNB",
        "zn_stain": "",
        "remarks": "",
    }


def test_save_culture_denied_for_low_role_writes_nothing(con):
    rid = make_receipt(con, status="pending")
    iid = make_item(con, rid)
    with pytest.raises(PermissionError):
        svc.save_culture(
            con,
            item_id=iid,
            culture=_culture(),
            sensitivities=[("Amikacin", "S")],
            actor_username="rita",
            actor_role="receptionist",
        )
    assert (
        _count(con, "SELECT COUNT(*) FROM cultures WHERE receipt_item_id=?", iid) == 0
    )


def test_save_culture_writes_all_and_reports(con):
    rid = make_receipt(con, status="pending")
    iid = make_item(con, rid)
    svc.save_culture(
        con,
        item_id=iid,
        culture=_culture(),
        sensitivities=[("Amikacin", "S"), ("", "R")],  # blank antibiotic is skipped
        actor_username="tom",
        actor_role="technician",
    )
    cid = con.execute(
        "SELECT id FROM cultures WHERE receipt_item_id=?", (iid,)
    ).fetchone()["id"]
    assert (
        _count(con, "SELECT COUNT(*) FROM culture_sensitivity WHERE culture_id=?", cid)
        == 1
    )
    assert (
        con.execute("SELECT reported FROM receipt_items WHERE id=?", (iid,)).fetchone()[
            0
        ]
        == 1
    )
    assert (
        con.execute("SELECT status FROM receipts WHERE id=?", (rid,)).fetchone()[0]
        == "reported"
    )
    assert (
        _count(con, "SELECT COUNT(*) FROM audit_log WHERE action='culture_saved'") >= 1
    )


def test_save_culture_replaces_previous(con):
    rid = make_receipt(con, status="pending")
    iid = make_item(con, rid)
    svc.save_culture(
        con,
        item_id=iid,
        culture=_culture(),
        sensitivities=[],
        actor_username="tom",
        actor_role="technician",
    )
    svc.save_culture(
        con,
        item_id=iid,
        culture=_culture(),
        sensitivities=[],
        actor_username="tom",
        actor_role="technician",
    )
    # DELETE-then-INSERT means exactly one culture row remains, not two.
    assert (
        _count(con, "SELECT COUNT(*) FROM cultures WHERE receipt_item_id=?", iid) == 1
    )


def test_release_rolls_back_on_bad_item(con):
    # A result row referencing a non-existent receipt_item violates the FK; the whole
    # release rolls back and re-raises, leaving the receipt un-reported.
    rid = make_receipt(con, status="pending")
    rows = [{"item_id": 999999, "parameter_id": None, "value": "x", "hidden": 0}]
    with pytest.raises(Exception):  # noqa: B017 - sqlite IntegrityError subclass
        svc.release_results(
            con,
            receipt_id=rid,
            result_rows=rows,
            remarks={},
            static_rows=[],
            actor_username="tom",
            actor_role="technician",
        )
    assert (
        con.execute("SELECT status FROM receipts WHERE id=?", (rid,)).fetchone()[0]
        == "pending"
    )


def test_save_culture_rolls_back_on_bad_item(con):
    with pytest.raises(Exception):  # noqa: B017 - sqlite IntegrityError subclass
        svc.save_culture(
            con,
            item_id=999999,
            culture=_culture(),
            sensitivities=[],
            actor_username="tom",
            actor_role="technician",
        )
    assert (
        _count(con, "SELECT COUNT(*) FROM cultures WHERE receipt_item_id=?", 999999)
        == 0
    )
