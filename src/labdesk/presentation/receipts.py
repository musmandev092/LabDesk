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

        # receipt (bill) actions — available as soon as a saved receipt is selected
        self.prev_rcpt_btn = _btn("Preview receipt", self.preview_receipt)
        self.print_rcpt_btn = _btn("Print receipt", self.reprint)
        self.pdf_rcpt_btn = _btn("Save receipt PDF", self.save_receipt_pdf)
        self.wa_rcpt_btn = _btn("WhatsApp receipt", self.whatsapp_receipt)
        # report actions — only once results are entered (report ready)
        self.prev_rpt_btn = _btn("Preview report", self.preview)
        self.print_rpt_btn = _btn("Print report", self.print_report)
        self.pdf_rpt_btn = _btn("Save report PDF", self.save_report_pdf)
        self.wa_rpt_btn = _btn("WhatsApp report", self.whatsapp_report)
        self.verify_rpt_btn = _btn("Verify report", self.verify_report)
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

        # FlowLayout so this 12-button action bar WRAPS to more rows on narrow
        # windows instead of forcing a ~1870px minimum (which made the whole app
        # unusable below ~2100px wide — wider than most laptop screens).
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
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setFrameShadow(QFrame.Sunken)
        tb.addWidget(sep2)
        tb.addWidget(self.pay_btn)
        tb.addWidget(self.deliver_btn)
        # editing the bill (discount/paid/method) and voiding are manager/admin actions
        self._can_edit_bill = can(self.user["role"], "apply_discount")
        # once a bill/report is delivered, only an admin may edit it — a technician
        # (manager) can edit only while it is still pending/reported.
        self._is_admin = can(self.user["role"], "manage_users")
        if self._can_edit_bill:
            tb.addWidget(self.edit_btn)
        else:
            self.edit_btn.hide()
        if can(self.user["role"], "delete"):
            tb.addWidget(self.void_btn)  # voiding a bill is a manager/admin action
        else:
            self.void_btn.hide()
        root.addLayout(tb)

        # filters
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
        # calendar date-range filter (optional — enabled by its checkbox)
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
        # Double-clicking a row does NOT print — printing is an explicit toolbar
        # action so a report is never sent to the printer by accident.
        # Right-click a row for the same actions as the toolbar.
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_row_menu)
        root.addWidget(self.table, 1)

        self.summary = muted("")
        root.addWidget(self.summary)

    # ---------------------------------------------------------------
    def _date_edit(self) -> QDateEdit:
        """A calendar-popup date editor, defaulting to today, disabled until the
        'By date' filter is switched on."""
        d = QDateEdit()
        d.setCalendarPopup(True)
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
            self.use_dates.setChecked(False)  # toggles off → disables the editors
        self.refresh()

    def _date_clause(self) -> tuple[str | None, list]:
        """SQL fragment + args for the active date-range filter, else (None, [])."""
        if not self.use_dates.isChecked():
            return None, []
        d1 = self.date_from.date()
        d2 = self.date_to.date()
        if d1 > d2:  # tolerate a reversed range
            d1, d2 = d2, d1
        # half-open upper bound (to-date + 1 day) so the whole 'to' day is included
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

    def refresh(self) -> None:
        q = like_term(self.search.text())
        sql = (
            "SELECT * FROM receipts WHERE (COALESCE(patient_name,'') LIKE ? ESCAPE '\\' "
            "OR COALESCE(lab_no,'') LIKE ? ESCAPE '\\' OR COALESCE(mr_no,'') LIKE ? ESCAPE '\\')"
        )
        args = [q, q, q]
        st = self.status.currentData()
        if st and st != "All":
            sql += " AND status=?"
            args.append(st)
        if self.today_only.isChecked():
            sql += f" AND {db.RECEIVED_TODAY}"
        dc, dargs = self._date_clause()
        if dc:
            sql += f" AND {dc}"
            args += dargs
        if self.dues_only.isChecked():
            sql += f" AND due>0.005 AND {db.NOT_VOIDED}"
        sql += " ORDER BY id DESC LIMIT 1000"
        rows = self.con.execute(sql, args).fetchall()
        cur = db.currency(self.con)
        self.table.setRowCount(0)
        self._ids = []
        tot_net = tot_paid = tot_due = 0.0
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
            if not voided:  # voided bills don't count toward the money totals
                tot_net += r["net_amount"] or 0
                tot_paid += r["paid"] or 0
                tot_due += r["due"] or 0
        self.sub.setText(f"{len(rows)} receipt(s)")
        self.sub.show()
        self.summary.setText(
            f"Showing {len(rows)} receipt(s)   •   Net {money(tot_net, cur)}   •   "
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
            ready = (
                row["status"] or ""
            ) in REPORT_READY  # report only when results are in
            for b in self._report_btns:
                b.setEnabled(ready)
                b.setToolTip("" if ready else "Report not ready yet (results pending)")
            self.pay_btn.setEnabled(bool(row["due"] and row["due"] > 0))
            delivered = (row["status"] or "") == "delivered"
            self.deliver_btn.setEnabled(ready and not delivered)
            # A bill is FROZEN the moment its report is ready (reported/delivered):
            # no one — not even an admin — may change its charges after results exist.
            # Only pending / in-progress bills can be edited.
            self.edit_btn.setEnabled(self._can_edit_bill and not ready)
            self.void_btn.setEnabled(True)
        else:
            for b in (
                *self._report_btns,
                self.pay_btn,
                self.deliver_btn,
                self.edit_btn,
                self.void_btn,
            ):
                b.setEnabled(False)
            # A voided bill is read-only — but an admin may still PREVIEW the
            # cancelled receipt (and report, if results exist) on screen for
            # reference/audit. Nothing that emits or alters it stays enabled:
            # no print, PDF, WhatsApp, edit, void, pay or deliver.
            if voided and self._is_admin:
                self.prev_rcpt_btn.setEnabled(True)
                if (row["status"] or "") in REPORT_READY:
                    self.prev_rpt_btn.setEnabled(True)

    def _show_row_menu(self, pos) -> None:
        """Right-click menu on a receipt row. Mirrors the toolbar exactly: same
        labels, same enabled/disabled (greyed = not available yet) and the same
        role-based visibility — the buttons stay the single source of truth."""
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return  # no menu on empty space
        # select the right-clicked row so the actions (and button states) target it
        self.table.selectRow(idx.row())
        groups = (
            self._receipt_btns,
            self._report_btns,
            (self.pay_btn, self.deliver_btn, self.edit_btn, self.void_btn),
        )
        menu = QMenu(self)
        first = True
        for btns in groups:
            shown = [b for b in btns if b.isVisibleTo(self)]  # respects role hiding
            if not shown:
                continue
            if not first:
                menu.addSeparator()
            first = False
            for b in shown:
                act = menu.addAction(b.text())
                act.setEnabled(b.isEnabled())  # greyed when the action isn't available
                act.triggered.connect(b.click)
        if not menu.isEmpty():
            menu.exec(self.table.viewport().mapToGlobal(pos))

    # ---------------------------------------------------------------
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
            # neutralise spreadsheet formula injection: a cell a spreadsheet would
            # treat as a formula (leading = + - @ tab CR) is prefixed with a quote
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
