"""Test Catalog: browse/search tests, view parameters, edit charges/details."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import db
from ..roles import can
from . import tasks
from .catalog_dialogs import PanelsDialog, ParametersDialog, TestDialog
from .widgets import (
    like_term,
    page_header,
    toast_info,
)


class CatalogPage(QWidget):
    def __init__(self, con, user: dict) -> None:
        super().__init__()
        self.con = con
        self.user = user
        self._ids: list = []  # parallel to tests table rows; filled by refresh
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        add = QPushButton("+ Add test")
        add.clicked.connect(self.add)
        edit = QPushButton("Edit")
        edit.setObjectName("ghost")
        edit.clicked.connect(self.edit)
        self.retire_btn = QPushButton("Retire / Restore")
        self.retire_btn.setObjectName("ghost")
        self.retire_btn.clicked.connect(self.toggle_retire)
        self.params_btn = QPushButton("Edit parameters…")
        self.params_btn.setObjectName("ghost")
        self.params_btn.clicked.connect(self.edit_parameters)
        self.panels_btn = QPushButton("Panels…")
        self.panels_btn.setObjectName("ghost")
        self.panels_btn.clicked.connect(self.manage_panels)
        if not can(user["role"], "edit_catalog"):
            add.hide()
            edit.hide()
            self.retire_btn.hide()  # read-only for lower roles
            self.params_btn.hide()
            self.panels_btn.hide()
        header, self.sub = page_header(
            "Test Catalog",
            "",
            add,
            edit,
            self.retire_btn,
            self.params_btn,
            self.panels_btn,
        )
        lay.addWidget(header)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search tests by name…")
        self.search.setMinimumHeight(40)
        self.search.textChanged.connect(tasks.debounce(self, self.refresh))
        self.show_retired = QCheckBox("Show retired")
        self.show_retired.toggled.connect(self.refresh)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.show_retired)
        lay.addLayout(bar)

        split = QSplitter()
        split.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tests = QTableWidget(0, 3)
        self.tests.setHorizontalHeaderLabels(["Test", "Charges (Rs.)", "Category"])
        _th = self.tests.horizontalHeader()
        _th.setSectionResizeMode(0, QHeaderView.Stretch)  # Test name fills
        _th.setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )  # "Charges (Rs.)" no longer clipped
        _th.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Category
        self.tests.setSelectionBehavior(QTableWidget.SelectRows)
        self.tests.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tests.itemSelectionChanged.connect(self.show_params)
        self.tests.doubleClicked.connect(self.edit)
        split.addWidget(self.tests)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("Parameters / report lines"))
        self.params = QTableWidget(0, 5)
        self.params.setHorizontalHeaderLabels(
            ["#", "Parameter", "Units", "Ref (M)", "Ref (F)"]
        )
        ph = self.params.horizontalHeader()
        ph.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # narrow #
        ph.setSectionResizeMode(1, QHeaderView.Stretch)  # parameter name
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

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        q = like_term(self.search.text())
        active_clause = "" if self.show_retired.isChecked() else "active=1 AND "
        rows = self.con.execute(
            f"SELECT * FROM tests WHERE {active_clause}name LIKE ? ESCAPE '\\' "
            "ORDER BY name LIMIT 1000",
            (q,),
        ).fetchall()
        total = self.con.execute(
            "SELECT COUNT(*) FROM tests WHERE active=1"
        ).fetchone()[0]
        self.sub.setText(f"{total} active tests in catalog")
        self.sub.show()
        self.tests.setRowCount(0)
        self._ids = []
        for r in rows:
            i = self.tests.rowCount()
            self.tests.insertRow(i)
            self._ids.append(r["id"])
            name = r["name"] + ("  (retired)" if not r["active"] else "")
            item = QTableWidgetItem(name)
            if not r["active"]:
                item.setForeground(QColor("#c0392b"))
            self.tests.setItem(i, 0, item)
            charge = QTableWidgetItem(f"{(r['charges'] or 0):,.0f}")
            charge.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tests.setItem(i, 1, charge)
            self.tests.setItem(i, 2, QTableWidgetItem(r["category"] or ""))
        if self.tests.rowCount() and self.tests.currentRow() < 0:
            self.tests.selectRow(0)  # show params for the first test by default

    def _selected_id(self) -> int | None:
        r = self.tests.currentRow()
        return self._ids[r] if 0 <= r < len(self._ids) else None

    def show_params(self) -> None:
        tid = self._selected_id()
        self.params.setRowCount(0)
        if tid is None:
            return
        rows = self.con.execute(
            "SELECT * FROM test_parameters WHERE test_id=? ORDER BY seq", (tid,)
        ).fetchall()
        for r in rows:
            i = self.params.rowCount()
            self.params.insertRow(i)
            self.params.setItem(i, 0, QTableWidgetItem(str(r["seq"] + 1)))
            self.params.setItem(i, 1, QTableWidgetItem(r["name"] or ""))
            self.params.setItem(i, 2, QTableWidgetItem(r["units"] or ""))
            self.params.setItem(i, 3, QTableWidgetItem(r["ref_male"] or ""))
            self.params.setItem(i, 4, QTableWidgetItem(r["ref_female"] or ""))

    def add(self) -> None:
        if not can(self.user["role"], "edit_catalog"):
            return
        d = TestDialog(self)
        if d.exec() == QDialog.Accepted:
            v = d.values()
            if not v["name"]:
                return
            self.con.execute(
                "INSERT INTO tests(name,charges,category,sample_required,report_head,"
                "method_note,render_category) VALUES (?,?,?,?,?,?,?)",
                (
                    v["name"],
                    v["charges"],
                    v["category"],
                    v["sample_required"],
                    v["report_head"],
                    v["method_note"],
                    v["render_category"],
                ),
            )
            self.con.commit()
            db.log_audit(self.con, self.user["username"], "test_created", v["name"])
            self.refresh()

    def edit(self) -> None:
        if not can(self.user["role"], "edit_catalog"):
            return
        tid = self._selected_id()
        if tid is None:
            return
        row = self.con.execute("SELECT * FROM tests WHERE id=?", (tid,)).fetchone()
        d = TestDialog(self, row)
        if d.exec() == QDialog.Accepted:
            v = d.values()
            if not v["name"]:
                return  # never blank a test's name (matches add())
            self.con.execute(
                "UPDATE tests SET name=?,charges=?,category=?,sample_required=?,"
                "report_head=?,method_note=?,render_category=? WHERE id=?",
                (
                    v["name"],
                    v["charges"],
                    v["category"],
                    v["sample_required"],
                    v["report_head"],
                    v["method_note"],
                    v["render_category"],
                    tid,
                ),
            )
            self.con.commit()
            db.log_audit(self.con, self.user["username"], "test_updated", v["name"])
            self.refresh()

    def manage_panels(self) -> None:
        if not can(self.user["role"], "edit_catalog"):
            return
        PanelsDialog(self.con, self.user, self).exec()

    def edit_parameters(self) -> None:
        if not can(self.user["role"], "edit_catalog"):
            return
        tid = self._selected_id()
        if tid is None:
            toast_info(self, "Parameters", "Select a test first.")
            return
        row = self.con.execute("SELECT name FROM tests WHERE id=?", (tid,)).fetchone()
        dlg = ParametersDialog(
            self.con, self.user, tid, row["name"] if row else "", self
        )
        if dlg.exec() == QDialog.Accepted:
            self.show_params()  # refresh the read-only preview pane

    def toggle_retire(self) -> None:
        if not can(self.user["role"], "edit_catalog"):
            return
        tid = self._selected_id()
        if tid is None:
            return
        row = self.con.execute(
            "SELECT name, active FROM tests WHERE id=?", (tid,)
        ).fetchone()
        if not row:
            return
        new_active = 0 if row["active"] else 1
        verb = "restore" if new_active else "retire"
        if (
            QMessageBox.question(
                self, "Catalog", f"{verb.capitalize()} test “{row['name']}”?"
            )
            != QMessageBox.Yes
        ):
            return
        self.con.execute("UPDATE tests SET active=? WHERE id=?", (new_active, tid))
        self.con.commit()
        db.log_audit(
            self.con,
            self.user["username"],
            "test_activated" if new_active else "test_deactivated",
            row["name"],
        )
        self.refresh()
