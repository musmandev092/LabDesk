"""Microbiology: culture & sensitivity reporting."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..application import results as results_svc
from . import tasks
from .widgets import card, h2, page_header, toast_info, toast_warn


class MicrobiologyPage(QWidget):
    def __init__(self, con, user: dict) -> None:
        super().__init__()
        self.con = con
        self.user = user
        self.current_item = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header, _ = page_header(
            "Microbiology", "Culture & sensitivity — select an order, enter findings"
        )
        root.addWidget(header)

        split = QSplitter()
        split.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # left: culture orders
        left = QWidget()
        ll = QVBoxLayout(left)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search patient / lab no…")
        self.search.textChanged.connect(tasks.debounce(self, self.refresh_list))
        ll.addWidget(self.search)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Lab No", "Patient", "Test"])
        mh = self.table.horizontalHeader()
        mh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        mh.setSectionResizeMode(1, QHeaderView.Stretch)
        mh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.load_item)
        ll.addWidget(self.table)
        split.addWidget(left)

        # right: culture form
        right = QWidget()
        rl = QVBoxLayout(right)
        self.header = h2("Select a culture order")
        rl.addWidget(self.header)

        form = QFormLayout()
        self.specimen = self._combo("specimen")
        self.growth = self._combo("growth")
        self.organism = QLineEdit()
        self.colony = QLineEdit()
        self.gram = self._combo("gram")
        self.zn = self._combo("zn")
        self.remarks = QPlainTextEdit()
        self.remarks.setMaximumHeight(70)
        form.addRow("Specimen", self.specimen)
        form.addRow("Growth", self.growth)
        form.addRow("Organism", self.organism)
        form.addRow("Colony count", self.colony)
        form.addRow("Gram stain", self.gram)
        form.addRow("ZN stain", self.zn)
        form.addRow("Remarks", self.remarks)
        fw = QWidget()
        fw.setLayout(form)
        rl.addWidget(card(h2("Findings"), fw))

        # sensitivity
        sens_head = QHBoxLayout()
        sens_head.addWidget(QLabel("Antibiotic sensitivity"))
        add_ab = QPushButton("+ Add antibiotic")
        add_ab.setObjectName("ghost")
        add_ab.clicked.connect(self.add_sens_row)
        sens_head.addStretch(1)
        sens_head.addWidget(add_ab)
        rl.addLayout(sens_head)
        self.sens = QTableWidget(0, 2)
        self.sens.setHorizontalHeaderLabels(["Antibiotic", "S / I / R"])
        self.sens.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        rl.addWidget(self.sens)

        save = QPushButton("Save culture report")
        save.clicked.connect(self.save)
        rl.addWidget(save)
        split.addWidget(right)
        split.setSizes([500, 700])
        root.addWidget(split, 1)

        sc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(self.clear_selection)
        self.table.viewport().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.table.viewport() and event.type() == QEvent.MouseButtonPress:
            if not self.table.indexAt(event.position().toPoint()).isValid():
                self.clear_selection()
        return super().eventFilter(obj, event)

    def clear_selection(self) -> None:
        # block signals so clearSelection() doesn't re-fire load_item
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.blockSignals(False)
        self.current_item = None
        self.header.setText("Select a culture order")
        for w in (self.specimen, self.growth, self.gram, self.zn):
            w.setCurrentIndex(0)
        for w in (self.organism, self.colony):
            w.clear()
        self.remarks.clear()
        self.sens.setRowCount(0)

    def _combo(self, kind: str) -> QComboBox:
        cb = QComboBox()
        cb.setEditable(True)
        cb.addItem("")
        for r in self.con.execute(
            "SELECT value FROM micro_lists WHERE kind=? GROUP BY value ORDER BY MIN(seq), value",
            (kind,),
        ):
            cb.addItem(r["value"])
        return cb

    def on_show(self) -> None:
        self.refresh_list()

    def refresh_list(self) -> None:
        q = f"%{self.search.text().strip()}%"
        rows = self.con.execute(
            """SELECT ri.id AS item_id, r.lab_no, r.patient_name, ri.test_name
               FROM receipt_items ri JOIN receipts r ON r.id=ri.receipt_id
               JOIN tests t ON t.id=ri.test_id
               WHERE t.is_culture=1 AND (COALESCE(r.patient_name,'') LIKE ?
                                         OR COALESCE(r.lab_no,'') LIKE ?)
               ORDER BY ri.id DESC LIMIT 300""",
            (q, q),
        ).fetchall()
        self.table.setRowCount(0)
        self._items = []
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            self._items.append(r["item_id"])
            self.table.setItem(i, 0, QTableWidgetItem(r["lab_no"] or ""))
            self.table.setItem(i, 1, QTableWidgetItem(r["patient_name"] or ""))
            self.table.setItem(i, 2, QTableWidgetItem(r["test_name"] or ""))

    def load_item(self) -> None:
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            return
        r = sel[0].row()
        if not (0 <= r < len(self._items)):
            return
        self.current_item = self._items[r]
        lab = self.table.item(r, 0).text()
        patient = self.table.item(r, 1).text()
        test = self.table.item(r, 2).text()
        self.header.setText(f"{lab} — {patient} — {test}")
        existing = self.con.execute(
            "SELECT * FROM cultures WHERE receipt_item_id=?", (self.current_item,)
        ).fetchone()
        self.sens.setRowCount(0)
        # reset fields first so a culture with no saved data doesn't show stale values
        for w in (self.specimen, self.growth, self.gram, self.zn):
            w.setCurrentIndex(0)
        self.organism.clear()
        self.colony.clear()
        self.remarks.clear()
        if existing:
            self.specimen.setCurrentText(existing["specimen"] or "")
            self.growth.setCurrentText(existing["growth"] or "")
            self.organism.setText(existing["organism"] or "")
            self.colony.setText(existing["colony_count"] or "")
            self.gram.setCurrentText(existing["gram_stain"] or "")
            self.zn.setCurrentText(existing["zn_stain"] or "")
            self.remarks.setPlainText(existing["remarks"] or "")
            for s in self.con.execute(
                "SELECT * FROM culture_sensitivity WHERE culture_id=?",
                (existing["id"],),
            ):
                self._add_sens(s["antibiotic"], s["result"])

    def _add_sens(self, antibiotic: str = "", result: str = "S") -> None:
        i = self.sens.rowCount()
        self.sens.insertRow(i)
        ab = QComboBox()
        ab.setEditable(True)
        for r in self.con.execute(
            "SELECT value FROM micro_lists WHERE kind='antibiotic' GROUP BY value ORDER BY value"
        ):
            ab.addItem(r["value"])
        ab.setCurrentText(antibiotic)
        res = QComboBox()
        res.addItems(["S", "I", "R"])
        res.setCurrentText(result or "S")
        self.sens.setCellWidget(i, 0, ab)
        self.sens.setCellWidget(i, 1, res)

    def add_sens_row(self) -> None:
        self._add_sens()

    def save(self) -> None:
        if self.current_item is None:
            toast_warn(self, "Microbiology", "Select a culture order first.")
            return
        c = self.con
        # DB writes + authorization + audit happen at results_svc.save_culture
        culture = {
            "specimen": self.specimen.currentText(),
            "growth": self.growth.currentText(),
            "organism": self.organism.text().strip(),
            "colony_count": self.colony.text().strip(),
            "gram_stain": self.gram.currentText(),
            "zn_stain": self.zn.currentText(),
            "remarks": self.remarks.toPlainText().strip(),
        }
        sensitivities = [
            (
                self.sens.cellWidget(i, 0).currentText().strip(),
                self.sens.cellWidget(i, 1).currentText(),
            )
            for i in range(self.sens.rowCount())
        ]
        try:
            results_svc.save_culture(
                c,
                item_id=self.current_item,
                culture=culture,
                sensitivities=sensitivities,
                actor_username=self.user["username"],
                actor_role=self.user["role"],
            )
        except PermissionError:
            toast_warn(
                self,
                "Not allowed",
                "You don't have permission to save culture reports.",
            )
            return
        except Exception as e:
            toast_warn(
                self,
                "Save failed",
                f"The culture report was NOT saved — please try again.\n\n{e}",
            )
            return
        toast_info(self, "Microbiology", "✓ Culture report saved.")
