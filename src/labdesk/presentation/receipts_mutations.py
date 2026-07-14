"""Receipt mutations (receive due, mark delivered, edit, void) — split out of ReceiptsPage."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QMessageBox,
)

from .. import db
from ..application import receipts as receipts_svc
from ..db import sqlite3
from ..roles import can
from .widgets import (
    money,
    toast_warn,
)

# a report can be previewed/printed only once results are in
REPORT_READY = ("reported", "delivered")


from .receipt_dialogs import _EditReceiptDialog
import contextlib


class ReceiptsMutationsMixin:
    def receive_due(self) -> None:
        rid = self._selected_id()
        if rid is None:
            return
        r = self.con.execute(
            "SELECT lab_no, due FROM receipts WHERE id=?", (rid,)
        ).fetchone()
        if not r or not r["due"] or r["due"] <= 0:
            return
        cur = db.currency(self.con)
        # partial payments allowed; cannot exceed due
        amount, ok = QInputDialog.getDouble(
            self,
            "Receive payment",
            f"Amount received for {r['lab_no']}  (due {money(r['due'], cur)}):",
            float(r["due"]),
            0.0,
            float(r["due"]),
            2,
        )
        if not ok or amount <= 0:
            return
        db.receive_due(
            self.con, rid, amount, self.user["username"], actor_role=self.user["role"]
        )
        self.refresh()

    def mark_delivered(self) -> None:
        rid = self._selected_id()
        if rid is None:
            return
        r = self.con.execute(
            "SELECT lab_no, status FROM receipts WHERE id=?", (rid,)
        ).fetchone()
        if not r or r["status"] not in REPORT_READY:
            return
        receipts_svc.mark_receipt_delivered(
            self.con, rid, self.user["username"], actor_role=self.user["role"]
        )
        self.refresh()

    def edit_receipt(self) -> None:
        if not self._can_edit_bill:
            return
        rid = self._selected_id()
        if rid is None:
            return
        rec = self.con.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()
        if not rec or ("voided" in rec.keys() and rec["voided"]):
            return  # a voided bill is read-only
        if (rec["status"] or "") in REPORT_READY:
            return  # frozen for everyone once reported/delivered
        cur = db.currency(self.con)
        dlg = _EditReceiptDialog(self.con, rec, cur, self)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        # delta of money actually collected (capped at net) — an over-payment is
        # change handed back, so it must not move the ledger
        old_collected = min(rec["paid"] or 0.0, rec["net_amount"] or 0.0)
        new_collected = min(v["paid"], v["net_amount"])
        delta = new_collected - old_collected
        try:
            # guarded to never drop an item that has results/cultures
            for iid in v["removed_item_ids"]:
                self.con.execute(
                    "DELETE FROM receipt_items WHERE id=? AND receipt_id=? "
                    "AND id NOT IN (SELECT receipt_item_id FROM results) "
                    "AND id NOT IN (SELECT receipt_item_id FROM cultures WHERE receipt_item_id IS NOT NULL)",
                    (iid, rid),
                )
            # add newly-picked tests (dual-write the paisa columns)
            for a in v["added"]:
                self.con.execute(
                    "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge,charge_paisa) "
                    "VALUES (?,?,?,?,CAST(ROUND(?*100) AS INTEGER))",
                    (rid, a["test_id"], a["name"], a["charge"], a["charge"]),
                )
            self.con.execute(
                "UPDATE receipts SET subtotal=?, discount_pct=?, less=?, net_amount=?, paid=?, due=?, "
                "payment_method=?, subtotal_paisa=CAST(ROUND(?*100) AS INTEGER), "
                "less_paisa=CAST(ROUND(?*100) AS INTEGER), "
                "net_amount_paisa=CAST(ROUND(?*100) AS INTEGER), "
                "paid_paisa=CAST(ROUND(?*100) AS INTEGER), "
                "due_paisa=CAST(ROUND(?*100) AS INTEGER) WHERE id=?",
                (
                    v["subtotal"],
                    v["discount_pct"],
                    v["subtotal"] - v["net_amount"],
                    v["net_amount"],
                    v["paid"],
                    v["due"],
                    v["payment_method"],
                    v["subtotal"],
                    v["subtotal"] - v["net_amount"],
                    v["net_amount"],
                    v["paid"],
                    v["due"],
                    rid,
                ),
            )
            # a test added to a finalised bill sends the report back to in-progress
            if v["added"] and (rec["status"] or "") in REPORT_READY:
                self.con.execute(
                    "UPDATE receipts SET status='in_progress' WHERE id=?", (rid,)
                )
            # keep the ledger balanced for any change in money actually collected
            if abs(delta) > 1e-9:
                if delta > 0:
                    self.con.execute(
                        "INSERT INTO ledger(kind,ref_id,detail,credit,credit_paisa,date) "
                        "VALUES ('adjustment',?,?,?,CAST(ROUND(?*100) AS INTEGER),"
                        "date('now','localtime'))",
                        (rid, f"Bill edit {rec['lab_no']} — extra paid", delta, delta),
                    )
                else:
                    self.con.execute(
                        "INSERT INTO ledger(kind,ref_id,detail,debit,debit_paisa,date) "
                        "VALUES ('adjustment',?,?,?,CAST(ROUND(?*100) AS INTEGER),"
                        "date('now','localtime'))",
                        (rid, f"Bill edit {rec['lab_no']} — refund", -delta, -delta),
                    )
            self.con.commit()
        except sqlite3.Error as e:
            with contextlib.suppress(sqlite3.Error):
                self.con.rollback()
            toast_warn(self, "Edit bill", f"Could not save the changes:\n{e}")
            return
        change = ""
        if v["added"] or v["removed_item_ids"]:
            change = f", +{len(v['added'])}/-{len(v['removed_item_ids'])} tests"
        db.log_audit(
            self.con,
            self.user["username"],
            "receipt_edited",
            f"{rec['lab_no']} — disc {v['discount_pct']:g}%, net {v['net_amount']:.0f}, "
            f"paid {v['paid']:.0f}, due {v['due']:.0f}{change}",
        )
        self.refresh()

    def void_receipt(self) -> None:
        if not can(self.user["role"], "delete"):
            return  # defence in depth — voiding is an admin action
        rid = self._selected_id()
        if rid is None:
            return
        r = self.con.execute(
            "SELECT lab_no, paid, voided FROM receipts WHERE id=?", (rid,)
        ).fetchone()
        if not r or r["voided"]:
            return
        reason, ok = QInputDialog.getText(
            self, "Void receipt", f"Reason for voiding {r['lab_no']} (required):"
        )
        if not ok:
            return  # cancelled
        if not reason.strip():
            toast_warn(self, "Void receipt", "A reason is required to void a receipt.")
            return
        if (
            QMessageBox.question(
                self,
                "Void receipt",
                f"Void {r['lab_no']}? It will be excluded from income, dues and the worklist. "
                "This cannot be undone.",
            )
            != QMessageBox.Yes
        ):
            return
        receipts_svc.void_receipt(
            self.con,
            rid,
            reason.strip(),
            self.user["username"],
            actor_role=self.user["role"],
        )
        self.refresh()
