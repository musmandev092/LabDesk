"""Small reusable UI helpers."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy,
)

from .style import PRIMARY, PRIMARY_DARK, MUTED, BORDER


def _fixed_v(w: QWidget) -> QWidget:
    """Pin a widget's vertical size so layouts never inflate it (gap-bug guard)."""
    w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    return w


def h1(text: str) -> QLabel:
    lbl = QLabel(text); lbl.setObjectName("h1"); return _fixed_v(lbl)


def h2(text: str) -> QLabel:
    lbl = QLabel(text); lbl.setObjectName("h2"); return _fixed_v(lbl)


def muted(text: str) -> QLabel:
    lbl = QLabel(text); lbl.setObjectName("muted"); return _fixed_v(lbl)


def field_label(text: str) -> QLabel:
    lbl = QLabel(text); lbl.setObjectName("fieldlbl"); return _fixed_v(lbl)


def page_header(title: str, subtitle: str = "", *actions: QWidget) -> tuple[QWidget, QLabel]:
    """A consistent page header: title (+subtitle) on the left, actions on the right.
    Returns (header_widget, subtitle_label) so callers can update the subtitle."""
    bar = QWidget()
    bar.setObjectName("PageHeader")
    bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    outer = QVBoxLayout(bar)
    outer.setContentsMargins(2, 0, 2, 10)
    outer.setSpacing(2)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    left = QVBoxLayout()
    left.setSpacing(1)
    left.addWidget(h1(title))
    sub = muted(subtitle)
    if not subtitle:
        sub.hide()
    left.addWidget(sub)
    row.addLayout(left)
    row.addStretch(1)
    for a in actions:
        a.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        row.addWidget(a, 0, Qt.AlignVCenter)
    outer.addLayout(row)
    return bar, sub


def card(*children: QWidget, title: str = "") -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(10)
    if title:
        lay.addWidget(h2(title))
    for c in children:
        lay.addWidget(c)
    return f


def stat_card(title: str, value: str, color: str = PRIMARY, on_click=None) -> QFrame:
    f = QFrame()
    f.setObjectName("statcard")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(20, 18, 20, 18)
    lay.setSpacing(4)
    t = QLabel(title); t.setObjectName("muted")
    v = QLabel(value)
    v.setStyleSheet(f"font-size: 30px; font-weight: 800; color: {color};")
    lay.addWidget(t)
    lay.addWidget(v)
    if on_click is not None:
        hint = QLabel("Open →"); hint.setStyleSheet(f"color:{color};font-weight:700;font-size:12px;")
        lay.addWidget(hint)
        f.setCursor(Qt.PointingHandCursor)
        f.setStyleSheet("QFrame#statcard:hover { border-color: %s; background: #f3fafa; }" % color)
        f.mousePressEvent = lambda e, cb=on_click: cb()
    else:
        lay.addStretch(1)
    f.value_label = v  # type: ignore[attr-defined]
    return f


def money(value: float, currency: str = "Rs.") -> str:
    if value < 0:
        return f"- {currency} {abs(value):,.0f}"
    return f"{currency} {value:,.0f}"
