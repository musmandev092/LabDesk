"""WhatsApp settings card + its actions, split out of the SettingsPage god-class.

A mixin: the methods run on the composed SettingsPage instance, so they use the
shared helpers (self._form/_add_field/_flbl) and widgets (self.inputs, self.con,
self.user) exactly as before — pure reorganisation, no behavior change.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)

from .. import db, whatsapp
from . import tasks
from .settings_fields import WHATSAPP_FIELDS
from .widgets import card, muted, toast_info, toast_warn


class WhatsAppSettingsMixin:
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
        self._wa_conn_btn = test
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

    def _test_whatsapp(self) -> None:
        # Run the status check OFF the UI thread — check_status() is a blocking HTTP
        # GET (up to 8s); doing it inline froze the whole window if the gateway was
        # down/slow. Mirrors _send_test_whatsapp's background pattern.
        def done(work_ok: bool, result) -> None:
            if work_ok and isinstance(result, tuple):
                ok, msg = result
            else:
                ok, msg = False, (result if isinstance(result, str) else "Failed.")
            self.wa_status.setText(("✓ " if ok else "✗ ") + msg)
            db.log_audit(
                self.con,
                self.user["username"],
                "whatsapp_test",
                ("ok" if ok else "failed") + f" — {msg[:80]}",
            )
            (toast_info if ok else toast_warn)(self, "WhatsApp", msg)

        tasks.run_in_background(
            self,
            whatsapp.check_status,
            done,
            clicked=self._wa_conn_btn,
            busy_text="Checking…",
        )

    def _open_wa_login(self) -> None:
        url = (
            self.inputs["whatsapp_url"].text().strip()
            or db.get_setting(self.con, "whatsapp_url", "")
        ).rstrip("/")
        if not url:
            toast_warn(self, "WhatsApp", "Set the Gateway URL first.")
            return
        ok, why = whatsapp.validate_url(url)
        if not ok:
            toast_warn(self, "WhatsApp", why)
            return
        QDesktopServices.openUrl(QUrl(url + "/login"))

    def _send_test_whatsapp(self) -> None:
        num = self.wa_test_num.text().strip()
        if not num:
            toast_warn(self, "WhatsApp", "Enter a number to send the test to.")
            return
        lab = db.get_setting(self.con, "lab_name", "") or "LabDesk"
        text = f"✅ {lab}: WhatsApp test from LabDesk — your gateway is working."

        def done(work_ok: bool, result) -> None:
            if work_ok and isinstance(result, tuple):
                success, msg = result
            else:
                success, msg = (
                    False,
                    (result if isinstance(result, str) else "Failed to send."),
                )
            self.wa_status.setText(("✓ " if success else "✗ ") + msg)
            db.log_audit(
                self.con,
                self.user["username"],
                "whatsapp_test_message",
                ("sent" if success else "failed") + f" — {num}",
            )
            (toast_info if success else toast_warn)(self, "WhatsApp", msg)

        tasks.run_in_background(
            self,
            lambda con: whatsapp.send_text(con, num, text),
            done,
            clicked=self._wa_test_btn,
            busy_text="Sending…",
        )
