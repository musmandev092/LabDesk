"""Settings: lab branding, registration, report footer, WhatsApp, security."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtPrintSupport import QPrinterInfo
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, db, report, whatsapp
from ..roles import can
from . import tasks
from .style import (
    DEVELOPER,
    DEVELOPER_EMAILS,
    DEVELOPER_GITHUB,
    PRODUCT_NAME,
    PRODUCT_TAGLINE,
    apply_theme,
)
from .widgets import (
    card,
    field_label,
    max_width_center,
    muted,
    page_header,
    toast_info,
    toast_warn,
)

_LABEL_W = 200  # shared label-column width so all settings cards align


from .settings_backup import BackupSettingsMixin
from .settings_fields import (
    LAB_FIELDS,
    LOGO_FIELDS,
    MAX_LENGTHS,
    NUMERIC_FIELDS,
    PROMO_FIELDS,
    RECEIPT_FIELDS,
    REG_FIELDS,
    REPORT_FIELDS,
)
from .settings_users import UsersSettingsMixin
from .settings_whatsapp import WhatsAppSettingsMixin


class SettingsPage(
    UsersSettingsMixin, WhatsAppSettingsMixin, BackupSettingsMixin, QWidget
):
    def __init__(self, con, user) -> None:
        super().__init__()
        self.con = con
        self.user = user
        self._user_ids: list[
            int
        ] = []  # parallel to users_table rows; filled by refresh_users
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
        col.addWidget(self._license_card())
        col.addWidget(self._about_card())
        col.addStretch(1)

        # Cap the form at a readable width and centre it: without this the fields
        # (AllNonFixedFieldsGrow) overflow the right edge at 1280 and stretch to
        # ~3300 px on 4K. The centred max-width wrapper fixes BOTH at once.
        scroll.setWidget(max_width_center(host, 880))
        root.addWidget(scroll, 1)

        self.save_btn = QPushButton("Save settings")
        self.save_btn.setMinimumHeight(42)
        self.save_btn.clicked.connect(self.save)
        root.addWidget(self.save_btn)

        self._install_numeric_validators()  # restrict numeric fields to valid input

    # ---- builders ----
    def _install_numeric_validators(self) -> None:
        """Stop letters / out-of-range values being typed into numeric fields. A
        validator only blocks bad keystrokes; save() still range-checks (a validator
        accepts 'intermediate' input like a lone '-' or a partial number)."""
        for key, (kind, lo, hi, _msg) in NUMERIC_FIELDS.items():
            le = self.inputs.get(key)
            if le is None:
                continue
            if kind == "float":
                v = QDoubleValidator(float(lo), float(hi), 2, le)
                v.setNotation(QDoubleValidator.StandardNotation)
            else:
                v = QIntValidator(int(lo), int(hi), le)
            le.setValidator(v)

    def _validate_numeric(self) -> str | None:
        """Return an error message if any numeric field holds a non-number or an
        out-of-range value; None if all are fine. Blank = use the default downstream."""
        for key, (kind, lo, hi, msg) in NUMERIC_FIELDS.items():
            le = self.inputs.get(key)
            if le is None:
                continue
            txt = le.text().strip()
            if not txt:
                continue
            try:
                val = float(txt) if kind == "float" else int(txt)
            except ValueError:
                return msg
            if not (lo <= val <= hi):
                return msg
        return None

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
        if key == "whatsapp_api_key":
            # the access token is a secret — mask it (with a reveal toggle) instead of
            # showing it in cleartext on the admin screen.
            le.setEchoMode(QLineEdit.Password)
            le.setClearButtonEnabled(True)
            act = le.addAction(
                self.style().standardIcon(QStyle.SP_FileDialogContentsView),
                QLineEdit.TrailingPosition,
            )
            act.setToolTip("Show / hide the token")
            act.triggered.connect(
                lambda: le.setEchoMode(
                    QLineEdit.Normal
                    if le.echoMode() == QLineEdit.Password
                    else QLineEdit.Password
                )
            )
        if len(field) > 2 and field[2]:
            le.setPlaceholderText(field[2])
        if key in MAX_LENGTHS:
            # cap the length so an over-long value can't overflow the printed
            # report/receipt header (e.g. a very long lab name)
            le.setMaxLength(MAX_LENGTHS[key])
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

    def _license_card(self) -> QWidget:
        """Node-lock license status for THIS machine + a way to (re)activate. The
        full activation flow (request → vendor → license file) lives in the same
        dialog shown at first launch — this just makes it reachable from Settings."""
        from .. import licensing

        col = QVBoxLayout()
        col.setSpacing(6)
        state, payload = licensing.check()
        if state == "ok":
            lab = (payload or {}).get("lab") or ""
            expiry = (payload or {}).get("expiry") or ""
            text = (
                f"<b>Activated</b>{(' — ' + lab) if lab else ''}<br>"
                f"Expires: {expiry or 'never (perpetual)'}"
            )
        elif state == "unactivated":
            text = "<b>Not activated</b> — this computer has no license yet."
        else:
            text = (
                f"<b>License problem:</b> {state.replace('_', ' ')}. Re-activate below."
            )
        status = QLabel(text)
        status.setTextFormat(Qt.RichText)
        status.setWordWrap(True)
        col.addWidget(status)

        code = QLabel(f"This computer's code: <b>{licensing.current_code()}</b>")
        code.setTextFormat(Qt.RichText)
        code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        col.addWidget(code)

        btn = QPushButton("Activate / load license…")
        btn.setObjectName("ghost")
        btn.clicked.connect(self._open_activation)
        col.addWidget(btn)

        w = QWidget()
        w.setLayout(col)
        return card(w, title="License & activation")

    def _open_activation(self) -> None:
        from .. import licensing
        from .activation import ActivationDialog

        ActivationDialog(initial_state=licensing.check()[0], parent=self).exec()

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
            db.log_audit(
                self.con, self.user["username"], "printer_test", name or "ask-each-time"
            )
        except Exception as e:
            toast_warn(self, "Printer", f"Could not print:\n{e}")

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

    def _security_card(self) -> QWidget:
        form = self._form()
        self._add_field(
            form, ("idle_lock_minutes", "Auto-lock after (minutes)", "0 = off")
        )
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
                le.setText(
                    db.get_secret("whatsapp_api_key")
                    or db.get_setting(self.con, key, "")
                )
            else:
                le.setText(db.get_setting(self.con, key, ""))
        self.wa_auto.setChecked(db.get_setting(self.con, "whatsapp_auto", "0") == "1")
        self.wa_auto_receipt.setChecked(
            db.get_setting(self.con, "whatsapp_auto_receipt", "0") == "1"
        )
        if hasattr(self, "auto_backup_chk"):
            self.auto_backup_chk.setChecked(
                db.get_setting(self.con, "auto_backup", "1") == "1"
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
        self._refresh_backup_status()

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
            toast_warn(self, "Image", f"Could not use that image:\n{e}")

    def save(self) -> None:
        # defence-in-depth: settings writes are admin-level; gate the action too
        # (consistent with the other mutating actions, not just page visibility).
        if not can(self.user["role"], "edit_settings"):
            toast_warn(self, "Settings", "You don't have permission to change settings.")
            return
        # reject non-numeric / out-of-range numeric fields before anything is written
        num_err = self._validate_numeric()
        if num_err:
            toast_warn(self, "Settings", num_err)
            return
        # validate the gateway URL (SSRF / mis-send guard) before persisting
        wa_url = self.inputs["whatsapp_url"].text().strip()
        if wa_url:
            ok, why = whatsapp.validate_url(wa_url)
            if not ok:
                toast_warn(self, "WhatsApp", why)
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
            elif not whatsapp.is_local_url(wa_url) and (
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
            key: le.text().strip()
            for key, le in self.inputs.items()
            if key != "whatsapp_api_key"
        }
        updates["whatsapp_api_key"] = ""  # token lives in the secret file, never the DB
        updates["whatsapp_auto"] = "1" if self.wa_auto.isChecked() else "0"
        updates["whatsapp_auto_receipt"] = (
            "1" if self.wa_auto_receipt.isChecked() else "0"
        )
        if hasattr(self, "auto_backup_chk"):
            updates["auto_backup"] = "1" if self.auto_backup_chk.isChecked() else "0"
        updates["theme"] = theme
        updates["default_printer"] = self.printer_combo.currentData() or ""
        token = self.inputs["whatsapp_api_key"].text().strip()

        # The DB write + secret-file write run on a background thread (the button
        # shows "Saving…"); the toast and theme restyle happen back on the UI thread.
        def work(con):
            db.set_settings(con, updates)  # one commit — no freeze
            # WhatsApp token → private 0600 secret file (kept out of the DB)
            db.set_secret("whatsapp_api_key", token)
            db.log_audit(con, self.user["username"], "settings_saved", f"theme={theme}")
            return True

        def done(ok, result):
            if not ok:
                toast_warn(self, "Settings", f"Could not save settings:\n{result}")
                return
            if theme != prev_theme:
                self._apply_theme()  # only restyle when it changed (UI thread)
            toast_info(self, "Settings", "Saved.")

        tasks.run_in_background(
            self, work, done, clicked=self.save_btn, busy_text="Saving…"
        )

    def change_pw(self) -> None:
        pw = self.new_pw.text()
        if len(pw) < 6:
            toast_warn(self, "Password", "Password must be at least 6 characters.")
            return
        h, salt = db.hash_password(pw)
        self.con.execute(
            "UPDATE users SET pass_hash=?, salt=?, must_change_password=0 WHERE id=?",
            (h, salt, self.user["id"]),
        )
        self.con.commit()
        db.log_audit(
            self.con, self.user["username"], "password_changed", "own password"
        )
        self.new_pw.clear()
        toast_info(self, "Password", "Password updated.")
