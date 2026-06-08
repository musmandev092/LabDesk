"""Run slow work on a background thread so the GUI never freezes.

Generalises the WhatsApp-send pattern (originally in ui/wa.py): a QThreadPool
worker runs ``work(con)`` with its OWN SQLite connection (handles can't cross
threads) and reports the result back on the UI thread via a queued signal.

Notes that make this safe:
  * the in-flight task is kept in ``_active`` until it finishes — otherwise
    Python garbage-collects the runnable the moment the caller returns and the
    completion callback never fires;
  * every widget touch in the callback is guarded with ``_alive`` in case the
    page / window was closed while the work was still running;
  * the worker never raises out of run() (a crash there would take the app down).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from .. import db

try:  # detect a widget destroyed while work was in flight
    from shiboken6 import Shiboken

    def _alive(obj: Any) -> bool:
        return obj is not None and Shiboken.isValid(obj)
except Exception:  # pragma: no cover - fallback if shiboken layout differs

    def _alive(obj: Any) -> bool:
        return obj is not None


_active: set[Any] = set()  # keep running tasks referenced until they complete


class _Signals(QObject):
    done = Signal(bool, object)


class _Runnable(QRunnable):
    def __init__(self, work: Callable[[Any], Any]) -> None:
        super().__init__()
        self._work = work
        self.signals = _Signals()

    def run(self) -> None:
        ok, result = False, "Something went wrong."
        con = None
        try:
            con = db.connect()  # fresh connection owned by THIS thread
            result = self._work(con)
            ok = True
        except Exception as e:
            ok, result = False, (str(e) or e.__class__.__name__)
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
            self.signals.done.emit(ok, result)


def run_in_background(
    parent: Any,
    work: Callable[[Any], Any],
    on_done: Callable[[bool, Any], None],
    *,
    clicked: Any = None,
    lock: tuple[Any, ...] = (),
    busy_text: str = "Working…",
) -> None:
    """Run ``work(con)`` on a pool thread, then call ``on_done(ok, result)`` on
    the UI thread.

    work(con)            any callable; ``con`` is a fresh worker-thread connection.
                         Its return value is passed to on_done as ``result``.
    on_done(ok, result)  ok is False when work raised — then ``result`` is the
                         error message (str).
    clicked              button to disable + show ``busy_text`` on during the run.
    lock                 extra buttons to disable while running (anti double-click).
    """
    locks = list(dict.fromkeys([b for b in (clicked, *lock) if b is not None]))
    prev_enabled = {b: b.isEnabled() for b in locks}
    prev_text = clicked.text() if clicked is not None else None
    for b in locks:
        b.setEnabled(False)
    if clicked is not None and busy_text:
        clicked.setText(busy_text)

    task = _Runnable(work)
    task.setAutoDelete(False)  # we manage its lifetime via _active
    _active.add(task)

    def _finished(ok: bool, result: Any) -> None:
        _active.discard(task)
        if clicked is not None and _alive(clicked) and prev_text is not None:
            clicked.setText(prev_text)
        upd = getattr(parent, "_update_buttons", None)
        if callable(upd) and _alive(parent):
            try:
                upd()
            except Exception:
                pass
        else:
            for b in locks:
                if _alive(b):
                    b.setEnabled(prev_enabled.get(b, True))
        if _alive(parent):
            try:
                on_done(ok, result)
            except Exception:
                pass

    task.signals.done.connect(_finished)  # cross-thread → queued onto the UI thread
    QThreadPool.globalInstance().start(task)


def build_pdf(
    parent: Any,
    build: Callable[[Any], Any],
    on_ready: Callable[[Any], None],
    *,
    clicked: Any = None,
    lock: tuple[Any, ...] = (),
    busy_text: str = "Working…",
    error_title: str = "Document",
) -> None:
    """Build something (usually PDF bytes) via ``build(con)`` off the UI thread,
    then call ``on_ready(result)`` on success. On failure, show one uniform
    warning dialog — saves every caller repeating the ok/error branch."""
    from PySide6.QtWidgets import QMessageBox

    def _done(ok: bool, result: Any) -> None:
        if not ok:
            QMessageBox.warning(parent, error_title, f"Could not prepare the document:\n{result}")
            return
        on_ready(result)

    run_in_background(parent, build, _done, clicked=clicked, lock=lock, busy_text=busy_text)


def debounce(owner: Any, slot: Callable[[], Any], ms: int = 250) -> Callable[..., None]:
    """Return a callable that fires ``slot`` only after ``ms`` of quiet, so a
    search box hits the DB once after typing stops, not on every keystroke. The
    QTimer is parented to ``owner`` so it lives exactly as long as the widget."""
    timer = QTimer(owner)
    timer.setSingleShot(True)
    timer.setInterval(ms)
    timer.timeout.connect(slot)

    def trigger(*_args: Any) -> None:
        timer.start()

    return trigger
