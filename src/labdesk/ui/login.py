"""Login dialog."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QPushButton, QLabel, QMessageBox, QFrame,
)

from .. import db
from .style import PRODUCT_NAME, PRODUCT_TAGLINE


class LoginDialog(QDialog):
    def __init__(self, con, parent=None):
        super().__init__(parent)
        self.con = con
        self.user = None
        lab = db.get_setting(con, "lab_name", "") or PRODUCT_NAME
        self.setWindowTitle(f"Sign in — {lab}")
        self.setMinimumWidth(420)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(0)

        mark = QLabel((lab[:2] or PRODUCT_NAME[:2]).upper())
        mark.setObjectName("brandMark")
        mark.setFixedSize(60, 60)
        mark.setAlignment(Qt.AlignCenter)
        outer.addWidget(mark, 0, Qt.AlignHCenter)
        outer.addSpacing(14)

        title = QLabel(lab)
        title.setObjectName("authTitle")
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        outer.addWidget(title)
        sub = QLabel(db.get_setting(con, "lab_subtitle", "") or PRODUCT_TAGLINE)
        sub.setObjectName("muted")
        sub.setAlignment(Qt.AlignCenter)
        outer.addWidget(sub)
        outer.addSpacing(20)
        outer.addStretch(1)

        self.username = QLineEdit()
        self.username.setPlaceholderText("Username")
        outer.addWidget(self.username)
        outer.addSpacing(10)

        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.Password)
        outer.addWidget(self.password)
        outer.addSpacing(18)

        btn = QPushButton("Sign in")
        btn.setMinimumHeight(42)
        btn.clicked.connect(self.try_login)
        outer.addWidget(btn)
        outer.addStretch(2)

        self.password.returnPressed.connect(self.try_login)
        self.username.returnPressed.connect(lambda: self.password.setFocus())
        self.username.setFocus()

    def try_login(self):
        u = self.username.text().strip()
        p = self.password.text()
        user = db.verify_user(self.con, u, p)
        if user:
            self.user = user
            self.accept()
        else:
            QMessageBox.warning(self, "Sign in", "Invalid username or password.")
            self.password.clear()
            self.password.setFocus()
