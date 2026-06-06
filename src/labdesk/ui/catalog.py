"""Test Catalog: browse/search tests, view parameters, edit charges/details."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTableWidget, QTableWidgetItem,
    QLineEdit, QPushButton, QHeaderView, QDialog, QFormLayout, QDoubleSpinBox,
    QComboBox, QPlainTextEdit, QLabel, QMessageBox, QSizePolicy,
)

from .widgets import h1, muted, page_header
from ..constants import SPECIMEN_PRESETS
from ..roles import can


class TestDialog(QDialog):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle("Test")
        self.setMinimumWidth(440)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.charges = QDoubleSpinBox(); self.charges.setMaximum(1_000_000); self.charges.setPrefix("Rs. ")
        self.category = QComboBox(); self.category.setEditable(True)
        self.category.addItems(["Routine", "Special", "X-Ray", "Ultrasound", "Histopath", ""])
        self.sample = QComboBox(); self.sample.setEditable(True)
        self.sample.addItem("")
        self.sample.addItems(SPECIMEN_PRESETS)
        self.head = QLineEdit()
        self.method = QPlainTextEdit(); self.method.setMaximumHeight(90)
        form.addRow("Test name *", self.name)
        form.addRow("Charges", self.charges)
        form.addRow("Category", self.category)
        form.addRow("Sample required", self.sample)
        form.addRow("Report head", self.head)
        form.addRow("Method / comments", self.method)
        if data:
            self.name.setText(data["name"] or "")
            self.charges.setValue(data["charges"] or 0)
            self.category.setCurrentText(data["category"] or "")
            self.sample.setCurrentText(data["sample_required"] or "")
            self.head.setText(data["report_head"] or "")
            self.method.setPlainText(data["method_note"] or "")
        btns = QHBoxLayout()
        ok = QPushButton("Save"); ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel"); cancel.setObjectName("ghost"); cancel.clicked.connect(self.reject)
        btns.addStretch(1); btns.addWidget(cancel); btns.addWidget(ok)
        form.addRow(btns)

    def values(self):
        return {
            "name": self.name.text().strip(),
            "charges": self.charges.value(),
            "category": self.category.currentText().strip(),
            "sample_required": self.sample.currentText().strip(),
            "report_head": self.head.text().strip(),
            "method_note": self.method.toPlainText().strip(),
        }


class CatalogPage(QWidget):
    def __init__(self, con, user):
        super().__init__()
        self.con = con
        self.user = user
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        add = QPushButton("+ Add test"); add.clicked.connect(self.add)
        edit = QPushButton("Edit"); edit.setObjectName("ghost"); edit.clicked.connect(self.edit)
        if not can(user["role"], "edit_catalog"):
            add.hide(); edit.hide()  # read-only for lower roles
            self.tests_readonly = True
        header, self.sub = page_header("Test Catalog", "", add, edit)
        lay.addWidget(header)

        self.search = QLineEdit(); self.search.setPlaceholderText("Search tests by name…")
        self.search.setMinimumHeight(40)
        self.search.textChanged.connect(self.refresh)
        lay.addWidget(self.search)

        split = QSplitter()
        split.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tests = QTableWidget(0, 3)
        self.tests.setHorizontalHeaderLabels(["Test", "Charges (Rs.)", "Category"])
        self.tests.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tests.setSelectionBehavior(QTableWidget.SelectRows)
        self.tests.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tests.itemSelectionChanged.connect(self.show_params)
        self.tests.doubleClicked.connect(self.edit)
        split.addWidget(self.tests)

        right = QWidget(); rl = QVBoxLayout(right)
        rl.addWidget(QLabel("Parameters / report lines"))
        self.params = QTableWidget(0, 5)
        self.params.setHorizontalHeaderLabels(["#", "Parameter", "Units", "Ref (M)", "Ref (F)"])
        ph = self.params.horizontalHeader()
        ph.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # narrow #
        ph.setSectionResizeMode(1, QHeaderView.Stretch)           # parameter name
        ph.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # units
        ph.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        ph.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.params.verticalHeader().setVisible(False)
        self.params.setAlternatingRowColors(True)
        self.params.setEditTriggers(QTableWidget.NoEditTriggers)
        rl.addWidget(self.params)
        split.addWidget(right)
        split.setSizes([560, 540])
        lay.addWidget(split, 1)

    def on_show(self):
        self.refresh()

    def refresh(self):
        q = f"%{self.search.text().strip()}%"
        rows = self.con.execute(
            "SELECT * FROM tests WHERE active=1 AND name LIKE ? ORDER BY name LIMIT 1000",
            (q,),
        ).fetchall()
        total = self.con.execute("SELECT COUNT(*) FROM tests WHERE active=1").fetchone()[0]
        self.sub.setText(f"{total} tests in catalog")
        self.sub.show()
        self.tests.setRowCount(0)
        self._ids = []
        for r in rows:
            i = self.tests.rowCount(); self.tests.insertRow(i)
            self._ids.append(r["id"])
            self.tests.setItem(i, 0, QTableWidgetItem(r["name"]))
            charge = QTableWidgetItem(f"{(r['charges'] or 0):,.0f}")
            charge.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tests.setItem(i, 1, charge)
            self.tests.setItem(i, 2, QTableWidgetItem(r["category"] or ""))
        if self.tests.rowCount() and self.tests.currentRow() < 0:
            self.tests.selectRow(0)  # show params for the first test by default

    def _selected_id(self):
        r = self.tests.currentRow()
        return self._ids[r] if 0 <= r < len(self._ids) else None

    def show_params(self):
        tid = self._selected_id()
        self.params.setRowCount(0)
        if tid is None:
            return
        rows = self.con.execute(
            "SELECT * FROM test_parameters WHERE test_id=? ORDER BY seq", (tid,)
        ).fetchall()
        for r in rows:
            i = self.params.rowCount(); self.params.insertRow(i)
            self.params.setItem(i, 0, QTableWidgetItem(str(r["seq"] + 1)))
            self.params.setItem(i, 1, QTableWidgetItem(r["name"] or ""))
            self.params.setItem(i, 2, QTableWidgetItem(r["units"] or ""))
            self.params.setItem(i, 3, QTableWidgetItem(r["ref_male"] or ""))
            self.params.setItem(i, 4, QTableWidgetItem(r["ref_female"] or ""))

    def add(self):
        if not can(self.user["role"], "edit_catalog"):
            return
        d = TestDialog(self)
        if d.exec() == QDialog.Accepted:
            v = d.values()
            if not v["name"]:
                return
            self.con.execute(
                "INSERT INTO tests(name,charges,category,sample_required,report_head,method_note)"
                " VALUES (?,?,?,?,?,?)",
                (v["name"], v["charges"], v["category"], v["sample_required"],
                 v["report_head"], v["method_note"]),
            )
            self.con.commit(); self.refresh()

    def edit(self):
        if not can(self.user["role"], "edit_catalog"):
            return
        tid = self._selected_id()
        if tid is None:
            return
        row = self.con.execute("SELECT * FROM tests WHERE id=?", (tid,)).fetchone()
        d = TestDialog(self, row)
        if d.exec() == QDialog.Accepted:
            v = d.values()
            self.con.execute(
                "UPDATE tests SET name=?,charges=?,category=?,sample_required=?,"
                "report_head=?,method_note=? WHERE id=?",
                (v["name"], v["charges"], v["category"], v["sample_required"],
                 v["report_head"], v["method_note"], tid),
            )
            self.con.commit(); self.refresh()
