"""Background WhatsApp sending so the GUI never freezes.

Building the PDF + base64-encoding it + the HTTP upload takes a few seconds (and
up to the timeout if the gateway is down). Doing that on the UI thread freezes
the window and makes Linux pop the "application not responding" dialog. This
module runs the whole thing on a QThreadPool worker — with its OWN SQLite
connection (sqlite handles can't be shared across threads) — and reports back on
the main thread, so the UI stays fully responsive.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QMessageBox

from .. import db, whatsapp

try:  # to safely detect a widget destroyed while a send was in flight
    from shiboken6 import Shiboken

    def _alive(obj) -> bool:
        return obj is not None and Shiboken.isValid(obj)
except Exception:  # pragma: no cover - fallback if shiboken layout differs
    def _alive(obj) -> bool:
        return obj is not None


# Keep in-flight tasks referenced until they finish — otherwise Python garbage
# collects the runnable (and its signal object) the moment send_async returns,
# and the completion callback never fires.
_active: set = set()


class _Signals(QObject):
    done = Signal(bool, str)


class _SendRunnable(QRunnable):
    """Runs one send on a pool thread. Opens its own DB connection; never raises
    out of run() (a crash here would take the whole app down)."""

    def __init__(self, kind: str, receipt_id: int):
        super().__init__()
        self.kind = kind
        self.receipt_id = receipt_id
        self.signals = _Signals()

    def run(self):  # noqa: D401
        ok, msg = False, "Something went wrong while sending."
        con = None
        try:
            con = db.connect()  # a fresh connection owned by THIS thread
            fn = whatsapp.send_receipt if self.kind == "receipt" else whatsapp.send_report
            ok, msg = fn(con, self.receipt_id)
        except Exception as e:  # noqa: BLE001 - last-resort guard
            ok, msg = False, f"Could not send on WhatsApp: {e}"
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:  # noqa: BLE001
                    pass
            self.signals.done.emit(bool(ok), str(msg))


def send_async(parent, con, kind: str, receipt_id: int, *,
               clicked=None, lock_buttons=(), on_done=None) -> bool:
    """Send a 'receipt' or 'report' PDF to the patient on a background thread.

    Returns True if the send was started, False if it was rejected up-front by a
    pre-flight check (so callers can stop, e.g. not flip any state).

    parent       widget for message boxes / liveness checks
    con          main-thread connection, used ONLY for the instant pre-checks
    clicked      the button the user pressed (shows a "Sending…" state)
    lock_buttons buttons to disable while the send is in flight (anti double-send)
    on_done      optional callback(ok: bool, msg: str) after completion
    """
    if receipt_id is None:
        return False
    # --- instant, no-network pre-flight: immediate clear feedback, no freeze ---
    ok, msg = whatsapp.config_ready(con)
    if not ok:
        QMessageBox.warning(parent, "WhatsApp", msg)
        return False
    ok, msg = whatsapp.recipient_ready(con, receipt_id)
    if not ok:
        QMessageBox.warning(parent, "WhatsApp", msg)
        return False

    locks = list(dict.fromkeys([b for b in (clicked, *lock_buttons) if b is not None]))
    prev_enabled = {b: b.isEnabled() for b in locks}
    prev_text = clicked.text() if clicked is not None else None
    for b in locks:
        b.setEnabled(False)
    if clicked is not None:
        clicked.setText("Sending…")

    task = _SendRunnable(kind, receipt_id)
    task.setAutoDelete(False)   # we manage its lifetime via _active
    _active.add(task)

    def _finished(success: bool, message: str):
        _active.discard(task)   # release the task now that it's done
        # the page/window may have been closed during the send — guard everything
        if clicked is not None and _alive(clicked) and prev_text is not None:
            clicked.setText(prev_text)
        upd = getattr(parent, "_update_buttons", None)
        if callable(upd) and _alive(parent):
            try:
                upd()  # let the page recompute correct enabled states
            except Exception:  # noqa: BLE001
                pass
        else:
            for b in locks:
                if _alive(b):
                    b.setEnabled(prev_enabled.get(b, True))
        if _alive(parent):
            (QMessageBox.information if success else QMessageBox.warning)(
                parent, "WhatsApp", message)
        if on_done is not None:
            try:
                on_done(success, message)
            except Exception:  # noqa: BLE001
                pass

    task.signals.done.connect(_finished)  # cross-thread → queued onto the UI thread
    QThreadPool.globalInstance().start(task)
    return True
