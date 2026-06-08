"""Settings: lab branding, registration, report footer, WhatsApp, security."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtPrintSupport import QPrinterInfo
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, db, report, whatsapp
from ..roles import ROLES, can, role_label
from . import tasks
from .style import (
    DEVELOPER,
    DEVELOPER_EMAILS,
    DEVELOPER_GITHUB,
    PRODUCT_NAME,
    PRODUCT_TAGLINE,
    apply_theme,
)
from .widgets import card, field_label, max_width_center, muted, page_header

_LABEL_W = 200  # shared label-column width so all settings cards align


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


# (key, label) — plain text settings grouped per section
LAB_FIELDS: list[tuple[str, ...]] = [
    ("lab_name", "Lab name"),
    ("lab_subtitle", "Subtitle / tagline"),
    ("address", "Address"),
    ("phone", "Phone"),
    ("mobile", "Mobile"),
    ("email", "Email"),
    ("currency", "Currency symbol"),
    ("lab_no_prefix", "Lab no. prefix"),
]
REG_FIELDS: list[tuple[str, ...]] = [
    ("phc_reg_no", "PHC registration no."),
    ("lab_reg_no", "Lab registration no."),
]
PROMO_FIELDS: list[tuple[str, ...]] = [
    ("promo_discount_pct", "Special-day discount %", "0 = off"),
    ("promo_until", "Promo active until", "YYYY-MM-DD (blank = no end)"),
]
REPORT_FIELDS: list[tuple[str, ...]] = [
    ("report_footer", "Report footer line"),
    ("dept_band", "Department band"),
    ("signatory_1_name", "Signatory 1 — name"),
    ("signatory_1_title", "Signatory 1 — title"),
    ("signatory_2_name", "Signatory 2 — name"),
    ("signatory_2_title", "Signatory 2 — title"),
]
RECEIPT_FIELDS: list[tuple[str, ...]] = [
    ("receipt_remarks", "Remarks line", "Shown under the bill's Remarks heading"),
    ("receipt_footer_note", "Footer note", "Small italic line at the bottom of the bill"),
]
LOGO_FIELDS = [
    ("logo_path", "Main logo"),
    ("accred_logo_1", "Secondary logo"),
]
WHATSAPP_FIELDS: list[tuple[str, ...]] = [
    ("whatsapp_url", "Gateway URL", "http://localhost:8080"),
    ("whatsapp_api_key", "Access token", "wuzapi user token"),
    ("whatsapp_country_code", "Country code", "92"),
    ("whatsapp_timeout", "Upload timeout (sec)", "40"),
    ("whatsapp_report_caption", "Report caption", "{lab} — Report {lab_no} for {name}"),
    ("whatsapp_receipt_caption", "Receipt caption", "{lab} — Receipt {lab_no} for {name}"),
]


class SettingsPage(QWidget):
    def __init__(self, con, user) -> None:
        super().__init__()
        self.con = con
        self.user = user
        self._user_ids: list[int] = []  # parallel to users_table rows; filled by refresh_users
        self.inputs: dict[str, QLineEdit] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        header, _ = page_header("Settings", "Branding, registration and report options")
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        col = QVBoxLayout(host)
        col.setSpacing(14)

        col.addWidget(self._appearance_card())
        col.addWidget(self._text_card("Laboratory information", LAB_FIELDS))
        col.addWidget(self._text_card("Registration & accreditation", REG_FIELDS))
        col.addWidget(self._logo_card())
        col.addWidget(self._printer_card())
        col.addWidget(self._text_card("Special-day discount", PROMO_FIELDS))
        col.addWidget(self._text_card("Report footer", REPORT_FIELDS))
        col.addWidget(self._text_card("Receipt footer", RECEIPT_FIELDS))
        col.addWidget(self._whatsapp_card())
        col.addWidget(self._security_card())
        # Backup/restore replaces the entire database — gate it behind an explicit
        # admin capability rather than mere Settings-page visibility.
        if can(self.user["role"], "manage_backups"):
            col.addWidget(self._backup_card())
        if can(self.user["role"], "manage_users"):
            col.addWidget(self._users_card())
        col.addWidget(self._about_card())
        col.addStretch(1)

        # Cap the form at a readable width and centre it: without this the fields
        # (AllNonFixedFieldsGrow) overflow the right edge at 1280 and stretch to
        # ~3300 px on 4K. The centred max-width wrapper fixes BOTH at once.
        scroll.setWidget(max_width_center(host, 880))
        root.addWidget(scroll, 1)

        save = QPushButton("Save settings")
        save.setMinimumHeight(42)
        save.clicked.connect(self.save)
        root.addWidget(save)

    # ---- builders ----
    def _flbl(self, text: str) -> QLabel:
        lbl = field_label(text)
        lbl.setFixedWidth(_LABEL_W)
        lbl.setWordWrap(True)  # never clip a long label
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return lbl

    def _form(self) -> QFormLayout:
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        return form

    def _add_field(self, form: QFormLayout, field: tuple[str, ...]) -> QLineEdit:
        """field = (key, label[, placeholder]) -> a QLineEdit row."""
        key, label = field[0], field[1]
        le = QLineEdit()
        if len(field) > 2 and field[2]:
            le.setPlaceholderText(field[2])
        self.inputs[key] = le
        form.addRow(self._flbl(label), le)
        return le

    def _text_card(self, title: str, fields: list[tuple[str, ...]]) -> QWidget:
        form = self._form()
        for f in fields:
            self._add_field(form, f)
        w = QWidget()
        w.setLayout(form)
        return card(w, title=title)

    def _about_card(self) -> QWidget:
        """Product + developer credit (the lab's own branding is set above; this
        is the fixed credit for whoever built the software)."""
        col = QVBoxLayout()
        col.setSpacing(6)
        prod = QLabel(f"<b>{PRODUCT_NAME}</b> v{__version__} — {PRODUCT_TAGLINE}")
        prod.setTextInteractionFlags(Qt.TextSelectableByMouse)
        col.addWidget(prod)
        emails = "  ·  ".join(f"<a href='mailto:{e}'>{e}</a>" for e in DEVELOPER_EMAILS)
        info = QLabel(
            f"Developed by <b>{DEVELOPER}</b><br>"
            f"GitHub: <a href='https://{DEVELOPER_GITHUB}'>{DEVELOPER_GITHUB}</a><br>"
            f"Email: {emails}"
        )
        info.setTextFormat(Qt.RichText)
        info.setOpenExternalLinks(True)
        info.setTextInteractionFlags(Qt.TextBrowserInteraction)
        col.addWidget(info)
        w = QWidget()
        w.setLayout(col)
        return card(w, title="About")

    def _logo_card(self) -> QWidget:
        form = self._form()
        for key, label in LOGO_FIELDS:
            le = QLineEdit()
            le.setReadOnly(True)
            self.inputs[key] = le
            btn = QPushButton("Choose…")
            btn.setObjectName("ghost")
            btn.clicked.connect(lambda _=False, k=key: self._pick(k))
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(le, 1)
            row.addWidget(btn)
            rw = QWidget()
            rw.setLayout(row)
            form.addRow(self._flbl(label), rw)
        w = QWidget()
        w.setLayout(form)
        return card(w, title="Logos")

    def _printer_card(self) -> QWidget:
        form = self._form()
        self.printer_combo = QComboBox()
        self.printer_combo.addItem("Ask each time (show print dialog)", "")
        for name in QPrinterInfo.availablePrinterNames():
            self.printer_combo.addItem(name, name)
        form.addRow(self._flbl("Default printer"), self.printer_combo)
        test = QPushButton("Print test page")
        test.setObjectName("ghost")
        test.clicked.connect(self._test_printer)
        form.addRow("", test)
        w = QWidget()
        w.setLayout(form)
        return card(
            muted(
                "Pick a printer to print receipts/reports straight to it. "
                "Leave on “Ask each time” to choose at print time."
            ),
            w,
            title="Printer",
        )

    def _test_printer(self) -> None:
        name = self.printer_combo.currentData() or ""
        try:
            report.print_test_page(self, name)
            db.log_audit(self.con, self.user["username"], "printer_test", name or "ask-each-time")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Printer", f"Could not print:\n{e}")

    def _appearance_card(self) -> QWidget:
        form = self._form()
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        # No live preview: the theme is applied only when Save is pressed, so simply
        # picking Dark and leaving without saving never changes the look.
        form.addRow(self._flbl("Theme"), self.theme_combo)
        w = QWidget()
        w.setLayout(form)
        return card(
            muted(
                "Choose a light or dark look. The change takes effect when you "
                "click Save settings."
            ),
            w,
            title="Appearance",
        )

    def _apply_theme(self) -> None:
        theme = self.theme_combo.currentData() or "light"
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)

    def _whatsapp_card(self) -> QWidget:
        form = self._form()
        for f in WHATSAPP_FIELDS:
            self._add_field(form, f)
        self.wa_auto = QCheckBox("Auto-send the report when results are saved")
        form.addRow("", self.wa_auto)
        self.wa_auto_receipt = QCheckBox("Auto-send the bill when a receipt is saved")
        form.addRow("", self.wa_auto_receipt)

        # status line + action buttons
        self.wa_status = muted("")
        form.addRow("", self.wa_status)

        test = QPushButton("Test connection")
        test.setObjectName("ghost")
        test.clicked.connect(self._test_whatsapp)
        link = QPushButton("Open linking page (QR)")
        link.setObjectName("ghost")
        link.clicked.connect(self._open_wa_login)
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.addWidget(test)
        row1.addWidget(link)
        row1.addStretch(1)
        rw1 = QWidget()
        rw1.setLayout(row1)
        form.addRow("", rw1)

        # send a real test message (the user triggers this, not automatic)
        self.wa_test_num = QLineEdit()
        self.wa_test_num.setPlaceholderText("03XXXXXXXXX")
        send = QPushButton("Send test message")
        send.setObjectName("ghost")
        send.clicked.connect(self._send_test_whatsapp)
        self._wa_test_btn = send
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.addWidget(self.wa_test_num, 1)
        row2.addWidget(send)
        rw2 = QWidget()
        rw2.setLayout(row2)
        form.addRow(self._flbl("Send test to"), rw2)

        w = QWidget()
        w.setLayout(form)
        return card(
            muted(
                "Self-hosted WhatsApp gateway (free, sends report/receipt PDFs). "
                "See WHATSAPP_SETUP.md — run it, scan the QR, then put its URL and "
                "access token here. Captions accept {lab}, {lab_no}, {name}.\n\n"
                "Privacy: reports/bills are delivered through WhatsApp (Meta). Only "
                "send to patients who have agreed — set per patient in Reception."
            ),
            w,
            title="WhatsApp gateway",
        )

    def _users_card(self) -> QWidget:
        bar = QHBoxLayout()
        add = QPushButton("+ Add user")
        add.clicked.connect(self._add_user)
        reset = QPushButton("Reset password")
        reset.setObjectName("ghost")
        reset.clicked.connect(self._reset_user_pw)
        disable = QPushButton("Enable / Disable")
        disable.setObjectName("ghost")
        disable.clicked.connect(self._toggle_user)
        bar.addStretch(1)
        bar.addWidget(add)
        bar.addWidget(reset)
        bar.addWidget(disable)
        barw = QWidget()
        barw.setLayout(bar)
        self.users_table = QTableWidget(0, 4)
        self.users_table.setHorizontalHeaderLabels(["Username", "Full name", "Role", "Active"])
        hh = self.users_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Interactive)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.users_table.setColumnWidth(0, 150)
        self.users_table.setColumnWidth(2, 160)
        self.users_table.verticalHeader().setVisible(False)
        self.users_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.users_table.setSelectionBehavior(QTableWidget.SelectRows)
        return card(
            muted("Create staff logins and set their access level."),
            barw,
            self.users_table,
            title="Users & roles",
        )

    def refresh_users(self) -> None:
        if not hasattr(self, "users_table"):
            return
        rows = self.con.execute(
            "SELECT id,username,full_name,role,active FROM users ORDER BY username"
        ).fetchall()
        self.users_table.setRowCount(0)
        self._user_ids = []
        for r in rows:
            i = self.users_table.rowCount()
            self.users_table.insertRow(i)
            self._user_ids.append(r["id"])
            self.users_table.setItem(i, 0, QTableWidgetItem(r["username"]))
            self.users_table.setItem(i, 1, QTableWidgetItem(r["full_name"] or ""))
            self.users_table.setItem(i, 2, QTableWidgetItem(role_label(r["role"])))
            self.users_table.setItem(i, 3, QTableWidgetItem("Yes" if r["active"] else "No"))

    def _add_user(self) -> None:
        if not can(self.user["role"], "manage_users"):
            return  # defence in depth — managing users is admin-only
        d = UserDialog(self)
        if d.exec() == QDialog.Accepted:
            v = d.values()
            if not v["username"] or len(v["password"]) < 6:
                QMessageBox.warning(self, "User", "Username and a 6+ char password are required.")
                return
            if self.con.execute(
                "SELECT 1 FROM users WHERE username=?", (v["username"],)
            ).fetchone():
                QMessageBox.warning(self, "User", "That username already exists.")
                return
            h, salt = db.hash_password(v["password"])
            # new staff must set their own password on first login
            self.con.execute(
                "INSERT INTO users(username,full_name,pass_hash,salt,role,must_change_password) "
                "VALUES (?,?,?,?,?,1)",
                (v["username"], v["full_name"], h, salt, v["role"]),
            )
            self.con.commit()
            db.log_audit(
                self.con,
                self.user["username"],
                "user_created",
                f"{v['username']} ({role_label(v['role'])})",
            )
            self.refresh_users()

    def _toggle_user(self) -> None:
        if not can(self.user["role"], "manage_users"):
            return  # defence in depth — managing users is admin-only
        r = self.users_table.currentRow()
        if not (0 <= r < len(self._user_ids)):
            return
        uid = self._user_ids[r]
        if uid == self.user["id"]:
            QMessageBox.warning(self, "User", "You cannot disable your own account.")
            return
        row = self.con.execute("SELECT username, active FROM users WHERE id=?", (uid,)).fetchone()
        self.con.execute("UPDATE users SET active = 1 - active WHERE id=?", (uid,))
        self.con.commit()
        now_active = 0 if (row and row["active"]) else 1
        db.log_audit(
            self.con,
            self.user["username"],
            "user_enabled" if now_active else "user_disabled",
            (row["username"] if row else str(uid)),
        )
        self.refresh_users()

    def _backup_card(self) -> QWidget:
        now = QPushButton("Back up now")
        now.setObjectName("ghost")
        now.clicked.connect(self._backup_now)
        self._backup_btn = now
        restore = QPushButton("Restore from file…")
        restore.setObjectName("ghost")
        restore.clicked.connect(self._restore_db)
        self._restore_btn = restore
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(now)
        row.addWidget(restore)
        row.addStretch(1)
        w = QWidget()
        w.setLayout(row)
        return card(
            muted(
                "Automatic timestamped backups run on every launch (kept in the data "
                "folder). You can also back up now or restore from a backup file."
            ),
            w,
            title="Backup & restore",
        )

    def _backup_now(self) -> None:
        if not can(self.user["role"], "manage_backups"):
            return  # defence in depth — backup/restore is admin-only
        user = self.user["username"]

        def work(con) -> object | None:
            p = db.backup_db("manual")  # makes its own connections; con unused
            if p:
                db.log_audit(con, user, "backup_created", str(p))
            return p

        def done(work_ok: bool, result) -> None:
            if work_ok and result:
                QMessageBox.information(self, "Backup", f"Backup saved:\n{result}")
            else:
                QMessageBox.warning(self, "Backup", "Could not create a backup.")

        tasks.run_in_background(
            self,
            work,
            done,
            clicked=self._backup_btn,
            lock=(self._restore_btn,),
            busy_text="Backing up…",
        )

    def _restore_db(self) -> None:
        if not can(self.user["role"], "manage_backups"):
            QMessageBox.warning(
                self, "Restore", "You don't have permission to restore the database."
            )
            return
        bdir = str(db.data_dir() / "backups")
        path, _ = QFileDialog.getOpenFileName(
            self, "Restore from backup", bdir, "SQLite (*.sqlite)"
        )
        if not path:
            return
        if (
            QMessageBox.question(
                self,
                "Restore",
                "This REPLACES the current database with the selected backup (a safety copy of "
                "the current data is kept). You must close and reopen LabDesk afterwards. Continue?",
            )
            != QMessageBox.Yes
        ):
            return

        def done(work_ok: bool, result) -> None:
            if work_ok and result:
                db.log_audit(self.con, self.user["username"], "db_restored", path)
                QMessageBox.information(
                    self, "Restore", "Database restored. Please close and reopen LabDesk now."
                )
            else:
                QMessageBox.warning(self, "Restore", "Restore failed (file unreadable?).")

        tasks.run_in_background(
            self,
            lambda con: db.restore_db(path),
            done,
            clicked=self._restore_btn,
            lock=(self._backup_btn,),
            busy_text="Restoring…",
        )

    def _reset_user_pw(self) -> None:
        if not can(self.user["role"], "manage_users"):
            return  # defence in depth — managing users is admin-only
        import secrets as _secrets

        r = self.users_table.currentRow()
        if not (0 <= r < len(self._user_ids)):
            QMessageBox.warning(self, "Reset password", "Select a user first.")
            return
        uid = self._user_ids[r]
        uname = self.con.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()[0]
        temp = "Temp-" + _secrets.token_hex(4)  # 32-bit single-use, e.g. Temp-9af3c1d2
        h, salt = db.hash_password(temp)
        self.con.execute(
            "UPDATE users SET pass_hash=?, salt=?, must_change_password=1, "
            "failed_attempts=0, locked_until=NULL WHERE id=?",
            (h, salt, uid),
        )
        self.con.commit()
        db.log_audit(self.con, self.user["username"], "password_reset", uname)
        QMessageBox.information(
            self,
            "Reset password",
            f"Temporary password for {uname}:\n\n    {temp}\n\n"
            "They must set a new password at next login.",
        )

    def _security_card(self) -> QWidget:
        form = self._form()
        self._add_field(form, ("idle_lock_minutes", "Auto-lock after (minutes)", "0 = off"))
        self.new_pw = QLineEdit()
        self.new_pw.setEchoMode(QLineEdit.Password)
        self.new_pw.setPlaceholderText("at least 6 characters")
        form.addRow(self._flbl("New password"), self.new_pw)
        chpw = QPushButton("Change my password")
        chpw.setObjectName("ghost")
        chpw.clicked.connect(self.change_pw)
        form.addRow("", chpw)
        w = QWidget()
        w.setLayout(form)
        return card(w, title="Security")

    # ---- behaviour ----
    def on_show(self) -> None:
        for key, le in self.inputs.items():
            if key == "whatsapp_api_key":
                # token is kept in the private secret file, not the DB
                le.setText(db.get_secret("whatsapp_api_key") or db.get_setting(self.con, key, ""))
            else:
                le.setText(db.get_setting(self.con, key, ""))
        self.wa_auto.setChecked(db.get_setting(self.con, "whatsapp_auto", "0") == "1")
        self.wa_auto_receipt.setChecked(
            db.get_setting(self.con, "whatsapp_auto_receipt", "0") == "1"
        )
        theme = db.get_setting(self.con, "theme", "light")
        ti = self.theme_combo.findData(theme)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(ti if ti >= 0 else 0)
        self.theme_combo.blockSignals(False)
        cur = db.get_setting(self.con, "default_printer", "")
        i = self.printer_combo.findData(cur)
        self.printer_combo.setCurrentIndex(i if i >= 0 else 0)
        self.refresh_users()

    def _pick(self, key: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose image", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if not path:
            return
        # Copy the chosen image into the protected data dir so branding files live
        # inside it (not referenced from arbitrary, possibly-sensitive locations).
        try:
            self.inputs[key].setText(str(db.import_asset(path, key)))
        except OSError as e:
            QMessageBox.warning(self, "Image", f"Could not use that image:\n{e}")

    def save(self) -> None:
        # validate the gateway URL (SSRF / mis-send guard) before persisting
        wa_url = self.inputs["whatsapp_url"].text().strip()
        if wa_url:
            ok, why = whatsapp.validate_url(wa_url)
            if not ok:
                QMessageBox.warning(self, "WhatsApp", why)
                return
            import urllib.parse as _urlparse

            scheme = _urlparse.urlparse(wa_url).scheme
            if scheme == "http" and not whatsapp.is_loopback_url(wa_url):
                # Plain http to anything other than this very computer means the
                # patient PDF AND the access token travel UNENCRYPTED over the
                # network where they can be intercepted. Strongly warn.
                if (
                    QMessageBox.question(
                        self,
                        "WhatsApp — insecure connection",
                        "This gateway uses plain http:// to a host that is NOT this "
                        "computer. Patient reports and your access token would be sent "
                        "UNENCRYPTED over the network and could be intercepted.\n\n"
                        "Use https:// for any gateway not running on this machine. "
                        "Save anyway?",
                    )
                    != QMessageBox.Yes
                ):
                    return
            elif not whatsapp.is_local_url(wa_url):
                if (
                    QMessageBox.question(
                        self,
                        "WhatsApp",
                        "The gateway URL is not a local/loopback address. Patient PDFs and "
                        "your access token would be sent to that host. Save anyway?",
                    )
                    != QMessageBox.Yes
                ):
                    return
        # Collect every field into one mapping and write it in a SINGLE transaction.
        # Saving key-by-key used to fsync ~30 times and froze the UI for a beat.
        theme = self.theme_combo.currentData() or "light"
        prev_theme = db.get_setting(self.con, "theme", "light")
        updates = {
            key: le.text().strip() for key, le in self.inputs.items() if key != "whatsapp_api_key"
        }
        updates["whatsapp_api_key"] = ""  # token lives in the secret file, never the DB
        updates["whatsapp_auto"] = "1" if self.wa_auto.isChecked() else "0"
        updates["whatsapp_auto_receipt"] = "1" if self.wa_auto_receipt.isChecked() else "0"
        updates["theme"] = theme
        updates["default_printer"] = self.printer_combo.currentData() or ""
        db.set_settings(self.con, updates)  # one commit — no freeze
        # WhatsApp token → private 0600 secret file (kept out of the DB)
        db.set_secret("whatsapp_api_key", self.inputs["whatsapp_api_key"].text().strip())
        if theme != prev_theme:
            self._apply_theme()  # only restyle when it changed
        db.log_audit(self.con, self.user["username"], "settings_saved", f"theme={theme}")
        QMessageBox.information(self, "Settings", "Saved.")

    def _test_whatsapp(self) -> None:
        ok, msg = whatsapp.check_status(self.con)
        self.wa_status.setText(("✓ " if ok else "✗ ") + msg)
        db.log_audit(
            self.con,
            self.user["username"],
            "whatsapp_test",
            ("ok" if ok else "failed") + f" — {msg[:80]}",
        )
        (QMessageBox.information if ok else QMessageBox.warning)(self, "WhatsApp", msg)

    def _open_wa_login(self) -> None:
        url = (
            self.inputs["whatsapp_url"].text().strip()
            or db.get_setting(self.con, "whatsapp_url", "")
        ).rstrip("/")
        if not url:
            QMessageBox.warning(self, "WhatsApp", "Set the Gateway URL first.")
            return
        ok, why = whatsapp.validate_url(url)
        if not ok:
            QMessageBox.warning(self, "WhatsApp", why)
            return
        QDesktopServices.openUrl(QUrl(url + "/login"))

    def _send_test_whatsapp(self) -> None:
        num = self.wa_test_num.text().strip()
        if not num:
            QMessageBox.warning(self, "WhatsApp", "Enter a number to send the test to.")
            return
        lab = db.get_setting(self.con, "lab_name", "") or "LabDesk"
        text = f"✅ {lab}: WhatsApp test from LabDesk — your gateway is working."

        def done(work_ok: bool, result) -> None:
            if work_ok and isinstance(result, tuple):
                success, msg = result
            else:
                success, msg = False, (result if isinstance(result, str) else "Failed to send.")
            self.wa_status.setText(("✓ " if success else "✗ ") + msg)
            db.log_audit(
                self.con,
                self.user["username"],
                "whatsapp_test_message",
                ("sent" if success else "failed") + f" — {num}",
            )
            (QMessageBox.information if success else QMessageBox.warning)(self, "WhatsApp", msg)

        tasks.run_in_background(
            self,
            lambda con: whatsapp.send_text(con, num, text),
            done,
            clicked=self._wa_test_btn,
            busy_text="Sending…",
        )

    def change_pw(self) -> None:
        pw = self.new_pw.text()
        if len(pw) < 6:
            QMessageBox.warning(self, "Password", "Password must be at least 6 characters.")
            return
        h, salt = db.hash_password(pw)
        self.con.execute(
            "UPDATE users SET pass_hash=?, salt=?, must_change_password=0 WHERE id=?",
            (h, salt, self.user["id"]),
        )
        self.con.commit()
        db.log_audit(self.con, self.user["username"], "password_changed", "own password")
        self.new_pw.clear()
        QMessageBox.information(self, "Password", "Password updated.")
