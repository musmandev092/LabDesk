"""Backup / restore / DB-password settings, split out of the SettingsPage god-class.

A mixin (runs on the composed SettingsPage instance). Backup/restore and the
database-password change are admin-gated (can("manage_backups")) exactly as
before — pure reorganisation, no behavior change.
"""

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
            row.addWidget(chpw)  # only meaningful when the DB is encrypted
            from ..db import keyvault

            if keyvault.available():
                row.addWidget(forget)  # only when a system wallet exists
        row.addStretch(1)
        w = QWidget()
        w.setLayout(row)

        # automatic-backup controls: an on/off toggle + a destination folder that
        # can live on a USB stick or a network share.
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

        # A plain label (not muted()) so we fully own its colour — it turns red as a
        # nudge when the last backup is stale, or when none has ever been made.
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
        """Show when the database was last backed up (from the audit trail), nudging
        in red if it has never been done or is a week or more stale."""
        if not hasattr(self, "_backup_status"):
            return  # card only exists for users who can manage backups
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
            return  # defence in depth — backup/restore is admin-only
        # let the user choose where to save the encrypted backup (Save-As dialog),
        # defaulting to the folder they last saved a backup to (else home).
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
            ok = db.backup_to(path)  # encrypted copy to the chosen file
            if ok:
                db.log_audit(con, user, "backup_created", path)
            return path if ok else None

        def done(work_ok: bool, result) -> None:
            if work_ok and result:
                # remember this folder so the next Save-As / Restore opens here
                db.set_setting(self.con, "last_backup_dir", str(Path(result).parent))
                toast_info(self, "Backup", f"Backup saved:\n{result}")
                self._refresh_backup_status()  # update the "Last backup" line right away
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
            return  # defence in depth — admin-only
        if not db.ENCRYPTION_AVAILABLE:
            toast_warn(
                self, "Database password", "This build's database is not encrypted."
            )
            return
        from .unlock import ChangePasswordDialog

        dlg = ChangePasswordDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        # rekey runs on the LIVE connection so it keeps working with the new key;
        # it verifies the current password and takes a backup first.
        if db.rekey_database(self.con, dlg.current, dlg.new):
            db.log_audit(self.con, self.user["username"], "db_password_changed", "")
            # if the password was remembered in the wallet, update it to the new one
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
        # start in the folder backups were last saved to (that's where they live)
        start = db.get_setting(self.con, "last_backup_dir", "")
        if not (start and Path(start).is_dir()):
            start = str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Restore from backup", start, "SQLite (*.sqlite)"
        )
        if not path:
            return
        src = Path(path)
        # Validate the file FIRST, before we touch the live connection — a bad pick
        # then changes nothing. A valid backup must open AND have a users table.
        # __current__ means it opens with the current password; otherwise we offer
        # to enter the password it WAS made with (e.g. before a password change), so
        # a perfectly good older backup is never wrongly rejected as "not a backup".
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
        # CRITICAL: close the live connection (and flush/checkpoint its WAL) BEFORE the
        # file is replaced, otherwise the old session checkpoints stale data back over
        # the restored database. Then restore synchronously and quit for a clean reopen.
        win = self.window()
        if win is not None:
            win._logged_out = True  # skip the logout-audit on the closed connection
            win._restoring = True  # skip the on-exit auto-backup (DB is being swapped)
        # Restoring a backup made under a different password: adopt that password as the
        # session key so restore_db's guard passes and the next unlock uses it, and
        # update any saved wallet password to match (else auto-unlock would then fail).
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
