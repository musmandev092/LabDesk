"""Doctors: referring-doctor directory with add/edit/delete."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QDialog, QFormLayout, QLineEdit, QMessageBox, QHeaderView, QLabel,
)

from .widgets import page_header
from .. import db
from ..roles import can


class DoctorDialog(QDialog):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        title = "Edit doctor" if data else "Add doctor"
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        form = QFormLayout(self)
        heading = QLabel(title); heading.setObjectName("h2")
        form.addRow(heading)
        self.name = QLineEdit()
        self.hospital = QLineEdit()
        self.area = QLineEdit()
        self.tel = QLineEdit()
        self.mobile = QLineEdit()
        form.addRow("Name *", self.name)
        form.addRow("Hospital", self.hospital)
        form.addRow("Area", self.area)
        form.addRow("Phone", self.tel)
        form.addRow("Mobile", self.mobile)
        if data:
            self.name.setText(data["name"] or "")
            self.hospital.setText(data["hospital"] or "")
            self.area.setText(data["area"] or "")
            self.tel.setText(data["tel"] or "")
            self.mobile.setText(data["mobile"] or "")
        btns = QHBoxLayout()
        ok = QPushButton("Save"); ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel"); cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        btns.addStretch(1); btns.addWidget(cancel); btns.addWidget(ok)
        form.addRow(btns)

    def values(self):
        return {
            "name": self.name.text().strip(),
            "hospital": self.hospital.text().strip(),
            "area": self.area.text().strip(),
            "tel": self.tel.text().strip(),
            "mobile": self.mobile.text().strip(),
        }


class DoctorsPage(QWidget):
    def __init__(self, con, user):
        super().__init__()
        self.con = con
        self.user = user
        self._ids = []   # parallel to doctors table rows; filled by refresh
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        add = QPushButton("+ Add doctor"); add.clicked.connect(self.add)
        self.edit_btn = QPushButton("Edit"); self.edit_btn.setObjectName("ghost"); self.edit_btn.clicked.connect(self.edit)
        self.del_btn = QPushButton("Delete"); self.del_btn.setObjectName("danger"); self.del_btn.clicked.connect(self.delete)
        self.edit_btn.setEnabled(False); self.del_btn.setEnabled(False)
        header, _ = page_header("Referring Doctors", "", add, self.edit_btn, self.del_btn)
        lay.addWidget(header)

        self.search = QLineEdit(); self.search.setPlaceholderText("Search doctors…")
        self.search.setMinimumHeight(40)
        self.search.textChanged.connect(self.refresh)
        lay.addWidget(self.search)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "Hospital", "Area", "Phone", "Mobile"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self.edit)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        lay.addWidget(self.table, 1)
        self._ids = []

    def _update_buttons(self):
        has = self.table.currentRow() >= 0 and self.table.currentRow() < len(self._ids)
        self.edit_btn.setEnabled(has); self.del_btn.setEnabled(has)

    def on_show(self):
        self.refresh()

    def refresh(self):
        q = f"%{self.search.text().strip()}%"
        rows = self.con.execute(
            "SELECT * FROM doctors WHERE active=1 AND (name LIKE ? OR hospital LIKE ?)"
            " ORDER BY name", (q, q),
        ).fetchall()
        self.table.setRowCount(0)
        self._ids = []
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            self._ids.append(r["id"])
            for col, key in enumerate(["name", "hospital", "area", "tel", "mobile"]):
                self.table.setItem(i, col, QTableWidgetItem(r[key] or ""))

    def _selected_id(self):
        r = self.table.currentRow()
        return self._ids[r] if 0 <= r < len(self._ids) else None

    def add(self):
        d = DoctorDialog(self)
        if d.exec() == QDialog.Accepted:
            v = d.values()
            if not v["name"]:
                return
            self.con.execute(
                "INSERT INTO doctors(name,hospital,area,tel,mobile) VALUES (?,?,?,?,?)",
                (v["name"], v["hospital"], v["area"], v["tel"], v["mobile"]),
            )
            self.con.commit()
            db.log_audit(self.con, self.user["username"], "doctor_created", v["name"])
            self.refresh()

    def edit(self):
        did = self._selected_id()
        if did is None:
            return
        row = self.con.execute("SELECT * FROM doctors WHERE id=?", (did,)).fetchone()
        d = DoctorDialog(self, row)
        if d.exec() == QDialog.Accepted:
            v = d.values()
            if not v["name"]:
                QMessageBox.warning(self, "Doctor", "Name cannot be empty.")
                return
            self.con.execute(
                "UPDATE doctors SET name=?,hospital=?,area=?,tel=?,mobile=? WHERE id=?",
                (v["name"], v["hospital"], v["area"], v["tel"], v["mobile"], did),
            )
            self.con.commit()
            db.log_audit(self.con, self.user["username"], "doctor_updated", v["name"])
            self.refresh()

    def delete(self):
        did = self._selected_id()
        if did is None:
            return
        if not can(self.user["role"], "delete"):
            QMessageBox.warning(self, "Delete", "You don't have permission to delete doctors.")
            return
        if QMessageBox.question(self, "Delete", "Delete this doctor?") == QMessageBox.Yes:
            row = self.con.execute("SELECT name FROM doctors WHERE id=?", (did,)).fetchone()
            self.con.execute("UPDATE doctors SET active=0 WHERE id=?", (did,))
            self.con.commit()
            db.log_audit(self.con, self.user["username"], "doctor_deleted",
                         (row["name"] if row else str(did)))
            self.refresh()
