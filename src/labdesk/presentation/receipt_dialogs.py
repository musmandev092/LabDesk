"""Dialogs used by the Receipts page — extracted from receipts.py to keep that
page focused. ``_PreviewDialog`` shows a rendered document as image pages;
``_EditReceiptDialog`` edits a saved bill (tests, discount, paid, method)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..application import billing
from ..constants import PAYMENT_METHODS
from .widgets import fit_to_screen, like_term, money, toast_warn


class _PreviewDialog(QDialog):
    """In-app preview of a report/receipt — the document rendered to image pages
    (native Qt, no QtPdf viewer) shown in a scroll area."""

    def __init__(self, pages, parent=None, title: str = "Preview") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        fit_to_screen(
            self, 840, 1040
        )  # scroll area below; clamp so it fits short screens
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
            item = QListWidgetItem(
                f"{no}{r['name']}   —   {self.cur} {r['charges']:,.0f}"
            )
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
        # exact integer-paisa math so a discount can't leave a sub-cent "phantom due"
        return billing.compute_bill_totals(
            self.items, self.discount.value(), self.paid.value()
        )["net"]

    def _recompute(self) -> None:
        totals = billing.compute_bill_totals(
            self.items, self.discount.value(), self.paid.value()
        )
        self.sub_lbl.setText(money(totals["subtotal"], self.cur))
        self.net_lbl.setText(money(totals["net"], self.cur))
        self.due_lbl.setText(money(totals["due"], self.cur))

    def _try_accept(self) -> None:
        if not self.items:
            toast_warn(self, "Edit bill", "A bill must have at least one test.")
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
