"""Database unlock / first-run password dialogs, shown before the main window.

The live database is encrypted with SQLCipher; these collect the passphrase that
unlocks it. There is NO recovery — a lost passphrase means the data is gone — so the
set/confirm dialog warns clearly.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
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


class FirstRunDialog(QDialog):
    """First run (after activation): start a brand-new laboratory, or restore from a
    backup (e.g. moving to a new computer). Sets ``self.choice`` to 'new' | 'restore'."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.choice: str | None = None
        self.setWindowTitle(f"{PRODUCT_NAME} — Set up")
        self.setModal(True)
        lay = QVBoxLayout(self)
        title = QLabel("Welcome to LabDesk")
        title.setStyleSheet("font-size:16px; font-weight:800;")
        lay.addWidget(title)
        sub = QLabel(
            "Is this a brand-new laboratory, or are you restoring from a backup "
            "(for example, setting up a new computer)?"
        )
        sub.setWordWrap(True)
        lay.addWidget(sub)
        new_btn = QPushButton("Start a new laboratory")
        new_btn.setMinimumHeight(44)
        new_btn.clicked.connect(lambda: self._pick("new"))
        rst_btn = QPushButton("Restore from a backup")
        rst_btn.setObjectName("ghost")
        rst_btn.setMinimumHeight(44)
        rst_btn.clicked.connect(lambda: self._pick("restore"))
        lay.addWidget(new_btn)
        lay.addWidget(rst_btn)
        row = QHBoxLayout()
        row.addStretch(1)
        quit_btn = QPushButton("Quit")
        quit_btn.setObjectName("ghost")
        quit_btn.clicked.connect(self.reject)
        row.addWidget(quit_btn)
        lay.addLayout(row)

    def _pick(self, choice: str) -> None:
        self.choice = choice
        self.accept()


class RestoreBackupDialog(QDialog):
    """Pick a LabDesk backup file + the password it was saved with, validated before
    accepting. Exposes ``path``, ``passphrase`` and ``remember`` for the caller to
    install the backup as the live DB."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.path: str | None = None
        self.passphrase: str | None = None
        self.remember = False
        self.setWindowTitle(f"{PRODUCT_NAME} — Restore from backup")
        self.setModal(True)
        lay = QVBoxLayout(self)
        lay.addWidget(
            QLabel(
                "Choose a LabDesk backup file and enter the password it was saved with."
            )
        )
        frow = QHBoxLayout()
        self.file_lbl = QLineEdit()
        self.file_lbl.setReadOnly(True)
        self.file_lbl.setPlaceholderText("No backup selected")
        self.file_lbl.setMinimumWidth(320)
        self.file_lbl.setMinimumHeight(36)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        frow.addWidget(self.file_lbl, 1)
        frow.addWidget(browse)
        lay.addLayout(frow)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("Backup password")
        self.pw.setMinimumHeight(36)
        lay.addWidget(self.pw)
        note = QLabel(
            "Use the password this backup was encrypted with (it may differ from a "
            "new one). It becomes this computer's database password."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#6b7280; font-size:12px;")
        lay.addWidget(note)
        self._remember_cb = _remember_checkbox()
        if self._remember_cb is not None:
            lay.addWidget(self._remember_cb)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Restore")
        ok.setDefault(True)
        ok.clicked.connect(self._try)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose backup",
            str(Path.home()),
            "LabDesk backup (*.sqlite);;All files (*)",
        )
        if path:
            self.path = path
            self.file_lbl.setText(path)

    def _try(self) -> None:
        from ..db.backup import _looks_like_labdesk_db

        if not self.path:
            toast_warn(self, "Restore", "Choose a backup file first.")
            return
        pw = self.pw.text()
        if not pw:
            toast_warn(self, "Restore", "Enter the backup's password.")
            return
        if not _looks_like_labdesk_db(Path(self.path), pw):
            toast_warn(
                self,
                "Restore",
                "Couldn't open this backup with that password.\n"
                "Check the file and password and try again.",
            )
            return
        self.passphrase = pw
        self.remember = bool(self._remember_cb and self._remember_cb.isChecked())
        self.accept()


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
