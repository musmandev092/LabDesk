"""Logs: the admin-only audit trail of actions across the app."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import db
from . import tasks
from .widgets import muted, page_header

# action key -> (friendly label, colour) for the table
ACTION_LABELS = {
    # session / lifecycle
    "login": ("Signed in", "#1f9d55"),
    "login_failed": ("Failed sign-in", "#c0392b"),
    "logout": ("Signed out", "#64727d"),
    "setup_completed": ("Setup completed", "#0e7c86"),
    # patients / reception
    "patient_created": ("Patient created", "#0e7c86"),
    "patient_updated": ("Patient updated", "#0e7c86"),
    "receipt_created": ("Receipt created", "#0e7c86"),
    "discount_approved": ("Discount applied", "#b9770e"),
    "discount_approval_failed": ("Discount approval failed", "#c0392b"),
    # results / microbiology
    "results_saved": ("Results saved", "#0e7c86"),
    "culture_saved": ("Culture saved", "#0e7c86"),
    # money
    "due_received": ("Due payment received", "#1f9d55"),
    "expense_added": ("Expense added", "#b9770e"),
    "expense_updated": ("Expense edited", "#b9770e"),
    "expense_deleted": ("Expense deleted", "#c0392b"),
    # output (print / preview / pdf / whatsapp)
    "previewed_receipt": ("Previewed receipt", "#64727d"),
    "previewed_report": ("Previewed report", "#64727d"),
    "printed_receipt": ("Printed receipt", "#0a5f67"),
    "printed_report": ("Printed report", "#0a5f67"),
    "exported_pdf": ("Saved PDF", "#0a5f67"),
    "whatsapp_report": ("WhatsApp report", "#0a5f67"),
    "whatsapp_receipt": ("WhatsApp receipt", "#0a5f67"),
    "whatsapp_test": ("WhatsApp connection test", "#64727d"),
    "whatsapp_test_message": ("WhatsApp test message", "#0a5f67"),
    "printer_test": ("Printer test", "#64727d"),
    # admin / catalog / users / settings
    "user_created": ("User created", "#0e7c86"),
    "user_enabled": ("User enabled", "#1f9d55"),
    "user_disabled": ("User disabled", "#c0392b"),
    "password_changed": ("Password changed", "#b9770e"),
    "password_reset": ("Password reset (admin)", "#b9770e"),
    "backup_created": ("Backup created", "#1f9d55"),
    "db_restored": ("Database restored", "#c0392b"),
    "settings_saved": ("Settings updated", "#64727d"),
    "doctor_created": ("Doctor added", "#0e7c86"),
    "doctor_updated": ("Doctor edited", "#0e7c86"),
    "doctor_deleted": ("Doctor deleted", "#c0392b"),
    "test_created": ("Test added", "#0e7c86"),
    "test_updated": ("Test edited", "#0e7c86"),
    "test_deleted": ("Test deleted", "#c0392b"),
    "test_deactivated": ("Test retired", "#c0392b"),
    "test_activated": ("Test restored", "#1f9d55"),
    "parameters_edited": ("Parameters edited", "#0e7c86"),
    "receipt_voided": ("Receipt voided", "#c0392b"),
    "receipt_edited": ("Bill edited", "#b9770e"),
    "report_delivered": ("Report delivered", "#1f9d55"),
    "exported_csv": ("CSV exported", "#0a5f67"),
    "panel_created": ("Panel created", "#0e7c86"),
    "panel_updated": ("Panel edited", "#0e7c86"),
    "panel_deleted": ("Panel deleted", "#c0392b"),
    "logs_cleared": ("Logs cleared", "#c0392b"),
}


class LogsPage(QWidget):
    def __init__(self, con, user: dict) -> None:
        super().__init__()
        self.con = con
        self.user = user

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        self.verify_btn = QPushButton("Verify integrity")
        self.verify_btn.setObjectName("ghost")
        self.verify_btn.clicked.connect(self.verify_integrity)
        self.clear_btn = QPushButton("Clear old logs…")
        self.clear_btn.setObjectName("ghost")
        self.clear_btn.clicked.connect(self.clear_old)
        header, self.sub = page_header(
            "Logs", "Audit trail of activity", self.verify_btn, self.clear_btn
        )
        root.addWidget(header)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search user / action / detail…")
        self.search.setMinimumHeight(40)
        self.search.textChanged.connect(tasks.debounce(self, self.refresh))
        self.action = QComboBox()
        self.action.setMinimumHeight(40)
        self.action.addItem("All actions", "")
        for key, (lbl, _c) in ACTION_LABELS.items():
            self.action.addItem(lbl, key)
        self.action.currentIndexChanged.connect(self.refresh)
        self.today = QCheckBox("Today only")
        self.today.toggled.connect(self.refresh)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.action)
        bar.addWidget(self.today)
        root.addLayout(bar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["When", "User", "Action", "Detail"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        root.addWidget(self.table, 1)

        self.summary = muted("")
        root.addWidget(self.summary)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        q = f"%{self.search.text().strip()}%"
        sql = (
            "SELECT at, username, action, detail FROM audit_log "
            "WHERE (username LIKE ? OR action LIKE ? OR detail LIKE ?)"
        )
        args = [q, q, q]
        a = self.action.currentData()
        if a:
            sql += " AND action=?"
            args.append(a)
        if self.today.isChecked():
            sql += " AND date(at)=date('now','localtime')"
        sql += " ORDER BY id DESC LIMIT 1000"
        rows = self.con.execute(sql, args).fetchall()
        self.table.setRowCount(0)
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem((r["at"] or "")[:19]))
            self.table.setItem(i, 1, QTableWidgetItem(r["username"] or ""))
            lbl, col = ACTION_LABELS.get(r["action"], (r["action"] or "", None))
            ai = QTableWidgetItem(lbl)
            if col:
                ai.setForeground(QColor(col))
                f = ai.font()
                f.setBold(True)
                ai.setFont(f)
            self.table.setItem(i, 2, ai)
            self.table.setItem(i, 3, QTableWidgetItem(r["detail"] or ""))
        n = len(rows)
        self.summary.setText(f"{n} entr{'y' if n == 1 else 'ies'} shown (newest first, max 1000)")

    def verify_integrity(self) -> None:
        # Hashing the whole chain grows with the log — run it off the UI thread.
        def done(work_ok: bool, result) -> None:
            if not work_ok:
                QMessageBox.warning(self, "Logs", f"Could not verify the log:\n{result}")
                return
            ok, bad = result
            if ok:
                QMessageBox.information(
                    self, "Logs", "Audit log integrity OK — the hash chain is intact."
                )
            else:
                QMessageBox.warning(
                    self,
                    "Logs",
                    f"Integrity check FAILED near entry #{bad}. "
                    "The audit log appears to have been altered or truncated.",
                )

        tasks.run_in_background(
            self,
            lambda con: db.verify_audit_chain(con),
            done,
            clicked=self.verify_btn,
            lock=(self.clear_btn,),
            busy_text="Verifying…",
        )

    def clear_old(self) -> None:
        if (
            QMessageBox.question(self, "Clear logs", "Delete audit-log entries older than 90 days?")
            != QMessageBox.Yes
        ):
            return
        user = self.user["username"]

        def work(con) -> bool:
            con.execute("DELETE FROM audit_log WHERE at < datetime('now','localtime','-90 days')")
            con.commit()
            db.log_audit(con, user, "logs_cleared", "removed entries older than 90 days")
            # re-anchor the hash chain so 'Verify integrity' stays valid after the purge
            db.rechain_audit(con)
            return True

        def done(work_ok: bool, result) -> None:
            if not work_ok:
                QMessageBox.warning(self, "Clear logs", f"Could not clear logs:\n{result}")
            self.refresh()

        tasks.run_in_background(
            self, work, done, clicked=self.clear_btn, lock=(self.verify_btn,), busy_text="Clearing…"
        )
