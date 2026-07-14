"""Login dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .. import __version__, db
from .style import DEVELOPER, DEVELOPER_GITHUB, PRODUCT_NAME, PRODUCT_TAGLINE
from .widgets import toast_info, toast_warn


class LoginDialog(QDialog):
    def __init__(self, con, parent=None) -> None:
        super().__init__(parent)
        self.con = con
        self.user = None
        lab = db.get_setting(con, "lab_name", "") or PRODUCT_NAME
        self.setWindowTitle(f"Sign in — {lab}")
        self.setMinimumSize(420, 560)

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
        # avoid double-firing try_login via returnPressed + default-button activation
        btn.setAutoDefault(False)
        btn.setDefault(False)
        btn.clicked.connect(self.try_login)
        outer.addWidget(btn)
        outer.addStretch(2)

        credit = QLabel(
            f"{PRODUCT_NAME} v{__version__}  ·  Developed by {DEVELOPER}  ·  {DEVELOPER_GITHUB}"
        )
        credit.setObjectName("muted")
        credit.setAlignment(Qt.AlignCenter)
        credit.setWordWrap(True)
        credit.setStyleSheet("font-size: 11px;")
        outer.addWidget(credit)

        self.password.returnPressed.connect(self.try_login)
        self.username.returnPressed.connect(lambda: self.password.setFocus())
        self.username.setFocus()

    def try_login(self) -> None:
        u = self.username.text().strip()
        p = self.password.text()
        rem = db.lock_remaining(self.con, u)
        if rem:
            toast_warn(
                self,
                "Sign in",
                f"Too many failed attempts. Try again in {rem} second(s).",
            )
            return
        user = db.verify_user(self.con, u, p)
        if user:
            db.log_audit(self.con, user["username"], "login", "signed in")
            if "must_change_password" in user.keys() and user["must_change_password"]:
                if not self._force_password_change(user):
                    return
            self.user = user
            self.accept()
        else:
            # attempted username goes in DETAIL, not the username column (log-injection)
            db.log_audit(
                self.con,
                "(unauthenticated)",
                "login_failed",
                f"attempted username: {u or '(blank)'}",
            )
            rem2 = db.lock_remaining(self.con, u)
            if rem2:
                toast_warn(
                    self,
                    "Sign in",
                    f"Too many failed attempts. Locked for {rem2} second(s).",
                )
            else:
                toast_warn(self, "Sign in", "Invalid username or password.")
            self.password.clear()
            self.password.setFocus()

    def _force_password_change(self, user) -> bool:
        """Make a user with must_change_password set a new one before entering."""
        toast_info(
            self,
            "Set a new password",
            "For security, please set a new password before continuing.",
        )
        while True:
            pw, ok = QInputDialog.getText(
                self,
                "New password",
                "New password (at least 6 characters):",
                QLineEdit.Password,
            )
            if not ok:
                return False
            pw = pw.strip()
            if len(pw) < 6:
                toast_warn(self, "Password", "Password must be at least 6 characters.")
                continue
            if pw.lower() == "admin":
                toast_warn(self, "Password", "Please choose a different password.")
                continue
            h, salt = db.hash_password(pw)
            self.con.execute(
                "UPDATE users SET pass_hash=?, salt=?, must_change_password=0 WHERE id=?",
                (h, salt, user["id"]),
            )
            self.con.commit()
            db.log_audit(
                self.con,
                user["username"],
                "password_changed",
                "forced first-login change",
            )
            return True
