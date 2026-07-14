"""Backup / restore / DB-password settings mixin for SettingsPage."""

from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QWidget,
)

from .. import db
from ..roles import can
from . import tasks
from .widgets import card, muted, toast_info, toast_warn


class BackupSettingsMixin:
    def _backup_card(self) -> QWidget:
        now = QPushButton("Back up now")
        now.setObjectName("ghost")
        now.clicked.connect(self._backup_now)
        self._backup_btn = now
        restore = QPushButton("Restore from file…")
        restore.setObjectName("ghost")
        restore.clicked.connect(self._restore_db)
        self._restore_btn = restore
        chpw = QPushButton("Change database password…")
        chpw.setObjectName("ghost")
        chpw.clicked.connect(self._change_db_password)
        forget = QPushButton("Forget saved password")
        forget.setObjectName("ghost")
        forget.clicked.connect(self._forget_saved_password)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(now)
        row.addWidget(restore)
        if db.ENCRYPTION_AVAILABLE:
            row.addWidget(chpw)
            from ..db import keyvault

            if keyvault.available():
                row.addWidget(forget)
        row.addStretch(1)
        w = QWidget()
        w.setLayout(row)

        self.auto_backup_chk = QCheckBox(
            "Automatic backups — save an encrypted copy on exit and once a day"
        )
        self.inputs["backup_dir"] = QLineEdit()
        self.inputs["backup_dir"].setReadOnly(True)
        self.inputs["backup_dir"].setPlaceholderText(
            f"Default: {db.fallback_backup_dir()}"
        )
        choose = QPushButton("Choose folder…")
        choose.setObjectName("ghost")
        choose.clicked.connect(self._pick_backup_dir)
        dirrow = QHBoxLayout()
        dirrow.setContentsMargins(0, 0, 0, 0)
        dirrow.addWidget(self._flbl("Backup folder"))
        dirrow.addWidget(self.inputs["backup_dir"], 1)
        dirrow.addWidget(choose)
        dirw = QWidget()
        dirw.setLayout(dirrow)

        # plain label (not muted()) so it can turn red when stale
        self._backup_status = QLabel("")
        self._backup_status.setWordWrap(True)
        return card(
            muted(
                "LabDesk automatically saves an encrypted backup when it closes and once a "
                "day. Choose where to keep them — a USB drive or a network folder is ideal. "
                f"If that location isn’t available, the backup is saved to "
                f"{db.fallback_backup_dir()} instead. You can also “Back up now” any time."
            ),
            self.auto_backup_chk,
            dirw,
            self._backup_status,
            w,
            title="Backup & restore",
        )

    def _pick_backup_dir(self) -> None:
        start = self.inputs["backup_dir"].text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Choose backup folder", start)
        if path:
            self.inputs["backup_dir"].setText(path)

    def _refresh_backup_status(self) -> None:
        """Show when the DB was last backed up, in red if stale/never."""
        if not hasattr(self, "_backup_status"):
            return
        row = self.con.execute(
            "SELECT at FROM audit_log WHERE action='backup_created' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row or not row["at"]:
            self._backup_status.setText(
                "⚠  No backup has been made yet — make one now and keep it somewhere safe."
            )
            self._backup_status.setStyleSheet("color:#c0392b; font-weight:600;")
            return
        import datetime as _dt

        try:
            d = _dt.datetime.fromisoformat(str(row["at"])[:19])
        except ValueError:
            self._backup_status.setText(f"Last backup: {row['at']}")
            self._backup_status.setStyleSheet("color:#666;")
            return
        days = (_dt.datetime.now() - d).days
        human = (
            "today" if days <= 0 else ("yesterday" if days == 1 else f"{days} days ago")
        )
        self._backup_status.setText(
            f"Last backup: {d.strftime('%Y-%m-%d %H:%M')}  ({human})"
        )
        stale = days >= 7
        self._backup_status.setStyleSheet(
            "color:#c0392b; font-weight:600;" if stale else "color:#666;"
        )

    def _backup_now(self) -> None:
        if not can(self.user["role"], "manage_backups"):
            return
        import time

        base = db.get_setting(self.con, "last_backup_dir", "")
        if not (base and Path(base).is_dir()):
            base = str(Path.home())
        default = str(
            Path(base) / f"labdesk-backup-{time.strftime('%Y%m%d-%H%M%S')}.sqlite"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save backup as", default, "SQLite (*.sqlite)"
        )
        if not path:
            return
        if not path.lower().endswith(".sqlite"):
            path += ".sqlite"
        user = self.user["username"]

        def work(con) -> object | None:
            ok = db.backup_to(path)
            if ok:
                db.log_audit(con, user, "backup_created", path)
            return path if ok else None

        def done(work_ok: bool, result) -> None:
            if work_ok and result:
                db.set_setting(self.con, "last_backup_dir", str(Path(result).parent))
                toast_info(self, "Backup", f"Backup saved:\n{result}")
                self._refresh_backup_status()
            else:
                toast_warn(self, "Backup", "Could not create a backup.")

        tasks.run_in_background(
            self,
            work,
            done,
            clicked=self._backup_btn,
            lock=(self._restore_btn,),
            busy_text="Backing up…",
        )

    def _change_db_password(self) -> None:
        if not can(self.user["role"], "manage_backups"):
            return
        if not db.ENCRYPTION_AVAILABLE:
            toast_warn(
                self, "Database password", "This build's database is not encrypted."
            )
            return
        from .unlock import ChangePasswordDialog

        dlg = ChangePasswordDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        # rekey on the live connection; verifies current password, backs up first
        if db.rekey_database(self.con, dlg.current, dlg.new):
            db.log_audit(self.con, self.user["username"], "db_password_changed", "")
            from ..db import keyvault

            if keyvault.load_key() is not None:
                keyvault.store_key(dlg.new)
            toast_info(
                self,
                "Database password",
                "Database password changed. Backups made before now still need the old password.",
            )
        else:
            toast_warn(
                self,
                "Database password",
                "Could not change it — check the current password and try again.",
            )

    def _forget_saved_password(self) -> None:
        if not can(self.user["role"], "manage_backups"):
            return
        from ..db import keyvault

        if keyvault.load_key() is None:
            toast_info(self, "Saved password", "No saved password on this computer.")
            return
        keyvault.clear_key()
        db.log_audit(self.con, self.user["username"], "db_password_forgotten", "")
        toast_info(
            self,
            "Saved password",
            "Forgotten. LabDesk will ask for the database password on next launch.",
        )

    def _restore_db(self) -> None:
        if not can(self.user["role"], "manage_backups"):
            toast_warn(
                self, "Restore", "You don't have permission to restore the database."
            )
            return
        start = db.get_setting(self.con, "last_backup_dir", "")
        if not (start and Path(start).is_dir()):
            start = str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Restore from backup", start, "SQLite (*.sqlite)"
        )
        if not path:
            return
        src = Path(path)
        # validate before touching the live connection; __current__ means it opens
        # with the current password, else prompt for the password it was made under
        restore_key = "__current__"
        if not db._looks_like_labdesk_db(src):
            pw, ok = QInputDialog.getText(
                self,
                "Different database password",
                "This file didn’t open with the current database password.\n\n"
                "If it’s a LabDesk backup made under a PREVIOUS password, enter that "
                "password to restore it:",
                QLineEdit.Password,
            )
            if not ok:
                return
            pw = pw or ""
            if not pw or not db._looks_like_labdesk_db(src, key=pw):
                toast_warn(
                    self,
                    "Restore",
                    "That isn’t a LabDesk backup, or the password doesn’t open it.",
                )
                return
            restore_key = pw
        if (
            QMessageBox.question(
                self,
                "Restore",
                "This REPLACES the current database with the selected backup (a safety copy "
                "of the current data is kept). LabDesk will close afterwards — reopen it to "
                "continue. Continue?",
            )
            != QMessageBox.Yes
        ):
            return
        db.log_audit(self.con, self.user["username"], "db_restored", path)
        # close the live connection (flush WAL) before the file is replaced
        win = self.window()
        if win is not None:
            win._logged_out = True
            win._restoring = True
        # adopt a non-current restore password as the session key + saved wallet password
        if restore_key != "__current__":
            db.unlock(restore_key)
            from ..db import keyvault

            if keyvault.load_key() is not None:
                keyvault.store_key(restore_key)
        with contextlib.suppress(Exception):
            self.con.close()
        ok = db.restore_db(path)
        if ok:
            extra = (
                ""
                if restore_key == "__current__"
                else "\n\nFrom now on, unlock LabDesk with that backup’s password."
            )
            QMessageBox.information(
                self,
                "Restore",
                "Database restored. LabDesk will now close — reopen it to continue."
                + extra,
            )
        else:
            QMessageBox.warning(self, "Restore", "Restore failed — please try again.")
        QApplication.instance().quit()
