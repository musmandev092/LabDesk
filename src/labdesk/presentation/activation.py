"""First-run activation dialog (node-locked licensing)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .. import licensing
from .style import PRODUCT_NAME
from .widgets import toast_info, toast_warn

_STATE_MESSAGE = {
    "unactivated": "This copy of LabDesk needs to be activated for this computer.",
    "wrong_machine": "The installed license is for a different computer. Activate this one.",
    "expired": "The license has expired. Please obtain a renewed license.",
    "bad_signature": "The installed license is invalid or was modified. Please re-activate.",
    "invalid": "The installed license could not be read. Please re-activate.",
}


class ActivationDialog(QDialog):
    def __init__(self, initial_state: str = "unactivated", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Activate {PRODUCT_NAME}")
        self.setMinimumWidth(560)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 22)
        root.setSpacing(12)

        title = QLabel(f"Activate {PRODUCT_NAME}")
        title.setStyleSheet("font-size:18px; font-weight:700;")
        root.addWidget(title)

        msg = QLabel(_STATE_MESSAGE.get(initial_state, _STATE_MESSAGE["unactivated"]))
        msg.setWordWrap(True)
        if initial_state != "unactivated":
            msg.setStyleSheet("color:#c0392b; font-weight:600;")
        root.addWidget(msg)

        steps = QLabel(
            "1. Send the activation request below to your vendor.\n"
            "2. They send back a license file.\n"
            "3. Load it with “Load license file…” (or paste it) and click Activate."
        )
        steps.setWordWrap(True)
        steps.setStyleSheet("color:#555;")
        root.addWidget(steps)

        code = QLabel(f"This computer's code:  <b>{licensing.current_code()}</b>")
        code.setTextFormat(Qt.RichText)
        code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(code)

        root.addWidget(QLabel("Activation request (send this to your vendor):"))
        self.request_box = QPlainTextEdit(licensing.build_request())
        self.request_box.setReadOnly(True)
        self.request_box.setFixedHeight(70)
        self.request_box.setStyleSheet("font-family:monospace; font-size:11px;")
        root.addWidget(self.request_box)

        req_row = QHBoxLayout()
        copy = QPushButton("Copy request")
        copy.setObjectName("ghost")
        copy.clicked.connect(self._copy_request)
        save_req = QPushButton("Save request…")
        save_req.setObjectName("ghost")
        save_req.clicked.connect(self._save_request)
        req_row.addWidget(copy)
        req_row.addWidget(save_req)
        req_row.addStretch(1)
        root.addLayout(req_row)

        root.addWidget(
            QLabel("License from your vendor (load a file, or paste it here):")
        )
        self.license_box = QPlainTextEdit()
        self.license_box.setPlaceholderText(
            "Paste the license text here, or use “Load license file…”"
        )
        self.license_box.setFixedHeight(90)
        self.license_box.setStyleSheet("font-family:monospace; font-size:11px;")
        root.addWidget(self.license_box)

        bottom = QHBoxLayout()
        load = QPushButton("Load license file…")
        load.setObjectName("ghost")
        load.clicked.connect(self._load_file)
        bottom.addWidget(load)
        bottom.addStretch(1)
        quit_btn = QPushButton("Quit")
        quit_btn.setObjectName("ghost")
        quit_btn.clicked.connect(self.reject)
        activate = QPushButton("Activate")
        activate.setMinimumHeight(38)
        activate.clicked.connect(self._activate)
        bottom.addWidget(quit_btn)
        bottom.addWidget(activate)
        root.addLayout(bottom)

    def _copy_request(self) -> None:
        QApplication.clipboard().setText(self.request_box.toPlainText())
        toast_info(self, "Activation", "Activation request copied to the clipboard.")

    def _save_request(self) -> None:
        default = str(Path.home() / "labdesk-activation-request.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save activation request", default, "Text (*.txt)"
        )
        if not path:
            return
        try:
            Path(path).write_text(self.request_box.toPlainText(), encoding="utf-8")
            toast_info(self, "Activation", f"Saved:\n{path}")
        except OSError as e:
            toast_warn(self, "Activation", f"Could not save:\n{e}")

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load license file",
            str(Path.home()),
            "License (*.lic);;All files (*)",
        )
        if not path:
            return
        try:
            self.license_box.setPlainText(Path(path).read_text(encoding="utf-8"))
        except OSError as e:
            toast_warn(self, "Activation", f"Could not read the file:\n{e}")

    def _activate(self) -> None:
        ok, message = licensing.install_license(self.license_box.toPlainText())
        if ok:
            toast_info(self, "Activation", "Activated — thank you.")
            self.accept()
        else:
            toast_warn(self, "Activation", message)
