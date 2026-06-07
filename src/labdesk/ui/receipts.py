"""Receipts: history of all saved receipts — search, reprint, take due payment."""
from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QLineEdit,
    QComboBox, QPushButton, QHeaderView, QLabel, QDateEdit, QMessageBox, QCheckBox,
    QDialog, QFrame, QInputDialog, QFileDialog, QFormLayout, QDoubleSpinBox,
)

from .widgets import muted, page_header, money, num_item, selected_id, status_badge
from . import wa, tasks
from .. import db, report
from ..constants import PAYMENT_METHODS
from ..roles import can

# a report can be previewed/printed only once results are in
REPORT_READY = ("reported", "delivered")


class _PreviewDialog(QDialog):
    """In-app PDF preview of a report or receipt (uses Qt's PDF viewer)."""
    def __init__(self, pdf_path, parent=None, title="Preview"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(840, 1040)
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView
        self._doc = QPdfDocument(self)
        self._doc.load(pdf_path)
        view = QPdfView(self)
        view.setDocument(self._doc)
        try:
            view.setPageMode(QPdfView.PageMode.MultiPage)
            view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        except Exception:
            pass
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(view)


class _EditReceiptDialog(QDialog):
    """Adjust a pending bill's discount, amount paid and payment method.
    Subtotal (the tests) is fixed here — add/remove tests via a new receipt."""
    def __init__(self, rec, currency="Rs.", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit bill {rec['lab_no'] or ''}")
        self.setMinimumWidth(380)
        self._sub = rec["subtotal"] or 0.0
        self.cur = currency
        form = QFormLayout(self)
        form.addRow("Patient", QLabel(rec["patient_name"] or ""))
        self.sub_lbl = QLabel(money(self._sub, currency))
        form.addRow("Subtotal", self.sub_lbl)
        self.discount = QDoubleSpinBox(); self.discount.setMaximum(100); self.discount.setSuffix(" %")
        self.discount.setValue(rec["discount_pct"] or 0)
        self.discount.valueChanged.connect(self._recompute)
        form.addRow("Discount", self.discount)
        self.net_lbl = QLabel(); self.net_lbl.setStyleSheet("font-weight:800;color:#0a5f67;")
        form.addRow("Net payable", self.net_lbl)
        self.paid = QDoubleSpinBox(); self.paid.setMaximum(1_000_000); self.paid.setPrefix(f"{currency} ")
        self.paid.setValue(rec["paid"] or 0)
        self.paid.valueChanged.connect(self._recompute)
        form.addRow("Paid", self.paid)
        self.method = QComboBox()
        self.method.addItems(PAYMENT_METHODS)
        if rec["payment_method"]:
            self.method.setCurrentText(rec["payment_method"])
        form.addRow("Payment method", self.method)
        self.due_lbl = QLabel(); self.due_lbl.setStyleSheet("font-weight:800;color:#c0392b;")
        form.addRow("Due", self.due_lbl)
        btns = QHBoxLayout()
        ok = QPushButton("Save changes"); ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel"); cancel.setObjectName("ghost"); cancel.clicked.connect(self.reject)
        btns.addStretch(1); btns.addWidget(cancel); btns.addWidget(ok)
        form.addRow(btns)
        self._recompute()

    def _net(self):
        return max(0.0, self._sub - self._sub * self.discount.value() / 100.0)

    def _recompute(self):
        net = self._net()
        due = max(0.0, net - self.paid.value())
        self.net_lbl.setText(money(net, self.cur))
        self.due_lbl.setText(money(due, self.cur))

    def values(self):
        net = self._net()
        return {
            "discount_pct": self.discount.value(),
            "net_amount": net,
            "paid": self.paid.value(),
            "due": max(0.0, net - self.paid.value()),
            "payment_method": self.method.currentText(),
        }


class ReceiptsPage(QWidget):
    def __init__(self, con, user):
        super().__init__()
        self.con = con
        self.user = user
        self._ids = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header, self.sub = page_header("Receipts / Reports", "All saved receipts")
        root.addWidget(header)

        def _btn(text, slot):
            b = QPushButton(text); b.setObjectName("ghost"); b.setEnabled(False)
            b.clicked.connect(slot)
            return b
        # receipt (bill) actions — available as soon as a saved receipt is selected
        self.prev_rcpt_btn = _btn("Preview receipt", self.preview_receipt)
        self.print_rcpt_btn = _btn("Print receipt", self.reprint)
        self.wa_rcpt_btn = _btn("WhatsApp receipt", self.whatsapp_receipt)
        # report actions — only once results are entered (report ready)
        self.prev_rpt_btn = _btn("Preview report", self.preview)
        self.print_rpt_btn = _btn("Print report", self.print_report)
        self.wa_rpt_btn = _btn("WhatsApp report", self.whatsapp_report)
        self.pay_btn = _btn("Receive due", self.receive_due)
        self.deliver_btn = _btn("Mark delivered", self.mark_delivered)
        self.edit_btn = _btn("Edit bill", self.edit_receipt)
        self.void_btn = _btn("Void", self.void_receipt)
        self._report_btns = (self.prev_rpt_btn, self.print_rpt_btn, self.wa_rpt_btn)
        self._receipt_btns = (self.prev_rcpt_btn, self.print_rcpt_btn, self.wa_rcpt_btn)

        tb = QHBoxLayout(); tb.setSpacing(8)
        rcpt_lbl = QLabel("Receipt:"); rcpt_lbl.setObjectName("muted"); tb.addWidget(rcpt_lbl)
        for b in self._receipt_btns:
            tb.addWidget(b)
        sep1 = QFrame(); sep1.setFrameShape(QFrame.VLine); sep1.setFrameShadow(QFrame.Sunken)
        tb.addWidget(sep1)
        rpt_lbl = QLabel("Report:"); rpt_lbl.setObjectName("muted"); tb.addWidget(rpt_lbl)
        for b in self._report_btns:
            tb.addWidget(b)
        sep2 = QFrame(); sep2.setFrameShape(QFrame.VLine); sep2.setFrameShadow(QFrame.Sunken)
        tb.addWidget(sep2)
        tb.addWidget(self.pay_btn)
        tb.addWidget(self.deliver_btn)
        # editing the bill (discount/paid/method) and voiding are manager/admin actions
        self._can_edit_bill = can(self.user["role"], "apply_discount")
        if self._can_edit_bill:
            tb.addWidget(self.edit_btn)
        else:
            self.edit_btn.hide()
        if can(self.user["role"], "delete"):
            tb.addWidget(self.void_btn)   # voiding a bill is a manager/admin action
        else:
            self.void_btn.hide()
        tb.addStretch(1)
        root.addLayout(tb)

        # filters
        bar = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search patient / lab no / MR no…")
        self.search.setMinimumHeight(40)
        self.search.textChanged.connect(tasks.debounce(self, self.refresh))
        self.status = QComboBox(); self.status.setMinimumHeight(40)
        for v, lbl in [("All", "All status"), ("pending", "Pending"), ("in_progress", "In Progress"),
                       ("reported", "Reported"), ("delivered", "Delivered")]:
            self.status.addItem(lbl, v)
        self.status.currentIndexChanged.connect(self.refresh)
        self.today_only = QCheckBox("Today only"); self.today_only.toggled.connect(self.refresh)
        self.dues_only = QCheckBox("Dues only"); self.dues_only.toggled.connect(self.refresh)
        export = QPushButton("Export CSV"); export.setObjectName("ghost")
        export.clicked.connect(self.export_csv)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.status)
        bar.addWidget(self.today_only)
        bar.addWidget(self.dues_only)
        bar.addWidget(export)
        root.addLayout(bar)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Lab No", "Date", "Patient", "Doctor", "Net (Rs.)", "Paid (Rs.)", "Due (Rs.)", "Status"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.doubleClicked.connect(self.reprint)
        root.addWidget(self.table, 1)

        self.summary = muted("")
        root.addWidget(self.summary)

    # ---------------------------------------------------------------
    def on_show(self):
        self.refresh()

    def apply_nav(self, today=False, dues=False, **_):
        """Called when navigated to from the dashboard."""
        self.today_only.setChecked(bool(today))
        self.dues_only.setChecked(bool(dues))
        self.refresh()

    def refresh(self):
        q = f"%{self.search.text().strip()}%"
        sql = ("SELECT * FROM receipts WHERE (COALESCE(patient_name,'') LIKE ? "
               "OR COALESCE(lab_no,'') LIKE ? OR COALESCE(mr_no,'') LIKE ?)")
        args = [q, q, q]
        st = self.status.currentData()
        if st and st != "All":
            sql += " AND status=?"; args.append(st)
        if self.today_only.isChecked():
            sql += f" AND {db.RECEIVED_TODAY}"
        if self.dues_only.isChecked():
            sql += f" AND due>0 AND {db.NOT_VOIDED}"
        sql += " ORDER BY id DESC LIMIT 1000"
        rows = self.con.execute(sql, args).fetchall()
        cur = db.currency(self.con)
        self.table.setRowCount(0); self._ids = []
        tot_net = tot_paid = tot_due = 0.0
        for r in rows:
            i = self.table.rowCount(); self.table.insertRow(i)
            self._ids.append(r["id"])
            self.table.setItem(i, 0, QTableWidgetItem(r["lab_no"] or ""))
            self.table.setItem(i, 1, QTableWidgetItem((r["received_at"] or "")[:16]))
            self.table.setItem(i, 2, QTableWidgetItem(r["patient_name"] or ""))
            self.table.setItem(i, 3, QTableWidgetItem(r["dr_name"] or ""))
            self.table.setItem(i, 4, num_item(f"{r['net_amount']:,.0f}"))
            self.table.setItem(i, 5, num_item(f"{r['paid']:,.0f}"))
            self.table.setItem(i, 6, num_item(f"{r['due']:,.0f}", "#c0392b" if r["due"] else None))
            voided = ("voided" in r.keys() and r["voided"])
            self.table.setItem(i, 7, status_badge(r["status"] or "", voided))
            if not voided:   # voided bills don't count toward the money totals
                tot_net += r["net_amount"] or 0
                tot_paid += r["paid"] or 0
                tot_due += r["due"] or 0
        self.sub.setText(f"{len(rows)} receipt(s)")
        self.sub.show()
        self.summary.setText(
            f"Showing {len(rows)} receipt(s)   •   Net {money(tot_net, cur)}   •   "
            f"Paid {money(tot_paid, cur)}   •   Due {money(tot_due, cur)}")
        self._update_buttons()

    def _selected_id(self):
        return selected_id(self.table, self._ids)

    def _update_buttons(self):
        rid = self._selected_id()
        on = rid is not None
        voided = False
        if on:
            row = self.con.execute(
                "SELECT due, status, voided FROM receipts WHERE id=?", (rid,)).fetchone()
            voided = bool("voided" in row.keys() and row["voided"])
        active = on and not voided   # a voided bill is read-only
        for b in self._receipt_btns:
            b.setEnabled(active)
        if active:
            ready = (row["status"] or "") in REPORT_READY   # report only when results are in
            for b in self._report_btns:
                b.setEnabled(ready)
                b.setToolTip("" if ready else "Report not ready yet (results pending)")
            self.pay_btn.setEnabled(bool(row["due"] and row["due"] > 0))
            self.deliver_btn.setEnabled(ready and (row["status"] or "") != "delivered")
            # bill can be edited until it's been handed over (delivered)
            self.edit_btn.setEnabled(self._can_edit_bill and (row["status"] or "") != "delivered")
            self.void_btn.setEnabled(True)
        else:
            for b in (*self._report_btns, self.pay_btn, self.deliver_btn,
                      self.edit_btn, self.void_btn):
                b.setEnabled(False)

    # ---------------------------------------------------------------
    def _lab_no(self, rid):
        r = self.con.execute("SELECT lab_no FROM receipts WHERE id=?", (rid,)).fetchone()
        return (r["lab_no"] if r and r["lab_no"] else f"#{rid}")

    def _preview(self, kind):
        """kind: 'report' or 'receipt'. Builds the PDF off the UI thread, then
        opens the preview dialog when it's ready (window stays responsive)."""
        rid = self._selected_id()
        if rid is None:
            return
        clicked = self.prev_rcpt_btn if kind == "receipt" else self.prev_rpt_btn
        title = "Receipt preview" if kind == "receipt" else "Report preview"
        build = report.build_receipt_bytes if kind == "receipt" else report.build_report_bytes
        labno = self._lab_no(rid)

        def ready(result):
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)  # 0600
            tmp.write(result); tmp.close()
            db.log_audit(self.con, self.user["username"], "previewed_" + kind, labno)
            try:
                _PreviewDialog(tmp.name, self, title).exec()
            finally:
                try:
                    os.remove(tmp.name)        # no patient-PII residue in temp
                except OSError:
                    pass

        tasks.build_pdf(self, lambda con: build(con, rid), ready,
                        clicked=clicked, busy_text="Opening…", error_title="Preview")

    def preview(self):
        self._preview("report")

    def preview_receipt(self):
        self._preview("receipt")

    def _send_whatsapp(self, kind):
        rid = self._selected_id()
        if rid is None:
            return
        clicked = self.wa_rcpt_btn if kind == "receipt" else self.wa_rpt_btn
        # runs on a background thread; disables both WhatsApp buttons until done
        wa.send_async(self, self.con, kind, rid, clicked=clicked,
                      lock_buttons=(self.wa_rcpt_btn, self.wa_rpt_btn),
                      on_done=lambda ok, m: db.log_audit(
                          self.con, self.user["username"], "whatsapp_" + kind,
                          ("sent" if ok else "failed") + f" — receipt {rid}"))

    def whatsapp_receipt(self):
        self._send_whatsapp("receipt")

    def whatsapp_report(self):
        self._send_whatsapp("report")

    def _print(self, kind):
        """Build the PDF off the UI thread, then print on the UI thread."""
        rid = self._selected_id()
        if rid is None:
            return
        clicked = self.print_rcpt_btn if kind == "receipt" else self.print_rpt_btn
        title = "Print Receipt" if kind == "receipt" else "Print Report"
        build = report.build_receipt_bytes if kind == "receipt" else report.build_report_bytes
        printer = db.get_setting(self.con, "default_printer", "")
        labno = self._lab_no(rid)

        def ready(result):
            report.print_bytes(result, self, title, printer)
            db.log_audit(self.con, self.user["username"], "printed_" + kind, labno)

        tasks.build_pdf(self, lambda con: build(con, rid), ready,
                        clicked=clicked, busy_text="Preparing…", error_title="Print")

    def reprint(self):
        self._print("receipt")

    def print_report(self):
        self._print("report")

    def receive_due(self):
        rid = self._selected_id()
        if rid is None:
            return
        r = self.con.execute(
            "SELECT lab_no, due FROM receipts WHERE id=?", (rid,)).fetchone()
        if not r or not r["due"] or r["due"] <= 0:
            return
        cur = db.currency(self.con)
        # prompt for the actual amount received (supports partial payments; cannot exceed due)
        amount, ok = QInputDialog.getDouble(
            self, "Receive payment",
            f"Amount received for {r['lab_no']}  (due {money(r['due'], cur)}):",
            float(r["due"]), 0.0, float(r["due"]), 2)
        if not ok or amount <= 0:
            return
        db.receive_due(self.con, rid, amount, self.user["username"])
        self.refresh()

    def mark_delivered(self):
        rid = self._selected_id()
        if rid is None:
            return
        r = self.con.execute("SELECT lab_no, status FROM receipts WHERE id=?", (rid,)).fetchone()
        if not r or r["status"] not in REPORT_READY:
            return
        self.con.execute(
            "UPDATE receipts SET status='delivered', delivered_at=datetime('now','localtime'), "
            "delivered_by=? WHERE id=?", (self.user["username"], rid))
        self.con.commit()
        db.log_audit(self.con, self.user["username"], "report_delivered", r["lab_no"] or f"#{rid}")
        self.refresh()

    def edit_receipt(self):
        if not self._can_edit_bill:
            return
        rid = self._selected_id()
        if rid is None:
            return
        rec = self.con.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()
        if not rec or ("voided" in rec.keys() and rec["voided"]) or rec["status"] == "delivered":
            return
        cur = db.currency(self.con)
        dlg = _EditReceiptDialog(rec, cur, self)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        old_paid = rec["paid"] or 0.0
        delta = v["paid"] - old_paid
        try:
            self.con.execute(
                "UPDATE receipts SET discount_pct=?, less=?, net_amount=?, paid=?, due=?, "
                "payment_method=? WHERE id=?",
                (v["discount_pct"], (rec["subtotal"] or 0) - v["net_amount"], v["net_amount"],
                 v["paid"], v["due"], v["payment_method"], rid))
            # keep the ledger balanced for any change in money actually collected
            if abs(delta) > 1e-9:
                if delta > 0:
                    self.con.execute(
                        "INSERT INTO ledger(kind,ref_id,detail,credit,date) "
                        "VALUES ('adjustment',?,?,?,date('now','localtime'))",
                        (rid, f"Bill edit {rec['lab_no']} — extra paid", delta))
                else:
                    self.con.execute(
                        "INSERT INTO ledger(kind,ref_id,detail,debit,date) "
                        "VALUES ('adjustment',?,?,?,date('now','localtime'))",
                        (rid, f"Bill edit {rec['lab_no']} — refund", -delta))
            self.con.commit()
        except Exception as e:  # noqa: BLE001
            try:
                self.con.rollback()
            except Exception:  # noqa: BLE001
                pass
            QMessageBox.warning(self, "Edit bill", f"Could not save the changes:\n{e}")
            return
        db.log_audit(self.con, self.user["username"], "receipt_edited",
                     f"{rec['lab_no']} — disc {v['discount_pct']:g}%, net {v['net_amount']:.0f}, "
                     f"paid {v['paid']:.0f}, due {v['due']:.0f}")
        self.refresh()

    def void_receipt(self):
        rid = self._selected_id()
        if rid is None:
            return
        r = self.con.execute("SELECT lab_no, paid, voided FROM receipts WHERE id=?", (rid,)).fetchone()
        if not r or r["voided"]:
            return
        reason, ok = QInputDialog.getText(self, "Void receipt", f"Reason for voiding {r['lab_no']}:")
        if not ok or not reason.strip():
            return
        if QMessageBox.question(
            self, "Void receipt",
            f"Void {r['lab_no']}? It will be excluded from income, dues and the worklist. "
            "This cannot be undone.") != QMessageBox.Yes:
            return
        self.con.execute(
            "UPDATE receipts SET voided=1, void_reason=?, voided_at=datetime('now','localtime'), "
            "voided_by=?, due=0 WHERE id=?", (reason.strip(), self.user["username"], rid))
        if r["paid"]:  # reversing ledger entry keeps ledger-based accounting balanced
            self.con.execute(
                "INSERT INTO ledger(kind,ref_id,detail,debit,date) "
                "VALUES ('void',?,?,?,date('now','localtime'))",
                (rid, f"Void {r['lab_no']} — {reason.strip()[:60]}", r["paid"]))
        self.con.commit()
        db.log_audit(self.con, self.user["username"], "receipt_voided",
                     f"{r['lab_no']} — {reason.strip()[:80]}")
        self.refresh()

    def export_csv(self):
        import csv
        path, _ = QFileDialog.getSaveFileName(self, "Export receipts to CSV", "receipts.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        try:
            cols = self.table.columnCount()
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([self.table.horizontalHeaderItem(c).text() for c in range(cols)])
                for r in range(self.table.rowCount()):
                    w.writerow([(self.table.item(r, c).text() if self.table.item(r, c) else "")
                                for c in range(cols)])
            db.log_audit(self.con, self.user["username"], "exported_csv",
                         f"receipts ({self.table.rowCount()} rows) → {path}")
            QMessageBox.information(self, "Export",
                                   f"Exported {self.table.rowCount()} rows to:\n{path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Export", f"Could not export:\n{e}")
