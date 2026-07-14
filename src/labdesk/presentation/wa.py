"""Background WhatsApp sending: pre-flight checks plus the actual send."""

from __future__ import annotations

from collections.abc import Callable

from .. import whatsapp
from . import tasks
from .widgets import toast_info, toast_warn


def send_async(
    parent,
    con,
    kind: str,
    receipt_id: int | None,
    *,
    clicked=None,
    lock_buttons: tuple = (),
    on_done: Callable[[bool, str], None] | None = None,
) -> bool:
    """Send a 'receipt' or 'report' PDF to the patient on a background thread."""
    if receipt_id is None:
        return False
    ok, msg = whatsapp.config_ready(con)
    if not ok:
        toast_warn(parent, "WhatsApp", msg)
        return False
    ok, msg = whatsapp.recipient_ready(con, receipt_id)
    if not ok:
        toast_warn(parent, "WhatsApp", msg)
        return False

    fn = whatsapp.send_receipt if kind == "receipt" else whatsapp.send_report

    def _done(work_ok: bool, result: object) -> None:
        if work_ok and isinstance(result, tuple):
            success, message = result
        else:
            success = False
            message = (
                result if isinstance(result, str) else "Could not send on WhatsApp."
            )
        (toast_info if success else toast_warn)(parent, "WhatsApp", message)
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
