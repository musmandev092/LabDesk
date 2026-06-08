"""Accounts: income/expense summary, expense entry, outstanding dues."""
from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget, QTableWidgetItem,
    QLineEdit, QDoubleSpinBox, QPushButton, QHeaderView, QLabel, QGridLayout,
    QDateEdit, QInputDialog, QSizePolicy,
)

from .widgets import stat_card, money, page_header, field_label, num_item, selected_id
from .. import db


class AccountsPage(QWidget):
    def __init__(self, con, user):
        super().__init__()
        self.con = con
        self.user = user
        self._due_ids = []   # parallel to due_table rows; filled by refresh_dues
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header, _ = page_header("Accounts", "Income, expenses and outstanding dues")
        root.addWidget(header)

        tabs = QTabWidget()
        tabs.addTab(self._summary_tab(), "Summary")
        tabs.addTab(self._expenses_tab(), "Expenses")
        tabs.addTab(self._dues_tab(), "Outstanding Dues")
        root.addWidget(tabs, 1)
        self.tabs = tabs

    # ---- summary ----
    def _summary_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        rng = QHBoxLayout()
        self.from_date = QDateEdit(QDate.currentDate().addDays(-30)); self.from_date.setCalendarPopup(True)
        self.from_date.setDisplayFormat("dd MMM yyyy")
        self.to_date = QDateEdit(QDate.currentDate()); self.to_date.setCalendarPopup(True)
        self.to_date.setDisplayFormat("dd MMM yyyy")
        go = QPushButton("Apply"); go.clicked.connect(self.refresh_summary)
        rng.addWidget(QLabel("From")); rng.addWidget(self.from_date)
        rng.addWidget(QLabel("To")); rng.addWidget(self.to_date)
        rng.addWidget(go); rng.addStretch(1)
        lay.addLayout(rng)
        grid = QGridLayout(); grid.setSpacing(12)
        self.c_income = stat_card("Income (paid)", "Rs. 0", "#1f9d55")
        self.c_expense = stat_card("Expenses", "Rs. 0", "#c0392b")
        self.c_net = stat_card("Net", "Rs. 0", "#0a5f67")
        self.c_due = stat_card("Outstanding (all-time)", "Rs. 0", "#b9770e")
        grid.addWidget(self.c_income, 0, 0); grid.addWidget(self.c_expense, 0, 1)
        grid.addWidget(self.c_net, 0, 2); grid.addWidget(self.c_due, 0, 3)
        lay.addLayout(grid)
        # cash reconciliation: collected money broken down by payment method
        lay.addSpacing(8)
        lay.addWidget(field_label("Collection by payment method (paid in range)"))
        self.method_table = QTableWidget(0, 3)
        self.method_table.setHorizontalHeaderLabels(["Method", "Receipts", "Collected (Rs.)"])
        _mh = self.method_table.horizontalHeader()
        _mh.setSectionResizeMode(0, QHeaderView.Stretch)   # Method grows
        # fixed, generous widths for the numeric columns so the bold "Collected
        # (Rs.)" header can never be clipped at the table's right edge
        _mh.setSectionResizeMode(1, QHeaderView.Fixed)
        _mh.setSectionResizeMode(2, QHeaderView.Fixed)
        self.method_table.setColumnWidth(1, 100)
        self.method_table.setColumnWidth(2, 150)
        self.method_table.verticalHeader().setVisible(False)
        self.method_table.setAlternatingRowColors(True)
        self.method_table.setEditTriggers(QTableWidget.NoEditTriggers)
        # Rule 2 (no dead-space caps): instead of a fixed maximumHeight (which made a
        # lab with many payment methods scroll inside a short box while the page sat
        # empty), the table is sized to its exact content after each refresh
        # (_fit_method_table). The trailing stretch keeps a sparse table top-aligned;
        # an unusually long one grows and the page scroll view takes over.
        self.method_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay.addWidget(self.method_table)
        lay.addStretch(1)
        return w

    def _fit_method_table(self):
        """Pin the breakdown table to exactly its content height (header + rows) so
        it never internally scrolls and never shows empty filler rows."""
        t = self.method_table
        h = t.horizontalHeader().height() + 2 * t.frameWidth()
        for r in range(t.rowCount()):
            h += t.rowHeight(r)
        t.setFixedHeight(h)

    def refresh_summary(self):
        c = self.con; cur = db.currency(c)
        f = self.from_date.date().toString("yyyy-MM-dd")
        t = self.to_date.date().toString("yyyy-MM-dd")
        income = c.execute(
            "SELECT COALESCE(SUM(paid),0) FROM receipts "
            f"WHERE {db.NOT_VOIDED} AND date(received_at) BETWEEN ? AND ?",
            (f, t)).fetchone()[0]
        expense = c.execute(
            "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE date BETWEEN ? AND ?",
            (f, t)).fetchone()[0]
        due = c.execute(
            f"SELECT COALESCE(SUM(due),0) FROM receipts WHERE due>0.005 AND {db.NOT_VOIDED}"
        ).fetchone()[0]
        self.c_income.value_label.setText(money(income, cur))
        self.c_expense.value_label.setText(money(expense, cur))
        net = income - expense
        self.c_net.value_label.setText(money(net, cur))
        net_color = "#c0392b" if net < 0 else "#0a5f67"
        self.c_net.value_label.setStyleSheet(
            f"font-size: 30px; font-weight: 800; color: {net_color};")
        self.c_due.value_label.setText(money(due, cur))
        # cash reconciliation breakdown by payment method
        methods = c.execute(
            "SELECT COALESCE(NULLIF(TRIM(payment_method),''),'Cash') AS m, "
            "COUNT(*) AS n, COALESCE(SUM(paid),0) AS total FROM receipts "
            f"WHERE {db.NOT_VOIDED} AND paid>0 AND date(received_at) BETWEEN ? AND ? "
            "GROUP BY m ORDER BY total DESC", (f, t)).fetchall()
        self.method_table.setRowCount(0)
        for m in methods:
            i = self.method_table.rowCount(); self.method_table.insertRow(i)
            self.method_table.setItem(i, 0, QTableWidgetItem(m["m"]))
            self.method_table.setItem(i, 1, num_item(str(m["n"])))
            self.method_table.setItem(i, 2, num_item(f"{m['total']:,.0f}"))
        # total row
        i = self.method_table.rowCount(); self.method_table.insertRow(i)
        tot_item = QTableWidgetItem("Total")
        fnt = tot_item.font(); fnt.setBold(True); tot_item.setFont(fnt)
        self.method_table.setItem(i, 0, tot_item)
        self.method_table.setItem(i, 1, num_item(str(sum(m["n"] for m in methods))))
        tot_amt = num_item(f"{sum(m['total'] for m in methods):,.0f}")
        tot_amt.setFont(fnt)
        self.method_table.setItem(i, 2, tot_amt)
        self._fit_method_table()    # size to content (Rule 2: use space, no dead box)

    # ---- expenses ----
    def _expenses_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        self.exp_date = QDateEdit(QDate.currentDate()); self.exp_date.setCalendarPopup(True)
        self.exp_date.setDisplayFormat("dd MMM yyyy")
        self.exp_head = QLineEdit(); self.exp_head.setPlaceholderText("e.g. Reagents, Salary")
        self.exp_detail = QLineEdit(); self.exp_detail.setPlaceholderText("Description")
        self.exp_amount = QDoubleSpinBox(); self.exp_amount.setMaximum(10_000_000); self.exp_amount.setPrefix("Rs. ")
        add = QPushButton("Add expense"); add.clicked.connect(self.add_expense)
        # aligned label-over-input grid
        grid = QGridLayout(); grid.setSpacing(6)
        grid.setColumnStretch(1, 2); grid.setColumnStretch(2, 3)
        for col, text in enumerate(["Date", "Head", "Detail", "Amount", ""]):
            if text:
                grid.addWidget(field_label(text), 0, col)
        grid.addWidget(self.exp_date, 1, 0); grid.addWidget(self.exp_head, 1, 1)
        grid.addWidget(self.exp_detail, 1, 2); grid.addWidget(self.exp_amount, 1, 3)
        grid.addWidget(add, 1, 4)
        lay.addLayout(grid)
        self.exp_table = QTableWidget(0, 4)
        self.exp_table.setHorizontalHeaderLabels(["Date", "Head", "Detail", "Amount (Rs.)"])
        self.exp_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.exp_table.verticalHeader().setVisible(False)
        self.exp_table.setAlternatingRowColors(True)
        self.exp_table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.exp_table)
        return w

    def add_expense(self):
        if self.exp_amount.value() <= 0:
            return
        self.con.execute(
            "INSERT INTO expenses(date,head,detail,amount,created_by) VALUES (?,?,?,?,?)",
            (self.exp_date.date().toString("yyyy-MM-dd"), self.exp_head.text().strip(),
             self.exp_detail.text().strip(), self.exp_amount.value(), self.user["username"]),
        )
        self.con.execute(
            "INSERT INTO ledger(date,kind,detail,debit) VALUES (?,'expense',?,?)",
            (self.exp_date.date().toString("yyyy-MM-dd"),
             self.exp_head.text().strip(), self.exp_amount.value()),
        )
        self.con.commit()
        db.log_audit(self.con, self.user["username"], "expense_added",
                     f"{self.exp_head.text().strip() or 'expense'} — {money(self.exp_amount.value())}")
        self.exp_head.clear(); self.exp_detail.clear(); self.exp_amount.setValue(0)
        self.refresh_expenses()

    def refresh_expenses(self):
        rows = self.con.execute("SELECT * FROM expenses ORDER BY date DESC, id DESC LIMIT 500").fetchall()
        self.exp_table.setRowCount(0)
        for r in rows:
            i = self.exp_table.rowCount(); self.exp_table.insertRow(i)
            self.exp_table.setItem(i, 0, QTableWidgetItem(r["date"] or ""))
            self.exp_table.setItem(i, 1, QTableWidgetItem(r["head"] or ""))
            self.exp_table.setItem(i, 2, QTableWidgetItem(r["detail"] or ""))
            self.exp_table.setItem(i, 3, num_item(f"{r['amount']:,.0f}"))

    # ---- dues ----
    def _dues_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Receipts with outstanding balance"))
        self.recover_btn = QPushButton("Mark selected as paid"); self.recover_btn.setObjectName("ghost")
        self.recover_btn.clicked.connect(self.recover_due); self.recover_btn.setEnabled(False)
        bar.addStretch(1); bar.addWidget(self.recover_btn)
        lay.addLayout(bar)
        self.due_table = QTableWidget(0, 5)
        self.due_table.setHorizontalHeaderLabels(["Lab No", "Patient", "Net (Rs.)", "Paid (Rs.)", "Due (Rs.)"])
        self.due_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.due_table.verticalHeader().setVisible(False)
        self.due_table.setAlternatingRowColors(True)
        self.due_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.due_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.due_table.itemSelectionChanged.connect(
            lambda: self.recover_btn.setEnabled(
                bool(self.due_table.selectionModel().selectedRows())))
        lay.addWidget(self.due_table)
        return w

    def refresh_dues(self):
        rows = self.con.execute(
            f"SELECT * FROM receipts WHERE due>0.005 AND {db.NOT_VOIDED} ORDER BY id DESC"
        ).fetchall()
        self.due_table.setRowCount(0); self._due_ids = []
        for r in rows:
            i = self.due_table.rowCount(); self.due_table.insertRow(i)
            self._due_ids.append(r["id"])
            self.due_table.setItem(i, 0, QTableWidgetItem(r["lab_no"] or ""))
            self.due_table.setItem(i, 1, QTableWidgetItem(r["patient_name"] or ""))
            self.due_table.setItem(i, 2, num_item(f"{r['net_amount']:,.0f}"))
            self.due_table.setItem(i, 3, num_item(f"{r['paid']:,.0f}"))
            self.due_table.setItem(i, 4, num_item(f"{r['due']:,.0f}"))
        self.recover_btn.setEnabled(False)

    def recover_due(self):
        # use the actual selection, not currentRow (which survives a rebuild and
        # would settle a different receipt than the one highlighted)
        rid = selected_id(self.due_table, self._due_ids)
        if rid is None:
            return
        rec = self.con.execute("SELECT lab_no, due FROM receipts WHERE id=?", (rid,)).fetchone()
        if not rec or not rec["due"] or rec["due"] <= 0:
            return
        amount, ok = QInputDialog.getDouble(
            self, "Recover due",
            f"Amount received for {rec['lab_no']}  (due {money(rec['due'])}):",
            float(rec["due"]), 0.0, float(rec["due"]), 2)
        if not ok or amount <= 0:
            return
        db.receive_due(self.con, rid, amount, self.user["username"])
        self.refresh_dues(); self.refresh_summary()

    def on_show(self):
        self.refresh_summary()
        self.refresh_expenses()
        self.refresh_dues()
