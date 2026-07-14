"""Run slow work on a background QThreadPool thread so the GUI never freezes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from .. import db
from .widgets import toast_warn
import contextlib

try:
    from shiboken6 import Shiboken

    def _alive(obj: Any) -> bool:
        return obj is not None and Shiboken.isValid(obj)
except Exception:  # pragma: no cover - fallback if shiboken layout differs

    def _alive(obj: Any) -> bool:
        return obj is not None


_active: set[Any] = set()  # keeps running tasks referenced until they complete


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
            con = db.connect()
            result = self._work(con)
            ok = True
        except Exception as e:
            ok, result = False, (str(e) or e.__class__.__name__)
        finally:
            if con is not None:
                with contextlib.suppress(Exception):
                    con.close()
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
    """Run ``work(con)`` on a pool thread, then call ``on_done(ok, result)`` on the UI thread."""
    locks = list(dict.fromkeys([b for b in (clicked, *lock) if b is not None]))
    prev_enabled = {b: b.isEnabled() for b in locks}
    prev_text = clicked.text() if clicked is not None else None
    for b in locks:
        b.setEnabled(False)
    if clicked is not None and busy_text:
        clicked.setText(busy_text)

    task = _Runnable(work)
    task.setAutoDelete(False)  # lifetime managed via _active
    _active.add(task)

    def _finished(ok: bool, result: Any) -> None:
        _active.discard(task)
        if clicked is not None and _alive(clicked) and prev_text is not None:
            clicked.setText(prev_text)
        upd = getattr(parent, "_update_buttons", None)
        if callable(upd) and _alive(parent):
            with contextlib.suppress(Exception):
                upd()
        else:
            for b in locks:
                if _alive(b):
                    b.setEnabled(prev_enabled.get(b, True))
        if _alive(parent):
            with contextlib.suppress(Exception):
                on_done(ok, result)

    task.signals.done.connect(_finished)
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
    """Build something (usually PDF bytes) off the UI thread; show one uniform warning dialog on failure."""

    def _done(ok: bool, result: Any) -> None:
        if not ok:
            toast_warn(
                parent, error_title, f"Could not prepare the document:\n{result}"
            )
            return
        on_ready(result)

    run_in_background(
        parent, build, _done, clicked=clicked, lock=lock, busy_text=busy_text
    )


def debounce(owner: Any, slot: Callable[[], Any], ms: int = 250) -> Callable[..., None]:
    """Return a callable that fires ``slot`` only after ``ms`` of quiet (e.g. debounce a search box)."""
    timer = QTimer(owner)
    timer.setSingleShot(True)
    timer.setInterval(ms)
    timer.timeout.connect(slot)

    def trigger(*_args: Any) -> None:
        timer.start()

    return trigger
