"""Test search + cart management for reception, split out of ReceptionPage.

A mixin (runs on the composed ReceptionPage instance). update_specimen_options and
statusBar_message stay on the page (they use a module-local helper / are shared);
everything else cart-related lives here. Pure reorganisation, no behavior change.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QListWidgetItem,
    QMenu,
    QPushButton,
    QTableWidgetItem,
)

from .. import db
from ..application import billing
from .widgets import money


class ReceptionCartMixin:
    def _hint_item(self, text: str) -> QListWidgetItem:
        it = QListWidgetItem(text)
        it.setFlags(Qt.NoItemFlags)
        it.setForeground(Qt.gray)
        return it

    def search_tests(self, text: str | None = None) -> None:
        text = (self.test_search.text() if text is None else text).strip()
        self.results.clear()
        cur = db.currency(self.con)
        if len(text) < 1:
            self.results.addItem(
                self._hint_item(
                    "Start typing a test name or number above to see matches…"
                )
            )
            return
        like = f"%{text}%"
        # match on the test name OR its (legacy) test number — staff often know
        # tests by the number from the old system.
        rows = self.con.execute(
            "SELECT id,name,charges,legacy_no FROM tests WHERE active=1 "
            "AND (name LIKE ? OR CAST(legacy_no AS TEXT) LIKE ?) "
            "ORDER BY name LIMIT 40",
            (like, like),
        ).fetchall()
        if not rows:
            self.results.addItem(self._hint_item(f"No tests match “{text}”."))
            return
        for r in rows:
            no = f"#{r['legacy_no']}  " if r["legacy_no"] else ""
            it = QListWidgetItem(f"{no}{r['name']}   —   {cur} {r['charges']:,.0f}")
            it.setData(Qt.UserRole, (r["id"], r["name"], r["charges"]))
            self.results.addItem(it)

    def _show_panel_menu(self) -> None:
        """Drop down the saved panels; picking one adds all its tests to the cart."""
        panels = db.list_panels(self.con)
        menu = QMenu(self)
        if not panels:
            act = menu.addAction("No panels yet — create them in Test Catalog")
            act.setEnabled(False)
        else:
            for p in panels:
                menu.addAction(
                    p["name"],
                    lambda _=False, pid=p["id"], nm=p["name"]: self._add_panel(pid, nm),
                )
        menu.exec(self.panel_btn.mapToGlobal(self.panel_btn.rect().bottomLeft()))

    def _add_panel(self, panel_id: int, name: str) -> None:
        rows = db.panel_tests(self.con, panel_id)
        added = 0
        for r in rows:
            if any(c["test_id"] == r["id"] for c in self.cart):
                continue
            self.cart.append(
                {"test_id": r["id"], "name": r["name"], "charge": r["charges"]}
            )
            added += 1
        self.refresh_cart()
        skipped = len(rows) - added
        msg = f"Added {added} test(s) from “{name}”."
        if skipped:
            msg += f" {skipped} already in the cart."
        self.statusBar_message(msg)

    def _add_top_test(self) -> None:
        """Enter in the test search box adds the first matching test."""
        for i in range(self.results.count()):
            it = self.results.item(i)
            if it.data(Qt.UserRole):
                self.add_from_list(it)
                self.test_search.clear()
                return

    def add_from_list(self, item: QListWidgetItem | None) -> None:
        # itemActivated can fire with no item (Enter on a focused empty list, esp. Wayland)
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return  # hint / empty-state row
        tid, name, charge = data
        if any(c["test_id"] == tid for c in self.cart):
            return  # no duplicates
        self.cart.append({"test_id": tid, "name": name, "charge": charge})
        self.test_search.clear()
        self.search_tests("")
        self.refresh_cart()

    def remove_cart(self, idx: int) -> None:
        del self.cart[idx]
        self.refresh_cart()

    def refresh_cart(self) -> None:
        self.cart_table.setRowCount(0)
        for i, c in enumerate(self.cart):
            r = self.cart_table.rowCount()
            self.cart_table.insertRow(r)
            self.cart_table.setItem(r, 0, QTableWidgetItem(c["name"]))
            charge_it = QTableWidgetItem(f"{c['charge']:,.0f}")
            charge_it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.cart_table.setItem(r, 1, charge_it)
            btn = QPushButton("✕")
            btn.setToolTip("Remove this test")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedSize(28, 26)
            btn.setStyleSheet(
                "QPushButton{background:transparent;color:#c0392b;border:1px solid #e3b4ae;"
                "border-radius:6px;font-weight:bold;padding:0;}"
                "QPushButton:hover{background:#c0392b;color:white;border-color:#c0392b;}"
            )
            btn.clicked.connect(lambda _=False, idx=i: self.remove_cart(idx))
            self.cart_table.setCellWidget(r, 2, btn)
        self.update_specimen_options()
        self.recompute()

    def recompute(self) -> None:
        cur = db.currency(self.con)
        totals = billing.compute_bill_totals(
            self.cart, self.discount.value(), self.paid.value()
        )
        sub = totals["subtotal"]
        net = totals["net"]
        due = totals["due"]
        change = totals["change"]
        self.subtotal.setText(money(sub, cur))
        self.net.setText(money(net, cur))
        self.due.setText(money(due, cur))
        # show the change-to-return row only when the customer overpaid (due == 0)
        self.change.setText(money(change, cur))
        self.change_lbl.setVisible(change > 0)
        self.change.setVisible(change > 0)
        self._net = net
        self._sub = sub
