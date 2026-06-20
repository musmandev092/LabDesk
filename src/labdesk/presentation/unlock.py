"""Database unlock / first-run password dialogs, shown before the main window.

The live database is encrypted with SQLCipher; these collect the passphrase that
unlocks it. There is NO recovery — a lost passphrase means the data is gone — so the
set/confirm dialog warns clearly.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .. import db
from ..db import keyvault
from .style import PRODUCT_NAME
from .widgets import toast_warn


def _remember_checkbox() -> QCheckBox | None:
    """A 'remember on this computer' checkbox, or None when no system wallet is
    available (KDE Wallet / GNOME Keyring). Stores the key so the password isn't
    retyped every launch — protected by the OS login session."""
    if not keyvault.available():
        return None
    cb = QCheckBox("Remember on this computer (uses your system wallet)")
    cb.setToolTip(
        "Saves the password in your KDE Wallet / GNOME Keyring so LabDesk opens "
        "without asking. Unlocked by your OS login; a copied database stays protected."
    )
    return cb


class UnlockDialog(QDialog):
    """Prompt for the DB passphrase to open an existing encrypted database."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.passphrase: str | None = None
        self.remember = False
        self.setWindowTitle(f"{PRODUCT_NAME} — Unlock")
        self.setModal(True)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Enter the database password to open LabDesk."))
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("Database password")
        self.pw.setMinimumWidth(300)
        self.pw.setMinimumHeight(36)
        lay.addWidget(self.pw)
        self._remember_cb = _remember_checkbox()
        if self._remember_cb is not None:
            lay.addWidget(self._remember_cb)
        row = QHBoxLayout()
        row.addStretch(1)
        quit_btn = QPushButton("Quit")
        quit_btn.clicked.connect(self.reject)
        ok = QPushButton("Unlock")
        ok.setDefault(True)
        ok.clicked.connect(self._try)
        row.addWidget(quit_btn)
        row.addWidget(ok)
        lay.addLayout(row)
        self.pw.returnPressed.connect(self._try)

    def _try(self) -> None:
        pw = self.pw.text()
        if pw and db.verify_passphrase(pw):
            self.passphrase = pw
            self.remember = bool(self._remember_cb and self._remember_cb.isChecked())
            self.accept()
        else:
            toast_warn(self, "Unlock", "Wrong password — try again.")
            self.pw.selectAll()
            self.pw.setFocus()


class SetPasswordDialog(QDialog):
    """First run / migration: choose the DB passphrase, with a data-loss warning."""

    def __init__(self, parent=None, *, migrating: bool = False) -> None:
        super().__init__(parent)
        self.passphrase: str | None = None
        self.remember = False
        self.setWindowTitle(f"{PRODUCT_NAME} — Set database password")
        self.setModal(True)
        lay = QVBoxLayout(self)
        intro = (
            "Your existing data will be encrypted with this password."
            if migrating
            else "Choose a password to encrypt this computer's LabDesk database."
        )
        lbl = QLabel(intro)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        warn = QLabel(
            "⚠  Keep this password safe. It CANNOT be recovered — if it is lost, the "
            "data cannot be opened by anyone, including the developer."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#b9770e; font-weight:600;")
        lay.addWidget(warn)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("New database password")
        self.pw.setMinimumWidth(320)
        self.pw.setMinimumHeight(36)
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.Password)
        self.pw2.setPlaceholderText("Confirm password")
        self.pw2.setMinimumHeight(36)
        lay.addWidget(self.pw)
        lay.addWidget(self.pw2)
        self._remember_cb = _remember_checkbox()
        if self._remember_cb is not None:
            lay.addWidget(self._remember_cb)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Set password")
        ok.setDefault(True)
        ok.clicked.connect(self._try)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def _try(self) -> None:
        pw = self.pw.text()
        if len(pw) < 6:
            toast_warn(self, "Database password", "Use at least 6 characters.")
            return
        if pw != self.pw2.text():
            toast_warn(self, "Database password", "The two passwords don't match.")
            return
        self.passphrase = pw
        self.remember = bool(self._remember_cb and self._remember_cb.isChecked())
        self.accept()


class ChangePasswordDialog(QDialog):
    """Change the database password: current + new + confirm, with the
    backup-compatibility warning."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.current: str | None = None
        self.new: str | None = None
        self.setWindowTitle(f"{PRODUCT_NAME} — Change database password")
        self.setModal(True)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Change the password that encrypts the database."))
        self.cur = QLineEdit()
        self.cur.setEchoMode(QLineEdit.Password)
        self.cur.setPlaceholderText("Current database password")
        self.cur.setMinimumWidth(340)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("New password")
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.Password)
        self.pw2.setPlaceholderText("Confirm new password")
        for w in (self.cur, self.pw, self.pw2):
            w.setMinimumHeight(36)
            lay.addWidget(w)
        warn = QLabel(
            "⚠  Backups made before this change will still need the OLD password to "
            "restore. The new password cannot be recovered if it is lost."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#b9770e; font-weight:600;")
        lay.addWidget(warn)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Change password")
        ok.setDefault(True)
        ok.clicked.connect(self._try)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def _try(self) -> None:
        if len(self.pw.text()) < 6:
            toast_warn(
                self, "Database password", "New password must be at least 6 characters."
            )
            return
        if self.pw.text() != self.pw2.text():
            toast_warn(self, "Database password", "The new passwords don't match.")
            return
        self.current = self.cur.text()
        self.new = self.pw.text()
        self.accept()
