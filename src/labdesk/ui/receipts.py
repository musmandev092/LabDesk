"""Receipts: history of all saved receipts — search, reprint, take due payment."""
from __future__ import annotations

import tempfile

from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QLineEdit,
    QComboBox, QPushButton, QHeaderView, QLabel, QDateEdit, QMessageBox, QCheckBox,
    QDialog, QFrame,
)

from .widgets import h1, muted, page_header, money
from . import wa
from .. import db, report

STATUS_COLORS = {"pending": "#b9770e", "in_progress": "#0e7c86",
                 "reported": "#1f9d55", "delivered": "#6b7280"}
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
        tb.addStretch(1)
        root.addLayout(tb)

        # filters
        bar = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search patient / lab no / MR no…")
        self.search.setMinimumHeight(40)
        self.search.textChanged.connect(self.refresh)
        self.status = QComboBox(); self.status.setMinimumHeight(40)
        for v, lbl in [("All", "All status"), ("pending", "Pending"), ("in_progress", "In Progress"),
                       ("reported", "Reported"), ("delivered", "Delivered")]:
            self.status.addItem(lbl, v)
        self.status.currentIndexChanged.connect(self.refresh)
        self.today_only = QCheckBox("Today only"); self.today_only.toggled.connect(self.refresh)
        self.dues_only = QCheckBox("Dues only"); self.dues_only.toggled.connect(self.refresh)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.status)
        bar.addWidget(self.today_only)
        bar.addWidget(self.dues_only)
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

    def _num(self, text, color=None):
        it = QTableWidgetItem(text)
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if color:
            it.setForeground(QColor(color))
        return it

    def refresh(self):
        q = f"%{self.search.text().strip()}%"
        sql = ("SELECT * FROM receipts WHERE (patient_name LIKE ? OR lab_no LIKE ? OR mr_no LIKE ?)")
        args = [q, q, q]
        st = self.status.currentData()
        if st and st != "All":
            sql += " AND status=?"; args.append(st)
        if self.today_only.isChecked():
            sql += " AND date(received_at)=date('now','localtime')"
        if self.dues_only.isChecked():
            sql += " AND due>0"
        sql += " ORDER BY id DESC LIMIT 1000"
        rows = self.con.execute(sql, args).fetchall()
        cur = db.get_setting(self.con, "currency", "Rs.")
        self.table.setRowCount(0); self._ids = []
        tot_net = tot_paid = tot_due = 0.0
        for r in rows:
            i = self.table.rowCount(); self.table.insertRow(i)
            self._ids.append(r["id"])
            self.table.setItem(i, 0, QTableWidgetItem(r["lab_no"] or ""))
            self.table.setItem(i, 1, QTableWidgetItem((r["received_at"] or "")[:16]))
            self.table.setItem(i, 2, QTableWidgetItem(r["patient_name"] or ""))
            self.table.setItem(i, 3, QTableWidgetItem(r["dr_name"] or ""))
            self.table.setItem(i, 4, self._num(f"{r['net_amount']:,.0f}"))
            self.table.setItem(i, 5, self._num(f"{r['paid']:,.0f}"))
            self.table.setItem(i, 6, self._num(f"{r['due']:,.0f}", "#c0392b" if r["due"] else None))
            st_item = QTableWidgetItem((r["status"] or "").replace("_", " ").title())
            col = STATUS_COLORS.get(r["status"] or "")
            if col:
                st_item.setForeground(QColor(col))
                fnt = st_item.font(); fnt.setBold(True); st_item.setFont(fnt)
            self.table.setItem(i, 7, st_item)
            tot_net += r["net_amount"] or 0; tot_paid += r["paid"] or 0; tot_due += r["due"] or 0
        self.sub.setText(f"{len(rows)} receipt(s)")
        self.sub.show()
        self.summary.setText(
            f"Showing {len(rows)} receipt(s)   •   Net {money(tot_net, cur)}   •   "
            f"Paid {money(tot_paid, cur)}   •   Due {money(tot_due, cur)}")
        self._update_buttons()

    def _selected_id(self):
        r = self.table.currentRow()
        return self._ids[r] if 0 <= r < len(self._ids) else None

    def _update_buttons(self):
        rid = self._selected_id()
        on = rid is not None
        # receipt (bill) actions are available as soon as a row is selected
        for b in self._receipt_btns:
            b.setEnabled(on)
        if on:
            row = self.con.execute(
                "SELECT due, status FROM receipts WHERE id=?", (rid,)).fetchone()
            ready = (row["status"] or "") in REPORT_READY   # report only when results are in
            for b in self._report_btns:
                b.setEnabled(ready)
                b.setToolTip("" if ready else "Report not ready yet (results pending)")
            self.pay_btn.setEnabled(bool(row["due"] and row["due"] > 0))
        else:
            for b in (*self._report_btns, self.pay_btn):
                b.setEnabled(False)

    # ---------------------------------------------------------------
    def _preview(self, kind):
        """kind: 'report' or 'receipt'."""
        rid = self._selected_id()
        if rid is None:
            return
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False); tmp.close()
            if kind == "receipt":
                report.export_receipt_pdf(self.con, rid, tmp.name)
                _PreviewDialog(tmp.name, self, "Receipt preview").exec()
            else:
                report.export_report_pdf(self.con, rid, tmp.name)
                _PreviewDialog(tmp.name, self, "Report preview").exec()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Preview", f"Could not build the preview:\n{e}")

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
                      lock_buttons=(self.wa_rcpt_btn, self.wa_rpt_btn))

    def whatsapp_receipt(self):
        self._send_whatsapp("receipt")

    def whatsapp_report(self):
        self._send_whatsapp("report")

    def reprint(self):
        rid = self._selected_id()
        if rid is not None:
            report.print_receipt(self.con, rid, self)

    def print_report(self):
        rid = self._selected_id()
        if rid is not None:
            report.print_report(self.con, rid, self)

    def receive_due(self):
        rid = self._selected_id()
        if rid is None:
            return
        r = self.con.execute("SELECT lab_no, due FROM receipts WHERE id=?", (rid,)).fetchone()
        if not r or not r["due"]:
            return
        cur = db.get_setting(self.con, "currency", "Rs.")
        if QMessageBox.question(
            self, "Receive payment",
            f"Mark {r['lab_no']} due of {money(r['due'], cur)} as fully paid?",
        ) != QMessageBox.Yes:
            return
        self.con.execute(
            "INSERT INTO ledger(kind,ref_id,detail,credit,date) "
            "VALUES ('due_recovery',?,?,?,date('now','localtime'))",
            (rid, f"Due recovered {r['lab_no']}", r["due"]))
        self.con.execute("UPDATE receipts SET paid=net_amount, due=0 WHERE id=?", (rid,))
        self.con.commit()
        self.refresh()
