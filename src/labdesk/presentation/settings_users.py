"""Users & roles settings card + actions, split out of the SettingsPage god-class.

A mixin (runs on the composed SettingsPage instance). The privileged user
mutations go through application.users (require("manage_users") + audit) exactly as
before — this is pure reorganisation, no behavior change.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ..application import users as users_svc
from ..roles import can, role_label
from .settings_dialogs import TempPasswordDialog, UserDialog
from .widgets import card, muted, toast_warn


class UsersSettingsMixin:
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
        self.users_table.setHorizontalHeaderLabels(
            ["Username", "Full name", "Role", "Active"]
        )
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
            self.users_table.setItem(
                i, 3, QTableWidgetItem("Yes" if r["active"] else "No")
            )

    def _add_user(self) -> None:
        if not can(self.user["role"], "manage_users"):
            return  # defence in depth — managing users is admin-only
        d = UserDialog(self)
        if d.exec() == QDialog.Accepted:
            v = d.values()
            if not v["username"] or len(v["password"]) < 6:
                toast_warn(
                    self, "User", "Username and a 6+ char password are required."
                )
                return
            if self.con.execute(
                "SELECT 1 FROM users WHERE username=?", (v["username"],)
            ).fetchone():
                toast_warn(self, "User", "That username already exists.")
                return
            users_svc.create_user(
                self.con,
                username=v["username"],
                full_name=v["full_name"],
                password=v["password"],
                role=v["role"],
                actor_username=self.user["username"],
                actor_role=self.user["role"],
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
            toast_warn(self, "User", "You cannot disable your own account.")
            return
        users_svc.set_user_active(
            self.con,
            user_id=uid,
            actor_username=self.user["username"],
            actor_role=self.user["role"],
        )
        self.refresh_users()

    def _reset_user_pw(self) -> None:
        if not can(self.user["role"], "manage_users"):
            return  # defence in depth — managing users is admin-only
        r = self.users_table.currentRow()
        if not (0 <= r < len(self._user_ids)):
            toast_warn(self, "Reset password", "Select a user first.")
            return
        uid = self._user_ids[r]
        uname, temp = users_svc.reset_user_password(
            self.con,
            user_id=uid,
            actor_username=self.user["username"],
            actor_role=self.user["role"],
        )
        # Show it in a persistent, copyable dialog — NOT a toast (which would
        # auto-dismiss in a few seconds and lose a single-use credential).
        TempPasswordDialog(uname, temp, self).exec()
