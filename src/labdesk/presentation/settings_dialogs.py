"""Dialogs used by the Settings page — extracted from settings.py to keep that
page focused. ``UserDialog`` collects a new user's details; ``TempPasswordDialog``
shows a one-time temporary password in a persistent, copyable form."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..roles import ROLES
from .widgets import muted


class UserDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New user")
        self.setMinimumWidth(440)
        form = QFormLayout(self)
        self.username = QLineEdit()
        self.full_name = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.role = QComboBox()
        for key, (lvl, label, desc) in sorted(ROLES.items(), key=lambda kv: kv[1][0]):
            self.role.addItem(f"{label} — {desc}", key)
        self.role.setCurrentIndex(0)  # default Receptionist (lowest)
        form.addRow("Username *", self.username)
        form.addRow("Full name", self.full_name)
        form.addRow("Password *", self.password)
        form.addRow("Role", self.role)
        btns = QHBoxLayout()
        ok = QPushButton("Create")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        form.addRow(btns)

    def values(self) -> dict[str, str]:
        return {
            "username": self.username.text().strip(),
            "full_name": self.full_name.text().strip(),
            "password": self.password.text(),
            "role": self.role.currentData(),
        }


class TempPasswordDialog(QDialog):
    """Show a one-time temporary password in a persistent, copyable form.

    A toast would auto-dismiss after a few seconds — far too easy to miss a
    single-use credential the admin has to hand to a user — so this stays open
    until they close it, with the password selectable and a one-click Copy.
    """

    def __init__(self, username: str, temp: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Temporary password")
        self.setMinimumWidth(440)
        col = QVBoxLayout(self)
        col.setSpacing(10)
        head = QLabel(f"Temporary password for <b>{username}</b>:")
        head.setTextFormat(Qt.RichText)
        col.addWidget(head)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        field = QLineEdit(temp)
        field.setReadOnly(True)
        field.setCursorPosition(0)
        f = field.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 2)
        field.setFont(f)
        copy = QPushButton("Copy")
        copy.setObjectName("ghost")

        def _copy() -> None:
            QApplication.clipboard().setText(temp)
            copy.setText("Copied ✓")

        copy.clicked.connect(_copy)
        row.addWidget(field, 1)
        row.addWidget(copy)
        col.addLayout(row)

        col.addWidget(
            muted("Give this to the user. They must set a new password at next login.")
        )
        ok = QPushButton("Done")
        ok.clicked.connect(self.accept)
        bar = QHBoxLayout()
        bar.addStretch(1)
        bar.addWidget(ok)
        col.addLayout(bar)
