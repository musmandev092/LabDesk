"""Receipts: history of all saved receipts — search, reprint, take due payment."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import db, render, report
from ..constants import PAYMENT_METHODS
from ..roles import can
from . import tasks, wa
from .widgets import (
    FlowLayout,
    fit_to_screen,
    like_term,
    money,
    muted,
    num_item,
    page_header,
    selected_id,
    status_badge,
)

# a report can be previewed/printed only once results are in
REPORT_READY = ("reported", "delivered")


class _PreviewDialog(QDialog):
    """In-app preview of a report/receipt — the document rendered to image pages
    (native Qt, no QtPdf viewer) shown in a scroll area."""

    def __init__(self, pages, parent=None, title: str = "Preview") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        fit_to_screen(self, 840, 1040)  # scroll area below; clamp so it fits short screens
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        host = QWidget()
        vl = QVBoxLayout(host)
        vl.setContentsMargins(12, 12, 12, 12)
        vl.setSpacing(12)
        for img in pages:
            lbl = QLabel()
            lbl.setAlignment(Qt.AlignHCenter)
            # scale each A4 page to a comfortable on-screen width, keeping aspect
            pm = QPixmap.fromImage(img).scaledToWidth(780, Qt.SmoothTransformation)
            lbl.setPixmap(pm)
            vl.addWidget(lbl)
        scroll.setWidget(host)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll)


class _EditReceiptDialog(QDialog):
    """Edit a saved bill: add/remove tests, adjust discount, amount paid and
    payment method. A test that already has results entered cannot be removed
    (so a finalised result can never be orphaned)."""

    def __init__(self, con, rec, currency: str = "Rs.", parent=None) -> None:
        super().__init__(parent)
        self.con = con
        self.rec = rec
        self.cur = currency
        self.setWindowTitle(f"Edit bill {rec['lab_no'] or ''}")
        self.setMinimumWidth(480)

        # working copy of the line items; item_id is None for a freshly-added test
        self.items: list[dict] = []
        for it in con.execute(
            "SELECT id, test_id, test_name, charge FROM receipt_items WHERE receipt_id=? ORDER BY id",
            (rec["id"],),
        ):
            self.items.append(
                {
                    "item_id": it["id"],
                    "test_id": it["test_id"],
                    "name": it["test_name"],
                    "charge": it["charge"] or 0.0,
                    "has_results": self._has_results(it["id"]),
                }
            )
        self._removed: list = []  # item_ids of existing rows the user removed

        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"Patient: <b>{rec['patient_name'] or ''}</b>"))

        # current tests
        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["Test", "Charge", ""])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        th = self.tbl.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.Stretch)
        th.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        th.setSectionResizeMode(2, QHeaderView.Fixed)
        self.tbl.setColumnWidth(2, 44)
        # Taller so a typical multi-test bill shows its rows cleanly instead of
        # cramming ~1.5 rows behind a scrollbar; longer bills scroll past ~7 rows.
        self.tbl.setMinimumHeight(180)
        self.tbl.setMaximumHeight(300)
        root.addWidget(self.tbl)

        # add a test (by name or number)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Add test by name or number…")
        self.search.textChanged.connect(self._search_tests)
        self.results = QListWidget()
        self.results.setMaximumHeight(120)
        self.results.hide()
        self.results.itemActivated.connect(self._add_from_list)
        self.results.itemDoubleClicked.connect(self._add_from_list)
        root.addWidget(self.search)
        root.addWidget(self.results)

        # money
        form = QFormLayout()
        self.sub_lbl = QLabel()
        form.addRow("Subtotal", self.sub_lbl)
        self.discount = QDoubleSpinBox()
        self.discount.setMaximum(100)
        self.discount.setSuffix(" %")
        self.discount.setValue(rec["discount_pct"] or 0)
        self.discount.valueChanged.connect(self._recompute)
        form.addRow("Discount", self.discount)
        self.net_lbl = QLabel()
        self.net_lbl.setStyleSheet("font-weight:800;color:#0a5f67;")
        form.addRow("Net payable", self.net_lbl)
        self.paid = QDoubleSpinBox()
        self.paid.setMaximum(1_000_000)
        self.paid.setPrefix(f"{currency} ")
        self.paid.setValue(rec["paid"] or 0)
        self.paid.valueChanged.connect(self._recompute)
        form.addRow("Paid", self.paid)
        self.method = QComboBox()
        self.method.addItems(PAYMENT_METHODS)
        if rec["payment_method"]:
            self.method.setCurrentText(rec["payment_method"])
        form.addRow("Payment method", self.method)
        self.due_lbl = QLabel()
        self.due_lbl.setStyleSheet("font-weight:800;color:#c0392b;")
        form.addRow("Due", self.due_lbl)
        root.addLayout(form)

        btns = QHBoxLayout()
        ok = QPushButton("Save changes")
        ok.clicked.connect(self._try_accept)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

        self._refresh_table()
        self._recompute()

    # ---- tests -----------------------------------------------------
    def _has_results(self, item_id) -> bool:
        """True if any result/culture row exists for this line item."""
        for tbl in ("results", "cultures"):
            if self.con.execute(
                f"SELECT 1 FROM {tbl} WHERE receipt_item_id=? LIMIT 1", (item_id,)
            ).fetchone():
                return True
        return False

    def _refresh_table(self) -> None:
        self.tbl.setRowCount(0)
        for i, c in enumerate(self.items):
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            self.tbl.setItem(r, 0, QTableWidgetItem(c["name"] or ""))
            ci = QTableWidgetItem(f"{c['charge']:,.0f}")
            ci.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl.setItem(r, 1, ci)
            btn = QPushButton("✕")
            btn.setFixedSize(26, 24)
            btn.setCursor(Qt.PointingHandCursor)
            if c["has_results"]:
                btn.setEnabled(False)
                btn.setToolTip("Results already entered — this test can't be removed")
                btn.setStyleSheet(
                    "QPushButton{background:transparent;color:#8a949c;"
                    "border:1px solid #3a4a56;border-radius:6px;padding:0;}"
                )
            else:
                btn.setToolTip("Remove this test")
                btn.setStyleSheet(
                    "QPushButton{background:transparent;color:#c0392b;border:1px solid #e3b4ae;"
                    "border-radius:6px;font-weight:bold;padding:0;}"
                    "QPushButton:hover{background:#c0392b;color:white;border-color:#c0392b;}"
                )
                btn.clicked.connect(lambda _=False, idx=i: self._remove(idx))
            # center the small button in the cell
            wrap = QWidget()
            wl = QHBoxLayout(wrap)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.addWidget(btn, 0, Qt.AlignCenter)
            self.tbl.setCellWidget(r, 2, wrap)

    def _remove(self, idx: int) -> None:
        it = self.items[idx]
        if it["has_results"]:
            return
        if it["item_id"] is not None:
            self._removed.append(it["item_id"])
        del self.items[idx]
        self._refresh_table()
        self._recompute()

    def _search_tests(self, text: str) -> None:
        text = (text or "").strip()
        self.results.clear()
        if len(text) < 1:
            self.results.hide()
            return
        like = like_term(text)
        rows = self.con.execute(
            "SELECT id,name,charges,legacy_no FROM tests WHERE active=1 "
            "AND (name LIKE ? ESCAPE '\\' OR CAST(legacy_no AS TEXT) LIKE ? ESCAPE '\\') "
            "ORDER BY name LIMIT 30",
            (like, like),
        ).fetchall()
        for r in rows:
            no = f"#{r['legacy_no']}  " if r["legacy_no"] else ""
            item = QListWidgetItem(f"{no}{r['name']}   —   {self.cur} {r['charges']:,.0f}")
            item.setData(Qt.UserRole, (r["id"], r["name"], r["charges"]))
            self.results.addItem(item)
        self.results.setVisible(bool(rows))

    def _add_from_list(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        tid, name, charge = data
        if any(c["test_id"] == tid for c in self.items):
            return  # already on the bill
        self.items.append(
            {
                "item_id": None,
                "test_id": tid,
                "name": name,
                "charge": charge or 0.0,
                "has_results": False,
            }
        )
        self.search.clear()
        self.results.clear()
        self.results.hide()
        self._refresh_table()
        self._recompute()

    # ---- money -----------------------------------------------------
    def _subtotal(self) -> float:
        return round(sum(c["charge"] for c in self.items), 2)

    def _net(self) -> float:
        # round to whole paisa so a discount can't leave a sub-cent "phantom due"
        sub = self._subtotal()
        return round(max(0.0, sub - sub * self.discount.value() / 100.0), 2)

    def _recompute(self) -> None:
        self.sub_lbl.setText(money(self._subtotal(), self.cur))
        net = self._net()
        due = round(max(0.0, net - self.paid.value()), 2)
        self.net_lbl.setText(money(net, self.cur))
        self.due_lbl.setText(money(due, self.cur))

    def _try_accept(self) -> None:
        if not self.items:
            QMessageBox.warning(self, "Edit bill", "A bill must have at least one test.")
            return
        self.accept()

    def values(self) -> dict:
        net = self._net()
        paid = round(self.paid.value(), 2)
        return {
            "subtotal": self._subtotal(),
            "discount_pct": self.discount.value(),
            "net_amount": net,
            "paid": paid,
            "due": round(max(0.0, net - paid), 2),
            "payment_method": self.method.currentText(),
            "removed_item_ids": list(self._removed),
            "added": [c for c in self.items if c["item_id"] is None],
        }


class ReceiptsPage(QWidget):
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
        self.pay_btn = _btn("Receive due", self.receive_due)
        self.deliver_btn = _btn("Mark delivered", self.mark_delivered)
        self.edit_btn = _btn("Edit bill", self.edit_receipt)
        self.void_btn = _btn("Void", self.void_receipt)
        self._report_btns = (
            self.prev_rpt_btn,
            self.print_rpt_btn,
            self.pdf_rpt_btn,
            self.wa_rpt_btn,
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
            self.table.setItem(i, 6, num_item(f"{r['due']:,.0f}", "#c0392b" if r["due"] else None))
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
            ready = (row["status"] or "") in REPORT_READY  # report only when results are in
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
        r = self.con.execute("SELECT lab_no FROM receipts WHERE id=?", (rid,)).fetchone()
        return r["lab_no"] if r and r["lab_no"] else f"#{rid}"

    def _preview(self, kind: str) -> None:
        """kind: 'report' or 'receipt'. Render to image pages natively and show
        them in the preview dialog — no PDF temp file, no QtPdf viewer."""
        rid = self._selected_id()
        if rid is None:
            return
        title = "Receipt preview" if kind == "receipt" else "Report preview"
        labno = self._lab_no(rid)
        try:
            pages = render.render_pages(self.con, rid, kind)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Preview", f"Could not build preview:\n{e}")
            return
        db.log_audit(self.con, self.user["username"], "previewed_" + kind, labno)
        _PreviewDialog(pages, self, title).exec()

    def preview(self) -> None:
        self._preview("report")

    def preview_receipt(self) -> None:
        self._preview("receipt")

    def _send_whatsapp(self, kind: str) -> None:
        rid = self._selected_id()
        if rid is None:
            return
        clicked = self.wa_rcpt_btn if kind == "receipt" else self.wa_rpt_btn
        # runs on a background thread; disables both WhatsApp buttons until done
        wa.send_async(
            self,
            self.con,
            kind,
            rid,
            clicked=clicked,
            lock_buttons=(self.wa_rcpt_btn, self.wa_rpt_btn),
            on_done=lambda ok, m: db.log_audit(
                self.con,
                self.user["username"],
                "whatsapp_" + kind,
                ("sent" if ok else "failed") + f" — receipt {rid}",
            ),
        )

    def whatsapp_receipt(self) -> None:
        self._send_whatsapp("receipt")

    def whatsapp_report(self) -> None:
        self._send_whatsapp("report")

    def _print(self, kind: str) -> None:
        """Render straight onto the printer (native, vector — no PDF round-trip)."""
        rid = self._selected_id()
        if rid is None:
            return
        title = "Print Receipt" if kind == "receipt" else "Print Report"
        printer = db.get_setting(self.con, "default_printer", "")
        labno = self._lab_no(rid)
        try:
            report.print_doc(self.con, rid, kind, self, title, printer)
            db.log_audit(self.con, self.user["username"], "printed_" + kind, labno)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Print", f"Could not print:\n{e}")

    def reprint(self) -> None:
        self._print("receipt")

    def print_report(self) -> None:
        self._print("report")

    def _save_pdf(self, kind: str) -> None:
        """Export the receipt or report to a PDF chosen by the user (background)."""
        rid = self._selected_id()
        if rid is None:
            return
        labno = self._lab_no(rid)
        stem = labno if not labno.startswith("#") else f"receipt_{rid}"
        default = f"{stem}-{kind}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, f"Save {kind} PDF", default, "PDF (*.pdf)")
        if not path:
            return
        export = report.export_receipt_pdf if kind == "receipt" else report.export_report_pdf
        clicked = self.pdf_rcpt_btn if kind == "receipt" else self.pdf_rpt_btn

        def done(ok: bool, result) -> None:
            if ok:
                db.log_audit(
                    self.con, self.user["username"], "exported_pdf", f"{labno} {kind} → {path}"
                )
                QMessageBox.information(self, "PDF", f"Saved:\n{path}")
            else:
                QMessageBox.warning(self, "PDF", f"Could not save the PDF:\n{result}")

        tasks.run_in_background(
            self, lambda con: export(con, rid, path), done, clicked=clicked, busy_text="Saving…"
        )

    def save_receipt_pdf(self) -> None:
        self._save_pdf("receipt")

    def save_report_pdf(self) -> None:
        self._save_pdf("report")

    def receive_due(self) -> None:
        rid = self._selected_id()
        if rid is None:
            return
        r = self.con.execute("SELECT lab_no, due FROM receipts WHERE id=?", (rid,)).fetchone()
        if not r or not r["due"] or r["due"] <= 0:
            return
        cur = db.currency(self.con)
        # prompt for the actual amount received (supports partial payments; cannot exceed due)
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
        db.receive_due(self.con, rid, amount, self.user["username"])
        self.refresh()

    def mark_delivered(self) -> None:
        rid = self._selected_id()
        if rid is None:
            return
        r = self.con.execute("SELECT lab_no, status FROM receipts WHERE id=?", (rid,)).fetchone()
        if not r or r["status"] not in REPORT_READY:
            return
        self.con.execute(
            "UPDATE receipts SET status='delivered', delivered_at=datetime('now','localtime'), "
            "delivered_by=? WHERE id=?",
            (self.user["username"], rid),
        )
        self.con.commit()
        db.log_audit(self.con, self.user["username"], "report_delivered", r["lab_no"] or f"#{rid}")
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
            return  # once reported/delivered the bill is frozen for everyone (incl. admin)
        cur = db.currency(self.con)
        dlg = _EditReceiptDialog(self.con, rec, cur, self)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        old_paid = rec["paid"] or 0.0
        delta = v["paid"] - old_paid
        try:
            # remove deleted line items — guarded to never drop one that has
            # results/cultures (defence in depth; the dialog already blocks it)
            for iid in v["removed_item_ids"]:
                self.con.execute(
                    "DELETE FROM receipt_items WHERE id=? AND receipt_id=? "
                    "AND id NOT IN (SELECT receipt_item_id FROM results) "
                    "AND id NOT IN (SELECT receipt_item_id FROM cultures WHERE receipt_item_id IS NOT NULL)",
                    (iid, rid),
                )
            # add newly-picked tests
            for a in v["added"]:
                self.con.execute(
                    "INSERT INTO receipt_items(receipt_id,test_id,test_name,charge) VALUES (?,?,?,?)",
                    (rid, a["test_id"], a["name"], a["charge"]),
                )
            self.con.execute(
                "UPDATE receipts SET subtotal=?, discount_pct=?, less=?, net_amount=?, paid=?, due=?, "
                "payment_method=? WHERE id=?",
                (
                    v["subtotal"],
                    v["discount_pct"],
                    v["subtotal"] - v["net_amount"],
                    v["net_amount"],
                    v["paid"],
                    v["due"],
                    v["payment_method"],
                    rid,
                ),
            )
            # adding a test to an already-finalised bill makes the report incomplete
            # again → send it back to the worklist as in-progress.
            if v["added"] and (rec["status"] or "") in REPORT_READY:
                self.con.execute("UPDATE receipts SET status='in_progress' WHERE id=?", (rid,))
            # keep the ledger balanced for any change in money actually collected
            if abs(delta) > 1e-9:
                if delta > 0:
                    self.con.execute(
                        "INSERT INTO ledger(kind,ref_id,detail,credit,date) "
                        "VALUES ('adjustment',?,?,?,date('now','localtime'))",
                        (rid, f"Bill edit {rec['lab_no']} — extra paid", delta),
                    )
                else:
                    self.con.execute(
                        "INSERT INTO ledger(kind,ref_id,detail,debit,date) "
                        "VALUES ('adjustment',?,?,?,date('now','localtime'))",
                        (rid, f"Bill edit {rec['lab_no']} — refund", -delta),
                    )
            self.con.commit()
        except Exception as e:
            try:
                self.con.rollback()
            except Exception:
                pass
            QMessageBox.warning(self, "Edit bill", f"Could not save the changes:\n{e}")
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
            QMessageBox.warning(self, "Void receipt", "A reason is required to void a receipt.")
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
        self.con.execute(
            "UPDATE receipts SET voided=1, void_reason=?, voided_at=datetime('now','localtime'), "
            "voided_by=?, due=0 WHERE id=?",
            (reason.strip(), self.user["username"], rid),
        )
        if r["paid"]:  # reversing ledger entry keeps ledger-based accounting balanced
            self.con.execute(
                "INSERT INTO ledger(kind,ref_id,detail,debit,date) "
                "VALUES ('void',?,?,?,date('now','localtime'))",
                (rid, f"Void {r['lab_no']} — {reason.strip()[:60]}", r["paid"]),
            )
        self.con.commit()
        db.log_audit(
            self.con,
            self.user["username"],
            "receipt_voided",
            f"{r['lab_no']} — {reason.strip()[:80]}",
        )
        self.refresh()

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
                w.writerow([_safe(self.table.horizontalHeaderItem(c)) for c in range(cols)])
                for r in range(self.table.rowCount()):
                    w.writerow([_safe(self.table.item(r, c)) for c in range(cols)])
            db.log_audit(
                self.con,
                self.user["username"],
                "exported_csv",
                f"receipts ({self.table.rowCount()} rows) → {path}",
            )
            QMessageBox.information(
                self, "Export", f"Exported {self.table.rowCount()} rows to:\n{path}"
            )
        except Exception as e:
            QMessageBox.warning(self, "Export", f"Could not export:\n{e}")
