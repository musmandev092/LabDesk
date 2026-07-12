"""Catalog dialogs (add/edit a test, edit its parameters, manage panels).

Lifted out of catalog.py to thin the page module; behavior unchanged.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
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
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import db
from ..constants import SPECIMEN_PRESETS
from .widgets import (
    fit_to_screen,
    muted,
    toast_info,
    toast_warn,
)


# Report-layout override options (value stored in tests.render_category; ""=auto).
RENDER_LAYOUTS = [
    ("Auto (detect from parameters)", ""),
    ("Numeric table (value / unit / reference)", "numeric_tabular"),
    ("Qualitative (result + reference, no unit)", "qualitative"),
    ("Blood bank (result only)", "blood_bank"),
    ("Descriptive / narrative (findings + impression)", "descriptive"),
]


class TestDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, data=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Test")
        self.setMinimumWidth(440)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.charges = QDoubleSpinBox()
        self.charges.setMaximum(1_000_000)
        self.charges.setPrefix("Rs. ")
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems(
            ["Routine", "Special", "X-Ray", "Ultrasound", "Histopath", ""]
        )
        self.sample = QComboBox()
        self.sample.setEditable(True)
        self.sample.addItem("")
        self.sample.addItems(SPECIMEN_PRESETS)
        self.head = QLineEdit()
        self.method = QPlainTextEdit()
        self.method.setMaximumHeight(90)
        # Report layout override — normally the layout is detected from the test's
        # parameters; this lets an admin force a specific one if a test is
        # misclassified. Empty data => "Auto (detect)".
        self.render_cat = QComboBox()
        for label, code in RENDER_LAYOUTS:
            self.render_cat.addItem(label, code)
        form.addRow("Test name *", self.name)
        form.addRow("Charges", self.charges)
        form.addRow("Category", self.category)
        form.addRow("Sample required", self.sample)
        form.addRow("Report head", self.head)
        form.addRow("Report layout", self.render_cat)
        form.addRow("Method / comments", self.method)
        if data:
            self.name.setText(data["name"] or "")
            self.charges.setValue(data["charges"] or 0)
            self.category.setCurrentText(data["category"] or "")
            self.sample.setCurrentText(data["sample_required"] or "")
            self.head.setText(data["report_head"] or "")
            self.method.setPlainText(data["method_note"] or "")
            rc = (
                data["render_category"] if "render_category" in data.keys() else ""
            ) or ""
            idx = self.render_cat.findData(rc)
            self.render_cat.setCurrentIndex(idx if idx >= 0 else 0)
        btns = QHBoxLayout()
        ok = QPushButton("Save")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        form.addRow(btns)

    def values(self) -> dict:
        return {
            "name": self.name.text().strip(),
            "charges": self.charges.value(),
            "category": self.category.currentText().strip(),
            "sample_required": self.sample.currentText().strip(),
            "report_head": self.head.text().strip(),
            "method_note": self.method.toPlainText().strip(),
            # "" (Auto) is stored as NULL → classify at render time
            "render_category": self.render_cat.currentData() or None,
        }


PART_TYPES = [("Normal line", "N"), ("Section heading", "H"), ("Note / ref-only", "L")]


class ParametersDialog(QDialog):
    """In-app editor for a test's report lines (parameters / headings / notes)."""

    def __init__(
        self,
        con,
        user: dict,
        test_id: int,
        test_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.con = con
        self.user = user
        self.test_id = test_id
        self.setWindowTitle(f"Parameters — {test_name}")
        fit_to_screen(self, 860, 560)
        lay = QVBoxLayout(self)
        lay.addWidget(
            muted(
                "Define the lines that appear on this test's report. "
                "“Section heading” is a bold sub-title; “Note / ref-only” is an "
                "italic line with no result box."
            )
        )

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Type", "Parameter", "Units", "Ref (Male)", "Ref (Female)", "Default"]
        )
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        for c in range(2, 6):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        # rows must be tall enough for the styled "Type" dropdown (padding + rounded
        # border) — otherwise it gets squished to a thin text-less oval.
        self.table.verticalHeader().setDefaultSectionSize(40)
        # cell editors are QLineEdits; the app-wide 8px input padding squeezes their
        # text region inside a table row until it clips vertically. Give the in-table
        # editors a tighter padding so the typed text is fully visible.
        self.table.setStyleSheet("QLineEdit { padding: 1px 6px; }")
        lay.addWidget(self.table, 1)

        bar = QHBoxLayout()
        add = QPushButton("+ Add line")
        add.clicked.connect(self._add_row)
        rm = QPushButton("Remove")
        rm.setObjectName("ghost")
        rm.clicked.connect(self._remove_row)
        up = QPushButton("↑ Up")
        up.setObjectName("ghost")
        up.clicked.connect(lambda: self._move(-1))
        dn = QPushButton("↓ Down")
        dn.setObjectName("ghost")
        dn.clicked.connect(lambda: self._move(1))
        bar.addWidget(add)
        bar.addWidget(rm)
        bar.addWidget(up)
        bar.addWidget(dn)
        bar.addStretch(1)
        save = QPushButton("Save")
        save.clicked.connect(self._save)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        bar.addWidget(cancel)
        bar.addWidget(save)
        lay.addLayout(bar)

        self.rows = [
            dict(r)
            for r in self.con.execute(
                "SELECT * FROM test_parameters WHERE test_id=? ORDER BY seq, id",
                (test_id,),
            ).fetchall()
        ]
        self._render()

    def _type_combo(self, value: str | None) -> QComboBox:
        cb = QComboBox()
        for lbl, code in PART_TYPES:
            cb.addItem(lbl, code)
        idx = cb.findData((value or "N").upper())
        cb.setCurrentIndex(idx if idx >= 0 else 0)
        cb.setMinimumHeight(30)  # so the label text isn't clipped inside the cell
        return cb

    def _render(self) -> None:
        self.table.setRowCount(0)
        for r in self.rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            self.table.setCellWidget(i, 0, self._type_combo(r.get("part_type")))
            self.table.setItem(i, 1, QTableWidgetItem(r.get("name") or ""))
            self.table.setItem(i, 2, QTableWidgetItem(r.get("units") or ""))
            self.table.setItem(i, 3, QTableWidgetItem(r.get("ref_male") or ""))
            self.table.setItem(i, 4, QTableWidgetItem(r.get("ref_female") or ""))
            self.table.setItem(i, 5, QTableWidgetItem(r.get("default_result") or ""))

    def _sync(self) -> None:
        """Pull the table's current contents back into self.rows (preserving ids)."""
        for i, r in enumerate(self.rows):
            cb = self.table.cellWidget(i, 0)
            if cb is not None:
                r["part_type"] = cb.currentData()
            r["name"] = self._cell(i, 1)
            r["units"] = self._cell(i, 2)
            r["ref_male"] = self._cell(i, 3)
            r["ref_female"] = self._cell(i, 4)
            r["default_result"] = self._cell(i, 5)

    def _cell(self, i: int, c: int) -> str:
        it = self.table.item(i, c)
        return it.text().strip() if it else ""

    def _add_row(self) -> None:
        self._sync()
        self.rows.append(
            {
                "id": None,
                "part_type": "N",
                "name": "",
                "units": "",
                "ref_male": "",
                "ref_female": "",
                "default_result": "",
            }
        )
        self._render()
        self.table.selectRow(len(self.rows) - 1)

    def _remove_row(self) -> None:
        i = self.table.currentRow()
        if not (0 <= i < len(self.rows)):
            return
        self._sync()
        del self.rows[i]
        self._render()

    def _move(self, delta: int) -> None:
        i = self.table.currentRow()
        j = i + delta
        if not (0 <= i < len(self.rows) and 0 <= j < len(self.rows)):
            return
        self._sync()
        self.rows[i], self.rows[j] = self.rows[j], self.rows[i]
        self._render()
        self.table.selectRow(j)

    def _save(self) -> None:
        self._sync()
        # drop fully-empty rows so accidental blank lines don't print
        rows = [
            r
            for r in self.rows
            if (r.get("name") or "").strip() or (r.get("part_type") or "N") != "N"
        ]
        try:
            db.save_test_parameters(
                self.con,
                self.test_id,
                rows,
                actor_role=self.user["role"],
                username=self.user["username"],
            )
        except db.ParameterInUseError as e:
            toast_warn(self, "Parameters", str(e))
            return
        except Exception as e:
            toast_warn(self, "Parameters", f"Could not save the parameters:\n{e}")
            return
        # audit is recorded inside save_test_parameters (mutation-layer trail)
        self.accept()


class PanelsDialog(QDialog):
    """Manage test panels / profiles — named bundles of tests added together."""

    def __init__(self, con, user: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.con = con
        self.user = user
        self.setWindowTitle("Test panels / profiles")
        fit_to_screen(self, 720, 520)
        self._panel_id: int | None = None

        root = QHBoxLayout(self)
        # left: list of panels
        left = QVBoxLayout()
        left.addWidget(QLabel("Panels"))
        self.panel_list = QListWidget()
        self.panel_list.currentItemChanged.connect(self._load_panel)
        left.addWidget(self.panel_list, 1)
        lb = QHBoxLayout()
        new = QPushButton("New")
        new.clicked.connect(self._new_panel)
        self.del_btn = QPushButton("Delete")
        self.del_btn.setObjectName("ghost")
        self.del_btn.clicked.connect(self._delete_panel)
        self.del_btn.setEnabled(False)
        lb.addWidget(new)
        lb.addWidget(self.del_btn)
        left.addLayout(lb)
        root.addLayout(left, 2)

        # right: editor
        right = QVBoxLayout()
        right.addWidget(QLabel("Panel name"))
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. Fever Profile")
        right.addWidget(self.name)
        right.addWidget(QLabel("Tests in this panel (tick to include)"))
        self.test_search = QLineEdit()
        self.test_search.setPlaceholderText("Filter tests…")
        self.test_search.textChanged.connect(self._filter_tests)
        right.addWidget(self.test_search)
        self.tests = QListWidget()
        right.addWidget(self.tests, 1)
        save = QPushButton("Save panel")
        save.clicked.connect(self._save)
        close = QPushButton("Close")
        close.setObjectName("ghost")
        close.clicked.connect(self.accept)
        rb = QHBoxLayout()
        rb.addStretch(1)
        rb.addWidget(close)
        rb.addWidget(save)
        right.addLayout(rb)
        root.addLayout(right, 3)

        self._load_all_tests()
        self._refresh_panels()
        self._new_panel()

    def _load_all_tests(self) -> None:
        self._all_tests = self.con.execute(
            "SELECT id, name FROM tests WHERE active=1 ORDER BY name COLLATE NOCASE"
        ).fetchall()

    def _populate_tests(self, checked_ids: list[int] | None) -> None:
        checked = set(checked_ids or [])
        self.tests.clear()
        for t in self._all_tests:
            it = QListWidgetItem(t["name"])
            it.setData(Qt.UserRole, t["id"])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if t["id"] in checked else Qt.Unchecked)
            self.tests.addItem(it)
        self._filter_tests(self.test_search.text())

    def _filter_tests(self, text: str) -> None:
        text = (text or "").strip().lower()
        for i in range(self.tests.count()):
            it = self.tests.item(i)
            it.setHidden(bool(text) and text not in it.text().lower())

    def _checked_ids(self) -> list:
        out = []
        for i in range(self.tests.count()):
            it = self.tests.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def _refresh_panels(self) -> None:
        self.panel_list.blockSignals(True)
        self.panel_list.clear()
        for p in db.list_panels(self.con):
            n = len(db.panel_tests(self.con, p["id"]))
            it = QListWidgetItem(f"{p['name']}  ({n})")
            it.setData(Qt.UserRole, p["id"])
            self.panel_list.addItem(it)
        self.panel_list.blockSignals(False)

    def _new_panel(self) -> None:
        self._panel_id = None
        self.panel_list.clearSelection()
        self.name.clear()
        self._populate_tests([])
        self.del_btn.setEnabled(False)
        self.name.setFocus()

    def _load_panel(self, item, _prev=None) -> None:
        if item is None:
            return
        pid = item.data(Qt.UserRole)
        if pid is None:
            return
        row = self.con.execute("SELECT * FROM panels WHERE id=?", (pid,)).fetchone()
        if not row:
            return
        self._panel_id = pid
        self.name.setText(row["name"] or "")
        self._populate_tests([t["id"] for t in db.panel_tests(self.con, pid)])
        self.del_btn.setEnabled(True)

    def _save(self) -> None:
        name = self.name.text().strip()
        if not name:
            toast_warn(self, "Panel", "Give the panel a name.")
            return
        ids = self._checked_ids()
        if not ids:
            toast_warn(self, "Panel", "Tick at least one test for the panel.")
            return
        pid = db.save_panel(
            self.con,
            name,
            ids,
            self._panel_id,
            actor_role=self.user["role"],
            username=self.user["username"],
        )
        # audit is recorded inside save_panel (mutation-layer trail)
        self._panel_id = pid
        self._refresh_panels()
        # re-select the saved panel
        for i in range(self.panel_list.count()):
            if self.panel_list.item(i).data(Qt.UserRole) == pid:
                self.panel_list.setCurrentRow(i)
                break
        toast_info(self, "Panel", f"Saved “{name}”.")

    def _delete_panel(self) -> None:
        if self._panel_id is None:
            return
        name = self.name.text().strip()
        if (
            QMessageBox.question(self, "Panel", f"Delete panel “{name}”?")
            != QMessageBox.Yes
        ):
            return
        db.delete_panel(
            self.con,
            self._panel_id,
            actor_role=self.user["role"],
            username=self.user["username"],
        )
        # audit is recorded inside delete_panel (mutation-layer trail)
        self._refresh_panels()
        self._new_panel()
