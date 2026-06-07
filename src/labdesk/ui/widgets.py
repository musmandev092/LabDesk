"""Small reusable UI helpers."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy, QTableWidgetItem,
)

from .style import PRIMARY, PRIMARY_DARK, MUTED, BORDER

# status → (display colour) for receipt/worklist tables (single source of truth)
STATUS_COLORS = {"pending": "#b9770e", "in_progress": "#0e7c86",
                 "reported": "#1f9d55", "delivered": "#6b7280"}


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


def like_term(text: str) -> str:
    """Build a %wrapped% LIKE pattern with the wildcards % _ \\ escaped so user
    input matches literally. Pair with ESCAPE '\\' in the query."""
    t = (text or "").strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{t}%"


def money(value: float, currency: str = "Rs.") -> str:
    value = value or 0.0          # normalise -0.0 / None so we never print "-0"
    if value < 0:
        return f"- {currency} {abs(value):,.0f}"
    return f"{currency} {value:,.0f}"


def num_item(text: str, color: str | None = None) -> QTableWidgetItem:
    """A right-aligned, optionally-coloured table cell for money/number columns."""
    it = QTableWidgetItem(text)
    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if color:
        it.setForeground(QColor(color))
    return it


def selected_id(table, ids):
    """The id (from a parallel ``ids`` list) of the table's selected row, or None.

    Derived from the actual selection (NOT currentRow): a cleared selection
    leaves currentRow set, which would otherwise act on a stale row."""
    sel = table.selectionModel().selectedRows()
    if not sel:
        return None
    r = sel[0].row()
    return ids[r] if 0 <= r < len(ids) else None


def status_badge(status: str, voided: bool = False) -> QTableWidgetItem:
    """A bold, colour-coded status cell shared by the receipt/worklist tables."""
    text = "Voided" if voided else (status or "").replace("_", " ").title()
    it = QTableWidgetItem(text)
    col = "#c0392b" if voided else STATUS_COLORS.get(status or "")
    if col:
        it.setForeground(QColor(col))
        fnt = it.font(); fnt.setBold(True); it.setFont(fnt)
    return it
