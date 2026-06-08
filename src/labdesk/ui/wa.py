"""Background WhatsApp sending.

The threading machinery lives in ui/tasks.py; this module adds the WhatsApp
specifics: instant no-network pre-flight checks (so the user gets immediate
feedback instead of a frozen wait) and the result message box.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from .. import whatsapp
from . import tasks


def send_async(
    parent, con, kind: str, receipt_id: int, *, clicked=None, lock_buttons=(), on_done=None
) -> bool:
    """Send a 'receipt' or 'report' PDF to the patient on a background thread.

    Returns True if the send was started, False if a pre-flight check rejected it.
    `con` is the main-thread connection, used only for the instant pre-checks; the
    actual send runs on a worker thread with its own connection (see ui/tasks.py).
    """
    if receipt_id is None:
        return False
    # instant, no-network pre-flight → immediate clear feedback, no freeze
    ok, msg = whatsapp.config_ready(con)
    if not ok:
        QMessageBox.warning(parent, "WhatsApp", msg)
        return False
    ok, msg = whatsapp.recipient_ready(con, receipt_id)
    if not ok:
        QMessageBox.warning(parent, "WhatsApp", msg)
        return False

    fn = whatsapp.send_receipt if kind == "receipt" else whatsapp.send_report

    def _done(work_ok, result):
        # send_report/send_receipt return (success, message); work_ok is False
        # only if the worker raised unexpectedly (then result is the error str).
        if work_ok and isinstance(result, tuple):
            success, message = result
        else:
            success = False
            message = result if isinstance(result, str) else "Could not send on WhatsApp."
        (QMessageBox.information if success else QMessageBox.warning)(parent, "WhatsApp", message)
        if on_done is not None:
            on_done(success, message)

    tasks.run_in_background(
        parent,
        lambda con2: fn(con2, receipt_id),
        _done,
        clicked=clicked,
        lock=lock_buttons,
        busy_text="Sending…",
    )
    return True
