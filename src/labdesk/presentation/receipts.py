"""Receipts: history of all saved receipts — search, reprint, take due payment."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import db
from ..roles import can
from . import tasks
from .widgets import (
    FlowLayout,
    like_term,
    money,
    muted,
    num_item,
    page_header,
    selected_id,
    setup_date_edit,
    status_badge,
    toast_info,
    toast_warn,
)

# a report can be previewed/printed only once results are in
REPORT_READY = ("reported", "delivered")


from .receipts_mutations import ReceiptsMutationsMixin
from .receipts_output import ReceiptsOutputMixin


class ReceiptsPage(ReceiptsOutputMixin, ReceiptsMutationsMixin, QWidget):
    def __init__(self, con, user) -> None:
        super().__init__()
        self.con = con
        self.user = user
        self._ids: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header, self.sub = page_header("Receipts / Reports", "All saved receipts")
        root.addWidget(header)

        def _btn(text: str, slot) -> QPushButton:
            b = QPushButton(text)
            b.setObjectName("ghost")
            b.setEnabled(False)
            b.clicked.connect(slot)
            return b

        self.prev_rcpt_btn = _btn("Preview receipt", self.preview_receipt)
        self.print_rcpt_btn = _btn("Print receipt", self.reprint)
        self.pdf_rcpt_btn = _btn("Save receipt PDF", self.save_receipt_pdf)
        self.wa_rcpt_btn = _btn("WhatsApp receipt", self.whatsapp_receipt)
        self.prev_rpt_btn = _btn("Preview report", self.preview)
        self.print_rpt_btn = _btn("Print report", self.print_report)
        # admin-only: a header/footer-free copy for the lab's own letterhead pad
        self.print_plain_btn = _btn("Print on letterhead", self.print_report_plain)
        self.pdf_rpt_btn = _btn("Save report PDF", self.save_report_pdf)
        self.wa_rpt_btn = _btn("WhatsApp report", self.whatsapp_report)
        self.verify_rpt_btn = _btn("Verify report", self.verify_report)
        # per-print, non-persisted paper-saving toggle; read by ReceiptsOutputMixin
        self.one_per_page_chk = QCheckBox("One test per page")
        self.pay_btn = _btn("Receive due", self.receive_due)
        self.deliver_btn = _btn("Mark delivered", self.mark_delivered)
        self.edit_btn = _btn("Edit bill", self.edit_receipt)
        self.void_btn = _btn("Void", self.void_receipt)
        self._report_btns = (
            self.prev_rpt_btn,
            self.print_rpt_btn,
            self.pdf_rpt_btn,
            self.wa_rpt_btn,
            self.verify_rpt_btn,
        )
        self._receipt_btns = (
            self.prev_rcpt_btn,
            self.print_rcpt_btn,
            self.pdf_rcpt_btn,
            self.wa_rcpt_btn,
        )

        # FlowLayout wraps this action bar on narrow windows instead of forcing
        # a ~1870px minimum width
        tb = FlowLayout(hspacing=8, vspacing=6)
        rcpt_lbl = QLabel("Receipt:")
        rcpt_lbl.setObjectName("muted")
        tb.addWidget(rcpt_lbl)
        for b in self._receipt_btns:
            tb.addWidget(b)
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setFrameShadow(QFrame.Sunken)
        tb.addWidget(sep1)
        rpt_lbl = QLabel("Report:")
        rpt_lbl.setObjectName("muted")
        tb.addWidget(rpt_lbl)
        for b in self._report_btns:
            tb.addWidget(b)
        tb.addWidget(self.one_per_page_chk)
        if can(self.user["role"], "manage_users"):
            tb.addWidget(self.print_plain_btn)
        else:
            self.print_plain_btn.hide()
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setFrameShadow(QFrame.Sunken)
        tb.addWidget(sep2)
        tb.addWidget(self.pay_btn)
        tb.addWidget(self.deliver_btn)
        self._can_edit_bill = can(self.user["role"], "apply_discount")
        # once delivered, only an admin may edit; a manager only while pending/reported
        self._is_admin = can(self.user["role"], "manage_users")
        if self._can_edit_bill:
            tb.addWidget(self.edit_btn)
        else:
            self.edit_btn.hide()
        if can(self.user["role"], "delete"):
            tb.addWidget(self.void_btn)
        else:
            self.void_btn.hide()
        root.addLayout(tb)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search patient / lab no / Patient ID…")
        self.search.setMinimumHeight(40)
        self.search.textChanged.connect(tasks.debounce(self, self.refresh))
        self.status = QComboBox()
        self.status.setMinimumHeight(40)
        for v, lbl in [
            ("All", "All status"),
            ("pending", "Pending"),
            ("in_progress", "In Progress"),
            ("reported", "Reported"),
            ("delivered", "Delivered"),
        ]:
            self.status.addItem(lbl, v)
        self.status.currentIndexChanged.connect(self.refresh)
        self.today_only = QCheckBox("Today only")
        self.today_only.toggled.connect(self._today_toggled)
        self.dues_only = QCheckBox("Dues only")
        self.dues_only.toggled.connect(self.refresh)
        self.use_dates = QCheckBox("By date")
        self.use_dates.toggled.connect(self._dates_toggled)
        self.date_from = self._date_edit()
        self.date_to = self._date_edit()
        self.date_from.dateChanged.connect(self.refresh)
        self.date_to.dateChanged.connect(self.refresh)
        export = QPushButton("Export CSV")
        export.setObjectName("ghost")
        export.clicked.connect(self.export_csv)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.status)
        bar.addWidget(self.today_only)
        bar.addWidget(self.dues_only)
        bar.addWidget(self.use_dates)
        bar.addWidget(self.date_from)
        bar.addWidget(QLabel("→"))
        bar.addWidget(self.date_to)
        bar.addWidget(export)
        root.addLayout(bar)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            [
                "Lab No",
                "Date",
                "Patient",
                "Doctor",
                "Net (Rs.)",
                "Paid (Rs.)",
                "Due (Rs.)",
                "Status",
            ]
        )
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
        # printing is an explicit toolbar action, never a double-click
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_row_menu)
        root.addWidget(self.table, 1)

        self.summary = muted("")
        root.addWidget(self.summary)

    def _date_edit(self) -> QDateEdit:
        """A calendar-popup date editor, disabled until the 'By date' filter is on."""
        d = QDateEdit()
        setup_date_edit(d)
        d.setDisplayFormat("yyyy-MM-dd")
        d.setDate(QDate.currentDate())
        d.setEnabled(False)
        d.setMinimumHeight(40)
        return d

    def _dates_toggled(self, on: bool) -> None:
        self.date_from.setEnabled(on)
        self.date_to.setEnabled(on)
        if on and self.today_only.isChecked():  # the two date filters are exclusive
            self.today_only.blockSignals(True)
            self.today_only.setChecked(False)
            self.today_only.blockSignals(False)
        self.refresh()

    def _today_toggled(self, on: bool) -> None:
        if on and self.use_dates.isChecked():
            self.use_dates.setChecked(False)
        self.refresh()

    def _date_clause(self) -> tuple[str | None, list]:
        """SQL fragment + args for the active date-range filter, else (None, [])."""
        if not self.use_dates.isChecked():
            return None, []
        d1 = self.date_from.date()
        d2 = self.date_to.date()
        if d1 > d2:
            d1, d2 = d2, d1
        return (
            "received_at >= ? AND received_at < ?",
            [d1.toString("yyyy-MM-dd"), d2.addDays(1).toString("yyyy-MM-dd")],
        )

    def on_show(self) -> None:
        self.refresh()

    def apply_nav(self, today: bool = False, dues: bool = False, **_) -> None:
        """Called when navigated to from the dashboard."""
        self.today_only.setChecked(bool(today))
        self.dues_only.setChecked(bool(dues))
        self.refresh()

    _ROW_CAP = 1000  # most-recent rows shown in the table (kept responsive)

    def refresh(self) -> None:
        q = like_term(self.search.text())
        where = (
            "(COALESCE(patient_name,'') LIKE ? ESCAPE '\\' "
            "OR COALESCE(lab_no,'') LIKE ? ESCAPE '\\' OR COALESCE(mr_no,'') LIKE ? ESCAPE '\\')"
        )
        args = [q, q, q]
        st = self.status.currentData()
        if st and st != "All":
            where += " AND status=?"
            args.append(st)
        if self.today_only.isChecked():
            where += f" AND {db.RECEIVED_TODAY}"
        dc, dargs = self._date_clause()
        if dc:
            where += f" AND {dc}"
            args += dargs
        if self.dues_only.isChecked():
            where += f" AND due>0.005 AND {db.NOT_VOIDED}"
        rows = self.con.execute(
            f"SELECT * FROM receipts WHERE {where} ORDER BY id DESC LIMIT {self._ROW_CAP}",
            args,
        ).fetchall()
        # totals + count over ALL matching rows, not just the capped page
        agg = self.con.execute(
            f"SELECT COUNT(*) AS n, "
            f"COALESCE(SUM(CASE WHEN {db.NOT_VOIDED} THEN net_amount ELSE 0 END),0) AS net, "
            f"COALESCE(SUM(CASE WHEN {db.NOT_VOIDED} THEN paid ELSE 0 END),0) AS paid, "
            f"COALESCE(SUM(CASE WHEN {db.NOT_VOIDED} THEN due ELSE 0 END),0) AS due "
            f"FROM receipts WHERE {where}",
            args,
        ).fetchone()
        total_n, tot_net, tot_paid, tot_due = (
            agg["n"],
            agg["net"],
            agg["paid"],
            agg["due"],
        )
        cur = db.currency(self.con)
        self.table.setRowCount(0)
        self._ids = []
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            self._ids.append(r["id"])
            self.table.setItem(i, 0, QTableWidgetItem(r["lab_no"] or ""))
            self.table.setItem(i, 1, QTableWidgetItem((r["received_at"] or "")[:16]))
            self.table.setItem(i, 2, QTableWidgetItem(r["patient_name"] or ""))
            self.table.setItem(i, 3, QTableWidgetItem(r["dr_name"] or ""))
            self.table.setItem(i, 4, num_item(f"{r['net_amount']:,.0f}"))
            self.table.setItem(i, 5, num_item(f"{r['paid']:,.0f}"))
            self.table.setItem(
                i, 6, num_item(f"{r['due']:,.0f}", "#c0392b" if r["due"] else None)
            )
            voided = "voided" in r.keys() and r["voided"]
            self.table.setItem(i, 7, status_badge(r["status"] or "", voided))
        capped = total_n > len(rows)
        shown = (
            f"Showing first {len(rows):,} of {total_n:,}"
            if capped
            else f"{total_n:,} receipt(s)"
        )
        self.sub.setText(shown)
        self.sub.show()
        self.summary.setText(
            f"{shown}   •   Net {money(tot_net, cur)}   •   "
            f"Paid {money(tot_paid, cur)}   •   Due {money(tot_due, cur)}"
        )
        self._update_buttons()

    def _selected_id(self) -> int | None:
        return selected_id(self.table, self._ids)

    def _update_buttons(self) -> None:
        rid = self._selected_id()
        on = rid is not None
        voided = False
        if on:
            row = self.con.execute(
                "SELECT due, status, voided FROM receipts WHERE id=?", (rid,)
            ).fetchone()
            voided = bool("voided" in row.keys() and row["voided"])
        active = on and not voided  # a voided bill is read-only
        for b in self._receipt_btns:
            b.setEnabled(active)
        if active:
            ready = (row["status"] or "") in REPORT_READY
            for b in self._report_btns:
                b.setEnabled(ready)
                b.setToolTip("" if ready else "Report not ready yet (results pending)")
            self.print_plain_btn.setEnabled(ready and self._is_admin)
            self.pay_btn.setEnabled(bool(row["due"] and row["due"] > 0))
            delivered = (row["status"] or "") == "delivered"
            self.deliver_btn.setEnabled(ready and not delivered)
            # a bill is frozen the moment its report is ready — no one may edit it then
            self.edit_btn.setEnabled(self._can_edit_bill and not ready)
            self.void_btn.setEnabled(True)
        else:
            for b in (
                *self._report_btns,
                self.print_plain_btn,
                self.pay_btn,
                self.deliver_btn,
                self.edit_btn,
                self.void_btn,
            ):
                b.setEnabled(False)
            # a voided bill is read-only, but an admin may still preview it
            if voided and self._is_admin:
                self.prev_rcpt_btn.setEnabled(True)
                if (row["status"] or "") in REPORT_READY:
                    self.prev_rpt_btn.setEnabled(True)

    def _show_row_menu(self, pos) -> None:
        """Right-click menu on a receipt row — mirrors the toolbar exactly."""
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        self.table.selectRow(idx.row())
        groups = (
            self._receipt_btns,
            self._report_btns,
            (self.pay_btn, self.deliver_btn, self.edit_btn, self.void_btn),
        )
        menu = QMenu(self)
        first = True
        for btns in groups:
            shown = [b for b in btns if b.isVisibleTo(self)]
            if not shown:
                continue
            if not first:
                menu.addSeparator()
            first = False
            for b in shown:
                act = menu.addAction(b.text())
                act.setEnabled(b.isEnabled())
                act.triggered.connect(b.click)
        if not menu.isEmpty():
            menu.exec(self.table.viewport().mapToGlobal(pos))

    def _lab_no(self, rid: int) -> str:
        r = self.con.execute(
            "SELECT lab_no FROM receipts WHERE id=?", (rid,)
        ).fetchone()
        return r["lab_no"] if r and r["lab_no"] else f"#{rid}"

    def export_csv(self) -> None:
        import csv

        path, _ = QFileDialog.getSaveFileName(
            self, "Export receipts to CSV", "receipts.csv", "CSV (*.csv)"
        )
        if not path:
            return

        def _safe(item: QTableWidgetItem | None) -> str:
            # neutralise spreadsheet formula injection (leading = + - @ tab CR)
            s = item.text() if item else ""
            return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

        try:
            cols = self.table.columnCount()
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(
                    [_safe(self.table.horizontalHeaderItem(c)) for c in range(cols)]
                )
                for r in range(self.table.rowCount()):
                    w.writerow([_safe(self.table.item(r, c)) for c in range(cols)])
            db.log_audit(
                self.con,
                self.user["username"],
                "exported_csv",
                f"receipts ({self.table.rowCount()} rows) → {path}",
            )
            toast_info(
                self, "Export", f"Exported {self.table.rowCount()} rows to:\n{path}"
            )
        except Exception as e:
            toast_warn(self, "Export", f"Could not export:\n{e}")
