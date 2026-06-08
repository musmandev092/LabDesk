"""Receipt DB-mutation helpers (no Qt).

These perform the writes + audit exactly as the ReceiptsPage view did after its
confirmation dialogs. The view keeps the dialogs/refresh; the SQL + audit live
here so they can be tested directly.
"""

from __future__ import annotations

import sqlite3

from .. import db


def void_receipt(con: sqlite3.Connection, receipt_id: int, reason: str, username: str) -> None:
    """Void a receipt: mark voided, zero its due, reverse the ledger if paid, audit.

    ``reason`` is expected already-stripped by the caller (the view stripped it
    before confirming); the lab_no is read here for the ledger/audit detail.
    """
    r = con.execute(
        "SELECT lab_no, paid, voided FROM receipts WHERE id=?", (receipt_id,)
    ).fetchone()
    con.execute(
        "UPDATE receipts SET voided=1, void_reason=?, voided_at=datetime('now','localtime'), "
        "voided_by=?, due=0 WHERE id=?",
        (reason, username, receipt_id),
    )
    if r["paid"]:  # reversing ledger entry keeps ledger-based accounting balanced
        con.execute(
            "INSERT INTO ledger(kind,ref_id,detail,debit,date) "
            "VALUES ('void',?,?,?,date('now','localtime'))",
            (receipt_id, f"Void {r['lab_no']} — {reason[:60]}", r["paid"]),
        )
    con.commit()
    db.log_audit(
        con,
        username,
        "receipt_voided",
        f"{r['lab_no']} — {reason[:80]}",
    )


def mark_receipt_delivered(con: sqlite3.Connection, receipt_id: int, username: str) -> None:
    """Mark a receipt's report as delivered + audit."""
    r = con.execute("SELECT lab_no FROM receipts WHERE id=?", (receipt_id,)).fetchone()
    con.execute(
        "UPDATE receipts SET status='delivered', delivered_at=datetime('now','localtime'), "
        "delivered_by=? WHERE id=?",
        (username, receipt_id),
    )
    con.commit()
    db.log_audit(con, username, "report_delivered", r["lab_no"] or f"#{receipt_id}")
