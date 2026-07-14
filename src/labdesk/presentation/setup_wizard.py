"""First-run setup wizard — collects each lab's branding + admin password."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import db
from .style import PRODUCT_NAME
from .widgets import field_label, fit_to_screen, toast_warn


class SetupWizard(QDialog):
    def __init__(self, con, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.con = con
        self.setWindowTitle(f"Welcome to {PRODUCT_NAME}")
        # small floor fits a 1366x768 laptop; the form scrolls (QScrollArea below)
        self.setMinimumSize(560, 480)
        fit_to_screen(self, 700, 880)

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 28)
        root.setSpacing(6)

        mark = QLabel(PRODUCT_NAME[:2].upper())
        mark.setObjectName("brandMark")
        mark.setFixedSize(64, 64)
        mark.setAlignment(Qt.AlignCenter)
        root.addWidget(mark, 0, Qt.AlignHCenter)

        title = QLabel("Set up your laboratory")
        title.setObjectName("authTitle")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)
        sub = QLabel(
            "This information appears on screens and on every printed report.\n"
            "You can change it later in Settings."
        )
        sub.setObjectName("muted")
        sub.setAlignment(Qt.AlignCenter)
        root.addWidget(sub)
        root.addSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QFrame()
        host.setObjectName("authCard")
        grid = QGridLayout(host)
        grid.setContentsMargins(26, 24, 26, 24)
        grid.setSpacing(12)
        grid.setColumnStretch(1, 1)

        self.fields: dict[str, QLineEdit] = {}
        r = 0

        def add(
            key: str, label: str, placeholder: str = "", required: bool = False
        ) -> QLineEdit:
            nonlocal r
            grid.addWidget(field_label(label + (" *" if required else "")), r, 0)
            le = QLineEdit()
            le.setPlaceholderText(placeholder)
            self.fields[key] = le
            grid.addWidget(le, r, 1)
            r += 1
            return le

        add("lab_name", "Laboratory name", "e.g. City Diagnostic Lab", required=True)
        add(
            "lab_subtitle",
            "Tagline / subtitle",
            "e.g. Pathology • Microbiology • Radiology",
        )
        add("address", "Address", "Street, City")
        add("phone", "Phone", "Landline")
        add("mobile", "Mobile", "Mobile / WhatsApp")
        add("email", "Email", "lab@example.com")
        add(
            "phc_reg_no",
            "PHC registration no.",
            "Punjab Healthcare Commission reg. no.",
        )
        add("lab_reg_no", "Lab registration no.", "Lab / pharmacy registration no.")
        add("currency", "Currency symbol", "Rs.")
        add(
            "lab_no_prefix",
            "Receipt no. prefix",
            "e.g. LAB → receipts numbered LAB-00001, LAB-00002 …",
        )
        self.fields["currency"].setText("Rs.")
        self.fields["lab_no_prefix"].setText("LAB")

        grid.addWidget(field_label("Logo (optional)"), r, 0)
        logo_row = QHBoxLayout()
        self.logo = QLineEdit()
        self.logo.setReadOnly(True)
        self.logo.setPlaceholderText("No logo selected")
        pick = QPushButton("Choose…")
        pick.setObjectName("ghost")
        pick.clicked.connect(self._pick_logo)
        logo_row.addWidget(self.logo)
        logo_row.addWidget(pick)
        lw = QWidget()
        lw.setLayout(logo_row)
        grid.addWidget(lw, r, 1)
        r += 1

        # blank uses the Documents fallback
        grid.addWidget(field_label("Backup folder (optional)"), r, 0)
        bk_row = QHBoxLayout()
        self.backup_dir = QLineEdit()
        self.backup_dir.setReadOnly(True)
        self.backup_dir.setPlaceholderText(f"Default: {db.fallback_backup_dir()}")
        bpick = QPushButton("Choose…")
        bpick.setObjectName("ghost")
        bpick.clicked.connect(self._pick_backup_dir)
        bk_row.addWidget(self.backup_dir)
        bk_row.addWidget(bpick)
        bw = QWidget()
        bw.setLayout(bk_row)
        grid.addWidget(bw, r, 1)
        r += 1

        sep = QLabel("Administrator account")
        sep.setStyleSheet("font-weight:700; margin-top:8px;")
        grid.addWidget(sep, r, 0, 1, 2)
        r += 1
        grid.addWidget(field_label("Administrator name *"), r, 0)
        self.admin_name = QLineEdit()
        self.admin_name.setPlaceholderText("e.g. Dr. Imran Ali")
        grid.addWidget(self.admin_name, r, 1)
        r += 1
        grid.addWidget(field_label("Login username *"), r, 0)
        self.admin_user = QLineEdit()
        self.admin_user.setText("admin")
        grid.addWidget(self.admin_user, r, 1)
        r += 1
        grid.addWidget(field_label("New password *"), r, 0)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("Set an admin password")
        grid.addWidget(self.pw, r, 1)
        r += 1
        grid.addWidget(field_label("Confirm password *"), r, 0)
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.Password)
        grid.addWidget(self.pw2, r, 1)
        r += 1

        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        finish = QPushButton("Finish setup  →")
        finish.clicked.connect(self._finish)
        btns.addWidget(finish)
        root.addLayout(btns)

    def _pick_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose logo", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if path:
            self.logo.setText(path)

    def _pick_backup_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose backup folder", "")
        if path:
            self.backup_dir.setText(path)

    def _finish(self) -> None:
        name = self.fields["lab_name"].text().strip()
        if not name:
            toast_warn(self, "Setup", "Please enter your laboratory name.")
            return
        admin_name = self.admin_name.text().strip()
        username = self.admin_user.text().strip() or "admin"
        if not admin_name:
            toast_warn(self, "Setup", "Please enter the administrator's name.")
            return
        pw = self.pw.text()
        if len(pw) < 6:
            toast_warn(self, "Setup", "Admin password must be at least 6 characters.")
            return
        if pw.lower() == "admin":
            toast_warn(
                self, "Setup", "Please choose a stronger password (not 'admin')."
            )
            return
        if pw != self.pw2.text():
            toast_warn(self, "Setup", "Passwords do not match.")
            return
        c = self.con
        for key, le in self.fields.items():
            db.set_setting(c, key, le.text().strip())
        db.set_setting(c, "logo_path", self.logo.text().strip())
        db.set_setting(c, "backup_dir", self.backup_dir.text().strip())
        db.set_setting(c, "configured", "1")
        h, salt = db.hash_password(pw)
        # admin set their own password here → clear the forced-change flag
        c.execute(
            "UPDATE users SET username=?, full_name=?, pass_hash=?, salt=?, "
            "must_change_password=0 WHERE username='admin'",
            (username, admin_name, h, salt),
        )
        c.commit()
        db.log_audit(
            c,
            username,
            "setup_completed",
            f"first-run setup by {admin_name or username}",
        )
        self.accept()
