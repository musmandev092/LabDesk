"""Login dialog."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QPushButton, QLabel, QMessageBox, QInputDialog,
)

from .. import db, __version__
from .style import PRODUCT_NAME, PRODUCT_TAGLINE, DEVELOPER, DEVELOPER_GITHUB


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
        # Don't let the button auto-activate on Enter: otherwise pressing Enter in
        # the password field fires BOTH returnPressed AND this default button, so
        # try_login runs twice (two "Invalid username or password" popups).
        btn.setAutoDefault(False)
        btn.setDefault(False)
        btn.clicked.connect(self.try_login)
        outer.addWidget(btn)
        outer.addStretch(2)

        credit = QLabel(
            f"{PRODUCT_NAME} v{__version__}  ·  Developed by {DEVELOPER}  ·  {DEVELOPER_GITHUB}")
        credit.setObjectName("muted")
        credit.setAlignment(Qt.AlignCenter)
        outer.addWidget(credit)

        # Enter: username → move to password; password → sign in (once).
        self.password.returnPressed.connect(self.try_login)
        self.username.returnPressed.connect(lambda: self.password.setFocus())
        self.username.setFocus()

    def try_login(self):
        u = self.username.text().strip()
        p = self.password.text()
        rem = db.lock_remaining(self.con, u)
        if rem:
            QMessageBox.warning(self, "Sign in",
                                f"Too many failed attempts. Try again in {rem} second(s).")
            return
        user = db.verify_user(self.con, u, p)
        if user:
            db.log_audit(self.con, user["username"], "login", "signed in")
            if "must_change_password" in user.keys() and user["must_change_password"]:
                if not self._force_password_change(user):
                    return                       # cancelled → stay on the login screen
            self.user = user
            self.accept()
        else:
            # store the attacker-controlled username in DETAIL, not the username
            # column (log-injection / misleading actor), and surface lockout.
            db.log_audit(self.con, "(unauthenticated)", "login_failed",
                         f"attempted username: {u or '(blank)'}")
            rem2 = db.lock_remaining(self.con, u)
            if rem2:
                QMessageBox.warning(self, "Sign in",
                                    f"Too many failed attempts. Locked for {rem2} second(s).")
            else:
                QMessageBox.warning(self, "Sign in", "Invalid username or password.")
            self.password.clear()
            self.password.setFocus()

    def _force_password_change(self, user) -> bool:
        """Make a user with must_change_password set a new one before entering."""
        QMessageBox.information(self, "Set a new password",
                               "For security, please set a new password before continuing.")
        while True:
            pw, ok = QInputDialog.getText(self, "New password",
                                          "New password (at least 6 characters):",
                                          QLineEdit.Password)
            if not ok:
                return False
            pw = pw.strip()
            if len(pw) < 6:
                QMessageBox.warning(self, "Password", "Password must be at least 6 characters.")
                continue
            if pw.lower() == "admin":
                QMessageBox.warning(self, "Password", "Please choose a different password.")
                continue
            h, salt = db.hash_password(pw)
            self.con.execute(
                "UPDATE users SET pass_hash=?, salt=?, must_change_password=0 WHERE id=?",
                (h, salt, user["id"]))
            self.con.commit()
            db.log_audit(self.con, user["username"], "password_changed",
                         "forced first-login change")
            return True
